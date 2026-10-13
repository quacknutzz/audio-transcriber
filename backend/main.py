import os
import gc
import json
import time
import shutil
import logging
from pathlib import Path

import torch
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from services.separation import SeparationService
from services.transcription import TranscriptionService
from services.music_processing import MusicProcessingService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ghostnote")

app = FastAPI(title="GhostNote Local API")

# CORS for local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "processed"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "stems").mkdir(exist_ok=True)
(OUTPUT_DIR / "midi").mkdir(exist_ok=True)
(OUTPUT_DIR / "xml").mkdir(exist_ok=True)

STATE_FILE = OUTPUT_DIR / "state.json"

separation_service = SeparationService(OUTPUT_DIR / "stems")
transcription_service = TranscriptionService(OUTPUT_DIR / "midi")
music_processing_service = MusicProcessingService(OUTPUT_DIR / "xml")

# In-memory status tracker
job_status = {}

# Mount static folders so Next.js / Electron can stream audio stems & read sheet music XML
app.mount("/xml", StaticFiles(directory=str(OUTPUT_DIR / "xml")), name="xml")
app.mount("/stems", StaticFiles(directory=str(OUTPUT_DIR / "stems")), name="stems")

def save_state():
    """Snapshots completed jobs to state.json so history survives app restarts."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(job_status, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state.json: {e}")

@app.on_event("startup")
def load_existing_jobs():
    """Restores previous completed jobs on app launch."""
    global job_status
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                completed = {k: v for k, v in saved.items() if v.get("status") == "completed"}
                job_status.update(completed)
            logger.info(f"Restored {len(completed)} completed transcription jobs from history.")
        except Exception as e:
            logger.error(f"Failed to read state.json: {e}")

def is_silent(audio_path: Path, threshold: float = 0.005) -> bool:
    """Checks whether an isolated stem is silent to avoid wasting compute."""
    try:
        import soundfile as sf
        import numpy as np
        data, _ = sf.read(str(audio_path))
        peak = float(np.max(np.abs(data)))
        return peak < threshold
    except Exception:
        return False

def free_gpu_memory():
    """Purges PyTorch CUDA cache and collects Python garbage."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

async def process_audio_task(file_path: Path, filename: str):
    """
    100% local, VRAM-safe sequential pipeline:
    1. Demucs 6-stem separation (subprocess isolation guarantees full VRAM release)
    2. Silence check
    3. Specialized sequential transcription (Piano -> Vocals -> Bass -> Guitar/Other -> Drums)
    4. Music21 notation quantization and MusicXML export
    5. Local state persistence
    """
    start_time = time.time()
    project_name = file_path.stem
    logger.info(f"Starting local processing pipeline for: {filename}")
    
    try:
        # 1. Stem Separation
        job_status[filename] = {
            "status": "processing",
            "progress": 10,
            "message": "Separating stems with Demucs (Vocals, Drums, Bass, Guitar, Piano, Other)..."
        }
        
        stems = await separation_service.separate_audio(file_path)
        free_gpu_memory()
        
        if not stems:
            raise RuntimeError("Demucs failed to isolate any stems.")

        # 2. Identify active (non-silent) stems
        active_stems = {}
        for inst, p in stems.items():
            if not is_silent(p):
                active_stems[inst] = p
            else:
                logger.info(f"Stem '{inst}' is silent, skipping transcription.")

        # Stems to transcribe into sheet music
        transcribe_order = ["piano", "vocals", "bass", "guitar", "other"]
        pending_instruments = [inst for inst in transcribe_order if inst in active_stems]
        
        results_urls = {}
        stems_urls = {}
        
        # Populate stem audio URLs for audio playback in the UI
        for inst, p in stems.items():
            try:
                rel = Path(p).relative_to(OUTPUT_DIR / "stems")
                stems_urls[inst] = f"/stems/{rel.as_posix()}"
            except Exception:
                pass

        total_inst = len(pending_instruments)
        
        # 3. Sequential transcription (Strictly one instrument at a time to stay under 3GB VRAM)
        for idx, inst in enumerate(pending_instruments):
            progress_val = int(25 + ((idx / max(total_inst, 1)) * 65))
            job_status[filename] = {
                "status": "processing",
                "progress": progress_val,
                "message": f"Transcribing {inst.capitalize()} ({idx + 1}/{total_inst})..."
            }
            logger.info(f"Transcribing stem: {inst}")
            
            stem_audio_path = active_stems[inst]
            output_name = f"{project_name}_{inst}"
            
            # Specialized transcription
            midi_path = await transcription_service.transcribe_instrument(
                stem_audio_path, output_name, instrument_name=inst
            )
            free_gpu_memory()
            
            # MusicXML conversion
            if midi_path and midi_path.exists():
                try:
                    xml_path = music_processing_service.midi_to_xml(
                        midi_path, output_name, audio_ref_path=file_path
                    )
                    results_urls[inst] = f"/xml/{xml_path.name}"
                    logger.info(f"Successfully generated sheet music for {inst}: {xml_path.name}")
                except Exception as xml_err:
                    logger.error(f"MusicXML generation failed for {inst}: {xml_err}")

        # Drums: Include audio stem for playback. (If drum notation was desired, unpitched transcription can be enabled)
        if "drums" in stems and "drums" not in stems_urls:
            try:
                rel = Path(stems["drums"]).relative_to(OUTPUT_DIR / "stems")
                stems_urls["drums"] = f"/stems/{rel.as_posix()}"
            except Exception:
                pass

        elapsed = time.time() - start_time
        m, s = divmod(int(elapsed), 60)
        time_str = f"{m}m {s}s" if m > 0 else f"{s}s"

        job_status[filename] = {
            "status": "completed",
            "progress": 100,
            "message": f"Transcription completed in {time_str}!",
            "results": results_urls,
            "stems": stems_urls
        }
        save_state()
        logger.info(f"Completed job {filename} in {time_str}. {len(results_urls)} scores created.")

    except Exception as e:
        logger.error(f"Processing failed for {filename}: {e}", exc_info=True)
        job_status[filename] = {
            "status": "error",
            "progress": 0,
            "message": str(e)
        }

