from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1366, "height": 968})
    page.goto("http://127.0.0.1:3000", wait_until="networkidle")
    page.wait_for_timeout(2000)

    # Click the other card directly by looking for the Other h3
    cards = page.locator("div.grid > div").all()
    print("Found cards:", len(cards))
    for card in cards:
        text = card.inner_text()
        print("Card text:", text.encode("ascii", "replace").decode("ascii").replace("\n", " | "))
        if "other" in text.lower():
            print("Clicking other card...")
            btn = card.locator("button:has-text('View Score')")
            if btn.count() > 0:
                btn.click()
            else:
                card.click()
            page.wait_for_timeout(3000)
            page.screenshot(path="taylor_swift_other_direct.png", full_page=True)
            print("Saved taylor_swift_other_direct.png")
            break

    browser.close()
