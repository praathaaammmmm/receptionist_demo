"""Voice Agent Phase 2: the browser voice agent demo (/voice-agent-demo) and its session API."""
import re
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app import config
from app.models import Appointment, CallLog
from app.schemas import VoiceAgentStart
from app.services import tts, voice_agent_demo
from app.voice_agent import conversation, policy, wording
from app.voice_agent.context import IST
from app.voice_agent.conversation import Conversation, State, extract_name, extract_phone

API = "/api/voice-agent-demo"
MON, SAT, SUN = 19, 17, 18  # October 2026


class Call:
    """Drives one voice agent demo call through the API, the way the page does."""

    def __init__(self, client, **options):
        self.client = client
        response = client.post(f"{API}/start", json=options)
        assert response.status_code == 201, response.text
        self.last = response.json()
        self.id = self.last["session_id"]
        self.replies = [self.last]

    def say(self, text, language=None, status=200):
        body = {"text": text} | ({"language": language} if language else {})
        response = self.client.post(f"{API}/{self.id}/message", json=body)
        assert response.status_code == status, response.text
        if status == 200:
            self.last = response.json()
            self.replies.append(self.last)
        return response.json()

    @property
    def text(self):
        return " ".join(m["text"] for m in self.last["messages"])

    def all_text(self):
        return " ".join(m["text"] for r in self.replies for m in r["messages"])

    def end(self):
        response = self.client.post(f"{API}/{self.id}/end")
        assert response.status_code == 200, response.text
        return response.json()


def callbacks(client):
    return client.get("/api/callbacks").json()


def call_logs(client):
    return client.get("/api/calls").json()


def appointment_count(client):
    with client.app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(Appointment))


def give_details(call, name="Asha Verma", phone="98765 43210", reason=None, patient="first visit",
                 doctor="no preference", when="Saturday morning"):
    call.say("yes")
    assert call.last["state"] == "capture_name"
    call.say(name)
    call.say(phone)
    if reason is not None:
        assert call.last["state"] == "capture_reason"
        call.say(reason)
    # Appointment enquiries also ask new or existing patient, preferred doctor and preferred time.
    for state, answer in (("capture_patient_type", patient), ("capture_doctor", doctor), ("capture_time", when)):
        if call.last["state"] == state:
            call.say(answer)
    assert call.last["state"] == "confirm_details"


# --- Page and routes --------------------------------------------------------------------------

def test_page_loads_with_truthful_disclosures_and_no_prompt(client):
    page = client.get("/voice-agent-demo")
    assert page.status_code == 200
    html = page.text
    for text in ["AI Voice Receptionist Demo",
                 "Interactive prototype using sample data. Not connected to a live clinic phone number.",
                 "Back to dashboard", "English", "हिंदी", "Hinglish", "What the clinic team sees", "Tap to speak",
                 "browser-based interactive prototype", "sample, demo data", "not connected to a live clinic telephone number",
                 "does not provide medical advice", "not a production recording system", "End call", "Replay last response",
                 "Mute voice", "Call activity", "Callback queue"]:
        assert text.lower() in html.lower(), text
    for scenario in wording.DEMO_SCENARIOS:
        assert f'data-scenario="{scenario["id"]}"' in html and scenario["label"] in html
    for prompt_only in ("SPEAKING STYLE", "RUNTIME CONTEXT", "TOOLS (call only these", "JSON schema"):
        assert prompt_only not in html
    assert html.index("js/call-audio.js") < html.index("js/voice-agent.js")


def test_existing_assistant_and_call_demo_still_load(client):
    for path in ("/assistant", "/call-demo", "/"):
        assert client.get(path).status_code == 200
    assert 'href="/voice-agent-demo"' in client.get("/").text  # reachable from the dashboard's call activity card


def test_opening_the_page_creates_no_call_log_or_callback(client):
    before = len(callbacks(client))
    for _ in range(3):
        client.get("/voice-agent-demo")
    assert call_logs(client) == [] and len(callbacks(client)) == before


def test_starting_a_call_writes_nothing_until_it_ends(client):
    call = Call(client)
    call.say("What are your opening hours?")
    assert call_logs(client) == []
    call.end()
    assert len(call_logs(client)) == 1


