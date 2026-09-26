"""
Astra + OANDA XAUUSD Live Chart - Shows forming candle + live price
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

app = FastAPI(title="Astra XAUUSD Live")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OANDA_API_KEY = os.getenv("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_ENVIRONMENT = os.getenv("OANDA_ENVIRONMENT", "practice")

alerts_log = []
last_signal = 0
last_alert_time = None
last_oanda_error = None
last_live_price = None

class ChatRequest(BaseModel):
    message: str
    history: list = []
    system_prompt: str = "You are Astra standby."

class ChatResponse(BaseModel):
    reply: str
    model: str

def get_oanda_client():
    global last_oanda_error
    if not OANDA_API_KEY:
        last_oanda_error = "OANDA_API_KEY missing"
        return None
    try:
        import oandapyV20
        return oandapyV20.API(access_token=OANDA_API_KEY, environment=OANDA_ENVIRONMENT)
    except Exception as e:
        last_oanda_error = f"Client error: {e}"
        return None

def fetch_oanda_candles(granularity="M15", count=100, include_incomplete=True):
    global last_oanda_error, last_live_price
    client = get_oanda_client()
    if not client:
        return None
    try:
        import oandapyV20.endpoints.instruments as instruments
        params = {"granularity": granularity, "count": count, "includeFirst": "false"}
        r = instruments.InstrumentsCandles(instrument="XAU_USD", params=params)
        client.request(r)
        rows = []
        for c in r.response['candles']:
            # Include incomplete for live forming candle
            if not c['complete'] and not include_incomplete:
                continue
            rows.append({
                "time": c['time'],
                "open": float(c['mid']['o']),
                "high": float(c['mid']['h']),
                "low": float(c['mid']['l']),
                "close": float(c['mid']['c']),
                "volume": int(c['volume']),
                "complete": c['complete']
            })
        # Also get live pricing for real-time price
        try:
            import oandapyV20.endpoints.pricing as pricing
            params_price = {"instruments": "XAU_USD"}
            r_price = pricing.PricingInfo(accountID=OANDA_ACCOUNT_ID, params=params_price)
            client.request(r_price)
            prices = r_price.response['prices']
            if prices:
                last_live_price = {
                    "bid": float(prices[0]['bids'][0]['price']),
                    "ask": float(prices[0]['asks'][0]['price']),
                    "mid": (float(prices[0]['bids'][0]['price']) + float(prices[0]['asks'][0]['price']))/2,
                    "time": prices[0]['time']
                }
        except Exception as e:
            print(f"Pricing error: {e}")
        
        last_oanda_error = None
        return rows
    except Exception as e:
        last_oanda_error = f"Fetch error: {e}"
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
    # Use only complete candles for signal, but include incomplete for display
    complete = [c for c in candles if c.get('complete', True)]
    if len(complete) < 60:
        complete = candles
    closes = [c['close'] for c in complete]
    ema_fast = ema(closes, 20)
    ema_slow = ema(closes, 50)
    rsi_vals = rsi(closes, 14)
    atr_vals = atr(complete, 14)
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
        "time": complete[last]['time'],
        "live_price": last_live_price
    }

def check_and_alert():
    global last_signal, last_alert_time, alerts_log
    while True:
        try:
            candles = fetch_oanda_candles("M15", 100, True)
            if not candles:
                time.sleep(60)
                continue
            sig = compute_signal(candles)
            if not sig:
                time.sleep(60)
                continue
            cur = sig['signal']
            if cur !=0 and cur != last_signal:
                txt = f"🚨 ASTRA ALERT: XAUUSD {'LONG' if cur==1 else 'SHORT'} at ${sig['close']:.2f} RSI {sig['rsi']:.1f}"
                entry = {"time": datetime.utcnow().isoformat(), "signal": cur, "price": sig['close'], "alert_text": txt}
                alerts_log.insert(0, entry)
                alerts_log = alerts_log[:50]
                last_signal = cur
                last_alert_time = datetime.utcnow().isoformat()
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
        "oanda": {"has_key": bool(OANDA_API_KEY), "account_id": OANDA_ACCOUNT_ID, "env": OANDA_ENVIRONMENT, "last_error": last_oanda_error, "last_live_price": last_live_price},
        "alerts": {"last_signal": last_signal, "count": len(alerts_log)},
        "market_note": "XAUUSD closed Sat/Sun. Last candle Friday. Live price still updates via OANDA pricing API."
    }

@app.get("/api/xauusd/live")
def live():
    candles = fetch_oanda_candles("M15", 20, True)
    if not candles:
        return {"status":"error","error": last_oanda_error, "has_key": bool(OANDA_API_KEY)}
    # Separate complete vs forming
    complete = [c for c in candles if c.get('complete')]
    forming = [c for c in candles if not c.get('complete')]
    return {
        "status":"ok",
        "price": last_live_price['mid'] if last_live_price else candles[-1]['close'],
        "bid": last_live_price['bid'] if last_live_price else None,
        "ask": last_live_price['ask'] if last_live_price else None,
        "live_price": last_live_price,
        "last_complete": complete[-1] if complete else None,
        "forming_candle": forming[-1] if forming else None,
        "last_10": candles[-10:],
        "market_closed": "Weekend - market closed Sat/Sun, last candle Friday" if datetime.utcnow().weekday()>=5 else "Market open"
    }

@app.get("/api/xauusd/signal")
def signal():
    candles = fetch_oanda_candles("M15", 100, True)
    if not candles:
        return {"status":"error","error": last_oanda_error}
    sig = compute_signal(candles)
    return {"status":"ok","signal": sig, "last_signal": last_signal, "live_price": last_live_price}

@app.get("/api/alerts")
def alerts():
    return {"status":"ok","alerts": alerts_log}

@app.post("/api/alerts/test")
def test():
    sig = {"close": last_live_price['mid'] if last_live_price else 4284.97, "ema_fast":4280,"ema_slow":4275,"rsi":58,"atr":5.2,"signal":1,"time":datetime.utcnow().isoformat()}
    txt = f"🚨 TEST ALERT: XAUUSD LONG at ${sig['close']:.2f}"
    entry = {"time": datetime.utcnow().isoformat(), "signal": 1, "price": sig['close'], "alert_text": txt}
    alerts_log.insert(0, entry)
    return {"status":"ok","alert": entry}

@app.post("/api/chat")
def chat(req: ChatRequest):
    return ChatResponse(reply=f"Live XAUUSD ${last_live_price['mid']:.2f} if live else 4284.97 | {last_oanda_error or 'OANDA OK'}", model="oanda")
