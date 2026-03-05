import os, time, pathlib

def ttl_seconds() -> int:
    v = os.getenv("CACHE_TTL_SECONDS", "21600").strip()
    try:
        return max(0, int(v))
    except:
        return 21600

def cache_path_csv(uf: str) -> str:
    uf = uf.upper()
    return f"/tmp/caixa_{uf}.csv"

def is_fresh(path: str) -> bool:
    ttl = ttl_seconds()
    if ttl <= 0:
        return False
    p = pathlib.Path(path)
    if not p.exists():
        return False
    age = time.time() - p.stat().st_mtime
    return age <= ttl
