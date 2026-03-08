# 🎵 Audio Transcriber

An advanced, end-to-end desktop application that converts complex polyphonic audio files (MP3/WAV) directly into playable, editable sheet music and MIDI tracks. Built to tackle the difficult challenge of polyphonic music transcription with an incredibly sleek, modern interface.

## 🚀 Overview

This project automatically processes an uploaded audio file and passes it through an AI pipeline that:
1. **Separates** the audio into distinct instrument stems (Vocals, Drums, Bass, Other/Piano).
2. **Transcribes** those individual stems into musical notes.
3. **Quantizes & Converts** the notation into standard `.musicxml` and `.mid` formats.
4. **Visualizes** the resulting sheet music directly within the application, alongside an interactive audio player.

## 🛠️ Tech Stack & Architecture

This application uses a loosely coupled, modern full-stack architecture packaged as a desktop app:

*   **Frontend (UI):** [Next.js](https://nextjs.org/) (React) + Tailwind CSS v4. Features a stunning, premium "glassmorphism" aesthetic with dynamic gradients and real-time progress polling. Uses `OpenSheetMusicDisplay` to natively render MusicXML files in the browser.
*   **Backend (API & Processing):** [FastAPI](https://fastapi.tiangolo.com/) (Python). Manages the REST API layer, asynchronous task execution, and file I/O operations safely without locking the UI.
*   **Desktop Wrapper:** [Electron](https://www.electronjs.org/). Acts as the host shell. A custom launcher script automatically spawns and manages the lifecycles of both the Python backend and Next.js frontend, creating a seamless "double-click" desktop experience for the user.
*   **AI Models:** 
    *   **Demucs (by Meta):** State-of-the-art model used for high-fidelity source separation (isolating the instruments).
    *   **MT3 (by Google):** Multi-Task Multitrack Music Transcription for high-quality polyphonic transcription.
    *   **Basic Pitch (by Spotify):** Used as a highly accurate, lightweight fallback for monophonic or specific instrument stems (like Bass/Vocals).
    *   **Music21:** A powerful Python toolkit used to assemble the detected notes, parse time signatures, quantize the rhythm, and export the final musical score.

---

## 🔮 Future Improvements: Custom Transcription Model

While the current pipeline leverages powerful open-source AI, transcription of highly complex, layered audio is notoriously difficult. 

The ultimate goal for this project is to replace the generic pre-trained inference models (MT3 / Basic Pitch) with a **custom-built, intensively trained Neural Network specifically tailored for "near-perfect" accuracy.** 

To achieve professional, production-standard transcription, this custom model would feature:
*   **Intensive Supervised Training:** Trained on an aggressively curated, massive dataset of perfectly paired `.wav` multitracks and their exact, human-verified `.musicxml` sheets. 
*   **Advanced Architecture:** Likely utilizing a massive Transformer-based (or hybrid CNN-Transformer) architecture that takes in multi-resolution spectrograms and outputs tokenized musical events.
*   **Nuanced Expression:** Designed to understand and predict micro-timing, velocity (dynamics), and complex chord voicings far better than zero-shot general models.
*   **Compute-Heavy Training:** This training pipeline would require intensive, prolonged GPU cluster training, focusing specifically on minimizing the error rate in rhythmic quantization and polyphonic overlap, leading to a transcription that requires zero manual editing.
