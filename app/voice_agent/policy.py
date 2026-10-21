"""Safety and conversation policy for the voice agent. Deterministic: no LLM decides these rules.

`respond()` classifies one caller utterance with the data-driven RULES below, checked in
order, so the safest path wins: urgent symptoms first, then clinical questions, panel
schemes, requests for a person, questions only the doctor or front desk can answer,
ordinary tooth pain, and finally approved facts. Anything that matches nothing is
unknown information: the agent says it doesn't know and offers a callback.

`CallSession` holds the per-call rules: callbacks only after confirmation, at most one
per call (plus one separate urgent escalation), and no ending a call where the caller
asked for a person until they were transferred or offered a callback.

Patterns match English, Hinglish (Roman) and Hindi (Devanagari). They err towards the
safer path: a false emergency costs a caller a 112 instruction, a missed one could cost more.
Negation is not understood ("no bleeding" still matches bleeding rules only if the wording
also says it won't stop, is heavy, and so on).
"""
import re
from dataclasses import dataclass, field

from . import knowledge_base, wording
from .context import RuntimeContext
from .knowledge import APPROVED, ApprovedKnowledge
from .phone import spoken_digits
from .schemas import (
    CALLER_NUMBER,
    CallbackCategory,
    CallbackDetails,
    CreateCallbackArgs,
    Language,
    NextAction,
    PolicyPath,
    PolicyResponse,
    UnknownInformation,
)


@dataclass(frozen=True)
class Rule:
    """Matches when every group has at least one matching pattern (AND of ORs)."""

    id: str
    label: str
    groups: tuple[tuple[str, ...], ...]

    def matches(self, text: str) -> bool:
        return all(any(re.search(p, text, re.IGNORECASE) for p in group) for group in self.groups)


def _rule(id: str, label: str, *groups: tuple[str, ...]) -> Rule:
    return Rule(id, label, groups)


_SWELL = (r"swell", r"swollen", r"\bsoo?j(?:an|a|i)\b", r"\bsujan\b", "सूजन", "सूज")

# C. Urgent symptoms. The response is always: call 112 / go to emergency care now.
URGENT_SYMPTOMS = (
    _rule("heavy_bleeding", "Heavy bleeding that will not stop",
          (r"bleed.*\b(?:won'?t|will not|doesn'?t|does not|isn'?t|is not|not|can'?t|cannot) (?:stop|be stopped)",
           r"bleed.*\bnot stopping", r"bleed\w* (?:won'?t|will not|doesn'?t|does not|isn'?t|is not|not) stop",
           r"(?:won'?t|will not|can'?t|cannot) stop (?:the )?bleed",
           r"(?:heavy|heavily|a lot of|lots of|severe|non[- ]?stop|continuous|uncontrolled) bleed",
           r"bleed\w* (?:heavily|a lot|non[- ]?stop|continuously)",
           r"\bkhoon\b.*\bnahi?n? ruk", r"\bbahut (?:zyada )?khoon\b", r"\bkhoon\b.*\b(?:band|ruk) nahi",
           "खून.*नहीं रुक", "बहुत खून", "खून.*बंद नहीं")),
    _rule("spreading_swelling", "Facial or neck swelling that is spreading or affecting the eye",
          _SWELL,
          (r"spread", r"\beyes?\b", r"\bneck\b", r"\bthroat\b", r"\bgetting (?:bigger|worse)\b",
           r"\bphail", r"\bfail rah", r"\baankh", r"\bgardan\b", r"\bgal[ae]\b",
           "फैल", "आँख", "आंख", "गर्दन", "गले")),
    _rule("breathing_swallowing", "Difficulty breathing or swallowing",
          (r"(?:difficult\w*|trouble|hard|can'?t|cannot|unable to|struggling to|problem) "
           r"(?:in |with )?(?:breath|swallow)",
           r"(?:breath\w*|swallow\w*) (?:is )?(?:difficult|hard|a problem)", r"short(?:ness)? of breath",
           r"\bsaa?ns\b.*\b(?:dikkat|takl[ei]e?f|pareshani|nahi|phool)", r"\bnigal\w*\b.*\b(?:dikkat|nahi|takl)",
           "साँस.*(?:दिक्कत|तकलीफ|नहीं|फूल)", "सांस.*(?:दिक्कत|तकलीफ|नहीं|फूल)", "निगल.*(?:दिक्कत|नहीं|तकलीफ)")),
    _rule("face_jaw_injury", "Serious face or jaw injury",
          (r"(?:serious|bad|major|severe|big) (?:face|facial|jaw) injur", r"(?:broke|broken|fractured?) (?:my |his |her )?jaw",
           r"jaw (?:is |was )?(?:broken|fractured|dislocated)", r"(?:accident|fell|fall|hit|punched).*\b(?:face|jaw)\b",
           r"\b(?:face|jaw)\b.*\b(?:accident|injur)", r"\bjab(?:da|de)\b.*\b(?:tut|toot|chot)", r"\bchehr[ae]\b.*\bchot\b",
           r"\baccident\b", "जबड़ा टूट", "जबड़े.*चोट", "चेहरे.*चोट", "एक्सीडेंट", "दुर्घटना")),
    _rule("unconscious", "Loss of consciousness",
          (r"(?:lost|loss of|losing|lose) consciousness", r"unconscious", r"passed out", r"faint(?:ed|ing)",
           r"\bbehosh\b", "बेहोश")),
    _rule("fever_with_swelling", "High fever with swelling",
          (r"fever", r"high temperature", r"\bbukh?aa?r\b", r"\btaap\b", "बुखार"),
          _SWELL),
)

