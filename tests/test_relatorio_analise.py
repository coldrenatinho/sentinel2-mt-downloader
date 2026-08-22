import importlib.util
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from sentinel2_mt.analise.relatorio import GeradorRelatorioAnalise, LIMITACAO_AREA


MATPLOTLIB_DISPONIVEL = importlib.util.find_spec("matplotlib") is not None


class TestRelatorioAnalise(TestCase):
    @skipUnless(MATPLOTLIB_DISPONIVEL, "matplotlib não está instalado")
    def test_gera_pdf_atomico_com_permissao_restritiva(self) -> None:
        with TemporaryDirectory() as temporario:
            destino = Path(temporario) / "relatorios" / "analise.pdf"
            analise = {
                "analysis_id": "analise-001",
                "regiao": "Sinop",
                "bbox": [-56, -13, -55, -12],
                "periodo_inicio": "2025-01-01",
                "periodo_fim": "2025-01-31",
                "scene_id": "S2_TESTE",
                "fonte": "Sentinel-2 / INPE",
                "resumo": {"caixas": 4, "classe": "talhão"},
                "modelo_versao": "1.0",
                "modelo_hash": "sha256:abc",
                "metodologia": "Detecção por caixas delimitadoras.",
            }

            resultado = GeradorRelatorioAnalise().gerar(destino, analise)

            self.assertEqual(resultado, destino)
            self.assertTrue(destino.read_bytes().startswith(b"%PDF"))
            self.assertEqual(stat.S_IMODE(destino.stat().st_mode), 0o600)
            self.assertFalse(list(destino.parent.glob(".*.tmp")))

    @skipUnless(MATPLOTLIB_DISPONIVEL, "matplotlib não está instalado")
    def test_aceita_objeto_por_duck_typing_e_imagem_opcional(self) -> None:
        from matplotlib import pyplot as plt

        class AnaliseFake:
            analysis_id = "duck-typing"
            region = "Cuiabá"
            summary = {"caixas": 1}
            model_version = "teste"
            model_hash = "hash"

        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            imagem = raiz / "preview.png"
            plt.imsave(imagem, [[[0.2, 0.4, 0.6]]])
            destino = raiz / "relatorio.pdf"

            GeradorRelatorioAnalise().gerar(
                destino,
                AnaliseFake(),
                imagens=[{"path": imagem, "titulo": "Preview RGB"}],
            )

            self.assertGreater(destino.stat().st_size, 1_000)

    def test_limite_nao_afirma_area_em_hectares(self) -> None:
        self.assertIn("não pode ser convertida nem apresentada como hectares", LIMITACAO_AREA)
