"""
GPT-6 Astra Standby Website Widget - Backend
Model: gpt-6-astra (OpenAI)
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Astra Standby API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (widget.js, index.html)
app.mount("/static", StaticFiles(directory="."), name="static")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_ID = os.getenv("ASTRA_MODEL", "gpt-6-astra")

class ChatRequest(BaseModel):
    message: str
    history: list = []  # [{"role":"user","content":"..."}]
    system_prompt: str = "You are GPT-6 Astra, OpenAI's flagship model for demanding end-to-end work. You are standby on this website as a helpful assistant. Be concise, friendly, and proactive. You help with coding, research, trading, and general questions."

class ChatResponse(BaseModel):
    reply: str
    model: str

@app.get("/", response_class=HTMLResponse)
def demo():
    with open("index.html", "r") as f:
        return f.read()

@app.get("/embed", response_class=HTMLResponse)
def embed_demo():
    with open("embed.html", "r") as f:
        return f.read()

@app.get("/widget.js")
def get_widget():
    with open("widget.js", "r") as f:
        content = f.read()
    return HTMLResponse(content, media_type="application/javascript")

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    user_msg = req.message.strip()
    if not user_msg:
        return ChatResponse(reply="Hi! Astra is standby. How can I help?", model=MODEL_ID)

    # If no API key, return smart mock (so preview works without key)
    if not OPENAI_API_KEY:
        # Mock Astra-like response for demo
        mock_reply = f"""[DEMO MODE - Add OPENAI_API_KEY to use real GPT-6 Astra]

I'm Astra, standby on your site. You said: "{user_msg}"

I can help with:
- XAUUSD auto-trading (I see you built a bot)
- Coding & website automation
- Research & analysis

To enable real GPT-6 Astra:
1. Set OPENAI_API_KEY in .env
2. Model will be `{MODEL_ID}` (1.05M context, $10/$50 per 1M)

Want me to wire it to your real OpenAI key?"""
        return ChatResponse(reply=mock_reply, model=f"{MODEL_ID} (demo)")

    # Real OpenAI call
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        messages = [{"role": "system", "content": req.system_prompt}]
        # include history (last 10)
        for h in req.history[-10:]:
            if h.get("role") in ["user","assistant"] and h.get("content"):
                messages.append(h)
        messages.append({"role": "user", "content": user_msg})

        # Astra supports reasoning effort: low, medium, high, xhigh, max
        # We'll use medium for website chat for speed
        response = client.chat.completions.create(
            model=MODEL_ID,
            messages=messages,
            max_tokens=2000,
            temperature=0.7,
        )
        reply = response.choices[0].message.content
        return ChatResponse(reply=reply, model=MODEL_ID)
    except Exception as e:
        return ChatResponse(reply=f"Astra error (check API key/model access): {str(e)}\n\nMake sure your OpenAI account has access to gpt-6-astra. It was released Sep 3 2026 and requires Pro/Business or API access.", model=MODEL_ID)

@app.get("/api/status")
def status():
    return {
        "model": MODEL_ID,
        "has_api_key": bool(OPENAI_API_KEY),
        "mode": "live" if OPENAI_API_KEY else "demo",
        "context_window": "1,050,000",
        "standby": True,
        "endpoints": ["/api/chat", "/api/status", "/widget.js"]
    }
