@echo off
rem Start sbobina with a double click on Windows: installs uv if missing,
rem prepares the environment and opens the web UI in the browser.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "UV_BIN=%USERPROFILE%\.local\bin"
where uv >nul 2>nul
if not errorlevel 1 goto have_uv
if exist "%UV_BIN%\uv.exe" (
    set "PATH=%UV_BIN%;%PATH%"
    goto have_uv
)

echo Serve uv (gestisce Python e le librerie di sbobina) e non è installato.
choice /c SN /m "Lo installo ora da https://astral.sh/uv/install.ps1"
if errorlevel 2 (
    echo Installazione annullata. Istruzioni: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%UV_BIN%;%PATH%"

:have_uv
set "EXTRA="
where nvidia-smi >nul 2>nul
if errorlevel 1 goto no_gpu
nvidia-smi -L >nul 2>nul
if errorlevel 1 goto no_gpu
echo Scheda NVIDIA trovata: uso la GPU.
set "EXTRA=--extra cuda"
goto run

:no_gpu
echo Nessuna scheda NVIDIA utilizzabile: la trascrizione userà il processore (più lenta).

:run
echo Preparo l'ambiente (la prima volta può richiedere qualche minuto)...
uv run %EXTRA% sbobina web %*
rem Keep the window open so an error message stays readable.
pause
