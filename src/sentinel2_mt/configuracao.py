from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
import math
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ConfiguracaoStac:
    url: str
    colecao: str


@dataclass(frozen=True)
class ConfiguracaoArea:
    nome: str
    uf: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class ConfiguracaoPeriodo:
    inicio: str
    fim: str


@dataclass(frozen=True)
class ConfiguracaoQualidade:
    filtrar_nuvens: bool = True
    nuvem_max_pct: float = 20.0
    manter_scl: bool = True
    camadas_auxiliares: tuple[str, ...] = ("SCL", "CLEAROB", "TOTALOB", "PROVENANCE")

    @property
    def cena_nuvem_max_pct(self) -> float:
        """Alias explícito para distinguir o limite da cena do limite dos patches."""
        return self.nuvem_max_pct


@dataclass(frozen=True)
class ConfiguracaoPreview:
    gerar_rgb: bool = True
    tamanho_max_px: int = 1600
    metodo: str = "percentile"
    minimo: float = 0.0
    maximo: float = 2000.0
    percentil_min: float = 2.0
    percentil_max: float = 98.0
    qualidade_jpeg: int = 92


@dataclass(frozen=True)
class ConfiguracaoRGBDataset:
    gerar_png: bool = True
    metodo: str = "fixed"
    minimo: float = 0.0
    maximo: float = 2000.0
    percentil_min: float = 2.0
    percentil_max: float = 98.0


@dataclass(frozen=True)
class ConfiguracaoPatches:
    habilitado: bool = True
    tamanho_px: int = 512
    stride_px: int = 512
    nuvem_max_pct: float = 10.0
    dados_validos_min_pct: float = 90.0
    max_patches_por_cena: int = 100_000


@dataclass(frozen=True)
class ConfiguracaoDataset:
    gerar: bool = False
    pasta: str = "data/dataset"
    catalogo: str = "catalogo/patches.csv"
    rgb: ConfiguracaoRGBDataset = field(default_factory=ConfiguracaoRGBDataset)
    patches: ConfiguracaoPatches = field(default_factory=ConfiguracaoPatches)
    gerar_geotiff_multibanda: bool = True
    gerar_metadata_json: bool = True


@dataclass(frozen=True)
class ConfiguracaoDownload:
    pasta: str = "data/sentinel2"
    catalogo: str = "catalogo/catalogo_imagens.csv"
    timeout_segundos: int = 120
    chunk_mb: int = 1
    max_itens_teste: int = 5
    max_candidatos_teste: int = 40


@dataclass(frozen=True)
class ConfiguracaoSincronizacao:
    pasta_remota: str = "sentinel2-mt"
    oauth_json: str = "config/google-oauth.json"
    token_json: str = "config/google-token.json"
    pasta_id: str = "root"
    tamanho_lote: int = 100
    extensoes: tuple[str, ...] = (".tif", ".tiff", ".jpg", ".jpeg")


@dataclass(frozen=True)
class ConfiguracaoAnalise:
    modelo: str = "analise/models/agricultura.pt"
    modelo_sha256: str = ""
    confianca_minima: float = 0.25
    iou_maximo: float = 0.45
    tamanho_inferencia_px: int = 640
    pasta: str = "data/analises"
    historico: str = "data/historico-analises.sqlite3"
    gerar_relatorio: bool = True
    max_imagens: int = 1000


