from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from threading import Lock
from tempfile import mkdtemp
from typing import Any
from urllib.parse import urlparse
import warnings
import weakref

from PIL import Image, ImageDraw, ImageFont

from .. import __version__

from .modelos import Deteccao, MetadadosModelo, ResultadoDeteccao, TipoEntrada


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_BYTES_IMAGEM = 100 * 1024 * 1024
MAX_PIXELS_IMAGEM = 100_000_000
MAX_DETECCOES_POR_IMAGEM = 1000


def _raizes_padrao() -> tuple[Path, ...]:
    raizes = [Path(__file__).resolve().parents[3]]
    if getattr(sys, "frozen", False):
        raizes.append(Path(sys.executable).resolve().parent)
    pasta_bundle = getattr(sys, "_MEIPASS", None)
    if pasta_bundle:
        raizes.append(Path(pasta_bundle).resolve())
    return tuple(dict.fromkeys(raizes))


def _parece_url(valor: str) -> bool:
    analisado = urlparse(valor)
    return bool(analisado.scheme or analisado.netloc) or valor.startswith("//")


def _esta_contido(caminho: Path, raiz: Path) -> bool:
    try:
        caminho.relative_to(raiz)
    except ValueError:
        return False
    return True


def resolver_caminho_modelo(
    caminho: str | os.PathLike[str],
    raizes_confiaveis: Iterable[str | os.PathLike[str]] | None = None,
) -> Path:
    """Resolve um peso local regular e contido em uma raiz explicitamente confiável."""
    valor = os.fspath(caminho)
    if not valor or _parece_url(valor):
        raise ValueError("O modelo deve ser um arquivo local .pt, não uma URL")
    informado = Path(valor).expanduser()
    if informado.suffix.lower() != ".pt":
        raise ValueError("O modelo deve ter extensão .pt")

    raizes = tuple(
        dict.fromkeys(
            Path(raiz).expanduser().resolve()
            for raiz in (raizes_confiaveis if raizes_confiaveis is not None else _raizes_padrao())
        )
    )
    if not raizes:
        raise ValueError("Ao menos uma raiz confiável deve ser informada")

    candidatos = (informado,) if informado.is_absolute() else tuple(raiz / informado for raiz in raizes)
    for candidato in candidatos:
        raiz_candidata = next(
            (raiz for raiz in raizes if _esta_contido(candidato.absolute(), raiz)), None
        )
        if raiz_candidata is None:
            continue
        relativo = candidato.absolute().relative_to(raiz_candidata)
        atual = raiz_candidata
        tem_symlink = False
        for parte in relativo.parts:
            atual = atual / parte
            if atual.is_symlink():
                tem_symlink = True
                break
        if tem_symlink:
            raise ValueError("Links simbólicos não são aceitos como modelo")
        resolvido = candidato.resolve(strict=False)
        if not any(_esta_contido(resolvido, raiz) for raiz in raizes):
            continue
        try:
            estado = candidato.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(estado.st_mode):
            raise ValueError("Links simbólicos não são aceitos como modelo")
        if not stat.S_ISREG(estado.st_mode):
            raise ValueError("O modelo deve ser um arquivo regular")
        return resolvido

    raise ValueError("Modelo inexistente ou fora das raízes confiáveis")