def test_unknown_session_and_bad_input(client):
    assert client.post(f"{API}/nope/message", json={"text": "hi"}).status_code == 404
    assert client.post(f"{API}/nope/end").status_code == 404
    assert client.post(f"{API}/start", json={"transfer": "always"}).status_code == 422
    call = Call(client)
    assert client.post(f"{API}/{call.id}/message", json={"text": "x" * 501}).status_code == 422


# --- Runtime context --------------------------------------------------------------------------

def test_start_applies_a_fresh_ist_runtime_context(client):
    call = Call(client)
    context = call.last["context"]
    today = datetime.now(IST).strftime("%a %d %b %Y")
    assert context["now_ist"].startswith(today) and context["now_ist"].endswith("IST")
    expected = voice_agent_demo.build_context(VoiceAgentStart())
    assert context["clinic_open_now"] == expected.clinic_open_now
    assert context["transfer_available"] == expected.transfer_available
    assert context["caller_number_available"] is False
    assert context["simulation"] == {"transfer": "auto", "caller_id": "unknown", "clinic": "auto"}


@pytest.mark.parametrize("moment, open_now, transfer", [
    (datetime(2026, 10, MON, 11, 0, tzinfo=IST), True, True),
    (datetime(2026, 10, SAT, 21, 0, tzinfo=IST), False, False),
    (datetime(2026, 10, SUN, 11, 0, tzinfo=IST), False, False),
])
def test_build_context_uses_ist_hours(moment, open_now, transfer):
    context = voice_agent_demo.build_context(VoiceAgentStart(), moment)
    assert (context.clinic_open_now, context.transfer_available) == (open_now, transfer)


def test_demo_overrides_are_explicit_simulations():
    sunday = datetime(2026, 10, SUN, 11, 0, tzinfo=IST)
    opened = voice_agent_demo.build_context(VoiceAgentStart(clinic="open"), sunday)
    assert opened.clinic_open_now and opened.transfer_available
    closed = voice_agent_demo.build_context(VoiceAgentStart(clinic="closed", transfer="available"), sunday)
    assert not closed.clinic_open_now and closed.transfer_available
    assert not voice_agent_demo.build_context(VoiceAgentStart(transfer="unavailable"),
                                              datetime(2026, 10, MON, 11, 0, tzinfo=IST)).transfer_available
    present = voice_agent_demo.build_context(VoiceAgentStart(caller_id="present"), sunday)
    assert present.caller_number == voice_agent_demo.DEMO_CALLER_NUMBER


def test_greeting_depends_on_transfer_and_hours(client):
    with_transfer = Call(client, clinic="open", transfer="available").text
    assert "try to connect you to reception" in with_transfer and "closed right now" not in with_transfer
    closed = Call(client, clinic="closed").text
    assert "The clinic is closed right now." in closed and "Reception can't take calls right now" in closed
    for text in (with_transfer, closed):
        assert "no audio is recorded" in text and text.endswith("How can I help you today?")


# --- Conversations ----------------------------------------------------------------------------

def test_appointment_request_creates_a_callback_only_after_valid_confirmed_details(client):
    before_callbacks, before_appointments = len(callbacks(client)), appointment_count(client)
    call = Call(client, clinic="open", transfer="unavailable")
    call.say("I want to book a consultation.")
    assert "can't book appointments on this call" in call.text and call.last["state"] == "offer_callback"
    call.say("yes")
    call.say("My name is Asha Verma")
    assert call.last["caller"]["name"] == "Asha Verma"
    call.say("12345")
    assert "doesn't sound like a 10-digit Indian mobile number" in call.text and call.last["state"] == "capture_phone"
    call.say("5876543210")  # starts with 5
    assert call.last["state"] == "capture_phone"
    call.say("+91 98765 43210")
    assert call.text == "What would you like the appointment for?"
    call.say("A routine cleaning")
    assert call.text == "Have you visited Smriti Raj Dentistry before, or would this be your first visit?"
    call.say("This is my first visit")
    assert call.text.startswith("Do you have a preferred doctor?")
    call.say("Doctor Smriti please")
    assert call.text == "Which day and time would suit you best?"
    call.say("Saturday morning")
    assert call.text == ("Just to confirm, your name is Asha Verma, and we should call you on 9 8 7 6 5, 4 3 2 1 0. "
                         "The reason is: A routine cleaning. New patient. Preferred doctor: Doctor Smriti Raj. "
                         "Preferred time: Saturday morning. Is that right?")
    assert len(callbacks(client)) == before_callbacks  # nothing yet
    call.say("hmm")
    assert call.text == "Please say yes if that's right, or no to change it." and len(callbacks(client)) == before_callbacks
    call.say("yes")
    created = call.last["callback_created"]
    assert created["category"] == "appointment" and created["href"] == f"/#callback-{created['id']}"
    assert "as soon as possible during clinic hours" in call.text
    tasks = callbacks(client)
    assert len(tasks) == before_callbacks + 1
    task = next(t for t in tasks if t["id"] == created["id"])
    assert (task["name"], task["mobile"], task["source"], task["status"]) == ("Asha Verma", "9876543210", "AI_DEMO", "OPEN")
    assert task["reason"] == "Appointment request: A routine cleaning"
    assert task["notes"] == ("Voice agent demo call. Caller language: English. New patient. Preferred doctor: "
                             "Dr. Smriti Raj. Preferred day/time: Saturday morning. Wants a consultation: yes.")
    assert appointment_count(client) == before_appointments  # no booking in this phase


