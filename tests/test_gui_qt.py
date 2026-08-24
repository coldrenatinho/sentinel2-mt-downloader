from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch

import yaml


PYSIDE_DISPONIVEL = importlib.util.find_spec("PySide6") is not None

if PYSIDE_DISPONIVEL:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtWidgets

    import gerar_config_gui as gui


@skipUnless(PYSIDE_DISPONIVEL, "PySide6 é uma dependência opcional da GUI")
class TestGuiQt(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.mapa_widget_original = gui.MapaWidget

        class MapaFake(QtWidgets.QWidget):
            areaSelecionada = QtCore.Signal(object)

            def __init__(self, bbox_inicial, parent=None):
                super().__init__(parent)
                self.bbox = list(bbox_inicial)

            def exibir_bbox(self, bbox):
                self.bbox = list(bbox)

            def capturar_bbox(self):
                self.areaSelecionada.emit(self.bbox)

            def reativar(self):
                pass

        gui.MapaWidget = MapaFake

    @classmethod
    def tearDownClass(cls) -> None:
        gui.MapaWidget = cls.mapa_widget_original

    def setUp(self) -> None:
        self.temporario = TemporaryDirectory()
        self.pasta = Path(self.temporario.name)
        gui.LOCAL_DB = self.pasta / "perfis.db"
        self.script_original = gui.SCRIPT_CLI
        self.janela = gui.MainWindow()
        self.janela.output_path.setText(str(self.pasta / "config.yaml"))
        self.janela.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        if self.janela.processo.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.janela.processo.kill()
            self.janela.processo.waitForFinished(1000)
        self.janela.close()
        gui.SCRIPT_CLI = self.script_original
        self.temporario.cleanup()

    def _aguardar_processo(self, segundos: float = 5) -> None:
        limite = time.monotonic() + segundos
        while (
            self.janela.processo.state() != QtCore.QProcess.ProcessState.NotRunning
            and time.monotonic() < limite
        ):
            self.app.processEvents()
            QtCore.QThread.msleep(10)
        self.app.processEvents()

    def test_navegacao_exibe_todas_as_paginas(self) -> None:
        for indice, (titulo, _) in enumerate(self.janela.PAGINAS):
            self.janela.botoes_navegacao[indice].click()
            self.app.processEvents()

            self.assertEqual(self.janela.stack.currentIndex(), indice)
            self.assertEqual(self.janela.titulo_pagina.text(), titulo)
            self.assertTrue(self.janela.stack.currentWidget().isVisible())

        self.assertEqual(self.janela.PAGINAS[-2][0], "Sobre")
        self.assertEqual(self.janela.PAGINAS[-1][0], "Preciso de ajuda")
        self.janela.botoes_navegacao[-1].click()
        self.app.processEvents()
        textos = [label.text() for label in self.janela.stack.currentWidget().findChildren(QtWidgets.QLabel)]
        self.assertIn("Problemas comuns", textos)

    def test_salva_yaml_com_os_dados_do_formulario(self) -> None:
        self.janela.nome_regiao.setText("Norte de MT")
        destino = self.janela._salvar_configuracao(avisar=False)

        self.assertEqual(destino, self.pasta / "config.yaml")
        payload = yaml.safe_load(destino.read_text(encoding="utf-8"))
        self.assertEqual(payload["area"]["nome"], "Norte de MT")
        self.assertEqual(payload["sincronizacao"]["tamanho_lote"], 100)
        self.assertEqual(payload["analise"]["modelo"], "analise/models/best.pt")
        self.assertEqual(payload["analise"]["confianca_minima"], 0.25)

    def test_bandas_e_colecao_sao_selecionaveis_por_checkbox(self) -> None:
        self.janela.bandas_checkboxes["B02"].setChecked(False)
        self.janela.bandas_checkboxes["NDVI"].setChecked(False)
        self.janela.colecoes_checkboxes["S2_L2A-1"].setChecked(True)

        dados = self.janela._coletar_dados()

        self.assertNotIn("B02", dados["bandas"])
        self.assertNotIn("NDVI", dados["bandas"])
        self.assertIn("B03", dados["bandas"])
        self.assertEqual(dados["colecao"], "S2_L2A-1")
        self.assertEqual(
            self.janela.bandas_checkboxes["B02"].accessibleDescription(),
            self.janela.DESCRICOES_BANDAS["B02"],
        )

    def test_aplica_area_selecionada_no_mapa(self) -> None:
        self.janela.mapa.bbox = [-59.5, -14.2, -57.1, -12.4]
        self.janela.mapa.capturar_bbox()
        self.app.processEvents()

        self.assertAlmostEqual(self.janela.oeste.value(), -59.5)
        self.assertAlmostEqual(self.janela.sul.value(), -14.2)
        self.assertAlmostEqual(self.janela.leste.value(), -57.1)
        self.assertAlmostEqual(self.janela.norte.value(), -12.4)

    def test_controles_numericos_usam_deslizadores_e_preservam_precision(self) -> None:
        self.assertIsInstance(self.janela.nuvem_max_pct.deslizador, QtWidgets.QSlider)
        self.assertEqual(
            self.janela.nuvem_max_pct.deslizador.orientation(),
            QtCore.Qt.Orientation.Horizontal,
        )
        self.janela._receber_bbox([-61.650006, -18.050006, -50.200006, -7.300006])

        self.assertEqual(self.janela.oeste.value(), -61.650006)
        self.assertEqual(self.janela.norte.value(), -7.300006)
        self.assertTrue(self.janela.findChildren(QtWidgets.QToolButton, "helpIcon"))
        self.assertTrue(
            all(icone.toolTip() for icone in self.janela.findChildren(QtWidgets.QToolButton, "helpIcon"))
        )
        helper = self.janela.findChildren(QtWidgets.QToolButton, "helpIcon")[0]
        helper.enterEvent(QtCore.QEvent(QtCore.QEvent.Type.Enter))
        self.assertEqual(QtWidgets.QToolTip.text(), helper.toolTip())
        helper.leaveEvent(QtCore.QEvent(QtCore.QEvent.Type.Leave))
        self.assertEqual(self.janela.chunk_mb.rotulo_valor.text(), "1 MB")
        self.assertEqual(self.janela.dataset_rgb_minimo.rotulo_valor.text(), "0")

    def test_perfis_sao_agrupados_e_carregados_corretamente(self) -> None:
        primeiro = self.janela.store.salvar(
            {
                "nome_regiao": "MT Norte",
                "uf": "MT",
                "bbox": [-58, -13, -55, -10],
                "bandas": ["B02"],
            }
        )
        segundo = self.janela.store.salvar(
            {
                "nome_regiao": "MT Sul",
                "uf": "MT",
                "bbox": [-57, -17, -54, -14],
                "bandas": ["B04"],
            }
        )
        self.janela._recarregar_perfis()

        grupo = self.janela.perfis.topLevelItem(0)
        self.assertEqual(grupo.text(0), "MT")
        self.assertEqual(grupo.childCount(), 2)
        ids = {grupo.child(i).data(0, QtCore.Qt.ItemDataRole.UserRole) for i in range(2)}
        self.assertEqual(ids, {primeiro, segundo})

        item_segundo = next(
            grupo.child(i)
            for i in range(grupo.childCount())
            if grupo.child(i).data(0, QtCore.Qt.ItemDataRole.UserRole) == segundo
        )
        self.janela.perfis.setCurrentItem(item_segundo)
        perfil = self.janela._perfil_selecionado()
        self.assertEqual(perfil["nome_regiao"], "MT Sul")

    def test_executa_cli_e_exibe_saida_no_log(self) -> None:
        script = self.pasta / "cli_fake.py"
        script.write_text(
            "import sys\nprint('operacao-fake-ok')\nprint('argumentos=' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        gui.SCRIPT_CLI = script
        indice = self.janela.operacao.findData("baixar")
        self.janela.operacao.setCurrentIndex(indice)
        self.janela.max_execucao.setValue(2)

        self.janela._executar()
        self._aguardar_processo()

        texto = self.janela.log.toPlainText()
        self.assertIn("operacao-fake-ok", texto)
        self.assertIn("--baixar", texto)
        self.assertIn("--max-itens 2", texto)
        self.assertIn("[Concluído]", texto)
        self.assertTrue(self.janela.btn_executar.isEnabled())
        self.assertFalse(self.janela.btn_cancelar.isEnabled())

    def test_binario_empacotado_reentra_em_modo_cli(self) -> None:
        with (
            patch.object(gui, "EMPACOTADO", True),
            patch.object(gui.sys, "executable", "/usr/bin/sentinel2-mt"),
        ):
            programa, argumentos, pasta = gui.comando_cli_empacotado(
                ["--config", "/tmp/config.yaml", "--baixar"]
            )

        self.assertEqual(programa, "/usr/bin/sentinel2-mt")
        self.assertEqual(
            argumentos,
            ["--cli", "--config", "/tmp/config.yaml", "--baixar"],
        )
        self.assertEqual(pasta, Path.home())

    def test_execucao_mantem_selecao_legivel_para_proxima_operacao(self) -> None:
        indice = self.janela.operacao.findData("baixar")
        self.janela.operacao.setCurrentIndex(indice)

        self.janela._definir_execucao(True, "Executando")

        self.assertTrue(self.janela.operacao.isEnabled())
        self.assertTrue(self.janela.max_execucao.isEnabled())
        self.assertFalse(self.janela.btn_executar.isEnabled())
        self.assertTrue(self.janela.btn_cancelar.isEnabled())
        grupo = gui.QtGui.QPalette.ColorGroup.Disabled
        papel = gui.QtGui.QPalette.ColorRole
        paleta = self.app.palette()
        self.assertEqual(
            paleta.color(grupo, papel.Text).name(),
            gui.CORES["desabilitado_texto"],
        )
        self.assertEqual(
            paleta.color(grupo, papel.Base).name(),
            gui.CORES["desabilitado_fundo"],
        )

        self.janela._definir_execucao(False, "Pronto")

    def test_carrega_resultado_da_analise_em_tela(self) -> None:
        pasta_dataset = self.pasta / "dataset"
        pasta_analises = self.pasta / "analises"
        pasta_dataset.mkdir()
        pasta_analises.mkdir()
        self.janela.pasta_analises.setText(str(pasta_analises))
        self.janela.historico_analises.setText(str(self.pasta / "historico.sqlite3"))
        self.janela._coletar_dados = lambda: {
            **gui.MainWindow._coletar_dados(self.janela),
            "pasta_dataset": str(pasta_dataset),
            "pasta_analises": str(pasta_analises),
        }
        self.assertIsNotNone(self.janela._salvar_configuracao(avisar=False))
        original = pasta_dataset / "original.png"
        anotada = pasta_analises / "anotada.png"
        imagem = gui.QtGui.QPixmap(24, 24)
        imagem.fill(gui.QtGui.QColor("green"))
        self.assertTrue(imagem.save(str(original), "PNG"))
        self.assertTrue(imagem.save(str(anotada), "PNG"))
        relatorio = pasta_analises / "relatorio.pdf"
        relatorio.write_bytes(b"%PDF-fake")
        resultado = pasta_analises / "resultado.json"
        resultado.write_text(
            json.dumps(
                {
                    "analysis_id": "a1",
                    "regiao": "Sinop",
                    "periodo_inicio": "2026-01-01",
                    "periodo_fim": "2026-03-31",
                    "scene_ids": ["CENA"],
                    "dispositivo": "cpu",
                    "imagem_original": str(original),
                    "imagem_analisada": str(anotada),
                    "caminho_relatorio": str(relatorio),
                    "estatisticas": {
                        "total_deteccoes": 2,
                        "por_classe": {"soja": 2},
                        "confianca_media_por_classe": {"soja": 0.8},
                        "confianca_minima_por_classe": {"soja": 0.7},
                        "confianca_maxima_por_classe": {"soja": 0.9},
                    },
                }
            ),
            encoding="utf-8",
        )

        self.janela._carregar_resultado_analise(resultado)

        self.assertEqual(self.janela.stack.currentIndex(), 4)
        self.assertEqual(self.janela.analise_tabela.rowCount(), 1)
        self.assertEqual(self.janela.analise_tabela.item(0, 0).text(), "soja")
        self.assertIn("Detecções: 2", self.janela.analise_info.text())
        self.assertTrue(self.janela.btn_relatorio.isEnabled())
        self.assertTrue(self.janela.btn_salvar_relatorio.isEnabled())

        destino = self.pasta / "relatorio-exportado.pdf"
        with patch.object(
            gui.QtWidgets.QFileDialog,
            "getSaveFileName",
            return_value=(str(destino), "Documento PDF (*.pdf)"),
        ):
            self.janela._salvar_relatorio_analise()
        self.assertEqual(destino.read_bytes(), b"%PDF-fake")

    def test_marcador_de_resultado_rejeita_caminho_absoluto_e_traversal(self) -> None:
        self.janela._operacao_em_execucao = "analisar"

        self.janela._processar_linha_resultado(
            "[ANALISE_RESULTADO] /tmp/resultado.json"
        )
        self.assertIsNone(self.janela._resultado_pendente)
        self.janela._processar_linha_resultado(
            "[ANALISE_RESULTADO] ../resultado.json"
        )
        self.assertIsNone(self.janela._resultado_pendente)

        self.janela._processar_linha_resultado(
            "[ANALISE_RESULTADO] data/analises/a1/resultado.json"
        )
        self.assertEqual(
            self.janela._resultado_pendente,
            gui.ROOT / "data/analises/a1/resultado.json",
        )

    def test_cancela_operacao_em_andamento(self) -> None:
        script = self.pasta / "cli_lenta.py"
        script.write_text(
            "import time\nprint('iniciada', flush=True)\ntime.sleep(10)\n",
            encoding="utf-8",
        )
        gui.SCRIPT_CLI = script
        self.janela._executar()
        limite_inicio = time.monotonic() + 2
        while (
            self.janela.processo.state() == QtCore.QProcess.ProcessState.Starting
            and time.monotonic() < limite_inicio
        ):
            self.app.processEvents()
        self.assertTrue(self.janela.btn_cancelar.isEnabled())

        self.janela._cancelar()
        self._aguardar_processo(4)

        self.assertEqual(
            self.janela.processo.state(), QtCore.QProcess.ProcessState.NotRunning
        )
        self.assertTrue(self.janela.btn_executar.isEnabled())
        self.assertFalse(self.janela.btn_cancelar.isEnabled())
