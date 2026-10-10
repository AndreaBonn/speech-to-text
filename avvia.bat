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
call :ensure_ollama
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
exit /b 0

rem Ollama is optional (correction, exams, summaries, chat, OCR). When it is
rem missing, offer to install it and download the models; never without consent.
:ensure_ollama
set "OLLAMA_DIR=%LOCALAPPDATA%\Programs\Ollama"
where ollama >nul 2>nul
if not errorlevel 1 exit /b 0
if exist "%OLLAMA_DIR%\ollama.exe" exit /b 0

echo.
echo Ollama non è installato. Serve per correzione del testo, esami, riassunti, chat e OCR.
echo La trascrizione funziona anche senza.
choice /c SN /m "Lo installo ora, con i modelli necessari"
if errorlevel 2 goto ollama_skip

call :install_ollama
if not exist "%OLLAMA_DIR%\ollama.exe" goto ollama_failed
set "PATH=%OLLAMA_DIR%;%PATH%"

rem The installer normally starts the server; start it ourselves if it does not answer.
ollama list >nul 2>nul
if not errorlevel 1 goto ollama_pull
start "" /min "%OLLAMA_DIR%\ollama.exe" serve
set "TRIES=0"

:ollama_wait
ollama list >nul 2>nul
if not errorlevel 1 goto ollama_pull
set /a TRIES+=1
if %TRIES% geq 15 goto ollama_pull
ping -n 3 127.0.0.1 >nul
goto ollama_wait

:ollama_pull
echo Scarico i modelli: sono diversi GB, può richiedere molto tempo.
ollama pull qwen3.5:9b
if errorlevel 1 echo Modello qwen3.5:9b non scaricato: potrai scaricarlo dalla pagina Modelli.
ollama pull qwen3-embedding:8b
if errorlevel 1 echo Modello qwen3-embedding:8b non scaricato: la ricerca userà solo le parole chiave.
exit /b 0

:ollama_failed
echo Installazione di Ollama non riuscita. Installalo a mano da https://ollama.com/download e rilancia.
exit /b 0

:ollama_skip
echo Proseguo senza Ollama: potrai installarlo più tardi da https://ollama.com/download
exit /b 0

:install_ollama
where winget >nul 2>nul
if errorlevel 1 goto ollama_download
winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
if exist "%OLLAMA_DIR%\ollama.exe" exit /b 0

:ollama_download
echo Scarico l'installer di Ollama da https://ollama.com ...
powershell -NoProfile -ExecutionPolicy ByPass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri https://ollama.com/download/OllamaSetup.exe -OutFile $env:TEMP\OllamaSetup.exe"
if errorlevel 1 exit /b 1
start /wait "" "%TEMP%\OllamaSetup.exe" /SILENT
exit /b 0
