import pyupbit
import time
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
import requests
from queue import Queue
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd
import numpy as np
import os
from pathlib import Path
import xlsxwriter
import pyttsx3

# TTS 엔진 초기화
try:
    tts_engine = pyttsx3.init()
    # 말하기 속도 조절 (기본값: 200)
    rate = tts_engine.getProperty('rate')
    tts_engine.setProperty('rate', 150) # 150으로 설정 (보통 속도)
    
    tts_queue = Queue()
    tts_lock = threading.Lock()
    tts_worker_thread = None
except Exception as e:
    print(f"TTS 엔진 초기화 오류: {e}")
    tts_engine = None

def tts_worker():
    """TTS 큐의 메시지를 순차적으로 처리하는 작업자"""
    while True:
        try:
            text = tts_queue.get()
            if text is None: # 종료 신호
                break
            with tts_lock:
                if tts_engine:
                    tts_engine.say(text)
                    tts_engine.runAndWait()
            tts_queue.task_done()
        except Exception as e:
            print(f"TTS 작업자 오류: {e}")

def speak_async(text):
    """TTS 큐에 메시지를 추가 (논블로킹)"""
    if tts_engine and config.get('tts_enabled', True):
        tts_queue.put(text)

def start_tts_worker():
    """TTS 작업자 스레드 시작"""
    global tts_worker_thread
    if tts_engine and (tts_worker_thread is None or not tts_worker_thread.is_alive()):
        tts_worker_thread = threading.Thread(target=tts_worker, daemon=True)
        tts_worker_thread.start()

def stop_tts_worker():
    """TTS 작업자 스레드 종료"""
    if tts_worker_thread and tts_worker_thread.is_alive():
        tts_queue.put(None) # 종료 신호
        tts_worker_thread.join(timeout=2)


# 설정 파일 관리
config_file = "config.json"
profit_file = "profits.json"
log_file = "trade_logs.json"
state_file = "trading_state.json"
state_lock = threading.Lock() # 상태 파일 접근을 위한 락

default_config = {
    "upbit_access": "",
    "upbit_secret": "",
    "kakao_token": "",
    "panic_threshold": -5.0,  # 급락 임계값 (%)
    "stop_loss_threshold": -10.0,  # 손절 임계값 (%)
    "trailing_stop": True,  # 트레일링 스탑 사용
    "trailing_stop_percent": 3.0,  # 트레일링 스탑 비율 (%)
    "use_limit_orders": True,  # 지정가 주문 사용
    "limit_order_buffer": 0.2,  # 지정가 주문 버퍼 (%)
    "max_position_size": 0.3,  # 최대 포지션 크기 (총 자산 대비)
    "emergency_exit_enabled": True,  # 긴급 청산 활성화
    "auto_grid_count": True, # 그리드 개수 자동 계산
    "tts_enabled": True, # TTS 음성 안내 사용
    "kakao_enabled": True, # 카카오톡 알림 사용
    "total_investment": "100000",
    "grid_count": "10",
    "period": "4시간",
    "target_profit_percent": "10",
    "demo_mode": 1
}

def save_trading_state(ticker, positions, demo_mode):
    """현재 포지션 상태를 파일에 저장"""
    with state_lock:
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                all_states = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            all_states = {}
        
        state_key = f"demo_{ticker}" if demo_mode else f"real_{ticker}"
        all_states[state_key] = positions
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(all_states, f, indent=4, ensure_ascii=False)

