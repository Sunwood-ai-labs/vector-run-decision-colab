@echo off
cd /d "%~dp0"
echo VECTOR RUN rule mock: http://127.0.0.1:8780/health
where uv >nul 2>&1 && uv run --no-project --python 3.12 server\decision_server.py --mock --port 8780 && goto :eof
where py >nul 2>&1 && py -3 server\decision_server.py --mock --port 8780 && goto :eof
python server\decision_server.py --mock --port 8780
