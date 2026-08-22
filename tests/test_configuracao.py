from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from sentinel2_mt.configuracao import ConfiguracaoProjeto


CONFIG_MINIMA = """
stac:
  url: https://exemplo.test/stac
  colecao: S2
area:
  nome: Mato Grosso
  uf: MT
  bbox: [-61.0, -18.0, -50.0, -7.0]
periodo:
  inicio: '2025-01-01'
  fim: '2025-12-31'
bandas: [B02, B03, B04]
download:
  pasta: data/imagens
"""


class TestConfiguracaoProjeto(TestCase):
    def test_carrega_defaults_e_resolve_caminho(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            arquivo = raiz / "config.yaml"
            arquivo.write_text(CONFIG_MINIMA, encoding="utf-8")

            config = ConfiguracaoProjeto.carregar(arquivo, raiz=raiz)

            self.assertEqual(config.area.uf, "MT")
            self.assertEqual(config.download.timeout_segundos, 120)
            self.assertEqual(config.sincronizacao.tamanho_lote, 100)
            self.assertFalse(config.dataset.gerar)
            self.assertEqual(config.preview.metodo, "percentile")
            self.assertEqual(config.dataset.patches.tamanho_px, 512)
            self.assertEqual(config.dataset.patches.max_patches_por_cena, 100_000)
            self.assertEqual(config.analise.modelo, "analise/models/agricultura.pt")
            self.assertEqual(config.analise.tamanho_inferencia_px, 640)
            self.assertEqual(config.analise.max_imagens, 1000)
            self.assertEqual(config.caminho(config.download.pasta), raiz / "data/imagens")

    def test_rejeita_bbox_incompleto(self) -> None:
        with TemporaryDirectory() as temporario:
            arquivo = Path(temporario) / "config.yaml"
            arquivo.write_text(CONFIG_MINIMA.replace("[-61.0, -18.0, -50.0, -7.0]", "[-61.0, -18.0]"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "quatro coordenadas"):
                ConfiguracaoProjeto.carregar(arquivo)

    def test_rejeita_bbox_invertido_e_periodo_invalido(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            arquivo = raiz / "config.yaml"
            arquivo.write_text(
                CONFIG_MINIMA.replace(
                    "[-61.0, -18.0, -50.0, -7.0]", "[-50.0, -18.0, -61.0, -7.0]"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "oeste < leste"):
                ConfiguracaoProjeto.carregar(arquivo, raiz=raiz)

            arquivo.write_text(
                CONFIG_MINIMA.replace("'2025-01-01'", "'2026-01-01'"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "posterior"):
                ConfiguracaoProjeto.carregar(arquivo, raiz=raiz)

    def test_expande_variavel_do_dotenv(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            pasta_config = raiz / "config"
            pasta_config.mkdir()
            arquivo = pasta_config / "config.yaml"
            arquivo.write_text(
                CONFIG_MINIMA + "\nsincronizacao:\n  oauth_json: '${GOOGLE_OAUTH_JSON:-config/padrao.json}'\n",
                encoding="utf-8",
            )
            (pasta_config / ".env").write_text("GOOGLE_OAUTH_JSON=config/cliente.json\n", encoding="utf-8")

            config = ConfiguracaoProjeto.carregar(arquivo, raiz=raiz)

            self.assertEqual(config.sincronizacao.oauth_json, "config/cliente.json")

    def test_carrega_nova_configuracao_dataset(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            arquivo = raiz / "config.yaml"
            arquivo.write_text(
                CONFIG_MINIMA
                + """
preview:
  metodo: fixed
  minimo: 0
  maximo: 2000
dataset:
  gerar: true
  rgb:
    metodo: percentile
  patches:
    tamanho_px: 256
    stride_px: 128
    nuvem_max_pct: 8
    dados_validos_min_pct: 95
""",
                encoding="utf-8",
            )

            config = ConfiguracaoProjeto.carregar(arquivo, raiz=raiz)

            self.assertTrue(config.dataset.gerar)
            self.assertEqual(config.dataset.patches.tamanho_px, 256)
            self.assertEqual(config.dataset.patches.stride_px, 128)
            self.assertEqual(config.dataset.rgb.metodo, "percentile")
            self.assertEqual(config.preview.metodo, "fixed")

    def test_carrega_e_valida_configuracao_analise(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            arquivo = raiz / "config.yaml"
            arquivo.write_text(
                CONFIG_MINIMA
                + """
analise:
  modelo: analise/models/agricultura.pt
  modelo_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  confianca_minima: 0.4
  iou_maximo: 0.5
  tamanho_inferencia_px: 768
  max_imagens: 12
""",
                encoding="utf-8",
            )

            config = ConfiguracaoProjeto.carregar(arquivo, raiz=raiz)

            self.assertEqual(config.analise.confianca_minima, 0.4)
            self.assertEqual(config.analise.tamanho_inferencia_px, 768)
            self.assertEqual(config.analise.max_imagens, 12)
