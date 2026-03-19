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
        Converts a MIDI file to MusicXML with metadata.
        """
        output_xml_path = self.output_dir / f"{output_name}.musicxml"
        self.logger.info(f"Converting MIDI to XML: {midi_path} -> {output_xml_path}")
        
        try:
            # Detect Metadata if reference audio provided
            tempo_bpm = 120.0
            key_tonic = "C"
            if audio_ref_path and audio_ref_path.exists():
                tempo_bpm, key_tonic = self.detect_attributes(audio_ref_path)

            # Load MIDI
            mf = music21.converter.parse(str(midi_path))
            
            # We want to preserve tracks/parts if they exist, but usually basic-pitch outputs one track.
            # We will flatten it to one part but KEEP polyphony (Recurse notes).
            
            original_part = mf.parts[0] if mf.parts else mf.flatten()
            
            new_part = music21.stream.Part()
            new_part.id = 'P1'
            new_part.partName = output_name
            
            # 1. Insert Metadata
            # Key
            new_part.insert(0, music21.key.Key(key_tonic))
            # Tempo
            new_part.insert(0, music21.tempo.MetronomeMark(number=round(tempo_bpm)))
            # Time Sig (assume 4/4 for now, detection is hard)
            new_part.insert(0, music21.meter.TimeSignature('4/4'))

            # Detect Instrument (Clef/Patch)
            name_lower = output_name.lower()
            if "bass" in name_lower:
                new_part.insert(0, music21.clef.BassClef())
                new_part.insert(0, music21.instrument.ElectricBass())
            elif "guitar" in name_lower:
                new_part.insert(0, music21.clef.TrebleClef())
                new_part.insert(0, music21.instrument.ElectricGuitar())
            elif "piano" in name_lower:
                new_part.insert(0, music21.instrument.Piano())
            elif "vocal" in name_lower or "voice" in name_lower:
                new_part.insert(0, music21.instrument.Vocalist())
            elif "drums" in name_lower or "drum" in name_lower:
                new_part.insert(0, music21.clef.PercussionClef())
                new_part.insert(0, music21.instrument.Percussion())
            else:
                new_part.insert(0, music21.instrument.Piano()) # Default

            # 2. Smart Quantization
            # Instead of destructive resampling, we iterate notes and snap start/duration.
            # Grid = 16th note (0.25)
            grid = 0.25
            
            for el in original_part.recurse().notes:
                # Snap offset (start time)
                raw_offset = el.offset
                quantized_offset = round(raw_offset / grid) * grid
                
                # Snap duration
                raw_dur = el.duration.quarterLength
                quantized_dur = round(raw_dur / grid) * grid
                if quantized_dur < grid: quantized_dur = grid # Min duration
                
                # Clone and adjust using deepcopy to safely preserve Unpitched and PercussionChord elements
                import copy
                new_el = copy.deepcopy(el)
                
                if hasattr(new_el, 'volume') and hasattr(el, 'volume') and el.volume is not None:
                    new_el.volume = el.volume
                new_el.quarterLength = quantized_dur
                
                # Insert at new offset
                new_part.insert(quantized_offset, new_el)

            # 3. Clean up notation (ties, beams)
            try:
                new_part.makeNotation(inPlace=True)
            except Exception as notation_e:
                self.logger.warning(f"makeNotation skipped (expected for percussion/Unpitched): {notation_e}")
            
            # 4. Force Voice 1 (to satisfy strict parsers)
            for n in new_part.recurse().notesAndRests:
                n.voice = 1
            
            # Write to MusicXML
            new_part.write('musicxml', fp=str(output_xml_path))
            
            return output_xml_path

        except Exception as e:
            import traceback
            self.logger.error(f"MusicXML conversion failed: {e}\n{traceback.format_exc()}")
            raise e
