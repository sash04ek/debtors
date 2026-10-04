#!/bin/sh
# Сборка приложения на macOS: результат — dist/Должники.app
# Нужен Python с Tk (python.org). Используем .venv проекта, если он есть.
set -e
cd "$(dirname "$0")"
# Пересборка поверх запущенного приложения ломает его: оно подгружает модули из заменённого файла и падает с ошибками вроде
# «Error -3 while decompressing data: incorrect header check». Поэтому сначала закройте приложение (или FORCE=1, если запущена не эта копия).
if [ -z "$FORCE" ] && pgrep -f "dist/Должники.app/Contents/MacOS" >/dev/null 2>&1; then
    echo "Приложение dist/Должники.app запущено: закройте его и повторите (или FORCE=1 ./build.sh)." >&2
    exit 1
fi
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
[ -x "$PY" ] || PY=python3
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt pyinstaller
# версия для окна «О программе»: ближайший тег репозитория (если есть)
V=$(git describe --tags --abbrev=0 2>/dev/null || echo "разработка")
printf 'VERSION = "%s"\n' "$V" > version.py
.venv/bin/python -m PyInstaller --noconfirm --collect-data petrovich --windowed --icon assets/icon.icns --add-data "assets/icon.png:assets" --add-data "assets/gear.png:assets" --add-data "assets/gear_hover.png:assets" --name "Должники" app.py
./add_document_types.sh "dist/Должники.app"
git checkout -- version.py 2>/dev/null || true      # в репозитории остаётся значение по умолчанию
echo "Готово: dist/Должники.app"
