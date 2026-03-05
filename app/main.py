from __future__ import annotations
import time, os, traceback
from fastapi import FastAPI, Depends, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from .auth import require_api_key
from .cache import cache_path_csv, is_fresh
from .csv_parser import parse_caixa_csv, sale_mode
from .scraper import download_csv_by_uf, fetch_detail
from pydantic import BaseModel, HttpUrl

class DetailRequest(BaseModel):
    url: HttpUrl

app = FastAPI(title="CAIXA Scraper API", version="0.2.0")

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc(limit=12)
    # log no Render
    print("UNHANDLED_ERROR", {"path": str(request.url), "err": repr(exc)})
    print(tb)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": str(exc) or repr(exc),
            "error_type": exc.__class__.__name__,
            "path": str(request.url),
            "traceback": tb,
        },
    )

@app.get("/health")
def health():
    return {"ok": True, "service": "integrador-caixa", "ts": int(time.time())}

@app.post("/detail")
async def detail(req: DetailRequest, _: None = Depends(require_api_key)):
    max_images = int(os.getenv("MAX_IMAGES", "8"))
    try:
        d, tr = await fetch_detail(str(req.url), max_images=max_images)
        return {"ok": True, "detail": d, "trace": tr}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "error_type": e.__class__.__name__}, status_code=502)

@app.post("/warm")
async def warm(_: None = Depends(require_api_key)):
    # aquece Playwright: abre a página de download (não depende de CSV)
    try:
        d, tr = await fetch_detail("https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp", max_images=0)
        return {"ok": True, "note": "warmed", "trace": tr}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "error_type": e.__class__.__name__}, status_code=502)

@app.post("/sync/{uf}/one")
async def sync_one(uf: str, _: None = Depends(require_api_key)):
    uf = uf.upper()
    t0 = time.time()
    trace = {"uf": uf, "steps": []}

    csv_path = cache_path_csv(uf)

    try:
        if is_fresh(csv_path):
            trace["steps"].append({"step":"csv_cache_hit","path":csv_path})
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                csv_text = f.read()
        else:
            trace["steps"].append({"step":"csv_cache_miss"})
            try:
                csv_text, tr = await download_csv_by_uf(uf)
                trace["steps"].append({"step":"download_csv_done","download_trace":tr})
            except Exception as e:
                trace["steps"].append({"step":"download_csv_failed","error":str(e),"error_type":e.__class__.__name__})
                raise
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

        try:
            det, det_trace = await fetch_detail(link, max_images=max_images)
            trace["steps"].append({"step":"detail_done","detail_trace":det_trace})
        except Exception as e:
            trace["steps"].append({"step":"detail_failed","error":str(e),"error_type":e.__class__.__name__})
            return JSONResponse({"ok": False, "uf": uf, "error": "Falha ao acessar detalhe do imóvel", "detail_url": link, "trace": trace}, status_code=502)

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

    except Exception as e:
        trace["steps"].append({"step":"sync_failed","error":str(e),"error_type":e.__class__.__name__})
        trace["duration_ms"] = int((time.time() - t0) * 1000)
        return JSONResponse({"ok": False, "uf": uf, "error": "Falha no sync", "trace": trace}, status_code=502)
