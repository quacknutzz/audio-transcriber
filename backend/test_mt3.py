import asyncio
import os
import sys
from pathlib import Path
import librosa

# Add the current directory to sys.path so we can import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.transcription import TranscriptionService

async def test_mt3():
    # Find a sample stem audio file to test on
    # E.g., processed/stems/Taylor Swift - Love Story/htdemucs_6s/Taylor Swift - Love Story/piano.wav
    audio_file = Path("processed/stems/Taylor Swift - Love Story/htdemucs_6s/Taylor Swift - Love Story/piano.wav")
    
    if not audio_file.exists():
        print(f"Test audio not found at {audio_file}. Trying to find *any* .wav file in processed/stems...")
        wav_files = list(Path("processed/stems").rglob("*.wav"))
        if not wav_files:
            print("No .wav files found to test MT3 on.")
            return
        audio_file = wav_files[0]
        
    print(f"Testing MT3 on: {audio_file}")
    
    # Run the MT3 transcription
    try:
        service = TranscriptionService(output_dir=Path("processed/midi"))
        y, sr = librosa.load(audio_file, sr=16000) # MT3 expects 16kHz
        # We'll just call the private _transcribe_mt3 directly to ensure it doesn't fall back to Basic Pitch silently
        print("Calling MT3 model directly...")
        # Actually _transcribe_mt3 expects an audio path, output name, instrument name
        # Let's call the actual method
        midi_path = await service._transcribe_mt3(audio_file, "test_mt3_output", "piano")
        print(f"MT3 Transcription succeeded! Output saved to: {midi_path}")

    except Exception as e:
        print(f"MT3 Transcription failed! Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mt3())