# A. Clinical questions: medicines, dosage, home remedies, diagnosis or reassurance.
CLINICAL = _rule("clinical", "Clinical question", (
    r"\b(?:medicines?|medication|tablets?|pills?|pain ?killers?|antibiotics?|doses?|dosage|mg|ibuprofen|paracetamol|"
    r"crocin|combiflam|amoxicillin|dolo|ointment|gel)\b",
    r"what (?:should|can|do) i (?:take|apply|use|put)", r"home remed", r"\bremed(?:y|ies)\b", r"\bclove oil\b",
    r"\bsalt water\b", r"is (?:it|this|that) (?:serious|normal|dangerous|an infection|infected|cancer|bad)",
    r"(?:do|could|might|can) i have (?:an? )?(?:infection|abscess|cancer|cavity|gum disease)",
    r"what(?:'s| is) wrong with", *_SWELL, r"should i (?:be )?worr", r"(?:will|would) (?:it|this) (?:go away|heal|get better)",
    r"\b(?:dawai|dawa|dava|davai|goli|golia)\b", r"\bkya (?:khaun|khau|lagaun|lagau|lun|loon)\b",
    r"\bgharelu\b", r"\bnuskh?[ae]\b", r"\bserious (?:hai|to nahi)", r"\bchinta\b", r"\binfection (?:hai|to nahi)",
    "दवा", "दवाई", "गोली", "घरेलू", "नुस्खा", "गंभीर", "चिंता", "इन्फेक्शन",
    # aftercare and recovery instructions
    r"\bafter (?:my |the |a |an )?(?:extraction|root canal|rct|implant|surgery|filling|cleaning|scaling)\b.*"
    r"\b(?:eat|drink|brush|smok|care|do|pain|bleed|swell|normal|heal|rinse)",
    r"\b(?:eat|drink|brush|rinse|smoke)\b.*\bafter (?:my |the |a |an )?(?:extraction|root canal|rct|implant|surgery|filling)",
    r"\b(?:extraction|root canal|rct|implant|surgery) ke baad\b",
    # X-ray, report or test interpretation
    r"\b(?:x-?ray|report|scan|result)s?\b.*\b(?:shows?|says?|means?|normal|look|found)\b",
    r"\breport (?:mein|me) kya\b", "रिपोर्ट.*(?:क्या|मतलब)", "एक्स-रे.*(?:क्या|मतलब)",
))

PANEL = _rule("panel", "Panel scheme question", (
    r"\bcghs\b", r"\bechs\b", r"\bcisf\b", r"(?-i:\bDU\b)", r"delhi university", r"air ?india",
    r"\bpanel\b", r"empanel", "सीजीएचएस", "ईसीएचएस", "सीआईएसएफ", "एयर इंडिया", "पैनल",
))
_CGHS = (r"\bcghs\b", "सीजीएचएस")

HUMAN_REQUEST = _rule("human_request", "Caller asks for a person", (
    r"(?:speak|talk) (?:to|with) (?:a |an |the |some )?(?:person|human|someone|somebody|receptionist|reception|staff|"
    r"doctor|real|actual|manager|owner)",
    r"\b(?:real|actual|live) person\b", r"\bhuman\b", r"\boperator\b", r"connect me", r"transfer (?:me|the call)",
    r"\bkisi (?:insaan|aadmi|person|staff|insan)\b", r"\b(?:reception(?:ist)?|doctor|staff|insaan|insan|manager)\b.*\bbaat\b",
    r"\bbaat karwa", "किसी (?:इंसान|व्यक्ति|स्टाफ)", "(?:रिसेप्शन|डॉक्टर|स्टाफ|इंसान).*बात", "बात करवा", "बात करनी",
))

TOOTH_PAIN = _rule("tooth_pain", "Ordinary tooth pain or sensitivity", (
    r"tooth ?ache", r"\b(?:tooth|teeth|dental|gum|gums|molar|wisdom)\b.*\b(?:pain|ache|aching|hurts?|hurting|sore|sensitiv)",
    r"\b(?:pain|ache|sensitivity|sore)\b.*\b(?:tooth|teeth|gum|gums|molar)\b", r"\bsensitiv",
    r"\b(?:daant|dant|daat|daanton|danto)\b.*\b(?:dard|dukh|jhanjhan)", r"\bdard\b", r"\bjhanjhan",
    r"\bthand?a (?:lagta|lag raha|pani)", "दर्द", "झनझनाहट", "ठंडा लग",
))

