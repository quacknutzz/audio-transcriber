import pretty_midi
import music21
from pathlib import Path
import numpy as np

def test_bass_filtration():
    mid_path = Path("backend/processed/midi/Taylor Swift - Love Story_bass_basic_pitch.mid")
    pm = pretty_midi.PrettyMIDI(str(mid_path))
    notes = pm.instruments[0].notes
    print(f"Original Bass notes: {len(notes)}")

    # 1. Monophonic + attack-decay merger for octave flips
    # Sort by start time
    sorted_notes = sorted(notes, key=lambda n: n.start)
    merged = []
    
    for n in sorted_notes:
        if not merged:
            merged.append({"start": n.start, "end": n.end, "pitch": n.pitch, "vel": n.velocity})
            continue
        prev = merged[-1]
        
        # Check if this note is an octave continuation of the previous note (within 0.15s)
        is_octave_flip = abs(n.pitch - prev["pitch"]) in [11, 12, 13]
        is_close_in_time = (n.start - prev["end"]) <= 0.15
        
        if is_octave_flip and is_close_in_time:
            # Merge into continuous note, keeping the stronger pitch or normalizing to octave 2
            prev["end"] = max(prev["end"], n.end)
            # Normalize to sounding octave 2 (pitches 36 to 48)
            norm_p = prev["pitch"]
            while norm_p < 36: norm_p += 12
            while norm_p > 48: norm_p -= 12
            prev["pitch"] = norm_p
        elif n.start < prev["end"]:
            # Overlap in bass -> cut previous note or ignore micro-overlap
            if n.start > prev["start"] + 0.1:
                prev["end"] = n.start
                merged.append({"start": n.start, "end": n.end, "pitch": n.pitch, "vel": n.velocity})
        else:
            # Normalize pitch to octave 2
            norm_p = n.pitch
            while norm_p < 36: norm_p += 12
            while norm_p > 48: norm_p -= 12
            merged.append({"start": n.start, "end": n.end, "pitch": norm_p, "vel": n.velocity})

    print(f"Merged Bass notes: {len(merged)}")
    
    # Transpose +12 for standard bass clef notation
    for m in merged:
        m["pitch"] += 12
        
    print(f"Sample transformed bass pitches: {[pretty_midi.note_number_to_name(m['pitch']) for m in merged[:15]]}")

def test_guitar_filtration():
    mid_path = Path("backend/processed/midi/Taylor Swift - Love Story_guitar_basic_pitch.mid")
    pm = pretty_midi.PrettyMIDI(str(mid_path))
    notes = pm.instruments[0].notes
    print(f"\nOriginal Guitar notes: {len(notes)}")

    # 1. Strum consolidation window (50ms)
    sorted_notes = sorted(notes, key=lambda n: n.start)
    chords = []
    
    for n in sorted_notes:
        if n.velocity < 40 and (n.end - n.start) < 0.1:
            continue # drop faint noise
        if not chords or (n.start - chords[-1]["start"] > 0.055):
            chords.append({"start": n.start, "end": n.end, "pitches": [n.pitch], "vels": [n.velocity]})
        else:
            chords[-1]["pitches"].append(n.pitch)
            chords[-1]["vels"].append(n.velocity)
            chords[-1]["end"] = max(chords[-1]["end"], n.end)

    print(f"Consolidated strum events: {len(chords)}")

    # 2. Harmonic Overtone Sieve & Polyphony Clamping (max 4 distinct voices)
    cleaned_chords = []
    for c in chords:
        pitches = c["pitches"]
        # Standard guitar transposition (+12 semitones)
        transposed = [p + 12 for p in pitches]
        
        # Sort and deduplicate by pitch class
        seen_pcs = set()
        filtered = []
        for p in sorted(transposed):
            pc = p % 12
            # Allow at most one octave repetition
            if list(seen_pcs).count(pc) < 1:
                filtered.append(p)
                seen_pcs.add(pc)
        
        # Cap polyphony to 3-4 notes max for clean readable chords
        if len(filtered) > 4:
            # Keep bass note, and top 3 notes
            filtered = [filtered[0]] + filtered[-3:]
            
        if filtered:
            cleaned_chords.append({
                "start": c["start"],
                "end": c["end"],
                "pitches": filtered
            })

    print(f"Cleaned guitar chord events: {len(cleaned_chords)}")
    sample_chords = [[pretty_midi.note_number_to_name(p) for p in c["pitches"]] for c in cleaned_chords[:10]]
    print(f"Sample transformed guitar chords: {sample_chords}")

if __name__ == "__main__":
    test_bass_filtration()
    test_guitar_filtration()
