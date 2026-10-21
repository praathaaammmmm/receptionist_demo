"""Structured knowledge base for the voice agent, in the categories the clinic owner reviews.

Every answer the agent can speak is an entry here (or a Phase 1 line in wording.py that an entry
points to). Each entry records its approval status:

  approved_brief            from the owner's approved brief (Phase 1 knowledge.py)
  system_fact               a fact about this assistant itself (languages, how callbacks work)
  owner_approval_required   drafted wording for this demo; the owner must approve it before production
  not_provided              the owner has not supplied this: the agent says it doesn't know and offers a callback

Nothing here is read by the dashboard, and the demo doctors and services in the database are untouched.
A language model (llm.py), if one is configured, only picks entry ids; it never writes the words.
"""
import re
from dataclasses import dataclass, field

from . import wording
from .knowledge import APPROVED

APPROVED_BRIEF = "approved_brief"
SYSTEM_FACT = "system_fact"
NEEDS_APPROVAL = "owner_approval_required"
NOT_PROVIDED = "not_provided"

CATEGORIES = (
    "clinic_profile", "location_and_directions", "hours_and_closures", "contact_details", "doctors", "services",
    "visit_logistics", "appointment_policies", "fees_and_payments", "panels_and_insurance", "safe_general_answers",
    "callback_required_topics", "clinical_refusal_topics", "urgent_symptom_topics", "language_translations",
)

_EXPLAIN = (r"\bwhat(?:'s| is| are| does| do)\b", r"\bexplain", r"\bhow (?:is|are|does|do you|long)\b", r"\btell me about\b",
            r"\bmean(?:s|ing)?\b", r"\bprocess\b", r"\bprocedure\b", r"\bkya (?:hota|hoti|hai|hain)\b",
            r"\bkaise (?:hota|hoti|karte)\b", r"\bsamjha", r"\bbatao\b", r"\bbataiye\b",
            "क्या होता", "क्या है", "कैसे होता", "समझा", "बताइए", "बताओ")


@dataclass(frozen=True)
class Entry:
    id: str
    category: str
    status: str
    summary: str  # one line, English: what the entry answers (for reviewers and the language model)
    text: dict | None = None  # {"en", "hi", "hinglish"}; None means the line comes from `line` or is not provided
    line: str | None = None  # a Phase 1 wording.LINES key, filled with the spoken facts
    groups: tuple[tuple[str, ...], ...] = ()  # rule-based matching: every group needs one hit
    priority: str = "high"  # "high": checked before fees and general facts; "low": after them
    offer_callback: str | None = None  # callback category to offer after answering
    lead: dict | None = None  # not_provided: what the agent says it doesn't know

    def matches(self, text: str) -> bool:
        return bool(self.groups) and all(any(re.search(p, text, re.IGNORECASE) for p in g) for g in self.groups)

    def say(self, language: str) -> str:
        if self.line:
            return wording.line(self.line, language, **wording.facts(language))
        return self.text[language]


def _t(en: str, hi: str, hinglish: str) -> dict:
    return {"en": en, "hi": hi, "hinglish": hinglish}


def _procedure(id: str, name: str, terms: tuple[str, ...], text: dict) -> Entry:
    return Entry(id, "services", NEEDS_APPROVAL, f"General, high-level explanation of {name} (never a recommendation)",
                 text=text, groups=(_EXPLAIN, terms), priority="low")


_SERVICE_TERMS = {s.id: s.patterns for s in APPROVED.services}

