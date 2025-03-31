
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import datetime
import uvicorn
import requests
from pymongo import MongoClient
import os
import numpy as np
import os
from dotenv import load_dotenv
load_dotenv()

mongo_uri = os.getenv("MONGO_URI")

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
client = MongoClient("mongodb+srv://zwright134:ytrSF4yXMzrJ0dYY@signalhivecluster.z704jfh.mongodb.net/?retryWrites=true&w=majority&appName=SignalHiveCluster")
db = client["signalhive"]
signals_collection = db["signals"]

# Signal schema
class Signal(BaseModel):
    pair: str
    signal: str
    entry: float
    sl: float
    tp: float
    score: int
    timestamp: str

# Helper to simulate a score (you can expand this)
def generate_signal(pair):
    try:
        url = f"https://api-fxpractice.oanda.com/v3/instruments/{pair}/candles"
        headers = {
            "Authorization": "Bearer f190fd5180959520a82169c94f755e2c-69f3e3afba5796fe4db4d0852699da06"
        }
        params = {
            "granularity": "M15",
            "count": 100,
            "price": "M"
        }
        res = requests.get(url, headers=headers, params=params)
        candles = res.json()["candles"]

        closes = np.array([float(c["mid"]["c"]) for c in candles])
        ema_fast = closes[-5:].mean()
        ema_slow = closes[-20:].mean()

        score = 0
        signal = "Neutral"
        if ema_fast > ema_slow:
            signal = "Buy"
            score += 5
        elif ema_fast < ema_slow:
            signal = "Sell"
            score += 5

        entry = closes[-1]
        sl = entry - 0.002 if signal == "Buy" else entry + 0.002
        tp = entry + 0.004 if signal == "Buy" else entry - 0.004

        return {
            "pair": pair,
            "signal": signal,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "score": score,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"pair": pair, "signal": "Error", "entry": 0, "sl": 0, "tp": 0, "score": 0, "timestamp": str(e)}

# Endpoint: Get recent signals
@app.get("/api/signals", response_model=List[Signal])
def get_signals():
    try:
        recent_signals = list(signals_collection.find().sort("timestamp", -1).limit(10))
        for s in recent_signals:
            s["_id"] = str(s["_id"])
        return recent_signals
    except Exception as e:
        return [{"pair": "ERROR", "signal": str(e), "entry": 0, "sl": 0, "tp": 0, "score": 0, "timestamp": ""}]

# Endpoint: Trigger update
@app.post("/api/update")
def update_signals():
    try:
        pairs = ["EUR_USD", "USD_JPY", "GBP_USD", "AUD_USD"]
        new_signals = []
        for pair in pairs:
            signal_data = generate_signal(pair)
            result = signals_collection.insert_one(signal_data)
            signal_data["_id"] = str(result.inserted_id)  # keep it for reference
            new_signals.append(signal_data)

        # Strip _id before returning
        for s in new_signals:
            if "_id" in s:
                del s["_id"]

        return {"status": "updated", "signals": new_signals}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
