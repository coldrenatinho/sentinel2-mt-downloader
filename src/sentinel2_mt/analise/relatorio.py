from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


LIMITACAO_AREA = (
    "As caixas representam detecções em imagem. Sem escala, resolução espacial e "
    "geometria georreferenciada validadas, sua quantidade ou área em pixels não "
    "pode ser convertida nem apresentada como hectares."
)


def _valor(objeto: object, *nomes: str, padrao: Any = "") -> Any:
    for nome in nomes:
        if isinstance(objeto, Mapping) and nome in objeto:
            return objeto[nome]
        if hasattr(objeto, nome):
            return getattr(objeto, nome)
    return padrao


def _texto(valor: Any) -> str:
    if valor is None:
        return "-"
    if isinstance(valor, Mapping):
        return ", ".join(f"{chave}: {_texto(item)}" for chave, item in sorted(valor.items())) or "-"
    if isinstance(valor, Sequence) and not isinstance(valor, (str, bytes, bytearray)):
        return ", ".join(_texto(item) for item in valor) or "-"
    return str(valor)


class GeradorRelatorioAnalise:
    """Gera um PDF local a partir de objetos simples, dataclasses ou mapeamentos."""

    VERDE = "#102B24"
    VERDE_MEDIO = "#2D7F5E"
    VERDE_CLARO = "#49C98B"
    TERRACOTA = "#C9794A"
    FUNDO = "#F4F7F6"
    TEXTO = "#17201D"
    TEXTO_SUAVE = "#5B6B65"
    BORDA = "#DCE6E2"

    def gerar(
        self,
        caminho: Path | str,
        analise: object,
        imagens: Sequence[object] | None = None,
    ) -> Path:
        # Importação tardia mantém o histórico utilizável sem a dependência opcional.
        from matplotlib import image as mpimg
        from matplotlib import pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages

        destino = Path(caminho)
        pasta_ja_existia = destino.parent.exists()
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not pasta_ja_existia:
            os.chmod(destino.parent, 0o700)

        temporario: Path | None = None
        figuras = []
        try:
            with NamedTemporaryFile(
                prefix=f".{destino.name}.", suffix=".tmp", dir=destino.parent, delete=False
            ) as arquivo:
                temporario = Path(arquivo.name)
                os.chmod(temporario, 0o600)

            with PdfPages(temporario) as pdf:
                figura = plt.figure(figsize=(8.27, 11.69))
                figuras.append(figura)
                eixo = figura.add_axes((0.08, 0.06, 0.84, 0.90))
                eixo.axis("off")
                self._pagina_principal(eixo, analise)
                pdf.savefig(figura)

                figura_grafico = self._figura_classes(plt, analise)
                if figura_grafico is not None:
                    figuras.append(figura_grafico)
                    pdf.savefig(figura_grafico)

                for imagem in imagens or ():
                    figura_imagem = self._figura_imagem(plt, mpimg, imagem)
                    if figura_imagem is not None:
                        figuras.append(figura_imagem)
                        pdf.savefig(figura_imagem)

            with temporario.open("rb") as arquivo:
                os.fsync(arquivo.fileno())
            os.replace(temporario, destino)
            temporario = None
            os.chmod(destino, 0o600)
            return destino
        finally:
            for figura in figuras:
                plt.close(figura)
            if temporario is not None:
                temporario.unlink(missing_ok=True)

    @staticmethod
    def _pagina_principal(eixo, analise: object) -> None:
        import matplotlib.patches as patches

        analysis_id = _valor(analise, "analysis_id", "id", padrao="-")
        regiao = _valor(analise, "regiao", "region", padrao="-")
        bbox = _valor(analise, "bbox", padrao="-")
        inicio = _valor(analise, "periodo_inicio", "period_start", padrao="-")
        fim = _valor(analise, "periodo_fim", "period_end", padrao="-")
        scene_id = _valor(analise, "scene_id", padrao="-")
        fonte = _valor(analise, "fonte", "source", padrao="Sentinel-2 / INPE Brazil Data Cube")
        resumo = _valor(analise, "resumo", "summary", "resultados", padrao={})
        versao = _valor(analise, "modelo_versao", "model_version", padrao="-")
        modelo_hash = _valor(analise, "modelo_hash", "model_hash", padrao="-")
        metodologia = _valor(
            analise,
            "metodologia",
            "methodology",
            padrao="Inferência automatizada sobre imagem de sensoriamento remoto.",
        )

        resumo = resumo if isinstance(resumo, Mapping) else {}
        figura = eixo.figure
        figura.patch.set_facecolor(GeradorRelatorioAnalise.FUNDO)
        eixo.set_xlim(0, 1)
        eixo.set_ylim(0, 1)
        eixo.axis("off")

        # Faixa de marca e identificação do relatório.
        eixo.add_patch(patches.Rectangle((0, 0.86), 1, 0.14, color=GeradorRelatorioAnalise.VERDE, transform=eixo.transAxes))
        eixo.add_patch(patches.Rectangle((0, 0.855), 1, 0.005, color=GeradorRelatorioAnalise.VERDE_CLARO, transform=eixo.transAxes))
        eixo.text(0.04, 0.955, "SENTINEL-2 MT", color="white", fontsize=9, fontweight="bold", va="top", transform=eixo.transAxes)
        eixo.text(0.04, 0.912, "Relatório de análise territorial", color="white", fontsize=20, fontweight="bold", va="top", transform=eixo.transAxes)
        eixo.text(0.96, 0.95, _texto(analysis_id), color="#CBE2DB", fontsize=8.5, ha="right", va="top", transform=eixo.transAxes)
        eixo.text(0.96, 0.915, "INPE / Brazil Data Cube", color="#9CC4B7", fontsize=8.5, ha="right", va="top", transform=eixo.transAxes)

        total = resumo.get("total_deteccoes", resumo.get("caixas", 0))
        confianca = resumo.get("confianca_media", resumo.get("confianca", None))
        total_tiles = resumo.get("total_tiles", resumo.get("amostras", 0))
        percentual = resumo.get("percentual_tiles_com_deteccao", None)
        indicadores = (
            ("DETECÇÕES", _texto(total), GeradorRelatorioAnalise.TERRACOTA),
            ("CONFIANÇA MÉDIA", f"{float(confianca) * 100:.1f}%" if confianca is not None else "-", GeradorRelatorioAnalise.VERDE_MEDIO),
            ("TILES ANALISADOS", _texto(total_tiles), GeradorRelatorioAnalise.VERDE),
            ("TILES COM SINAL", f"{float(percentual):.1f}%" if percentual is not None else "-", GeradorRelatorioAnalise.VERDE_CLARO),
        )
        for indice, (rotulo, valor, cor) in enumerate(indicadores):
            x = 0.04 + indice * 0.235
            eixo.add_patch(patches.FancyBboxPatch((x, 0.765), 0.215, 0.065, boxstyle="round,pad=0.008,rounding_size=0.012", facecolor="white", edgecolor=GeradorRelatorioAnalise.BORDA, linewidth=0.8, transform=eixo.transAxes))
            eixo.add_patch(patches.Rectangle((x, 0.765), 0.008, 0.065, color=cor, transform=eixo.transAxes))
            eixo.text(x + 0.022, 0.809, rotulo, color=GeradorRelatorioAnalise.TEXTO_SUAVE, fontsize=7, fontweight="bold", va="top", transform=eixo.transAxes)
            eixo.text(x + 0.022, 0.779, valor, color=GeradorRelatorioAnalise.TEXTO, fontsize=14, fontweight="bold", va="top", transform=eixo.transAxes)

        def bloco(x, y, largura, altura, titulo, linhas, cor=GeradorRelatorioAnalise.VERDE_MEDIO):
            eixo.add_patch(patches.FancyBboxPatch((x, y), largura, altura, boxstyle="round,pad=0.012,rounding_size=0.012", facecolor="white", edgecolor=GeradorRelatorioAnalise.BORDA, linewidth=0.8, transform=eixo.transAxes))
            eixo.add_patch(patches.Rectangle((x, y + altura - 0.008), largura, 0.008, color=cor, transform=eixo.transAxes))
            eixo.text(x + 0.022, y + altura - 0.035, titulo.upper(), color=GeradorRelatorioAnalise.TEXTO, fontsize=9, fontweight="bold", va="top", transform=eixo.transAxes)
            yy = y + altura - 0.072
            for linha in linhas:
                for parte in GeradorRelatorioAnalise._quebrar(linha, 48 if largura < 0.5 else 78):
                    eixo.text(x + 0.022, yy, parte, color=GeradorRelatorioAnalise.TEXTO_SUAVE, fontsize=8.2, va="top", transform=eixo.transAxes)
                    yy -= 0.026
                yy -= 0.006

        bloco(0.04, 0.52, 0.445, 0.21, "Área e período", (
            f"Região: {_texto(regiao)}", f"Período: {_texto(inicio)} a {_texto(fim)}",
            f"BBox: {_texto(bbox)}", f"Cena(s): {_texto(scene_id)}", f"Fonte: {_texto(fonte)}",
        ), GeradorRelatorioAnalise.TERRACOTA)
        bloco(0.515, 0.52, 0.445, 0.21, "Modelo e método", (
            _texto(metodologia), f"Versão: {_texto(versao)}", f"Hash: {_texto(modelo_hash)}",
        ), GeradorRelatorioAnalise.VERDE_MEDIO)

        por_classe = resumo.get("por_classe", {})
        classe_texto = [f"{classe}: {quantidade}" for classe, quantidade in por_classe.items()] if isinstance(por_classe, Mapping) else []
        bloco(0.04, 0.25, 0.445, 0.21, "Leitura rápida", tuple(classe_texto or ("Nenhuma detecção registrada.",)), GeradorRelatorioAnalise.VERDE_CLARO)
        bloco(0.515, 0.25, 0.445, 0.21, "Limitações e interpretação", (LIMITACAO_AREA,), GeradorRelatorioAnalise.TERRACOTA)

        eixo.text(0.04, 0.16, "Resumo estatístico", color=GeradorRelatorioAnalise.VERDE, fontsize=10, fontweight="bold", transform=eixo.transAxes)
        resumo_linhas = []
        for chave, valor in resumo.items():
            if isinstance(valor, Mapping) or isinstance(valor, (list, tuple)):
                continue
            resumo_linhas.append(f"{chave.replace('_', ' ').capitalize()}: {_texto(valor)}")
        resumo_texto = "  |  ".join(resumo_linhas[:6]) or "Sem métricas adicionais."
        eixo.text(0.04, 0.13, "\n".join(GeradorRelatorioAnalise._quebrar(resumo_texto, 112)), color=GeradorRelatorioAnalise.TEXTO_SUAVE, fontsize=8, va="top", transform=eixo.transAxes)
        eixo.text(0.04, 0.035, "Documento gerado automaticamente pelo Sentinel-2 MT Downloader", color="#82938C", fontsize=7.5, transform=eixo.transAxes)
        eixo.text(0.96, 0.035, "CONFIDENCIAL - USO TÉCNICO", color="#82938C", fontsize=7.5, ha="right", transform=eixo.transAxes)

    @staticmethod
    def _quebrar(texto: str, largura: int) -> list[str]:
        from textwrap import wrap

        return wrap(str(texto), width=largura, break_long_words=False, break_on_hyphens=False) or [""]

    @staticmethod
    def _figura_classes(plt, analise: object):
        resumo = _valor(analise, "resumo", "summary", "resultados", padrao={})
        por_classe = resumo.get("por_classe", {}) if isinstance(resumo, Mapping) else {}
        if not isinstance(por_classe, Mapping) or not por_classe:
            return None
        classes = sorted(str(classe) for classe in por_classe)
        valores = [int(por_classe[classe]) for classe in classes]
        figura, eixo = plt.subplots(figsize=(8.27, 5.8))
        figura.patch.set_facecolor(GeradorRelatorioAnalise.FUNDO)
        eixo.set_facecolor("white")
        barras = eixo.barh(classes, valores, color=GeradorRelatorioAnalise.VERDE_MEDIO, height=0.58)
        eixo.set_title("Detecções por classe", loc="left", color=GeradorRelatorioAnalise.VERDE, fontsize=17, fontweight="bold", pad=22)
        eixo.text(0, 1.02, "Distribuição das ocorrências encontradas pelo modelo", transform=eixo.transAxes, color=GeradorRelatorioAnalise.TEXTO_SUAVE, fontsize=9)
        eixo.set_xlabel("Quantidade de caixas detectadas", color=GeradorRelatorioAnalise.TEXTO_SUAVE)
        eixo.grid(axis="x", alpha=0.18, color=GeradorRelatorioAnalise.VERDE_MEDIO)
        eixo.spines[["top", "right", "left"]].set_visible(False)
        eixo.spines["bottom"].set_color(GeradorRelatorioAnalise.BORDA)
        eixo.tick_params(axis="both", colors=GeradorRelatorioAnalise.TEXTO_SUAVE, length=0)
        for barra, valor in zip(barras, valores):
            eixo.text(valor + max(valores) * 0.02, barra.get_y() + barra.get_height() / 2, str(valor), va="center", color=GeradorRelatorioAnalise.TEXTO, fontweight="bold")
        figura.subplots_adjust(left=0.16, right=0.94, top=0.84, bottom=0.15)
        return figura

    @staticmethod
    def _figura_imagem(plt, mpimg, item: object):
        titulo = "Imagem da análise"
        imagem = item
        if isinstance(item, Mapping):
            imagem = item.get("imagem", item.get("path", item.get("caminho")))
            titulo = str(item.get("titulo", item.get("title", titulo)))
        else:
            titulo = str(_valor(item, "titulo", "title", padrao=titulo))
            imagem = _valor(item, "imagem", "path", "caminho", padrao=item)
        if imagem is None:
            return None
        if isinstance(imagem, (str, os.PathLike)):
            imagem = mpimg.imread(Path(imagem))
        figura, eixo = plt.subplots(figsize=(8.27, 11.69))
        figura.patch.set_facecolor(GeradorRelatorioAnalise.FUNDO)
        eixo.set_facecolor("white")
        eixo.imshow(imagem)
        eixo.set_title(titulo, loc="left", color=GeradorRelatorioAnalise.VERDE, fontsize=17, fontweight="bold", pad=18)
        eixo.axis("off")
        figura.text(0.06, 0.035, "SENTINEL-2 MT  |  Evidência visual da análise", color="#82938C", fontsize=8)
        figura.text(0.94, 0.035, "USO TÉCNICO", color="#82938C", fontsize=8, ha="right")
        figura.subplots_adjust(left=0.06, right=0.94, top=0.9, bottom=0.08)
        return figura


def gerar_relatorio_pdf(
    caminho: Path | str,
    analise: object,
    imagens: Sequence[object] | None = None,
) -> Path:
    return GeradorRelatorioAnalise().gerar(caminho, analise, imagens)


GeradorRelatorioPDF = GeradorRelatorioAnalise
