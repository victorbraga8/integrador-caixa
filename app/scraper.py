from __future__ import annotations

import os
import time
import tempfile
import traceback
import base64
from urllib.parse import urljoin
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

DOWNLOAD_URL = "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"

def _ua() -> str:
    return os.getenv(
        "UA",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

def _b64_file(path: str, max_bytes: int = 180_000) -> str | None:
    # keep response size controlled
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
        return base64.b64encode(raw).decode("ascii")
    except Exception:
        return None

async def download_csv_by_uf(uf: str):
    uf = (uf or "").strip().upper()
    trace: dict = {"uf": uf, "steps": []}
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

        # --- event logging (ALL) ---
        console_logs = []
        req_failed = []
        res_log = []

        page.on("console", lambda m: console_logs.append({"type": m.type, "text": m.text}))
        page.on("pageerror", lambda e: console_logs.append({"type": "pageerror", "text": str(e)}))
        page.on("requestfailed", lambda r: req_failed.append({"url": r.url, "failure": (r.failure or {}).get("errorText")}))
        page.on("response", lambda r: res_log.append({"url": r.url, "status": r.status}) if "download-lista" in r.url else None)

        try:
            resp = await page.goto(DOWNLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            trace["steps"].append({"step": "goto", "url": page.url, "status": (resp.status if resp else None)})

            # wait more for JS hydration (Render sometimes slower)
            try:
                await page.wait_for_load_state("networkidle", timeout=45000)
                trace["steps"].append({"step": "networkidle"})
            except Exception:
                trace["steps"].append({"step": "networkidle_timeout"})

            # always probe HTML
            html = await page.content()
            trace["steps"].append({
                "step": "html_probe",
                "final_url": page.url,
                "has_cmb_estado": ("id=\"cmb_estado\"" in html) or ("#cmb_estado" in html) or ("cmb_estado" in html),
                "has_btn_next1": ("id=\"btn_next1\"" in html) or ("btn_next1" in html),
                "html_len": len(html),
                "html_preview": html[:2500],
            })

            # IMPORTANT: element may be hidden (opacity:0) -> use attached
            await page.wait_for_selector("#cmb_estado", state="attached", timeout=60000)
            trace["steps"].append({"step": "uf_select_found", "selector": "#cmb_estado"})

            # set UF
            await page.select_option("#cmb_estado", uf)
            trace["steps"].append({"step": "uf_selected", "uf": uf})

            # wait next button and download
            await page.wait_for_selector("#btn_next1", state="attached", timeout=60000)
            trace["steps"].append({"step": "next_found", "selector": "#btn_next1"})

            async with page.expect_download(timeout=90000) as di:
                await page.click("#btn_next1")

            download = await di.value
            suggested = download.suggested_filename
            tmp_path = os.path.join(tempfile.gettempdir(), f"caixa_{uf}_{int(time.time())}_{suggested}")
            await download.save_as(tmp_path)

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

            trace["steps"].append({
                "step": "csv_downloaded",
                "file": suggested,
                "bytes": len(raw),
                "encoding": enc,
            })

            # include helpful logs
            trace["steps"].append({"step": "console_logs", "items": console_logs[-40:]})
            if req_failed:
                trace["steps"].append({"step": "request_failed", "items": req_failed[-20:]})
            if res_log:
                trace["steps"].append({"step": "responses", "items": res_log[-30:]})

            trace["duration_ms"] = int((time.time() - t0) * 1000)
            await context.close()
            await browser.close()
            return text, trace

        except Exception as e:
            # capture screenshot/html ALWAYS on failure
            shot_path = os.path.join(tempfile.gettempdir(), f"caixa_fail_{uf}_{int(time.time())}.png")
            html_fail = ""
            try:
                await page.screenshot(path=shot_path, full_page=True)
                html_fail = await page.content()
            except Exception:
                shot_path = ""
                html_fail = ""

            trace["steps"].append({
                "step": "failure_dump",
                "final_url": page.url,
                "screenshot_b64": (_b64_file(shot_path) if shot_path else None),
                "html_preview": (html_fail[:3500] if html_fail else None),
            })

            trace["steps"].append({"step": "console_logs", "items": console_logs[-60:]})
            if req_failed:
                trace["steps"].append({"step": "request_failed", "items": req_failed[-40:]})
            if res_log:
                trace["steps"].append({"step": "responses", "items": res_log[-60:]})

            trace["error"] = str(e) or repr(e)
            trace["error_type"] = e.__class__.__name__
            trace["traceback"] = traceback.format_exc(limit=14)
            trace["duration_ms"] = int((time.time() - t0) * 1000)

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
    url = str(url)
    trace: dict = {"url": url, "steps": []}
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
            user_agent=_ua(),
            locale="pt-BR",
            viewport={"width": 1365, "height": 768},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"},
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        console_logs = []
        page.on("console", lambda m: console_logs.append({"type": m.type, "text": m.text}))
        page.on("pageerror", lambda e: console_logs.append({"type": "pageerror", "text": str(e)}))

        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            trace["steps"].append({"step": "goto", "final_url": page.url, "status": (resp.status if resp else None)})

            try:
                await page.wait_for_load_state("networkidle", timeout=45000)
                trace["steps"].append({"step": "networkidle"})
            except Exception:
                trace["steps"].append({"step": "networkidle_timeout"})

            title = ""
            try:
                title = (await page.locator("h1").first.inner_text()).strip()
            except Exception:
                pass

            related_text = ""
            try:
                rb = page.locator("div.related-box").first
                await rb.wait_for(state="attached", timeout=25000)
                related_text = (await rb.inner_text()).strip()
                trace["steps"].append({"step": "related_box_found", "chars": len(related_text)})
            except Exception as e:
                trace["steps"].append({"step": "related_box_not_found", "error": str(e)})

            imgs = []
            try:
                nodes = page.locator("img")
                n = await nodes.count()
                for i in range(n):
                    if len(imgs) >= max_images:
                        break
                    src = (await nodes.nth(i).get_attribute("src")) or ""
                    if not src or src.startswith("data:"):
                        continue
                    abs_src = urljoin(url, src)
                    if abs_src not in imgs:
                        imgs.append(abs_src)
            except Exception:
                pass

            trace["steps"].append({"step": "console_logs", "items": console_logs[-40:]})
            trace["duration_ms"] = int((time.time() - t0) * 1000)

            await context.close()
            await browser.close()
            return {
                "title": title,
                "related_box_text": related_text,
                "images": imgs[:max_images],
                "source_url": url,
            }, trace

        except Exception as e:
            shot_path = os.path.join(tempfile.gettempdir(), f"caixa_detail_fail_{int(time.time())}.png")
            html_fail = ""
            try:
                await page.screenshot(path=shot_path, full_page=True)
                html_fail = await page.content()
            except Exception:
                shot_path = ""
                html_fail = ""

            trace["steps"].append({
                "step": "failure_dump",
                "final_url": page.url,
                "screenshot_b64": (_b64_file(shot_path) if shot_path else None),
                "html_preview": (html_fail[:3500] if html_fail else None),
            })

            trace["steps"].append({"step": "console_logs", "items": console_logs[-60:]})
            trace["error"] = str(e) or repr(e)
            trace["error_type"] = e.__class__.__name__
            trace["traceback"] = traceback.format_exc(limit=14)
            trace["duration_ms"] = int((time.time() - t0) * 1000)

            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            raise
