"""Voice Agent Phase 3: server-side transcription, controlled language-model understanding and the
expanded, structured knowledge base."""
import builtins
import io
import re
import tempfile
import wave
from datetime import datetime
from types import SimpleNamespace

import pytest

from app import config
from app.services import stt
from app.voice_agent import knowledge_base as kb
from app.voice_agent import llm, policy, prompt, wording
from app.voice_agent.context import IST, build_runtime_context
from app.voice_agent.conversation import Conversation

from .test_voice_agent_demo import API, Call, callbacks, give_details

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MONDAY = datetime(2026, 10, 19, 11, 0, tzinfo=IST)


def wav_bytes(seconds=1.0, rate=16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\0\1" * int(seconds * rate))
    return buffer.getvalue()


class FakeTranscriber:
    def __init__(self, text="Sunday ko clinic khula hai kya?", low=False):
        self.text, self.low, self.calls = text, low, []

    def status(self):
        return {"available": True, "engine": "fake", "model": "test", "installed": True, "package": True,
                "loaded": True, "device": "cpu", "runs": "in this test", "modes": stt.MODES}

    def transcribe(self, audio, language, content_type=None):
        self.calls.append((type(audio), len(audio), language, content_type))
        return stt.Transcript(self.text, language, 1.0, 0.1, "test", "cpu", 0.3 if self.low else 0.9, self.low)


# --- Transcription endpoint and adapter -------------------------------------------------------

def test_transcribe_contract(client):
    fake = client.app.state.transcriber = FakeTranscriber()
    response = client.post(f"{API}/transcribe?language=hinglish", content=b"x" * 4000,
                           headers={"content-type": "audio/webm;codecs=opus"})
    assert response.status_code == 200
    body = response.json()
    timings = body.pop("timings")
    assert body == {"text": "Sunday ko clinic khula hai kya?", "language": "hinglish", "mode": stt.MODES["hinglish"],
                    "audio_seconds": 1.0, "processing_seconds": 0.1, "model": "test", "device": "cpu",
                    "confidence": 0.9, "low_confidence": False, "message": None, "detected_language": None,
                    "script": None, "stored": False}
    assert set(timings) == {"server_ms"} and timings["server_ms"] >= 0
    assert fake.calls == [(bytes, 4000, "hinglish", "audio/webm;codecs=opus")]
    assert "no separate Hinglish model" in body["mode"]


def test_low_confidence_transcript_carries_the_try_again_message(client):
    client.app.state.transcriber = FakeTranscriber("mm", low=True)
    body = client.post(f"{API}/transcribe?language=en", content=b"x" * 4000).json()
    assert body["low_confidence"] is True
    assert body["message"] == "I may not have caught that clearly. Please say that again, or type your message."


def test_transcribe_rejects_unknown_language(client):
    client.app.state.transcriber = FakeTranscriber()
    assert client.post(f"{API}/transcribe?language=fr", content=b"x" * 4000).status_code == 400


def test_missing_model_means_typed_input_only(client):
    assert not stt.model_installed()  # tests run without the model (see conftest)
    status = client.get(f"{API}/transcription").json()
    assert status["available"] is False and status["installed"] is False
    response = client.post(f"{API}/transcribe?language=en", content=wav_bytes())
    assert response.status_code == 503 and response.json()["error"] == "stt_unavailable"
    html = client.get("/voice-agent-demo").text
    assert "Not installed: typed input only" in html
    assert client.get("/voice-agent-demo").status_code == 200  # the page never fails


def test_page_load_does_not_load_a_model(client):
    client.get("/voice-agent-demo")
    assert client.app.state.transcriber.status()["loaded"] is False


def test_audio_is_decoded_in_memory():
    samples = stt.decode(wav_bytes(0.5, rate=22050))
    assert samples.dtype.name == "float32" and abs(len(samples) - 8000) < 400  # resampled to 16 kHz


def test_local_whisper_never_writes_audio_anywhere(monkeypatch, tmp_path):
    """The adapter decodes and transcribes from memory: no file is opened for writing, no temp file is made."""
    monkeypatch.setattr(config, "VOICE_AGENT_STT_DIR", tmp_path)
    folder = tmp_path / config.VOICE_AGENT_STT_MODEL
    folder.mkdir()
    (folder / "model.bin").write_bytes(b"x")
    (folder / "config.json").write_text("{}")
    segment = SimpleNamespace(text=" Hello there ", start=0.0, end=1.0, avg_logprob=-0.2, no_speech_prob=0.01,
                              compression_ratio=1.1)
    whisper = stt.LocalWhisper()
    whisper._model = SimpleNamespace(transcribe=lambda samples, **kw: (iter([segment]), None))
    whisper._device = "cpu"
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        assert not any(m in mode for m in "wax+"), f"audio code opened {file} for writing"
        return real_open(file, mode, *args, **kwargs)

    def no_temp(*args, **kwargs):
        raise AssertionError("audio code created a temporary file")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", no_temp)
    monkeypatch.setattr(tempfile, "mkstemp", no_temp)
    before = set(tmp_path.rglob("*"))
    result = whisper.transcribe(wav_bytes(), "en", "audio/wav")
    assert result.text == "Hello there" and result.low_confidence is False and result.confidence > 0.8
    assert set(tmp_path.rglob("*")) == before


def test_low_confidence_is_detected():
    whisper = stt.LocalWhisper()
    shaky = SimpleNamespace(text="uh", start=0.0, end=1.0, avg_logprob=-1.4, no_speech_prob=0.2, compression_ratio=1.0)
    whisper._model = SimpleNamespace(transcribe=lambda samples, **kw: (iter([shaky]), None))
    text, confidence, low = whisper._run([0.0], "hinglish")
    assert text == "uh" and low is True and confidence < 0.3
    whisper._model = SimpleNamespace(transcribe=lambda samples, **kw: (iter([]), None))
    assert whisper._run([0.0], "en") == ("", 0.0, True)


def test_hinglish_uses_the_multilingual_model_in_roman_script_mode():
    seen = {}
    whisper = stt.LocalWhisper()
    segment = SimpleNamespace(text="Sunday ko clinic khula hai kya?", start=0, end=1, avg_logprob=-0.1,
                              no_speech_prob=0.0, compression_ratio=1.0)

    def transcribe(samples, **kwargs):
        seen.update(kwargs)
        return iter([segment]), None

    whisper._model = SimpleNamespace(transcribe=transcribe)
    whisper._run([0.0], "hinglish")
    assert seen["language"] == "en" and "mujhe appointment chahiye" in seen["initial_prompt"]


def test_too_short_or_too_long_recordings_are_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "VOICE_AGENT_STT_DIR", tmp_path)
    (tmp_path / config.VOICE_AGENT_STT_MODEL).mkdir()
    for name in ("model.bin", "config.json"):
        (tmp_path / config.VOICE_AGENT_STT_MODEL / name).write_text("x")
    whisper = stt.LocalWhisper()
    with pytest.raises(stt.ValidationError):
        whisper.transcribe(b"x" * 10, "en")
    with pytest.raises(stt.ValidationError):
        whisper.transcribe(b"x" * (config.VOICE_AGENT_STT_MAX_BYTES + 1), "en")
    monkeypatch.setattr(config, "VOICE_AGENT_STT_MAX_SECONDS", 0.5)
    with pytest.raises(stt.ValidationError):
        whisper.transcribe(wav_bytes(2.0), "en")


