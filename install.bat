@echo off
chcp 65001 >nul

echo 🚀 자동 그리드 트레이딩 봇 설치를 시작합니다...
echo 🚀 Starting Auto Grid Trading Bot Installation...

REM Python 버전 확인
echo.
echo 🔍 Python 버전 확인 중...
python --version
if %errorlevel% neq 0 (
    echo ❌ Python이 설치되지 않았습니다. Python 3.8 이상을 설치해주세요.
    echo ❌ Python is not installed. Please install Python 3.8 or higher.
    pause
    exit /b 1
)

REM 가상환경 생성
echo.
echo 📦 가상환경 생성 중...
echo 📦 Creating virtual environment...
python -m venv venv

REM 가상환경 활성화
echo.
echo ✅ 가상환경 활성화 중...
echo ✅ Activating virtual environment...
call venv\Scripts\activate.bat

REM 필수 라이브러리 설치
echo.
echo 📚 필수 라이브러리 설치 중...
echo 📚 Installing required libraries...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo 🎉 설치가 완료되었습니다!
echo 🎉 Installation completed!
echo.
echo 다음 단계:
echo Next steps:
echo 1. config.json 파일을 설정하세요 (API 키 등)
echo 1. Configure config.json file (API keys, etc.)
echo 2. 다음 명령으로 봇을 실행하세요:
echo 2. Run the bot with the following command:
echo    venv\Scripts\activate.bat && python main.py
echo.
echo 📖 자세한 사용법은 README.md를 참고하세요.
echo 📖 For detailed usage, please refer to README.md.

pause