# Questions only the doctor or front desk can answer, by topic. Each becomes UnknownInformation.
UNKNOWN_TOPICS = (
    _rule("treatment_suitability", "Treatment suitability",
          (r"(?:am i|is (?:he|she|my \w+)) (?:suitable|eligible|a candidate|a good candidate|fit) for",
           r"(?:do|will|would) i need (?!(?:an? |to (?:book|make|get|have) an? )?(?:consultation|appointment|check[- ]?up))",
           r"should i (?:get|have|go for|do)\b",
           r"(?:is|are) (?:an? )?(?:implants?|braces|aligners?|root canals?|rct|extraction|whitening)\b.*\b"
           r"(?:right|good|suitable|safe|better|best|ok)",
           r"which (?:treatment|option|one) (?:is|would be|will be) (?:best|better|right)", r"better option",
           r"\bkya mujhe\b.*\b(?:chahiye|karwana|lagwana|zaroorat)", r"\b(?:sahi|theek|thik) rahega\b",
           "क्या मुझे.*(?:चाहिए|करवाना|लगवाना|ज़रूरत|जरूरत)", "सही रहेगा", "ठीक रहेगा")),
    _rule("insurance", "Insurance",
          (r"insurance", r"mediclaim", r"\btpa\b", r"cashless", r"reimburse", r"\bclaim\b", r"\bbee?ma\b",
           "बीमा", "इंश्योरेंस", "क्लेम")),
    _rule("doctor_schedule", "Doctor schedules",
          (r"\b(?:dr\.?|doctors?)(?:\W|$)", "डॉक्टर", "डाक्टर"),
          (r"\b(?:available|availability|timings?|schedule|which days?|what days?|come in|sits?|in today|"
           r"when|what time)\b", r"\b(?:kab|kis din|kitne baje|timing)\b", "कब", "किस दिन", "कितने बजे", "टाइमिंग")),
)

_APPOINTMENT_WORDS = (r"\bappointments?\b", r"\bbookings?\b", r"\bvisit\b", r"\bslot\b", "अपॉइंटमेंट", "बुकिंग")
INTENTS = (
    _rule("reschedule_request", "Reschedule request",
          (r"\bre-?schedul", r"\bpostpone", r"\bprepone", r"\b(?:change|move|shift) (?:my |the )?(?:appointment|booking|time|date)",
           r"\b(?:appointment|booking) (?:shift|badal|change|aage|peeche)", r"\banother (?:day|date|time)\b",
           "अपॉइंटमेंट.*(?:बदल|शिफ्ट|आगे|पीछे)", "(?:बदल|शिफ्ट).*अपॉइंटमेंट")),
    _rule("cancellation_request", "Cancellation request",
          (r"\bcancel", r"\bradd\b", "कैंसल", "रद्द"), _APPOINTMENT_WORDS + (r"\bcancel (?:it|karna|kar|karni)\b",)),
    _rule("booking_status", "Booking status enquiry",
          (r"\b(?:is|check|confirm|status|booked|confirmed)\b.*\b(?:my|the|meri|mera)\b.*\b(?:appointment|booking)",
           r"\b(?:appointment|booking) (?:status|confirmed|booked|hai kya|confirm)", r"\bdo i have an? (?:appointment|booking)",
           r"\b(?:meri|mera) (?:appointment|booking)\b", "मेरी अपॉइंटमेंट", "बुकिंग.*(?:कन्फर्म|पक्की)")),
    _rule("missed_call", "Missed-call callback",
          (r"\bmissed (?:a |your )?call", r"\bgot a call from\b", r"\byou called me\b", r"\bcall aaya tha\b",
           "मिस्ड कॉल", "कॉल आया था")),
    _rule("website_enquiry", "Website or contact-form enquiry",
          (r"\bwebsite\b", r"\bcontact form\b", r"\bonline form\b", r"\benquiry form\b", r"\bform (?:bhara|filled|submitted|bhar)",
           r"\bfilled (?:a|the|your) form\b", "वेबसाइट", "फ़ॉर्म", "फॉर्म")),
    _rule("complaint", "Complaint needing staff action",
          (r"\bcomplain", r"\bunhappy\b", r"\bnot happy\b", r"\bbad experience\b", r"\brude\b", r"\brefund\b",
           r"\bshikayat\b", "शिकायत", "नाराज़", "रिफंड")),
    _rule("patient_records", "Patient records request",
          (r"\b(?:my|patient|medical|dental|old) (?:records?|reports?|file|history|prescriptions?)\b",
           r"\bcopy of (?:my )?(?:x-?ray|report|records?)\b", "मेरी रिपोर्ट", "रिकॉर्ड")),
)

