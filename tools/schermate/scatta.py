"""Le schermate della vetrina: dati finti, servizi locali (avvia.sh). Uso: vedi LEGGIMI.md qui accanto."""
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

V = sys.argv[1]
CHROME = os.environ.get("CHROME") or "google-chrome"     # un Chrome/Chromium già installato


def init_data():
    campi = {"auth_date": str(int(time.time())), "query_id": "AAprova",
             "user": json.dumps({"id": 424242, "first_name": "Tu", "language_code": "it"}, separators=(",", ":"))}
    controllo = "\n".join(f"{k}={v}" for k, v in sorted(campi.items()))
    campi["hash"] = hmac.new(bytes.fromhex("a" * 64), controllo.encode(), hashlib.sha256).hexdigest()
    return urlencode(campi)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])
    # 1. installatore grafico, modulo compilato
    pg = b.new_page(viewport={"width": 1100, "height": 860}, device_scale_factor=1.5)
    pg.goto("http://127.0.0.1:18777/")
    pg.wait_for_timeout(600)
    for campo, valore in (("#ip", "203.0.113.10"), ("#password", "non-una-password-vera"),
                          ("#admin_email", "tu@example.invalid"), ("#ts_hostname", "la-mia-vps")):
        pg.fill(campo, valore)
    pg.evaluate("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)")
    pg.wait_for_timeout(400)
    pg.screenshot(path=f"{V}/scatti/installatore.png")
    # 2. pannello: aggiornamenti
    pg = b.new_page(viewport={"width": 1100, "height": 820}, device_scale_factor=1.5, extra_http_headers={"X-Forwarded-Proto": "https"})
    pg.goto("http://127.0.0.1:18080/admin/login")
    pg.fill("input[name=email]", "tu@example.invalid")
    pg.fill("input[name=password]", "Schermata-di-Prova-1777")
    pg.press("input[name=password]", "Enter")
    pg.wait_for_load_state("networkidle")
    print("dopo il login:", pg.url)
    for nome in ("update",):
        pg.goto(f"http://127.0.0.1:18080/admin/{nome}")
        pg.wait_for_load_state("networkidle")
        pg.wait_for_timeout(500)
        pg.screenshot(path=f"{V}/scatti/pannello-{nome}.png", full_page=True)
    # 3. Mini App (telefono), con l'SDK di Telegram finto e un accesso firmato con la chiave di prova
    ctx = b.new_context(viewport={"width": 400, "height": 760}, device_scale_factor=2, is_mobile=True)
    ctx.route("**/telegram-web-app.js", lambda r: r.fulfill(content_type="application/javascript", body=""))
    ctx.add_init_script("window.Telegram={WebApp:{initData:%s,initDataUnsafe:{},ready(){},expand(){},close(){},"
                        "colorScheme:'light',themeParams:{},MainButton:{show(){},hide(){},setText(){},onClick(){}},"
                        "BackButton:{show(){},hide(){},onClick(){}},HapticFeedback:{impactOccurred(){},notificationOccurred(){}},"
                        "onEvent(){},showAlert(m){},showConfirm(m,c){c&&c(true)},openLink(){},setHeaderColor(){},setBackgroundColor(){}}};"
                        % json.dumps(init_data()))
    pg = ctx.new_page()
    pg.on("console", lambda m: print("console:", m.text[:160]) if m.type == "error" else None)
    pg.goto("http://127.0.0.1:18080/app")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(1500)
    pg.click("button[data-tab=notebook]")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{V}/scatti/miniapp.png")
    # 4. l'immagine di anteprima dei link (1280x640), da tools/schermate/anteprima.html
    pg = b.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=1)
    pg.goto("file://" + str(Path(__file__).with_name("anteprima.html")))
    pg.wait_for_timeout(300)
    pg.screenshot(path=f"{V}/scatti/anteprima-social.png")
    b.close()
print("fatto")