def test_saying_no_at_read_back_restarts_detail_capture(client):
    call = Call(client)
    call.say("I want to book a consultation.")
    give_details(call, reason="Braces")
    call.say("no, that's wrong")
    assert call.last["state"] == "capture_name" and call.text.startswith("Let's correct that.")
    call.say("Asha")
    call.say("9876543210")
    assert call.last["state"] == "capture_reason"  # every detail is collected again
    call.say("Braces")
    for answer in ("existing patient", "Doctor Raj", "Monday evening"):
        call.say(answer)
    assert "Preferred doctor: Doctor Raj Tiwary" in call.text
    call.say("yes")
    assert call.last["callback_created"] and call.last["caller"]["name"] == "Asha"


def test_callback_goes_through_the_existing_service_exactly_once(client, monkeypatch):
    real = voice_agent_demo.callbacks.create_callback
    used = []
    monkeypatch.setattr(voice_agent_demo.callbacks, "create_callback", lambda *a, **k: used.append(k) or real(*a, **k))
    call = Call(client)
    call.say("I want to book a consultation.")
    give_details(call, reason="Check-up")
    call.say("yes")
    call.say("Can I also book a cleaning?")
    call.say("yes")
    assert "already passed a callback request" in call.text and call.last["state"] == "listening"
    call.end()
    assert len(used) == 1 and used[0]["source"] == "AI_DEMO"


def test_human_transfer_failure_becomes_callback_capture(client):
    call = Call(client, clinic="open", transfer="available")
    call.say("Can I speak to someone at reception?")
    assert call.last["transfer"] == {"attempted": True, "result": "failed", "simulated": True}
    texts = [m["text"] for m in call.last["messages"]]
    assert texts[0] == "Of course. Let me connect you to our reception now."
    assert texts[1].startswith("I'm sorry, I couldn't connect you just now.") and texts[1].endswith("May I have your name, please?")
    assert call.last["state"] == "capture_name"
    call.say("Ravi Kumar")
    call.say("9811122233")
    assert call.text == "Briefly, what would you like our team to call you about?"
    call.say("Change my appointment time")
    call.say("yes")
    assert call.last["callback_created"]["category"] == "human_request"
    task = next(t for t in callbacks(client) if t["id"] == call.last["callback_created"]["id"])
    assert task["reason"] == "Asked to speak to reception: Change my appointment time"


def test_human_request_without_transfer_goes_straight_to_details(client):
    call = Call(client, transfer="unavailable")
    call.say("I want to talk to a person")
    assert call.last["transfer"] == {"attempted": False, "result": "unavailable", "simulated": True}
    assert "can't take a call right now" in call.text and call.last["state"] == "capture_name"


def test_panel_enquiry_creates_a_panel_callback(client):
    call = Call(client)
    call.say("Do you accept CGHS? What documents do I need?")
    assert call.text.startswith("Smriti Raj Dentistry is CGHS-empanelled.")
    assert "can't confirm eligibility, rates, documents or referrals" in call.text
    give_details(call, name="Meena")
    call.say("yes")
    assert call.last["callback_created"]["category"] == "panel"
    task = next(t for t in callbacks(client) if t["id"] == call.last["callback_created"]["id"])
    assert task["reason"].startswith("Panel enquiry (CGHS, ECHS, CISF, DU, Air India): Do you accept CGHS?")