# What the rules return when they cannot place the caller's words: only these go to a language model.
UNMATCHED_TOPICS = {"not_approved", "service_not_listed"}

# Requests with an unambiguous wording, routed by rules even when a language model is configured.
EXPLICIT_INTENTS = {"reschedule_request", "cancellation_request", "booking_status", "missed_call", "website_enquiry",
                    "complaint", "patient_records", "insurance"}

_FEE_WORDS = (r"\b(?:fees?|costs?|prices?|pricing|charges?|rates?|expensive|cheap)\b", r"how much",
              r"\bkitn[ae]\b.*\b(?:paise|rupay|rupees|ka|ki|lag)", r"\bkharch", r"\bdaam\b", r"\bfees?\b",
              "फ़ीस", "फीस", "खर्च", "कीमत", "दाम", "कितने पैसे", "कितना पैसा", "चार्ज")

CONSULTATION_FEE = _rule("consultation_fee", "Initial consultation fee", _FEE_WORDS, (
    r"consult", r"check[- ]?up", r"first visit", r"initial", r"\bpehli\b", r"\bopd\b",
    "कंसल्टेशन", "परामर्श", "चेकअप", "पहली",
))
TREATMENT_COST = _rule("treatment_cost", "Treatment costs", _FEE_WORDS)

APPOINTMENT_AVAILABILITY = _rule("appointment_availability", "Appointment availability", (
    r"\bslots?\b", r"\bavailable (?:today|tomorrow|on|at|this)", r"\b(?:today|tomorrow)\b.*\bavailab",
    r"\bfree (?:today|tomorrow)\b", r"\bearliest\b", r"can i (?:come|visit|get|be seen) (?:in |at )?"
    r"(?:today|tomorrow|now|this|at \d|\d)", r"\b(?:aaj|kal)\b.*\b(?:appointment|slot|aa sakt|mil sakt|time milega)",
    "स्लॉट", "(?:आज|कल).*(?:आ सकत|मिल सकत|समय मिल|टाइम मिल)",
))
# Asking to book: no live booking on a call, so this becomes an appointment callback.
APPOINTMENT_REQUEST = _rule("appointment_request", "Appointment booking request", (
    r"\bbook(?:ing)?\b", r"\bappointments?\b", r"\b(?:schedule|fix|make|get) (?:a |an )?(?:visit|consultation|check[- ]?up)",
    "अपॉइंटमेंट", "बुक",
    # Spelling variants speech recognition produces for "appointment" (अपॉंटमेंट, अपोइंटमेंट, अपाइंटमेंट ...)
    "अप[ॉोा]\\S{0,3}ंटमेंट", r"\bap+o\w{0,3}nt?ment\b",
))

# Approved facts, in the order they are checked.
KNOWN_TOPICS = (
    _rule("hours", "Opening hours",
          (r"\b(?:hours|timings?|open|opening|opens|close|closed|closing|sunday|saturday|working days?)\b",
           r"what time (?:do|does|are) (?:you|the clinic)",
           r"\b(?:khul|khula|khulta|band|kab tak|kitne baje|samay|ravivar|itwar|shanivar)\b", r"\bkhol(?:a|te|ti|ta)\b",
           "खुल", "खोल", "बंद", "कब तक", "कितने बजे", "समय", "रविवार", "शनिवार")),
    _rule("address", "Address and landmark",
          (r"\baddress\b", r"\bwhere\b", r"\blocat(?:ion|ed)\b", r"\blandmark\b",
           r"\b(?:kahan|kaha|kidhar)\b", r"\bpata\b",
           "कहाँ", "कहां", "पता", "लोकेशन")),
    _rule("contact", "Phone numbers and email",
          (r"\b(?:phone|number|numbers|email|e-mail|mail|contact|landline)\b", r"call you",
           "नंबर", "फ़ोन", "फोन", "ईमेल")),
    _rule("payment", "Payment methods",
          (r"\b(?:pay|paying|payment|upi|gpay|google pay|phonepe|paytm|cards?|credit|debit|cash)\b",
           "भुगतान", "पेमेंट", "यूपीआई", "कार्ड", "कैश", "नकद")),
    _rule("doctors", "Doctors and specialties",
          (r"\b(?:doctors?|dentists?|dr\.?|specialists?|periodontist|implantologist|orthodontist)\b",
           "डॉक्टर", "डाक्टर"),
          (r"\b(?:who|which|what kind|tell me about|your doctors|your dentists|specialit|specialt|speciali[sz]|"
           r"qualified|names?)\b", r"\bkaun\b", "कौन")),
)

