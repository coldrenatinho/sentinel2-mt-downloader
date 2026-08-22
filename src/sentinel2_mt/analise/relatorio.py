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
        return "—"
    if isinstance(valor, Mapping):
        return ", ".join(f"{chave}: {_texto(item)}" for chave, item in sorted(valor.items())) or "—"
    if isinstance(valor, Sequence) and not isinstance(valor, (str, bytes, bytearray)):
        return ", ".join(_texto(item) for item in valor) or "—"
    return str(valor)


class GeradorRelatorioAnalise:
    """Gera um PDF local a partir de objetos simples, dataclasses ou mapeamentos."""

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
        analysis_id = _valor(analise, "analysis_id", "id", padrao="—")
        regiao = _valor(analise, "regiao", "region", padrao="—")
        bbox = _valor(analise, "bbox", padrao="—")
        inicio = _valor(analise, "periodo_inicio", "period_start", padrao="—")
        fim = _valor(analise, "periodo_fim", "period_end", padrao="—")
        scene_id = _valor(analise, "scene_id", padrao="—")
        fonte = _valor(analise, "fonte", "source", padrao="Sentinel-2 / INPE Brazil Data Cube")
        resumo = _valor(analise, "resumo", "summary", "resultados", padrao={})
        versao = _valor(analise, "modelo_versao", "model_version", padrao="—")
        modelo_hash = _valor(analise, "modelo_hash", "model_hash", padrao="—")
        metodologia = _valor(
            analise,
            "metodologia",
            "methodology",
            padrao="Inferência automatizada sobre imagem de sensoriamento remoto.",
        )

        linhas = [
            ("Relatório de análise", 18, "bold"),
            (f"Identificação: {_texto(analysis_id)}", 10, "normal"),
            ("", 5, "normal"),
            ("Identificação e fonte", 13, "bold"),
            (f"Região: {_texto(regiao)}", 10, "normal"),
            (f"BBox: {_texto(bbox)}", 10, "normal"),
            (f"Período: {_texto(inicio)} a {_texto(fim)}", 10, "normal"),
            (f"Cena: {_texto(scene_id)}", 10, "normal"),
            (f"Fonte: {_texto(fonte)}", 10, "normal"),
            ("", 5, "normal"),
            ("Resultados", 13, "bold"),
            (_texto(resumo), 10, "normal"),
            ("", 5, "normal"),
            ("Metodologia e modelo", 13, "bold"),
            (_texto(metodologia), 10, "normal"),
            (f"Versão do modelo: {_texto(versao)}", 10, "normal"),
            (f"Hash do modelo: {_texto(modelo_hash)}", 10, "normal"),
            ("", 5, "normal"),
            ("Limitações", 13, "bold"),
            (LIMITACAO_AREA, 10, "normal"),
        ]
        y = 0.98
        for texto, tamanho, peso in linhas:
            eixo.text(0, y, texto, fontsize=tamanho, fontweight=peso, va="top", wrap=True)
            y -= 0.035 if texto else 0.018

    @staticmethod
    def _figura_classes(plt, analise: object):
        resumo = _valor(analise, "resumo", "summary", "resultados", padrao={})
        por_classe = resumo.get("por_classe", {}) if isinstance(resumo, Mapping) else {}
        if not isinstance(por_classe, Mapping) or not por_classe:
            return None
        classes = sorted(str(classe) for classe in por_classe)
        valores = [int(por_classe[classe]) for classe in classes]
        figura, eixo = plt.subplots(figsize=(8.27, 5.8))
        eixo.barh(classes, valores, color="#2d7f5e")
        eixo.set_title("Detecções por classe")
        eixo.set_xlabel("Quantidade de caixas detectadas")
        eixo.grid(axis="x", alpha=0.2)
        figura.tight_layout()
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
        eixo.imshow(imagem)
        eixo.set_title(titulo)
        eixo.axis("off")
        figura.tight_layout()
        return figura


def gerar_relatorio_pdf(
    caminho: Path | str,
    analise: object,
    imagens: Sequence[object] | None = None,
) -> Path:
    return GeradorRelatorioAnalise().gerar(caminho, analise, imagens)


GeradorRelatorioPDF = GeradorRelatorioAnalise
