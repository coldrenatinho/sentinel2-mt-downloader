from __future__ import annotations

from dataclasses import fields
from unittest import TestCase

from sentinel2_mt.analise import (
    Deteccao,
    EstatisticasAnalise,
    MetadadosModelo,
    ResultadoDeteccao,
    calcular_estatisticas,
)


HASH_MODELO = "a" * 64


def resultado(
    nome: str,
    tipo: str,
    deteccoes: tuple[Deteccao, ...],
    nuvens: float | None,
) -> ResultadoDeteccao:
    return ResultadoDeteccao(
        entrada=f"{nome}.png",
        sha256_entrada=(nome[0] * 64),
        largura=256,
        altura=256,
        deteccoes=deteccoes,
        modelo=MetadadosModelo(
            nome="best.pt",
            sha256=HASH_MODELO,
            versao="2026.1",
            dispositivo="cpu",
        ),
        versao="2.1.0-beta.1",
        tipo_entrada=tipo,
        nuvens_pct=nuvens,
    )


class TestEstatisticasAnalise(TestCase):
    def test_agrega_contagem_classes_confiancas_percentuais_nuvens_e_proveniencia(self) -> None:
        soja_90 = Deteccao("soja", 0.9, (0, 0, 10, 10), 0)
        soja_60 = Deteccao("soja", 0.6, (10, 10, 20, 20), 0)
        milho_30 = Deteccao("milho", 0.3, (5, 5, 8, 8), 1)
        resultados = (
            resultado("a", "imagem", (soja_90, milho_30), 10.0),
            resultado("b", "imagem", (), 30.0),
            resultado("c", "tile", (soja_60,), None),
            resultado("d", "tile", (), 20.0),
        )

        resumo = calcular_estatisticas(resultados)

        self.assertEqual(resumo.total_deteccoes, 3)
        self.assertEqual(resumo.por_classe, {"milho": 1, "soja": 2})
        self.assertEqual(resumo.confianca_media_por_classe["soja"], 0.75)
        self.assertEqual(resumo.confianca_minima_por_classe["milho"], 0.3)
        self.assertEqual(resumo.confianca_maxima_por_classe["soja"], 0.9)
        self.assertEqual(resumo.deteccoes_por_classe, resumo.por_classe)
        self.assertAlmostEqual(resumo.confianca_media, 0.6)
        self.assertEqual(resumo.confianca_minima, 0.3)
        self.assertEqual(resumo.confianca_maxima, 0.9)
        self.assertEqual((resumo.total_imagens, resumo.imagens_com_deteccao), (2, 1))
        self.assertEqual(resumo.percentual_imagens_com_deteccao, 50.0)
        self.assertEqual((resumo.total_tiles, resumo.tiles_com_deteccao), (2, 1))
        self.assertEqual(resumo.percentual_tiles_com_deteccao, 50.0)
        self.assertEqual(resumo.amostras_com_nuvens, 3)
        self.assertEqual(resumo.nuvens_media_pct, 20.0)
        self.assertEqual(resumo.nuvens_minima_pct, 10.0)
        self.assertEqual(resumo.nuvens_maxima_pct, 30.0)
        self.assertEqual(resumo.hashes_modelos, (HASH_MODELO,))
        self.assertEqual(resumo.hashes_entradas, ("a" * 64, "b" * 64, "c" * 64, "d" * 64))
        self.assertEqual(resumo.versoes, ("2.1.0-beta.1",))

    def test_vazio_nao_divide_por_zero_e_nao_inventa_confianca_ou_nuvens(self) -> None:
        resumo = calcular_estatisticas([])

        self.assertEqual(resumo.total_deteccoes, 0)
        self.assertEqual(resumo.por_classe, {})
        self.assertIsNone(resumo.confianca_media)
        self.assertIsNone(resumo.confianca_minima)
        self.assertIsNone(resumo.confianca_maxima)
        self.assertEqual(resumo.percentual_imagens_com_deteccao, 0.0)
        self.assertEqual(resumo.percentual_tiles_com_deteccao, 0.0)
        self.assertIsNone(resumo.nuvens_media_pct)

    def test_contrato_nao_declara_area(self) -> None:
        nomes = {campo.name.lower() for campo in fields(EstatisticasAnalise)}

        self.assertFalse(any("area" in nome or "hectare" in nome for nome in nomes))
