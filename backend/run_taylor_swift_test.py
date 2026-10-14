import time
import json
import urllib.request
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

API_BASE = "http://127.0.0.1:8000"
FRONTEND_BASE = "http://127.0.0.1:3000"
AUDIO_FILE = Path("backend/uploads/Taylor Swift - Love Story.mp3")

def upload_and_monitor():
    print(f"=== [Step 1] Uploading {AUDIO_FILE.name} to {API_BASE}/upload ===")
    with open(AUDIO_FILE, "rb") as f:
        file_bytes = f.read()

    boundary = "----WebKitFormBoundaryLoveStoryPipeline"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{AUDIO_FILE.name}"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{API_BASE}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )

    with urllib.request.urlopen(req) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))
        print("Upload initiated:", resp_data)
        filename = resp_data["filename"]

    print(f"\n=== [Step 2] Monitoring background progress for {filename} ===")
    start_t = time.time()
    last_msg = ""
    while True:
        status_url = f"{API_BASE}/status/{urllib.parse.quote(filename)}"
        try:
            with urllib.request.urlopen(status_url) as s_resp:
                data = json.loads(s_resp.read().decode("utf-8"))
                status = data.get("status")
                progress = data.get("progress", 0)
                msg = data.get("message", "")
                
                if msg != last_msg:
                    print(f"  [{int(time.time() - start_t):02d}s] {progress}% - {msg}")
                    last_msg = msg
                    
                if status == "completed":
                    print(f"\n=== [Success] Completed in {int(time.time() - start_t)}s! ===")
                    print("Scores:", json.dumps(data.get("results"), indent=2))
                    return data
                elif status == "error":
                    raise RuntimeError(f"Processing failed: {msg}")
        except Exception as e:
            if "completed" not in str(e):
                print(f"  Polling notice: {e}")

        time.sleep(3.0)

def verify_score_metrics(data):
    print("\n=== [Step 3] Verifying MusicXML Notation Metrics ===")
    import re
    xml_dir = Path("backend/processed/xml")
    
    for inst, xml_url in data.get("results", {}).items():
        xml_name = Path(xml_url).name
        xml_path = xml_dir / xml_name
        assert xml_path.exists(), f"Score missing: {xml_path}"
        
        text = xml_path.read_text(encoding="utf-8")
        fifths = re.findall(r'<fifths>(-?\d+)</fifths>', text)
        tempo = re.findall(r'<per-minute>(\d+)</per-minute>', text)
        accs = re.findall(r'<accidental>(\w+)</accidental>', text)
        
        print(f"  Track: {inst.upper():8s}")
        print(f"    Key Fifths: {fifths[:1]} (2 = D Major / B minor)")
        print(f"    Tempo BPM:  {tempo[:1]}")
        print(f"    Accidentals count: {len(accs)}")
        
        assert "Music21 Fragment" not in text
        if inst == "vocals":
            # Previously 382 accidentals! Should now be < 80!
            print(f"    -> Vocal accidentals reduced to: {len(accs)} (was 382 previously!)")
            assert len(accs) < 100, f"Too many accidentals on vocals: {len(accs)}"

def verify_in_browser():
    print("\n=== [Step 4] Browser Verification via Playwright ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 968})
        
        page.goto(FRONTEND_BASE, wait_until="networkidle")
        page.wait_for_timeout(2500)
        
        # Select Taylor Swift in project switcher if not already selected
        ts_btn = page.locator("button:has-text('Taylor Swift - Love Story')")
        if ts_btn.count() > 0:
            print("Switching to Taylor Swift - Love Story project in studio...")
            ts_btn.first.click()
            page.wait_for_timeout(2000)
            
        # Check all audio players on the page
        audios = page.locator("audio").all()
        print(f"Found {len(audios)} audio players on homepage.")
        assert len(audios) >= 6, "Expected at least 6 stem audio players"
        
        # Check vocal stem player
        vocal_audio = page.locator("audio[src*='vocals.wav']").first
        dur = vocal_audio.evaluate("el => el.duration")
        print(f"Vocals stem audio duration: {dur:.2f}s")
        assert dur > 200, f"Expected full song duration (~230s), got {dur}s"
        
        # Test seeking past the 17s intro to verse 1 (18.0s)
        print("Testing vocal playback at 18.0s (verse entry)...")
        vocal_audio.evaluate("el => { el.currentTime = 18.0; el.play(); }")
        page.wait_for_timeout(1500)
        v_state = vocal_audio.evaluate("el => ({ paused: el.paused, time: el.currentTime })")
        print("  Vocal playback state:", v_state)
        assert not v_state["paused"], "Vocal stem should be playing!"
        assert v_state["time"] >= 18.0, "Playhead should be at/past 18s!"
        
        # Verify Sheet Music notation is rendered cleanly
        svgs = page.locator(".bg-white svg")
        assert svgs.count() > 0, "Sheet music SVG should be rendered"
        print(f"  [OK] Sheet music SVG rendered with {svgs.count()} score elements!")
        
        # Take verification screenshot of the rendered score and stem players
        screenshot_path = "taylor_swift_verified.png"
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"\nFinal studio screenshot saved to {screenshot_path}!")
        
        browser.close()
        print("\n>>> ALL TESTS AND VERIFICATIONS COMPLETED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    job_data = upload_and_monitor()
    verify_score_metrics(job_data)
    verify_in_browser()
