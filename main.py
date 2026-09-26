"""
GPT-6 Astra Standby + OANDA XAUUSD Live Chart + Astra Alert Signals
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
from dotenv import load_dotenv
from datetime import datetime
import threading
import time

load_dotenv()

app = FastAPI(title="Astra Standby + XAUUSD OANDA + Alerts")

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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Alert State ---
alerts_log = []
last_signal = 0
last_alert_time = None

class ChatRequest(BaseModel):
    message: str
    history: list = []
    system_prompt: str = "You are GPT-6 Astra, flagship model, standby on XAUUSD trading site. You have live OANDA data. Be concise."

class ChatResponse(BaseModel):
    reply: str
    model: str

def get_oanda_client():
    if not OANDA_API_KEY:
        return None
    try:
        import oandapyV20
        return oandapyV20.API(access_token=OANDA_API_KEY, environment=OANDA_ENVIRONMENT)
    except:
        return None

def fetch_xauusd_oanda(granularity="M15", count=100):
    client = get_oanda_client()
    if not client:
        return None
    try:
        import oandapyV20.endpoints.instruments as instruments
        params = {"granularity": granularity, "count": count}
        r = instruments.InstrumentsCandles(instrument="XAU_USD", params=params)
        client.request(r)
        candles = r.response['candles']
        rows = []
        for c in candles:
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
        return rows
    except Exception as e:
        print(f"OANDA fetch error: {e}")
        return None

def compute_signal_from_candles(candles):
    if not candles or len(candles) < 50:
        return None
    import pandas as pd
    df = pd.DataFrame(candles)
    df['close'] = df['close'].astype(float)
    df['ema_fast'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift()).abs()
    tr3 = (df['low'] - df['close'].shift()).abs()
    import numpy as np
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    last = df.iloc[-1]
    prev = df.iloc[-2]
    signal = 0
    if last['ema_fast'] > last['ema_slow'] and prev['ema_fast'] <= prev['ema_slow'] and last['rsi'] < 70 and last['rsi'] > 50:
        signal = 1
    elif last['ema_fast'] < last['ema_slow'] and prev['ema_fast'] >= prev['ema_slow'] and last['rsi'] > 30 and last['rsi'] < 50:
        signal = -1
    return {
        "close": float(last['close']),
        "ema_fast": float(last['ema_fast']),
        "ema_slow": float(last['ema_slow']),
        "rsi": float(last['rsi']),
        "atr": float(last['atr']),
        "signal": int(signal),
        "time": last['time'] if 'time' in last else str(df.index[-1])
    }

def generate_astra_alert(signal_data):
    """Use GPT-6 Astra (or free fallback) to generate alert explanation"""
    price = signal_data['close']
    ema_f = signal_data['ema_fast']
    ema_s = signal_data['ema_slow']
    rsi = signal_data['rsi']
    atr = signal_data['atr']
    sig = signal_data['signal']
    
    direction = "LONG 🟢 BUY" if sig==1 else "SHORT 🔴 SELL"
    sl = price - atr*1.5 if sig==1 else price + atr*1.5
    tp = price + atr*3.0 if sig==1 else price - atr*3.0
    
    prompt = f"""You are GPT-6 Astra, expert XAUUSD analyst. Generate a concise trading alert.

Data:
- XAUUSD Price: ${price:.2f}
- Signal: {direction} (EMA 20 {ema_f:.2f} crossed {'above' if sig==1 else 'below'} EMA 50 {ema_s:.2f})
- RSI: {rsi:.1f}
- ATR: {atr:.2f}
- SL: ${sl:.2f} (1.5x ATR), TP: ${tp:.2f} (3x ATR)
- Time: {signal_data['time']}
- Account: {OANDA_ACCOUNT_ID} (Practice $100k)

Generate alert in this format:
🚨 ASTRA ALERT: XAUUSD {direction}
Price: $...
Reason: EMA crossover + RSI...
Risk: SL $... TP $... (1:2 RR)
Action: ...

Keep under 100 words, include risk disclaimer."""

    # Try OpenAI GPT-6 Astra first
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=MODEL_ID,
                messages=[{"role":"system","content":"You are GPT-6 Astra, XAUUSD expert. Generate concise trading alerts."},
                          {"role":"user","content":prompt}],
                max_tokens=300
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"OpenAI alert error: {e}")
    
    # Fallback Gemini free
    if GEMINI_API_KEY:
        try:
            import requests
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents":[{"role":"user","parts":[{"text":prompt}]}]}
            r = requests.post(url, json=payload, timeout=15)
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"Gemini alert error: {e}")
    
    # Fallback template
    return f"""🚨 ASTRA ALERT: XAUUSD {direction}

