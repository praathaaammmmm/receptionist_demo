"""Multilingual call demo (English, Hindi, Hinglish), local voice selection and Back to dashboard."""
import io
import json
import re
import string
import wave
from pathlib import Path

import pytest

from app import config, knowledge, knowledge_translations as wording
from app.services import call_language, tts

from .test_assistant import slot_options

ROOT = Path(__file__).resolve().parent.parent
REAL_VOICES = ROOT / "voices"
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
FIREFOX_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:157.0) Gecko/20100101 Firefox/157.0"


class Call:
    """Drives the call-demo endpoints in one language, the way the call screen does."""

    def __init__(self, client, language="en"):
        self.client, self.language = client, language
        response = client.post("/api/call-demo/start", json={"language": language})
        assert response.status_code == 201, response.text
        body = response.json()
        self.id, self.log = body["call"]["id"], body["call"]
        self.reply = body["reply"]
        self.state = self.reply["state"]
        self.transcript = [m["text"] for m in self.reply["messages"]]

    def send(self, text="", action=None, value=None, language=None):
        response = self.client.post(
            f"/api/call-demo/{self.id}/message",
            json={"text": text, "action": action, "value": value, "state": self.state, "language": language or self.language},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        self.reply, self.log, self.state = body["reply"], body["call"], body["reply"]["state"]
        self.transcript += [m["text"] for m in self.reply["messages"]]
        return self.reply

    def shortcut(self, phrase):
        return self.send(action="say", value=phrase)

    def choose(self, action, value=None):
        option = next(o for o in self.reply["options"] if o["action"] == action and (value is None or o["value"] == value))
        return self.send(action=option["action"], value=option["value"])

    def end(self, language=None):
        response = self.client.post(f"/api/call-demo/{self.id}/end", json={"language": language} if language else None)
        assert response.status_code == 200
        return response.json()

    @property
    def text(self):
        return "\n".join(self.transcript)


def logged(client, call_id):
    return next(c for c in client.get("/api/calls").json() if c["id"] == call_id)


# --- Approved wording ---------------------------------------------------------------
def _fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _roman_words(text):
    """Latin-letter words left after removing {placeholders} (the Hindi voice reads those badly)."""
    return re.findall(r"[A-Za-z]{2,}", re.sub(r"\{\w+\}", "", text))


def test_every_approved_message_has_all_versions_with_the_same_data():
    for key, versions in wording.MESSAGES.items():
        assert set(versions) == {*wording.LANGUAGE_CODES, "hinglish_speech"}, key
        assert _fields(versions["hi"]) == _fields(versions["en"]) == _fields(versions["hinglish"]) == _fields(versions["hinglish_speech"]), key
        assert DEVANAGARI.search(versions["hi"]), f"{key}: Hindi must be written in Devanagari"
        assert not DEVANAGARI.search(versions["hinglish"]), f"{key}: Hinglish is Roman Hindi"
        # The reviewed Hinglish voice script is Devanagari, with no Roman Hinglish left in it.
        assert DEVANAGARI.search(versions["hinglish_speech"]), key
        assert _roman_words(versions["hinglish_speech"]) == [], (key, _roman_words(versions["hinglish_speech"]))
    for label, versions in wording.LABELS.items():
        assert set(versions) == {"hi", "hinglish"}, label
        assert DEVANAGARI.search(versions["hi"]), label
    for message, versions in wording.SERVICE_MESSAGES.items():
        assert DEVANAGARI.search(versions["hi"]), message
        assert DEVANAGARI.search(versions["hinglish_speech"]) and not _roman_words(versions["hinglish_speech"]), message


def test_required_call_messages_are_covered():
    for key in ("voice_greeting", "welcome", "topic_hours", "closed_day", "closed_day_next", "ask_name", "ask_mobile",
                "ask_service", "ask_doctor", "ask_date", "slots_three", "slot_option", "confirm_details", "booking_saved",
                "booking_status", "callback_human", "callback_reference", "callback_clinical", "urgent_note",
                "waitlist_offer", "waitlist_joined", "how_can_i_help", "choose", "callback_unsupported", "goodbye"):
        assert key in wording.MESSAGES, key


def test_every_message_key_the_assistant_uses_is_approved():
    source = (ROOT / "app/services/assistant.py").read_text()
    used = set(re.findall(r'_t\(\s*"(\w+)"', source)) | {f"callback_{c}" for c in knowledge.CALLBACK_INTROS}
    used |= {f"topic_{t['id']}" for t in knowledge.TOPICS}
    assert used and used <= set(wording.MESSAGES), used - set(wording.MESSAGES)


def test_translations_contain_no_medical_advice():
    everything = " ".join(v for versions in wording.MESSAGES.values() for v in versions.values()).lower()
    for advice in ("paracetamol", "ibuprofen", "antibiotic", "you should take", "mg", "पैरासिटामोल", "लेनी चाहिए"):
        assert advice not in everything


# --- Replies per language ---------------------------------------------------------
def test_greeting_is_chosen_by_language(client):
    english, hindi, hinglish = Call(client, "en"), Call(client, "hi"), Call(client, "hinglish")
    assert english.transcript[0].startswith("Thank you for calling Smriti Raj Dentistry. The clinic is closed")
    assert hindi.transcript[0] == "Smriti Raj Dentistry में कॉल करने के लिए धन्यवाद। इस समय क्लिनिक बंद है, इसलिए आप हमारे स्वचालित असिस्टेंट से बात कर रहे हैं।"
    assert "चिकित्सा सलाह नहीं दे सकती" in hindi.transcript[1]
    assert hinglish.transcript[0].startswith("Smriti Raj Dentistry ko call karne ke liye dhanyavaad.")
    assert not DEVANAGARI.search(hinglish.text)
    assert [english.reply["language"], hindi.reply["language"], hinglish.reply["language"]] == ["en", "hi", "hinglish"]
    # The language is stored on the simulated call log.
    assert [logged(client, c.id)["language"] for c in (english, hindi, hinglish)] == ["en", "hi", "hinglish"]


def test_opening_hours_in_each_language(client):
    for language, expected in (("en", knowledge.CLINIC_HOURS), ("hi", wording.MESSAGES["topic_hours"]["hi"]),
                               ("hinglish", wording.MESSAGES["topic_hours"]["hinglish"])):
        call = Call(client, language)
        reply = call.shortcut("What are your opening hours?")
        assert reply["messages"][0]["text"] == expected
        assert call.end()["call"]["outcome"] == "FAQ_ANSWERED"


def test_hindi_sunday_closure(client):
    call = Call(client, "hi")
    reply = call.shortcut("Can I come on Sunday?")
    assert reply["messages"][0]["text"].startswith("Smriti Raj Dentistry रविवार को बंद रहता है।")
    assert client.get("/api/callbacks").json() == []
    # Asked in Hindi, the same closure rule applies.
    typed = call.send("क्या मैं रविवार को आ सकता हूँ?")
    assert typed["messages"][0]["text"].startswith("Smriti Raj Dentistry रविवार को बंद रहता है।")
    assert not [o for o in typed["options"] if "रविवार" in o["label"]]
    assert call.end()["call"]["outcome"] == "FAQ_ANSWERED"


def test_hindi_clinical_question_gets_the_safety_response_and_a_callback(client):
    call = Call(client, "hi")
    reply = call.shortcut("I have severe tooth pain; what medicine should I take?")
    first = reply["messages"][0]["text"]
    assert "न ही कोई निदान या इलाज सुझा सकती हूँ" in first
    assert wording.MESSAGES["urgent_note"]["hi"] in first  # emergency wording, in Hindi
    assert reply["answered"] is None
    assert reply["input"]["label"] == "नाम"
    call.send("किरण उदाहरण")
    call.send("5550910003")
    task = client.get("/api/callbacks").json()[0]
    assert task["reason"].startswith("Clinical question the assistant did not answer")
    assert task["status"] == "OPEN" and task["name"] == "किरण उदाहरण"
    assert "C-" in call.text and "हमारा स्टाफ़ क्लिनिक के समय में आपसे संपर्क करेगा" in call.text
    assert call.end()["call"]["outcome"] == "CALLBACK_CREATED"


def test_typed_hindi_and_hinglish_follow_the_same_rules(client):
    call = Call(client, "hi")
    assert call.send("दांत में दर्द है, कौन सी दवा लूँ?")["state"]["data"]["cb"]["category"] == "clinical"
    call = Call(client, "hinglish")
    assert call.send("Mere daant mein dard hai")["state"]["data"]["cb"]["category"] == "clinical"
    call = Call(client, "hi")
    assert call.send("मुझे किसी व्यक्ति से बात करनी है")["state"]["data"]["cb"]["category"] == "human"
    call = Call(client, "hinglish")
    assert call.send("Mujhe appointment book karna hai")["state"]["flow"] == "booking"


def test_hindi_booking_keeps_data_values_and_the_booking_rules(client):
    call = Call(client, "hi")
    reply = call.shortcut("I need to book a consultation.")
    assert reply["messages"][0]["text"] == wording.MESSAGES["booking_guidance"]["hi"]
    assert [o["label"] for o in reply["options"][:2]] == ["नए मरीज़", "पुराने मरीज़"]
    call.choose("pick", "new")
    call.send("निशा उदाहरण")
    call.send("555 091 0001")
    call.choose("skip")
    reply = call.send(action="pick", value=client.get("/api/services").json()[0]["id"])
    assert "Dr. Anika Rao, General Dentistry" in [o["label"] for o in reply["options"]]  # names are data, unchanged
    call.choose("pick", "any")
    reply = call.choose("pick", "earliest")
    slots = slot_options(reply)
    assert len(slots) == 3
    # The three offered times are read out as options 1, 2 and 3 in Hindi, with times and doctors unchanged.
    readout = [m["text"] for m in reply["messages"] if m.get("key") == "slot_option"]
    assert [line.split(":")[0] for line in readout] == ["विकल्प 1", "विकल्प 2", "विकल्प 3"]
    for line, slot in zip(readout, slots):
        day, time, doctor = slot["params"]["day"], slot["params"]["time"], slot["params"]["doctor"]
        assert time in line and doctor in line and time in slot["label"]
        assert not re.search(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", line + slot["label"])  # weekday names in Hindi
    reply = call.send(action="slot", value=slots[0]["value"])
    assert reply["messages"][-1]["text"].startswith("कृपया विवरण जाँच लें:")
    assert "• मोबाइल: 5550910001" in reply["messages"][-1]["text"]
    reply = call.choose("confirm")
    booking = reply["booking"]
    assert booking["status"] == "PENDING"
    assert reply["messages"][0]["text"] == "धन्यवाद, निशा उदाहरण। आपका कंसल्टेशन अनुरोध सेव हो गया है।"
    assert f"#{booking['reference']}" in reply["messages"][1]["text"]

    log = call.end()["call"]
    assert log["outcome"] == "BOOKING_CREATED" and log["appointment_id"] == booking["reference"]
    assert log["language"] == "hi" and log["caller_mobile"] == "5550910001"
    saved = next(a for a in client.get("/api/appointments").json() + client.get("/api/appointments", params={"scope": "today"}).json()
                 if a["id"] == booking["reference"])
    assert saved["source"] == "AI_DEMO" and saved["status"] == "PENDING"


def test_hinglish_callback_and_waitlist_behave_as_in_english(client):
    call = Call(client, "hinglish")
    reply = call.shortcut("I want to speak to a person.")
    assert reply["messages"][0]["text"] == wording.MESSAGES["callback_human"]["hinglish"]
    call.send("Ravi Example")
    reply = call.send("5550910002")
    assert reply["callback"]["status"] == "OPEN"
    assert reply["messages"][0]["text"] == "Dhanyavaad, Ravi Example. Maine aapki request front desk tak pahuncha di hai."
    assert client.get("/api/callbacks").json()[0]["reason"] == "Asked to speak to a person."
    assert call.end()["call"]["outcome"] == "CALLBACK_CREATED"

    call = Call(client, "hinglish")
    call.shortcut("I need to book a consultation.")
    call.choose("pick", "new")
    call.send("Wait Example")
    call.send("5550910004")
    call.choose("skip")
    call.send(action="pick", value=client.get("/api/services").json()[0]["id"])
    call.choose("pick", "any")
    call.choose("pick", "earliest")
    reply = call.choose("waitlist")
    assert reply["messages"][0]["text"] == wording.MESSAGES["waitlist_offer"]["hinglish"]
    reply = call.choose("pick", "MORNING")
    assert reply["waitlist"]["status"] == "WAITING"
    assert reply["messages"][0]["text"] == "Dhanyavaad, Wait Example. Aapka naam hamari waitlist mein hai."
    assert reply["waitlist"]["reference"] in reply["messages"][1]["text"]


def test_switching_language_mid_call_changes_the_next_reply_and_the_log(client):
    call = Call(client, "en")
    assert call.shortcut("What are your opening hours?")["messages"][0]["text"] == knowledge.CLINIC_HOURS
    reply = call.send(action="say", value="What are your opening hours?", language="hi")
    assert reply["messages"][0]["text"] == wording.MESSAGES["topic_hours"]["hi"]
    assert logged(client, call.id)["language"] == "hi"
    ended = call.end(language="hinglish")
    assert ended["call"]["language"] == "hinglish"
    assert ended["goodbye"]["text"] == "Smriti Raj Dentistry ko call karne ke liye dhanyavaad. Namaste."


def test_english_call_is_unchanged_apart_from_reading_out_the_offered_times(client):
    call = Call(client, "en")
    call.shortcut("I need to book a consultation.")
    call.choose("pick", "new")
    call.send("Eng Example")
    call.send("5550910005")
    call.choose("skip")
    call.send(action="pick", value=client.get("/api/services").json()[0]["id"])
    call.choose("pick", "any")
    reply = call.choose("pick", "earliest")
    assert reply["messages"][0]["text"] == "Here are three available times:"
    readout = [m["text"] for m in reply["messages"][1:]]
    slots = slot_options(reply)
    assert readout[0] == f"Option 1: {slots[0]['params']['day']} at {slots[0]['params']['time']} with {slots[0]['params']['doctor']}."
    assert len(readout) == 3
    assert call.end()["goodbye"]["text"] == "Thank you for calling Smriti Raj Dentistry. Goodbye."


def test_website_assistant_stays_in_english(client):
    reply = client.post("/api/assistant/message", json={"action": "start"}).json()
    assert reply["messages"][0]["text"].startswith("Hello, and welcome to Smriti Raj Dentistry.")
    assert "language" not in reply
    assert client.post("/api/call-demo/start", json={"language": "fr"}).status_code == 422


def test_hindi_dates_translate_names_only():
    assert call_language.localize_label("Mon, 19 Oct · 4:30 PM · Dr. Anika Rao", "hi") == "सोमवार, 19 अक्टूबर · 4:30 PM · Dr. Anika Rao"
    assert call_language.localize_label("Today · 9:00 AM · Dr. Meera Iyer", "hi") == "आज · 9:00 AM · Dr. Meera Iyer"
    assert call_language.localize_label("Mon, 19 Oct · 4:30 PM · Dr. Anika Rao", "hinglish") == "Mon, 19 Oct · 4:30 PM · Dr. Anika Rao"


# --- Voice selection -----------------------------------------------------------------
def test_each_language_uses_its_configured_local_voice():
    assert config.VOICE_ENGLISH == "en_GB-cori-medium" and config.VOICE_ENGLISH_SPEAKER == ""
    assert tts.voice_for("en") == ("en_GB-cori-medium", "")
    assert tts.voice_for("hi") == ("hi_IN-priyamvada-medium", "")
    assert tts.voice_for("hinglish") == ("hi_IN-priyamvada-medium", "")  # Hinglish speaks Devanagari Hindi
    assert tts.model_path("hinglish").name == "hi_IN-priyamvada-medium.onnx"
    assert tts.model_path("hi").name == "hi_IN-priyamvada-medium.onnx"
    with pytest.raises(tts.ValidationError):
        tts.voice_for("fr")


def test_voice_status_reports_every_language(client):
    status = client.get("/api/call-demo/voice").json()
    assert status["voice"] == "en_GB-cori-medium" and status["speaker"] is None
    languages = status["languages"]
    assert languages["hi"]["voice"] == "hi_IN-priyamvada-medium" and languages["hi"]["label"] == "Local Hindi voice"
    assert languages["hinglish"]["voice"] == "hi_IN-priyamvada-medium"
    assert languages["hinglish"]["label"] == "Hinglish conversation · Hindi local voice"
    assert languages["en"]["label"] == "Local English voice"


def test_speech_request_passes_the_language_to_the_right_voice(client, monkeypatch):
    spoken = []
    monkeypatch.setattr(tts, "available", lambda language="en": True)
    monkeypatch.setattr(tts, "synthesize", lambda text, language="en": spoken.append((text, language)) or b"RIFFfake")
    for language, header in (("hi", "hi_IN-priyamvada-medium"), ("hinglish", "hi_IN-priyamvada-medium")):
        response = client.post("/api/call-demo/speech", json={"text": "नमस्ते", "language": language})
        assert response.status_code == 200 and response.headers["x-voice"] == header
    assert spoken == [("नमस्ते", "hi"), ("नमस्ते", "hinglish")]
    assert client.post("/api/call-demo/speech", json={"text": "hi", "language": "xx"}).status_code == 422


def test_missing_hindi_pack_is_text_only_and_calls_still_work(client, monkeypatch):
    # English installed, Hindi missing: Hindi must never fall back to the English voice.
    with monkeypatch.context() as m:
        m.setattr(tts, "available", lambda language="en": language != "hi")
        m.setattr(tts, "pack_installed", lambda language="en": language != "hi")
        page = client.get("/call-demo").text
        assert wording.VOICE_MISSING_MESSAGE in page
        hindi_test = page.split('id="audio-test-hi"')[1].split(">")[0]
        assert 'aria-disabled="true"' in hindi_test and "not installed" in hindi_test
        assert 'aria-disabled' not in page.split('id="audio-test"')[1].split(">")[0]
    # Without the pack the speech endpoint refuses Hindi instead of substituting another voice.
    refused = client.post("/api/call-demo/speech", json={"text": "नमस्ते", "language": "hi"})
    assert refused.status_code == 503 and refused.json()["message"] == wording.VOICE_MISSING_MESSAGE
    call = Call(client, "hi")
    call.shortcut("I want to speak to a person.")
    call.send("राम उदाहरण")
    assert call.send("5550910006")["callback"]["status"] == "OPEN"


def test_missing_pack_on_disk_is_never_replaced(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.VOICE_DIR", tmp_path)
    (tmp_path / "en_GB-cori-medium.onnx").write_bytes(b"x")
    (tmp_path / "en_GB-cori-medium.onnx.json").write_text("{}")
    assert tts.pack_installed("en")
    # Hindi and Hinglish both need the Hindi pack; the English one is never used instead.
    for language in ("hi", "hinglish"):
        assert not tts.pack_installed(language) and not tts.available(language)
        with pytest.raises(tts.VoiceUnavailableError):
            tts.synthesize("नमस्ते", language)


def test_hindi_speech_text_is_made_speakable():
    said = tts.prepare("Dr. Anika Rao, सोमवार, 19 अक्टूबर, 4:30 PM। संदर्भ #12", "hi")
    assert said == "डॉक्टर अनिका राव, सोमवार, 19 अक्टूबर, 4:30 पी एम। संदर्भ नंबर 12"
    assert tts.prepare("आपकी बुकिंग लंबित (PENDING) है।", "hi") == "आपकी बुकिंग लंबित है।"
    assert tts.prepare("Your reference is #6.", "en") == "Your reference is number 6."  # English unchanged


def _seconds(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio)) as wav:
        return wav.getnframes() / wav.getframerate()


@pytest.mark.real_voice
@pytest.mark.parametrize("language,text", [
    ("en", "Hello. This is the Smriti Raj Dentistry appointment assistant."),
    ("hi", "नमस्ते। मैं स्मृति राज डेंटिस्ट्री की अपॉइंटमेंट असिस्टेंट हूँ।"),
    ("hinglish", wording.UI["hinglish"]["test_speech"]),
])
def test_speech_endpoint_returns_real_wav_from_the_installed_packs(client, language, text):
    if not tts.available(language):
        pytest.skip(f"{tts.voice_for(language)[0]} not installed (run scripts/download_voice.py --all-demo-languages)")
    response = client.post("/api/call-demo/speech", json={"text": text, "language": language})
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF" and response.content[8:12] == b"WAVE"
    assert 1.5 < _seconds(response.content) < 12
    assert response.headers["x-voice"].startswith(tts.voice_for(language)[0])


# --- Hinglish: Roman Hindi on screen, Devanagari for the Hindi voice --------------------------
def test_hinglish_transcript_is_roman_and_its_speech_is_devanagari(client):
    call = Call(client, "hinglish")
    for message in call.reply["messages"]:
        assert not DEVANAGARI.search(message["text"])
        assert DEVANAGARI.search(message["speech_text"]) and not _roman_words(message["speech_text"]), message
    assert call.reply["messages"][0]["speech_text"] == (
        "स्मृति राज डेंटिस्ट्री को कॉल करने के लिए धन्यवाद। अभी क्लिनिक बंद है, इसलिए आप हमारे ऑटोमेटेड असिस्टेंट से बात कर रहे हैं।"
    )
    sunday = call.shortcut("Can I come on Sunday?")["messages"][0]
    assert sunday["text"].startswith("Smriti Raj Dentistry Sunday ko band rehta hai. Agle available appointments")
    assert sunday["speech_text"].startswith("स्मृति राज डेंटिस्ट्री रविवार को बंद रहता है। अगले उपलब्ध अपॉइंटमेंट")
    assert not _roman_words(sunday["speech_text"])
    ended = call.end()
    assert ended["goodbye"]["text"].endswith("Namaste.") and ended["goodbye"]["speech_text"].endswith("नमस्ते।")


def test_english_and_hindi_speak_what_they_show(client):
    english = Call(client, "en")
    assert all(m["speech_text"] == m["text"] for m in english.reply["messages"])
    hindi = Call(client, "hi")
    for message in hindi.reply["messages"]:
        assert DEVANAGARI.search(message["speech_text"])
    # Hindi speech only swaps in approved pronunciations of names (here, the clinic name).
    assert hindi.reply["messages"][0]["speech_text"] == hindi.reply["messages"][0]["text"].replace("Smriti Raj Dentistry", "स्मृति राज डेंटिस्ट्री")
    assert hindi.reply["messages"][1]["speech_text"] == hindi.reply["messages"][1]["text"]


def test_hinglish_booking_flow_is_unchanged_and_speaks_data_clearly(client):
    call = Call(client, "hinglish")
    call.shortcut("I need to book a consultation.")
    call.choose("pick", "new")
    call.send("Hinglish Example")
    call.send("5550910007")
    call.choose("skip")
    call.send(action="pick", value=client.get("/api/services").json()[0]["id"])
    call.choose("pick", "any")
    reply = call.choose("pick", "earliest")
    slots = slot_options(reply)
    readout = [m for m in reply["messages"] if m.get("key") == "slot_option"]
    assert len(readout) == 3
    for message, slot in zip(readout, slots):
        time, doctor = slot["params"]["time"], slot["params"]["doctor"]
        assert message["text"].startswith("Option ") and time in message["text"] and doctor in message["text"]
        spoken = message["speech_text"]
        assert spoken.startswith("ऑप्शन ") and time.split()[0] in spoken  # digits stay digits
        assert wording.SPEECH_NAMES[doctor] in spoken and doctor not in spoken  # approved pronunciation
    call.send(action="slot", value=slots[0]["value"])
    reply = call.choose("confirm")
    booking = reply["booking"]
    assert booking["status"] == "PENDING"
    assert reply["messages"][1]["text"].endswith(f"Aapka reference #{booking['reference']} hai.")
    assert reply["messages"][1]["speech_text"] == (
        f"जब तक हमारा फ्रंट डेस्क कन्फ़र्म नहीं करता, आपकी बुकिंग पेंडिंग है। आपका रेफ़रेंस नंबर {booking['reference']} है।"
    )
    log = call.end()["call"]
    assert log["outcome"] == "BOOKING_CREATED" and log["appointment_id"] == booking["reference"] and log["language"] == "hinglish"


def test_hinglish_callback_reference_and_mobile_are_spoken_as_digits(client):
    call = Call(client, "hinglish")
    call.shortcut("I want to speak to a person.")
    call.send("Asha Example")
    reply = call.send("5550910008")
    task_id = reply["callback"]["reference"].split("-")[1]
    assert reply["messages"][1]["speech_text"] == f"हमारा स्टाफ़ क्लिनिक आवर्स में आपसे कॉन्टैक्ट करेगा। आपका रेफ़रेंस सी {task_id} है।"
    assert call.end()["call"]["outcome"] == "CALLBACK_CREATED"


def test_page_speaks_speech_text_and_offers_a_hinglish_voice_test(client):
    page = client.get("/call-demo").text
    assert 'id="audio-test-hinglish"' in page and "Test Hinglish voice" in page
    config_json = json.loads(page.split('id="call-config">')[1].split("</script>")[0])
    hinglish = next(language for language in config_json["languages"] if language["code"] == "hinglish")
    assert hinglish["voice"]["label"] == "Hinglish conversation · Hindi local voice"
    assert hinglish["voice"]["voice"] == "hi_IN-priyamvada-medium"
    assert "Local Hinglish voice" not in page
    script = (ROOT / "app/static/js/call.js").read_text()
    assert 'const pack = (code) => (code === "en" ? "en" : "hi");' in script
    assert "message.speech_text || message.text" in script
    assert "LANGS[code].ui.test_speech" in script
    assert DEVANAGARI.search(wording.UI["hinglish"]["test_speech"])


@pytest.mark.real_voice
def test_hinglish_reply_audio_comes_from_the_hindi_pack(client):
    if not tts.available("hinglish"):
        pytest.skip("hi_IN-priyamvada-medium not installed")
    speech = Call(client, "hinglish").reply["messages"][0]["speech_text"]
    response = client.post("/api/call-demo/speech", json={"text": speech, "language": "hinglish"})
    assert response.status_code == 200 and response.headers["x-voice"] == "hi_IN-priyamvada-medium"
    assert response.content[:4] == b"RIFF" and 2 < _seconds(response.content) < 15


# --- Call demo page --------------------------------------------------------------------
def test_language_selector_is_shown_and_persisted(client):
    page = client.get("/call-demo").text
    radios = re.findall(r'<input type="radio" name="call-language" value="(\w+)"( checked)?>', page)
    assert [code for code, _ in radios] == ["en", "hi", "hinglish"]
    assert radios[0][1] == " checked"  # English by default
    for label in ("English", "हिंदी", "Hinglish"):
        assert f">{label}</span>" in page
    assert "Change language" in page and "The next assistant reply will use the new language." in page
    assert 'id="call-lang-tag"' in page and "Local English voice" in page
    script = (ROOT / "app/static/js/call.js").read_text()
    assert 'const LANGUAGE_KEY = "smriti.callDemo.language"' in script
    assert "localStorage.getItem(LANGUAGE_KEY)" in script and "localStorage.setItem(LANGUAGE_KEY, code)" in script
    assert "language_changed" in script
    assert "{ language }" in script  # sent with start and end; every turn carries it too
    assert "state, language }" in script


def test_caller_phrases_are_shown_in_the_chosen_language_but_send_english(client):
    page = client.get("/call-demo").text
    assert 'data-phrase="Can I come on Sunday?"' in page
    assert 'data-label-hi="क्या रविवार को आ सकते हैं?"' in page
    assert 'data-label-hinglish="Kya Sunday ko aa sakte hain?"' in page


def test_firefox_uses_local_voice_when_installed_and_stays_honest_without_it(client, monkeypatch):
    page = client.get("/call-demo", headers={"user-agent": FIREFOX_UA}).text
    assert 'data-text-mode="firefox"' in page and "not installed" in page
    monkeypatch.setattr(tts, "available", lambda language="en": True)
    monkeypatch.setattr(tts, "pack_installed", lambda language="en": True)
    page = client.get("/call-demo", headers={"user-agent": FIREFOX_UA}).text
    assert "data-text-mode" not in page and 'data-server-voice="1"' in page
    assert "Audio is generated on this computer for the demo." in page


# --- Back to dashboard ---------------------------------------------------------------
@pytest.mark.parametrize("path", ["/assistant", "/call-demo"])
def test_back_to_dashboard_is_in_the_header_and_guarded(client, path):
    page = client.get(path).text
    header = page.split("<main")[0]
    assert re.search(r'<a class="btn btn-sm[^"]*" href="/" data-leave-guard><svg[^>]*>.*?</svg>Back to dashboard</a>', header)
    assert "Leave this conversation?" in page and "Your active demo conversation will end." in page
    assert ">Stay here</button>" in page and ">Leave dashboard</button>" in page
    assert "js/leave-guard.js" in page
    done = page.split('id="done-actions"')[1].split("</div>")[0]
    assert "Back to dashboard" in done
    assert ("Start another demo call" if path == "/call-demo" else "Start another conversation") in done
    assert client.get("/").status_code == 200


def test_leave_guard_only_asks_during_an_active_conversation():
    guard = (ROOT / "app/static/js/leave-guard.js").read_text()
    assert "if (!isActive()) return;" in guard  # no conversation: the link just navigates
    assert "event.preventDefault()" in guard and "dialog.showModal()" in guard
    assert "await beforeLeave()" in guard and "window.location.assign(target)" in guard
    call_js = (ROOT / "app/static/js/call.js").read_text()
    guard_call = call_js.split("window.LeaveGuard({")[1].split("});")[0]
    assert "isActive: () => !!callId" in guard_call and "return endCall(true);" in guard_call
    assistant_js = (ROOT / "app/static/js/assistant.js").read_text()
    assert "window.LeaveGuard({ isActive: () => active" in assistant_js


def test_leaving_an_active_call_ends_it_with_the_right_outcome(client):
    call = Call(client, "hi")
    call.shortcut("What are your opening hours?")
    assert logged(client, call.id)["completed_at"] is None
    # What "Leave dashboard" sends (the page's own end flow), and what the pagehide beacon sends.
    left = client.post(f"/api/call-demo/{call.id}/end", json={"language": "hi"}).json()["call"]
    assert left["outcome"] == "FAQ_ANSWERED" and left["completed_at"] is not None
    other = Call(client)
    beacon = client.post(f"/api/call-demo/{other.id}/end", content=b'{"language":"en"}', headers={"content-type": "application/json"})
    assert beacon.status_code == 200 and beacon.json()["call"]["outcome"] == "ENDED"


def test_visiting_pages_without_a_conversation_creates_no_call_log(client):
    for path in ("/call-demo", "/assistant", "/", "/call-demo"):
        assert client.get(path).status_code == 200
    assert client.get("/api/calls").json() == []


def test_mobile_layout_rules_prevent_horizontal_overflow():
    css = (ROOT / "app/static/css/call.css").read_text()
    assert ".lang-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));" in css
    assert ".call-topbar {" in css and "flex-wrap: wrap" in css.split(".call-topbar {")[1].split("}")[0]
    assert ".audio-tests { grid-column: 1 / -1; display: flex; flex-wrap: wrap;" in css
    assert "overflow-wrap: anywhere" in css.split(".audio-voice-model {")[1].split("}")[0]
    assert ".lang-choice input:focus-visible + span { outline:" in css
    app_css = (ROOT / "app/static/css/app.css").read_text()
    assert ".leave-dialog { width: min(420px, calc(100vw - 32px));" in app_css
    assert ".btn-on-dark:focus-visible" in app_css
    assistant_css = (ROOT / "app/static/css/assistant.css").read_text()
    assert ".done-actions { display: flex; flex-wrap: wrap;" in assistant_css


def test_download_script_offers_all_demo_languages():
    script = (ROOT / "scripts/download_voice.py").read_text()
    assert "--all-demo-languages" in script and "def verify(" in script and "def list_installed(" in script
    assert "voices/" in (ROOT / ".gitignore").read_text()
