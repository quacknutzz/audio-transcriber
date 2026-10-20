import asyncio
import json
import time
from pathlib import Path
import music21
from services.transcription import TranscriptionService
from services.music_processing import MusicProcessingService

base_dir = Path("backend")
midi_dir = base_dir / "processed/midi"
xml_dir = base_dir / "processed/xml"
stems_dir = base_dir / "processed/stems"
uploads_dir = base_dir / "uploads"

ts = TranscriptionService(output_dir=midi_dir)
svc = MusicProcessingService(output_dir=xml_dir)

# Remove any drum sheet music XMLs (Drums is strictly Audio-Only) and silent bleed files
for stale in [
    midi_dir / "introoooo - drop_piano_piano.mid",
    midi_dir / "introoooo - drop_vocals_basic_pitch.mid",
    xml_dir / "introoooo - drop_piano.musicxml",
    xml_dir / "introoooo - drop_vocals.musicxml",
    xml_dir / "introoooo - drop_drums.musicxml",
    xml_dir / "Taylor Swift - Love Story_drums.musicxml",
]:
    if stale.exists():
        stale.unlink()

async def rebuild_all():
    state_path = base_dir / "processed/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    # 1. Taylor Swift - Love Story (All 5 Pitched Stems: vocals, piano, guitar, bass, other; Drums = Audio Only)
    ts_audio = uploads_dir / "Taylor Swift - Love Story.mp3"
    ts_stem_folder = stems_dir / "Taylor Swift - Love Story/htdemucs_6s/Taylor Swift - Love Story"
    ts_drum = ts_stem_folder / "drums.wav"

    # Re-transcribe piano and other with the upgraded peak-normalized & cross-stem bleed-filtered transcriber
    ts_piano_mid = await ts.transcribe_instrument(ts_stem_folder / "piano.wav", "Taylor Swift - Love Story_piano", "piano")
    ts_other_mid = await ts.transcribe_instrument(ts_stem_folder / "other.wav", "Taylor Swift - Love Story_other", "other")

    ts_results = {}
    master_key = None
    for inst, mid_path in [
        ("vocals", midi_dir / "Taylor Swift - Love Story_vocals_basic_pitch.mid"),
        ("piano", ts_piano_mid),
        ("guitar", midi_dir / "Taylor Swift - Love Story_guitar_basic_pitch.mid"),
        ("bass", midi_dir / "Taylor Swift - Love Story_bass_basic_pitch.mid"),
        ("other", ts_other_mid),
    ]:
        out_name = f"Taylor Swift - Love Story_{inst}"
        xml_path = svc.midi_to_xml(
            mid_path, out_name, audio_ref_path=ts_audio, drum_ref_path=ts_drum,
            master_key_sig=master_key
        )
        ts_results[inst] = f"/xml/{xml_path.name}"
        if master_key is None:
            s = music21.converter.parse(str(xml_path))
            ks = s.recurse().getElementsByClass(music21.key.KeySignature)
            if ks:
                master_key = ks.first()

    if "Taylor Swift - Love Story.mp3" not in state:
        state["Taylor Swift - Love Story.mp3"] = {
            "status": "completed",
            "progress": 100,
            "message": "Transcription completed!",
            "stems": {
                k: f"/stems/Taylor Swift - Love Story/htdemucs_6s/Taylor Swift - Love Story/{k}.wav"
                for k in ["bass", "drums", "guitar", "other", "piano", "vocals"]
            },
            "updated_at": time.time(),
        }
    state["Taylor Swift - Love Story.mp3"]["results"] = ts_results

    # 2. introoooo - drop.mp3 (Pitched Stems: bass, guitar, other; Drums = Audio Only)
    id_audio = uploads_dir / "introoooo - drop.mp3"
    id_stem_folder = stems_dir / "introoooo - drop/htdemucs_6s/introoooo - drop"
    id_drum = id_stem_folder / "drums.wav"
    if id_audio.exists() and id_stem_folder.exists():
        id_results = {}
        id_master_key = None
        for inst, mid_name in [
            ("bass", "introoooo - drop_bass_basic_pitch.mid"),
            ("guitar", "introoooo - drop_guitar_basic_pitch.mid"),
            ("other", "introoooo - drop_other_basic_pitch.mid"),
        ]:
            mid = midi_dir / mid_name
            if not mid.exists():
                continue
            out_name = f"introoooo - drop_{inst}"
            xml_path = svc.midi_to_xml(
                mid, out_name, audio_ref_path=id_audio, drum_ref_path=id_drum,
                master_key_sig=id_master_key
            )
            id_results[inst] = f"/xml/{xml_path.name}"
            if id_master_key is None:
                s = music21.converter.parse(str(xml_path))
                ks = s.recurse().getElementsByClass(music21.key.KeySignature)
                if ks:
                    id_master_key = ks.first()
        state["introoooo - drop.mp3"] = {
            "status": "completed",
            "progress": 100,
            "message": "Transcription completed!",
            "results": id_results,
            "stems": {
                k: f"/stems/introoooo - drop/htdemucs_6s/introoooo - drop/{k}.wav"
                for k in ["bass", "drums", "guitar", "other", "piano", "vocals"]
                if (id_stem_folder / f"{k}.wav").exists()
            },
            "updated_at": time.time() - 60,
        }

    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print("Successfully rebuilt all project MusicXMLs and updated state.json!")

if __name__ == "__main__":
    asyncio.run(rebuild_all())
