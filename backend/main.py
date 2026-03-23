from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
import asyncio
from pathlib import Path
from services.separation import SeparationService
from services.transcription import TranscriptionService
from services.music_processing import MusicProcessingService

app = FastAPI()

# In-memory dictionary to track processing status
# Keys are filenames, values are dicts with 'status', 'progress', 'message', and 'results'
job_status = {}

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("processed")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

separation_service = SeparationService(OUTPUT_DIR / "stems")
transcription_service = TranscriptionService(OUTPUT_DIR / "midi")
music_processing_service = MusicProcessingService(OUTPUT_DIR / "xml")

# Mount the XML directory statically so the frontend can read the generated files
app.mount("/xml", StaticFiles(directory=str(OUTPUT_DIR / "xml")), name="xml")
app.mount("/stems", StaticFiles(directory=str(OUTPUT_DIR / "stems")), name="stems")

@app.get("/")
def read_root():
    return {"message": "Audio Transcriber API is running"}

@app.on_event("startup")
def load_existing_jobs():
    """
    On server boot, scan the processed directory and populate job_status
    so the UI can still display results for past transcribed files.
    """
    if not (OUTPUT_DIR / "xml").exists():
        return
        
    # Group found XML files by their original filename root (e.g., test_audio_piano.musicxml -> test_audio)
    recovered_jobs = {}
    for xml_file in (OUTPUT_DIR / "xml").glob("*.musicxml"):
        # Files are named like: projectname_instrument.musicxml
        # We need to extract 'projectname'
        parts = xml_file.stem.rsplit("_", 1)
        if len(parts) == 2:
            project_name, instrument = parts
            
            # Use a single virtual extension to avoid duplicating history items
            virtual_filename = project_name + ".mp3"
            if virtual_filename not in recovered_jobs:
                recovered_jobs[virtual_filename] = {}
            recovered_jobs[virtual_filename][instrument] = f"/xml/{xml_file.name}"
          
    for virt_filename, results in recovered_jobs.items():
        # Try to recover stem audio URLs too
        stems_urls = {}
        for instrument in results.keys():
            parts = list((OUTPUT_DIR / "stems").glob(f"**/htdemucs_6s/**/{instrument}.wav"))
            if parts:
                rel_path = parts[0].relative_to(OUTPUT_DIR / "stems")
                stems_urls[instrument] = f"/stems/{rel_path.as_posix()}"
                
        job_status[virt_filename] = {
            "status": "completed", 
            "progress": 100, 
            "message": "Loaded from history.",
            "results": results,
            "stems": stems_urls
        }
    print(f"Loaded {len(recovered_jobs)} previous jobs into memory.")

def is_silent(audio_path: Path, threshold: float = 0.01) -> bool:
    """Check if an audio file is essentially silent by reading peak amplitude."""
    try:
        import soundfile as sf
        import numpy as np
        data, _ = sf.read(str(audio_path))
        peak = float(np.max(np.abs(data)))
        return peak < threshold
    except Exception:
        return False  # If we can't read it, assume it has content

