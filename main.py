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

# === 설정 파일 관리 ===
config_file = "config.json"
profit_file = "profits.json"
log_file = "trade_logs.json"

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
    "emergency_exit_enabled": True  # 긴급 청산 활성화
}

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

# === 카카오톡 알림 API ===
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

# === JSON 파일 관리 ===
def initialize_files():
    """필요한 JSON 파일들 초기화"""
    for file in [profit_file, log_file, config_file]:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
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
        except (FileNotFoundError, json.JSONDecodeError):
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
        except (FileNotFoundError, json.JSONDecodeError):
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

# === 급락 감지 및 대응 전략 ===
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

# === 개선된 주문 실행 함수 ===
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
    except Exception as e:
        print(f"매도 주문 실행 오류: {e}")
        return None

# === 상태 평가 개선 ===
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

# === 가격 범위 계산 함수 ===
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

# === 차트 데이터 가져오기 ===
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

# === 백테스트 모듈 ===
def run_backtest(ticker, start_date, end_date, grid_count, total_investment, period="1일"):
    """백테스트 실행"""
    try:
        # 과거 데이터 가져오기
        df = pyupbit.get_ohlcv(ticker, interval="day", count=100)  # 최근 100일
        if df is None or df.empty:
            return None
        
        # 백테스트 결과 시뮬레이션 (간단한 버전)
        initial_balance = total_investment
        balance = initial_balance
        positions = []
        trades = []
        
        high_price = df['high'].max()
        low_price = df['low'].min()
        price_gap = (high_price - low_price) / grid_count
        amount_per_grid = total_investment / grid_count
        
        # 각 일자별로 그리드 트레이딩 시뮬레이션
        for index, row in df.iterrows():
            current_price = row['close']
            
            # 매수 조건 체크 (단순화)
            grid_level = int((current_price - low_price) / price_gap)
            if grid_level >= 0 and grid_level < grid_count:
                if balance >= amount_per_grid:
                    quantity = amount_per_grid / current_price
                    balance -= amount_per_grid
                    positions.append({'price': current_price, 'quantity': quantity})
                    trades.append({'date': index, 'type': 'buy', 'price': current_price, 'quantity': quantity})
            
            # 매도 조건 체크 (단순화)
            for pos in positions[:]:
                if current_price > pos['price'] * 1.02:  # 2% 이상 상승시 매도
                    sell_amount = pos['quantity'] * current_price
                    balance += sell_amount
                    positions.remove(pos)
                    trades.append({'date': index, 'type': 'sell', 'price': current_price, 'quantity': pos['quantity']})
        
        # 최종 수익 계산
        final_value = balance + sum(pos['quantity'] * df.iloc[-1]['close'] for pos in positions)
        total_return = (final_value - initial_balance) / initial_balance * 100
        
        return {
            'total_return': total_return,
            'final_value': final_value,
            'num_trades': len(trades),
            'trades': trades[-10:]  # 최근 10개 거래만
        }
        
    except Exception as e:
        print(f"백테스트 오류: {e}")
        return None

# === 개선된 그리드 트레이딩 로직 ===
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
        demo_positions = []
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
        real_positions = []
        total_invested = 0
    
    prev_price = current_price
    update_gui('chart_data', high_price, low_price, grid_levels)
    
    total_realized_profit = 0

    while not stop_event.is_set():
        price = pyupbit.get_current_price(ticker)
        if price is None:
            time.sleep(10)
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
                        
                        log_msg = f"그리드{i+1} 매수: {price:,.0f}원 ({quantity:.6f}개) → 목표: {target_sell_price:,.0f}원"
                        if panic_mode:
                            log_msg += " [급락대응]"
                        log_trade(ticker, "데모 매수", log_msg, lambda log: update_gui('log', log))
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
                    
                    buy_cost = position['quantity'] * position['actual_buy_price']
                    net_profit = net_sell_amount - buy_cost
                    total_realized_profit += net_profit

                    log_msg = f"{sell_reason} 매도: {price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원"
                    log_trade(ticker, "데모 매도", log_msg, lambda log: update_gui('log', log))
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
                                    total_invested += actual_buy_amount
                                    
                                    log_msg = f"그리드{i+1} 매수: {price:,.0f}원 ({executed_volume:.6f}개) → 목표: {target_sell_price:,.0f}원"
                                    if panic_mode:
                                        log_msg += " [급락대응]"
                                    log_trade(ticker, "실제 매수", log_msg, lambda log: update_gui('log', log))
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
                        log_msg = f"{sell_reason} 매도: {price:,.0f}원 ({position['quantity']:.6f}개)"
                        log_trade(ticker, "실제 매도", log_msg, lambda log: update_gui('log', log))
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
            
            # 상세 알림 메시지 생성
            summary_msg = f"""
{ticker} 목표 달성 완료!
목표 수익률: {target_profit_percent}%
실제 수익률: {profit_percent:.2f}%
운영 시간: {running_time_str}
총 거래 횟수: {len([log for log in previous_prices if 'trade' in str(log)])}
실현 수익: {total_realized_profit:,.0f}원
"""
            send_kakao_message(summary_msg.strip())
            break
        
        prev_price = price
        time.sleep(3)

    if stop_event.is_set():
        log_trade(ticker, '중지', '사용자 요청', lambda log: update_gui('log', log))
        update_gui('status', "상태: 중지됨", "Orange.TLabel", False, False)

