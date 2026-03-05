# CAIXA Scraper API (Render) — FastAPI + Playwright

API para:
- navegar no fluxo da CAIXA e baixar o CSV por UF (ex: RJ)
- parsear e filtrar apenas "Venda Online" / "Venda Direta Online"
- abrir o link do imóvel e extrair `div.related-box` + imagens
- devolver JSON pronto para o plugin WordPress inserir/atualizar o CPT

## Endpoints
- GET /health
- POST /warm
- POST /sync/{uf}/one
- POST /detail  (body: {"url": "https://..."})

## Auth
Header obrigatório:
- `X-API-KEY: <API_TOKEN>`

Defina `API_TOKEN` em env.

## Cache (cold-start blindagem)
- CSV cache: `/tmp/caixa_{UF}.csv`
- TTL por env: `CACHE_TTL_SECONDS` (default: 21600 = 6h)

## Rodar local
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload --port 10000
```

## Deploy no Render
- Service: Web Service
- Runtime: Docker
- Health Check Path: `/health`
- Env Vars:
  - `API_TOKEN` (obrigatório)
  - `CACHE_TTL_SECONDS` (opcional)
  - `PLAYWRIGHT_HEADLESS` (opcional, default: true)
