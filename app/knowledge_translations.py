"""Approved wording for the call demo in English, Hindi (हिंदी) and Hinglish.

Part of the approved clinic knowledge (see app/knowledge.py). The assistant chooses
WHAT to say with the same rules in every language; this file only decides HOW each
approved message is worded. Booking, callback, waitlist, opening-hours and safety
rules never depend on the language.

Hinglish has two reviewed versions of every message: "hinglish" is the Roman Hindi shown in the
transcript, and "hinglish_speech" is the same meaning in Devanagari, which is what the Hindi voice
reads aloud (a Hindi voice cannot read Roman Hindi well). Nothing is transliterated at run time.

Rules for editing:
- Every message has all versions (en, hi, hinglish, hinglish_speech), with the same {placeholders}.
- Placeholders carry data (names, dates, times, numbers, references, doctor and
  service names). They are inserted unchanged, apart from Hindi weekday and month
  names, so data is never re-worded.
- No message may contain dental or medical advice.
- The Hindi and Hinglish text is a demo draft. A fluent speaker at the clinic should
  review it before any public use.
"""
from . import knowledge

LANGUAGE_CODES = ("en", "hi", "hinglish")
DEFAULT_LANGUAGE = "en"

LANGUAGES = {
    "en": {"label": "English", "html_lang": "en", "voice_label": "Local English voice"},
    "hi": {"label": "हिंदी", "html_lang": "hi", "voice_label": "Local Hindi voice"},
    "hinglish": {"label": "Hinglish", "html_lang": "hi-Latn", "voice_label": "Hinglish conversation · Hindi local voice"},
}

# Shown when the voice pack a language needs is not installed. The call carries on as text.
VOICE_MISSING_MESSAGE = "This local voice pack is not installed. The conversation remains available as text."

_SAFETY = {
    "en": knowledge.SAFETY_NOTE,
    "hi": "मैं दांतों या स्वास्थ्य से जुड़ी चिकित्सा सलाह नहीं दे सकती। आपके लिए क्या उपयुक्त है, इस पर डेंटिस्ट कंसल्टेशन में बात कर सकते हैं।",
    "hinglish": "Main dental ya medical salaah nahin de sakti. Aapke liye kya suitable hai, yeh dentist consultation mein discuss kar sakte hain.",
    "hinglish_speech": "मैं डेंटल या मेडिकल सलाह नहीं दे सकती। आपके लिए क्या सूटेबल है, यह डेंटिस्ट कंसल्टेशन में डिस्कस कर सकते हैं।",
}

_URGENT = {
    "en": knowledge.URGENT_NOTE,
    "hi": "अगर आपको तुरंत मदद चाहिए, तो कृपया सीधे क्लिनिक को फ़ोन करें या अपनी स्थानीय आपातकालीन सेवाओं से संपर्क करें।",
    "hinglish": "Agar aapko turant madad chahiye, toh please seedhe clinic ko phone kariye ya apni local emergency services se contact kariye.",
    "hinglish_speech": "अगर आपको तुरंत मदद चाहिए, तो प्लीज़ सीधे क्लिनिक को फ़ोन करिए या अपनी लोकल इमरजेंसी सर्विसेज़ से कॉन्टैक्ट करिए।",
}

