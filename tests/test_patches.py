from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID
from unittest import TestCase

import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window, transform as window_transform

from sentinel2_mt.catalogo import RepositorioCatalogoPatchesCSV
from sentinel2_mt.configuracao import (
    ConfiguracaoDataset,
    ConfiguracaoPatches,
    ConfiguracaoRGBDataset,
)
from sentinel2_mt.patches import GeradorDataset
from sentinel2_mt.imagens import ProcessadorImagem


CRS = "EPSG:31981"
TRANSFORM = from_origin(500000, 1000000, 10, 10)


def criar_raster(
    caminho: Path,
    dados: np.ndarray,
    *,
    transform=TRANSFORM,
    crs: str = CRS,
    nodata: int = 0,
) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        caminho,
        "w",
        driver="GTiff",
        width=dados.shape[1],
        height=dados.shape[0],
        count=1,
        dtype=dados.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as raster:
        raster.write(dados, 1)
    return caminho


def cena_sintetica(raiz: Path, tamanho: int, scl: np.ndarray | None = None) -> tuple[Path, dict, dict]:
    cena = raiz / "data/sentinel2/2025-10-01/S2_TESTE"
    arquivos = {
        "B02": criar_raster(cena / "B02.tif", np.full((tamanho, tamanho), 500, dtype=np.uint16)),
        "B03": criar_raster(cena / "B03.tif", np.full((tamanho, tamanho), 1000, dtype=np.uint16)),
        "B04": criar_raster(cena / "B04.tif", np.full((tamanho, tamanho), 1500, dtype=np.uint16)),
        "B08": criar_raster(cena / "B08.tif", np.full((tamanho, tamanho), 1800, dtype=np.uint16)),
    }
    scl_dados = scl if scl is not None else np.full((tamanho, tamanho), 4, dtype=np.uint8)
    auxiliares = {"SCL": criar_raster(cena / "qualidade/SCL.tif", scl_dados)}
    return cena, arquivos, auxiliares


