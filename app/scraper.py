from __future__ import annotations

import os, time, tempfile, traceback
from urllib.parse import urljoin
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

DOWNLOAD_URL = "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"

UF_SELECTORS = [
    "#cmb_estado",
    "select[name='cmb_estado']",
    "select.select#cmb_estado",
    "select",
]

NEXT_SELECTORS = [
    "#btn_next1",
    "button#btn_next1",
    "button.submit-blue",
    "text=Próximo",
]

RELATED_BOX = "div.related-box"

def _now_tag() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

async def _new_browser():
    # Render-friendly flags
    return async_playwright()

async def download_csv_by_uf(uf: str):
    uf = (uf or "").strip().upper()
    trace = {"uf": uf, "steps": []}
    t0 = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            accept_downloads=True,
            user_agent=os.getenv("UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"),
            locale="pt-BR",
        )
        page = await context.new_page()

        try:
            await page.goto(DOWNLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            trace["steps"].append({"step": "open_download_page", "url": DOWNLOAD_URL})

            sel_used = None
            for sel in UF_SELECTORS:
                try:
                    await page.wait_for_selector(sel, timeout=15000)
                    sel_used = sel
                    break
                except PWTimeoutError:
                    continue

            if not sel_used:
                # help debug: small html snippet
                html = await page.content()
                trace["steps"].append({"step": "uf_select_not_found", "html_preview": html[:1200]})
                raise RuntimeError("select de UF não encontrado na página")

            trace["steps"].append({"step": "uf_select_found", "selector": sel_used})

            # ensure option exists
            try:
                await page.wait_for_selector(f"{sel_used} option[value='{uf}']", timeout=15000)
            except PWTimeoutError:
                # fallback: don't include sel_used in selector if it's "select"
                await page.wait_for_selector(f"option[value='{uf}']", timeout=15000)

            await page.select_option(sel_used, uf)
            trace["steps"].append({"step": "uf_selected", "uf": uf})

            btn_used = None
            for b in NEXT_SELECTORS:
                try:
                    await page.wait_for_selector(b, timeout=10000)
                    btn_used = b
                    break
                except PWTimeoutError:
                    continue

            if not btn_used:
                trace["steps"].append({"step": "next_button_not_found"})
                raise RuntimeError("botão Próximo não encontrado")

            trace["steps"].append({"step": "next_button_found", "selector": btn_used})

            async with page.expect_download(timeout=60000) as download_info:
                await page.click(btn_used)

            download = await download_info.value
            suggested = download.suggested_filename
            tmp_path = os.path.join(tempfile.gettempdir(), f"caixa-{uf}-{_now_tag()}-{suggested}")
            await download.save_as(tmp_path)
            trace["steps"].append({"step": "csv_downloaded", "file": suggested, "path": tmp_path})

            # decode robustly (CAIXA typically latin1/cp1252)
            raw = open(tmp_path, "rb").read()
            try:
                text = raw.decode("utf-8")
                enc = "utf-8"
            except UnicodeDecodeError:
                try:
                    text = raw.decode("cp1252")
                    enc = "cp1252"
                except UnicodeDecodeError:
                    text = raw.decode("latin1", errors="replace")
                    enc = "latin1"

            trace["steps"].append({"step": "csv_decoded", "encoding": enc, "bytes": len(raw)})
            trace["duration_ms"] = int((time.time() - t0) * 1000)
            await context.close()
            await browser.close()
            return text, trace

        except Exception as e:
            tag = _now_tag()
            # best-effort artifacts
            try:
                shot = os.path.join(tempfile.gettempdir(), f"caixa-download-{uf}-{tag}.png")
                await page.screenshot(path=shot, full_page=True)
                trace["steps"].append({"step": "screenshot_saved", "path": shot})
            except Exception:
                pass
            try:
                html = await page.content()
                trace["steps"].append({"step": "html_preview", "value": html[:1200]})
            except Exception:
                pass

            trace["duration_ms"] = int((time.time() - t0) * 1000)
            trace["error"] = str(e) or repr(e)
            trace["error_type"] = e.__class__.__name__
            trace["traceback"] = traceback.format_exc(limit=10)
            await context.close()
            await browser.close()
            raise

async def fetch_detail(url: str, max_images: int = 8):
    trace = {"url": url, "steps": []}
    t0 = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=os.getenv("UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"),
            locale="pt-BR",
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            trace["steps"].append({"step": "open_detail", "url": url})

            # Title
            title = ""
            for sel in ["h1", "h1 strong", "title"]:
                try:
                    loc = page.locator(sel).first
                    if await loc.count():
                        title = (await loc.inner_text()).strip()
                        if title:
                            trace["steps"].append({"step":"title_found","selector":sel})
                            break
                except Exception:
                    continue

            # related-box text (payment rules live there)
            related_text = ""
            try:
                rb = page.locator(RELATED_BOX).first
                await rb.wait_for(timeout=10000)
                related_text = (await rb.inner_text()).strip()
                trace["steps"].append({"step":"related_box_found","chars":len(related_text)})
            except Exception:
                trace["steps"].append({"step":"related_box_not_found"})

            # collect images (gallery + any img)
            imgs = []
            try:
                img_nodes = page.locator("img")
                n = await img_nodes.count()
                for i in range(n):
                    if len(imgs) >= max_images:
                        break
                    node = img_nodes.nth(i)
                    src = (await node.get_attribute("src")) or ""
                    if not src:
                        continue
                    if src.startswith("data:"):
                        continue
                    abs_src = urljoin(url, src)
                    if abs_src not in imgs:
                        imgs.append(abs_src)
                trace["steps"].append({"step":"images_collected","count":len(imgs)})
            except Exception as e:
                trace["steps"].append({"step":"images_failed","error":str(e)})

            detail = {
                "title": title,
                "related_box_text": related_text,
                "images": imgs[:max_images],
                "source_url": url,
            }

            trace["duration_ms"] = int((time.time() - t0) * 1000)
            await context.close()
            await browser.close()
            return detail, trace

        except Exception as e:
            tag = _now_tag()
            try:
                shot = os.path.join(tempfile.gettempdir(), f"caixa-detail-{tag}.png")
                await page.screenshot(path=shot, full_page=True)
                trace["steps"].append({"step": "screenshot_saved", "path": shot})
            except Exception:
                pass
            try:
                html = await page.content()
                trace["steps"].append({"step": "html_preview", "value": html[:1200]})
            except Exception:
                pass

            trace["duration_ms"] = int((time.time() - t0) * 1000)
            trace["error"] = str(e) or repr(e)
            trace["error_type"] = e.__class__.__name__
            trace["traceback"] = traceback.format_exc(limit=10)
            await context.close()
            await browser.close()
            raise
