# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an automated cryptocurrency grid trading bot for Upbit exchange with a Tkinter GUI. The bot implements grid trading strategies for BTC, ETH, and XRP with advanced features including trend-following logic, risk management, and real-time monitoring.

## Core Architecture

**Single-file application**: All functionality is contained in `main.py` (~5000+ lines)
- **GUI Layer**: Tkinter-based interface with real-time charts using matplotlib
- **Trading Engine**: Grid trading algorithm with trend confirmation buffers
- **Data Management**: JSON-based persistence for trading state, logs, and profits
- **API Integration**: Upbit API for trading operations and real-time data
- **Notification System**: TTS (Text-to-Speech) and KakaoTalk notifications

**Key Components**:
- Grid trading logic with configurable risk modes (보수적/안정적/공격적/극공격적)
- Real-time price monitoring and chart visualization
- Trading state persistence across sessions
- Automated optimization based on trading performance

## Development Commands

**Installation**:
```bash
# Automated setup
./install.sh              # macOS/Linux
install.bat               # Windows

# Manual setup
python3 -m venv venv
source venv/bin/activate   # macOS/Linux: venv\Scripts\activate on Windows
pip install -r requirements.txt
```

**Running the application**:
```bash
source venv/bin/activate   # Activate virtual environment first
python main.py            # Run the trading bot
```

**Key dependencies**:
- `pyupbit==0.2.34` - Upbit exchange API
- `matplotlib==3.10.5` - Real-time chart visualization
- `tkinter` - GUI framework (built-in with Python)
- `pandas/numpy` - Data processing
- `pyttsx3` - Text-to-speech functionality

## Configuration

**config.json** - Main configuration file:
```json
{
    "upbit_access": "YOUR_UPBIT_ACCESS_KEY",
    "upbit_secret": "YOUR_UPBIT_SECRET_KEY", 
    "total_investment": "100000000",
    "demo_mode": 1,
    "auto_trading_mode": true,
    "risk_mode": "보수적",
    "tts_enabled": true,
    "advanced_grid_trading": true,
    "grid_confirmation_buffer": 0.1,
    "fee_rate": 0.0005
}
```

## Data Files

- **trading_state.json**: Current trading positions and grid states
- **trade_logs.json**: Complete trading history
- **profits.json**: Profit/loss tracking data
- **config.json**: Bot configuration and API keys

## Key Trading Logic

**Grid Trading Strategy**:
1. Calculate grid levels based on price range (high/low of selected period)
2. Wait for grid price + 0.1% confirmation buffer before executing trades
3. Trend-following: Buy on downtrend reversal, sell on uptrend reversal
4. Auto-optimization every hour based on win rate and profit metrics

**Risk Modes**:
- 보수적 (Conservative): 15 grids, 30% investment ratio
- 안정적 (Stable): 20 grids, 50% investment ratio  
- 공격적 (Aggressive): 25 grids, 70% investment ratio
- 극공격적 (Ultra-Aggressive): 30 grids, 90% investment ratio

## GUI Features

- Real-time interactive charts with matplotlib navigation toolbar
- Mouse/keyboard chart controls (drag, zoom, arrow keys)
- Trading status indicators for each coin
- Profit/loss tracking with real-time updates
- Trading log popup window
- Excel export functionality

## Common Tasks

**Adding new features**: All code modifications should be made to `main.py`
**Testing**: Use demo_mode=1 in config.json for safe testing
**Debugging**: Check trade_logs.json for detailed trading history
**Data reset**: Use "데이터초기화" button to clear all trading data

## Security Notes

- Never commit API keys to version control
- Use demo mode for testing new features
- API keys should have minimal required permissions (read + trade only)