#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
트렌드 기반 리밸런싱 및 그리드 거래 개선사항 테스트
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from trading.trading import XRPTradingBot
import json
import time

def test_trend_based_rebalancing():
    """트렌드 기반 리밸런싱 및 그리드 거래 수정사항 테스트"""
    print("🧪 트렌드 기반 리밸런싱 테스트 시작...")
    
    # 봇 초기화 (데모 모드)
    bot = XRPTradingBot('config.json')
    
    # 현재 가격 조회
    current_price = 3933.0  # 테스트용 고정값
    volatility = 0.03  # 3% 변동성
    
    print(f"\n📊 테스트 조건:")
    print(f"   💎 현재가: {current_price:,.0f}원")
    print(f"   📈 변동성: {volatility*100:.1f}%")
    
    # 1. 트렌드 기반 리밸런싱 비율 계산 테스트
    print("\n🔄 트렌드 기반 리밸런싱 비율 계산 테스트...")
    
    # 다양한 트렌드 시나리오로 테스트
    test_trends = [
        (0.4, "강상승"),
        (0.15, "상승"), 
        (0.05, "중립"),
        (-0.15, "하락"),
        (-0.4, "강하락")
    ]
    
    for trend_value, trend_name in test_trends:
        # 임시로 트렌드를 시뮬레이션하는 가격 히스토리 생성
        # 상승 트렌드면 시작 가격을 낮게, 하락 트렌드면 시작 가격을 높게
        base_price = current_price - (trend_value * 1000)  # 트렌드에 따라 시작점 조정
        
        price_history = []
        for i in range(20):
            # 선형적으로 증가/감소하는 가격 패턴
            price = base_price + (trend_value * 1000 * i / 19)
            price_history.append({'price': price, 'timestamp': time.time() - (19-i)})
        
        bot.price_history = price_history
        
        cash_ratio, coin_ratio = bot.calculate_optimal_cash_coin_ratio(current_price, volatility)
        
        print(f"   📊 {trend_name} 트렌드 ({trend_value:+.2f}): 현금 {cash_ratio*100:.1f}%, 코인 {coin_ratio*100:.1f}%")
    
    # 2. 그리드 레벨 계산 테스트
    print(f"\n🎯 적응형 그리드 레벨 계산 테스트...")
    grid_levels = bot.calculate_adaptive_grid_levels(current_price)
    print(f"   📈 생성된 그리드: {len(grid_levels)}개")
    print(f"   💰 가격 범위: {min(grid_levels):,.0f}원 ~ {max(grid_levels):,.0f}원")
    
    # 현재가 기준으로 매수/매도 레벨 분석
    buy_levels = [level for level in grid_levels if level < current_price * 0.995]
    sell_levels = [level for level in grid_levels if level > current_price * 1.005]
    
    print(f"   📉 매수 레벨: {len(buy_levels)}개 ({min(buy_levels) if buy_levels else 0:,.0f}원 ~ {max(buy_levels) if buy_levels else 0:,.0f}원)")
    print(f"   📈 매도 레벨: {len(sell_levels)}개 ({min(sell_levels) if sell_levels else 0:,.0f}원 ~ {max(sell_levels) if sell_levels else 0:,.0f}원)")
    
    # 3. 초기 그리드 주문 배치 테스트 (시뮬레이션)
    print(f"\n🔄 초기 그리드 주문 배치 테스트...")
    
    # 테스트용 잔고 설정
    bot.trading_state['current_krw_balance'] = 500000  # 50만원
    bot.trading_state['current_xrp_balance'] = 100     # 100 XRP
    
    result = bot.place_initial_grid_orders(current_price, grid_levels)
    
    if result:
        total_orders = len(bot.trading_state.get('grid_orders', {}))
        buy_orders = len([k for k in bot.trading_state.get('grid_orders', {}) if k.startswith('buy_')])
        sell_orders = len([k for k in bot.trading_state.get('grid_orders', {}) if k.startswith('sell_')])
        
        print(f"   ✅ 초기 주문 배치 성공!")
        print(f"   📊 총 주문: {total_orders}개")
        print(f"   📉 매수 주문: {buy_orders}개") 
        print(f"   📈 매도 주문: {sell_orders}개")
    else:
        print(f"   ❌ 초기 주문 배치 실패")
    
    print(f"\n✅ 트렌드 기반 리밸런싱 테스트 완료!")
    return True

if __name__ == "__main__":
    test_trend_based_rebalancing()