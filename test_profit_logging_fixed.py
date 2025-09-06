#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
수익 로깅 기능 테스트 (현재 아키텍처 대응)
"""

import sys
import os
import json
import time
from datetime import datetime
from pathlib import Path

# 현재 아키텍처에서는 main.py의 함수들을 직접 사용
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def log_profit_trade(trade_type, buy_price, sell_price, amount, investment_amount, 
                     profit_amount, profit_rate, buy_order_id, sell_order_id):
    """수익 거래 로깅 함수 (현재 아키텍처 호환)"""
    
    # 데이터 디렉토리 경로
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    profit_file = data_dir / "profits.json"
    
    # 기존 수익 데이터 로드
    try:
        if profit_file.exists():
            with open(profit_file, 'r', encoding='utf-8') as f:
                profits_data = json.load(f)
        else:
            profits_data = {}
    except (FileNotFoundError, json.JSONDecodeError):
        profits_data = {}
    
    # 새로운 거래 기록 생성
    timestamp = datetime.now().isoformat()
    ticker = "KRW-XRP"  # XRP 고정 (테스트)
    
    # profits_data 구조는 기존 코드를 참고하여 생성
    if ticker not in profits_data:
        profits_data[ticker] = []
    
    trade_record = {
        "timestamp": timestamp,
        "trade_type": trade_type,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "amount": amount,
        "investment_amount": investment_amount,
        "profit_amount": profit_amount,
        "profit_rate": profit_rate,
        "buy_order_id": buy_order_id,
        "sell_order_id": sell_order_id
    }
    
    profits_data[ticker].append(trade_record)
    
    # 파일에 저장
    try:
        with open(profit_file, 'w', encoding='utf-8') as f:
            json.dump(profits_data, f, indent=4, ensure_ascii=False)
        print(f"✅ 수익 거래 기록 저장 완료: {trade_type} - {profit_amount:,.0f}원 ({profit_rate:+.2f}%)")
    except Exception as e:
        print(f"❌ 수익 거래 기록 저장 실패: {e}")

def test_profit_logging():
    """수익 로깅 기능 테스트"""
    print("🧪 수익 로깅 기능 테스트 시작...")
    
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
        log_profit_trade(**data)
        time.sleep(0.1)  # 작은 지연
    
    # 생성된 profits.json 파일 확인
    profit_file = Path("data/profits.json")
    if profit_file.exists():
        print(f"\n✅ {profit_file} 파일이 생성되었습니다!")
        
        with open(profit_file, 'r', encoding='utf-8') as f:
            profits_data = json.load(f)
        
        # XRP 거래 기록 확인
        xrp_trades = profits_data.get("KRW-XRP", [])
        print(f"📄 총 {len(xrp_trades)}개의 XRP 거래 기록이 저장되었습니다:")
        
        total_profit = 0
        for i, trade in enumerate(xrp_trades, 1):
            profit_emoji = "💰" if trade['profit_amount'] > 0 else "📉"
            print(f"  {i}. [{trade['timestamp'][:19]}] {profit_emoji} {trade['trade_type']}")
            print(f"     💎 {trade['buy_price']:,.0f}원 → {trade['sell_price']:,.0f}원 ({trade['amount']} XRP)")
            print(f"     📊 수익: {trade['profit_amount']:,.0f}원 ({trade['profit_rate']:+.2f}%)")
            total_profit += trade['profit_amount']
        
        print(f"\n📈 총 누적 수익: {total_profit:,.0f}원")
        
        # 파일 내용 미리보기
        if xrp_trades:
            print(f"\n📄 {profit_file} 파일 내용 샘플:")
            print(json.dumps(xrp_trades[0], indent=2, ensure_ascii=False))
        
    else:
        print(f"❌ {profit_file} 파일이 생성되지 않았습니다.")
        return False
    
    print("\n✅ 수익 로깅 기능 테스트 완료!")
    return True

if __name__ == "__main__":
    test_profit_logging()