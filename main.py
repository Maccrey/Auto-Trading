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

def get_korean_coin_name(ticker):
    """코인 티커를 한국어 이름으로 변환"""
    coin_names = {
        'KRW-BTC': '비트코인',
        'KRW-ETH': '이더리움',
        'KRW-XRP': '리플'
    }
    return coin_names.get(ticker, ticker.replace('KRW-', ''))

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
    "limit_order_buffer": 0.1,  # 지정가 주문 버퍼 (0.1%로 조정)
    "max_position_size": 0.3,  # 최대 포지션 크기 (총 자산 대비)
    "emergency_exit_enabled": True,  # 긴급 청산 활성화
    "auto_grid_count": True, # 그리드 개수 자동 계산
    "max_grid_count": 30, # 투자 성향에 따른 최대 그리드 수
    "investment_profile": "보통", # 현재 선택된 투자 성향
    "tts_enabled": True, # TTS 음성 안내 사용
    "kakao_enabled": True, # 카카오톡 알림 사용
    "total_investment": "100000",
    "grid_count": "10",
    "period": "4시간",
    "target_profit_percent": "",
    "demo_mode": 1,
    "use_custom_range": False,  # 사용자 지정 가격 범위 사용
    "custom_high_price": "",    # 상한선
    "custom_low_price": "",     # 하한선
    "advanced_grid_trading": True,  # 고급 그리드 거래 활성화
    "grid_confirmation_buffer": 0.1,  # 그리드 확인 버퍼 (%)
    "fee_rate": 0.0005,  # 거래 수수료율 (0.05%)
    "auto_trading_mode": False,  # 완전 자동 거래 모드
    "risk_mode": "보수적",  # 리스크 모드 (보수적, 안정적, 공격적, 극공격적)
    "auto_update_interval": 60,  # 자동 업데이트 간격 (분)
    "performance_tracking": True,  # 실적 추적 활성화
    "auto_optimization": True  # 자동 최적화 활성화
}

# 완전 자동 거래 시스템
class AutoTradingSystem:
    def __init__(self):
        self.risk_profiles = {
            "보수적": {
                "max_grid_count": 15,
                "max_investment_ratio": 0.3,  # 총 자산의 30%만 투자
                "panic_threshold": -3.0,  # 3% 하락시 급락 감지
                "stop_loss_threshold": -5.0,  # 5% 손절
                "trailing_stop_percent": 2.0,  # 2% 트레일링 스탑
                "grid_confirmation_buffer": 0.2,  # 확인 버퍼 크게
                "rebalance_threshold": 0.05  # 5% 변동시 리밸런싱
            },
            "안정적": {
                "max_grid_count": 20,
                "max_investment_ratio": 0.5,
                "panic_threshold": -5.0,
                "stop_loss_threshold": -8.0,
                "trailing_stop_percent": 3.0,
                "grid_confirmation_buffer": 0.15,
                "rebalance_threshold": 0.08
            },
            "공격적": {
                "max_grid_count": 30,
                "max_investment_ratio": 0.7,
                "panic_threshold": -7.0,
                "stop_loss_threshold": -12.0,
                "trailing_stop_percent": 4.0,
                "grid_confirmation_buffer": 0.1,
                "rebalance_threshold": 0.12
            },
            "극공격적": {
                "max_grid_count": 50,
                "max_investment_ratio": 0.9,
                "panic_threshold": -10.0,
                "stop_loss_threshold": -15.0,
                "trailing_stop_percent": 5.0,
                "grid_confirmation_buffer": 0.05,
                "rebalance_threshold": 0.15
            }
        }
        
        self.performance_data = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_profit": 0.0,
            "max_drawdown": 0.0,
            "last_optimization": None,
            "hourly_performance": []
        }
    
    def get_risk_settings(self, risk_mode):
        """리스크 모드에 따른 설정 반환"""
        return self.risk_profiles.get(risk_mode, self.risk_profiles["안정적"])
    
    def analyze_performance(self, trades_data):
        """거래 실적 분석"""
        if not trades_data:
            return {"status": "insufficient_data"}
        
        # 최근 24시간 거래 분석
        recent_trades = [t for t in trades_data if self._is_recent_trade(t, 24)]
        
        if len(recent_trades) < 5:
            return {"status": "insufficient_recent_data"}
        
        win_rate = len([t for t in recent_trades if t.get('profit', 0) > 0]) / len(recent_trades)
        avg_profit = sum(t.get('profit', 0) for t in recent_trades) / len(recent_trades)
        total_profit = sum(t.get('profit', 0) for t in recent_trades)
        
        return {
            "status": "success",
            "win_rate": win_rate,
            "avg_profit": avg_profit,
            "total_profit": total_profit,
            "trade_count": len(recent_trades),
            "recommendation": self._get_recommendation(win_rate, avg_profit)
        }
    
    def _is_recent_trade(self, trade, hours):
        """최근 거래인지 확인"""
        try:
            from datetime import datetime, timedelta
            trade_time = datetime.strptime(trade.get('time', ''), '%Y-%m-%d %H:%M:%S')
            return datetime.now() - trade_time < timedelta(hours=hours)
        except:
            return False
    
    def _get_recommendation(self, win_rate, avg_profit):
        """실적 기반 추천"""
        if win_rate > 0.7 and avg_profit > 1000:
            return "increase_aggression"  # 공격성 증가
        elif win_rate < 0.4 or avg_profit < -500:
            return "decrease_aggression"  # 공격성 감소
        else:
            return "maintain"  # 현재 유지
    
    def optimize_parameters(self, current_config, performance_analysis):
        """실적 기반 파라미터 자동 최적화"""
        if performance_analysis["status"] != "success":
            return current_config
        
        optimized_config = current_config.copy()
        recommendation = performance_analysis["recommendation"]
        current_risk = current_config.get("risk_mode", "안정적")
        
        # 리스크 모드 자동 조정
        risk_modes = ["보수적", "안정적", "공격적", "극공격적"]
        current_index = risk_modes.index(current_risk) if current_risk in risk_modes else 1
        
        if recommendation == "increase_aggression" and current_index < 3:
            new_risk_mode = risk_modes[current_index + 1]
            optimized_config["risk_mode"] = new_risk_mode
            print(f"실적 우수로 리스크 모드 상향 조정: {current_risk} → {new_risk_mode}")
        elif recommendation == "decrease_aggression" and current_index > 0:
            new_risk_mode = risk_modes[current_index - 1]
            optimized_config["risk_mode"] = new_risk_mode
            print(f"실적 부진으로 리스크 모드 하향 조정: {current_risk} → {new_risk_mode}")
        
        # 리스크 프로필에 따른 설정 적용
        risk_settings = self.get_risk_settings(optimized_config["risk_mode"])
        optimized_config.update({
            "max_grid_count": risk_settings["max_grid_count"],
            "panic_threshold": risk_settings["panic_threshold"],
            "stop_loss_threshold": risk_settings["stop_loss_threshold"],
            "trailing_stop_percent": risk_settings["trailing_stop_percent"],
            "grid_confirmation_buffer": risk_settings["grid_confirmation_buffer"]
        })
        
        # 승률에 따른 세부 조정
        win_rate = performance_analysis["win_rate"]
        if win_rate > 0.8:  # 매우 높은 승률
            optimized_config["grid_confirmation_buffer"] *= 0.8  # 버퍼 감소로 더 적극적
        elif win_rate < 0.3:  # 매우 낮은 승률
            optimized_config["grid_confirmation_buffer"] *= 1.5  # 버퍼 증가로 더 신중
        
        optimized_config["last_optimization"] = datetime.now().isoformat()
        return optimized_config

# 글로벌 자동 거래 시스템 인스턴스
auto_trading_system = AutoTradingSystem()

# 자동 최적화 스케줄러
class AutoOptimizationScheduler:
    def __init__(self):
        self.last_optimization = None
        self.optimization_thread = None
        self.stop_optimization = False
        
    def start_auto_optimization(self, update_callback):
        """자동 최적화 스레드 시작"""
        if self.optimization_thread and self.optimization_thread.is_alive():
            return
            
        self.stop_optimization = False
        self.optimization_thread = threading.Thread(
            target=self._optimization_worker, 
            args=(update_callback,), 
            daemon=True
        )
        self.optimization_thread.start()
        
    def stop_auto_optimization(self):
        """자동 최적화 스레드 중지"""
        self.stop_optimization = True
        if self.optimization_thread:
            self.optimization_thread.join(timeout=5)
    
    def _optimization_worker(self, update_callback):
        """자동 최적화 작업자"""
        while not self.stop_optimization:
            try:
                # 설정에서 간격 확인
                interval_minutes = config.get('auto_update_interval', 60)
                
                # 간격만큼 대기 (10초씩 체크하여 중단 신호 확인)
                for _ in range(int(interval_minutes * 6)):  # 60분 = 360 * 10초
                    if self.stop_optimization:
                        return
                    time.sleep(10)
                
                # 자동 거래 모드가 활성화된 경우에만 최적화 실행
                if config.get('auto_trading_mode', False) and config.get('auto_optimization', True):
                    self._perform_optimization(update_callback)
                    
            except Exception as e:
                print(f"자동 최적화 오류: {e}")
                time.sleep(300)  # 오류 발생시 5분 대기
    
    def _perform_optimization(self, update_callback):
        """실제 최적화 수행"""
        try:
            print("자동 최적화 시작...")
            
            # 거래 로그 데이터 로드
            trades_data = self._load_recent_trades()
            
            # 실적 분석
            performance = auto_trading_system.analyze_performance(trades_data)
            
            if performance["status"] == "success":
                # 파라미터 최적화
                optimized_config = auto_trading_system.optimize_parameters(config, performance)
                
                # 설정 업데이트
                if optimized_config != config:
                    config.update(optimized_config)
                    save_config(config)
                    
                    # UI 업데이트 콜백 호출
                    if update_callback:
                        update_callback(config)
                    
                    # 최적화 결과 로그
                    self._log_optimization_result(performance, optimized_config)
                    
                    # 카카오 알림
                    if config.get('kakao_enabled', True):
                        self._send_optimization_notification(performance, optimized_config)
                else:
                    print("최적화 결과 변경사항 없음")
            else:
                print(f"최적화 건너뛰기: {performance['status']}")
                
            self.last_optimization = datetime.now()
            
        except Exception as e:
            print(f"최적화 수행 중 오류: {e}")
    
    def _load_recent_trades(self):
        """최근 거래 데이터 로드"""
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            all_trades = []
            for ticker_trades in data.values():
                for trade in ticker_trades:
                    # 매수/매도 쌍을 찾아 수익 계산
                    if 'profit' not in trade:
                        trade['profit'] = self._calculate_trade_profit(trade)
                    all_trades.append(trade)
            
            return all_trades
        except:
            return []
    
    def _calculate_trade_profit(self, trade):
        """거래별 수익 계산"""
        # 간단한 수익 추정 (실제로는 매수/매도 쌍을 매칭해야 함)
        action = trade.get('action', '')
        if '매수' in action:
            return 0  # 매수는 수익 0
        elif '매도' in action:
            # 매도는 평균 수익률 가정 (실제 구현시 더 정확하게)
            return 1000  # 임시값
        return 0
    
    def _log_optimization_result(self, performance, new_config):
        """최적화 결과 로그"""
        risk_mode = new_config.get('risk_mode', '알 수 없음')
        win_rate = performance.get('win_rate', 0) * 100
        total_profit = performance.get('total_profit', 0)
        
        log_msg = f"자동최적화 완료 - 리스크모드: {risk_mode}, 승률: {win_rate:.1f}%, 수익: {total_profit:,.0f}원"
        print(log_msg)
    
    def _send_optimization_notification(self, performance, new_config):
        """최적화 알림 발송"""
        try:
            risk_mode = new_config.get('risk_mode', '알 수 없음')
            win_rate = performance.get('win_rate', 0) * 100
            
            message = f"🤖 자동최적화 완료\n리스크 모드: {risk_mode}\n승률: {win_rate:.1f}%"
            send_kakao_message(message)
        except:
            pass

