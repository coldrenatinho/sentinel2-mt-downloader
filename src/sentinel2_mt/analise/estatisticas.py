from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from statistics import fmean

from .modelos import EstatisticasAnalise, ResultadoDeteccao


def _percentual(parte: int, total: int) -> float:
    return 0.0 if total == 0 else parte * 100.0 / total


def calcular_estatisticas(resultados: Iterable[ResultadoDeteccao]) -> EstatisticasAnalise:
    """Agrega contagens e percentuais; caixas não são convertidas em área."""
    itens = tuple(resultados)
    deteccoes = tuple(deteccao for resultado in itens for deteccao in resultado.deteccoes)
    confiancas = tuple(deteccao.confianca for deteccao in deteccoes)
    nuvens = tuple(
        resultado.nuvens_pct for resultado in itens if resultado.nuvens_pct is not None
    )
    imagens = tuple(resultado for resultado in itens if resultado.tipo_entrada == "imagem")
    tiles = tuple(resultado for resultado in itens if resultado.tipo_entrada == "tile")
    imagens_detectadas = sum(resultado.tem_deteccao for resultado in imagens)
    tiles_detectados = sum(resultado.tem_deteccao for resultado in tiles)
    classes = sorted({item.classe for item in deteccoes})
    confiancas_por_classe = {
        classe: tuple(item.confianca for item in deteccoes if item.classe == classe)
        for classe in classes
    }

    return EstatisticasAnalise(
        total_deteccoes=len(deteccoes),
        por_classe=dict(sorted(Counter(item.classe for item in deteccoes).items())),
        confianca_media_por_classe={
            classe: fmean(valores) for classe, valores in confiancas_por_classe.items()
        },
        confianca_minima_por_classe={
            classe: min(valores) for classe, valores in confiancas_por_classe.items()
        },
        confianca_maxima_por_classe={
            classe: max(valores) for classe, valores in confiancas_por_classe.items()
        },
        confianca_media=fmean(confiancas) if confiancas else None,
        confianca_minima=min(confiancas) if confiancas else None,
        confianca_maxima=max(confiancas) if confiancas else None,
        total_imagens=len(imagens),
        imagens_com_deteccao=imagens_detectadas,
        percentual_imagens_com_deteccao=_percentual(imagens_detectadas, len(imagens)),
        total_tiles=len(tiles),
        tiles_com_deteccao=tiles_detectados,
        percentual_tiles_com_deteccao=_percentual(tiles_detectados, len(tiles)),
        amostras_com_nuvens=len(nuvens),
        nuvens_media_pct=fmean(nuvens) if nuvens else None,
        nuvens_minima_pct=min(nuvens) if nuvens else None,
        nuvens_maxima_pct=max(nuvens) if nuvens else None,
        hashes_modelos=tuple(sorted({resultado.modelo.sha256 for resultado in itens})),
        hashes_entradas=tuple(resultado.sha256_entrada for resultado in itens),
        versoes=tuple(sorted({resultado.versao for resultado in itens})),
    )