# Asked whether we offer something no approved service matches.
_SERVICE_QUESTION = (r"\bdo you (?:do|offer|have|provide|treat|give)\b", r"\b(?:offer|provide)\b",
                     r"\bkya aap\b.*\b(?:karte|hota|milta|dete)", r"\bhota hai\b", "क्या आप.*(?:करते|देते)", "होता है")


CALLBACK_REQUEST = _rule("callback_request", "Caller asks to be called back", (
    r"\bcall (?:me )?back\b", r"\bcallback\b", r"\b(?:ring|phone|call) me\b", r"\bcall back kar",
    r"\bmujhe (?:call|phone) kar", "कॉल बैक", "कॉलबैक", "मुझे (?:कॉल|फ़ोन|फोन) कर",
))

# Short replies during the conversation. NO is checked before YES ("not right", "ji nahin").
NO = _rule("no", "No", (
    r"\b(?:no|nope|nah|not|don'?t|never ?mind|wrong|incorrect|nahi|nahin|nai|mat|galat)\b", "नहीं", "मत", "गलत", "ग़लत",
))
YES = _rule("yes", "Yes", (
    r"\b(?:yes|yeah|yep|yup|sure|ok|okay|correct|right|please|go ahead|haan|haa|han|ha|ji|theek|thik|sahi|"
    r"bilkul|zaroor|zarur|kar do|kardo)\b", "हाँ", "हां", "जी", "ठीक", "सही", "बिल्कुल", "ज़रूर", "जरूर",
))
GREETING = _rule("greeting", "Only a greeting", (
    r"^\W*(?:hello|hi|hey|hii|namaste|namaskar|good (?:morning|afternoon|evening))\W*(?:ji|there)?\W*$",
    r"^\W*(?:नमस्ते|नमस्कार|हेलो|हैलो)\W*(?:जी)?\W*$",
))
GOODBYE = _rule("goodbye", "Caller is finished", (
    r"\b(?:bye|goodbye|that'?s all|that is all|nothing else|no thanks|no thank you|thank you|thanks|"
    r"bas|alvida|dhanyavaad|dhanyavad|shukriya)\b", "बस", "धन्यवाद", "अलविदा", "शुक्रिया",
))


def is_no(text: str) -> bool:
    return NO.matches(matching_text(text))


def is_yes(text: str) -> bool:
    return not is_no(text) and YES.matches(matching_text(text))


def is_greeting(text: str) -> bool:
    return GREETING.matches(_normalise(text))


def is_goodbye(text: str) -> bool:
    return GOODBYE.matches(matching_text(text))


@dataclass(frozen=True)
class Classification:
    path: PolicyPath
    topic: str
    matched_rules: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    return " ".join(text.replace("’", "'").replace("‘", "'").split())


# English words that speech recognition often writes in Devanagari, and common Hindi words, in Roman
# script. Used only to match intents: the transcript the caller sees is never changed.
MATCHING_TRANSLITERATIONS = {
    "संडे": "sunday", "मंडे": "monday", "सैटरडे": "saturday", "क्लिनिक": "clinic", "अपॉइंटमेंट": "appointment",
    "अपोइंटमेंट": "appointment", "अपॉइन्टमेंट": "appointment", "रूट कैनाल": "root canal", "इम्प्लांट": "implant",
    "इंप्लांट": "implant", "कंसल्टेशन": "consultation", "फीस": "fee", "फ़ीस": "fee", "रिसेप्शनिस्ट": "receptionist",
    "रिसेप्शन": "reception", "डॉक्टर": "doctor", "ओपन": "open", "बुक": "book", "कैंसल": "cancel", "ब्रेसेस": "braces",
    "टाइम": "time", "पेमेंट": "payment", "नंबर": "number", "एड्रेस": "address", "पार्किंग": "parking",
    "मुझे": "mujhe", "चाहिए": "chahiye", "खुला": "khula", "कितना": "kitna", "कितनी": "kitni", "बात": "baat",
    "करनी": "karni", "करना": "karna", "के लिए": "ke liye", "क्या": "kya", "है": "hai", "हैं": "hain",
    "को": "ko", "से": "se", "में": "mein", "का": "ka", "की": "ki", "के": "ke", "नहीं": "nahin", "कब": "kab",
}
# Whole Devanagari words only, so nothing inside a longer word is changed.
_LETTER = r"[\u0900-\u0963\u0966-\u097F]"  # Devanagari, except the danda punctuation
_TRANSLITERATE = re.compile(rf"(?<!{_LETTER})(?:" + "|".join(
    sorted(map(re.escape, MATCHING_TRANSLITERATIONS), key=len, reverse=True)) + rf")(?!{_LETTER})")


def matching_text(text: str) -> str:
    """The text rules are matched against: the original, plus a Roman reading of mixed-script words."""
    text = _normalise(text)
    roman = _TRANSLITERATE.sub(lambda m: MATCHING_TRANSLITERATIONS[m.group()], text)
    return text if roman == text else f"{text} \n {roman}"


