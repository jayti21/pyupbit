import pyupbit
import pandas as pd
import numpy as np
import time
import datetime
import requests
import os

# ==============================
# 1️⃣ 기본 설정
# ==============================
access = "lSWxkEmAF73kGsf4xQSgvE7dh1mu16O0R1LTYWWR"
secret = "OEgT6ziEoNHl3AeDfXHgxXIHj9ZvGxvD4hVcuaLO"
market = "KRW-VIRTUAL"  # 거래 마켓
interval = "minute1"
count = 200
trade_amount = 100000   # 매수 금액 (원화)
log_file = "trade_log.csv"

# ==============================
# 2️⃣ 텔레그램 설정
# ==============================
# telegram_token = "8240460505:AAGmA8nHxsTNYYn6E3rMGR_ZO9JyfF-clcQ"  ##BOT_1
# telegram_chat_id = "7906626308"

telegram_token = "8542911616:AAHjHJ-nK3k0iaNY2QVjMUvhD18TA4Fr15c" ## BOT_2
telegram_chat_id = "7906626308"

def send_telegram(msg):
    """텔레그램 메시지 전송"""
    try:
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        params = {"chat_id": telegram_chat_id, "text": msg}
        requests.get(url, params=params)
    except Exception as e:
        print("⚠️ 텔레그램 전송 실패:", e)

# ==============================
# 3️⃣ 업비트 객체 생성
# ==============================
upbit = pyupbit.Upbit(access, secret)

print("✅ 자동매매 시작:", datetime.datetime.now())
send_telegram("🤖 자동매매 시작됨!")

# ==============================
# 2️⃣ 장세 판단 함수
# ==============================
def detect_market_trend(df):
    short_ma = df['MA9']
    mid_ma = df['MA20']
    long_ma = df['MA40']

    if short_ma.iloc[-1] > mid_ma.iloc[-1] > long_ma.iloc[-1]:
        return "상승장"
    elif short_ma.iloc[-1] < mid_ma.iloc[-1] < long_ma.iloc[-1]:
        return "하락장"
    else:
        return "횡보장"

# ==============================
# 3️⃣ 데이터 불러오기 + 신호 계산
# ==============================
def get_data():
    df = pyupbit.get_ohlcv(market, interval=interval, count=count)
    if df is None:
        raise ValueError("데이터 불러오기 실패")

    for ma in [3, 5, 9, 20, 40]:
        df[f'MA{ma}'] = df['close'].rolling(ma).mean()

    df['MAA'] = (df['close']*0.5 + df['MA3']*0.5 + df['MA5']) / 2
    df['MAA3'] = df['MAA'].rolling(3).mean()

    df['MA_BB'] = df['close'].rolling(10).mean()
    df['BB_STD'] = df['close'].rolling(10).std()
    df['UpperBBand'] = df['MA_BB'] + 2 * df['BB_STD']
    df['LowerBBand'] = df['MA_BB'] - 2 * df['BB_STD']

    df['Market_Trend'] = df.apply(lambda x: detect_market_trend(df.loc[:x.name]), axis=1)
    df['Buy_Signal'] = False

    # 상승장
    df.loc[df['Market_Trend'] == "상승장", 'Buy_Signal'] = (
        # ((df['MA9'].shift(1) < df['MA20'].shift(1)) &
        # (df['MA9'] > df['MA20']) &) |
        # ((df['close'] > df['MA3']) &
        (df['close'].shift(2) > df['close'].shift(1)) &
        (df['close'].shift(1) > df['close']) &
        (df['MA3'] > df['MA5']) &
        (df['MA5'] > df['MA9']) &
        (df['MA9'] > df['MA20']) &
        (((df['MA9'].shift(1)-df['MA20'].shift(1))/(df['MA9']-df['MA20'])) <  1)
        )
    
    df.loc[df['Market_Trend'] == "상승장", 'Sell_Signal'] = (False        
    )
    

    df.loc[df['Market_Trend'] == "횡보장", 'Buy_Signal'] = (
        # ((df['close'] > df['MA3']) &
        (df['close'].shift(2) > df['close'].shift(1)) &
        (df['close'].shift(1) > df['close']) &
        (df['MA3'] > df['MA5']) &
        (df['MA5'] > df['MA9']) &
        (df['MA9'] > df['MA20']) &
        (((df['MA9'].shift(2)-df['MA20'].shift(2))/(df['MA9']-df['MA20'])) <  1)
        )
    
    df.loc[df['Market_Trend'] == "횡보장", 'Sell_Signal'] = (False)
    

    df.loc[df['Market_Trend'] == "하락장", 'Buy_Signal'] = ( False
        # ((df['close'] > df['MA3']) &
        # (df['MA3'] > df['MA5']) &
        # (df['MA5'] > df['MA9']) &
        # (df['MA9'] > df['MA20']) 
        )
    
    df.loc[df['Market_Trend'] == "하락장", 'Sell_Signal'] = (False)

    return df