# === 설정 창 ===
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
    
    ttk.Label(api_frame, text="업비트 Access Key:", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(10, 5))
    vars_dict['upbit_access'] = tk.StringVar(value=config.get('upbit_access', ''))
    access_entry = ttk.Entry(api_frame, textvariable=vars_dict['upbit_access'], show='*', width=60)
    access_entry.pack(fill='x', pady=(0, 10))
    
    ttk.Label(api_frame, text="업비트 Secret Key:", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=5)
    vars_dict['upbit_secret'] = tk.StringVar(value=config.get('upbit_secret', ''))
    secret_entry = ttk.Entry(api_frame, textvariable=vars_dict['upbit_secret'], show='*', width=60)
    secret_entry.pack(fill='x', pady=(0, 10))
    
    ttk.Label(api_frame, text="카카오톡 액세스 토큰:", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=5)
    vars_dict['kakao_token'] = tk.StringVar(value=config.get('kakao_token', ''))
    kakao_entry = ttk.Entry(api_frame, textvariable=vars_dict['kakao_token'], show='*', width=60)
    kakao_entry.pack(fill='x', pady=(0, 10))
    
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
                balance = test_upbit.get_balances()
                if balance:
                    messagebox.showinfo("성공", "업비트 API 연결 성공!")
                else:
                    messagebox.showwarning("경고", "업비트 API 연결 실패")
            else:
                messagebox.showwarning("경고", "업비트 API 키를 입력해주세요.")
        except Exception as e:
            messagebox.showerror("오류", f"API 테스트 실패: {e}")
    
    ttk.Button(button_frame, text="연결 테스트", command=test_connection).pack(side='left', padx=(0, 10))
    ttk.Button(button_frame, text="저장", command=save_settings).pack(side='right', padx=(10, 0))
    ttk.Button(button_frame, text="취소", command=settings_window.destroy).pack(side='right')

