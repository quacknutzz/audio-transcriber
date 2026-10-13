import music21

midi_path = r"C:\Users\rishi\.gemini\antigravity\scratch\audio_transcriber\backend\processed\midi\Taylor Swift - Love Story_other_mt3.mid"
mf = music21.converter.parse(midi_path)
original_part = mf.parts[0] if mf.parts else mf.flatten()

new_part = music21.stream.Part()
grid = 0.25

max_offset = 0

for el in original_part.flatten().notes:
    raw_offset = el.offset
    quantized_offset = round(raw_offset / grid) * grid
    if quantized_offset > max_offset: max_offset = quantized_offset
    
    raw_dur = el.duration.quarterLength
    quantized_dur = round(raw_dur / grid) * grid
    if quantized_dur < grid: quantized_dur = grid
    
    import copy
    new_el = copy.deepcopy(el)
    new_el.quarterLength = quantized_dur
    new_part.insert(quantized_offset, new_el)

print(f"Max absolute offset in song: {max_offset} beats")
print(f"Total notes: {len(new_part.elements)}")

chordified = new_part.chordify()
print(f"Total elements after chordify: {len(chordified.elements)}")