# --- Controlled language model ---------------------------------------------------------------

class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply or {}, error, []

    def complete_json(self, system, user, schema, timeout):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error:
            raise llm.LLMUnavailable(self.error)
        return self.reply


def decision(intent, ids=(), doctor="not_mentioned", when="", need="caller wants something"):
    return {"intent": intent, "answer_ids": list(ids), "preferred_doctor": doctor, "preferred_time": when,
            "caller_need": need}


def talk(reply=None, error=None, language="en", context=None):
    provider = FakeProvider(reply, error)
    conversation = Conversation(context or build_runtime_context(MONDAY), language, router=llm.Router(provider))
    return conversation, provider


def say(conversation, text, saved=None):
    return conversation.handle(text, None, lambda details, intent: (saved.append((details, intent)) if saved is not None
                                                                     else None) or 1)


def test_router_prompt_is_compact_static_and_has_no_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret")
    context = build_runtime_context(MONDAY, caller_number="9876543210")
    system = llm.system_prompt(context)
    # Phase 3.1: a short prompt that is identical on every turn (no clock, no caller), so it can be cached.
    assert system == llm.system_prompt(build_runtime_context(datetime(2026, 10, 18, 23, 0, tzinfo=IST)))
    assert len(system) < len(prompt.render_system_prompt(context)) and len(system) < 9000
    assert "ROUTING TASK" in system and "procedure_root_canal:" in system and "service:implants:" in system
    assert "Never answer from your own knowledge" in system and "never diagnose" in system.lower()
    for secret in ("sk-test-secret", "9876543210", "43210"):
        assert secret not in system
    for not_provided in ("parking:", "walk_in:", "accessibility:"):
        assert not_provided not in system  # nothing to answer with: these always become callbacks
    schema = llm.decision_schema()
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]["intent"]["enum"]) == set(llm.INTENTS)


