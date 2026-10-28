"""Capture the real field app, shielded mode, against the mock zanchor.

Needs: apps/field served on :8803, mock_zanchor on :8801, explorer on :8802.
Writes assets/field-*.png at 1440x900 @2x.
"""

from playwright.sync_api import sync_playwright

URL = (
    "http://127.0.0.1:8803/index.html?anchor=shielded"
    "&zanchor=http://127.0.0.1:8801&explorer=http://127.0.0.1:8802"
    "&minDelay=0&jitter=0&ledgerLabel=MOCK%20ZANCHOR%20DEMO"
)

with sync_playwright() as p:
    b = p.chromium.launch(
        executable_path="/Users/udingethe/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    )
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    page.goto(URL)
    page.add_style_tag(content="#toast{display:none!important}")
    page.wait_for_timeout(800)
    page.screenshot(path="assets/field-00-empty.png")
    page.click('[data-act="seed"]')
    page.wait_for_timeout(1500)
    page.screenshot(path="assets/field-01-seeded.png", full_page=True)
    print("html after seed:", len(page.content()))
    print(
        page.evaluate(
            "document.querySelector('#journal-h').closest('section,div,article').outerHTML.slice(0,300)"
        )
    )

    def shot(n):
        page.screenshot(path=f"assets/field-{n}.png", full_page=True)
        for key, hid in (("outbox", "outbox-h"), ("journal", "journal-h")):
            page.locator(f"#{hid}").locator("xpath=../..").screenshot(
                path=f"assets/el-{n}-{key}.png"
            )

    page.click("text=Demo: tamper with a queued copy")
    page.wait_for_timeout(500)
    shot("02-tamper-open")
    page.click("#tamper")
    page.wait_for_timeout(900)
    shot("03-tampered")
    page.click("#sync")
    page.wait_for_timeout(1500)
    shot("04-refused")
    page.click('[data-act="restore"]')
    page.wait_for_timeout(900)
    shot("05-restored")
    page.click("#sync")
    page.wait_for_timeout(4000)
    shot("06-synced")
    page.wait_for_timeout(15000)
    shot("07-settled")
    b.close()
