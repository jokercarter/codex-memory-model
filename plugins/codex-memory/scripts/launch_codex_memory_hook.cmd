@echo off
setlocal EnableExtensions
set "PLUGIN_ROOT=%~dp0.."
set "PYTHON_EXE="
set "PYTHON_MODE=direct"
if defined CODEX_MEMORY_PYTHON if exist "%CODEX_MEMORY_PYTHON%" set "PYTHON_EXE=%CODEX_MEMORY_PYTHON%"
if not defined PYTHON_EXE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\OpenAI\Codex\runtimes\python\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\OpenAI\Codex\runtimes\python\python.exe"
if not defined PYTHON_EXE for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE for /f "delims=" %%P in ('where py.exe 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P" & set "PYTHON_MODE=launcher"
if not defined PYTHON_EXE (
  echo Codex Memory plugin could not find Python 3.10 or newer. 1>&2
  exit /b 1
)
set "PYTHONIOENCODING=utf-8"
if /I "%PYTHON_MODE%"=="launcher" (
  "%PYTHON_EXE%" -3 "%PLUGIN_ROOT%\runtime\codex_memory_hook.py" %*
) else (
  "%PYTHON_EXE%" "%PLUGIN_ROOT%\runtime\codex_memory_hook.py" %*
)
exit /b %ERRORLEVEL%