# === 백테스트 창 ===
def open_backtest_window(root):
    """백테스트 창 열기"""
    bt_window = tk.Toplevel(root)
    bt_window.title("백테스트")
    bt_window.geometry("600x650")
    bt_window.transient(root)
    bt_window.grab_set()
    
    # 설정 프레임
    settings_frame = ttk.LabelFrame(bt_window, text="백테스트 설정")
    settings_frame.pack(fill='x', padx=10, pady=10)
    
    ttk.Label(settings_frame, text="코인:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
    ticker_var = tk.StringVar(value="KRW-BTC")
    ticker_combo = ttk.Combobox(settings_frame, textvariable=ticker_var, values=["KRW-BTC", "KRW-ETH", "KRW-XRP"])
    ticker_combo.grid(row=0, column=1, sticky='ew', padx=5)
    
    ttk.Label(settings_frame, text="투자금액:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
    amount_var = tk.StringVar(value="1000000")
    amount_entry = ttk.Entry(settings_frame, textvariable=amount_var)
    amount_entry.grid(row=1, column=1, sticky='ew', padx=5)
    
    ttk.Label(settings_frame, text="그리드 개수:").grid(row=2, column=0, sticky='w', padx=5, pady=5)
    grid_var = tk.StringVar(value="10")
    grid_entry = ttk.Entry(settings_frame, textvariable=grid_var)
    grid_entry.grid(row=2, column=1, sticky='ew', padx=5)

    auto_grid_var = tk.BooleanVar()
    auto_grid_check = ttk.Checkbutton(settings_frame, text="최적 그리드 자동 계산", variable=auto_grid_var)
    auto_grid_check.grid(row=3, column=0, columnspan=2, pady=5)
    
    settings_frame.grid_columnconfigure(1, weight=1)
    
    # 결과 프레임
    result_frame = ttk.LabelFrame(bt_window, text="백테스트 결과")
    result_frame.pack(expand=True, fill='both', padx=10, pady=10)
    
    result_text = tk.Text(result_frame, wrap='word')
    result_scrollbar = ttk.Scrollbar(result_frame, orient='vertical', command=result_text.yview)
    result_text.configure(yscrollcommand=result_scrollbar.set)
    result_scrollbar.pack(side='right', fill='y')
    result_text.pack(side='left', expand=True, fill='both')
    
    def run_bt():
        try:
            ticker = ticker_var.get()
            amount = int(amount_var.get())
            grid_count = int(grid_var.get())
            
            result_text.delete(1.0, tk.END)
            result_text.insert(tk.END, "백테스트 실행 중...\n\n")
            bt_window.update()
            
            # 백테스트 실행
            result = run_backtest(ticker, None, None, grid_count, amount)
            
            if result:
                result_text.delete(1.0, tk.END)
                result_text.insert(tk.END, f"=== 백테스트 결과 ({ticker}) ===\n\n")
                result_text.insert(tk.END, f"총 수익률: {result['total_return']:.2f}%\n")
                result_text.insert(tk.END, f"최종 자산: {result['final_value']:,.0f}원\n")
                result_text.insert(tk.END, f"총 거래 횟수: {result['num_trades']}회\n\n")
                result_text.insert(tk.END, "최근 거래 내역:\n")
                for trade in result['trades']:
                    result_text.insert(tk.END, f"{trade['date']}: {trade['type']} {trade['price']:,.0f}원\n")
            else:
                result_text.delete(1.0, tk.END)
                result_text.insert(tk.END, "백테스트 실행 실패\n")
                
        except Exception as e:
            result_text.delete(1.0, tk.END)
            result_text.insert(tk.END, f"오류 발생: {e}\n")
    
    ttk.Button(bt_window, text="백테스트 실행", command=run_bt).pack(pady=10)


# === GUI 대시보드 ===
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

    root = tk.Tk()
    root.title("그리드 투자 자동매매 대시보드 v2.0")
    root.geometry("1400x900")

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
    
    # 설정 아이콘 추가
    settings_icon_frame = ttk.Frame(settings_frame)
    settings_icon_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))
    
    ttk.Button(settings_icon_frame, text="⚙️ 시스템 설정", 
               command=lambda: open_settings_window(root, config, update_config)).pack(side='left')
    ttk.Button(settings_icon_frame, text="📊 백테스트", 
               command=lambda: open_backtest_window(root)).pack(side='left', padx=(10, 0))
    def export_data_to_excel():
        """데이터 엑셀 내보내기"""
        success, filename = export_to_excel()
        if success:
            messagebox.showinfo("성공", f"데이터가 {filename}로 내보내기되었습니다.")
        else:
            messagebox.showerror("오류", f"내보내기 실패: {filename}")

    ttk.Button(settings_icon_frame, text="📄 엑셀 내보내기", 
               command=export_data_to_excel).pack(side='left', padx=(10, 0))
    
    ttk.Label(settings_frame, text="총 투자 금액 (KRW):").grid(row=1, column=0, sticky='w', padx=3, pady=1)
    amount_entry = ttk.Entry(settings_frame)
    amount_entry.insert(0, "100000")
    amount_entry.grid(row=1, column=1, sticky='ew', padx=3)

    ttk.Label(settings_frame, text="그리드 개수:").grid(row=2, column=0, sticky='w', padx=3, pady=1)
    grid_entry = ttk.Entry(settings_frame)
    grid_entry.insert(0, "10")
    grid_entry.grid(row=2, column=1, sticky='ew', padx=3)

    ttk.Label(settings_frame, text="가격 범위 기준:").grid(row=3, column=0, sticky='w', padx=3, pady=1)
    period_combo = ttk.Combobox(settings_frame, values=["1시간", "4시간", "1일", "7일"], state="readonly")
    period_combo.set("1일")
    period_combo.grid(row=3, column=1, sticky='ew', padx=3)

    ttk.Label(settings_frame, text="목표 수익률 (%):").grid(row=4, column=0, sticky='w', padx=3, pady=1)
    target_entry = ttk.Entry(settings_frame)
    target_entry.insert(0, "10")
    target_entry.grid(row=4, column=1, sticky='ew', padx=3)

    demo_var = tk.IntVar(value=1)
    demo_check = ttk.Checkbutton(settings_frame, text="데모 모드", variable=demo_var)
    demo_check.grid(row=5, column=0, columnspan=2, sticky='w', padx=3, pady=3)

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
        except (FileNotFoundError, json.JSONDecodeError):
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
            selected_tickers = [ticker for ticker, var in ticker_vars.items() if var.get()]
            if not selected_tickers:
                messagebox.showwarning("경고", "거래할 코인을 하나 이상 선택해주세요.")
                return

            total_investment = int(amount_entry.get())
            grid_count = int(grid_entry.get())
            period = period_combo.get()
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
    control_button.grid(row=6, column=0, columnspan=2, sticky='ew', pady=8, padx=3)

    # 설명 라벨 추가
    info_text = "그리드 투자: 설정 기간의 최고가/최저가 범위를 그리드로 분할하여 자동 매수/매도 (v2.0 - 급락대응/손절/트레일링스탑)"
    info_label = ttk.Label(settings_frame, text=info_text, font=('Helvetica', 8), foreground='gray')
    info_label.grid(row=7, column=0, columnspan=2, sticky='ew', padx=3, pady=2)
    
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