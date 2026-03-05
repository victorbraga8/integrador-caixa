
from __future__ import annotations
import os, time, tempfile, traceback
from urllib.parse import urljoin
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

URL="https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"

async def download_csv_by_uf(uf:str):
    uf=uf.upper()
    trace={"uf":uf,"steps":[]}
    t0=time.time()

    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=await browser.new_context(accept_downloads=True)
        page=await context.new_page()

        try:
            await page.goto(URL,wait_until="domcontentloaded",timeout=60000)
            trace["steps"].append({"step":"page_loaded"})

            # IMPORTANT: selector exists but is hidden (opacity:0)
            await page.wait_for_selector("#cmb_estado",state="attached",timeout=20000)
            trace["steps"].append({"step":"uf_select_found"})

            await page.select_option("#cmb_estado",uf)
            trace["steps"].append({"step":"uf_selected","uf":uf})

            await page.wait_for_selector("#btn_next1",state="attached",timeout=20000)

            async with page.expect_download(timeout=60000) as d:
                await page.click("#btn_next1")

            download=await d.value
            path=os.path.join(tempfile.gettempdir(),f"caixa_{uf}_{int(time.time())}.csv")
            await download.save_as(path)

            raw=open(path,"rb").read()

            try:
                txt=raw.decode("utf-8")
            except:
                txt=raw.decode("latin1","replace")

            trace["steps"].append({"step":"csv_downloaded","bytes":len(raw)})
            trace["duration_ms"]=int((time.time()-t0)*1000)

            await browser.close()
            return txt,trace

        except Exception as e:
            trace["error"]=str(e)
            trace["traceback"]=traceback.format_exc()
            trace["duration_ms"]=int((time.time()-t0)*1000)
            await browser.close()
            raise

async def fetch_detail(url:str,max_images:int=8):
    trace={"url":url,"steps":[]}
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        page=await browser.new_page()

        await page.goto(url,wait_until="domcontentloaded",timeout=60000)

        title=""
        try:
            title=await page.locator("h1").inner_text()
        except:
            pass

        imgs=[]
        nodes=page.locator("img")
        count=await nodes.count()
        for i in range(count):
            if len(imgs)>=max_images:
                break
            src=await nodes.nth(i).get_attribute("src")
            if src and src.startswith("http"):
                imgs.append(src)

        detail={
            "title":title,
            "images":imgs,
            "source_url":url
        }

        await browser.close()
        return detail,trace
