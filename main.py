"""
ASTRA6BOT - Real GPT-6 Astra Signal Only (No EMA/RSI lines)
OANDA XAUUSD Live
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

app = FastAPI(title="ASTRA6BOT GPT-6 Signal")

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
last_gpt6_signal = None
last_oanda_error = None
last_live_price = None

class ChatRequest(BaseModel):
    message: str
    history: list = []
    system_prompt: str = "You are GPT-6 Astra XAUUSD expert."

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

def fetch_oanda_candles(granularity="M15", count=100):
    global last_oanda_error, last_live_price
    client = get_oanda_client()
    if not client:
        return None
    try:
        import oandapyV20.endpoints.instruments as instruments
        import oandapyV20.endpoints.pricing as pricing
        params = {"granularity": granularity, "count": count}
        r = instruments.InstrumentsCandles(instrument="XAU_USD", params=params)
        client.request(r)
        rows = []
        for c in r.response['candles']:
            rows.append({
                "time": c['time'],
                "open": float(c['mid']['o']),
                "high": float(c['mid']['h']),
                "low": float(c['mid']['l']),
                "close": float(c['mid']['c']),
                "volume": int(c['volume']),
                "complete": c['complete']
            })
        try:
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
        except:
            pass
        last_oanda_error = None
        return rows
    except Exception as e:
        last_oanda_error = f"Fetch error: {e}"
        return None

def generate_gpt6_signal(candles):
    """Real GPT-6 Astra gives signal only - no EMA/RSI"""
    global last_gpt6_signal
    if not candles or len(candles) < 20:
        return None
    
    # Prepare candle data for GPT-6
    recent = candles[-20:]
    closes = [c['close'] for c in recent]
    highs = [c['high'] for c in recent]
    lows = [c['low'] for c in recent]
    
    # Simple stats for prompt
    price = closes[-1]
    price_1h_ago = closes[-4] if len(closes)>=4 else closes[0]
    price_4h_ago = closes[-16] if len(closes)>=16 else closes[0]
    change_1h = ((price - price_1h_ago)/price_1h_ago*100) if price_1h_ago else 0
    change_4h = ((price - price_4h_ago)/price_4h_ago*100) if price_4h_ago else 0
    high_20 = max(highs)
    low_20 = min(lows)
    
    candle_text = "\n".join([f"{c['time'][11:16]} O:{c['open']:.2f} H:{c['high']:.2f} L:{c['low']:.2f} C:{c['close']:.2f} V:{c['volume']}" for c in recent[-10:]])
    
    prompt = f"""You are GPT-6 Astra, OpenAI's flagship trading analyst for XAUUSD (Gold). Analyze REAL OANDA data and give ONLY signal.

REAL OANDA XAUUSD M15 Data (last 10 candles):
{candle_text}

Current Stats:
- Current Price: ${price:.2f} (Bid/Ask from OANDA Practice live)
- 1H change: {change_1h:.2f}% | 4H change: {change_4h:.2f}%
- 20-candle High: ${high_20:.2f} Low: ${low_20:.2f}
- Time: {recent[-1]['time']} UTC
- Market: Weekend closed, last candle Friday (but analyze anyway)

Task: As GPT-6 Astra, give XAUUSD signal based on price action, support/resistance, trend, momentum from REAL candles above. NO EMA/RSI - use pure price action analysis like GPT-6 would.

Respond in EXACT JSON format (no extra text):
{{
  "signal": 1 or -1 or 0,
  "confidence": 0-100,
  "direction": "LONG" or "SHORT" or "HOLD",
  "reason": "1 sentence reason with price levels",
  "sl": float,
  "tp": float,
  "analysis": "2-3 sentences GPT-6 style analysis"
}}

