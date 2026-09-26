"""
GPT-6 Astra Standby + OANDA XAUUSD Live Chart + Alerts - LIGHTWEIGHT
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
from dotenv import load_dotenv
from datetime import datetime
import threading
import time

load_dotenv()

app = FastAPI(title="Astra Standby + XAUUSD")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OANDA_API_KEY = os.getenv("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_ENVIRONMENT = os.getenv("OANDA_ENVIRONMENT", "practice")
MODEL_ID = os.getenv("ASTRA_MODEL", "gpt-6-astra")

alerts_log = []
last_signal = 0
last_alert_time = None
last_oanda_error = None

class ChatRequest(BaseModel):
    message: str
    history: list = []
    system_prompt: str = "You are GPT-6 Astra standby on XAUUSD site."

class ChatResponse(BaseModel):
    reply: str
    model: str

def get_oanda_client():
    global last_oanda_error
    if not OANDA_API_KEY:
        last_oanda_error = "OANDA_API_KEY env missing"
        return None
    try:
        import oandapyV20
        return oandapyV20.API(access_token=OANDA_API_KEY, environment=OANDA_ENVIRONMENT)
    except Exception as e:
        last_oanda_error = f"oandapyV20 import/client error: {e}"
        return None

def fetch_xauusd_oanda(granularity="M15", count=100):
    global last_oanda_error
    client = get_oanda_client()
    if not client:
        return None
    try:
        import oandapyV20.endpoints.instruments as instruments
        params = {"granularity": granularity, "count": count}
        r = instruments.InstrumentsCandles(instrument="XAU_USD", params=params)
        client.request(r)
        rows = []
        for c in r.response['candles']:
            if not c['complete']:
                continue
            rows.append({
                "time": c['time'],
                "open": float(c['mid']['o']),
                "high": float(c['mid']['h']),
                "low": float(c['mid']['l']),
                "close": float(c['mid']['c']),
                "volume": int(c['volume'])
            })
        last_oanda_error = None
        return rows
    except Exception as e:
        last_oanda_error = f"OANDA fetch error: {e}"
        print(last_oanda_error)
        return None

def ema(prices, period):
    k = 2/(period+1)
    ema_vals = [prices[0]]
    for p in prices[1:]:
        ema_vals.append(p*k + ema_vals[-1]*(1-k))
    return ema_vals

def rsi(prices, period=14):
    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff,0))
        losses.append(max(-diff,0))
    if len(gains) < period:
        return [50]*len(prices)
    avg_gain = sum(gains[:period])/period
    avg_loss = sum(losses[:period])/period
    rsi_vals = [0]*period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain*(period-1) + gains[i])/period
        avg_loss = (avg_loss*(period-1) + losses[i])/period
        if avg_loss==0:
            rsi_vals.append(100)
        else:
            rs = avg_gain/avg_loss
            rsi_vals.append(100 - (100/(1+rs)))
    return [50]* (len(prices)-len(rsi_vals)) + rsi_vals

def atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]['high']
        l = candles[i]['low']
        pc = candles[i-1]['close']
        tr = max(h-l, abs(h-pc), abs(l-pc))
        trs.append(tr)
    if len(trs) < period:
        return [5.0]*len(candles)
    avg = sum(trs[:period])/period
    atr_vals = [avg]*period
    for i in range(period, len(trs)):
        avg = (avg*(period-1) + trs[i])/period
        atr_vals.append(avg)
    return [atr_vals[0]]*(len(candles)-len(atr_vals)) + atr_vals

def compute_signal(candles):
    if not candles or len(candles) < 60:
        return None
    closes = [c['close'] for c in candles]
    ema_fast = ema(closes, 20)
    ema_slow = ema(closes, 50)
    rsi_vals = rsi(closes, 14)
    atr_vals = atr(candles, 14)
    last = len(closes)-1
    prev = last-1
    sig = 0
    if ema_fast[last] > ema_slow[last] and ema_fast[prev] <= ema_slow[prev] and rsi_vals[last] < 70 and rsi_vals[last] > 50:
        sig = 1
    elif ema_fast[last] < ema_slow[last] and ema_fast[prev] >= ema_slow[prev] and rsi_vals[last] > 30 and rsi_vals[last] < 50:
        sig = -1
    return {
        "close": closes[last],
        "ema_fast": ema_fast[last],
        "ema_slow": ema_slow[last],
        "rsi": rsi_vals[last],
        "atr": atr_vals[last],
        "signal": sig,
        "time": candles[last]['time']
    }

def generate_alert_text(sig):
    price = sig['close']
    atr_v = sig['atr']
    sl = price - atr_v*1.5 if sig['signal']==1 else price + atr_v*1.5
    tp = price + atr_v*3.0 if sig['signal']==1 else price - atr_v*3.0
    direction = "LONG 🟢 BUY" if sig['signal']==1 else "SHORT 🔴 SELL"
    return f"""🚨 ASTRA ALERT: XAUUSD {direction}
