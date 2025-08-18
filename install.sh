#!/bin/bash

# 자동 그리드 트레이딩 봇 설치 스크립트
# Auto Grid Trading Bot Installation Script

echo "🚀 자동 그리드 트레이딩 봇 설치를 시작합니다..."
echo "🚀 Starting Auto Grid Trading Bot Installation..."

# Python 버전 확인
echo ""
echo "🔍 Python 버전 확인 중..."
python3 --version

if [ $? -ne 0 ]; then
    echo "❌ Python 3이 설치되지 않았습니다. Python 3.8 이상을 설치해주세요."
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# 가상환경 생성
echo ""
echo "📦 가상환경 생성 중..."
echo "📦 Creating virtual environment..."
python3 -m venv venv

# 가상환경 활성화
echo ""
echo "✅ 가상환경 활성화 중..."
echo "✅ Activating virtual environment..."
source venv/bin/activate

# 필수 라이브러리 설치
echo ""
echo "📚 필수 라이브러리 설치 중..."
echo "📚 Installing required libraries..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "🎉 설치가 완료되었습니다!"
echo "🎉 Installation completed!"
echo ""
echo "다음 단계:"
echo "Next steps:"
echo "1. config.json 파일을 설정하세요 (API 키 등)"
echo "1. Configure config.json file (API keys, etc.)"
echo "2. 다음 명령으로 봇을 실행하세요:"
echo "2. Run the bot with the following command:"
echo "   source venv/bin/activate && python main.py"
echo ""
echo "📖 자세한 사용법은 README.md를 참고하세요."
echo "📖 For detailed usage, please refer to README.md."