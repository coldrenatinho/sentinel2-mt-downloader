from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class GeradorConfiguracao:
    """Monta e persiste o config.yaml sem depender da interface gráfica."""

    BBOX_PADRAO = [-61.65, -18.05, -50.20, -7.30]
    BANDAS_PADRAO = [
        "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12", "NDVI", "EVI"
    ]

    @staticmethod
    def validar_bbox(bbox: list[float]) -> list[float]:
        if len(bbox) != 4:
            raise ValueError(
                "A bounding box deve conter exatamente 4 valores: "
                "[oeste, sul, leste, norte]."
            )
        oeste, sul, leste, norte = (float(valor) for valor in bbox)
        if oeste >= leste or sul >= norte:
            raise ValueError("A bounding box deve respeitar oeste < leste e sul < norte.")
        return [oeste, sul, leste, norte]

    def gerar(self, dados: dict[str, Any]) -> dict[str, Any]:
        bbox = self.validar_bbox(dados.get("bbox", self.BBOX_PADRAO))
        bandas = dados.get("bandas") or list(self.BANDAS_PADRAO)
        return {
            "stac": {
                "url": dados.get("stac_url", "https://data.inpe.br/bdc/stac/v1/"),
                "colecao": dados.get("colecao", "S2-16D-2"),
            },
            "area": {
                "nome": dados.get("nome_regiao", "Região personalizada"),
                "uf": dados.get("uf", "MT"),
                "bbox": bbox,
            },
            "periodo": {
                "inicio": dados.get("inicio", "2025-09-01"),
                "fim": dados.get("fim", "2026-04-30"),
            },
            "bandas": bandas,
            "qualidade": {
                "filtrar_nuvens": bool(dados.get("filtrar_nuvens", True)),
                "nuvem_max_pct": float(dados.get("nuvem_max_pct", 40)),
                "manter_scl": bool(dados.get("manter_scl", True)),
                "camadas_auxiliares": dados.get(
                    "camadas_auxiliares", ["SCL", "CLEAROB", "TOTALOB", "PROVENANCE"]
                ),
            },
            "preview": {
                "gerar_rgb": bool(dados.get("gerar_rgb", True)),
                "tamanho_max_px": int(dados.get("tamanho_max_px", 1600)),
                "metodo": dados.get("preview_metodo", "percentile"),
                "percentil_min": float(dados.get("percentil_min", 2)),
                "percentil_max": float(dados.get("percentil_max", 98)),
                "qualidade_jpeg": int(dados.get("qualidade_jpeg", 92)),
            },
            "dataset": {
                "gerar": bool(dados.get("gerar_dataset", False)),
                "pasta": dados.get("pasta_dataset", "data/dataset"),
                "catalogo": dados.get("catalogo_patches", "catalogo/patches.csv"),
                "rgb": {
                    "gerar_png": bool(dados.get("gerar_rgb_png", True)),
                    "metodo": dados.get("dataset_rgb_metodo", "fixed"),
                    "minimo": float(dados.get("dataset_rgb_minimo", 0)),
                    "maximo": float(dados.get("dataset_rgb_maximo", 2000)),
                    "percentil_min": float(dados.get("dataset_percentil_min", 2)),
                    "percentil_max": float(dados.get("dataset_percentil_max", 98)),
                },
                "patches": {
                    "habilitado": bool(dados.get("patches_habilitado", True)),
                    "tamanho_px": int(dados.get("patch_tamanho_px", 512)),
                    "stride_px": int(dados.get("patch_stride_px", 512)),
                    "nuvem_max_pct": float(dados.get("patch_nuvem_max_pct", 10)),
                    "dados_validos_min_pct": float(dados.get("dados_validos_min_pct", 90)),
                    "max_patches_por_cena": int(dados.get("max_patches_por_cena", 100000)),
                },
                "gerar_geotiff_multibanda": bool(dados.get("gerar_geotiff_multibanda", True)),
                "gerar_metadata_json": bool(dados.get("gerar_metadata_json", True)),
            },
            "download": {
                "pasta": dados.get("pasta_download", "data/sentinel2"),
                "catalogo": dados.get("catalogo", "catalogo/catalogo_imagens.csv"),
                "timeout_segundos": int(dados.get("timeout_segundos", 120)),
                "chunk_mb": int(dados.get("chunk_mb", 1)),
                "max_itens_teste": int(dados.get("max_itens_teste", 5)),
                "max_candidatos_teste": int(dados.get("max_candidatos_teste", 40)),
            },
            "analise": {
                "modelo": dados.get("modelo_ia", "analise/models/agricultura.pt"),
                "modelo_sha256": dados.get("modelo_sha256", ""),
                "confianca_minima": float(dados.get("confianca_minima", 0.25)),
                "iou_maximo": float(dados.get("iou_maximo", 0.45)),
                "tamanho_inferencia_px": int(dados.get("tamanho_inferencia_px", 640)),
                "pasta": dados.get("pasta_analises", "data/analises"),
                "historico": dados.get(
                    "historico_analises", "data/historico-analises.sqlite3"
                ),
                "gerar_relatorio": bool(dados.get("gerar_relatorio", True)),
                "max_imagens": int(dados.get("max_imagens_analise", 1000)),
            },
            "sincronizacao": {
                "pasta_remota": dados.get("pasta_remota", "sentinel2-mt"),
                "oauth_json": dados.get("oauth_json", "${GOOGLE_OAUTH_JSON:-}"),
                "token_json": dados.get(
                    "token_json", "${GOOGLE_TOKEN_JSON:-config/google-token.json}"
                ),
                "pasta_id": dados.get("pasta_id", "${GOOGLE_PASTA_ID:-root}"),
                "tamanho_lote": int(dados.get("tamanho_lote", 100)),
                "extensoes": dados.get(
                    "extensoes", [".tif", ".tiff", ".jpg", ".jpeg"]
                ),
            },
        }

    def salvar(self, caminho: str | Path, dados: dict[str, Any]) -> Path:
        destino = Path(caminho).expanduser()
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", encoding="utf-8") as arquivo:
            yaml.safe_dump(
                self.gerar(dados), arquivo, allow_unicode=True, sort_keys=False
            )
        return destino


_gerador = GeradorConfiguracao()


def bbox_para_yaml(bbox: list[float]) -> list[float]:
    return _gerador.validar_bbox(bbox)


def gerar_config(dados: dict[str, Any]) -> dict[str, Any]:
    return _gerador.gerar(dados)


def salvar_config(caminho: str | Path, dados: dict[str, Any]) -> Path:
    return _gerador.salvar(caminho, dados)
