@echo off
rem Сборка приложения на Windows: результат — dist\Должники.exe
python -m venv .venv-build
call .venv-build\Scripts\activate.bat
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --collect-data petrovich --collect-data sv_ttk --windowed --onefile --icon assets\icon.ico --add-data "assets\icon.png;assets" --add-data "assets\gear.png;assets" --add-data "assets\gear_hover.png;assets" --name "Должники" app.py
