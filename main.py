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
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import pandas as pd
import numpy as np
import os
from pathlib import Path
import xlsxwriter
import pyttsx3
import shutil

# TTS 엔진 초기화
try:
    tts_engine = pyttsx3.init()
    # 말하기 속도 조절 (기본값: 200)
    rate = tts_engine.getProperty('rate')
    tts_engine.setProperty('rate', 150) # 150으로 설정 (보통 속도)
    
    tts_queue = Queue()
    tts_lock = threading.Lock()
    tts_worker_thread = None
    
    # TTS 경고 중복 방지를 위한 변수
    last_alert_time = {}  # 각 코인별 마지막 경고 시간
    alert_cooldown = 60   # 경고 쿨다운 시간 (초)
    
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

def analyze_market_condition(ticker, current_price, recent_prices, high_price, low_price):
    """시장 상태 분석 함수"""
    try:
        if len(recent_prices) < 10:
            return "데이터 부족", "분석 불가"
        
        # 최근 가격 변화율 계산
        price_1min_ago = recent_prices[-2] if len(recent_prices) >= 2 else current_price
        price_5min_ago = recent_prices[-6] if len(recent_prices) >= 6 else current_price
        price_10min_ago = recent_prices[-11] if len(recent_prices) >= 11 else current_price
        
        change_1min = ((current_price - price_1min_ago) / price_1min_ago) * 100
        change_5min = ((current_price - price_5min_ago) / price_5min_ago) * 100
        change_10min = ((current_price - price_10min_ago) / price_10min_ago) * 100
        
        # 박스권 계산 (최고가와 최저가 사이의 구간)
        box_range = f"{low_price:,.0f}원~{high_price:,.0f}원"
        price_position = (current_price - low_price) / (high_price - low_price) if high_price > low_price else 0.5
        
        # 상태 결정
        status = ""
        details = ""
        
        # 급등/급락 기준: 1분 3% 이상 또는 5분 7% 이상 또는 10분 10% 이상
        if change_1min >= 3.0 or change_5min >= 7.0 or change_10min >= 10.0:
            status = "급등"
            if change_1min >= 5.0:
                details = f"초급등 {change_1min:+.1f}% (1분)"
            elif change_5min >= 10.0:
                details = f"강급등 {change_5min:+.1f}% (5분)"
            else:
                details = f"급등 {change_10min:+.1f}% (10분)"
                
        elif change_1min <= -3.0 or change_5min <= -7.0 or change_10min <= -10.0:
            status = "급락"
            if change_1min <= -5.0:
                details = f"초급락 {change_1min:+.1f}% (1분)"
            elif change_5min <= -10.0:
                details = f"강급락 {change_5min:+.1f}% (5분)"
            else:
                details = f"급락 {change_10min:+.1f}% (10분)"
                
        elif price_position >= 0.8:
            status = "고점권"
            details = f"상단 {price_position*100:.0f}% ({box_range})"
            
        elif price_position <= 0.2:
            status = "저점권"
            details = f"하단 {price_position*100:.0f}% ({box_range})"
            
        elif 0.3 <= price_position <= 0.7:
            status = "박스권"
            details = f"중간 {price_position*100:.0f}% ({box_range})"
            
        elif change_5min > 2.0:
            status = "상승"
            details = f"상승세 {change_5min:+.1f}% (5분)"
            
        elif change_5min < -2.0:
            status = "하락"
            details = f"하락세 {change_5min:+.1f}% (5분)"
            
        else:
            status = "보합"
            details = f"횡보 {change_5min:+.1f}% ({box_range})"
            
        return status, details
        
    except Exception as e:
        print(f"시장 상태 분석 오류: {e}")
        return "오류", "분석 실패"

def speak_async(text, repeat=1):
    """TTS 큐에 메시지를 추가 (논블로킹)"""
    if tts_engine and config.get('tts_enabled', True):
        for _ in range(repeat):
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


# 데이터 폴더 및 파일 관리
# 데이터 폴더 생성
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

# 백업 폴더도 생성
backup_dir = data_dir / "backup"
backup_dir.mkdir(exist_ok=True)
(backup_dir / "corrupted").mkdir(exist_ok=True)
(backup_dir / "daily").mkdir(exist_ok=True)

# 설정 파일 관리
config_file = data_dir / "config.json"
profit_file = data_dir / "profits.json"
log_file = data_dir / "trade_logs.json"
state_file = data_dir / "trading_state.json"
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
    "auto_optimization": True,  # 자동 최적화 활성화
    # 코인별 그리드 설정
    "coin_specific_grids": {
        "KRW-BTC": {
            "enabled": True,
            "grid_count": 20,
            "price_range_days": 7,
            "volatility_multiplier": 1.0,
            "min_grid_count": 10,
            "max_grid_count": 50
        },
        "KRW-ETH": {
            "enabled": True,
            "grid_count": 25,
            "price_range_days": 5,
            "volatility_multiplier": 1.2,
            "min_grid_count": 15,
            "max_grid_count": 60
        },
        "KRW-XRP": {
            "enabled": True,
            "grid_count": 30,
            "price_range_days": 3,
            "volatility_multiplier": 1.5,
            "min_grid_count": 20,
            "max_grid_count": 80
        }
    }
}

class CoinSpecificGridManager:
    """코인별 그리드 설정 및 최적화 관리자"""
    
    def __init__(self):
        self.coin_profiles = {
            "KRW-BTC": {
                "volatility_factor": 1.0,  # 기준 변동성
                "liquidity_factor": 1.0,   # 기준 유동성
                "trend_sensitivity": 0.8,  # 트렌드 민감도 (낮음)
                "optimal_grid_base": 20,   # 기본 그리드 수
                "price_tier_multiplier": 1.0  # 가격대 별 변경 비율
            },
            "KRW-ETH": {
                "volatility_factor": 1.2,
                "liquidity_factor": 1.1,
                "trend_sensitivity": 1.0,
                "optimal_grid_base": 25,
                "price_tier_multiplier": 1.1
            },
            "KRW-XRP": {
                "volatility_factor": 1.8,
                "liquidity_factor": 0.9,
                "trend_sensitivity": 1.3,
                "optimal_grid_base": 30,
                "price_tier_multiplier": 1.3
            }
        }
    
    def get_coin_profile(self, ticker):
        """코인별 프로필 반환"""
        return self.coin_profiles.get(ticker, self.coin_profiles["KRW-BTC"])
    
    def calculate_optimal_grid_count(self, ticker, price_range, total_investment, current_price=None):
        """코인별 최적 그리드 수 계산 (자동 최적화 포함)"""
        try:
            auto_mode = config.get('auto_trading_mode', False)
            coin_name = get_korean_coin_name(ticker)
            print(f"⚙️ {coin_name} 그리드 계산 - 자동모드: {auto_mode}")
            
            # 자동 모드에서는 고급 최적화 알고리즘 사용
            if auto_mode:
                _, optimal_grid_count = self.find_optimal_period_and_grid(ticker)
                print(f"⚙️ {coin_name} 자동 그리드: {optimal_grid_count}개")
                return optimal_grid_count
                
            # 수동 모드에서는 기존 로직 사용
            profile = self.get_coin_profile(ticker)
            coin_config = config.get('coin_specific_grids', {}).get(ticker, {})
            
            # 기본 그리드 수
            base_grids = coin_config.get('grid_count', profile['optimal_grid_base'])
            
            # 가격 범위에 따른 조정
            if price_range and len(price_range) >= 2:
                high_price, low_price = price_range[0], price_range[1]
                price_volatility = (high_price - low_price) / low_price
                
                # 변동성에 따른 그리드 수 조정
                volatility_adjustment = price_volatility * profile['volatility_factor']
                
                # 최종 그리드 수 계산
                optimal_grids = int(base_grids * (1 + volatility_adjustment))
                
                # 범위 제한
                min_grids = coin_config.get('min_grid_count', 5)
                max_grids = coin_config.get('max_grid_count', 100)
                
                optimal_grids = max(min_grids, min(max_grids, optimal_grids))
                
                return optimal_grids
            
            return base_grids
            
        except Exception as e:
            print(f"코인별 그리드 계산 오류 ({ticker}): {e}")
            return 20  # 기본값
    
    def get_price_range_days(self, ticker):
        """코인별 가격 범위 계산 기간 반환 (자동 최적화 포함)"""
        # 자동 모드에서는 최적 기간 계산
        auto_mode = config.get('auto_trading_mode', False)
        coin_name = get_korean_coin_name(ticker)
        print(f"📊 {coin_name} 기간 계산 - 자동모드: {auto_mode}")
        
        if auto_mode:
            optimal_period, _ = self.find_optimal_period_and_grid(ticker)
            return optimal_period
        
        # 수동 모드에서는 설정된 기간 사용
        coin_config = config.get('coin_specific_grids', {}).get(ticker, {})
        manual_period = coin_config.get('price_range_days', 7)
        print(f"📊 {coin_name} 수동 기간: {manual_period}일")
        return manual_period
    
    def find_optimal_period_and_grid(self, ticker):
        """최적의 기간과 그리드 개수를 찾는 고급 알고리즘 (백테스팅 포함)"""
        try:
            coin_name = get_korean_coin_name(ticker)
            print(f"🔍 {coin_name} 자동 최적화 시작...")
            
            # 여러 기간을 테스트
            test_periods = [3, 5, 7, 10, 14, 21, 30]
            best_score = -1
            best_period = 7
            best_grid_count = 20
            
            current_price = pyupbit.get_current_price(ticker)
            if not current_price:
                return best_period, best_grid_count
                
            for period in test_periods:
                try:
                    # 각 기간별로 가격 범위 계산
                    high_price, low_price = calculate_price_range(ticker, period)
                    if high_price <= low_price:
                        continue
                        
                    # 변동성과 트렌드 분석
                    price_range = high_price - low_price
                    volatility = price_range / ((high_price + low_price) / 2)
                    
                    # 현재가가 범위 내에 있는지 확인
                    price_position = (current_price - low_price) / price_range if price_range > 0 else 0.5
                    
                    # 최적 그리드 개수 계산 (변동성과 가격 위치 기반)
                    base_grid = self.get_coin_profile(ticker)["optimal_grid_base"]
                    
                    # 변동성에 따른 그리드 밀도 조정
                    grid_density_factor = 1.0
                    if volatility > 0.15:  # 높은 변동성
                        grid_density_factor = 1.3
                    elif volatility < 0.05:  # 낮은 변동성
                        grid_density_factor = 0.8
                        
                    optimal_grid = int(base_grid * grid_density_factor * (1 + volatility * 0.5))
                    optimal_grid = max(10, min(50, optimal_grid))  # 10-50 범위 제한
                    
                    # 백테스팅 점수 (간단한 시뮬레이션)
                    backtest_score = self._simulate_grid_performance(ticker, period, optimal_grid, high_price, low_price)
                    
                    # 수익성 점수 계산
                    # 1. 변동성 점수 (적당한 변동성이 좋음, 0.08-0.15가 이상적)
                    optimal_volatility = 0.10
                    volatility_score = 1 / (1 + abs(volatility - optimal_volatility) * 10)
                    
                    # 2. 가격 위치 점수 (중간에서 약간 아래가 좋음, 0.3-0.6이 이상적)
                    ideal_position = 0.45
                    position_score = 1 - abs(price_position - ideal_position) * 2
                    position_score = max(0, position_score)
                    
                    # 3. 기간 점수 (7-14일이 최적)
                    if 5 <= period <= 14:
                        period_score = 1.0
                    else:
                        period_score = 1 / (1 + abs(period - 10) * 0.1)
                    
                    # 4. 백테스팅 점수
                    backtest_weight = 0.3
                    
                    # 종합 점수 (백테스팅 결과 포함)
                    total_score = (
                        volatility_score * 0.3 + 
                        position_score * 0.25 + 
                        period_score * 0.15 + 
                        backtest_score * backtest_weight
                    )
                    
                    if total_score > best_score:
                        best_score = total_score
                        best_period = period
                        best_grid_count = optimal_grid
                        
                except Exception as e:
                    continue
                    
            # 최적화 결과 로그 출력
            coin_name = get_korean_coin_name(ticker)
            print(f"🔍 {coin_name} 자동 최적화 완료: {best_period}일 기간, 그리드 {best_grid_count}개 (점수: {best_score:.3f})")
            
            return best_period, best_grid_count
            
        except Exception as e:
            print(f"최적 기간 계산 오류: {e}")
            return 7, 20
    
    def force_optimization_for_all_coins(self):
        """모든 코인에 대해 강제로 최적화 실행"""
        tickers = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP']
        print("🚀 전체 코인 자동 최적화 강제 실행 시작...")
        
        # 최적화 결과를 저장할 딕셔너리
        optimization_results = {}
        
        for ticker in tickers:
            try:
                optimal_period, optimal_grid = self.find_optimal_period_and_grid(ticker)
                coin_name = get_korean_coin_name(ticker)
                print(f"✅ {coin_name}: {optimal_period}일/{optimal_grid}그리드")
                
                # 결과 저장
                optimization_results[ticker] = {
                    'period': optimal_period,
                    'grid_count': optimal_grid
                }
                
                # config에도 업데이트 (차트 제목 반영용)
                if 'coin_specific_grids' not in config:
                    config['coin_specific_grids'] = {}
                if ticker not in config['coin_specific_grids']:
                    config['coin_specific_grids'][ticker] = {}
                    
                config['coin_specific_grids'][ticker]['price_range_days'] = optimal_period
                config['coin_specific_grids'][ticker]['grid_count'] = optimal_grid
                
            except Exception as e:
                print(f"❌ {ticker} 최적화 실패: {e}")
        
        print("🚀 전체 코인 자동 최적화 완료!")
        
        # 설정 저장
        save_config(config)
        
        return optimization_results
    
    def _simulate_grid_performance(self, ticker, period, grid_count, high_price, low_price):
        """그리드 성능 시뮬레이션 (간단한 백테스팅)"""
        try:
            # 가격 변화 패턴 분석
            price_range = high_price - low_price
            grid_gap = price_range / grid_count
            
            # 변동성 대비 그리드 간격의 효율성
            avg_price = (high_price + low_price) / 2
            relative_gap = grid_gap / avg_price
            
            # 이상적인 그리드 간격은 평균 가격의 1-3%
            if 0.01 <= relative_gap <= 0.03:
                gap_score = 1.0
            elif relative_gap < 0.005:
                gap_score = 0.3  # 너무 조밀
            elif relative_gap > 0.05:
                gap_score = 0.4  # 너무 성김
            else:
                gap_score = 0.7
                
            # 그리드 개수의 적절성 (15-35개가 이상적)
            if 15 <= grid_count <= 35:
                count_score = 1.0
            else:
                count_score = max(0.3, 1 - abs(grid_count - 25) * 0.02)
            
            # 종합 백테스트 점수
            simulation_score = (gap_score * 0.6 + count_score * 0.4)
            
            return simulation_score
            
        except Exception as e:
            return 0.5  # 중간 점수
    
    def adjust_grid_for_market_condition(self, ticker, base_grid_count, market_data):
        """시장 상황에 따른 그리드 수 동적 조정"""
        try:
            profile = self.get_coin_profile(ticker)
            
            # 시장 데이터에서 지표 추출
            volatility = market_data.get('volatility', 0)
            trend_strength = market_data.get('trend_strength', 0)
            volume_ratio = market_data.get('volume_ratio', 1.0)
            
            adjustment_factor = 1.0
            
            # 1. 변동성 반영
            if volatility > 0.05:  # 5% 이상 변동성
                adjustment_factor *= (1 + volatility * profile['volatility_factor'])
            
            # 2. 트렌드 강도 반영
            if trend_strength > 0.03:  # 강한 트렌드
                adjustment_factor *= (1 + trend_strength * profile['trend_sensitivity'])
            
            # 3. 거래량 반영
            if volume_ratio > 1.5:  # 평소보다 1.5배 이상
                adjustment_factor *= 1.1
            elif volume_ratio < 0.7:  # 평소보다 30% 이하
                adjustment_factor *= 0.9
            
            adjusted_grids = int(base_grid_count * adjustment_factor)
            
            # 범위 제한
            coin_config = config.get('coin_specific_grids', {}).get(ticker, {})
            min_grids = coin_config.get('min_grid_count', 5)
            max_grids = coin_config.get('max_grid_count', 100)
            
            return max(min_grids, min(max_grids, adjusted_grids))
            
        except Exception as e:
            print(f"시장 조건 그리드 조정 오류 ({ticker}): {e}")
            return base_grid_count
    
    def get_real_time_market_data(self, ticker):
        """실시간 시장 데이터 수집 및 분석"""
        try:
            # 1시간 봉 데이터 24개 가져오기
            df = pyupbit.get_ohlcv(ticker, interval='minute60', count=24)
            if df is None or len(df) < 10:
                return {'volatility': 0, 'trend_strength': 0, 'volume_ratio': 1.0}
            
            # 변동성 계산 (24시간 기준)
            price_changes = df['close'].pct_change().abs()
            volatility = price_changes.std()
            
            # 트렌드 강도 계산 (최근 12시간 vs 이전 12시간)
            recent_avg = df['close'][-12:].mean()
            prev_avg = df['close'][-24:-12].mean()
            trend_strength = abs((recent_avg - prev_avg) / prev_avg)
            
            # 거래량 비율 (최근 6시간 vs 평균)
            recent_volume = df['volume'][-6:].mean()
            avg_volume = df['volume'].mean()
            volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
            
            return {
                'volatility': volatility,
                'trend_strength': trend_strength,
                'volume_ratio': volume_ratio
            }
            
        except Exception as e:
            print(f"실시간 시장 데이터 수집 오류 ({ticker}): {e}")
            return {'volatility': 0, 'trend_strength': 0, 'volume_ratio': 1.0}

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
            "hourly_performance": [],
            "volatility_score": 0.0,
            "trend_strength": 0.0,
            "portfolio_risk": 0.0
        }
    
    def get_risk_settings(self, risk_mode):
        """리스크 모드에 따른 설정 반환"""
        return self.risk_profiles.get(risk_mode, self.risk_profiles["안정적"])
    
    def analyze_performance(self, trades_data):
        """고급 거래 실적 분석"""
        if not trades_data:
            return {"status": "insufficient_data"}
        
        # 최근 24시간 거래 분석
        recent_trades = [t for t in trades_data if self._is_recent_trade(t, 24)]
        
        if len(recent_trades) < 3:  # 최소 요구 거래 수 감소
            return {"status": "insufficient_recent_data"}
        
        win_rate = len([t for t in recent_trades if t.get('profit', 0) > 0]) / len(recent_trades)
        avg_profit = sum(t.get('profit', 0) for t in recent_trades) / len(recent_trades)
        total_profit = sum(t.get('profit', 0) for t in recent_trades)
        
        # 시장 변동성 분석
        volatility_score = self._calculate_market_volatility()
        trend_strength = self._calculate_trend_strength()
        drawdown_ratio = self._calculate_current_drawdown()
        
        return {
            "status": "success",
            "win_rate": win_rate,
            "avg_profit": avg_profit,
            "total_profit": total_profit,
            "trade_count": len(recent_trades),
            "volatility_score": volatility_score,
            "trend_strength": trend_strength,
            "drawdown_ratio": drawdown_ratio,
            "recommendation": self._get_advanced_recommendation(win_rate, avg_profit, volatility_score, trend_strength, drawdown_ratio)
        }
    
    def _is_recent_trade(self, trade, hours):
        """최근 거래인지 확인"""
        try:
            from datetime import datetime, timedelta
            trade_time = datetime.strptime(trade.get('time', ''), '%Y-%m-%d %H:%M:%S')
            return datetime.now() - trade_time < timedelta(hours=hours)
        except:
            return False
    
    def _calculate_market_volatility(self):
        """시장 변동성 계산"""
        try:
            tickers = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP']
            volatilities = []
            
            for ticker in tickers:
                df = pyupbit.get_ohlcv(ticker, interval='minute60', count=24)
                if df is not None and len(df) > 1:
                    price_changes = df['close'].pct_change().abs()
                    volatility = price_changes.std() * 100
                    volatilities.append(volatility)
            
            return sum(volatilities) / len(volatilities) if volatilities else 0.0
        except:
            return 0.0
    
    def _calculate_trend_strength(self):
        """트렌드 강도 계산"""
        try:
            tickers = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP']
            trend_scores = []
            
            for ticker in tickers:
                df = pyupbit.get_ohlcv(ticker, interval='minute60', count=12)
                if df is not None and len(df) > 6:
                    recent_change = (df['close'].iloc[-1] - df['close'].iloc[-6]) / df['close'].iloc[-6]
                    trend_scores.append(abs(recent_change))
            
            return sum(trend_scores) / len(trend_scores) if trend_scores else 0.0
        except:
            return 0.0
    
    def _calculate_current_drawdown(self):
        """현재 드로다운 비율 계산"""
        try:
            total_unrealized_loss = 0
            total_investment_value = 0
            
            for ticker in ['KRW-BTC', 'KRW-ETH', 'KRW-XRP']:
                positions = load_trading_state(ticker, demo_mode=True)
                current_price = pyupbit.get_current_price(ticker)
                
                if positions and current_price:
                    for pos in positions:
                        buy_price = pos.get('buy_price', 0)
                        quantity = pos.get('quantity', 0)
                        
                        current_value = quantity * current_price
                        buy_value = quantity * buy_price
                        
                        total_investment_value += buy_value
                        if current_value < buy_value:
                            total_unrealized_loss += (buy_value - current_value)
            
            return total_unrealized_loss / total_investment_value if total_investment_value > 0 else 0.0
        except:
            return 0.0
    
    def _get_advanced_recommendation(self, win_rate, avg_profit, volatility, trend_strength, drawdown):
        """고급 다요소 기반 추천 시스템"""
        score = 0
        
        # 승률 가중치 (40%)
        if win_rate > 0.7:
            score += 40
        elif win_rate > 0.5:
            score += 20
        elif win_rate < 0.3:
            score -= 30
        
        # 평균 수익 가중치 (30%)
        if avg_profit > 2000:
            score += 30
        elif avg_profit > 500:
            score += 15
        elif avg_profit < -1000:
            score -= 25
        
        # 변동성 고려 (15%)
        if volatility > 3.0:  # 고변동성
            score -= 15
        elif volatility < 1.0:  # 저변동성
            score += 10
        
        # 드로다운 리스크 (15%)
        if drawdown > 0.1:  # 10% 이상 드로다운
            score -= 20
        elif drawdown > 0.05:  # 5% 이상 드로다운
            score -= 10
        
        # 최종 추천 결정
        if score >= 30:
            return "increase_aggression_strong"
        elif score >= 10:
            return "increase_aggression_mild"
        elif score >= -10:
            return "maintain"
        elif score >= -30:
            return "decrease_aggression_mild"
        else:
            return "decrease_aggression_strong"
    
    def optimize_parameters(self, current_config, performance_analysis):
        """고급 다요소 기반 파라미터 자동 최적화"""
        if performance_analysis["status"] != "success":
            return current_config
        
        optimized_config = current_config.copy()
        recommendation = performance_analysis["recommendation"]
        current_risk = current_config.get("risk_mode", "안정적")
        
        # 리스크 모드 자동 조정 (더 세밀한 단계별 조정)
        risk_modes = ["보수적", "안정적", "공격적", "극공격적"]
        current_index = risk_modes.index(current_risk) if current_risk in risk_modes else 1
        
        if "increase_aggression" in recommendation:
            if "strong" in recommendation and current_index < 3:
                # 강한 상향 신호: 2단계 상향 (최대 극공격적까지)
                new_index = min(current_index + 2, 3)
                new_risk_mode = risk_modes[new_index]
                optimized_config["risk_mode"] = new_risk_mode
                print(f"실적 매우 우수 - 리스크 모드 강한 상향: {current_risk} → {new_risk_mode}")
            elif "mild" in recommendation and current_index < 3:
                # 온화한 상햦 신호: 1단계 상향
                new_risk_mode = risk_modes[current_index + 1]
                optimized_config["risk_mode"] = new_risk_mode
                print(f"실적 우수 - 리스크 모드 온화한 상향: {current_risk} → {new_risk_mode}")
        elif "decrease_aggression" in recommendation:
            if "strong" in recommendation and current_index > 0:
                # 강한 하향 신호: 2단계 하향 (최소 보수적까지)
                new_index = max(current_index - 2, 0)
                new_risk_mode = risk_modes[new_index]
                optimized_config["risk_mode"] = new_risk_mode
                print(f"실적 매우 부진 - 리스크 모드 강한 하향: {current_risk} → {new_risk_mode}")
            elif "mild" in recommendation and current_index > 0:
                # 온화한 하향 신호: 1단계 하향
                new_risk_mode = risk_modes[current_index - 1]
                optimized_config["risk_mode"] = new_risk_mode
                print(f"실적 부진 - 리스크 모드 온화한 하향: {current_risk} → {new_risk_mode}")
        
        # 리스크 프로필에 따른 설정 적용
        risk_settings = self.get_risk_settings(optimized_config["risk_mode"])
        optimized_config.update({
            "max_grid_count": risk_settings["max_grid_count"],
            "panic_threshold": risk_settings["panic_threshold"],
            "stop_loss_threshold": risk_settings["stop_loss_threshold"],
            "trailing_stop_percent": risk_settings["trailing_stop_percent"],
            "grid_confirmation_buffer": risk_settings["grid_confirmation_buffer"]
        })
        
        # 동적 파라미터 조정
        volatility = performance_analysis.get("volatility_score", 0)
        drawdown = performance_analysis.get("drawdown_ratio", 0)
        win_rate = performance_analysis["win_rate"]
        
        # 변동성에 따른 그리드 버퍼 조정
        if volatility > 3.0:  # 고변동성
            optimized_config["grid_confirmation_buffer"] *= 1.3
        elif volatility < 1.0:  # 저변동성
            optimized_config["grid_confirmation_buffer"] *= 0.8
        
        # 드로다운에 따른 리스크 조정
        if drawdown > 0.1:  # 10% 이상 드로다운
            optimized_config["stop_loss_threshold"] = risk_settings["stop_loss_threshold"] * 0.7  # 손절 기준 강화
            optimized_config["trailing_stop_percent"] = risk_settings["trailing_stop_percent"] * 1.5  # 트레일링 스톱 강화
        
        # 승률에 따른 세밀 조정
        if win_rate > 0.8:  # 매우 높은 승률
            optimized_config["grid_confirmation_buffer"] *= 0.7  # 버퍼 강한 감소
        elif win_rate < 0.3:  # 매우 낮은 승률
            optimized_config["grid_confirmation_buffer"] *= 1.8  # 버퍼 강한 증가
        
        # 코인별 동적 그리드 수 조정 (시장 상황에 따라)
        trend_strength = performance_analysis.get("trend_strength", 0)
        
        # 각 코인별로 다른 그리드 수 적용
        coin_grids = {}
        for ticker in ['KRW-BTC', 'KRW-ETH', 'KRW-XRP']:
            coin_config = config.get('coin_specific_grids', {}).get(ticker, {})
            base_grids = coin_config.get('grid_count', 20)
            
            # 시장 상황 반영
            market_data = {
                'volatility': volatility,
                'trend_strength': trend_strength,
                'volume_ratio': 1.0  # 기본값
            }
            
            adjusted_grids = coin_grid_manager.adjust_grid_for_market_condition(ticker, base_grids, market_data)
            coin_grids[ticker] = adjusted_grids
            
            # 코인별 설정 업데이트
            if ticker not in optimized_config.get('coin_specific_grids', {}):
                if 'coin_specific_grids' not in optimized_config:
                    optimized_config['coin_specific_grids'] = {}
                optimized_config['coin_specific_grids'][ticker] = coin_config.copy()
            
            optimized_config['coin_specific_grids'][ticker]['grid_count'] = adjusted_grids
        
        # 전체 최대 그리드 수도 업데이트 (최대값 사용)
        max_coin_grids = max(coin_grids.values()) if coin_grids else risk_settings["max_grid_count"]
        optimized_config["max_grid_count"] = max_coin_grids
        
        print(f"코인별 그리드 수 업데이트: BTC={coin_grids.get('KRW-BTC', 20)}, ETH={coin_grids.get('KRW-ETH', 25)}, XRP={coin_grids.get('KRW-XRP', 30)}")
        
        optimized_config["last_optimization"] = datetime.now().isoformat()
        # 동적 그리드 수 조정 로직 추가
        optimized_config = self.dynamic_grid_adjustment(optimized_config, performance_analysis)
        
        return optimized_config
    
    def dynamic_grid_adjustment(self, config, performance_analysis):
        """코인별 동적 그리드 수 조정"""
        try:
            volatility = performance_analysis.get('volatility_score', 0)
            trend_strength = performance_analysis.get('trend_strength', 0)
            win_rate = performance_analysis.get('win_rate', 0)
            
            # 코인별 그리드 수 동적 조정
            coin_grids_updated = {}
            
            for ticker in ['KRW-BTC', 'KRW-ETH', 'KRW-XRP']:
                coin_config = config.get('coin_specific_grids', {}).get(ticker, {})
                base_grid_count = coin_config.get('grid_count', 20)
                
                # 시장 데이터 준비
                market_data = {
                    'volatility': volatility,
                    'trend_strength': trend_strength,
                    'volume_ratio': 1.0,
                    'win_rate': win_rate
                }
                
                # 코인별 조정
                adjusted_grids = coin_grid_manager.adjust_grid_for_market_condition(ticker, base_grid_count, market_data)
                coin_grids_updated[ticker] = adjusted_grids
                
                # 설정 업데이트
                if 'coin_specific_grids' not in config:
                    config['coin_specific_grids'] = {}
                if ticker not in config['coin_specific_grids']:
                    config['coin_specific_grids'][ticker] = coin_config.copy()
                
                config['coin_specific_grids'][ticker]['grid_count'] = adjusted_grids
                
                if adjusted_grids != base_grid_count:
                    korean_name = get_korean_coin_name(ticker)
                    print(f"{korean_name} 그리드 수 동적 조정: {base_grid_count} → {adjusted_grids}")
            
            # 전체 최대 그리드 수 업데이트
            max_grids = max(coin_grids_updated.values()) if coin_grids_updated else config.get('max_grid_count', 20)
            config['max_grid_count'] = max_grids
            
            return config
            
        except Exception as e:
            print(f"코인별 동적 그리드 조정 오류: {e}")
            return config