Price: ${price:.2f}
Reason: EMA 20 ({ema_f:.2f}) crossed {'above' if sig==1 else 'below'} EMA 50 ({ema_s:.2f}) + RSI {rsi:.1f} {'bullish' if sig==1 else 'bearish'} momentum
Risk: SL ${sl:.2f} (1.5x ATR) | TP ${tp:.2f} (3x ATR) | RR 1:2
ATR: {atr:.2f} | Time: {signal_data['time'][:16]}

⚠️ Demo - Practice account {OANDA_ACCOUNT_ID}. Not financial advice. Manage risk: 1% per trade."""

def send_telegram_alert(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode":"Markdown"}, timeout=10)
        return True
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def check_and_alert():
    global last_signal, last_alert_time, alerts_log
    while True:
        try:
            candles = fetch_xauusd_oanda("M15", 100)
            if not candles:
                time.sleep(60)
                continue
            sig = compute_signal_from_candles(candles)
            if not sig:
                time.sleep(60)
                continue
            
            current_sig = sig['signal']
            # Alert only on new LONG/SHORT signal (not HOLD) and different from last
            if current_sig != 0 and current_sig != last_signal:
                print(f"NEW SIGNAL DETECTED: {current_sig} at {sig['close']}")
                alert_text = generate_astra_alert(sig)
                alert_entry = {
                    "time": datetime.utcnow().isoformat(),
                    "signal": current_sig,
                    "price": sig['close'],
                    "rsi": sig['rsi'],
                    "ema_fast": sig['ema_fast'],
                    "ema_slow": sig['ema_slow'],
                    "alert_text": alert_text
                }
                alerts_log.insert(0, alert_entry)
                alerts_log = alerts_log[:50]  # keep last 50
                last_signal = current_sig
                last_alert_time = datetime.utcnow().isoformat()
                
                # Try Telegram
                send_telegram_alert(alert_text)
                
                print(f"ALERT GENERATED: {alert_text[:100]}...")
            
            # Update last_signal even if HOLD, to track
            if current_sig == 0:
                # Don't reset last_signal on HOLD, keep last LONG/SHORT to avoid repeat alerts
                pass
            
        except Exception as e:
            print(f"Alert loop error: {e}")
        time.sleep(60)  # check every 60s

# Start alert thread
alert_thread = threading.Thread(target=check_and_alert, daemon=True)
alert_thread.start()

@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r") as f:
        return f.read()

@app.get("/widget.js")
def widget():
    with open("widget.js", "r") as f:
        return f.read()

@app.get("/embed", response_class=HTMLResponse)
def embed():
    with open("embed.html", "r") as f:
        return f.read()

@app.get("/api/status")
def status():
    return {
        "model": MODEL_ID,
        "standby": True,
        "oanda": {"has_key": bool(OANDA_API_KEY), "account_id": OANDA_ACCOUNT_ID, "environment": OANDA_ENVIRONMENT},
        "alerts": {"last_signal": last_signal, "last_alert_time": last_alert_time, "total_alerts": len(alerts_log), "telegram_enabled": bool(TELEGRAM_BOT_TOKEN)},
        "endpoints": ["/api/chat", "/api/xauusd/live", "/api/xauusd/signal", "/api/alerts", "/api/alerts/latest"]
    }

@app.get("/api/xauusd/live")
def xauusd_live():
    candles = fetch_xauusd_oanda("M15", 10)
    if not candles:
        return {"status":"error","error":"OANDA_API_KEY missing"}
    return {"status":"ok","source":"OANDA v20 Practice","instrument":"XAU_USD","price": candles[-1]['close'], "candle": candles[-1], "last_10": candles[-10:]}

@app.get("/api/xauusd/signal")
def xauusd_signal():
    candles = fetch_xauusd_oanda("M15", 100)
    if not candles:
        return {"status":"error","error":"OANDA_API_KEY missing"}
    sig = compute_signal_from_candles(candles)
    return {"status":"ok","source":"OANDA Practice M15","instrument":"XAU_USD","signal": sig, "last_alert_signal": last_signal}

@app.get("/api/alerts")
def get_alerts():
    return {"status":"ok","alerts": alerts_log, "last_signal": last_signal, "last_alert_time": last_alert_time}

@app.get("/api/alerts/latest")
def latest_alert():
    if not alerts_log:
        return {"status":"ok","message":"No alerts yet - waiting for LONG/SHORT signal. Current monitoring every 60s."}
    return {"status":"ok","latest": alerts_log[0]}

@app.post("/api/alerts/test")
def test_alert():
    """Force generate test alert"""
    candles = fetch_xauusd_oanda("M15", 100)
    if not candles:
        return {"status":"error","error":"OANDA_API_KEY missing"}
    sig = compute_signal_from_candles(candles)
    if not sig:
        return {"status":"error","error":"No signal data"}
    # Force signal to LONG for test if currently HOLD
    if sig['signal']==0:
        sig['signal']=1
    alert_text = generate_astra_alert(sig)
    entry = {"time": datetime.utcnow().isoformat(), "signal": sig['signal'], "price": sig['close'], "alert_text": alert_text}
    alerts_log.insert(0, entry)
    send_telegram_alert(f"🧪 TEST ALERT\n{alert_text}")
    return {"status":"ok","alert": entry}

@app.post("/api/chat")
def chat(req: ChatRequest):
    user_msg = req.message.lower()
    if any(k in user_msg for k in ["xau", "gold", "signal", "alert", "oanda"]):
        candles = fetch_xauusd_oanda("M15", 100)
        if candles:
            sig = compute_signal_from_candles(candles)
            if sig:
                alert_preview = ""
                if alerts_log:
                    alert_preview = f"\n\nLast Astra Alert:\n{alerts_log[0]['alert_text'][:300]}"
                txt = f"""🪙 Live XAUUSD (OANDA Practice)

