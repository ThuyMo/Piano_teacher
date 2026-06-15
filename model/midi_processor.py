import sys
from pathlib import Path
from typing import Optional

import mido
from mido import MidiFile, MidiTrack, Message

def split_midi_hands(input_file_path, output_rh_path, output_lh_path):
    mid = MidiFile(input_file_path)
    
    rh_mid = MidiFile(ticks_per_beat=mid.ticks_per_beat)
    lh_mid = MidiFile(ticks_per_beat=mid.ticks_per_beat)
    rh_track = MidiTrack()
    lh_track = MidiTrack()
    rh_mid.tracks.append(rh_track)
    lh_mid.tracks.append(lh_track)
    
    # Lists to hold tuples of (absolute_tick, message)
    rh_absolute_msgs = []
    lh_absolute_msgs = []
    
    # Trailing pitch trackers for distance method
    last_rh_pitch = 67  # G4
    last_lh_pitch = 55  # G3
    
    # Maps an absolute note activation to a hand: (note_num) -> 'RH' or 'LH'
    # Using a list tracking active notes to cleanly handle duplicate overlapping notes
    active_notes = {} 
    
    # 1. Convert the merged track into an absolute timeline
    current_absolute_tick = 0
    merged_messages = mido.merge_tracks(mid.tracks)
    
    for msg in merged_messages:
        current_absolute_tick += msg.time  # Move forward in absolute time
        
        # Meta events (tempo, time signatures) must go to both tracks at the exact same absolute time
        if msg.is_meta or msg.type not in ['note_on', 'note_off']:
            rh_absolute_msgs.append((current_absolute_tick, msg.copy()))
            lh_absolute_msgs.append((current_absolute_tick, msg.copy()))
            continue
            
        if msg.type == 'note_on' and msg.velocity > 0:
            # Calculate distance to last played notes
            rh_distance = abs(msg.note - last_rh_pitch)
            lh_distance = abs(msg.note - last_lh_pitch)
            
            if rh_distance == lh_distance:
                assigned_hand = 'RH' if msg.note >= 60 else 'LH'
            elif rh_distance < lh_distance:
                assigned_hand = 'RH'
            else:
                assigned_hand = 'LH'
                
            # Track which hand owns this specific active note pitch
            if assigned_hand == 'RH':
                last_rh_pitch = msg.note
                rh_absolute_msgs.append((current_absolute_tick, msg.copy()))
                active_notes[msg.note] = 'RH'
            else:
                last_lh_pitch = msg.note
                lh_absolute_msgs.append((current_absolute_tick, msg.copy()))
                active_notes[msg.note] = 'LH'
                
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            # Find which hand turned this note on
            assigned_hand = active_notes.get(msg.note, None)
            
            if assigned_hand == 'RH':
                rh_absolute_msgs.append((current_absolute_tick, msg.copy()))
            elif assigned_hand == 'LH':
                lh_absolute_msgs.append((current_absolute_tick, msg.copy()))
            else:
                # Fallback: if untracked, send higher notes to RH, lower to LH
                if msg.note >= 60:
                    rh_absolute_msgs.append((current_absolute_tick, msg.copy()))
                else:
                    lh_absolute_msgs.append((current_absolute_tick, msg.copy()))

    # 2. Helper function to turn absolute timelines back into standard relative MIDI deltas
    def compile_absolute_to_delta_track(target_track, absolute_msg_list):
        # Sort by absolute time just to be perfectly safe
        absolute_msg_list.sort(key=lambda x: x[0])
        
        last_tick = 0
        for abs_tick, msg in absolute_msg_list:
            delta_time = abs_tick - last_tick
            msg.time = delta_time
            target_track.append(msg)
            last_tick = abs_tick

    # 3. Compile and build the final MIDI tracks
    compile_absolute_to_delta_track(rh_track, rh_absolute_msgs)
    compile_absolute_to_delta_track(lh_track, lh_absolute_msgs)
    
    # Save the output files
    rh_mid.save(output_rh_path)
    lh_mid.save(output_lh_path)
    print(f"Perfect Sync Separation complete!\nRH: {output_rh_path}\nLH: {output_lh_path}")

def extract_right_hand(
    midi_path: str,
    output_path: Optional[str] = None,
) -> Path:
    """
    Convenience wrapper: split both hands and return only the right-hand Path.
    Left-hand file is saved alongside as <stem>_LH.mid.
    """
    p = Path(midi_path)
    rh_path = str(output_path) if output_path else str(p.parent / f"{p.stem}_RH{p.suffix}")
    lh_path = str(p.parent / f"{p.stem}_LH{p.suffix}")
    split_midi_hands(midi_path, rh_path, lh_path)
    return Path(rh_path)


# --- Example Execution ---
if __name__ == "__main__":
    result = split_midi_hands(sys.argv[1], sys.argv[1].replace(".mid", "_RH.mid"), sys.argv[1].replace(".mid", "_LH.mid"))
    print(f"MIDI saved to: {result}")
