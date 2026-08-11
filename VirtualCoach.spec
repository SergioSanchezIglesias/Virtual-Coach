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

# customtkinter NO es solo codigo: lleva temas (.json), fuentes e iconos en su
# carpeta assets/. PyInstaller no recoge datos por su cuenta, asi que sin esto
# el .exe arranca y revienta al pintar la primera ventana.
ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")

# darkdetect (dependencia de customtkinter) elige su modulo por plataforma
# DENTRO de un if sys.platform, en tiempo de ejecucion. Lo que PyInstaller ve
# al analizar el codigo no basta para garantizar que _windows_detect viaje.
dd_datas, dd_binaries, dd_hidden = collect_all("darkdetect")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=sd_binaries + ctk_binaries + dd_binaries,
    # los clips de voz viajan dentro
    datas=[("voces", "voces")] + sd_datas + ctk_datas + dd_datas,
    # pyirsdk se importa tarde, hay que forzarlo
    hiddenimports=["irsdk"] + sd_hidden + ctk_hidden + dd_hidden,
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
