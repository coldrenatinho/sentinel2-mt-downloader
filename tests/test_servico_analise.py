import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_origin

from sentinel2_mt.analise.modelos import Deteccao, MetadadosModelo, ResultadoDeteccao
from sentinel2_mt.analise.servico import OpcoesAnalise, ServicoAnaliseAgricola
from sentinel2_mt.configuracao import ConfiguracaoProjeto


CONFIG = """
stac: {url: https://example.test/stac, colecao: S2}
area: {nome: Sinop, uf: MT, bbox: [-56.0, -13.0, -55.0, -12.0]}
periodo: {inicio: '2026-01-01', fim: '2026-03-31'}
bandas: [B02, B03, B04]
download: {pasta: data/sentinel2}
dataset:
  pasta: data/dataset
  catalogo: catalogo/patches.csv
analise:
  modelo: analise/models/agricultura.pt
  modelo_sha256: ''
  pasta: data/analises
  historico: data/historico.sqlite3
  gerar_relatorio: true
"""


class DetectorFake:
    sha256_modelo = "a" * 64
    _dispositivo_solicitado = "cpu"

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def detectar(self, imagem, **kwargs):
        return ResultadoDeteccao(
            entrada=str(imagem),
            sha256_entrada="b" * 64,
            largura=32,
            altura=32,
            deteccoes=(Deteccao("soja", 0.8, (1, 2, 10, 12), 0),),
            modelo=MetadadosModelo(
                nome="agricultura.pt", sha256=self.sha256_modelo,
                versao="0.1.0", dispositivo="cpu", classes={0: "soja"},
            ),
            versao="teste",
            tipo_entrada="tile",
            nuvens_pct=kwargs.get("nuvens_pct"),
        )

    def desenhar_overlay(self, imagem, _resultado):
        with Image.open(imagem) as aberta:
            return aberta.convert("RGB")


class HistoricoFake:
    registros = []

    def __init__(self, *_args) -> None:
        pass

    def salvar(self, registro):
        self.registros.append(registro)


class TestServicoAnaliseAgricola(TestCase):
    def test_analisa_patches_aprovados_preserva_multibanda_e_gera_artefatos(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            config_path = raiz / "config" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text(CONFIG, encoding="utf-8")
            config = ConfiguracaoProjeto.carregar(config_path, raiz=raiz)

            pasta_patch = raiz / "data/dataset/2026-02-01/CENA/PATCH_1"
            pasta_patch.mkdir(parents=True)
            rgb = pasta_patch / "rgb.png"
            Image.new("RGB", (32, 32), "green").save(rgb)
            multibanda = pasta_patch / "multiband.tif"
            with rasterio.open(
                multibanda, "w", driver="GTiff", width=32, height=32, count=3,
                dtype="uint16", crs="EPSG:4326", transform=from_origin(-55.8, -12.2, 0.01, 0.01),
                nodata=0,
            ) as destino:
                for indice, banda in enumerate(("B04", "B03", "B02"), start=1):
                    destino.write(np.full((32, 32), indice * 100, dtype=np.uint16), indice)
                    destino.set_band_description(indice, banda)
                mascara = np.full((32, 32), 255, dtype=np.uint8)
                mascara[0, 0] = 0
                destino.write_mask(mascara)
            with rasterio.open(multibanda) as fonte:
                contrato_antes = (
                    fonte.profile, fonte.bounds, fonte.descriptions,
                    tuple(fonte.checksum(i) for i in fonte.indexes), fonte.dataset_mask().tobytes(),
                )
            catalogo = raiz / "catalogo/patches.csv"
            catalogo.parent.mkdir()
            with catalogo.open("w", newline="", encoding="utf-8") as arquivo:
                escritor = csv.DictWriter(
                    arquivo,
                    fieldnames=(
                        "patch_id", "scene_id", "collection", "date", "bbox", "crs",
                        "bands", "rgb_png", "geotiff_path", "cloud_pct", "status",
                    ),
                )
                escritor.writeheader()
                escritor.writerow(
                    {
                        "patch_id": "PATCH_1", "scene_id": "CENA", "collection": "S2",
                        "date": "2026-02-01", "bbox": "[-55.8,-12.52,-55.48,-12.2]",
                        "crs": "EPSG:4326", "bands": "B02;B03;B04",
                        "rgb_png": rgb.relative_to(raiz).as_posix(), "cloud_pct": "8.5",
                        "geotiff_path": multibanda.relative_to(raiz).as_posix(),
                        "status": "APROVADO",
                    }
                )
                escritor.writerow(
                    {
                        "patch_id": "FORA", "scene_id": "OUTRA_REGIAO", "collection": "S2",
                        "date": "2026-02-01", "bbox": "[-48,-5,-47,-4]", "crs": "EPSG:4326",
                        "bands": "B02;B03;B04", "rgb_png": rgb.relative_to(raiz).as_posix(),
                        "geotiff_path": multibanda.relative_to(raiz).as_posix(), "cloud_pct": "1",
                        "status": "APROVADO",
                    }
                )
            HistoricoFake.registros.clear()
            servico = ServicoAnaliseAgricola(
                config,
                detector_factory=DetectorFake,
                historico_factory=HistoricoFake,
                saida=lambda _mensagem: None,
            )

            resultado = servico.executar(OpcoesAnalise(coletar=False))

            self.assertEqual(resultado.estatisticas.total_deteccoes, 1)
            self.assertEqual(resultado.estatisticas.por_classe, {"soja": 1})
            self.assertTrue(Path(resultado.imagem_analisada).is_file())
            self.assertTrue(Path(resultado.caminho_resultado).is_file())
            self.assertTrue(Path(resultado.caminho_relatorio).is_file())
            self.assertTrue(Path(resultado.caminho_relatorio).read_bytes().startswith(b"%PDF"))
            with rasterio.open(multibanda) as fonte:
                contrato_depois = (
                    fonte.profile, fonte.bounds, fonte.descriptions,
                    tuple(fonte.checksum(i) for i in fonte.indexes), fonte.dataset_mask().tobytes(),
                )
            self.assertEqual(contrato_depois, contrato_antes)
            self.assertEqual(HistoricoFake.registros[0]["status"], "concluida")
            self.assertNotIn("area", resultado.estatisticas.para_dict())

            repetido = servico.executar(OpcoesAnalise(coletar=False))
            self.assertEqual(repetido.analysis_id, resultado.analysis_id)

            entradas = servico._listar_entradas("2026-01-01", "2026-03-31")
            alterada = [dict(entradas[0], scene_id="CENA_COM_MESMO_RGB")]
            id_alterado = servico._analysis_id(
                alterada, DetectorFake(), "2026-01-01", "2026-03-31"
            )
            self.assertNotEqual(id_alterado, resultado.analysis_id)