# 글로벌 시스템 인스턴스
auto_trading_system = AutoTradingSystem()
coin_grid_manager = CoinSpecificGridManager()

# 자동 최적화 스케줄러
class AutoOptimizationScheduler:
    def __init__(self):
        self.last_optimization = None
        self.optimization_thread = None
        self.stop_optimization = False
        
    def start_auto_optimization(self, update_callback):
        """자동 최적화 스레드 시작"""
        if self.optimization_thread and self.optimization_thread.is_alive():
            print("⚠️ 자동 최적화 스레드가 이미 실행 중입니다")
            return
            
        print("🎯 자동 최적화 스레드 시작 중...")
        self.stop_optimization = False
        self.optimization_thread = threading.Thread(
            target=self._optimization_worker, 
            args=(update_callback,), 
            daemon=True
        )
        self.optimization_thread.start()
        print("✅ 자동 최적화 스레드 시작 완료")
        
    def stop_auto_optimization(self):
        """자동 최적화 스레드 중지"""
        self.stop_optimization = True
        if self.optimization_thread:
            self.optimization_thread.join(timeout=5)
    
    def _optimization_worker(self, update_callback):
        """자동 최적화 작업자"""
        print(f"🤖 자동 최적화 워커 시작 - 간격: {config.get('auto_update_interval', 60)}분")
        
        while not self.stop_optimization:
            try:
                # 설정에서 간격 확인
                interval_minutes = config.get('auto_update_interval', 60)
                print(f"⏰ 다음 최적화까지 {interval_minutes}분 대기 시작...")
                
                # 간격만큼 대기 (10초씩 체크하여 중단 신호 확인)
                for i in range(int(interval_minutes * 6)):  # 60분 = 360 * 10초
                    if self.stop_optimization:
                        print("🛑 최적화 워커 중단 신호 수신")
                        return
                    time.sleep(10)
                    
                    # 매 5분마다 상태 출력 (30회 = 5분)
                    if (i + 1) % 30 == 0:
                        remaining_minutes = (interval_minutes * 6 - i - 1) / 6
                        print(f"⏱️ 최적화까지 약 {remaining_minutes:.1f}분 남음")
                
                print(f"🔍 자동 최적화 실행 조건 체크...")
                print(f"  - 자동 모드: {config.get('auto_trading_mode', False)}")
                print(f"  - 자동 최적화: {config.get('auto_optimization', True)}")
                
                # 자동 거래 모드가 활성화된 경우에만 최적화 실행
                if config.get('auto_trading_mode', False) and config.get('auto_optimization', True):
                    print("✅ 조건 만족 - 자동 최적화 실행")
                    self._perform_optimization(update_callback)
                else:
                    print("❌ 조건 불만족 - 최적화 건너뜀")
                    
            except Exception as e:
                print(f"❗ 자동 최적화 오류: {e}")
                time.sleep(300)  # 오류 발생시 5분 대기
                
        print("🔚 자동 최적화 워커 종료")
    
    def _perform_optimization(self, update_callback):
        """실제 최적화 수행"""
        try:
            print("🚀 자동 최적화 시작...")
            
            # 코인별 그리드 최적화 실행
            results = coin_grid_manager.force_optimization_for_all_coins()
            
            if results:
                print("✅ 자동 최적화 완료")
                
                # 설정 업데이트 (최적화된 값들을 config에 반영)
                for ticker, result in results.items():
                    optimal_period, optimal_grid = result
                    coin_key = ticker.replace('KRW-', '').lower()
                    
                    # 코인별 설정 업데이트
                    if 'coin_specific_grids' not in config:
                        config['coin_specific_grids'] = {}
                    if coin_key not in config['coin_specific_grids']:
                        config['coin_specific_grids'][coin_key] = {}
                        
                    config['coin_specific_grids'][coin_key]['period'] = optimal_period
                    config['coin_specific_grids'][coin_key]['grid_count'] = optimal_grid
                
                # 마지막 최적화 시간 기록
                config['last_optimization'] = datetime.now().isoformat()
                save_config(config)
                
                # UI 업데이트 콜백 호출
                if update_callback:
                    update_callback(config)
                
                print(f"📊 최적화 결과: {len(results)}개 코인 업데이트 완료")
            else:
                print("❌ 최적화 결과 없음")
                    
            # 수익권 포지션 자동 매도 처리 (활성 거래가 있는 경우)
            if hasattr(self, 'active_tickers'):
                for ticker in getattr(self, 'active_tickers', []):
                    try:
                        sold_qty, profit = check_and_sell_profitable_positions(ticker, demo_mode=True)
                        if sold_qty > 0:
                            korean_name = get_korean_coin_name(ticker)
                            auto_sell_reason = "수익 실현 조건 만족으로 자동 매도"
                            auto_sell_details = {
                                "coin_name": korean_name,
                                "sold_quantity": f"{sold_qty:.6f}개",
                                "profit": f"{profit:,.0f}원",
                                "trigger": "시간 기반 수익 실현 체크"
                            }
                            log_trade("AUTO_SYSTEM", "자동매도", f"{korean_name}: {sold_qty:.6f}개 매도, 수익: {profit:,.0f}원", auto_sell_reason, auto_sell_details)
                            speak_async(f"{korean_name} 자동 수익 실현")
                    except Exception as e:
                        print(f"자동 매도 처리 오류 ({ticker}): {e}")
            else:
                print("❌ 최적화 결과 없음")
                
                # 실패해도 수익권 포지션 자동 매도는 수행
                if hasattr(self, 'active_tickers'):
                    for ticker in getattr(self, 'active_tickers', []):
                        try:
                            sold_qty, profit = check_and_sell_profitable_positions(ticker, demo_mode=True)
                            if sold_qty > 0:
                                korean_name = get_korean_coin_name(ticker)
                                backup_sell_reason = "최적화 실패 시 백업 수익 실현"
                                backup_sell_details = {
                                    "coin_name": korean_name,
                                    "sold_quantity": f"{sold_qty:.6f}개",
                                    "profit": f"{profit:,.0f}원",
                                    "trigger": "백업 수익 실현 체크"
                                }
                                log_trade("AUTO_SYSTEM", "자동매도", f"{korean_name}: {sold_qty:.6f}개 매도, 수익: {profit:,.0f}원", backup_sell_reason, backup_sell_details)
                        except Exception as e:
                            print(f"자동 매도 처리 오류 ({ticker}): {e}")
                
            self.last_optimization = datetime.now()
            
        except Exception as e:
            print(f"최적화 수행 중 오류: {e}")
            # 오류 발생시에도 기본적인 수익 실현 기능은 수행 (중복 방지)
            try:
                current_investment = float(config.get('total_investment', 100000000))
                updated_investment, total_profit = update_investment_with_profits(current_investment, force_update=False)
                if total_profit > 0 and updated_investment != current_investment:
                    config['total_investment'] = str(int(updated_investment))
                    save_config(config)
                    reinvest_reason = "오류 발생 시 비상 수익 재투자"
                    reinvest_details = {
                        "previous_investment": f"{current_investment:,.0f}원",
                        "profit": f"{total_profit:,.0f}원",
                        "new_investment": f"{updated_investment:,.0f}원",
                        "trigger": "시스템 오류 시 안전 조치"
                    }
                    log_trade("AUTO_SYSTEM", "비상수익재투자", f"수익: +{total_profit:,.0f}원", reinvest_reason, reinvest_details)
            except:
                pass
    
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

def perform_manual_optimization():
    """수동 최적화 실행"""
    def optimization_task():
        try:
            messagebox.showinfo("최적화 시작", "수동 최적화를 시작합니다. 잠시 기다려주세요...")
            
            # 거래 로그 데이터 로드
            trades_data = auto_scheduler._load_recent_trades()
            if len(trades_data) < 10:
                messagebox.showwarning("최적화 실패", "최적화를 위한 충분한 거래 데이터가 없습니다. (최소 10개 필요)")
                return
            
            # 성능 분석
            performance = auto_trading_system.analyze_performance(trades_data)
            
            if performance["status"] == "success":
                # 파라미터 최적화
                old_config = dict(config)  # 이전 설정 복사
                optimized_config = auto_trading_system.optimize_parameters(config, performance)
                
                # 설정 업데이트
                config.update(optimized_config)
                save_config(config)
                
                # 최적화 시간 업데이트
                config['last_optimization'] = datetime.now().isoformat()
                save_config(config)
                
                # GUI 업데이트는 메인 스레드에서 처리됨
                
                # 최적화 결과 로그
                auto_scheduler._log_optimization_result(performance, optimized_config)
                
                # 결과 메시지
                win_rate = performance.get('win_rate', 0) * 100
                total_profit = performance.get('total_profit', 0)
                new_risk_mode = config.get('risk_mode', '알 수 없음')
                
                result_msg = f"✅ 수동 최적화 완료!\n\n"
                result_msg += f"🎯 리스크 모드: {new_risk_mode}\n"
                result_msg += f"📊 승률: {win_rate:.1f}%\n"
                result_msg += f"💰 수익: {total_profit:,.0f}원\n"
                result_msg += f"🕐 최적화 시간: {datetime.now().strftime('%H:%M')}"
                
                messagebox.showinfo("최적화 완료", result_msg)
                
                # 카카오 알림
                if config.get('kakao_enabled', True):
                    auto_scheduler._send_optimization_notification(performance, optimized_config)
                    
            else:
                messagebox.showwarning("최적화 실패", f"최적화를 수행할 수 없습니다:\n{performance.get('message', '알 수 없는 오류')}")
                
        except Exception as e:
            messagebox.showerror("최적화 오류", f"수동 최적화 중 오류가 발생했습니다:\n{e}")
    
    # 별도 스레드에서 실행 (GUI 블록 방지)
    threading.Thread(target=optimization_task, daemon=True).start()

# 고도화된 기술적 분석 시스템
class AdvancedTechnicalAnalyzer:
    """보조지표를 활용한 고도화된 기술적 분석 시스템"""
    
    def __init__(self):
        self.indicators_cache = {}
        self.signal_history = {}
    
    def calculate_rsi(self, prices, period=14):
        """RSI 계산"""
        if len(prices) < period + 1:
            return None
            
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gains = pd.Series(gains).rolling(window=period).mean()
        avg_losses = pd.Series(losses).rolling(window=period).mean()
        
        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if len(rsi) > 0 else None
    
    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        """MACD 계산"""
        if len(prices) < slow + signal:
            return None, None, None
            
        prices_series = pd.Series(prices)
        ema_fast = prices_series.ewm(span=fast).mean()
        ema_slow = prices_series.ewm(span=slow).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        
        return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]
    
    def calculate_bollinger_bands(self, prices, period=20, std_dev=2):
        """볼린저 밴드 계산"""
        if len(prices) < period:
            return None, None, None
            
        prices_series = pd.Series(prices)
        sma = prices_series.rolling(window=period).mean()
        std = prices_series.rolling(window=period).std()
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return upper_band.iloc[-1], sma.iloc[-1], lower_band.iloc[-1]
    
    def calculate_stochastic(self, highs, lows, closes, k_period=14, d_period=3):
        """스토캐스틱 계산"""
        if len(closes) < k_period:
            return None, None
            
        lowest_lows = pd.Series(lows).rolling(window=k_period).min()
        highest_highs = pd.Series(highs).rolling(window=k_period).max()
        
        k_percent = 100 * ((pd.Series(closes) - lowest_lows) / (highest_highs - lowest_lows))
        d_percent = k_percent.rolling(window=d_period).mean()
        
        return k_percent.iloc[-1], d_percent.iloc[-1]
    
    def calculate_williams_r(self, highs, lows, closes, period=14):
        """윌리엄스 %R 계산"""
        if len(closes) < period:
            return None
            
        highest_highs = pd.Series(highs).rolling(window=period).max()
        lowest_lows = pd.Series(lows).rolling(window=period).min()
        
        williams_r = -100 * ((highest_highs - pd.Series(closes)) / (highest_highs - lowest_lows))
        return williams_r.iloc[-1]
    
    def calculate_momentum(self, prices, period=10):
        """모멘텀 계산"""
        if len(prices) < period + 1:
            return None
        return (prices[-1] / prices[-period-1] - 1) * 100
    
    def get_comprehensive_signals(self, ticker, current_price, market_data=None):
        """종합적인 매수/매도 신호 분석"""
        try:
            # 시장 데이터 가져오기
            if market_data is None:
                df = pyupbit.get_ohlcv(ticker, interval="minute60", count=100)
                if df is None or len(df) < 50:
                    return {'signal': 'hold', 'strength': 0, 'confidence': 0}
            else:
                df = market_data
            
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            volumes = df['volume'].values
            
            signals = {}
            
            # 1. RSI 분석
            rsi = self.calculate_rsi(closes)
            if rsi is not None:
                if rsi < 30:
                    signals['rsi'] = {'signal': 'strong_buy', 'value': rsi, 'weight': 0.25}
                elif rsi < 45:
                    signals['rsi'] = {'signal': 'buy', 'value': rsi, 'weight': 0.15}
                elif rsi > 70:
                    signals['rsi'] = {'signal': 'strong_sell', 'value': rsi, 'weight': 0.25}
                elif rsi > 55:
                    signals['rsi'] = {'signal': 'sell', 'value': rsi, 'weight': 0.15}
                else:
                    signals['rsi'] = {'signal': 'hold', 'value': rsi, 'weight': 0.05}
            
            # 2. MACD 분석
            macd, signal_line, histogram = self.calculate_macd(closes)
            if macd is not None and signal_line is not None:
                if histogram > 0 and macd > signal_line:
                    signals['macd'] = {'signal': 'buy', 'weight': 0.2}
                elif histogram < 0 and macd < signal_line:
                    signals['macd'] = {'signal': 'sell', 'weight': 0.2}
                else:
                    signals['macd'] = {'signal': 'hold', 'weight': 0.1}
            
            # 3. 볼린저 밴드 분석
            bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(closes)
            if bb_upper is not None and bb_lower is not None:
                bb_position = (current_price - bb_lower) / (bb_upper - bb_lower)
                if bb_position < 0.1:
                    signals['bollinger'] = {'signal': 'strong_buy', 'position': bb_position, 'weight': 0.2}
                elif bb_position < 0.3:
                    signals['bollinger'] = {'signal': 'buy', 'position': bb_position, 'weight': 0.15}
                elif bb_position > 0.9:
                    signals['bollinger'] = {'signal': 'strong_sell', 'position': bb_position, 'weight': 0.2}
                elif bb_position > 0.7:
                    signals['bollinger'] = {'signal': 'sell', 'position': bb_position, 'weight': 0.15}
                else:
                    signals['bollinger'] = {'signal': 'hold', 'position': bb_position, 'weight': 0.05}
            
            # 4. 스토캐스틱 분석
            k_percent, d_percent = self.calculate_stochastic(highs, lows, closes)
            if k_percent is not None and d_percent is not None:
                if k_percent < 20 and d_percent < 20:
                    signals['stochastic'] = {'signal': 'strong_buy', 'k': k_percent, 'd': d_percent, 'weight': 0.15}
                elif k_percent < 40:
                    signals['stochastic'] = {'signal': 'buy', 'k': k_percent, 'd': d_percent, 'weight': 0.1}
                elif k_percent > 80 and d_percent > 80:
                    signals['stochastic'] = {'signal': 'strong_sell', 'k': k_percent, 'd': d_percent, 'weight': 0.15}
                elif k_percent > 60:
                    signals['stochastic'] = {'signal': 'sell', 'k': k_percent, 'd': d_percent, 'weight': 0.1}
                else:
                    signals['stochastic'] = {'signal': 'hold', 'k': k_percent, 'd': d_percent, 'weight': 0.05}
            
            # 5. 거래량 분석
            recent_volume_avg = np.mean(volumes[-10:])
            current_volume = volumes[-1]
            volume_ratio = current_volume / recent_volume_avg if recent_volume_avg > 0 else 1
            
            if volume_ratio > 2.0:  # 거래량 급증
                signals['volume'] = {'signal': 'volume_surge', 'ratio': volume_ratio, 'weight': 0.1}
            elif volume_ratio > 1.5:
                signals['volume'] = {'signal': 'volume_high', 'ratio': volume_ratio, 'weight': 0.05}
            else:
                signals['volume'] = {'signal': 'volume_normal', 'ratio': volume_ratio, 'weight': 0.02}
            
            # 6. 종합 신호 계산
            buy_score = 0
            sell_score = 0
            total_weight = 0
            
            for indicator, data in signals.items():
                weight = data['weight']
                signal = data['signal']
                
                if 'strong_buy' in signal:
                    buy_score += weight * 2
                elif 'buy' in signal:
                    buy_score += weight * 1
                elif 'strong_sell' in signal:
                    sell_score += weight * 2
                elif 'sell' in signal:
                    sell_score += weight * 1
                
                total_weight += weight
            
            # 신호 강도 및 신뢰도 계산
            net_score = buy_score - sell_score
            strength = abs(net_score) / total_weight if total_weight > 0 else 0
            confidence = min(100, strength * 100)
            
            # 최종 신호 결정
            if net_score > 0.3:
                final_signal = 'strong_buy' if net_score > 0.5 else 'buy'
            elif net_score < -0.3:
                final_signal = 'strong_sell' if net_score < -0.5 else 'sell'
            else:
                final_signal = 'hold'
            
            return {
                'signal': final_signal,
                'strength': strength,
                'confidence': confidence,
                'buy_score': buy_score,
                'sell_score': sell_score,
                'indicators': signals,
                'net_score': net_score
            }
            
        except Exception as e:
            print(f"기술적 분석 오류 ({ticker}): {e}")
            return {'signal': 'hold', 'strength': 0, 'confidence': 0}
    
    def should_override_grid_signal(self, ticker, grid_signal, current_price, market_data=None):
        """그리드 신호를 기술적 분석으로 Override할지 결정"""
        technical_analysis = self.get_comprehensive_signals(ticker, current_price, market_data)
        
        # 높은 신뢰도의 반대 신호가 있을 때만 Override
        if technical_analysis['confidence'] < 70:
            return False, technical_analysis
        
        # 그리드가 매수 신호인데 기술적 분석이 강한 매도 신호
        if grid_signal == 'buy' and technical_analysis['signal'] in ['strong_sell', 'sell']:
            return True, technical_analysis
        
        # 그리드가 매도 신호인데 기술적 분석이 강한 매수 신호  
        if grid_signal == 'sell' and technical_analysis['signal'] in ['strong_buy', 'buy']:
            return True, technical_analysis
        
        return False, technical_analysis

