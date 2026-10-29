from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path.cwd().resolve()

analysis = Analysis(
    [str(project_root / "app" / "desktop.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "alembic.ini"), "."),
        (str(project_root / "alembic"), "alembic"),
        (str(project_root / "frontend" / "dist"), "frontend/dist"),
        *collect_data_files("tzdata"),
    ],
    hiddenimports=[*collect_submodules("app"), *collect_submodules("uvicorn")],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="interntrack-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
