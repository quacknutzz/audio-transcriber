from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1366, "height": 968})
    page.goto("http://127.0.0.1:3000", wait_until="networkidle")
    page.wait_for_timeout(2000)

    # Make sure Taylor Swift is selected
    ts_btn = page.locator("button:has-text('Taylor Swift - Love Story')")
    if ts_btn.count() > 0:
        ts_btn.first.click()
        page.wait_for_timeout(2000)

    for inst in ["vocals", "guitar", "bass", "other"]:
        card = page.locator("div.rounded-xl").filter(has=page.locator(f"h3:text-is('{inst}')")).first
        if card.count() > 0:
            btn = card.locator("button:has-text('View Score'), button:has-text('Viewing')")
            if btn.count() > 0:
                btn.first.click()
            else:
                card.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=f"taylor_swift_{inst}_new_score.png", full_page=True)
            print(f"Captured {inst} new score successfully")
        else:
            print(f"Could not find card for {inst}")

    browser.close()