# 글로벌 기술적 분석기 인스턴스
technical_analyzer = AdvancedTechnicalAnalyzer()

# 고도화된 리스크 관리 시스템
class AdvancedRiskManager:
    """고도화된 리스크 관리 및 손절 시스템"""
    
    def __init__(self):
        self.position_risks = {}
        self.market_conditions = {}
        self.emergency_stop = False
    
    def calculate_position_risk(self, ticker, position, current_price):
        """개별 포지션 리스크 계산"""
        buy_price = position.get('actual_buy_price', position.get('buy_price', 0))
        if buy_price <= 0:
            return {'risk_level': 'unknown', 'loss_percent': 0}
        
        # 현재 손실률 계산 (음수: 손실, 양수: 수익)
        loss_percent = ((current_price - buy_price) / buy_price) * 100
        
        # 리스크 레벨 결정
        if loss_percent <= -15:  # 15% 이상 하락
            risk_level = 'extreme'
        elif loss_percent <= -10:  # 10% 이상 하락
            risk_level = 'high'
        elif loss_percent <= -5:   # 5% 이상 하락
            risk_level = 'medium'
        elif loss_percent <= -2:   # 2% 이상 하락
            risk_level = 'low'
        else:
            risk_level = 'safe'
        
        return {
            'risk_level': risk_level,
            'loss_percent': loss_percent,
            'should_stop_loss': loss_percent < config.get('stop_loss_threshold', -5.0)
        }
    
    def should_emergency_stop(self, ticker, current_price, positions):
        """긴급 정지 조건 확인"""
        if not positions:
            return False, "포지션 없음"
        
        total_loss = 0
        high_risk_positions = 0
        
        for position in positions:
            risk_info = self.calculate_position_risk(ticker, position, current_price)
            if risk_info['loss_percent'] < -10:  # 10% 이상 손실
                total_loss += abs(risk_info['loss_percent'])
                high_risk_positions += 1
        
        # 긴급 정지 조건:
        # 1. 평균 손실이 12% 이상
        # 2. 고위험 포지션이 전체의 50% 이상
        avg_loss = total_loss / len(positions) if positions else 0
        high_risk_ratio = high_risk_positions / len(positions) if positions else 0
        
        emergency_conditions = [
            (avg_loss > 12, f"평균 손실 {avg_loss:.1f}% 초과"),
            (high_risk_ratio > 0.5, f"고위험 포지션 {high_risk_ratio*100:.0f}% 초과")
        ]
        
        for condition, reason in emergency_conditions:
            if condition:
                return True, reason
        
        return False, "정상"
    
    def calculate_optimal_position_size(self, ticker, base_amount, technical_analysis):
        """기술적 분석 기반 최적 포지션 크기 계산"""
        confidence = technical_analysis.get('confidence', 50)
        signal_strength = technical_analysis.get('strength', 0.5)
        
        # 신뢰도와 신호 강도에 따른 포지션 크기 조정
        if confidence > 80 and signal_strength > 0.7:
            multiplier = 1.3  # 강한 신호일 때 30% 증가
        elif confidence > 60 and signal_strength > 0.5:
            multiplier = 1.1  # 보통 신호일 때 10% 증가
        elif confidence < 40 or signal_strength < 0.3:
            multiplier = 0.7  # 약한 신호일 때 30% 감소
        else:
            multiplier = 1.0  # 기본 크기
        
        # 리스크 모드에 따른 추가 조정
        risk_mode = config.get('risk_mode', '안정적')
        risk_multipliers = {
            '보수적': 0.8,
            '안정적': 1.0,
            '공격적': 1.2,
            '극공격적': 1.4
        }
        
        risk_multiplier = risk_multipliers.get(risk_mode, 1.0)
        final_amount = base_amount * multiplier * risk_multiplier
        
        return min(final_amount, base_amount * 1.5)  # 최대 150%까지만 허용
    
    def should_cut_loss(self, ticker, position, current_price, technical_analysis):
        """손절 여부 결정"""
        risk_info = self.calculate_position_risk(ticker, position, current_price)
        
        # 기본 손절 조건
        if risk_info['should_stop_loss']:
            return True, f"손절선 도달 (손실: {risk_info['loss_percent']:.1f}%)"
        
        # 기술적 분석 기반 손절
        signal = technical_analysis.get('signal', 'hold')
        confidence = technical_analysis.get('confidence', 0)
        
        # 강한 매도 신호 + 높은 신뢰도 + 손실 상황
        if (signal == 'strong_sell' and 
            confidence > 75 and 
            risk_info['loss_percent'] < -3):  # 3% 이상 손실
            return True, f"기술적 손절 ({signal}, 신뢰도: {confidence:.0f}%)"
        
        return False, "유지"
    
    def get_market_sentiment(self, ticker, current_price, recent_prices):
        """시장 심리 분석"""
        if len(recent_prices) < 10:
            return "insufficient_data"
        
        # 최근 10분봉의 변동성 계산
        volatility = np.std(recent_prices[-10:]) / np.mean(recent_prices[-10:])
        price_momentum = (recent_prices[-1] - recent_prices[-5]) / recent_prices[-5]
        
        if volatility > 0.05:  # 5% 이상 변동성
            if price_momentum > 0.02:
                return "bullish_volatile"  # 상승 변동성
            elif price_momentum < -0.02:
                return "bearish_volatile"  # 하락 변동성
            else:
                return "neutral_volatile"  # 중립 변동성
        else:
            if price_momentum > 0.01:
                return "bullish_stable"    # 안정적 상승
            elif price_momentum < -0.01:
                return "bearish_stable"    # 안정적 하락
            else:
                return "sideways"          # 횡보

# 글로벌 리스크 관리자 인스턴스
risk_manager = AdvancedRiskManager()

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
config = {}
stop_event = None

# 코인별 투자금 분배 시스템
class CoinAllocationSystem:
    def __init__(self):
        self.coin_profiles = {
            "KRW-BTC": {
                "volatility_weight": 0.6,    # 안정성 중심
                "min_allocation": 0.20,       # 최소 20% 분배
                "max_allocation": 0.50        # 최대 50% 분배
            },
            "KRW-ETH": {
                "volatility_weight": 0.8,    # 중간 안정성
                "min_allocation": 0.15,       # 최소 15% 분배
                "max_allocation": 0.45        # 최대 45% 분배
            },
            "KRW-XRP": {
                "volatility_weight": 1.0,    # 고수익 추구
                "min_allocation": 0.10,       # 최소 10% 분배
                "max_allocation": 0.40        # 최대 40% 분배
            }
        }
        self.allocation_cache = {}
        self.last_calculation_time = None
    
    def analyze_coin_performance(self, ticker, period='1h'):
        """코인별 성과 분석"""
        try:
            # 가격 데이터 수집
            df = pyupbit.get_ohlcv(ticker, interval='minute60', count=24)  # 최근 24시간
            if df is None or df.empty:
                return {'score': 0.5, 'volatility': 0.05, 'trend': 0}
            
            # 변동성 계산
            volatility = (df['high'] - df['low']).mean() / df['close'].mean()
            
            # 트렌드 강도 계산
            price_change = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0]
            
            # 거래량 분석
            volume_ratio = df['volume'].iloc[-6:].mean() / df['volume'].mean()  # 최근 6시간 대비
            
            # 종합 점수 계산 (0.0 ~ 1.0)
            trend_score = max(0, price_change + 0.5)  # 상승 트렌드에 가중치
            volatility_score = min(1.0, volatility * 10)  # 적절한 변동성에 가중치
            volume_score = min(1.0, volume_ratio)  # 거래량 증가에 가중치
            
            composite_score = (trend_score * 0.4 + volatility_score * 0.4 + volume_score * 0.2)
            
            return {
                'score': composite_score,
                'volatility': volatility,
                'trend': price_change,
                'volume_ratio': volume_ratio
            }
            
        except Exception as e:
            print(f"코인 성과 분석 오류 ({ticker}): {e}")
            return {'score': 0.5, 'volatility': 0.05, 'trend': 0}
    
    def calculate_grid_efficiency(self, ticker, grid_count, price_range):
        """그리드 효율성 계산"""
        try:
            profile = self.coin_profiles.get(ticker, {'volatility_weight': 0.7})
            
            # 가격 범위 대비 그리드 밀도
            if price_range > 0:
                grid_density = grid_count / price_range
            else:
                grid_density = 0.1
            
            # 최적 그리드 개수와의 차이 (적을수록 좋음)
            optimal_grids = 20 + int(profile['volatility_weight'] * 15)  # 20-35개 사이
            grid_deviation = abs(grid_count - optimal_grids) / optimal_grids
            
            # 효율성 점수 계산 (0.0 ~ 1.0)
            efficiency_score = max(0.1, 1.0 - grid_deviation)
            
            return efficiency_score
            
        except Exception as e:
            print(f"그리드 효율성 계산 오류 ({ticker}): {e}")
            return 0.5
    
    def calculate_optimal_allocation(self, total_investment, active_coins, grid_configs):
        """총 투자금을 코인별로 최적 분배"""
        try:
            current_time = datetime.now()
            # 5분마다 재계산
            if (self.last_calculation_time and 
                (current_time - self.last_calculation_time).total_seconds() < 300):
                return self.allocation_cache
            
            coin_scores = {}
            total_score = 0
            
            # 각 코인별 점수 계산
            for ticker in active_coins:
                if ticker not in self.coin_profiles:
                    continue
                
                # 성과 분석
                performance = self.analyze_coin_performance(ticker)
                
                # 그리드 설정 효율성
                grid_info = grid_configs.get(ticker, {})
                grid_count = grid_info.get('count', 20)
                price_range = grid_info.get('range', 100000)
                grid_efficiency = self.calculate_grid_efficiency(ticker, grid_count, price_range)
                
                # 코인 프로필 가중치
                profile = self.coin_profiles[ticker]
                volatility_factor = profile['volatility_weight']
                
                # 종합 점수 계산
                composite_score = (
                    performance['score'] * 0.5 +       # 성과 50%
                    grid_efficiency * 0.3 +            # 그리드 효율성 30%
                    volatility_factor * 0.2             # 코인 특성 20%
                )
                
                coin_scores[ticker] = composite_score
                total_score += composite_score
            
            # 분배 비율 계산
            allocations = {}
            remaining_investment = total_investment
            
            for ticker in active_coins:
                if ticker not in coin_scores:
                    continue
                
                profile = self.coin_profiles[ticker]
                
                if total_score > 0:
                    # 점수 기반 초기 분배
                    score_ratio = coin_scores[ticker] / total_score
                    initial_allocation = total_investment * score_ratio
                else:
                    # 동일 분배
                    initial_allocation = total_investment / len(active_coins)
                
                # 최소/최대 한도 적용
                min_amount = total_investment * profile['min_allocation']
                max_amount = total_investment * profile['max_allocation']
                
                final_allocation = max(min_amount, min(max_amount, initial_allocation))
                allocations[ticker] = final_allocation
                remaining_investment -= final_allocation
            
            # 남은 투자금 재분배 (비례 분배)
            if remaining_investment != 0 and allocations:
                current_total = sum(allocations.values())
                if current_total > 0:
                    for ticker in allocations:
                        ratio = allocations[ticker] / current_total
                        allocations[ticker] += remaining_investment * ratio
            
            # 캐시 업데이트
            self.allocation_cache = allocations
            self.last_calculation_time = current_time
            
            return allocations
            
        except Exception as e:
            print(f"투자금 분배 계산 오류: {e}")
            # 오류 시 동일 분배
            equal_allocation = total_investment / max(1, len(active_coins))
            return {ticker: equal_allocation for ticker in active_coins}
    
    def get_allocation_info(self, ticker):
        """특정 코인의 분배 정보 반환"""
        return self.allocation_cache.get(ticker, 0)
    
    def get_total_allocated(self):
        """총 분배된 금액 반환"""
        return sum(self.allocation_cache.values())
    
    def rebalance_allocations(self, total_investment, active_coins, grid_configs):
        """업데이트 간격마다 투자금 재분배"""
        try:
            # 새로운 분배 계산
            new_allocations = self.calculate_optimal_allocation(total_investment, active_coins, grid_configs)
            
            # 분배 변화량 계산 및 로그
            for ticker in active_coins:
                old_allocation = self.allocation_cache.get(ticker, 0)
                new_allocation = new_allocations.get(ticker, 0)
                change = new_allocation - old_allocation
                
                if abs(change) > total_investment * 0.05:  # 5% 이상 변화시에만 로그
                    change_percent = (change / total_investment) * 100
                    reallocation_reason = f"포트폴리오 최적화로 {change_percent:+.1f}% 조정"
                    reallocation_details = {
                        "old_allocation": f"{old_allocation:,.0f}원",
                        "new_allocation": f"{new_allocation:,.0f}원",
                        "change_amount": f"{change:+,.0f}원",
                        "change_percent": f"{change_percent:+.1f}%",
                        "total_investment": f"{total_investment:,.0f}원",
                        "trigger": "포트폴리오 리밸런싱"
                    }
                    log_trade(ticker, "투자금재분배", f"{old_allocation:,.0f}원 → {new_allocation:,.0f}원 ({change_percent:+.1f}%)", reallocation_reason, reallocation_details)
            
            return new_allocations
            
        except Exception as e:
            print(f"투자금 재분배 오류: {e}")
            return self.allocation_cache

def calculate_total_investment_with_profits():
    """수익을 포함한 전체 투자금 계산"""
    try:
        # 기본 투자금
        total_investment = float(config.get('total_investment', 1000000))
        
        # 실현된 수익 추가
        total_realized_profit = calculate_total_realized_profit()
        
        return total_investment + total_realized_profit
        
    except Exception as e:
        print(f"전체 투자금 계산 오류: {e}")
        return float(config.get('total_investment', 1000000))

# 전역 투자금 분배 시스템 인스턴스
coin_allocation_system = CoinAllocationSystem()

# 매수/매도 개수 추적
trade_counts = {
    "KRW-BTC": {"buy": 0, "sell": 0, "profitable_sell": 0},
    "KRW-ETH": {"buy": 0, "sell": 0, "profitable_sell": 0}, 
    "KRW-XRP": {"buy": 0, "sell": 0, "profitable_sell": 0}
}

def initialize_trade_counts_from_logs():
    """거래 로그를 기반으로 실제 trade_counts 초기화"""
    global trade_counts
    
    # trade_counts 초기화
    for ticker in trade_counts:
        trade_counts[ticker] = {"buy": 0, "sell": 0, "profitable_sell": 0}
    
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
            
            # 각 코인별로 로그 분석
            for ticker, ticker_logs in logs.items():
                if ticker in trade_counts:
                    for log_entry in ticker_logs:
                        action = log_entry.get('action', '')
                        # 실제 거래만 카운트 (데모 거래 제외)
                        if '데모' not in action and '자동매도' not in action:
                            if '매수' in action:
                                trade_counts[ticker]["buy"] += 1
                            elif '매도' in action:
                                trade_counts[ticker]["sell"] += 1
                                # 수익 거래 여부 확인 (details에서 수익 정보 확인)
                                details = log_entry.get('details', {})
                                if isinstance(details, dict):
                                    profit_info = details.get('profit', '0')
                                    if isinstance(profit_info, str) and '원' in profit_info:
                                        try:
                                            profit_value = int(profit_info.replace('원', '').replace(',', ''))
                                            if profit_value > 0:
                                                trade_counts[ticker]["profitable_sell"] += 1
                                        except:
                                            pass
                                            
        print(f"📊 거래 횟수 초기화 완료:")
        for ticker, counts in trade_counts.items():
            coin_name = get_korean_coin_name(ticker)
            print(f"  {coin_name}: 매수 {counts['buy']}회, 매도 {counts['sell']}회, 수익거래 {counts['profitable_sell']}회")
            
    except Exception as e:
        print(f"거래 횟수 초기화 오류: {e}")
        # 오류 발생시 모든 값을 0으로 초기화
        for ticker in trade_counts:
            trade_counts[ticker] = {"buy": 0, "sell": 0, "profitable_sell": 0}

# 실시간 로그 팝업 관련 전역 변수
current_log_popup = None
current_log_tree = None

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

def save_profits_data(profits_data):
    """수익 데이터를 파일에 저장"""
    try:
        with open(profit_file, 'w', encoding='utf-8') as f:
            json.dump(profits_data, f, indent=4, ensure_ascii=False)
        print(f"수익 데이터 저장 완료: {profits_data}")  # 디버그 로그
        return True
    except Exception as e:
        print(f"수익 데이터 저장 오류: {e}")
        return False

def calculate_total_realized_profit():
    """실현된 총 수익 계산"""
    try:
        profits_data = load_profits_data()
        total_profit = 0
        
        for ticker, profit in profits_data.items():
            if isinstance(profit, (int, float)):
                total_profit += profit
        
        return total_profit
    except Exception as e:
        print(f"총 수익 계산 오류: {e}")
        return 0

def calculate_ticker_realized_profit(ticker):
    """특정 코인의 실현수익 계산"""
    try:
        profits_data = load_profits_data()
        return profits_data.get(ticker, 0)
    except Exception as e:
        print(f"{ticker} 실현수익 계산 오류: {e}")
        return 0

def check_and_sell_profitable_positions(ticker, demo_mode=True):
    """고급 수익권 포지션 확인 및 리스크 기반 자동 매도"""
    try:
        positions = load_trading_state(ticker, demo_mode)
        if not positions:
            return 0, 0
        
        current_price = pyupbit.get_current_price(ticker)
        if current_price is None:
            return 0, 0
        
        total_sold_quantity = 0
        total_profit = 0
        remaining_positions = []
        
        # 리스크 설정 가져오기
        risk_settings = auto_trading_system.get_risk_settings(config.get('risk_mode', '안정적'))
        trailing_stop_percent = risk_settings.get('trailing_stop_percent', 2.0)
        stop_loss_threshold = risk_settings.get('stop_loss_threshold', -8.0)
        
        for position in positions:
            buy_price = position.get('buy_price', 0)
            quantity = position.get('quantity', 0)
            highest_price = position.get('highest_price', buy_price)
            
            # 최고가 업데이트
            if current_price > highest_price:
                position['highest_price'] = current_price
                highest_price = current_price
            
            profit_rate = (current_price - buy_price) / buy_price * 100
            trailing_stop_price = highest_price * (1 - trailing_stop_percent / 100)
            
            should_sell = False
            sell_reason = ""
            
            # 1. 손절 로직 (우선순위 최고)
            if profit_rate <= stop_loss_threshold:
                should_sell = True
                sell_reason = f"손절({profit_rate:.1f}%)"
            
            # 2. 트레일링 스톱 (수익권에서만 작동)
            elif profit_rate > 1.0 and current_price <= trailing_stop_price:
                should_sell = True
                sell_reason = f"트레일링스톱({profit_rate:.1f}%)"
            
            # 3. 기본 수익 실현 (기존 로직)
            elif current_price > buy_price * 1.005:  # 0.5% 이상 수익시
                should_sell = True
                sell_reason = f"수익실현({profit_rate:.1f}%)"
            
            if should_sell:
                # 매도 처리
                sell_value = quantity * current_price
                buy_value = quantity * buy_price
                profit = sell_value - buy_value - (sell_value * 0.0005)
                
                total_sold_quantity += quantity
                total_profit += profit
                
                # 수익권 포지션 매도 이유 상세 기록
                position_sell_reason = f"{sell_reason} 조건 만족"
                position_sell_details = {
                    "buy_price": f"{buy_price:,.0f}원",
                    "sell_price": f"{current_price:,.0f}원",
                    "quantity": f"{quantity:.6f}개",
                    "profit": f"{profit:,.0f}원",
                    "profit_rate": f"{profit_rate:.1f}%",
                    "highest_price": f"{highest_price:,.0f}원",
                    "condition": sell_reason,
                    "trigger": "자동 수익 실현"
                }
                log_trade(ticker, sell_reason, f"{current_price:,.0f}원 ({quantity:.6f}개) 수익: {profit:,.0f}원", position_sell_reason, position_sell_details)
                
                korean_name = get_korean_coin_name(ticker)
                speak_async(f"{korean_name} {sell_reason} 매도 완료")
            else:
                # 유지 (최고가 업데이트된 포지션 저장)
                remaining_positions.append(position)
        
        # 남은 포지션 저장
        save_trading_state(ticker, remaining_positions, demo_mode)
        
        # 수익 데이터 업데이트
        if total_profit > 0:
            profits_data = load_profits_data()
            current_profit = profits_data.get(ticker, 0)
            profits_data[ticker] = current_profit + total_profit
            save_profits_data(profits_data)
        
        return total_sold_quantity, total_profit
        
    except Exception as e:
        print(f"수익권 포지션 매도 오류: {e}")
        return 0, 0

