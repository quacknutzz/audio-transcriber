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
            
            for ext in [".wav", ".mp3", ".m4a"]:
                virtual_filename = project_name + ext
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

async def process_audio_task(file_path: Path, filename: str):
    """
    Background task to handle the heavy lifting of separation and transcription.
    """
    try:
        job_status[filename] = {"status": "processing", "progress": 10, "message": "Separating stems..."}
        # 1. Separation
        print(f"Separating {filename}...")
        stems = await separation_service.separate_audio(file_path)
        print(f"Separation complete. Stems: {stems.keys()}")
        job_status[filename] = {"status": "processing", "progress": 50, "message": "Transcribing instruments..."}

        # 2. Transcription
        results = {}
        project_name = file_path.stem
        
        # Transcribe Bass (Melody)
        if "bass" in stems:
            midi_path = await transcription_service.transcribe_melody(stems["bass"], f"{project_name}_bass", instrument_name="bass")
            xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_bass", audio_ref_path=file_path)
            results["bass"] = xml_path

        # Transcribe Guitar (Melody)
        if "guitar" in stems:
            midi_path = await transcription_service.transcribe_melody(stems["guitar"], f"{project_name}_guitar", instrument_name="guitar")
            xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_guitar", audio_ref_path=file_path)
            results["guitar"] = xml_path
        if "other" in stems:
             midi_path = await transcription_service.transcribe_melody(stems["other"], f"{project_name}_other", instrument_name="other")
             xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_other", audio_ref_path=file_path)
             results["other"] = xml_path

        # Transcribe Vocals (Melody)
        if "vocals" in stems:
            midi_path = await transcription_service.transcribe_melody(stems["vocals"], f"{project_name}_vocals", instrument_name="vocals")
            xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_vocals", audio_ref_path=file_path)
            results["vocals"] = xml_path
            
        # Transcribe Piano/Keys (Melody/Chords)
        if "piano" in stems:
            midi_path = await transcription_service.transcribe_melody(stems["piano"], f"{project_name}_piano", instrument_name="piano")
            xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_piano", audio_ref_path=file_path)
            results["piano"] = xml_path
        elif "keys" in stems: # In case we map it differently later
             midi_path = await transcription_service.transcribe_melody(stems["keys"], f"{project_name}_keys", instrument_name="piano")
             xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_keys", audio_ref_path=file_path)
             results["keys"] = xml_path

        # Transcribe Drums (Percussion)
        if "drums" in stems:
            midi_path = await transcription_service.transcribe_melody(stems["drums"], f"{project_name}_drums", instrument_name="drums")
            drum_xml_path = music_processing_service.midi_to_xml(midi_path, f"{project_name}_drums", audio_ref_path=file_path)
            results["drums"] = drum_xml_path
            
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
                    # Path is not relative to stems dir, skip
                    pass
            
        print(f"Processing complete for {filename}. Results: {results_urls}")
        job_status[filename] = {
            "status": "completed", 
            "progress": 100, 
            "message": "Transcription successful.",
            "results": results_urls,
            "stems": stems_urls
        }
        
    except Exception as e:
        print(f"Error processing {filename}: {e}")
        job_status[filename] = {"status": "error", "progress": 0, "message": str(e)}

@app.post("/upload")
async def upload_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        file_path = UPLOAD_DIR / file.filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Initialize job status
        job_status[file.filename] = {"status": "processing", "progress": 0, "message": "Queued for processing..."}

        # Offload processing to background task
        background_tasks.add_task(process_audio_task, file_path, file.filename)
        
        return {"filename": file.filename, "message": "File uploaded successfully. Processing started in background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{filename}")
async def get_status(filename: str):
    status = job_status.get(filename)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