# key -> wording per language. English entries are the exact text the assistant has always used.
MESSAGES = {
    # Greetings
    "voice_greeting": {
        "en": knowledge.VOICE_GREETING[0],
        "hi": "{clinic} में कॉल करने के लिए धन्यवाद। इस समय क्लिनिक बंद है, इसलिए आप हमारे स्वचालित असिस्टेंट से बात कर रहे हैं।",
        "hinglish": "{clinic} ko call karne ke liye dhanyavaad. Abhi clinic band hai, isliye aap hamare automated assistant se baat kar rahe hain.",
        "hinglish_speech": "{clinic} को कॉल करने के लिए धन्यवाद। अभी क्लिनिक बंद है, इसलिए आप हमारे ऑटोमेटेड असिस्टेंट से बात कर रहे हैं।",
    },
    "voice_greeting_help": {
        "en": knowledge.VOICE_GREETING[1],
        "hi": "मैं कंसल्टेशन बुक करने में, क्लिनिक से जुड़े सामान्य सवालों के जवाब देने में, या हमारे फ्रंट डेस्क से आपको कॉल करवाने में मदद कर सकती हूँ। मैं दांतों या स्वास्थ्य से जुड़ी चिकित्सा सलाह नहीं दे सकती।",
        "hinglish": "Main consultation book karne mein, clinic ke general sawaalon ke jawab dene mein, ya front desk se aapko call karwane mein madad kar sakti hoon. Main dental ya medical salaah nahin de sakti.",
        "hinglish_speech": "मैं कंसल्टेशन बुक करने में, क्लिनिक के जनरल सवालों के जवाब देने में, या फ्रंट डेस्क से आपको कॉल करवाने में मदद कर सकती हूँ। मैं डेंटल या मेडिकल सलाह नहीं दे सकती।",
    },
    "welcome": {
        "en": (
            "Hello, and welcome to {clinic}. I can help you book a consultation, answer general questions "
            "about the clinic, or ask our front desk to call you."
        ),
        "hi": "नमस्ते, {clinic} में आपका स्वागत है। मैं कंसल्टेशन बुक करने में, क्लिनिक से जुड़े सामान्य सवालों के जवाब देने में, या हमारे फ्रंट डेस्क से आपको कॉल करवाने में मदद कर सकती हूँ।",
        "hinglish": "Namaste, {clinic} mein aapka swagat hai. Main consultation book karne mein, clinic ke general sawaalon ke jawab dene mein, ya front desk se aapko call karwane mein madad kar sakti hoon.",
        "hinglish_speech": "नमस्ते, {clinic} में आपका स्वागत है। मैं कंसल्टेशन बुक करने में, क्लिनिक के जनरल सवालों के जवाब देने में, या फ्रंट डेस्क से आपको कॉल करवाने में मदद कर सकती हूँ।",
    },
    "no_advice": {
        "en": "I can't give dental or medical advice.",
        "hi": "मैं दांतों या स्वास्थ्य से जुड़ी चिकित्सा सलाह नहीं दे सकती।",
        "hinglish": "Main dental ya medical salaah nahin de sakti.",
        "hinglish_speech": "मैं डेंटल या मेडिकल सलाह नहीं दे सकती।",
    },
    "goodbye": {
        "en": "Thank you for calling {clinic}. Goodbye.",
        "hi": "{clinic} में कॉल करने के लिए धन्यवाद। नमस्ते।",
        "hinglish": "{clinic} ko call karne ke liye dhanyavaad. Namaste.",
        "hinglish_speech": "{clinic} को कॉल करने के लिए धन्यवाद। नमस्ते।",
    },
    # Unclear input and small talk
    "how_can_i_help": {
        "en": "How can I help? You can type a question or choose an option.",
        "hi": "मैं आपकी कैसे मदद कर सकती हूँ? आप अपना सवाल लिख सकते हैं या कोई विकल्प चुन सकते हैं।",
        "hinglish": "Main aapki kaise madad kar sakti hoon? Aap apna sawaal type kar sakte hain ya koi option chun sakte hain.",
        "hinglish_speech": "मैं आपकी कैसे मदद कर सकती हूँ? आप अपना सवाल टाइप कर सकते हैं या कोई ऑप्शन चुन सकते हैं।",
    },
    "choose": {
        "en": "Please choose one of the options below.",
        "hi": "कृपया नीचे दिए गए विकल्पों में से कोई एक चुनें।",
        "hinglish": "Please neeche diye gaye options mein se koi ek chuniye.",
        "hinglish_speech": "प्लीज़ नीचे दिए गए ऑप्शन्स में से कोई एक चुनिए।",
    },
    "thanks": {
        "en": "You're welcome. Is there anything else I can help with?",
        "hi": "आपका स्वागत है। क्या मैं आपकी किसी और चीज़ में मदद कर सकती हूँ?",
        "hinglish": "Koi baat nahin. Kya main aapki kisi aur cheez mein madad kar sakti hoon?",
        "hinglish_speech": "कोई बात नहीं। क्या मैं आपकी किसी और चीज़ में मदद कर सकती हूँ?",
    },
    # Opening hours and the Sunday closure
    "topic_hours": {
        "en": knowledge.CLINIC_HOURS,
        "hi": "Smriti Raj Dentistry सोमवार से शनिवार, सुबह 9:00 बजे से रात 8:00 बजे तक खुला रहता है। रविवार को क्लिनिक बंद रहता है।",
        "hinglish": "Smriti Raj Dentistry Monday se Saturday, subah 9:00 AM se raat 8:00 PM tak khula rehta hai. Sunday ko clinic band rehta hai.",
        "hinglish_speech": "स्मृति राज डेंटिस्ट्री सोमवार से शनिवार, सुबह 9 बजे से रात 8 बजे तक खुला रहता है। रविवार को क्लिनिक बंद रहता है।",
    },
    "closed_day": {
        "en": "{clinic} is closed on {weekday}.",
        "hi": "{clinic} {weekday} को बंद रहता है।",
        "hinglish": "{clinic} {weekday} ko band rehta hai.",
        "hinglish_speech": "{clinic} {weekday} को बंद रहता है।",
    },
    "closed_day_next": {
        "en": "{clinic} is closed on {weekday}. The next available appointments are on {next_weekday}.",
        "hi": "{clinic} {weekday} को बंद रहता है। अगले उपलब्ध अपॉइंटमेंट {next_weekday} को हैं।",
        "hinglish": "{clinic} {weekday} ko band rehta hai. Agle available appointments {next_weekday} ko hain.",
        "hinglish_speech": "{clinic} {weekday} को बंद रहता है। अगले उपलब्ध अपॉइंटमेंट {next_weekday} को हैं।",
    },
    "booking_window": {
        "en": "Appointments can be booked up to 7 days ahead, so here are the earliest available times.",
        "hi": "अपॉइंटमेंट केवल 7 दिन आगे तक बुक किए जा सकते हैं, इसलिए यहाँ सबसे पहले उपलब्ध समय दिए गए हैं।",
        "hinglish": "Appointments sirf 7 din aage tak book ho sakte hain, isliye yeh sabse pehle available times hain.",
        "hinglish_speech": "अपॉइंटमेंट सिर्फ़ 7 दिन आगे तक बुक हो सकते हैं, इसलिए ये सबसे पहले उपलब्ध टाइम्स हैं।",
    },
    # Other approved answers
    "topic_fees": {
        "en": next(t["answer"] for t in knowledge.TOPICS if t["id"] == "fees"),
        "hi": "इस डेमो में कंसल्टेशन शुल्क केवल नमूना राशि हैं:\n{fees}\nइलाज का खर्च डेंटिस्ट की जाँच पर निर्भर करता है, इसलिए मैं यहाँ उसकी राशि नहीं बता सकती। हमारा फ्रंट डेस्क मौजूदा शुल्क की पुष्टि कर सकता है।",
        "hinglish": "Is demo mein consultation fees sirf sample values hain:\n{fees}\nTreatment ka kharcha dentist ke assessment par depend karta hai, isliye main yahan quote nahin kar sakti. Hamara front desk current fees confirm kar sakta hai.",
        "hinglish_speech": "इस डेमो में कंसल्टेशन फ़ीस सिर्फ़ सैंपल वैल्यूज़ हैं:\n{fees}\nट्रीटमेंट का खर्चा डेंटिस्ट के असेसमेंट पर डिपेंड करता है, इसलिए मैं यहाँ कोट नहीं कर सकती। हमारा फ्रंट डेस्क करंट फ़ीस कन्फ़र्म कर सकता है।",
    },
    "topic_location": {
        "en": next(t["answer"] for t in knowledge.TOPICS if t["id"] == "location"),
        "hi": "{clinic} का पता: {address}\nफ़ोन: {phone}\nईमेल: {email}",
        "hinglish": "{clinic} ka address hai: {address}\nPhone: {phone}\nEmail: {email}",
        "hinglish_speech": "{clinic} का एड्रेस है: {address}\nफ़ोन: {phone}\nईमेल: {email}",
    },
    "topic_doctors": {
        "en": next(t["answer"] for t in knowledge.TOPICS if t["id"] == "doctors"),
        "hi": "हमारे डॉक्टर:\n{doctors}",
        "hinglish": "Hamare doctors:\n{doctors}",
        "hinglish_speech": "हमारे डॉक्टर्स:\n{doctors}",
    },
    "topic_services": {
        "en": next(t["answer"] for t in knowledge.TOPICS if t["id"] == "services"),
        "hi": "हम इन सेवाओं के लिए कंसल्टेशन देते हैं:\n{services}\n" + _SAFETY["hi"],
        "hinglish": "Hum in services ke liye consultation dete hain:\n{services}\n" + _SAFETY["hinglish"],
        "hinglish_speech": "हम इन सर्विसेज़ के लिए कंसल्टेशन देते हैं:\n{services}\n" + _SAFETY["hinglish_speech"],
    },
    "service_answer": {
        "en": knowledge.SERVICE_ANSWER,
        "hi": "जी हाँ, {service} हमारी सेवाओं में शामिल है। " + _SAFETY["hi"],
        "hinglish": "Haan, {service} hamari services mein shaamil hai. " + _SAFETY["hinglish"],
        "hinglish_speech": "हाँ, {service} हमारी सर्विसेज़ में शामिल है। " + _SAFETY["hinglish_speech"],
    },
    "book_question": {
        "en": "Would you like to book a consultation?",
        "hi": "क्या आप कंसल्टेशन बुक करना चाहेंगे?",
        "hinglish": "Kya aap consultation book karna chahenge?",
        "hinglish_speech": "क्या आप कंसल्टेशन बुक करना चाहेंगे?",
    },
    # Booking questions
    "booking_guidance": {
        "en": knowledge.BOOKING_GUIDANCE,
        "hi": "मैं यहीं आपकी कंसल्टेशन बुक कर सकती हूँ। मैं मरीज़ का नाम और मोबाइल नंबर, आने का कारण, और पसंदीदा डॉक्टर व दिन पूछूँगी, फिर उपलब्ध समय बताऊँगी। जब तक हमारा फ्रंट डेस्क पुष्टि नहीं करता, बुकिंग एक अनुरोध ही रहती है।",
        "hinglish": "Main yahin aapka consultation book kar sakti hoon. Main patient ka naam aur mobile number, visit ka reason, aur preferred doctor aur din poochhungi, phir available times bataungi. Jab tak hamara front desk confirm nahin karta, booking ek request hi rehti hai.",
        "hinglish_speech": "मैं यहीं आपका कंसल्टेशन बुक कर सकती हूँ। मैं पेशेंट का नाम और मोबाइल नंबर, विज़िट का रीज़न, और पसंदीदा डॉक्टर और दिन पूछूँगी, फिर उपलब्ध टाइम्स बताऊँगी। जब तक हमारा फ्रंट डेस्क कन्फ़र्म नहीं करता, बुकिंग एक रिक्वेस्ट ही रहती है।",
    },
    "ask_patient_type": {
        "en": "Has the patient visited us before?",
        "hi": "क्या मरीज़ पहले हमारे क्लिनिक आ चुके हैं?",
        "hinglish": "Kya patient pehle hamare clinic aa chuke hain?",
        "hinglish_speech": "क्या पेशेंट पहले हमारे क्लिनिक आ चुके हैं?",
    },
    "ask_name": {
        "en": "What is the patient's full name?",
        "hi": "मरीज़ का पूरा नाम क्या है?",
        "hinglish": "Patient ka poora naam kya hai?",
        "hinglish_speech": "पेशेंट का पूरा नाम क्या है?",
    },
    "enter_full_name": {
        "en": "Please enter the patient's full name.",
        "hi": "कृपया मरीज़ का पूरा नाम लिखें।",
        "hinglish": "Please patient ka poora naam likhiye.",
        "hinglish_speech": "प्लीज़ पेशेंट का पूरा नाम लिखिए।",
    },
    "ask_mobile": {
        "en": "What mobile number can we reach you on?",
        "hi": "हम आपसे किस मोबाइल नंबर पर संपर्क करें?",
        "hinglish": "Hum aapse kis mobile number par contact karein?",
        "hinglish_speech": "हम आपसे किस मोबाइल नंबर पर कॉन्टैक्ट करें?",
    },
    "ask_email": {
        "en": "An email address is optional. You can skip this.",
        "hi": "ईमेल पता देना ज़रूरी नहीं है। आप इसे छोड़ सकते हैं।",
        "hinglish": "Email address dena zaroori nahin hai. Aap ise skip kar sakte hain.",
        "hinglish_speech": "ईमेल एड्रेस देना ज़रूरी नहीं है। आप इसे स्किप कर सकते हैं।",
    },
    "bad_email": {
        "en": "That doesn't look like an email address. Please try again, or skip this step.",
        "hi": "यह ईमेल पता सही नहीं लग रहा। कृपया फिर से लिखें, या यह चरण छोड़ दें।",
        "hinglish": "Yeh email address sahi nahin lag raha. Please dobara likhiye, ya yeh step skip kar dijiye.",
        "hinglish_speech": "यह ईमेल एड्रेस सही नहीं लग रहा। प्लीज़ दोबारा लिखिए, या यह स्टेप स्किप कर दीजिए।",
    },
    "ask_service": {
        "en": "What is the visit for?",
        "hi": "आप किस लिए आना चाहते हैं?",
        "hinglish": "Visit kis liye hai?",
        "hinglish_speech": "विज़िट किस लिए है?",
    },
    "ask_doctor": {
        "en": "Do you have a preferred doctor?",
        "hi": "क्या आप किसी खास डॉक्टर से मिलना चाहेंगे?",
        "hinglish": "Kya aap kisi particular doctor se milna chahenge?",
        "hinglish_speech": "क्या आप किसी खास डॉक्टर से मिलना चाहेंगे?",
    },
    "ask_date": {
        "en": "Which day would you prefer?",
        "hi": "आप किस दिन आना पसंद करेंगे?",
        "hinglish": "Aap kis din aana pasand karenge?",
        "hinglish_speech": "आप किस दिन आना पसंद करेंगे?",
    },
    # Offered times
    "slots_three": {
        "en": "Here are three available times:",
        "hi": "ये तीन समय उपलब्ध हैं:",
        "hinglish": "Yeh teen times available hain:",
        "hinglish_speech": "ये तीन टाइम्स उपलब्ध हैं:",
    },
    "slots_some": {
        "en": "Here are the available times:",
        "hi": "ये समय उपलब्ध हैं:",
        "hinglish": "Yeh times available hain:",
        "hinglish_speech": "ये टाइम्स उपलब्ध हैं:",
    },
    # Read out on the call demo after the offer, one per offered time (options 1, 2 and 3).
    "slot_option": {
        "en": "Option {number}: {day} at {time} with {doctor}.",
        "hi": "विकल्प {number}: {day}, {time}, {doctor} के साथ।",
        "hinglish": "Option {number}: {day}, {time}, {doctor} ke saath.",
        "hinglish_speech": "ऑप्शन {number}: {day}, {time}, {doctor} के साथ।",
    },
    "slots_from_later": {
        "en": "There are no free times from that day onwards, so here are the next available ones.",
        "hi": "उस दिन या उसके बाद कोई समय खाली नहीं है, इसलिए यहाँ सबसे नज़दीकी उपलब्ध समय दिए गए हैं।",
        "hinglish": "Us din ya uske baad koi time free nahin hai, isliye yeh sabse nazdeeki available times hain.",
        "hinglish_speech": "उस दिन या उसके बाद कोई टाइम फ़्री नहीं है, इसलिए ये सबसे नज़दीकी उपलब्ध टाइम्स हैं।",
    },
    "slots_wrapped": {
        "en": "Those were all the times I could find. Here are the first options again.",
        "hi": "मुझे इतने ही समय मिले। यहाँ पहले वाले विकल्प फिर से दिए गए हैं।",
        "hinglish": "Mujhe itne hi times mile. Yeh pehle wale options phir se hain.",
        "hinglish_speech": "मुझे इतने ही टाइम्स मिले। ये पहले वाले ऑप्शन्स फिर से हैं।",
    },
    "choose_time": {
        "en": "Please choose one of the times below.",
        "hi": "कृपया नीचे दिए गए समयों में से कोई एक चुनें।",
        "hinglish": "Please neeche diye gaye times mein se koi ek chuniye.",
        "hinglish_speech": "प्लीज़ नीचे दिए गए टाइम्स में से कोई एक चुनिए।",
    },
    "no_slots": {
        "en": (
            "There are no free consultation times for that choice in the next 7 days. "
            "You can choose another doctor, or join the waitlist and our staff will contact you if a time becomes free."
        ),
        "hi": "अगले 7 दिनों में इस चुनाव के लिए कोई कंसल्टेशन समय खाली नहीं है। आप कोई दूसरे डॉक्टर चुन सकते हैं, या वेटलिस्ट में नाम लिखवा सकते हैं; कोई समय खाली होने पर हमारा स्टाफ़ आपसे संपर्क करेगा।",
        "hinglish": "Agle 7 dinon mein is choice ke liye koi consultation time free nahin hai. Aap koi doosre doctor chun sakte hain, ya waitlist join kar sakte hain; time free hone par hamara staff aapse contact karega.",
        "hinglish_speech": "अगले 7 दिनों में इस चॉइस के लिए कोई कंसल्टेशन टाइम फ़्री नहीं है। आप कोई दूसरे डॉक्टर चुन सकते हैं, या वेटलिस्ट जॉइन कर सकते हैं; टाइम फ़्री होने पर हमारा स्टाफ़ आपसे कॉन्टैक्ट करेगा।",
    },
    # Booking confirmation
    "confirm_details": {
        "en": (
            "Please check the details:\n• Patient: {name}\n• Mobile: {mobile}\n• Visit: {service}\n"
            "• Doctor: {doctor}\n• When: {date} at {time} ({minutes} min)"
        ),
        "hi": "कृपया विवरण जाँच लें:\n• मरीज़: {name}\n• मोबाइल: {mobile}\n• विज़िट: {service}\n• डॉक्टर: {doctor}\n• समय: {date}, {time} ({minutes} मिनट)",
        "hinglish": "Please details check kar lijiye:\n• Patient: {name}\n• Mobile: {mobile}\n• Visit: {service}\n• Doctor: {doctor}\n• Kab: {date}, {time} ({minutes} min)",
        "hinglish_speech": "प्लीज़ डिटेल्स चेक कर लीजिए:\n• पेशेंट: {name}\n• मोबाइल: {mobile}\n• विज़िट: {service}\n• डॉक्टर: {doctor}\n• कब: {date}, {time} ({minutes} मिनट)",
    },
    "booking_saved": {
        "en": "Thank you, {name}. Your consultation request is saved.",
        "hi": "धन्यवाद, {name}। आपका कंसल्टेशन अनुरोध सेव हो गया है।",
        "hinglish": "Dhanyavaad, {name}. Aapki consultation request save ho gayi hai.",
        "hinglish_speech": "धन्यवाद, {name}। आपकी कंसल्टेशन रिक्वेस्ट सेव हो गई है।",
    },
    "booking_status": {
        "en": "Your booking is {status} until our front desk confirms it. Your reference is #{reference}.",
        "hi": "जब तक हमारा फ्रंट डेस्क पुष्टि नहीं करता, आपकी बुकिंग {status} है। आपका संदर्भ नंबर #{reference} है।",
        "hinglish": "Jab tak hamara front desk confirm nahin karta, aapki booking {status} hai. Aapka reference #{reference} hai.",
        "hinglish_speech": "जब तक हमारा फ्रंट डेस्क कन्फ़र्म नहीं करता, आपकी बुकिंग {status} है। आपका रेफ़रेंस नंबर {reference} है।",
    },
    # Waitlist
    "waitlist_offer": {
        "en": "I can add you to our waitlist. When would you prefer to come in?",
        "hi": "मैं आपका नाम हमारी वेटलिस्ट में जोड़ सकती हूँ। आप किस समय आना पसंद करेंगे?",
        "hinglish": "Main aapka naam hamari waitlist mein add kar sakti hoon. Aap kis time aana pasand karenge?",
        "hinglish_speech": "मैं आपका नाम हमारी वेटलिस्ट में ऐड कर सकती हूँ। आप किस टाइम आना पसंद करेंगे?",
    },
    "waitlist_joined": {
        "en": "Thank you, {name}. You are on our waitlist.",
        "hi": "धन्यवाद, {name}। आपका नाम हमारी वेटलिस्ट में है।",
        "hinglish": "Dhanyavaad, {name}. Aapka naam hamari waitlist mein hai.",
        "hinglish_speech": "धन्यवाद, {name}। आपका नाम हमारी वेटलिस्ट में है।",
    },
    "waitlist_details": {
        "en": (
            "Nothing has been booked. If a suitable time becomes free, our staff will contact you during clinic hours "
            "to offer it. Your waitlist reference is W-{reference}."
        ),
        "hi": "अभी कुछ भी बुक नहीं हुआ है। कोई उपयुक्त समय खाली होने पर हमारा स्टाफ़ क्लिनिक के समय में आपसे संपर्क करेगा। आपका वेटलिस्ट संदर्भ W-{reference} है।",
        "hinglish": "Abhi kuch bhi book nahin hua hai. Koi suitable time free hone par hamara staff clinic hours mein aapse contact karega. Aapka waitlist reference W-{reference} hai.",
        "hinglish_speech": "अभी कुछ भी बुक नहीं हुआ है। कोई सूटेबल टाइम फ़्री होने पर हमारा स्टाफ़ क्लिनिक आवर्स में आपसे कॉन्टैक्ट करेगा। आपका वेटलिस्ट रेफ़रेंस डब्ल्यू {reference} है।",
    },
    # Human handoff, clinical safety and emergency wording
    "callback_human": {
        "en": knowledge.CALLBACK_INTROS["human"],
        "hi": "ज़रूर। मैं हमारे फ्रंट डेस्क से आपको कॉल करने के लिए कहूँगी।",
        "hinglish": "Zaroor. Main hamare front desk ko aapko call karne ke liye bolungi.",
        "hinglish_speech": "ज़रूर। मैं हमारे फ्रंट डेस्क को आपको कॉल करने के लिए बोलूँगी।",
    },
    "callback_clinical": {
        "en": knowledge.CALLBACK_INTROS["clinical"],
        "hi": "मैं क्लिनिकल या मेडिकल सवालों के जवाब नहीं दे सकती, और न ही कोई निदान या इलाज सुझा सकती हूँ। मैं हमारे फ्रंट डेस्क से आपको कॉल करने के लिए कहूँगी, ताकि हमारी टीम का कोई सदस्य आपकी मदद कर सके।\n" + _URGENT["hi"],
        "hinglish": "Main clinical ya medical sawaalon ka jawab nahin de sakti, aur koi diagnosis ya treatment suggest nahin kar sakti. Main front desk ko aapko call karne ke liye bolungi, taaki hamari team ka koi member aapki madad kar sake.\n" + _URGENT["hinglish"],
        "hinglish_speech": "मैं क्लिनिकल या मेडिकल सवालों का जवाब नहीं दे सकती, और कोई डायग्नोसिस या ट्रीटमेंट सजेस्ट नहीं कर सकती। मैं फ्रंट डेस्क को आपको कॉल करने के लिए बोलूँगी, ताकि हमारी टीम का कोई मेंबर आपकी मदद कर सके।\n" + _URGENT["hinglish_speech"],
    },
    "callback_unsupported": {
        "en": knowledge.CALLBACK_INTROS["unsupported"],
        "hi": "इस सवाल के लिए मेरे पास स्वीकृत जानकारी नहीं है। मैं हमारे फ्रंट डेस्क से आपको कॉल करने के लिए कहूँगी।",
        "hinglish": "Is sawaal ke liye mere paas approved jaankari nahin hai. Main front desk ko aapko call karne ke liye bolungi.",
        "hinglish_speech": "इस सवाल के लिए मेरे पास अप्रूव्ड जानकारी नहीं है। मैं फ्रंट डेस्क को आपको कॉल करने के लिए बोलूँगी।",
    },
    "callback_cghs": {
        "en": knowledge.CALLBACK_INTROS["cghs"],
        "hi": "मैं यहाँ CGHS या ECHS की पात्रता या कवरेज की पुष्टि नहीं कर सकती। हमारा फ्रंट डेस्क जाँच करके आपको वापस कॉल करेगा। आपकी पूछताछ किस योजना के बारे में है?",
        "hinglish": "Main yahan CGHS ya ECHS eligibility ya cover confirm nahin kar sakti. Hamara front desk check karke aapko call back karega. Aapki enquiry kis scheme ke baare mein hai?",
        "hinglish_speech": "मैं यहाँ सी जी एच एस या ई सी एच एस एलिजिबिलिटी या कवर कन्फ़र्म नहीं कर सकती। हमारा फ्रंट डेस्क चेक करके आपको कॉल बैक करेगा। आपकी इन्क्वायरी किस स्कीम के बारे में है?",
    },
    "urgent_note": _URGENT,
    "ask_scheme": {
        "en": "Which scheme is your enquiry about?",
        "hi": "आपकी पूछताछ किस योजना के बारे में है?",
        "hinglish": "Aapki enquiry kis scheme ke baare mein hai?",
        "hinglish_speech": "आपकी इन्क्वायरी किस स्कीम के बारे में है?",
    },
    "ask_callback_name": {
        "en": "Who should we ask for? Please enter a name.",
        "hi": "हम किनके लिए पूछें? कृपया नाम लिखें।",
        "hinglish": "Hum kiske liye poochhein? Please naam likhiye.",
        "hinglish_speech": "हम किसके लिए पूछें? प्लीज़ नाम लिखिए।",
    },
    "enter_name": {
        "en": "Please enter a name.",
        "hi": "कृपया नाम लिखें।",
        "hinglish": "Please naam likhiye.",
        "hinglish_speech": "प्लीज़ नाम लिखिए।",
    },
    "ask_callback_mobile": {
        "en": "What mobile number should we call?",
        "hi": "हम किस मोबाइल नंबर पर कॉल करें?",
        "hinglish": "Hum kis mobile number par call karein?",
        "hinglish_speech": "हम किस मोबाइल नंबर पर कॉल करें?",
    },
    "callback_saved": {
        "en": "Thank you, {name}. I've passed your request to our front desk.",
        "hi": "धन्यवाद, {name}। मैंने आपका अनुरोध हमारे फ्रंट डेस्क तक पहुँचा दिया है।",
        "hinglish": "Dhanyavaad, {name}. Maine aapki request front desk tak pahuncha di hai.",
        "hinglish_speech": "धन्यवाद, {name}। मैंने आपकी रिक्वेस्ट फ्रंट डेस्क तक पहुँचा दी है।",
    },
    "callback_reference": {
        "en": knowledge.CALLBACK_PROMISE + " Your reference is C-{reference}.",
        "hi": "हमारा स्टाफ़ क्लिनिक के समय में आपसे संपर्क करेगा। आपका संदर्भ नंबर C-{reference} है।",
        "hinglish": "Hamara staff clinic hours mein aapse contact karega. Aapka reference C-{reference} hai.",
        "hinglish_speech": "हमारा स्टाफ़ क्लिनिक आवर्स में आपसे कॉन्टैक्ट करेगा। आपका रेफ़रेंस सी {reference} है।",
    },
}

