@echo off
echo ============================================
echo MyProctor.ai Setup Script (Windows)
echo ============================================
echo.

REM Check Python
python --version
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo Upgrading pip...
pip install --upgrade pip setuptools wheel

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Check for missing model files
echo.
echo Checking for required model files...
set MODELS_MISSING=0

if not exist "models\yolov3.weights" (
    echo WARNING: models\yolov3.weights is missing
    echo Download from: https://pjreddie.com/media/files/yolov3.weights
    set MODELS_MISSING=1
)

if not exist "models\opencv_face_detector_uint8.pb" (
    echo WARNING: models\opencv_face_detector_uint8.pb is missing
    set MODELS_MISSING=1
)

if not exist "models\opencv_face_detector.pbtxt" (
    echo WARNING: models\opencv_face_detector.pbtxt is missing
    set MODELS_MISSING=1
)

if not exist "models\pose_model\saved_model.pb" (
    echo WARNING: models\pose_model\saved_model.pb is missing
    set MODELS_MISSING=1
)

if %MODELS_MISSING%==1 (
    echo.
    echo Some model files are missing. Please download them before running the application.
    pause
)

REM Create .env file if it doesn't exist
if not exist ".env" (
    echo.
    echo Creating .env file from template...
    copy .env.example .env
    echo IMPORTANT: Please edit .env and configure your settings!
)

echo.
echo ============================================
echo Setup complete!
echo ============================================
echo.
echo Next steps:
echo 1. Edit .env file with your database and mail settings
echo 2. Set up MySQL database using DB/quizappstructure.sql
echo 3. Run: python app.py
echo.
echo The application will be available at: http://localhost:5000
echo.
pause
