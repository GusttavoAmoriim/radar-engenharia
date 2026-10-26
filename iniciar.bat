@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Criei o arquivo .env. Vou abrir para voce editar.
  echo Troque RADAR_PASSWORD pela sua senha e coloque RADAR_COOKIE_SECURE=0. Salve e feche o Bloco de Notas.
  notepad ".env"
  echo Agora execute o iniciar.bat de novo.
  pause
  exit /b 0
)

where py >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale com este comando e abra um terminal novo:
  echo winget install -e --id Python.Python.3.12
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Preparando o ambiente. So na primeira vez, pode demorar alguns minutos...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Falha ao criar o ambiente do Python.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Falha ao instalar as dependencias.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" run_local.py
pause
