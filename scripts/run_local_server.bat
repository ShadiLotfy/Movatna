@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" "server.py" > "instance\flask.out.log" 2> "instance\flask.err.log"