def test_router_answers_only_with_approved_wording():
    conversation, provider = talk(decision("answer", ["hours", "parking", "made_up_id"],
                                           need="Closes at 6pm, parking free, treatment costs ₹2000"))
    turn = say(conversation, "yo, when do you lot shut up shop")
    texts = [m.text for m in turn.messages]
    assert texts == [wording.line("hours", "en"), wording.line("anything_else", "en")]
    assert turn.engine == "llm" and turn.source == "approved_knowledge"
    joined = " ".join(texts)
    assert "₹" not in joined and "2000" not in joined and "6pm" not in joined and "parking" not in joined
    payload = provider.calls[0]["user"]
    assert '"caller_said": "yo, when do you lot shut up shop"' in payload
    assert '"selected_language": "en"' in payload


def test_router_service_ids_and_hindi_selection():
    conversation, _ = talk(decision("answer", ["service:braces_aligners"]), language="hi")
    turn = say(conversation, "क्या आप टेढ़े दांत ठीक करते हैं?")
    assert turn.messages[0].text == "जी हाँ, हमारे यहाँ ब्रेसेस और क्लियर अलाइनर की सुविधा है।"


def test_hinglish_reply_is_roman_and_spoken_from_hindi():
    conversation, _ = talk(decision("answer", ["procedure_root_canal"]), language="hinglish")
    turn = say(conversation, "root canal kya hota hai")
    entry = kb.BY_ID["procedure_root_canal"]
    assert turn.messages[0].text == entry.text["hinglish"] and not DEVANAGARI.search(turn.messages[0].text)
    assert turn.messages[0].speech_text == entry.text["hi"]


@pytest.mark.parametrize("raw", [
    {"intent": "make_booking", "answer_ids": []},
    {"answer_ids": ["hours"]},
    "not a dict",
])
def test_invalid_router_replies_fall_back_to_rules(raw):
    conversation, _ = talk(raw)
    turn = say(conversation, "yo, when do you lot shut up shop")
    assert turn.engine == "rules" and "language model unavailable" in turn.engine_note and turn.handled_by == "fallback"
    assert turn.messages[0].text == policy.unknown_information("not_approved", "en").text  # never a guess


def test_router_error_falls_back_to_rules():
    conversation, provider = talk(error="Ollama: ConnectTimeout")
    turn = say(conversation, "how is the weather near the clinic")
    assert turn.engine == "rules" and turn.engine_note == "Rule-based policy (language model unavailable: Ollama: ConnectTimeout)"
    assert turn.path == "unknown" and "don't want to guess" in turn.messages[0].text and len(provider.calls) == 1


def test_clear_rule_matches_do_not_wait_for_the_model():
    conversation, provider = talk(decision("answer", ["parking"]))
    turn = say(conversation, "What are your opening hours?")
    assert provider.calls == [] and turn.handled_by == "rule" and turn.engine_note == "Rule-based policy (clear match)"


def test_explicit_requests_are_routed_by_rules_without_the_model():
    conversation, provider = talk(decision("answer", ["hours"]))
    turn = say(conversation, "I need to reschedule my appointment")
    assert provider.calls == [] and turn.topic == "reschedule_request"
    assert turn.engine_note == "Rule-based policy (explicit request)"


def test_answer_without_ids_becomes_unknown():
    conversation, _ = talk(decision("answer", []))
    turn = say(conversation, "What's the wifi password?")
    assert turn.path == "unknown" and "don't want to guess" in turn.messages[0].text