def matched_services(text: str, knowledge: ApprovedKnowledge = APPROVED) -> list[str]:
    return [s.id for s in knowledge.services if any(re.search(p, text, re.IGNORECASE) for p in s.patterns)]


def _from_entry(entry: knowledge_base.Entry) -> Classification:
    path = PolicyPath.UNKNOWN if entry.status == knowledge_base.NOT_PROVIDED else PolicyPath.ANSWER
    return Classification(path, entry.id, (entry.id,))


def classify(text: str, knowledge: ApprovedKnowledge = APPROVED) -> Classification:
    text = matching_text(text)
    urgent = tuple(rule.id for rule in URGENT_SYMPTOMS if rule.matches(text))
    if urgent:
        return Classification(PolicyPath.EMERGENCY, "urgent_symptoms", urgent)
    if CLINICAL.matches(text):
        return Classification(PolicyPath.CLINICAL, "clinical_question", (CLINICAL.id,))
    if PANEL.matches(text):
        return Classification(PolicyPath.PANEL, "panel", (PANEL.id,))
    if HUMAN_REQUEST.matches(text):
        return Classification(PolicyPath.HUMAN_REQUEST, "human_request", (HUMAN_REQUEST.id,))
    suitability = UNKNOWN_TOPICS[0]
    if suitability.matches(text):
        return Classification(PolicyPath.UNKNOWN, suitability.id, (suitability.id,))
    if TOOTH_PAIN.matches(text):
        return Classification(PolicyPath.TOOTH_PAIN, "tooth_pain", (TOOTH_PAIN.id,))
    for rule in INTENTS + UNKNOWN_TOPICS[1:]:
        if rule.matches(text):
            return Classification(PolicyPath.UNKNOWN, rule.id, (rule.id,))
    entry = knowledge_base.match(text, "high")
    if entry:
        return _from_entry(entry)
    if CONSULTATION_FEE.matches(text):
        return Classification(PolicyPath.ANSWER, CONSULTATION_FEE.id, (CONSULTATION_FEE.id,))
    for rule in (TREATMENT_COST, APPOINTMENT_AVAILABILITY, APPOINTMENT_REQUEST):
        if rule.matches(text):
            return Classification(PolicyPath.UNKNOWN, rule.id, (rule.id,))
    for rule in KNOWN_TOPICS:
        if rule.matches(text):
            return Classification(PolicyPath.ANSWER, rule.id, (rule.id,))
    entry = knowledge_base.match(text, "low")
    if entry:
        return _from_entry(entry)
    services = matched_services(text, knowledge)
    if services:
        return Classification(PolicyPath.ANSWER, "services", tuple(services))
    if any(re.search(p, text, re.IGNORECASE) for p in _SERVICE_QUESTION):
        return Classification(PolicyPath.UNKNOWN, "service_not_listed")
    if CALLBACK_REQUEST.matches(text):
        return Classification(PolicyPath.CALLBACK_REQUEST, "callback_request", (CALLBACK_REQUEST.id,))
    return Classification(PolicyPath.UNKNOWN, "not_approved")


# --- Responses -------------------------------------------------------------------------------

def callback_promise(context: RuntimeContext, language: Language | str) -> str:
    """When staff will call back. Never a fixed number of minutes."""
    return wording.PROMISE["open" if context.clinic_open_now else "closed"][Language(language)]


def emergency_response(context: RuntimeContext, language: Language | str, matched: tuple[str, ...] = ()) -> PolicyResponse:
    language = Language(language)
    follow_up = (
        wording.line("emergency_transfer", language)
        if context.transfer_available
        else wording.line("emergency_callback", language, promise=callback_promise(context, language))
    )
    return PolicyResponse(
        path=PolicyPath.EMERGENCY,
        language=language,
        text=f"{wording.line('emergency', language)} {follow_up}",
        next_action=NextAction.TRANSFER if context.transfer_available else NextAction.OFFER_CALLBACK,
        topic="urgent_symptoms",
        callback_category=CallbackCategory.URGENT,
        urgent=True,
        matched_rules=matched,
    )


def clinical_response(language: Language | str) -> PolicyResponse:
    language = Language(language)
    return PolicyResponse(
        path=PolicyPath.CLINICAL,
        language=language,
        text=wording.line("clinical", language),
        next_action=NextAction.OFFER_CALLBACK,
        topic="clinical_question",
        callback_category=CallbackCategory.ENQUIRY,
        matched_rules=(CLINICAL.id,),
    )


def tooth_pain_response(language: Language | str) -> PolicyResponse:
    language = Language(language)
    return PolicyResponse(
        path=PolicyPath.TOOTH_PAIN,
        language=language,
        text=wording.line("tooth_pain", language),
        next_action=NextAction.OFFER_CALLBACK,
        topic="tooth_pain",
        callback_category=CallbackCategory.APPOINTMENT,
        matched_rules=(TOOTH_PAIN.id,),
    )


