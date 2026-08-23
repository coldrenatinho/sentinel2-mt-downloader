from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Callable

from rasterio.warp import transform_bounds
from rasterio.errors import RasterioError

from .detector import DetectorAgricola
from .estatisticas import calcular_estatisticas
from .historico import RepositorioHistoricoAnalises
from .modelos import EstatisticasAnalise, ResultadoDeteccao
from .relatorio import GeradorRelatorioAnalise
from ..configuracao import ConfiguracaoProjeto
from ..servico import OpcoesColeta, ServicoSentinel2


LOGGER = logging.getLogger(__name__)
PATCH_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,140}$")


@dataclass(frozen=True, slots=True)
class OpcoesAnalise:
    inicio: str | None = None
    fim: str | None = None
    max_itens: int | None = None
    patch_size: int | None = None
    patch_stride: int | None = None
    coletar: bool = True


@dataclass(frozen=True, slots=True)
class ResultadoAnaliseRegiao:
    analysis_id: str
    criado_em: str
    regiao: str
    bbox: tuple[float, float, float, float]
    periodo_inicio: str
    periodo_fim: str
    scene_ids: tuple[str, ...]
    modelo_versao: str
    modelo_hash: str
    dispositivo: str
    estatisticas: EstatisticasAnalise
    resultados: tuple[ResultadoDeteccao, ...]
    imagem_original: str
    imagem_analisada: str
    caminho_resultado: str
    caminho_relatorio: str = ""

    def para_dict(self) -> dict:
        dados = asdict(self)
        dados["resumo"] = dados["estatisticas"]
        return dados


