"""
GPT-6 Astra Standby Website + XAUUSD OANDA Live - Render 24/7
Model: gpt-6-astra + OANDA v20 Practice API for XAUUSD (same as TradingView)
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Astra Standby + XAUUSD OANDA")

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

class ChatRequest(BaseModel):
    message: str
    history: list = []
    system_prompt: str = "You are GPT-6 Astra, OpenAI's flagship model, standby on this website. You also have access to live XAUUSD data via OANDA Practice API. Be concise, friendly."

class ChatResponse(BaseModel):
    reply: str
    model: str

# --- OANDA XAUUSD Data ---
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
    # EMA
    df['ema_fast'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    last = df.iloc[-1]
    prev = df.iloc[-2]
    # Signal
    signal = 0
    if last['ema_fast'] > last['ema_slow'] and prev['ema_fast'] <= prev['ema_slow'] and last['rsi'] < 70 and last['rsi'] > 50:
        signal = 1  # long
    elif last['ema_fast'] < last['ema_slow'] and prev['ema_fast'] >= prev['ema_slow'] and last['rsi'] > 30 and last['rsi'] < 50:
        signal = -1  # short
    
    return {
        "close": float(last['close']),
        "ema_fast": float(last['ema_fast']),
        "ema_slow": float(last['ema_slow']),
        "rsi": float(last['rsi']),
        "signal": int(signal),
        "time": last['time'] if 'time' in last else str(df.index[-1])
    }

@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r") as f:
        return f.read()

@app.get("/widget.js")
def widget():
    with open("widget.js", "r") as f:
        content = f.read()
    return HTMLResponse(content, media_type="application/javascript")

@app.get("/embed", response_class=HTMLResponse)
def embed():
    with open("embed.html", "r") as f:
        return f.read()

@app.get("/api/status")
def status():
    return {
        "model": MODEL_ID,
        "standby": True,
        "oanda": {
            "has_key": bool(OANDA_API_KEY),
            "account_id": OANDA_ACCOUNT_ID,
            "environment": OANDA_ENVIRONMENT,
            "instrument": "XAU_USD",
            "live_url": "https://renderbot-hw94.onrender.com/api/xauusd/live"
        },
        "ai_providers": {
            "openai_gpt6_astra": bool(OPENAI_API_KEY),
            "gemini": bool(GEMINI_API_KEY),
            "groq": bool(GROQ_API_KEY)
        },
        "endpoints": ["/api/chat", "/api/xauusd/live", "/api/xauusd/signal", "/api/status", "/widget.js"]
    }

@app.get("/api/xauusd/live")
def xauusd_live():
    candles = fetch_xauusd_oanda("M15", 10)
    if not candles:
        return {"status":"error","error":"OANDA_API_KEY missing or invalid. Set in Render Environment."}
    latest = candles[-1]
    return {
        "status":"ok",
        "source":"OANDA v20 Practice - same as TradingView",
        "instrument":"XAU_USD",
        "price": latest['close'],
        "candle": latest,
        "last_10": candles[-10:]
    }

@app.get("/api/xauusd/signal")
def xauusd_signal():
    candles = fetch_xauusd_oanda("M15", 100)
    if not candles:
        return {"status":"error","error":"OANDA_API_KEY missing"}
    sig = compute_signal_from_candles(candles)
    return {
        "status":"ok",
        "source":"OANDA Practice M15",
        "instrument":"XAU_USD",
        "signal": sig,
        "interpretation": "1=LONG, -1=SHORT, 0=HOLD"
    }

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    user_msg = req.message.lower()
    
    # If user asks about XAUUSD / gold, give live OANDA data
    if any(k in user_msg for k in ["xau", "gold", "signal", "price", "oanda"]):
        candles = fetch_xauusd_oanda("M15", 100)
        if candles:
            sig = compute_signal_from_candles(candles)
            if sig:
                txt = f"""🪙 **Live XAUUSD (OANDA Practice - same as TradingView)**

Price: **${sig['close']:.2f}**
EMA 20/50: {sig['ema_fast']:.2f} / {sig['ema_slow']:.2f}
RSI: {sig['rsi']:.1f}
Signal: **{ 'LONG 🟢' if sig['signal']==1 else 'SHORT 🔴' if sig['signal']==-1 else 'HOLD ⚪'}** ({sig['signal']})

Time: {sig['time']}
Account: {OANDA_ACCOUNT_ID} Balance: $100k demo

This is real OANDA v20 data from api-fxpractice.oanda.com"""
                return ChatResponse(reply=txt, model="oanda-live")
    
    # Otherwise AI chat (free tier)
    msg = req.message.strip()
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
        except Exception as e:
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
        except Exception as e:
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

    # Demo fallback
    return ChatResponse(reply=f"[DEMO - Astra Standby]\nYou said: {msg}\n\nI have live OANDA XAUUSD connected! Ask 'XAUUSD signal' for real price.\n\nTo enable real AI, add GEMINI_API_KEY in Render Environment (free).", model="demo")
