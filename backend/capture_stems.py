from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.goto("http://127.0.0.1:3000", wait_until="networkidle")
    page.wait_for_timeout(2500)

    # 1. Taylor Swift - Love Story
    ts_btn = page.locator("button:has-text('Taylor Swift - Love Story')")
    if ts_btn.count() > 0:
        ts_btn.first.click()
        page.wait_for_timeout(2000)

    for inst in ["vocals", "guitar", "bass", "other", "drums"]:
        card = page.locator("div.rounded-xl").filter(has=page.locator(f"h3:text-is('{inst}')")).first
        if card.count() > 0:
            btn = card.locator("button:has-text('View Score'), button:has-text('Viewing')")
            if btn.count() > 0:
                btn.first.click()
            else:
                card.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=f"taylor_swift_{inst}_new_score.png", full_page=True)
            # Also capture a focused screenshot of the top portion of the score
            page.screenshot(path=f"taylor_swift_{inst}_crop.png", clip={"x": 280, "y": 420, "width": 1120, "height": 950})
            print(f"Captured Taylor Swift {inst} score successfully")

    # 2. introoooo - drop
    id_btn = page.locator("button:has-text('introoooo - drop')")
    if id_btn.count() > 0:
        id_btn.first.click()
        page.wait_for_timeout(2000)
        for inst in ["bass", "guitar"]:
            card = page.locator("div.rounded-xl").filter(has=page.locator(f"h3:text-is('{inst}')")).first
            if card.count() > 0:
                btn = card.locator("button:has-text('View Score'), button:has-text('Viewing')")
                if btn.count() > 0:
                    btn.first.click()
                else:
                    card.click()
                page.wait_for_timeout(2500)
                page.screenshot(path=f"intro_drop_{inst}_score.png", clip={"x": 280, "y": 420, "width": 1120, "height": 900})
                print(f"Captured introoooo - drop {inst} score successfully")

    browser.close()
