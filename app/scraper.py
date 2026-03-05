from __future__ import annotations
import os, time
from urllib.parse import urljoin
from playwright.async_api import async_playwright

DOWNLOAD_PAGE = "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"

def _headless() -> bool:
    v = os.getenv("PLAYWRIGHT_HEADLESS", "true").strip().lower()
    return v not in ("0","false","no","off")

async def download_csv_by_uf(uf: str) -> tuple[str, dict]:
    uf = uf.upper().strip()
    trace = {"uf": uf, "steps": []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=_headless(), args=["--no-sandbox"])
        context = await browser.new_context(locale="pt-BR")
        page = await context.new_page()

        t0 = time.time()
        trace["steps"].append({"step":"goto_download_page","url":DOWNLOAD_PAGE})
        await page.goto(DOWNLOAD_PAGE, wait_until="domcontentloaded", timeout=120_000)

        sel = page.locator("select")
        if await sel.count() == 0:
            raise RuntimeError("select de UF não encontrado na página")

        trace["steps"].append({"step":"select_uf","value":uf})
        await sel.first.select_option(value=uf)

        btn = page.get_by_role("button", name="Próximo")
        if await btn.count() == 0:
            btn = page.locator("text=Próximo").first

        trace["steps"].append({"step":"click_next_expect_download"})
        async with page.expect_download(timeout=120_000) as dl_info:
            await btn.click()

        download = await dl_info.value
        path = await download.path()
        if path:
            with open(path, "rb") as f:
                data = f.read()
        else:
            data = await download.content()

        await context.close()
        await browser.close()

        trace["duration_ms"] = int((time.time() - t0) * 1000)

        try:
            txt = data.decode("utf-8")
        except:
            txt = data.decode("latin-1", errors="replace")
        return txt, trace

async def fetch_detail(url: str, max_images: int = 8) -> tuple[dict, dict]:
    trace = {"url": url, "steps": []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=_headless(), args=["--no-sandbox"])
        context = await browser.new_context(locale="pt-BR")
        page = await context.new_page()

        t0 = time.time()
        trace["steps"].append({"step":"goto_detail","url":url})
        await page.goto(url, wait_until="domcontentloaded", timeout=120_000)

        rb = page.locator(".related-box").first
        related_text = ""
        if await rb.count() > 0:
            related_text = (await rb.inner_text()).strip()
        trace["steps"].append({"step":"extract_related_box","len":len(related_text)})

        imgs = page.locator("img")
        srcs = []
        n = await imgs.count()
        for i in range(min(n, 60)):
            s = await imgs.nth(i).get_attribute("src")
            if not s or s.startswith("data:"):
                continue
            srcs.append(urljoin(url, s))

        uniq = []
        seen = set()
        for s in srcs:
            if s in seen:
                continue
            seen.add(s)
            uniq.append(s)

        uniq = uniq[: max(0, int(max_images))]
        trace["steps"].append({"step":"extract_images","count":len(uniq)})

        await context.close()
        await browser.close()

        trace["duration_ms"] = int((time.time() - t0) * 1000)
        return {"related_box_text": related_text, "images": uniq}, trace
