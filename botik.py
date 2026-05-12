import time
import requests
import pandas as pd
import yfinance as yf
import threading

def safe_series(x):
    if hasattr(x, "squeeze"):
        return x.squeeze()
    return x

from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================
# SETTINGS
# =========================

import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

ASSETS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCAD=X",
    "USDCHF=X", "EURCAD=X", "EURGBP=X",
    "GBPJPY=X", "EURJPY=X", "AUDUSD=X",
    "BTC-USD", "ETH-USD",
    "AAPL", "TSLA", "MSFT", "GOOGL"
]

active_signals = {}

# =========================
# TELEGRAM
# =========================

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except:
        pass

# =========================
# SAFE DATA LOADER (FIXED)
# =========================

def get_data(asset):

    try:
        df = yf.download(asset, period="1d", interval="1m", progress=False)
    except:
        return None

    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close"]].dropna()

    df["Close"] = df["Close"].squeeze()
    df["Open"] = df["Open"].squeeze()
    df["High"] = df["High"].squeeze()
    df["Low"] = df["Low"].squeeze()

    if len(df) < 60:
        return None

    df["Close"] = df["Close"].astype(float)

    return df

# =========================
# FILTERS
# =========================

def is_flat(df):
    try:
        adx = ADXIndicator(df["High"], df["Low"], df["Close"], 14).adx()
        return adx.iloc[-1] < 22
    except:
        return True


def is_news(df):
    try:
        atr = AverageTrueRange(df["High"], df["Low"], df["Close"], 14).average_true_range()
        return atr.iloc[-1] > atr.mean() * 2
    except:
        return True

# =========================
# COOLDOWN
# =========================

def can_send(asset):
    if asset in active_signals:
        if time.time() - active_signals[asset] < 600:
            return False
    return True

# =========================
# 5M TREND (FIXED SAFE)
# =========================

def get_trend_5m(asset):

    try:
        df = yf.download(asset, period="1d", interval="5m", progress=False)
    except:
        return None

    if df is None or df.empty:
        return None

    if len(df) < 50:
        return None

    close = df["Close"].squeeze().astype(float)

    ema20 = EMAIndicator(close, 20).ema_indicator()
    ema50 = EMAIndicator(close, 50).ema_indicator()

    if ema20.isna().iloc[-1] or ema50.isna().iloc[-1]:
        return None

    return "UP" if ema20.iloc[-1] > ema50.iloc[-1] else "DOWN"

# =========================
# SCORE ENGINE
# =========================

def get_score(df):

    last = df.iloc[-1]

    score = 0
    direction = None

    ema_up = last["EMA9"] > last["EMA20"] > last["EMA50"]
    ema_down = last["EMA9"] < last["EMA20"] < last["EMA50"]

    if ema_up:
        score += 25
        direction = "CALL"
    elif ema_down:
        score += 25
        direction = "PUT"

    if direction == "CALL" and 50 <= last["RSI"] <= 72:
        score += 15
    elif direction == "PUT" and 28 <= last["RSI"] <= 48:
        score += 15

    if direction == "CALL" and last["MACD"] > last["MACD_SIGNAL"]:
        score += 20
    elif direction == "PUT" and last["MACD"] < last["MACD_SIGNAL"]:
        score += 20

    if last["ADX"] > 28:
        score += 30
    elif last["ADX"] > 22:
        score += 15

    return score, direction, last["ADX"]

# =========================
# EXPIRATION
# =========================

def get_exp(score, adx):

    if score >= 80 and adx > 30:
        return "2 min"
    elif score >= 75:
        return "3 min"
    elif score >= 65:
        return "4 min"
    elif score >= 60:
        return "5 min"
    else:
        return None

# =========================
# VALIDATION
# =========================

def is_valid(score, adx):
    return score >= 65 and adx >= 25

# =========================
# ANALYZE (STABLE)
# =========================

def analyze_asset(asset):

    if not can_send(asset):
        return None

    df = get_data(asset)

    if df is None:
        return None

    if is_flat(df) or is_news(df):
        return None

    df["EMA9"] = EMAIndicator(df["Close"], 9).ema_indicator()
    df["EMA20"] = EMAIndicator(df["Close"], 20).ema_indicator()
    df["EMA50"] = EMAIndicator(df["Close"], 50).ema_indicator()

    df["RSI"] = RSIIndicator(df["Close"], 14).rsi()

    macd = MACD(df["Close"])
    df["MACD"] = macd.macd()
    df["MACD_SIGNAL"] = macd.macd_signal()

    adx = ADXIndicator(df["High"], df["Low"], df["Close"], 14).adx()
    df["ADX"] = adx

    df = df.dropna()

    score, direction, adx_val = get_score(df)

    if not is_valid(score, adx_val):
        return None

    trend_5m = get_trend_5m(asset)

    if trend_5m is None:
        return None

    if direction == "CALL" and trend_5m != "UP":
        return None

    if direction == "PUT" and trend_5m != "DOWN":
        return None

    exp = get_exp(score, adx_val)

    if exp is None:
        return None

    return {
        "asset": asset,
        "signal": f"STRONG {direction}",
        "score": score,
        "expiration": exp,
        "adx": adx_val
    }

# =========================
# SEND SIGNAL
# =========================

def send_signal(data):

    active_signals[data["asset"]] = time.time()

    msg = f"""
📊 {data['asset']}

🔥 {data['signal']}
📈 Score: {data['score']}/100
⏱ Expiration: {data['expiration']}
📊 ADX: {round(data['adx'],2)}
"""

    send_telegram(msg)

# =========================
# LOOP (SAFE)
# =========================

def auto_loop():

    while True:

        try:
            for asset in ASSETS:

                data = analyze_asset(asset)

                if data:
                    send_signal(data)

            time.sleep(10)

        except Exception as e:
            print("Loop error:", e)
            time.sleep(5)

# =========================
# TELEGRAM COMMANDS
# =========================

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):

    results = []

    for asset in ASSETS:

        data = analyze_asset(asset)

        if data:
            results.append(f"{asset} → {data['signal']} ({data['score']})")

    await update.message.reply_text("\n".join(results) if results else "⛔ Нет сигналов")


# =========================
# START
# =========================

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("check", check))

threading.Thread(target=auto_loop, daemon=True).start()

print("Bot started...")
app.run_polling()
