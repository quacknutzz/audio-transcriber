import asyncio
import json
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

# Remove silent bleed files from introoooo - drop
for stale in [
    midi_dir / "introoooo - drop_piano_piano.mid",
    midi_dir / "introoooo - drop_vocals_basic_pitch.mid",
    xml_dir / "introoooo - drop_piano.musicxml",
    xml_dir / "introoooo - drop_vocals.musicxml",
]:
    if stale.exists():
        stale.unlink()

async def rebuild_all():
    state_path = base_dir / "processed/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))

    # 1. Taylor Swift - Love Story
    ts_audio = uploads_dir / "Taylor Swift - Love Story.mp3"
    ts_drum = stems_dir / "Taylor Swift - Love Story/htdemucs_6s/Taylor Swift - Love Story/drums.wav"
    ts_results = {}
    master_key = None
    for inst, mid_name in [
        ("vocals", "Taylor Swift - Love Story_vocals_basic_pitch.mid"),
        ("guitar", "Taylor Swift - Love Story_guitar_basic_pitch.mid"),
        ("bass", "Taylor Swift - Love Story_bass_basic_pitch.mid"),
        ("other", "Taylor Swift - Love Story_other_basic_pitch.mid"),
        ("drums", "Taylor Swift - Love Story_drums_drums.mid"),
    ]:
        mid = midi_dir / mid_name
        out_name = f"Taylor Swift - Love Story_{inst}"
        xml_path = svc.midi_to_xml(
            mid, out_name, audio_ref_path=ts_audio, drum_ref_path=ts_drum,
            master_key_sig=master_key if inst != "drums" else None
        )
        ts_results[inst] = f"/xml/{xml_path.name}"
        if master_key is None and inst != "drums":
            s = music21.converter.parse(str(xml_path))
            ks = s.recurse().getElementsByClass(music21.key.KeySignature)
            if ks:
                master_key = ks.first()
    state["Taylor Swift - Love Story.mp3"]["results"] = ts_results

    # 2. introoooo - drop.mp3
    id_audio = uploads_dir / "introoooo - drop.mp3"
    id_drum = stems_dir / "introoooo - drop/htdemucs_6s/introoooo - drop/drums.wav"
    id_drum_mid = await ts.transcribe_instrument(id_drum, "introoooo - drop_drums", "drums")
    id_results = {}
    id_master_key = None
    for inst, mid_name in [
        ("bass", "introoooo - drop_bass_basic_pitch.mid"),
        ("guitar", "introoooo - drop_guitar_basic_pitch.mid"),
        ("other", "introoooo - drop_other_basic_pitch.mid"),
        ("drums", "introoooo - drop_drums_drums.mid"),
    ]:
        mid = midi_dir / mid_name
        out_name = f"introoooo - drop_{inst}"
        xml_path = svc.midi_to_xml(
            mid, out_name, audio_ref_path=id_audio, drum_ref_path=id_drum,
            master_key_sig=id_master_key if inst != "drums" else None
        )
        id_results[inst] = f"/xml/{xml_path.name}"
        if id_master_key is None and inst != "drums":
            s = music21.converter.parse(str(xml_path))
            ks = s.recurse().getElementsByClass(music21.key.KeySignature)
            if ks:
                id_master_key = ks.first()
    state["introoooo - drop.mp3"]["results"] = id_results

    # 3. test_pipeline_sample.wav
    tp_audio = uploads_dir / "test_pipeline_sample.wav"
    tp_drum = stems_dir / "test_pipeline_sample/htdemucs_6s/test_pipeline_sample/drums.wav"
    tp_results = {}
    tp_master_key = None
    for inst, mid_name in [
        ("bass", "test_pipeline_sample_bass_basic_pitch.mid"),
        ("other", "test_pipeline_sample_other_basic_pitch.mid"),
    ]:
        mid = midi_dir / mid_name
        out_name = f"test_pipeline_sample_{inst}"
        xml_path = svc.midi_to_xml(
            mid, out_name, audio_ref_path=tp_audio, drum_ref_path=tp_drum,
            master_key_sig=tp_master_key
        )
        tp_results[inst] = f"/xml/{xml_path.name}"
        if tp_master_key is None:
            s = music21.converter.parse(str(xml_path))
            ks = s.recurse().getElementsByClass(music21.key.KeySignature)
            if ks:
                tp_master_key = ks.first()
    state["test_pipeline_sample.wav"]["results"] = tp_results

    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print("Successfully rebuilt all project MusicXMLs and updated state.json!")

if __name__ == "__main__":
    asyncio.run(rebuild_all())