@pytest.mark.parametrize("text, path", [
    ("My face is swollen and the swelling is spreading to my eye", "emergency"),
    ("Which painkiller should I take?", "clinical"),
    ("My tooth hurts when I drink cold water", "tooth_pain"),
    ("Do I need a root canal?", "unknown"),
])
def test_safety_rules_run_before_and_without_the_model(text, path):
    conversation, provider = talk(decision("answer", ["procedure_root_canal"]))
    turn = say(conversation, text)
    assert provider.calls == []  # never sent to the language model
    assert turn.path == path and turn.engine == "rules" and turn.engine_note.startswith("Safety rule")
    if path == "emergency":
        assert "112" in turn.messages[0].text and turn.source == "emergency_escalation"
    else:
        assert all("112" not in m.text for m in turn.messages)


def test_model_clinical_decision_gives_the_safe_reply():
    conversation, _ = talk(decision("clinical"))
    turn = say(conversation, "is it normal for the root canal tooth to feel weird")
    assert turn.path == "clinical" and turn.source == "safety_fallback"
    assert turn.messages[0].text == wording.line("clinical", "en") and "112" not in turn.messages[0].text


def test_model_cannot_skip_confirmation_or_the_one_callback_rule():
    saved = []
    conversation, provider = talk(decision("appointment_request", doctor="smriti_raj", when="Saturday morning"))
    say(conversation, "I'd like to pop in to see Dr Smriti sometime", saved)
    assert conversation.state == "offer_callback" and saved == []
    for text in ("yes", "Asha", "9876543210", "check-up", "new"):
        say(conversation, text, saved)
    assert conversation.state == "confirm_details" and saved == []  # doctor and time were already given
    say(conversation, "yes", saved)
    assert len(saved) == 1 and saved[0][1] == "appointment_request"
    assert "Preferred doctor: Dr. Smriti Raj. Preferred day/time: Saturday morning." in saved[0][0].notes
    provider.reply = decision("callback_request")
    turn = say(conversation, "also call me about something else", saved)
    say(conversation, "Asha", saved)
    assert len(saved) == 1 and "already passed a callback request" in " ".join(m.text for m in turn.messages)


# --- Expanded approved answers (rules, no model) ----------------------------------------------

@pytest.mark.parametrize("question, topic, source", [
    ("What services do you offer?", "services_list", "approved_knowledge"),
    ("What is a root canal?", "procedure_root_canal", "approved_knowledge"),
    ("How is an implant done?", "procedure_implant", "approved_knowledge"),
    ("What are braces?", "procedure_braces", "approved_knowledge"),
    ("Do I need a consultation first?", "consultation_first", "approved_knowledge"),
    ("What is the difference between a consultation and a procedure?", "consultation_vs_procedure", "approved_knowledge"),
    ("Which doctor handles braces?", "doctor_specialties", "approved_knowledge"),
    ("What should I bring?", "what_to_bring", "approved_knowledge"),
    ("What happens on the first visit?", "first_visit", "approved_knowledge"),
    ("How early should I arrive?", "arrival_checkin", "approved_knowledge"),
    ("Can I speak in Hindi?", "languages", "approved_knowledge"),
    ("How do I get there?", "directions", "approved_knowledge"),
    ("How do I book an appointment?", "how_to_book", "approved_knowledge"),
    ("Is there parking?", "parking", "callback_required"),
    ("Do you have wheelchair access?", "accessibility", "callback_required"),
    ("Do you take walk-ins?", "walk_in", "callback_required"),
    ("Are you open on Diwali?", "holidays", "callback_required"),
    ("What is your cancellation policy?", "cancellation_policy", "callback_required"),
    ("What can I eat after my extraction?", "clinical_question", "safety_fallback"),
    ("What does my x-ray report show?", "clinical_question", "safety_fallback"),
])
def test_expanded_answers(client, question, topic, source):
    call = Call(client)
    call.say(question)
    assert call.last["decision"]["topic"] == topic and call.last["decision"]["source"] == source
    assert call.last["decision"]["engine_note"]


def test_consultation_fee_may_be_answered_but_treatment_prices_never(client):
    call = Call(client)
    call.say("Implant ka consultation fee kitna hai?", language="hinglish")
    assert call.last["decision"]["topic"] == "consultation_fee" and "500 rupees" in call.text
    call.say("How much does an implant cost?", language="en")
    assert call.last["decision"]["topic"] == "treatment_cost" and "can't quote treatment prices" in call.text
    assert set(re.findall(r"\d+", call.text)) <= {"500"}


