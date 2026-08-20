@echo off
rem Launch the Master League companion app from the repo root so it can find
rem tools\play_match.py and build\master.db by walking up from its own folder.
cd /d "%~dp0"
set EXE=%~dp0src\ML.App\bin\Debug\net8.0\ML.App.exe
if not exist "%EXE%" (
    echo Building the app for the first time...
    dotnet build "%~dp0src\ML.App\ML.App.csproj" -v q
)
start "" "%EXE%"