@app.get("/")
def read_root():
    gpu_info = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU Mode"
    return {
        "status": "online",
        "service": "GhostNote Local AI API",
        "hardware": gpu_info
    }

@app.post("/upload")
async def upload_audio(file: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")

        filename = file.filename
        file_path = UPLOAD_DIR / filename
        
        # Save raw audio locally
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
            
        logger.info(f"Received upload: {filename} ({len(contents)} bytes)")

        # Initial tracking state
        job_status[filename] = {
            "status": "processing",
            "progress": 5,
            "message": "Audio loaded. Starting local pipeline..."
        }

        # Dispatch background processing task on the local machine
        background_tasks.add_task(process_audio_task, file_path, filename)

        return {"filename": filename, "message": "Uploaded successfully. Processing locally in background."}

    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/active")
async def get_active_job():
    """Returns any currently processing task so the UI reconnects on page refresh."""
    for filename, data in job_status.items():
        if data.get("status") == "processing":
            return {"filename": filename, **data}
    return None

@app.get("/status/{filename}")
async def get_status(filename: str):
    status = job_status.get(filename)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status

@app.get("/history")
async def get_history():
    """Returns all historical completed songs for the side panel."""
    history = []
    for filename, status_data in job_status.items():
        if status_data.get("status") == "completed":
            history.append({
                "filename": filename,
                "results": status_data.get("results", {}),
                "stems": status_data.get("stems", {}),
                "message": status_data.get("message", "")
            })
    return history

@app.delete("/history/{filename}")
async def delete_history_item(filename: str):
    """Deletes the job from history and purges generated stems and sheet music from disk."""
    project_name = Path(filename).stem
    
    if filename in job_status:
        del job_status[filename]
        
    # Also remove any keys sharing the same project stem
    for k in list(job_status.keys()):
        if Path(k).stem == project_name:
            del job_status[k]

    # Delete original upload
    orig_file = UPLOAD_DIR / filename
    if orig_file.exists():
        orig_file.unlink(missing_ok=True)

    # Delete XMLs and MIDIs
    for folder, ext in [("xml", ".musicxml"), ("midi", ".mid")]:
        for f in (OUTPUT_DIR / folder).glob(f"{project_name}_*{ext}"):
            f.unlink(missing_ok=True)

    # Delete stem folder
    stem_dir = OUTPUT_DIR / "stems" / project_name
    if stem_dir.exists():
        shutil.rmtree(stem_dir, ignore_errors=True)

    save_state()
    return {"status": "success", "message": f"Deleted {filename} and all generated assets."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