def _sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _snapshot_modelo(caminho: Path, pasta: Path) -> tuple[Path, str]:
    """Copia e hasheia o mesmo inode para evitar troca entre validação e carga."""
    destino = pasta / caminho.name
    origem_fd = os.open(caminho, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    destino_fd = os.open(
        destino,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    digest = hashlib.sha256()
    try:
        estado = os.fstat(origem_fd)
        if not stat.S_ISREG(estado.st_mode):
            raise ValueError("O modelo deve ser um arquivo regular")
        while True:
            bloco = os.read(origem_fd, 1024 * 1024)
            if not bloco:
                break
            digest.update(bloco)
            restante = memoryview(bloco)
            while restante:
                escritos = os.write(destino_fd, restante)
                if escritos <= 0:
                    raise OSError("Falha ao copiar o modelo para a área privada")
                restante = restante[escritos:]
        os.fsync(destino_fd)
    finally:
        os.close(origem_fd)
        os.close(destino_fd)
    return destino, digest.hexdigest()


def _lista(valor: Any) -> list:
    atual = valor
    for metodo in ("detach", "cpu"):
        funcao = getattr(atual, metodo, None)
        if callable(funcao):
            atual = funcao()
    tolist = getattr(atual, "tolist", None)
    return tolist() if callable(tolist) else list(atual)


def _normalizar_classes(valor: Any) -> dict[int, str]:
    if isinstance(valor, Mapping):
        return {int(chave): str(nome) for chave, nome in valor.items()}
    if isinstance(valor, Sequence) and not isinstance(valor, (str, bytes)):
        return {indice: str(nome) for indice, nome in enumerate(valor)}
    return {}


class DetectorAgricola:
    """Adaptador lazy para inferência agrícola com resultados estáveis do domínio."""

    def __init__(
        self,
        caminho_modelo: str | os.PathLike[str],
        *,
        sha256_modelo: str | None = None,
        versao_modelo: str = "não informada",
        dispositivo: str = "auto",
        raizes_confiaveis: Iterable[str | os.PathLike[str]] | None = None,
        fabrica_modelo: Callable[[str], Any] | None = None,
        disponibilidade_cuda: Callable[[], bool] | None = None,
    ) -> None:
        caminho_origem = resolver_caminho_modelo(caminho_modelo, raizes_confiaveis)
        self.nome_modelo = caminho_origem.name
        pasta_snapshot = Path(mkdtemp(prefix="sentinel-mt-modelo-"))
        self._finalizador_snapshot = weakref.finalize(
            self, shutil.rmtree, pasta_snapshot, True
        )
        self.caminho_modelo, self.sha256_modelo = _snapshot_modelo(
            caminho_origem, pasta_snapshot
        )
        if sha256_modelo is not None:
            if not SHA256_RE.fullmatch(sha256_modelo):
                raise ValueError("SHA-256 esperado deve conter 64 dígitos hexadecimais")
            if not hmac.compare_digest(self.sha256_modelo, sha256_modelo.lower()):
                raise ValueError("SHA-256 do modelo não corresponde ao valor esperado")
        self.versao_modelo = str(versao_modelo)
        self._dispositivo_solicitado = dispositivo.lower()
        if self._dispositivo_solicitado not in {"auto", "cpu", "cuda", "cuda:0"}:
            raise ValueError("Dispositivo deve ser auto, cpu, cuda ou cuda:0")
        self._fabrica_modelo = fabrica_modelo
        self._disponibilidade_cuda = disponibilidade_cuda
        self._modelo: Any | None = None
        self._dispositivo: str | None = None
        self._lock = Lock()

    def _cuda_disponivel(self) -> bool:
        if self._disponibilidade_cuda is not None:
            return bool(self._disponibilidade_cuda())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import torch  # import opcional e deliberadamente lazy
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Runtime de IA não instalado; instale os requisitos do Sentinel MT"
            ) from exc

        return bool(torch.cuda.is_available())

    def _selecionar_dispositivo(self) -> str:
        if self._dispositivo_solicitado == "cpu":
            return "cpu"
        disponivel = self._cuda_disponivel()
        if self._dispositivo_solicitado in {"cuda", "cuda:0"} and not disponivel:
            raise RuntimeError("GPU CUDA solicitada, mas não está disponível")
        return "cuda:0" if disponivel else "cpu"

    def _carregar_modelo(self) -> Any:
        if self._modelo is not None:
            return self._modelo
        with self._lock:
            if self._modelo is None:
                fabrica = self._fabrica_modelo
                if fabrica is None:
                    try:
                        from ultralytics import YOLO  # import opcional e deliberadamente lazy
                    except ModuleNotFoundError as exc:
                        raise RuntimeError(
                            "Ultralytics não está instalado; instale os requisitos do Sentinel MT"
                        ) from exc

                    fabrica = YOLO
                self._dispositivo = self.dispositivo
                self._modelo = fabrica(str(self.caminho_modelo))
        return self._modelo

    @property
    def modelo_carregado(self) -> bool:
        return self._modelo is not None

    def fechar(self) -> None:
        """Libera o snapshot privado quando a inferência não será mais usada."""
        self._finalizador_snapshot()

    @property
    def dispositivo(self) -> str:
        """Retorna o backend efetivo, usando CPU quando CUDA não está disponível."""
        if self._dispositivo is None:
            self._dispositivo = self._selecionar_dispositivo()
        return self._dispositivo

    def detectar(
        self,
        imagem: str | os.PathLike[str],
        *,
        confianca_minima: float = 0.25,
        iou_maximo: float = 0.45,
        tamanho_inferencia_px: int = 640,
        tipo_entrada: TipoEntrada = "imagem",
        nuvens_pct: float | None = None,
    ) -> ResultadoDeteccao:
        caminho_imagem = Path(imagem).expanduser()
        if not caminho_imagem.is_file():
            raise ValueError("A entrada deve ser um arquivo de imagem local")
        if caminho_imagem.stat().st_size > MAX_BYTES_IMAGEM:
            raise ValueError("A imagem excede o limite de 100 MB")
        if tipo_entrada not in {"imagem", "tile"}:
            raise ValueError("tipo_entrada deve ser imagem ou tile")
        if not 0.0 <= confianca_minima <= 1.0:
            raise ValueError("confianca_minima deve estar entre 0 e 1")
        if not 0.0 <= iou_maximo <= 1.0:
            raise ValueError("iou_maximo deve estar entre 0 e 1")
        if tamanho_inferencia_px <= 0:
            raise ValueError("tamanho_inferencia_px deve ser positivo")
        if nuvens_pct is not None and not 0.0 <= nuvens_pct <= 100.0:
            raise ValueError("nuvens_pct deve estar entre 0 e 100")

        sha256_entrada = _sha256_arquivo(caminho_imagem)
        with Image.open(caminho_imagem) as aberta:
            largura, altura = aberta.size
            if largura * altura > MAX_PIXELS_IMAGEM:
                raise ValueError("A imagem excede o limite de 100 megapixels")

        modelo = self._carregar_modelo()
        bruto = modelo.predict(
            source=str(caminho_imagem),
            device=self._dispositivo,
            conf=confianca_minima,
            iou=iou_maximo,
            imgsz=tamanho_inferencia_px,
            max_det=MAX_DETECCOES_POR_IMAGEM,
            verbose=False,
        )
        resultados = list(bruto)
        primeiro = resultados[0] if resultados else None
        classes = _normalizar_classes(
            getattr(primeiro, "names", None) if primeiro is not None else getattr(modelo, "names", None)
        )
        if not classes:
            classes = _normalizar_classes(getattr(modelo, "names", None))
        deteccoes = self._transformar_resultado(primeiro, classes)
        metadados = MetadadosModelo(
            nome=self.nome_modelo,
            sha256=self.sha256_modelo,
            versao=self.versao_modelo,
            dispositivo=self._dispositivo or "cpu",
            classes=classes,
        )
        return ResultadoDeteccao(
            entrada=str(caminho_imagem),
            sha256_entrada=sha256_entrada,
            largura=largura,
            altura=altura,
            deteccoes=deteccoes,
            modelo=metadados,
            versao=__version__,
            tipo_entrada=tipo_entrada,
            nuvens_pct=nuvens_pct,
        )

    @staticmethod
    def _transformar_resultado(resultado: Any, classes: Mapping[int, str]) -> tuple[Deteccao, ...]:
        caixas = getattr(resultado, "boxes", None) if resultado is not None else None
        if caixas is None:
            return ()
        coordenadas = _lista(getattr(caixas, "xyxy", ()))
        confiancas = _lista(getattr(caixas, "conf", ()))
        identificadores = _lista(getattr(caixas, "cls", ()))
        if not (len(coordenadas) == len(confiancas) == len(identificadores)):
            raise ValueError("Saída do detector contém vetores com tamanhos incompatíveis")
        return tuple(
            Deteccao(
                classe=classes.get(int(id_classe), str(int(id_classe))),
                confianca=float(confianca),
                caixa=tuple(float(valor) for valor in coordenada),
                id_classe=int(id_classe),
            )
            for coordenada, confianca, id_classe in zip(
                coordenadas, confiancas, identificadores, strict=True
            )
        )

    def desenhar_overlay(
        self,
        imagem: str | os.PathLike[str] | Image.Image,
        resultado: ResultadoDeteccao,
        *,
        cor: str | tuple[int, int, int] = "#ffb000",
        largura_linha: int = 3,
    ) -> Image.Image:
        """Desenha caixas em uma cópia RGB, sem alterar a imagem científica original."""
        if isinstance(imagem, Image.Image):
            saida = imagem.convert("RGB").copy()
        else:
            with Image.open(imagem) as aberta:
                saida = aberta.convert("RGB")
        if saida.size != (resultado.largura, resultado.altura):
            raise ValueError("Dimensões da imagem não correspondem ao resultado")
        if largura_linha < 1:
            raise ValueError("largura_linha deve ser positiva")

        desenho = ImageDraw.Draw(saida)
        fonte = ImageFont.load_default()
        for deteccao in resultado.deteccoes:
            x1, y1, x2, y2 = deteccao.caixa
            desenho.rectangle((x1, y1, x2, y2), outline=cor, width=largura_linha)
            rotulo = f"{deteccao.classe} {deteccao.confianca:.2f}"
            caixa_texto = desenho.textbbox((x1, y1), rotulo, font=fonte)
            topo = max(0.0, y1 - (caixa_texto[3] - caixa_texto[1]) - 2)
            caixa_texto = desenho.textbbox((x1, topo), rotulo, font=fonte)
            desenho.rectangle(caixa_texto, fill=cor)
            desenho.text((x1, topo), rotulo, fill="black", font=fonte)
        return saida
