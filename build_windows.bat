@echo off
rem Build JAR for Windows from a clean virtual environment.
setlocal

cd /d "%~dp0"

set "PYTHON=python"
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYTHON=py -3"

if not exist ".venv-build" (
    %PYTHON% -m venv .venv-build
)
call .venv-build\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements-dev.txt

echo ==^> running tests
python -m unittest discover -s tests -t .
if errorlevel 1 goto :error

echo ==^> building CLI binary
pyinstaller --clean --noconfirm packaging\jar-cli.spec
if errorlevel 1 goto :error

echo ==^> building desktop binary
pyinstaller --clean --noconfirm packaging\jar-desktop.spec
if errorlevel 1 goto :error

echo ==^> smoke testing CLI binary
python scripts\smoke_test.py dist\jar.exe
if errorlevel 1 goto :error

echo ==^> packaging release archive
python scripts\package_release.py --dist dist --output release --platform windows
if errorlevel 1 goto :error

echo.
echo Done. Archives are in %CD%\release
exit /b 0

:error
echo Build failed.
exit /b 1
