# FINOVA — Goal-Based Personal Finance Planning Engine

English-language web app (Flask + vanilla JS) built from the "BƯỚC CODE" specification.

## Run locally
    pip install -r requirements.txt
    cp .env.example .env      # add GEMINI_API_KEY (optional)
    python app.py             # http://localhost:5000

## Deploy on Render
1. Push this folder to a GitHub repo.
2. Render → New → Blueprint (uses `render.yaml`) or New Web Service:
   Build `pip install -r requirements.txt`, Start `gunicorn app:app --workers 2 --timeout 120 --bind 0.0.0.0:$PORT`.
3. Add environment variable `GEMINI_API_KEY` (Google AI Studio). It is read server-side only.
4. Data (SQLite) lives in `instance/`. Render's free tier has an ephemeral disk: accounts/ratings reset on redeploy.
   Attach a Render Disk and set `DATA_DIR=/var/data` to persist.

Without an API key the site still works: Python computes everything and explanations are rule-based.

## Structure
- `engine.py` deterministic calculations, scenarios, Excel import/export, self-tests
- `narrative.py` rule-based explanations from engine output
- `ai.py` Gemini proxy, chatbot system instructions, RAG over `data/faq.json`
- `app.py` Flask API + SQLite; `static/` front end