# Messages raised by the booking services themselves (validation and slot conflicts), by English text.
SERVICE_MESSAGES = {
    "Please enter a valid mobile number (7 to 15 digits).": {
        "hi": "कृपया सही मोबाइल नंबर लिखें (7 से 15 अंक)।",
        "hinglish": "Please sahi mobile number likhiye (7 se 15 digits).",
        "hinglish_speech": "प्लीज़ सही मोबाइल नंबर लिखिए, 7 से 15 अंकों का।",
    },
    "This slot has just been booked. Please choose another available time.": {
        "hi": "यह समय अभी-अभी बुक हो गया है। कृपया कोई दूसरा उपलब्ध समय चुनें।",
        "hinglish": "Yeh slot abhi-abhi book ho gaya hai. Please koi doosra available time chuniye.",
        "hinglish_speech": "यह स्लॉट अभी-अभी बुक हो गया है। प्लीज़ कोई दूसरा उपलब्ध टाइम चुनिए।",
    },
    "Please enter the patient's name.": {
        "hi": "कृपया मरीज़ का नाम लिखें।",
        "hinglish": "Please patient ka naam likhiye.",
        "hinglish_speech": "प्लीज़ पेशेंट का नाम लिखिए।",
    },
}

# Button and input wording, by English label. Values sent back to the server never change.
LABELS = {
    "Speak to a person": {"hi": "किसी व्यक्ति से बात करें", "hinglish": "Kisi person se baat karein"},
    "Book a consultation": {"hi": "कंसल्टेशन बुक करें", "hinglish": "Consultation book karein"},
    "Start over": {"hi": "फिर से शुरू करें", "hinglish": "Phir se shuru karein"},
    "New patient": {"hi": "नए मरीज़", "hinglish": "Naye patient"},
    "Existing patient": {"hi": "पुराने मरीज़", "hinglish": "Purane patient"},
    "Skip": {"hi": "छोड़ें", "hinglish": "Skip karein"},
    "No preference": {"hi": "कोई खास पसंद नहीं", "hinglish": "Koi preference nahin"},
    "Join waitlist": {"hi": "वेटलिस्ट में जुड़ें", "hinglish": "Waitlist join karein"},
    "Earliest available": {"hi": "सबसे पहला उपलब्ध समय", "hinglish": "Sabse pehla available"},
    "Today": {"hi": "आज", "hinglish": "Aaj"},
    "Show other times": {"hi": "दूसरे समय दिखाएँ", "hinglish": "Doosre times dikhayein"},
    "Change day": {"hi": "दिन बदलें", "hinglish": "Din badlein"},
    "Confirm booking": {"hi": "बुकिंग की पुष्टि करें", "hinglish": "Booking confirm karein"},
    "Choose another time": {"hi": "दूसरा समय चुनें", "hinglish": "Doosra time chunein"},
    "Morning": {"hi": "सुबह", "hinglish": "Subah"},
    "Afternoon": {"hi": "दोपहर", "hinglish": "Dopahar"},
    "Any time": {"hi": "किसी भी समय", "hinglish": "Kabhi bhi"},
    "Ask something else": {"hi": "कुछ और पूछें", "hinglish": "Kuch aur poochhein"},
    "No thanks": {"hi": "नहीं, धन्यवाद", "hinglish": "Nahin, thank you"},
    "Not sure": {"hi": "पक्का नहीं पता", "hinglish": "Pakka nahin pata"},
    "Book for {service}": {"hi": "{service} के लिए बुक करें", "hinglish": "{service} ke liye book karein"},
    # Input labels and placeholders
    "Full name": {"hi": "पूरा नाम", "hinglish": "Poora naam"},
    "Name": {"hi": "नाम", "hinglish": "Naam"},
    "Mobile number": {"hi": "मोबाइल नंबर", "hinglish": "Mobile number"},
    "Email (optional)": {"hi": "ईमेल (वैकल्पिक)", "hinglish": "Email (optional)"},
    # Suggested prompts and caller phrases (what is displayed; the English phrase is what is sent)
    "What are your opening hours?": {"hi": "क्लिनिक कब खुला रहता है?", "hinglish": "Clinic ki timings kya hain?"},
    "I want to book a consultation.": {"hi": "मुझे कंसल्टेशन बुक करनी है।", "hinglish": "Mujhe consultation book karni hai."},
    "I need to book a consultation.": {"hi": "मुझे कंसल्टेशन बुक करनी है।", "hinglish": "Mujhe consultation book karni hai."},
    "Do you offer dental implants?": {"hi": "क्या आप डेंटल इम्प्लांट करते हैं?", "hinglish": "Kya aap dental implants karte hain?"},
    "I want to speak to a person.": {"hi": "मुझे किसी व्यक्ति से बात करनी है।", "hinglish": "Mujhe kisi person se baat karni hai."},
    "I have severe tooth pain; what medicine should I take?": {
        "hi": "मेरे दांत में तेज़ दर्द है; मुझे कौन-सी दवा लेनी चाहिए?",
        "hinglish": "Mere daant mein bahut dard hai; kaunsi dawai leni chahiye?",
    },
    "Can I come on Sunday?": {"hi": "क्या रविवार को आ सकते हैं?", "hinglish": "Kya Sunday ko aa sakte hain?"},
}

