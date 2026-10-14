from pathlib import Path
import music21
import re
from services.music_processing import MusicProcessingService

base_dir = Path("backend")
svc = MusicProcessingService(output_dir=base_dir / "processed/xml")

midi_dir = base_dir / "processed/midi"
audio_file = base_dir / "uploads/Taylor Swift - Love Story.mp3"
drum_path = base_dir / "processed/stems/Taylor Swift - Love Story/htdemucs_6s/Taylor Swift - Love Story/drums.wav"

order = ["vocals", "guitar", "bass", "other"]
master_key = None

for inst in order:
    mid = midi_dir / f"Taylor Swift - Love Story_{inst}_basic_pitch.mid"
    out_name = f"Taylor Swift - Love Story_{inst}"
    print(f"\nProcessing {inst.upper()}...")
    xml_path = svc.midi_to_xml(
        mid, out_name, audio_ref_path=audio_file, drum_ref_path=drum_path,
        master_key_sig=master_key
    )
    
    # Read metrics
    text = xml_path.read_text(encoding="utf-8")
    fifths = re.findall(r'<fifths>(-?\d+)</fifths>', text)
    tempo = re.findall(r'<per-minute>(\d+)</per-minute>', text)
    accs = re.findall(r'<accidental>(\w+)</accidental>', text)
    ties = re.findall(r'<tie type="start"/>', text)
    measures = re.findall(r'<measure number="(\d+)"', text)
    max_m = max([int(m) for m in measures], default=0)
    
    print(f"  {inst.upper()}: Measures={max_m}, Fifths={fifths[:1]}, Tempo={tempo[:1]}, Ties={len(ties)}, Accidentals={len(accs)}")
    
    if master_key is None:
        score = music21.converter.parse(str(xml_path))
        ks = score.recurse().getElementsByClass(music21.key.KeySignature)
        if ks:
            master_key = ks.first()
            print(f"  --> Master key established as: {master_key} (sharps={master_key.sharps})")

print("\nAll stems converted successfully!")