@dataclass(frozen=True)
class ConfiguracaoProjeto:
    raiz: Path
    stac: ConfiguracaoStac
    area: ConfiguracaoArea
    periodo: ConfiguracaoPeriodo
    bandas: tuple[str, ...]
    qualidade: ConfiguracaoQualidade
    preview: ConfiguracaoPreview
    download: ConfiguracaoDownload
    sincronizacao: ConfiguracaoSincronizacao
    dataset: ConfiguracaoDataset = field(default_factory=ConfiguracaoDataset)
    analise: ConfiguracaoAnalise = field(default_factory=ConfiguracaoAnalise)

    @classmethod
    def carregar(cls, caminho: Path, raiz: Path | None = None) -> "ConfiguracaoProjeto":
        caminho = caminho.expanduser().resolve()
        with caminho.open("r", encoding="utf-8") as arquivo:
            dados = yaml.safe_load(arquivo) or {}

        ambiente = cls._carregar_dotenv(caminho.parent / ".env")
        ambiente.update(os.environ)
        dados = cls._expandir_variaveis(dados, ambiente)

        cls._validar_secoes(dados)
        raiz_projeto = (raiz or caminho.parents[1]).resolve()
        area = dados["area"]
        bbox = tuple(float(valor) for valor in area["bbox"])
        if len(bbox) != 4:
            raise ValueError("area.bbox deve conter quatro coordenadas")

        qualidade = dict(dados.get("qualidade", {}))
        if "cena_nuvem_max_pct" in qualidade:
            qualidade.setdefault("nuvem_max_pct", qualidade.pop("cena_nuvem_max_pct"))
        qualidade["camadas_auxiliares"] = tuple(
            str(asset).upper() for asset in qualidade.get(
                "camadas_auxiliares", ("SCL", "CLEAROB", "TOTALOB", "PROVENANCE")
            )
        )
        preview = dict(dados.get("preview", {}))
        preview.setdefault("metodo", "percentile")
        dataset_dados = dict(dados.get("dataset", {}))
        rgb_dados = dict(dataset_dados.pop("rgb", {}))
        if "gerar_rgb_png" in dataset_dados:
            rgb_dados.setdefault("gerar_png", dataset_dados.pop("gerar_rgb_png"))
        patches_dados = dict(dataset_dados.pop("patches", {}))
        download = dados.get("download", {})
        sincronizacao = dados.get("sincronizacao", {})
        analise = dict(dados.get("analise", {}))
        oauth_json = sincronizacao.get("oauth_json") or cls._descobrir_oauth(raiz_projeto)
        config = cls(
            raiz=raiz_projeto,
            stac=ConfiguracaoStac(**dados["stac"]),
            area=ConfiguracaoArea(nome=area["nome"], uf=area["uf"], bbox=bbox),
            periodo=ConfiguracaoPeriodo(
                inicio=str(dados["periodo"]["inicio"]),
                fim=str(dados["periodo"]["fim"]),
            ),
            bandas=tuple(str(banda).upper() for banda in dados["bandas"]),
            qualidade=ConfiguracaoQualidade(**qualidade),
            preview=ConfiguracaoPreview(**preview),
            download=ConfiguracaoDownload(**download),
            sincronizacao=ConfiguracaoSincronizacao(
                pasta_remota=sincronizacao.get("pasta_remota", "sentinel2-mt"),
                oauth_json=oauth_json,
                token_json=sincronizacao.get("token_json", "config/google-token.json"),
                pasta_id=str(sincronizacao.get("pasta_id", "root")),
                tamanho_lote=int(sincronizacao.get("tamanho_lote", 100)),
                extensoes=tuple(sincronizacao.get("extensoes", (".tif", ".tiff", ".jpg", ".jpeg"))),
            ),
            dataset=ConfiguracaoDataset(
                rgb=ConfiguracaoRGBDataset(**rgb_dados),
                patches=ConfiguracaoPatches(**patches_dados),
                **dataset_dados,
            ),
            analise=ConfiguracaoAnalise(**analise),
        )
        config.validar()
        return config

    @staticmethod
    def _carregar_dotenv(caminho: Path) -> dict[str, str]:
        ambiente: dict[str, str] = {}
        if not caminho.is_file():
            return ambiente
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            if linha.startswith("export "):
                linha = linha[7:].strip()
            chave, valor = linha.split("=", 1)
            ambiente[chave.strip()] = valor.strip().strip("\"'")
        return ambiente

    @classmethod
    def _expandir_variaveis(cls, valor: Any, ambiente: dict[str, str]) -> Any:
        if isinstance(valor, dict):
            return {chave: cls._expandir_variaveis(item, ambiente) for chave, item in valor.items()}
        if isinstance(valor, list):
            return [cls._expandir_variaveis(item, ambiente) for item in valor]
        if not isinstance(valor, str):
            return valor

        padrao = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")

        def substituir(correspondencia: re.Match[str]) -> str:
            chave, default = correspondencia.group(1), correspondencia.group(2) or ""
            return ambiente.get(chave) or default

        return padrao.sub(substituir, valor)

    @staticmethod
    def _descobrir_oauth(raiz: Path) -> str:
        candidatos = sorted((raiz / "config").glob("client_secret_*.json"))
        if len(candidatos) == 1:
            return str(candidatos[0])
        if len(candidatos) > 1:
            raise ValueError("Há mais de um client_secret_*.json; informe GOOGLE_OAUTH_JSON no config/.env")
        return "config/google-oauth.json"

    @staticmethod
    def _validar_secoes(dados: dict) -> None:
        obrigatorias = ("stac", "area", "periodo", "bandas", "download")
        ausentes = [secao for secao in obrigatorias if secao not in dados]
        if ausentes:
            raise ValueError(f"Seções obrigatórias ausentes: {', '.join(ausentes)}")

    def validar(self) -> None:
        if not self.stac.url or not self.stac.colecao:
            raise ValueError("stac.url e stac.colecao são obrigatórios")
        if not self.bandas:
            raise ValueError("Ao menos uma banda deve ser configurada")
        oeste, sul, leste, norte = self.area.bbox
        if not all(math.isfinite(valor) for valor in self.area.bbox):
            raise ValueError("area.bbox deve conter coordenadas finitas")
        if not (-180 <= oeste < leste <= 180 and -90 <= sul < norte <= 90):
            raise ValueError(
                "area.bbox deve respeitar limites geográficos e oeste < leste, sul < norte"
            )
        try:
            inicio = date.fromisoformat(self.periodo.inicio)
            fim = date.fromisoformat(self.periodo.fim)
        except ValueError as exc:
            raise ValueError("periodo deve usar datas válidas no formato AAAA-MM-DD") from exc
        if inicio > fim:
            raise ValueError("periodo.inicio não pode ser posterior a periodo.fim")
        if self.download.timeout_segundos <= 0 or self.download.chunk_mb <= 0:
            raise ValueError("Timeout e tamanho do chunk devem ser positivos")
        if not 0 <= self.qualidade.nuvem_max_pct <= 100:
            raise ValueError("qualidade.nuvem_max_pct deve estar entre 0 e 100")
        if self.preview.metodo not in {"fixed", "percentile"}:
            raise ValueError("preview.metodo deve ser fixed ou percentile")
        if self.preview.tamanho_max_px <= 0:
            raise ValueError("preview.tamanho_max_px deve ser positivo")
        if not 1 <= self.preview.qualidade_jpeg <= 100:
            raise ValueError("preview.qualidade_jpeg deve estar entre 1 e 100")
        self._validar_rgb(
            self.preview.metodo,
            self.preview.minimo,
            self.preview.maximo,
            self.preview.percentil_min,
            self.preview.percentil_max,
            "preview",
        )
        patches = self.dataset.patches
        if patches.tamanho_px not in {256, 512}:
            raise ValueError("dataset.patches.tamanho_px deve ser 256 ou 512")
        if patches.stride_px <= 0:
            raise ValueError("dataset.patches.stride_px deve ser positivo")
        if patches.max_patches_por_cena <= 0:
            raise ValueError("dataset.patches.max_patches_por_cena deve ser positivo")
        if not 0 <= patches.nuvem_max_pct <= 100:
            raise ValueError("dataset.patches.nuvem_max_pct deve estar entre 0 e 100")
        if not 0 <= patches.dados_validos_min_pct <= 100:
            raise ValueError("dataset.patches.dados_validos_min_pct deve estar entre 0 e 100")
        rgb = self.dataset.rgb
        self._validar_rgb(rgb.metodo, rgb.minimo, rgb.maximo, rgb.percentil_min, rgb.percentil_max, "dataset.rgb")
        if self.sincronizacao.tamanho_lote <= 0:
            raise ValueError("sincronizacao.tamanho_lote deve ser maior que zero")
        if not 0 <= self.analise.confianca_minima <= 1:
            raise ValueError("analise.confianca_minima deve estar entre 0 e 1")
        if not 0 <= self.analise.iou_maximo <= 1:
            raise ValueError("analise.iou_maximo deve estar entre 0 e 1")
        if self.analise.tamanho_inferencia_px <= 0:
            raise ValueError("analise.tamanho_inferencia_px deve ser positivo")
        if self.analise.tamanho_inferencia_px > 2048:
            raise ValueError("analise.tamanho_inferencia_px não pode exceder 2048")
        if self.analise.max_imagens < 0:
            raise ValueError("analise.max_imagens não pode ser negativo")
        if self.analise.max_imagens > 10_000:
            raise ValueError("analise.max_imagens não pode exceder 10000")
        sha256 = self.analise.modelo_sha256.strip().lower()
        if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("analise.modelo_sha256 deve ser um SHA-256 hexadecimal")

    @staticmethod
    def _validar_rgb(
        metodo: str,
        minimo: float,
        maximo: float,
        percentil_min: float,
        percentil_max: float,
        prefixo: str,
    ) -> None:
        if metodo not in {"fixed", "percentile"}:
            raise ValueError(f"{prefixo}.metodo deve ser fixed ou percentile")
        if maximo <= minimo:
            raise ValueError(f"{prefixo}.maximo deve ser maior que minimo")
        if not 0 <= percentil_min < percentil_max <= 100:
            raise ValueError(f"Percentis de {prefixo} devem respeitar 0 <= min < max <= 100")

    def caminho(self, valor: str | Path) -> Path:
        caminho = Path(valor).expanduser()
        return caminho if caminho.is_absolute() else self.raiz / caminho
