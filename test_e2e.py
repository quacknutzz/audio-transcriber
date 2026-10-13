import time
import requests
import sys

# The exact file the user mentioned
file_path = r"C:\Users\rishi\Downloads\Taylor Swift - Love Story.mp3"
filename = "Taylor Swift - Love Story.mp3"

print(f"[{time.strftime('%X')}] POST /upload starting...")
with open(file_path, "rb") as f:
    files = {"file": (filename, f, "audio/mpeg")}
    try:
        res = requests.post("http://127.0.0.1:8000/upload", files=files, timeout=60)
        print(f"[{time.strftime('%X')}] Upload Response: {res.json()}")
    except Exception as e:
        print(f"[{time.strftime('%X')}] Failed to upload: {e}")
        sys.exit(1)

print(f"[{time.strftime('%X')}] Polling /status...")
start_time = time.time()
while True:
    time.sleep(10)
    try:
        res = requests.get(f"http://127.0.0.1:8000/status/{filename}", timeout=10)
        data = res.json()
        status = data.get("status")
        prog = data.get("progress")
        msg = data.get("message")
        
        elapsed = int(time.time() - start_time)
        print(f"[{elapsed}s] {status} ({prog}%): {msg}")
        
        if status in ["completed", "error"]:
            print(f"\nFinal output:\n{data}")
            break
    except Exception as e:
        print(f"Polling error: {e}")
