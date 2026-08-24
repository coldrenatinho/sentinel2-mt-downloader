from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable
import uuid

import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, transform as window_transform

from .configuracao import ConfiguracaoDataset
from .caminhos import caminho_contido, componente_seguro
from .imagens import ProcessadorImagem
from .modelos import RegistroPatch, ResumoDataset


RESOLUCAO_NATIVA_METROS = {
    "B02": 10,
    "B03": 10,
    "B04": 10,
    "B08": 10,
    "B05": 20,
    "B06": 20,
    "B07": 20,
    "B8A": 20,
    "B11": 20,
    "B12": 20,
}


class GeradorDataset:
    BANDAS_REFERENCIA = ("B02", "B03", "B04", "B08", "B05", "B8A")

    def __init__(
        self,
        config: ConfiguracaoDataset,
        raiz: Path,
        processador: ProcessadorImagem | None = None,
        saida: Callable[[str], None] = print,
    ) -> None:
        self.config = config
        self.raiz = raiz
        self.processador = processador or ProcessadorImagem()
        self.saida = saida

    def gerar_cena(
        self,
        *,
        scene_id: str,
        collection: str,
        date: str,
        source_scene: Path,
        arquivos: dict[str, Path],
        auxiliares: dict[str, Path] | None = None,
        bandas_desejadas: tuple[str, ...] | list[str] | None = None,
        manter_scl: bool = True,
    ) -> tuple[list[RegistroPatch], ResumoDataset]:
        auxiliares = auxiliares or {}
        desejadas = tuple(bandas_desejadas or arquivos.keys())
        registros: list[RegistroPatch] = []
        resumo = ResumoDataset()
        self.saida(f"[DATASET] Cena: {scene_id}")

        with ExitStack() as pilha:
            origens = self._abrir_rasters(pilha, arquivos)
            if not origens:
                raise ValueError(f"Cena {scene_id} não possui GeoTIFF científico legível")
            ordem = [nome for nome in desejadas if nome in origens]
            ordem.extend(sorted(nome for nome in origens if nome not in ordem))
            origens = {nome: origens[nome] for nome in ordem}
            nome_referencia = self._escolher_referencia(origens)
            referencia = origens[nome_referencia]

            patches = self.config.patches
            colunas = (referencia.width + patches.stride_px - 1) // patches.stride_px
            linhas = (referencia.height + patches.stride_px - 1) // patches.stride_px
            total_candidatos = colunas * linhas
            if total_candidatos > patches.max_patches_por_cena:
                raise ValueError(
                    f"Configuração produziria {total_candidatos} patches na cena; "
                    f"limite: {patches.max_patches_por_cena}"
                )

            alinhados = {}
            for nome, origem in origens.items():
                try:
                    alinhados[nome] = self._alinhar(
                        pilha, origem, referencia, Resampling.bilinear
                    )
                except (ValueError, rasterio.errors.RasterioError) as exc:
                    self.saida(f"[DATASET] Asset {nome} não pôde ser alinhado e foi ignorado: {exc}")
            scl = self._abrir_scl(pilha, auxiliares.get("SCL"), referencia)
            ausentes = [banda for banda in desejadas if banda not in alinhados]

            numero = 0
            for y in range(0, referencia.height, patches.stride_px):
                for x in range(0, referencia.width, patches.stride_px):
                    numero += 1
                    resumo.candidatos += 1
                    janela = Window(x, y, patches.tamanho_px, patches.tamanho_px)
                    transformacao = window_transform(janela, referencia.transform)
                    arrays = {
                        nome: self._ler_janela(origem, x, y, patches.tamanho_px)
                        for nome, origem in alinhados.items()
                    }
                    mascaras = {
                        nome: ~np.ma.getmaskarray(array) & np.isfinite(np.asarray(array.data))
                        for nome, array in arrays.items()
                    }
                    mascara_valida = np.logical_and.reduce(tuple(mascaras.values()))
                    valid_pct = float(mascara_valida.sum() * 100.0 / mascara_valida.size)

                    cloud_pct: float | None = None
                    if scl is not None:
                        scl_array = self._ler_janela(scl, x, y, patches.tamanho_px)
                        scl_valida = ~np.ma.getmaskarray(scl_array)
                        cloud_pct = self.processador.percentual_nuvem_scl(
                            np.asarray(scl_array.filled(0)), scl_valida
                        )

                    patch_id = self.patch_id(
                        scene_id,
                        x,
                        y,
                        patches.tamanho_px,
                        collection=collection,
                        date=date,
                        transformacao=transformacao,
                        crs=referencia.crs,
                        bandas=tuple(alinhados),
                    )
                    base = self._registro_base(
                        patch_id=patch_id,
                        scene_id=scene_id,
                        collection=collection,
                        date=date,
                        source_scene=source_scene,
                        transformacao=transformacao,
                        crs=referencia.crs,
                        cloud_pct=cloud_pct,
                        valid_pct=valid_pct,
                        bandas=tuple(alinhados),
                        ausentes=ausentes,
                        auxiliares=auxiliares,
                        manter_scl=manter_scl,
                    )
                    if cloud_pct is not None and cloud_pct > patches.nuvem_max_pct:
                        self._limpar_produtos_patch(base)
                        resumo.descartados_nuvem += 1
                        base.status = "REJEITADO_NUVEM"
                        registros.append(base)
                        self.saida(
                            f"[PATCH] {numero:03d} | cloud={cloud_pct:.2f}% | "
                            "REJEITADO_NUVEM"
                        )
                        continue
                    if valid_pct < patches.dados_validos_min_pct:
                        self._limpar_produtos_patch(base)
                        resumo.descartados_nodata += 1
                        base.status = "REJEITADO_NODATA"
                        registros.append(base)
                        self.saida(
                            f"[PATCH] {numero:03d} | valid={valid_pct:.2f}% | "
                            "REJEITADO_NODATA"
                        )
                        continue

                    try:
                        self._gravar_patch(
                            registro=base,
                            arrays=arrays,
                            mascaras=mascaras,
                            mascara_valida=mascara_valida,
                            nodatas={nome: origem.nodata for nome, origem in alinhados.items()},
                            transformacao=transformacao,
                            crs=referencia.crs,
                            source_scene=source_scene,
                            auxiliares=auxiliares,
                            fontes=arquivos,
                            manter_scl=manter_scl,
                        )
                        resumo.aprovados += 1
                        base.status = "APROVADO" if scl is not None else "APROVADO_SEM_SCL"
                        self.saida(
                            f"[PATCH] {numero:03d} | cloud="
                            f"{self._pct_log(cloud_pct)} | valid={valid_pct:.2f}% | APROVADO"
                        )
                    except Exception as exc:
                        resumo.erros += 1
                        base.status = "ERRO"
                        base.erro = str(exc)
                        self.saida(f"[PATCH] {numero:03d} | ERRO | {exc}")
                    registros.append(base)

        self._limpar_produtos_obsoletos_cena(date, scene_id, registros)
        self._imprimir_resumo(resumo)
        return registros, resumo

    def _abrir_rasters(self, pilha: ExitStack, arquivos: dict[str, Path]) -> dict[str, object]:
        origens = {}
        for nome, caminho in arquivos.items():
            if not caminho.is_file():
                continue
            try:
                origens[nome] = pilha.enter_context(rasterio.open(caminho))
            except rasterio.errors.RasterioIOError as exc:
                self.saida(f"[DATASET] Asset {nome} ignorado: {exc}")
        return origens

    def _abrir_scl(self, pilha: ExitStack, caminho: Path | None, referencia):
        if caminho is None or not caminho.is_file():
            return None
        try:
            origem = pilha.enter_context(rasterio.open(caminho))
            return self._alinhar(pilha, origem, referencia, Resampling.nearest)
        except (ValueError, rasterio.errors.RasterioError) as exc:
            self.saida(f"[DATASET] SCL ignorado: {exc}")
            return None

    @classmethod
    def _escolher_referencia(cls, origens: dict[str, object]) -> str:
        ordem = (*cls.BANDAS_REFERENCIA, *origens)
        referencia = next(
            (nome for nome in ordem if nome in origens and origens[nome].crs is not None),
            None,
        )
        if referencia is None:
            raise ValueError("Nenhum raster científico possui CRS para servir de referência")
        return referencia

    @staticmethod
    def _alinhado(origem, referencia) -> bool:
        return (
            origem.crs == referencia.crs
            and origem.width == referencia.width
            and origem.height == referencia.height
            and origem.transform.almost_equals(referencia.transform)
        )

    def _alinhar(self, pilha: ExitStack, origem, referencia, resampling: Resampling):
        if self._alinhado(origem, referencia):
            return origem
        if origem.crs is None:
            raise ValueError(f"Asset {origem.name} não possui CRS")
        return pilha.enter_context(
            WarpedVRT(
                origem,
                crs=referencia.crs,
                transform=referencia.transform,
                width=referencia.width,
                height=referencia.height,
                resampling=resampling,
                src_nodata=origem.nodata,
                nodata=origem.nodata,
                add_alpha=origem.nodata is None,
            )
        )

    @staticmethod
    def _ler_janela(origem, x: int, y: int, tamanho: int) -> np.ma.MaskedArray:
        largura = max(0, min(tamanho, origem.width - x))
        altura = max(0, min(tamanho, origem.height - y))
        saida = np.ma.masked_all((tamanho, tamanho), dtype=origem.dtypes[0])
        if largura == 0 or altura == 0:
            return saida
        dados = origem.read(1, window=Window(x, y, largura, altura), masked=True)
        saida[:altura, :largura] = dados
        return saida

    def _gravar_patch(
        self,
        *,
        registro: RegistroPatch,
        arrays: dict[str, np.ma.MaskedArray],
        mascaras: dict[str, np.ndarray],
        mascara_valida: np.ndarray,
        nodatas: dict[str, float | int | None],
        transformacao,
        crs,
        source_scene: Path,
        auxiliares: dict[str, Path],
        fontes: dict[str, Path],
        manter_scl: bool,
    ) -> None:
        pasta = self._pasta_patch(registro)
        pasta.parent.mkdir(parents=True, exist_ok=True)
        gerados: set[str] = set()
        rgb_gerado: str | None = None

        with TemporaryDirectory(prefix=f".{registro.patch_id}.", dir=pasta.parent) as temporario:
            pasta_temporaria = Path(temporario)

            if self.config.gerar_geotiff_multibanda:
                geotiff = pasta_temporaria / "multiband.tif"
                self._gravar_geotiff(
                    geotiff,
                    arrays,
                    mascara_valida,
                    nodatas,
                    transformacao,
                    crs,
                    registro.patch_id,
                    registro.scene_id,
                    self._relativo(source_scene),
                    registro.collection,
                )
                gerados.add("multiband.tif")
                if (pasta_temporaria / "multiband.tif.msk").is_file():
                    gerados.add("multiband.tif.msk")

            if self.config.rgb.gerar_png and all(
                nome in arrays for nome in ("B04", "B03", "B02")
            ):
                rgb = self.processador.gerar_rgb_array(
                    (
                        arrays["B04"].data,
                        arrays["B03"].data,
                        arrays["B02"].data,
                    ),
                    (
                        mascaras["B04"],
                        mascaras["B03"],
                        mascaras["B02"],
                    ),
                    self.config.rgb,
                )

                rgb_gerado = f"{self._uuid_rgb(registro)}.png"
                Image.fromarray(rgb, mode="RGB").save(
                    pasta_temporaria / rgb_gerado,
                    "PNG",
                )
                gerados.add(rgb_gerado)

            if self.config.gerar_metadata_json:
                metadata = {
                    "patch_id": registro.patch_id,
                    "scene_id": registro.scene_id,
                    "collection": registro.collection,
                    "date": registro.date,
                    "bands": list(arrays),
                    "missing_bands": registro.missing_bands.split(";") if registro.missing_bands else [],
                    "bounds": json.loads(registro.bbox),
                    "crs": registro.crs,
                    "width": registro.width,
                    "height": registro.height,
                    "pixel_size": json.loads(registro.pixel_size),
                    "cloud_pct": float(registro.cloud_pct) if registro.cloud_pct else None,
                    "valid_pixel_pct": float(registro.valid_pixel_pct),
                    "source_scene": self._relativo(source_scene),
                    "source_assets": {
                        "scientific": {
                            nome: self._relativo(caminho) for nome, caminho in fontes.items()
                            if nome in arrays
                        },
                        "quality": {
                            nome: self._relativo(caminho) for nome, caminho in auxiliares.items()
                            if nome != "SCL" or manter_scl
                        },
                    },
                    "quality_processing": {
                        "used_layers": list(auxiliares),
                        "non_persistent_layers": [
                            nome for nome in auxiliares if nome == "SCL" and not manter_scl
                        ],
                    },
                    "native_resolution_m": {
                        nome: RESOLUCAO_NATIVA_METROS.get(nome) for nome in arrays
                    },
                    "resampling": {
                        "continuous_bands": "bilinear",
                        "categorical_masks": "nearest",
                    },
                }
                (pasta_temporaria / "metadata.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                gerados.add("metadata.json")

            pasta.mkdir(parents=True, exist_ok=True)

            for nome in gerados:
                os.replace(pasta_temporaria / nome, pasta / nome)

            conhecidos = {
                "multiband.tif",
                "multiband.tif.msk",
                "metadata.json",
            }
            for nome in conhecidos - gerados:
                (pasta / nome).unlink(missing_ok=True)

            # Remove PNGs de execuções anteriores, preservando apenas o PNG
            # gerado nesta execução. A comparação do sufixo é case-insensitive
            # para também eliminar o antigo "rgb.png".
            for arquivo in pasta.iterdir():
                if (
                    arquivo.is_file()
                    and arquivo.suffix.lower() == ".png"
                    and arquivo.name not in gerados
                ):
                    arquivo.unlink(missing_ok=True)

        if "multiband.tif" in gerados:
            registro.geotiff_path = self._relativo(pasta / "multiband.tif")

        if rgb_gerado is not None:
            registro.rgb_png = self._relativo(pasta / rgb_gerado)
        else:
            registro.rgb_png = ""

    def _limpar_produtos_patch(self, registro: RegistroPatch) -> None:
        pasta = self._pasta_patch(registro)

        for nome in ("multiband.tif", "multiband.tif.msk", "metadata.json"):
            (pasta / nome).unlink(missing_ok=True)

        if pasta.is_dir():
            for arquivo in pasta.iterdir():
                if arquivo.is_file() and arquivo.suffix.lower() == ".png":
                    arquivo.unlink(missing_ok=True)

            try:
                pasta.rmdir()
            except OSError:
                pass

    @staticmethod
    def _uuid_rgb(registro: RegistroPatch) -> str:
        """Gera um nome UUID estável para o RGB do patch.

        UUID5 evita colisões entre patches e mantém o nome reproduzível em
        regenerações do mesmo patch.
        """
        chave = "|".join(
            (registro.collection, registro.scene_id, registro.date, registro.patch_id)
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sentinel2-mt:rgb:{chave}"))

    def _limpar_produtos_obsoletos_cena(
        self,
        date: str,
        scene_id: str,
        registros: list[RegistroPatch],
    ) -> None:
        pasta_cena = caminho_contido(
            (self.raiz / self.config.pasta).expanduser().resolve(),
            componente_seguro(date, "sem_data"),
            componente_seguro(scene_id, "scene"),
        )
        if not pasta_cena.is_dir():
            return

        atuais = {registro.patch_id for registro in registros}
        conhecidos = ("multiband.tif", "multiband.tif.msk", "metadata.json")

        for pasta in pasta_cena.iterdir():
            if not pasta.is_dir() or pasta.name in atuais:
                continue

            for nome in conhecidos:
                (pasta / nome).unlink(missing_ok=True)

            for arquivo in pasta.iterdir():
                if arquivo.is_file() and arquivo.suffix.lower() == ".png":
                    arquivo.unlink(missing_ok=True)

            try:
                pasta.rmdir()
            except OSError:
                pass

    def _pasta_patch(self, registro: RegistroPatch) -> Path:
        raiz_dataset = (self.raiz / self.config.pasta).expanduser().resolve()
        return caminho_contido(
            raiz_dataset,
            componente_seguro(registro.date, "sem_data"),
            componente_seguro(registro.scene_id, "scene"),
            componente_seguro(registro.patch_id, "patch"),
        )

    @staticmethod
    def _gravar_geotiff(
        destino: Path,
        arrays: dict[str, np.ma.MaskedArray],
        mascara_valida: np.ndarray,
        nodatas: dict[str, float | int | None],
        transformacao,
        crs,
        patch_id: str,
        scene_id: str,
        source_scene: str,
        collection: str,
    ) -> None:
        nomes = tuple(arrays)
        dtype = np.result_type(*(array.dtype for array in arrays.values()))
        nodata = GeradorDataset._nodata_comum(tuple(nodatas.get(nome) for nome in nomes))
        preenchimento = nodata
        if preenchimento is None:
            preenchimento = np.nan if np.issubdtype(dtype, np.floating) else 0
        tamanho = next(iter(arrays.values())).shape[0]
        with rasterio.open(
            destino,
            "w",
            driver="GTiff",
            width=tamanho,
            height=tamanho,
            count=len(nomes),
            dtype=dtype,
            crs=crs,
            transform=transformacao,
            nodata=nodata,
            compress="deflate",
        ) as saida:
            for indice, nome in enumerate(nomes, start=1):
                dados = arrays[nome].astype(dtype).filled(preenchimento)
                saida.write(dados, indice)
                saida.set_band_description(indice, nome)
                tags = {"SOURCE_BAND": nome}
                if nome in RESOLUCAO_NATIVA_METROS:
                    tags["NATIVE_RESOLUTION_M"] = str(RESOLUCAO_NATIVA_METROS[nome])
                saida.update_tags(indice, **tags)
            saida.write_mask((mascara_valida.astype(np.uint8) * 255))
            saida.update_tags(
                PATCH_ID=patch_id,
                SCENE_ID=scene_id,
                SOURCE_SCENE=source_scene,
                COLLECTION=collection,
                BANDS=",".join(nomes),
            )

    @staticmethod
    def _nodata_comum(valores: tuple[float | int | None, ...]):
        primeiro = valores[0]
        for valor in valores[1:]:
            ambos_nan = (
                isinstance(primeiro, float)
                and isinstance(valor, float)
                and np.isnan(primeiro)
                and np.isnan(valor)
            )
            if not ambos_nan and valor != primeiro:
                return None
        return primeiro

    def _registro_base(
        self,
        *,
        patch_id: str,
        scene_id: str,
        collection: str,
        date: str,
        source_scene: Path,
        transformacao,
        crs,
        cloud_pct: float | None,
        valid_pct: float,
        bandas: tuple[str, ...],
        ausentes: list[str],
        auxiliares: dict[str, Path],
        manter_scl: bool,
    ) -> RegistroPatch:
        tamanho = self.config.patches.tamanho_px
        oeste, sul, leste, norte = array_bounds(tamanho, tamanho, transformacao)
        return RegistroPatch(
            patch_id=patch_id,
            scene_id=scene_id,
            collection=collection,
            date=date,
            bbox=json.dumps([oeste, sul, leste, norte]),
            crs=str(crs),
            width=tamanho,
            height=tamanho,
            pixel_size=json.dumps([abs(transformacao.a), abs(transformacao.e)]),
            cloud_pct="" if cloud_pct is None else f"{cloud_pct:.2f}",
            valid_pixel_pct=f"{valid_pct:.2f}",
            source_scene=self._relativo(source_scene),
            bands=";".join(bandas),
            missing_bands=";".join(ausentes),
            scl_path=(
                self._relativo(auxiliares["SCL"])
                if manter_scl and "SCL" in auxiliares
                else ""
            ),
            CLEAROB=self._relativo(auxiliares["CLEAROB"]) if "CLEAROB" in auxiliares else "",
            TOTALOB=self._relativo(auxiliares["TOTALOB"]) if "TOTALOB" in auxiliares else "",
            PROVENANCE=self._relativo(auxiliares["PROVENANCE"]) if "PROVENANCE" in auxiliares else "",
        )

    @staticmethod
    def patch_id(
        scene_id: str,
        x: int,
        y: int,
        tamanho: int,
        *,
        collection: str = "",
        date: str = "",
        transformacao=None,
        crs=None,
        bandas: tuple[str, ...] | list[str] = (),
    ) -> str:
        cena = componente_seguro(scene_id, "scene", limite=80)
        grade = tuple(float(valor) for valor in transformacao) if transformacao is not None else ()
        receita = {
            "collection": collection,
            "date": date,
            "scene_id": scene_id,
            "x": x,
            "y": y,
            "size": tamanho,
            "transform": grade,
            "crs": str(crs or ""),
            "bands": list(bandas),
        }
        origem = json.dumps(
            receita,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(origem).hexdigest()[:12]
        return f"{cena}_{digest}_x{x:06d}_y{y:06d}_{tamanho}"

    def _relativo(self, caminho: Path) -> str:
        try:
            return str(caminho.resolve().relative_to(self.raiz.resolve()))
        except ValueError:
            return caminho.name

    @staticmethod
    def _pct_log(valor: float | None) -> str:
        return "n/a" if valor is None else f"{valor:.2f}%"

    def _imprimir_resumo(self, resumo: ResumoDataset) -> None:
        self.saida(f"Patches candidatos: {resumo.candidatos}")
        self.saida(f"Patches aprovados: {resumo.aprovados}")
        self.saida(f"Descartados por nuvem: {resumo.descartados_nuvem}")
        self.saida(f"Descartados por nodata: {resumo.descartados_nodata}")
        self.saida(f"Erros: {resumo.erros}")
