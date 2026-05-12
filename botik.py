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
# STATE MEMORY (ГЛАВНОЕ УЛУЧШЕНИЕ)
# =========================

state = {}  # asset → {phase, direction, strength, time}

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

    if len(df) < 80:
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
    ema50 = EMAIndicator(close, 50).ema_indicator()

    adx = ADXIndicator(df["High"], df["Low"], close, 14).adx()

    return rsi, macd, ema9, ema20, ema50, adx

# =========================
# LOGIC HELPERS
# =========================

def arrow(direction):
    return "⬆️ BUY" if direction == "BUY" else "⬇️ SELL"


# RSI breakout (ВАЖНО ИСПРАВЛЕНО)
def rsi_logic(rsi):

    prev = rsi.iloc[-2]
    now = rsi.iloc[-1]

    buy = prev < 30 and now > 30
    sell = prev > 70 and now < 70

    return buy, sell


# MACD momentum (не только cross)
def macd_logic(macd):

    m = macd.macd()
    s = macd.macd_signal()

    buy = m.iloc[-1] > s.iloc[-1] and m.iloc[-1] > m.iloc[-2]
    sell = m.iloc[-1] < s.iloc[-1] and m.iloc[-1] < m.iloc[-2]

    return buy, sell


# EMA trend
def ema_logic(ema9, ema20, ema50):

    buy = ema9.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]
    sell = ema9.iloc[-1] < ema20.iloc[-1] < ema50.iloc[-1]

    return buy, sell


# ADX filter
def adx_logic(adx):

    val = adx.iloc[-1]

    return val > 22, val  # active market + value

# =========================
# PHASE ENGINE (ГЛАВНАЯ ЛОГИКА)
# =========================

def analyze(asset):

    df = get_data(asset)
    if df is None:
        return

    rsi, macd, ema9, ema20, ema50, adx = indicators(df)

    if len(df) < 80:
        return

    rsi_buy, rsi_sell = rsi_logic(rsi)
    macd_buy, macd_sell = macd_logic(macd)
    ema_buy, ema_sell = ema_logic(ema9, ema20, ema50)
    market_ok, adx_val = adx_logic(adx)

    if not market_ok:
        return

    buy_score = sum([rsi_buy, macd_buy, ema_buy])
    sell_score = sum([rsi_sell, macd_sell, ema_sell])

    direction = "BUY" if buy_score >= sell_score else "SELL"
    score = buy_score if direction == "BUY" else sell_score

    # =========================
    # STATE MEMORY
    # =========================

    prev_state = state.get(asset, {})

    phase = "SETUP"

    if score == 1:
        phase = "SETUP"
    elif score == 2:
        phase = "CONFIRM"
    elif score == 3:
        phase = "ENTRY"

    # защита от повторов
    if prev_state.get("phase") == phase:
        return

    state[asset] = {
        "phase": phase,
        "direction": direction,
        "time": time.time()
    }

    # =========================
    # MESSAGES
    # =========================

    if phase == "SETUP":

        send_telegram(f"""
📊 {asset}

⚠️ SETUP {arrow(direction)}

Рынок начинает формировать движение
ADX: {round(adx_val,2)}
""")

    elif phase == "CONFIRM":

        send_telegram(f"""
📊 {asset}

⏳ CONFIRMATION {arrow(direction)}

Идёт подтверждение сигнала
2/3 условий выполнены
ADX: {round(adx_val,2)}
""")

    elif phase == "ENTRY":

        send_telegram(f"""
🔥 {asset}

{arrow(direction)} — ВХОД СЕЙЧАС

✔ RSI + MACD + EMA подтверждены
📊 ADX: {round(adx_val,2)}

⚡ ОТКРЫВАЙ СДЕЛКУ
""")

# =========================
# LOOP
# =========================

def loop():

    while True:
        try:
            for a in ASSETS:
                analyze(a)

            time.sleep(10)

        except Exception as e:
            print("error:", e)
            time.sleep(5)

# =========================
# TELEGRAM COMMAND
# =========================

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running PRO v2")

# =========================
# START
# =========================

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("check", check))

threading.Thread(target=loop, daemon=True).start()

print("PRO v2 bot started")
app.run_polling()