def panel_response(language: Language | str, text: str = "") -> UnknownInformation:
    language = Language(language)
    lead = (wording.line("panel_cghs", language) + " "
            if any(re.search(p, matching_text(text), re.IGNORECASE) for p in _CGHS) else "")
    return UnknownInformation(
        path=PolicyPath.PANEL,
        language=language,
        text=lead + wording.line("panel", language),
        topic="panel",
        callback_category=CallbackCategory.PANEL,
        matched_rules=(PANEL.id,),
    )


_APPOINTMENT_TOPICS = ("appointment_request", "appointment_availability", "doctor_schedule", "reschedule_request",
                       "cancellation_request", "booking_status")
_INTENT_TOPICS = {rule.id for rule in INTENTS}
_OTHER_TOPICS = ("complaint",)


def unknown_information(topic: str, language: Language | str) -> UnknownInformation:
    """No answer: say so without guessing, and offer a callback."""
    language = Language(language)
    entry = knowledge_base.BY_ID.get(topic)
    if entry is not None and entry.lead:
        lead = entry.lead[language]
    else:
        lead = wording.UNKNOWN_LEADS.get(topic, wording.UNKNOWN_LEADS["default"])[language]
    if topic in ("appointment_request", "appointment_availability"):
        offer = wording.APPOINTMENT_OFFER[language]
    elif topic in _INTENT_TOPICS:
        offer = wording.line("offer_short", language)
    else:
        offer = wording.line("unknown_offer", language)
    return UnknownInformation(
        language=language,
        text=f"{lead} {offer}",
        topic=topic,
        callback_category=(CallbackCategory.APPOINTMENT if topic in _APPOINTMENT_TOPICS
                           else CallbackCategory.OTHER if topic in _OTHER_TOPICS else CallbackCategory.ENQUIRY),
        matched_rules=(topic,),
    )


def approved_answer(topic: str, language: Language | str, services: tuple[str, ...] = ()) -> PolicyResponse:
    language = Language(language)
    entry = knowledge_base.BY_ID.get(topic)
    if topic == "services":
        names = [wording.SERVICE_NAMES[s][wording.LANGUAGES.index(language)] for s in services]
        text = wording.line("services", language, services=wording.join(names, language))
    elif entry is not None:
        text = entry.say(language)
    else:
        text = wording.line(topic, language, **wording.facts(language))
    offer = entry.offer_callback if entry is not None else None
    return PolicyResponse(
        path=PolicyPath.ANSWER,
        language=language,
        text=text,
        next_action=NextAction.OFFER_CALLBACK if offer else NextAction.CONTINUE,
        callback_category=CallbackCategory(offer) if offer else None,
        topic=topic,
        matched_rules=services or (topic,),
    )


# How the demo labels where a reply came from.
SOURCE_APPROVED = "approved_knowledge"
SOURCE_CALLBACK = "callback_required"
SOURCE_SAFETY = "safety_fallback"
SOURCE_EMERGENCY = "emergency_escalation"


def response_source(path: PolicyPath | str) -> str:
    path = PolicyPath(path)
    if path == PolicyPath.EMERGENCY:
        return SOURCE_EMERGENCY
    if path in (PolicyPath.CLINICAL, PolicyPath.TOOTH_PAIN):
        return SOURCE_SAFETY
    if path == PolicyPath.ANSWER:
        return SOURCE_APPROVED
    return SOURCE_CALLBACK


def human_request_response(context: RuntimeContext, language: Language | str) -> PolicyResponse:
    """Transfer only when reception can take it; otherwise go straight to callback capture."""
    language = Language(language)
    if context.transfer_available:
        return PolicyResponse(
            path=PolicyPath.HUMAN_REQUEST, language=language, text=wording.line("transfer", language),
            next_action=NextAction.TRANSFER, topic="human_request",
            callback_category=CallbackCategory.HUMAN_REQUEST,
        )
    return PolicyResponse(
        path=PolicyPath.HUMAN_REQUEST, language=language,
        text=wording.line("transfer_unavailable", language, promise=callback_promise(context, language)),
        next_action=NextAction.CAPTURE_CALLBACK, topic="human_request",
        callback_category=CallbackCategory.HUMAN_REQUEST,
    )


def transfer_failed_response(context: RuntimeContext, language: Language | str, urgent: bool = False) -> PolicyResponse:
    language = Language(language)
    return PolicyResponse(
        path=PolicyPath.EMERGENCY if urgent else PolicyPath.HUMAN_REQUEST,
        language=language,
        text=wording.line("transfer_failed", language, promise=callback_promise(context, language)),
        next_action=NextAction.CAPTURE_CALLBACK,
        topic="transfer_failed",
        callback_category=CallbackCategory.URGENT if urgent else CallbackCategory.HUMAN_REQUEST,
        urgent=urgent,
    )


