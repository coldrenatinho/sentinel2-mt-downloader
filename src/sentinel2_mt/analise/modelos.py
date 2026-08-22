from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


TipoEntrada = Literal["imagem", "tile"]


@dataclass(frozen=True, slots=True)
class Deteccao:
    """Uma detecção normalizada, sem objetos de Ultralytics ou Torch."""

    classe: str
    confianca: float
    caixa: tuple[float, float, float, float]
    id_classe: int | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Alias interoperável para a caixa ``(x1, y1, x2, y2)`` em pixels."""
        return self.caixa

    def para_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MetadadosModelo:
    nome: str
    sha256: str
    versao: str
    dispositivo: str
    classes: dict[int, str] = field(default_factory=dict)

    def para_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResultadoDeteccao:
    entrada: str
    sha256_entrada: str
    largura: int
    altura: int
    deteccoes: tuple[Deteccao, ...]
    modelo: MetadadosModelo
    versao: str
    tipo_entrada: TipoEntrada = "imagem"
    nuvens_pct: float | None = None

    @property
    def contagem(self) -> int:
        return len(self.deteccoes)

    @property
    def tem_deteccao(self) -> bool:
        return bool(self.deteccoes)

    def para_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EstatisticasAnalise:
    total_deteccoes: int
    por_classe: dict[str, int]
    confianca_media_por_classe: dict[str, float]
    confianca_minima_por_classe: dict[str, float]
    confianca_maxima_por_classe: dict[str, float]
    confianca_media: float | None
    confianca_minima: float | None
    confianca_maxima: float | None
    total_imagens: int
    imagens_com_deteccao: int
    percentual_imagens_com_deteccao: float
    total_tiles: int
    tiles_com_deteccao: int
    percentual_tiles_com_deteccao: float
    amostras_com_nuvens: int
    nuvens_media_pct: float | None
    nuvens_minima_pct: float | None
    nuvens_maxima_pct: float | None
    hashes_modelos: tuple[str, ...]
    hashes_entradas: tuple[str, ...]
    versoes: tuple[str, ...]

    @property
    def deteccoes_por_classe(self) -> dict[str, int]:
        return self.por_classe

    def para_dict(self) -> dict:
        return asdict(self)