ENTRIES = (
    # clinic_profile
    Entry("clinic_about", "clinic_profile", APPROVED_BRIEF, "What the clinic is and who its doctors are",
          text=_t("Smriti Raj Dentistry is a dental clinic in Sector 13, Dwarka, New Delhi. Our doctors are Doctor Raj "
                  "Tiwary and Doctor Smriti Raj.",
                  "स्मृति राज डेंटिस्ट्री सेक्टर 13, द्वारका, नई दिल्ली में एक डेंटल क्लिनिक है। हमारे डॉक्टर हैं डॉक्टर राज "
                  "तिवारी और डॉक्टर स्मृति राज।",
                  "Smriti Raj Dentistry Sector 13, Dwarka, New Delhi mein ek dental clinic hai. Hamare doctors hain "
                  "Doctor Raj Tiwary aur Doctor Smriti Raj."),
          groups=((r"\babout (?:the |your )?clinic\b", r"\btell me about (?:the |your )?clinic", r"\bwhat is smriti raj",
                   r"\bclinic ke baare mein\b", "क्लिनिक के बारे में"),), priority="low"),
    # location_and_directions
    Entry("address", "location_and_directions", APPROVED_BRIEF, "Clinic address and landmark", line="address"),
    Entry("directions", "location_and_directions", APPROVED_BRIEF,
          "How to find the clinic: area and landmark only; detailed directions need a callback",
          text=_t("We're in Sector 13, Dwarka, near Pragati Public School, on the basement floor of Plot Number 54. I "
                  "don't have step-by-step directions, but our team can call you to guide you. Would you like that?",
                  "हम सेक्टर 13, द्वारका में प्रगति पब्लिक स्कूल के पास हैं, प्लॉट नंबर 54 के बेसमेंट फ़्लोर पर। मेरे पास रास्ते "
                  "की पूरी जानकारी नहीं है, लेकिन हमारी टीम आपको कॉल करके रास्ता बता सकती है। क्या आप ऐसा चाहेंगे?",
                  "Hum Sector 13, Dwarka mein Pragati Public School ke paas hain, Plot Number 54 ke basement floor par. "
                  "Mere paas poore directions nahin hain, lekin hamari team aapko call karke raasta bata sakti hai. Kya "
                  "aap aisa chahenge?"),
          groups=((r"\bdirections?\b", r"\bhow (?:do|can|to) (?:i |we )?(?:get|reach|come|find)\b", r"\broute\b",
                   r"\braasta\b", r"\bkaise (?:aaun|aayein|aau|pahunch)", "रास्ता", "कैसे पहुँच", "कैसे पहुंच"),),
          offer_callback="enquiry"),
    Entry("parking", "location_and_directions", NOT_PROVIDED, "Parking at or near the clinic",
          lead=_t("I don't have confirmed information about parking.",
                  "मेरे पास पार्किंग के बारे में पक्की जानकारी नहीं है।",
                  "Mere paas parking ke baare mein confirmed jaankari nahin hai."),
          groups=((r"\bpark(?:ing)?\b", "पार्किंग"),)),
    Entry("accessibility", "location_and_directions", NOT_PROVIDED, "Wheelchair, lift or step-free access",
          lead=_t("I don't have confirmed information about wheelchair or step-free access.",
                  "मेरे पास व्हीलचेयर या बिना सीढ़ी वाले रास्ते के बारे में पक्की जानकारी नहीं है।",
                  "Mere paas wheelchair ya bina seedhi wale raaste ke baare mein confirmed jaankari nahin hai."),
          groups=((r"wheel ?chair", r"accessib", r"\bdisab", r"\blift\b", r"\belevator\b", r"\bstairs?\b", r"\bramp\b",
                   r"\bseedhi", "सीढ़ी", "व्हीलचेयर", "लिफ्ट"),)),
    # hours_and_closures
    Entry("hours", "hours_and_closures", APPROVED_BRIEF,
          "Opening hours: which days and what times the clinic opens and closes; closed on Sunday", line="hours"),
    Entry("holidays", "hours_and_closures", NOT_PROVIDED, "Public holiday and festival closures",
          lead=_t("I don't have the clinic's holiday schedule.",
                  "मेरे पास क्लिनिक की छुट्टियों की जानकारी नहीं है।",
                  "Mere paas clinic ki chhuttiyon ki jaankari nahin hai."),
          groups=((r"\bholidays?\b", r"\bdiwali\b", r"\bholi\b", r"\bfestival", r"\bchhutti", "छुट्टी", "त्योहार", "दिवाली"),)),
    # contact_details
    Entry("contact", "contact_details", APPROVED_BRIEF, "Reception and alternate phone numbers and email", line="contact"),
    Entry("whatsapp", "contact_details", NOT_PROVIDED, "A WhatsApp number for the clinic",
          lead=_t("I don't have a confirmed WhatsApp number for the clinic.",
                  "मेरे पास क्लिनिक का पक्का व्हाट्सऐप नंबर नहीं है।",
                  "Mere paas clinic ka confirmed WhatsApp number nahin hai."),
          groups=((r"whats ?app", "व्हाट्सऐप", "व्हाट्सएप"),)),
    # doctors
    Entry("doctors", "doctors", APPROVED_BRIEF, "Doctor names and specialties", line="doctors"),
    Entry("doctor_specialties", "doctors", NEEDS_APPROVAL,
          "Which kind of work each doctor's specialty generally covers (not which doctor a symptom needs)",
          text=_t("Doctor Raj Tiwary's work as a periodontist and implantologist generally covers gum treatment and "
                  "dental implants. Doctor Smriti Raj's work focuses on children's dentistry and orthodontics, such as "
                  "braces and aligners. Our team will suggest the right doctor once they know what you need.",
                  "डॉक्टर राज तिवारी का काम, पेरियोडॉन्टिस्ट और इम्प्लांटोलॉजिस्ट के रूप में, आम तौर पर मसूड़ों के इलाज और "
                  "डेंटल इम्प्लांट से जुड़ा है। डॉक्टर स्मृति राज का काम बच्चों की दंत चिकित्सा और ऑर्थोडॉन्टिक्स, जैसे "
                  "ब्रेसेस और अलाइनर, पर केंद्रित है। आपको किस डॉक्टर से मिलना है, यह हमारी टीम आपकी ज़रूरत जानकर बताएगी।",
                  "Doctor Raj Tiwary ka kaam, periodontist aur implantologist ke roop mein, aam taur par gum treatment "
                  "aur dental implants se juda hai. Doctor Smriti Raj ka kaam children's dentistry aur orthodontics, "
                  "jaise braces aur aligners, par focused hai. Aapko kis doctor se milna hai, yeh hamari team aapki "
                  "zaroorat jaankar batayegi."),
          groups=((r"\bwhich doctor\b", r"\b(?:doctor|dentist) (?:for|who (?:does|handles|treats))\b", r"\bkis doctor\b",
                   r"\bkaun(?:sa| se)? doctor\b", "किस डॉक्टर", "कौन से डॉक्टर", "कौन सा डॉक्टर"),)),
    # services
    Entry("services_list", "services", APPROVED_BRIEF, "The full list of services", line=None,
          text={lang: wording.line("services_all", lang, services=wording.join(
              [names[i] for names in wording.SERVICE_NAMES.values()], lang))
                for i, lang in enumerate(wording.LANGUAGES)},
          groups=((r"\bwhat (?:services|treatments)\b", r"\bwhich (?:services|treatments)\b", r"\b(?:list|all) (?:of )?(?:your )?(?:services|treatments)\b",
                   r"\bservices do you\b", r"\bkya kya\b", r"\bkaun ?kaun\b", "क्या-क्या", "क्या क्या", "कौन-कौन", "सेवाएँ"),),
          priority="low"),
    Entry("consultation_vs_procedure", "services", NEEDS_APPROVAL,
          "What a consultation is, compared with having a procedure",
          text=_t("The consultation is an assessment: the doctor examines you, explains the options and plans any "
                  "treatment. Treatment itself is usually done at a separate visit, and its cost is confirmed after "
                  "the assessment.",
                  "कंसल्टेशन एक जाँच है: डॉक्टर आपकी जाँच करके विकल्प समझाते हैं और ज़रूरत हो तो इलाज की योजना बनाते हैं। "
                  "इलाज आम तौर पर अलग विज़िट में होता है, और उसका खर्च जाँच के बाद बताया जाता है।",
                  "Consultation ek assessment hai: doctor aapko check karke options samjhate hain aur zaroorat ho toh "
                  "treatment plan karte hain. Treatment aam taur par alag visit mein hota hai, aur uska kharcha "
                  "assessment ke baad bataya jaata hai."),
          groups=((r"\bdifference\b", r"\bfa?rak\b", r"\bvs\b", r"\bversus\b", r"what happens (?:in|at|during)",
                   r"\bconsultation (?:mein|me) kya\b", "फ़र्क", "फर्क", "में क्या होता"),
                  (r"consult", "कंसल्टेशन")), priority="low"),
    Entry("consultation_first", "services", NEEDS_APPROVAL, "Whether treatment needs a consultation first",
          text=_t("Yes, treatment usually starts with a consultation, so the doctor can assess you and explain the "
                  "options first.",
                  "जी हाँ, इलाज आम तौर पर कंसल्टेशन से शुरू होता है, ताकि डॉक्टर पहले जाँच करके विकल्प समझा सकें।",
                  "Ji haan, treatment aam taur par consultation se shuru hota hai, taaki doctor pehle check karke "
                  "options samjha sakein."),
          groups=((r"\bneed\b", r"\bhave to\b", r"\bmust\b", r"\bfirst\b", r"\bpehle\b", r"\bzaroori\b", "ज़रूरी", "जरूरी", "पहले"),
                  (r"consult", "कंसल्टेशन")), priority="low"),
    _procedure("procedure_root_canal", "root canal treatment", _SERVICE_TERMS["root_canal"], _t(
        "A root canal treatment cleans the inside of a tooth and seals it, so the tooth can be kept. Whether it's "
        "needed is decided by the doctor after an assessment.",
        "रूट कैनाल ट्रीटमेंट में दांत के अंदर के हिस्से को साफ़ करके सील किया जाता है, ताकि दांत को बचाया जा सके। इसकी "
        "ज़रूरत है या नहीं, यह डॉक्टर जाँच के बाद तय करते हैं।",
        "Root canal treatment mein daant ke andar ke hisse ko saaf karke seal kiya jaata hai, taaki daant bachaya ja "
        "sake. Iski zaroorat hai ya nahin, yeh doctor assessment ke baad decide karte hain.")),
    _procedure("procedure_implant", "dental implants", _SERVICE_TERMS["implants"], _t(
        "A dental implant is a small post placed in the jaw to support a replacement tooth. The doctor assesses "
        "whether an implant is suitable before planning anything.",
        "डेंटल इम्प्लांट जबड़े में लगाया जाने वाला एक छोटा पोस्ट होता है, जिस पर नया दांत लगाया जाता है। इम्प्लांट सही "
        "रहेगा या नहीं, यह डॉक्टर जाँच के बाद ही तय करते हैं।",
        "Dental implant jabde mein lagaya jaane wala ek chhota post hota hai, jis par naya daant lagaya jaata hai. "
        "Implant suitable hai ya nahin, yeh doctor assessment ke baad hi decide karte hain.")),
    _procedure("procedure_cleaning", "teeth cleaning and scaling", _SERVICE_TERMS["cleaning"], _t(
        "Teeth cleaning and scaling remove hard deposits and stains that brushing can't, usually in one visit. The "
        "doctor checks your teeth first.",
        "दांतों की सफ़ाई और स्केलिंग में वह जमा हुआ मैल और दाग हटाए जाते हैं जो ब्रश से नहीं हटते, आम तौर पर एक ही "
        "विज़िट में। डॉक्टर पहले आपके दांतों की जाँच करते हैं।",
        "Teeth cleaning aur scaling mein woh jama hua mail aur daag hataye jaate hain jo brush se nahin hatte, aam "
        "taur par ek hi visit mein. Doctor pehle aapke daanton ki jaanch karte hain.")),
    _procedure("procedure_braces", "braces and clear aligners", _SERVICE_TERMS["braces_aligners"], _t(
        "Braces and clear aligners gently move teeth into a better position over several months. The doctor "
        "assesses which option, if any, suits you.",
        "ब्रेसेस और क्लियर अलाइनर कई महीनों में धीरे-धीरे दांतों को सही जगह पर लाते हैं। आपके लिए कौन सा विकल्प सही है, "
        "यह डॉक्टर जाँच के बाद बताते हैं।",
        "Braces aur clear aligners kai mahinon mein dheere-dheere daanton ko sahi jagah par laate hain. Aapke liye "
        "kaunsa option sahi hai, yeh doctor assessment ke baad batate hain.")),
    _procedure("procedure_extraction", "tooth extraction", _SERVICE_TERMS["extraction"], _t(
        "A tooth extraction means removing a tooth that can't be kept. The doctor decides after an assessment "
        "whether it's needed.",
        "दांत निकालने का मतलब है ऐसा दांत निकालना जिसे बचाया नहीं जा सकता। इसकी ज़रूरत है या नहीं, यह डॉक्टर जाँच के बाद "
        "तय करते हैं।",
        "Tooth extraction ka matlab hai aisa daant nikaalna jise bachaya nahin ja sakta. Iski zaroorat hai ya nahin, "
        "yeh doctor assessment ke baad decide karte hain.")),
    _procedure("procedure_crowns", "crowns and bridges", _SERVICE_TERMS["crowns_bridges"], _t(
        "A crown is a cap that covers a damaged tooth, and a bridge replaces a missing tooth by attaching to the "
        "teeth beside it. The doctor advises which, if any, is suitable after an assessment.",
        "क्राउन एक कैप है जो खराब दांत को ढकती है, और ब्रिज आस-पास के दांतों से जुड़कर गायब दांत की जगह भरता है। कौन सा "
        "सही है, यह डॉक्टर जाँच के बाद बताते हैं।",
        "Crown ek cap hai jo kharab daant ko dhakti hai, aur bridge aas-paas ke daanton se judkar missing daant ki "
        "jagah bharta hai. Kaunsa sahi hai, yeh doctor assessment ke baad batate hain.")),
    _procedure("procedure_children", "children's dentistry", _SERVICE_TERMS["children"], _t(
        "Children's dentistry covers check-ups and treatment for children, with care suited to their age. Doctor "
        "Smriti Raj specialises in pediatric dentistry.",
        "बच्चों की दंत चिकित्सा में बच्चों की जाँच और इलाज उनकी उम्र के हिसाब से किया जाता है। डॉक्टर स्मृति राज बच्चों "
        "की दंत चिकित्सा में विशेषज्ञ हैं।",
        "Children's dentistry mein bachchon ki jaanch aur ilaaj unki umar ke hisaab se kiya jaata hai. Doctor Smriti "
        "Raj pediatric dentistry mein specialist hain.")),
    _procedure("procedure_gum", "gum treatment", _SERVICE_TERMS["gum"], _t(
        "Gum treatment looks after the gums and the bone that support the teeth. Doctor Raj Tiwary is a "
        "periodontist, a gum specialist, and assesses what's needed.",
        "मसूड़ों के इलाज में दांतों को सहारा देने वाले मसूड़ों और हड्डी का ध्यान रखा जाता है। डॉक्टर राज तिवारी "
        "पेरियोडॉन्टिस्ट, यानी मसूड़ों के विशेषज्ञ हैं, और जाँच के बाद बताते हैं कि क्या ज़रूरी है।",
        "Gum treatment mein daanton ko sahara dene wale masoodon aur haddi ka dhyaan rakha jaata hai. Doctor Raj "
        "Tiwary periodontist, yaani masoodon ke specialist hain, aur assessment ke baad batate hain ki kya zaroori "
        "hai.")),
    _procedure("procedure_xray", "digital dental X-rays", _SERVICE_TERMS["xray"], _t(
        "Digital dental X-rays are pictures that help the doctor see inside the teeth and jaw. The doctor decides "
        "when an X-ray is needed and explains the results in person.",
        "डिजिटल डेंटल एक्स-रे ऐसी तस्वीरें हैं जिनसे डॉक्टर दांतों और जबड़े के अंदर देख पाते हैं। एक्स-रे कब ज़रूरी है, "
        "यह डॉक्टर तय करते हैं और नतीजे खुद समझाते हैं।",
        "Digital dental X-ray aisi photos hain jinse doctor daanton aur jabde ke andar dekh paate hain. X-ray kab "
        "zaroori hai, yeh doctor decide karte hain aur results khud samjhate hain.")),
    # visit_logistics
    Entry("languages", "visit_logistics", SYSTEM_FACT, "Which languages this assistant can talk in",
          text=_t("I can talk with you in English, Hindi or Hinglish. Just speak the way you're comfortable.",
                  "मैं आपसे अंग्रेज़ी, हिंदी या हिंग्लिश में बात कर सकती हूँ। आप जैसे सहज हों, वैसे बोलिए।",
                  "Main aapse English, Hindi ya Hinglish mein baat kar sakti hoon. Aap jaise comfortable hon, waise "
                  "boliye."),
          groups=((r"\blanguages?\b", r"\bbhasha\b", r"\b(?:speak|talk|baat) (?:in )?(?:hindi|english)\b",
                   r"\b(?:hindi|english) (?:me|mein) (?:baat|bol)", "भाषा", "हिंदी में"),)),
    Entry("first_visit", "visit_logistics", NEEDS_APPROVAL, "What happens on a first visit",
          text=_t("On a first visit, reception takes your details, then the doctor examines you and explains the "
                  "options. Any treatment is planned after that.",
                  "पहली बार आने पर रिसेप्शन आपकी जानकारी लेता है, फिर डॉक्टर जाँच करके विकल्प समझाते हैं। कोई भी इलाज "
                  "उसके बाद तय होता है।",
                  "Pehli visit par reception aapki details leta hai, phir doctor check karke options samjhate hain. Koi "
                  "bhi treatment uske baad plan hota hai."),
          groups=((r"\bfirst (?:visit|time|appointment)\b", r"\bnew patient\b", r"\bpehli (?:baar|visit)\b",
                   "पहली बार", "पहली विज़िट"),)),
    Entry("what_to_bring", "visit_logistics", NEEDS_APPROVAL, "What to bring to a consultation",
          text=_t("Please bring any previous dental reports or X-rays you have, and a list of any medicines you take.",
                  "अगर आपके पास पुरानी डेंटल रिपोर्ट या एक्स-रे हों तो साथ लाइए, और आप जो दवाइयाँ लेते हैं उनकी सूची भी।",
                  "Agar aapke paas purani dental reports ya X-ray hon toh saath laaiye, aur aap jo medicines lete hain "
                  "unki list bhi."),
          groups=((r"\bwhat (?:should|do|must) i (?:bring|carry)\b", r"\bbring (?:with|along)\b", r"\bkya (?:laana|laaun|lekar|le kar)\b",
                   "क्या लाना", "साथ क्या", "क्या लेकर"),)),
    Entry("arrival_checkin", "visit_logistics", NEEDS_APPROVAL, "Arriving and checking in",
          text=_t("Please arrive about ten minutes early and give your name at reception, who will check you in.",
                  "कृपया लगभग दस मिनट पहले पहुँचें और रिसेप्शन पर अपना नाम बताएँ, वहाँ आपका चेक-इन होगा।",
                  "Please lagbhag das minute pehle pahunchiye aur reception par apna naam bataiye, wahan aapka check-in "
                  "hoga."),
          groups=((r"\bcheck[- ]?in\b", r"\barriv", r"\bhow early\b", r"\bkitna pehle\b", "कितना पहले", "चेक-इन", "चेक इन"),)),
    Entry("walk_in", "visit_logistics", NOT_PROVIDED, "Whether walk-in visits are accepted",
          lead=_t("I can't confirm whether walk-in visits are possible.",
                  "मैं पुष्टि नहीं कर सकती कि बिना अपॉइंटमेंट के आना संभव है या नहीं।",
                  "Main confirm nahin kar sakti ki bina appointment ke aana possible hai ya nahin."),
          groups=((r"\bwalk[- ]?ins?\b", r"\bwithout (?:an )?appointment\b", r"\bbina appointment\b", "बिना अपॉइंटमेंट"),)),
    # appointment_policies
    Entry("how_to_book", "appointment_policies", SYSTEM_FACT, "How to request an appointment through this assistant",
          text=_t("To book, I'll take your name and number, and our team will call you to fix a time. Appointments "
                  "are confirmed only by our team. Shall I take your details?",
                  "बुकिंग के लिए मैं आपका नाम और नंबर लूँगी, और हमारी टीम आपको समय तय करने के लिए कॉल करेगी। अपॉइंटमेंट "
                  "सिर्फ़ हमारी टीम ही कन्फ़र्म करती है। क्या मैं आपकी जानकारी ले लूँ?",
                  "Booking ke liye main aapka naam aur number lungi, aur hamari team aapko time fix karne ke liye call "
                  "karegi. Appointment sirf hamari team hi confirm karti hai. Kya main aapki details le loon?"),
          groups=((r"\bhow (?:do|can|to) (?:i )?(?:book|make|get|request|schedule|fix)\b", r"\bappointment kaise\b",
                   r"\bkaise (?:book|appointment)", "अपॉइंटमेंट कैसे", "कैसे बुक"),),
          offer_callback="appointment"),
    Entry("cancellation_policy", "appointment_policies", NOT_PROVIDED, "Cancellation, lateness or no-show policy",
          lead=_t("I don't have the clinic's cancellation or no-show policy.",
                  "मेरे पास क्लिनिक की कैंसलेशन या न आने से जुड़ी पॉलिसी की जानकारी नहीं है।",
                  "Mere paas clinic ki cancellation ya no-show policy ki jaankari nahin hai."),
          groups=((r"cancel", r"no[- ]?show", r"\blate\b", "कैंसल"), (r"\bpolicy\b", r"\bfee\b", r"\bcharge", r"\brules?\b", "पॉलिसी"))),
    # fees_and_payments
    Entry("consultation_fee", "fees_and_payments", APPROVED_BRIEF, "Initial consultation fee (500 rupees); never treatment prices",
          line="consultation_fee"),
    Entry("payment", "fees_and_payments", APPROVED_BRIEF, "Payment methods: cash, UPI, cards", line="payment"),
    # safe_general_answers
    Entry("doctor_assesses", "safe_general_answers", SYSTEM_FACT,
          "Safe general reply for a non-clinical dental question not covered elsewhere: the doctor assesses it",
          text=_t("The doctor will assess this in a consultation, and a team member can explain the next steps. "
                  "Would you like a callback?",
                  "डॉक्टर कंसल्टेशन में इसकी जाँच करेंगे, और हमारी टीम का कोई सदस्य आगे के कदम बता सकता है। क्या आप "
                  "कॉलबैक चाहेंगे?",
                  "Doctor consultation mein iska assessment karenge, aur hamari team ka koi member aage ke steps bata "
                  "sakta hai. Kya aap callback chahenge?"),
          offer_callback="enquiry"),
)

