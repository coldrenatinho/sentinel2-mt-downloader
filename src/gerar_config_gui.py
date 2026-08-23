from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWebEngineWidgets import QWebEngineView

from sentinel2_mt.config_builder import GeradorConfiguracao, gerar_config, salvar_config as persistir_config
from sentinel2_mt.configuracao import ConfiguracaoProjeto
from sentinel2_mt.analise.historico import RepositorioHistoricoAnalises
from sentinel2_mt.gui_support import (
    LocalConfigStore,
    montar_argumentos_operacao,
    normalizar_bbox,
)
from sentinel2_mt.gui_theme import CORES, folha_estilos


EMPACOTADO = bool(getattr(sys, "frozen", False))
if EMPACOTADO:
    ROOT = Path.home()
    XDG_CONFIG_HOME = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    ).expanduser()
    CONFIG_USUARIO = XDG_CONFIG_HOME / "sentinel2-mt"
    DEFAULT_CONFIG = CONFIG_USUARIO / "config.yaml"
    LOCAL_DB = CONFIG_USUARIO / "configuracoes_local.db"
    SCRIPT_CLI = Path(sys.executable)
else:
    ROOT = Path(__file__).resolve().parents[1]
    DEFAULT_CONFIG = ROOT / "config" / "config.yaml"
    LOCAL_DB = ROOT / "config" / "configuracoes_local.db"
    SCRIPT_CLI = ROOT / "src" / "baixar_inpe_mt.py"

# Compatibilidade com integrações que importavam esta função do módulo da GUI.
bbox_para_yaml = normalizar_bbox


ESTILO = folha_estilos()


def comando_cli_empacotado(argumentos: list[str]) -> tuple[str, list[str], Path]:
    """Monta a operação da GUI para código-fonte ou executável congelado."""
    if EMPACOTADO:
        return sys.executable, ["--cli", *argumentos], Path.home()
    return sys.executable, ["-u", str(SCRIPT_CLI), *argumentos], ROOT


def botao(texto: str, tipo: str = "secondaryButton") -> QtWidgets.QPushButton:
    componente = QtWidgets.QPushButton(texto)
    componente.setObjectName(tipo)
    componente.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    return componente


