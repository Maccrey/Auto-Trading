# 📈 자동 거래 봇 (Auto-Trading Bot)

이 프로젝트는 그리드 트레이딩 전략을 기반으로 하는 자동 암호화폐 거래 봇입니다. 사용자 친화적인 GUI를 통해 실시간 모니터링 및 설정을 제공하며, 다양한 시장 상황에 대응할 수 있는 고급 기능을 포함하고 있습니다.

## ✨ 주요 기능

*   **그리드 트레이딩 (Grid Trading)**: 설정된 가격 범위 내에서 자동으로 매수/매도 그리드를 생성하여 거래를 수행합니다.
*   **상승 추세 추종 매도 (Ascending Trend Following)**: 목표가에 도달해도 즉시 매도하지 않고, 가격이 계속 상승할 경우 매도를 보류합니다. 추세가 꺾여 이전에 도달했던 최고 그리드 가격으로 하락할 때 매도를 실행하여 수익을 극대화합니다.
*   **패닉 모드 (급락 대응)**: 시장의 급격한 하락 시 자동으로 매수 전략을 조정하여 위험을 관리합니다.
*   **트레일링 스탑 (Trailing Stop)**: 최고점 대비 일정 비율 하락 시 자동으로 포지션을 청산하여 수익을 보존합니다.
*   **긴급 청산 (Emergency Exit)**: 설정된 손실 임계점에 도달 시 모든 포지션을 긴급 청산합니다.
*   **지정가 주문 (Limit Orders)**: 시장가 주문 대신 지정가 주문을 사용하여 거래 수수료를 절감합니다.
*   **데이터 영속성 (Data Persistence)**: 거래 상태, 수익, 거래 로그를 파일로 저장하여 프로그램 재시작 후에도 이어서 거래할 수 있습니다.
*   **사용자 친화적 GUI**: 실시간 차트, 현재 자산 현황, 거래 로그 등을 직관적으로 확인할 수 있는 그래픽 사용자 인터페이스를 제공합니다.
*   **데이터 초기화/재설정**: 모든 거래 데이터(거래 상태, 수익, 로그)를 쉽게 초기화하고, `config.json`의 총 투자금을 기본값으로 재설정할 수 있습니다.
*   **동적 총 투자금**: 기존 거래 데이터가 존재할 경우, `config.json`의 초기 투자금 대신 현재 보유하고 있는 코인과 현금의 총 가치를 기준으로 봇이 작동합니다.

## 🚀 시작하기

### 📋 사전 준비