def respond(text: str, context: RuntimeContext, language: Language | str = Language.EN,
            knowledge: ApprovedKnowledge = APPROVED) -> PolicyResponse:
    """The policy decision and spoken reply for one caller utterance."""
    found = classify(text, knowledge)
    if found.path == PolicyPath.EMERGENCY:
        return emergency_response(context, language, found.matched_rules)
    if found.path == PolicyPath.CLINICAL:
        return clinical_response(language)
    if found.path == PolicyPath.PANEL:
        return panel_response(language, text)
    if found.path == PolicyPath.HUMAN_REQUEST:
        return human_request_response(context, language)
    if found.path == PolicyPath.TOOTH_PAIN:
        return tooth_pain_response(language)
    if found.path == PolicyPath.CALLBACK_REQUEST:
        language = Language(language)
        return PolicyResponse(
            path=PolicyPath.CALLBACK_REQUEST, language=language, text=wording.line("callback_request", language),
            next_action=NextAction.CAPTURE_CALLBACK, topic="callback_request",
            callback_category=CallbackCategory.OTHER, matched_rules=found.matched_rules,
        )
    if found.path == PolicyPath.ANSWER:
        return approved_answer(found.topic, language, found.matched_rules if found.topic == "services" else ())
    if found.topic == "panel":
        return panel_response(language, text)
    return unknown_information(found.topic, language)


# --- Callback capture --------------------------------------------------------------------------

def confirm_details_line(name: str, phone: str, language: Language | str, reason: str | None = None,
                         preferences: str | None = None) -> str:
    """The read-back the caller must say yes to before a callback is created."""
    language = Language(language)
    if reason:
        intro = (wording.line("confirm_intro_caller_number", language, name=name) if phone == CALLER_NUMBER
                 else wording.line("confirm_intro_number", language, name=name, phone=spoken_digits(phone)))
        parts = [intro, wording.line("confirm_reason", language, reason=reason.rstrip(".।? "))]
        if preferences:
            parts.append(preferences)
        return " ".join(parts + [wording.line("confirm_question", language)])
    if phone == CALLER_NUMBER:
        return wording.line("confirm_details_caller_number", language, name=name)
    return wording.line("confirm_details", language, name=name, phone=spoken_digits(phone))


class CallbackRefused(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EndCallDecision:
    allowed: bool
    reason: str


@dataclass
class CallSession:
    """Per-call policy state. Records callback requests; it does not save or place anything."""

    context: RuntimeContext
    callbacks: list[CallbackDetails] = field(default_factory=list)
    human_requested: bool = False
    transferred: bool = False
    callback_offered: bool = False

    def respond(self, text: str, language: Language | str = Language.EN) -> PolicyResponse:
        return self.note(respond(text, self.context, language))

    def note(self, response: PolicyResponse) -> PolicyResponse:
        if response.path == PolicyPath.HUMAN_REQUEST:
            self.human_requested = True
        if response.next_action in (NextAction.OFFER_CALLBACK, NextAction.CAPTURE_CALLBACK):
            self.callback_offered = True
        return response

    def transfer_result(self, succeeded: bool, language: Language | str, urgent: bool = False) -> PolicyResponse | None:
        """After transfer_to_reception: None when connected, otherwise straight into callback capture."""
        if not self.context.transfer_available:
            raise CallbackRefused("transfer_unavailable", "Transfer is not available on this call.")
        if succeeded:
            self.transferred = True
            return None
        return self.note(transfer_failed_response(self.context, language, urgent))

    def create_callback(self, args: CreateCallbackArgs, *, confirmed: bool) -> CallbackDetails:
        """Validate a create_callback request against the per-call rules."""
        if not confirmed:
            raise CallbackRefused("not_confirmed", "The caller has not confirmed their name and number.")
        phone = args.phone
        if phone == CALLER_NUMBER:
            if not self.context.caller_number:
                raise CallbackRefused("no_caller_number", "There is no caller number on this call; ask for one.")
            phone = self.context.caller_number
        details = CallbackDetails(**{**args.model_dump(), "phone": phone})
        if self.callbacks:
            separate_urgent = details.urgent and not any(c.urgent for c in self.callbacks) and len(self.callbacks) == 1
            if not separate_urgent:
                raise CallbackRefused("duplicate", "A callback has already been requested on this call.")
        self.callbacks.append(details)
        self.callback_offered = True
        return details

    def callback_created_line(self, details: CallbackDetails) -> str:
        return wording.line("callback_created", details.language, name=details.name,
                            promise=callback_promise(self.context, details.language))

    def can_end_call(self) -> EndCallDecision:
        if self.human_requested and not (self.transferred or self.callback_offered):
            return EndCallDecision(False, "The caller asked for a person: transfer them or offer a callback first.")
        return EndCallDecision(True, "ok")
