@echo off
cd /d "%~dp0"
echo 決断レーン: http://127.0.0.1:8734/
where py >nul 2>&1 && py -3 -m http.server 8734 && goto :eof
python -m http.server 8734
