@echo off
cd /d "%~dp0"
echo VECTOR RUN: http://127.0.0.1:8734/
where uv >nul 2>&1 && uv run --no-project --python 3.12 -m http.server 8734 --bind 127.0.0.1 && goto :eof
where py >nul 2>&1 && py -3 -m http.server 8734 && goto :eof
python -m http.server 8734
