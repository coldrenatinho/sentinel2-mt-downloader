from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from sentinel2_mt.cli import AplicacaoCLI


class TestCLIAnalise(TestCase):
    @patch("sentinel2_mt.cli.ServicoAnaliseAgricola")
    @patch("sentinel2_mt.cli.ConfiguracaoProjeto.carregar")
    def test_analisar_reutiliza_caso_de_uso_e_repassa_opcoes(self, carregar, servico) -> None:
        config = SimpleNamespace(raiz=Path("/projeto"))
        carregar.return_value = config
        servico.return_value.executar.return_value = SimpleNamespace(
            caminho_resultado="/projeto/data/analises/a1/resultado.json"
        )

        codigo = AplicacaoCLI().executar(
            [
                "--config", "config.yaml", "--analisar", "--inicio", "2026-01-01",
                "--fim", "2026-03-31", "--max-itens", "2", "--patch-size", "512",
                "--patch-stride", "512",
            ]
        )

        self.assertEqual(codigo, 0)
        opcoes = servico.return_value.executar.call_args.args[0]
        self.assertEqual(opcoes.inicio, "2026-01-01")
        self.assertEqual(opcoes.max_itens, 2)
        self.assertEqual(opcoes.patch_size, 512)

    @patch("sentinel2_mt.cli.ConfiguracaoProjeto.carregar")
    def test_rejeita_analise_e_sincronizacao_simultaneas(self, carregar) -> None:
        carregar.return_value = SimpleNamespace(raiz=Path("/projeto"))
        codigo = AplicacaoCLI().executar(
            ["--config", "config.yaml", "--analisar", "--sincronizar"]
        )
        self.assertEqual(codigo, 1)
