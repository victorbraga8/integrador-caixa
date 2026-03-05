from __future__ import annotations
import re

def _norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("°","").replace("º","").replace("ª","")
    s = re.sub(r"[^\w]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")

def parse_caixa_csv(csv_text: str) -> list[dict[str, str]]:
    csv_text = re.sub(r"^\ufeff", "", csv_text)
    lines = [l for l in re.split(r"\r\n|\n|\r", csv_text) if l.strip()]
    header_idx = -1
    for i, l in enumerate(lines):
        if "N° do imóvel" in l or "Nº do imóvel" in l or "N° do imovel" in l:
            header_idx = i
            break
    if header_idx == -1:
        return []

    header_raw = lines[header_idx].split(";")
    header = [_norm_key(h) for h in header_raw]

    out: list[dict[str, str]] = []
    for l in lines[header_idx+1:]:
        cols = l.split(";")
        if len(cols) < len(header):
            continue
        row = {header[i]: (cols[i] or "").strip() for i in range(len(header))}
        if row.get("n_do_imovel"):
            row["n_do_imovel"] = row["n_do_imovel"].replace(" ", "").strip()
        out.append(row)
    return out

def sale_mode(row: dict[str, str]) -> str | None:
    m = row.get("modalidade_de_venda", "") or ""
    if "Venda Direta Online" in m:
        return "Venda Direta Online"
    if "Venda Online" in m:
        return "Venda Online"
    return None
