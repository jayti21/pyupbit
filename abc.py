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
interval = "minute3"
count = 2000
trade_amount = 200000   # ✅ 지정 금액 (원화 단위)
log_file = "trade_log.csv"

# ==============================
# 2️⃣ 텔레그램 설정
# ==============================
telegram_token = "8240460505:AAGmA8nHxsTNYYn6E3rMGR_ZO9JyfF-clcQ"
telegram_chat_id = "7906626308"

def send_telegram(msg):
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
# 4️⃣ 장세 판단 함수
# ==============================
def detect_market_trend(df):
    short_ma = df['MA20']
    mid_ma = df['MA40']
    long_ma = df['MA60']
    if short_ma.iloc[-1] > mid_ma.iloc[-1] > long_ma.iloc[-1]:
        return "상승장"
    elif short_ma.iloc[-1] < mid_ma.iloc[-1] < long_ma.iloc[-1]:
        return "하락장"
    else:
        return "횡보장"

# ==============================
# 5️⃣ 데이터 불러오기 + 신호 계산
# ==============================
def get_data():
    df = pyupbit.get_ohlcv(market, interval=interval, count=count)
    if df is None:
        raise ValueError("데이터를 불러오지 못했습니다.")

    # 이동평균 계산
    for ma in [3, 5, 9, 10, 20, 40, 60]:
        df[f'MA{ma}'] = df['close'].rolling(ma).mean()

    # 볼린저밴드
    df['MA_BB'] = df['close'].rolling(20).mean()
    df['BB_STD'] = df['close'].rolling(20).std()
    df['UUpperBBand'] = df['MA_BB'] + 4 * df['BB_STD']
    df['UpperBBand'] = df['MA_BB'] + 2 * df['BB_STD']
    df['CUpperBBand'] = df['MA_BB'] + 0.5 * df['BB_STD']
    df['CLowerBBand'] = df['MA_BB'] - 0.5 * df['BB_STD']
    df['LowerBBand'] = df['MA_BB'] - 2 * df['BB_STD']
    df['LLowerBBand'] = df['MA_BB'] - 7 * df['BB_STD']


    # 장세 판단
    df['Market_Trend'] = df.apply(lambda x: detect_market_trend(df.loc[:x.name]), axis=1)

    # ==============================
    # 장세별 매수/매도 조건 (원래 전략 유지)
    # ==============================
    df['Buy_Signal'] = False
    df['Sell_Signal'] = False

    ## 상승장
    df.loc[df['Market_Trend'] == "상승장", 'Buy_Signal'] = (
        (df['close'] > df['close']) &
        (df['close'].shift(3) < df['close']) &
        (df['close'].shift(2) < df['close']) &
        (df['close'].shift(1) < df['close']) &
        (((df['MA20'].shift(4)-df['MA40'].shift(4))/(df['MA20']-df['MA40'])) > 0.8 ) |
        (df['close'] > df['UpperBBand'])
    )
    df.loc[df['Market_Trend'] == "상승장", 'Sell_Signal'] = (
          (df['MA9'].shift(1) > df['MA9'])
    )
    ## 하락장
    df.loc[df['Market_Trend'] == "하락장", 'Buy_Signal'] = (
        df['Market_Trend'] == "상승장"
    )
    df.loc[df['Market_Trend'] == "하락장", 'Sell_Signal'] = (
        (df['Market_Trend'] == "하락장")
        )
    ## 횡보장
    df.loc[df['Market_Trend'] == "횡보장", 'Buy_Signal'] = (
        ((df['close'] < df['LowerBBand']) &
         (df['close'].shift(2) < df['close']) &
         (df['close'].shift(1) < df['close'])) |
        ((df['close'] < df['MA60']) &
         (df['close'] < df['MA40']) &
         (df['close'] < df['MA20']) &
         (df['close'].shift(1) < df['MA5'])&
         (df['close'].shift(2) < df['MA5'])) 
        )
    df.loc[df['Market_Trend'] == "횡보장", 'Sell_Signal'] = (
        (df['close'] > df['UpperBBand']) |
        (df['close'] < df['LowerBBand']) |
        (df['Market_Trend'].shift(1) == "상승장")
        )  
    
    return df

# ==============================
# 6️⃣ 거래 로그 저장
# ==============================
def log_trade(trade_type, price, profit=None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_data = {
        "Time": timestamp,
        "Type": trade_type,
        "Price": price,
        "Profit(%)": profit if profit is not None else ""
    }

    df_log = pd.DataFrame([log_data])
    if not os.path.exists(log_file):
        df_log.to_csv(log_file, index=False, encoding='utf-8-sig')
    else:
        df_log.to_csv(log_file, mode='a', header=False, index=False, encoding='utf-8-sig')

# ==============================
# 7️⃣ 실시간 거래 루프
# ==============================
in_position = False
buy_price = 0

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

        # 매수 조건
        if latest['Buy_Signal'] and not in_position:
            if balance > trade_amount:
                buy_amt = trade_amount * 0.9995
                order = upbit.buy_market_order(market, buy_amt)
                buy_price = current_price
                in_position = True

                msg = f"🚀 매수 체결!\n{market} @ {current_price:.0f} KRW\n장세: {latest['Market_Trend']}"
                print(msg)
                send_telegram(msg)
                log_trade("BUY", current_price)
            else:
                print("잔고 부족 → 매수 불가")

        # 매도 조건
        elif latest['Sell_Signal'] and in_position:
            if coin_balance > 0:
                order = upbit.sell_market_order(market, coin_balance)
                profit = (current_price - buy_price) / buy_price * 100
                in_position = False

                msg = f"💰 매도 체결!\n{market} @ {current_price:.0f} KRW\n수익률: {profit:.2f}%"
                print(msg)
                send_telegram(msg)
                log_trade("SELL", current_price, profit)
            else:
                print("보유 코인 없음 → 매도 불가")
   
        print(f"{datetime.datetime.now()} | {market} | {latest['Market_Trend']} | MA20: {latest['MA20']} MA40: {latest['MA40']} MA60: {latest['MA60']} | 현재가: {current_price:.0f} | 포지션: {'보유중' if in_position else '대기중'}")
        send_telegram(f"{datetime.datetime.now()} | {market} | {latest['Market_Trend']} | MA20: {latest['MA20']} MA40: {latest['MA40']} MA60:{latest['MA60']} | 현재가: {current_price:.0f} | 포지션: {'보유중' if in_position else '대기중'}")
        time.sleep(180)  # 3분 주기 (minute3)

    except Exception as e:
        print("⚠️ 오류 발생:", e)
        send_telegram(f"⚠️ 오류 발생: {e}")
        time.sleep(10)
