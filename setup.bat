@echo off
echo Setting up Teto environment...

:: Create virtual environment
python -m venv .venv
if errorlevel 1 (
    echo Failed to create virtual environment. Make sure Python is installed.
    pause
    exit /b 1
)

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Upgrade pip
python -m pip install --upgrade pip

:: Install dependencies
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Setup complete! Activate the environment with:
echo   .venv\Scripts\activate.bat
pause
