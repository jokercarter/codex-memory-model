@echo off
setlocal EnableExtensions
set "PYTHONW_EXE="
if defined CODEX_MEMORY_PYTHON for %%P in ("%CODEX_MEMORY_PYTHON%") do set "PYTHONW_EXE=%%~dpnP.exe"
if not defined PYTHONW_EXE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe" set "PYTHONW_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if not defined PYTHONW_EXE for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYTHONW_EXE set "PYTHONW_EXE=%%P"
if not defined PYTHONW_EXE (
  echo Python 3 was not found. Set CODEX_MEMORY_PYTHON or install Python with pythonw.exe. 1>&2
  pause
  exit /b 1
)
start "Codex Memory" "%PYTHONW_EXE%" "%~dp0codex_memory_dashboard.py"
exit /b 0