@pytest.mark.parametrize("question, intent, label, ask", [
    ("I want to reschedule my appointment", "reschedule_request", "Reschedule request", "ask_reason_reschedule"),
    ("Please cancel my appointment", "cancellation_request", "Cancellation request", "ask_reason_cancel"),
    ("Is my appointment confirmed?", "booking_status", "Booking status enquiry (not verified on the call)", "ask_reason_status"),
])
def test_appointment_changes_become_the_right_callback(client, question, intent, label, ask):
    call = Call(client)
    call.say(question)
    assert call.last["decision"]["topic"] == intent and call.last["state"] == "offer_callback"
    call.say("yes")
    call.say("Ravi")
    call.say("9811122233")
    assert call.text == wording.line(ask, "en")
    call.say("The one on Friday with Dr Raj")
    assert call.last["state"] == "confirm_details"
    call.say("yes")
    created = call.last["callback_created"]
    assert created["category"] == "appointment"
    task = next(t for t in callbacks(client) if t["id"] == created["id"])
    assert task["reason"] == f"{label}: The one on Friday with Dr Raj"


@pytest.mark.parametrize("question, label", [
    ("I missed a call from this number", "Missed-call callback"),
    ("I filled the contact form on your website", "Website or contact-form enquiry"),
    ("I want to complain about my last visit", "Complaint: needs staff follow-up"),
    ("I need a copy of my dental records", "Patient records request"),
])
def test_other_callback_intents(client, question, label):
    call = Call(client)
    call.say(question)
    give_details(call, reason=None) if call.last["decision"]["topic"] not in ("missed_call",) else None
    if call.last["state"] == "offer_callback":
        give_details(call)
    call.say("yes")
    task = next(t for t in callbacks(client) if t["id"] == call.last["callback_created"]["id"])
    assert task["reason"].startswith(label + ": ")


def test_panel_questions_never_promise_eligibility(client):
    for language in ("en", "hi", "hinglish"):
        call = Call(client, language=language)
        call.say("Is my ECHS card accepted? Am I eligible?")
        assert call.last["decision"]["topic"] == "panel" and call.last["decision"]["source"] == "callback_required"
        text = call.text.lower()
        assert "eligible" not in text.replace("eligibility", "") and "accepted" not in text and "covered" not in text
    for versions in (wording.LINES["panel"], wording.LINES["panel_cghs"]):
        for text in versions.values():
            assert "ECHS-empanelled" not in text and "accept" not in text.lower()


# --- Hinglish microphone examples -----------------------------------------------------------

@pytest.mark.parametrize("heard, topic, path", [
    ("Mujhe root canal ke liye appointment chahiye.", "appointment_request", "unknown"),
    ("Sunday ko clinic khula hai kya?", "hours", "answer"),
    ("Mujhe receptionist se baat karni hai.", "human_request", "human_request"),
    ("Implant ka consultation fee kitna hai?", "consultation_fee", "answer"),
    # The same phrases as a transcript that came back partly in Devanagari
    ("मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए।", "appointment_request", "unknown"),
    ("संडे को क्लिनिक खुला है क्या?", "hours", "answer"),
    ("मुझे रिसेप्शनिस्ट से बात करनी है।", "human_request", "human_request"),
])
def test_hinglish_phrases_reply_in_roman_hinglish(client, heard, topic, path):
    call = Call(client, language="hinglish", transfer="unavailable")
    call.say(heard, language="hinglish")
    assert call.last["language"] == "hinglish"  # the selected language is kept whatever the transcript's script
    assert call.last["decision"]["topic"] == topic and call.last["decision"]["path"] == path
    for message in call.last["messages"]:
        assert not DEVANAGARI.search(message["text"]), message["text"]  # replies in Roman Hinglish
        assert DEVANAGARI.search(message["speech_text"])  # spoken by the Hindi voice


def test_root_canal_appointment_keeps_the_callers_own_words_as_the_reason(client):
    call = Call(client, language="hinglish")
    call.say("मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए।")
    give_details(call, name="Asha", patient="pehli baar", doctor="koi bhi", when="Saturday subah")
    assert "मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए" in call.text  # never transliterated in what is shown
    call.say("haan")
    task = next(t for t in callbacks(client) if t["id"] == call.last["callback_created"]["id"])
    assert task["reason"] == "Appointment request: मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए।"
    assert "New patient" in task["notes"] and "Saturday subah" in task["notes"]


def test_matching_normalisation_is_for_matching_only():
    original = "संडे को क्लिनिक खुला है क्या?"
    matched = policy.matching_text(original)
    assert matched.startswith(original) and "sunday ko clinic khula hai kya" in matched
    assert policy.matching_text("Sunday ko clinic khula hai kya?") == "Sunday ko clinic khula hai kya?"


