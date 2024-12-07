import mido


def midi_to_array(midi_file):
    """
    Convert a MIDI file to an array of (frequency, start_time) tuples for each track.
    Adds a silence note (0 Hz) at the end of each track to ensure no buzzers are stuck on.
    """
    mid = mido.MidiFile(midi_file)
    songs = []

    for track in mid.tracks:
        track_data = []
        accumulated_ticks = 0
        current_tempo = 500000  # Default tempo
        seconds_per_tick = mido.tick2second(1, mid.ticks_per_beat, current_tempo)
        last_note_time = 0  # To track the end of the last note

        for msg in track:
            accumulated_ticks += msg.time
            if msg.type == 'set_tempo':
                current_tempo = msg.tempo
                seconds_per_tick = mido.tick2second(1, mid.ticks_per_beat, current_tempo)
            if msg.type == 'note_on' and msg.velocity > 0:
                start_time = accumulated_ticks * seconds_per_tick
                frequency = 440.0 * (2.0 ** ((msg.note - 69) / 12.0))
                track_data.append((frequency, round(start_time, 6)))
                last_note_time = max(last_note_time, start_time)
            elif msg.type in ['note_off', 'note_on'] and msg.velocity == 0:
                start_time = accumulated_ticks * seconds_per_tick
                track_data.append((0.0, round(start_time, 6)))  # Represent silence
                last_note_time = max(last_note_time, start_time)

        # Add a final silence note to ensure no buzzers are stuck on
        final_silence_time = round(last_note_time + 0.1, 6)  # Add a small buffer if needed
        track_data.append((0.0, final_silence_time))

        songs.append(track_data)

    return songs


# Example usage
midi_file = "reward.mid"  # Replace with your MIDI file path
tracks = midi_to_array(midi_file)

# Print results for each track
for i, track in enumerate(tracks):
    print(f"Track {i}:")
    print("[")
    for note in track:
        print(f"    ({note[0]:.2f}, {note[1]:.6f}),")
    print("]")
