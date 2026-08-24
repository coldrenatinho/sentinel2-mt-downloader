from __future__ import annotations


CORES = {
    "fundo": "#f4f7f6",
    "superficie": "#ffffff",
    "superficie_campo": "#fbfdfc",
    "texto": "#17201d",
    "texto_suave": "#485750",
    "sidebar": "#102b24",
    "sidebar_hover": "#173b32",
    "sidebar_ativo": "#225344",
    "sidebar_texto": "#cbe2db",
    "sidebar_texto_suave": "#9cc4b7",
    "destaque": "#0f7548",
    "destaque_hover": "#0b633c",
    "destaque_claro": "#49c98b",
    "destaque_texto": "#0a2018",
    "borda": "#c8d6d1",
    "borda_suave": "#dce6e2",
    "secundario_fundo": "#eef4f1",
    "secundario_texto": "#173a2f",
    "perigo_fundo": "#fff0ee",
    "perigo_texto": "#8f2e24",
    "log_fundo": "#0d211a",
    "log_texto": "#e2f5ed",
    "preview_fundo": "#eaf1ee",
    "preview_texto": "#43534d",
    "status_fundo": "#e5f7ee",
    "status_texto": "#135f3d",
    "desabilitado_fundo": "#e1e8e5",
    "desabilitado_texto": "#26332e",
}


PARES_CONTRASTE = {
    "texto principal": ("texto", "fundo", 4.5),
    "texto em cartão": ("texto", "superficie", 4.5),
    "texto auxiliar": ("texto_suave", "superficie", 4.5),
    "subtítulo": ("texto_suave", "fundo", 4.5),
    "campo": ("texto", "superficie_campo", 4.5),
    "navegação": ("sidebar_texto", "sidebar", 4.5),
    "navegação auxiliar": ("sidebar_texto_suave", "sidebar", 4.5),
    "botão primário": ("superficie", "destaque", 4.5),
    "botão secundário": ("secundario_texto", "secundario_fundo", 4.5),
    "botão de perigo": ("perigo_texto", "perigo_fundo", 4.5),
    "log": ("log_texto", "log_fundo", 4.5),
    "preview": ("preview_texto", "preview_fundo", 4.5),
    "status": ("status_texto", "status_fundo", 4.5),
    "controle desabilitado": (
        "desabilitado_texto",
        "desabilitado_fundo",
        4.5,
    ),
}


def _luminancia(cor: str) -> float:
    canais = [int(cor[indice : indice + 2], 16) / 255 for indice in (1, 3, 5)]
    lineares = [
        canal / 12.92
        if canal <= 0.04045
        else ((canal + 0.055) / 1.055) ** 2.4
        for canal in canais
    ]
    return 0.2126 * lineares[0] + 0.7152 * lineares[1] + 0.0722 * lineares[2]


def razao_contraste(frente: str, fundo: str) -> float:
    luminancias = sorted((_luminancia(frente), _luminancia(fundo)), reverse=True)
    return (luminancias[0] + 0.05) / (luminancias[1] + 0.05)


def contrastes() -> dict[str, float]:
    return {
        nome: razao_contraste(CORES[frente], CORES[fundo])
        for nome, (frente, fundo, _) in PARES_CONTRASTE.items()
    }


