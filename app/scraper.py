from __future__ import annotations

import os, time, tempfile, traceback
from urllib.parse import urljoin
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

DOWNLOAD_URL = "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"

def _now_tag() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

def _ua() -> str:
    return os.getenv(
        "UA",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

async def download_csv_by_uf(uf: str):
    uf = (uf or "").strip().upper()
    trace = {"uf": uf, "steps": []}
    t0 = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            accept_downloads=True,
            user_agent=_ua(),
            locale="pt-BR",
            viewport={"width": 1365, "height": 768},
            extra_http_headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        page = await context.new_page()
        page.set_default_timeout(60000)

        # reduce webdriver signals a bit (best-effort)
        try:
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        except Exception:
            pass

        try:
            resp = await page.goto(DOWNLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            status = resp.status if resp else None
            trace["steps"].append({"step": "goto", "url": page.url, "status": status})

            # some pages render via JS after domcontentloaded
            try:
                await page.wait_for_load_state("networkidle", timeout=45000)
                trace["steps"].append({"step": "networkidle"})
            except Exception:
                trace["steps"].append({"step": "networkidle_timeout"})

            # quick probe: is #cmb_estado in HTML at all?
            html = await page.content()
            has_id = "#cmb_estado" in html or "id=\"cmb_estado\"" in html or "cmb_estado" in html
            trace["steps"].append({"step": "html_probe", "has_cmb_estado": bool(has_id), "html_len": len(html)})

            # try to find selector attached (NOT visible)
            try:
                await page.wait_for_selector("#cmb_estado", state="attached", timeout=60000)
                trace["steps"].append({"step": "uf_select_found", "selector": "#cmb_estado"})
            except PWTimeoutError as e:
                # dump preview + screenshot for debug (this is critical: on Render the page may differ / block)
                tag = _now_tag()
                shot = os.path.join(tempfile.gettempdir(), f"caixa-download-{uf}-{tag}.png")
                try:
                    await page.screenshot(path=shot, full_page=True)
                except Exception:
                    shot = None

                html2 = await page.content()
                trace["steps"].append({
                    "step": "uf_select_not_found",
                    "error": str(e),
                    "screenshot": shot,
                    "html_preview": html2[:1800],
                    "final_url": page.url,
                })
                raise RuntimeError("select de UF não encontrado na página")

            # select option
            await page.select_option("#cmb_estado", uf)
            trace["steps"].append({"step": "uf_selected", "uf": uf})

            # click Próximo and catch download
            await page.wait_for_selector("#btn_next1", state="attached", timeout=60000)
            trace["steps"].append({"step": "next_found"})

            async with page.expect_download(timeout=60000) as download_info:
                await page.click("#btn_next1")

            download = await download_info.value
            suggested = download.suggested_filename
            tmp_path = os.path.join(tempfile.gettempdir(), f"caixa-{uf}-{_now_tag()}-{suggested}")
            await download.save_as(tmp_path)
            trace["steps"].append({"step": "csv_downloaded", "file": suggested, "path": tmp_path})

            raw = open(tmp_path, "rb").read()
            enc = "utf-8"
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                enc = "cp1252"
                try:
                    text = raw.decode("cp1252")
                except UnicodeDecodeError:
                    enc = "latin1"
                    text = raw.decode("latin1", errors="replace")

            trace["steps"].append({"step": "csv_decoded", "encoding": enc, "bytes": len(raw)})
            trace["duration_ms"] = int((time.time() - t0) * 1000)

            await context.close()
            await browser.close()
            return text, trace

        except Exception as e:
            trace["duration_ms"] = int((time.time() - t0) * 1000)
            trace["error"] = str(e) or repr(e)
            trace["error_type"] = e.__class__.__name__
            trace["traceback"] = traceback.format_exc(limit=12)
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            raise


async def fetch_detail(url: str, max_images: int = 8):
    trace = {"url": url, "steps": []}
    t0 = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=_ua(),
            locale="pt-BR",
            viewport={"width": 1365, "height": 768},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"},
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            trace["steps"].append({"step": "goto", "url": page.url, "status": resp.status if resp else None})

            try:
                await page.wait_for_load_state("networkidle", timeout=45000)
                trace["steps"].append({"step": "networkidle"})
            except Exception:
                trace["steps"].append({"step": "networkidle_timeout"})

            title = ""
            for sel in ["h1", "h1 strong", "title"]:
                try:
                    loc = page.locator(sel).first
                    if await loc.count():
                        title = (await loc.inner_text()).strip()
                        if title:
                            break
                except Exception:
                    continue

            related_text = ""
            try:
                rb = page.locator("div.related-box").first
                await rb.wait_for(state="attached", timeout=20000)
                related_text = (await rb.inner_text()).strip()
                trace["steps"].append({"step": "related_box_found", "chars": len(related_text)})
            except Exception:
                trace["steps"].append({"step": "related_box_not_found"})

            imgs = []
            try:
                img_nodes = page.locator("img")
                n = await img_nodes.count()
                for i in range(n):
                    if len(imgs) >= max_images:
                        break
                    node = img_nodes.nth(i)
                    src = (await node.get_attribute("src")) or ""
                    if not src or src.startswith("data:"):
                        continue
                    abs_src = urljoin(url, src)
                    if abs_src not in imgs:
                        imgs.append(abs_src)
            except Exception:
                pass

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
            trace["duration_ms"] = int((time.time() - t0) * 1000)
            trace["error"] = str(e) or repr(e)
            trace["error_type"] = e.__class__.__name__
            trace["traceback"] = traceback.format_exc(limit=12)
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            raise