# 글로벌 자동 최적화 스케줄러 인스턴스
auto_scheduler = AutoOptimizationScheduler()

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

upbit = None

# 매수/매도 개수 추적
trade_counts = {
    "KRW-BTC": {"buy": 0, "sell": 0, "profitable_sell": 0},
    "KRW-ETH": {"buy": 0, "sell": 0, "profitable_sell": 0}, 
    "KRW-XRP": {"buy": 0, "sell": 0, "profitable_sell": 0}
}

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

def load_config():
    """설정 파일 로드"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            # 기본 설정과 로드된 설정을 병합 (새로운 설정 추가 시 기존 파일에 반영)
            merged_config = default_config.copy()
            merged_config.update(config_data)
            return merged_config
    except (FileNotFoundError, json.JSONDecodeError):
        # 파일이 없거나 JSON 형식이 잘못된 경우 기본 설정 사용 및 저장
        save_config(default_config)
        return default_config

config = load_config()



# 카카오톡 알림 API
def send_kakao_message(message):
    """카카오톡 메시지 전송"""
    if not config.get("kakao_enabled", True):
        return

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
            if response.status_code == 401:
                print("\n[알림] 카카오톡 액세스 토큰이 만료되었거나 유효하지 않습니다.")
                print("프로그램의 [시스템 설정 > 알림 설정]에서 토큰을 갱신해주세요.\n")
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

def load_profits_data():
    try:
        with open(profit_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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
            for ticker, profit in profits.items():
                profit_sheet.write(row, 0, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                profit_sheet.write(row, 1, ticker)
                profit_sheet.write(row, 2, profit)
                row += 1
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        workbook.close()
        return True, filename
    except Exception as e:
        print(f"엑셀 내보내기 오류: {e}")
        return False, str(e)


    
def log_trade(ticker, action, price):
    """거래 로그 기록 (파일 저장 전용)"""
    entry = {
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': action,
        'price': f"{price:,.0f}원" if isinstance(price, (int, float)) else str(price)
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
        
        return entry # GUI 업데이트를 위해 로그 항목 반환
            
    except Exception as e:
        print(f"로그 파일 처리 중 오류 발생: {e}")
        return None

# 급락 감지 및 대응 전략
def detect_panic_selling(current_price, previous_prices, threshold_percent=-5.0):
    """급락 상황 감지"""
    if len(previous_prices) < 10:  # 최소 10개 데이터 필요
        return False
    
    # 최근 10분간 평균 가격과 비교
    recent_avg = sum(previous_prices[-10:]) / 10
    price_change_percent = ((current_price - recent_avg) / recent_avg) * 100
    
    return price_change_percent <= threshold_percent

# 향상된 가격 범위 계산 함수
def calculate_enhanced_price_range(ticker, period, use_custom_range=False, custom_high=None, custom_low=None):
    """향상된 가격 범위 계산 (사용자 지정 범위 및 자동 그리드 개수 고려)"""
    if use_custom_range and custom_high and custom_low:
        try:
            high_price = float(custom_high)
            low_price = float(custom_low)
            if high_price > low_price:
                return high_price, low_price
        except (ValueError, TypeError):
            pass
    
    # 기존 범위 계산 로직 사용
    return calculate_price_range(ticker, period)

def calculate_dynamic_grid(base_low, base_high, current_price, panic_mode=False):
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
    global upbit, trade_counts
    if upbit is None:
        return None
    
    try:
        result = None
        if use_limit and config.get("use_limit_orders", True):
            # 지정가 주문 (현재가보다 약간 높게)
            buffer = config.get("limit_order_buffer", 0.2) / 100
            limit_price = current_price * (1 + buffer)
            # 업비트 가격 단위에 맞춰 조정
            limit_price = round(limit_price)
            
            quantity = amount / limit_price
            result = upbit.buy_limit_order(ticker, limit_price, quantity)
        else:
            # 시장가 주문
            result = upbit.buy_market_order(ticker, amount)
        
        # 주문 성공시 매수 개수 증가
        if result and result.get('uuid'):
            trade_counts[ticker]["buy"] += 1
            
        return result
    except requests.exceptions.RequestException as e:
        print(f"매수 주문 네트워크 오류: {e}")
        return None
    except Exception as e:
        print(f"매수 주문 실행 오류: {e}")
        return None

def execute_sell_order(ticker, quantity, current_price, use_limit=True):
    """개선된 매도 주문 실행"""
    global upbit, trade_counts
    if upbit is None:
        return None
    
    try:
        result = None
        if use_limit and config.get("use_limit_orders", True):
            # 지정가 주문 (현재가보다 약간 낮게)
            buffer = config.get("limit_order_buffer", 0.2) / 100
            limit_price = current_price * (1 - buffer)
            limit_price = round(limit_price)
            
            result = upbit.sell_limit_order(ticker, limit_price, quantity)
        else:
            # 시장가 주문
            result = upbit.sell_market_order(ticker, quantity)
            
        # 주문 성공시 매도 개수 증가
        if result and result.get('uuid'):
            trade_counts[ticker]["sell"] += 1
            
        return result
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

def calculate_auto_grid_count_enhanced(high_price, low_price, fee_rate=0.0005, investment_amount=1000000):
    """
    가격 범위와 거래 수수료를 고려하여 최적의 그리드 개수를 자동 계산
    """
    if low_price <= 0 or high_price <= low_price:
        return 15  # 기본값

    # 전체 가격 범위 백분율
    price_range_percent = ((high_price - low_price) / low_price) * 100

    # 그리드당 최소 수익률 (수수료 2배 + 0.1% 추가 이익)
    min_profit_per_grid = (fee_rate * 2 + 0.001) * 100
    
    # 이론적 최대 그리드 개수
    max_possible_grids = price_range_percent / min_profit_per_grid
    
    # 투자금액을 고려한 그리드 개수 조정
    min_investment_per_grid = 50000  # 격당 최소 투자금 5만원
    max_grids_by_investment = investment_amount / min_investment_per_grid
    
    # 최종 그리드 개수 결정
    optimal_grids = min(max_possible_grids, max_grids_by_investment)
    optimal_grids = max(10, min(50, int(optimal_grids)))  # 10~50 개 제한
    
    return optimal_grids

def calculate_optimal_grid_count(high_price, low_price, target_profit_percent=None, fee_rate=0.0005):
    """
    기존 호환성을 위한 래퍼 함수
    """
    return calculate_auto_grid_count_enhanced(high_price, low_price, fee_rate)

# 고급 그리드 거래 상태 추적
class AdvancedGridState:
    def __init__(self):
        self.pending_buy_orders = {}   # 대기 중인 매수 주문
        self.pending_sell_orders = {}  # 대기 중인 매도 주문
        self.price_history = []        # 가격 히스토리 (트렌드 분석용)
        self.last_grid_action = None   # 마지막 그리드 액션
        
    def add_price_history(self, price):
        self.price_history.append(price)
        if len(self.price_history) > 20:  # 최근 20개만 유지
            self.price_history.pop(0)
    
    def get_trend_direction(self):
        """가격 트렌드 방향 판단 (1: 상승, -1: 하락, 0: 횡보)"""
        if len(self.price_history) < 5:
            return 0
        
        recent_prices = self.price_history[-5:]
        if all(recent_prices[i] > recent_prices[i-1] for i in range(1, len(recent_prices))):
            return 1  # 상승 트렌드
        elif all(recent_prices[i] < recent_prices[i-1] for i in range(1, len(recent_prices))):
            return -1  # 하락 트렌드
        return 0  # 횡보

def check_advanced_grid_conditions(current_price, grid_price, action_type, grid_state, buffer_percent=0.1):
    """
    고급 그리드 거래 조건 확인
    - 하락시 그리드에서 바로 매수하지 않고, 트렌드 확인 후 상승시 매수
    - 상승시 그리드에서 바로 매도하지 않고, 트렌드 확인 후 하락시 매도
    """
    trend = grid_state.get_trend_direction()
    buffer = grid_price * (buffer_percent / 100)
    
    if action_type == "buy":
        # 매수 조건: 가격이 그리드 하단 근처이고 상승 트렌드일 때
        at_grid_level = current_price <= (grid_price + buffer)
        if at_grid_level:
            if trend >= 0:  # 상승 또는 횡보 트렌드
                return True, "buy_confirmed"
            else:
                return False, "buy_pending"  # 하락 트렌드 시 대기
        return False, "no_action"
        
    elif action_type == "sell":
        # 매도 조건: 가격이 그리드 상단 근처이고 하락 트렌드일 때
        at_grid_level = current_price >= (grid_price - buffer)
        if at_grid_level:
            if trend <= 0:  # 하락 또는 횡보 트렌드
                return True, "sell_confirmed"
            else:
                return False, "sell_pending"  # 상승 트렌드 시 대기
        return False, "no_action"
    
    return False, "invalid_action"

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
def run_backtest(ticker, total_investment, grid_count, period, stop_loss_threshold, use_trailing_stop, trailing_stop_percent, auto_grid, target_profit_percent):
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
            if target_profit_percent and target_profit_percent.strip():
                try:
                    target_profit = float(target_profit_percent)
                except (ValueError, TypeError):
                    target_profit = 10.0 # 기본값
            else:
                target_profit = 10.0 # 기본값
            grid_count = calculate_optimal_grid_count(high_price, low_price, target_profit, fee_rate)

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



def has_trade_logs(ticker):
    """지정된 티커에 대한 거래 로그가 있는지 확인"""
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = json.load(f)
        if ticker not in logs:
            return False
        # Check for actual buy/sell logs, not just informational ones
        for log in logs[ticker]:
            action = log.get('action', '')
            if '매수' in action or '매도' in action:
                return True
        return False
    except (FileNotFoundError, json.JSONDecodeError):
        return False

# 개선된 그리드 트레이딩 로직
def grid_trading(ticker, grid_count, total_investment, demo_mode, target_profit_percent_str, period, stop_event, gui_queue, total_profit_label, total_profit_rate_label, all_ticker_total_values, all_ticker_start_balances, profits_data):
    """개선된 그리드 트레이딩 (급락장 대응 포함)"""
    start_time = datetime.now()

    # 목표 수익률 처리
    if target_profit_percent_str and target_profit_percent_str.strip():
        try:
            target_profit_percent = float(target_profit_percent_str)
        except (ValueError, TypeError):
            target_profit_percent = float('inf') # 잘못된 값이면 무한으로 처리
    else:
        target_profit_percent = float('inf') # 미지정이면 무한으로 처리

    def update_gui(key, *args):
        gui_queue.put((key, ticker, args))
        
    def log_and_update(action, price):
        log_entry = log_trade(ticker, action, price)
        if log_entry:
            full_log = log_entry.copy()
            full_log['ticker'] = ticker
            update_gui('log', full_log)
    
    def check_api_data_validity(current_price, orderbook=None):
        """API 데이터 유효성 검사 (그리드 거래용)"""
        try:
            # 기본 가격 유효성 검사
            if current_price is None or current_price <= 0:
                return False, "현재가 데이터 오류"
            
            # 오더북 데이터가 있는 경우 추가 검사
            if orderbook:
                if not orderbook.get('orderbook_units') or len(orderbook['orderbook_units']) == 0:
                    return False, "오더북 데이터 없음"
                
                # 매수/매도 호가 존재 여부 확인
                first_unit = orderbook['orderbook_units'][0]
                if not first_unit.get('bid_price') or not first_unit.get('ask_price'):
                    return False, "매수/매도 호가 데이터 오류"
                
                # 스프레드 이상치 검사 (현재가 대비 5% 이상 차이나면 오류로 간주)
                bid_price = first_unit['bid_price']
                ask_price = first_unit['ask_price']
                spread_ratio = (ask_price - bid_price) / current_price
                if spread_ratio > 0.05:  # 5% 이상 스프레드는 비정상
                    return False, f"비정상적인 스프레드: {spread_ratio:.2%}"
            
            return True, "정상"
            
        except Exception as e:
            return False, f"데이터 검증 오류: {str(e)}"

    # 향상된 가격 범위 계산 (사용자 지정 범위 고려)
    use_custom_range = config.get('use_custom_range', False)
    custom_high = config.get('custom_high_price', '')
    custom_low = config.get('custom_low_price', '')
    
    high_price, low_price = calculate_enhanced_price_range(
        ticker, period, use_custom_range, custom_high, custom_low
    )
    
    if high_price is None or low_price is None:
        log_and_update('오류', '가격 범위 계산 실패')
        update_gui('status', "상태: 시작 실패", "Red.TLabel", False, False)
        return

    current_price = pyupbit.get_current_price(ticker)
    if current_price is None:
        log_and_update('오류', '시작 가격 조회 실패')
        update_gui('status', "상태: 시작 실패", "Red.TLabel", False, False)
        update_gui('action_status', 'error')
        return
    
    # API 데이터 유효성 초기 검사
    orderbook = None
    try:
        orderbook = pyupbit.get_orderbook(ticker)
    except:
        pass
    
    is_valid, error_msg = check_api_data_validity(current_price, orderbook)
    if not is_valid:
        log_and_update('오류', f'API 데이터 오류: {error_msg}')
        update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
        update_gui('action_status', 'error')
        return

    # 자동 거래 모드에서 리스크 설정 적용
    if config.get('auto_trading_mode', False):
        risk_settings = auto_trading_system.get_risk_settings(config.get('risk_mode', '안정적'))
        
        # 투자금액 조정 (리스크에 따라)
        max_investment_ratio = risk_settings['max_investment_ratio']
        adjusted_investment = total_investment * max_investment_ratio
        
        log_and_update('자동모드', f"리스크 모드: {config.get('risk_mode')}, 투자비율: {max_investment_ratio*100:.0f}%")
        
        # 그리드 개수를 리스크 설정에 따라 제한
        max_grids = risk_settings['max_grid_count']
        if grid_count > max_grids:
            grid_count = max_grids
            log_and_update('리스크조정', f"그리드 개수 제한: {max_grids}개")
        
        # 수수료 및 버퍼 설정 업데이트
        config['grid_confirmation_buffer'] = risk_settings['grid_confirmation_buffer']
        config['panic_threshold'] = risk_settings['panic_threshold']
        config['stop_loss_threshold'] = risk_settings['stop_loss_threshold']
        config['trailing_stop_percent'] = risk_settings['trailing_stop_percent']
    
    # 자동 그리드 개수 계산 (설정에 따라)
    if config.get('auto_grid_count', True):
        grid_count = calculate_auto_grid_count_enhanced(
            high_price, low_price, 
            config.get('fee_rate', 0.0005), 
            total_investment
        )
        log_and_update('자동계산', f"최적 그리드 개수: {grid_count}개")

    log_and_update('시작', f"{period} 범위: {low_price:,.0f}~{high_price:,.0f}")
    
    # 그리드 간격 계산
    price_gap = (high_price - low_price) / grid_count
    amount_per_grid = total_investment / grid_count
    
    # 그리드 가격 레벨 생성
    grid_levels = []
    for i in range(grid_count + 1):
        price_level = low_price + (price_gap * i)
        grid_levels.append(price_level)
    
    # 고급 그리드 상태 초기화
    advanced_grid_state = AdvancedGridState()
    
    log_and_update('설정', f"그리드 간격: {price_gap:,.0f}원, 격당투자: {amount_per_grid:,.0f}원")

    fee_rate = config.get('fee_rate', 0.0005)
    previous_prices = []  # 급락 감지용 이전 가격들
    panic_mode = False

    # Calculate current total assets and cash balance on startup
    current_price_for_calc = pyupbit.get_current_price(ticker)
    if current_price_for_calc is None:
        log_and_update('오류', '현재 가격 조회 실패')
        update_gui('status', "상태: 시작 실패", "Red.TLabel", False, False)
        return

    demo_positions = load_trading_state(ticker, True) # Load positions first

    current_held_assets_value = sum(pos['quantity'] * current_price_for_calc for pos in demo_positions)
    invested_in_held_positions = sum(pos['quantity'] * pos['buy_price'] for pos in demo_positions)
    
    # Ensure total_investment is treated as the initial capital
    initial_capital = float(total_investment) 
    current_cash_balance = initial_capital - invested_in_held_positions
    current_total_assets = current_cash_balance + current_held_assets_value

    highest_value = current_total_assets  # 트레일링 스탑용 최고 자산 가치
    
    if demo_mode:
        start_balance = current_total_assets
        demo_balance = current_total_assets
        if demo_positions:
            log_and_update('정보', f'{len(demo_positions)}개의 포지션을 복원했습니다.')
        total_invested = 0
    else:
        if upbit is None:
            log_and_update('오류', '업비트 API 초기화 안됨')
            update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
            return
            
        start_balance = upbit.get_balance("KRW")
        if start_balance is None:
            log_and_update('오류', '잔액 조회 실패')
            update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
            return
        real_positions = load_trading_state(ticker, False)
        if real_positions:
            log_and_update('정보', f'{len(real_positions)}개의 포지션을 복원했습니다.')
        total_invested = 0
    
    prev_price = current_price
    update_gui('chart_data', high_price, low_price, grid_levels)
    
    total_realized_profit = 0
    last_update_day = datetime.now().day

    # 새로운 매수 로직을 위한 상태 변수
    buy_pending = False
    lowest_grid_to_buy = -1

    while not stop_event.is_set():
        # 9시 정각 그리드 자동 갱신
        now = datetime.now()
        if config.get('auto_grid_count', True) and now.hour == 9 and now.day != last_update_day:
            log_and_update('정보', '오전 9시, 그리드 설정을 자동 갱신합니다.')
            
            new_high, new_low = calculate_price_range(ticker, period)
            if new_high and new_low:
                high_price, low_price = new_high, new_low
                grid_count = calculate_optimal_grid_count(high_price, low_price, target_profit_percent, fee_rate)
                price_gap = (high_price - low_price) / grid_count
                grid_levels = [low_price + (price_gap * i) for i in range(grid_count + 1)]
                
                log_and_update('설정 갱신', f"새 그리드: {grid_count}개, 범위: {low_price:,.0f}~{high_price:,.0f}")
                update_gui('chart_data', high_price, low_price, grid_levels)
            
            last_update_day = now.day

        try:
            price = pyupbit.get_current_price(ticker)
            if price is None: # None을 반환하는 경우 잠시 후 재시도
                update_gui('action_status', 'error')
                time.sleep(1)
                continue
                
            # API 데이터 유효성 검사
            try:
                orderbook = pyupbit.get_orderbook(ticker)
            except:
                orderbook = None
            
            is_valid, error_msg = check_api_data_validity(price, orderbook)
            if not is_valid:
                log_and_update('API오류', f'{error_msg}')
                update_gui('action_status', 'error')
                update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
                time.sleep(5)  # API 오류 시 5초 대기 후 재시도
                continue
                
        except KeyError as e: # 가격 데이터 형식 오류 처리
            log_and_update('오류', f'가격 데이터 조회 오류 (KeyError): {e}')
            update_gui('action_status', 'error')
            time.sleep(5) # 데이터 형식 오류 시 잠시 대기
            continue
        except requests.exceptions.RequestException as e:
            log_and_update('오류', f'네트워크 오류 발생: {e}')
            update_gui('action_status', 'error')
            time.sleep(10) # 네트워크 불안정시 더 길게 대기
            continue
        
        # 운영 시간 계산
        running_time = datetime.now() - start_time
        hours, remainder = divmod(int(running_time.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        running_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        update_gui('price', f"현재가: {price:,.0f}원", "Black.TLabel")
        update_gui('running_time', f"운영시간: {running_time_str}")
        
        # 가격 히스토리 업데이트 (급락 감지용 + 고급 그리드용)
        previous_prices.append(price)
        if len(previous_prices) > 30:  # 최근 30개만 유지
            previous_prices.pop(0)
        
        # 고급 그리드 상태 업데이트
        advanced_grid_state.add_price_history(price)
        
        # 급락 상황 감지
        new_panic_mode = detect_panic_selling(price, previous_prices, config.get("panic_threshold", -5.0))
        if new_panic_mode and not panic_mode:
            log_and_update('급락감지', '급락 대응 모드 활성화')
            send_kakao_message(f"{get_korean_coin_name(ticker)} 급락 감지! 대응 모드 활성화")
            
            # 동적 그리드 재계산
            new_low, new_high = calculate_dynamic_grid(low_price, high_price, price, True)
            new_price_gap = (new_high - new_low) / grid_count
            grid_levels = [new_low + (new_price_gap * i) for i in range(grid_count + 1)]
            update_gui('chart_data', new_high, new_low, grid_levels)
            
        panic_mode = new_panic_mode

        if demo_mode:
            # 데모 모드 매수 로직 (하락 추세 추종)
            if buy_pending:
                # 매수 보류 중일 때
                # 더 낮은 그리드로 가격이 하락했는지 체크
                if lowest_grid_to_buy > 0 and price <= grid_levels[lowest_grid_to_buy - 1]:
                    lowest_grid_to_buy -= 1
                    log_msg = f"매수 보류 및 목표 하향: {grid_levels[lowest_grid_to_buy]:,.0f}원"
                    log_and_update("데모 매수보류", log_msg)
                    speak_async(f"{get_korean_coin_name(ticker)} 매수 목표 하향")
                    update_gui('action_status', 'looking_buy')
                
                else:
                    # 가격이 반등하여 최저 그리드를 '확실히' 돌파했는지 체크 (매수 실행)
                    confirmation_buffer = 0.001 # 0.1% 버퍼
                    buy_confirmation_price = grid_levels[lowest_grid_to_buy] * (1 + confirmation_buffer)
                    if price >= buy_confirmation_price:
                        buy_price = grid_levels[lowest_grid_to_buy]
                        already_bought = any(pos['buy_price'] == buy_price for pos in demo_positions)

                        if not already_bought and demo_balance >= amount_per_grid:
                            buy_multiplier = 1.5 if panic_mode else 1.0
                            actual_buy_amount = min(amount_per_grid * buy_multiplier, demo_balance)
                            
                            quantity = (actual_buy_amount * (1 - fee_rate)) / buy_price
                            demo_balance -= actual_buy_amount
                            total_invested += actual_buy_amount
                            
                            target_sell_price = grid_levels[lowest_grid_to_buy + 1]
                            
                            demo_positions.append({
                                'buy_price': buy_price,
                                'quantity': quantity,
                                'target_sell_price': target_sell_price,
                                'actual_buy_price': buy_price,
                                'highest_price': buy_price,
                                'sell_held': False,
                                'highest_grid_reached': -1
                            })
                            save_trading_state(ticker, demo_positions, True)

                            log_msg = f"하락추세 반등 매수: {buy_price:,.0f}원 ({quantity:.6f}개)"
                            log_and_update("데모 매수", log_msg)
                            speak_async(f"데모 모드, {get_korean_coin_name(ticker)} {buy_price:,.0f}원에 최종 매수되었습니다.")
                            send_kakao_message(f"[데모 최종매수] {get_korean_coin_name(ticker)} {buy_price:,.0f}원 ({quantity:.6f}개)")
                            
                            # 데모 모드에서도 매수 횟수 증가
                            trade_counts[ticker]["buy"] += 1
                            
                            update_gui('refresh_chart')
                            update_gui('action_status', 'trading')

                        # 매수 실행 후 상태 초기화
                        buy_pending = False
                        lowest_grid_to_buy = -1

            else:
                # 매수 보류 중이 아닐 때: 최초 매수 그리드 도달 체크
                for i, grid_price in enumerate(grid_levels[:-1]):
                    if prev_price > grid_price and price <= grid_price:
                        already_bought = any(pos['buy_price'] == grid_price for pos in demo_positions)
                        if not already_bought:
                            buy_pending = True
                            lowest_grid_to_buy = i
                            log_msg = f"매수 그리드 {grid_price:,.0f}원 도달. 매수 보류 시작."
                            log_and_update("데모 매수보류", log_msg)
                            speak_async(f"{get_korean_coin_name(ticker)} 매수 보류 시작")
                            update_gui('refresh_chart')
                            update_gui('action_status', 'looking_buy')
                            break # 첫번째 도달한 그리드만 처리
            
            # 데모 모드 매도 로직 (상승 추세 추종 및 트레일링 스탑 포함)
            for position in demo_positions[:]:
                # 최고가 업데이트 (트레일링 스탑용)
                if price > position['highest_price']:
                    position['highest_price'] = price

                # 안전장치: 손절 및 포트폴리오 트레일링 스탑은 항상 체크
                stop_loss_triggered = price <= position['actual_buy_price'] * (1 + config.get("stop_loss_threshold", -10.0) / 100)
                trailing_stop_triggered = False
                if config.get("trailing_stop", True):
                    trailing_percent = config.get("trailing_stop_percent", 3.0) / 100
                    if price <= position['highest_price'] * (1 - trailing_percent):
                        trailing_stop_triggered = True

                if stop_loss_triggered or trailing_stop_triggered:
                    sell_reason = "손절" if stop_loss_triggered else "트레일링스탑"
                    # 즉시 매도 실행
                    sell_amount = position['quantity'] * price
                    net_sell_amount = sell_amount * (1 - fee_rate)
                    demo_balance += net_sell_amount
                    demo_positions.remove(position)
                    save_trading_state(ticker, demo_positions, True)
                    
                    buy_cost = position['quantity'] * position['actual_buy_price']
                    net_profit = net_sell_amount - buy_cost
                    total_realized_profit += net_profit

                    log_msg = f"{sell_reason} 매도: {price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원"
                    log_and_update("데모 매도", log_msg)
                    speak_async(f"데모 모드, {sell_reason}, {get_korean_coin_name(ticker)}" + f" {price:,.0f}원에 매도되었습니다.")
                    send_kakao_message(f"[데모 매도] {get_korean_coin_name(ticker)} {price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원 ({sell_reason})")
                    
                    # 데모 모드에서도 매도 횟수 증가
                    trade_counts[ticker]["sell"] += 1
                    if net_profit > 0:  # 수익이 난 거래만 카운트
                        trade_counts[ticker]["profitable_sell"] += 1
                    
                    update_gui('refresh_chart')
                    continue # 다음 포지션으로

                # 상승 추세 추종 매도 로직
                if position.get('sell_held', False):
                    # 매도 보류 상태일 때
                    current_highest_grid = position['highest_grid_reached']
                    
                    # 가격이 다음 그리드 이상으로 상승했는지 체크
                    if current_highest_grid < len(grid_levels) - 1 and price >= grid_levels[current_highest_grid + 1]:
                        position['highest_grid_reached'] += 1
                        new_target_price = grid_levels[position['highest_grid_reached']]
                        position['target_sell_price'] = new_target_price
                        log_msg = f"매도 보류 및 목표 상향: {new_target_price:,.0f}원"
                        log_and_update("데모 매도보류", log_msg)
                        speak_async(f"{get_korean_coin_name(ticker)} " + "매도 보류 시작")
                        update_gui('refresh_chart')
                        update_gui('action_status', 'looking_sell')

                    else:
                        # 가격이 최고 그리드 아래로 '확실히' 하락했는지 체크 (매도 실행)
                        confirmation_buffer = 0.001 # 0.1% 버퍼
                        sell_confirmation_price = grid_levels[current_highest_grid] * (1 - confirmation_buffer)
                        if price <= sell_confirmation_price:
                            sell_price = grid_levels[current_highest_grid] # 하락한 그리드 가격으로 매도
                            sell_amount = position['quantity'] * sell_price
                            net_sell_amount = sell_amount * (1 - fee_rate)
                            
                            demo_balance += net_sell_amount
                            demo_positions.remove(position)
                            save_trading_state(ticker, demo_positions, True)
                            
                            buy_cost = position['quantity'] * position['actual_buy_price']
                            net_profit = net_sell_amount - buy_cost
                            total_realized_profit += net_profit

                            log_msg = f"상승추세 종료 매도: {sell_price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원"
                            log_and_update("데모 매도", log_msg)
                            speak_async(f"데모 모드, {get_korean_coin_name(ticker)} " + f" {sell_price:,.0f}원에 최종 매도되었습니다.")
                            send_kakao_message(f"[데모 최종매도] {get_korean_coin_name(ticker)} {sell_price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원")
                            
                            # 데모 모드에서도 매도 횟수 증가
                            trade_counts[ticker]["sell"] += 1
                            if net_profit > 0:  # 수익이 난 거래만 카운트
                                trade_counts[ticker]["profitable_sell"] += 1
                            
                            update_gui('refresh_chart')
                            update_gui('action_status', 'trading')

                else:
                    # 매도 보류 상태가 아닐 때: 최초 목표가 도달 체크
                    if price >= position['target_sell_price']:
                        position['sell_held'] = True
                        # 현재 그리드 레벨 찾기
                        for i, level in enumerate(grid_levels):
                            if position['target_sell_price'] == level:
                                position['highest_grid_reached'] = i
                                break
                        
                        if position['highest_grid_reached'] != -1:
                            log_msg = f"목표가 {position['target_sell_price']:,.0f}원 도달. 매도 보류 시작."
                            log_and_update("데모 매도보류", log_msg)
                            speak_async(f"{get_korean_coin_name(ticker)} " + "매도 보류 시작")
                            update_gui('refresh_chart')
                            update_gui('action_status', 'looking_sell')
            
            # 긴급 청산 체크
            held_value = sum(pos['quantity'] * price for pos in demo_positions)
            total_value = demo_balance + held_value
            
            # 코인 보유량이 0일 때 평가수익도 0으로 처리
            coin_quantity = sum(pos['quantity'] for pos in demo_positions)
            if coin_quantity == 0:
                held_value = 0  # 보유 코인이 없으면 코인가치도 0
            
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
                
                log_and_update('긴급청산', f'손실 임계점 도달: {profit_percent:.2f}%')
                send_kakao_message(f"{ticker} 긴급 청산 실행! 손실률: {profit_percent:.2f}%")
                break
            
            # 트레일링 스탑 (전체 포트폴리오)
            if total_value > highest_value:
                highest_value = total_value
            elif (config.get("trailing_stop", True) and 
                  total_value <= highest_value * (1 - config.get("trailing_stop_percent", 3.0) / 100)):
                log_and_update('트레일링청산', f'최고점 대비 {config.get("trailing_stop_percent", 3.0)}% 하락')
                break
                
            profit = total_value - start_balance
            
            # 코인 보유량이 0일 때 평가수익도 현금 잔고 기준으로만 계산
            if coin_quantity == 0:
                profit = demo_balance - start_balance  # 현금 잔고 - 시작 잔고
                total_value = demo_balance  # 총 자산도 현금만
                
            realized_profit_percent = (total_realized_profit / total_investment) * 100 if total_investment > 0 else 0
            
            update_gui('details', demo_balance, coin_quantity, held_value, total_value, profit, profit_percent, total_realized_profit, realized_profit_percent)

            # 고급 그리드 차트 상태 업데이트
            positions = demo_positions
            grid_status = {
                'pending_buys': advanced_grid_state.pending_buy_orders,
                'pending_sells': advanced_grid_state.pending_sell_orders,
                'trend': advanced_grid_state.get_trend_direction(),
                'current_price': price,
                'grid_levels': grid_levels
            }
            update_gui('chart_state', positions, grid_status)
            
        else:
            # 실제 거래 모드 로직 (생략 - 데모와 유사하게 수정 필요) 
            # TODO: 실제 거래 로직 구현
            pass # 실제 거래 로직도 데모와 동일한 방식으로 log_and_update 및 update_gui('refresh_chart') 호출 필요


        
        status, style = evaluate_status(profit_percent, True, panic_mode)
        update_gui('status', f"상태: {status}", style, True, panic_mode)

        # 목표 수익률 달성 체크
        if profit_percent >= target_profit_percent:
            log_and_update('성공', '목표 수익 달성')
            update_gui('status', "상태: 목표 달성!", "Blue.TLabel", True, False)
            save_trading_state(ticker, [], demo_mode) # 성공 시 상태 초기화
            
            # 상세 알림 메시지 생성
            summary_msg = (
                f"{get_korean_coin_name(ticker)} 목표 달성 완료!\n"
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
        
        # 매수/매도 보류 중이 아닐 때는 대기 상태로 설정
        if not buy_pending and not any(pos.get('sell_held', False) for pos in demo_positions):
            update_gui('action_status', 'waiting')
            
        time.sleep(3)

    if stop_event.is_set():
        log_and_update('중지', '사용자 요청')
        update_gui('status', "상태: 중지됨", "Orange.TLabel", False, False)
        update_gui('action_status', 'waiting')

def open_settings_window(parent, current_config, update_callback, grid_recalc_callback):
    """시스템 설정 창을 엽니다."""
    win = tk.Toplevel(parent)
    win.title("시스템 설정")
    win.geometry("600x550")

    notebook = ttk.Notebook(win)
    notebook.pack(expand=True, fill='both', padx=10, pady=10)

    # 1. API 설정 탭
    api_frame = ttk.Frame(notebook)
    notebook.add(api_frame, text='API 설정')

    ttk.Label(api_frame, text="Upbit Access Key:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
    upbit_access_entry = ttk.Entry(api_frame, width=50)
    upbit_access_entry.insert(0, current_config.get('upbit_access', ''))
    upbit_access_entry.grid(row=0, column=1, padx=5, pady=5)

    ttk.Label(api_frame, text="Upbit Secret Key:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
    upbit_secret_entry = ttk.Entry(api_frame, width=50, show='*')
    upbit_secret_entry.insert(0, current_config.get('upbit_secret', ''))
    upbit_secret_entry.grid(row=1, column=1, padx=5, pady=5)

    ttk.Label(api_frame, text="KakaoTalk Token:").grid(row=2, column=0, sticky='w', padx=5, pady=5)
    kakao_token_entry = ttk.Entry(api_frame, width=50)
    kakao_token_entry.insert(0, current_config.get('kakao_token', ''))
    kakao_token_entry.grid(row=2, column=1, padx=5, pady=5)

    # 2. 거래 전략 탭
    strategy_frame = ttk.Frame(notebook)
    notebook.add(strategy_frame, text='거래 전략')

    ttk.Label(strategy_frame, text="급락 감지 임계값 (%):").grid(row=0, column=0, sticky='w', padx=5, pady=5)
    panic_threshold_entry = ttk.Entry(strategy_frame)
    panic_threshold_entry.insert(0, current_config.get('panic_threshold', -5.0))
    panic_threshold_entry.grid(row=0, column=1, padx=5, pady=5)

    ttk.Label(strategy_frame, text="손절 임계값 (%):").grid(row=1, column=0, sticky='w', padx=5, pady=5)
    stop_loss_entry = ttk.Entry(strategy_frame)
    stop_loss_entry.insert(0, current_config.get('stop_loss_threshold', -10.0))
    stop_loss_entry.grid(row=1, column=1, padx=5, pady=5)

    trailing_stop_var = tk.BooleanVar(value=current_config.get('trailing_stop', True))
    ttk.Checkbutton(strategy_frame, text="트레일링 스탑 사용", variable=trailing_stop_var).grid(row=2, column=0, columnspan=2, sticky='w', padx=5)

    ttk.Label(strategy_frame, text="트레일링 스탑 비율 (%):").grid(row=3, column=0, sticky='w', padx=5, pady=5)
    trailing_stop_percent_entry = ttk.Entry(strategy_frame)
    trailing_stop_percent_entry.insert(0, current_config.get('trailing_stop_percent', 3.0))
    trailing_stop_percent_entry.grid(row=3, column=1, padx=5, pady=5)
    
    ttk.Label(strategy_frame, text="최대 포지션 크기 (% of total assets):").grid(row=4, column=0, sticky='w', padx=5, pady=5)
    max_position_size_entry = ttk.Entry(strategy_frame)
    max_position_size_entry.insert(0, current_config.get('max_position_size', 0.3))
    max_position_size_entry.grid(row=4, column=1, padx=5, pady=5)

    # 3. 주문 설정 탭
    order_frame = ttk.Frame(notebook)
    notebook.add(order_frame, text='주문 설정')

    use_limit_orders_var = tk.BooleanVar(value=current_config.get('use_limit_orders', True))
    ttk.Checkbutton(order_frame, text="지정가 주문 사용", variable=use_limit_orders_var).grid(row=0, column=0, columnspan=2, sticky='w', padx=5)

    ttk.Label(order_frame, text="지정가 주문 버퍼 (%):").grid(row=1, column=0, sticky='w', padx=5, pady=5)
    limit_order_buffer_entry = ttk.Entry(order_frame)
    limit_order_buffer_entry.insert(0, current_config.get('limit_order_buffer', 0.2))
    limit_order_buffer_entry.grid(row=1, column=1, padx=5, pady=5)

    # 4. 고급 그리드 설정 탭
    advanced_frame = ttk.Frame(notebook)
    notebook.add(advanced_frame, text='고급 그리드')
    
    use_custom_range_var = tk.BooleanVar(value=current_config.get('use_custom_range', False))
    ttk.Checkbutton(advanced_frame, text="사용자 지정 가격 범위 사용", variable=use_custom_range_var).grid(row=0, column=0, columnspan=2, sticky='w', padx=5)
    
    ttk.Label(advanced_frame, text="상한선 (원):").grid(row=1, column=0, sticky='w', padx=5, pady=5)
    custom_high_entry = ttk.Entry(advanced_frame)
    custom_high_entry.insert(0, current_config.get('custom_high_price', ''))
    custom_high_entry.grid(row=1, column=1, padx=5, pady=5)
    
    ttk.Label(advanced_frame, text="하한선 (원):").grid(row=2, column=0, sticky='w', padx=5, pady=5)
    custom_low_entry = ttk.Entry(advanced_frame)
    custom_low_entry.insert(0, current_config.get('custom_low_price', ''))
    custom_low_entry.grid(row=2, column=1, padx=5, pady=5)
    
    advanced_grid_var = tk.BooleanVar(value=current_config.get('advanced_grid_trading', True))
    ttk.Checkbutton(advanced_frame, text="고급 그리드 거래 활성화", variable=advanced_grid_var).grid(row=3, column=0, columnspan=2, sticky='w', padx=5)
    
    ttk.Label(advanced_frame, text="그리드 확인 버퍼 (%):").grid(row=4, column=0, sticky='w', padx=5, pady=5)
    grid_buffer_entry = ttk.Entry(advanced_frame)
    grid_buffer_entry.insert(0, current_config.get('grid_confirmation_buffer', 0.1))
    grid_buffer_entry.grid(row=4, column=1, padx=5, pady=5)
    
    ttk.Label(advanced_frame, text="거래 수수료율 (%):").grid(row=5, column=0, sticky='w', padx=5, pady=5)
    fee_rate_entry = ttk.Entry(advanced_frame)
    fee_rate_entry.insert(0, current_config.get('fee_rate', 0.0005) * 100)  # 백분율로 표시
    fee_rate_entry.grid(row=5, column=1, padx=5, pady=5)

    # 5. 자동 거래 설정 탭
    auto_frame = ttk.Frame(notebook)
    notebook.add(auto_frame, text='자동 거래')
    
    auto_trading_var = tk.BooleanVar(value=current_config.get('auto_trading_mode', False))
    ttk.Checkbutton(auto_frame, text="완전 자동 거래 모드 활성화", variable=auto_trading_var).grid(row=0, column=0, columnspan=2, sticky='w', padx=5)
    
    performance_tracking_var = tk.BooleanVar(value=current_config.get('performance_tracking', True))
    ttk.Checkbutton(auto_frame, text="실적 추적 활성화", variable=performance_tracking_var).grid(row=1, column=0, columnspan=2, sticky='w', padx=5)
    
    auto_optimization_var = tk.BooleanVar(value=current_config.get('auto_optimization', True))
    ttk.Checkbutton(auto_frame, text="자동 최적화 활성화", variable=auto_optimization_var).grid(row=2, column=0, columnspan=2, sticky='w', padx=5)
    
    # 참고 정보 라벨
    info_label = ttk.Label(auto_frame, text="리스크 모드와 업데이트 간격은 메인화면에서 설정할 수 있습니다.", 
                          foreground="gray", font=('Helvetica', 9))
    info_label.grid(row=3, column=0, columnspan=2, padx=5, pady=10, sticky='w')

    # 6. 알림 설정 탭
    notification_frame = ttk.Frame(notebook)
    notebook.add(notification_frame, text='알림 설정')

    tts_enabled_var = tk.BooleanVar(value=current_config.get('tts_enabled', True))
    ttk.Checkbutton(notification_frame, text="TTS 음성 안내 사용", variable=tts_enabled_var).grid(row=0, column=0, sticky='w', padx=5)

    kakao_enabled_var = tk.BooleanVar(value=current_config.get('kakao_enabled', True))
    ttk.Checkbutton(notification_frame, text="카카오톡 알림 사용", variable=kakao_enabled_var).grid(row=1, column=0, sticky='w', padx=5)

    def save_and_close():
        try:
            # API
            current_config['upbit_access'] = upbit_access_entry.get()
            current_config['upbit_secret'] = upbit_secret_entry.get()
            current_config['kakao_token'] = kakao_token_entry.get()
            # Strategy
            current_config['panic_threshold'] = float(panic_threshold_entry.get())
            current_config['stop_loss_threshold'] = float(stop_loss_entry.get())
            current_config['trailing_stop'] = trailing_stop_var.get()
            current_config['trailing_stop_percent'] = float(trailing_stop_percent_entry.get())
            current_config['max_position_size'] = float(max_position_size_entry.get())
            # Order
            current_config['use_limit_orders'] = use_limit_orders_var.get()
            current_config['limit_order_buffer'] = float(limit_order_buffer_entry.get())
            # Advanced Grid
            current_config['use_custom_range'] = use_custom_range_var.get()
            current_config['custom_high_price'] = custom_high_entry.get()
            current_config['custom_low_price'] = custom_low_entry.get()
            current_config['advanced_grid_trading'] = advanced_grid_var.get()
            current_config['grid_confirmation_buffer'] = float(grid_buffer_entry.get())
            current_config['fee_rate'] = float(fee_rate_entry.get()) / 100  # 백분율에서 소수로 변환
            # Auto Trading (리스크 모드와 업데이트 간격은 메인화면에서 관리됨)
            current_config['auto_trading_mode'] = auto_trading_var.get()
            current_config['performance_tracking'] = performance_tracking_var.get()
            current_config['auto_optimization'] = auto_optimization_var.get()
            # Notification
            current_config['tts_enabled'] = tts_enabled_var.get()
            current_config['kakao_enabled'] = kakao_enabled_var.get()

            if save_config(current_config):
                messagebox.showinfo("성공", "설정이 저장되었습니다.", parent=win)
                if update_callback:
                    update_callback(current_config)
                if grid_recalc_callback:
                    grid_recalc_callback(None) # Recalculate grid
                win.destroy()
            else:
                messagebox.showerror("오류", "설정 저장에 실패했습니다.", parent=win)
        except ValueError:
            messagebox.showerror("입력 오류", "숫자 필드에 올바른 값을 입력하세요.", parent=win)

    save_button = ttk.Button(win, text="저장", command=save_and_close)
    save_button.pack(pady=10)


def open_backtest_window(parent, total_investment_str, grid_count_str, period, auto_grid):
    """백테스트 창을 엽니다."""
    win = tk.Toplevel(parent)
    win.title("백테스트")
    win.geometry("800x600")

    main_frame = ttk.Frame(win, padding=10)
    main_frame.pack(expand=True, fill='both')

    # 설정 프레임
    settings_frame = ttk.LabelFrame(main_frame, text="백테스트 설정")
    settings_frame.pack(fill='x', pady=5)

    ttk.Label(settings_frame, text="코인 선택:").grid(row=0, column=0, padx=5, pady=2, sticky='w')
    ticker_combo = ttk.Combobox(settings_frame, values=["KRW-BTC", "KRW-ETH", "KRW-XRP"], state="readonly")
    ticker_combo.set("KRW-BTC")
    ticker_combo.grid(row=0, column=1, padx=5, pady=2, sticky='ew')

    ttk.Label(settings_frame, text="총 투자 금액:").grid(row=1, column=0, padx=5, pady=2, sticky='w')
    amount_entry = ttk.Entry(settings_frame)
    amount_entry.insert(0, total_investment_str)
    amount_entry.grid(row=1, column=1, padx=5, pady=2, sticky='ew')

    ttk.Label(settings_frame, text="그리드 개수:").grid(row=2, column=0, padx=5, pady=2, sticky='w')
    grid_entry = ttk.Entry(settings_frame)
    grid_entry.insert(0, grid_count_str)
    grid_entry.grid(row=2, column=1, padx=5, pady=2, sticky='ew')
    
    auto_grid_var = tk.BooleanVar(value=auto_grid)
    auto_grid_check = ttk.Checkbutton(settings_frame, text="그리드 개수 자동 계산", variable=auto_grid_var)
    auto_grid_check.grid(row=2, column=2, padx=5, pady=2, sticky='w')

    ttk.Label(settings_frame, text="기간:").grid(row=3, column=0, padx=5, pady=2, sticky='w')
    period_combo = ttk.Combobox(settings_frame, values=["1시간", "4시간", "1일", "7일"], state="readonly")
    period_combo.set(period)
    period_combo.grid(row=3, column=1, padx=5, pady=2, sticky='ew')

    ttk.Label(settings_frame, text="손절매 (%):").grid(row=4, column=0, padx=5, pady=2, sticky='w')
    stop_loss_entry = ttk.Entry(settings_frame)
    stop_loss_entry.insert(0, config.get('stop_loss_threshold', -10.0))
    stop_loss_entry.grid(row=4, column=1, padx=5, pady=2, sticky='ew')
    
    ttk.Label(settings_frame, text="목표 수익률 (%):").grid(row=5, column=0, padx=5, pady=2, sticky='w')
    target_profit_entry = ttk.Entry(settings_frame)
    target_profit_entry.insert(0, config.get('target_profit_percent', '10'))
    target_profit_entry.grid(row=5, column=1, padx=5, pady=2, sticky='ew')

    use_trailing_var = tk.BooleanVar(value=config.get('trailing_stop', True))
    ttk.Checkbutton(settings_frame, text="트레일링 스탑 사용", variable=use_trailing_var).grid(row=6, column=0, padx=5, pady=2, sticky='w')

    ttk.Label(settings_frame, text="트레일링 %:").grid(row=6, column=1, padx=5, pady=2, sticky='w')
    trailing_percent_entry = ttk.Entry(settings_frame)
    trailing_percent_entry.insert(0, config.get('trailing_stop_percent', 3.0))
    trailing_percent_entry.grid(row=6, column=2, padx=5, pady=2, sticky='ew')

    # 결과 프레임
    result_frame = ttk.LabelFrame(main_frame, text="백테스트 결과")
    result_frame.pack(expand=True, fill='both', pady=5)
    result_text = tk.Text(result_frame, wrap='word', height=15, width=80)
    result_text.pack(expand=True, fill='both', padx=5, pady=5)

    def start_backtest():
        result_text.delete('1.0', tk.END)
        result_text.insert(tk.END, "백테스트를 시작합니다. 잠시만 기다려주세요...\n\n")
        win.update_idletasks()

        try:
            ticker = ticker_combo.get()
            total_investment = float(amount_entry.get())
            grid_count = int(grid_entry.get())
            period_val = period_combo.get()
            stop_loss = float(stop_loss_entry.get())
            use_trailing = use_trailing_var.get()
            trailing_percent = float(trailing_percent_entry.get())
            auto_grid_val = auto_grid_var.get()
            target_profit_percent = target_profit_entry.get()

            results = run_backtest(ticker, total_investment, grid_count, period_val, stop_loss, use_trailing, trailing_percent, auto_grid_val, target_profit_percent)

            if results:
                result_str = (
                    f"백테스트 기간: {results['start_date']} ~ {results['end_date']}\n"
                    f"초기 자본: {results['initial_balance']:,.0f} 원\n"
                    f"최종 자산: {results['final_value']:,.0f} 원\n"
                    f"총 수익률: {results['total_return']:.2f} %\n"
                    "------------------------------------\n"
                    f"총 거래 횟수: {results['num_trades']} (매수: {results['buy_count']}, 매도: {results['sell_count']})\n"
                    f"승률: {results['win_rate']:.2f} %\n"
                    f"최고 자산 가치: {results['highest_value']:,.0f} 원\n"
                    f"최저 자산 가치: {results['lowest_value']:,.0f} 원\n"
                )
                result_text.insert(tk.END, result_str)
            else:
                result_text.insert(tk.END, "백테스트 실행 중 오류가 발생했습니다.")

        except ValueError as e:
            messagebox.showerror("입력 오류", f"숫자 필드에 올바른 값을 입력하세요: {e}", parent=win)
        except Exception as e:
            messagebox.showerror("오류", f"백테스트 중 오류 발생: {e}", parent=win)

    run_button = ttk.Button(settings_frame, text="백테스트 실행", command=start_backtest)
    run_button.grid(row=7, column=0, columnspan=3, pady=10)


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
    all_ticker_total_values = {} # 각 티커의 현재 총 자산 가치
    all_ticker_start_balances = {} # 각 티커의 시작 자본
    all_ticker_realized_profits = {} # 각 티커별 실현 수익
    profits_data = load_profits_data() # 수익 데이터 로드
    global config, upbit, total_profit_label, total_profit_rate_label # Declare global for new labels

    start_tts_worker()

    root = tk.Tk()
    root.title("그리드 투자 자동매매 대시보드 v2.6")
    root.geometry("1400x900")

    def on_closing():
        if messagebox.askokcancel("종료", "정말로 종료하시겠습니까?"):
            if active_trades:
                for ticker, stop_event in active_trades.items():
                    stop_event.set()
                active_trades.clear()  # active_trades 딕셔너리 클리어
            stop_tts_worker()
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    def update_config(new_config):
        """설정 업데이트 콜백"""
        global config, upbit
        config = new_config
        initialize_upbit()
        # 자동거래 상태 업데이트
        if 'update_auto_status' in globals():
            update_auto_status()

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
    action_status_labels = {}  # 행동 상태 라벨
    detail_labels = {}
    
    tickers = ("KRW-BTC", "KRW-ETH", "KRW-XRP")
    for i, ticker in enumerate(tickers):
        var = tk.IntVar()
        cb = ttk.Checkbutton(ticker_frame, text=ticker, variable=var)
        cb.grid(row=i*6, column=0, sticky='w', padx=3, pady=1)
        ticker_vars[ticker] = var
        
        # 상태 및 운영시간
        status_labels[ticker] = ttk.Label(ticker_frame, text="상태: 대기중", style="Gray.TLabel")
        status_labels[ticker].grid(row=i*6, column=1, sticky='w', padx=3)
        
        running_time_labels[ticker] = ttk.Label(ticker_frame, text="운영시간: 00:00:00", style="Gray.TLabel")
        running_time_labels[ticker].grid(row=i*6, column=2, sticky='w', padx=3)
        
        # 현재가
        current_price_labels[ticker] = ttk.Label(ticker_frame, text="현재가: -", style="Gray.TLabel")
        current_price_labels[ticker].grid(row=i*6, column=3, sticky='w', padx=3)
        
        # 행동 상태 (새로 추가)
        action_status_labels[ticker] = ttk.Label(ticker_frame, text="🔍 대기중", style="Blue.TLabel", font=('Helvetica', 9, 'bold'))
        action_status_labels[ticker].grid(row=i*6+1, column=1, columnspan=2, sticky='w', padx=3)
        
        # 상세 정보
        detail_labels[ticker] = {
            'profit': ttk.Label(ticker_frame, text="평가수익: 0원", style="Gray.TLabel"),
            'profit_rate': ttk.Label(ticker_frame, text="(0.00%)", style="Gray.TLabel"),
            'realized_profit': ttk.Label(ticker_frame, text="실현수익: 0원", style="Gray.TLabel"),
            'realized_profit_rate': ttk.Label(ticker_frame, text="(0.00%)", style="Gray.TLabel"),
            'cash': ttk.Label(ticker_frame, text="현금: 0원", style="Gray.TLabel"),
            'coin_qty': ttk.Label(ticker_frame, text="보유: 0개", style="Gray.TLabel"),
            'coin_value': ttk.Label(ticker_frame, text="코인가치: 0원", style="Gray.TLabel"),
            'total_value': ttk.Label(ticker_frame, text="총자산: 0원", style="Gray.TLabel"),
            'buy_count': ttk.Label(ticker_frame, text="📈 매수: 0회", style="Gray.TLabel", font=('Helvetica', 8)),
            'sell_count': ttk.Label(ticker_frame, text="📉 매도: 0회", style="Gray.TLabel", font=('Helvetica', 8)),
            'profitable_sell_count': ttk.Label(ticker_frame, text="💰 수익거래: 0회", style="Gray.TLabel", font=('Helvetica', 8))
        }
        
        detail_labels[ticker]['profit'].grid(row=i*6+2, column=0, sticky='w', padx=3)
        detail_labels[ticker]['profit_rate'].grid(row=i*6+2, column=1, sticky='w', padx=3)
        detail_labels[ticker]['realized_profit'].grid(row=i*6+2, column=2, sticky='w', padx=3)
        detail_labels[ticker]['realized_profit_rate'].grid(row=i*6+2, column=3, sticky='w', padx=3)
        detail_labels[ticker]['cash'].grid(row=i*6+3, column=0, sticky='w', padx=3)
        detail_labels[ticker]['coin_qty'].grid(row=i*6+3, column=1, sticky='w', padx=3)
        detail_labels[ticker]['coin_value'].grid(row=i*6+3, column=2, sticky='w', padx=3)
        detail_labels[ticker]['total_value'].grid(row=i*6+3, column=3, sticky='w', padx=3)
        detail_labels[ticker]['buy_count'].grid(row=i*6+4, column=0, sticky='w', padx=3)
        detail_labels[ticker]['sell_count'].grid(row=i*6+4, column=1, sticky='w', padx=3)
        detail_labels[ticker]['profitable_sell_count'].grid(row=i*6+4, column=2, columnspan=2, sticky='w', padx=3)
        
        # 구분선
        if i < len(tickers) - 1:
            sep = ttk.Separator(ticker_frame, orient='horizontal')
            sep.grid(row=i*6+5, column=0, columnspan=4, sticky='ew', pady=3)

    # 총 실현수익 및 수익률 표시 라벨
    total_profit_label = ttk.Label(ticker_frame, text="총 실현수익: 0원", font=('Helvetica', 10, 'bold'), style="Black.TLabel")
    total_profit_label.grid(row=len(tickers)*6 + 1, column=0, columnspan=2, sticky='w', padx=3, pady=5)

    total_profit_rate_label = ttk.Label(ticker_frame, text="총 실현수익률: (0.00%)", font=('Helvetica', 10, 'bold'), style="Black.TLabel")
    total_profit_rate_label.grid(row=len(tickers)*6 + 1, column=2, columnspan=2, sticky='w', padx=3, pady=5)

    # 그리드 투자 설정
    settings_frame = ttk.LabelFrame(top_frame, text="🔧 그리드 투자 설정")
    settings_frame.grid(row=0, column=1, sticky='nswe', padx=(4, 0))
    settings_frame.grid_columnconfigure(1, weight=1)
    
    # 자동거래 상태 정보 프레임
    status_info_frame = ttk.Frame(settings_frame)
    status_info_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(5, 10))
    status_info_frame.grid_columnconfigure(0, weight=1)
    status_info_frame.grid_columnconfigure(1, weight=1)
    
    # 자동거래 상태 라벨들
    auto_mode_label = ttk.Label(status_info_frame, text="🔴 자동 모드: 비활성", foreground="red", font=('Helvetica', 9, 'bold'))
    auto_mode_label.grid(row=0, column=0, sticky='w', padx=3)
    
    update_interval_label = ttk.Label(status_info_frame, text=f"⏰ 업데이트: {config.get('auto_update_interval', 60)}분", foreground="purple", font=('Helvetica', 8))
    update_interval_label.grid(row=1, column=0, sticky='w', padx=3)
    
    risk_mode_status_label = ttk.Label(status_info_frame, text=f"⚡ 리스크: {config.get('risk_mode', '안정적')}", foreground="blue", font=('Helvetica', 9, 'bold'))
    risk_mode_status_label.grid(row=0, column=1, sticky='w', padx=3)
    
    last_optimization_label = ttk.Label(status_info_frame, text="🔄 최근 최적화: -", foreground="gray", font=('Helvetica', 8))
    last_optimization_label.grid(row=1, column=1, sticky='w', padx=3)

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

    ttk.Label(settings_frame, text="목표 수익률 (%) (미지정 시 무한):").grid(row=5, column=0, sticky='w', padx=3, pady=1)
    target_entry = ttk.Entry(settings_frame)
    target_entry.insert(0, config.get("target_profit_percent", "10"))
    target_entry.grid(row=5, column=1, sticky='ew', padx=3)

    # 자동거래 제어 및 설정
    control_frame = ttk.Frame(settings_frame)
    control_frame.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(5, 5))
    control_frame.grid_columnconfigure(1, weight=1)
    
    ttk.Label(control_frame, text="자동거래 모드:").grid(row=0, column=0, sticky='w', padx=3, pady=1)
    auto_trading_var = tk.BooleanVar(value=config.get("auto_trading_mode", False))
    auto_trading_check = ttk.Checkbutton(control_frame, text="🤖 활성화", variable=auto_trading_var)
    auto_trading_check.grid(row=0, column=1, sticky='w', padx=3, pady=1)

    # 리스크 모드 선택
    ttk.Label(control_frame, text="리스크 모드:").grid(row=1, column=0, sticky='w', padx=3, pady=1)
    risk_mode_combo = ttk.Combobox(control_frame, values=["보수적", "안정적", "공격적", "극공격적"], state="readonly")
    risk_mode_combo.set(config.get("risk_mode", "보수적"))
    risk_mode_combo.grid(row=1, column=1, sticky='ew', padx=3)
    
    # 업데이트 간격 설정
    ttk.Label(control_frame, text="업데이트 간격(분):").grid(row=2, column=0, sticky='w', padx=3, pady=1)
    update_interval_entry = ttk.Entry(control_frame, width=15)
    update_interval_entry.insert(0, str(config.get("auto_update_interval", 60)))
    update_interval_entry.grid(row=2, column=1, sticky='w', padx=3)
    
    # 자동거래 상태 업데이트 함수들
    def update_auto_status():
        """자동 거래 상태 업데이트"""
        if config.get('auto_trading_mode', False):
            auto_mode_label.config(text="🟢 자동 모드: 활성", foreground="green")
        else:
            auto_mode_label.config(text="🔴 자동 모드: 비활성", foreground="red")
        
        risk_mode = config.get('risk_mode', '안정적')
        risk_colors = {"보수적": "blue", "안정적": "green", "공격적": "orange", "극공격적": "red"}
        risk_mode_status_label.config(text=f"⚡ 리스크: {risk_mode}", foreground=risk_colors.get(risk_mode, "blue"))
        
        # 업데이트 간격 표시
        update_interval_label.config(text=f"⏰ 업데이트: {config.get('auto_update_interval', 60)}분")
        
        last_opt = config.get('last_optimization')
        if last_opt:
            try:
                opt_time = datetime.fromisoformat(last_opt).strftime('%H:%M')
                last_optimization_label.config(text=f"🔄 최근 최적화: {opt_time}")
            except:
                last_optimization_label.config(text="🔄 최근 최적화: -")
        else:
            last_optimization_label.config(text="🔄 최근 최적화: -")
    
    def update_action_status(ticker, status_type):
        """코인별 행동 상태 업데이트
        status_type: 'waiting', 'looking_buy', 'looking_sell', 'trading', 'error'
        """
        status_texts = {
            'waiting': "🔍 대기중",
            'looking_buy': "📈 매수 시점 찾는 중",
            'looking_sell': "📉 매도 시점 찾는 중", 
            'trading': "⚡ 거래 실행 중",
            'error': "❌ API 오류 감지됨"
        }
        
        status_colors = {
            'waiting': "Blue.TLabel",
            'looking_buy': "Green.TLabel", 
            'looking_sell': "Orange.TLabel",
            'trading': "Purple.TLabel",
            'error': "Red.TLabel"
        }
        
        if ticker in action_status_labels:
            action_status_labels[ticker].config(
                text=status_texts.get(status_type, "🔍 대기중"),
                style=status_colors.get(status_type, "Blue.TLabel")
            )
    
    def check_api_data_validity(ticker, current_price, orderbook=None):
        """API 데이터 유효성 검사"""
        try:
            # 기본 가격 유효성 검사
            if current_price is None or current_price <= 0:
                return False, "현재가 데이터 오류"
            
            # 오더북 데이터가 있는 경우 추가 검사
            if orderbook:
                if not orderbook.get('orderbook_units') or len(orderbook['orderbook_units']) == 0:
                    return False, "오더북 데이터 없음"
                
                # 매수/매도 호가 존재 여부 확인
                first_unit = orderbook['orderbook_units'][0]
                if not first_unit.get('bid_price') or not first_unit.get('ask_price'):
                    return False, "매수/매도 호가 데이터 오류"
                
                # 스프레드 이상치 검사 (현재가 대비 5% 이상 차이나면 오류로 간주)
                bid_price = first_unit['bid_price']
                ask_price = first_unit['ask_price']
                spread_ratio = (ask_price - bid_price) / current_price
                if spread_ratio > 0.05:  # 5% 이상 스프레드는 비정상
                    return False, f"비정상적인 스프레드: {spread_ratio:.2%}"
            
            return True, "정상"
            
        except Exception as e:
            return False, f"데이터 검증 오류: {str(e)}"
    
    def toggle_auto_mode():
        """자동 거래 모드 토글"""
        current = config.get('auto_trading_mode', False)
        config['auto_trading_mode'] = not current
        auto_trading_var.set(not current)
        save_config(config)
        update_auto_status()
        
        if config['auto_trading_mode']:
            # 자동 최적화 시작
            auto_scheduler.start_auto_optimization(update_config)
            messagebox.showinfo("자동 모드", "자동 거래 모드가 활성화되었습니다.")
        else:
            # 자동 최적화 중지
            auto_scheduler.stop_auto_optimization()
            messagebox.showinfo("자동 모드", "자동 거래 모드가 비활성화되었습니다.")
    
    # 변경시 즉시 자동거래 상태 업데이트
    def on_auto_trading_change():
        config["auto_trading_mode"] = auto_trading_var.get()
        save_config(config)
        update_auto_status()
        
        if config['auto_trading_mode']:
            auto_scheduler.start_auto_optimization(update_config)
        else:
            auto_scheduler.stop_auto_optimization()
    
    def on_risk_mode_change(event):
        config["risk_mode"] = risk_mode_combo.get()
        save_config(config)
        update_auto_status()
    
    auto_trading_var.trace('w', lambda *args: on_auto_trading_change())
    risk_mode_combo.bind('<<ComboboxSelected>>', on_risk_mode_change)
    
    # 버튼 프레임 준비 (실제 버튼들은 함수 정의 후에 생성)
    main_button_frame = ttk.Frame(settings_frame)
    main_button_frame.grid(row=7, column=0, columnspan=2, sticky='ew', pady=(10, 5))
    main_button_frame.grid_columnconfigure(0, weight=4)  # 거래시작 버튼 영역 (40% 비율)
    main_button_frame.grid_columnconfigure(1, weight=3)  # 자동모드 버튼 영역 (30% 비율)
    main_button_frame.grid_columnconfigure(2, weight=3)  # 고급설정 버튼 영역 (30% 비율)
    
    # 버튼 스타일 정의
    button_style = ttk.Style()
    button_style.configure('Small.TButton', font=('Helvetica', 9), padding=(2, 0))

    demo_var = tk.IntVar(value=config.get("demo_mode", 1))
    demo_check = ttk.Checkbutton(settings_frame, text="데모 모드", variable=demo_var)
    demo_check.grid(row=8, column=0, columnspan=2, sticky='w', padx=3, pady=3)
    
    # 초기 자동거래 상태 설정
    update_auto_status()

    def add_log_to_gui(log_entry):
        """GUI 로그 트리에 새 로그 항목 추가"""
        ticker = log_entry.get('ticker', 'SYSTEM')
        action = log_entry.get('action', '')
        price_info = log_entry.get('price', '')
        log_time = log_entry.get('time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        log_tree.insert('', 'end', values=(log_time, ticker, action, price_info))
        log_tree.yview_moveto(1) # 항상 최신 로그가 보이도록 스크롤

    def load_previous_trading_state():
        """이전 거래 상태를 로드하여 이어서 거래할 수 있도록 함"""
        try:
            # 거래 상태 파일들이 존재하는지 확인
            state_files_exist = False
            for ticker in ["KRW-BTC", "KRW-ETH", "KRW-XRP"]:
                state_file_path = f"trading_state_{ticker.replace('-', '_')}.json"
                if os.path.exists(state_file_path):
                    with open(state_file_path, 'r', encoding='utf-8') as f:
                        state_data = json.load(f)
                        if state_data.get('positions') or state_data.get('balance'):
                            state_files_exist = True
                            break
            
            if state_files_exist:
                response = messagebox.askyesno(
                    "거래 상태 복구", 
                    "이전 거래 데이터가 발견되었습니다.\n이어서 거래하시겠습니까?\n\n'예'를 선택하면 기존 포지션과 잔고를 유지합니다.\n'아니오'를 선택하면 새로운 거래를 시작합니다."
                )
                return response
            return False
        except Exception as e:
            print(f"거래 상태 로드 확인 오류: {e}")
            return False

    def toggle_trading():
        """거래 시작/중지 로직 통합"""
        # 거래 중지 로직
        if active_trades:
            for ticker, stop_event in active_trades.items():
                stop_event.set()
            active_trades.clear()  # active_trades 딕셔너리 클리어
            toggle_button.config(text="거래 시작")
            return

        # 거래 시작 로직
        if not initialize_upbit() and not demo_var.get():
            messagebox.showerror("오류", "업비트 API 키가 유효하지 않습니다.")
            return

        selected_tickers = [ticker for ticker, var in ticker_vars.items() if var.get()]
        if not selected_tickers:
            messagebox.showwarning("경고", "거래할 코인을 선택해주세요.")
            return

        try:
            # 현재 UI 설정값을 config에 저장
            config["total_investment"] = amount_entry.get()
            config["grid_count"] = grid_entry.get()
            config["period"] = period_combo.get()
            config["target_profit_percent"] = target_entry.get()
            config["demo_mode"] = demo_var.get()
            config["auto_grid_count"] = auto_grid_var.get()
            config["auto_trading_mode"] = auto_trading_var.get()
            config["risk_mode"] = risk_mode_combo.get()
            
            # 업데이트 간격 저장
            try:
                config["auto_update_interval"] = int(update_interval_entry.get())
            except ValueError:
                config["auto_update_interval"] = 60  # 기본값
                
            save_config(config)
            
            # 자동거래 상태 업데이트
            update_auto_status()

            total_investment = float(amount_entry.get())
            grid_count = int(grid_entry.get())
            period = period_combo.get()
            demo_mode = demo_var.get()
            target_profit_percent_str = target_entry.get()

            # 자동 그리드 개수 계산
            if auto_grid_var.get():
                representative_ticker = selected_tickers[0]
                high_price, low_price = calculate_price_range(representative_ticker, period)
                if high_price and low_price:
                    target_profit = 10.0
                    if target_profit_percent_str and target_profit_percent_str.strip():
                        try:
                            target_profit = float(target_profit_percent_str)
                        except (ValueError, TypeError):
                            pass
                    new_grid_count = calculate_optimal_grid_count(high_price, low_price, target_profit, 0.0005)
                    grid_entry.delete(0, tk.END)
                    grid_entry.insert(0, str(new_grid_count))
                    grid_count = new_grid_count # 업데이트된 그리드 수 사용
                    log_entry = log_trade(representative_ticker, '정보', f'{period} 기준, 자동 계산된 그리드: {new_grid_count}개')
                    if log_entry:
                        log_entry['ticker'] = representative_ticker
                        add_log_to_gui(log_entry)
                else:
                    messagebox.showwarning("경고", f"{representative_ticker}의 가격 범위 계산에 실패하여 자동 그리드 계산을 중단합니다.")
                    return

        except ValueError:
            messagebox.showerror("오류", "투자 금액과 그리드 개수는 숫자여야 합니다.")
            return

        toggle_button.config(text="거래 정지")
        for ticker in selected_tickers:
            if ticker not in active_trades:
                stop_event = threading.Event()
                active_trades[ticker] = stop_event
                
                trade_thread = threading.Thread(
                    target=grid_trading,
                    args=(
                        ticker, grid_count, total_investment, demo_mode,
                        target_profit_percent_str, period, stop_event, gui_queue,
                        total_profit_label, total_profit_rate_label,
                        all_ticker_total_values, all_ticker_start_balances, profits_data
                    ),
                    daemon=True
                )
                trade_thread.start()
                status_labels[ticker].config(text="상태: 시작중...", style="Blue.TLabel")

    # toggle_trading 함수 정의 후 버튼들 생성
    # 거래시작 버튼
    toggle_button = ttk.Button(main_button_frame, text="거래 시작", command=toggle_trading)
    toggle_button.grid(row=0, column=0, padx=(0, 5), sticky='nsew')
    
    # 자동모드 토글 버튼 (폭 30% 축소, 높이는 거래시작 버튼과 동일)
    auto_toggle_btn = ttk.Button(main_button_frame, text="🤖 자동모드", command=toggle_auto_mode, style='Small.TButton')
    auto_toggle_btn.grid(row=0, column=1, padx=(2, 2), sticky='nsew')
    
    # 설정 버튼 (폭 30% 축소, 높이는 거래시작 버튼과 동일)
    settings_btn = ttk.Button(main_button_frame, text="⚙️ 고급설정", command=lambda: open_settings_window(root, config, update_config, None), style='Small.TButton')
    settings_btn.grid(row=0, column=2, padx=(2, 0), sticky='nsew')

    def update_grid_count_on_period_change(event):
        if auto_grid_var.get():
            try:
                selected_tickers = [ticker for ticker, var in ticker_vars.items() if var.get()]
                representative_ticker = selected_tickers[0] if selected_tickers else "KRW-BTC"
                period = period_combo.get()
                high_price, low_price = calculate_price_range(representative_ticker, period)
                
                target_profit_str = target_entry.get()
                target_profit = 10.0
                if target_profit_str and target_profit_str.strip():
                    try:
                        target_profit = float(target_profit_str)
                    except (ValueError, TypeError):
                        pass

                if high_price and low_price:
                    new_grid_count = calculate_optimal_grid_count(high_price, low_price, target_profit, 0.0005)
                    grid_entry.delete(0, tk.END)
                    grid_entry.insert(0, str(new_grid_count))
                    log_entry = log_trade(representative_ticker, '정보', f'{period} 기준, 자동 계산된 그리드: {new_grid_count}개')
                    if log_entry:
                        log_entry['ticker'] = representative_ticker
                        add_log_to_gui(log_entry)
                else:
                    log_entry = log_trade(representative_ticker, '오류', f'{period} 기준 가격 범위 계산 실패')
                    if log_entry:
                        log_entry['ticker'] = representative_ticker
                        add_log_to_gui(log_entry)
            except Exception as e:
                print(f"그리드 자동 계산 오류: {e}")

    period_combo.bind("<<ComboboxSelected>>", update_grid_count_on_period_change)

    # 추가 기능 버튼들을 settings_frame의 하단에 배치
    additional_buttons_frame = ttk.Frame(settings_frame)
    additional_buttons_frame.grid(row=9, column=0, columnspan=2, sticky='ew', pady=(5, 5))
    additional_buttons_frame.grid_columnconfigure(0, weight=1)
    additional_buttons_frame.grid_columnconfigure(1, weight=1)
    
    # 첫 번째 줄 버튼들
    button_row1 = ttk.Frame(additional_buttons_frame)
    button_row1.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 5))
    
    ttk.Button(button_row1, text="📊 백테스트", 
               command=lambda: open_backtest_window(root, amount_entry.get(), grid_entry.get(), period_combo.get(), auto_grid_var.get())).pack(side='left', padx=(0, 5))
    
    def export_data_to_excel():
        success, filename = export_to_excel()
        if success:
            messagebox.showinfo("성공", f"데이터가 {filename}로 내보내기되었습니다.")
        else:
            messagebox.showerror("오류", f"내보내기 실패: {filename}")

    ttk.Button(button_row1, text="📄 엑셀 내보내기", 
               command=export_data_to_excel).pack(side='left', padx=(5, 5))
    ttk.Button(button_row1, text="🗑️ 데이터 초기화", 
               command=lambda: clear_all_data(log_tree, detail_labels, tickers, total_profit_label, total_profit_rate_label, all_ticker_total_values, all_ticker_start_balances, all_ticker_realized_profits)).pack(side='left', padx=(5, 0))

    def clear_all_data(log_tree, detail_labels, tickers, total_profit_label, total_profit_rate_label, all_ticker_total_values, all_ticker_start_balances, all_ticker_realized_profits):
        # Clear log_tree
        for item in log_tree.get_children():
            log_tree.delete(item)

        # 2. 각 티커별 상세 정보 초기화
        # 2. 각 티커별 상세 정보 초기화 (이 부분은 이미 clear_all_data 함수 내에 있으므로 중복 제거)
        for ticker in tickers:
            detail_labels[ticker]['profit'].config(text="평가수익: 0원", style="Gray.TLabel")
            detail_labels[ticker]['profit_rate'].config(text="(0.00%)", style="Gray.TLabel")
            detail_labels[ticker]['realized_profit'].config(text="실현수익: 0원", style="Gray.TLabel")
            detail_labels[ticker]['realized_profit_rate'].config(text="(0.00%)", style="Gray.TLabel")
            detail_labels[ticker]['cash'].config(text="현금: 0원", style="Gray.TLabel")
            detail_labels[ticker]['coin_qty'].config(text="보유: 0개", style="Gray.TLabel")
            detail_labels[ticker]['coin_value'].config(text="코인가치: 0원", style="Gray.TLabel")
            detail_labels[ticker]['total_value'].config(text="총자산: 0원", style="Gray.TLabel")
            detail_labels[ticker]['buy_count'].config(text="📈 매수: 0회", style="Gray.TLabel")
            detail_labels[ticker]['sell_count'].config(text="📉 매도: 0회", style="Gray.TLabel")
            detail_labels[ticker]['profitable_sell_count'].config(text="💰 수익거래: 0회", style="Gray.TLabel")
            
            # 매수/매도 개수 초기화
            trade_counts[ticker]["buy"] = 0
            trade_counts[ticker]["sell"] = 0
            trade_counts[ticker]["profitable_sell"] = 0


        # Clear tickers and related data structures
        all_ticker_total_values.clear()
        all_ticker_start_balances.clear()
        all_ticker_realized_profits.clear()

        # Reset total profit labels
        total_profit_label.config(text="총 실현수익: 0원", style="Black.TLabel")
        total_profit_rate_label.config(text="총 실현수익률: (0.00%)", style="Black.TLabel")

        # Clear JSON files
        for filename in ["profits.json", "trade_logs.json", "trading_state.json"]:
            try:
                with open(filename, 'w') as f:
                    json.dump({}, f)  # Write an empty JSON object
            except Exception as e:
                print(f"Error clearing {filename}: {e}")

        print("All data cleared.")

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
                ax.axhline(y=level, color='gray', linestyle='--', alpha=0.5, linewidth=0.5)
            
            ax.axhline(y=high_price, color='green', linestyle='-', alpha=0.8, linewidth=1, label='상한선')
            ax.axhline(y=low_price, color='red', linestyle='-', alpha=0.8, linewidth=1, label='하한선')

        # 거래 기록 표시
        trade_points = {'buy': [], 'sell': [], 'hold_buy': [], 'hold_sell': []}
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
                        else: # 가격 정보가 없는 로그 (e.g., '시작')
                            continue

                        info_text = f"{log['action']}: {log['price']}"
                        point_data = {'time': trade_time, 'price': trade_price, 'info': info_text}

                        if '매수보류' in action:
                            trade_points['hold_buy'].append(point_data)
                        elif '매도보류' in action:
                            trade_points['hold_sell'].append(point_data)
                        elif '매수' in action:
                            trade_points['buy'].append(point_data)
                        elif '매도' in action:
                            trade_points['sell'].append(point_data)

                    except (ValueError, TypeError) as e:
                        print(f"로그 파싱 오류: {log} -> {e}")
                        continue
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            pass

        scatters = []
        all_trade_points = []

        # 매수/매도/보류 표기
        if trade_points['buy']:
            buy_times = [p['time'] for p in trade_points['buy']]
            buy_prices = [p['price'] for p in trade_points['buy']]
            scatters.append(ax.scatter(buy_times, buy_prices, color='blue', marker='^', s=60, zorder=5, label='매수'))
            all_trade_points.extend(trade_points['buy'])

        if trade_points['sell']:
            sell_times = [p['time'] for p in trade_points['sell']]
            sell_prices = [p['price'] for p in trade_points['sell']]
            scatters.append(ax.scatter(sell_times, sell_prices, color='red', marker='v', s=60, zorder=5, label='매도'))
            all_trade_points.extend(trade_points['sell'])
        
        if trade_points['hold_buy']:
            hold_buy_times = [p['time'] for p in trade_points['hold_buy']]
            hold_buy_prices = [p['price'] for p in trade_points['hold_buy']]
            scatters.append(ax.scatter(hold_buy_times, hold_buy_prices, color='cyan', marker='>', s=40, zorder=4, label='매수보류'))
            all_trade_points.extend(trade_points['hold_buy'])

        if trade_points['hold_sell']:
            hold_sell_times = [p['time'] for p in trade_points['hold_sell']]
            hold_sell_prices = [p['price'] for p in trade_points['hold_sell']]
            scatters.append(ax.scatter(hold_sell_times, hold_sell_prices, color='magenta', marker='<', s=40, zorder=4, label='매도보류'))
            all_trade_points.extend(trade_points['hold_sell'])
        
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        
        # Annotation 객체 생성
        annot = ax.annotate("", xy=(0,0), xytext=(10,10), textcoords="offset points",
                            bbox=dict(boxstyle="round", fc="w", ec="k", lw=1),
                            arrowprops=dict(arrowstyle="->"))
        annot.set_visible(False)

        # 호버 이벤트 데이터 저장
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

    def load_initial_logs():
        """초기 로그 로드"""
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            all_logs = []
            for ticker, ticker_logs in logs.items():
                for log in ticker_logs:
                    full_log = log.copy()
                    full_log['ticker'] = ticker
                    all_logs.append(full_log)
            
            # 시간순으로 정렬
            all_logs.sort(key=lambda x: x.get('time', ''))
            
            for log in all_logs:
                add_log_to_gui(log)

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
                elif key == 'action_status':
                    update_action_status(ticker, args[0])
                elif key == 'price':
                    current_price_labels[ticker].config(text=args[0], style=args[1])
                elif key == 'running_time':
                    running_time_labels[ticker].config(text=args[0], style="Blue.TLabel")
                elif key == 'details':
                    cash, coin_qty, held_value, total_value, profit, profit_percent, total_realized_profit, realized_profit_percent = args
                    
                    # 코인 보유량이 0일 때 평가수익을 0으로 강제 설정
                    if coin_qty == 0:
                        held_value = 0
                        profit = 0  # 평가수익 0으로 설정
                        profit_percent = 0  # 평가수익률도 0으로 설정
                    
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
                    detail_labels[ticker]['buy_count'].config(text=f"📈 매수: {trade_counts[ticker]['buy']}회", style="Black.TLabel")
                    detail_labels[ticker]['sell_count'].config(text=f"📉 매도: {trade_counts[ticker]['sell']}회", style="Black.TLabel")
                    detail_labels[ticker]['profitable_sell_count'].config(text=f"💰 수익거래: {trade_counts[ticker]['profitable_sell']}회", style="Green.TLabel")

                    all_ticker_total_values[ticker] = total_value
                    all_ticker_start_balances[ticker] = float(config.get("total_investment", "0")) 
                    all_ticker_realized_profits[ticker] = total_realized_profit

                    total_sum_current_value = sum(all_ticker_total_values.values())
                    total_sum_initial_investment = sum(all_ticker_start_balances.values())

                    overall_profit = sum(all_ticker_realized_profits.values())
                    overall_profit_percent = (overall_profit / total_sum_initial_investment) * 100 if total_sum_initial_investment > 0 else 0

                    total_profit_label.config(text=f'총 실현수익: {overall_profit:,.0f}원', style=get_profit_color_style(overall_profit))
                    total_profit_rate_label.config(text=f'총 실현수익률: ({overall_profit_percent:+.2f}%)', style=get_profit_color_style(overall_profit))
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

    # 설명 라벨 추가
    info_text = "그리드 투자: 설정 기간의 최고가/최저가 범위를 그리드로 분할하여 자동 매수/매도 (v2.6 - 차트/로그 개선)"
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
    root.after(1000, refresh_charts)
    
    root.mainloop()

if __name__ == "__main__":
    initialize_files()
    start_dashboard()