def folha_estilos() -> str:
    return """
QMainWindow, QWidget#root { background: %(fundo)s; color: %(texto)s; }
QWidget { color: %(texto)s; font-family: "Inter", "Noto Sans", sans-serif; font-size: 14px; }
QFrame#sidebar { background: %(sidebar)s; border: none; }
QLabel#brandMark {
    background: %(destaque_claro)s; color: %(destaque_texto)s; border-radius: 20px;
    font-size: 16px; font-weight: 800;
}
QLabel#brandTitle { color: %(superficie)s; font-size: 16px; font-weight: 700; }
QLabel#brandSub { color: %(sidebar_texto_suave)s; font-size: 12px; }
QPushButton#navButton {
    color: %(sidebar_texto)s; background: transparent; border: none;
    border-radius: 8px; padding: 11px 14px; text-align: left;
}
QPushButton#navButton:hover { background: %(sidebar_hover)s; color: %(superficie)s; }
QPushButton#navButton:checked { background: %(sidebar_ativo)s; color: %(superficie)s; font-weight: 700; }
QLabel#pageTitle { font-size: 25px; font-weight: 750; color: %(texto)s; }
QLabel#pageSubtitle { color: %(texto_suave)s; font-size: 13px; }
QLabel#statusChip {
    background: %(status_fundo)s; color: %(status_texto)s; border: 1px solid %(borda)s;
    border-radius: 12px; padding: 6px 11px; font-weight: 700;
}
QFrame#card { background: rgba(255, 255, 255, 238); border: 1px solid %(borda_suave)s; border-radius: 12px; }
QLabel#cardTitle { font-size: 16px; font-weight: 700; color: %(texto)s; }
QLabel#cardHelp { color: %(texto_suave)s; font-size: 12px; }
QLineEdit, QDateEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QPlainTextEdit, QListWidget, QTreeWidget {
    color: %(texto)s; background: %(superficie_campo)s; border: 1px solid %(borda)s;
    border-radius: 7px; padding: 7px; selection-color: %(destaque_texto)s;
    selection-background-color: %(destaque_claro)s;
}
QLineEdit:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus {
    border: 2px solid %(destaque)s;
}
QLineEdit:disabled, QDateEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled, QPlainTextEdit:disabled {
    color: %(desabilitado_texto)s; background-color: %(desabilitado_fundo)s;
    border-color: %(borda)s;
}
QComboBox:disabled::drop-down {
    background-color: %(desabilitado_fundo)s; border-left: 1px solid %(borda)s;
}
QSpinBox:disabled::up-button, QSpinBox:disabled::down-button,
QDoubleSpinBox:disabled::up-button, QDoubleSpinBox:disabled::down-button {
    background-color: %(desabilitado_fundo)s; border-left: 1px solid %(borda)s;
}
QComboBox:disabled QAbstractItemView {
    color: %(desabilitado_texto)s; background-color: %(desabilitado_fundo)s;
}
QSlider#numericSlider::groove:horizontal {
    height: 8px; background: %(borda_suave)s; border-radius: 4px;
}
QSlider#numericSlider::sub-page:horizontal {
    background: %(destaque)s; border-radius: 4px;
}
QSlider#numericSlider::add-page:horizontal {
    background: #dce9e3; border-radius: 4px;
}
QSlider#numericSlider::handle:horizontal {
    background: %(destaque_claro)s; border: 2px solid %(destaque)s;
    width: 18px; height: 18px; margin: -7px 0; border-radius: 10px;
}
QSlider#numericSlider::handle:horizontal:hover { background: #7be0ac; }
QSlider#numericSlider:disabled::sub-page { background: %(desabilitado_fundo)s; }
QSlider#numericSlider:disabled::handle {
    background: %(desabilitado_fundo)s; border-color: %(borda)s;
}
QLabel#numericSliderValue {
    color: %(destaque)s; background: %(secundario_fundo)s; border: 1px solid %(borda)s;
    border-radius: 6px; padding: 5px 7px; font-weight: 700;
}
QLabel#numericSliderValue:disabled { color: %(desabilitado_texto)s; background: %(desabilitado_fundo)s; }
QToolButton#helpIcon {
    color: %(destaque)s; background: %(secundario_fundo)s; border: 1px solid %(borda)s;
    border-radius: 9px; min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px;
    padding: 0; font-weight: 800;
}
QToolButton#helpIcon:hover, QToolButton#helpIcon:focus {
    color: %(superficie)s; background: %(destaque)s; border-color: %(destaque)s;
}
QCheckBox { color: %(texto)s; spacing: 8px; }
QComboBox QAbstractItemView, QMenu, QCalendarWidget, QDialog, QMessageBox {
    color: %(texto)s; background: %(superficie)s; selection-color: %(destaque_texto)s;
    selection-background-color: %(destaque_claro)s;
}
QCalendarWidget QToolButton { color: %(texto)s; background: %(secundario_fundo)s; }
QCalendarWidget QAbstractItemView { color: %(texto)s; background: %(superficie)s; }
QHeaderView::section {
    color: %(texto)s; background: %(secundario_fundo)s; border: none;
    border-bottom: 1px solid %(borda)s; padding: 7px; font-weight: 700;
}
QPushButton#primaryButton {
    background: %(destaque)s; color: %(superficie)s; border: none; border-radius: 8px;
    padding: 10px 17px; font-weight: 700;
}
QPushButton#primaryButton:hover { background: %(destaque_hover)s; }
QPushButton#primaryButton:disabled {
    background: %(desabilitado_fundo)s; color: %(desabilitado_texto)s;
}
QPushButton#secondaryButton {
    background: %(secundario_fundo)s; color: %(secundario_texto)s; border: 1px solid %(borda)s;
    border-radius: 8px; padding: 9px 15px; font-weight: 650;
}
QPushButton#secondaryButton:hover { background: #dfeae5; }
QPushButton#dangerButton {
    background: %(perigo_fundo)s; color: %(perigo_texto)s; border: 1px solid #e9b9b2;
    border-radius: 8px; padding: 9px 15px; font-weight: 700;
}
QPushButton#dangerButton:hover { background: #ffded9; }
QPushButton#dangerButton:disabled {
    background: %(desabilitado_fundo)s; color: %(desabilitado_texto)s; border-color: %(borda_suave)s;
}
QProgressBar { border: none; border-radius: 3px; background: %(borda_suave)s; max-height: 7px; }
QProgressBar::chunk { background: %(destaque)s; border-radius: 3px; }
QPlainTextEdit#log {
    background: %(log_fundo)s; color: %(log_texto)s; border: none;
    font-family: "JetBrains Mono", "Noto Sans Mono", monospace; font-size: 13px;
}
QLabel#previewImage {
    background: %(preview_fundo)s; border: 1px dashed %(borda)s; border-radius: 10px;
    color: %(preview_texto)s;
}
QStatusBar { color: %(texto)s; background: %(superficie)s; }
QToolTip { color: %(texto)s; background: %(superficie)s; border: 1px solid %(borda)s; padding: 5px; }
QSplitter::handle { background: %(borda_suave)s; width: 4px; height: 4px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
""" % CORES
