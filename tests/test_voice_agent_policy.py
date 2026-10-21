"""Voice Agent Phase 1: approved knowledge, runtime context, callback, safety, transfer and prompt policy."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app import config, knowledge as website_knowledge
from app.voice_agent import phone, policy, prompt, wording
from app.voice_agent.context import IST, build_runtime_context, is_clinic_open, next_working_day
from app.voice_agent.knowledge import APPROVED, PENDING_OWNER_REVIEW
from app.voice_agent.schemas import (
    CALLER_NUMBER,
    TOOLS,
    CallbackCategory,
    CallbackDetails,
    CreateCallbackArgs,
    Language,
    NextAction,
    PolicyPath,
    UnknownInformation,
)

LANGS = ("en", "hi", "hinglish")
# 2026-10-17 is a Saturday, 2026-10-18 a Sunday, 2026-10-19 a Monday.
SAT, SUN, MON = (17, 18, 19)


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


@pytest.fixture
def open_ctx():
    return build_runtime_context(at(MON, 11), caller_number="+91 98765 43210")


@pytest.fixture
def closed_ctx():
    return build_runtime_context(at(SUN, 11))


# --- Approved knowledge -----------------------------------------------------------------------

def test_approved_knowledge_is_structured_and_exact():
    c = APPROVED.clinic
    assert c.name == "Smriti Raj Dentistry"
    assert c.address == "Basement Floor, Plot Number 54, Sector 13, Dwarka, New Delhi 110075"
    assert c.landmark == "Near Pragati Public School"
    assert (c.reception_phone, c.alternate_phone) == ("+91 85272 75521", "+91 73037 86284")
    assert c.email == "bhargava.smriti.raj@gmail.com"
    assert [(d.name, d.specialties) for d in APPROVED.doctors] == [
        ("Dr. Raj Tiwary", ("Periodontist", "Implantologist")),
        ("Dr. Smriti Raj", ("Pediatric Dentistry", "Orthodontics")),
    ]
    assert APPROVED.specialist_support == ("endodontics", "oral surgery", "prosthodontics", "orthodontics")
    assert len(APPROVED.services) == 14
    assert APPROVED.services[-1].name == "Same-day tooth or implant consultation, subject to doctor assessment"
    money = APPROVED.commercial
    assert money.consultation_fee_inr == 500 and money.quote_treatment_prices is False
    assert money.payment_methods == ("cash", "UPI", "cards")
    assert money.empanelments == ("CGHS",)
    assert money.panel_schemes == ("CGHS", "ECHS", "CISF", "DU", "Air India")
    assert PENDING_OWNER_REVIEW


def test_voice_knowledge_is_isolated_from_the_demo_configuration():
    # The dashboard's sample data and the website assistant are untouched and not merged.
    assert website_knowledge.ASSISTANT_MODE == "guided"
    assert "Smriti Raj Dentistry" in website_knowledge.CLINIC_HOURS
    assert not hasattr(config, "APPROVED")
    assert set(wording.SERVICE_NAMES) == {s.id for s in APPROVED.services}


def test_spoken_hours_match_the_structured_hours():
    h = APPROVED.hours
    assert (h.opens.hour, h.closes.hour, h.days) == (9, 20, (0, 1, 2, 3, 4, 5))
    assert "9 AM to 8 PM" in wording.LINES["hours"]["en"] and "Sunday" in wording.LINES["hours"]["en"]


# --- Runtime context --------------------------------------------------------------------------

@pytest.mark.parametrize("moment, open_now, transfer", [
    (at(MON, 8, 59), False, False),
    (at(MON, 9, 0), True, False),
    (at(MON, 9, 29), True, False),
    (at(MON, 9, 30), True, True),
    (at(MON, 19, 29), True, True),
    (at(MON, 19, 30), True, False),
    (at(MON, 19, 59), True, False),
    (at(MON, 20, 0), False, False),
    (at(SAT, 12), True, True),
    (at(SAT, 20, 0), False, False),  # Saturday after 8 PM
    (at(SAT, 21, 30), False, False),
    (at(SUN, 11), False, False),  # Sunday closed all day
    (at(SUN, 15), False, False),
])
def test_open_and_transfer_windows(moment, open_now, transfer):
    ctx = build_runtime_context(moment)
    assert (ctx.clinic_open_now, ctx.transfer_available) == (open_now, transfer)


def test_times_in_other_timezones_are_converted_to_ist():
    # 14:45 UTC on Saturday is 8:15 PM IST: closed. 03:30 UTC Monday is 9:00 AM IST: open.
    assert not build_runtime_context(datetime(2026, 10, 17, 14, 45, tzinfo=timezone.utc)).clinic_open_now
    ctx = build_runtime_context(datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc))
    assert ctx.clinic_open_now and ctx.now_ist.utcoffset() == timedelta(hours=5, minutes=30)
    assert ctx.now_ist.hour == 9


def test_naive_times_are_rejected():
    with pytest.raises(ValueError):
        build_runtime_context(datetime(2026, 10, 19, 11, 0))
    with pytest.raises(ValueError):
        is_clinic_open(datetime(2026, 10, 19, 11, 0))


def test_default_now_is_ist():
    assert build_runtime_context().now_ist.utcoffset() == timedelta(hours=5, minutes=30)


def test_staff_availability_overrides_the_transfer_window():
    assert build_runtime_context(at(MON, 11), staff_available=False).transfer_available is False
    late = build_runtime_context(at(MON, 19, 45), staff_available=True)
    assert late.transfer_available is True and late.clinic_open_now is True


def test_next_working_day_skips_sunday():
    assert next_working_day(at(SAT, 21).date()) == at(MON, 9).date()
    assert next_working_day(at(MON, 9).date()).weekday() == 1


def test_caller_number_is_optional_normalised_and_never_shown():
    ctx = build_runtime_context(at(MON, 11), caller_number="+91 98765-43210")
    assert ctx.caller_number == "9876543210" and ctx.caller_number_available
    assert "9876543210" not in repr(ctx) and "43210" not in repr(ctx)
    assert build_runtime_context(at(MON, 11)).caller_number is None
    assert build_runtime_context(at(MON, 11), caller_number="011 2345 6789").caller_number is None  # landline


def test_caller_number_never_appears_in_any_response(open_ctx):
    for text in ["what is my number", "what's your number", "call me back", "I want to speak to a person"]:
        for lang in LANGS:
            assert "43210" not in policy.respond(text, open_ctx, lang).text


# --- Phone numbers ----------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["9876543210", "+919876543210", "+91 98765 43210", "09876543210",
                                 "98765-43210", "(+91) 98765 43210", "6000000000", "7123456789", "8527275521"])
def test_valid_indian_mobiles(raw):
    assert len(phone.normalize_indian_mobile(raw)) == 10 and phone.is_valid_indian_mobile(raw)


@pytest.mark.parametrize("raw", ["", None, "5876543210", "1234567890", "987654321", "98765432101",
                                 "919876543210", "+1 9876543210", "+91 0987654321", "00919876543210",
                                 "98765abcde", "011 2345 6789"])
def test_invalid_indian_mobiles(raw):
    assert not phone.is_valid_indian_mobile(raw)
    with pytest.raises(phone.InvalidPhone):
        phone.normalize_indian_mobile(raw)


def test_phone_spoken_and_masked_forms():
    assert phone.spoken_digits("9876543210") == "9 8 7 6 5, 4 3 2 1 0"
    assert phone.masked("9876543210") == "XXXXXX3210"


# --- Callback rules ---------------------------------------------------------------------------

def args(**overrides):
    base = dict(name="Asha Verma", phone="+91 98765 43210", language="en", reason="Wants an appointment",
                category="appointment", urgent=False, notes=None)
    return CreateCallbackArgs(**{**base, **overrides})


def test_callback_categories():
    assert [c.value for c in CallbackCategory] == ["appointment", "enquiry", "panel", "human_request", "urgent", "other"]


def test_callback_details_validate_phone_and_urgency():
    details = CallbackDetails(**args().model_dump())
    assert details.phone == "9876543210" and details.language == Language.EN
    with pytest.raises(ValidationError):
        CallbackDetails(**args(phone="12345").model_dump())
    with pytest.raises(ValidationError):
        CallbackDetails(**args(urgent=True).model_dump())  # urgent flag needs the urgent category
    with pytest.raises(ValidationError):
        CallbackDetails(**args(category="urgent").model_dump())
    with pytest.raises(ValidationError):
        CallbackDetails(**args(name="  ").model_dump())
    with pytest.raises(ValidationError):
        CreateCallbackArgs(**args().model_dump(), extra_field="x")


def test_callback_only_after_confirmation(open_ctx):
    session = policy.CallSession(open_ctx)
    with pytest.raises(policy.CallbackRefused) as refused:
        session.create_callback(args(), confirmed=False)
    assert refused.value.code == "not_confirmed" and session.callbacks == []
    assert session.create_callback(args(), confirmed=True).phone == "9876543210"


def test_one_callback_per_call_plus_one_separate_urgent_escalation(open_ctx):
    session = policy.CallSession(open_ctx)
    session.create_callback(args(), confirmed=True)
    with pytest.raises(policy.CallbackRefused) as refused:
        session.create_callback(args(category="enquiry", reason="Another question"), confirmed=True)
    assert refused.value.code == "duplicate"
    session.create_callback(args(category="urgent", urgent=True, reason="Swelling spreading"), confirmed=True)
    with pytest.raises(policy.CallbackRefused):
        session.create_callback(args(category="urgent", urgent=True, reason="Again"), confirmed=True)
    assert [c.category for c in session.callbacks] == ["appointment", "urgent"]


def test_urgent_first_allows_no_second_callback(open_ctx):
    session = policy.CallSession(open_ctx)
    session.create_callback(args(category="urgent", urgent=True), confirmed=True)
    with pytest.raises(policy.CallbackRefused):
        session.create_callback(args(), confirmed=True)


def test_callback_on_the_caller_number_without_reading_it(open_ctx):
    session = policy.CallSession(open_ctx)
    line = policy.confirm_details_line("Asha", CALLER_NUMBER, "en")
    assert "the number you're calling from" in line and "4 3 2 1 0" not in line
    assert session.create_callback(args(phone=CALLER_NUMBER), confirmed=True).phone == "9876543210"
    no_caller = policy.CallSession(build_runtime_context(at(MON, 11)))
    with pytest.raises(policy.CallbackRefused) as refused:
        no_caller.create_callback(args(phone=CALLER_NUMBER), confirmed=True)
    assert refused.value.code == "no_caller_number"


def test_readback_confirms_name_and_digits():
    assert policy.confirm_details_line("Asha", "9876543210", "en") == (
        "Just to confirm, your name is Asha and we should call you on 9 8 7 6 5, 4 3 2 1 0. Is that right?")


def test_callback_promise_wording(open_ctx, closed_ctx):
    assert policy.callback_promise(open_ctx, "en") == "as soon as possible during clinic hours"
    assert policy.callback_promise(closed_ctx, "en") == "on the next working day"
    saturday_night = build_runtime_context(at(SAT, 20, 30))
    assert policy.callback_promise(saturday_night, "en") == "on the next working day"
    details = CallbackDetails(**args().model_dump())
    assert policy.CallSession(closed_ctx).callback_created_line(details) == (
        "Thank you, Asha Verma. Our team will call you back on the next working day.")


def test_no_line_promises_a_fixed_number_of_minutes():
    every_line = [text for versions in [*wording.LINES.values(), *wording.UNKNOWN_LEADS.values(),
                                        *wording.PROMISE.values()] for text in versions.values()]
    for text in every_line:
        assert not re.search(r"\d+\s*(?:min|minute|मिनट)", text, re.IGNORECASE), text


# --- Unknown information ----------------------------------------------------------------------

UNKNOWN_QUESTIONS = {
    "doctor_schedule": ["When is Dr Raj available?", "What days does the doctor come in?", "doctor kab milenge"],
    "treatment_cost": ["How much does a root canal cost?", "implant ka kitna kharcha hai", "इम्प्लांट की कीमत क्या है"],
    "insurance": ["Do you take insurance?", "Is mediclaim accepted?", "क्या बीमा चलता है"],
    "appointment_availability": ["Can I come tomorrow?", "Is there a slot at 5?", "Are you available tomorrow?"],
    "appointment_request": ["I want to book an appointment", "Can I book a consultation?", "अपॉइंटमेंट चाहिए"],
    "treatment_suitability": ["Do I need a root canal?", "Am I suitable for implants?", "kya mujhe braces chahiye"],
    "service_not_listed": ["Do you do Botox?", "Do you do Invisalign?"],
    "whatsapp": ["Do you have a WhatsApp group?"],
    "parking": ["Is there parking?"],
    "not_approved": ["What's the weather like?", "Is Dr Raj married?"],
}


@pytest.mark.parametrize("topic, question", [(t, q) for t, qs in UNKNOWN_QUESTIONS.items() for q in qs])
def test_unknown_information_never_fabricates(open_ctx, topic, question):
    for lang in LANGS:
        result = policy.respond(question, open_ctx, lang)
        assert isinstance(result, UnknownInformation), (question, result)
        assert result.topic == topic and result.answered is False
        assert result.next_action == NextAction.OFFER_CALLBACK and result.callback_category
        # The only amount ever spoken is the approved consultation fee.
        assert set(re.findall(r"\d+", result.text)) <= {"500"}
        assert not re.search(r"\b\d{1,2}(?::\d{2})? ?(?:AM|PM|baje)\b|बजे", result.text, re.IGNORECASE)


def test_unknown_information_offers_callback_in_every_language(open_ctx):
    texts = {lang: policy.unknown_information("not_approved", lang).text for lang in LANGS}
    assert "don't want to guess" in texts["en"] and "call you back" in texts["en"]
    assert "अंदाज़ा नहीं" in texts["hi"] and "कॉल" in texts["hi"]
    assert "guess nahin" in texts["hinglish"] and "call back" in texts["hinglish"]


def test_treatment_cost_never_quoted(open_ctx):
    for question in ["how much is an implant", "braces price", "cost of cleaning", "how much does it cost"]:
        result = policy.respond(question, open_ctx)
        assert result.topic == "treatment_cost" and "can't quote treatment prices" in result.text


# --- Approved answers -------------------------------------------------------------------------

@pytest.mark.parametrize("question, topic, expect", [
    ("What are your opening hours?", "hours", "Monday to Saturday"),
    ("Are you open on Sunday?", "hours", "closed on Sunday"),
    ("Where is the clinic?", "address", "Pragati Public School"),
    ("What's your email?", "contact", "bhargava dot smriti dot raj at gmail dot com"),
    ("What is the consultation fee?", "consultation_fee", "500 rupees"),
    ("Can I pay by UPI?", "payment", "cash, UPI or card"),
    ("Who are your doctors?", "doctors", "Doctor Raj Tiwary"),
    ("Do you do implants?", "services", "dental implants"),
    ("Do you treat children?", "services", "children's dentistry"),
])
def test_approved_answers(open_ctx, question, topic, expect):
    result = policy.respond(question, open_ctx)
    assert (result.path, result.topic, result.next_action) == (PolicyPath.ANSWER, topic, NextAction.CONTINUE)
    assert expect in result.text


def test_answers_exist_in_hindi_and_hinglish(open_ctx):
    assert "रविवार" in policy.respond("क्लिनिक कब खुलता है", open_ctx, "hi").text
    assert "Sunday" in policy.respond("clinic kab tak khula hai", open_ctx, "hinglish").text
    assert "500 रुपये" in policy.respond("कंसल्टेशन फीस कितनी है", open_ctx, "hi").text
    assert "Pragati Public School ke paas" in policy.respond("clinic kahan hai", open_ctx, "hinglish").text


# --- Clinical, tooth pain and emergencies -----------------------------------------------------

@pytest.mark.parametrize("question", [
    "What medicine should I take for my tooth?", "How much ibuprofen can I take?", "Any home remedies?",
    "Is it serious?", "Should I be worried about this?", "Do I have an infection?", "Will it go away on its own?",
    "My cheek is a bit swollen", "dard ke liye kaunsi dawai lun", "koi gharelu nuskha batao",
    "कौन सी दवा लूं", "क्या यह गंभीर है",
])
def test_clinical_questions_get_no_advice_and_a_callback(open_ctx, question):
    result = policy.respond(question, open_ctx)
    assert result.path == PolicyPath.CLINICAL and result.next_action == NextAction.OFFER_CALLBACK
    assert "can't diagnose" in result.text and not result.urgent
    for word in ("ibuprofen", "paracetamol", "clove", "salt", "probably", "nothing to worry", "don't worry"):
        assert word not in result.text.lower()


@pytest.mark.parametrize("question", [
    "I have a toothache", "My teeth are sensitive to cold", "My tooth hurts when I chew",
    "daant mein bahut dard hai", "मुझे दांत में दर्द है",
])
def test_ordinary_tooth_pain_is_not_an_emergency(open_ctx, question):
    result = policy.respond(question, open_ctx)
    assert result.path == PolicyPath.TOOTH_PAIN and not result.urgent
    assert result.callback_category == CallbackCategory.APPOINTMENT
    assert "subject to the doctor's assessment" in result.text and "112" not in result.text


URGENT = {
    "heavy_bleeding": ["My gums are bleeding and it won't stop", "There is heavy bleeding after extraction",
                       "khoon ruk nahi raha", "खून नहीं रुक रहा"],
    "spreading_swelling": ["The swelling is spreading to my eye", "My face is swollen up to the neck",
                           "sujan aankh tak aa gayi", "सूजन गर्दन तक फैल रही है"],
    "breathing_swallowing": ["I can't breathe properly", "I have difficulty swallowing",
                             "saans lene mein dikkat ho rahi hai", "निगलने में दिक्कत है"],
    "face_jaw_injury": ["I think I broke my jaw", "He fell and hit his face badly", "jabda toot gaya"],
    "unconscious": ["He passed out", "She lost consciousness after the extraction", "behosh ho gaya"],
    "fever_with_swelling": ["I have high fever and swelling", "bukhar hai aur sujan bhi", "बुखार और सूजन है"],
}


@pytest.mark.parametrize("rule, question", [(r, q) for r, qs in URGENT.items() for q in qs])
def test_urgent_symptoms_take_the_emergency_path(open_ctx, rule, question):
    result = policy.respond(question, open_ctx)
    assert result.path == PolicyPath.EMERGENCY and result.urgent and rule in result.matched_rules
    assert result.callback_category == CallbackCategory.URGENT
    assert result.text.startswith("This sounds like an emergency. Please call 112 now")


def test_emergency_wins_over_every_other_rule(open_ctx):
    result = policy.respond("What medicine for swelling spreading to my eye? Connect me to a person", open_ctx)
    assert result.path == PolicyPath.EMERGENCY


def test_emergency_follow_up_depends_on_transfer(open_ctx, closed_ctx):
    assert policy.respond("I can't breathe", open_ctx).next_action == NextAction.TRANSFER
    closed = policy.respond("I can't breathe", closed_ctx, "hi")
    assert closed.next_action == NextAction.OFFER_CALLBACK
    assert closed.text.startswith("यह इमरजेंसी") and "112" in closed.text and "अगले कार्य दिवस" in closed.text


def test_panel_questions_become_panel_callbacks(open_ctx):
    for question in ["Do you accept ECHS?", "I am a CISF employee, can I come?", "Is DU staff covered?",
                     "Air India panel rates?", "What documents do I need for CGHS?"]:
        result = policy.respond(question, open_ctx)
        assert isinstance(result, UnknownInformation) and result.path == PolicyPath.PANEL
        assert result.callback_category == CallbackCategory.PANEL
        assert "can't confirm eligibility, rates, documents or referrals" in result.text
    assert policy.respond("Are you CGHS empanelled?", open_ctx).text.startswith(
        "Smriti Raj Dentistry is CGHS-empanelled.")
    assert "CGHS-empanelled" not in policy.respond("Do you accept ECHS?", open_ctx).text
    assert policy.classify("main abhi kar du?").path != PolicyPath.PANEL  # Hinglish "du" is not Delhi University


# --- Human transfer ---------------------------------------------------------------------------

def test_human_request_transfers_when_available(open_ctx):
    session = policy.CallSession(open_ctx)
    result = session.respond("I want to speak to a person")
    assert result.next_action == NextAction.TRANSFER and result.text == "Of course. Let me connect you to our reception now."
    assert not session.can_end_call().allowed  # nothing has happened yet
    assert session.transfer_result(True, "en") is None
    assert session.can_end_call().allowed


def test_transfer_failure_becomes_callback_capture(open_ctx):
    session = policy.CallSession(open_ctx)
    session.respond("reception se baat karwa do", "hinglish")
    failed = session.transfer_result(False, "hinglish")
    assert failed.next_action == NextAction.CAPTURE_CALLBACK
    assert failed.callback_category == CallbackCategory.HUMAN_REQUEST
    assert "connect nahin kar paayi" in failed.text and "clinic hours mein jaldi se jaldi" in failed.text
    assert session.can_end_call().allowed  # callback has been offered


def test_human_request_without_transfer_goes_straight_to_callback(closed_ctx):
    session = policy.CallSession(closed_ctx)
    result = session.respond("Can I talk to the receptionist?")
    assert result.next_action == NextAction.CAPTURE_CALLBACK
    assert "on the next working day" in result.text and result.text.endswith("May I have your name, please?")
    assert session.can_end_call().allowed
    with pytest.raises(policy.CallbackRefused):
        session.transfer_result(False, "en")  # never attempt a transfer that isn't available


def test_staff_unavailable_blocks_transfer_even_in_the_window():
    ctx = build_runtime_context(at(MON, 11), staff_available=False)
    assert policy.respond("connect me to a human", ctx).next_action == NextAction.CAPTURE_CALLBACK


def test_failed_urgent_transfer_captures_an_urgent_callback(open_ctx):
    session = policy.CallSession(open_ctx)
    failed = session.transfer_result(False, "en", urgent=True)
    assert failed.urgent and failed.callback_category == CallbackCategory.URGENT


# --- Spoken output ----------------------------------------------------------------------------

def test_spoken_lines_have_no_bullets_emojis_urls_or_symbols():
    texts = [t for versions in [*wording.LINES.values(), *wording.UNKNOWN_LEADS.values()] for t in versions.values()]
    texts += [s for names in wording.SERVICE_NAMES.values() for s in names]
    for text in texts:
        assert not re.search(r"^\s*[-*•]|https?://|www\.|@|₹|[\U0001F300-\U0001FAFF]|\n", text), text


def test_every_line_exists_in_all_three_languages():
    for versions in [*wording.LINES.values(), *wording.UNKNOWN_LEADS.values(), *wording.PROMISE.values(),
                     wording.FACTS]:
        assert set(versions) == set(LANGS)
    assert all(re.search(r"[ऀ-ॿ]", v["hi"]) for v in wording.LINES.values())
    assert not any(re.search(r"[ऀ-ॿ]", v["hinglish"]) for v in wording.LINES.values())


# --- Prompt renderer and tool contracts -------------------------------------------------------

def test_prompt_includes_runtime_knowledge_safety_and_tools(open_ctx):
    text = prompt.render_system_prompt(open_ctx)
    for expected in [
        "Monday 19 October 2026, 11:00 AM IST", "Clinic open now: yes", "Transfer to reception available: yes",
        "Caller number: available", f'phone="{CALLER_NUMBER}"', '"as soon as possible during clinic hours"',
        "Basement Floor, Plot Number 54, Sector 13, Dwarka, New Delhi 110075", "Near Pragati Public School",
        "+91 85272 75521", "+91 73037 86284", "bhargava.smriti.raj@gmail.com", "Dr. Raj Tiwary: Periodontist and Implantologist",
        "Initial consultation fee: 500 rupees only", "never quote them", "CGHS-empanelled",
        "Ask one question at a time", "English, Hindi or Hinglish", "no bullet points", "emojis", "URLs",
        "no diagnosis", "no medicine or dosage advice", "no home remedies", "no reassurance", "call 112",
        "Heavy bleeding that will not stop", "Loss of consciousness", "read back the name and number",
        "transfer_to_reception", "create_callback", "end_call", "Never guess", "Doctor schedules",
        "Treatment costs", "Panel eligibility", "Insurance", "Appointment availability", "Treatment suitability",
        "Never promise a callback within a set number of minutes",
    ]:
        assert expected in text, expected
    assert "9876543210" not in text and "43210" not in text


def test_prompt_reflects_closed_clinic_and_missing_caller_number(closed_ctx):
    text = prompt.render_system_prompt(closed_ctx)
    assert "Clinic open now: no" in text and "Transfer to reception available: no" in text
    assert "Caller number: not available" in text and '"on the next working day"' in text


def test_tool_contracts():
    assert [t.name for t in TOOLS] == ["create_callback", "transfer_to_reception", "end_call"]
    schema = TOOLS[0].parameters_schema()
    assert set(schema["properties"]) == {"name", "phone", "language", "reason", "category", "urgent", "notes"}
    assert set(schema["required"]) == {"name", "phone", "language", "reason", "category", "urgent"}
    assert TOOLS[1].parameters_schema()["properties"] == {} and TOOLS[2].parameters_schema()["properties"] == {}
    assert all(t.rules for t in TOOLS)


def test_example_lines_in_three_languages():
    examples = {lang: prompt.example_lines(lang) for lang in LANGS}
    assert all(len(lines) == len(prompt.EXAMPLE_KEYS) for lines in examples.values())
    assert examples["hi"][0].startswith("यह इमरजेंसी") and examples["hinglish"][0].startswith("Yeh emergency")
