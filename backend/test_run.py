import asyncio
from pathlib import Path
from services.transcription import TranscriptionService
from services.music_processing import MusicProcessingService

OUTPUT_DIR = Path("processed")
transcription_service = TranscriptionService(OUTPUT_DIR / "midi")
music_processing = MusicProcessingService(OUTPUT_DIR / "xml")

async def main():
    stem_path = Path("processed/stems/introoooo - drop/htdemucs_6s/introoooo - drop/piano.wav")
    print(f"Testing pipeline for: {stem_path.absolute()}")
    
    if not stem_path.exists():
        print("Stem not found!")
        return
        
    project_name = "introoooo - drop"
    instrument = "piano"
    
    # Transcribe (forcing basic-pitch fallback because of MT3 error)
    print(f"Transcribing {instrument} from {stem_path}...")
    midi_path = await transcription_service.transcribe_melody(
        stem_path, 
        f"{project_name}_{instrument}", 
        instrument
    )
    print(f"MIDI output: {midi_path}")
    
    # Sheet Music Export
    print(f"Generating XML for {instrument}...")
    xml_path = music_processing.midi_to_xml(midi_path, f"{project_name}_{instrument}")
    print(f"XML output: {xml_path}")

if __name__ == "__main__":
    asyncio.run(main())