1.  **Python 3.8 이상 설치**: [Python 공식 웹사이트](https://www.python.org/downloads/)에서 다운로드하여 설치합니다.
2.  **Upbit API 키 발급**: [Upbit 개발자 센터](https://upbit.com/developer_center)에서 Access Key와 Secret Key를 발급받습니다. (반드시 `입출금 기능 사용`은 체크 해제하고 `Open API 조회`와 `주문` 권한만 부여하세요.)
3.  **카카오톡 알림 설정 (선택 사항)**: 카카오톡 메시지를 받으려면 [카카오 개발자 센터](https://developers.kakao.com/)에서 카카오톡 메시지 전송을 위한 설정을 완료해야 합니다.

### ⚙️ 설치 및 실행

1.  **프로젝트 클론 또는 다운로드**:
    ```bash
    git clone [프로젝트_레포지토리_URL]
    cd [프로젝트_폴더_이름]
    ```
2.  **가상 환경 설정 및 활성화**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # macOS/Linux
    # venv\Scripts\activate  # Windows
    ```
3.  **필요한 라이브러리 설치**:
    ```bash
    pip install -r requirements.txt
    ```
    (requirements.txt 파일이 없다면, 다음 라이브러리들을 수동으로 설치해주세요: `pyupbit`, `requests`, `matplotlib`, `pandas`, `numpy`, `xlsxwriter`, `pyttsx3`)
4.  **`config.json` 설정**:
    프로젝트 루트 디렉토리에 `config.json` 파일을 생성하고, 발급받은 Upbit API 키와 기타 설정을 입력합니다.
    ```json
    {
        "upbit_access": "YOUR_UPBIT_ACCESS_KEY",
        "upbit_secret": "YOUR_UPBIT_SECRET_KEY",
        "kakao_token": "YOUR_KAKAO_TOKEN",
        "tts_enabled": true,
        "kakao_enabled": true,
        "panic_threshold": -5.0,
        "stop_loss_threshold": -10.0,
        "trailing_stop": true,
        "trailing_stop_percent": 3.0,
        "emergency_exit_enabled": true,
        "use_limit_orders": true,
        "limit_order_buffer": 0.2,
        "max_position_size": 0.3,
        "total_investment": "100000000",
        "grid_count": "8",
        "period": "1시간",
        "target_profit_percent": "10",
        "demo_mode": 1,
        "auto_grid_count": true
    }
    ```
    *   `upbit_access`, `upbit_secret`: Upbit API 키
    *   `kakao_token`: 카카오톡 알림을 위한 토큰 (선택 사항)
    *   `tts_enabled`: TTS(Text-to-Speech) 음성 안내 활성화 여부
    *   `kakao_enabled`: 카카오톡 알림 활성화 여부
    *   `panic_threshold`: 패닉 모드 진입을 위한 손실 임계점 (%)
    *   `stop_loss_threshold`: 손절매를 위한 손실 임계점 (%)
    *   `trailing_stop`: 트레일링 스탑 활성화 여부
    *   `trailing_stop_percent`: 트레일링 스탑 발동 비율 (%)
    *   `emergency_exit_enabled`: 긴급 청산 활성화 여부
    *   `use_limit_orders`: 지정가 주문 사용 여부
    *   `limit_order_buffer`: 지정가 주문 시 현재가 대비 버퍼 (%)
    *   `max_position_size`: 단일 코인에 대한 최대 투자 비율 (총 투자금 대비)
    *   `total_investment`: 초기 총 투자금 (문자열 형식)
    *   `grid_count`: 그리드 개수
    *   `period`: 차트 및 그리드 계산 기준 시간 단위 (예: "1시간", "4시간", "1일")
    *   `target_profit_percent`: 목표 수익률 (%)
    *   `demo_mode`: 데모 모드 활성화 (1: 활성화, 0: 비활성화)
    *   `auto_grid_count`: 그리드 개수 자동 계산 활성화 여부

5.  **봇 실행**:
    ```bash
    python main.py
    ```

## 🖥️ GUI 사용법

봇을 실행하면 직관적인 GUI가 나타납니다.

*   **코인 선택**: 거래할 코인을 선택합니다.
*   **설정 탭**:
    *   **총 투자금**: 봇이 운용할 총 투자금을 설정합니다.
    *   **그리드 개수**: 그리드 트레이딩에 사용할 그리드 개수를 설정합니다.
    *   **기간**: 차트 및 그리드 계산 기준 시간 단위를 설정합니다.
    *   **목표 수익률**: 목표 수익률을 설정합니다.
    *   **데모 모드**: 데모 거래를 활성화/비활성화합니다.
    *   **시작/중지 버튼**: 거래 봇을 시작하거나 중지합니다.
    *   **⚙️ 시스템 설정**: `config.json` 파일을 열어 고급 설정을 직접 편집할 수 있습니다.
    *   **📊 백테스트**: 과거 데이터를 기반으로 전략의 성능을 시뮬레이션합니다.
    *   **📄 엑셀 내보내기**: 현재 거래 데이터를 엑셀 파일로 내보냅니다.
    *   **🗑️ 데이터 초기화**: `trading_state.json`, `profits.json`, `trade_logs.json` 파일을 삭제하고 `config.json`의 `total_investment`를 기본값으로 재설정합니다. **주의: 이 작업은 모든 거래 기록을 삭제합니다.**

*   **실시간 차트 및 그리드**: 선택한 코인의 실시간 가격 차트와 그리드 레벨을 시각적으로 보여줍니다.
*   **거래 현황**: 현재 보유 코인, 현금 잔액, 총 자산, 평가 손익, 실현 손익 등을 실시간으로 표시합니다.
*   **거래 로그**: 봇의 모든 거래 활동 및 시스템 메시지를 기록합니다.

## 🗄️ 데이터 파일

*   `config.json`: 봇의 설정 정보를 저장합니다.
*   `trading_state.json`: 현재 보유하고 있는 코인 포지션 및 거래 상태를 저장합니다. 프로그램 재시작 시 이어서 거래할 수 있도록 합니다.
*   `profits.json`: 실현된 수익 및 손실 기록을 저장합니다.
*   `trade_logs.json`: 모든 거래 활동 및 시스템 로그를 저장합니다.

## ⚠️ 주의 사항

*   이 봇은 투자 전략의 예시이며, 실제 투자에는 손실 위험이 따릅니다.
*   API 키 관리에 유의하고, 민감한 정보가 노출되지 않도록 주의하십시오.
*   데모 모드에서 충분히 테스트한 후 실제 거래에 사용하십시오.

## 🛠️ 문제 해결

### 카카오톡 알림 실패 (`this access token does not exist`)

이 오류는 `config.json`에 설정된 `kakao_token`이 유효하지 않거나 만료되었을 때 발생합니다.

**해결 방법:**

1.  [카카오 개발자 센터](https://developers.kakao.com/)에 로그인합니다.
2.  새로운 액세스 토큰을 발급받거나 기존 토큰을 갱신합니다.
3.  발급받은 새 토큰으로 `config.json` 파일의 `kakao_token` 값을 업데이트합니다.
4.  프로그램을 재시작합니다.