def rotulo_com_ajuda(texto: str, ajuda: str) -> QtWidgets.QWidget:
    """Cria um rótulo compacto com ajuda contextual acessível."""
    conteiner = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(conteiner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    rotulo = QtWidgets.QLabel(texto)
    icone = QtWidgets.QToolButton()
    icone.setObjectName("helpIcon")
    icone.setText("?")
    icone.setToolTip(ajuda)
    icone.setStatusTip(ajuda)
    icone.setAccessibleName(f"Ajuda: {texto}")
    icone.setAccessibleDescription(ajuda)
    icone.setCursor(QtCore.Qt.CursorShape.WhatsThisCursor)
    icone.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    layout.addWidget(rotulo)
    layout.addWidget(icone)
    layout.addStretch()
    return conteiner


def configurar_aplicacao(app: QtWidgets.QApplication) -> None:
    """Neutraliza temas do sistema e garante a mesma legibilidade em todo desktop."""
    if app.property("sentinel2TemaAplicado"):
        return
    app.setStyle("Fusion")
    paleta = QtGui.QPalette()
    papel = QtGui.QPalette.ColorRole
    paleta.setColor(papel.Window, QtGui.QColor(CORES["fundo"]))
    paleta.setColor(papel.WindowText, QtGui.QColor(CORES["texto"]))
    paleta.setColor(papel.Base, QtGui.QColor(CORES["superficie_campo"]))
    paleta.setColor(papel.AlternateBase, QtGui.QColor(CORES["secundario_fundo"]))
    paleta.setColor(papel.ToolTipBase, QtGui.QColor(CORES["superficie"]))
    paleta.setColor(papel.ToolTipText, QtGui.QColor(CORES["texto"]))
    paleta.setColor(papel.Text, QtGui.QColor(CORES["texto"]))
    paleta.setColor(papel.Button, QtGui.QColor(CORES["secundario_fundo"]))
    paleta.setColor(papel.ButtonText, QtGui.QColor(CORES["secundario_texto"]))
    paleta.setColor(papel.Highlight, QtGui.QColor(CORES["destaque_claro"]))
    paleta.setColor(papel.HighlightedText, QtGui.QColor(CORES["destaque_texto"]))
    paleta.setColor(papel.Link, QtGui.QColor(CORES["destaque"]))
    paleta.setColor(papel.PlaceholderText, QtGui.QColor(CORES["texto_suave"]))
    desabilitado = QtGui.QPalette.ColorGroup.Disabled
    paleta.setColor(
        desabilitado, papel.WindowText, QtGui.QColor(CORES["desabilitado_texto"])
    )
    paleta.setColor(desabilitado, papel.Text, QtGui.QColor(CORES["desabilitado_texto"]))
    paleta.setColor(
        desabilitado, papel.ButtonText, QtGui.QColor(CORES["desabilitado_texto"])
    )
    paleta.setColor(
        desabilitado, papel.Base, QtGui.QColor(CORES["desabilitado_fundo"])
    )
    paleta.setColor(
        desabilitado, papel.Button, QtGui.QColor(CORES["desabilitado_fundo"])
    )
    app.setPalette(paleta)
    app.setProperty("sentinel2TemaAplicado", True)


class Cartao(QtWidgets.QFrame):
    def __init__(self, titulo: str, ajuda: str = "") -> None:
        super().__init__()
        self.setObjectName("card")
        self.layout_principal = QtWidgets.QVBoxLayout(self)
        self.layout_principal.setContentsMargins(18, 16, 18, 18)
        self.layout_principal.setSpacing(10)
        rotulo = QtWidgets.QLabel(titulo)
        rotulo.setObjectName("cardTitle")
        self.layout_principal.addWidget(rotulo)
        if ajuda:
            descricao = QtWidgets.QLabel(ajuda)
            descricao.setObjectName("cardHelp")
            descricao.setWordWrap(True)
            self.layout_principal.addWidget(descricao)


class ControleNumerico(QtWidgets.QWidget):
    """Controle numérico por deslizador, com o valor legível ao lado do trilho."""

    valueChanged = QtCore.Signal(object)

    def __init__(
        self,
        minimo: float,
        maximo: float,
        valor: float,
        sufixo: str = "",
        *,
        casas_decimais: int = 0,
    ) -> None:
        super().__init__()
        self._minimo = minimo
        self._maximo = maximo
        self._casas_decimais = casas_decimais
        self._escala = 10**casas_decimais
        self._sufixo = sufixo
        self._texto_valor_especial = ""

        self.deslizador = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.deslizador.setObjectName("numericSlider")
        self.deslizador.setRange(
            round(minimo * self._escala), round(maximo * self._escala)
        )
        self.deslizador.setSingleStep(1)
        self.deslizador.setPageStep(max(1, (self.deslizador.maximum() - self.deslizador.minimum()) // 20))
        self.deslizador.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.deslizador.setTickInterval(
            max(1, (self.deslizador.maximum() - self.deslizador.minimum()) // 5)
        )
        self.deslizador.setToolTip("Arraste para ajustar o valor; use as setas para ajustes finos.")

        self.rotulo_valor = QtWidgets.QLabel()
        self.rotulo_valor.setObjectName("numericSliderValue")
        self.rotulo_valor.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.rotulo_valor.setMinimumWidth(82)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.deslizador, 1)
        layout.addWidget(self.rotulo_valor)
        self.deslizador.valueChanged.connect(self._atualizar_rotulo)
        self.setValue(valor)

    def _atualizar_rotulo(self, _posicao: int) -> None:
        valor = self.value()
        if self._texto_valor_especial and valor == self._minimo:
            texto = self._texto_valor_especial
        elif self._casas_decimais:
            texto = f"{valor:.{self._casas_decimais}f}{self._sufixo}"
        else:
            texto = f"{int(valor)}{self._sufixo}"
        self.rotulo_valor.setText(texto)
        self.deslizador.setAccessibleName(texto)
        self.valueChanged.emit(valor)

    def value(self) -> int | float:
        valor = self.deslizador.value() / self._escala
        return round(valor, self._casas_decimais) if self._casas_decimais else int(valor)

    def setValue(self, valor: int | float) -> None:
        posicao = round(float(valor) * self._escala)
        mudou = posicao != self.deslizador.value()
        self.deslizador.setValue(posicao)
        if not mudou:
            self._atualizar_rotulo(posicao)

    def setSpecialValueText(self, texto: str) -> None:
        self._texto_valor_especial = texto
        self._atualizar_rotulo(self.deslizador.value())

    def setEnabled(self, ativo: bool) -> None:
        super().setEnabled(ativo)
        self.deslizador.setEnabled(ativo)


class MapaWidget(QWebEngineView):
    areaSelecionada = QtCore.Signal(object)
    mapaPronto = QtCore.Signal()
    mapaErro = QtCore.Signal(str)

    def __init__(self, bbox_inicial: list[float], parent=None) -> None:
        super().__init__(parent)
        self._bbox_pendente = normalizar_bbox(bbox_inicial)
        self._html_iniciado = False
        self._mapa_pronto = False
        self._erro_mapa = False
        self._tentativas_estado = 0
        self.setMinimumHeight(460)
        self.setStyleSheet("background: #dfe9e5;")

        self._estado_mapa = QtWidgets.QLabel("Carregando mapa...", self)
        self._estado_mapa.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._estado_mapa.setStyleSheet(
            "background: #dfe9e5; color: #31554a; font-size: 14px; font-weight: 600;"
        )
        self._estado_mapa.show()

        self._timer_estado = QtCore.QTimer(self)
        self._timer_estado.setInterval(250)
        self._timer_estado.timeout.connect(self._verificar_estado)
        self.loadFinished.connect(self._ao_carregar)

    def showEvent(self, evento: QtGui.QShowEvent) -> None:
        super().showEvent(evento)
        if self._erro_mapa:
            self._html_iniciado = False
            self._erro_mapa = False
        self._iniciar_mapa()
        if self._mapa_pronto:
            QtCore.QTimer.singleShot(0, self.reativar)
            QtCore.QTimer.singleShot(150, self.reativar)

    def resizeEvent(self, evento: QtGui.QResizeEvent) -> None:
        super().resizeEvent(evento)
        self._estado_mapa.setGeometry(self.rect())

    def _iniciar_mapa(self) -> None:
        if self._html_iniciado:
            return
        self._html_iniciado = True
        self._erro_mapa = False
        self._tentativas_estado = 0
        self._estado_mapa.setText("Carregando mapa...")
        self._estado_mapa.show()
        self._estado_mapa.raise_()
        self.setHtml(self._html(), QtCore.QUrl("https://mapa.local/"))

    def _ao_carregar(self, carregou: bool) -> None:
        if not carregou:
            self._mostrar_erro("Não foi possível carregar o documento do mapa.")
            return
        self._timer_estado.start()
        self._verificar_estado()

    def _verificar_estado(self) -> None:
        if not self._html_iniciado or self._mapa_pronto:
            self._timer_estado.stop()
            return
        self._tentativas_estado += 1
        self.page().runJavaScript(
            "JSON.stringify({ready: window.mapReady === true, error: window.mapError || ''})",
            self._receber_estado,
        )

    def _receber_estado(self, valor: str | None) -> None:
        try:
            estado = json.loads(valor) if valor else {}
        except (TypeError, ValueError):
            estado = {}
        if estado.get("ready"):
            self._timer_estado.stop()
            self._mapa_pronto = True
            self._estado_mapa.hide()
            self._aplicar_bbox_pendente()
            self._invalidar_tamanho()
            self.mapaPronto.emit()
            return
        if estado.get("error"):
            self._mostrar_erro(str(estado["error"]))
            return
        if self._tentativas_estado >= 40:
            self._mostrar_erro(
                "O mapa não respondeu. Verifique a conexão e tente abrir esta página novamente."
            )

    def _mostrar_erro(self, mensagem: str) -> None:
        self._timer_estado.stop()
        self._erro_mapa = True
        self._estado_mapa.setText(mensagem)
        self._estado_mapa.show()
        self._estado_mapa.raise_()
        self.mapaErro.emit(mensagem)

    def _invalidar_tamanho(self) -> None:
        if self._mapa_pronto:
            self.page().runJavaScript("window.invalidateMapSize && window.invalidateMapSize();")

    def reativar(self) -> None:
        self._iniciar_mapa()
        if not self._mapa_pronto:
            return
        self._invalidar_tamanho()

    def exibir_bbox(self, bbox: list[float]) -> None:
        self._bbox_pendente = normalizar_bbox(bbox)
        if self._mapa_pronto:
            self._aplicar_bbox_pendente()

    def _aplicar_bbox_pendente(self) -> None:
        self.page().runJavaScript(
            f"window.setSelection && window.setSelection({json.dumps(self._bbox_pendente)});"
        )

    def capturar_bbox(self) -> None:
        if not self._mapa_pronto:
            self.areaSelecionada.emit(None)
            return
        self.page().runJavaScript(
            "JSON.stringify(window.currentSelection)", self._receber_selecao
        )

    def _receber_selecao(self, valor: str | None) -> None:
        try:
            bbox = json.loads(valor) if valor else None
            bbox = normalizar_bbox(bbox) if isinstance(bbox, list) else None
        except (TypeError, ValueError):
            bbox = None
        if bbox is not None:
            self._bbox_pendente = bbox
        self.areaSelecionada.emit(bbox)

    @staticmethod
    def _html() -> str:
        return """
        <!doctype html><html><head><meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <meta http-equiv="Content-Security-Policy" content="default-src 'none';
          script-src 'nonce-sentinel2-map' https://unpkg.com https://cdn.jsdelivr.net;
          style-src 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net;
          img-src data: https://*.tile.openstreetmap.org;" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H"
          crossorigin="anonymous" />
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H"
          crossorigin="anonymous" />
        <style>
          html, body, #map { margin: 0; width: 100%; height: 100%; background: #dfe9e5; }
          .hint { position: absolute; z-index: 900; top: 12px; left: 50%; transform: translateX(-50%);
            background: rgba(16,43,36,.92); color: white; border-radius: 8px; padding: 8px 12px;
            font: 12px sans-serif; box-shadow: 0 3px 12px rgba(0,0,0,.18); }
        </style></head><body><div id="map"></div>
        <div class="hint">Segure Shift e arraste para selecionar uma área</div>
        <script nonce="sentinel2-map">
          window.currentSelection = null;
          window.mapReady = false;
          window.mapError = '';
          let map = null;
          let start = null;
          let rectangle = null;

          window.setSelection = function(bbox, ajustarVisao = true) {
            if (!map || !bbox || bbox.length !== 4) return;
            window.currentSelection = bbox;
            const bounds = [[bbox[1], bbox[0]], [bbox[3], bbox[2]]];
            if (rectangle) map.removeLayer(rectangle);
            rectangle = L.rectangle(bounds, {color: '#168a58', weight: 2, fillOpacity: .16}).addTo(map);
            if (ajustarVisao) {
              map.fitBounds(bounds, {padding: [24, 24], maxZoom: 10, animate: false});
            }
            setTimeout(() => map.invalidateSize(), 100);
          };

          window.invalidateMapSize = function() {
            if (map) map.invalidateSize();
          };

          function iniciarMapa() {
            try {
              map = L.map('map', {worldCopyJump: true, boxZoom: false}).setView([-15.5, -55.0], 5);
              L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors'
              }).addTo(map);
              map.on('mousedown', function(event) {
                if (!event.originalEvent.shiftKey) return;
                start = event.latlng;
                map.dragging.disable();
              });
              map.on('mousemove', function(event) {
                if (!start) return;
                window.setSelection([
                  Math.min(start.lng, event.latlng.lng), Math.min(start.lat, event.latlng.lat),
                  Math.max(start.lng, event.latlng.lng), Math.max(start.lat, event.latlng.lat)
                ], false);
              });
              map.on('mouseup', function(event) {
                if (!start) return;
                window.setSelection([
                  Math.min(start.lng, event.latlng.lng), Math.min(start.lat, event.latlng.lat),
                  Math.max(start.lng, event.latlng.lng), Math.max(start.lat, event.latlng.lat)
                ], false);
                start = null;
                map.dragging.enable();
              });
              window.addEventListener('resize', window.invalidateMapSize);
              window.mapReady = true;
            } catch (erro) {
              window.mapError = 'Falha ao inicializar o mapa: ' + erro.message;
            }
          }

          function carregarLeaflet(indice) {
            const fontes = [
              'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
              'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js'
            ];
            if (indice >= fontes.length) {
              window.mapError = 'Não foi possível carregar a biblioteca do mapa.';
              return;
            }
            const script = document.createElement('script');
            script.src = fontes[indice];
            script.crossOrigin = 'anonymous';
            script.integrity = 'sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH';
            script.onload = iniciarMapa;
            script.onerror = () => carregarLeaflet(indice + 1);
            document.head.appendChild(script);
          }

          carregarLeaflet(0);
        </script></body></html>
        """


class MainWindow(QtWidgets.QMainWindow):
    PAGINAS = (
        ("Visão geral", "Execute e acompanhe as operações"),
        ("Área e período", "Escolha a região no mapa"),
        ("Dados e qualidade", "Ajuste STAC, bandas e filtros"),
        ("Google Drive", "Configure OAuth e sincronização"),
        ("Análise da região", "Consulte detecções, imagens e estatísticas"),
        ("Histórico", "Acesse análises e relatórios locais"),
        ("Configuração", "Revise YAML e perfis locais"),
    )

    def __init__(self) -> None:
        super().__init__()
        configurar_aplicacao(QtWidgets.QApplication.instance())
        self.setWindowTitle("Sentinel-2 MT • Central de Operações")
        self.resize(1480, 920)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(ESTILO)

        self.store = LocalConfigStore(LOCAL_DB)
        self.processo = QtCore.QProcess(self)
        self.processo.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.processo.readyReadStandardOutput.connect(self._ler_saida)
        self.processo.finished.connect(self._processo_finalizado)
        self.processo.errorOccurred.connect(self._erro_processo)
        self._saida_pendente = ""
        self._ultimo_resultado: dict[str, Any] | None = None
        self._operacao_em_execucao = ""
        self._resultado_pendente: Path | None = None

        self._criar_campos()
        self._montar_janela()
        self._conectar_eventos()
        self._atualizar_preview_yaml()
        self._recarregar_perfis()
        self._atualizar_operacao()

    def _criar_campos(self) -> None:
        self.nome_regiao = QtWidgets.QLineEdit("Mato Grosso")
        self.uf = QtWidgets.QLineEdit("MT")
        self.uf.setMaxLength(2)
        self.oeste = self._coordenada(-180, 180, -61.65)
        self.sul = self._coordenada(-90, 90, -18.05)
        self.leste = self._coordenada(-180, 180, -50.20)
        self.norte = self._coordenada(-90, 90, -7.30)

        self.inicio = QtWidgets.QDateEdit(QtCore.QDate(2025, 9, 1))
        self.fim = QtWidgets.QDateEdit(QtCore.QDate(2026, 4, 30))
        for campo in (self.inicio, self.fim):
            campo.setCalendarPopup(True)
            campo.setDisplayFormat("dd/MM/yyyy")

        self.colecao = QtWidgets.QLineEdit("S2-16D-2")
        self.stac_url = QtWidgets.QLineEdit("https://data.inpe.br/bdc/stac/v1/")
        self.bandas = QtWidgets.QLineEdit(
            "B02, B03, B04, B05, B06, B07, B08, B8A, B11, B12, NDVI, EVI"
        )
        self.filtrar_nuvens = QtWidgets.QCheckBox("Descartar cenas com nuvens/sombra")
        self.filtrar_nuvens.setChecked(True)
        self.manter_scl = QtWidgets.QCheckBox("Manter arquivo SCL")
        self.manter_scl.setChecked(True)
        self.gerar_rgb = QtWidgets.QCheckBox("Gerar preview RGB")
        self.gerar_rgb.setChecked(True)
        self.nuvem_max_pct = self._inteiro(0, 100, 40, "%")
        self.tamanho_max_px = self._inteiro(100, 5000, 1600, " px")
        self.qualidade_jpeg = self._inteiro(1, 100, 92, "%")
        self.gerar_dataset = QtWidgets.QCheckBox("Gerar dataset após o download")
        self.patch_tamanho_px = QtWidgets.QComboBox()
        self.patch_tamanho_px.addItem("512 px", 512)
        self.patch_tamanho_px.addItem("256 px", 256)
        self.patch_stride_px = self._inteiro(1, 4096, 512, " px")
        self.patch_nuvem_max_pct = self._inteiro(0, 100, 10, "%")
        self.dados_validos_min_pct = self._inteiro(0, 100, 90, "%")
        self.dataset_rgb_minimo = self._inteiro(-10000, 10000, 0)
        self.dataset_rgb_maximo = self._inteiro(-10000, 30000, 2000)

        self.modelo_ia = QtWidgets.QLineEdit("analise/models/best.pt")
        self.modelo_sha256 = QtWidgets.QLineEdit()
        self.modelo_sha256.setPlaceholderText("Opcional: SHA-256 do modelo aprovado")
        self.confianca_minima = self._inteiro(0, 100, 25, "%")
        self.iou_maximo = self._inteiro(0, 100, 45, "%")
        self.tamanho_inferencia_px = self._inteiro(128, 2048, 640, " px")
        self.pasta_analises = QtWidgets.QLineEdit("data/analises")
        self.historico_analises = QtWidgets.QLineEdit("data/historico-analises.sqlite3")
        self.gerar_relatorio = QtWidgets.QCheckBox("Gerar relatório PDF automaticamente")
        self.gerar_relatorio.setChecked(True)
        self.max_imagens_analise = self._inteiro(0, 10000, 1000)
        self.max_imagens_analise.setSpecialValueText("Todas")

        self.pasta_download = QtWidgets.QLineEdit("data/sentinel2")
        self.catalogo = QtWidgets.QLineEdit("catalogo/catalogo_imagens.csv")
        self.output_path = QtWidgets.QLineEdit(str(DEFAULT_CONFIG))
        self.timeout_segundos = self._inteiro(30, 600, 120, " s")
        self.chunk_mb = self._inteiro(1, 50, 1, " MB")
        self.max_itens_teste = self._inteiro(0, 1000, 5)
        self.max_candidatos_teste = self._inteiro(1, 1000, 40)

        self.oauth_json = QtWidgets.QLineEdit("${GOOGLE_OAUTH_JSON:-}")
        self.oauth_json.setPlaceholderText("Selecione o client_secret_*.json")
        self.token_json = QtWidgets.QLineEdit("${GOOGLE_TOKEN_JSON:-config/google-token.json}")
        self.pasta_remota = QtWidgets.QLineEdit("sentinel2-mt")
        self.pasta_id = QtWidgets.QLineEdit("${GOOGLE_PASTA_ID:-root}")
        self.tamanho_lote = self._inteiro(1, 1000, 100, " arquivos")

        self.operacao = QtWidgets.QComboBox()
        self.operacao.addItem("Catalogar sem baixar", "catalogar")
        self.operacao.addItem("Baixar imagens aprovadas", "baixar")
        self.operacao.addItem("Gerar dataset das cenas locais", "dataset")
        self.operacao.addItem("Analisar região com IA", "analisar")
        self.operacao.addItem("Sincronizar com Google Drive", "sincronizar")
        self.max_execucao = self._inteiro(0, 1000, 5)
        self.max_execucao.setSpecialValueText("Todas")

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(4000)
        self.yaml_preview = QtWidgets.QPlainTextEdit()
        self.yaml_preview.setReadOnly(True)
        self.perfis = QtWidgets.QTreeWidget()
        self.perfis.setHeaderLabel("Presets por região / UF")
        self.perfis.setAlternatingRowColors(True)
        self.perfis.setExpandsOnDoubleClick(True)
        self.imagem_preview = QtWidgets.QLabel("Nenhum preview selecionado")
        self.imagem_preview.setObjectName("previewImage")
        self.imagem_preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.imagem_preview.setMinimumHeight(210)
        self.analise_info = QtWidgets.QLabel("Execute 'Analisar região com IA' para ver os resultados.")
        self.analise_info.setWordWrap(True)
        self.analise_tabela = QtWidgets.QTableWidget(0, 5)
        self.analise_tabela.setHorizontalHeaderLabels(
            ["Classe", "Detecções", "Confiança média", "Mínima", "Máxima"]
        )
        self.analise_tabela.horizontalHeader().setStretchLastSection(True)
        self.analise_original = QtWidgets.QLabel("Imagem RGB original")
        self.analise_anotada = QtWidgets.QLabel("Imagem com detecções")
        for imagem in (self.analise_original, self.analise_anotada):
            imagem.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            imagem.setMinimumHeight(240)
        self.historico_tabela = QtWidgets.QTableWidget(0, 5)
        self.historico_tabela.setHorizontalHeaderLabels(
            ["Data", "Região", "Período", "Detecções", "Relatório"]
        )
        self.historico_tabela.horizontalHeader().setStretchLastSection(True)

    @staticmethod
    def _inteiro(minimo: int, maximo: int, valor: int, sufixo: str = "") -> ControleNumerico:
        return ControleNumerico(minimo, maximo, valor, sufixo)

    @staticmethod
    def _coordenada(minimo: float, maximo: float, valor: float) -> ControleNumerico:
        # Mantém a precisão de seis casas já suportada pela configuração e pelo mapa.
        return ControleNumerico(minimo, maximo, valor, "°", casas_decimais=6)

    def _montar_janela(self) -> None:
        raiz = QtWidgets.QWidget()
        raiz.setObjectName("root")
        estrutura = QtWidgets.QHBoxLayout(raiz)
        estrutura.setContentsMargins(0, 0, 0, 0)
        estrutura.setSpacing(0)
        estrutura.addWidget(self._criar_sidebar())

        area = QtWidgets.QWidget()
        layout_area = QtWidgets.QVBoxLayout(area)
        layout_area.setContentsMargins(28, 20, 28, 18)
        layout_area.setSpacing(16)
        layout_area.addLayout(self._criar_cabecalho())

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._pagina_visao_geral())
        self.stack.addWidget(self._pagina_area())
        self.stack.addWidget(self._pagina_dados())
        self.stack.addWidget(self._pagina_drive())
        self.stack.addWidget(self._pagina_analise())
        self.stack.addWidget(self._pagina_historico())
        self.stack.addWidget(self._pagina_config())
        layout_area.addWidget(self.stack, 1)
        layout_area.addWidget(self._barra_acoes())
        estrutura.addWidget(area, 1)
        self.setCentralWidget(raiz)

    def _criar_sidebar(self) -> QtWidgets.QFrame:
        painel = QtWidgets.QFrame()
        painel.setObjectName("sidebar")
        painel.setFixedWidth(230)
        layout = QtWidgets.QVBoxLayout(painel)
        layout.setContentsMargins(18, 22, 18, 20)
        layout.setSpacing(8)

        marca = QtWidgets.QHBoxLayout()
        simbolo = QtWidgets.QLabel("S2")
        simbolo.setObjectName("brandMark")
        simbolo.setFixedSize(40, 40)
        simbolo.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        textos = QtWidgets.QVBoxLayout()
        titulo = QtWidgets.QLabel("Sentinel-2 MT")
        titulo.setObjectName("brandTitle")
        subtitulo = QtWidgets.QLabel("Downloader & Sync")
        subtitulo.setObjectName("brandSub")
        textos.addWidget(titulo)
        textos.addWidget(subtitulo)
        marca.addWidget(simbolo)
        marca.addLayout(textos)
        layout.addLayout(marca)
        layout.addSpacing(24)

        self.grupo_navegacao = QtWidgets.QButtonGroup(self)
        self.grupo_navegacao.setExclusive(True)
        self.botoes_navegacao: list[QtWidgets.QPushButton] = []
        for indice, (nome, _) in enumerate(self.PAGINAS):
            item = botao(nome, "navButton")
            item.setCheckable(True)
            item.clicked.connect(lambda _=False, i=indice: self._navegar(i))
            self.grupo_navegacao.addButton(item, indice)
            self.botoes_navegacao.append(item)
            layout.addWidget(item)
        self.botoes_navegacao[0].setChecked(True)
        layout.addStretch()
        versao = QtWidgets.QLabel("API STAC INPE\nGoogle Drive OAuth")
        versao.setObjectName("brandSub")
        layout.addWidget(versao)
        return painel

    def _criar_cabecalho(self) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        textos = QtWidgets.QVBoxLayout()
        self.titulo_pagina = QtWidgets.QLabel(self.PAGINAS[0][0])
        self.titulo_pagina.setObjectName("pageTitle")
        self.subtitulo_pagina = QtWidgets.QLabel(self.PAGINAS[0][1])
        self.subtitulo_pagina.setObjectName("pageSubtitle")
        textos.addWidget(self.titulo_pagina)
        textos.addWidget(self.subtitulo_pagina)
        layout.addLayout(textos)
        layout.addStretch()
        self.status = QtWidgets.QLabel("Pronto")
        self.status.setObjectName("statusChip")
        layout.addWidget(self.status)
        return layout

    def _pagina_visao_geral(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        topo = QtWidgets.QHBoxLayout()
        operacao = Cartao("Nova operação", "A configuração é salva automaticamente antes da execução.")
        form = QtWidgets.QFormLayout()
        form.addRow("Operação", self.operacao)
        form.addRow(
            rotulo_com_ajuda(
                "Máximo de cenas", "Limita quantas cenas serão processadas; em 'Todas', não há limite."
            ),
            self.max_execucao,
        )
        self.resumo_operacao = QtWidgets.QLabel()
        self.resumo_operacao.setWordWrap(True)
        self.resumo_operacao.setObjectName("cardHelp")
        operacao.layout_principal.addLayout(form)
        operacao.layout_principal.addWidget(self.resumo_operacao)
        topo.addWidget(operacao, 2)

        destinos = Cartao("Arquivos locais", "Abra rapidamente a pasta de imagens ou um preview RGB.")
        linha = QtWidgets.QHBoxLayout()
        abrir_pasta = botao("Abrir pasta de imagens")
        abrir_pasta.clicked.connect(self._abrir_pasta_imagens)
        abrir_preview = botao("Visualizar preview")
        abrir_preview.clicked.connect(self._abrir_imagem_preview)
        linha.addWidget(abrir_pasta)
        linha.addWidget(abrir_preview)
        destinos.layout_principal.addLayout(linha)
        topo.addWidget(destinos, 2)
        layout.addLayout(topo)

        divisor = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        log_card = Cartao("Saída da operação", "Acompanhe downloads, lotes e autenticação em tempo real.")
        log_card.layout_principal.addWidget(self.log, 1)
        divisor.addWidget(log_card)
        preview_card = Cartao("Preview da cena")
        preview_card.layout_principal.addWidget(self.imagem_preview, 1)
        divisor.addWidget(preview_card)
        divisor.setSizes([760, 390])
        layout.addWidget(divisor, 1)
        return pagina

    def _pagina_area(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        bbox_inicial = [self.oeste.value(), self.sul.value(), self.leste.value(), self.norte.value()]
        self.mapa = MapaWidget(bbox_inicial, self)
        mapa_card = Cartao("Área de interesse", "Navegue normalmente; use Shift + arraste para desenhar.")
        mapa_card.layout_principal.addWidget(self.mapa, 1)
        aplicar = botao("Aplicar seleção do mapa", "primaryButton")
        aplicar.clicked.connect(self.mapa.capturar_bbox)
        mapa_card.layout_principal.addWidget(aplicar)
        layout.addWidget(mapa_card, 3)

        detalhes = Cartao("Região e período", "As coordenadas usam a ordem oeste, sul, leste, norte.")
        form = QtWidgets.QFormLayout()
        form.addRow("Nome", self.nome_regiao)
        form.addRow("UF", self.uf)
        form.addRow("Data inicial", self.inicio)
        form.addRow("Data final", self.fim)
        form.addRow(rotulo_com_ajuda("Oeste", "Longitude do limite oeste da área."), self.oeste)
        form.addRow(rotulo_com_ajuda("Sul", "Latitude do limite sul da área."), self.sul)
        form.addRow(rotulo_com_ajuda("Leste", "Longitude do limite leste da área."), self.leste)
        form.addRow(rotulo_com_ajuda("Norte", "Latitude do limite norte da área."), self.norte)
        detalhes.layout_principal.addLayout(form)
        salvar_perfil = botao("Salvar como perfil local")
        salvar_perfil.clicked.connect(self._salvar_perfil)
        detalhes.layout_principal.addWidget(salvar_perfil)
        detalhes.layout_principal.addStretch()
        layout.addWidget(detalhes, 1)
        return pagina

    def _pagina_dados(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        fonte = Cartao("Fonte STAC", "Catálogo público do INPE/Brazil Data Cube.")
        form_fonte = QtWidgets.QFormLayout()
        form_fonte.addRow("URL STAC", self.stac_url)
        form_fonte.addRow("Coleção", self.colecao)
        form_fonte.addRow("Bandas", self.bandas)
        form_fonte.addRow("Pasta de download", self.pasta_download)
        form_fonte.addRow("Catálogo CSV", self.catalogo)
        form_fonte.addRow(rotulo_com_ajuda("Timeout", "Tempo máximo de espera por uma resposta do servidor."), self.timeout_segundos)
        form_fonte.addRow(rotulo_com_ajuda("Chunk", "Tamanho de cada bloco usado ao baixar arquivos."), self.chunk_mb)
        form_fonte.addRow(rotulo_com_ajuda("Cenas padrão", "Quantidade de cenas usada em execuções de teste."), self.max_itens_teste)
        form_fonte.addRow(rotulo_com_ajuda("Candidatos máximos", "Limite de cenas avaliadas antes de aplicar os filtros."), self.max_candidatos_teste)
        fonte.layout_principal.addLayout(form_fonte)
        fonte.layout_principal.addStretch()
        layout.addWidget(fonte, 1)

        qualidade = Cartao("Qualidade e visualização", "Filtre antes de baixar as bandas científicas maiores.")
        form_qualidade = QtWidgets.QFormLayout()
        form_qualidade.addRow(self.filtrar_nuvens)
        form_qualidade.addRow(rotulo_com_ajuda("Limite de nuvens", "Descarta cenas cuja cobertura de nuvens exceda este percentual."), self.nuvem_max_pct)
        form_qualidade.addRow(self.manter_scl)
        form_qualidade.addRow(self.gerar_rgb)
        form_qualidade.addRow(rotulo_com_ajuda("Tamanho do preview", "Maior dimensão em pixels da imagem RGB de prévia."), self.tamanho_max_px)
        form_qualidade.addRow(rotulo_com_ajuda("Qualidade JPEG", "Qualidade de compressão das prévias RGB; valores maiores geram arquivos maiores."), self.qualidade_jpeg)
        form_qualidade.addRow(self.gerar_dataset)
        form_qualidade.addRow("Tamanho do patch", self.patch_tamanho_px)
        form_qualidade.addRow(rotulo_com_ajuda("Stride do patch", "Distância entre patches consecutivos; menor que o tamanho do patch cria sobreposição."), self.patch_stride_px)
        form_qualidade.addRow(rotulo_com_ajuda("Nuvem máxima por patch", "Descarta patches cuja proporção de nuvens exceda este percentual."), self.patch_nuvem_max_pct)
        form_qualidade.addRow(rotulo_com_ajuda("Dados válidos mínimos", "Mantém somente patches com pelo menos este percentual de pixels válidos."), self.dados_validos_min_pct)
        form_qualidade.addRow(rotulo_com_ajuda("RGB dataset mínimo", "Limite inferior para converter valores científicos em RGB."), self.dataset_rgb_minimo)
        form_qualidade.addRow(rotulo_com_ajuda("RGB dataset máximo", "Limite superior para converter valores científicos em RGB."), self.dataset_rgb_maximo)
        form_qualidade.addRow("Modelo agrícola", self.modelo_ia)
        form_qualidade.addRow("SHA-256 do modelo", self.modelo_sha256)
        form_qualidade.addRow(rotulo_com_ajuda("Confiança mínima", "Detecções abaixo deste limiar não entram nos resultados."), self.confianca_minima)
        form_qualidade.addRow(rotulo_com_ajuda("IoU máximo", "Controla a supressão de caixas sobrepostas pelo modelo."), self.iou_maximo)
        form_qualidade.addRow("Tamanho da inferência", self.tamanho_inferencia_px)
        form_qualidade.addRow("Pasta das análises", self.pasta_analises)
        form_qualidade.addRow("Histórico local", self.historico_analises)
        form_qualidade.addRow(self.gerar_relatorio)
        form_qualidade.addRow(rotulo_com_ajuda("Imagens por análise", "Zero processa todos os patches aprovados do período."), self.max_imagens_analise)
        qualidade.layout_principal.addLayout(form_qualidade)
        qualidade.layout_principal.addStretch()
        layout.addWidget(qualidade, 1)
        return pagina

    def _pagina_drive(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        credenciais = Cartao(
            "OAuth do Google",
            "Escolha o JSON de aplicativo para computador. O token será criado e reutilizado automaticamente.",
        )
        escolher = botao("Selecionar JSON OAuth")
        escolher.clicked.connect(self._selecionar_oauth)
        linha_oauth = QtWidgets.QHBoxLayout()
        linha_oauth.addWidget(self.oauth_json, 1)
        linha_oauth.addWidget(escolher)
        form = QtWidgets.QFormLayout()
        form.addRow("Credencial OAuth", linha_oauth)
        form.addRow("Token local", self.token_json)
        credenciais.layout_principal.addLayout(form)
        layout.addWidget(credenciais)

        destino = Cartao("Destino e lotes", "A hierarquia local de datas e cenas é preservada no Drive.")
        form_destino = QtWidgets.QFormLayout()
        form_destino.addRow("Nome da pasta remota", self.pasta_remota)
        form_destino.addRow("ID da pasta pai", self.pasta_id)
        form_destino.addRow(rotulo_com_ajuda("Tamanho do lote", "Número de arquivos enviados ao Google Drive por lote."), self.tamanho_lote)
        destino.layout_principal.addLayout(form_destino)
        layout.addWidget(destino)

        nota = QtWidgets.QLabel(
            "Privacidade: a aplicação solicita o escopo drive.file, limitado aos arquivos "
            "criados ou abertos pelo próprio aplicativo. Se o projeto OAuth estiver em modo "
            "de teste, a conta Google usada no login precisa estar cadastrada como usuário de "
            "teste pelo proprietário do JSON. Credenciais não são salvas nos perfis de região."
        )
        nota.setWordWrap(True)
        nota.setObjectName("pageSubtitle")
        layout.addWidget(nota)
        layout.addStretch()
        return pagina

    def _pagina_config(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        config = Cartao("config.yaml", "Revise o conteúdo antes de salvar ou executar.")
        caminho_linha = QtWidgets.QHBoxLayout()
        caminho_linha.addWidget(self.output_path, 1)
        escolher = botao("Escolher arquivo")
        escolher.clicked.connect(self._selecionar_config)
        caminho_linha.addWidget(escolher)
        config.layout_principal.addLayout(caminho_linha)
        config.layout_principal.addWidget(self.yaml_preview, 1)
        atualizar = botao("Atualizar prévia")
        atualizar.clicked.connect(self._atualizar_preview_yaml)
        config.layout_principal.addWidget(atualizar)
        layout.addWidget(config, 2)

        perfis = Cartao("Perfis de região", "Salvos apenas neste computador em um banco SQLite local.")
        perfis.layout_principal.addWidget(self.perfis, 1)
        linha = QtWidgets.QHBoxLayout()
        carregar = botao("Carregar")
        carregar.clicked.connect(self._carregar_perfil)
        excluir = botao("Excluir", "dangerButton")
        excluir.clicked.connect(self._excluir_perfil)
        linha.addWidget(carregar)
        linha.addWidget(excluir)
        perfis.layout_principal.addLayout(linha)
        layout.addWidget(perfis, 1)
        return pagina

    def _pagina_analise(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        resumo = Cartao(
            "Análise da região",
            "As contagens vêm de caixas detectadas; caixas não equivalem à área real dos talhões.",
        )
        resumo.layout_principal.addWidget(self.analise_info)
        resumo.layout_principal.addWidget(self.analise_tabela)
        layout.addWidget(resumo, 1)

        imagens = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        original = Cartao("Imagem RGB original")
        original.layout_principal.addWidget(self.analise_original, 1)
        analisada = Cartao("Imagem com detecções")
        analisada.layout_principal.addWidget(self.analise_anotada, 1)
        imagens.addWidget(original)
        imagens.addWidget(analisada)
        layout.addWidget(imagens, 2)
        self.btn_relatorio = botao("Abrir relatório PDF", "primaryButton")
        self.btn_relatorio.setEnabled(False)
        self.btn_relatorio.clicked.connect(self._abrir_relatorio_analise)
        layout.addWidget(self.btn_relatorio, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        return pagina

    def _pagina_historico(self) -> QtWidgets.QWidget:
        pagina = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(pagina)
        layout.setContentsMargins(0, 0, 0, 0)
        cartao = Cartao(
            "Histórico local",
            "O banco guarda somente metadados e caminhos; GeoTIFFs permanecem fora do SQLite.",
        )
        cartao.layout_principal.addWidget(self.historico_tabela, 1)
        atualizar = botao("Atualizar histórico")
        atualizar.clicked.connect(self._recarregar_historico)
        cartao.layout_principal.addWidget(atualizar)
        layout.addWidget(cartao)
        return pagina

    def _barra_acoes(self) -> QtWidgets.QWidget:
        barra = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(barra)
        layout.setContentsMargins(0, 0, 0, 0)
        self.progresso = QtWidgets.QProgressBar()
        self.progresso.setTextVisible(False)
        self.progresso.setFixedWidth(180)
        self.progresso.setRange(0, 1)
        self.progresso.setValue(0)
        layout.addWidget(self.progresso)
        layout.addStretch()
        self.btn_salvar = botao("Salvar configuração")
        self.btn_cancelar = botao("Cancelar", "dangerButton")
        self.btn_cancelar.setEnabled(False)
        self.btn_executar = botao("Executar operação", "primaryButton")
        layout.addWidget(self.btn_salvar)
        layout.addWidget(self.btn_cancelar)
        layout.addWidget(self.btn_executar)
        return barra

    def _conectar_eventos(self) -> None:
        self.mapa.areaSelecionada.connect(self._receber_bbox)
        self.operacao.currentIndexChanged.connect(self._atualizar_operacao)
        self.btn_salvar.clicked.connect(self._salvar_configuracao)
        self.btn_executar.clicked.connect(self._executar)
        self.btn_cancelar.clicked.connect(self._cancelar)
        self.historico_tabela.doubleClicked.connect(self._abrir_relatorio_historico)

    def _navegar(self, indice: int) -> None:
        self.stack.setCurrentIndex(indice)
        self.titulo_pagina.setText(self.PAGINAS[indice][0])
        self.subtitulo_pagina.setText(self.PAGINAS[indice][1])
        if indice == 1:
            QtCore.QTimer.singleShot(0, self.mapa.reativar)
            QtCore.QTimer.singleShot(200, self.mapa.reativar)
        elif indice == 5:
            self._recarregar_historico()

    def _atualizar_operacao(self) -> None:
        operacao = self.operacao.currentData()
        mensagens = {
            "catalogar": "Consulta o INPE e atualiza o catálogo CSV sem baixar GeoTIFFs.",
            "baixar": "Filtra nuvens, baixa as bandas aprovadas e gera previews RGB.",
            "dataset": "Reutiliza GeoTIFFs locais e gera patches científicos e RGB PNG.",
            "analisar": "Baixa e processa cenas, executa o detector agrícola e gera resultados locais.",
            "sincronizar": "Envia as imagens locais ao Google Drive em lotes configuráveis.",
        }
        self.resumo_operacao.setText(mensagens[str(operacao)])
        self.max_execucao.setEnabled(operacao != "sincronizar")
        self.max_execucao.setToolTip(
            "Não se aplica à sincronização."
            if operacao == "sincronizar"
            else "Limite de cenas desta operação; zero processa todas."
        )

    def _coletar_dados(self) -> dict[str, Any]:
        bbox = normalizar_bbox(
            [self.oeste.value(), self.sul.value(), self.leste.value(), self.norte.value()]
        )
        bandas = [banda.strip() for banda in self.bandas.text().split(",") if banda.strip()]
        return {
            "bbox": bbox,
            "nome_regiao": self.nome_regiao.text().strip() or "Região personalizada",
            "uf": self.uf.text().strip().upper() or "MT",
            "colecao": self.colecao.text().strip() or "S2-16D-2",
            "stac_url": self.stac_url.text().strip() or "https://data.inpe.br/bdc/stac/v1/",
            "inicio": self.inicio.date().toString(QtCore.Qt.DateFormat.ISODate),
            "fim": self.fim.date().toString(QtCore.Qt.DateFormat.ISODate),
            "bandas": bandas or GeradorConfiguracao.BANDAS_PADRAO,
            "filtrar_nuvens": self.filtrar_nuvens.isChecked(),
            "manter_scl": self.manter_scl.isChecked(),
            "gerar_rgb": self.gerar_rgb.isChecked(),
            "nuvem_max_pct": self.nuvem_max_pct.value(),
            "pasta_download": self.pasta_download.text().strip() or "data/sentinel2",
            "catalogo": self.catalogo.text().strip() or "catalogo/catalogo_imagens.csv",
            "tamanho_max_px": self.tamanho_max_px.value(),
            "qualidade_jpeg": self.qualidade_jpeg.value(),
            "gerar_dataset": self.gerar_dataset.isChecked(),
            "patch_tamanho_px": int(self.patch_tamanho_px.currentData()),
            "patch_stride_px": self.patch_stride_px.value(),
            "patch_nuvem_max_pct": self.patch_nuvem_max_pct.value(),
            "dados_validos_min_pct": self.dados_validos_min_pct.value(),
            "dataset_rgb_metodo": "fixed",
            "dataset_rgb_minimo": self.dataset_rgb_minimo.value(),
            "dataset_rgb_maximo": self.dataset_rgb_maximo.value(),
            "modelo_ia": self.modelo_ia.text().strip() or "analise/models/best.pt",
            "modelo_sha256": self.modelo_sha256.text().strip().lower(),
            "confianca_minima": self.confianca_minima.value() / 100.0,
            "iou_maximo": self.iou_maximo.value() / 100.0,
            "tamanho_inferencia_px": self.tamanho_inferencia_px.value(),
            "pasta_analises": self.pasta_analises.text().strip() or "data/analises",
            "historico_analises": self.historico_analises.text().strip()
            or "data/historico-analises.sqlite3",
            "gerar_relatorio": self.gerar_relatorio.isChecked(),
            "max_imagens_analise": self.max_imagens_analise.value(),
            "timeout_segundos": self.timeout_segundos.value(),
            "chunk_mb": self.chunk_mb.value(),
            "max_itens_teste": self.max_itens_teste.value(),
            "max_candidatos_teste": self.max_candidatos_teste.value(),
            "pasta_remota": self.pasta_remota.text().strip() or "sentinel2-mt",
            "oauth_json": self.oauth_json.text().strip() or "${GOOGLE_OAUTH_JSON:-}",
            "token_json": self.token_json.text().strip()
            or "${GOOGLE_TOKEN_JSON:-config/google-token.json}",
            "pasta_id": self.pasta_id.text().strip() or "${GOOGLE_PASTA_ID:-root}",
            "tamanho_lote": self.tamanho_lote.value(),
            "extensoes": [".tif", ".tiff", ".jpg", ".jpeg"],
        }

    def _atualizar_preview_yaml(self) -> None:
        try:
            payload = gerar_config(self._coletar_dados())
            self.yaml_preview.setPlainText(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
            )
        except (TypeError, ValueError) as erro:
            self.yaml_preview.setPlainText(f"Configuração inválida: {erro}")

    def _salvar_configuracao(self, avisar: bool = True) -> Path | None:
        try:
            destino = persistir_config(
                self.output_path.text().strip() or DEFAULT_CONFIG,
                self._coletar_dados(),
            )
            self._atualizar_preview_yaml()
            self.status.setText("Configuração salva")
            if avisar:
                self.statusBar().showMessage(f"Configuração salva em {destino}", 5000)
            return destino
        except Exception as erro:
            QtWidgets.QMessageBox.critical(self, "Configuração inválida", str(erro))
            return None

    def _executar(self) -> None:
        if self.processo.state() != QtCore.QProcess.ProcessState.NotRunning:
            return
        config = self._salvar_configuracao(avisar=False)
        if config is None:
            return
        try:
            argumentos = montar_argumentos_operacao(
                str(self.operacao.currentData()),
                config,
                inicio=self.inicio.date().toString(QtCore.Qt.DateFormat.ISODate),
                fim=self.fim.date().toString(QtCore.Qt.DateFormat.ISODate),
                max_itens=self.max_execucao.value(),
                oauth_json=self.oauth_json.text().strip(),
                tamanho_lote=self.tamanho_lote.value(),
                patch_size=int(self.patch_tamanho_px.currentData()),
                patch_stride=self.patch_stride_px.value(),
            )
        except (FileNotFoundError, TypeError, ValueError) as erro:
            QtWidgets.QMessageBox.warning(self, "Não foi possível executar", str(erro))
            return

        self.log.clear()
        self._saida_pendente = ""
        self._resultado_pendente = None
        self._operacao_em_execucao = str(self.operacao.currentData())
        programa, argumentos_processo, diretorio = comando_cli_empacotado(argumentos)
        self.log.appendPlainText(
            f"$ {shlex.join([programa, *argumentos_processo])}\n"
        )
        self._definir_execucao(True, "Executando")
        self.processo.setWorkingDirectory(str(diretorio))
        self.processo.start(programa, argumentos_processo)

    def _ler_saida(self) -> None:
        texto = bytes(self.processo.readAllStandardOutput()).decode("utf-8", errors="replace")
        if texto:
            cursor = self.log.textCursor()
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
            cursor.insertText(texto)
            self.log.setTextCursor(cursor)
            self.log.ensureCursorVisible()
            self._saida_pendente += texto
            while "\n" in self._saida_pendente:
                linha, self._saida_pendente = self._saida_pendente.split("\n", 1)
                self._processar_linha_resultado(linha)

    def _processo_finalizado(self, codigo: int, _status) -> None:
        if self._saida_pendente:
            self._processar_linha_resultado(self._saida_pendente)
            self._saida_pendente = ""
        if codigo == 0 and self._resultado_pendente is not None:
            try:
                self._carregar_resultado_analise(self._resultado_pendente)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as erro:
                self.log.appendPlainText(f"\n[ERRO] Resultado da análise inválido: {erro}")
            finally:
                self._resultado_pendente = None
        mensagem = "Concluído" if codigo == 0 else f"Encerrado com código {codigo}"
        self.log.appendPlainText(f"\n[{mensagem}]")
        self._definir_execucao(False, mensagem)

    def _processar_linha_resultado(self, linha: str) -> None:
        marcador = "[ANALISE_RESULTADO] "
        if self._operacao_em_execucao != "analisar" or not linha.startswith(marcador):
            return
        caminho = Path(linha[len(marcador):].strip()).expanduser()
        if caminho.is_absolute() or ".." in caminho.parts or caminho.suffix.lower() != ".json":
            return
        self._resultado_pendente = ROOT / caminho

    def _carregar_resultado_analise(self, caminho: Path) -> None:
        _, raiz_analises = self._raizes_artefatos()
        caminho = self._resolver_em_raiz(caminho, raiz_analises, {".json"})
        if caminho.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("resultado.json excede o limite de 10 MB")
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(dados, dict) or "estatisticas" not in dados:
            raise ValueError("estrutura JSON inesperada")
        self._ultimo_resultado = dados
        estatisticas = dados["estatisticas"]
        periodo = f"{dados.get('periodo_inicio', '—')} a {dados.get('periodo_fim', '—')}"
        self.analise_info.setText(
            f"Região: {dados.get('regiao', '—')}\nPeríodo: {periodo}\n"
            f"Cenas: {', '.join(dados.get('scene_ids', [])) or '—'}\n"
            f"Dispositivo de processamento: {dados.get('dispositivo', '—')}\n"
            f"Detecções: {estatisticas.get('total_deteccoes', 0)}"
        )
        por_classe = estatisticas.get("por_classe", {})
        self.analise_tabela.setRowCount(len(por_classe))
        for linha, classe in enumerate(sorted(por_classe)):
            valores = (
                classe,
                str(por_classe[classe]),
                self._percentual_confianca(estatisticas.get("confianca_media_por_classe", {}).get(classe)),
                self._percentual_confianca(estatisticas.get("confianca_minima_por_classe", {}).get(classe)),
                self._percentual_confianca(estatisticas.get("confianca_maxima_por_classe", {}).get(classe)),
            )
            for coluna, valor in enumerate(valores):
                self.analise_tabela.setItem(linha, coluna, QtWidgets.QTableWidgetItem(valor))
        raiz_dataset, raiz_analises = self._raizes_artefatos()
        self._exibir_imagem_resultado(
            self.analise_original, dados.get("imagem_original", ""), raiz_dataset
        )
        self._exibir_imagem_resultado(
            self.analise_anotada, dados.get("imagem_analisada", ""), raiz_analises
        )
        relatorio = self._resolver_em_raiz_opcional(
            dados.get("caminho_relatorio", ""), raiz_analises, {".pdf"}
        )
        self.btn_relatorio.setEnabled(bool(relatorio and relatorio.is_file()))
        self._navegar(4)
        self._recarregar_historico()

    @staticmethod
    def _percentual_confianca(valor: object) -> str:
        return "—" if valor is None else f"{float(valor) * 100:.1f}%"

    def _raizes_artefatos(self) -> tuple[Path, Path]:
        config_path = Path(self.output_path.text().strip() or DEFAULT_CONFIG)
        config = ConfiguracaoProjeto.carregar(config_path, raiz=ROOT)
        return (
            config.caminho(config.dataset.pasta).resolve(),
            config.caminho(config.analise.pasta).resolve(),
        )

    @staticmethod
    def _resolver_em_raiz(valor: object, raiz: Path, sufixos: set[str]) -> Path:
        caminho = Path(str(valor)).expanduser()
        caminho = caminho if caminho.is_absolute() else ROOT / caminho
        if caminho.is_symlink():
            raise ValueError("Links simbólicos não são aceitos para artefatos")
        resolvido = caminho.resolve()
        try:
            resolvido.relative_to(raiz.resolve())
        except ValueError as exc:
            raise ValueError("Artefato fora da raiz permitida") from exc
        if resolvido.is_symlink() or not resolvido.is_file() or resolvido.suffix.lower() not in sufixos:
            raise ValueError("Artefato ausente ou inválido")
        return resolvido

    def _resolver_em_raiz_opcional(
        self, valor: object, raiz: Path, sufixos: set[str]
    ) -> Path | None:
        if not valor:
            return None
        try:
            return self._resolver_em_raiz(valor, raiz, sufixos)
        except ValueError:
            return None

    def _exibir_imagem_resultado(
        self, rotulo: QtWidgets.QLabel, valor: object, raiz: Path
    ) -> None:
        caminho = self._resolver_em_raiz_opcional(
            valor, raiz, {".png", ".jpg", ".jpeg"}
        )
        imagem = QtGui.QPixmap(str(caminho)) if caminho else QtGui.QPixmap()
        if imagem.isNull():
            rotulo.setText("Imagem indisponível")
            rotulo.setPixmap(QtGui.QPixmap())
            return
        rotulo.setPixmap(
            imagem.scaled(
                560, 360, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _abrir_relatorio_analise(self) -> None:
        if not self._ultimo_resultado:
            return
        _, raiz_analises = self._raizes_artefatos()
        caminho = self._resolver_em_raiz_opcional(
            self._ultimo_resultado.get("caminho_relatorio", ""), raiz_analises, {".pdf"}
        )
        if caminho and caminho.is_file():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(caminho)))

    def _recarregar_historico(self) -> None:
        self.historico_tabela.setRowCount(0)
        try:
            config_path = Path(self.output_path.text().strip() or DEFAULT_CONFIG)
            if not config_path.is_file():
                return
            config = ConfiguracaoProjeto.carregar(config_path, raiz=ROOT)
            banco = config.caminho(config.analise.historico)
            if not banco.is_file():
                return
            registros = RepositorioHistoricoAnalises(banco, ROOT).listar(limite=200)
        except (OSError, TypeError, ValueError):
            return
        self.historico_tabela.setRowCount(len(registros))
        for linha, registro in enumerate(registros):
            resumo = registro.resumo if isinstance(registro.resumo, dict) else {}
            valores = (
                registro.criado_em,
                registro.regiao,
                f"{registro.periodo_inicio} a {registro.periodo_fim}",
                str(resumo.get("total_deteccoes", 0)),
                registro.report_path or "—",
            )
            for coluna, valor in enumerate(valores):
                item = QtWidgets.QTableWidgetItem(valor)
                if coluna == 4:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, registro.report_path)
                self.historico_tabela.setItem(linha, coluna, item)

    def _abrir_relatorio_historico(self, indice: QtCore.QModelIndex) -> None:
        item = self.historico_tabela.item(indice.row(), 4)
        _, raiz_analises = self._raizes_artefatos()
        caminho = self._resolver_em_raiz_opcional(
            item.data(QtCore.Qt.ItemDataRole.UserRole) if item else "",
            raiz_analises,
            {".pdf"},
        )
        if caminho and caminho.is_file():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(caminho)))

    def _erro_processo(self, erro) -> None:
        if erro == QtCore.QProcess.ProcessError.FailedToStart:
            self.log.appendPlainText("\n[ERRO] Não foi possível iniciar o processo Python.")
            self._definir_execucao(False, "Falha ao iniciar")

    def _definir_execucao(self, executando: bool, mensagem: str) -> None:
        self.btn_executar.setEnabled(not executando)
        self.btn_salvar.setEnabled(not executando)
        self.btn_cancelar.setEnabled(executando)
        # A operação em andamento já recebeu uma cópia dos argumentos. Manter estes
        # controles ativos evita perda de contraste e permite preparar a próxima fila.
        self.operacao.setEnabled(True)
        self._atualizar_operacao()
        self.progresso.setRange(0, 0 if executando else 1)
        if not executando:
            self.progresso.setValue(0)
        self.status.setText(mensagem)

    def _cancelar(self) -> None:
        if self.processo.state() == QtCore.QProcess.ProcessState.NotRunning:
            return
        self.status.setText("Cancelando…")
        self.processo.terminate()
        QtCore.QTimer.singleShot(3000, self._forcar_cancelamento)

    def _forcar_cancelamento(self) -> None:
        if self.processo.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.processo.kill()

    def _receber_bbox(self, bbox: object) -> None:
        if not isinstance(bbox, list):
            self.statusBar().showMessage("Desenhe uma área com Shift + arraste no mapa.", 5000)
            return
        try:
            oeste, sul, leste, norte = normalizar_bbox(bbox)
        except (TypeError, ValueError) as erro:
            self.statusBar().showMessage(str(erro), 5000)
            return
        self.oeste.setValue(oeste)
        self.sul.setValue(sul)
        self.leste.setValue(leste)
        self.norte.setValue(norte)
        self.statusBar().showMessage("Área do mapa aplicada à configuração.", 4000)

    def _salvar_perfil(self) -> None:
        try:
            item_id = self.store.salvar(self._coletar_dados())
            self._recarregar_perfis()
            self.statusBar().showMessage(f"Perfil local #{item_id} salvo.", 5000)
        except Exception as erro:
            QtWidgets.QMessageBox.critical(self, "Erro ao salvar perfil", str(erro))

    def _recarregar_perfis(self) -> None:
        self.perfis.clear()
        grupos = self.store.listar_por_uf()
        if not grupos:
            vazio = QtWidgets.QTreeWidgetItem(["Nenhum preset salvo"])
            vazio.setDisabled(True)
            self.perfis.addTopLevelItem(vazio)
            return

        for uf, perfis in grupos.items():
            grupo = QtWidgets.QTreeWidgetItem([uf])
            grupo.setExpanded(True)
            for perfil in perfis:
                item = QtWidgets.QTreeWidgetItem([perfil["nome_regiao"]])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, perfil["id"])
                grupo.addChild(item)
            self.perfis.addTopLevelItem(grupo)

    def _perfil_selecionado(self) -> dict[str, Any] | None:
        item = self.perfis.currentItem()
        if item is None:
            return None
        if item.childCount() > 0:
            item = item.child(0)
        perfil_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if perfil_id is None:
            return None
        return self.store.carregar(int(perfil_id))

    def _carregar_perfil(self) -> None:
        perfil = self._perfil_selecionado()
        if perfil is None:
            self.statusBar().showMessage("Selecione um perfil para carregar.", 4000)
            return
        self._aplicar_dados(json.loads(perfil["payload"]))
        self.statusBar().showMessage(f"Perfil '{perfil['nome_regiao']}' carregado.", 5000)

    def _excluir_perfil(self) -> None:
        perfil = self._perfil_selecionado()
        if perfil is None:
            self.statusBar().showMessage("Selecione um perfil para excluir.", 4000)
            return
        resposta = QtWidgets.QMessageBox.question(
            self,
            "Excluir perfil",
            f"Excluir o perfil '{perfil['nome_regiao']}'?",
        )
        if resposta == QtWidgets.QMessageBox.StandardButton.Yes:
            self.store.excluir(int(perfil["id"]))
            self._recarregar_perfis()

    def _aplicar_dados(self, dados: dict[str, Any]) -> None:
        self.nome_regiao.setText(str(dados.get("nome_regiao", self.nome_regiao.text())))
        self.uf.setText(str(dados.get("uf", self.uf.text())))
        self.colecao.setText(str(dados.get("colecao", self.colecao.text())))
        self.stac_url.setText(str(dados.get("stac_url", self.stac_url.text())))
        self.bandas.setText(", ".join(dados.get("bandas", [])) or self.bandas.text())
        for campo, chave in ((self.inicio, "inicio"), (self.fim, "fim")):
            data = QtCore.QDate.fromString(str(dados.get(chave, "")), QtCore.Qt.DateFormat.ISODate)
            if data.isValid():
                campo.setDate(data)
        bbox = normalizar_bbox(dados.get("bbox", self._bbox_atual()))
        self.oeste.setValue(bbox[0])
        self.sul.setValue(bbox[1])
        self.leste.setValue(bbox[2])
        self.norte.setValue(bbox[3])
        self.mapa.exibir_bbox(bbox)
        self._atualizar_preview_yaml()

    def _bbox_atual(self) -> list[float]:
        return [self.oeste.value(), self.sul.value(), self.leste.value(), self.norte.value()]

    def _selecionar_oauth(self) -> None:
        caminho, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Selecione o JSON OAuth", str(ROOT / "config"), "Arquivos JSON (*.json)"
        )
        if caminho:
            self.oauth_json.setText(caminho)

    def _selecionar_config(self) -> None:
        caminho, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Salvar configuração", self.output_path.text(), "YAML (*.yaml *.yml)"
        )
        if caminho:
            self.output_path.setText(caminho)

    def _abrir_pasta_imagens(self) -> None:
        pasta = Path(self.pasta_download.text().strip() or "data/sentinel2").expanduser()
        if not pasta.is_absolute():
            pasta = ROOT / pasta
        pasta.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(pasta)))

    def _abrir_imagem_preview(self) -> None:
        caminho, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Abrir preview",
            str(ROOT / (self.pasta_download.text().strip() or "data/sentinel2")),
            "Imagens (*.png *.jpg *.jpeg *.bmp)",
        )
        if not caminho:
            return
        imagem = QtGui.QPixmap(caminho)
        if imagem.isNull():
            self.statusBar().showMessage("Não foi possível carregar a imagem.", 5000)
            return
        self.imagem_preview.setPixmap(
            imagem.scaled(
                520,
                380,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )

    def closeEvent(self, evento: QtGui.QCloseEvent) -> None:
        if self.processo.state() != QtCore.QProcess.ProcessState.NotRunning:
            resposta = QtWidgets.QMessageBox.question(
                self, "Operação em andamento", "Cancelar a operação e sair?"
            )
            if resposta != QtWidgets.QMessageBox.StandardButton.Yes:
                evento.ignore()
                return
            self.processo.kill()
            self.processo.waitForFinished(1500)
        evento.accept()


def main(argv: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    smoke_test = "--smoke-test" in argumentos
    argumentos_qt = [sys.argv[0], *(arg for arg in argumentos if arg != "--smoke-test")]
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argumentos_qt)
    app.setApplicationName("Sentinel-2 MT")
    app.setOrganizationName("Sentinel2 MT")
    configurar_aplicacao(app)
    janela = MainWindow()
    janela.show()
    if smoke_test:
        QtCore.QTimer.singleShot(1200, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
