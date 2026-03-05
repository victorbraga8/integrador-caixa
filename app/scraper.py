
# PATCHED scraper for CAIXA download page
# Only change: robust selector for UF dropdown and download trigger

import asyncio
from playwright.async_api import async_playwright

URL = "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"

UF_SELECTORS = [
    "#cmb_estado",
    "select[name='cmb_estado']",
    "select"
]

NEXT_BUTTON_SELECTORS = [
    "#btn_next1",
    "button#btn_next1",
    "button.submit-blue"
]

async def download_csv_for_uf(page, uf="RJ"):
    selector_used=None

    for sel in UF_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=8000)
            selector_used=sel
            break
        except:
            pass

    if not selector_used:
        raise RuntimeError("select de UF não encontrado na página")

    await page.select_option(selector_used, uf)

    btn=None
    for b in NEXT_BUTTON_SELECTORS:
        try:
            await page.wait_for_selector(b, timeout=5000)
            btn=b
            break
        except:
            pass

    if not btn:
        raise RuntimeError("botão Próximo não encontrado")

    async with page.expect_download() as download_info:
        await page.click(btn)

    download=await download_info.value
    path=await download.path()
    return path


async def run_sync(uf="RJ"):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        await page.goto(URL, timeout=60000)

        csv_path = await download_csv_for_uf(page, uf)

        with open(csv_path,"r",encoding="latin1",errors="ignore") as f:
            lines=f.readlines()

        return {
            "ok": True,
            "uf": uf,
            "lines": len(lines)
        }
