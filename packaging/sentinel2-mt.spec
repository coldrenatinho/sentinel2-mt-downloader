from pathlib import Path
import hashlib
import json

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).parent
datas = []
binaries = []
hiddenimports = []

for pacote in (
    "rasterio",
    "textual",
    "pystac",
    "googleapiclient",
    "matplotlib",
    "torch",
    "ultralytics",
):
    pacote_datas, pacote_binaries, pacote_hiddenimports = collect_all(pacote)
    datas += pacote_datas
    binaries += pacote_binaries
    hiddenimports += pacote_hiddenimports

modelos = ROOT / "src/sentinel2_mt/analise/models"
if modelos.is_dir():
    metadata_modelo = modelos / "model_metadata.json"
    modelo = modelos / "agricultura.pt"
    if metadata_modelo.is_file():
        datas.append((str(metadata_modelo), "sentinel2_mt/analise/models"))
    if modelo.is_file():
        metadata = json.loads(metadata_modelo.read_text(encoding="utf-8"))
        esperado = str(metadata.get("sha256", "")).lower()
        calculado = hashlib.sha256(modelo.read_bytes()).hexdigest()
        if esperado != calculado:
            raise ValueError("SHA-256 de agricultura.pt diverge de model_metadata.json")
        datas.append((str(modelo), "sentinel2_mt/analise/models"))

analise = Analysis(
    [str(ROOT / "src/main.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # PySide6 e QtWebEngine fazem parte da distribuição principal. Os hooks
    # nativos do PyInstaller coletam os plugins, recursos e subprocessos Qt.
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "streamlit",
        "folium",
        "streamlit_folium",
    ],
    noarchive=False,
)
pyz = PYZ(analise.pure)

executavel = EXE(
    pyz,
    analise.scripts,
    analise.binaries,
    analise.datas,
    [],
    name="sentinel2-mt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
