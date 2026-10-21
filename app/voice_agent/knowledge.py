"""Approved clinic knowledge for the voice agent.

This is the only source of facts the voice agent may state. It is deliberately kept
apart from app/config.py and the seeded demo doctors and services, which are sample
values for the dashboard and may not match the real clinic.

Anything not recorded here is unknown: the agent must say so and offer a callback.
Items in PENDING_OWNER_REVIEW still need the clinic owner's sign-off before production.
"""
from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class OpeningHours:
    days: tuple[int, ...]  # datetime.weekday(): Monday is 0, Sunday is 6
    opens: time
    closes: time  # closed from this minute onwards
    transfer_from: time  # live transfers to reception are attempted in this window only
    transfer_until: time
    timezone: str
    summary: str
    closed_summary: str


@dataclass(frozen=True)
class Clinic:
    name: str
    address: str
    landmark: str
    reception_phone: str
    alternate_phone: str
    email: str


@dataclass(frozen=True)
class Doctor:
    name: str
    specialties: tuple[str, ...]


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    # How callers may name the service, in English, Hinglish and Hindi (regular expressions).
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class Commercial:
    consultation_fee_inr: int
    quote_treatment_prices: bool
    payment_methods: tuple[str, ...]
    empanelments: tuple[str, ...]
    # Panel schemes: every question about these becomes a panel callback.
    panel_schemes: tuple[str, ...]
    panel_never_discuss: tuple[str, ...]


@dataclass(frozen=True)
class ApprovedKnowledge:
    clinic: Clinic
    hours: OpeningHours
    doctors: tuple[Doctor, ...]
    specialist_support: tuple[str, ...]
    services: tuple[Service, ...]
    commercial: Commercial


APPROVED = ApprovedKnowledge(
    clinic=Clinic(
        name="Smriti Raj Dentistry",
        address="Basement Floor, Plot Number 54, Sector 13, Dwarka, New Delhi 110075",
        landmark="Near Pragati Public School",
        reception_phone="+91 85272 75521",
        alternate_phone="+91 73037 86284",
        email="bhargava.smriti.raj@gmail.com",
    ),
    hours=OpeningHours(
        days=(0, 1, 2, 3, 4, 5),
        opens=time(9, 0),
        closes=time(20, 0),
        transfer_from=time(9, 30),
        transfer_until=time(19, 30),
        timezone="IST",
        summary="Monday to Saturday, 9:00 AM to 8:00 PM IST",
        closed_summary="Sunday",
    ),
    doctors=(
        Doctor("Dr. Raj Tiwary", ("Periodontist", "Implantologist")),
        Doctor("Dr. Smriti Raj", ("Pediatric Dentistry", "Orthodontics")),
    ),
    specialist_support=("endodontics", "oral surgery", "prosthodontics", "orthodontics"),
    services=(
        Service("checkup", "Dental check-ups and consultations",
                (r"check[- ]?ups?", r"consultations?", "चेकअप", "चेक-अप")),
        Service("cavity", "Tooth pain and cavity assessment",
                (r"cavit(?:y|ies)", r"\bkeed[ae]\b", "कैविटी", "कीड़ा", "कीड़े")),
        Service("fillings", "Fillings", (r"fillings?", "फिलिंग")),
        Service("root_canal", "Root canal treatment", (r"root ?canals?", r"\brct\b", "रूट कैनाल")),
        Service("cleaning", "Teeth cleaning and scaling",
                (r"clean(?:ing)?", r"scaling", r"\bsafai\b", "सफ़ाई", "सफाई", "स्केलिंग", "क्लीनिंग")),
        Service("extraction", "Tooth extraction",
                (r"extract(?:ion)?", r"(?:remove|pull|take out) (?:a |my )?(?:tooth|teeth)",
                 r"\b(?:daant|dant|daat)\b.*\bnik(?:a|aa)l", "दांत निकाल", "दाँत निकाल")),
        Service("crowns_bridges", "Crowns and bridges", (r"crowns?", r"bridges?", r"\bcaps?\b", "क्राउन", "ब्रिज", "कैप")),
        Service("implants", "Dental implants", (r"implants?", "इम्प्लांट", "इंप्लांट")),
        Service("braces_aligners", "Braces and clear aligners",
                (r"braces", r"aligners?", "ब्रेसेस", "ब्रेसिज़", "अलाइनर", "एलाइनर")),
        Service("smile_whitening", "Smile design and teeth whitening",
                (r"smile (?:design|makeover)", r"whiten(?:ing)?", "व्हाइटनिंग", "स्माइल डिज़ाइन", "स्माइल डिजाइन")),
        Service("children", "Children's dentistry",
                (r"\bchild(?:ren)?\b", r"\bkids?\b", r"pa?ediatric", r"\bbachch?(?:a|e|on|o)\b", "बच्च")),
        Service("gum", "Gum treatment", (r"\bgums?\b", r"\bmasood(?:a|e|on|o)\b", "मसूड़")),
        Service("xray", "Digital dental X-rays", (r"x[- ]?rays?", "एक्स-रे", "एक्सरे")),
        Service("same_day", "Same-day tooth or implant consultation, subject to doctor assessment",
                (r"same[- ]day", r"\baaj hi\b", "आज ही")),
    ),
    commercial=Commercial(
        consultation_fee_inr=500,
        quote_treatment_prices=False,
        payment_methods=("cash", "UPI", "cards"),
        empanelments=("CGHS",),
        panel_schemes=("CGHS", "ECHS", "CISF", "DU", "Air India"),
        panel_never_discuss=("eligibility", "rates", "documents", "referrals", "promises"),
    ),
)

# Not yet confirmed by the clinic owner. Production use waits on each of these.
PENDING_OWNER_REVIEW = (
    "Every fact above (address, landmark, hours, phone numbers, email, doctors, specialist support, "
    "services, the 500 rupee initial consultation fee, payment methods and CGHS empanelment) is the "
    "approved brief for this phase; the owner must re-confirm it before the agent answers real callers.",
    "The live-transfer window (Monday to Saturday, 9:30 AM to 7:30 PM IST) and who answers transfers.",
    "Hindi and Hinglish wording in app/voice_agent/wording.py, including the Devanagari spelling of "
    "the doctors' names, the address and the email address read aloud.",
    "The urgent-symptom list and the 112 emergency instruction in app/voice_agent/policy.py.",
    "Whether 'same-day consultation, subject to doctor assessment' may be offered for ordinary tooth pain.",
    "Who handles panel callbacks (CGHS, ECHS, CISF, DU, Air India) and how quickly.",
    "The dashboard's demo doctors, services and fees still differ from this knowledge; they are not merged.",
)
