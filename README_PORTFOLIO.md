# Multilingual AI Voice Receptionist

A portfolio demo of a clinic operations platform with a multilingual AI voice receptionist. It combines a receptionist dashboard with a browser-based voice agent that handles routine enquiries safely, captures callback requests, and routes clinical questions to humans.

> **Portfolio/demo project.** All public-facing data must be fictional sample data. Do not use it with real patients or as a medical system without authentication, privacy controls, clinic approval, and production telephony integration.

## Highlights

- Voice-agent demo in English, Hindi, and Hinglish
- Local microphone transcription with Faster-Whisper
- Controlled AI answer selection with approved knowledge only
- Rule-based medical-safety, emergency, and human-handoff paths
- Low-confidence speech review before an action is taken
- Local text-to-speech with cancellation-safe playback
- Optional consented reference-voice experiment, with a standard voice fallback
- Appointment, callback, follow-up, waitlist, notification, and QR check-in workflows
- Doctor workspace, schedule, patient timeline, and operational analytics
- Extensive automated test coverage for workflow, privacy, safety, and browser interaction

## Architecture

```text
Browser microphone
  → local speech-to-text
  → deterministic safety and workflow rules
  → controlled intent/approved-answer selection
  → clinic operations services
  → local text-to-speech
  → browser playback
```

The voice agent does not diagnose, prescribe medication, provide treatment advice, or invent clinic information. Uncertain, clinical, payment-panel, and unsupported questions are routed to a receptionist callback workflow.

## Tech stack

- Python, FastAPI, SQLAlchemy, SQLite
- Jinja templates, vanilla JavaScript, CSS
- Faster-Whisper for local speech-to-text
- Ollama for constrained intent selection where enabled
- Piper for local text-to-speech
- Optional local reference-voice backend for a consented demo experiment
- Pytest with API, service, browser, and audio-flow tests

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8001
```

Open:

- Reception dashboard: <http://127.0.0.1:8001>
- Voice-agent demo: <http://127.0.0.1:8001/voice-agent-demo>
- Patient assistant: <http://127.0.0.1:8001/assistant>

Run tests:

```bash
.venv/bin/python -m pytest
```

Voice features require optional local model downloads. Keep model files, generated audio, reference clips, databases, secrets, and real clinic configuration out of version control.

## Before publishing

Replace every real clinic reference with fictional portfolio data, including names, addresses, phone numbers, emails, doctors, policies, and knowledge-base content. Do not publish:

- patient or caller records;
- local databases or recordings;
- API keys, environment files, or model credentials;
- consented voice-reference clips or generated cloned speech;
- owner-only documents or deployment configuration.

## Current limitations

- Browser demo only: no live phone number or telephony provider is connected.
- No authentication or role-based production access controls.
- No production compliance, retention, consent, or audit policy.
- Knowledge and language wording need clinic-owner review before real use.
- The optional reference voice is a local, consented demonstration feature only.

## What I learned

This project explores the practical constraints of voice AI: latency, multilingual speech recognition, safe action-taking, fallbacks, cancellation handling, privacy boundaries, and keeping an AI assistant operationally useful without letting it invent medical or clinic information.
