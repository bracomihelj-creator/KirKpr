@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "APP=%~dp0convert_KIrKpr_to_minimax.py"
set "LOG=%~dp0KIRKPR_zagon_napaka.log"
set "PYTHON_OK="

>"%LOG%" echo [%date% %time%] Preverjanje zagona KIR/KPR -^> Minimax

for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    if not defined PYTHON_OK (
        "%%P" -c "import tkinter, lxml" >>"%LOG%" 2>&1
        if !errorlevel! equ 0 set "PYTHON_OK=%%P"
    )
)

if defined PYTHON_OK (
    for %%F in ("!PYTHON_OK!") do set "PYTHONW_OK=%%~dpFpythonw.exe"
    >>"%LOG%" echo Uporabljen Python: !PYTHON_OK!
    if exist "!PYTHONW_OK!" (
        start "" /B "!PYTHONW_OK!" "%APP%" 2>>"%LOG%"
    ) else (
        start "KIR/KPR Minimax" /B "!PYTHON_OK!" "%APP%" 2>>"%LOG%"
    )
    exit /b 0
)

where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import tkinter, lxml" >>"%LOG%" 2>&1
    if !errorlevel! equ 0 (
        >>"%LOG%" echo Uporabljen Python Launcher: py -3
        start "" /B pyw -3 "%APP%" 2>>"%LOG%"
        exit /b 0
    )
)

echo.
echo KIR/KPR -^> Minimax se ne more zagnati.
echo Python 3 s knjiznico lxml ni bil najden.
echo.
echo Podrobnosti so v:
echo %LOG%
echo.
type "%LOG%"
echo.
echo Namestitev lxml: python -m pip install lxml
pause
exit /b 1
