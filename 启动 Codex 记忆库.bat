@echo off
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw "%~dp0codex_memory_vault.pyw"
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0codex_memory_vault.pyw"
    exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
    start "" python "%~dp0codex_memory_vault.pyw"
    exit /b 0
)

echo 未找到 Python 3。请先安装 Python 3，并在安装时勾选“Add Python to PATH”。
pause
