#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
수익 로깅 기능 테스트
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from trading.trading import XRPTradingBot
import json
import time

def test_profit_logging():
    """수익 로깅 기능 테스트"""
    print("🧪 수익 로깅 기능 테스트 시작...")
    
    # 봇 초기화 (데모 모드)
    bot = XRPTradingBot('config.json')
    
    # 수익 로그 테스트 데이터
    test_data = [
        {
            'trade_type': 'grid_sell',
            'buy_price': 3900.0,
            'sell_price': 4000.0,
            'amount': 10.0,
            'investment_amount': 39000.0,
            'profit_amount': 950.0,  # 수수료 차감 후
            'profit_rate': 2.44,
            'buy_order_id': 'demo-buy-001001',
            'sell_order_id': 'demo-sell-001001'
        },
        {
            'trade_type': 'grid_sell',
            'buy_price': 3950.0,
            'sell_price': 4100.0,
            'amount': 5.0,
            'investment_amount': 19750.0,
            'profit_amount': 730.0,  # 수수료 차감 후
            'profit_rate': 3.70,
            'buy_order_id': 'demo-buy-001002',
            'sell_order_id': 'demo-sell-001002'
        },
        {
            'trade_type': 'grid_sell',
            'buy_price': 4000.0,
            'sell_price': 3950.0,  # 손실 케이스
            'amount': 8.0,
            'investment_amount': 32000.0,
            'profit_amount': -480.0,  # 손실
            'profit_rate': -1.50,
            'buy_order_id': 'demo-buy-001003',
            'sell_order_id': 'demo-sell-001003'
        }
    ]
    
    # 테스트 데이터로 수익 로그 기록
    print("📊 테스트 거래 기록 생성 중...")
    for i, data in enumerate(test_data, 1):
        print(f"\n🔄 테스트 거래 {i}: {data['trade_type']}")
        bot.log_profit_trade(**data)
        time.sleep(0.1)  # 작은 지연
    
    # 생성된 profit.json 파일 확인
    if os.path.exists('profit.json'):
        print("\n✅ profit.json 파일이 생성되었습니다!")
        
        with open('profit.json', 'r', encoding='utf-8') as f:
            profit_logs = json.load(f)
        
        print(f"📄 총 {len(profit_logs)}개의 거래 기록이 저장되었습니다:")
        
        total_profit = 0
        for i, log in enumerate(profit_logs, 1):
            profit_emoji = "💰" if log['profit_amount'] > 0 else "📉"
            print(f"  {i}. [{log['timestamp'][:19]}] {profit_emoji} {log['trade_type']}")
            print(f"     💎 {log['buy_price']:,.0f}원 → {log['sell_price']:,.0f}원 ({log['amount']} XRP)")
            print(f"     📊 수익: {log['profit_amount']:,.0f}원 ({log['profit_rate']:+.2f}%)")
            total_profit += log['profit_amount']
        
        print(f"\n📈 총 누적 수익: {total_profit:,.0f}원")
        
        # 파일 내용 미리보기
        print("\n📄 profit.json 파일 내용 샘플:")
        print(json.dumps(profit_logs[0], indent=2, ensure_ascii=False))
        
    else:
        print("❌ profit.json 파일이 생성되지 않았습니다.")
        return False
    
    print("\n✅ 수익 로깅 기능 테스트 완료!")
    return True

if __name__ == "__main__":
    test_profit_logging()