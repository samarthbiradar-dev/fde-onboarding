# Day 4 Project 5 — Voice Pipeline (STT + LLM + TTS)

A full speech-to-speech pipeline and its individual building blocks.

**Stack:**
- STT — ElevenLabs Scribe (speech-to-text)
- LLM — Llama 3.3 70B via Groq
- TTS — ElevenLabs (text-to-speech)
- Mic/Speaker — `sounddevice` + macOS `afplay`

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in ELEVENLABS_API_KEY and GROQ_API_KEY
```

`sounddevice` needs PortAudio. On macOS:
```bash
brew install portaudio
```

---

## Scripts

### 01 — Transcribe an audio file

```bash
python3 01_transcribe_file.py recording.wav
```

Sends an audio file to ElevenLabs Scribe and prints the transcript. Run `02` first to create `recording.wav`.

---

### 02 — Transcribe from microphone

```bash
python3 02_transcribe_mic.py
```

Records 5 seconds from your mic, saves as `recording.wav`, then transcribes it. Spoken words appear as text.

---

### 03 — Text to speech

```bash
python3 03_tts.py
```

Converts a hardcoded sentence to speech using ElevenLabs (George voice, `eleven_flash_v2_5` model) and plays it through your speakers via `afplay`.

---

### 04 — Streaming TTS

```bash
python3 04_tts_stream.py
```

Same as `03` but uses the streaming API. Reports time-to-first-audio-chunk (how quickly ElevenLabs starts sending audio) separately from total generation time.

---

### 05 — Full voice pipeline (capstone)

```bash
python3 05_pipeline.py
```

The complete loop:

```
You speak  →  ElevenLabs Scribe (STT)  →  Groq LLM  →  ElevenLabs TTS  →  You hear the answer
```

Press Enter when prompted, speak your question (you have 5 seconds), then listen to the answer. After each turn it prints a full latency breakdown:

```
--- Latency ---
STT (transcription):  0.82s
LLM (answer):         1.43s
TTS (speech gen):     1.21s
End-to-end:           3.46s
```

---

## Architecture

```
┌─────────────┐    WAV     ┌──────────────────┐   text    ┌──────────────┐
│  Microphone │──────────▶ │ ElevenLabs Scribe │─────────▶│  Groq LLM   │
└─────────────┘            └──────────────────┘           └──────┬───────┘
                                                                  │ text
                                                                  ▼
┌─────────────┐    MP3     ┌──────────────────┐
│   Speaker   │◀────────── │  ElevenLabs TTS  │
└─────────────┘            └──────────────────┘
```

## Voice & model config

| Setting | Value |
|---|---|
| Voice | George (`JBFqnCBsd6RMkjVDRZzb`) |
| TTS model | `eleven_flash_v2_5` (optimised for low latency) |
| STT model | `scribe_v1` |
| LLM model | `llama-3.3-70b-versatile` via Groq |
| Recording | 16kHz mono, 5 seconds |
