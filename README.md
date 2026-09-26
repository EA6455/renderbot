# Astra Standby - Deploy to Render 24/7

Your GPT-6 Astra standby website is ready for Render.

## Deploy in 2 minutes (no API token needed)

### Option A: Dashboard (Easiest)
1. Push this folder to GitHub:
   ```bash
   git init
   git add .
   git commit -m "astra standby"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/astra-standby.git
   git push -u origin main
   ```
2. Go to **dashboard.render.com** → **New +** → **Web Service**
3. Connect your GitHub repo `astra-standby`
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT` [3]
   - **Region:** Singapore (closest to Phnom Penh)
   - **Plan:** Free (sleeps after 15min, or $7/mo for always-on) [3]
5. Add env vars in **Environment** tab:
   - `GEMINI_API_KEY` = your free key from aistudio.google.com/app/apikey (recommended, free, no card)
   - Or `GROQ_API_KEY` from console.groq.com/keys
   - Or `OPENAI_API_KEY` for real gpt-6-astra
6. Click **Create Web Service** → Live URL like `https://astra-standby.onrender.com`

### Option B: Blueprint (render.yaml)
1. Push to GitHub
2. In Render dashboard → **New +** → **Blueprint** → Connect repo
3. Render reads `render.yaml` and creates service automatically

## After Deploy - Embed on ANY Website

Add 1 line before `</body>`:

```html
<script src="https://astra-standby.onrender.com/widget.js" 
  data-api="https://astra-standby.onrender.com/api/chat"
  data-color="#f5c518"
  data-title="Astra • Standby">
</script>
```

Now Astra orb is standby 24/7 on your site.

## Free API Keys (no credit card)

- **Gemini 2.5 Flash:** 15 RPM / 1500/day / 1M context [free] → aistudio.google.com/app/apikey
- **Groq Llama 3.3 70B:** 750 tok/s, fastest → console.groq.com/keys
- **OpenRouter:** 50 req/day free → openrouter.ai/keys

## Why your token failed

You sent `731bc4f461f89c97db0ad13119c80649` — Render API returns `Unauthorized`. Valid Render API keys start with `rnd_...` and are created at dashboard.render.com → Account Settings → API Keys.

You don't need API key to deploy via dashboard — just use GitHub method above.

## Local Test

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001
# Open http://localhost:8001
```

## Files
- `main.py` - FastAPI backend (supports gpt-6-astra, gemini, groq, openrouter)
- `index.html` - Demo landing
- `widget.js` - Embeddable standby orb
- `embed.html` - Embed instructions
- `render.yaml` - Render blueprint
