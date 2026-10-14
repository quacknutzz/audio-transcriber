import time
import json
import urllib.request
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

API_BASE = "http://127.0.0.1:8000"
FRONTEND_BASE = "http://127.0.0.1:3000"
TEST_AUDIO = Path("backend/test_pipeline_sample.wav")

def upload_and_process():
    print(f"--- [Step 1] Uploading {TEST_AUDIO.name} to {API_BASE}/upload ---")
    
    # Read audio bytes
    with open(TEST_AUDIO, "rb") as f:
        file_bytes = f.read()
        
    boundary = "----WebKitFormBoundaryE2ETestPipeline"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{TEST_AUDIO.name}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{API_BASE}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )
    
    with urllib.request.urlopen(req) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))
        print("Upload response:", resp_data)
        filename = resp_data["filename"]
        
    print(f"\n--- [Step 2] Polling status for {filename} ---")
    start_t = time.time()
    while True:
        status_url = f"{API_BASE}/status/{urllib.parse.quote(filename)}"
        with urllib.request.urlopen(status_url) as s_resp:
            s_data = json.loads(s_resp.read().decode("utf-8"))
            status = s_data.get("status")
            progress = s_data.get("progress", 0)
            msg = s_data.get("message", "")
            print(f"  [{int(time.time() - start_t)}s] Status: {status} ({progress}%) - {msg}")
            
            if status == "completed":
                print("\nProcessing completed successfully!")
                print("Results:", json.dumps(s_data.get("results"), indent=2))
                print("Stems:", json.dumps(s_data.get("stems"), indent=2))
                return s_data
            elif status == "error":
                raise RuntimeError(f"Processing failed with error: {msg}")
                
        time.sleep(3.0)

def verify_files(results_data):
    print("\n--- [Step 3] Verifying generated XML and Stem files on disk ---")
    processed_dir = Path("backend/processed")
    
    # Verify XML files
    for inst, xml_rel in results_data.get("results", {}).items():
        xml_file = processed_dir / xml_rel.lstrip("/")
        assert xml_file.exists(), f"XML file missing: {xml_file}"
        assert xml_file.stat().st_size > 500, f"XML file too small: {xml_file}"
        xml_text = xml_file.read_text(encoding="utf-8")
        assert "Music21 Fragment" not in xml_text, f"Found 'Music21 Fragment' in {xml_file}"
        print(f"  [OK] {inst} sheet music: {xml_file.name} ({xml_file.stat().st_size} bytes)")
        
    # Verify Stems files
    for inst, stem_rel in results_data.get("stems", {}).items():
        stem_file = processed_dir / stem_rel.lstrip("/")
        assert stem_file.exists(), f"Stem audio file missing: {stem_file}"
        assert stem_file.stat().st_size > 1000, f"Stem file too small: {stem_file}"
        print(f"  [OK] {inst} audio stem: {stem_file.name} ({stem_file.stat().st_size} bytes)")

def test_ui_in_browser(filename):
    print("\n--- [Step 4] Automated Browser Playback & Rendering Verification ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 968})
        
        errors = []
        page.on("pageerror", lambda err: errors.append(f"PageError: {err}"))
        page.on("console", lambda msg: errors.append(f"ConsoleError: {msg.text}") if msg.type == "error" else None)
        
        print(f"Navigating to {FRONTEND_BASE}...")
        page.goto(FRONTEND_BASE, wait_until="networkidle")
        page.wait_for_timeout(2500)
        
        # Verify page error is empty
        assert not errors, f"Browser encountered errors on load: {errors}"
        
        # Click the project button if not already active
        stem_name = Path(filename).stem
        proj_btn = page.locator(f"button:has-text('{stem_name}')")
        if proj_btn.count() > 0:
            print(f"Selecting project button for '{stem_name}'...")
            proj_btn.first.click()
            page.wait_for_timeout(2000)
            
        # Verify stem audio elements
        audios = page.locator("audio").all()
        print(f"Found {len(audios)} audio players on homepage.")
        assert len(audios) >= 4, f"Expected at least 4 stem audio players, got {len(audios)}"
        
        for idx, a in enumerate(audios):
            src = a.get_attribute("src")
            ready = a.evaluate("el => el.readyState")
            dur = a.evaluate("el => el.duration")
            has_controls = a.get_attribute("controls") is not None
            print(f"  Track player [{idx}]: src={src.split('/')[-1]}, duration={dur:.2f}s, readyState={ready}, controls={has_controls}")
            assert has_controls, "Audio player must have native HTML5 controls enabled!"
            assert ready == 4, f"Audio player {src} failed to load metadata/audio (readyState={ready})"
            assert dur > 0, f"Audio player {src} reported 0s duration!"
            
        # Test playing the first stem player
        first_audio = page.locator("audio").first
        print("\nTesting playback of stem audio player 0...")
        first_audio.evaluate("el => { el.currentTime = 0.5; el.play(); }")
        page.wait_for_timeout(1500)
        
        state = first_audio.evaluate("""el => ({
            paused: el.paused,
            currentTime: el.currentTime,
            duration: el.duration
        })""")
        print("  Playback state after 1.5s:", json.dumps(state, indent=2))
        assert not state["paused"], "Audio player should be actively playing!"
        assert state["currentTime"] >= 0.5, "Playhead should be advancing!"
        
        # Verify sheet music notation rendered by OSMD
        print("\nVerifying sheet music notation display...")
        svg_score = page.locator(".bg-white svg")
        assert svg_score.count() > 0, "No sheet music SVG found on page!"
        print(f"  [OK] Sheet music SVG rendered with {svg_score.count()} SVG element(s)!")
        
        # Check that 'Music21 Fragment' is nowhere in the page body
        body_text = page.locator("body").inner_text()
        assert "Music21 Fragment" not in body_text, "Found unwanted 'Music21 Fragment' on page!"
        assert "100% offline AI" not in body_text, "Found unwanted AI badge on page!"
        
        # Take full page screenshot
        page.screenshot(path="e2e_verified_screenshot.png", full_page=True)
        print("\nFull page screenshot saved to e2e_verified_screenshot.png!")
        
        browser.close()
        print("\n>>> ALL END-TO-END CRITERIA MET AND VERIFIED! <<<")

if __name__ == "__main__":
    result = upload_and_process()
    verify_files(result)
    test_ui_in_browser(TEST_AUDIO.name)
