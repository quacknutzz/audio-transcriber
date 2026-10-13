# 🎵 GhostNote (Audio Transcriber)

An advanced, end-to-end desktop application that converts complex polyphonic audio files (MP3/WAV/FLAC) directly into playable, editable sheet music and MIDI tracks. Built to tackle the difficult challenge of polyphonic music transcription with a sleek, modern desktop interface. 100% offline and runs locally on your GPU.

## 🚀 Overview

GhostNote processes audio through a cascading **Separate $\to$ Transcribe** pipeline:
1. **Separates** the audio mixture into 6 distinct instrument stems (Vocals, Drums, Bass, Guitar, Piano, Other) using Meta's **HTDemucs 6s**.
2. **Transcribes** each isolated stem using domain-specific AI models:
   * **Piano / Keys:** ByteDance's CRNN model trained on the MAESTRO dataset (~96.7% note F1 accuracy with sustain pedal awareness).
   * **Vocals:** Spotify's Basic Pitch tuned with high onset sensitivity and vocal note duration filtering.
   * **Bass:** Basic Pitch constrained to bass fundamental frequencies (40 Hz – 400 Hz) to eliminate drum bleed.
   * **Guitar & Other:** Basic Pitch polyphonic ONNX model for clean chord and riff transcription.
   * **Drums:** Transient onset detection mapped to standard General MIDI percussion events (Kick / Snare / Hi-Hat).
3. **Quantizes & Converts** the notation into standard `.musicxml` and `.mid` formats via `music21`.
4. **Visualizes** the resulting sheet music natively using `OpenSheetMusicDisplay`, alongside multi-track audio stem players for instant listening and comparison.

## 🛠️ Architecture

* **Desktop Shell:** [Electron](https://www.electronjs.org/) manages the application window and automatically orchestrates background backend/frontend processes.
* **Frontend:** [Next.js](https://nextjs.org/) (React 19) + Tailwind CSS v4 with glassmorphism UI, real-time stage progress polling, and an interactive History drawer.
* **Backend:** [FastAPI](https://fastapi.tiangolo.com/) (Python) running a VRAM-safe, sequential GPU pipeline (<3.5GB peak VRAM footprint, ideal for 6GB GPUs like the NVIDIA RTX 4050).
* **State Persistence:** Local `state.json` caches completed songs and generated assets so past scores are instantly available across restarts.

## 💻 Quick Start

### 1. Launch the Desktop App
Double-click [`start_app.bat`](./start_app.bat) or run:
```bash
start_app.bat
```
This automatically cleans any stale processes on ports 3000 and 8000, starts the FastAPI server and Next.js dev server, and launches the Electron window.

### 2. Manual Start (Optional)
**Backend:**
```bash
cd backend
venv\Scripts\activate
uvicorn main:app --host 127.0.0.1 --port 8000
```

**Frontend:**
```bash
cd frontend
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.
