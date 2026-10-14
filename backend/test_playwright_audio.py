from playwright.sync_api import sync_playwright
import time
import json

def test_audio():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        
        console_msgs = []
        page.on('console', lambda msg: console_msgs.append(f"[{msg.type}] {msg.text}"))
        
        print("Navigating to http://127.0.0.1:3000...")
        page.goto('http://127.0.0.1:3000', wait_until='networkidle')
        page.wait_for_timeout(2000)
        
        # Check all audio elements
        audios = page.locator('audio').all()
        print(f"Total audio elements on page: {len(audios)}")
        assert len(audios) >= 6, f"Expected at least 6 audio elements, got {len(audios)}"
        
        for i, a in enumerate(audios):
            src = a.get_attribute('src')
            ready = a.evaluate("el => el.readyState")
            dur = a.evaluate("el => el.duration")
            has_controls = a.get_attribute('controls') is not None
            print(f"  Audio[{i}]: src={src.split('/')[-1]}, readyState={ready}, duration={dur:.2f}s, controls={has_controls}")
            
        # Test playing the 'other' stem (starts at 0.0s)
        other_audio = page.locator('audio[src*="other.wav"]')
        assert other_audio.count() > 0, "Could not find 'other.wav' audio element"
        
        print("\nTesting playback of 'other.wav'...")
        other_audio.evaluate("el => { el.currentTime = 1.0; el.play(); }")
        page.wait_for_timeout(1500)
        
        other_state = other_audio.evaluate("""el => ({
            paused: el.paused,
            currentTime: el.currentTime,
            duration: el.duration,
            volume: el.volume
        })""")
        print("  'other.wav' state:", json.dumps(other_state, indent=2))
        assert not other_state["paused"], "Audio should be actively playing!"
        assert other_state["currentTime"] > 1.0, "Playhead should have advanced past 1.0s!"
        
        # Test seeking vocals past the silent intro (e.g. to 17.0s)
        vocals_audio = page.locator('audio[src*="vocals.wav"]').first
        print("\nTesting seeking and playback of 'vocals.wav' at 17.0s...")
        vocals_audio.evaluate("el => { el.currentTime = 17.0; el.play(); }")
        page.wait_for_timeout(1500)
        
        vocals_state = vocals_audio.evaluate("""el => ({
            paused: el.paused,
            currentTime: el.currentTime,
            duration: el.duration
        })""")
        print("  'vocals.wav' state:", json.dumps(vocals_state, indent=2))
        assert not vocals_state["paused"], "Vocals audio should be playing!"
        assert vocals_state["currentTime"] >= 17.0, "Vocals playhead should be at or past 17.0s!"
        
        # Check sheet music rendering
        print("\nChecking sheet music notation rendering...")
        svgs = page.locator('.bg-white svg').all()
        print(f"Total sheet music SVG elements rendered: {len(svgs)}")
        assert len(svgs) > 0, "Expected sheet music SVG to be rendered by OSMD"
        
        # Take verification screenshot
        page.screenshot(path="homepage_playback_verified.png")
        print("\nScreenshot saved to homepage_playback_verified.png")
        
        browser.close()
        print("\nAll Playwright UI playback tests PASSED successfully!")

if __name__ == '__main__':
    test_audio()