@pytest.mark.parametrize("language, question", [
    ("en", "I have tooth pain. Which painkiller should I take?"),
    ("en", "My teeth are sensitive, is it serious?"),
    ("en", "Should I get a root canal or an extraction?"),
    ("hi", "दर्द के लिए कौन सी दवा लूं?"),
    ("hinglish", "dard ke liye kaunsi dawai lun?"),
])
def test_ordinary_clinical_questions_never_say_112(client, language, question):
    call = Call(client, language=language)
    call.say(question)
    assert call.last["decision"]["path"] in ("clinical", "tooth_pain", "unknown")
    assert call.last["state"] == "offer_callback"
    for message in call.last["messages"]:
        assert "112" not in message["text"] and "112" not in message["speech_text"]
    give_details(call)
    call.say("yes")
    for message in call.all_text().split():
        assert message != "112"
    assert call.last["callback_created"]["urgent"] is False


def test_112_appears_only_in_the_emergency_lines():
    for key, versions in wording.LINES.items():
        if any("112" in text for text in versions.values()):
            assert key.startswith("emergency"), key
    for versions in wording.UNKNOWN_LEADS.values():
        assert not any("112" in text for text in versions.values())


def test_urgent_symptoms_give_the_emergency_instruction_and_an_optional_urgent_callback(client):
    call = Call(client, clinic="closed")
    call.say("My face is swollen and the swelling is spreading to my eye.")
    assert call.text.startswith("This sounds like an emergency. Please call 112 now")
    assert "on the next working day" in call.text and call.last["decision"]["urgent"] is True
    give_details(call, name="Kiran")
    call.say("yes")
    created = call.last["callback_created"]
    assert created["urgent"] is True and created["category"] == "urgent"
    task = next(t for t in callbacks(client) if t["id"] == created["id"])
    assert task["reason"].startswith("URGENT: caller told to call 112: My face is swollen")


def test_urgent_with_transfer_offers_transfer_then_callback(client):
    call = Call(client, clinic="open", transfer="available")
    call.say("There is heavy bleeding after the extraction")
    assert "112" in call.text and call.last["state"] == "offer_transfer"
    call.say("yes please")
    assert call.last["transfer"]["result"] == "failed" and call.last["state"] == "capture_name"


def test_urgent_callback_may_follow_a_separate_normal_callback(client):
    call = Call(client)
    call.say("I want to book a consultation.")
    give_details(call, reason="Check-up")
    call.say("yes")
    call.say("I can't breathe properly")
    give_details(call)
    call.say("yes")
    assert call.last["callback_created"]["urgent"] is True
    assert len(call.last["callbacks"]) == 2


@pytest.mark.parametrize("question", ["Is there parking near the clinic?", "Do you do Botox?",
                                      "When is Dr Raj available?", "How much does an implant cost?"])
def test_unknown_questions_do_not_invent_information(client, question):
    call = Call(client)
    call.say(question)
    assert call.last["decision"]["path"] == "unknown" and call.last["state"] == "offer_callback"
    assert set(re.findall(r"\d+", call.text)) <= {"500"}
    assert any(p in call.text for p in ("don't have", "can't quote", "won't guess"))


def test_faq_answer_and_goodbye_log_the_call(client):
    call = Call(client)
    call.say("Are you open on Sunday?")
    assert "closed on Sunday" in call.text and call.text.endswith("Is there anything else I can help with?")
    call.say("no thanks")
    assert call.text == "Thank you for calling Smriti Raj Dentistry. Goodbye."
    assert call.last["ended"] is True and call.last["input_enabled"] is False
    logged = call_logs(client)
    assert len(logged) == 1 and logged[0]["outcome"] == "FAQ_ANSWERED" and logged[0]["channel"] == "VOICE_AGENT"
    call.say("hello", status=409)
    assert call.end()["already_ended"] is True and len(call_logs(client)) == 1


# --- Languages --------------------------------------------------------------------------------