async def process_audio_task(file_path: Path, filename: str):
    """
    Background task to handle the heavy lifting of separation and transcription.
    """
    import time
    start_time = time.time()
    
    try:
        job_status[filename] = {"status": "processing", "progress": 10, "message": "Separating stems..."}
        # 1. Separation
        print(f"Separating {filename}...")
        stems = await separation_service.separate_audio(file_path)
        print(f"Separation complete. Stems: {stems.keys()}")
        job_status[filename] = {"status": "processing", "progress": 50, "message": "Transcribing instruments..."}

        # 2. Transcription (with silence detection and smart routing)
        results = {}
        project_name = file_path.stem
        
        # ── Multiprocessing: dispatch MT3 stems to 2 parallel OS processes ──
        from concurrent.futures import ProcessPoolExecutor
        from services.mt3_worker import transcribe_stem
        import asyncio
        
        loop = asyncio.get_event_loop()
        midi_output_dir = OUTPUT_DIR / "midi"
        midi_output_dir.mkdir(parents=True, exist_ok=True)

        # Collect MT3 stems (non-vocals, non-silent)
        mt3_jobs = []  # (stem_key, instrument_name, stem_path, midi_output_path)
        vocal_job = None  # vocals go through Basic Pitch in the main process
        
        for stem_key, instrument_name in [("bass", "bass"), ("guitar", "guitar"), ("other", "other"), ("piano", "piano")]:
            if stem_key in stems:
                stem_path = stems[stem_key]
                if is_silent(stem_path):
                    print(f"Skipping {stem_key}: silent stem detected.")
                    continue
                midi_out = str(midi_output_dir / f"{project_name}_{stem_key}_mt3.mid")
                mt3_jobs.append((stem_key, instrument_name, str(stem_path), midi_out))
        
        # Handle keys->piano alias
        if "keys" in stems and "piano" not in stems:
            stem_path = stems["keys"]
            if not is_silent(stem_path):
                midi_out = str(midi_output_dir / f"{project_name}_keys_mt3.mid")
                mt3_jobs.append(("keys", "piano", str(stem_path), midi_out))
        
        # Check for vocals
        if "vocals" in stems and not is_silent(stems["vocals"]):
            vocal_job = ("vocals", "vocals")
        
        # Dispatch MT3 jobs to 2 parallel GPU worker processes
        print(f"Dispatching {len(mt3_jobs)} MT3 jobs to 2 parallel workers...")
        job_status[filename] = {"status": "processing", "progress": 55, "message": f"Transcribing {len(mt3_jobs)} instruments in parallel..."}
        
        mt3_futures = {}
        with ProcessPoolExecutor(max_workers=2) as pool:
            for stem_key, instrument_name, stem_path_str, midi_out_str in mt3_jobs:
                future = loop.run_in_executor(
                    pool,
                    transcribe_stem,
                    stem_path_str, midi_out_str, instrument_name
                )
                mt3_futures[stem_key] = (future, instrument_name)
            
            # While MT3 workers are crunching, run vocals through Basic Pitch in the main process
            if vocal_job:
                print("Transcribing vocals via Basic Pitch (main process)...")
                try:
                    midi_path = await transcription_service.transcribe_melody(
                        stems["vocals"], f"{project_name}_vocals", instrument_name="vocals"
                    )
                    xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_vocals", audio_ref_path=file_path)
                    results["vocals"] = xml_path
                except Exception as e:
                    print(f"Vocals transcription failed: {e}")
            
            # Await all MT3 worker results
            for stem_key, (future, instrument_name) in mt3_futures.items():
                try:
                    midi_path_str = await future
                    if midi_path_str:  # non-empty means success
                        midi_path = Path(midi_path_str)
                        xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_{stem_key}", audio_ref_path=file_path)
                        results[stem_key] = xml_path
                        print(f"✓ {stem_key} transcription complete.")
                    else:
                        # MT3 failed in the worker — fall back to Basic Pitch in main process
                        print(f"MT3 worker failed for {stem_key}, falling back to Basic Pitch...")
                        midi_path = await transcription_service._transcribe_basic_pitch(
                            stems[stem_key], f"{project_name}_{stem_key}", instrument_name
                        )
                        xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_{stem_key}", audio_ref_path=file_path)
                        results[stem_key] = xml_path
                except Exception as e:
                    print(f"Worker error for {stem_key}: {e}")
        
        print(f"All transcription complete. {len(results)} instruments processed.")

        # Drums: audio stem is served for playback, but NO sheet music is generated
            
        # Formulate web-accessible URLs
        results_urls = {}
        stems_urls = {}
        for instrument, local_path in results.items():
            # Convert system path to web XML URL
            xml_basename = Path(local_path).name
            results_urls[instrument] = f"/xml/{xml_basename}"
            
            # Formulate the expected stem URL if it exists
            if instrument in stems:
                try:
                    rel_path = Path(stems[instrument]).relative_to(OUTPUT_DIR / "stems")
                    stems_urls[instrument] = f"/stems/{rel_path.as_posix()}"
                except ValueError:
                    pass
        
        # Also serve drum audio for playback (no sheet music)
        if "drums" in stems and "drums" not in stems_urls:
            try:
                rel_path = Path(stems["drums"]).relative_to(OUTPUT_DIR / "stems")
                stems_urls["drums"] = f"/stems/{rel_path.as_posix()}"
            except ValueError:
                pass
            
        elapsed = time.time() - start_time
        m, s = divmod(int(elapsed), 60)
        time_str = f"{m}m {s}s" if m > 0 else f"{s}s"

        print(f"Processing complete for {filename}. Results: {results_urls}")
        job_status[filename] = {
            "status": "completed", 
            "progress": 100, 
            "message": f"Total process completed in {time_str}",
            "results": results_urls,
            "stems": stems_urls
        }
        
    except Exception as e:
        print(f"Error processing {filename}: {e}")
        job_status[filename] = {"status": "error", "progress": 0, "message": str(e)}

@app.post("/upload")
async def upload_audio(file: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")

        filename = file.filename
        file_path = UPLOAD_DIR / filename
        
        # Always treat as a new upload and process from scratch
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Initialize job status
        job_status[filename] = {"status": "processing", "progress": 0, "message": "Queued for processing..."}

        # Offload processing to background task
        background_tasks.add_task(process_audio_task, file_path, filename)
        
        return {"filename": file.filename, "message": "File uploaded successfully. Processing started in background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history")
async def get_history():
    """Return all completed transcription jobs for the history panel."""
    history = []
    for filename, status_data in job_status.items():
        if status_data.get("status") == "completed":
            history.append({
                "filename": filename,
                "results": status_data.get("results", {}),
                "stems": status_data.get("stems", {}),
                "message": status_data.get("message", ""),
            })
    return history

@app.delete("/history/{filename}")
async def delete_history_item(filename: str):
    """Deeply clear a job from RAM memory and physically delete all its generated XMLs/stems off the SSD."""
    project_name = Path(filename).stem
    
    # Sweep ALL virtual extensions from job_status memory
    deleted_any = False
    keys_to_delete = [k for k in job_status.keys() if Path(k).stem == project_name]
    for k in keys_to_delete:
        del job_status[k]
        deleted_any = True
        
    if not deleted_any:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 1. Delete original upload
    orig_file = UPLOAD_DIR / filename
    if orig_file.exists():
        orig_file.unlink()
        
    # 2. Delete generated XMLs and MIDIs
    for ext, folder in [(".musicxml", "xml"), (".mid", "midi")]:
        for filepath in (OUTPUT_DIR / folder).glob(f"{project_name}_*{ext}"):
            filepath.unlink()
            
    # 3. Delete heavy Demucs stem folder structure
    stem_dir = OUTPUT_DIR / "stems" / project_name
    if stem_dir.exists():
        shutil.rmtree(stem_dir)
        
    return {"status": "success", "message": f"Deleted {filename} entirely."}

@app.get("/status/{filename}")
async def get_status(filename: str):
    status = job_status.get(filename)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
