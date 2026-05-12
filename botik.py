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
# MEMORY (ЖИВОЙ МОЗГ)
# =========================

state = {}              # текущая фаза
signal_time = {}        # время входа в фазу

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
# HELPERS
# =========================

def arrow(direction):
    return "⬆️ BUY" if direction == "BUY" else "⬇️ SELL"


def probability(score, adx):
    p = 50 + score * 15 + (adx - 20) * 1.2
    return int(max(10, min(95, p)))

# =========================
# LOGIC
# =========================

def analyze(asset):

    df = get_data(asset)
    if df is None:
        return

    rsi, macd, ema9, ema20, ema50, adx = indicators(df)

    if adx.iloc[-1] < 22:
        return

    # RSI
    rsi_prev, rsi_now = rsi.iloc[-2], rsi.iloc[-1]
    rsi_buy = rsi_prev < 30 and rsi_now > 30
    rsi_sell = rsi_prev > 70 and rsi_now < 70

    # MACD
    macd_line = macd.macd()
    signal_line = macd.macd_signal()

    macd_buy = macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]
    macd_sell = macd_line.iloc[-2] > signal_line.iloc[-2] and macd_line.iloc[-1] < signal_line.iloc[-1]

    # EMA
    ema_buy = ema9.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1]
    ema_sell = ema9.iloc[-1] < ema20.iloc[-1] < ema50.iloc[-1]

    buy_score = sum([rsi_buy, macd_buy, ema_buy])
    sell_score = sum([rsi_sell, macd_sell, ema_sell])

    direction = "BUY" if buy_score >= sell_score else "SELL"
    score = max(buy_score, sell_score)

    prob = probability(score, adx.iloc[-1])

    # =========================
    # STATE MEMORY
    # =========================

    prev = state.get(asset, {}).get("phase")

    if score == 1:
        phase = "SETUP"
    elif score == 2:
        phase = "CONFIRM"
    elif score == 3:
        phase = "ENTRY"
    else:
        return

    # защита от спама
    if prev == phase:
        return

    state[asset] = {
        "phase": phase,
        "direction": direction,
        "time": time.time(),
        "prob": prob
    }

    signal_time[asset] = time.time()

    # =========================
    # MESSAGES
    # =========================

    if phase == "SETUP":
        send_telegram(f"""
📊 {asset}

⚠️ SETUP {arrow(direction)}
Формируется движение
📊 Probability: {prob}%
""")

    elif phase == "CONFIRM":
        send_telegram(f"""
📊 {asset}

⏳ CONFIRM {arrow(direction)}
2/3 условий выполнены
📊 Probability: {prob}%
""")

    elif phase == "ENTRY":
        send_telegram(f"""
🔥 {asset}

{arrow(direction)} — ВХОД СЕЙЧАС

📊 Probability: {prob}%
⚡ ОТКРЫВАЙ СДЕЛКУ
""")

# =========================
# STATUS (ЖИВОЙ МОЗГ)
# =========================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not state:
        await update.message.reply_text("📊 Нет активных сигналов")
        return

    msg = "🧠 LIVE BRAIN STATUS\n\n"

    now = time.time()

    for asset, data in state.items():

        t = int(now - data["time"])

        msg += (
            f"{asset}\n"
            f"{data['phase']} {arrow(data['direction'])}\n"
            f"Prob: {data['prob']}%\n"
            f"Age: {t} sec\n\n"
        )

    await update.message.reply_text(msg)

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
            print(e)
            time.sleep(5)

# =========================
# START
# =========================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("status", status))

threading.Thread(target=loop, daemon=True).start()

print("PRO v2.5 running")
app.run_polling()