def test_heard_transcript_is_passed_to_the_model_with_the_selected_language(client):
    provider = FakeProvider(decision("answer", ["hours"]))
    client.app.state.voice_agent_router = llm.Router(provider)
    call = Call(client, language="hinglish")
    response = client.post(f"{API}/{call.id}/message",
                           json={"text": "bhai aapka scene kya hai", "language": "hinglish",
                                 "heard": "bhai aapka seen kya hai"}).json()
    assert response["decision"]["engine"] == "llm" and response["decision"]["source_label"] == "Approved knowledge"
    payload = provider.calls[0]["user"]
    assert '"speech_recognised_as": "bhai aapka seen kya hai"' in payload
    assert '"selected_language": "hinglish"' in payload


# --- Knowledge base structure ----------------------------------------------------------------

def test_knowledge_base_structure():
    required = {"clinic_profile", "location_and_directions", "hours_and_closures", "contact_details", "doctors",
                "services", "visit_logistics", "appointment_policies", "fees_and_payments", "panels_and_insurance",
                "safe_general_answers", "callback_required_topics", "clinical_refusal_topics", "urgent_symptom_topics",
                "language_translations"}
    assert set(kb.CATEGORIES) == required
    for entry in kb.ENTRIES:
        assert entry.category in kb.CATEGORIES
        assert entry.status in (kb.APPROVED_BRIEF, kb.SYSTEM_FACT, kb.NEEDS_APPROVAL, kb.NOT_PROVIDED)
        if entry.status == kb.NOT_PROVIDED:
            assert entry.lead and set(entry.lead) == {"en", "hi", "hinglish"} and entry.text is None
        else:
            spoken = {lang: entry.say(lang) for lang in ("en", "hi", "hinglish")}
            assert all(spoken.values()) and DEVANAGARI.search(spoken["hi"]) and not DEVANAGARI.search(spoken["hinglish"])
            for text in spoken.values():
                assert "112" not in text and "₹" not in text and "http" not in text and "\n" not in text
    assert {e.id for e in kb.needing_owner_review()} >= {"first_visit", "procedure_root_canal", "parking", "walk_in"}
    assert kb.CALLBACK_REQUIRED_TOPICS and kb.CLINICAL_REFUSAL_TOPICS and kb.URGENT_SYMPTOM_TOPICS


def test_doctor_wording_assumes_no_gender():
    for entry in kb.ENTRIES:
        if entry.text:
            assert not re.search(r"\b(?:he|she|his|her|him)\b", entry.text["en"], re.I), entry.id


def test_procedure_explanations_never_recommend():
    for entry in kb.ENTRIES:
        if entry.id.startswith("procedure_"):
            assert re.search(r"doctor|Doctor", entry.text["en"])
            assert not re.search(r"\byou (?:should|need|must)\b", entry.text["en"], re.I)


def test_provider_configuration(monkeypatch):
    monkeypatch.setattr(config, "VOICE_AGENT_LLM_PROVIDER", "none")
    assert llm.router_from_config() is None
    monkeypatch.setattr(config, "VOICE_AGENT_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "VOICE_AGENT_LLM_MODEL", "")
    router = llm.router_from_config()
    assert router.status() == {"enabled": True, "provider": "ollama", "model": "qwen3:8b"}
    monkeypatch.setattr(config, "VOICE_AGENT_LLM_PROVIDER", "anthropic")
    assert llm.router_from_config().status()["model"] == "claude-opus-5-5"


def test_ollama_provider_parses_constrained_json(monkeypatch):
    import httpx

    sent = {}

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"intent": "greeting"}'}}

    def post(url, json, timeout):
        sent.update(url=url, body=json, timeout=timeout)
        return Reply()

    monkeypatch.setattr(httpx, "post", post)
    provider = llm.OllamaProvider("qwen3:8b", "http://127.0.0.1:11434/")
    assert provider.complete_json("system", "user", {"type": "object"}, 5) == {"intent": "greeting"}
    assert sent["url"] == "http://127.0.0.1:11434/api/chat" and sent["body"]["format"] == {"type": "object"}
    assert sent["body"]["stream"] is False and sent["timeout"] == 5

    def fail(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(llm.LLMUnavailable):
        provider.complete_json("system", "user", {}, 5)
