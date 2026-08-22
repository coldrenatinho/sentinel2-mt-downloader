from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import tui


class TestTUIAnalise(TestCase):
    def test_monta_comando_analise_uma_unica_vez(self) -> None:
        with TemporaryDirectory() as temporario:
            config = Path(temporario) / "config.yaml"
            config.write_text("teste", encoding="utf-8")
            valores = {
                "#operacao": "analisar",
                "#config": str(config),
                "#inicio": "2026-01-01",
                "#fim": "2026-03-31",
                "#max_itens": "2",
                "#patch_size": 512,
                "#patch_stride": "512",
                "#oauth_json": "",
                "#lote": "",
            }
            app = tui.SentinelTUI()

            with patch.object(
                app,
                "query_one",
                side_effect=lambda seletor, _tipo: SimpleNamespace(value=valores[seletor]),
            ):
                comando = app.montar_comando()

        self.assertEqual(comando.count("--analisar"), 1)
        self.assertIn("--patch-size", comando)
        self.assertIn("--patch-stride", comando)
