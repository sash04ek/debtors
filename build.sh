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
# Excel-файлы можно бросать на значок программы и открывать через «Открыть в…»
PLIST="dist/Должники.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :CFBundleDocumentTypes" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes array" \
  -c "Add :CFBundleDocumentTypes:0 dict" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string Excel" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer" \
  -c "Add :CFBundleDocumentTypes:0:LSHandlerRank string Alternate" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions array" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:0 string xlsx" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:1 string xls" \
  -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:2 string xlsm" "$PLIST"
codesign --force --deep --sign - "dist/Должники.app" 2>/dev/null || true
echo "Готово: dist/Должники.app"
