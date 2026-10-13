from pathlib import Path
from services.music_processing import MusicProcessingService

midi_path = Path(r"C:\Users\rishi\.gemini\antigravity\scratch\audio_transcriber\backend\processed\midi\Taylor Swift - Love Story_other_mt3.mid")
output_dir = Path(r"C:\Users\rishi\.gemini\antigravity\scratch\audio_transcriber\backend\processed\xml")

service = MusicProcessingService(output_dir)

try:
    print(f"Converting {midi_path}...")
    # output_name without extension
    output_xml = service.midi_to_xml(midi_path, "Taylor Swift - Love Story_other")
    print(f"Success! Saved to {output_xml}")
except Exception as e:
    import traceback
    print("Failed!")
    traceback.print_exc()