# Data shown inside Hindi messages: weekday and month names are written in Hindi, nothing else changes.
HINDI_WEEKDAYS = {
    "Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार", "Thursday": "गुरुवार",
    "Friday": "शुक्रवार", "Saturday": "शनिवार", "Sunday": "रविवार",
    "Mon": "सोमवार", "Tue": "मंगलवार", "Wed": "बुधवार", "Thu": "गुरुवार",
    "Fri": "शुक्रवार", "Sat": "शनिवार", "Sun": "रविवार",
}
HINDI_MONTHS = {
    "Jan": "जनवरी", "Feb": "फ़रवरी", "Mar": "मार्च", "Apr": "अप्रैल", "May": "मई", "Jun": "जून",
    "Jul": "जुलाई", "Aug": "अगस्त", "Sep": "सितंबर", "Oct": "अक्टूबर", "Nov": "नवंबर", "Dec": "दिसंबर",
}
# Booking status words inside a sentence. The receipt keeps the system status itself.
# "*_speech" is what the Hindi voice says.
STATUS_WORDS = {
    "PENDING": {"hi": "लंबित (PENDING)", "hinglish": "pending", "hi_speech": "लंबित", "hinglish_speech": "पेंडिंग"},
    "CONFIRMED": {"hi": "पक्की (CONFIRMED)", "hinglish": "confirmed", "hi_speech": "पक्की", "hinglish_speech": "कन्फ़र्म"},
}
# Small fixed words inside data lists (for example "(demo)" after a sample fee).
DATA_WORDS = {
    "hi": {"(demo)": "(डेमो)", "not listed": "उपलब्ध नहीं"},
    "hinglish": {"not listed": "available nahin"},
}

