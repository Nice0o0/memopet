@echo off
REM MemoPet 一键启动（Windows）：双击运行，或命令行执行
REM 前置：同级 ..\rwkv 检出（提供 .venv312、已转换权重与词表）
cd /d %~dp0

set PY=
if exist ..\rwkv\.venv312\Scripts\python.exe set PY=..\rwkv\.venv312\Scripts\python.exe
if "%PY%"=="" (
  echo [memopet] 未找到 ..\rwkv\.venv312，请先按 stateswap README 完成安装
  pause
  exit /b 1
)

echo [memopet] WebUI: http://127.0.0.1:8001
start "" http://127.0.0.1:8001
%PY% -m memopet.server --port 8001
pause
