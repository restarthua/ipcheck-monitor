@echo off
echo === IPCheck Monitor Build ===

echo.
echo [1/2] Installing dependencies...
pip install ai-ipcheck pystray Pillow pyinstaller

echo.
echo [2/2] Building exe...
pyinstaller --noconfirm --onefile --windowed --name "IPCheckMonitor" --add-data "checker.py;." --hidden-import ipcheck --hidden-import ipcheck.cli --hidden-import pystray._win32 app.py

echo.
echo === Done ===
echo Output: dist\IPCheckMonitor.exe
pause