def load_trading_state(ticker, demo_mode):
    """파일에서 포지션 상태를 로드"""
    with state_lock:
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                all_states = json.load(f)
            state_key = f"demo_{ticker}" if demo_mode else f"real_{ticker}"
            return all_states.get(state_key, [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []


def load_config():
    """설정 파일 로드"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        # 기본값으로 누락된 키 채우기
        for key, value in default_config.items():
            if key not in config:
                config[key] = value
        return config
    except (FileNotFoundError, json.JSONDecodeError):
        return default_config.copy()

def save_config(config):
    """설정 파일 저장"""
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"설정 저장 오류: {e}")
        return False

# 전역 설정
config = load_config()
upbit = None

def initialize_upbit():
    """업비트 API 초기화"""
    global upbit
    if config["upbit_access"] and config["upbit_secret"]:
        try:
            upbit = pyupbit.Upbit(config["upbit_access"], config["upbit_secret"])
            return True
        except Exception as e:
            print(f"업비트 API 초기화 실패: {e}")
            return False
    return False

# 카카오톡 알림 API
def send_kakao_message(message):
    """카카오톡 메시지 전송"""
    if not config["kakao_token"]:
        print("카카오톡 토큰이 설정되지 않았습니다.")
        return
        
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {config['kakao_token']}"}
    data = {"template_object": json.dumps({
        "object_type": "text",
        "text": message,
        "link": {"web_url": "https://upbit.com"}
    })}
    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        if response.status_code != 200:
            print(f"카카오톡 전송 실패: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"카카오톡 전송 중 오류 발생: {e}")

# JSON 파일 관리
def initialize_files():
    """필요한 JSON 파일들 초기화"""
    for file in [profit_file, log_file, config_file]:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            if file == config_file:
                save_config(default_config)
            else:
                with open(file, 'w', encoding='utf-8') as f:
                    json.dump({}, f)

def export_to_excel(filename=None):
    """로그와 수익 데이터를 엑셀로 내보내기"""
    if filename is None:
        filename = f"trading_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    try:
        workbook = xlsxwriter.Workbook(filename)
        
        # 거래 로그 시트
        log_sheet = workbook.add_worksheet("거래로그")
        log_headers = ["시간", "코인", "행동", "가격/내용"]
        
        for col, header in enumerate(log_headers):
            log_sheet.write(0, col, header)
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            
            row = 1
            for ticker, ticker_logs in logs.items():
                for log_entry in ticker_logs:
                    log_sheet.write(row, 0, log_entry.get('time', ''))
                    log_sheet.write(row, 1, ticker)
                    log_sheet.write(row, 2, log_entry.get('action', ''))
                    log_sheet.write(row, 3, log_entry.get('price', ''))
                    row += 1
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        # 수익 데이터 시트
        profit_sheet = workbook.add_worksheet("수익데이터")
        profit_headers = ["시간", "코인", "수익"]
        
        for col, header in enumerate(profit_headers):
            profit_sheet.write(0, col, header)
        
        try:
            with open(profit_file, 'r', encoding='utf-8') as f:
                profits = json.load(f)
            
            row = 1
            for ticker, ticker_profits in profits.items():
                for profit_entry in ticker_profits:
                    profit_sheet.write(row, 0, profit_entry.get('time', ''))
                    profit_sheet.write(row, 1, ticker)
                    profit_sheet.write(row, 2, profit_entry.get('profit', 0))
                    row += 1
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        workbook.close()
        return True, filename
    except Exception as e:
        print(f"엑셀 내보내기 오류: {e}")
        return False, str(e)

def update_profit(ticker, profit):
    """수익 데이터 업데이트"""
    try:
        try:
            with open(profit_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        
        if ticker not in data:
            data[ticker] = []
        data[ticker].append({
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'profit': profit
        })
        
        with open(profit_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
    except Exception as e:
        print(f"수익 파일 처리 중 오류 발생: {e}")

def log_trade(ticker, action, price, log_callback=None):
    """거래 로그 기록"""
    entry = {
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': action,
        'price': f"{price:,.0f}" if isinstance(price, (int, float)) else price
    }
    
    try:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        
        if ticker not in data:
            data[ticker] = []
        data[ticker].append(entry)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
    except Exception as e:
        print(f"로그 파일 처리 중 오류 발생: {e}")

    if log_callback:
        full_log_entry = entry.copy()
        full_log_entry['ticker'] = ticker
        log_callback(full_log_entry)

# 급락 감지 및 대응 전략
def detect_panic_selling(ticker, current_price, previous_prices, threshold_percent=-5.0):
    """급락 상황 감지"""
    if len(previous_prices) < 10:  # 최소 10개 데이터 필요
        return False
    
    # 최근 10분간 평균 가격과 비교
    recent_avg = sum(previous_prices[-10:]) / 10
    price_change_percent = ((current_price - recent_avg) / recent_avg) * 100
    
    return price_change_percent <= threshold_percent

def calculate_dynamic_grid(ticker, base_low, base_high, current_price, panic_mode=False):
    """동적 그리드 계산 (급락장 대응)"""
    if panic_mode:
        # 급락장에서는 더 조밀한 그리드와 현재가 중심의 범위 설정
        price_range = (base_high - base_low) * 0.6  # 범위를 60%로 축소
        new_low = max(base_low, current_price - price_range * 0.7)  # 현재가 아래 70%
        new_high = min(base_high, current_price + price_range * 0.3)  # 현재가 위 30%
        return new_low, new_high
    
    return base_low, base_high

# 개선된 주문 실행 함수
def execute_buy_order(ticker, amount, current_price, use_limit=True):
    """개선된 매수 주문 실행"""
    global upbit
    if upbit is None:
        return None
    
    try:
        if use_limit and config.get("use_limit_orders", True):
            # 지정가 주문 (현재가보다 약간 높게)
            buffer = config.get("limit_order_buffer", 0.2) / 100
            limit_price = current_price * (1 + buffer)
            # 업비트 가격 단위에 맞춰 조정
            limit_price = round(limit_price)
            
            quantity = amount / limit_price
            return upbit.buy_limit_order(ticker, limit_price, quantity)
        else:
            # 시장가 주문
            return upbit.buy_market_order(ticker, amount)
    except requests.exceptions.RequestException as e:
        print(f"매수 주문 네트워크 오류: {e}")
        return None
    except Exception as e:
        print(f"매수 주문 실행 오류: {e}")
        return None

def execute_sell_order(ticker, quantity, current_price, use_limit=True):
    """개선된 매도 주문 실행"""
    global upbit
    if upbit is None:
        return None
    
    try:
        if use_limit and config.get("use_limit_orders", True):
            # 지정가 주문 (현재가보다 약간 낮게)
            buffer = config.get("limit_order_buffer", 0.2) / 100
            limit_price = current_price * (1 - buffer)
            limit_price = round(limit_price)
            
            return upbit.sell_limit_order(ticker, limit_price, quantity)
        else:
            # 시장가 주문
            return upbit.sell_market_order(ticker, quantity)
    except requests.exceptions.RequestException as e:
        print(f"매도 주문 네트워크 오류: {e}")
        return None
    except Exception as e:
        print(f"매도 주문 실행 오류: {e}")
        return None

# 상태 평가 개선
def evaluate_status(profit_percent, is_trading=False, panic_mode=False):
    """상태 평가 (급락 모드 포함)"""
    if not is_trading:
        return "대기중", "Gray.TLabel"
    elif panic_mode:
        return "급락대응", "Purple.TLabel"
    elif profit_percent >= 3:
        return "매우좋음", "DarkGreen.TLabel"
    elif profit_percent >= 1:
        return "좋음", "Green.TLabel"
    elif profit_percent >= -1:
        return "보통", "Blue.TLabel"
    elif profit_percent >= -3:
        return "주의", "Orange.TLabel"
    else:
        return "위험", "Red.TLabel"

# 가격 범위 계산 함수
def calculate_price_range(ticker, period):
    """선택한 기간에 따라 상한가/하한가를 계산"""
    try:
        if period == "1시간":
            df = pyupbit.get_ohlcv(ticker, interval="minute60", count=1)
        elif period == "4시간":
            df = pyupbit.get_ohlcv(ticker, interval="minute60", count=4)
        elif period == "1일":
            df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
        elif period == "7일":
            df = pyupbit.get_ohlcv(ticker, interval="day", count=7)
        else:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
        
        if df is None or df.empty:
            return None, None
        
        high_price = df['high'].max()
        low_price = df['low'].min()
        
        # 약간의 여유를 두어 범위 확장 (상한 +2%, 하한 -2%)
        high_price = high_price * 1.02
        low_price = low_price * 0.98
        
        return high_price, low_price
    except Exception as e:
        print(f"가격 범위 계산 오류: {e}")
        return None, None

def calculate_optimal_grid_count(high_price, low_price):
    """가격 범위에 따라 최적의 그리드 개수를 계산"""
    if low_price <= 0:
        return 10  # 기본값

    price_range_percent = ((high_price - low_price) / low_price) * 100
    
    if price_range_percent < 5:
        return 8
    elif price_range_percent < 10:
        return 6
    elif price_range_percent < 15:
        return 5
    else:
        return 4

# 차트 데이터 가져오기
def get_chart_data(ticker, period):
    """차트용 데이터 가져오기"""
    try:
        if period == "1시간":
            df = pyupbit.get_ohlcv(ticker, interval="minute5", count=60)
        elif period == "4시간":
            df = pyupbit.get_ohlcv(ticker, interval="minute15", count=96)
        elif period == "1일":
            df = pyupbit.get_ohlcv(ticker, interval="minute60", count=48)
        elif period == "7일":
            df = pyupbit.get_ohlcv(ticker, interval="day", count=14)
        else:
            df = pyupbit.get_ohlcv(ticker, interval="minute60", count=48)
        
        return df
    except Exception as e:
        print(f"차트 데이터 가져오기 오류: {e}")
        return None

# 백테스트 모듈
def run_backtest(ticker, total_investment, grid_count, period, stop_loss_threshold, use_trailing_stop, trailing_stop_percent, auto_grid):
    """상세 백테스트 실행"""
    try:
        # 기간에 따라 데이터 가져오기
        if period == "1일":
            df = pyupbit.get_ohlcv(ticker, interval="day", count=90) # 3개월
        elif period == "7일":
            df = pyupbit.get_ohlcv(ticker, interval="day", count=180) # 6개월
        elif period == "4시간":
            df = pyupbit.get_ohlcv(ticker, interval="minute240", count=24 * 30) # 1개월
        elif period == "1시간":
            df = pyupbit.get_ohlcv(ticker, interval="minute60", count=24 * 14) # 2주
        else:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=90)

        if df is None or df.empty:
            print("백테스트 데이터 로드 실패")
            return None

        # 초기 설정
        initial_balance = total_investment
        balance = initial_balance
        positions = []
        trades = []
        fee_rate = 0.0005
        
        # 가격 범위 및 그리드 설정
        high_price, low_price = calculate_price_range(ticker, period)
        if not high_price or not low_price:
             # 전체 데이터에서 계산
            high_price = df['high'].max()
            low_price = df['low'].min()

        if auto_grid:
            grid_count = calculate_optimal_grid_count(high_price, low_price)

        price_gap = (high_price - low_price) / grid_count
        amount_per_grid = total_investment / grid_count
        grid_levels = [low_price + (price_gap * i) for i in range(grid_count + 1)]

        # 통계용 변수
        buy_count = 0
        sell_count = 0
        win_count = 0
        total_profit = 0
        highest_value = initial_balance
        lowest_value = initial_balance

        # 데이터 순회하며 시뮬레이션
        for i in range(1, len(df)):
            prev_price = df.iloc[i-1]['close']
            current_price = df.iloc[i]['close']
            
            # 매수 로직
            for j, grid_price in enumerate(grid_levels[:-1]):
                if prev_price > grid_price and current_price <= grid_price:
                    already_bought = any(pos['buy_grid_level'] == j for pos in positions)
                    if not already_bought and balance >= amount_per_grid:
                        quantity = (amount_per_grid / current_price) * (1 - fee_rate)
                        balance -= amount_per_grid
                        
                        target_sell_price = grid_levels[j + 1]
                        
                        positions.append({
                            'buy_price': current_price,
                            'quantity': quantity,
                            'target_sell_price': target_sell_price,
                            'highest_price': current_price, # 트레일링 스탑용
                            'buy_grid_level': j
                        })
                        trades.append({'date': df.index[i], 'type': 'buy', 'price': current_price, 'quantity': quantity})
                        buy_count += 1

            # 매도 로직
            for pos in positions[:]:
                sell_condition = False
                
                # 1. 목표가 도달
                if current_price >= pos['target_sell_price']:
                    sell_condition = True
                
                # 2. 트레일링 스탑
                if use_trailing_stop:
                    pos['highest_price'] = max(pos['highest_price'], current_price)
                    trailing_price = pos['highest_price'] * (1 - trailing_stop_percent / 100)
                    if current_price < trailing_price:
                        sell_condition = True
                
                # 3. 손절
                if current_price <= pos['buy_price'] * (1 + stop_loss_threshold / 100):
                    sell_condition = True

                if sell_condition:
                    sell_value = pos['quantity'] * current_price
                    net_sell_value = sell_value * (1 - fee_rate)
                    balance += net_sell_value
                    
                    profit = net_sell_value - (pos['quantity'] * pos['buy_price'])
                    total_profit += profit
                    if profit > 0:
                        win_count += 1

                    positions.remove(pos)
                    trades.append({'date': df.index[i], 'type': 'sell', 'price': current_price, 'quantity': pos['quantity']})
                    sell_count += 1

            # 현재 자산 가치 업데이트
            current_value = balance + sum(p['quantity'] * current_price for p in positions)
            highest_value = max(highest_value, current_value)
            lowest_value = min(lowest_value, current_value)

        # 최종 결과 계산
        final_value = balance + sum(p['quantity'] * df.iloc[-1]['close'] for p in positions)
        total_return = (final_value - initial_balance) / initial_balance * 100
        win_rate = (win_count / sell_count * 100) if sell_count > 0 else 0

        return {
            'total_return': total_return,
            'final_value': final_value,
            'num_trades': len(trades),
            'initial_balance': initial_balance,
            'buy_count': buy_count,
            'sell_count': sell_count,
            'win_rate': win_rate,
            'highest_value': highest_value,
            'lowest_value': lowest_value,
            'start_date': df.index[0].strftime('%Y-%m-%d'),
            'end_date': df.index[-1].strftime('%Y-%m-%d')
        }
        
    except Exception as e:
        import traceback
        print(f"백테스트 오류: {e}")
        traceback.print_exc()
        return None

# 개선된 그리드 트레이딩 로직
def grid_trading(ticker, grid_count, total_investment, demo_mode, target_profit_percent, period, stop_event, gui_queue):
    """개선된 그리드 트레이딩 (급락장 대응 포함)"""
    start_time = datetime.now()
    
    def update_gui(key, *args):
        gui_queue.put((key, ticker, args))

    # 가격 범위 계산
    high_price, low_price = calculate_price_range(ticker, period)
    if high_price is None or low_price is None:
        log_trade(ticker, '오류', '가격 범위 계산 실패', lambda log: update_gui('log', log))
        update_gui('status', "상태: 시작 실패", "Red.TLabel", False, False)
        return

    current_price = pyupbit.get_current_price(ticker)
    if current_price is None:
        log_trade(ticker, '오류', '시작 가격 조회 실패', lambda log: update_gui('log', log))
        update_gui('status', "상태: 시작 실패", "Red.TLabel", False, False)
        return

    log_trade(ticker, '시작', f"{period} 범위: {low_price:,.0f}~{high_price:,.0f}", lambda log: update_gui('log', log))
    
    # 그리드 간격 계산
    price_gap = (high_price - low_price) / grid_count
    amount_per_grid = total_investment / grid_count
    
    # 그리드 가격 레벨 생성
    grid_levels = []
    for i in range(grid_count + 1):
        price_level = low_price + (price_gap * i)
        grid_levels.append(price_level)
    
    log_trade(ticker, '설정', f"그리드 간격: {price_gap:,.0f}원, 격당투자: {amount_per_grid:,.0f}원", 
              lambda log: update_gui('log', log))

    fee_rate = 0.0005
    previous_prices = []  # 급락 감지용 이전 가격들
    panic_mode = False
    highest_value = total_investment  # 트레일링 스탑용 최고 자산 가치
    
    if demo_mode:
        start_balance = total_investment
        demo_balance = total_investment
        demo_positions = load_trading_state(ticker, True)
        if demo_positions:
            log_trade(ticker, '정보', f'{len(demo_positions)}개의 포지션을 복원했습니다.', lambda log: update_gui('log', log))
        total_invested = 0
    else:
        if upbit is None:
            log_trade(ticker, '오류', '업비트 API 초기화 안됨', lambda log: update_gui('log', log))
            update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
            return
            
        start_balance = upbit.get_balance("KRW")
        if start_balance is None:
            log_trade(ticker, '오류', '잔액 조회 실패', lambda log: update_gui('log', log))
            update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
            return
        real_positions = load_trading_state(ticker, False)
        if real_positions:
            log_trade(ticker, '정보', f'{len(real_positions)}개의 포지션을 복원했습니다.', lambda log: update_gui('log', log))
        total_invested = 0
    
    prev_price = current_price
    update_gui('chart_data', high_price, low_price, grid_levels)
    
    total_realized_profit = 0
    last_update_day = datetime.now().day

    while not stop_event.is_set():
        # 9시 정각 그리드 자동 갱신
        now = datetime.now()
        if config.get('auto_grid_count', True) and now.hour == 9 and now.day != last_update_day:
            log_trade(ticker, '정보', '오전 9시, 그리드 설정을 자동 갱신합니다.', lambda log: update_gui('log', log))
            
            new_high, new_low = calculate_price_range(ticker, period)
            if new_high and new_low:
                high_price, low_price = new_high, new_low
                grid_count = calculate_optimal_grid_count(high_price, low_price)
                price_gap = (high_price - low_price) / grid_count
                grid_levels = [low_price + (price_gap * i) for i in range(grid_count + 1)]
                
                log_trade(ticker, '설정 갱신', f"새 그리드: {grid_count}개, 범위: {low_price:,.0f}~{high_price:,.0f}", lambda log: update_gui('log', log))
                update_gui('chart_data', high_price, low_price, grid_levels)
            
            last_update_day = now.day

        try:
            price = pyupbit.get_current_price(ticker)
            if price is None:
                time.sleep(1) # None을 반환하는 경우 잠시 후 재시도
                continue
        except requests.exceptions.RequestException as e:
            log_trade(ticker, '오류', f'네트워크 오류 발생: {e}', lambda log: update_gui('log', log))
            time.sleep(10) # 네트워크 불안정시 더 길게 대기
            continue
        
        # 운영 시간 계산
        running_time = datetime.now() - start_time
        hours, remainder = divmod(int(running_time.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        running_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        update_gui('price', f"현재가: {price:,.0f}원", "Black.TLabel")
        update_gui('running_time', f"운영시간: {running_time_str}")
        
        # 가격 히스토리 업데이트 (급락 감지용)
        previous_prices.append(price)
        if len(previous_prices) > 30:  # 최근 30개만 유지
            previous_prices.pop(0)
        
        # 급락 상황 감지
        new_panic_mode = detect_panic_selling(ticker, price, previous_prices, config.get("panic_threshold", -5.0))
        if new_panic_mode and not panic_mode:
            log_trade(ticker, '급락감지', '급락 대응 모드 활성화', lambda log: update_gui('log', log))
            send_kakao_message(f"{ticker} 급락 감지! 대응 모드 활성화")
            
            # 동적 그리드 재계산
            new_low, new_high = calculate_dynamic_grid(ticker, low_price, high_price, price, True)
            new_price_gap = (new_high - new_low) / grid_count
            grid_levels = [new_low + (new_price_gap * i) for i in range(grid_count + 1)]
            update_gui('chart_data', new_high, new_low, grid_levels)
            
        panic_mode = new_panic_mode

        if demo_mode:
            # 데모 모드 매수 로직
            for i, grid_price in enumerate(grid_levels[:-1]):
                if prev_price > grid_price and price <= grid_price:
                    already_bought = any(pos['buy_price'] == grid_price for pos in demo_positions)
                    
                    if not already_bought and demo_balance >= amount_per_grid:
                        # 급락 모드에서는 더 적극적으로 매수
                        buy_multiplier = 1.5 if panic_mode else 1.0
                        actual_buy_amount = min(amount_per_grid * buy_multiplier, demo_balance)
                        
                        buy_amount = actual_buy_amount * (1 - fee_rate)
                        quantity = buy_amount / price
                        demo_balance -= actual_buy_amount
                        total_invested += actual_buy_amount
                        
                        target_sell_price = grid_levels[i + 1]
                        min_sell_price = price * (1 + 2 * fee_rate + 0.0005)
                        if target_sell_price < min_sell_price:
                            target_sell_price = min_sell_price

                        demo_positions.append({
                            'buy_price': grid_price,
                            'quantity': quantity,
                            'target_sell_price': target_sell_price,
                            'actual_buy_price': price,
                            'highest_price': price  # 트레일링 스탑용
                        })
                        save_trading_state(ticker, demo_positions, True)
                        
                        log_msg = f"그리드{i+1} 매수: {price:,.0f}원 ({quantity:.6f}개) → 목표: {target_sell_price:,.0f}원"
                        if panic_mode:
                            log_msg += " [급락대응]"
                        log_trade(ticker, "데모 매수", log_msg, lambda log: update_gui('log', log))
                        
                        # TTS 음성 안내
                        if config.get('tts_enabled', True):
                            tts_msg = f"데모 모드, 그리드 {i+1}, {ticker.replace('KRW-','')}" + f" {price:,.0f}원에 매수되었습니다."
                            speak_async(tts_msg)

                        # 카카오톡 알림
                        if config.get('kakao_enabled', True):
                            kakao_msg = f"[데모 매수] {ticker.replace('KRW-','')} {price:,.0f}원 ({quantity:.6f}개) 매수"
                            send_kakao_message(kakao_msg)

                        update_gui('refresh_chart')
            
            # 데모 모드 매도 로직 (트레일링 스탑 포함)
            for position in demo_positions[:]:
                # 최고가 업데이트
                if price > position['highest_price']:
                    position['highest_price'] = price
                
                sell_condition = False
                sell_reason = ""
                
                # 목표가 도달
                if price >= position['target_sell_price']:
                    sell_condition = True
                    sell_reason = "목표달성"
                
                # 트레일링 스탑
                elif config.get("trailing_stop", True):
                    trailing_percent = config.get("trailing_stop_percent", 3.0) / 100
                    if price <= position['highest_price'] * (1 - trailing_percent):
                        sell_condition = True
                        sell_reason = "트레일링스탑"
                
                # 손절
                elif price <= position['actual_buy_price'] * (1 + config.get("stop_loss_threshold", -10.0) / 100):
                    sell_condition = True
                    sell_reason = "손절"
                
                if sell_condition:
                    sell_amount = position['quantity'] * price
                    sell_fee = sell_amount * fee_rate
                    net_sell_amount = sell_amount - sell_fee
                    
                    demo_balance += net_sell_amount
                    demo_positions.remove(position)
                    save_trading_state(ticker, demo_positions, True)
                    
                    buy_cost = position['quantity'] * position['actual_buy_price']
                    net_profit = net_sell_amount - buy_cost
                    total_realized_profit += net_profit

                    log_msg = f"{sell_reason} 매도: {price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원"
                    log_trade(ticker, "데모 매도", log_msg, lambda log: update_gui('log', log))

                    # TTS 음성 안내
                    if config.get('tts_enabled', True):
                        tts_msg = f"데모 모드, {sell_reason}, {ticker.replace('KRW-','')}" + f" {price:,.0f}원에 매도되었습니다."
                        speak_async(tts_msg)

                    # 카카오톡 알림
                    if config.get('kakao_enabled', True):
                        kakao_msg = f"[데모 매도] {ticker.replace('KRW-','')} {price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원 ({sell_reason})"
                        send_kakao_message(kakao_msg)

                    update_gui('refresh_chart')
            
            # 긴급 청산 체크
            held_value = sum(pos['quantity'] * price for pos in demo_positions)
            total_value = demo_balance + held_value
            profit_percent = (total_value - start_balance) / start_balance * 100 if start_balance > 0 else 0
            
            if (config.get("emergency_exit_enabled", True) and 
                profit_percent <= config.get("stop_loss_threshold", -10.0)):
                # 모든 포지션 청산
                for position in demo_positions[:]:
                    sell_amount = position['quantity'] * price
                    sell_fee = sell_amount * fee_rate
                    net_sell_amount = sell_amount - sell_fee
                    demo_balance += net_sell_amount
                    demo_positions.remove(position)
                save_trading_state(ticker, demo_positions, True) # 상태 저장
                
                log_trade(ticker, '긴급청산', f'손실 임계점 도달: {profit_percent:.2f}%', lambda log: update_gui('log', log))
                send_kakao_message(f"{ticker} 긴급 청산 실행! 손실률: {profit_percent:.2f}%")
                break
            
            # 트레일링 스탑 (전체 포트폴리오)
            if total_value > highest_value:
                highest_value = total_value
            elif (config.get("trailing_stop", True) and 
                  total_value <= highest_value * (1 - config.get("trailing_stop_percent", 3.0) / 100)):
                log_trade(ticker, '트레일링청산', f'최고점 대비 {config.get("trailing_stop_percent", 3.0)}% 하락', lambda log: update_gui('log', log))
                break
                
            profit = total_value - start_balance
            realized_profit_percent = (total_realized_profit / total_investment) * 100 if total_investment > 0 else 0
            coin_quantity = sum(pos['quantity'] for pos in demo_positions)
            
            update_gui('details', demo_balance, coin_quantity, held_value, total_value, profit, profit_percent, total_realized_profit, realized_profit_percent)
            
        else:
            # 실제 거래 모드 매수 로직
            for i, grid_price in enumerate(grid_levels[:-1]):
                if prev_price > grid_price and price <= grid_price:
                    already_bought = any(pos['buy_price'] == grid_price for pos in real_positions)
                    
                    if not already_bought:
                        buy_multiplier = 1.5 if panic_mode else 1.0
                        actual_buy_amount = amount_per_grid * buy_multiplier
                        
                        res = execute_buy_order(ticker, actual_buy_amount, price, config.get("use_limit_orders", True))
                        if res and 'uuid' in res:
                            time.sleep(1)
                            order_info = upbit.get_order(res['uuid'])
                            if order_info and order_info.get('state') == 'done':
                                executed_volume = float(order_info.get('executed_volume', 0))
                                paid_fee = float(order_info.get('paid_fee', 0))
                                if executed_volume > 0:
                                    target_sell_price = grid_levels[i + 1]
                                    min_sell_price = price * (1 + 2 * fee_rate + 0.0005)
                                    if target_sell_price < min_sell_price:
                                        target_sell_price = min_sell_price

                                    real_positions.append({
                                        'buy_price': grid_price,
                                        'quantity': executed_volume,
                                        'target_sell_price': target_sell_price,
                                        'actual_buy_price': price,
                                        'fee': paid_fee,
                                        'highest_price': price
                                    })
                                    save_trading_state(ticker, real_positions, False)
                                    total_invested += actual_buy_amount
                                    
                                    log_msg = f"그리드{i+1} 매수: {price:,.0f}원 ({executed_volume:.6f}개) → 목표: {target_sell_price:,.0f}원"
                                    if panic_mode:
                                        log_msg += " [급락대응]"
                                    log_trade(ticker, "실제 매수", log_msg, lambda log: update_gui('log', log))

                                    # TTS 음성 안내
                                    if config.get('tts_enabled', True):
                                        tts_msg = f"그리드 {i+1}, {ticker.replace('KRW-','')}" + f" {price:,.0f}원에 매수되었습니다."
                                        speak_async(tts_msg)

                                    # 카카오톡 알림
                                    if config.get('kakao_enabled', True):
                                        kakao_msg = f"[실제 매수] {ticker.replace('KRW-','')} {price:,.0f}원 ({executed_volume:.6f}개) 매수"
                                        send_kakao_message(kakao_msg)

                                    update_gui('refresh_chart')
                        else:
                            log_trade(ticker, '오류', '매수 주문 실패', lambda log: update_gui('log', log))
            
            # 실제 거래 모드 매도 로직
            for position in real_positions[:]:
                if price > position['highest_price']:
                    position['highest_price'] = price
                
                sell_condition = False
                sell_reason = ""
                
                if price >= position['target_sell_price']:
                    sell_condition = True
                    sell_reason = "목표달성"
                elif config.get("trailing_stop", True):
                    trailing_percent = config.get("trailing_stop_percent", 3.0) / 100
                    if price <= position['highest_price'] * (1 - trailing_percent):
                        sell_condition = True
                        sell_reason = "트레일링스탑"
                elif price <= position['actual_buy_price'] * (1 + config.get("stop_loss_threshold", -10.0) / 100):
                    sell_condition = True
                    sell_reason = "손절"
                
                if sell_condition:
                    res = execute_sell_order(ticker, position['quantity'], price, config.get("use_limit_orders", True))
                    if res and 'uuid' in res:
                        real_positions.remove(position)
                        save_trading_state(ticker, real_positions, False)
                        log_msg = f"{sell_reason} 매도: {price:,.0f}원 ({position['quantity']:.6f}개)"
                        log_trade(ticker, "실제 매도", log_msg, lambda log: update_gui('log', log))

                        # TTS 음성 안내
                        if config.get('tts_enabled', True):
                            tts_msg = f"{sell_reason}, {ticker.replace('KRW-','')}" + f" {price:,.0f}원에 매도되었습니다."
                            speak_async(tts_msg)

                        # 카카오톡 알림
                        if config.get('kakao_enabled', True):
                            kakao_msg = f"[실제 매도] {ticker.replace('KRW-','')} {price:,.0f}원 ({position['quantity']:.6f}개) 매도 ({sell_reason})"
                            send_kakao_message(kakao_msg)

                        update_gui('refresh_chart')
                    else:
                        log_trade(ticker, '오류', '매도 주문 실패', lambda log: update_gui('log', log))
            
            # 실제 잔액 기반 수익 계산
            current_balance = upbit.get_balance("KRW")
            coin_balance = upbit.get_balance(ticker)
            if current_balance is not None and coin_balance is not None:
                held_value = coin_balance * price
                total_value = current_balance + held_value
                profit = total_value - start_balance
                profit_percent = (profit / start_balance) * 100 if start_balance > 0 else 0
                realized_profit_percent = (total_realized_profit / total_investment) * 100 if total_investment > 0 else 0

                # 긴급 청산 체크
                if (config.get("emergency_exit_enabled", True) and 
                    profit_percent <= config.get("stop_loss_threshold", -10.0)):
                    # 모든 코인 매도
                    if coin_balance > 0:
                        upbit.sell_market_order(ticker, coin_balance)
                        real_positions.clear() # 모든 포지션 제거
                        save_trading_state(ticker, real_positions, False) # 상태 저장
                        log_trade(ticker, '긴급청산', f'손실 임계점 도달: {profit_percent:.2f}%', lambda log: update_gui('log', log))
                        send_kakao_message(f"{ticker} 긴급 청산 실행! 손실률: {profit_percent:.2f}%")
                        break

                update_gui('details', current_balance, coin_balance, held_value, total_value, profit, profit_percent, total_realized_profit, realized_profit_percent)

        update_profit(ticker, profit_percent)
        
        status, style = evaluate_status(profit_percent, True, panic_mode)
        update_gui('status', f"상태: {status}", style, True, panic_mode)

        # 목표 수익률 달성 체크
        if profit_percent >= target_profit_percent:
            log_trade(ticker, '성공', '목표 수익 달성', lambda log: update_gui('log', log))
            update_gui('status', "상태: 목표 달성!", "Blue.TLabel", True, False)
            save_trading_state(ticker, [], demo_mode) # 성공 시 상태 초기화
            
            # 상세 알림 메시지 생성
            summary_msg = (
                f"{ticker} 목표 달성 완료!\n"
                f"시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"목표 수익률: {target_profit_percent}%\n"
                f"실제 수익률: {profit_percent:.2f}%\n"
                f"운영 시간: {running_time_str}\n"
                f"총 거래 횟수: {len([log for log in previous_prices if 'trade' in str(log)])}\n"
                f"실현 수익: {total_realized_profit:,.0f}원"
            )
            send_kakao_message(summary_msg)
            break
        
        prev_price = price
        time.sleep(3)

    if stop_event.is_set():
        log_trade(ticker, '중지', '사용자 요청', lambda log: update_gui('log', log))
        update_gui('status', "상태: 중지됨", "Orange.TLabel", False, False)

# 설정 창
def open_settings_window(root, config, callback):
    """설정 창 열기"""
    settings_window = tk.Toplevel(root)
    settings_window.title("시스템 설정")
    settings_window.geometry("500x600")
    settings_window.transient(root)
    settings_window.grab_set()
    
    # 설정 변수들
    vars_dict = {}
    
    notebook = ttk.Notebook(settings_window)
    notebook.pack(expand=True, fill='both', padx=10, pady=10)
    
    # API 설정 탭
    api_frame = ttk.Frame(notebook)
    notebook.add(api_frame, text="API 설정")
    
    # --- Access Key ---
    ttk.Label(api_frame, text="업비트 Access Key:", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(10, 5))
    vars_dict['upbit_access'] = tk.StringVar(value=config.get('upbit_access', ''))
    
    access_frame = ttk.Frame(api_frame)
    access_frame.pack(fill='x', pady=(0, 10))

    access_entry = ttk.Entry(access_frame, textvariable=vars_dict['upbit_access'], show='*')
    access_entry.pack(side='left', fill='x', expand=True)

    def paste_into_access_entry():
        try:
            clipboard_text = root.clipboard_get()
            access_entry.delete(0, tk.END)
            access_entry.insert(0, clipboard_text)
        except tk.TclError:
            messagebox.showwarning("클립보드 오류", "클립보드가 비어있거나 텍스트가 아닙니다.")

    access_paste_button = ttk.Button(access_frame, text="붙여넣기", command=paste_into_access_entry)
    access_paste_button.pack(side='right', padx=(5, 0))

    # --- Secret Key ---
    ttk.Label(api_frame, text="업비트 Secret Key:", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=5)
    vars_dict['upbit_secret'] = tk.StringVar(value=config.get('upbit_secret', ''))

    secret_frame = ttk.Frame(api_frame)
    secret_frame.pack(fill='x', pady=(0, 10))
    
    secret_entry = ttk.Entry(secret_frame, textvariable=vars_dict['upbit_secret'], show='*')
    secret_entry.pack(side='left', fill='x', expand=True)

    def paste_into_secret_entry():
        try:
            clipboard_text = root.clipboard_get()
            secret_entry.delete(0, tk.END)
            secret_entry.insert(0, clipboard_text)
        except tk.TclError:
            messagebox.showwarning("클립보드 오류", "클립보드가 비어있거나 텍스트가 아닙니다.")

    secret_paste_button = ttk.Button(secret_frame, text="붙여넣기", command=paste_into_secret_entry)
    secret_paste_button.pack(side='right', padx=(5, 0))
    
    # 알림 설정 탭
    notification_frame = ttk.Frame(notebook)
    notebook.add(notification_frame, text="알림 설정")

    ttk.Label(notification_frame, text="카카오톡 액세스 토큰:", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(10, 5))
    vars_dict['kakao_token'] = tk.StringVar(value=config.get('kakao_token', ''))
    
    # 프레임으로 감싸서 입력창과 버튼을 나란히 배치
    kakao_frame = ttk.Frame(notification_frame)
    kakao_frame.pack(fill='x', pady=(0, 10))

    def paste_from_clipboard():
        try:
            clipboard_text = root.clipboard_get()
            kakao_entry.delete(0, tk.END)
            kakao_entry.insert(0, clipboard_text)
        except tk.TclError:
            messagebox.showwarning("클립보드 오류", "클립보드가 비어있거나 텍스트가 아닙니다.")

    paste_button = ttk.Button(kakao_frame, text="붙여넣기", command=paste_from_clipboard)
    paste_button.pack(side='right', padx=(5, 0))

    kakao_entry = ttk.Entry(kakao_frame, textvariable=vars_dict['kakao_token'], show='*')
    kakao_entry.pack(side='left', fill='x', expand=True)

    vars_dict['tts_enabled'] = tk.BooleanVar(value=config.get('tts_enabled', True))
    tts_check = ttk.Checkbutton(notification_frame, text="TTS 음성 안내 사용", variable=vars_dict['tts_enabled'])
    tts_check.pack(anchor='w', pady=5)

    vars_dict['kakao_enabled'] = tk.BooleanVar(value=config.get('kakao_enabled', True))
    kakao_enabled_check = ttk.Checkbutton(notification_frame, text="카카오톡 알림 사용", variable=vars_dict['kakao_enabled'])
    kakao_enabled_check.pack(anchor='w', pady=5)

    # 리스크 관리 탭
    risk_frame = ttk.Frame(notebook)
    notebook.add(risk_frame, text="리스크 관리")
    
    # 급락 임계값
    ttk.Label(risk_frame, text="급락 감지 임계값 (%):", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(10, 5))
    vars_dict['panic_threshold'] = tk.DoubleVar(value=config.get('panic_threshold', -5.0))
    panic_entry = ttk.Entry(risk_frame, textvariable=vars_dict['panic_threshold'])
    panic_entry.pack(fill='x', pady=(0, 10))
    
    # 손절 임계값
    ttk.Label(risk_frame, text="손절 임계값 (%):", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=5)
    vars_dict['stop_loss_threshold'] = tk.DoubleVar(value=config.get('stop_loss_threshold', -10.0))
    stop_loss_entry = ttk.Entry(risk_frame, textvariable=vars_dict['stop_loss_threshold'])
    stop_loss_entry.pack(fill='x', pady=(0, 10))
    
    # 트레일링 스탑
    vars_dict['trailing_stop'] = tk.BooleanVar(value=config.get('trailing_stop', True))
    trailing_check = ttk.Checkbutton(risk_frame, text="트레일링 스탑 사용", variable=vars_dict['trailing_stop'])
    trailing_check.pack(anchor='w', pady=5)
    
    ttk.Label(risk_frame, text="트레일링 스탑 비율 (%):", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=5)
    vars_dict['trailing_stop_percent'] = tk.DoubleVar(value=config.get('trailing_stop_percent', 3.0))
    trailing_percent_entry = ttk.Entry(risk_frame, textvariable=vars_dict['trailing_stop_percent'])
    trailing_percent_entry.pack(fill='x', pady=(0, 10))
    
    # 긴급 청산
    vars_dict['emergency_exit_enabled'] = tk.BooleanVar(value=config.get('emergency_exit_enabled', True))
    emergency_check = ttk.Checkbutton(risk_frame, text="긴급 청산 활성화", variable=vars_dict['emergency_exit_enabled'])
    emergency_check.pack(anchor='w', pady=5)
    
    # 거래 설정 탭
    trade_frame = ttk.Frame(notebook)
    notebook.add(trade_frame, text="거래 설정")
    
    # 지정가 주문 사용
    vars_dict['use_limit_orders'] = tk.BooleanVar(value=config.get('use_limit_orders', True))
    limit_check = ttk.Checkbutton(trade_frame, text="지정가 주문 사용", variable=vars_dict['use_limit_orders'])
    limit_check.pack(anchor='w', pady=(10, 5))
    
    ttk.Label(trade_frame, text="지정가 주문 버퍼 (%):", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=5)
    vars_dict['limit_order_buffer'] = tk.DoubleVar(value=config.get('limit_order_buffer', 0.2))
    buffer_entry = ttk.Entry(trade_frame, textvariable=vars_dict['limit_order_buffer'])
    buffer_entry.pack(fill='x', pady=(0, 10))
    
    ttk.Label(trade_frame, text="최대 포지션 크기 (총 자산 대비 %):", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=5)
    vars_dict['max_position_size'] = tk.DoubleVar(value=config.get('max_position_size', 0.3))
    max_position_entry = ttk.Entry(trade_frame, textvariable=vars_dict['max_position_size'])
    max_position_entry.pack(fill='x', pady=(0, 10))
    
    # 버튼 프레임
    button_frame = ttk.Frame(settings_window)
    button_frame.pack(fill='x', padx=10, pady=10)
    
    def save_settings():
        try:
            new_config = {}
            for key, var in vars_dict.items():
                if isinstance(var, tk.BooleanVar):
                    new_config[key] = var.get()
                elif isinstance(var, tk.DoubleVar):
                    new_config[key] = var.get()
                else:
                    new_config[key] = var.get()
            
            if save_config(new_config):
                messagebox.showinfo("성공", "설정이 저장되었습니다.")
                callback(new_config)  # 메인 창에 새 설정 적용
                settings_window.destroy()
            else:
                messagebox.showerror("오류", "설정 저장에 실패했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 중 오류: {e}")
    
    def test_connection():
        try:
            # 업비트 API 테스트
            if vars_dict['upbit_access'].get() and vars_dict['upbit_secret'].get():
                test_upbit = pyupbit.Upbit(vars_dict['upbit_access'].get(), vars_dict['upbit_secret'].get())
                balance = test_upbit.get_balance("KRW") # KRW 잔고만 조회
                if balance is not None: # 0원일 수도 있으므로 None 체크
                    messagebox.showinfo("성공", f"업비트 API 연결 성공!\nKRW 잔액: {balance:,.0f}원")
                else:
                    messagebox.showwarning("경고", "업비트 API 연결에 실패했습니다. 키가 유효한지 확인해주세요.")
            else:
                messagebox.showwarning("경고", "업비트 API 키를 입력해주세요.")
        except Exception as e:
            messagebox.showerror("오류", f"API 테스트 실패: {e}")
    
    ttk.Button(button_frame, text="연결 테스트", command=test_connection).pack(side='left', padx=(0, 10))
    ttk.Button(button_frame, text="저장", command=save_settings).pack(side='right', padx=(10, 0))
    ttk.Button(button_frame, text="취소", command=settings_window.destroy).pack(side='right')

# 백테스트 창
def open_backtest_window(root, main_settings):
    """백테스트 창 열기"""
    bt_window = tk.Toplevel(root)
    bt_window.title("백테스트")
    bt_window.geometry("600x750") # 창 크기 조정
    bt_window.transient(root)
    bt_window.grab_set()
    
    # 설정 프레임
    settings_frame = ttk.LabelFrame(bt_window, text="백테스트 설정")
    settings_frame.pack(fill='x', padx=10, pady=10)
    
    # 설정 변수
    vars_dict = {
        'ticker': tk.StringVar(value="KRW-BTC"),
        'amount': tk.StringVar(value="1000000"),
        'grid_count': tk.StringVar(value="10"),
        'period': tk.StringVar(value="1일"),
        'stop_loss': tk.DoubleVar(value=config.get('stop_loss_threshold', -10.0)),
        'trailing_stop': tk.BooleanVar(value=config.get('trailing_stop', True)),
        'trailing_percent': tk.DoubleVar(value=config.get('trailing_stop_percent', 3.0)),
        'auto_grid': tk.BooleanVar(value=True)
    }

    def load_main_settings():
        """메인 설정 불러오기"""
        vars_dict['amount'].set(main_settings['amount'].get())
        vars_dict['grid_count'].set(main_settings['grid_count'].get())
        vars_dict['period'].set(main_settings['period'].get())
        vars_dict['auto_grid'].set(main_settings['auto_grid'].get())
        # 리스크 설정은 config에서 직접 가져옴
        vars_dict['stop_loss'].set(config.get('stop_loss_threshold', -10.0))
        vars_dict['trailing_stop'].set(config.get('trailing_stop', True))
        vars_dict['trailing_percent'].set(config.get('trailing_stop_percent', 3.0))
        
        messagebox.showinfo("정보", "메인 화면의 현재 설정을 불러왔습니다.")

    ttk.Button(settings_frame, text="현재 설정 불러오기", command=load_main_settings).grid(row=0, column=0, columnspan=2, pady=5)

    ttk.Label(settings_frame, text="코인:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
    ticker_combo = ttk.Combobox(settings_frame, textvariable=vars_dict['ticker'], values=["KRW-BTC", "KRW-ETH", "KRW-XRP"])
    ticker_combo.grid(row=1, column=1, sticky='ew', padx=5)
    
    ttk.Label(settings_frame, text="투자금액:").grid(row=2, column=0, sticky='w', padx=5, pady=5)
    amount_entry = ttk.Entry(settings_frame, textvariable=vars_dict['amount'])
    amount_entry.grid(row=2, column=1, sticky='ew', padx=5)
    
    ttk.Label(settings_frame, text="가격 범위 기준:").grid(row=3, column=0, sticky='w', padx=5, pady=5)
    period_combo = ttk.Combobox(settings_frame, textvariable=vars_dict['period'], values=["1시간", "4시간", "1일", "7일"], state="readonly")
    period_combo.grid(row=3, column=1, sticky='ew', padx=5)

    ttk.Label(settings_frame, text="그리드 개수:").grid(row=4, column=0, sticky='w', padx=5, pady=5)
    grid_entry = ttk.Entry(settings_frame, textvariable=vars_dict['grid_count'])
    grid_entry.grid(row=4, column=1, sticky='ew', padx=5)

    auto_grid_check = ttk.Checkbutton(settings_frame, text="최적 그리드 자동 계산", variable=vars_dict['auto_grid'])
    auto_grid_check.grid(row=5, column=0, columnspan=2, pady=5)

    ttk.Label(settings_frame, text="손절 임계값 (%):").grid(row=6, column=0, sticky='w', padx=5, pady=5)
    stop_loss_entry = ttk.Entry(settings_frame, textvariable=vars_dict['stop_loss'])
    stop_loss_entry.grid(row=6, column=1, sticky='ew', padx=5)

    trailing_check = ttk.Checkbutton(settings_frame, text="트레일링 스탑 사용", variable=vars_dict['trailing_stop'])
    trailing_check.grid(row=7, column=0, columnspan=2, pady=5)

    ttk.Label(settings_frame, text="트레일링 스탑 비율 (%):").grid(row=8, column=0, sticky='w', padx=5, pady=5)
    trailing_percent_entry = ttk.Entry(settings_frame, textvariable=vars_dict['trailing_percent'])
    trailing_percent_entry.grid(row=8, column=1, sticky='ew', padx=5)

    settings_frame.grid_columnconfigure(1, weight=1)
    
    # 결과 프레임
    result_frame = ttk.LabelFrame(bt_window, text="백테스트 결과")
    result_frame.pack(expand=True, fill='both', padx=10, pady=10)
    
    result_text = tk.Text(result_frame, wrap='word', height=15)
    result_scrollbar = ttk.Scrollbar(result_frame, orient='vertical', command=result_text.yview)
    result_text.configure(yscrollcommand=result_scrollbar.set)
    result_scrollbar.pack(side='right', fill='y')
    result_text.pack(side='left', expand=True, fill='both')
    
    def run_bt():
        try:
            params = {key: var.get() for key, var in vars_dict.items()}
            
            result_text.delete(1.0, tk.END)
            result_text.insert(tk.END, "백테스트 실행 중...\n\n")
            bt_window.update()
            
            # 백테스트 실행
            result = run_backtest(
                ticker=params['ticker'],
                total_investment=float(params['amount']),
                grid_count=int(params['grid_count']),
                period=params['period'],
                stop_loss_threshold=params['stop_loss'],
                use_trailing_stop=params['trailing_stop'],
                trailing_stop_percent=params['trailing_percent'],
                auto_grid=params['auto_grid']
            )
            
            if result:
                result_text.delete(1.0, tk.END)
                result_text.insert(tk.END, f"=== 백테스트 결과 ({params['ticker']}) ===\n\n")
                result_text.insert(tk.END, f"기간: {result['start_date']} ~ {result['end_date']}\n")
                result_text.insert(tk.END, f"초기 자본: {result['initial_balance']:,.0f}원\n")
                result_text.insert(tk.END, f"최종 자산: {result['final_value']:,.0f}원\n")
                result_text.insert(tk.END, f"총 수익률: {result['total_return']:.2f}%\n")
                result_text.insert(tk.END, f"총 거래 횟수: {result['num_trades']}회 (매수: {result['buy_count']}, 매도: {result['sell_count']})\n")
                result_text.insert(tk.END, f"승률: {result['win_rate']:.2f}%\n")
                result_text.insert(tk.END, f"최대 자산: {result['highest_value']:,.0f}원\n")
                result_text.insert(tk.END, f"최저 자산: {result['lowest_value']:,.0f}원\n")

            else:
                result_text.delete(1.0, tk.END)
                result_text.insert(tk.END, "백테스트 실행 실패\n")
                
        except Exception as e:
            result_text.delete(1.0, tk.END)
            result_text.insert(tk.END, f"오류 발생: {e}\n")
    
    ttk.Button(bt_window, text="백테스트 실행", command=run_bt).pack(pady=10)



# GUI 대시보드
def start_dashboard():
    """메인 대시보드 시작"""
    # 한글 폰트 설정
    import platform
    if platform.system() == 'Windows':
        plt.rcParams['font.family'] = 'Malgun Gothic'
    else:
        plt.rcParams['font.family'] = 'AppleGothic'
    plt.rcParams['axes.unicode_minus'] = False

    active_trades = {}
    gui_queue = Queue()
    chart_data = {}
    global config, upbit

    start_tts_worker()

    root = tk.Tk()
    root.title("그리드 투자 자동매매 대시보드 v2.0")
    root.geometry("1400x900")

    def on_closing():
        if messagebox.askokcancel("종료", "정말로 종료하시겠습니까?"):
            if active_trades:
                for ticker, stop_event in active_trades.items():
                    stop_event.set()
            stop_tts_worker()
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    def update_config(new_config):
        """설정 업데이트 콜백"""
        global config, upbit
        config = new_config
        initialize_upbit()

    style = ttk.Style()
    style.theme_use('clam')
    style.configure("TLabel", padding=3, font=('Helvetica', 9))
    style.configure("TButton", padding=5, font=('Helvetica', 10, 'bold'))
    style.configure("TCheckbutton", padding=3, font=('Helvetica', 9))
    style.configure("TEntry", padding=3, font=('Helvetica', 9))
    style.configure("TCombobox", padding=3, font=('Helvetica', 9))
    style.configure("TLabelframe", padding=8, font=('Helvetica', 11, 'bold'))
    style.configure("TLabelframe.Label", font=('Helvetica', 11, 'bold'))
    style.configure("Treeview.Heading", font=('Helvetica', 9, 'bold'))
    style.configure("Green.TLabel", foreground="green")
    style.configure("DarkGreen.TLabel", foreground="darkgreen", font=('Helvetica', 9, 'bold'))
    style.configure("Red.TLabel", foreground="red")
    style.configure("Orange.TLabel", foreground="orange")
    style.configure("Blue.TLabel", foreground="blue", font=('Helvetica', 9, 'bold'))
    style.configure("Purple.TLabel", foreground="purple", font=('Helvetica', 9, 'bold'))
    style.configure("Gray.TLabel", foreground="gray")
    style.configure("Black.TLabel", foreground="black")

    main_frame = ttk.Frame(root, padding="8")
    main_frame.pack(expand=True, fill='both')

    # 상단 프레임 (설정 + 현황)
    top_frame = ttk.Frame(main_frame)
    top_frame.pack(fill='x', pady=(0, 8))
    top_frame.grid_columnconfigure(0, weight=1)
    top_frame.grid_columnconfigure(1, weight=1)

    # 코인 선택 및 현황
    ticker_frame = ttk.LabelFrame(top_frame, text="코인 선택 및 현황")
    ticker_frame.grid(row=0, column=0, sticky='nswe', padx=(0, 4))
    ticker_vars = {}
    status_labels, current_price_labels, running_time_labels = {}, {}, {}
    detail_labels = {}
    
    tickers = ("KRW-BTC", "KRW-ETH", "KRW-XRP")
    for i, ticker in enumerate(tickers):
        var = tk.IntVar()
        cb = ttk.Checkbutton(ticker_frame, text=ticker, variable=var)
        cb.grid(row=i*5, column=0, sticky='w', padx=3, pady=1)
        ticker_vars[ticker] = var
        
        # 상태 및 운영시간
        status_labels[ticker] = ttk.Label(ticker_frame, text="상태: 대기중", style="Gray.TLabel")
        status_labels[ticker].grid(row=i*5, column=1, sticky='w', padx=3)
        
        running_time_labels[ticker] = ttk.Label(ticker_frame, text="운영시간: 00:00:00", style="Gray.TLabel")
        running_time_labels[ticker].grid(row=i*5, column=2, sticky='w', padx=3)
        
        # 현재가
        current_price_labels[ticker] = ttk.Label(ticker_frame, text="현재가: -", style="Gray.TLabel")
        current_price_labels[ticker].grid(row=i*5, column=3, sticky='w', padx=3)
        
        # 상세 정보
        detail_labels[ticker] = {
            'profit': ttk.Label(ticker_frame, text="평가수익: 0원", style="Gray.TLabel"),
            'profit_rate': ttk.Label(ticker_frame, text="(0.00%)", style="Gray.TLabel"),
            'realized_profit': ttk.Label(ticker_frame, text="실현수익: 0원", style="Gray.TLabel"),
            'realized_profit_rate': ttk.Label(ticker_frame, text="(0.00%)", style="Gray.TLabel"),
            'cash': ttk.Label(ticker_frame, text="현금: 0원", style="Gray.TLabel"),
            'coin_qty': ttk.Label(ticker_frame, text="보유: 0개", style="Gray.TLabel"),
            'coin_value': ttk.Label(ticker_frame, text="코인가치: 0원", style="Gray.TLabel"),
            'total_value': ttk.Label(ticker_frame, text="총자산: 0원", style="Gray.TLabel")
        }
        
        detail_labels[ticker]['profit'].grid(row=i*5+1, column=0, sticky='w', padx=3)
        detail_labels[ticker]['profit_rate'].grid(row=i*5+1, column=1, sticky='w', padx=3)
        detail_labels[ticker]['realized_profit'].grid(row=i*5+1, column=2, sticky='w', padx=3)
        detail_labels[ticker]['realized_profit_rate'].grid(row=i*5+1, column=3, sticky='w', padx=3)
        detail_labels[ticker]['cash'].grid(row=i*5+2, column=0, sticky='w', padx=3)
        detail_labels[ticker]['coin_qty'].grid(row=i*5+2, column=1, sticky='w', padx=3)
        detail_labels[ticker]['coin_value'].grid(row=i*5+2, column=2, sticky='w', padx=3)
        detail_labels[ticker]['total_value'].grid(row=i*5+2, column=3, sticky='w', padx=3)
        
        # 구분선
        if i < len(tickers) - 1:
            sep = ttk.Separator(ticker_frame, orient='horizontal')
            sep.grid(row=i*5+4, column=0, columnspan=4, sticky='ew', pady=3)

    # 그리드 투자 설정
    settings_frame = ttk.LabelFrame(top_frame, text="그리드 투자 설정")
    settings_frame.grid(row=0, column=1, sticky='nswe', padx=(4, 0))
    settings_frame.grid_columnconfigure(1, weight=1)
    
    settings_icon_frame = ttk.Frame(settings_frame)
    settings_icon_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))

    ttk.Label(settings_frame, text="총 투자 금액 (KRW):").grid(row=1, column=0, sticky='w', padx=3, pady=1)
    amount_entry = ttk.Entry(settings_frame)
    amount_entry.insert(0, config.get("total_investment", "100000"))
    amount_entry.grid(row=1, column=1, sticky='ew', padx=3)

    ttk.Label(settings_frame, text="그리드 개수:").grid(row=2, column=0, sticky='w', padx=3, pady=1)
    grid_entry = ttk.Entry(settings_frame)
    grid_entry.insert(0, config.get("grid_count", "10"))
    grid_entry.grid(row=2, column=1, sticky='ew', padx=3)

    auto_grid_var = tk.BooleanVar(value=config.get('auto_grid_count', True))
    auto_grid_check = ttk.Checkbutton(settings_frame, text="그리드 개수 자동 변경", variable=auto_grid_var)
    auto_grid_check.grid(row=3, column=0, columnspan=2, sticky='w', padx=3, pady=1)

    ttk.Label(settings_frame, text="가격 범위 기준:").grid(row=4, column=0, sticky='w', padx=3, pady=1)
    period_combo = ttk.Combobox(settings_frame, values=["1시간", "4시간", "1일", "7일"], state="readonly")
    period_combo.set(config.get("period", "4시간"))
    period_combo.grid(row=4, column=1, sticky='ew', padx=3)

    def update_grid_count_on_period_change(event):
        if auto_grid_var.get():
            try:
                selected_tickers = [ticker for ticker, var in ticker_vars.items() if var.get()]
                if not selected_tickers:
                    representative_ticker = "KRW-BTC"
                else:
                    representative_ticker = selected_tickers[0]

                period = period_combo.get()
                high_price, low_price = calculate_price_range(representative_ticker, period)
                
                if high_price and low_price:
                    new_grid_count = calculate_optimal_grid_count(high_price, low_price)
                    grid_entry.delete(0, tk.END)
                    grid_entry.insert(0, str(new_grid_count))
                    log_trade(representative_ticker, '정보', f'{period} 기준, 자동 계산된 그리드: {new_grid_count}개', add_log_to_gui)
                else:
                    log_trade(representative_ticker, '오류', f'{period} 기준 가격 범위 계산 실패', add_log_to_gui)
            except Exception as e:
                print(f"그리드 자동 계산 오류: {e}")

    period_combo.bind("<<ComboboxSelected>>", update_grid_count_on_period_change)

    ttk.Label(settings_frame, text="목표 수익률 (%):").grid(row=5, column=0, sticky='w', padx=3, pady=1)
    target_entry = ttk.Entry(settings_frame)
    target_entry.insert(0, config.get("target_profit_percent", "10"))
    target_entry.grid(row=5, column=1, sticky='ew', padx=3)

    demo_var = tk.IntVar(value=config.get("demo_mode", 1))
    demo_check = ttk.Checkbutton(settings_frame, text="데모 모드", variable=demo_var)
    demo_check.grid(row=6, column=0, columnspan=2, sticky='w', padx=3, pady=3)

    main_settings = {
        'amount': amount_entry,
        'grid_count': grid_entry,
        'period': period_combo,
        'auto_grid': auto_grid_var
    }

    ttk.Button(settings_icon_frame, text="⚙️ 시스템 설정", 
               command=lambda: open_settings_window(root, config, update_config)).pack(side='left')
    ttk.Button(settings_icon_frame, text="📊 백테스트", 
               command=lambda: open_backtest_window(root, main_settings)).pack(side='left', padx=(10, 0))
    def export_data_to_excel():
        success, filename = export_to_excel()
        if success:
            messagebox.showinfo("성공", f"데이터가 {filename}로 내보내기되었습니다.")
        else:
            messagebox.showerror("오류", f"내보내기 실패: {filename}")

    ttk.Button(settings_icon_frame, text="📄 엑셀 내보내기", 
               command=export_data_to_excel).pack(side='left', padx=(10, 0))

    # 중간 프레임 (차트)
    mid_frame = ttk.LabelFrame(main_frame, text="실시간 차트 및 그리드")
    mid_frame.pack(fill='x', pady=4)
    
    # 차트 컨테이너
    chart_container = ttk.Frame(mid_frame)
    chart_container.pack(fill='x', padx=5, pady=5)
    
    # matplotlib 차트 설정
    fig = Figure(figsize=(14, 4), dpi=80)
    charts = {}
    
    def create_chart_subplot(ticker, position):
        ax = fig.add_subplot(1, 3, position)
        ax.set_title(f'{ticker} 가격 차트', fontsize=10)
        ax.set_xlabel('시간', fontsize=8)
        ax.set_ylabel('가격 (KRW)', fontsize=8)
        ax.tick_params(axis='both', which='major', labelsize=7)
        charts[ticker] = ax
        return ax
    
    for i, ticker in enumerate(tickers, 1):
        create_chart_subplot(ticker, i)
    
    fig.tight_layout()
    canvas = FigureCanvasTkAgg(fig, chart_container)
    canvas.draw()
    canvas.get_tk_widget().pack(fill='x')

    def on_hover(event):
        if event.inaxes is None:
            return

        for ticker, ax in charts.items():
            if event.inaxes == ax and hasattr(ax, 'hover_data'):
                hover_data = ax.hover_data
                annot = hover_data['annot']
                found = False
                
                for scatter in hover_data['scatters']:
                    cont, ind = scatter.contains(event)
                    if cont:
                        idx = ind['ind'][0]
                        pos = scatter.get_offsets()[idx]
                        annot.xy = pos
                        
                        point_info = ""
                        for p in hover_data['points']:
                            if abs(p['price'] - pos[1]) < 1e-6:
                                point_info = p['info']
                                break

                        annot.set_text(point_info)
                        annot.get_bbox_patch().set_alpha(0.8)
                        annot.set_visible(True)
                        canvas.draw_idle()
                        found = True
                        break
                
                if not found and annot.get_visible():
                    annot.set_visible(False)
                    canvas.draw_idle()

    canvas.mpl_connect("motion_notify_event", on_hover)

    def update_chart(ticker, period):
        """차트 업데이트"""
        if ticker not in charts:
            return
        
        df = get_chart_data(ticker, period)
        if df is None or df.empty:
            return
        
        ax = charts[ticker]
        ax.clear()
        ax.set_title(f'{ticker} 가격 차트 ({period})', fontsize=10)
        ax.set_xlabel('시간', fontsize=8)
        ax.set_ylabel('가격 (KRW)', fontsize=8)
        ax.tick_params(axis='both', which='major', labelsize=7)
        
        # 가격 라인 그리기
        ax.plot(df.index, df['close'], 'b-', linewidth=1, label='가격')
        
        # 그리드 라인 그리기
        if ticker in chart_data:
            high_price, low_price, grid_levels = chart_data[ticker]
            for level in grid_levels:
                ax.axhline(y=level, color='red', linestyle='--', alpha=0.5, linewidth=0.5)
            
            ax.axhline(y=high_price, color='green', linestyle='-', alpha=0.8, linewidth=2, label='상한선')
            ax.axhline(y=low_price, color='red', linestyle='-', alpha=0.8, linewidth=2, label='하한선')

        # 거래 기록 표시
        trade_points = {'buy': [], 'sell': []}
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            if ticker in logs:
                for log in logs[ticker]:
                    action = log.get('action', '')
                    time_str = log.get('time')
                    price_str = log.get('price', '')

                    if not time_str or not price_str:
                        continue

                    try:
                        trade_time = pd.to_datetime(time_str)
                        
                        import re
                        price_match = re.search(r'([\d,]+)원', str(price_str))
                        if price_match:
                            trade_price = float(price_match.group(1).replace(',', ''))
                        else:
                            continue

                        if '매수' in action:
                            trade_points['buy'].append({'time': trade_time, 'price': trade_price, 'info': f"{log['action']}: {log['price']}"})
                        elif '매도' in action:
                            trade_points['sell'].append({'time': trade_time, 'price': trade_price, 'info': f"{log['action']}: {log['price']}"})
                    except (ValueError, TypeError) as e:
                        print(f"로그 파싱 오류: {log} -> {e}")
                        continue
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            pass

        buy_scatter = None
        sell_scatter = None

        if trade_points['buy']:
            buy_times = [p['time'] for p in trade_points['buy']]
            buy_prices = [p['price'] for p in trade_points['buy']]
            buy_scatter = ax.scatter(buy_times, buy_prices, color='blue', marker='^', s=50, zorder=5, label='매수')

        if trade_points['sell']:
            sell_times = [p['time'] for p in trade_points['sell']]
            sell_prices = [p['price'] for p in trade_points['sell']]
            sell_scatter = ax.scatter(sell_times, sell_prices, color='red', marker='v', s=50, zorder=5, label='매도')
        
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        
        # Annotation 객체 생성
        annot = ax.annotate("", xy=(0,0), xytext=(10,10), textcoords="offset points",
                            bbox=dict(boxstyle="round", fc="w", ec="k", lw=1),
                            arrowprops=dict(arrowstyle="->"))
        annot.set_visible(False)

        # 호버 이벤트 데이터 저장
        scatters = []
        all_trade_points = []
        if buy_scatter:
            scatters.append(buy_scatter)
            all_trade_points.extend(trade_points['buy'])
        if sell_scatter:
            scatters.append(sell_scatter)
            all_trade_points.extend(trade_points['sell'])

        charts[ticker].hover_data = {
            "scatters": scatters,
            "points": all_trade_points,
            "annot": annot
        }

        canvas.draw_idle()

    # 하단 프레임 (로그)
    log_frame = ttk.LabelFrame(main_frame, text="실시간 거래 기록")
    log_frame.pack(expand=True, fill='both')
    
    log_tree = ttk.Treeview(log_frame, columns=("시간", "코인", "종류", "가격"), show='headings')
    log_tree.heading("시간", text="시간")
    log_tree.heading("코인", text="코인")
    log_tree.heading("종류", text="종류")
    log_tree.heading("가격", text="내용")
    log_tree.column("시간", width=120, anchor='center')
    log_tree.column("코인", width=80, anchor='center')
    log_tree.column("종류", width=100, anchor='center')
    log_tree.column("가격", width=400, anchor='w')
    
    scrollbar = ttk.Scrollbar(log_frame, orient='vertical', command=log_tree.yview)
    log_tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    log_tree.pack(side='left', expand=True, fill='both')

    def add_log_to_gui(log):
        log_tree.insert('', 'end', values=(log['time'], log['ticker'], log['action'], log['price']))
        log_tree.yview_moveto(1)

    def load_initial_logs():
        """초기 로그 로드"""
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            for ticker, ticker_logs in logs.items():
                for log in ticker_logs:
                    full_log = log.copy()
                    full_log['ticker'] = ticker
                    add_log_to_gui(full_log)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def get_profit_color_style(profit):
        """수익에 따른 색상 스타일 반환"""
        if profit > 0:
            return "Green.TLabel"
        elif profit < 0:
            return "Red.TLabel"
        else:
            return "Black.TLabel"

    def process_gui_queue():
        """GUI 큐 처리"""
        while not gui_queue.empty():
            try:
                key, ticker, args = gui_queue.get_nowait()
                if key == 'log':
                    add_log_to_gui(args[0])
                elif key == 'status':
                    status_labels[ticker].config(text=args[0], style=args[1])
                elif key == 'price':
                    current_price_labels[ticker].config(text=args[0], style=args[1])
                elif key == 'running_time':
                    running_time_labels[ticker].config(text=args[0], style="Blue.TLabel")
                elif key == 'details':
                    cash, coin_qty, held_value, total_value, profit, profit_percent, total_realized_profit, realized_profit_percent = args
                    
                    profit_style = get_profit_color_style(profit)
                    realized_profit_style = get_profit_color_style(total_realized_profit)

                    detail_labels[ticker]['profit'].config(text=f"평가수익: {profit:,.0f}원", style=profit_style)
                    detail_labels[ticker]['profit_rate'].config(text=f"({profit_percent:+.2f}%)", style=profit_style)
                    detail_labels[ticker]['realized_profit'].config(text=f"실현수익: {total_realized_profit:,.0f}원", style=realized_profit_style)
                    detail_labels[ticker]['realized_profit_rate'].config(text=f"({realized_profit_percent:+.2f}%)", style=realized_profit_style)
                    detail_labels[ticker]['cash'].config(text=f"현금: {cash:,.0f}원", style="Black.TLabel")
                    detail_labels[ticker]['coin_qty'].config(text=f"보유: {coin_qty:.6f}개", style="Black.TLabel")
                    detail_labels[ticker]['coin_value'].config(text=f"코인가치: {held_value:,.0f}원", style="Black.TLabel")
                    detail_labels[ticker]['total_value'].config(text=f"총자산: {total_value:,.0f}원", style="Blue.TLabel")
                elif key == 'chart_data':
                    high_price, low_price, grid_levels = args
                    chart_data[ticker] = (high_price, low_price, grid_levels)
                    current_period = period_combo.get()
                    update_chart(ticker, current_period)
                elif key == 'refresh_chart':
                    current_period = period_combo.get()
                    update_chart(ticker, current_period)
            except Exception as e:
                print(f"GUI 업데이트 오류: {e}")
        root.after(100, process_gui_queue)

    def toggle_trading():
        """거래 시작/중지"""
        if active_trades:
            for ticker, stop_event in active_trades.items():
                stop_event.set()
                status_labels[ticker].config(text="상태: 중지 대기중...", style="Orange.TLabel")
                running_time_labels[ticker].config(text="운영시간: 00:00:00", style="Gray.TLabel")
                # 상세 정보 초기화
                for label_key, label in detail_labels[ticker].items():
                    if label_key == 'profit':
                        label.config(text="평가수익: 0원", style="Gray.TLabel")
                    elif label_key == 'profit_rate':
                        label.config(text="(0.00%)", style="Gray.TLabel")
                    elif label_key == 'realized_profit':
                        label.config(text="실현수익: 0원", style="Gray.TLabel")
                    elif label_key == 'realized_profit_rate':
                        label.config(text="(0.00%)", style="Gray.TLabel")
                    elif label_key == 'cash':
                        label.config(text="현금: 0원", style="Gray.TLabel")
                    elif label_key == 'coin_qty':
                        label.config(text="보유: 0개", style="Gray.TLabel")
                    elif label_key == 'coin_value':
                        label.config(text="코인가치: 0원", style="Gray.TLabel")
                    elif label_key == 'total_value':
                        label.config(text="총자산: 0원", style="Gray.TLabel")
            active_trades.clear()
            control_button.config(text="거래 시작")
            return

        try:
            # 현재 UI 설정값을 config에 저장
            config["total_investment"] = amount_entry.get()
            config["grid_count"] = grid_entry.get()
            config["period"] = period_combo.get()
            config["target_profit_percent"] = target_entry.get()
            config["demo_mode"] = demo_var.get()
            config["auto_grid_count"] = auto_grid_var.get()
            save_config(config)

            selected_tickers = [ticker for ticker, var in ticker_vars.items() if var.get()]
            if not selected_tickers:
                messagebox.showwarning("경고", "거래할 코인을 하나 이상 선택해주세요.")
                return

            period = period_combo.get()

            # 자동 그리드 개수 계산 로직
            if auto_grid_var.get():
                # 대표 티커(첫 번째 선택)를 기준으로 가격 범위 계산
                representative_ticker = selected_tickers[0]
                high_price, low_price = calculate_price_range(representative_ticker, period)
                if high_price and low_price:
                    new_grid_count = calculate_optimal_grid_count(high_price, low_price)
                    grid_entry.delete(0, tk.END)
                    grid_entry.insert(0, str(new_grid_count))
                    log_trade(representative_ticker, '정보', f'자동 계산된 그리드: {new_grid_count}개', add_log_to_gui)
                else:
                    messagebox.showwarning("경고", f"{representative_ticker}의 가격 범위 계산에 실패하여 자동 그리드 계산을 중단합니다.")
                    return

            total_investment = int(amount_entry.get())
            grid_count = int(grid_entry.get())
            demo_mode = bool(demo_var.get())
            target_profit = float(target_entry.get())
            
            if grid_count < 3 or grid_count > 50:
                messagebox.showwarning("경고", "그리드 개수는 3~50 사이로 설정해주세요.")
                return
                
            if total_investment < 10000:
                messagebox.showwarning("경고", "총 투자 금액은 최소 10,000원 이상이어야 합니다.")
                return
            
            # 실제 거래 모드일 때 API 키 확인
            if not demo_mode and (not config.get("upbit_access") or not config.get("upbit_secret")):
                messagebox.showwarning("경고", "실제 거래를 위해서는 업비트 API 키를 설정해주세요.")
                return
            
            control_button.config(text="거래 중지")

            for ticker in selected_tickers:
                if ticker in active_trades: 
                    continue
                
                stop_event = threading.Event()
                active_trades[ticker] = stop_event
                
                status_labels[ticker].config(text="상태: 시작중", style="Orange.TLabel")
                current_price_labels[ticker].config(text="현재가: 조회중...", style="Black.TLabel")
                running_time_labels[ticker].config(text="운영시간: 00:00:00", style="Blue.TLabel")
                
                # 상세 정보 초기화
                detail_labels[ticker]['profit'].config(text="평가수익: 0원", style="Black.TLabel")
                detail_labels[ticker]['profit_rate'].config(text="(0.00%)", style="Black.TLabel")
                detail_labels[ticker]['realized_profit'].config(text="실현수익: 0원", style="Black.TLabel")
                detail_labels[ticker]['realized_profit_rate'].config(text="(0.00%)", style="Black.TLabel")
                detail_labels[ticker]['cash'].config(text=f"현금: {total_investment:,.0f}원", style="Black.TLabel")
                detail_labels[ticker]['coin_qty'].config(text="보유: 0개", style="Black.TLabel")
                detail_labels[ticker]['coin_value'].config(text="코인가치: 0원", style="Black.TLabel")
                detail_labels[ticker]['total_value'].config(text=f"총자산: {total_investment:,.0f}원", style="Blue.TLabel")

                thread = threading.Thread(
                    target=grid_trading,
                    args=(ticker, grid_count, total_investment, demo_mode, target_profit, period, stop_event, gui_queue),
                    daemon=True
                )
                thread.start()
                
        except ValueError:
            messagebox.showerror("오류", "숫자 입력값들을 확인해주세요.")
            control_button.config(text="거래 시작")

    control_button = ttk.Button(settings_frame, text="거래 시작", command=toggle_trading)
    control_button.grid(row=7, column=0, columnspan=2, sticky='ew', pady=8, padx=3)

    # 설명 라벨 추가
    info_text = "그리드 투자: 설정 기간의 최고가/최저가 범위를 그리드로 분할하여 자동 매수/매도 (v2.0 - 급락대응/손절/트레일링스탑)"
    info_label = ttk.Label(settings_frame, text=info_text, font=('Helvetica', 8), foreground='gray')
    info_label.grid(row=8, column=0, columnspan=2, sticky='ew', padx=3, pady=2)
    
    # 차트 업데이트 버튼
    def refresh_charts():
        current_period = period_combo.get()
        for ticker in tickers:
            update_chart(ticker, current_period)
    
    chart_refresh_btn = ttk.Button(mid_frame, text="차트 새로고침", command=refresh_charts)
    chart_refresh_btn.pack(pady=5)

    # 초기화
    load_initial_logs()
    process_gui_queue()
    initialize_upbit()  # 업비트 API 초기화
    
    # 초기 차트 로드
    root.after(2000, refresh_charts)
    
    root.mainloop()

if __name__ == "__main__":
    initialize_files()
    start_dashboard()