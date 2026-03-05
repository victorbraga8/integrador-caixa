
from fastapi import FastAPI, Header
from scraper import run_sync

API_KEY = "vbraga_caixa_sync_9K2fL4sX81"

app = FastAPI()

def auth(key):
    if key != API_KEY:
        return False
    return True

@app.get("/health")
def health():
    return {"ok":True}

@app.post("/warm")
async def warm(x_api_key: str = Header(None)):
    if not auth(x_api_key):
        return {"ok":False,"error":"unauthorized"}
    return {"ok":True,"msg":"warm ok"}

@app.post("/sync/RJ/one")
async def sync_rj(x_api_key: str = Header(None)):
    if not auth(x_api_key):
        return {"ok":False,"error":"unauthorized"}

    result = await run_sync("RJ")
    return result
