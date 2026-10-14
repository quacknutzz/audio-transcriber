from pathlib import Path
import logging
import music21

class MusicProcessingService:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    def detect_attributes(self, audio_path: Path):
        """
        Uses Librosa to detect BPM and Key from the audio.
        """
        try:
            import librosa
            import numpy as np
            
            y, sr = librosa.load(str(audio_path), sr=None, duration=60) # Analyze first 60s
            
            # 1. Detect Tempo
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo, _ = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            if isinstance(tempo, np.ndarray):
                tempo = tempo.item()
            
            # 2. Detect Key
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            # Simple summation to find Tonic
            chroma_sum = np.sum(chroma, axis=1)
            top_idx = np.argmax(chroma_sum)
            # Map index to Note Name (0=C, 1=C#, etc)
            notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            key_note = notes[top_idx]
            
            self.logger.info(f"Detected Attributes: Tempo={tempo:.1f}, Key={key_note}")
            return tempo, key_note
            
        except Exception as e:
            self.logger.warning(f"Attribute detection failed: {e}")
            return 120.0, "C"

    def midi_to_xml(self, midi_path: Path, output_name: str, audio_ref_path: Path = None) -> Path:
        """
        Converts a MIDI file to clean, professionally formatted MusicXML:
        - Groups near-simultaneous polyphonic notes into coherent chords rather than slicing with chordify.
        - Preserves pure monophonic melody lines for vocals and bass.
        - Automatically creates valid musical measures and strips fragment metadata.
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
                tempo_bpm, key_tonic = self.detect_attributes(audio_ref_path)

            name_lower = output_name.lower()
            is_mono = any(m in name_lower for m in ["vocal", "voice", "bass"])
            is_drum = any(d in name_lower for d in ["drums", "drum", "percussion"])

            # 2. Parse MIDI with PrettyMIDI
            pm = pretty_midi.PrettyMIDI(str(midi_path))
            if not pm.instruments:
                raise ValueError("MIDI file contains no instrument tracks")

            inst = pm.instruments[0]

            # Filter out microscopic velocity/transient noise
            clean_notes = [
                n for n in inst.notes
                if not (n.end - n.start < 0.08 and n.velocity < 45)
            ]

            # 3. Cluster notes into coherent musical events
            events = []
            if is_mono:
                # Strictly sequential monophonic melody
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
                # Polyphonic chord clustering: group notes starting within 70ms into unified chords
                for n in sorted(clean_notes, key=lambda x: x.start):
                    if not events or (n.start - events[-1]["start"] > 0.07):
                        events.append({"start": n.start, "end": n.end, "pitches": [n.pitch]})
                    else:
                        events[-1]["pitches"].append(n.pitch)
                        events[-1]["end"] = max(events[-1]["end"], n.end)

            # 4. Construct music21 Part
            new_part = music21.stream.Part()
            new_part.id = 'P1'
            new_part.partName = ''

            # Key, Tempo, Time Signature
            new_part.insert(0, music21.key.Key(key_tonic))
            new_part.insert(0, music21.tempo.MetronomeMark(number=round(tempo_bpm)))
            new_part.insert(0, music21.meter.TimeSignature('4/4'))

            if "bass" in name_lower:
                new_part.insert(0, music21.clef.BassClef())
                new_part.insert(0, music21.instrument.ElectricBass())
            elif is_drum:
                new_part.insert(0, music21.clef.PercussionClef())
                new_part.insert(0, music21.instrument.Percussion())
            else:
                new_part.insert(0, music21.clef.TrebleClef())
                if "vocal" in name_lower or "voice" in name_lower:
                    new_part.insert(0, music21.instrument.Vocalist())
                elif "guitar" in name_lower:
                    new_part.insert(0, music21.instrument.ElectricGuitar())
                else:
                    new_part.insert(0, music21.instrument.Piano())

            # Convert seconds to quarter-note metric offsets
            sec_to_q = tempo_bpm / 60.0
            grid = 0.25 # 16th note grid
            last_end_q = 0.0

            for idx, ev in enumerate(events):
                raw_start_q = ev["start"] * sec_to_q
                q_start = round(raw_start_q / grid) * grid
                if q_start < last_end_q:
                    q_start = last_end_q

                raw_dur_q = (ev["end"] - ev["start"]) * sec_to_q
                q_dur = max(grid, round(raw_dur_q / grid) * grid)

                # Cap duration so subsequent chords don't get sliced
                if idx + 1 < len(events):
                    next_start_q = round((events[idx + 1]["start"] * sec_to_q) / grid) * grid
                    if next_start_q > q_start:
                        q_dur = min(q_dur, next_start_q - q_start)

                unique_pitches = sorted(list(set(ev["pitches"])))
                if len(unique_pitches) == 1 or is_mono:
                    p = unique_pitches[0] if "bass" in name_lower else unique_pitches[-1]
                    el = music21.note.Note(p)
                else:
                    el = music21.chord.Chord(unique_pitches)

                el.quarterLength = q_dur
                new_part.insert(q_start, el)
                last_end_q = q_start + q_dur

            # 5. Build proper musical measures
            new_part.makeMeasures(inPlace=True)
            for n in new_part.recurse().notesAndRests:
                n.voice = 1

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