class TestGeradorDataset(TestCase):
    def _gerar(self, raiz: Path, tamanho_raster: int, tamanho_patch: int, **patch_kwargs):
        cena, arquivos, auxiliares = cena_sintetica(raiz, tamanho_raster)
        patches = ConfiguracaoPatches(
            tamanho_px=tamanho_patch,
            stride_px=tamanho_patch,
            **patch_kwargs,
        )
        config = ConfiguracaoDataset(
            gerar=True,
            pasta="data/dataset",
            rgb=ConfiguracaoRGBDataset(),
            patches=patches,
        )
        return GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
            scene_id="S2_TESTE",
            collection="S2-16D-2",
            date="2025-10-01",
            source_scene=cena,
            arquivos=arquivos,
            auxiliares=auxiliares,
            bandas_desejadas=("B02", "B03", "B04", "B08", "EVI"),
        )

    def test_raster_1024_produz_quatro_patches_512(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)

            registros, resumo = self._gerar(raiz, 1024, 512)

            self.assertEqual(resumo.candidatos, 4)
            self.assertEqual(resumo.aprovados, 4)
            self.assertEqual(len(registros), 4)
            self.assertTrue(all(registro.status == "APROVADO" for registro in registros))

    def test_tamanho_256_e_georreferenciamento(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)

            registros, resumo = self._gerar(raiz, 512, 256)

            self.assertEqual(resumo.aprovados, 4)
            registro = next(item for item in registros if "x000256_y000000" in item.patch_id)
            geotiff = raiz / registro.geotiff_path
            with rasterio.open(geotiff) as raster:
                self.assertEqual((raster.width, raster.height), (256, 256))
                self.assertEqual(raster.crs.to_string(), CRS)
                self.assertTrue(
                    raster.transform.almost_equals(window_transform(Window(256, 0, 256, 256), TRANSFORM))
                )
                self.assertEqual(raster.bounds, rasterio.windows.bounds(Window(256, 0, 256, 256), TRANSFORM))
                self.assertEqual(raster.dtypes, ("uint16",) * 4)
                self.assertEqual(raster.descriptions, ("B02", "B03", "B04", "B08"))

    def test_pipeline_funcional_gera_png_geotiff_metadata_e_catalogo(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)

            registros, resumo = self._gerar(raiz, 256, 256)
            registro = registros[0]
            catalogo = raiz / "catalogo/patches.csv"
            RepositorioCatalogoPatchesCSV().salvar(catalogo, registros)

            self.assertEqual(resumo.aprovados, 1)
            rgb_path = raiz / registro.rgb_png
            UUID(rgb_path.stem)
            self.assertNotEqual(rgb_path.name, "rgb.png")
            with Image.open(rgb_path) as imagem:
                array = np.asarray(imagem)
                self.assertEqual(imagem.format, "PNG")
                self.assertEqual(array.shape, (256, 256, 3))
                self.assertEqual(array.dtype, np.uint8)
            metadata_path = rgb_path.parent / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["patch_id"], registro.patch_id)
            self.assertEqual(metadata["crs"], CRS)
            self.assertEqual(metadata["resampling"]["categorical_masks"], "nearest")
            self.assertEqual(metadata["native_resolution_m"]["B02"], 10)
            with catalogo.open(encoding="utf-8-sig") as arquivo:
                linha = next(csv.DictReader(arquivo))
            self.assertEqual(linha["status"], "APROVADO")
            self.assertEqual(linha["missing_bands"], "EVI")

    def test_rejeita_patch_acima_do_limite_de_nuvem(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            scl = np.full((256, 256), 9, dtype=np.uint8)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256, scl)
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256, nuvem_max_pct=10),
            )

            registros, resumo = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )

            self.assertEqual(resumo.descartados_nuvem, 1)
            self.assertEqual(registros[0].status, "REJEITADO_NUVEM")
            self.assertEqual(registros[0].cloud_pct, "100.00")
            self.assertEqual(registros[0].geotiff_path, "")

    def test_rejeita_patch_com_nodata_excessivo(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            dados = np.full((256, 256), 500, dtype=np.uint16)
            dados[:, :128] = 0
            arquivos["B02"] = criar_raster(cena / "B02.tif", dados)
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(
                    tamanho_px=256,
                    stride_px=256,
                    dados_validos_min_pct=90,
                ),
            )

            registros, resumo = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )

            self.assertEqual(resumo.descartados_nodata, 1)
            self.assertEqual(registros[0].status, "REJEITADO_NODATA")
            self.assertEqual(registros[0].valid_pixel_pct, "50.00")

    def test_asset_opcional_ausente_nao_interrompe(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)

            registros, resumo = self._gerar(raiz, 256, 256)

            self.assertEqual(resumo.erros, 0)
            self.assertEqual(resumo.aprovados, 1)
            self.assertEqual(registros[0].missing_bands, "EVI")

    def test_alinha_banda_20m_na_grade_sem_alterar_resolucao_nativa_declarada(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            arquivos["B05"] = criar_raster(
                cena / "B05.tif",
                np.full((128, 128), 2000, dtype=np.uint16),
                transform=from_origin(500000, 1000000, 20, 20),
            )
            auxiliares["SCL"] = criar_raster(
                cena / "qualidade/SCL.tif",
                np.full((128, 128), 4, dtype=np.uint8),
                transform=from_origin(500000, 1000000, 20, 20),
            )
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256),
            )

            registros, resumo = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2_L2A-1",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )

            self.assertEqual(resumo.aprovados, 1)
            with rasterio.open(raiz / registros[0].geotiff_path) as raster:
                indice = raster.descriptions.index("B05") + 1
                self.assertEqual(raster.shape, (256, 256))
                self.assertEqual(raster.res, (10.0, 10.0))
                self.assertEqual(raster.tags(indice)["NATIVE_RESOLUTION_M"], "20")

    def test_asset_opcional_sem_crs_e_ignorado_sem_perder_a_cena(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            arquivos["EVI"] = criar_raster(
                cena / "EVI.tif",
                np.full((256, 256), 1, dtype=np.uint16),
                crs=None,
            )
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256),
            )

            registros, resumo = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
                bandas_desejadas=("B02", "B03", "B04", "B08", "EVI"),
            )

            self.assertEqual(resumo.aprovados, 1)
            self.assertEqual(resumo.erros, 0)
            self.assertEqual(registros[0].missing_bands, "EVI")

    def test_cobertura_parcial_sem_nodata_nao_e_contada_como_valida(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            arquivos["EVI"] = criar_raster(
                cena / "EVI.tif",
                np.ones((256, 128), dtype=np.uint16),
                nodata=None,
            )
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(
                    tamanho_px=256,
                    stride_px=256,
                    dados_validos_min_pct=90,
                ),
            )

            registros, resumo = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
                bandas_desejadas=("B02", "B03", "B04", "B08", "EVI"),
            )

            self.assertEqual(resumo.descartados_nodata, 1)
            self.assertEqual(registros[0].status, "REJEITADO_NODATA")
            self.assertEqual(registros[0].valid_pixel_pct, "50.00")

    def test_regeneracao_rejeitada_remove_produtos_aprovados_antigos(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256),
            )
            gerador = GeradorDataset(config, raiz, saida=lambda _: None)
            aprovados, _ = gerador.gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )
            pasta_patch = (raiz / aprovados[0].geotiff_path).parent
            self.assertTrue((pasta_patch / "multiband.tif").is_file())
            auxiliares["SCL"] = criar_raster(
                cena / "qualidade/SCL.tif", np.full((256, 256), 9, dtype=np.uint8)
            )

            rejeitados, resumo = gerador.gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )

            self.assertEqual(resumo.descartados_nuvem, 1)
            self.assertEqual(rejeitados[0].status, "REJEITADO_NUVEM")
            self.assertFalse((pasta_patch / "multiband.tif").exists())
            self.assertFalse(list(pasta_patch.glob("*.png")))
            self.assertFalse((pasta_patch / "metadata.json").exists())

    def test_ordem_dos_canais_segue_configuracao_e_nao_filesystem(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            fora_de_ordem = {
                "B08": arquivos["B08"],
                "B02": arquivos["B02"],
                "B04": arquivos["B04"],
                "B03": arquivos["B03"],
            }
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256),
            )

            registros, _ = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=fora_de_ordem,
                auxiliares=auxiliares,
                bandas_desejadas=("B02", "B03", "B04", "B08"),
            )

            with rasterio.open(raiz / registros[0].geotiff_path) as raster:
                self.assertEqual(raster.descriptions, ("B02", "B03", "B04", "B08"))

    def test_patch_id_distingue_data_colecao_e_aliases_sanitizados(self) -> None:
        base = GeradorDataset.patch_id(
            "cena/a", 0, 0, 256, collection="S2-16D-2", date="2025-10-01"
        )
        outra_data = GeradorDataset.patch_id(
            "cena/a", 0, 0, 256, collection="S2-16D-2", date="2025-10-02"
        )
        outro_alias = GeradorDataset.patch_id(
            "cena?a", 0, 0, 256, collection="S2-16D-2", date="2025-10-01"
        )

        self.assertNotEqual(base, outra_data)
        self.assertNotEqual(base, outro_alias)
        self.assertNotIn("/", base)

    def test_patch_id_distingue_grade_crs_e_bandas(self) -> None:
        parametros = {
            "collection": "S2-16D-2",
            "date": "2025-10-01",
            "transformacao": TRANSFORM,
            "crs": CRS,
            "bandas": ("B02", "B03"),
        }
        base = GeradorDataset.patch_id("cena", 0, 0, 256, **parametros)
        outra_grade = GeradorDataset.patch_id(
            "cena",
            0,
            0,
            256,
            **{**parametros, "transformacao": from_origin(500010, 1000000, 10, 10)},
        )
        outro_crs = GeradorDataset.patch_id(
            "cena", 0, 0, 256, **{**parametros, "crs": "EPSG:4326"}
        )
        outras_bandas = GeradorDataset.patch_id(
            "cena", 0, 0, 256, **{**parametros, "bandas": ("B02", "B04")}
        )

        self.assertEqual(len({base, outra_grade, outro_crs, outras_bandas}), 4)

    def test_nova_receita_remove_produtos_da_receita_obsoleta(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256),
            )
            gerador = GeradorDataset(config, raiz, saida=lambda _: None)
            antigos, _ = gerador.gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )
            pasta_antiga = (raiz / antigos[0].geotiff_path).parent
            produto_outra_cena = (
                raiz / "data/dataset/2025-10-01/OUTRA_CENA/patch_antigo/multiband.tif"
            )
            produto_outra_cena.parent.mkdir(parents=True)
            produto_outra_cena.touch()

            novos, _ = gerador.gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos={nome: caminho for nome, caminho in arquivos.items() if nome != "B08"},
                auxiliares=auxiliares,
            )

            self.assertNotEqual(antigos[0].patch_id, novos[0].patch_id)
            self.assertFalse(pasta_antiga.exists())
            self.assertTrue((raiz / novos[0].geotiff_path).is_file())
            self.assertTrue(produto_outra_cena.is_file())

    def test_manifest_nao_publica_caminho_scl_descartavel(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256),
            )

            registros, _ = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
                manter_scl=False,
            )

            registro = registros[0]
            metadata = json.loads(
                ((raiz / registro.geotiff_path).parent / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(registro.scl_path, "")
            self.assertNotIn("SCL", metadata["source_assets"]["quality"])
            self.assertIn("SCL", metadata["quality_processing"]["used_layers"])
            self.assertEqual(
                metadata["quality_processing"]["non_persistent_layers"], ["SCL"]
            )

    def test_limite_preventivo_rejeita_stride_excessivamente_denso(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 512)
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(
                    tamanho_px=256,
                    stride_px=1,
                    max_patches_por_cena=100,
                ),
            )

            with self.assertRaisesRegex(ValueError, "limite: 100"):
                GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                    scene_id="S2_TESTE",
                    collection="S2-16D-2",
                    date="2025-10-01",
                    source_scene=cena,
                    arquivos=arquivos,
                    auxiliares=auxiliares,
                )

    def test_falha_na_regeneracao_preserva_produtos_aprovados(self) -> None:
        class ProcessadorComFalha(ProcessadorImagem):
            def gerar_rgb_array(self, *args, **kwargs):
                raise RuntimeError("falha controlada")

        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            cena, arquivos, auxiliares = cena_sintetica(raiz, 256)
            config = ConfiguracaoDataset(
                gerar=True,
                patches=ConfiguracaoPatches(tamanho_px=256, stride_px=256),
            )
            registros, _ = GeradorDataset(config, raiz, saida=lambda _: None).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )
            pasta = (raiz / registros[0].geotiff_path).parent
            geotiff_antes = (pasta / "multiband.tif").read_bytes()
            rgb_antes_path = next(pasta.glob("*.png"))
            rgb_antes = rgb_antes_path.read_bytes()

            falhos, resumo = GeradorDataset(
                config,
                raiz,
                processador=ProcessadorComFalha(),
                saida=lambda _: None,
            ).gerar_cena(
                scene_id="S2_TESTE",
                collection="S2-16D-2",
                date="2025-10-01",
                source_scene=cena,
                arquivos=arquivos,
                auxiliares=auxiliares,
            )

            self.assertEqual(resumo.erros, 1)
            self.assertEqual(falhos[0].status, "ERRO")
            self.assertEqual((pasta / "multiband.tif").read_bytes(), geotiff_antes)
            self.assertEqual(rgb_antes_path.read_bytes(), rgb_antes)
