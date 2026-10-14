from pathlib import Path
import math
import logging
import numpy as np
import music21

class MusicProcessingService:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    def detect_attributes(self, audio_path: Path, drum_path: Path = None):
        """
        Uses Librosa to detect BPM and Key from the audio.
        If an isolated drum track is available, detects tempo from drum transients for metronomic accuracy.
        """
        try:
            import librosa
            import numpy as np
            
            # 1. Detect Tempo (Prefer isolated drum transients if available)
            tempo_target = drum_path if (drum_path and drum_path.exists()) else audio_path
            y_tempo, sr_tempo = librosa.load(str(tempo_target), sr=22050, duration=90)
            onset_env = librosa.onset.onset_strength(y=y_tempo, sr=sr_tempo)
            tempo, _ = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr_tempo)
            if isinstance(tempo, np.ndarray):
                tempo = tempo.item()
            
            # If tempo is excessively slow (under 65), check if double-time is more standard
            if tempo < 65.0:
                tempo = tempo * 2.0
            
            # 2. Detect Key from harmonic audio
            y_harm, sr_harm = librosa.load(str(audio_path), sr=22050, duration=60)
            chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr_harm)
            chroma_sum = np.sum(chroma, axis=1)
            top_idx = np.argmax(chroma_sum)
            notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            key_note = notes[top_idx]
            
            self.logger.info(f"Detected Attributes: Tempo={tempo:.1f} BPM, Key={key_note} (source={tempo_target.name})")
            return tempo, key_note
            
        except Exception as e:
            self.logger.warning(f"Attribute detection failed: {e}")
            return 120.0, "C"

    def midi_to_xml(self, midi_path: Path, output_name: str, audio_ref_path: Path = None, drum_ref_path: Path = None, master_key_sig=None) -> Path:
        """
        Converts a MIDI file to clean, professionally formatted MusicXML:
        - Applies acoustic physics and musicology rules per instrument:
          * Guitar: 55ms strum consolidation, harmonic overtone sieve, +12 semitone 8vb written transposition.
          * Bass: Pluck attack-sustain octave merger, register normalization, +12 semitone 8vb written transposition.
          * Vocals: Monophonic pitch-continuity smoothing, zero transposition.
          * Other: Polyphonic chord sieving and overtone de-cluttering.
        - Harmonizes key signature across all stems with the master song key.
        - Mathematical invariant 4.0-beat measure containers with tie suppression and clean rest alignment.
        """
        import re
        import pretty_midi
        output_xml_path = self.output_dir / f"{output_name}.musicxml"
        self.logger.info(f"Converting MIDI to XML: {midi_path} -> {output_xml_path}")
        
        try:
            # 1. Detect BPM & Key
            tempo_bpm = 120.0
            key_tonic = "C"
            if audio_ref_path and audio_ref_path.exists():
                tempo_bpm, key_tonic = self.detect_attributes(audio_ref_path, drum_ref_path)

            name_lower = output_name.lower()
            is_vocal = any(m in name_lower for m in ["vocal", "voice"])
            is_bass = "bass" in name_lower
            is_guitar = "guitar" in name_lower
            is_drum = any(d in name_lower for d in ["drums", "drum", "percussion"])
            is_mono = is_vocal or is_bass

            # 2. Parse MIDI with PrettyMIDI
            pm = pretty_midi.PrettyMIDI(str(midi_path))
            if not pm.instruments:
                raise ValueError("MIDI file contains no instrument tracks")

            inst = pm.instruments[0]

            # Filter out microscopic velocity/transient noise
            clean_notes = [
                n for n in inst.notes
                if not (n.end - n.start < 0.08 and n.velocity < 40)
            ]

            # 3. Instrument-Aware Musicology & Physics Processing
            events = []

            if is_bass:
                # Bass: Monophonic pluck attack/decay merger & octave-jump continuity filter
                sorted_notes = sorted(clean_notes, key=lambda x: x.start)
                merged_bass = []
                for n in sorted_notes:
                    if not merged_bass:
                        merged_bass.append({"start": n.start, "end": n.end, "pitch": n.pitch, "vel": n.velocity})
                        continue
                    prev = merged_bass[-1]
                    # If consecutive note is an overtone jump (+/- 12 semitones) within 0.15s, merge attack into decay
                    is_octave_flip = abs(n.pitch - prev["pitch"]) in [11, 12, 13]
                    is_close = (n.start - prev["end"]) <= 0.15
                    if is_octave_flip and is_close:
                        prev["end"] = max(prev["end"], n.end)
                        norm_p = prev["pitch"]
                        while norm_p < 36: norm_p += 12
                        while norm_p > 48: norm_p -= 12
                        prev["pitch"] = norm_p
                    elif n.start < prev["end"]:
                        if n.start > prev["start"] + 0.1:
                            prev["end"] = n.start
                            merged_bass.append({"start": n.start, "end": n.end, "pitch": n.pitch, "vel": n.velocity})
                    else:
                        norm_p = n.pitch
                        while norm_p < 36: norm_p += 12
                        while norm_p > 48: norm_p -= 12
                        merged_bass.append({"start": n.start, "end": n.end, "pitch": norm_p, "vel": n.velocity})

                # Standard bass clef transposition (+12 semitones into written pitch, 8vb standard)
                for b in merged_bass:
                    events.append({
                        "start": b["start"],
                        "end": b["end"],
                        "pitches": [b["pitch"] + 12]
                    })

            elif is_guitar:
                # Guitar: 55ms strum consolidation + harmonic overtone sieve + +12 written transposition
                sorted_notes = sorted(clean_notes, key=lambda x: x.start)
                chords = []
                for n in sorted_notes:
                    if n.velocity < 40 and (n.end - n.start) < 0.1:
                        continue  # discard transient string scrapes
                    if not chords or (n.start - chords[-1]["start"] > 0.055):
                        chords.append({"start": n.start, "end": n.end, "pitches": [n.pitch]})
                    else:
                        chords[-1]["pitches"].append(n.pitch)
                        chords[-1]["end"] = max(chords[-1]["end"], n.end)

                for c in chords:
                    # Transpose +12 into standard guitar written pitch (8vb treble clef)
                    transposed = [p + 12 for p in c["pitches"]]
                    # Harmonic sieve: deduplicate pitch classes, allow at most 1 octave doubling
                    seen_pcs = {}
                    filtered = []
                    for p in sorted(transposed):
                        pc = p % 12
                        seen_pcs[pc] = seen_pcs.get(pc, 0) + 1
                        if seen_pcs[pc] <= 1:
                            filtered.append(p)
                    # Polyphony clamping: max 4 voices for humanly playable guitar chords
                    if len(filtered) > 4:
                        filtered = [filtered[0]] + filtered[-3:]
                    if filtered:
                        events.append({"start": c["start"], "end": c["end"], "pitches": filtered})

            elif is_vocal:
                # Strictly sequential monophonic vocal melody
                sorted_notes = sorted(clean_notes, key=lambda x: x.start)
                for n in sorted_notes:
                    if not events:
                        events.append({"start": n.start, "end": n.end, "pitches": [n.pitch]})
                    else:
                        prev = events[-1]
                        if n.start < prev["end"]:
                            prev["end"] = max(prev["start"] + 0.05, n.start)
                        if n.start >= prev["end"]:
                            events.append({"start": n.start, "end": n.end, "pitches": [n.pitch]})

            else:
                # Other / Synths / Strings: polyphonic clustering with overtone sieving
                sorted_notes = sorted(clean_notes, key=lambda x: x.start)
                chords = []
                for n in sorted_notes:
                    if n.velocity < 42:
                        continue
                    if not chords or (n.start - chords[-1]["start"] > 0.06):
                        chords.append({"start": n.start, "end": n.end, "pitches": [n.pitch]})
                    else:
                        chords[-1]["pitches"].append(n.pitch)
                        chords[-1]["end"] = max(chords[-1]["end"], n.end)

                for c in chords:
                    seen_pcs = {}
                    filtered = []
                    for p in sorted(c["pitches"]):
                        pc = p % 12
                        seen_pcs[pc] = seen_pcs.get(pc, 0) + 1
                        if seen_pcs[pc] <= 1:
                            filtered.append(p)
                    if len(filtered) > 4:
                        filtered = [filtered[0]] + filtered[-3:]
                    if filtered:
                        events.append({"start": c["start"], "end": c["end"], "pitches": filtered})

            # 4. Harmonized Song Key Signature
            detected_key = master_key_sig
            if not detected_key:
                if is_bass:
                    detected_key = music21.key.Key(key_tonic)
                else:
                    try:
                        temp_stream = music21.stream.Stream()
                        for ev in events:
                            for p in ev["pitches"]:
                                temp_stream.append(music21.note.Note(p))
                        if len(temp_stream.notes) >= 3:
                            detected_key = temp_stream.analyze('key')
                            self.logger.info(f"Music21 K-S Key for {output_name}: {detected_key} (sharps={detected_key.sharps})")
                    except Exception as k_err:
                        self.logger.warning(f"Key analysis fallback: {k_err}")

            if not detected_key:
                detected_key = music21.key.Key(key_tonic)

            # 5. Professional Rhythmic Quantization & Metric Beat Alignment
            beat_sec = 60.0 / max(tempo_bpm, 40.0)
            
            # Use 8th-note grid (0.5 beat) as standard musical subdivision for clean notation,
            # allowing 16th-note (0.25) only for fast runs (< 0.28s)
            quantized = []
            for ev in events:
                raw_dur = (ev["end"] - ev["start"]) / beat_sec
                raw_start = ev["start"] / beat_sec
                g = 0.25 if raw_dur < 0.28 else 0.5
                q_start = round(raw_start / g) * g
                q_dur = max(g, round(raw_dur / g) * g)
                quantized.append({"start": q_start, "dur": q_dur, "pitches": ev["pitches"]})

            # Prevent overlaps and connect small legato gaps (breath pauses <= 0.35 beat) in monophonic lines
            for idx in range(len(quantized) - 1):
                curr = quantized[idx]
                nxt = quantized[idx + 1]
                if curr["start"] + curr["dur"] > nxt["start"]:
                    curr["dur"] = max(0.25, nxt["start"] - curr["start"])
                gap = nxt["start"] - (curr["start"] + curr["dur"])
                if is_mono and 0.0 < gap <= 0.35:
                    curr["dur"] += gap

            max_q = max((ev["start"] + ev["dur"] for ev in quantized), default=4.0)
            total_measures = max(1, int(np.ceil(max_q / 4.0)))

            # Distribute notes into mathematically exact 4-beat measures
            measure_events = {m: [] for m in range(1, total_measures + 1)}

            for ev in quantized:
                q_s = ev["start"]
                q_d = ev["dur"]
                p = ev["pitches"]
                m_idx = int(q_s // 4.0) + 1
                offset_in_m = q_s % 4.0
                spill = (offset_in_m + q_d) - 4.0

                # Tie suppression policy:
                # If spillover across the barline is <= 0.5 beats (short tail/reverb bleed),
                # truncate cleanly to the barline rather than creating an unwanted tie!
                if spill <= 0.5:
                    dur_in_m = min(q_d, 4.0 - offset_in_m)
                    measure_events[m_idx].append({
                        "offset": offset_in_m,
                        "dur": dur_in_m,
                        "pitches": p,
                        "tie": None
                    })
                else:
                    # Genuinely sustained phrase held across barline -> split into tied notes
                    dur_m1 = 4.0 - offset_in_m
                    dur_m2 = round(spill / 0.5) * 0.5
                    measure_events[m_idx].append({
                        "offset": offset_in_m,
                        "dur": dur_m1,
                        "pitches": p,
                        "tie": "start"
                    })
                    if m_idx + 1 <= total_measures and dur_m2 > 0:
                        measure_events[m_idx + 1].append({
                            "offset": 0.0,
                            "dur": dur_m2,
                            "pitches": p,
                            "tie": "stop"
                        })

            # Construct music21 Part with explicit Measure objects
            new_part = music21.stream.Part()
            new_part.id = 'P1'
            new_part.partName = ''

            # Clef selection
            if "bass" in name_lower:
                part_clef = music21.clef.BassClef()
            elif is_drum:
                part_clef = music21.clef.PercussionClef()
            else:
                part_clef = music21.clef.TrebleClef()

            time_sig = music21.meter.TimeSignature('4/4')
            tempo_mark = music21.tempo.MetronomeMark(number=round(tempo_bpm))

            # Build each 4.0-beat Measure explicitly
            for m_num in range(1, total_measures + 1):
                m = music21.stream.Measure(number=m_num)
                
                if m_num == 1:
                    m.insert(0, part_clef)
                    m.insert(0, detected_key)
                    m.insert(0, time_sig)
                    m.insert(0, tempo_mark)

                evs = sorted(measure_events[m_num], key=lambda x: x["offset"])

                if not evs:
                    # Authentic full-measure rest
                    m.insert(0, music21.note.Rest(quarterLength=4.0))
                else:
                    curr_pos = 0.0
                    for ev in evs:
                        # Insert rest for gap before note
                        if ev["offset"] > curr_pos:
                            gap_dur = ev["offset"] - curr_pos
                            m.insert(curr_pos, music21.note.Rest(quarterLength=gap_dur))

                        unique_p = sorted(list(set(ev["pitches"])))
                        if len(unique_p) == 1 or is_mono:
                            pitch_val = unique_p[0] if "bass" in name_lower else unique_p[-1]
                            el = music21.note.Note(pitch_val, quarterLength=ev["dur"])
                            if el.pitch.accidental is not None and el.pitch.accidental.name == 'natural':
                                el.pitch.accidental = None
                        else:
                            el = music21.chord.Chord(unique_p, quarterLength=ev["dur"])
                            for po in el.pitches:
                                if po.accidental is not None and po.accidental.name == 'natural':
                                    po.accidental = None

                        if ev["tie"]:
                            el.tie = music21.tie.Tie(ev["tie"])

                        m.insert(ev["offset"], el)
                        curr_pos = ev["offset"] + ev["dur"]

                    # Fill remaining space in measure with rest
                    if curr_pos < 4.0:
                        m.insert(curr_pos, music21.note.Rest(quarterLength=4.0 - curr_pos))

                new_part.append(m)

            # Optimize accidentals: eliminate redundant naturals and duplicate measure sharps
            new_part.makeAccidentals(
                inPlace=True,
                cautionaryPitchClass=False,
                cautionaryAll=False,
                cautionaryNotImmediateRepeat=False
            )

            # 6. Wrap in Score with clean empty metadata
            clean_score = music21.stream.Score()
            clean_score.metadata = music21.metadata.Metadata()
            clean_score.metadata.title = None
            clean_score.metadata.movementName = None
            clean_score.metadata.composer = None
            clean_score.insert(0, new_part)

            # Export to MusicXML
            clean_score.write('musicxml', fp=str(output_xml_path))

            # 7. Post-process XML: strip any leftover "Music21 Fragment" and placeholder composer
            xml_content = output_xml_path.read_text(encoding='utf-8')
            xml_content = re.sub(r'\s*<movement-title>.*?</movement-title>', '', xml_content)
            xml_content = re.sub(r'\s*<creator.*?>.*?</creator>', '', xml_content)
            xml_content = xml_content.replace('Music21 Fragment', '').replace('Music21', '')
            output_xml_path.write_text(xml_content, encoding='utf-8')

            return output_xml_path

        except Exception as e:
            import traceback
            self.logger.error(f"MusicXML conversion failed: {e}\n{traceback.format_exc()}")
            raise e
