# Troopod API

Python FastAPI + Agno multi-agent backend.

## Local dev

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp ../.env.example .env    # fill in keys
uvicorn app.main:app --reload --port 8000
```

## Smoke tests

```bash
source .venv/bin/activate
python -m pytest -q                      # unit
python -m app.scripts.smoke_patcher      # patch a canned HTML snippet
```

## Layout

```
app/
  main.py              FastAPI app
  config.py            Env settings
  schemas/             Pydantic I/O contracts (shared with agents)
  tools/               scrape, search, vision, patcher (used as Agno tools)
  agents/              extractor, strategist, builder, verifier, refiner, pipeline
  services/            supabase_client (persistence helpers)
  routers/             HTTP routes
```