# ==============================
# 6️⃣ 거래 로그 저장
# ==============================
def log_trade(trade_type, price, profit=None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_data = {"Time": timestamp, "Type": trade_type, "Price": price, "Profit(%)": profit if profit is not None else ""}
    df_log = pd.DataFrame([log_data])

    if not os.path.exists(log_file):
        df_log.to_csv(log_file, index=False, encoding='utf-8-sig')
    else:
        df_log.to_csv(log_file, mode='a', header=False, index=False, encoding='utf-8-sig')

# ==============================
# 7️⃣ 실시간 거래 루프 (수익률 + 손절 + 트레일링 스탑)
# ==============================
in_position = False
buy_price = 0
max_profit_pct = 0  # 최고 수익률 추적

# 장세별 수익 / 손절 / 트레일링 스탑 기준 (%)
profit_targets = {"상승장": 3, "횡보장": 3, "하락장": 3}
stop_losses = {"상승장": -0.5, "횡보장": -0.5, "하락장": -0.5}
trailing_gaps = {"상승장": 0.5, "횡보장": 0.5, "하락장": 0.5}

while True:
    try:
        df = get_data()
        if df is None:
            print("⚠️ 데이터 불러오기 실패")
            time.sleep(10)
            continue

        latest = df.iloc[-1]
        current_price = pyupbit.get_current_price(market)
        coin_balance = upbit.get_balance(market.replace("KRW-", ""))
        balance = upbit.get_balance("KRW")
        market_trend = latest['Market_Trend']

        # ✅ 매수 로직
        if latest['Buy_Signal'] and not in_position:
            if balance > trade_amount:
                buy_amt = trade_amount * 0.9995
                order = upbit.buy_market_order(market, buy_amt)
                buy_price = current_price
                in_position = True
                max_profit_pct = 0

                msg = f"🚀 매수 체결!\n{market} @ {current_price:.0f} KRW\n장세: {market_trend}"
                print(msg)
                send_telegram(msg)
                log_trade("BUY", current_price)
            else:
                print("잔고 부족 → 매수 불가")

        # ✅ 매도 로직 (Sell 신호 + 목표수익 + 손절 + 트레일링 스탑)
        elif in_position:
            profit_pct = (current_price - buy_price) / buy_price * 100
            target_profit = profit_targets.get(market_trend, 2.0)
            stop_loss = stop_losses.get(market_trend, -1.0)
            trailing_gap = trailing_gaps.get(market_trend, 0.8)

            if profit_pct > max_profit_pct:
                max_profit_pct = profit_pct

            trigger = False
            reason = ""

            if latest['Sell_Signal']:
                reason = "📉 매도 신호 발생"
                trigger = True
            elif profit_pct >= target_profit:
                reason = f"🎯 목표 수익률 {target_profit}% 도달"
                trigger = True
            elif profit_pct <= stop_loss:
                reason = f"⚠️ 손절 기준 {stop_loss}% 도달"
                trigger = True
            elif profit_pct < (max_profit_pct - trailing_gap) and max_profit_pct > 0:
                reason = f"🔁 트레일링 스탑 발동 (최고 {max_profit_pct:.2f}% → 현재 {profit_pct:.2f}%)"
                trigger = True

            if trigger and coin_balance > 0:
                order = upbit.sell_market_order(market, coin_balance)
                in_position = False
                msg = f"💰 매도 체결!\n{market} @ {current_price:.0f} KRW\n이유: {reason}\n수익률: {profit_pct:.2f}%"
                print(msg)
                send_telegram(msg)
                log_trade("SELL", current_price, profit_pct)

        # ✅ 상태 출력 및 알림
        log_msg = (
            f"PC_{datetime.datetime.now()} | {market} | {market_trend} | "
            f"MA9: {latest['MA9']:.1f} MA20: {latest['MA20']:.1f} MA40: {latest['MA40']:.1f} | "
            f"현재가: {current_price:.0f} | 수익률: {profit_pct if in_position else 0:.2f}% | "
            f"최고수익률: {max_profit_pct:.2f}% | 포지션: {'보유중' if in_position else '대기중'}"
        )
        print(log_msg)
        send_telegram(log_msg)

        time.sleep(60)

    except Exception as e:
        print("⚠️ 오류 발생:", e)
        send_telegram(f"⚠️ 오류 발생: {e}")
        time.sleep(10)