class ServicoAnaliseAgricola:
    """Coordena aquisição, patches RGB, inferência, estatísticas, PDF e histórico."""

    def __init__(
        self,
        config: ConfiguracaoProjeto,
        *,
        detector_factory: Callable[..., DetectorAgricola] = DetectorAgricola,
        servico_coleta_factory: Callable[..., ServicoSentinel2] = ServicoSentinel2,
        historico_factory: Callable[..., RepositorioHistoricoAnalises] = RepositorioHistoricoAnalises,
        gerador_relatorio: GeradorRelatorioAnalise | None = None,
        saida: Callable[[str], None] = print,
    ) -> None:
        self.config = config
        self.detector_factory = detector_factory
        self.servico_coleta_factory = servico_coleta_factory
        self.historico_factory = historico_factory
        self.gerador_relatorio = gerador_relatorio or GeradorRelatorioAnalise()
        self.saida = saida

    def executar(self, opcoes: OpcoesAnalise | None = None) -> ResultadoAnaliseRegiao:
        opcoes = opcoes or OpcoesAnalise()
        inicio = opcoes.inicio or self.config.periodo.inicio
        fim = opcoes.fim or self.config.periodo.fim
        self._validar_periodo(inicio, fim)

        detector = self._criar_detector()
        self.saida(f"[IA] Dispositivo de processamento: {self._rotulo_dispositivo(detector)}")

        if opcoes.coletar:
            self.saida("[ANÁLISE] Obtendo e preparando imagens Sentinel-2...")
            resumo = self.servico_coleta_factory(self.config, saida=self.saida).executar(
                OpcoesColeta(
                    baixar_arquivos=True,
                    inicio=inicio,
                    fim=fim,
                    max_itens=opcoes.max_itens,
                    gerar_dataset=True,
                    patch_size=opcoes.patch_size,
                    patch_stride=opcoes.patch_stride,
                )
            )
            if resumo.erros:
                raise RuntimeError(
                    f"O processamento Sentinel-2 terminou com {resumo.erros} erro(s)"
                )

        entradas = self._listar_entradas(inicio, fim)
        if not entradas:
            raise ValueError("Nenhum patch RGB aprovado foi encontrado para o período informado")

        analysis_id = self._analysis_id(entradas, detector, inicio, fim)
        pasta_analise = self._caminho_estado(self.config.analise.pasta, "analise.pasta") / analysis_id
        pasta_analise.mkdir(parents=True, exist_ok=True)
        resultados: list[ResultadoDeteccao] = []
        overlays: list[Path] = []
        scene_ids: list[str] = []

        for indice, entrada in enumerate(entradas, start=1):
            caminho = entrada["caminho"]
            self.saida(f"[IA] Imagem {indice}/{len(entradas)}: {entrada['patch_id']}")
            resultado = detector.detectar(
                caminho,
                confianca_minima=self.config.analise.confianca_minima,
                iou_maximo=self.config.analise.iou_maximo,
                tamanho_inferencia_px=self.config.analise.tamanho_inferencia_px,
                tipo_entrada="tile",
                nuvens_pct=entrada["nuvens_pct"],
            )
            resultados.append(resultado)
            scene_ids.append(entrada["scene_id"])
            overlay = pasta_analise / f"{entrada['patch_id']}-deteccoes.png"
            self._salvar_imagem_atomica(detector.desenhar_overlay(caminho, resultado), overlay)
            overlays.append(overlay)

        estatisticas = calcular_estatisticas(resultados)
        criado_em = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        primeiro = resultados[0]
        caminho_resultado = pasta_analise / "resultado.json"
        caminho_relatorio = pasta_analise / "relatorio.pdf"
        analise = ResultadoAnaliseRegiao(
            analysis_id=analysis_id,
            criado_em=criado_em,
            regiao=self.config.area.nome,
            bbox=self.config.area.bbox,
            periodo_inicio=inicio,
            periodo_fim=fim,
            scene_ids=tuple(dict.fromkeys(scene_ids)),
            modelo_versao=primeiro.modelo.versao,
            modelo_hash=primeiro.modelo.sha256,
            dispositivo=primeiro.modelo.dispositivo,
            estatisticas=estatisticas,
            resultados=tuple(resultados),
            imagem_original=str(entradas[0]["caminho"]),
            imagem_analisada=str(overlays[0]),
            caminho_resultado=str(caminho_resultado),
            caminho_relatorio=str(caminho_relatorio) if self.config.analise.gerar_relatorio else "",
        )
        if self.config.analise.gerar_relatorio:
            try:
                self.gerador_relatorio.gerar(
                    caminho_relatorio,
                    {
                        "analysis_id": analysis_id,
                        "regiao": self.config.area.nome,
                        "bbox": self.config.area.bbox,
                        "periodo_inicio": inicio,
                        "periodo_fim": fim,
                        "scene_id": ", ".join(analise.scene_ids),
                        "resumo": estatisticas.para_dict(),
                        "modelo_versao": analise.modelo_versao,
                        "modelo_hash": analise.modelo_hash,
                        "metodologia": (
                            "Detecção YOLO sobre RGB B04/B03/B02 dos patches aprovados; "
                            "os GeoTIFFs multibanda científicos permanecem inalterados."
                        ),
                    },
                    imagens=(
                        {"path": entradas[0]["caminho"], "titulo": "Patch RGB original"},
                        {"path": overlays[0], "titulo": "Patch com detecções"},
                    ),
                )
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Não foi possível gerar o PDF: matplotlib não está instalado"
                ) from exc

        self._salvar_json_atomico(caminho_resultado, self._serializar_publico(analise))
        self._registrar_historico(analise)
        self.saida(f"[ANÁLISE] Resultado: {self._relativo(caminho_resultado)}")
        return analise

    def _criar_detector(self) -> DetectorAgricola:
        raiz_pacote = Path(__file__).resolve().parents[1]
        relativo = Path(self.config.analise.modelo)
        if relativo.is_absolute() or relativo.parent != Path("analise/models"):
            raise ValueError("analise.modelo deve apontar para analise/models/<arquivo>.pt")
        raizes = (raiz_pacote,)
        metadata = self._ler_metadata_modelo(raizes)
        hash_manifesto = str(metadata.get("sha256", "")).strip().lower()
        if self.detector_factory is DetectorAgricola:
            if not re.fullmatch(r"[0-9a-f]{64}", hash_manifesto):
                raise ValueError(
                    "model_metadata.json deve conter o SHA-256 aprovado do best.pt"
                )
            if (
                self.config.analise.modelo_sha256
                and self.config.analise.modelo_sha256.lower() != hash_manifesto
            ):
                raise ValueError("SHA-256 do YAML diverge do manifesto aprovado do modelo")
        return self.detector_factory(
            self.config.analise.modelo,
            sha256_modelo=hash_manifesto or self.config.analise.modelo_sha256 or None,
            versao_modelo=str(metadata.get("version", "não informada")),
            dispositivo="auto",
            raizes_confiaveis=raizes,
        )

    def _ler_metadata_modelo(self, raizes: tuple[Path, ...]) -> dict:
        relativo = Path(self.config.analise.modelo)
        for raiz in raizes:
            candidato = raiz / relativo.parent / "model_metadata.json"
            if candidato.is_file() and not candidato.is_symlink():
                try:
                    dados = json.loads(candidato.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Metadados do modelo inválidos: {candidato.name}") from exc
                return dados if isinstance(dados, dict) else {}
        return {}

    def _listar_entradas(self, inicio: str, fim: str) -> list[dict]:
        catalogo = self.config.caminho(self.config.dataset.catalogo)
        raiz_dataset = self.config.caminho(self.config.dataset.pasta).resolve()
        if not catalogo.is_file():
            raise FileNotFoundError(f"Catálogo de patches não encontrado: {catalogo}")
        entradas: list[dict] = []
        with catalogo.open("r", newline="", encoding="utf-8-sig") as arquivo:
            for linha in csv.DictReader(arquivo):
                if str(linha.get("status", "")) not in {"APROVADO", "APROVADO_SEM_SCL"}:
                    continue
                if str(linha.get("collection", "")) != self.config.stac.colecao:
                    continue
                data = str(linha.get("date", ""))
                if not inicio <= data <= fim:
                    continue
                rgb = str(linha.get("rgb_png", ""))
                if not rgb:
                    continue
                bandas = {item for item in str(linha.get("bands", "")).split(";") if item}
                if not {"B02", "B03", "B04"}.issubset(bandas):
                    continue
                if not self._intersecta_area(linha):
                    continue
                caminho = self.config.caminho(rgb).resolve()
                try:
                    caminho.relative_to(raiz_dataset)
                except ValueError:
                    LOGGER.warning("Entrada RGB fora da raiz do dataset ignorada: %s", caminho.name)
                    continue
                if not caminho.is_file() or caminho.is_symlink():
                    continue
                patch_id = str(linha.get("patch_id", caminho.parent.name))
                if not PATCH_ID_RE.fullmatch(patch_id):
                    LOGGER.warning("Identificador de patch inválido ignorado")
                    continue
                if caminho.parent.name != patch_id:
                    LOGGER.warning("RGB com identidade de patch inconsistente ignorado: %s", caminho.name)
                    continue
                geotiff_texto = str(linha.get("geotiff_path", ""))
                if not geotiff_texto:
                    continue
                geotiff = self.config.caminho(geotiff_texto).resolve()
                try:
                    geotiff.relative_to(raiz_dataset)
                except ValueError:
                    continue
                if (
                    not geotiff.is_file()
                    or geotiff.is_symlink()
                    or geotiff.parent != caminho.parent
                ):
                    continue
                metadata = caminho.parent / "metadata.json"
                if metadata.is_file() and not self._metadata_compativel(
                    metadata, patch_id, bandas
                ):
                    continue
                try:
                    nuvens = float(linha["cloud_pct"]) if linha.get("cloud_pct") else None
                except ValueError:
                    nuvens = None
                entradas.append(
                    {
                        "patch_id": patch_id,
                        "scene_id": str(linha.get("scene_id", "")),
                        "collection": str(linha.get("collection", "")),
                        "date": data,
                        "bbox": str(linha.get("bbox", "")),
                        "crs": str(linha.get("crs", "")),
                        "bands": ";".join(sorted(bandas)),
                        "caminho": caminho,
                        "geotiff": geotiff,
                        "nuvens_pct": nuvens,
                    }
                )
        entradas.sort(key=lambda item: (item["scene_id"], item["patch_id"]))
        limite = self.config.analise.max_imagens
        return entradas[:limite] if limite else entradas

    @staticmethod
    def _metadata_compativel(metadata: Path, patch_id: str, bandas: set[str]) -> bool:
        if metadata.is_symlink():
            return False
        try:
            dados = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        bandas_metadata = set(dados.get("bands", ())) if isinstance(dados, dict) else set()
        return (
            isinstance(dados, dict)
            and str(dados.get("patch_id", "")) == patch_id
            and {"B02", "B03", "B04"}.issubset(bandas_metadata)
            and bandas_metadata == bandas
        )

    def _intersecta_area(self, linha: dict) -> bool:
        try:
            bbox = json.loads(str(linha.get("bbox", "")))
            if not isinstance(bbox, list) or len(bbox) != 4:
                return False
            crs = str(linha.get("crs", ""))
            if not crs:
                return False
            oeste, sul, leste, norte = transform_bounds(
                crs, "EPSG:4326", *(float(valor) for valor in bbox), densify_pts=21
            )
        except (TypeError, ValueError, json.JSONDecodeError, RasterioError):
            return False
        area_oeste, area_sul, area_leste, area_norte = self.config.area.bbox
        return not (
            leste <= area_oeste
            or oeste >= area_leste
            or norte <= area_sul
            or sul >= area_norte
        )

    def _analysis_id(
        self,
        entradas: list[dict],
        detector: DetectorAgricola,
        inicio: str,
        fim: str,
    ) -> str:
        receita = {
            "bbox": self.config.area.bbox,
            "inicio": inicio,
            "fim": fim,
            "modelo": detector.sha256_modelo,
            "confianca": self.config.analise.confianca_minima,
            "iou": self.config.analise.iou_maximo,
            "tamanho": self.config.analise.tamanho_inferencia_px,
            "entradas": [
                {
                    "patch_id": item["patch_id"],
                    "scene_id": item["scene_id"],
                    "collection": item["collection"],
                    "date": item["date"],
                    "bbox": item["bbox"],
                    "crs": item["crs"],
                    "bands": item["bands"],
                    "path": self._relativo(item["caminho"]),
                    "sha256": self._sha256(item["caminho"]),
                }
                for item in entradas
            ],
        }
        digest = hashlib.sha256(
            json.dumps(receita, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        return f"analise-{digest}"

    def _registrar_historico(self, analise: ResultadoAnaliseRegiao) -> None:
        historico = self.historico_factory(
            self._caminho_estado(self.config.analise.historico, "analise.historico"),
            self.config.raiz,
        )
        historico.salvar(
            {
                "analysis_id": analise.analysis_id,
                "status": "concluida",
                "regiao": analise.regiao,
                "bbox": analise.bbox,
                "periodo_inicio": analise.periodo_inicio,
                "periodo_fim": analise.periodo_fim,
                "scene_id": ",".join(analise.scene_ids),
                "modelo_versao": analise.modelo_versao,
                "modelo_hash": analise.modelo_hash,
                "resumo": analise.estatisticas.para_dict(),
                "metadados": {"dispositivo": analise.dispositivo},
                "caminho_entrada": analise.imagem_original,
                "report_path": analise.caminho_relatorio,
            }
        )

    def _serializar_publico(self, analise: ResultadoAnaliseRegiao) -> dict:
        dados = analise.para_dict()
        for chave in ("imagem_original", "imagem_analisada", "caminho_resultado", "caminho_relatorio"):
            valor = dados.get(chave)
            if valor:
                dados[chave] = self._relativo(Path(valor))
        for resultado in dados["resultados"]:
            resultado["entrada"] = self._relativo(Path(resultado["entrada"]))
        return dados

    def _relativo(self, caminho: Path) -> str:
        try:
            return caminho.resolve().relative_to(self.config.raiz.resolve()).as_posix()
        except ValueError:
            return caminho.name

    def _caminho_estado(self, valor: str, campo: str) -> Path:
        informado = Path(valor).expanduser()
        caminho = informado if informado.is_absolute() else self.config.raiz / informado
        raiz = self.config.raiz.resolve()
        resolvido = caminho.resolve(strict=False)
        try:
            relativo = resolvido.relative_to(raiz)
        except ValueError as exc:
            raise ValueError(f"{campo} deve permanecer dentro da raiz da aplicação") from exc
        if not relativo.parts:
            raise ValueError(f"{campo} não pode ser a raiz da aplicação")
        atual = raiz
        for parte in relativo.parts:
            atual = atual / parte
            if atual.is_symlink():
                raise ValueError(f"{campo} não pode usar links simbólicos")
        return resolvido

    @staticmethod
    def _salvar_imagem_atomica(imagem, destino: Path) -> None:
        with NamedTemporaryFile(
            prefix=f".{destino.name}.", suffix=".png", dir=destino.parent, delete=False
        ) as arquivo:
            temporario = Path(arquivo.name)
        try:
            imagem.save(temporario, "PNG")
            os.replace(temporario, destino)
        finally:
            temporario.unlink(missing_ok=True)

    @staticmethod
    def _salvar_json_atomico(destino: Path, dados: dict) -> None:
        with NamedTemporaryFile(
            "w", prefix=f".{destino.name}.", suffix=".tmp", dir=destino.parent,
            delete=False, encoding="utf-8"
        ) as arquivo:
            temporario = Path(arquivo.name)
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
            arquivo.write("\n")
            arquivo.flush()
            os.fsync(arquivo.fileno())
        try:
            os.replace(temporario, destino)
        finally:
            temporario.unlink(missing_ok=True)

    @staticmethod
    def _sha256(caminho: Path) -> str:
        digest = hashlib.sha256()
        with caminho.open("rb") as arquivo:
            for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
                digest.update(bloco)
        return digest.hexdigest()

    @staticmethod
    def _validar_periodo(inicio: str, fim: str) -> None:
        try:
            data_inicio = datetime.fromisoformat(inicio).date()
            data_fim = datetime.fromisoformat(fim).date()
        except ValueError as exc:
            raise ValueError("Período deve usar datas válidas no formato AAAA-MM-DD") from exc
        if data_inicio > data_fim:
            raise ValueError("Data inicial não pode ser posterior à data final")

    @staticmethod
    def _rotulo_dispositivo(detector: DetectorAgricola) -> str:
        dispositivo = getattr(detector, "dispositivo", "cpu")
        return "NVIDIA GPU" if str(dispositivo).startswith("cuda") else "CPU"