def test_hindi_flow_uses_phase_1_wording(client):
    call = Call(client, language="hi", clinic="open", transfer="available")
    assert call.last["messages"][0]["text"] == wording.line("greeting", "hi")
    call.say("रविवार को क्लिनिक खुला है क्या?")
    assert call.last["messages"][0]["text"] == wording.line("hours", "hi")
    assert call.last["messages"][0]["speech_text"] == wording.line("hours", "hi")
    call.say("मुझे अपॉइंटमेंट चाहिए")
    assert call.last["messages"][0]["text"] == policy.unknown_information("appointment_request", "hi").text
    give_details(call, name="मेरा नाम आशा है", phone="९८७६५ ४३२१०", reason="सफ़ाई")
    assert call.last["caller"]["name"] == "आशा"
    call.say("हाँ")
    assert call.last["callback_created"] and "क्लिनिक के समय में जल्द से जल्द" in call.text


def test_hinglish_is_shown_in_roman_and_spoken_from_the_hindi_line(client):
    call = Call(client, language="hinglish", clinic="closed")
    call.say("Sunday ko clinic khula hai kya?")
    message = call.last["messages"][0]
    assert message["text"] == wording.line("hours", "hinglish")
    assert message["speech_text"] == wording.line("hours", "hi")
    speech = call.last["speech"]
    assert speech["text"] == " ".join(m["speech_text"] for m in call.last["messages"]) and speech["language"] == "hinglish"
    assert " ".join(speech["parts"]) == speech["text"]  # sentence by sentence, nothing added or lost


def test_language_can_change_during_a_call(client):
    call = Call(client)
    call.say("What are your opening hours?", language="hi")
    assert call.last["language"] == "hi" and "सोमवार" in call.text


def test_every_reply_fits_the_local_voice(client):
    call = Call(client, language="hi", caller_id="present", transfer="available", clinic="open")
    for text in ["आपके डॉक्टर कौन हैं?", "clinic ka address kya hai", "Can I speak to someone?", "Asha", "yes", "Cleaning",
                 "yes", "My face is swollen and the swelling is spreading to my eye."]:
        call.say(text)
    for reply in call.replies:
        if reply["speech"]:
            assert len(tts.prepare(reply["speech"]["text"], reply["speech"]["language"])) <= tts.MAX_CHARS


# --- Caller ID ----------------------------------------------------------------------------------

def test_caller_number_is_never_read_out_and_used_only_after_confirmation(client):
    call = Call(client, caller_id="present")
    digits = voice_agent_demo.DEMO_CALLER_NUMBER
    call.say("Please call me back")
    assert call.text == "Of course. May I have your name, please?"
    call.say("Asha")
    assert call.text == "Should we call you back on the number you're calling from?"
    assert call.last["caller"]["phone"] is None
    call.say("yes")
    call.say("Question about my bill")
    assert "the number you're calling from" in call.text
    spoken = " ".join(m["text"] + m["speech_text"] for r in call.replies for m in r["messages"])
    assert digits not in spoken and "4 3 2 1 0" not in spoken and digits[-4:] not in re.sub(r"\D", "", spoken)
    call.say("yes")
    task = next(t for t in callbacks(client) if t["id"] == call.last["callback_created"]["id"])
    assert task["mobile"] == digits and task["reason"] == "Callback request: Question about my bill"
    assert call.last["caller"]["phone"] == "98765 43210"


# --- End, logging and links ---------------------------------------------------------------------

def test_end_logs_once_and_refuses_later_replies(client):
    call = Call(client)
    call.say("I want to book a consultation.")
    give_details(call, reason="Implant consultation")
    call.say("yes")
    first = call.end()
    assert first["already_ended"] is False and first["ended"] is True and first["input_enabled"] is False
    second = call.end()
    assert second["already_ended"] is True and second["call_log_id"] == first["call_log_id"]
    logged = call_logs(client)
    assert len(logged) == 1
    log = logged[0]
    assert log["outcome"] == "CALLBACK_CREATED" and log["callback_task_id"] == first["callbacks"][0]["id"]
    assert (log["caller_name"], log["caller_mobile"], log["completed_at"] is not None) == ("Asha Verma", "9876543210", True)
    late = client.post(f"{API}/{call.id}/message", json={"text": "hello"})
    assert late.status_code == 409 and late.json()["error"] == "call_ended"


def test_ending_an_untouched_call_logs_an_ended_call(client):
    call = Call(client)
    assert call.end()["outcome"] == "ENDED"
    assert call_logs(client)[0]["outcome"] == "ENDED"