Price: ${sig['close']:.2f}
EMA 20/50: {sig['ema_fast']:.2f}/{sig['ema_slow']:.2f} RSI: {sig['rsi']:.1f}
Current Signal: {'LONG 🟢' if sig['signal']==1 else 'SHORT 🔴' if sig['signal']==-1 else 'HOLD ⚪'}

Astra Alert System: Monitoring every 60s. Last alert signal: {last_signal} at {last_alert_time}
Total alerts: {len(alerts_log)}
{alert_preview}

Ask 'test alert' to force a test alert, or set TELEGRAM_BOT_TOKEN for Telegram alerts."""
                return ChatResponse(reply=txt, model="oanda-astra-alert")

    msg = req.message.strip()
    if msg.lower() in ["test alert", "alert test"]:
        candles = fetch_xauusd_oanda("M15", 100)
        sig = compute_signal_from_candles(candles) if candles else None
        if sig:
            if sig['signal']==0:
                sig['signal']=1
            alert_text = generate_astra_alert(sig)
            return ChatResponse(reply=f"🧪 Test Alert Generated:\n\n{alert_text}", model="astra-alert-test")

    # AI fallback
    if GEMINI_API_KEY:
        try:
            import requests
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            contents = []
            for h in req.history[-10:]:
                role = "user" if h.get("role")=="user" else "model"
                contents.append({"role": role, "parts":[{"text": h.get("content","")}]})
            contents.append({"role":"user","parts":[{"text": msg}]})
            r = requests.post(url, json={"contents": contents}, timeout=20)
            data = r.json()
            reply = data["candidates"][0]["content"]["parts"][0]["text"]
            return ChatResponse(reply=reply, model="gemini-2.5-flash")
        except:
            pass

    if GROQ_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            messages = [{"role":"system","content":req.system_prompt}]
            for h in req.history[-10:]:
                messages.append(h)
            messages.append({"role":"user","content":msg})
            resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, max_tokens=1000)
            return ChatResponse(reply=resp.choices[0].message.content, model="llama-3.3-70b")
        except:
            pass

    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            messages = [{"role":"system","content":req.system_prompt}]
            for h in req.history[-10:]:
                messages.append(h)
            messages.append({"role":"user","content":msg})
            resp = client.chat.completions.create(model=MODEL_ID, messages=messages, max_tokens=1500)
            return ChatResponse(reply=resp.choices[0].message.content, model=MODEL_ID)
        except Exception as e:
            return ChatResponse(reply=f"Astra error: {e}", model=MODEL_ID)

    return ChatResponse(reply=f"[DEMO - Astra Alert System Active]\nMonitoring XAUUSD every 60s. Last signal: {last_signal}\nAsk 'XAUUSD signal' or 'test alert'.\nAdd GEMINI_API_KEY for real AI alerts.", model="demo")
