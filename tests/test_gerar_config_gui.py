import pathlib
from tempfile import TemporaryDirectory
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

from sentinel2_mt.config_builder import GeradorConfiguracao
from sentinel2_mt.gui_support import (
    LocalConfigStore,
    montar_argumentos_operacao,
    normalizar_bbox,
)


class TestGerarConfigGui(unittest.TestCase):
    def setUp(self):
        self.gerador = GeradorConfiguracao()

    def test_gerar_config_estrutura_core(self):
        dados = {
            "bbox": [-61.65, -18.05, -50.20, -7.30],
            "nome_regiao": "Mato Grosso",
            "uf": "MT",
            "colecao": "S2-16D-2",
            "stac_url": "https://data.inpe.br/bdc/stac/v1/",
            "inicio": "2025-09-01",
            "fim": "2026-04-30",
            "nuvem_max_pct": 20,
            "pasta_download": "data/sentinel2",
            "catalogo": "catalogo/catalogo_imagens.csv",
            "tamanho_max_px": 1600,
            "qualidade_jpeg": 92,
            "timeout_segundos": 120,
            "chunk_mb": 1,
            "max_itens_teste": 5,
            "max_candidatos_teste": 40,
        }

        config = self.gerador.gerar(dados)

        self.assertEqual(config["stac"]["colecao"], "S2-16D-2")
        self.assertEqual(config["area"]["bbox"], [-61.65, -18.05, -50.20, -7.30])
        self.assertEqual(config["periodo"]["inicio"], "2025-09-01")
        self.assertEqual(config["qualidade"]["nuvem_max_pct"], 20.0)
        self.assertEqual(config["download"]["pasta"], "data/sentinel2")
        self.assertEqual(config["sincronizacao"]["oauth_json"], "${GOOGLE_OAUTH_JSON:-}")
        self.assertEqual(config["sincronizacao"]["token_json"], "${GOOGLE_TOKEN_JSON:-config/google-token.json}")
        self.assertEqual(config["sincronizacao"]["pasta_id"], "${GOOGLE_PASTA_ID:-root}")
        self.assertEqual(config["sincronizacao"]["extensoes"], [".tif", ".tiff", ".jpg", ".jpeg"])
        self.assertEqual(config["dataset"]["patches"]["max_patches_por_cena"], 100000)
        self.assertEqual(config["analise"]["modelo"], "analise/models/best.pt")
        self.assertEqual(config["analise"]["confianca_minima"], 0.25)

    def test_salvar_config_cria_arquivo(self):
        dados = {"bbox": [-1, -2, 3, 4]}
        destino = self.gerador.salvar(ROOT / "tmp_config.yaml", dados)
        self.assertTrue(destino.exists())
        with destino.open("r", encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("stac:", texto)
        destino.unlink()

    def test_rejeita_bbox_invertida(self):
        with self.assertRaisesRegex(ValueError, "oeste < leste"):
            self.gerador.gerar({"bbox": [3, -2, -1, 4]})

    def test_bbox_para_yaml_normaliza_ordem(self):
        self.assertEqual(normalizar_bbox([3, 5, -1, 2]), [-1, 2, 3, 5])

    def test_bbox_rejeita_coordenadas_nao_finitas_ou_fora_do_globo(self):
        with self.assertRaisesRegex(ValueError, "finitas"):
            normalizar_bbox([float("nan"), -10, -50, -7])
        with self.assertRaisesRegex(ValueError, "Longitudes"):
            normalizar_bbox([-200, -10, -50, -7])
        with self.assertRaisesRegex(ValueError, "Latitudes"):
            normalizar_bbox([-60, -100, -50, -7])

    def test_local_config_store_persists_region(self):
        with TemporaryDirectory() as temporario:
            store = LocalConfigStore(pathlib.Path(temporario) / "perfis.db")
            dados = {
                "nome_regiao": "Região teste",
                "uf": "MT",
                "bbox": [-50, -10, -40, 0],
                "colecao": "S2-16D-2",
                "oauth_json": "/segredo/oauth.json",
                "token_json": "/segredo/token.json",
            }
            item_id = store.salvar(dados)
            item = store.carregar(item_id)

            self.assertIsNotNone(item)
            self.assertEqual(store.listar()[0]["nome_regiao"], "Região teste")
            self.assertNotIn("oauth_json", item["payload"])
            self.assertNotIn("token_json", item["payload"])

    def test_monta_argumentos_para_download(self):
        argumentos = montar_argumentos_operacao(
            "baixar",
            "config/config.yaml",
            inicio="2025-09-01",
            fim="2026-04-30",
            max_itens=8,
        )

        self.assertEqual(
            argumentos,
            [
                "--config",
                "config/config.yaml",
                "--baixar",
                "--inicio",
                "2025-09-01",
                "--fim",
                "2026-04-30",
                "--max-itens",
                "8",
            ],
        )

    def test_monta_argumentos_para_sincronizacao(self):
        argumentos = montar_argumentos_operacao(
            "sincronizar",
            "config/config.yaml",
            oauth_json="${GOOGLE_OAUTH_JSON:-}",
            tamanho_lote=25,
        )

        self.assertEqual(
            argumentos,
            ["--config", "config/config.yaml", "--sincronizar", "--lote", "25"],
        )

    def test_monta_argumentos_para_dataset_local(self):
        argumentos = montar_argumentos_operacao(
            "dataset",
            "config/config.yaml",
            max_itens=0,
            patch_size=256,
            patch_stride=128,
        )

        self.assertEqual(
            argumentos,
            [
                "--config",
                "config/config.yaml",
                "--gerar-dataset",
                "--max-itens",
                "0",
                "--patch-size",
                "256",
                "--patch-stride",
                "128",
            ],
        )

    def test_monta_argumentos_para_analise(self):
        argumentos = montar_argumentos_operacao(
            "analisar",
            "config/config.yaml",
            inicio="2026-01-01",
            fim="2026-03-31",
            max_itens=2,
            patch_size=512,
            patch_stride=512,
        )

        self.assertEqual(
            argumentos,
            [
                "--config",
                "config/config.yaml",
                "--analisar",
                "--inicio",
                "2026-01-01",
                "--fim",
                "2026-03-31",
                "--max-itens",
                "2",
                "--patch-size",
                "512",
                "--patch-stride",
                "512",
            ],
        )

    def test_local_config_store_agrupar_por_uf(self):
        with TemporaryDirectory() as temporario:
            store = LocalConfigStore(pathlib.Path(temporario) / "perfis_uf.db")
            store.salvar_configuracao(
                {
                    "nome_regiao": "MT Norte",
                    "uf": "MT",
                    "bbox": [-50, -10, -40, 0],
                    "colecao": "S2-16D-2",
                }
            )
            store.salvar_configuracao(
                {
                    "nome_regiao": "SP Centro",
                    "uf": "SP",
                    "bbox": [-47, -25, -45, -20],
                    "colecao": "S2-16D-2",
                }
            )
            grupos = store.listar_presets_por_uf()

            self.assertIn("MT", grupos)
            self.assertIn("SP", grupos)
            self.assertTrue(
                any(perfil["nome_regiao"] == "MT Norte" for perfil in grupos["MT"])
            )


if __name__ == "__main__":
    unittest.main()