# 투자금 업데이트 락
investment_update_lock = threading.Lock()
last_investment_update_time = 0
last_investment_update_profit = 0

def update_investment_with_profits(original_investment, force_update=False):
    """수익금을 포함하여 투자금 재계산 (중복 방지)"""
    global last_investment_update_time, last_investment_update_profit
    
    try:
        with investment_update_lock:
            current_time = time.time()
            
            # 5초 이내의 중복 업데이트 방지 (force_update가 True가 아닌 경우)
            if not force_update and (current_time - last_investment_update_time < 5):
                return original_investment + last_investment_update_profit, last_investment_update_profit
            
            total_profit = calculate_total_realized_profit()
            updated_investment = original_investment + total_profit
            
            # 수익이 있고 이전 업데이트와 다른 경우에만 로그 기록
            if total_profit > 0 and (force_update or total_profit != last_investment_update_profit):
                update_reason = f"실현 수익 {total_profit:,.0f}원 투자금 재투자"
                update_details = {
                    "original_investment": f"{original_investment:,.0f}원",
                    "realized_profit": f"{total_profit:,.0f}원",
                    "updated_investment": f"{updated_investment:,.0f}원",
                    "growth_rate": f"{((updated_investment - original_investment) / original_investment * 100):+.2f}%",
                    "force_update": "강제" if force_update else "자동",
                    "trigger": "수익 복리 투자"
                }
                log_trade("SYSTEM", "투자금 업데이트", f"기존: {original_investment:,.0f}원 + 수익: {total_profit:,.0f}원 = 신규: {updated_investment:,.0f}원", update_reason, update_details)
                speak_async(f"수익금 {total_profit:,.0f}원이 투자금에 포함되었습니다")
                
            last_investment_update_time = current_time
            last_investment_update_profit = total_profit
            
            return updated_investment, total_profit
    except Exception as e:
        print(f"투자금 업데이트 오류: {e}")
        return original_investment, 0


def backup_logs_before_clear():
    """데이터 초기화 전 로그 백업"""
    try:
        # data/backup 폴더 사용
        backup_folder = data_dir / "backup"
        backup_folder.mkdir(parents=True, exist_ok=True)
        
        # 현재 시간으로 백업 파일명 생성
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 각 데이터 파일 백업
        files_to_backup = [
            (log_file, f'trade_logs_{timestamp}.json'),
            (state_file, f'trading_state_{timestamp}.json'),
            (profit_file, f'profits_{timestamp}.json')
        ]
        
        backed_up_files = []
        for source, backup_name in files_to_backup:
            if os.path.exists(source):
                backup_path = backup_folder / backup_name
                shutil.copy2(source, backup_path)
                backed_up_files.append(backup_name)
                print(f"백업 완료: {source} → {backup_path}")
        
        # 백업 내역 로그 파일 생성
        backup_info = {
            'backup_time': timestamp,
            'backed_up_files': backed_up_files,
            'note': '데이터 초기화 전 자동 백업'
        }
        
        with open(backup_folder / f'backup_info_{timestamp}.json', 'w', encoding='utf-8') as f:
            json.dump(backup_info, f, indent=2, ensure_ascii=False)
        
        return len(backed_up_files)
        
    except Exception as e:
        print(f"백업 오류: {e}")
        raise

def auto_backup_logs():
    """정기 자동 백업 (매일 새벽)"""
    try:
        now = datetime.now()
        # 매일 새벽 2시에 백업 (시장 종료 후)
        if now.hour == 2 and now.minute == 0:
            daily_backup_dir = data_dir / "backup" / "daily"
            daily_backup_dir.mkdir(parents=True, exist_ok=True)
            
            date_str = now.strftime('%Y%m%d')
            
            # trade_logs.json이 존재하고 비어있지 않으면 백업
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # 로그가 있으면 백업
                    if data and any(logs for logs in data.values() if logs):
                        backup_path = daily_backup_dir / f'trade_logs_{date_str}.json'
                        shutil.copy2(log_file, backup_path)
                        print(f"일일 자동 백업 완료: {backup_path}")
                        
                        # 오래된 백업 파일 정리 (30일 이상)
                        cleanup_old_backups(daily_backup_dir, days=30)
                        
                except Exception as e:
                    print(f"일일 백업 오류: {e}")
                    
    except Exception as e:
        print(f"자동 백업 오류: {e}")

def cleanup_old_backups(backup_dir, days=30):
    """오래된 백업 파일 삭제"""
    try:
        cutoff_time = datetime.now() - timedelta(days=days)
        
        for file_path in backup_dir.glob('*.json'):
            if file_path.stat().st_mtime < cutoff_time.timestamp():
                file_path.unlink()
                print(f"오래된 백업 파일 삭제: {file_path}")
                
    except Exception as e:
        print(f"백업 파일 정리 오류: {e}")

def restore_logs_from_backup():
    """백업에서 로그 복구"""
    try:
        backup_folder = data_dir / "backup"
        if not backup_folder.exists():
            messagebox.showwarning("백업 없음", "data/backup 폴더가 없습니다.")
            return False
        
        # 백업 파일 목록 가져오기
        backup_files = list(backup_folder.glob('trade_logs_*.json'))
        daily_backup_files = list((backup_folder / 'daily').glob('trade_logs_*.json')) if (backup_folder / 'daily').exists() else []
        
        all_backup_files = backup_files + daily_backup_files
        
        if not all_backup_files:
            messagebox.showwarning("백업 없음", "백업된 로그 파일이 없습니다.")
            return False
        
        # 최신 백업 파일 선택
        latest_backup = max(all_backup_files, key=lambda x: x.stat().st_mtime)
        
        # 복구 확인
        confirm = messagebox.askyesno(
            "로그 복구", 
            f"최신 백업에서 로그를 복구하시겠습니까?\n\n백업 파일: {latest_backup.name}\n수정 시간: {datetime.fromtimestamp(latest_backup.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}\n\n현재 로그는 덮어쓰여집니다."
        )
        
        if confirm:
            shutil.copy2(latest_backup, log_file)
            messagebox.showinfo("복구 완료", f"로그가 성공적으로 복구되었습니다.\n\n복구된 파일: {latest_backup.name}")
            return True
            
        return False
        
    except Exception as e:
        messagebox.showerror("복구 오류", f"로그 복구 중 오류가 발생했습니다:\n{e}")
        return False

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


    
def safe_json_load(file_path, default_value=None):
    """안전한 JSON 파일 로드 (백업 및 복구 기능 포함)"""
    try:
        if not os.path.exists(file_path):
            return default_value if default_value is not None else {}
        
        # 파일 크기 검사
        if os.path.getsize(file_path) == 0:
            print(f"경고: {file_path} 파일이 비어있습니다. 기본값을 사용합니다.")
            return default_value if default_value is not None else {}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return default_value if default_value is not None else {}
            
            data = json.loads(content)
            return data
            
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 오류 ({file_path}): {e}")
        # 손상된 파일 백업 시도
        try:
            backup_corrupted_file(file_path)
        except:
            pass
        return default_value if default_value is not None else {}
        
    except UnicodeDecodeError as e:
        print(f"인코딩 오류 ({file_path}): {e}")
        try:
            backup_corrupted_file(file_path)
        except:
            pass
        return default_value if default_value is not None else {}
        
    except Exception as e:
        print(f"파일 로드 오류 ({file_path}): {e}")
        return default_value if default_value is not None else {}

def safe_json_save(file_path, data):
    """안전한 JSON 파일 저장 (임시 파일 사용, 파일 잠금)"""
    import time
    import random
    
    # 파일 잠금을 위한 최대 재시도 횟수
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            # 고유한 임시 파일명 생성 (동시 접근 방지)
            timestamp = int(time.time() * 1000)
            random_suffix = random.randint(1000, 9999)
            temp_file = f"{file_path}.tmp.{timestamp}.{random_suffix}"
            
            # 임시 파일에 먼저 저장
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            # 임시 파일이 정상적으로 저장되었는지 확인
            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                # 기존 파일 백업 (덧어쓰기 전)
                if os.path.exists(file_path):
                    backup_file = f"{file_path}.backup"
                    try:
                        shutil.copy2(file_path, backup_file)
                    except Exception as backup_err:
                        print(f"백업 파일 생성 실패: {backup_err}")
                
                # 임시 파일을 원본 파일로 이동
                shutil.move(temp_file, file_path)
                return True
            else:
                print(f"경고: 임시 파일 생성 실패: {temp_file}")
                # 실패한 임시 파일 정리
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except:
                    pass
                
        except (OSError, IOError) as e:
            print(f"JSON 저장 시도 {attempt + 1}/{max_retries} 실패 ({file_path}): {e}")
            
            # 실패한 임시 파일 정리
            try:
                if 'temp_file' in locals() and os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass
            
            if attempt < max_retries - 1:
                # 짧은 대기 후 재시도
                time.sleep(0.1 + (attempt * 0.05))
            
        except Exception as e:
            print(f"JSON 저장 오류 ({file_path}): {e}")
            break
    
    return False

def backup_corrupted_file(file_path):
    """손상된 파일 백업"""
    try:
        corrupted_backup_dir = data_dir / "backup" / "corrupted"
        corrupted_backup_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = Path(file_path).name
        backup_path = corrupted_backup_dir / f"{filename}.corrupted_{timestamp}"
        
        shutil.copy2(file_path, backup_path)
        print(f"손상된 파일 백업: {file_path} → {backup_path}")
        
    except Exception as e:
        print(f"손상된 파일 백업 오류: {e}")