# Approved Devanagari pronunciations of the seeded clinic, doctor, speciality and service names, used
# in the Hindi and Hinglish speech text (the transcript keeps the original spelling). Names added later
# in Settings, and names callers type, are not listed and are read with English sounds.
SPEECH_NAMES = {
    "Smriti Raj Dentistry": "स्मृति राज डेंटिस्ट्री",
    "Dr. Anika Rao": "डॉक्टर अनिका राव",
    "Dr. Vikram Shah": "डॉक्टर विक्रम शाह",
    "Dr. Meera Iyer": "डॉक्टर मीरा अय्यर",
    "General Consultation": "जनरल कंसल्टेशन",
    "Dental Implants": "डेंटल इम्प्लांट्स",
    "Root Canal Treatment": "रूट कैनाल ट्रीटमेंट",
    "Aligners": "अलाइनर्स",
    "General Dentistry": "जनरल डेंटिस्ट्री",
    "Implantology & Oral Surgery": "इम्प्लांटोलॉजी और ओरल सर्जरी",
    "Endodontics & Orthodontics": "एंडोडॉन्टिक्स और ऑर्थोडॉन्टिक्स",
}

# How the Hindi voice reads the remaining English tokens. Speech only; digits stay digits.
SPEECH_WORDS = {
    "hi": {
        **SPEECH_NAMES,
        "Dr.": "डॉक्टर",
        "PENDING": "",
        "CONFIRMED": "",
        "AM": "ए एम",
        "PM": "पी एम",
        "CGHS": "सी जी एच एस",
        "ECHS": "ई सी एच एस",
        "min": "मिनट",
        "number": "नंबर",
    },
}

