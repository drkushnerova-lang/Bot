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
    "USDCHF=X", "EURCAD=X", "EURGBP=X",
    "GBPJPY=X", "EURJPY=X", "AUDUSD=X",
    "BTC-USD", "ETH-USD",
    "AAPL", "TSLA", "MSFT", "GOOGL"
]

# =========================
# MEMORY
# =========================

state = {}
last_signal_time = {}
pre_signal_time = {}

COOLDOWN = 180  # 3 минуты между сигналами

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
# DATA
# =========================

def get_data(asset):
    df = yf.download(asset, period="1d", interval="1m", progress=False)

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
# LOGIC
# =========================

def analyze(asset):
    df = get_data(asset)
    if df is None:
        return

    rsi, macd, ema9, ema20, adx = indicators(df)

    rsi_now = rsi.iloc[-1]
    adx_now = adx.iloc[-1]

    # =========================
    # MACD HISTOGRAM (IMPROVED)
    # =========================

    macd_line = macd.macd()
    signal_line = macd.macd_signal()

    hist = macd_line - signal_line

    macd_buy = hist.iloc[-2] < 0 and hist.iloc[-1] > 0   # красный → зелёный
    macd_sell = hist.iloc[-2] > 0 and hist.iloc[-1] < 0  # зелёный → красный

    # =========================
    # CONDITIONS
    # =========================

    rsi_buy = rsi_now > 50
    rsi_sell = rsi_now < 50

    ema_buy = ema9.iloc[-1] > ema20.iloc[-1]
    ema_sell = ema9.iloc[-1] < ema20.iloc[-1]

    buy_score = int(rsi_buy) + int(macd_buy) + int(ema_buy)
    sell_score = int(rsi_sell) + int(macd_sell) + int(ema_sell)

    direction = "BUY" if buy_score >= sell_score else "SELL"
    score = max(buy_score, sell_score)

    # =========================
    # FILTERS
    # =========================

    if adx_now < 12:
        return

    if score < 2:
        return

    now = time.time()

    # cooldown
    last_time = last_signal_time.get(asset, 0)
    if now - last_time < COOLDOWN:
        return

    # =========================
    # PRE-SIGNAL LOGIC
    # =========================

    last_pre = pre_signal_time.get(asset, 0)

    if score == 2 and now - last_pre > 60:
        pre_signal_time[asset] = now

        send_telegram(
            f"""
⏳ {asset}

⚠️ PRE-SIGNAL
Возможный вход через 30–60 сек

📊 Direction: {direction}
📈 Strength: {score}/3
RSI: {round(rsi_now, 1)}
ADX: {round(adx_now, 1)}
"""
        )
        return

    # =========================
    # ENTRY SIGNAL
    # =========================

    if score == 3:
        last_signal_time[asset] = now

        send_telegram(
            f"""
🔥 {asset}

🚀 ENTRY NOW
{direction}

📈 Strength: 3/3
📊 Probability: {50 + score * 12 + (adx_now - 15) * 1.5:.0f}%

RSI: {round(rsi_now, 1)}
ADX: {round(adx_now, 1)}

⚡ ВХОД СЕЙЧАС
"""
        )

        state[asset] = {
            "direction": direction,
            "score": score,
            "time": now
        }

# =========================
# STATUS
# =========================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not state:
        await update.message.reply_text("📊 Пока нет активных сигналов")
        return

    msg = "🧠 LIVE STATUS\n\n"
    now = time.time()

    for asset, data in state.items():
        age = int(now - data["time"])

        msg += (
            f"{asset}\n"
            f"{data['direction']} | {data['score']}/3\n"
            f"Age: {age}s\n\n"
        )

    await update.message.reply_text(msg)

# =========================
# LOOP
# =========================

def loop():
    while True:
        for a in ASSETS:
            try:
                analyze(a)
            except:
                pass

        time.sleep(10)

# =========================
# START
# =========================

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("status", status))

threading.Thread(target=loop, daemon=True).start()

print("BOT RUNNING v3 (PRE-SIGNAL ENABLED)")
app.run_polling()
