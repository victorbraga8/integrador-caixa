from __future__ import annotations
import time, os
from fastapi import FastAPI, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from .auth import require_api_key
from .cache import cache_path_csv, is_fresh
from .csv_parser import parse_caixa_csv, sale_mode
from .scraper import download_csv_by_uf, fetch_detail
from pydantic import BaseModel, HttpUrl

class DetailRequest(BaseModel):
    url: HttpUrl

app = FastAPI(title="CAIXA Scraper API", version="0.1.0")

@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"

@app.post("/detail")
async def detail(req: DetailRequest, _: None = Depends(require_api_key)):
    max_images = int(os.getenv("MAX_IMAGES", "8"))
    d, tr = await fetch_detail(str(req.url), max_images=max_images)
    return {"ok": True, "detail": d, "trace": tr}

@app.post("/warm")
async def warm(_: None = Depends(require_api_key)):
    # aquece Playwright sem depender do CSV
    d, tr = await fetch_detail("https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp", max_images=0)
    return {"ok": True, "note": "warmed", "trace": tr}

@app.post("/sync/{uf}/one")
async def sync_one(uf: str, _: None = Depends(require_api_key)):
    uf = uf.upper()
    t0 = time.time()
    trace = {"uf": uf, "steps": []}

    csv_path = cache_path_csv(uf)
    if is_fresh(csv_path):
        trace["steps"].append({"step":"csv_cache_hit","path":csv_path})
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            csv_text = f.read()
    else:
        trace["steps"].append({"step":"csv_cache_miss"})
        csv_text, tr = await download_csv_by_uf(uf)
        trace["steps"].append({"step":"download_csv_done","download_trace":tr})
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(csv_text)

    rows = parse_caixa_csv(csv_text)
    trace["steps"].append({"step":"csv_parsed","rows":len(rows)})

    picked = None
    for r in rows:
        sm = sale_mode(r)
        link = (r.get("link_de_acesso") or "").strip()
        if sm and link.startswith("http"):
            picked = dict(r)
            picked["__sale_mode"] = sm
            break

    if not picked:
        return JSONResponse({"ok": False, "uf": uf, "error": "Nenhum imóvel elegível (Venda Online/Direta) encontrado", "trace": trace}, status_code=404)

    link = picked.get("link_de_acesso")
    caixa_id = picked.get("n_do_imovel")
    max_images = int(os.getenv("MAX_IMAGES", "8"))

    det, det_trace = await fetch_detail(link, max_images=max_images)
    trace["steps"].append({"step":"detail_done","detail_trace":det_trace})
    trace["duration_ms"] = int((time.time() - t0) * 1000)

    return {
        "ok": True,
        "uf": uf,
        "caixa_id": caixa_id,
        "link": link,
        "sale_mode": picked.get("__sale_mode"),
        "row": {k:v for k,v in picked.items() if not k.startswith("__")},
        "detail": det,
        "trace": trace,
    }
