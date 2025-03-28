from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import datetime
import uvicorn
import requests
from pymongo import MongoClient
import os
import numpy as np
from fastapi.middleware.cors import CORSMiddleware  # ✅ Add this line

app = FastAPI()

# ✅ Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Later you can change this to ["https://signalhive.online"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# MongoDB connection
client = MongoClient("mongodb+srv://zwright134:ytrSF4yXMzrJOdYY@signalhivecluster.z704jfh.mongodb.net/?retryWrites=true&w=majority&appName=SignalHiveCluster")
db = client['SignalHive']
signals_collection = db['signals']

# OANDA Setup (Demo endpoint)
OANDA_URL = "https://api-fxpractice.oanda.com/v3/instruments/{}/candles"
API_KEY = "f190fd5180959520a82169c94f755e2c-69f3e3afba5796fe4db4d0852699da06"
ACCOUNT_ID = "101-001-30351568-001"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}"
}

PAIRS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "XAU_USD"]

class Signal(BaseModel):
    pair: str
    signal: str  # Buy, Sell, Neutral
    entry: float
    sl: float
    tp: float
    score: int
    timestamp: str

@app.get("/api/signals", response_model=List[Signal])
def get_signals():
    recent_signals = list(signals_collection.find().sort("timestamp", -1).limit(10))
    for s in recent_signals:
        s["_id"] = str(s["_id"])
    return recent_signals

# Indicator calculations
def RSI(prices, period=14):
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)

    return rsi

def EMA(prices, period):
    return np.convolve(prices, np.ones((period,))/period, mode='valid')

def MACD(prices):
    ema12 = EMA(prices, 12)[-1]
    ema26 = EMA(prices, 26)[-1]
    return ema12 - ema26

def Bollinger(prices, period=20):
    sma = np.mean(prices[-period:])
    std = np.std(prices[-period:])
    upper = sma + 2 * std
    lower = sma - 2 * std
    return upper, lower

def generate_signal(pair: str):
    params = {
        "count": 100,
        "granularity": "H1"
    }
    url = OANDA_URL.format(pair)
    res = requests.get(url, headers=HEADERS, params=params)
    candles = res.json().get("candles", [])

    if not candles:
        return None

    close_prices = [float(c["mid"]["c"]) for c in candles if c["complete"]]
    if len(close_prices) < 30:
        return None

    last_close = close_prices[-1]
    score = 0

    # Indicator Scoring
    rsi_vals = RSI(close_prices)
    rsi_latest = rsi_vals[-1]
    if rsi_latest < 30:
        score += 1  # Oversold
    elif rsi_latest > 70:
        score -= 1  # Overbought

    macd_val = MACD(close_prices)
    if macd_val > 0:
        score += 1
    else:
        score -= 1

    ema_200 = EMA(close_prices, 200)
    if len(ema_200) > 0 and last_close > ema_200[-1]:
        score += 1
    elif len(ema_200) > 0:
        score -= 1

    upper, lower = Bollinger(close_prices)
    if last_close < lower:
        score += 1  # Likely bounce
    elif last_close > upper:
        score -= 1

    # Final signal
    if score >= 4:
        signal = "Strong Buy"
    elif score >= 2:
        signal = "Buy"
    elif score <= -4:
        signal = "Strong Sell"
    elif score <= -2:
        signal = "Sell"
    else:
        signal = "Neutral"

    sl = round(last_close * (0.995 if signal.startswith("Buy") else 1.005), 5)
    tp = round(last_close * (1.005 if signal.startswith("Buy") else 0.995), 5)

    signal_doc = {
        "pair": pair,
        "signal": signal,
        "entry": last_close,
        "sl": sl,
        "tp": tp,
        "score": score,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

    signals_collection.insert_one(signal_doc)
    return signal_doc

@app.post("/api/update")
def update_all_signals():
    results = []
    for pair in PAIRS:
        result = generate_signal(pair)
        if result:
            results.append(result)
    return {"status": "updated", "signals": results}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
