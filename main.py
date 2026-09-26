"""
ASTRA6 - Dashboard Signal Alerts + Ladder + OANDA
"""
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import os, json, hashlib, secrets, time, math
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

app = FastAPI(title="ASTRA6")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OANDA_API_KEY = os.getenv("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_ENVIRONMENT = os.getenv("OANDA_ENVIRONMENT", "practice")

USERS_FILE = Path("users.json")
TOKENS_FILE = Path("tokens.json")
CONTACTS_FILE = Path("contacts.json")
SIGNALS_FILE = Path("signals.json")

def load_json_file(p, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except:
        return default

def save_json_file(p, data):
    p.write_text(json.dumps(data, indent=2))

def load_users(): return load_json_file(USERS_FILE, {})
def save_users(u): save_json_file(USERS_FILE, u)
def load_tokens(): return load_json_file(TOKENS_FILE, {})
def save_tokens(t): save_json_file(TOKENS_FILE, t)
def load_contacts(): return load_json_file(CONTACTS_FILE, [])
def save_contacts(c): save_json_file(CONTACTS_FILE, c)
def load_signals(): return load_json_file(SIGNALS_FILE, [])
def save_signals(s): save_json_file(SIGNALS_FILE, s[-200:])  # keep last 200

def hash_password(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 100000).hex()

def create_user(email, password):
    users = load_users()
    email = email.lower().strip()
    if email in users:
        return None, "Email already registered"
    if len(password) < 6:
        return None, "Password must be at least 6 characters"
    salt = secrets.token_hex(16)
    users[email] = {"email": email, "salt": salt, "hash": hash_password(password, salt), "created": time.time()}
    save_users(users)
    return users[email], None

def verify_user(email, password):
    users = load_users()
    u = users.get(email.lower().strip())
    if not u: return None
    if hash_password(password, u["salt"]) == u["hash"]:
        return u
    return None

def create_token(email):
    tokens = load_tokens()
    token = secrets.token_urlsafe(32)
    tokens[token] = {"email": email, "created": time.time(), "expires": time.time() + 30*24*3600}
    save_tokens(tokens)
    return token, tokens[token]

def verify_token(token):
    if not token: return None
    tokens = load_tokens()
    data = tokens.get(token)
    if not data: return None
    if data["expires"] < time.time():
        del tokens[token]
        save_tokens(tokens)
        return None
    return data

def get_token_data(authorization: str = Header(None)):
    if not authorization: return None
    return verify_token(authorization.replace("Bearer ", "").strip())

def get_current_user(authorization: str = Header(None)):
    d = get_token_data(authorization)
    return d["email"] if d else None

def require_auth(authorization: str = Header(None)):
    email = get_current_user(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in required")
    return email

class AuthRequest(BaseModel):
    email: str
    password: str

class ContactRequest(BaseModel):
    email: str
    subject: str = ""
    message: str

# OANDA
def get_oanda_client():
    if not OANDA_API_KEY: return None
    try:
        import oandapyV20
        return oandapyV20.API(access_token=OANDA_API_KEY, environment=OANDA_ENVIRONMENT)
    except:
        return None

def fetch_candles(granularity="M15", count=100):
    client = get_oanda_client()
    if not client: return None
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

# Signal Logic
def sma(values, period):
    if len(values) < period: return sum(values)/len(values) if values else 0
    return sum(values[-period:])/period

def rsi(values, period=14):
    if len(values) < period+1: return 50
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i-1]
        if diff > 0: gains.append(diff); losses.append(0)
        else: gains.append(0); losses.append(abs(diff))
    if len(gains) < period: return 50
    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period
    if avg_loss == 0: return 100
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

def generate_signal(candles, live_price=None):
    if not candles or len(candles) < 20:
        return None
    closes = [c['close'] for c in candles if c['complete']]
    if len(closes) < 20:
        closes = [c['close'] for c in candles]
    if len(closes) < 5:
        return None
    s20 = sma(closes, 20)
    s50 = sma(closes, 50) if len(closes) >= 20 else s20
    r = rsi(closes, 14)
    last = closes[-1]
    prev = closes[-2] if len(closes) >=2 else last
    change_pct = ((last - prev)/prev*100) if prev else 0
    vol_avg = sum(c['volume'] for c in candles[-10:])/10 if len(candles)>=10 else candles[-1]['volume']
    vol_last = candles[-1]['volume']
    vol_ratio = vol_last / vol_avg if vol_avg else 1

    # Determine signal
    signal_type = "HOLD"
    confidence = 55
    reasons = []

    if s20 > s50:
        reasons.append(f"SMA20 {s20:.1f} > SMA50 {s50:.1f} uptrend")
        if last > prev:
            reasons.append(f"Price up {change_pct:+.2f}%")
        if r < 70 and r > 45:
            reasons.append(f"RSI {r:.0f} bullish zone")
            if vol_ratio > 1.1:
                signal_type = "BUY"
                confidence = 75 + min(15, (r-45)/2 + (vol_ratio-1)*10)
                reasons.append(f"Vol {vol_ratio:.1f}x high")
            else:
                signal_type = "BUY"
                confidence = 65
        elif r >= 70:
            signal_type = "HOLD"
            confidence = 60
            reasons.append(f"RSI {r:.0f} overbought")
        else:
            signal_type = "HOLD"
            confidence = 50
    elif s20 < s50:
        reasons.append(f"SMA20 {s20:.1f} < SMA50 {s50:.1f} downtrend")
        if last < prev:
            reasons.append(f"Price down {change_pct:+.2f}%")
        if r > 30 and r < 55:
            reasons.append(f"RSI {r:.0f} bearish zone")
            if vol_ratio > 1.1:
                signal_type = "SELL"
                confidence = 75 + min(15, (55-r)/2 + (vol_ratio-1)*10)
                reasons.append(f"Vol {vol_ratio:.1f}x high")
            else:
                signal_type = "SELL"
                confidence = 65
        elif r <= 30:
            signal_type = "HOLD"
            confidence = 60
            reasons.append(f"RSI {r:.0f} oversold")
        else:
            signal_type = "HOLD"
            confidence = 50
    else:
        reasons.append("Sideways, no clear trend")
        signal_type = "HOLD"
        confidence = 50

    confidence = max(45, min(92, int(confidence)))

    # Only alert if significant - check last signal
    signals = load_signals()
    last_sig = signals[-1] if signals else None
    should_alert = True
    if last_sig:
        # If same type and price change <0.3% and <5 min since last, don't alert
        time_diff = time.time() - last_sig.get('timestamp', 0)
        price_diff_pct = abs(last - last_sig.get('price', last))/last*100 if last else 0
        if last_sig['type'] == signal_type and price_diff_pct < 0.25 and time_diff < 300:
            should_alert = False
        # If HOLD and last was HOLD and <10 min, don't alert
        if signal_type == "HOLD" and last_sig['type'] == "HOLD" and time_diff < 600:
            should_alert = False

    sig = {
        "id": secrets.token_hex(6),
        "timestamp": time.time(),
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "price": live_price['mid'] if live_price else last,
        "bid": live_price['bid'] if live_price else None,
        "ask": live_price['ask'] if live_price else None,
        "type": signal_type,
        "confidence": confidence,
        "rsi": round(r,1),
        "sma20": round(s20,2),
        "sma50": round(s50,2),
        "change_pct": round(change_pct,3),
        "volume_ratio": round(vol_ratio,2),
        "reasons": reasons,
        "should_alert": should_alert
    }

    # Save only if should_alert or first time or type change
    if should_alert or not last_sig or last_sig['type'] != signal_type:
        signals.append(sig)
        save_signals(signals)

    return sig

# Routes
@app.get("/", response_class=HTMLResponse)
def home():
    return open("index.html").read()

@app.get("/telegram-qr.jpg")
def telegram_qr():
    p = Path("telegram-qr.jpg")
    if p.exists():
        return FileResponse(p, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="QR not found")

@app.get("/t_me-astra6render.jpg")
def telegram_qr_alias():
    p = Path("telegram-qr.jpg")
    if p.exists():
        return FileResponse(p, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="QR not found")

@app.get("/widget.js")
def widget():
    try:
        return HTMLResponse(open("widget.js").read(), media_type="application/javascript")
    except:
        return HTMLResponse("// ASTRA6", media_type="application/javascript")

@app.get("/api/status")
def status():
    users = load_users()
    contacts = load_contacts()
    signals = load_signals()
    return {
        "name": "ASTRA6",
        "oanda": {"has_key": bool(OANDA_API_KEY), "account_id": OANDA_ACCOUNT_ID, "env": OANDA_ENVIRONMENT},
        "mode": "ASTRA6 Dashboard",
        "users": len(users),
        "contacts": len(contacts),
        "signals": len(signals),
        "ladder": ["Dashboard","Live Signals","Sign In","Sign Up","Account","Admin Contact"],
        "endpoints": ["/api/xauusd/live","/api/xauusd/history","/api/signals/current","/api/signals/history","/api/auth/signup","/api/auth/signin","/api/auth/me","/api/contact"]
    }

# AUTH
@app.post("/api/auth/signup")
def signup(req: AuthRequest):
    user, err = create_user(req.email, req.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    token, tdata = create_token(user["email"])
    return {"status":"ok","email": user["email"], "token": token, "message":"Account created", "created": user["created"], "expires": tdata["expires"]}

@app.post("/api/auth/signin")
def signin(req: AuthRequest):
    user = verify_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token, tdata = create_token(user["email"])
    return {"status":"ok","email": user["email"], "token": token, "message":"Signed in", "created": user["created"], "expires": tdata["expires"]}

@app.get("/api/auth/me")
def me(authorization: str = Header(None)):
    data = get_token_data(authorization)
    if not data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    users = load_users()
    user = users.get(data["email"], {})
    return {"status":"ok","email": data["email"], "created": user.get("created"), "expires": data.get("expires"), "token_created": data.get("created")}

@app.post("/api/auth/signout")
def signout(authorization: str = Header(None)):
    if not authorization:
        return {"status":"ok"}
    token = authorization.replace("Bearer ", "").strip()
    tokens = load_tokens()
    if token in tokens:
        del tokens[token]
        save_tokens(tokens)
    return {"status":"ok","message":"Signed out"}

@app.post("/api/contact")
def contact(req: ContactRequest):
    if not req.email or not req.message:
        raise HTTPException(status_code=400, detail="Email and message required")
    if len(req.message) < 5:
        raise HTTPException(status_code=400, detail="Message too short")
    contacts = load_contacts()
    entry = {"id": secrets.token_hex(8), "email": req.email.lower().strip(), "subject": req.subject[:200], "message": req.message[:2000], "time": time.time(), "time_str": time.strftime("%Y-%m-%d %H:%M:%S")}
    contacts.append(entry)
    save_contacts(contacts)
    return {"status":"ok","message":"Message sent to admin","id": entry["id"]}

@app.get("/api/contact")
def list_contacts(authorization: str = Header(None)):
    email = get_current_user(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in required")
    contacts = load_contacts()
    return {"status":"ok","count": len(contacts), "contacts": contacts[-20:]}

# SIGNALS DASHBOARD
@app.get("/api/signals/current")
def signals_current(email: str = Depends(require_auth)):
    result = fetch_candles("M15", 100)
    if not result:
        raise HTTPException(status_code=500, detail="OANDA error")
    candles, live_price = result
    sig = generate_signal(candles, live_price)
    if not sig:
        raise HTTPException(status_code=500, detail="Signal generation failed")
    return {"status":"ok","signal": sig, "user": email}

@app.get("/api/signals/history")
def signals_history(limit: int = 20, email: str = Depends(require_auth)):
    signals = load_signals()
    # Return last N, newest first
    return {"status":"ok","count": len(signals), "signals": list(reversed(signals[-limit:])), "user": email}

@app.get("/api/signals/alerts")
def signals_alerts(limit: int = 10, email: str = Depends(require_auth)):
    signals = load_signals()
    # Only alerts where should_alert true and not HOLD, or last 10 with type change
    alerts = [s for s in signals if s.get('should_alert') and s['type'] != 'HOLD']
    if not alerts:
        alerts = [s for s in signals if s['type'] != 'HOLD'][-limit:]
    return {"status":"ok","count": len(alerts), "alerts": list(reversed(alerts[-limit:])), "user": email}

# PROTECTED DATA
@app.get("/api/xauusd/live")
def live(email: str = Depends(require_auth)):
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
        "user": email
    }

@app.get("/api/xauusd/history")
def history(granularity: str = "M15", count: int = 100, email: str = Depends(require_auth)):
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
        "user": email
    }
