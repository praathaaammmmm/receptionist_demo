"""Approved clinic knowledge for the patient-facing assistant.

The assistant answers ONLY from this file plus the clinic profile, doctors and
services stored in the database (editable on the Settings page). Anything it
cannot answer from here becomes a callback task for the front desk.

Everything marked PLACEHOLDER must be supplied or approved by the clinic owner.
"""

# "guided" = deterministic, rule-based demo flow. No LLM provider or API key is
# configured, so nothing here calls an AI model. If a provider is added later it
# must sit behind an adapter that can only use these answers and the same
# booking/callback actions as app/services/assistant.py.
ASSISTANT_MODE = "guided"

CLINIC_WEBSITE = "https://smritirajdentistry.com"

CLINIC_HOURS = (
    "Smriti Raj Dentistry is open Monday to Saturday from 9:00 AM to 8:00 PM. The clinic is closed on Sunday."
)

BOOKING_GUIDANCE = (
    "I can book a consultation for you here. I'll ask for the patient's name and mobile number, "
    "the reason for the visit and a preferred doctor and day, then offer available times. "
    "Bookings are requests until our front desk confirms them."
)

CALLBACK_PROMISE = "Our staff will contact you during clinic hours."

URGENT_NOTE = (
    "If you need urgent help, please phone the clinic directly or contact your local emergency services."
)

SAFETY_NOTE = (
    "I can't give dental or medical advice. A dentist can discuss what is suitable for you at a consultation."
)

# Spoken at the start of a simulated after-hours call (see /call-demo).
VOICE_GREETING = [
    "Thank you for calling {clinic}. The clinic is closed at the moment, so you have reached our automated assistant.",
    "I can help you book a consultation, answer general questions about the clinic, or ask our front desk "
    "to call you. I can't give dental or medical advice.",
]

# One-click caller phrases on the call demo page.
VOICE_DEMO_SHORTCUTS = [
    "I need to book a consultation.",
    "What are your opening hours?",
    "I want to speak to a person.",
    "I have severe tooth pain; what medicine should I take?",
    "Can I come on Sunday?",
]

# Shown on the public page and in the welcome message.
SUGGESTED_PROMPTS = [
    "What are your opening hours?",
    "I want to book a consultation.",
    "Do you offer dental implants?",
    "I want to speak to a person.",
]

# How patients may refer to each supported service. Keys must match service names in the database.
SERVICE_ALIASES = {
    "General Consultation": [r"general consultation", r"check[- ]?ups?", r"general dentist\w*"],
    "Dental Implants": [r"implants?"],
    "Root Canal Treatment": [r"root canals?", r"\brct\b"],
    "Aligners": [r"aligners?"],
}

# Approved answers. {placeholders} are filled from the clinic record, doctors and
# services in the database: {clinic} {address} {phone} {email} {doctors} {services} {fees}
TOPICS = [
    {
        "id": "fees",
        "patterns": [r"\bfees?\b", r"\bcosts?\b", r"\bprices?\b", r"\bpricing\b", r"\bcharges?\b", r"\bhow much\b"],
        "answer": (
            "Consultation fees in this demo are sample values only:\n{fees}\n"
            "Treatment costs depend on the dentist's assessment, so I can't quote them here. "
            "Our front desk can confirm current fees."
        ),
    },
    {
        "id": "hours",
        "patterns": [r"\bhours?\b", r"\bopen\w*\b", r"\bclos\w*\b", r"\btimings?\b", r"\bwhat time\b"],
        "answer": CLINIC_HOURS,
    },
    {
        "id": "location",
        "patterns": [
            r"\bwhere\b", r"\baddress\b", r"\blocat\w*\b", r"\bdirections?\b", r"\bcontact\b",
            r"\bphone\b", r"\bnumber\b", r"\bemail\b", r"\breach you\b",
        ],
        "answer": "{clinic} is at {address}.\nPhone: {phone}\nEmail: {email}",
    },
    {
        "id": "doctors",
        "patterns": [r"\bdoctors?\b", r"\bdentists?\b", r"\bspecialists?\b", r"\bspecialit\w*\b", r"\bwho\b"],
        "answer": "Our doctors:\n{doctors}",
    },
    {
        "id": "services",
        "patterns": [r"\bservices?\b", r"\btreatments?\b", r"\boffer\w*\b", r"\bprovide\w*\b", r"\bdo you do\b"],
        "answer": "We offer consultations for:\n{services}\n" + SAFETY_NOTE,
    },
]

# Used when a patient asks whether a specific supported service is offered.
SERVICE_ANSWER = "Yes, {service} is one of the services we offer. " + SAFETY_NOTE

CALLBACK_INTROS = {
    "human": "Of course. I'll ask our front desk to call you.",
    "clinical": (
        "I'm not able to answer clinical or medical questions, and I can't suggest a diagnosis or treatment. "
        "I'll ask our front desk to call you so a member of the team can help.\n" + URGENT_NOTE
    ),
    "unsupported": "I don't have approved information to answer that. I'll ask our front desk to call you.",
    # Safe wording for government-scheme enquiries: collect the scheme, never confirm eligibility.
    "cghs": (
        "I can't confirm CGHS or ECHS eligibility or cover here. "
        "Our front desk will check and call you back. Which scheme is your enquiry about?"
    ),
}
