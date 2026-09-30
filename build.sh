#!/bin/sh
# Сборка приложения на macOS: результат — dist/Должники.app
# Нужен Python с Tk (python.org). Используем .venv проекта, если он есть.
set -e
cd "$(dirname "$0")"
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
[ -x "$PY" ] || PY=python3
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt pyinstaller
.venv/bin/python -m PyInstaller --noconfirm --collect-data petrovich --windowed --icon assets/icon.icns --add-data "assets/icon.png:assets" --add-data "assets/gear.png:assets" --add-data "assets/gear_hover.png:assets" --name "Должники" app.py
echo "Готово: dist/Должники.app"
