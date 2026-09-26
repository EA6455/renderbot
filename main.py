"""
ASTRA6 - Auth + OANDA Live
"""
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os, json, hashlib, secrets, time
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

def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text())
    except:
        return {}

def save_users(users):
    USERS_FILE.write_text(json.dumps(users, indent=2))

def load_tokens():
    if not TOKENS_FILE.exists():
        return {}
    try:
        return json.loads(TOKENS_FILE.read_text())
    except:
        return {}

def save_tokens(tokens):
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))

def hash_password(password, salt):
    # pbkdf2_hmac sha256 100k iterations
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()

def create_user(email, password):
    users = load_users()
    email = email.lower().strip()
    if email in users:
        return None, "Email already registered"
    if len(password) < 6:
        return None, "Password must be at least 6 characters"
    salt = secrets.token_hex(16)
    pwd_hash = hash_password(password, salt)
    users[email] = {"email": email, "salt": salt, "hash": pwd_hash, "created": time.time()}
    save_users(users)
    return users[email], None

def verify_user(email, password):
    users = load_users()
    email = email.lower().strip()
    u = users.get(email)
    if not u:
        return None
    if hash_password(password, u["salt"]) == u["hash"]:
        return u
    return None

def create_token(email):
    tokens = load_tokens()
    token = secrets.token_urlsafe(32)
    tokens[token] = {"email": email, "created": time.time(), "expires": time.time() + 30*24*3600}
    save_tokens(tokens)
    return token

def verify_token(token):
    if not token:
        return None
    tokens = load_tokens()
    # support Bearer prefix stripping outside
    data = tokens.get(token)
    if not data:
        return None
    if data["expires"] < time.time():
        # expired, remove
        del tokens[token]
        save_tokens(tokens)
        return None
    return data["email"]

def get_current_user(authorization: str = Header(None)):
    if not authorization:
        return None
    # Expected "Bearer <token>"
    token = authorization.replace("Bearer ", "").strip()
    email = verify_token(token)
    return email

def require_auth(authorization: str = Header(None)):
    email = get_current_user(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in required to access signals")
    return email

class AuthRequest(BaseModel):
    email: str
    password: str

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
        return HTMLResponse("// ASTRA6", media_type="application/javascript")

@app.get("/api/status")
def status():
    users = load_users()
    return {
        "name": "ASTRA6",
        "oanda": {"has_key": bool(OANDA_API_KEY), "account_id": OANDA_ACCOUNT_ID, "env": OANDA_ENVIRONMENT},
        "mode": "ASTRA6",
        "users": len(users),
        "endpoints": ["/api/xauusd/live","/api/xauusd/history","/api/auth/signup","/api/auth/signin","/api/auth/me"]
    }

# AUTH
@app.post("/api/auth/signup")
def signup(req: AuthRequest):
    user, err = create_user(req.email, req.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    token = create_token(user["email"])
    return {"status":"ok","email": user["email"], "token": token, "message":"Account created"}

@app.post("/api/auth/signin")
def signin(req: AuthRequest):
    user = verify_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["email"])
    return {"status":"ok","email": user["email"], "token": token, "message":"Signed in"}

@app.get("/api/auth/me")
def me(authorization: str = Header(None)):
    email = get_current_user(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"status":"ok","email": email}

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

# PROTECTED DATA - require auth to access signals
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