def log_trade(ticker, action, price, reason=None, details=None):
    """거래 로그 기록 (개선된 안전 버전 - 매수/매도 이유 포함)"""
    entry = {
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': action,
        'price': f"{price:,.0f}원" if isinstance(price, (int, float)) else str(price)
    }
    
    # 매수/매도 이유 및 상세 정보 추가
    if reason:
        entry['reason'] = reason
    if details:
        entry['details'] = details
    
    try:
        # 안전한 로드
        data = safe_json_load(log_file, {})
        
        if ticker not in data:
            data[ticker] = []
        data[ticker].append(entry)
        
        # 안전한 저장
        if safe_json_save(log_file, data):
            return entry
        else:
            print(f"로그 저장 실패: {ticker} - {action}")
            return None
            
    except Exception as e:
        print(f"로그 기록 오류: {e}")
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
    """코인별 최적화된 가격 범위 계산"""
    actual_period = period
    
    # 코인별 설정 기간 사용
    if config.get('auto_trading_mode', False):
        coin_period = coin_grid_manager.get_price_range_days(ticker)
        if coin_period != period:
            actual_period = f"{coin_period}일"
            print(f"{get_korean_coin_name(ticker)} 코인별 가격범위 기간: {actual_period}")
    
    """향상된 가격 범위 계산 (사용자 지정 범위 및 자동 그리드 개수 고려)"""
    if use_custom_range and custom_high and custom_low:
        try:
            high_price = float(custom_high)
            low_price = float(custom_low)
            if high_price > low_price:
                return high_price, low_price, actual_period
        except (ValueError, TypeError):
            pass
    
    # 기존 범위 계산 로직 사용 (실제 기간은 숫자값 필요)
    period_for_calc = coin_grid_manager.get_price_range_days(ticker) if config.get('auto_trading_mode', False) else period
    high_price, low_price = calculate_price_range(ticker, period_for_calc)
    return high_price, low_price, actual_period

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
    """선택한 기간에 따라 상한가/하한가를 계산 (개선된 버전)"""
    print(f"🔍 가격 범위 계산 시작: {ticker}, 기간: {period}")
    
    # 최대 3번 재시도
    for attempt in range(3):
        try:
            print(f"   시도 {attempt + 1}/3...")
            
            # 숫자 형태의 일 수 처리
            if isinstance(period, (int, float)):
                df = pyupbit.get_ohlcv(ticker, interval="day", count=int(period))
                print(f"   일 수 기반 데이터 요청: {int(period)}일")
            elif period == "1시간":
                df = pyupbit.get_ohlcv(ticker, interval="minute60", count=1)
                print(f"   1시간 데이터 요청")
            elif period == "4시간":
                df = pyupbit.get_ohlcv(ticker, interval="minute60", count=4)
                print(f"   4시간 데이터 요청")
            elif period == "1일":
                df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
                print(f"   1일 데이터 요청")
            elif period == "7일":
                df = pyupbit.get_ohlcv(ticker, interval="day", count=7)
                print(f"   7일 데이터 요청")
            else:
                # 기본값으로 7일 사용
                df = pyupbit.get_ohlcv(ticker, interval="day", count=7)
                print(f"   기본값 7일 데이터 요청 (입력값: {period})")
            
            if df is None:
                print(f"   ❌ 데이터가 None입니다. (시도 {attempt + 1}/3)")
                if attempt < 2:  # 마지막 시도가 아니면
                    time.sleep(1)  # 1초 대기
                    continue
                else:
                    return None, None
                    
            if df.empty:
                print(f"   ❌ 데이터가 비어있습니다. (시도 {attempt + 1}/3)")
                if attempt < 2:
                    time.sleep(1)
                    continue
                else:
                    return None, None
            
            print(f"   ✅ 데이터 수신 성공: {len(df)}개 행")
            
            high_price = df['high'].max()
            low_price = df['low'].min()
            
            print(f"   원본 범위: {low_price:,.0f} ~ {high_price:,.0f}")
            
            # 유효성 검사
            if high_price <= 0 or low_price <= 0 or high_price <= low_price:
                print(f"   ❌ 잘못된 가격 범위: 상한={high_price}, 하한={low_price}")
                if attempt < 2:
                    time.sleep(1)
                    continue
                else:
                    return None, None
            
            # 약간의 여유를 두어 범위 확장 (상한 +2%, 하한 -2%)
            high_price = high_price * 1.02
            low_price = low_price * 0.98
            
            print(f"   📊 최종 범위: {low_price:,.0f} ~ {high_price:,.0f} (±2% 여유)")
            
            return high_price, low_price
            
        except requests.exceptions.RequestException as e:
            print(f"   🌐 네트워크 오류 (시도 {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2)  # 네트워크 오류시 2초 대기
                continue
        except Exception as e:
            print(f"   ❌ 가격 범위 계산 오류 (시도 {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(1)
                continue
    
    print(f"   💥 모든 시도 실패")
    return None, None

def calculate_auto_grid_count_enhanced(high_price, low_price, fee_rate=0.0005, investment_amount=1000000, ticker=None):
    """코인별 최적화된 그리드 수 계산"""
    # 코인별 최적화 사용
    if ticker and config.get('auto_trading_mode', False):
        optimal_grids = coin_grid_manager.calculate_optimal_grid_count(ticker, [high_price, low_price], investment_amount)
        print(f"{get_korean_coin_name(ticker)} 코인별 최적 그리드: {optimal_grids}개")
        return optimal_grids
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

def calculate_optimal_grid_count(high_price, low_price, target_profit_percent=None, fee_rate=0.0005, ticker=None):
    """코인별 최적 그리드 수 계산 (호환성 유지)"""
    # 코인별 최적화 사용
    if ticker and config.get('auto_trading_mode', False):
        return coin_grid_manager.calculate_optimal_grid_count(ticker, [high_price, low_price], 0)
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
def grid_trading(ticker, grid_count, total_investment, demo_mode, target_profit_percent_str, period, stop_event, gui_queue, total_profit_label, total_profit_rate_label, all_ticker_total_values, all_ticker_start_balances, profits_data, should_resume=False):
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
        
        # 분배 현황 동기화
        if key == 'allocation_info':
            allocation_data = coin_allocation_system.allocation_cache
            total_allocated = coin_allocation_system.get_total_allocated()
            gui_queue.put(('allocation_display', ticker, (allocation_data, total_allocated)))
        
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
    
    high_price, low_price, actual_period = calculate_enhanced_price_range(
        ticker, period, use_custom_range, custom_high, custom_low
    )
    
    if high_price is None or low_price is None:
        error_msg = f'{get_korean_coin_name(ticker)} 가격 범위 계산 실패'
        log_and_update('오류', error_msg)
        update_gui('status', f"상태: 가격 조회 실패 ({ticker})", "Red.TLabel", False, False)
        print(f"💥 {ticker} 거래 시작 실패: 가격 범위를 계산할 수 없습니다")
        print(f"   - 네트워크 연결을 확인하세요")
        print(f"   - Upbit API 상태를 확인하세요")
        print(f"   - 잠시 후 다시 시도하세요")
        return

    print(f"🔍 {ticker} 현재 가격 조회 중...")
    current_price = None
    
    # 현재 가격 조회 재시도 (최대 3번)
    for attempt in range(3):
        try:
            current_price = pyupbit.get_current_price(ticker)
            if current_price is not None:
                print(f"   ✅ 현재 가격 조회 성공: {current_price:,.0f}원")
                break
            else:
                print(f"   ❌ 현재 가격이 None (시도 {attempt + 1}/3)")
                if attempt < 2:
                    time.sleep(1)
        except Exception as e:
            print(f"   ❌ 현재 가격 조회 오류 (시도 {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(1)
    
    if current_price is None:
        error_msg = f'{get_korean_coin_name(ticker)} 현재 가격 조회 실패'
        log_and_update('오류', error_msg)
        update_gui('status', f"상태: 현재가 조회 실패 ({ticker})", "Red.TLabel", False, False)
        update_gui('action_status', 'error')
        print(f"💥 {ticker} 거래 시작 실패: 현재 가격을 조회할 수 없습니다")
        print(f"   - 해당 코인이 상장폐지되었는지 확인하세요")
        print(f"   - Upbit 서버 상태를 확인하세요")
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
        total_investment = total_investment * max_investment_ratio  # 이미 사용되는 변수를 직접 업데이트
        
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
            total_investment,
            ticker  # 코인별 최적화를 위해 ticker 전달
        )
        log_and_update('자동계산', f"최적 그리드 개수: {grid_count}개")

    log_and_update('시작', f"{actual_period} 범위: {low_price:,.0f}~{high_price:,.0f}")
    
    # 거래 시작 성공 상태 표시
    coin_name = get_korean_coin_name(ticker)
    print(f"🎉 {coin_name} 거래 시작 성공!")
    print(f"   - 가격 범위: {low_price:,.0f} ~ {high_price:,.0f}원")
    print(f"   - 그리드 개수: {grid_count}개")
    print(f"   - 투자 금액: {total_investment:,.0f}원")
    print(f"   - 현재 가격: {current_price:,.0f}원")
    
    update_gui('status', f"상태: 거래 중 ({coin_name})", "Green.TLabel", False, False)
    
    # GUI에 실제 사용된 기간 정보 전송
    update_gui('period_info', actual_period, high_price, low_price, grid_count)
    
    # 고급 그리드 상태 초기화
    advanced_grid_state = AdvancedGridState()

    fee_rate = config.get('fee_rate', 0.0005)
    previous_prices = []  # 급락 감지용 이전 가격들
    panic_mode = False

    # Calculate current total assets and cash balance on startup
    print(f"🔍 {ticker} 자산 계산용 현재 가격 조회 중...")
    current_price_for_calc = None
    
    # 자산 계산용 현재 가격 재시도
    for attempt in range(3):
        try:
            current_price_for_calc = pyupbit.get_current_price(ticker)
            if current_price_for_calc is not None:
                print(f"   ✅ 자산 계산용 가격 조회 성공: {current_price_for_calc:,.0f}원")
                break
            else:
                print(f"   ❌ 자산 계산용 가격이 None (시도 {attempt + 1}/3)")
                if attempt < 2:
                    time.sleep(1)
        except Exception as e:
            print(f"   ❌ 자산 계산용 가격 조회 오류 (시도 {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(1)
    
    if current_price_for_calc is None:
        error_msg = f'{get_korean_coin_name(ticker)} 자산 계산 실패'
        log_and_update('오류', error_msg)
        update_gui('status', f"상태: 자산 계산 실패 ({ticker})", "Red.TLabel", False, False)
        print(f"💥 {ticker} 거래 시작 실패: 자산 계산을 위한 현재 가격을 조회할 수 없습니다")
        return

    # 거래 재개 여부에 따른 데이터 로드
    if should_resume:
        # 1단계: 수익권 포지션 자동 매도
        sold_quantity, profit_amount = check_and_sell_profitable_positions(ticker, demo_mode)
        if sold_quantity > 0:
            log_and_update('수익실현', f'{sold_quantity:.6f}개 매도완료, 수익: {profit_amount:,.0f}원')
        
        # 2단계: 투자금은 이미 start_trading에서 업데이트되었으므로 여기서는 생략
        # (중복 업데이트 방지)
        
        # 자동모드인 경우 리스크 설정 재적용
        if config.get('auto_trading_mode', False):
            # 리스크 설정 재적용
            risk_settings = auto_trading_system.get_risk_settings(config.get('risk_mode', '안정적'))
            max_investment_ratio = risk_settings['max_investment_ratio']
            adjusted_investment = total_investment * max_investment_ratio
            
            # 그리드 개수 제한 재적용
            max_grids = risk_settings['max_grid_count']
            if grid_count > max_grids:
                grid_count = max_grids
                log_and_update('리스크재조정', f"그리드 개수 제한: {max_grids}개")
        
        # 2.5단계: 거래 재개 시에도 투자금 분배 재계산
        active_coins = [coin for coin in ['KRW-BTC', 'KRW-ETH', 'KRW-XRP'] 
                       if config.get(f'trade_{coin.split("-")[1].lower()}', False)]
        
        if len(active_coins) > 1:  # 다중 코인 거래인 경우만 재분배
            # 그리드 설정 정보 수집 (재개 시)
            grid_configs = {}
            for coin in active_coins:
                try:
                    coin_high, coin_low = calculate_price_range(coin, period)
                    if coin_high and coin_low:
                        coin_grid_count = calculate_optimal_grid_count(coin_high, coin_low, target_profit_percent, fee_rate, coin)
                        grid_configs[coin] = {
                            'count': coin_grid_count,
                            'range': coin_high - coin_low,
                            'high': coin_high,
                            'low': coin_low
                        }
                except Exception as e:
                    print(f"그리드 설정 수집 오류 ({coin}): {e}")
            
            # 투자금 재분배 계산
            allocations = coin_allocation_system.calculate_optimal_allocation(
                total_investment, active_coins, grid_configs
            )
            
            # 현재 코인의 분배된 투자금 사용
            allocated_investment = allocations.get(ticker, total_investment / len(active_coins))
            total_investment = allocated_investment  # 분배된 투자금으로 업데이트
            
            log_and_update('재분배완료', f"거래재개 시 분배금: {allocated_investment:,.0f}원 ({allocated_investment/sum(allocations.values())*100:.1f}%)")
            
            # GUI에 분배 정보 업데이트
            update_gui('allocation_info')
        
        # 3단계: 남은 포지션 로드
        demo_positions = load_trading_state(ticker, demo_mode)
        current_held_assets_value = sum(pos['quantity'] * current_price_for_calc for pos in demo_positions)
        invested_in_held_positions = sum(pos['quantity'] * pos['buy_price'] for pos in demo_positions)
        
        # 업데이트된 투자금 기준으로 자산 계산 (실현수익 포함)
        initial_capital = float(total_investment)
        
        # 실현수익 조회
        total_realized_profit = calculate_total_realized_profit()
        
        # 현금 잔고 = 총 투자금 - 현재 보유 포지션에 투입된 금액
        current_cash_balance = initial_capital - invested_in_held_positions
        
        # 총자산 = 현금 잔고 + 현재 코인 가치 (실현수익은 이미 총 투자금에 반영됨)
        current_total_assets = current_cash_balance + current_held_assets_value
        
        # 그리드 계산 재수행 (현재 보유 포지션 고려)
        price_gap = (high_price - low_price) / grid_count
        
        # 기존 포지션들이 차지한 그리드 슬롯 계산
        occupied_grid_slots = len(demo_positions)
        available_grid_slots = max(1, grid_count - occupied_grid_slots)  # 최소 1개 슬롯은 보장
        
        # 사용 가능한 현금으로 남은 그리드 슬롯에 투자
        if current_cash_balance > 0 and available_grid_slots > 0:
            amount_per_grid = current_cash_balance / available_grid_slots
        else:
            amount_per_grid = total_investment / grid_count  # 폴백: 기존 방식
        
        log_and_update('거래재개', f"보유포지션: {occupied_grid_slots}개, 사용가능현금: {current_cash_balance:,.0f}원, 남은슬롯: {available_grid_slots}개")
        
        # 그리드 가격 레벨 재생성
        grid_levels = []
        for i in range(grid_count + 1):
            price_level = low_price + (price_gap * i)
            grid_levels.append(price_level)
        
        log_and_update('설정재조정', f"그리드 간격: {price_gap:,.0f}원, 격당투자: {amount_per_grid:,.0f}원")
        
        if demo_mode:
            # 시작 잔고는 실현수익을 제외한 순수 초기 투자금으로 설정
            start_balance = initial_capital
            # 데모 잔고는 현재 현금 잔고로 설정 (실현수익이 반영된 투자금에서 보유 포지션 차감)
            demo_balance = current_cash_balance
            if demo_positions:
                log_and_update('정보', f'거래 재개: {len(demo_positions)}개의 포지션 유지')
            else:
                log_and_update('정보', '거래 재개: 모든 포지션 정리 완료')
            update_gui('action_status', 'waiting')
            total_invested = 0
    else:
        # 새로운 거래 시작 - 기존 상태 초기화
        demo_positions = []
        save_trading_state(ticker, [], True)  # 빈 상태로 저장
        current_held_assets_value = 0
        invested_in_held_positions = 0
        
        # 코인별 투자금 분배 계산 (새 거래)
        active_coins = [coin for coin in ['KRW-BTC', 'KRW-ETH', 'KRW-XRP'] 
                       if config.get(f'trade_{coin.split("-")[1].lower()}', False)]
        
        # 그리드 설정 정보 수집
        grid_configs = {}
        for coin in active_coins:
            try:
                coin_high, coin_low = calculate_price_range(coin, period)
                if coin_high and coin_low:
                    coin_grid_count = calculate_optimal_grid_count(coin_high, coin_low, target_profit_percent, fee_rate, coin)
                    grid_configs[coin] = {
                        'count': coin_grid_count,
                        'range': coin_high - coin_low,
                        'high': coin_high,
                        'low': coin_low
                    }
            except Exception as e:
                print(f"그리드 설정 수집 오류 ({coin}): {e}")
        
        # 투자금 자동 분배
        allocations = coin_allocation_system.calculate_optimal_allocation(
            total_investment, active_coins, grid_configs
        )
        
        # 현재 코인의 분배된 투자금 사용
        allocated_investment = allocations.get(ticker, total_investment / len(active_coins) if active_coins else total_investment)
        
        log_and_update('투자금분배', f"총 투자금: {total_investment:,.0f}원 중 {allocated_investment:,.0f}원 ({allocated_investment/total_investment*100:.1f}%) 분배")
        
        # GUI에 분배 정보 업데이트
        update_gui('allocation_info')
        
        initial_capital = float(allocated_investment)  # 분배된 투자금 사용
        current_cash_balance = initial_capital
        current_total_assets = initial_capital
        
        # 그리드 간격 계산 (분배된 투자금 기준)
        price_gap = (high_price - low_price) / grid_count
        amount_per_grid = allocated_investment / grid_count
        
        # 그리드 가격 레벨 생성
        grid_levels = []
        for i in range(grid_count + 1):
            price_level = low_price + (price_gap * i)
            grid_levels.append(price_level)
        
        log_and_update('설정', f"그리드 간격: {price_gap:,.0f}원, 격당투자: {amount_per_grid:,.0f}원")
        
        if demo_mode:
            # 새로운 거래 시작: 시작 잔고와 데모 잔고를 초기 투자금으로 설정
            start_balance = initial_capital
            demo_balance = initial_capital
            log_and_update('정보', '새로운 거래를 시작합니다.')
            update_gui('action_status', 'waiting')
            total_invested = 0

    highest_value = current_total_assets  # 트레일링 스탑용 최고 자산 가치
    
    if not demo_mode:
        print(f"💰 실거래 모드 - {get_korean_coin_name(ticker)} 계좌 정보 조회 중...")
        if upbit is None:
            log_and_update('오류', '업비트 API 초기화 안됨')
            update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
            return
        
        # 현재 보유 현금 조회
        start_balance = upbit.get_balance("KRW")
        if start_balance is None:
            log_and_update('오류', '잔액 조회 실패')
            update_gui('status', "상태: API 오류", "Red.TLabel", False, False)
            return
        
        # 현재 보유 코인 조회
        current_coin_balance = upbit.get_balance(ticker)
        if current_coin_balance is None:
            current_coin_balance = 0.0
            
        print(f"   ✅ 현금 보유: {start_balance:,.0f}원")
        print(f"   ✅ {get_korean_coin_name(ticker)} 보유: {current_coin_balance:.8f}개")
        
        # 기존 거래 상태 복원
        real_positions = load_trading_state(ticker, False)
        if real_positions:
            print(f"   📊 기존 포지션 복원: {len(real_positions)}개")
            log_and_update('정보', f'{len(real_positions)}개의 포지션을 복원했습니다.')
        else:
            # 포지션이 없지만 코인을 보유하고 있다면 자동으로 포지션 생성
            if current_coin_balance > 0.0001:  # 최소 보유량 체크
                auto_position = {
                    'quantity': current_coin_balance,
                    'buy_price': current_price_for_calc,  # 현재가로 추정
                    'actual_buy_price': current_price_for_calc,
                    'target_sell_price': current_price_for_calc * 1.02,  # 2% 수익률 목표
                    'highest_price': current_price_for_calc,
                    'buy_grid_level': 0,
                    'auto_created': True  # 자동 생성 포지션 표시
                }
                real_positions = [auto_position]
                save_trading_state(ticker, real_positions, False)
                print(f"   🔄 자동 포지션 생성: {current_coin_balance:.8f}개 (현재가 기준)")
                log_and_update('자동생성', f'보유 코인 기반 포지션 자동 생성: {current_coin_balance:.8f}개')
        
        total_invested = 0
    
    prev_price = current_price
    update_gui('chart_data', high_price, low_price, grid_levels, grid_count, allocated_investment if 'allocated_investment' in locals() else total_investment)
    
    total_realized_profit = 0
    last_update_day = datetime.now().day

    # 새로운 매수 로직을 위한 상태 변수
    buy_pending = False
    lowest_grid_to_buy = -1
    recent_prices = []  # 가격 히스토리 저장

    while not stop_event.is_set():
        # 9시 정각 그리드 자동 갱신 및 투자금 재분배
        now = datetime.now()
        if config.get('auto_grid_count', True) and now.hour == 9 and now.day != last_update_day:
            log_and_update('정보', '오전 9시, 그리드 설정 및 투자금 분배를 자동 갱신합니다.')
            
            # 코인별 투자금 재분배
            active_coins = [coin for coin in ['KRW-BTC', 'KRW-ETH', 'KRW-XRP'] 
                           if config.get(f'trade_{coin.split("-")[1].lower()}', False)]
            
            # 그리드 설정 정보 업데이트
            grid_configs = {}
            for coin in active_coins:
                try:
                    coin_high, coin_low = calculate_price_range(coin, period)
                    if coin_high and coin_low:
                        coin_grid_count = calculate_optimal_grid_count(coin_high, coin_low, target_profit_percent, fee_rate, coin)
                        grid_configs[coin] = {
                            'count': coin_grid_count,
                            'range': coin_high - coin_low,
                            'high': coin_high,
                            'low': coin_low
                        }
                except Exception as e:
                    print(f"그리드 설정 업데이트 오류 ({coin}): {e}")
            
            # 투자금 재분배 (수익 포함 전체 투자금 기준)
            current_total_investment = calculate_total_investment_with_profits()
            new_allocations = coin_allocation_system.rebalance_allocations(
                current_total_investment, active_coins, grid_configs
            )
            
            # 현재 코인의 새로운 분배 금액
            new_allocated_investment = new_allocations.get(ticker, current_total_investment / len(active_coins) if active_coins else current_total_investment)
            
            # 그리드 설정 업데이트
            new_high, new_low = calculate_price_range(ticker, period)
            if new_high and new_low:
                high_price, low_price = new_high, new_low
                grid_count = calculate_optimal_grid_count(high_price, low_price, target_profit_percent, fee_rate, ticker)
                price_gap = (high_price - low_price) / grid_count
                amount_per_grid = new_allocated_investment / grid_count  # 새로운 분배 금액 기준
                grid_levels = [low_price + (price_gap * i) for i in range(grid_count + 1)]
                
                log_and_update('설정갱신', f"새 그리드: {grid_count}개, 범위: {low_price:,.0f}~{high_price:,.0f}, 격당투자: {amount_per_grid:,.0f}원")
                update_gui('chart_data', high_price, low_price, grid_levels, grid_count, new_allocated_investment)
            
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
            
            # 가격 히스토리 업데이트 (최대 20개 유지)
            recent_prices.append(price)
            if len(recent_prices) > 20:
                recent_prices.pop(0)
            
            # 긴급 정지 조건 확인
            if demo_mode and demo_positions:
                emergency_stop, emergency_reason = risk_manager.should_emergency_stop(ticker, price, demo_positions)
                if emergency_stop:
                    log_and_update('긴급정지', f"긴급 거래 중단: {emergency_reason}")
                    speak_async(f"긴급 상황! {get_korean_coin_name(ticker)} 거래를 중단합니다.")
                    update_gui('status', "상태: 긴급 정지", "Red.TLabel", False, False)
                    break
            
            # 기술적 분석 및 개별 포지션 리스크 관리
            if demo_mode and demo_positions:
                current_technical_analysis = technical_analyzer.get_comprehensive_signals(ticker, price)
                positions_to_remove = []
                
                for i, position in enumerate(demo_positions):
                    # 손절 조건 확인
                    should_cut, cut_reason = risk_manager.should_cut_loss(
                        ticker, position, price, current_technical_analysis
                    )
                    
                    if should_cut:
                        # 강제 손절 매도
                        sell_amount = position['quantity'] * price
                        net_sell_amount = sell_amount * (1 - fee_rate)
                        
                        demo_balance += net_sell_amount
                        positions_to_remove.append(position)
                        
                        buy_cost = position['quantity'] * position.get('actual_buy_price', position['buy_price'])
                        net_loss = net_sell_amount - buy_cost
                        total_realized_profit += net_loss
                        
                        # profits.json에 손실 데이터 저장
                        profits_data = load_profits_data()
                        current_profit = profits_data.get(ticker, 0)
                        profits_data[ticker] = current_profit + net_loss
                        save_profits_data(profits_data)
                        
                        log_msg = f"손절 매도: {price:,.0f}원 ({position['quantity']:.6f}개) 손실: {net_loss:,.0f}원 ({cut_reason})"
                        log_and_update("데모 손절", log_msg)
                        speak_async(f"손절! {get_korean_coin_name(ticker)} {price:,.0f}원에 매도")
                        send_kakao_message(f"[손절 매도] {get_korean_coin_name(ticker)} {price:,.0f}원 ({position['quantity']:.6f}개) 손실: {net_loss:,.0f}원")
                
                # 손절된 포지션 제거
                for position in positions_to_remove:
                    demo_positions.remove(position)
                
                if positions_to_remove:
                    save_trading_state(ticker, demo_positions, True)
                    update_gui('refresh_chart')
                    
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
        
        # 최고가 업데이트 (트레일링 스톱용)
        if demo_mode:
            current_held_assets_value = sum(pos['quantity'] * price for pos in demo_positions)
            current_total_value = (demo_balance - total_invested) + current_held_assets_value
            
            if current_total_value > highest_value:
                highest_value = current_total_value
        
        # 자동 리스크 관리 (자동모드에서만 작동)
        if config.get('auto_trading_mode', False) and demo_positions:
            risk_settings = auto_trading_system.get_risk_settings(config.get('risk_mode', '안정적'))
            
            # 1. 포트폴리오 전체 손절 검사
            total_unrealized_loss = 0
            total_investment_value = 0
            
            for pos in demo_positions:
                buy_value = pos['quantity'] * pos['buy_price']
                current_value = pos['quantity'] * price
                total_investment_value += buy_value
                
                if current_value < buy_value:
                    total_unrealized_loss += (buy_value - current_value)
            
            if total_investment_value > 0:
                portfolio_loss_ratio = total_unrealized_loss / total_investment_value
                
                # 포트폴리오 전체 손절 대응
                if portfolio_loss_ratio > abs(risk_settings['stop_loss_threshold']) / 100:
                    log_and_update('포트폴리오손절', f'전체 손실 {portfolio_loss_ratio:.1%} - 모든 포지션 정리')
                    
                    # 모든 포지션 강제 매도
                    for pos in demo_positions:
                        sell_value = pos['quantity'] * price
                        buy_value = pos['quantity'] * pos['buy_price']
                        loss = sell_value - buy_value - (sell_value * 0.0005)
                        total_realized_profit += loss
                        
                        portfolio_reason = f"포트폴리오 전체 손실 {portfolio_loss_ratio:.1%} 초과"
                        portfolio_details = {
                            "total_loss_ratio": f"{portfolio_loss_ratio:.1%}",
                            "stop_loss_threshold": f"{abs(risk_settings['stop_loss_threshold'])}%",
                            "position_buy_price": f"{pos['buy_price']:,.0f}원",
                            "position_sell_price": f"{price:,.0f}원",
                            "quantity": f"{pos['quantity']:.6f}개",
                            "position_loss": f"{loss:,.0f}원",
                            "trigger": "포트폴리오 리스크 관리"
                        }
                        log_trade(ticker, "포트폴리오손절", f"{price:,.0f}원 ({pos['quantity']:.6f}개) 손실: {loss:,.0f}원", portfolio_reason, portfolio_details)
                    
                    demo_positions = []  # 모든 포지션 정리
                    save_trading_state(ticker, demo_positions, demo_mode)
                    
                    speak_async(f"{get_korean_coin_name(ticker)} 포트폴리오 손절 실행")
                    send_kakao_message(f"{get_korean_coin_name(ticker)} 포트폴리오 손절: 전체 포지션 정리")
            
            # 2. 트레일링 스톱 검사 (수익권에서만)
            if demo_mode and current_total_value > start_balance:
                trailing_stop_percent = risk_settings.get('trailing_stop_percent', 2.0)
                trailing_stop_price = highest_value * (1 - trailing_stop_percent / 100)
                
                if current_total_value <= trailing_stop_price:
                    log_and_update('트레일링스톱', f'최고점 {highest_value:,.0f}원에서 {trailing_stop_percent}% 하락 - 전체 매도')
                    
                    # 모든 포지션 매도
                    for pos in demo_positions:
                        sell_value = pos['quantity'] * price
                        buy_value = pos['quantity'] * pos['buy_price']
                        profit = sell_value - buy_value - (sell_value * 0.0005)
                        total_realized_profit += profit
                        
                        log_trade(ticker, "트레일링스톱", f"{price:,.0f}원 ({pos['quantity']:.6f}개) 수익: {profit:,.0f}원")
                    
                    demo_positions = []
                    save_trading_state(ticker, demo_positions, demo_mode)
                    
                    speak_async(f"{get_korean_coin_name(ticker)} 트레일링 스톱 실행")
                    send_kakao_message(f"{get_korean_coin_name(ticker)} 트레일링 스톱: 전체 수익 실현")
        
        # 급락 상황 감지
        new_panic_mode = detect_panic_selling(price, previous_prices, config.get("panic_threshold", -5.0))
        if new_panic_mode and not panic_mode:
            log_and_update('급락감지', '급락 대응 모드 활성화')
            send_kakao_message(f"{get_korean_coin_name(ticker)} 급락 감지! 대응 모드 활성화")
            
            # 동적 그리드 재계산
            new_low, new_high = calculate_dynamic_grid(low_price, high_price, price, True)
            new_price_gap = (new_high - new_low) / grid_count
            grid_levels = [new_low + (new_price_gap * i) for i in range(grid_count + 1)]
            current_investment = amount_per_grid * grid_count if 'amount_per_grid' in locals() else total_investment
            update_gui('chart_data', new_high, new_low, grid_levels, grid_count, current_investment)
            
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
                    # 가격이 반등하여 최저 그리드를 '확실히' 돌파했는지 체크 (매수 실행 + 기술적 분석)
                    confirmation_buffer = 0.001 # 0.1% 버퍼
                    buy_confirmation_price = grid_levels[lowest_grid_to_buy] * (1 + confirmation_buffer)
                    
                    # 기본 가격 조건 확인
                    price_condition_met = price >= buy_confirmation_price
                    
                    if price_condition_met:
                        # 기술적 분석으로 매수 신호 검증
                        should_override, technical_analysis = technical_analyzer.should_override_grid_signal(ticker, 'buy', price)
                        technical_signal = technical_analysis.get('signal', 'hold')
                        confidence = technical_analysis.get('confidence', 0)
                        
                        # 매수 실행 조건:
                        # 1. 기술적 분석이 매수를 방해하지 않음 (override가 아님)
                        # 2. 또는 기술적 분석이 강한 매수 신호
                        execute_buy = not should_override or technical_signal in ['strong_buy', 'buy']
                        
                        if execute_buy:
                            buy_price = grid_levels[lowest_grid_to_buy]
                            already_bought = any(pos['buy_price'] == buy_price for pos in demo_positions)

                            if not already_bought and demo_balance >= amount_per_grid:
                                # 리스크 관리 기반 최적 포지션 크기 계산
                                optimal_amount = risk_manager.calculate_optimal_position_size(
                                    ticker, amount_per_grid, technical_analysis
                                )
                                
                                # 급락장에서는 추가 조정
                                buy_multiplier = 1.3 if panic_mode else 1.0
                                actual_buy_amount = min(optimal_amount * buy_multiplier, demo_balance)
                                
                                # 시장 심리 고려한 추가 조정
                                market_sentiment = risk_manager.get_market_sentiment(ticker, price, recent_prices)
                                if market_sentiment in ['bearish_volatile', 'bearish_stable']:
                                    actual_buy_amount *= 0.9  # 하락장에서는 10% 감소
                                
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
                                    'highest_grid_reached': -1,
                                    'technical_score': technical_analysis.get('net_score', 0),
                                    'confidence': confidence
                                })
                                save_trading_state(ticker, demo_positions, True)

                                # 기술적 분석 정보 포함한 로그
                                signal_info = f" (기술분석: {technical_signal}, 신뢰도: {confidence:.0f}%)" if confidence > 50 else ""
                                log_msg = f"하락추세 반전 매수: {buy_price:,.0f}원 ({quantity:.6f}개){signal_info}"
                                
                                # 매수 결정 이유 상세 기록
                                buy_reason = f"그리드 레벨 {lowest_grid_to_buy+1} 반등 확인"
                                buy_details = {
                                    "grid_price": f"{grid_levels[lowest_grid_to_buy]:,.0f}원",
                                    "confirmation_price": f"{buy_confirmation_price:,.0f}원", 
                                    "current_price": f"{price:,.0f}원",
                                    "technical_signal": technical_signal,
                                    "confidence": f"{confidence:.1f}%",
                                    "override_status": "미적용" if not should_override else "적용",
                                    "position_size": f"{actual_buy_amount:,.0f}원",
                                    "market_sentiment": market_sentiment,
                                    "panic_mode": "활성" if panic_mode else "비활성"
                                }
                                log_trade(ticker, "데모 매수", log_msg, buy_reason, buy_details)
                                speak_async(f"데모 모드, {get_korean_coin_name(ticker)} {buy_price:,.0f}원에 최종 매수되었습니다.")
                                send_kakao_message(f"[데모 최종매수] {get_korean_coin_name(ticker)} {buy_price:,.0f}원 ({quantity:.6f}개){signal_info}")
                                
                        else:
                            # 기술적 분석이 매수를 방해하는 경우
                            if should_override:
                                log_msg = f"매수 신호 무시 (기술분석: {technical_signal}, 신뢰도: {confidence:.0f}%)"
                                cancel_reason = f"기술적 분석 override 신호"
                                cancel_details = {
                                    "grid_price": f"{grid_levels[lowest_grid_to_buy]:,.0f}원",
                                    "current_price": f"{price:,.0f}원",
                                    "technical_signal": technical_signal,
                                    "confidence": f"{confidence:.1f}%",
                                    "reason": "기술적 분석이 매수 반대 신호 발생"
                                }
                                log_trade(ticker, "데모 매수취소", log_msg, cancel_reason, cancel_details)
                            
                            # 데모 모드에서도 매수 횟수 증가 (거래 통계용)
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
                            reason = f"그리드 레벨 {i+1}/{len(grid_levels)} 도달"
                            details = f"이전가격: {prev_price:,.0f}원 → 현재가격: {price:,.0f}원 (그리드가격: {grid_price:,.0f}원)"
                            log_trade(ticker, "데모 매수보류", log_msg, reason, details)
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
                    
                    # profits.json에 수익 데이터 저장 (수익/손실 모두 기록)
                    profits_data = load_profits_data()
                    current_profit = profits_data.get(ticker, 0)
                    profits_data[ticker] = current_profit + net_profit
                    save_profits_data(profits_data)
                    print(f"프로스 저장: {ticker} 수익 {net_profit:,.0f}원 추가")  # 디버그

                    log_msg = f"{sell_reason} 매도: {price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원"
                    
                    # 손절/트레일링스탑 매도 이유 상세 기록
                    sell_details = {
                        "buy_price": f"{position['actual_buy_price']:,.0f}원",
                        "sell_price": f"{price:,.0f}원",
                        "highest_price": f"{position['highest_price']:,.0f}원",
                        "quantity": f"{position['quantity']:.6f}개",
                        "net_profit": f"{net_profit:,.0f}원",
                        "stop_loss_threshold": f"{config.get('stop_loss_threshold', -10.0)}%",
                        "trailing_stop_percent": f"{config.get('trailing_stop_percent', 3.0)}%" if config.get('trailing_stop', True) else "비활성"
                    }
                    
                    if stop_loss_triggered:
                        stop_reason = f"손절 기준 도달 ({position['actual_buy_price'] * (1 + config.get('stop_loss_threshold', -10.0) / 100):,.0f}원 하회)"
                    else:
                        stop_reason = f"트레일링스탑 기준 도달 (최고가 대비 {config.get('trailing_stop_percent', 3.0)}% 하락)"
                    
                    log_trade(ticker, "데모 매도", log_msg, stop_reason, sell_details)
                    speak_async(f"데모 모드, {sell_reason}, {get_korean_coin_name(ticker)}" + f" {price:,.0f}원에 매도되었습니다.")
                    send_kakao_message(f"[데모 매도] {get_korean_coin_name(ticker)} {price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원 ({sell_reason})")
                    
                    # 데모 모드에서도 매도 횟수 증가 (거래 통계용)
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
                        
                        # 매도 보류 목표 상향 이유 기록
                        hold_reason = f"상승 추세 지속으로 그리드 {current_highest_grid+2} 레벨 목표 상향"
                        hold_details = {
                            "previous_target": f"{grid_levels[current_highest_grid]:,.0f}원",
                            "new_target": f"{new_target_price:,.0f}원",
                            "current_price": f"{price:,.0f}원",
                            "grid_level": f"{position['highest_grid_reached']+1}/{len(grid_levels)}"
                        }
                        log_trade(ticker, "데모 매도보류", log_msg, hold_reason, hold_details)
                        speak_async(f"{get_korean_coin_name(ticker)} " + "매도 보류 시작")
                        update_gui('refresh_chart')
                        update_gui('action_status', 'looking_sell')

                    else:
                        # 가격이 최고 그리드 아래로 '확실히' 하락했는지 체크 (매도 실행 + 기술적 분석)
                        confirmation_buffer = 0.001 # 0.1% 버퍼
                        sell_confirmation_price = grid_levels[current_highest_grid] * (1 - confirmation_buffer)
                        price_condition_met = price <= sell_confirmation_price
                        
                        if price_condition_met:
                            # 기술적 분석으로 매도 신호 검증
                            should_override, technical_analysis = technical_analyzer.should_override_grid_signal(ticker, 'sell', price)
                            technical_signal = technical_analysis.get('signal', 'hold')
                            confidence = technical_analysis.get('confidence', 0)
                            
                            # 매도 실행 조건:
                            # 1. 기술적 분석이 매도를 방해하지 않음 (override가 아님)
                            # 2. 또는 기술적 분석이 강한 매도 신호
                            execute_sell = not should_override or technical_signal in ['strong_sell', 'sell']
                            
                            if execute_sell:
                                sell_price = grid_levels[current_highest_grid] # 하락한 그리드 가격으로 매도
                                sell_amount = position['quantity'] * sell_price
                                net_sell_amount = sell_amount * (1 - fee_rate)
                                
                                demo_balance += net_sell_amount
                                demo_positions.remove(position)
                                save_trading_state(ticker, demo_positions, True)
                                
                                buy_cost = position['quantity'] * position['actual_buy_price']
                                net_profit = net_sell_amount - buy_cost
                                total_realized_profit += net_profit
                                
                                # profits.json에 수익 데이터 저장 (수익/손실 모두 기록)
                                profits_data = load_profits_data()
                                current_profit = profits_data.get(ticker, 0)
                                profits_data[ticker] = current_profit + net_profit
                                save_profits_data(profits_data)
                                print(f"프로스 저장: {ticker} 수익 {net_profit:,.0f}원 추가")  # 디버그

                                # 기술적 분석 정보 포함한 로그
                                signal_info = f" (기술분석: {technical_signal}, 신뢰도: {confidence:.0f}%)" if confidence > 50 else ""
                                log_msg = f"상승추세 종료 매도: {sell_price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원{signal_info}"
                                
                                # 그리드 매도 실행 이유 상세 기록
                                grid_sell_reason = f"그리드 레벨 {current_highest_grid+1} 하락 확인"
                                grid_sell_details = {
                                    "buy_price": f"{position['actual_buy_price']:,.0f}원",
                                    "sell_price": f"{sell_price:,.0f}원",
                                    "grid_level": f"{current_highest_grid+1}/{len(grid_levels)}",
                                    "confirmation_price": f"{sell_confirmation_price:,.0f}원",
                                    "current_price": f"{price:,.0f}원",
                                    "technical_signal": technical_signal,
                                    "confidence": f"{confidence:.1f}%",
                                    "override_status": "미적용" if not should_override else "적용",
                                    "net_profit": f"{net_profit:,.0f}원",
                                    "quantity": f"{position['quantity']:.6f}개"
                                }
                                log_trade(ticker, "데모 매도", log_msg, grid_sell_reason, grid_sell_details)
                                speak_async(f"데모 모드, {get_korean_coin_name(ticker)} " + f" {sell_price:,.0f}원에 최종 매도되었습니다.")
                                send_kakao_message(f"[데모 최종매도] {get_korean_coin_name(ticker)} {sell_price:,.0f}원 ({position['quantity']:.6f}개) 순수익: {net_profit:,.0f}원{signal_info}")
                                
                            else:
                                # 기술적 분석이 매도를 방해하는 경우
                                if should_override:
                                    log_msg = f"매도 신호 무시 (기술분석: {technical_signal}, 신뢰도: {confidence:.0f}%)"
                                    sell_cancel_reason = f"기술적 분석 override 신호"
                                    sell_cancel_details = {
                                        "grid_price": f"{grid_levels[current_highest_grid]:,.0f}원",
                                        "current_price": f"{price:,.0f}원",
                                        "technical_signal": technical_signal,
                                        "confidence": f"{confidence:.1f}%",
                                        "reason": "기술적 분석이 매도 반대 신호 발생"
                                    }
                                    log_trade(ticker, "데모 매도취소", log_msg, sell_cancel_reason, sell_cancel_details)
                            
                            # 데모 모드에서도 매도 횟수 증가 (거래 통계용)
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
                            
                            # 최초 매도 보류 시작 이유 기록
                            initial_hold_reason = f"목표 그리드 가격 도달로 매도 보류 시작"
                            initial_hold_details = {
                                "buy_price": f"{position['actual_buy_price']:,.0f}원",
                                "target_price": f"{position['target_sell_price']:,.0f}원",
                                "current_price": f"{price:,.0f}원",
                                "grid_level": f"{position['highest_grid_reached']+1}/{len(grid_levels)}",
                                "quantity": f"{position['quantity']:.6f}개"
                            }
                            log_trade(ticker, "데모 매도보류", log_msg, initial_hold_reason, initial_hold_details)
                            speak_async(f"{get_korean_coin_name(ticker)} " + "매도 보류 시작")
                            update_gui('refresh_chart')
                            update_gui('action_status', 'looking_sell')
            
            # 긴급 청산 체크
            held_value = sum(pos['quantity'] * price for pos in demo_positions)
            
            # 총자산 = 현금 잔고 + 코인 가치 (실현수익은 별도로 추가해야 함)
            ticker_realized_profit = calculate_ticker_realized_profit(ticker)
            total_value = demo_balance + held_value
            
            # 코인 보유량이 0일 때 평가수익도 0으로 처리
            coin_quantity = sum(pos['quantity'] for pos in demo_positions)
            if coin_quantity == 0:
                held_value = 0  # 보유 코인이 없으면 코인가치도 0
            
            # 긴급청산용 임시 수익률 계산
            temp_profit_percent = (total_value - start_balance) / start_balance * 100 if start_balance > 0 else 0
            
            if (config.get("emergency_exit_enabled", True) and 
                temp_profit_percent <= config.get("stop_loss_threshold", -10.0)):
                # 모든 포지션 청산
                total_emergency_profit = 0
                for position in demo_positions[:]:
                    sell_amount = position['quantity'] * price
                    sell_fee = sell_amount * fee_rate
                    net_sell_amount = sell_amount - sell_fee
                    demo_balance += net_sell_amount
                    
                    # 긴급청산에서도 수익 계산 및 저장
                    buy_cost = position['quantity'] * position['actual_buy_price']
                    net_profit = net_sell_amount - buy_cost
                    total_emergency_profit += net_profit
                    
                    demo_positions.remove(position)
                
                # profits.json에 긴급청산 수익 저장 (손실도 기록)
                if total_emergency_profit != 0:
                    profits_data = load_profits_data()
                    current_profit = profits_data.get(ticker, 0)
                    profits_data[ticker] = current_profit + total_emergency_profit
                    save_profits_data(profits_data)
                    print(f"긴급청산 수익 저장: {ticker} {total_emergency_profit:,.0f}원")  # 디버그
                
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
                
            # 평가수익 계산 (현재가 기준 코인가치 - 매수가 기준 투자금액)
            invested_amount = sum(pos['quantity'] * pos['actual_buy_price'] for pos in demo_positions)
            unrealized_profit = held_value - invested_amount  # 평가수익 = 현재 코인가치 - 투자금액
            
            # 해당 코인의 실현수익 계산
            ticker_realized_profit = calculate_ticker_realized_profit(ticker)
            
            # 총자산 = 초기 투자금 + 실현수익 + 평가수익
            total_value = start_balance + ticker_realized_profit + unrealized_profit
            
            # 전체 수익 = 실현수익 + 평가수익  
            profit = ticker_realized_profit + unrealized_profit
            
            # 전체 수익률 계산
            profit_percent = (profit / start_balance) * 100 if start_balance > 0 else 0
            
            # 코인 보유량이 0일 때 평가수익도 0으로 처리
            if coin_quantity == 0:
                unrealized_profit = 0
                held_value = 0
                profit = ticker_realized_profit  # 실현수익만
                total_value = start_balance + ticker_realized_profit  # 초기금 + 실현수익
                
            realized_profit_percent = (ticker_realized_profit / total_investment) * 100 if total_investment > 0 else 0
            
            # 평가수익과 평가수익률 계산
            unrealized_profit_percent = (unrealized_profit / total_investment) * 100 if total_investment > 0 else 0
            
            # 시장 상태 분석
            market_status, market_details = analyze_market_condition(ticker, price, recent_prices, high_price, low_price)
            
            # 급등/급락 시 경고 메시지 (중복 방지)
            if market_status in ["급등", "급락"]:
                current_time = time.time()
                last_time = last_alert_time.get(ticker, 0)
                
                # 쿨다운 시간이 지났거나, 처음 경고인 경우
                if current_time - last_time > alert_cooldown:
                    korean_name = get_korean_coin_name(ticker)
                    if "초급등" in market_details or "초급락" in market_details:
                        speak_async(f"긴급! {korean_name} {market_details}!", repeat=5)
                    elif "강급등" in market_details or "강급락" in market_details:
                        speak_async(f"주의! {korean_name} {market_details}!", repeat=3)
                    else:
                        speak_async(f"알림! {korean_name} {market_details}!", repeat=2)
                    
                    last_alert_time[ticker] = current_time
            
            update_gui('details', demo_balance, coin_quantity, held_value, total_value, profit, profit_percent, ticker_realized_profit, realized_profit_percent, unrealized_profit, unrealized_profit_percent)
            update_gui('market_status', market_status, market_details)

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
            # 실제 거래 모드 로직 - 데모와 동일한 로직이지만 실제 API 호출
            log_and_update('실제거래', '실제 거래 모드로 동작합니다.')
            
            # 실제 거래 로직은 데모 모드와 동일하지만 실제 API 호출을 사용
            # 현재 보유 현금 및 코인 조회
            if upbit:
                current_balance = upbit.get_balance("KRW")
                current_coin_balance = upbit.get_balance(ticker)
                print(f"💰 실거래 모드 - 현재 보유: 현금 {current_balance:,.0f}원, {get_korean_coin_name(ticker)} {current_coin_balance:.8f}개")
            
            # 실제 거래에서는 데모와 동일한 로직을 사용하되, 매매 시에만 실제 API를 호출
            positions = demo_positions
            
            # 실거래 매수 로직
            if not buy_pending and price <= grid_levels[lowest_grid_to_buy] * (1 + config.get('grid_confirmation_buffer', 0.1) / 100):
                if demo_balance >= amount_per_grid:
                    # 실제 매수 주문 실행
                    try:
                        buy_result = execute_buy_order(ticker, amount_per_grid, price)
                        if buy_result and buy_result.get('uuid'):
                            # 매수 성공 시 포지션 추가
                            buy_price = grid_levels[lowest_grid_to_buy]
                            quantity = (amount_per_grid * (1 - fee_rate)) / buy_price
                            
                            new_position = {
                                'quantity': quantity,
                                'buy_price': buy_price,
                                'actual_buy_price': price,
                                'target_sell_price': price * (1 + target_profit_percent / 100),
                                'highest_price': price,
                                'buy_grid_level': lowest_grid_to_buy,
                                'order_uuid': buy_result.get('uuid')  # 실거래에서는 주문 ID 저장
                            }
                            demo_positions.append(new_position)
                            save_trading_state(ticker, demo_positions, demo_mode)
                            
                            # 잔고 업데이트
                            demo_balance -= amount_per_grid
                            
                            buy_reason = f"그리드 레벨 {lowest_grid_to_buy+1} 매수 신호"
                            buy_details = {
                                "grid_price": f"{buy_price:,.0f}원",
                                "actual_price": f"{price:,.0f}원",
                                "quantity": f"{quantity:.8f}개",
                                "investment": f"{amount_per_grid:,.0f}원",
                                "order_id": buy_result.get('uuid')
                            }
                            log_trade(ticker, "실거래 매수", f"{price:,.0f}원 ({quantity:.6f}개) 투자: {amount_per_grid:,.0f}원", buy_reason, buy_details)
                            speak_async(f"실거래 매수 완료, {get_korean_coin_name(ticker)} {price:,.0f}원")
                            
                            print(f"🔥 실거래 매수 완료: {quantity:.8f}개 @ {price:,.0f}원")
                        else:
                            print(f"❌ 실거래 매수 실패: API 응답 오류")
                            log_trade(ticker, "매수 실패", f"주문 실패: {price:,.0f}원", "API 오류", {"error": str(buy_result)})
                            
                    except Exception as e:
                        print(f"❌ 실거래 매수 오류: {e}")
                        log_trade(ticker, "매수 오류", f"주문 오류: {price:,.0f}원", "예외 발생", {"error": str(e)})
            
            # 실거래 매도 로직
            for position in demo_positions[:]:
                if price >= position['target_sell_price']:
                    try:
                        sell_result = execute_sell_order(ticker, position['quantity'], price)
                        if sell_result and sell_result.get('uuid'):
                            # 매도 성공 시 포지션 제거 및 수익 계산
                            sell_amount = position['quantity'] * price * (1 - fee_rate)
                            buy_cost = position['quantity'] * position['actual_buy_price']
                            net_profit = sell_amount - buy_cost
                            
                            demo_positions.remove(position)
                            save_trading_state(ticker, demo_positions, demo_mode)
                            
                            demo_balance += sell_amount
                            total_realized_profit += net_profit
                            
                            # profits.json에 수익 저장
                            profits_data = load_profits_data()
                            current_profit = profits_data.get(ticker, 0)
                            profits_data[ticker] = current_profit + net_profit
                            save_profits_data(profits_data)
                            
                            sell_reason = f"목표 수익률 달성"
                            sell_details = {
                                "sell_price": f"{price:,.0f}원",
                                "quantity": f"{position['quantity']:.8f}개",
                                "profit": f"{net_profit:,.0f}원",
                                "profit_rate": f"{(net_profit/buy_cost*100):+.2f}%",
                                "order_id": sell_result.get('uuid')
                            }
                            log_trade(ticker, "실거래 매도", f"{price:,.0f}원 ({position['quantity']:.6f}개) 수익: {net_profit:,.0f}원", sell_reason, sell_details)
                            speak_async(f"실거래 매도 완료, {get_korean_coin_name(ticker)} 수익 {net_profit:,.0f}원")
                            
                            print(f"💰 실거래 매도 완료: {position['quantity']:.8f}개 @ {price:,.0f}원, 수익: {net_profit:,.0f}원")
                            
                            # 매도 횟수 증가
                            trade_counts[ticker]["sell"] += 1
                            if net_profit > 0:
                                trade_counts[ticker]["profitable_sell"] += 1
                                
                        else:
                            print(f"❌ 실거래 매도 실패: API 응답 오류")
                            log_trade(ticker, "매도 실패", f"주문 실패: {price:,.0f}원", "API 오류", {"error": str(sell_result)})
                            
                    except Exception as e:
                        print(f"❌ 실거래 매도 오류: {e}")
                        log_trade(ticker, "매도 오류", f"주문 오류: {price:,.0f}원", "예외 발생", {"error": str(e)})


        
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
    
    # 7. 코인별 그리드 설정 탭
    coin_frame = ttk.Frame(notebook)
    notebook.add(coin_frame, text='코인별 설정')
    
    # 상단 안내 메시지
    info_label = ttk.Label(coin_frame, text="ℹ️ 코인별로 다른 그리드 수와 가격범위 기간을 설정할 수 있습니다.", foreground="blue")
    info_label.grid(row=0, column=0, columnspan=4, sticky='w', padx=5, pady=(5, 10))
    
    # 코인별 설정 변수들
    coin_vars = {}
    
    # 헤더
    ttk.Label(coin_frame, text="코인", font=('Helvetica', 9, 'bold')).grid(row=1, column=0, padx=5, pady=2)
    ttk.Label(coin_frame, text="그리드 수", font=('Helvetica', 9, 'bold')).grid(row=1, column=1, padx=5, pady=2)
    ttk.Label(coin_frame, text="가격범위 기간(일)", font=('Helvetica', 9, 'bold')).grid(row=1, column=2, padx=5, pady=2)
    ttk.Label(coin_frame, text="변동성 배수", font=('Helvetica', 9, 'bold')).grid(row=1, column=3, padx=5, pady=2)
    
    # 코인별 설정 입력 필드
    coins = [
        ('KRW-BTC', '비트코인'),
        ('KRW-ETH', '이더리움'),
        ('KRW-XRP', '리플')
    ]
    
    for i, (ticker, name) in enumerate(coins, start=2):
        coin_config = current_config.get('coin_specific_grids', {}).get(ticker, {})
        
        # 코인 이름
        ttk.Label(coin_frame, text=name).grid(row=i, column=0, sticky='w', padx=5, pady=2)
        
        # 그리드 수
        grid_var = tk.StringVar(value=str(coin_config.get('grid_count', 20)))
        grid_entry = ttk.Entry(coin_frame, textvariable=grid_var, width=10)
        grid_entry.grid(row=i, column=1, padx=5, pady=2)
        
        # 가격범위 기간
        days_var = tk.StringVar(value=str(coin_config.get('price_range_days', 7)))
        days_entry = ttk.Entry(coin_frame, textvariable=days_var, width=10)
        days_entry.grid(row=i, column=2, padx=5, pady=2)
        
        # 변동성 배수
        vol_var = tk.StringVar(value=str(coin_config.get('volatility_multiplier', 1.0)))
        vol_entry = ttk.Entry(coin_frame, textvariable=vol_var, width=10)
        vol_entry.grid(row=i, column=3, padx=5, pady=2)
        
        coin_vars[ticker] = {
            'grid_count': grid_var,
            'price_range_days': days_var,
            'volatility_multiplier': vol_var
        }
    
    # 리셋 버튼
    def reset_coin_defaults():
        default_values = {
            'KRW-BTC': {'grid_count': 20, 'price_range_days': 7, 'volatility_multiplier': 1.0},
            'KRW-ETH': {'grid_count': 25, 'price_range_days': 5, 'volatility_multiplier': 1.2},
            'KRW-XRP': {'grid_count': 30, 'price_range_days': 3, 'volatility_multiplier': 1.5}
        }
        
        for ticker, values in default_values.items():
            if ticker in coin_vars:
                coin_vars[ticker]['grid_count'].set(str(values['grid_count']))
                coin_vars[ticker]['price_range_days'].set(str(values['price_range_days']))
                coin_vars[ticker]['volatility_multiplier'].set(str(values['volatility_multiplier']))
    
    reset_btn = ttk.Button(coin_frame, text="기본값 복원", command=reset_coin_defaults)
    reset_btn.grid(row=len(coins)+2, column=0, columnspan=2, pady=10, sticky='w', padx=5)
    
    # 도움말 메시지
    help_text = """ℹ️ 도움말:
• 그리드 수: 해당 코인의 기본 그리드 개수 (자동모드에서 시장상황에 따라 동적 조정됨)
• 가격범위 기간: 그리드 범위 계산에 사용할 과거 데이터 기간
• 변동성 배수: 변동성에 따른 그리드 수 조정 강도 (높을수록 더 많이 조정)"""
    
    help_label = ttk.Label(coin_frame, text=help_text, foreground="gray", font=('Helvetica', 8))
    help_label.grid(row=len(coins)+3, column=0, columnspan=4, sticky='w', padx=5, pady=5)

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
            
            # 코인별 설정 저장
            if 'coin_specific_grids' not in current_config:
                current_config['coin_specific_grids'] = {}
            
            for ticker in coin_vars:
                try:
                    grid_count = int(coin_vars[ticker]['grid_count'].get())
                    price_range_days = int(coin_vars[ticker]['price_range_days'].get())
                    volatility_multiplier = float(coin_vars[ticker]['volatility_multiplier'].get())
                    
                    current_config['coin_specific_grids'][ticker] = {
                        'enabled': True,
                        'grid_count': max(5, min(100, grid_count)),  # 5-100 범위 제한
                        'price_range_days': max(1, min(30, price_range_days)),  # 1-30일 범위
                        'volatility_multiplier': max(0.1, min(3.0, volatility_multiplier)),  # 0.1-3.0 범위
                        'min_grid_count': 5,
                        'max_grid_count': 100
                    }
                except ValueError:
                    # 잘못된 입력이 있으면 기본값 사용
                    messagebox.showwarning("입력 오류", f"{get_korean_coin_name(ticker)} 설정에 잘못된 값이 있어 기본값을 사용합니다.")
                    continue

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
    root.title("그리드 투자 자동매매 대시보드 v3.0")
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
    market_status_labels = {}  # 시장 상태 라벨
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
        
        # 시장 상태 (새로 추가)
        market_status_labels[ticker] = ttk.Label(ticker_frame, text="📊 분석중", style="Gray.TLabel", font=('Helvetica', 8))
        market_status_labels[ticker].grid(row=i*6+1, column=3, columnspan=2, sticky='w', padx=3)
        
        # 상세 정보
        detail_labels[ticker] = {
            'profit': ttk.Label(ticker_frame, text="총수익: 0원", style="Gray.TLabel"),
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
    main_button_frame.grid_columnconfigure(0, weight=3)  # 거래시작 버튼 영역 (30% 비율)
    main_button_frame.grid_columnconfigure(1, weight=2)  # 자동모드 버튼 영역 (20% 비율)  
    main_button_frame.grid_columnconfigure(2, weight=2)  # 최적화 버튼 영역 (20% 비율)
    main_button_frame.grid_columnconfigure(3, weight=3)  # 고급설정 버튼 영역 (30% 비율)
    
    # 버튼 스타일 정의
    button_style = ttk.Style()
    button_style.configure('Small.TButton', font=('Helvetica', 9), padding=(2, 0))
    button_style.configure('Small.TRadiobutton', font=('Helvetica', 8))  # 거래 모드 선택 글씨 크기 30% 축소

    # 거래 모드 선택 (라디오 버튼)
    trade_mode_frame = ttk.LabelFrame(settings_frame, text="📊 거래 모드 선택")
    trade_mode_frame.grid(row=8, column=0, columnspan=2, sticky='ew', padx=3, pady=3)
    
    demo_var = tk.IntVar(value=config.get("demo_mode", 1))
    
    demo_radio = ttk.Radiobutton(trade_mode_frame, text="🧪 데모 모드 (가상 거래)", 
                                variable=demo_var, value=1, style='Small.TRadiobutton')
    demo_radio.grid(row=0, column=0, sticky='w', padx=5, pady=2)
    
    real_radio = ttk.Radiobutton(trade_mode_frame, text="💰 실거래 모드 (실제 거래)", 
                                variable=demo_var, value=0, style='Small.TRadiobutton')
    real_radio.grid(row=0, column=1, sticky='w', padx=5, pady=2)
    
    # 거래 모드 설명 라벨
    mode_info_label = ttk.Label(trade_mode_frame, 
                               text="데모: 안전한 테스트 | 실거래: API 키 필요",
                               font=('Helvetica', 8), foreground='gray')
    mode_info_label.grid(row=1, column=0, columnspan=2, sticky='w', padx=5, pady=(0, 5))
    
    # 초기 자동거래 상태 설정
    update_auto_status()

    def show_trading_log_popup():
        """실시간 거래 로그 팝업창 표시"""
        global current_log_popup, current_log_tree
        
        # 이미 팝업이 열려있다면 포커스만 이동
        if current_log_popup and current_log_popup.winfo_exists():
            current_log_popup.lift()
            current_log_popup.focus_set()
            return
        
        popup = tk.Toplevel(root)
        popup.title("실시간 거래 로그")
        popup.geometry("800x500")
        popup.resizable(True, True)
        
        # 팝업 창을 부모 창 중앙에 위치
        popup.transient(root)
        popup.grab_set()
        
        current_log_popup = popup
        
        # 로그 트리뷰 생성
        log_tree_popup = ttk.Treeview(popup, columns=("시간", "코인", "종류", "가격"), show='headings')
        log_tree_popup.heading("시간", text="시간")
        log_tree_popup.heading("코인", text="코인")
        log_tree_popup.heading("종류", text="종류")
        log_tree_popup.heading("가격", text="내용")
        log_tree_popup.column("시간", width=120, anchor='center')
        log_tree_popup.column("코인", width=80, anchor='center')
        log_tree_popup.column("종류", width=100, anchor='center')
        log_tree_popup.column("가격", width=400, anchor='w')
        
        # 스크롤바 추가
        scrollbar_popup = ttk.Scrollbar(popup, orient='vertical', command=log_tree_popup.yview)
        log_tree_popup.configure(yscrollcommand=scrollbar_popup.set)
        scrollbar_popup.pack(side='right', fill='y')
        log_tree_popup.pack(side='left', expand=True, fill='both')
        
        # 기존 로그 로드
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
                all_logs = []
                
                # 티커별 로그를 모두 수집
                for ticker, ticker_logs in logs.items():
                    for log_entry in ticker_logs:
                        full_log = log_entry.copy()
                        full_log['ticker'] = ticker
                        all_logs.append(full_log)
                
                # 시간순으로 정렬
                all_logs.sort(key=lambda x: x.get('time', ''))
                
                # 트리뷰에 추가
                for log_entry in all_logs:
                    ticker = log_entry.get('ticker', 'SYSTEM')
                    action = log_entry.get('action', '')
                    price_info = log_entry.get('price', '')
                    log_time = log_entry.get('time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    log_tree_popup.insert('', 'end', values=(log_time, ticker, action, price_info))
                    
                # 최신 로그가 보이도록 스크롤
                if all_logs:
                    log_tree_popup.yview_moveto(1)
        except (FileNotFoundError, json.JSONDecodeError):
            # 로그 파일이 없거나 손상된 경우 빈 상태로 시작
            pass
        
        current_log_tree = log_tree_popup
        
        def on_popup_close():
            global current_log_popup, current_log_tree
            current_log_popup = None
            current_log_tree = None
            popup.destroy()
        
        # 닫기 이벤트 바인딩
        popup.protocol("WM_DELETE_WINDOW", on_popup_close)
        
        # 닫기 버튼 프레임
        button_frame = ttk.Frame(popup)
        button_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(button_frame, text="닫기", command=on_popup_close).pack(side='right')
        
        return log_tree_popup

    def add_log_to_gui(log_entry):
        """실시간 로그 팝업 업데이트"""
        global current_log_tree, current_log_popup
        
        # 팝업이 열려있고 유효할 때만 실시간 업데이트
        if (current_log_popup and current_log_tree and 
            hasattr(current_log_popup, 'winfo_exists') and 
            current_log_popup.winfo_exists()):
            
            try:
                ticker = log_entry.get('ticker', 'SYSTEM')
                action = log_entry.get('action', '')
                price_info = log_entry.get('price', '')
                log_time = log_entry.get('time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                
                # 새 로그를 트리뷰에 추가
                current_log_tree.insert('', 'end', values=(log_time, ticker, action, price_info))
                
                # 최신 로그가 보이도록 스크롤
                current_log_tree.yview_moveto(1)
                
            except Exception as e:
                print(f"로그 팝업 업데이트 오류: {e}")

    def load_previous_trading_state():
        """이전 거래 상태를 로드하여 이어서 거래할 수 있도록 함"""
        try:
            # 거래 상태 파일과 수익 데이터 확인
            has_trading_state = False
            has_profits = False
            
            # trading_state.json 확인
            if os.path.exists(state_file):
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    for key, positions in state_data.items():
                        if positions:  # 빈 리스트가 아닌 경우
                            has_trading_state = True
                            break
            
            # profits.json 확인
            if os.path.exists(profit_file):
                with open(profit_file, 'r', encoding='utf-8') as f:
                    profit_data = json.load(f)
                    if profit_data:  # 빈 딕셔너리가 아닌 경우
                        has_profits = True
            
            # trade_logs.json 확인
            has_trade_logs = False
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
                    for ticker_logs in log_data.values():
                        if ticker_logs:  # 빈 리스트가 아닌 경우
                            has_trade_logs = True
                            break
            
            if has_trading_state or has_profits or has_trade_logs:
                message = "이전 거래 데이터가 발견되었습니다.\n\n"
                if has_trading_state:
                    message += "• 보유 포지션 데이터 존재\n"
                if has_profits:
                    message += "• 수익 데이터 존재\n"
                if has_trade_logs:
                    message += "• 거래 로그 데이터 존재\n"
                    
                message += "\n이어서 거래하시겠습니까?\n\n"
                message += "'예': 기존 데이터를 바탕으로 거래 재개\n"
                message += "      - 수익권 포지션은 자동 매도 후 투자금에 반영\n"
                message += "      - 손실권 포지션은 유지하여 회복 대기\n"
                message += "'아니오': 모든 데이터 초기화 후 새로 시작"
                
                response = messagebox.askyesno("거래 상태 복구", message)
                return response
            return False
        except Exception as e:
            print(f"거래 상태 로드 확인 오류: {e}")
            return False

    def toggle_trading():
        """거래 시작/중지 로직 통합 (개선된 오류 처리)"""
        # 거래 중지 로직
        if active_trades:
            print("🛑 거래 중지 중...")
            for ticker, stop_event in active_trades.items():
                stop_event.set()
                print(f"   - {get_korean_coin_name(ticker)} 거래 중지 신호 전송")
            active_trades.clear()  # active_trades 딕셔너리 클리어
            
            # 자동 최적화 스케줄러도 중지
            auto_scheduler.stop_auto_optimization()
            print("🛑 자동 최적화 스케줄러 중지")
            
            toggle_button.config(text="거래 시작")
            print("✅ 모든 거래가 중지되었습니다.")
            return

        # 거래 시작 로직
        print("🚀 거래 시작 준비 중...")
        
        # API 초기화 확인
        if not demo_var.get():
            print("🔑 Upbit API 초기화 확인 중...")
            if not initialize_upbit():
                error_msg = "업비트 API 키가 유효하지 않습니다.\n\n해결 방법:\n1. 고급설정에서 API 키를 확인하세요\n2. 데모 모드로 테스트해보세요"
                messagebox.showerror("API 오류", error_msg)
                print("❌ API 초기화 실패")
                return
            print("✅ API 초기화 성공")
        else:
            print("🧪 데모 모드로 거래 시작")

        selected_tickers = [ticker for ticker, var in ticker_vars.items() if var.get()]
        if not selected_tickers:
            messagebox.showwarning("경고", "거래할 코인을 선택해주세요.")
            print("❌ 선택된 코인이 없습니다")
            return
        
        print(f"📊 선택된 코인: {', '.join([get_korean_coin_name(t) for t in selected_tickers])}")

        # 이전 거래 상태 로드 확인
        should_resume = load_previous_trading_state()
        
        # 거래 횟수를 거래 로그 기반으로 정확하게 초기화
        print("📈 거래 통계 초기화 중...")
        initialize_trade_counts_from_logs()

        try:
            print("⚙️ 설정 저장 중...")
            # 현재 UI 설정값을 config에 저장
            config["total_investment"] = amount_entry.get()
            config["grid_count"] = grid_entry.get()
            config["period"] = period_combo.get()
            config["target_profit_percent"] = target_entry.get()
            config["demo_mode"] = demo_var.get()
            config["auto_grid_count"] = auto_grid_var.get()
            
            # 자동 모드에서는 거래 시작 시 최적화 실행
            if config.get('auto_trading_mode', False):
                print("🚀 자동 모드 활성화 - 거래 시작 전 최적화 실행...")
                coin_grid_manager.force_optimization_for_all_coins()
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
            
            # 자동 모드에서 거래 시작 시 자동 최적화 스케줄러도 시작
            if config.get('auto_trading_mode', False):
                print("🤖 자동 최적화 스케줄러 시작...")
                auto_scheduler.start_auto_optimization(update_config)

            total_investment = float(amount_entry.get())
            grid_count = int(grid_entry.get())
            period = period_combo.get()
            demo_mode = demo_var.get()
            target_profit_percent_str = target_entry.get()
            
            # 거래 재개 시 수익 재투자 처리
            if should_resume:
                # 수익금을 포함한 업데이트된 투자금 계산 (force_update=True로 강제 업데이트)
                updated_investment, total_profit = update_investment_with_profits(total_investment, force_update=True)
                if total_profit > 0:
                    # UI에 업데이트된 투자금 반영
                    amount_entry.delete(0, tk.END)
                    amount_entry.insert(0, str(int(updated_investment)))
                    total_investment = updated_investment
                    
                    # config.json 파일에도 업데이트된 투자금 저장
                    config['total_investment'] = str(int(updated_investment))
                    save_config(config)
                    
                    # 자동모드인 경우 그리드 개수도 재계산
                    if auto_grid_var.get() and config.get('auto_trading_mode', False):
                        representative_ticker = selected_tickers[0] if selected_tickers else "KRW-BTC"
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
                            grid_count = new_grid_count

            # 자동 그리드 개수 계산 (재개가 아닌 경우만)
            if auto_grid_var.get() and not should_resume:
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
        print(f"🎯 {len(selected_tickers)}개 코인 거래 스레드 시작 중...")
        
        for ticker in selected_tickers:
            if ticker not in active_trades:
                coin_name = get_korean_coin_name(ticker)
                print(f"   🚀 {coin_name} 거래 스레드 시작 중...")
                
                stop_event = threading.Event()
                active_trades[ticker] = stop_event
                
                # 거래 시작 상태 표시
                update_gui_args = ('status', f"상태: {coin_name} 시작 중...", "Blue.TLabel", False, False)
                gui_queue.put((update_gui_args[0], ticker, update_gui_args[1:]))
                
                trade_thread = threading.Thread(
                    target=grid_trading,
                    args=(
                        ticker, grid_count, total_investment, demo_mode,
                        target_profit_percent_str, period, stop_event, gui_queue,
                        total_profit_label, total_profit_rate_label,
                        all_ticker_total_values, all_ticker_start_balances, profits_data, should_resume
                    ),
                    daemon=True
                )
                trade_thread.start()
                print(f"   ✅ {coin_name} 거래 스레드 시작 완료")
                
                # 상태를 보다 구체적으로 업데이트
                status_labels[ticker].config(text=f"상태: {coin_name} 준비 완료", style="Blue.TLabel")
        
        # 모든 거래 스레드 시작 완료
        print(f"🎉 모든 거래 스레드 시작 완료! ({len(selected_tickers)}개 코인)")
        print(f"   - 거래 모드: {'데모 모드' if demo_var.get() else '실제 거래'}")
        print(f"   - 투자 금액: {total_investment:,.0f}원")
        print(f"   - 그리드 개수: {grid_count}개")
        print("   - 각 코인의 상세 정보는 위의 로그를 확인하세요.")

    # toggle_trading 함수 정의 후 버튼들 생성
    # 거래시작 버튼
    toggle_button = ttk.Button(main_button_frame, text="거래 시작", command=toggle_trading)
    toggle_button.grid(row=0, column=0, padx=(0, 5), sticky='nsew')
    
    # 자동모드 토글 버튼
    auto_toggle_btn = ttk.Button(main_button_frame, text="🤖 자동모드", command=toggle_auto_mode, style='Small.TButton')
    auto_toggle_btn.grid(row=0, column=1, padx=(2, 2), sticky='nsew')
    
    # 최적화 강제 실행 함수
    def force_optimization():
        """최적화를 강제로 실행"""
        try:
            results = coin_grid_manager.force_optimization_for_all_coins()
            
            # 차트 업데이트 트리거
            for ticker in results.keys():
                if ticker in chart_data:
                    update_chart(ticker, int(config.get("period", 7)))
            
            # 결과 메시지 생성
            result_msg = "자동 최적화 완료!\n\n"
            for ticker, result in results.items():
                coin_name = get_korean_coin_name(ticker)
                result_msg += f"• {coin_name}: {result['period']}일/{result['grid_count']}그리드\n"
            
            messagebox.showinfo("최적화 완료", result_msg)
        except Exception as e:
            messagebox.showerror("최적화 오류", f"최적화 실행 중 오류가 발생했습니다:\n{e}")
    
    # 최적화 버튼
    optimize_btn = ttk.Button(main_button_frame, text="🔍 최적화", command=force_optimization, style='Small.TButton')
    optimize_btn.grid(row=0, column=2, padx=(2, 2), sticky='nsew')
    
    # 설정 버튼
    settings_btn = ttk.Button(main_button_frame, text="⚙️ 고급설정", command=lambda: open_settings_window(root, config, update_config, None), style='Small.TButton')
    settings_btn.grid(row=0, column=3, padx=(2, 0), sticky='nsew')

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
               command=lambda: clear_all_data(None, detail_labels, tickers, total_profit_label, total_profit_rate_label, all_ticker_total_values, all_ticker_start_balances, all_ticker_realized_profits)).pack(side='left', padx=(5, 5))
    ttk.Button(button_row1, text="🔄 로그 복구", 
               command=restore_logs_from_backup).pack(side='left', padx=(5, 2))
    ttk.Button(button_row1, text="📊 거래 로그", 
               command=show_trading_log_popup).pack(side='left', padx=(2, 2))
    ttk.Button(button_row1, text="⚡ 수동 최적화", 
               command=perform_manual_optimization).pack(side='left', padx=(2, 0))

    def clear_all_data(log_tree, detail_labels, tickers, total_profit_label, total_profit_rate_label, all_ticker_total_values, all_ticker_start_balances, all_ticker_realized_profits):
        # 안전 장치: 2단계 확인
        confirm1 = messagebox.askquestion(
            "데이터 초기화 경고", 
            "⚠️ 주의: 모든 거래 데이터가 영구적으로 \n삭제됩니다. (거래로그, 수익데이터, 포지션)\n\n정말로 초기화하시겠습니까?",
            icon='warning'
        )
        
        if confirm1 != 'yes':
            return
        
        # 2차 확인: 더 엄격한 경고
        confirm2 = messagebox.askquestion(
            "최종 확인", 
            "🚨 마지막 경고!\n\n이 작업은 되돌릴 수 없습니다.\n다음 데이터가 완전히 삭제됩니다:\n\n• 모든 거래 로그\n• 수익 데이터\n• 현재 포지션\n\n정말로 계속하시겠습니까?",
            icon='error'
        )
        
        if confirm2 != 'yes':
            return
        
        # 로그 백업 생성
        try:
            backup_logs_before_clear()
            messagebox.showinfo("백업 완료", "기존 로그가 'data/backup' 폴더에 백업되었습니다.")
        except Exception as e:
            print(f"백업 오류: {e}")
        
        # log_tree는 더 이상 사용하지 않음 (팝업으로 대체)

        # 2. 각 티커별 상세 정보 초기화
        # 2. 각 티커별 상세 정보 초기화 (이 부분은 이미 clear_all_data 함수 내에 있으므로 중복 제거)
        for ticker in tickers:
            detail_labels[ticker]['profit'].config(text="총수익: 0원", style="Gray.TLabel")
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
            
            # 시장 상태 라벨 초기화
            market_status_labels[ticker].config(text="📊 분석중", style="Gray.TLabel")
            
            # 매수/매도 개수 초기화
            trade_counts[ticker]["buy"] = 0
            trade_counts[ticker]["sell"] = 0
            trade_counts[ticker]["profitable_sell"] = 0


        # Clear tickers and related data structures
        all_ticker_total_values.clear()
        all_ticker_start_balances.clear()
        all_ticker_realized_profits.clear()
        
        # 차트 데이터 초기화
        chart_data.clear()
        
        # 거래 상태 파일들 삭제
        try:
            for ticker in tickers:
                state_file_path = f"trading_state_{ticker.replace('-', '_')}.json"
                if os.path.exists(state_file_path):
                    os.remove(state_file_path)
                    
            # 거래 로그 파일 초기화
            if os.path.exists(log_file):
                with open(log_file, 'w', encoding='utf-8') as f:
                    json.dump({}, f, ensure_ascii=False, indent=2)
                    
            # 수익 데이터 파일 초기화
            if os.path.exists(profit_file):
                with open(profit_file, 'w', encoding='utf-8') as f:
                    json.dump({}, f, ensure_ascii=False, indent=2)
                    
            # 거래 상태 파일 초기화
            if os.path.exists(state_file):
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump({}, f, ensure_ascii=False, indent=2)
                    
        except Exception as e:
            print(f"파일 삭제/초기화 오류: {e}")
        
        # 차트 새로고침 (그리드 리셋)
        try:
            current_period = period_combo.get()
            for ticker in tickers:
                update_chart(ticker, current_period)
        except Exception as e:
            print(f"차트 새로고침 오류: {e}")

        # Reset total profit labels
        total_profit_label.config(text="총 실현수익: 0원", style="Black.TLabel")
        total_profit_rate_label.config(text="총 실현수익률: (0.00%)", style="Black.TLabel")

        # Clear JSON files (redundant with above, keeping for compatibility)
        for file_path in [profit_file, log_file, state_file]:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f, ensure_ascii=False, indent=2)  # Write an empty JSON object
            except Exception as e:
                print(f"Error clearing {file_path}: {e}")

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
        
        # 자동 모드에서 최적화된 기간 표시
        if config.get('auto_trading_mode', False):
            try:
                optimal_period, optimal_grid = coin_grid_manager.find_optimal_period_and_grid(ticker)
                title = f'{ticker} 가격 차트 ({optimal_period}일/그리드{optimal_grid}개)'
            except Exception as e:
                title = f'{ticker} 가격 차트 (자동최적화)'
        else:
            title = f'{ticker} 가격 차트'
            
        ax.set_title(title, fontsize=10)
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
    canvas.get_tk_widget().pack(fill='both', expand=True)
    
    # 네비게이션 툴바 추가 (확대/축소/팬 기능)
    toolbar = NavigationToolbar2Tk(canvas, chart_container)
    toolbar.update()
    
    # 마우스 휠을 사용한 확대/축소 기능
    def on_scroll(event):
        if event.inaxes is None:
            return
        
        # 현재 축 범위 가져오기
        ax = event.inaxes
        xdata = event.xdata
        ydata = event.ydata
        
        if xdata is None or ydata is None:
            return
            
        # 확대/축소 비율
        base_scale = 1.1
        
        # 휠 방향에 따른 확대/축소
        if event.button == 'up':
            scale_factor = 1 / base_scale
        elif event.button == 'down':
            scale_factor = base_scale
        else:
            return
            
        # 현재 축 범위
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        
        # 마우스 포인터를 중심으로 확대/축소
        xrange = xlim[1] - xlim[0]
        yrange = ylim[1] - ylim[0]
        
        new_xrange = xrange * scale_factor
        new_yrange = yrange * scale_factor
        
        # 마우스 포인터 위치 기준으로 새로운 범위 계산
        x_center_ratio = (xdata - xlim[0]) / xrange
        y_center_ratio = (ydata - ylim[0]) / yrange
        
        new_xlim = [xdata - new_xrange * x_center_ratio, 
                   xdata + new_xrange * (1 - x_center_ratio)]
        new_ylim = [ydata - new_yrange * y_center_ratio, 
                   ydata + new_yrange * (1 - y_center_ratio)]
        
        ax.set_xlim(new_xlim)
        ax.set_ylim(new_ylim)
        
        canvas.draw_idle()
    
    # 마우스 휠 이벤트 연결
    canvas.mpl_connect('scroll_event', on_scroll)
    
    # 키보드 단축키를 통한 확대/축소 기능
    def on_key_press(event):
        if event.inaxes is None:
            return
            
        ax = event.inaxes
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        
        scale_factor = 1.1
        
        # 현재 범위의 중심점 계산
        x_center = (xlim[0] + xlim[1]) / 2
        y_center = (ylim[0] + ylim[1]) / 2
        
        xrange = xlim[1] - xlim[0]
        yrange = ylim[1] - ylim[0]
        
        # 이동 거리 (현재 범위의 10%)
        pan_factor = 0.1
        x_move = xrange * pan_factor
        y_move = yrange * pan_factor
        
        if event.key == '+' or event.key == '=':  # 확대
            new_xrange = xrange / scale_factor
            new_yrange = yrange / scale_factor
            # 중심점 기준으로 새로운 범위 설정
            new_xlim = [x_center - new_xrange/2, x_center + new_xrange/2]
            new_ylim = [y_center - new_yrange/2, y_center + new_yrange/2]
        elif event.key == '-':  # 축소
            new_xrange = xrange * scale_factor
            new_yrange = yrange * scale_factor
            # 중심점 기준으로 새로운 범위 설정
            new_xlim = [x_center - new_xrange/2, x_center + new_xrange/2]
            new_ylim = [y_center - new_yrange/2, y_center + new_yrange/2]
        elif event.key == 'r':  # 리셋 (전체 범위 표시)
            # 전체 데이터 범위로 리셋
            ax.relim()
            ax.autoscale()
            canvas.draw_idle()
            return
        elif event.key == 'left':  # 왼쪽으로 이동
            new_xlim = [xlim[0] - x_move, xlim[1] - x_move]
            new_ylim = ylim
        elif event.key == 'right':  # 오른쪽으로 이동
            new_xlim = [xlim[0] + x_move, xlim[1] + x_move]
            new_ylim = ylim
        elif event.key == 'up':  # 위로 이동
            new_xlim = xlim
            new_ylim = [ylim[0] + y_move, ylim[1] + y_move]
        elif event.key == 'down':  # 아래로 이동
            new_xlim = xlim
            new_ylim = [ylim[0] - y_move, ylim[1] - y_move]
        else:
            return
        
        ax.set_xlim(new_xlim)
        ax.set_ylim(new_ylim)
        
        canvas.draw_idle()
    
    # 키보드 이벤트 연결
    canvas.mpl_connect('key_press_event', on_key_press)
    
    # 마우스 드래그를 통한 팬(이동) 기능
    drag_data = {'pressed': False, 'start_x': None, 'start_y': None, 'xlim': None, 'ylim': None, 'ax': None}
    
    def on_button_press(event):
        """마우스 버튼 누름 이벤트"""
        if event.button == 1 and event.inaxes is not None and event.xdata is not None and event.ydata is not None:  # 좌클릭
            drag_data['pressed'] = True
            drag_data['start_x'] = event.xdata
            drag_data['start_y'] = event.ydata
            drag_data['ax'] = event.inaxes
            drag_data['xlim'] = list(event.inaxes.get_xlim())
            drag_data['ylim'] = list(event.inaxes.get_ylim())
    
    def on_button_release(event):
        """마우스 버튼 릴리즈 이벤트"""
        if drag_data['pressed']:
            drag_data['pressed'] = False
            drag_data['start_x'] = None
            drag_data['start_y'] = None
            drag_data['ax'] = None
            drag_data['xlim'] = None
            drag_data['ylim'] = None
    
    def on_motion(event):
        """마우스 이동 이벤트 (드래그 및 호버)"""
        # 드래그 기능
        if (drag_data['pressed'] and 
            event.inaxes == drag_data['ax'] and 
            event.xdata is not None and 
            event.ydata is not None and
            drag_data['start_x'] is not None and
            drag_data['start_y'] is not None):
            
            # 드래그 거리 계산
            dx = drag_data['start_x'] - event.xdata
            dy = drag_data['start_y'] - event.ydata
            
            # 원래 축 범위 기준으로 새로운 범위 계산
            xlim = drag_data['xlim']
            ylim = drag_data['ylim']
            
            new_xlim = [xlim[0] + dx, xlim[1] + dx]
            new_ylim = [ylim[0] + dy, ylim[1] + dy]
            
            # 축 범위 업데이트
            drag_data['ax'].set_xlim(new_xlim)
            drag_data['ax'].set_ylim(new_ylim)
            
            canvas.draw_idle()
        elif not drag_data['pressed']:
            # 드래그 중이 아닐 때만 호버 기능 호출
            on_hover(event)
    
    # 마우스 이벤트 연결
    canvas.mpl_connect('button_press_event', on_button_press)
    canvas.mpl_connect('button_release_event', on_button_release)
    canvas.mpl_connect('motion_notify_event', on_motion)
    
    # 캔버스가 키보드 포커스를 받을 수 있도록 설정
    canvas.get_tk_widget().focus_set()
    canvas.get_tk_widget().bind('<Button-1>', lambda e: canvas.get_tk_widget().focus_set())

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

    def update_chart(ticker, period):
        """차트 업데이트"""
        if ticker not in charts:
            return
        
        df = get_chart_data(ticker, period)
        if df is None or df.empty:
            return
        
        ax = charts[ticker]
        ax.clear()
        
        # 자동 모드에서 최적화된 기간과 그리드 정보 표시
        if config.get('auto_trading_mode', False):
            try:
                optimal_period, optimal_grid = coin_grid_manager.find_optimal_period_and_grid(ticker)
                title = f'{ticker} 가격 차트 ({optimal_period}일/그리드{optimal_grid}개)'
            except Exception as e:
                # 실제 사용된 기간 정보가 있으면 그것을 사용
                display_period = period
                if ticker in chart_data and len(chart_data[ticker]) >= 6:
                    actual_period = chart_data[ticker][5]
                    if actual_period:
                        display_period = actual_period
                title = f'{ticker} 가격 차트 ({display_period})'
        else:
            # 수동 모드에서는 기존 방식
            display_period = period
            if ticker in chart_data and len(chart_data[ticker]) >= 6:
                actual_period = chart_data[ticker][5]
                if actual_period:
                    display_period = actual_period
            title = f'{ticker} 가격 차트 ({display_period})'
        
        ax.set_title(title, fontsize=10)
        ax.set_xlabel('시간', fontsize=8)
        ax.set_ylabel('가격 (KRW)', fontsize=8)
        ax.tick_params(axis='both', which='major', labelsize=7)
        
        # 가격 라인 그리기
        ax.plot(df.index, df['close'], 'b-', linewidth=1, label='가격')
        
        # 실시간 현재 가격 표시
        try:
            current_price = pyupbit.get_current_price(ticker)
            if current_price and len(df) > 0:
                # 현재 가격 수평선 표시
                ax.axhline(y=current_price, color='orange', linestyle='-', alpha=0.8, linewidth=2, label=f'현재가 ({current_price:,.0f})')
                
                # 차트 우측에 실시간 정보 표시
                realtime_info = f'현재가: {current_price:,.0f}원\n시간: {datetime.now().strftime("%H:%M:%S")}'
                
                # 그리드와 현재 가격의 관계 정보 추가
                if ticker in chart_data and len(chart_data[ticker]) >= 3:
                    high_price, low_price, grid_levels = chart_data[ticker][:3]
                    if grid_levels:
                        # 현재 가격이 어느 그리드 영역에 있는지 표시
                        grid_position = "범위외"
                        if low_price <= current_price <= high_price:
                            for i, level in enumerate(grid_levels):
                                if current_price <= level:
                                    grid_position = f"그리드 {i+1}/{len(grid_levels)}"
                                    break
                        
                        price_ratio = ((current_price - low_price) / (high_price - low_price)) * 100 if high_price != low_price else 50
                        realtime_info += f'\n위치: {grid_position} ({price_ratio:.1f}%)'
                
                ax.text(0.98, 0.02, realtime_info, 
                       transform=ax.transAxes, 
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='orange', alpha=0.8),
                       fontsize=9, horizontalalignment='right', verticalalignment='bottom', fontweight='bold')
        except Exception as e:
            print(f"실시간 가격 표시 오류: {e}")
        
        # 그리드 라인 그리기
        if ticker in chart_data:
            chart_info = chart_data[ticker]
            if len(chart_info) >= 6:
                high_price, low_price, grid_levels, grid_count_info, allocated_amount, actual_period = chart_info
            elif len(chart_info) >= 5:
                high_price, low_price, grid_levels, grid_count_info, allocated_amount = chart_info[:5]
            else:
                high_price, low_price, grid_levels = chart_info[:3]
                grid_count_info = len(grid_levels) - 1 if grid_levels else 0
                allocated_amount = 0
            
            # 그리드 라인 및 현재 가격과의 관계 표시
            try:
                current_price = pyupbit.get_current_price(ticker)
                for i, level in enumerate(grid_levels):
                    # 현재 가격과 그리드 라인의 관계에 따라 색상 변경
                    if current_price:
                        if level > current_price:
                            # 현재가보다 높은 그리드 (매도 영역) - 빨간색
                            color = 'lightcoral'
                            alpha = 0.6
                        elif level < current_price:
                            # 현재가보다 낮은 그리드 (매수 영역) - 초록색
                            color = 'lightgreen'
                            alpha = 0.6
                        else:
                            # 현재가와 비슷한 그리드 - 노란색
                            color = 'yellow'
                            alpha = 0.8
                    else:
                        color = 'gray'
                        alpha = 0.5
                    
                    ax.axhline(y=level, color=color, linestyle='--', alpha=alpha, linewidth=0.8)
                    
                    # 중요한 그리드 라인에 가격 표시
                    if i % 3 == 0:  # 3번째마다 가격 표시
                        ax.text(0.01, level/ax.get_ylim()[1]*0.95, f'{level:,.0f}', 
                               transform=ax.transData, fontsize=7, alpha=0.8,
                               verticalalignment='center', horizontalalignment='left')
                        
            except Exception as e:
                # 실시간 가격 조회 실패시 기본 그리드 표시
                for level in grid_levels:
                    ax.axhline(y=level, color='gray', linestyle='--', alpha=0.5, linewidth=0.5)
            
            ax.axhline(y=high_price, color='green', linestyle='-', alpha=0.8, linewidth=1, label=f'상한선 ({high_price:,.0f})')
            ax.axhline(y=low_price, color='red', linestyle='-', alpha=0.8, linewidth=1, label=f'하한선 ({low_price:,.0f})')
            
            # 그리드 정보 표시
            if grid_count_info > 0:
                grid_gap = (high_price - low_price) / grid_count_info if grid_count_info > 0 else 0
                info_text = f'그리드: {grid_count_info}개 | 간격: {grid_gap:,.0f}원'
                if allocated_amount > 0:
                    amount_per_grid = allocated_amount / grid_count_info if grid_count_info > 0 else 0
                    info_text += f'\n총투자: {allocated_amount:,.0f}원 | 격당: {amount_per_grid:,.0f}원'
                    
                    # 분배 비율 표시 (총 투자금 대비)
                    if hasattr(coin_allocation_system, 'get_total_allocated') and coin_allocation_system.get_total_allocated() > 0:
                        total_allocated = coin_allocation_system.get_total_allocated()
                        allocation_ratio = (allocated_amount / total_allocated) * 100 if total_allocated > 0 else 0
                        info_text += f' | 분배: {allocation_ratio:.1f}%'
                        
                ax.text(0.02, 0.98, info_text, transform=ax.transAxes, 
                       bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', alpha=0.9),
                       fontsize=8, verticalalignment='top', fontweight='bold')

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

    # 실시간 거래 로그는 팝업으로 대체 (하단 프레임 제거)

    # load_initial_logs 함수는 더 이상 필요 없음 (팝업에서 직접 로드)

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
                elif key == 'market_status':
                    market_status, market_details = args
                    # 상태에 따른 색상 결정
                    if market_status == "급등":
                        style = "Red.TLabel" if "초급등" in market_details else "Orange.TLabel"
                        icon = "🚀" if "초급등" in market_details else "📈"
                    elif market_status == "급락":
                        style = "Blue.TLabel" if "초급락" in market_details else "Purple.TLabel" 
                        icon = "💥" if "초급락" in market_details else "📉"
                    elif market_status == "고점권":
                        style = "Red.TLabel"
                        icon = "🔺"
                    elif market_status == "저점권":
                        style = "Blue.TLabel"
                        icon = "🔻"
                    elif market_status == "박스권":
                        style = "Gray.TLabel"
                        icon = "📊"
                    elif market_status == "상승":
                        style = "Green.TLabel"
                        icon = "⬆️"
                    elif market_status == "하락":
                        style = "Red.TLabel"
                        icon = "⬇️"
                    else:
                        style = "Gray.TLabel"
                        icon = "➡️"
                    
                    # 텍스트가 너무 길면 축약
                    display_text = f"{icon} {market_status}: {market_details}"
                    if len(display_text) > 60:
                        display_text = f"{icon} {market_status}: {market_details[:25]}..."
                    market_status_labels[ticker].config(text=display_text, style=style)
                elif key == 'details':
                    if len(args) == 10:
                        cash, coin_qty, held_value, total_value, profit, profit_percent, total_realized_profit, realized_profit_percent, unrealized_profit, unrealized_profit_percent = args
                    else:
                        # 기존 호환성 유지
                        cash, coin_qty, held_value, total_value, profit, profit_percent, total_realized_profit, realized_profit_percent = args
                        unrealized_profit = profit - total_realized_profit
                        unrealized_profit_percent = 0
                    
                    # 코인 보유량이 0일 때 평가수익을 0으로 강제 설정
                    if coin_qty == 0:
                        held_value = 0
                        unrealized_profit = 0
                        unrealized_profit_percent = 0
                        profit = total_realized_profit  # 실현수익만
                        profit_percent = realized_profit_percent
                    
                    profit_style = get_profit_color_style(profit)
                    realized_profit_style = get_profit_color_style(total_realized_profit)
                    
                    # profit는 실현수익 + 평가수익의 총합이므로 "총수익"으로 표시
                    detail_labels[ticker]['profit'].config(text=f"총수익: {profit:,.0f}원", style=profit_style)
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
                elif key == 'period_info':
                    # 실제 사용된 기간 정보 저장
                    actual_period, high_price, low_price, grid_count = args
                    if ticker not in chart_data:
                        chart_data[ticker] = (0, 0, [], 0, 0, '')
                    
                    # 기존 데이터 유지 하면서 실제 기간 업데이트
                    if len(chart_data[ticker]) >= 6:
                        old_data = chart_data[ticker]
                        chart_data[ticker] = (high_price, low_price, old_data[2], grid_count, old_data[4], actual_period)
                    else:
                        chart_data[ticker] = (high_price, low_price, [], grid_count, 0, actual_period)
                elif key == 'chart_data':
                    if len(args) >= 5:
                        high_price, low_price, grid_levels, grid_count_info, allocated_amount = args
                        # 기존 실제 기간 정보 유지
                        actual_period = chart_data.get(ticker, ('', '', [], 0, 0, ''))[5] if ticker in chart_data and len(chart_data[ticker]) >= 6 else period_combo.get()
                        chart_data[ticker] = (high_price, low_price, grid_levels, grid_count_info, allocated_amount, actual_period)
                    else:
                        high_price, low_price, grid_levels = args
                        actual_period = chart_data.get(ticker, ('', '', [], 0, 0, ''))[5] if ticker in chart_data and len(chart_data[ticker]) >= 6 else period_combo.get()
                        chart_data[ticker] = (high_price, low_price, grid_levels, 0, 0, actual_period)
                    
                    # 실제 사용된 기간으로 차트 업데이트
                    actual_period_to_use = chart_data[ticker][5] if len(chart_data[ticker]) >= 6 else period_combo.get()
                    update_chart(ticker, actual_period_to_use)
                elif key == 'refresh_chart':
                    # 실제 사용된 기간이 있으면 그것을 사용, 없으면 기본값
                    actual_period_to_use = chart_data.get(ticker, ('', '', [], 0, 0, period_combo.get()))[5] if ticker in chart_data and len(chart_data.get(ticker, [])) >= 6 else period_combo.get()
                    update_chart(ticker, actual_period_to_use)
            except Exception as e:
                print(f"GUI 업데이트 오류: {e}")
        root.after(100, process_gui_queue)

    # 설명 라벨 추가
    info_text = "그리드 투자: 설정 기간의 최고가/최저가 범위를 그리드로 분할하여 자동 매수/매도 (v3.0 - 차트/로그 개선)"
    info_label = ttk.Label(settings_frame, text=info_text, font=('Helvetica', 8), foreground='gray')
    info_label.grid(row=8, column=0, columnspan=2, sticky='ew', padx=3, pady=2)
    
    # 차트 업데이트 버튼
    def refresh_charts():
        current_period = period_combo.get()
        for ticker in tickers:
            update_chart(ticker, current_period)
    
    # 차트 상태 표시 및 컨트롤
    chart_status_frame = ttk.Frame(mid_frame)
    chart_status_frame.pack(pady=5)
    
    chart_refresh_btn = ttk.Button(chart_status_frame, text="차트 새로고침", command=refresh_charts)
    chart_refresh_btn.pack(side='left', padx=(0, 5))
    
    # 실시간 업데이트 상태 표시
    global chart_status_label
    chart_status_label = ttk.Label(chart_status_frame, text="📊 실시간 업데이트: 준비중", 
                                  font=('Helvetica', 8), foreground='blue')
    chart_status_label.pack(side='left', padx=(5, 0))

    # 실시간 차트 자동 새로고침 스케줄러
    def auto_refresh_charts():
        """실시간 차트 자동 새로고침 (10초마다)"""
        try:
            current_time = datetime.now().strftime("%H:%M:%S")
            
            # 거래가 활성화되어 있을 때만 차트 자동 업데이트
            if active_trades:
                current_period = period_combo.get()
                updated_count = 0
                for ticker in active_trades.keys():
                    if ticker in charts:
                        # 실시간 차트 업데이트 (그리드와 현재 가격 포함)
                        update_chart(ticker, current_period)
                        updated_count += 1
                
                # 상태 업데이트
                chart_status_label.config(text=f"🔄 실시간 업데이트: 활성 ({updated_count}개 코인) - {current_time}", 
                                        foreground='green')
                        
            # 비활성화 상태에서도 주기적으로 현재 가격 업데이트 (30초마다)
            elif hasattr(auto_refresh_charts, 'update_count'):
                auto_refresh_charts.update_count += 1
                if auto_refresh_charts.update_count >= 3:  # 30초마다 (10초 * 3)
                    auto_refresh_charts.update_count = 0
                    current_period = period_combo.get()
                    selected_tickers = [ticker for ticker, var in ticker_vars.items() if var.get()]
                    updated_count = 0
                    for ticker in selected_tickers:
                        if ticker in charts:
                            update_chart(ticker, current_period)
                            updated_count += 1
                    
                    chart_status_label.config(text=f"⏸️ 주기적 업데이트: 대기중 ({updated_count}개 코인) - {current_time}", 
                                            foreground='orange')
                else:
                    chart_status_label.config(text=f"⏸️ 주기적 업데이트: 대기중 - {current_time}", 
                                            foreground='orange')
            else:
                auto_refresh_charts.update_count = 0
                chart_status_label.config(text=f"📊 실시간 업데이트: 준비중 - {current_time}", 
                                        foreground='blue')
                        
        except Exception as e:
            print(f"차트 자동 새로고침 오류: {e}")
            chart_status_label.config(text=f"❌ 업데이트 오류: {current_time}", foreground='red')
        finally:
            # 10초 후 다시 새로고침
            root.after(10000, auto_refresh_charts)
    
    # 자동 백업 스케줄러 시작
    def periodic_backup_check():
        """1분마다 자동 백업 검사"""
        try:
            auto_backup_logs()
        except Exception as e:
            print(f"자동 백업 검사 오류: {e}")
        finally:
            # 1분 후 다시 검사
            root.after(60000, periodic_backup_check)
    
    # 초기화
    process_gui_queue()
    initialize_upbit()  # 업비트 API 초기화
    
    # 자동 백업 시작
    root.after(5000, periodic_backup_check)  # 5초 후 시작
    
    # 실시간 차트 자동 새로고침 시작
    root.after(15000, auto_refresh_charts)  # 15초 후 시작 (초기 로드 이후)
    
    # 초기 차트 로드
    root.after(1000, refresh_charts)
    
    root.mainloop()

if __name__ == "__main__":
    initialize_files()
    start_dashboard()
