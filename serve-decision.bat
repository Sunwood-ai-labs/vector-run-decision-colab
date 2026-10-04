@echo off
cd /d "%~dp0"
echo Decision mock: http://127.0.0.1:8780/health
where py >nul 2>&1 && py -3 server\decision_server.py --mock --port 8780 && goto :eof
python server\decision_server.py --mock --port 8780
