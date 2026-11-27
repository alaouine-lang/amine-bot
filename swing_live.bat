@echo off
REM Paper trading quotidien du systeme swing - a planifier chaque soir vers 22h45 (heure de Paris)
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist data\paper mkdir data\paper
call .venv\Scripts\activate.bat
echo ===== %date% %time% =====>> data\paper\log.txt
python -m swing live >> data\paper\log.txt 2>&1