Signal: 1=LONG BUY, -1=SHORT SELL, 0=HOLD
SL/TP: Calculate based on recent swing high/low, ATR estimate.
Confidence: Your confidence 0-100."""

    # Try OpenAI GPT-6 Astra
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role":"system","content":"You are GPT-6 Astra, expert XAUUSD trader. Respond ONLY with valid JSON, no markdown."},
                    {"role":"user","content":prompt}
                ],
                max_tokens=500,
                temperature=0.3
            )
            import json
            text = resp.choices[0].message.content.strip()
            # Try parse JSON
            # Remove markdown code blocks if any
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            # Ensure required fields
            result = {
                "close": price,
                "signal": int(data.get("signal",0)),
                "confidence": int(data.get("confidence",50)),
                "direction": data.get("direction","HOLD"),
                "reason": data.get("reason","GPT-6 analysis"),
                "sl": float(data.get("sl", price*0.99)),
                "tp": float(data.get("tp", price*1.01)),
                "analysis": data.get("analysis","GPT-6 Astra analysis"),
                "time": recent[-1]['time'],
                "model": MODEL_ID,
                "source": "GPT-6 Astra Real"
            }
            last_gpt6_signal = result
            return result
        except Exception as e:
            print(f"GPT-6 Astra error: {e}")
            # fall through to free models

    # Fallback Gemini (free) - also GPT-6 style
    if GEMINI_API_KEY:
        try:
            import requests, json
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents":[{"role":"user","parts":[{"text":prompt + "\n\nRespond ONLY JSON, no markdown."}]}]}
            r = requests.post(url, json=payload, timeout=20)
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            j = json.loads(text)
            result = {
                "close": price,
                "signal": int(j.get("signal",0)),
                "confidence": int(j.get("confidence",50)),
                "direction": j.get("direction","HOLD"),
                "reason": j.get("reason","Gemini as Astra analysis"),
                "sl": float(j.get("sl", price*0.99)),
                "tp": float(j.get("tp", price*1.01)),
                "analysis": j.get("analysis","Analysis via Gemini free as Astra"),
                "time": recent[-1]['time'],
                "model": "gemini-2.5-flash (as Astra)",
                "source": "Gemini Free as GPT-6 Astra"
            }
            last_gpt6_signal = result
            return result
        except Exception as e:
            print(f"Gemini error: {e}")

    # Fallback Groq free
    if GROQ_API_KEY:
        try:
            from openai import OpenAI
            import json
            client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role":"system","content":"You are GPT-6 Astra. Respond ONLY JSON."},
                    {"role":"user","content":prompt}
                ],
                max_tokens=500,
                temperature=0.3
            )
            text = resp.choices[0].message.content.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            j = json.loads(text)
            result = {
                "close": price,
                "signal": int(j.get("signal",0)),
                "confidence": int(j.get("confidence",50)),
                "direction": j.get("direction","HOLD"),
                "reason": j.get("reason","Groq as Astra"),
                "sl": float(j.get("sl", price*0.99)),
                "tp": float(j.get("tp", price*1.01)),
                "analysis": j.get("analysis","Groq analysis as Astra"),
                "time": recent[-1]['time'],
                "model": "llama-3.3-70b (as Astra)",
                "source": "Groq Free as Astra"
            }
            last_gpt6_signal = result
            return result
        except Exception as e:
            print(f"Groq error: {e}")

    # Ultimate fallback - simple price action without EMA/RSI (still not EMA/RSI, just trend)
    trend = 1 if price > sum(closes[-10:])/10 else -1 if price < sum(closes[-10:])/10 else 0
    # If no AI key, return HOLD with explanation to add key
    result = {
        "close": price,
        "signal": 0,
        "confidence": 0,
        "direction": "HOLD",
        "reason": f"No AI key set - Add GEMINI_API_KEY (free) or OPENAI_API_KEY for real GPT-6 Astra signal. Price ${price:.2f} trend {'up' if trend==1 else 'down' if trend==-1 else 'flat'} last 10 candles.",
        "sl": price*0.995,
        "tp": price*1.005,
        "analysis": f"Demo mode: Need GEMINI_API_KEY (free at aistudio.google.com) or OPENAI_API_KEY for GPT-6 Astra. OANDA price ${price:.2f} from {recent[-1]['time']}. Add key in Render Env vars.",
        "time": recent[-1]['time'],
        "model": "demo - no AI key",
        "source": "Demo - Add GEMINI_API_KEY for real GPT-6 Astra"
    }
    last_gpt6_signal = result
    return result

def check_and_alert():
    global last_signal
    while True:
        try:
            candles = fetch_oanda_candles("M15", 100)
            if not candles:
                time.sleep(60)
                continue
            sig = generate_gpt6_signal(candles)
            if sig and sig['signal']!=0 and sig['signal']!=last_signal:
                txt = f"🚨 ASTRA6BOT GPT-6 ALERT: XAUUSD {sig['direction']} at ${sig['close']:.2f} Conf {sig['confidence']}% - {sig['reason']}"
                alerts_log.insert(0, {"time": datetime.utcnow().isoformat(), "signal": sig['signal'], "price": sig['close'], "alert_text": txt, "gpt6": sig})
                last_signal = sig['signal']
        except Exception as e:
            print(f"Alert error: {e}")
        time.sleep(120)  # GPT-6 check every 2 min to save API calls

threading.Thread(target=check_and_alert, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def home():
    return open("index.html").read()

@app.get("/widget.js")
def widget():
    return HTMLResponse(open("widget.js").read(), media_type="application/javascript")

@app.get("/api/status")
def status():
    return {
        "model": MODEL_ID,
        "standby": True,
        "mode": "GPT-6 Astra Signal Only - No EMA/RSI",
        "oanda": {"has_key": bool(OANDA_API_KEY), "account_id": OANDA_ACCOUNT_ID, "last_error": last_oanda_error, "live_price": last_live_price},
        "gpt6": {"last_signal": last_gpt6_signal, "has_openai_key": bool(OPENAI_API_KEY), "has_gemini_key": bool(GEMINI_API_KEY), "has_groq_key": bool(GROQ_API_KEY)},
        "endpoints": ["/api/xauusd/live","/api/xauusd/history","/api/xauusd/signal-gpt6","/api/alerts"]
    }

@app.get("/api/xauusd/live")
def live():
    candles = fetch_oanda_candles("M15", 20)
    if not candles:
        return {"status":"error","error": last_oanda_error}
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
        "last_10": candles[-10:]
    }

@app.get("/api/xauusd/history")
def history(granularity: str = "M15", count: int = 100, from_time: str = None):
    candles = fetch_oanda_candles(granularity, min(count,5000), from_time)
    if not candles:
        return {"status":"error","error": last_oanda_error}
    closes = [c['close'] for c in candles]
    return {
        "status":"ok",
        "granularity": granularity,
        "count": len(candles),
        "from": candles[0]['time'] if candles else None,
        "to": candles[-1]['time'] if candles else None,
        "latest_price": closes[-1] if closes else None,
        "candles": candles
    }

@app.get("/api/xauusd/signal-gpt6")
def signal_gpt6():
    candles = fetch_oanda_candles("M15", 100)
    if not candles:
        return {"status":"error","error": last_oanda_error}
    sig = generate_gpt6_signal(candles)
    return {"status":"ok","gpt6_signal": sig, "source": "Real GPT-6 Astra - No EMA/RSI"}

# Keep old endpoint for compatibility but now returns GPT-6
@app.get("/api/xauusd/signal")
def signal():
    candles = fetch_oanda_candles("M15", 100)
    if not candles:
        return {"status":"error","error": last_oanda_error}
    sig = generate_gpt6_signal(candles)
    return {"status":"ok","signal": sig, "note": "Now GPT-6 Astra only, no EMA/RSI"}

@app.get("/api/alerts")
def alerts():
    return {"status":"ok","alerts": alerts_log, "last_gpt6": last_gpt6_signal}

@app.post("/api/alerts/test")
def test():
    candles = fetch_oanda_candles("M15", 100)
    sig = generate_gpt6_signal(candles) if candles else {"close":4284.97,"signal":1,"confidence":85,"direction":"LONG","reason":"Test GPT-6 LONG","sl":4270,"tp":4310,"analysis":"Test","time":datetime.utcnow().isoformat(),"model":"test","source":"test"}
    txt = f"🧪 TEST GPT-6 ALERT: XAUUSD {sig['direction']} at ${sig['close']:.2f} - {sig['reason']}"
    entry = {"time": datetime.utcnow().isoformat(), "signal": sig['signal'], "price": sig['close'], "alert_text": txt, "gpt6": sig}
    alerts_log.insert(0, entry)
    return {"status":"ok","alert": entry}

@app.post("/api/chat")
def chat(req: ChatRequest):
    candles = fetch_oanda_candles("M15", 100)
    sig = generate_gpt6_signal(candles) if candles else None
    if sig:
        return ChatResponse(reply=f"🤖 ASTRA6BOT GPT-6 Signal:\n\nDirection: {sig['direction']} ({sig['signal']}) Conf: {sig['confidence']}%\nPrice: ${sig['close']:.2f}\nReason: {sig['reason']}\nSL: ${sig['sl']:.2f} TP: ${sig['tp']:.2f}\nAnalysis: {sig['analysis']}\nModel: {sig['model']}\nTime: {sig['time']}", model=sig['model'])
    return ChatResponse(reply="No OANDA data", model="error")
