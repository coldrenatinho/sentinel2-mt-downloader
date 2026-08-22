"""Detecção agrícola e estatísticas sem acoplamento ao backend de IA."""

from .detector import DetectorAgricola, resolver_caminho_modelo
from .estatisticas import calcular_estatisticas
from .modelos import Deteccao, EstatisticasAnalise, MetadadosModelo, ResultadoDeteccao

__all__ = [
    "Deteccao",
    "DetectorAgricola",
    "EstatisticasAnalise",
    "MetadadosModelo",
    "ResultadoDeteccao",
    "calcular_estatisticas",
    "resolver_caminho_modelo",
]
