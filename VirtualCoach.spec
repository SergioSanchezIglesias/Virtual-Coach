# -*- mode: python ; coding: utf-8 -*-
"""
Receta de PyInstaller para el ejecutable de Windows.

Construir EN WINDOWS (el .exe es de Windows, no se hace en Mac):

    pip install pyinstaller
    pyinstaller VirtualCoach.spec

Resultado: dist\\VirtualCoach\\VirtualCoach.exe  (carpeta portable, sin Python).
Copia la carpeta dist\\VirtualCoach a donde quieras y doble-clic al .exe.

Es --onedir (una carpeta) a proposito, no --onefile: asi la GUI puede lanzarse
a si misma (el coach) sin re-extraer todo el bundle en cada arranque.
"""
from PyInstaller.utils.hooks import collect_all

# sounddevice arrastra el DLL de PortAudio; collect_all se asegura de incluirlo.
sd_datas, sd_binaries, sd_hidden = collect_all("sounddevice")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=sd_binaries,
    datas=[("voces", "voces")] + sd_datas,   # los clips de voz viajan dentro
    hiddenimports=["irsdk"] + sd_hidden,      # pyirsdk se importa tarde, hay que forzarlo
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VirtualCoach",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # es una GUI: sin ventana de consola negra
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VirtualCoach",
)