Price: ${price:.2f}
Reason: EMA 20 ({sig['ema_fast']:.2f}) crossed {'above' if sig['signal']==1 else 'below'} EMA 50 ({sig['ema_slow']:.2f}) + RSI {sig['rsi']:.1f}
Risk: SL ${sl:.2f} (1.5x ATR) | TP ${tp:.2f} (3x ATR) | RR 1:2
ATR: {atr_v:.2f} | Time: {sig['time'][:16]} UTC
Account: {OANDA_ACCOUNT_ID}"""

def check_and_alert():
    global last_signal, last_alert_time, alerts_log
    while True:
        try:
            candles = fetch_xauusd_oanda("M15", 100)
            if not candles:
                time.sleep(60)
                continue
            sig = compute_signal(candles)
            if not sig:
                time.sleep(60)
                continue
            cur = sig['signal']
            if cur !=0 and cur != last_signal:
                txt = generate_alert_text(sig)
                entry = {"time": datetime.utcnow().isoformat(), "signal": cur, "price": sig['close'], "alert_text": txt}
                alerts_log.insert(0, entry)
                alerts_log = alerts_log[:50]
                last_signal = cur
                last_alert_time = datetime.utcnow().isoformat()
                print(f"NEW ALERT: {txt[:80]}")
        except Exception as e:
            print(f"Alert error: {e}")
        time.sleep(60)

threading.Thread(target=check_and_alert, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def home():
    return open("index.html").read()

@app.get("/widget.js")
def widget():
    return HTMLResponse(open("widget.js").read(), media_type="application/javascript")

@app.get("/embed", response_class=HTMLResponse)
def embed():
    return HTMLResponse(open("embed.html").read())

@app.get("/api/status")
def status():
    return {
        "model": MODEL_ID,
        "standby": True,
        "oanda": {"has_key": bool(OANDA_API_KEY), "account_id": OANDA_ACCOUNT_ID, "env": OANDA_ENVIRONMENT, "last_error": last_oanda_error},
        "alerts": {"last_signal": last_signal, "last_time": last_alert_time, "count": len(alerts_log)},
        "endpoints": ["/api/xauusd/live","/api/xauusd/signal","/api/alerts"]
    }

@app.get("/api/xauusd/live")
def live():
    candles = fetch_xauusd_oanda("M15", 10)
    if not candles:
        return {"status":"error","error": last_oanda_error or "OANDA key missing or fetch failed", "has_key": bool(OANDA_API_KEY)}
    return {"status":"ok","price": candles[-1]['close'], "candle": candles[-1], "last_10": candles[-10:], "source":"OANDA Practice"}

@app.get("/api/xauusd/signal")
def signal():
    candles = fetch_xauusd_oanda("M15", 100)
    if not candles:
        return {"status":"error","error": last_oanda_error or "OANDA key missing", "has_key": bool(OANDA_API_KEY)}
    sig = compute_signal(candles)
    return {"status":"ok","signal": sig, "last_signal": last_signal}

@app.get("/api/alerts")
def alerts():
    return {"status":"ok","alerts": alerts_log, "last_signal": last_signal}

@app.get("/api/alerts/latest")
def latest():
    if not alerts_log:
        return {"status":"ok","message":"No alerts yet - monitoring every 60s"}
    return {"status":"ok","latest": alerts_log[0]}

@app.post("/api/alerts/test")
def test():
    sig = {"close":4284.97,"ema_fast":4280,"ema_slow":4275,"rsi":58,"atr":5.2,"signal":1,"time":datetime.utcnow().isoformat()}
    txt = generate_alert_text(sig)
    entry = {"time": datetime.utcnow().isoformat(), "signal": sig['signal'], "price": sig['close'], "alert_text": txt}
    alerts_log.insert(0, entry)
    return {"status":"ok","alert": entry}

@app.post("/api/chat")
def chat(req: ChatRequest):
    msg = req.message.lower()
    if any(k in msg for k in ["xau","gold","signal","alert"]):
        candles = fetch_xauusd_oanda("M15", 100)
        sig = compute_signal(candles) if candles else None
        if sig:
            return ChatResponse(reply=f"🪙 XAUUSD ${sig['close']:.2f} EMA {sig['ema_fast']:.1f}/{sig['ema_slow']:.1f} RSI {sig['rsi']:.1f} Signal {'LONG' if sig['signal']==1 else 'SHORT' if sig['signal']==-1 else 'HOLD'} | Alerts: {len(alerts_log)}", model="oanda")
        else:
            return ChatResponse(reply=f"OANDA error: {last_oanda_error} | Has key: {bool(OANDA_API_KEY)}", model="debug")
    return ChatResponse(reply=f"Astra standby. Ask 'XAUUSD signal' | Alerts: {len(alerts_log)} Last error: {last_oanda_error}", model="demo")
