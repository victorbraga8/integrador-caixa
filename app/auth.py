import os
from fastapi import Header, HTTPException

def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-KEY")) -> None:
    token = os.getenv("API_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=500, detail="API_TOKEN env não configurado")
    if not x_api_key or x_api_key.strip() != token:
        raise HTTPException(status_code=401, detail="unauthorized")