# Call-demo screen text that changes with the language.
UI = {
    "en": {
        "language_changed": "Language changed to English. The next assistant reply will be in English.",
        "receipt_booking": "Booking request",
        "receipt_callback": "Callback request",
        "reference": "Reference",
        "visit": "Visit",
        "doctor": "Doctor",
        "when": "When",
        "status": "Status",
        "we_will_call": "We will call",
        "test_phrase": "Hello. This is the Smriti Raj Dentistry appointment assistant.",
        "test_speech": "Hello. This is the Smriti Raj Dentistry appointment assistant.",
    },
    "hi": {
        "language_changed": "भाषा हिंदी में बदल दी गई है। असिस्टेंट का अगला जवाब हिंदी में होगा।",
        "receipt_booking": "बुकिंग अनुरोध",
        "receipt_callback": "कॉलबैक अनुरोध",
        "reference": "संदर्भ",
        "visit": "विज़िट",
        "doctor": "डॉक्टर",
        "when": "समय",
        "status": "स्थिति",
        "we_will_call": "हम इस नंबर पर कॉल करेंगे",
        "test_phrase": "नमस्ते। मैं स्मृति राज डेंटिस्ट्री की अपॉइंटमेंट असिस्टेंट हूँ।",
        "test_speech": "नमस्ते। मैं स्मृति राज डेंटिस्ट्री की अपॉइंटमेंट असिस्टेंट हूँ।",
    },
    "hinglish": {
        "language_changed": "Language Hinglish mein badal di gayi hai. Assistant ka agla jawab Hinglish mein hoga.",
        "receipt_booking": "Booking request",
        "receipt_callback": "Callback request",
        "reference": "Reference",
        "visit": "Visit",
        "doctor": "Doctor",
        "when": "Kab",
        "status": "Status",
        "we_will_call": "Hum call karenge",
        "test_phrase": "Namaste. Main Smriti Raj Dentistry ki appointment assistant hoon.",
        "test_speech": "नमस्ते। मैं स्मृति राज डेंटिस्ट्री की अपॉइंटमेंट असिस्टेंट हूँ।",
    },
}
