import asyncio
import math
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI(title="Neuro Observatory Engine")

CHANNELS = [
    "Fp1", "Fp2", "F3", "F4", "F7", "F8",
    "C3", "C4", "Cz", "P3", "P4",
    "T7", "T8", "O1", "O2", "Pz",
]

SAMPLE_RATE = 125
BLOCK_SIZE = 25


@app.get("/health")
def health():
    return {
        "status": "ok",
        "device": "simulated-eeg",
        "channels": len(CHANNELS),
        "sampleRateHz": SAMPLE_RATE,
    }


@app.websocket("/ws/eeg")
async def eeg_stream(websocket: WebSocket):
    await websocket.accept()
    sequence = 0

    try:
        while True:
            sample_offset = sequence * BLOCK_SIZE
            samples = []

            for channel_index in range(len(CHANNELS)):
                phase = channel_index * 0.2
                values = []

                for i in range(BLOCK_SIZE):
                    t = (sample_offset + i) / SAMPLE_RATE

                    signal = (
                        20 * math.sin(2 * math.pi * 10 * t + phase)
                        + 6 * math.sin(2 * math.pi * 6 * t)
                    )
                    values.append(round(signal, 3))

                samples.append(values)

            await websocket.send_json({
                "schemaVersion": 1,
                "deviceId": "simulated-eeg",
                "sequence": sequence,
                "timestampMs": int(time.time() * 1000),
                "sampleRateHz": SAMPLE_RATE,
                "channelLabels": CHANNELS,
                "samplesUv": samples,
            })

            sequence += 1
            await asyncio.sleep(BLOCK_SIZE / SAMPLE_RATE)

    except (WebSocketDisconnect, OSError):
        pass