def test_links_point_to_the_created_records(client):
    patient = client.post("/api/patients", json={"name": "Asha Verma", "mobile": "9876543210"}).json()
    call = Call(client)
    call.say("I want to book a consultation.")
    give_details(call, reason="Cleaning")
    call.say("yes")
    task_id = call.last["callback_created"]["id"]
    links = {link["id"]: link["href"] for link in call.last["links"]}
    assert links["dashboard"] == "/" and links["callbacks"] == f"/#callback-{task_id}"
    assert links["timeline"] == f"/patients/{patient['id']}/timeline"
    assert "calls" not in links  # logged only when the call ends
    ended = call.end()
    links = {link["id"]: link["href"] for link in ended["links"]}
    assert links["calls"] == "/#call-activity"
    dashboard = client.get("/").text
    assert f'id="callback-{task_id}"' in dashboard and 'id="call-activity"' in dashboard
    assert "VOICE_AGENT" in dashboard and f"Callback C-{task_id}" in dashboard
    assert client.get(links["timeline"]).status_code == 200


def test_sessions_are_independent(client):
    first, second = Call(client, language="hi"), Call(client)
    assert first.id != second.id
    first.say("मुझे अपॉइंटमेंट चाहिए")
    second.say("What are your opening hours?")
    assert first.last["state"] == "offer_callback" and second.last["state"] == "listening"
    first.end()
    second.say("Where are you located?")
    assert "Pragati Public School" in second.text


# --- Conversation helpers ---------------------------------------------------------------------

def test_phone_and_name_extraction():
    assert extract_phone("९८७६५ ४३२१०") == "9876543210"
    assert extract_phone("nine eight seven six five four three two one zero") == "9876543210"
    assert extract_phone("+91 98765-43210") == "+919876543210"
    assert extract_name("my name is asha verma") == "Asha Verma"
    assert extract_name("mera naam Ravi hai") == "Ravi"
    assert extract_name("मेरा नाम आशा है") == "आशा"
    assert extract_name("9876543210") is None and extract_name("") is None
    assert extract_name("I would like to know about the doctor's timings please") is None


def test_closing_is_refused_until_a_person_request_is_handled():
    context = voice_agent_demo.build_context(VoiceAgentStart(), datetime(2026, 10, MON, 11, 0, tzinfo=IST))
    talk = Conversation(context)
    talk.session.human_requested = True  # asked for a person, nothing offered yet
    turn = talk.handle("bye", "en", lambda details, intent: 1)
    assert talk.state == State.OFFER_CALLBACK and not talk.ended
    assert turn.messages[0].text.startswith("Before you go, I can ask our team to call you back")
    talk.handle("no", "en", lambda details, intent: 1)
    talk.handle("bye", "en", lambda details, intent: 1)
    assert talk.ended


def test_a_failed_save_lets_the_caller_try_again():
    context = voice_agent_demo.build_context(VoiceAgentStart(), datetime(2026, 10, MON, 11, 0, tzinfo=IST))
    talk = Conversation(context)
    for text in ("I want to book a consultation.", "yes", "Asha", "9876543210", "Cleaning", "new", "any", "Friday"):
        talk.handle(text, "en", lambda details, intent: 1)

    def broken(details, intent):
        raise RuntimeError("database down")

    turn = talk.handle("yes", "en", broken)
    assert turn.callback_created is None and talk.session.callbacks == []
    assert turn.messages[0].text.startswith("I'm sorry, I couldn't save that request")
    turn = talk.handle("yes", "en", lambda details, intent: 7)
    assert turn.callback_id == 7


def test_turn_limit_ends_the_conversation():
    context = voice_agent_demo.build_context(VoiceAgentStart(), datetime(2026, 10, MON, 11, 0, tzinfo=IST))
    talk = Conversation(context)
    for _ in range(conversation.MAX_TURNS):
        talk.handle("What are your opening hours?", "en", lambda details, intent: 1)
    talk.handle("What are your opening hours?", "en", lambda details, intent: 1)
    assert talk.ended


def test_voice_status_reflects_installed_packs(client, monkeypatch):
    html = client.get("/voice-agent-demo").text
    assert '"available": false' in html  # tests run without the voice pack
    assert config.VOICE_DIR.name == "no-voices"
