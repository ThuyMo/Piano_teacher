"""
Piano Game Web Server
Usage: python server.py <midi_file.mid>
Then open http://localhost:8000
"""
import asyncio
import json
import queue
import sys
import threading
from pathlib import Path

import mido
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ─── MIDI file parsing ────────────────────────────────────────────────────────

def load_notes(path):
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat
    events = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            events.append((tick, msg))
    events.sort(key=lambda x: x[0])

    notes, pending = [], {}
    tempo, last_tick, last_sec = 500_000, 0, 0.0
    for abs_tick, msg in events:
        now = last_sec + (abs_tick - last_tick) * tempo / tpb / 1_000_000
        if msg.type == 'set_tempo':
            last_tick, last_sec, tempo = abs_tick, now, msg.tempo
        elif msg.type == 'note_on' and msg.velocity > 0:
            pending[msg.note] = now
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            if msg.note in pending:
                notes.append({'pitch': msg.note, 'start': pending.pop(msg.note), 'end': now})
    return sorted(notes, key=lambda x: x['start'])


def group_notes(notes, tol=0.05):
    groups, i = [], 0
    while i < len(notes):
        t = notes[i]['start']
        grp = []
        while i < len(notes) and notes[i]['start'] - t <= tol:
            grp.append(notes[i])
            i += 1
        groups.append({'time': t, 'notes': grp})
    return groups


# ─── Shared game state ────────────────────────────────────────────────────────

notes_data   = []
groups       = []
clients      = set()
midi_q       = queue.Queue()
active_notes = set()

g_time   = 0.0
g_status = 'PLAYING'
g_idx    = 0
g_score  = 0
g_hit    = set()

# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI()
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

@app.get("/")
async def index():
    return HTMLResponse((Path(__file__).parent / "static" / "index.html").read_text())

@app.get("/notes")
async def get_notes():
    return JSONResponse({"notes": notes_data, "total": len(groups)})

@app.websocket("/ws")
async def ws_handler(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)

# ─── Game loop ────────────────────────────────────────────────────────────────

async def game_loop():
    global g_time, g_status, g_idx, g_score, g_hit, clients
    last = asyncio.get_event_loop().time()

    while True:
        await asyncio.sleep(1 / 30)
        now = asyncio.get_event_loop().time()
        dt  = now - last
        last = now

        new_presses = []
        while True:
            try:
                msg = midi_q.get_nowait()
                if msg.type == 'note_on' and msg.velocity > 0:
                    active_notes.add(msg.note)
                    new_presses.append(msg.note)
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    active_notes.discard(msg.note)
            except queue.Empty:
                break

        if g_status == 'PLAYING':
            g_time += dt
            if g_idx >= len(groups):
                g_status = 'FINISHED'
            elif g_time >= groups[g_idx]['time']:
                g_time   = groups[g_idx]['time']
                g_status = 'WAITING'
                g_hit    = set()

        elif g_status == 'WAITING':
            required = {n['pitch'] for n in groups[g_idx]['notes']}
            for p in new_presses:
                if p in required:
                    g_hit.add(p)
            if g_hit >= required:
                g_score  += 1
                g_idx    += 1
                g_status  = 'PLAYING' if g_idx < len(groups) else 'FINISHED'

        wait_pitches = (
            [n['pitch'] for n in groups[g_idx]['notes']]
            if g_status == 'WAITING' and g_idx < len(groups) else []
        )

        if clients:
            payload = json.dumps({
                'type':         'state',
                'game_time':    g_time,
                'status':       g_status,
                'score':        g_score,
                'total':        len(groups),
                'active_notes': list(active_notes),
                'wait_pitches': wait_pitches,
                'hit_pitches':  list(g_hit),
            })
            dead = set()
            for ws in list(clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            clients -= dead


def midi_listener():
    ports = mido.get_input_names()
    if not ports:
        print("No MIDI device found.")
        return
    print(f"MIDI controller: {ports[0]}")
    with mido.open_input(ports[0]) as port:
        for msg in port:
            midi_q.put(msg)


@app.on_event("startup")
async def startup():
    asyncio.create_task(game_loop())
    threading.Thread(target=midi_listener, daemon=True).start()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python server.py <path/to/file.mid>")
        sys.exit(1)

    notes_data = load_notes(sys.argv[1])
    groups     = group_notes(notes_data)
    g_time     = (groups[0]['time'] - 4.0) if groups else 0.0

    print(f"Loaded: {len(notes_data)} notes, {len(groups)} groups")
    print("Open http://localhost:8000")
    uvicorn.run(app, host='0.0.0.0', port=8000)
