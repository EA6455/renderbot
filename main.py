"""
ASTRA6BOT - Pure OANDA XAUUSD Live Terminal - No GPT-6
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="ASTRA6BOT OANDA Live")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OANDA_API_KEY = os.getenv("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_ENVIRONMENT = os.getenv("OANDA_ENVIRONMENT", "practice")

def get_oanda_client():
    if not OANDA_API_KEY:
        return None
    try:
        import oandapyV20
        return oandapyV20.API(access_token=OANDA_API_KEY, environment=OANDA_ENVIRONMENT)
    except:
        return None

def fetch_candles(granularity="M15", count=100):
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
        # live price
        live_price = None
        try:
            params_price = {"instruments": "XAU_USD"}
            r_price = pricing.PricingInfo(accountID=OANDA_ACCOUNT_ID, params=params_price)
            client.request(r_price)
            p = r_price.response['prices'][0]
            live_price = {
                "bid": float(p['bids'][0]['price']),
                "ask": float(p['asks'][0]['price']),
                "mid": (float(p['bids'][0]['price']) + float(p['asks'][0]['price']))/2,
                "time": p['time']
            }
        except:
            pass
        return rows, live_price
    except Exception as e:
        print(f"OANDA error: {e}")
        return None, None

@app.get("/", response_class=HTMLResponse)
def home():
    return open("index.html").read()

@app.get("/widget.js")
def widget():
    try:
        return HTMLResponse(open("widget.js").read(), media_type="application/javascript")
    except:
        return HTMLResponse("// widget removed - ASTRA6BOT pure OANDA", media_type="application/javascript")

@app.get("/api/status")
def status():
    return {
        "name": "ASTRA6BOT",
        "oanda": {"has_key": bool(OANDA_API_KEY), "account_id": OANDA_ACCOUNT_ID, "env": OANDA_ENVIRONMENT},
        "mode": "Pure OANDA XAUUSD Live - No GPT-6",
        "endpoints": ["/api/xauusd/live","/api/xauusd/history"]
    }

@app.get("/api/xauusd/live")
def live():
    result = fetch_candles("M15", 20)
    if not result:
        return {"status":"error","error":"OANDA key missing"}
    candles, live_price = result
    if not candles:
        return {"status":"error","error":"No candles"}
    complete = [c for c in candles if c.get('complete')]
    forming = [c for c in candles if not c.get('complete')]
    return {
        "status":"ok",
        "price": live_price['mid'] if live_price else candles[-1]['close'],
        "bid": live_price['bid'] if live_price else None,
        "ask": live_price['ask'] if live_price else None,
        "live_price": live_price,
        "last_complete": complete[-1] if complete else None,
        "forming_candle": forming[-1] if forming else None,
        "last_10": candles[-10:],
        "source": "OANDA v20 Practice - Pure, No GPT-6"
    }

@app.get("/api/xauusd/history")
def history(granularity: str = "M15", count: int = 100, from_time: str = None):
    result = fetch_candles(granularity, min(count,5000))
    if not result:
        return {"status":"error","error":"OANDA key missing"}
    candles, _ = result
    if not candles:
        return {"status":"error","error":"No candles"}
    closes = [c['close'] for c in candles]
    return {
        "status":"ok",
        "granularity": granularity,
        "count": len(candles),
        "from": candles[0]['time'],
        "to": candles[-1]['time'],
        "latest_price": closes[-1],
        "candles": candles,
        "source": "OANDA v20 - History back to 2005 - Pure OANDA, No GPT-6"
    }
