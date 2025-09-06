#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pyupbit
import time
import json
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('xrp_trading.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class XRPTradingBot:
    """XRP 전용 실거래 그리드 트레이딩 봇"""
    
    def __init__(self, config_file: str = None):
        """트레이딩 봇 초기화"""
        if config_file is None:
            # 현재 스크립트의 디렉터리를 기준으로 config.json 경로 설정
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(current_dir, 'config.json')
        self.config_file = config_file
        self.load_config()
        
        self.access_key = self.config.get('upbit_access', '')
        self.secret_key = self.config.get('upbit_secret', '')
        self.upbit = None
        self.ticker = "KRW-XRP"
        self.is_running = False
        self.stop_event = threading.Event()
        
        # 트레이딩 상태
        self.trading_state = {
            'grid_levels': [],
            'grid_orders': {},
            'total_investment': 0,
            'current_krw_balance': 0,
            'current_xrp_balance': 0,
            'initial_krw_balance': 0,
            'initial_xrp_balance': 0,
            'total_profit': 0.0,
            'trade_count': 0,
            'last_grid_check': None,
            'stop_loss_triggered': False,
            'highest_portfolio_value': 0.0,
            'stop_loss_price': None
        }
        
        # 기본 설정값 (config.json에서 오버라이드됨)
        self.default_config = {
            'grid_count': 20,
            'fee_rate': 0.0005,
            'confirmation_buffer': 0.001,  # 0.1%
            'min_order_amount': 5000,  # 최소 주문 금액 5000원
            'max_order_amount': 100000,  # 최대 주문 금액 10만원
            'risk_mode': 'stable',
            'use_limit_orders': True,
            'limit_order_buffer': 0.002,  # 0.2%
            'stop_loss_enabled': True,
            'stop_loss_percentage': 3.0  # 3% 스탑로스
        }
        
        # 거래 로그
        self.trade_logs = []
        self.profits_data = []
        
        # 잔고 조회 캐시 (과도한 API 호출 방지)
        self._balance_cache = {'krw': 0, 'xrp': 0}
        self._balance_cache_time = 0
        self._balance_cache_duration = 5  # 5초 캐시
    
    def load_config(self) -> bool:
        """설정 파일 로드"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                
                # 기본 설정과 파일 설정 병합
                self.config = self.default_config.copy() if hasattr(self, 'default_config') else {}
                self.config.update(file_config)
                
                logger.info(f"✅ 설정 파일 로드 성공: {self.config_file}")
                return True
            else:
                logger.warning(f"⚠️ 설정 파일이 없습니다: {self.config_file}")
                self.config = self.default_config.copy() if hasattr(self, 'default_config') else {}
                return False
                
        except Exception as e:
            logger.error(f"❌ 설정 파일 로드 오류: {e}")
            self.config = self.default_config.copy() if hasattr(self, 'default_config') else {}
            return False
    
    def validate_config(self) -> bool:
        """설정 유효성 검사"""
        try:
            # API 키 확인
            if not self.access_key or self.access_key == "YOUR_UPBIT_ACCESS_KEY":
                logger.error("❌ 업비트 Access Key가 설정되지 않았습니다.")
                logger.info("💡 config.json 파일에서 'upbit_access' 값을 설정해주세요.")
                return False
            
            if not self.secret_key or self.secret_key == "YOUR_UPBIT_SECRET_KEY":
                logger.error("❌ 업비트 Secret Key가 설정되지 않았습니다.")
                logger.info("💡 config.json 파일에서 'upbit_secret' 값을 설정해주세요.")
                return False
            
            # 투자금액 확인
            total_investment = self.config.get('total_investment', 0)
            if total_investment <= 0:
                logger.error("❌ 투자금액이 올바르지 않습니다.")
                return False
            
            logger.info("✅ 설정 검증 완료")
            return True
            
        except Exception as e:
            logger.error(f"❌ 설정 검증 오류: {e}")
            return False
    
    def save_config(self):
        """현재 설정을 파일에 저장"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            logger.info("✅ 설정 파일 저장 완료")
        except Exception as e:
            logger.error(f"❌ 설정 파일 저장 오류: {e}")
    
    def update_initial_balances(self):
        """데모모드/실거래 모드에 따라 초기 잔고 설정 및 config.json 업데이트"""
        try:
            if self.config.get('demo_mode', True):
                # 데모 모드: 투자금액을 기반으로 초기 잔고 설정
                logger.info("🎮 데모 모드: 투자금액 기반 초기 잔고 설정 중...")
                
                # 투자금액을 우선적으로 초기 KRW 잔고로 사용 
                # 메모리의 config 값을 우선 사용 (사용자 입력 반영)
                total_investment = self.config.get('total_investment', 0)
                logger.debug(f"🔍 현재 메모리의 투자금액: {total_investment:,.0f}원")
                
                if total_investment > 0:
                    # 투자금액이 설정된 경우: 해당 금액을 KRW 잔고로 설정
                    demo_krw = total_investment
                    demo_xrp = self.config.get('initial_xrp_balance', 0)
                    logger.info(f"💵 투자금액 기반 설정: {demo_krw:,.0f}원")
                else:
                    # 투자금액이 0인 경우: config.json에서 기존 잔고 사용
                    demo_krw = self.config.get('initial_krw_balance', 300000)
                    demo_xrp = self.config.get('initial_xrp_balance', 0)
                    
                    # 기존 잔고도 0이면 기본값 사용
                    if demo_krw <= 0:
                        demo_krw = 300000  # 기본 30만원
                        logger.info(f"🎯 기본값 사용: {demo_krw:,.0f}원")
                
                account_info = {
                    'krw': demo_krw,
                    'xrp': demo_xrp
                }
                
                logger.info(f"📊 데모 모드 잔고 설정 완료:")
                logger.info(f"   💰 KRW 잔고: {demo_krw:,.0f}원")
                logger.info(f"   🪙 XRP 잔고: {demo_xrp:.6f}")
                logger.info(f"   💵 사용할 투자금액: {total_investment:,.0f}원")
                
            else:
                # 실거래 모드: 업비트 API에서 실제 잔고 조회
                logger.info("💸 실거래 모드: 업비트에서 현재 잔고 조회 중...")
                
                # API가 초기화되지 않은 경우 먼저 초기화
                if not self.upbit:
                    logger.info("🔄 API 초기화 중...")
                    if not self.initialize_api():
                        logger.error("❌ API 초기화 실패로 잔고 업데이트 불가")
                        logger.error("💡 다음을 확인하세요:")
                        logger.error("   1. API 키가 올바른지")
                        logger.error("   2. 네트워크 연결 상태")
                        logger.error("   3. 업비트 API 서버 상태")
                        return False
                
                # 실거래 모드에서는 강제로 캐시를 무효화하여 최신 잔고 조회
                logger.info("🔍 업비트 API에서 최신 계좌 정보 조회 중...")
                self._balance_cache_time = 0  # 캐시 무효화
                account_info = self.get_account_info(force_refresh=True)
            
            # 설정에 초기 잔고 업데이트
            self.config['initial_krw_balance'] = account_info['krw']
            self.config['initial_xrp_balance'] = account_info['xrp']
            self.config['last_balance_update'] = datetime.now().isoformat()
            
            # 실거래 모드에서 잔고가 0인 경우 경고 메시지
            if not self.config.get('demo_mode', True) and account_info['krw'] == 0 and account_info['xrp'] == 0:
                logger.warning("⚠️ 실거래 모드에서 모든 잔고가 0입니다!")
                logger.warning("💡 다음을 확인하세요:")
                logger.warning("   1. 업비트 계정에 실제 자산이 있는지")
                logger.warning("   2. API 키가 올바른 계정의 것인지")
                logger.warning("   3. API 키 권한에 '자산조회'가 포함되어 있는지")
                logger.warning("   4. 현재 IP 주소가 업비트에 등록되어 있는지")
            
            # 트레이딩 상태에도 반영
            self.trading_state['initial_krw_balance'] = account_info['krw']
            self.trading_state['initial_xrp_balance'] = account_info['xrp']
            self.trading_state['current_krw_balance'] = account_info['krw']
            self.trading_state['current_xrp_balance'] = account_info['xrp']
            
            # 현재 XRP 가격으로 총 자산 계산 및 투자금액 자동 설정
            current_price = self.get_current_price()
            if current_price:
                total_asset_value = account_info['krw'] + (account_info['xrp'] * current_price)
                logger.info(f"   💎 총 자산 가치: {total_asset_value:,.0f}원 (KRW: {account_info['krw']:,.0f}원 + XRP: {account_info['xrp']:.6f} × {current_price:,.0f}원)")
                
                # 실거래 모드에서 투자금액 스마트 계산
                if not self.config.get('demo_mode', True):
                    if total_asset_value > 0:
                        # 자산 상황에 따른 투자 전략 결정
                        krw_ratio = account_info['krw'] / total_asset_value
                        xrp_ratio = (account_info['xrp'] * current_price) / total_asset_value
                        
                        logger.info(f"   📊 자산 비율: KRW {krw_ratio:.1%}, XRP {xrp_ratio:.1%}")
                        
                        if krw_ratio >= 0.7:  # KRW 비중이 70% 이상
                            # 충분한 KRW → 적극적 그리드 투자
                            investment = account_info['krw'] * 0.8  # KRW의 80%
                            strategy = "적극적 매수 전략"
                        elif krw_ratio >= 0.3:  # KRW 비중이 30-70%
                            # 균형잡힌 포트폴리오 → 보통 투자
                            investment = account_info['krw'] * 0.6  # KRW의 60%
                            strategy = "균형 투자 전략"
                        elif account_info['krw'] >= 100000:  # KRW가 적어도 10만원 이상
                            # 소액 KRW + XRP 보유 → 보수적 투자
                            investment = account_info['krw'] * 0.5  # KRW의 50%
                            strategy = "보수적 투자 전략"
                        else:
                            # KRW가 너무 적음 → 최소 투자
                            investment = max(account_info['krw'] * 0.3, 10000)  # 최소 1만원
                            strategy = "최소 투자 전략"
                        
                        # 최소/최대 투자금액 제한
                        investment = max(investment, 50000)  # 최소 5만원
                        investment = min(investment, total_asset_value * 0.9)  # 총 자산의 90% 이하
                        
                        self.config['total_investment'] = investment
                        logger.info(f"🧠 {strategy} 적용: {investment:,.0f}원 투자")
                        
                    else:
                        # 잔고가 모두 0원인 경우
                        logger.warning(f"⚠️ 실거래 모드에서 모든 잔고가 0원입니다.")
                        logger.info(f"💡 실거래를 위해 업비트에 KRW를 입금하거나 API 설정을 확인하세요.")
                        self.config['total_investment'] = 0
            
            # config.json 파일 업데이트
            self.save_config()
            
            mode_text = "데모" if self.config.get('demo_mode', True) else "실거래"
            logger.info(f"✅ 초기 잔고 업데이트 완료 ({mode_text} 모드)")
            logger.info(f"   💰 KRW 잔고: {account_info['krw']:,.0f}원")
            logger.info(f"   🪙 XRP 잔고: {account_info['xrp']:.6f} XRP")
            logger.info(f"   💵 설정된 투자금액: {self.config.get('total_investment', 0):,.0f}원")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 초기 잔고 업데이트 오류: {e}")
            logger.error(f"오류 상세: {type(e).__name__}: {str(e)}")
            return False
        
    def initialize_api(self) -> bool:
        """업비트 API 초기화"""
        try:
            logger.info("🔄 업비트 API 초기화 시작...")
            logger.debug(f"📋 API 키 정보: access_key 길이={len(self.access_key)}, secret_key 길이={len(self.secret_key)}")
            
            # API 키 유효성 기본 검사
            if not self.access_key or not self.secret_key:
                logger.error("❌ API 키가 설정되지 않았습니다.")
                return False
            
            if len(self.access_key) < 20 or len(self.secret_key) < 20:
                logger.error("❌ API 키 길이가 너무 짧습니다. 올바른 키인지 확인하세요.")
                return False
            
            # Upbit 객체 생성
            logger.debug("🔧 pyupbit.Upbit 객체 생성 중...")
            self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)
            
            # API 연결 테스트
            logger.info("🧪 API 연결 테스트 중...")
            balances = self.upbit.get_balances()
            
            if balances is None:
                logger.error("❌ API 키가 올바르지 않거나 권한이 없습니다.")
                logger.error("💡 다음을 확인하세요:")
                logger.error("   1. 업비트에서 발급받은 정확한 API 키인지")
                logger.error("   2. API 키에 '자산조회' 권한이 있는지")
                logger.error("   3. 현재 IP가 업비트에 등록되어 있는지")
                self.upbit = None
                return False
            
            # 응답 타입 검증
            if not isinstance(balances, list):
                logger.error(f"❌ 예상치 못한 API 응답 타입: {type(balances)}")
                logger.error(f"응답 내용: {balances}")
                self.upbit = None
                return False
            
            logger.info("✅ 업비트 API 연결 성공")
            logger.info(f"📊 계좌에서 {len(balances)}개의 자산 발견")
            return True
            
        except Exception as e:
            logger.error(f"❌ API 초기화 실패: {e}")
            logger.error(f"오류 상세: {type(e).__name__}: {str(e)}")
            logger.error("💡 네트워크 연결과 업비트 API 서버 상태를 확인하세요.")
            self.upbit = None
            return False
    
    def get_account_info(self, force_refresh: bool = False) -> Dict[str, float]:
        """계좌 정보 조회 (데모모드/실거래 모드 구분, 캐시 적용)"""
        # 캐시가 유효한 경우 캐시된 값 반환 (force_refresh가 False인 경우만)
        current_time = time.time()
        if not force_refresh and (current_time - self._balance_cache_time) < self._balance_cache_duration:
            return self._balance_cache.copy()
        
        if self.config.get('demo_mode', True):
            # 데모 모드: config.json에서 잔고 정보 가져오기
            krw_balance = self.config.get('initial_krw_balance', 300000)
            xrp_balance = self.config.get('initial_xrp_balance', 0)
            
            # 데모 모드에서는 잔고 조회 로그를 debug 레벨로 (매번 출력 방지)
            if self._balance_cache_time == 0:  # 첫 번째 조회시에만 INFO 로그
                logger.info(f"🎮 [데모] 잔고 조회 - KRW: {krw_balance:,.0f}원, XRP: {xrp_balance:.6f}")
            else:
                logger.debug(f"🎮 [데모] 잔고 조회 - KRW: {krw_balance:,.0f}원, XRP: {xrp_balance:.6f}")
            
            # 캐시 업데이트
            balance_info = {'krw': krw_balance, 'xrp': xrp_balance}
            self._balance_cache = balance_info.copy()
            self._balance_cache_time = current_time
            
            return balance_info
        
        # 실거래 모드: 실제 API 호출
        try:
            logger.debug("🔍 업비트 API 잔고 조회 시작")
            
            # API 객체가 존재하는지 다시 한 번 확인
            if not self.upbit:
                logger.error("❌ API 객체가 None입니다. API 초기화 필요")
                return {'krw': 0, 'xrp': 0}
            
            # 잔고 조회 실행
            balances = self.upbit.get_balances()
            logger.debug(f"🔍 API 응답 데이터 타입: {type(balances)}")
            logger.debug(f"🔍 API 응답 내용: {balances}")
            
            # 응답이 None이거나 빈 리스트인 경우
            if balances is None:
                logger.error("❌ API에서 None 응답을 받았습니다.")
                logger.error("💡 가능한 원인:")
                logger.error("   1. API 키가 잘못됨")
                logger.error("   2. API 키 권한 부족 (조회 권한 필요)")
                logger.error("   3. IP 주소가 등록되지 않음")
                logger.error("   4. 업비트 API 서버 문제")
                return {'krw': 0, 'xrp': 0}
            
            if isinstance(balances, list) and len(balances) == 0:
                logger.warning("⚠️ 빈 잔고 리스트를 받았습니다.")
                logger.warning("💡 업비트 계좌에 자산이 없거나 API 설정에 문제가 있을 수 있습니다.")
                return {'krw': 0, 'xrp': 0}
            
            krw_balance = 0
            xrp_balance = 0
            
            # balances가 리스트인지 확인
            if isinstance(balances, list):
                logger.info(f"📊 총 {len(balances)}개의 자산 발견")
                for balance in balances:
                    if isinstance(balance, dict):
                        currency = balance.get('currency', '')
                        balance_amount = balance.get('balance', '0')
                        locked_amount = balance.get('locked', '0')
                        
                        logger.debug(f"   {currency}: 사용가능 {balance_amount}, 사용중 {locked_amount}")
                        
                        if currency == 'KRW':
                            krw_balance = float(balance_amount)
                            logger.info(f"💰 KRW 잔고 발견: {krw_balance:,.0f}원")
                        elif currency == 'XRP':
                            xrp_balance = float(balance_amount)
                            logger.info(f"🪙 XRP 잔고 발견: {xrp_balance:.6f}")
                    else:
                        logger.warning(f"⚠️ 예상치 못한 잔고 항목 타입: {type(balance)}")
            else:
                # balances가 dict 형태이거나 다른 타입인 경우
                logger.error(f"❌ 예상치 못한 잔고 데이터 형식: {type(balances)}")
                logger.error(f"잔고 데이터 내용: {balances}")
                return {'krw': 0, 'xrp': 0}
            
            # 결과 검증
            logger.info(f"✅ 잔고 조회 완료:")
            logger.info(f"   💰 KRW: {krw_balance:,.0f}원")
            logger.info(f"   🪙 XRP: {xrp_balance:.6f}")
            
            # 잔고가 모두 0인 경우 추가 안내
            if krw_balance == 0 and xrp_balance == 0:
                logger.warning("⚠️ 모든 잔고가 0입니다. 다음을 확인하세요:")
                logger.warning("   1. 업비트 계좌에 실제 자산이 있는지")
                logger.warning("   2. API 키 권한 설정 (조회 권한)")
                logger.warning("   3. 업비트 → 마이페이지 → Open API 관리 → IP 주소 등록")
                logger.warning("   4. API 키가 올바른 계정의 것인지")
            
            # 실거래 모드에서도 로그 빈도 조절 (force_refresh인 경우 항상 INFO 로그)
            if force_refresh or (current_time - self._balance_cache_time) > 30:  # 강제 갱신이거나 30초마다 INFO 로그
                logger.info(f"💰 실거래 모드 잔고 조회 완료 - KRW: {krw_balance:,.0f}원, XRP: {xrp_balance:.6f}")
            else:
                logger.debug(f"💰 잔고 조회 - KRW: {krw_balance:,.0f}원, XRP: {xrp_balance:.6f}")
            
            # 캐시 업데이트
            balance_info = {'krw': krw_balance, 'xrp': xrp_balance}
            self._balance_cache = balance_info.copy()
            self._balance_cache_time = current_time
            
            return balance_info
            
        except Exception as e:
            logger.error(f"❌ 실거래 모드 계좌 정보 조회 실패: {e}")
            logger.error(f"오류 세부사항: {type(e).__name__}: {str(e)}")
            
            # 일반적인 API 오류들에 대한 구체적인 안내
            error_msg = str(e).lower()
            if 'connection' in error_msg or 'network' in error_msg:
                logger.error("🌐 네트워크 연결 오류입니다. 인터넷 연결을 확인하세요.")
            elif 'unauthorized' in error_msg or 'invalid' in error_msg:
                logger.error("🔑 API 키 인증 오류입니다. API 키와 권한을 확인하세요.")
            elif 'ip' in error_msg or 'whitelist' in error_msg:
                logger.error("🏠 IP 주소 제한 오류입니다. 업비트에서 현재 IP를 등록하세요.")
            else:
                logger.error("❓ 알 수 없는 오류입니다. 업비트 API 상태를 확인하세요.")
            
            # API 오류 시 캐시된 값이 있으면 반환, 없으면 0
            if self._balance_cache_time > 0:
                logger.warning("⚠️ API 오류로 인해 캐시된 잔고 정보를 사용합니다")
                return self._balance_cache.copy()
            return {'krw': 0, 'xrp': 0}
    
    def get_current_price(self) -> Optional[float]:
        """현재 XRP 가격 조회"""
        try:
            current_price = pyupbit.get_current_price(self.ticker)
            if current_price is None or current_price <= 0:
                logger.warning("❌ 현재 가격 조회 실패")
                return None
            return current_price
        except Exception as e:
            logger.error(f"❌ 현재 가격 조회 오류: {e}")
            return None
    
    def calculate_price_range(self, period: str = '24h') -> Tuple[Optional[float], Optional[float]]:
        """가격 범위 계산"""
        try:
            if period == '24h':
                df = pyupbit.get_ohlcv(self.ticker, interval='minute60', count=24)
            elif period == '7d':
                df = pyupbit.get_ohlcv(self.ticker, interval='day', count=7)
            elif period == '30d':
                df = pyupbit.get_ohlcv(self.ticker, interval='day', count=30)
            else:
                df = pyupbit.get_ohlcv(self.ticker, interval='minute60', count=24)
            
            if df is None or df.empty:
                logger.error("❌ 가격 데이터 조회 실패")
                return None, None
            
            high_price = float(df['high'].max())
            low_price = float(df['low'].min())
            
            # 5% 범위 확장 (안전 마진)
            price_range = high_price - low_price
            margin = price_range * 0.05
            
            high_price += margin
            low_price -= margin
            
            return high_price, low_price
            
        except Exception as e:
            logger.error(f"❌ 가격 범위 계산 오류: {e}")
            return None, None
    
    def calculate_grid_levels(self, high_price: float, low_price: float, grid_count: int) -> List[float]:
        """그리드 레벨 계산"""
        try:
            if high_price <= low_price or grid_count <= 0:
                return []
            
            price_step = (high_price - low_price) / (grid_count + 1)
            grid_levels = []
            
            for i in range(1, grid_count + 1):
                level = low_price + (price_step * i)
                grid_levels.append(level)
            
            # 가격 순으로 정렬
            grid_levels.sort()
            return grid_levels
            
        except Exception as e:
            logger.error(f"❌ 그리드 레벨 계산 오류: {e}")
            return []
    
    def execute_buy_order(self, price: float, amount: float) -> Optional[Dict]:
        """매수 주문 실행"""
        try:
            # 안전 검사
            total_cost = amount * price
            if total_cost < self.config['min_order_amount']:
                logger.warning(f"⚠️ 주문 금액이 최소값보다 작음: {total_cost:.0f}원")
                return None
            
            if total_cost > self.config['max_order_amount']:
                amount = self.config['max_order_amount'] / price
                logger.info(f"📝 주문 금액 조정: {amount:.6f} XRP")
            
            # KRW 잔고 확인
            account_info = self.get_account_info()
            if account_info['krw'] < total_cost:
                logger.warning(f"⚠️ KRW 잔고 부족: {account_info['krw']:.0f}원 < {total_cost:.0f}원")
                return None
            
            if self.config.get('demo_mode', True):
                # 데모 모드: 가상 주문 실행
                logger.info(f"🎮 [데모] 매수 주문: {amount:.6f} XRP @ {price:.2f}원")
                
                # 가상의 주문 결과 생성
                result = {
                    'uuid': f'demo_buy_{int(time.time())}_{int(amount*1000000)}',
                    'side': 'bid',
                    'ord_type': 'limit' if self.config['use_limit_orders'] else 'market',
                    'price': str(price),
                    'volume': str(amount),
                    'demo_mode': True
                }
                
                # 데모 모드에서 잔고 업데이트 (config.json과 trading_state)
                self.config['initial_krw_balance'] -= total_cost
                self.config['initial_xrp_balance'] += amount
                self.trading_state['current_krw_balance'] -= total_cost
                self.trading_state['current_xrp_balance'] += amount
                self.save_config()
                
                # 캐시도 업데이트
                self._balance_cache['krw'] -= total_cost
                self._balance_cache['xrp'] += amount
                
                logger.info(f"✅ [데모] 매수 주문 성공: {amount:.6f} XRP @ {price:.2f}원")
                return result
                
            else:
                # 실거래 모드: 실제 주문 실행
                logger.info(f"💸 [실거래] 매수 주문: {amount:.6f} XRP @ {price:.2f}원")
                
                if self.config['use_limit_orders']:
                    # 지정가 주문
                    limit_price = price * (1 + self.config['limit_order_buffer'])
                    result = self.upbit.buy_limit_order(self.ticker, limit_price, amount)
                else:
                    # 시장가 주문
                    result = self.upbit.buy_market_order(self.ticker, total_cost)
                
                if result:
                    logger.info(f"✅ [실거래] 매수 주문 성공: {amount:.6f} XRP @ {price:.2f}원")
                    return result
                else:
                    logger.error("❌ [실거래] 매수 주문 실패")
                    return None
                
        except Exception as e:
            logger.error(f"❌ 매수 주문 오류: {e}")
            return None
    
    def execute_sell_order(self, price: float, amount: float) -> Optional[Dict]:
        """매도 주문 실행"""
        try:
            # XRP 잔고 확인
            account_info = self.get_account_info()
            if account_info['xrp'] < amount:
                logger.warning(f"⚠️ XRP 잔고 부족: {account_info['xrp']:.6f} < {amount:.6f}")
                return None
            
            # 최소 주문 금액 확인
            total_value = amount * price
            if total_value < self.config['min_order_amount']:
                logger.warning(f"⚠️ 주문 금액이 최소값보다 작음: {total_value:.0f}원")
                return None
            
            if self.config.get('demo_mode', True):
                # 데모 모드: 가상 주문 실행
                logger.info(f"🎮 [데모] 매도 주문: {amount:.6f} XRP @ {price:.2f}원")
                
                # 가상의 주문 결과 생성
                result = {
                    'uuid': f'demo_sell_{int(time.time())}_{int(amount*1000000)}',
                    'side': 'ask',
                    'ord_type': 'limit' if self.config['use_limit_orders'] else 'market',
                    'price': str(price),
                    'volume': str(amount),
                    'demo_mode': True
                }
                
                # 데모 모드에서 잔고 업데이트 (config.json과 trading_state)
                self.config['initial_krw_balance'] += total_value
                self.config['initial_xrp_balance'] -= amount
                self.trading_state['current_krw_balance'] += total_value
                self.trading_state['current_xrp_balance'] -= amount
                self.save_config()
                
                # 캐시도 업데이트
                self._balance_cache['krw'] += total_value
                self._balance_cache['xrp'] -= amount
                
                logger.info(f"✅ [데모] 매도 주문 성공: {amount:.6f} XRP @ {price:.2f}원")
                return result
                
            else:
                # 실거래 모드: 실제 주문 실행
                logger.info(f"💸 [실거래] 매도 주문: {amount:.6f} XRP @ {price:.2f}원")
                
                if self.config['use_limit_orders']:
                    # 지정가 주문
                    limit_price = price * (1 - self.config['limit_order_buffer'])
                    result = self.upbit.sell_limit_order(self.ticker, limit_price, amount)
                else:
                    # 시장가 주문
                    result = self.upbit.sell_market_order(self.ticker, amount)
                
                if result:
                    logger.info(f"✅ [실거래] 매도 주문 성공: {amount:.6f} XRP @ {price:.2f}원")
                    return result
                else:
                    logger.error("❌ [실거래] 매도 주문 실패")
                    return None
                
        except Exception as e:
            logger.error(f"❌ 매도 주문 오류: {e}")
            return None
    
    def log_trade(self, action: str, price: float, amount: float = 0, profit: float = 0):
        """거래 로그 기록"""
        trade_log = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'price': price,
            'amount': amount,
            'profit': profit,
            'total_profit': self.trading_state['total_profit']
        }
        
        self.trade_logs.append(trade_log)
        
        # 파일에 저장
        try:
            with open('xrp_trade_logs.json', 'w', encoding='utf-8') as f:
                json.dump(self.trade_logs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ 거래 로그 저장 오류: {e}")
    
    def save_trading_state(self):
        """트레이딩 상태 저장"""
        try:
            state_data = {
                'trading_state': self.trading_state,
                'config': self.config,
                'last_update': datetime.now().isoformat()
            }
            
            with open('xrp_trading_state.json', 'w', encoding='utf-8') as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"❌ 트레이딩 상태 저장 오류: {e}")
    
    def load_trading_state(self) -> bool:
        """트레이딩 상태 로드"""
        try:
            if os.path.exists('xrp_trading_state.json'):
                with open('xrp_trading_state.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trading_state = data.get('trading_state', self.trading_state)
                    
                    # 현재 메모리의 중요한 설정값들을 보존 (사용자 입력 보호)
                    preserved_settings = {
                        'total_investment': self.config.get('total_investment'),
                        'grid_count': self.config.get('grid_count'),
                        'demo_mode': self.config.get('demo_mode')
                    }
                    
                    # 기존 config 로드
                    loaded_config = data.get('config', {})
                    self.config.update(loaded_config)
                    
                    # 중요한 설정들을 현재 값으로 복원
                    for key, value in preserved_settings.items():
                        if value is not None:
                            self.config[key] = value
                            logger.debug(f"🔒 보존된 설정: {key} = {value}")
                    
                    logger.info("✅ 트레이딩 상태 로드 성공 (사용자 설정 보존)")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ 트레이딩 상태 로드 오류: {e}")
        
        return False
    
    def initialize_trading(self, total_investment: float = None, grid_count: int = None, period: str = None) -> bool:
        """트레이딩 초기화"""
        try:
            logger.info("🚀 XRP 그리드 트레이딩 시작")
            
            # 설정 검증
            if not self.validate_config():
                return False
            
            # API 초기화
            if not self.initialize_api():
                return False
            
            # 업비트에서 현재 잔고 조회 및 config.json 업데이트
            logger.info("🔄 업비트 계좌 정보 동기화 중...")
            if not self.update_initial_balances():
                logger.warning("⚠️ 잔고 업데이트 실패, 기존 설정 값 사용")
            
            # 설정에서 값 가져오기 (매개변수가 없으면)
            if total_investment is None:
                total_investment = self.config.get('total_investment', 400000)
            if grid_count is None:
                grid_count = self.config.get('grid_count', 20)
            if period is None:
                period = self.config.get('period', '24h')
            
            # 현재 계좌 정보는 이미 update_initial_balances()에서 업데이트됨
            account_info = {
                'krw': self.trading_state['current_krw_balance'],
                'xrp': self.trading_state['current_xrp_balance']
            }
            
            # 투자금액 검증 및 디버깅 정보 출력
            logger.info(f"🔍 투자금액 검증:")
            logger.info(f"   💵 설정된 투자금액: {total_investment:,.0f}원")
            logger.info(f"   💰 현재 KRW 잔고: {account_info['krw']:,.0f}원")
            logger.info(f"   🪙 현재 XRP 잔고: {account_info['xrp']:.6f}")
            
            if total_investment <= 0:
                logger.warning(f"⚠️ 투자금액이 0원 이하입니다: {total_investment:,.0f}원")
                logger.info(f"💡 다음을 확인하세요:")
                logger.info(f"   1. 설정에서 투자금액을 수정하여 적절한 값을 입력하세요")
                logger.info(f"   2. 데모 모드에서는 투자금액이 자동으로 KRW 잔고로 설정됩니다")
                return False
            
            if total_investment > account_info['krw']:
                if account_info['krw'] == 0:
                    logger.warning(f"⚠️ KRW 잔고가 0원입니다. API 키 설정 또는 IP 제한을 확인하세요.")
                    logger.info(f"💡 업비트 사이트에서 다음을 확인하세요:")
                    logger.info(f"   1. 마이페이지 → Open API 관리")
                    logger.info(f"   2. 현재 IP 주소 등록 여부")
                    logger.info(f"   3. API 키 권한 설정 (조회, 거래)")
                    return False
                else:
                    logger.error(f"❌ 투자금액이 KRW 잔고를 초과합니다: {total_investment:,.0f}원 > {account_info['krw']:,.0f}원")
                    return False
            
            self.trading_state['total_investment'] = total_investment
            self.config['grid_count'] = grid_count
            
            # 가격 범위 계산
            high_price, low_price = self.calculate_price_range(period)
            if not high_price or not low_price:
                logger.error("❌ 가격 범위 계산 실패")
                return False
            
            # 현재 가격 조회
            current_price = self.get_current_price()
            if not current_price:
                logger.error("❌ 현재 가격 조회 실패")
                return False
            
            # 그리드 레벨 계산
            grid_levels = self.calculate_grid_levels(high_price, low_price, grid_count)
            if not grid_levels:
                logger.error("❌ 그리드 레벨 계산 실패")
                return False
            
            self.trading_state['grid_levels'] = grid_levels
            
            logger.info(f"📊 가격 범위: {low_price:.2f} ~ {high_price:.2f}원")
            logger.info(f"🎯 현재 가격: {current_price:.2f}원")
            logger.info(f"🔢 그리드 개수: {len(grid_levels)}개")
            logger.info(f"💵 투자 금액: {total_investment:,.0f}원")
            
            # 초기 포트폴리오 가치 설정 (스탑로스 기준점)
            initial_portfolio_value = account_info['krw'] + (account_info['xrp'] * current_price)
            self.trading_state['highest_portfolio_value'] = initial_portfolio_value
            
            logger.info(f"🎯 초기 포트폴리오 가치: {initial_portfolio_value:,.0f}원")
            if self.config.get('stop_loss_enabled', False):
                stop_loss_threshold = initial_portfolio_value * (1 - self.config.get('stop_loss_percentage', 3.0) / 100)
                logger.info(f"🛑 스탑로스 기준: {stop_loss_threshold:,.0f}원 (-{self.config.get('stop_loss_percentage', 3.0)}%)")
            
            # 초기 상태 저장
            self.save_trading_state()
            self.log_trade("초기화", current_price)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 트레이딩 초기화 오류: {e}")
            return False
    
    def run_grid_trading(self):
        """그리드 트레이딩 메인 루프"""
        logger.info("🔄 그리드 트레이딩 루프 시작")
        
        while not self.stop_event.is_set():
            try:
                # 현재 가격 조회
                current_price = self.get_current_price()
                if not current_price:
                    logger.warning("⚠️ 가격 조회 실패, 3초 후 재시도")
                    time.sleep(3)
                    continue
                
                # 스탑로스 확인 (그리드 거래보다 우선)
                if self.check_stop_loss(current_price):
                    logger.critical("🚨 스탑로스 발동으로 거래 중지")
                    break
                
                # 그리드 레벨 확인
                self._check_grid_levels(current_price)
                
                # 계좌 정보 업데이트
                account_info = self.get_account_info()
                self.trading_state['current_krw_balance'] = account_info['krw']
                self.trading_state['current_xrp_balance'] = account_info['xrp']
                
                # 수익률 계산
                self._calculate_profit()
                
                # 상태 저장 (1분마다)
                if self.trading_state['trade_count'] % 20 == 0:
                    self.save_trading_state()
                
                # 5초 대기
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ 트레이딩 루프 오류: {e}")
                time.sleep(10)
    
    def _check_grid_levels(self, current_price: float):
        """그리드 레벨 체크 및 거래 실행"""
        try:
            grid_levels = self.trading_state['grid_levels']
            confirmation_buffer = self.config['confirmation_buffer']
            
            for i, level in enumerate(grid_levels):
                # 매수 조건: 현재가가 그리드 레벨보다 낮을 때 (확인 버퍼 적용)
                if current_price <= level * (1 - confirmation_buffer):
                    buy_key = f"buy_{i}"
                    if buy_key not in self.trading_state['grid_orders']:
                        logger.info(f"📊 그리드 매수 조건 충족: Level {i}, 현재가 {current_price:.2f}원 <= 그리드 {level:.2f}원")
                        self._execute_grid_buy(level, i)
                
                # 매도 조건: 현재가가 그리드 레벨보다 높고, 해당 레벨에서 매수했던 기록이 있을 때
                elif current_price >= level * (1 + confirmation_buffer):
                    buy_key = f"buy_{i}"
                    sell_key = f"sell_{i}"
                    if buy_key in self.trading_state['grid_orders'] and sell_key not in self.trading_state['grid_orders']:
                        logger.info(f"📊 그리드 매도 조건 충족: Level {i}, 현재가 {current_price:.2f}원 >= 그리드 {level:.2f}원")
                        self._execute_grid_sell(level, i)
                        
        except Exception as e:
            logger.error(f"❌ 그리드 레벨 체크 오류: {e}")
    
    def _execute_grid_buy(self, price: float, grid_index: int):
        """그리드 매수 실행"""
        try:
            # 투자금액이 0이면 매수하지 않음
            if self.trading_state['total_investment'] <= 0:
                logger.debug(f"⚠️ 투자금액이 0원이어서 그리드 매수 실행 안함: Level {grid_index}")
                return
                
            # 주문 금액 계산 (투자금을 그리드 수로 나눔)
            order_amount_krw = self.trading_state['total_investment'] / self.config['grid_count']
            
            # 최소 주문 금액보다 작으면 매수하지 않음
            if order_amount_krw < self.config['min_order_amount']:
                logger.debug(f"⚠️ 주문 금액이 최솟값보다 작음: {order_amount_krw:.0f}원 < {self.config['min_order_amount']:.0f}원")
                return
                
            xrp_amount = order_amount_krw / price
            
            # 매수 주문 실행
            result = self.execute_buy_order(price, xrp_amount)
            
            if result:
                # 주문 기록
                order_key = f"buy_{grid_index}"
                self.trading_state['grid_orders'][order_key] = {
                    'price': price,
                    'amount': xrp_amount,
                    'timestamp': datetime.now().isoformat(),
                    'order_id': result.get('uuid', ''),
                    'type': 'buy'
                }
                
                self.trading_state['trade_count'] += 1
                self.log_trade("매수", price, xrp_amount)
                
                logger.info(f"🟢 그리드 매수 완료: Level {grid_index} @ {price:.2f}원, {xrp_amount:.6f} XRP")
                
        except Exception as e:
            logger.error(f"❌ 그리드 매수 오류: {e}")
    
    def _execute_grid_sell(self, price: float, grid_index: int):
        """그리드 매도 실행"""
        try:
            # 해당 그리드의 매수 주문 찾기
            buy_key = f"buy_{grid_index}"
            if buy_key not in self.trading_state['grid_orders']:
                return
            
            buy_order = self.trading_state['grid_orders'][buy_key]
            sell_amount = buy_order['amount']
            
            # 최소 주문 금액 체크
            sell_value = sell_amount * price
            if sell_value < self.config['min_order_amount']:
                return
            
            # 매도 주문 실행
            result = self.execute_sell_order(price, sell_amount)
            
            if result:
                # 수익 계산
                buy_price = buy_order['price']
                profit = (price - buy_price) * sell_amount
                profit_after_fee = profit * (1 - self.config['fee_rate'] * 2)  # 매수/매도 수수료
                
                # 주문 기록
                sell_key = f"sell_{grid_index}"
                self.trading_state['grid_orders'][sell_key] = {
                    'price': price,
                    'amount': sell_amount,
                    'timestamp': datetime.now().isoformat(),
                    'order_id': result.get('uuid', ''),
                    'type': 'sell',
                    'profit': profit_after_fee
                }
                
                # 매수 주문 제거 (재사용을 위해)
                del self.trading_state['grid_orders'][buy_key]
                
                self.trading_state['trade_count'] += 1
                self.trading_state['total_profit'] += profit_after_fee
                
                self.log_trade("매도", price, sell_amount, profit_after_fee)
                
                logger.info(f"🔴 그리드 매도 완료: Level {grid_index} @ {price:.2f}원, 수익: {profit_after_fee:,.0f}원")
                
        except Exception as e:
            logger.error(f"❌ 그리드 매도 오류: {e}")
    
    def _calculate_profit(self):
        """총 수익률 계산"""
        try:
            account_info = self.get_account_info()
            current_price = self.get_current_price()
            
            if not current_price:
                return
            
            # 초기 자산 가치
            initial_total = (
                self.trading_state['initial_krw_balance'] + 
                self.trading_state['initial_xrp_balance'] * current_price
            )
            
            # 현재 자산 가치
            current_total = (
                account_info['krw'] + 
                account_info['xrp'] * current_price
            )
            
            # 수익률 계산
            if initial_total > 0:
                profit_rate = ((current_total - initial_total) / initial_total) * 100
                self.trading_state['total_profit'] = current_total - initial_total
                
                if self.trading_state['trade_count'] % 60 == 0:  # 5분마다 로그
                    logger.info(f"📈 현재 수익률: {profit_rate:.2f}% ({self.trading_state['total_profit']:,.0f}원)")
                    
        except Exception as e:
            logger.error(f"❌ 수익률 계산 오류: {e}")
    
    def check_stop_loss(self, current_price: float) -> bool:
        """스탑로스 조건 확인"""
        try:
            if not self.config.get('stop_loss_enabled', False):
                return False
            
            if self.trading_state.get('stop_loss_triggered', False):
                return True
            
            # 현재 포트폴리오 가치 계산
            account_info = self.get_account_info()
            current_portfolio_value = account_info['krw'] + (account_info['xrp'] * current_price)
            
            # 최고 포트폴리오 가치 업데이트
            if current_portfolio_value > self.trading_state.get('highest_portfolio_value', 0):
                self.trading_state['highest_portfolio_value'] = current_portfolio_value
                logger.info(f"📈 최고 포트폴리오 가치 업데이트: {current_portfolio_value:,.0f}원")
            
            # 스탑로스 비율 계산
            stop_loss_percentage = self.config.get('stop_loss_percentage', 3.0)
            highest_value = self.trading_state.get('highest_portfolio_value', 0)
            
            if highest_value > 0:
                current_loss_percentage = ((highest_value - current_portfolio_value) / highest_value) * 100
                
                if current_loss_percentage >= stop_loss_percentage:
                    logger.warning(f"⚠️ 스탑로스 조건 감지!")
                    logger.warning(f"   최고가치: {highest_value:,.0f}원")
                    logger.warning(f"   현재가치: {current_portfolio_value:,.0f}원")
                    logger.warning(f"   손실률: {current_loss_percentage:.2f}% (기준: {stop_loss_percentage}%)")
                    
                    self.trading_state['stop_loss_triggered'] = True
                    self.trading_state['stop_loss_price'] = current_price
                    
                    # 스탑로스 실행
                    self._execute_stop_loss(current_price, account_info['xrp'])
                    return True
                    
            return False
            
        except Exception as e:
            logger.error(f"❌ 스탑로스 체크 오류: {e}")
            return False
    
    def _execute_stop_loss(self, current_price: float, xrp_amount: float):
        """스탑로스 실행 - 모든 XRP 매도"""
        try:
            logger.critical(f"🚨 스탑로스 실행! 모든 XRP 매도")
            
            if xrp_amount > 0:
                # 시장가로 즉시 매도
                result = self.upbit.sell_market_order(self.ticker, xrp_amount)
                
                if result:
                    logger.critical(f"✅ 스탑로스 매도 완료: {xrp_amount:.6f} XRP @ {current_price:.2f}원")
                    
                    # 거래 로그 기록
                    self.log_trade("스탑로스", current_price, xrp_amount, 0)
                    
                    # 트레이딩 중지
                    self.stop_trading()
                else:
                    logger.error(f"❌ 스탑로스 매도 실패")
            else:
                logger.warning(f"⚠️ 매도할 XRP가 없습니다")
                
        except Exception as e:
            logger.error(f"❌ 스탑로스 실행 오류: {e}")
    
    def start_trading(self, total_investment: float = None, grid_count: int = None, period: str = None):
        """트레이딩 시작"""
        try:
            # 기존 상태 로드 시도
            self.load_trading_state()
            
            # 트레이딩 초기화
            if not self.initialize_trading(total_investment, grid_count, period):
                logger.error("❌ 트레이딩 초기화 실패")
                return False
            
            self.is_running = True
            
            # 트레이딩 스레드 시작
            trading_thread = threading.Thread(target=self.run_grid_trading)
            trading_thread.daemon = True
            trading_thread.start()
            
            logger.info("✅ XRP 그리드 트레이딩 시작 완료")
            return True
            
        except Exception as e:
            logger.error(f"❌ 트레이딩 시작 오류: {e}")
            return False
    
    def stop_trading(self):
        """트레이딩 중지"""
        try:
            logger.info("🛑 트레이딩 중지 요청")
            self.stop_event.set()
            self.is_running = False
            
            # 최종 상태 저장
            self.save_trading_state()
            
            logger.info("✅ XRP 그리드 트레이딩 중지 완료")
            
        except Exception as e:
            logger.error(f"❌ 트레이딩 중지 오류: {e}")
    
    def get_status(self) -> Dict:
        """현재 트레이딩 상태 반환"""
        try:
            current_price = self.get_current_price()
            account_info = self.get_account_info()
            
            return {
                'is_running': self.is_running,
                'current_price': current_price,
                'account_info': account_info,
                'trading_state': self.trading_state,
                'config': self.config,
                'trade_count': self.trading_state['trade_count'],
                'total_profit': self.trading_state['total_profit'],
                'grid_orders': len(self.trading_state['grid_orders'])
            }
            
        except Exception as e:
            logger.error(f"❌ 상태 조회 오류: {e}")
            return {}

def main():
    """메인 실행 함수"""
    print("🚀 XRP 그리드 트레이딩 봇 v4.2.7")
    print("=" * 50)
    
    # 봇 생성 (config.json 경로 자동 탐지)
    bot = XRPTradingBot()
    
    # 거래 모드 선택
    print("📋 거래 모드를 선택하세요:")
    print("  1. 데모 모드 (가상 거래 - 안전한 테스트)")
    print("  2. 실거래 모드 (실제 거래 - 주의 필요)")
    
    while True:
        mode_choice = input("\n모드 선택 (1/2): ").strip()
        if mode_choice == '1':
            bot.config['demo_mode'] = True
            print("✅ 데모 모드로 설정되었습니다.")
            break
        elif mode_choice == '2':
            bot.config['demo_mode'] = False
            print("⚠️ 실거래 모드로 설정되었습니다. 실제 자금이 사용됩니다!")
            print("정말로 실거래 모드로 진행하시겠습니까?")
            print("  1. Yes (실거래 진행)")
            print("  2. No (다시 선택)")
            
            while True:
                confirm_choice = input("확인 (1/2): ").strip()
                if confirm_choice == '1':
                    break
                elif confirm_choice == '2':
                    break
                else:
                    print("❌ 1 또는 2를 입력해주세요.")
            
            if confirm_choice == '1':
                break
            else:
                continue
        else:
            print("❌ 1 또는 2를 입력해주세요.")
    
    # 실거래 모드와 데모 모드에 따라 다른 처리
    config = bot.config
    is_demo_mode = config.get('demo_mode', True)
    mode_text = "데모 모드" if is_demo_mode else "실거래 모드"
    
    if is_demo_mode:
        # 데모 모드: 기존 설정 표시 및 수정 옵션 제공
        print(f"\n📋 현재 설정 ({mode_text}):")
        print(f"   투자 금액: {config.get('total_investment', 0):,}원")
        print(f"   그리드 개수: {config.get('grid_count', 20)}개")
        print(f"   기간: {config.get('period', '24h')}")
        print(f"   리스크 모드: {config.get('risk_mode', 'stable')}")
        print(f"   스탑로스: {config.get('stop_loss_percentage', 3.0):.1f}% ({'활성화' if config.get('stop_loss_enabled', True) else '비활성화'})")
        
        # 저장된 초기 잔고 정보 표시
        if config.get('last_balance_update'):
            print(f"\n💾 마지막 잔고 업데이트: {config.get('last_balance_update', 'N/A')}")
            print(f"   💰 KRW 잔고: {config.get('initial_krw_balance', 0):,.0f}원")
            print(f"   🪙 XRP 잔고: {config.get('initial_xrp_balance', 0):.6f}")
        else:
            print(f"\n⚠️  잔고 정보가 없습니다. 시작 시 업비트에서 자동으로 가져옵니다.")
        
        print()
        
        # 데모 모드: 설정 수정 옵션 제공
        print("설정을 수정하시겠습니까?")
        print("  1. Yes (설정 수정)")
        print("  2. No (현재 설정으로 진행)")
        
        while True:
            modify_choice = input("선택 (1/2): ").strip()
            if modify_choice in ['1', '2']:
                break
            else:
                print("❌ 1 또는 2를 입력해주세요.")
    else:
        # 실거래 모드: 업비트에서 실제 계좌 정보 자동 조회
        print(f"\n💸 실거래 모드 선택됨")
        print("🔄 업비트 API를 통해 실제 계좌 정보를 조회합니다...")
        print("⚠️  실제 자금이 사용되므로 신중히 진행하세요!")
        
        # API 초기화 및 계좌 정보 조회
        if not bot.initialize_api():
            print("❌ 업비트 API 연결 실패. 프로그램을 종료합니다.")
            return
            
        # 실제 잔고 조회
        if not bot.update_initial_balances():
            print("❌ 계좌 정보 조회 실패. 프로그램을 종료합니다.")
            return
        
        # 실거래 모드 설정 자동 계산
        current_krw = config.get('initial_krw_balance', 0)
        current_xrp = config.get('initial_xrp_balance', 0)
        total_investment = config.get('total_investment', 0)
        
        print(f"\n📊 실제 계좌 정보:")
        print(f"   💰 KRW 잔고: {current_krw:,.0f}원")
        print(f"   🪙 XRP 잔고: {current_xrp:.6f}")
        print(f"   💵 자동 설정된 투자금액: {total_investment:,.0f}원")
        print(f"   🔢 그리드 개수: {config.get('grid_count', 20)}개")
        print(f"   🛑 스탑로스: {config.get('stop_loss_percentage', 3.0):.1f}%")
        
        # 실거래 모드에서는 추가 확인
        print(f"\n⚠️  위 설정으로 실거래를 시작하시겠습니까?")
        print("   실제 자금이 투자되며, 손실 위험이 있습니다!")
        print("  1. Yes (실거래 시작)")
        print("  2. No (취소)")
        
        while True:
            final_confirm = input("최종 확인 (1/2): ").strip()
            if final_confirm == '1':
                print("✅ 실거래 모드로 진행합니다.")
                modify_choice = '2'  # 설정 수정하지 않고 바로 시작
                break
            elif final_confirm == '2':
                print("❌ 실거래가 취소되었습니다.")
                return
            else:
                print("❌ 1 또는 2를 입력해주세요.")
    
    # 데모 모드에서만 설정 수정 처리
    if is_demo_mode and modify_choice == '1':
        # 설정 수정 전에 config 저장
        original_config = bot.config.copy()
        
        try:
            new_investment = input(f"투자금액 ({config.get('total_investment', 0):,}원): ").strip()
            if new_investment:
                config['total_investment'] = float(new_investment)
                logger.info(f"💵 투자금액 업데이트: {float(new_investment):,.0f}원")
            
            new_grid_count = input(f"그리드 개수 ({config.get('grid_count', 20)}개): ").strip()
            if new_grid_count:
                config['grid_count'] = int(new_grid_count)
                logger.info(f"📊 그리드 개수 업데이트: {int(new_grid_count)}개")
            
            # 설정 변경 사항을 저장
            bot.save_config()
            logger.info("💾 변경된 설정을 config.json에 저장")
                
        except ValueError:
            print("❌ 올바른 숫자를 입력해주세요.")
            # 오류 시 원래 설정으로 복구
            bot.config = original_config
            return
    
    try:
        if bot.start_trading():
            print("\n✅ 트레이딩이 시작되었습니다!")
            print("명령어:")
            print("  1. status - 현재 상태 확인")
            print("  2. q - 종료")
            print()
            
            while bot.is_running:
                user_input = input("명령 입력 (1: status, 2: quit): ").strip().lower()
                if user_input in ['q', '2', 'quit']:
                    break
                elif user_input in ['status', '1', 's']:
                    status = bot.get_status()
                    print(f"\n📊 현재 상태:")
                    print(f"현재가: {status.get('current_price', 0):.2f}원")
                    print(f"거래 횟수: {status.get('trade_count', 0)}회")
                    print(f"총 수익: {status.get('total_profit', 0):,.0f}원")
                    print(f"활성 주문: {status.get('grid_orders', 0)}개")
                    print()
        
        bot.stop_trading()
        
    except KeyboardInterrupt:
        print("\n🛑 사용자에 의해 중지되었습니다.")
        bot.stop_trading()
    except Exception as e:
        print(f"❌ 예상치 못한 오류가 발생했습니다: {e}")
        bot.stop_trading()

def test_api_connection():
    """API 연결 테스트 전용 함수"""
    print("🧪 업비트 API 연결 테스트")
    print("=" * 40)
    
    # 봇 생성
    bot = XRPTradingBot()
    
    # 실거래 모드로 설정
    bot.config['demo_mode'] = False
    
    print("📋 설정 정보:")
    print(f"   Access Key: {bot.access_key[:10]}...{bot.access_key[-5:] if len(bot.access_key) > 15 else 'N/A'}")
    print(f"   Secret Key: {bot.secret_key[:10]}...{bot.secret_key[-5:] if len(bot.secret_key) > 15 else 'N/A'}")
    print()
    
    # API 초기화 테스트
    if bot.initialize_api():
        print("✅ API 초기화 성공!")
        
        # 잔고 조회 테스트
        print("\n📊 계좌 잔고 조회 테스트:")
        account_info = bot.get_account_info(force_refresh=True)
        print(f"   💰 KRW 잔고: {account_info['krw']:,.0f}원")
        print(f"   🪙 XRP 잔고: {account_info['xrp']:.6f}")
        
        # 현재 가격 조회 테스트
        print("\n💹 현재 가격 조회 테스트:")
        current_price = bot.get_current_price()
        if current_price:
            print(f"   📈 XRP 현재가: {current_price:,.0f}원")
            
            # 총 자산 계산
            total_value = account_info['krw'] + (account_info['xrp'] * current_price)
            print(f"   💎 총 자산 가치: {total_value:,.0f}원")
        
        return True
    else:
        print("❌ API 초기화 실패!")
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # API 연결 테스트 모드
        test_api_connection()
    else:
        # 일반 실행 모드
        main()