BY_ID = {e.id: e for e in ENTRIES}
SERVICE_ANSWER_IDS = {f"service:{s.id}": s.id for s in APPROVED.services}

# Topics that always become a callback (the agent never answers them itself).
CALLBACK_REQUIRED_TOPICS = (
    "doctor_schedule", "appointment_availability", "appointment_request", "treatment_cost", "insurance", "panel",
    "treatment_suitability", "reschedule_request", "cancellation_request", "booking_status", "missed_call",
    "website_enquiry", "complaint", "patient_records", *(e.id for e in ENTRIES if e.status == NOT_PROVIDED),
)
# Questions that get the clinical refusal and a callback: no diagnosis, advice or recommendation.
CLINICAL_REFUSAL_TOPICS = (
    "symptoms", "pain", "swelling", "medicines and dosage", "home remedies", "whether something is serious",
    "treatment suitability", "procedure recommendations for a symptom", "recovery and aftercare instructions",
    "X-ray, report or test interpretation",
)
# The deterministic urgent list lives in policy.URGENT_SYMPTOMS; it is never decided by a model.
URGENT_SYMPTOM_TOPICS = "policy.URGENT_SYMPTOMS"
# Every entry carries English, Hindi (Devanagari) and Hinglish (Roman); Phase 1 lines live in wording.LINES.
LANGUAGE_TRANSLATIONS = ("en", "hi", "hinglish")


def match(text: str, priority: str) -> Entry | None:
    for entry in ENTRIES:
        if entry.priority == priority and entry.matches(text):
            return entry
    return None


def catalogue() -> list[tuple[str, str]]:
    """(answer id, what it answers) for every answer a language model may choose."""
    items = [(e.id, e.summary) for e in ENTRIES if e.status != NOT_PROVIDED]
    items += [(key, f"Yes, the clinic offers: {s.name}") for key, s in
              ((k, next(x for x in APPROVED.services if x.id == v)) for k, v in SERVICE_ANSWER_IDS.items())]
    return items


def needing_owner_review() -> list[Entry]:
    return [e for e in ENTRIES if e.status in (NEEDS_APPROVAL, NOT_PROVIDED)]
