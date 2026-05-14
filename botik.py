import time
import requests
import pandas as pd
import yfinance as yf
import threading
import os
from dotenv import load_dotenv

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================
# SETTINGS
# =========================

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

ASSETS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCAD=X",
    "USDCHF=X", "EURCAD=X", "EURGBP=X", "GBPCHF=X",
    "GBPJPY=X", "EURJPY=X", "AUDUSD=X", "AUDNZD=X",
    "BTC-USD", "AUDJPY=X", "NZDJPY=X",
    "AAPL", "TSLA", "MSFT", "GOOGL"
]

COOLDOWN = 180  # 3 минуты

state = {}
last_signal_time = {}

# =========================
# TELEGRAM
# =========================

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# =========================
# DATA
# =========================

def get_data(asset):
    df = yf.download(asset, period="5d", interval="5m", progress=False)

    if df is None or df.empty:
        return None

    df = df[["Open", "High", "Low", "Close"]].dropna()

    if len(df) < 60:
        return None

    return df

# =========================
# INDICATORS
# =========================

def indicators(df):
    close = df["Close"]

    rsi = RSIIndicator(close, 14).rsi()
    macd = MACD(close)

    ema9 = EMAIndicator(close, 9).ema_indicator()
    ema20 = EMAIndicator(close, 20).ema_indicator()

    adx = ADXIndicator(df["High"], df["Low"], close, 14).adx()

    return rsi, macd, ema9, ema20, adx

# =========================
# ANALYZE
# =========================

def analyze(asset):
    df = get_data(asset)
    if df is None:
        return

    rsi, macd, ema9, ema20, adx = indicators(df)

    rsi_now = rsi.iloc[-1]
    adx_now = adx.iloc[-1]

    # =========================
    # EMA TREND
    # =========================

    ema_buy = ema9.iloc[-1] > ema20.iloc[-1]
    ema_sell = ema9.iloc[-1] < ema20.iloc[-1]

    # =========================
    # MACD
    # =========================

    macd_line = macd.macd()
    signal_line = macd.macd_signal()
    hist = macd_line - signal_line

    macd_buy = hist.iloc[-1] > 0 and hist.iloc[-2] <= 0
    macd_sell = hist.iloc[-1] < 0 and hist.iloc[-2] >= 0

    # =========================
    # RSI
    # =========================

    rsi_buy = rsi_now > 50
    rsi_sell = rsi_now < 50

    # =========================
    # FILTER FLAT
    # =========================

    if adx_now < 15:
        return

    # =========================
    # SCORE
    # =========================

    buy_score = int(ema_buy) + int(macd_buy) + int(rsi_buy)
    sell_score = int(ema_sell) + int(macd_sell) + int(rsi_sell)

    direction = "BUY" if buy_score > sell_score else "SELL"
    score = max(buy_score, sell_score)

    if score < 2:
        return

    # =========================
    # EXPIRATION (3–6 candles)
    # =========================

    if adx_now < 18:
        expiry = 3
    elif adx_now < 22:
        expiry = 4
    elif adx_now < 28:
        expiry = 5
    else:
        expiry = 6

    # =========================
    # COOLDOWN
    # =========================

    now = time.time()
    last_time = last_signal_time.get(asset, 0)

    if now - last_time < COOLDOWN:
        return

    last_signal_time[asset] = now

    # =========================
    # SEND SIGNAL
    # =========================

    send_telegram(
        f"""
📊 {asset}

➡️ Direction: {direction}

⏱ Expiry: {expiry} candles ({expiry * 5} min)

⭐ Signal strength: {score}/3
"""
    )

    state[asset] = {
        "asset": asset,
        "direction": direction,
        "score": score,
        "expiry": expiry,
        "time": now
    }

# =========================
# LOOP
# =========================

def loop():
    while True:
        for asset in ASSETS:
            try:
                analyze(asset)
            except Exception as e:
                print(f"Error {asset}:", e)

        time.sleep(10)

# =========================
# STATUS COMMAND
# =========================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not state:
        await update.message.reply_text("📊 Нет активных сигналов")
        return

    msg = "🧠 LIVE SIGNALS\n\n"
    now = time.time()

    for asset, data in state.items():
        age = int(now - data["time"])

        msg += (
            f"{asset}\n"
            f"{data['direction']} | {data['score']}/3\n"
            f"Expiry: {data['expiry']} candles\n"
            f"Age: {age}s\n\n"
        )

    await update.message.reply_text(msg)

# =========================
# START BOT
# =========================

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("status", status))

threading.Thread(target=loop, daemon=True).start()

print("BOT RUNNING (5m BINARIUM PRO VERSION)")
app.run_polling()
