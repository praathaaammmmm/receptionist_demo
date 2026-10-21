"""Every line the voice agent may speak, in English, Hindi (Devanagari) and Hinglish (Roman Hindi).

Lines are written to be read aloud: short sentences, no bullets, emojis, symbols or URLs.
Numbers are given in spoken form ("500 rupees", phone digits one at a time).
The voice is the same as the call demo's, so Hindi verbs use the feminine form.
All Hindi and Hinglish wording needs owner review before production.
"""
from .knowledge import APPROVED

LANGUAGES = ("en", "hi", "hinglish")

# Spoken forms of approved facts. Kept next to the lines that use them.
_FEE = APPROVED.commercial.consultation_fee_inr
_PHONE_RECEPTION = "8 5 2 7 2, 7 5 5 2 1"
_PHONE_ALTERNATE = "7 3 0 3 7, 8 6 2 8 4"

FACTS = {
    "en": {
        "address": "Basement Floor, Plot Number 54, Sector 13, Dwarka, New Delhi, pin code 1 1 0 0 7 5",
        "landmark": "near Pragati Public School",
        "email": "bhargava dot smriti dot raj at gmail dot com",
    },
    "hi": {
        "address": "बेसमेंट फ़्लोर, प्लॉट नंबर 54, सेक्टर 13, द्वारका, नई दिल्ली, पिन कोड 1 1 0 0 7 5",
        "landmark": "प्रगति पब्लिक स्कूल के पास",
        "email": "भार्गवा डॉट स्मृति डॉट राज एट जीमेल डॉट कॉम",
    },
    "hinglish": {
        "address": "Basement Floor, Plot Number 54, Sector 13, Dwarka, New Delhi, pin code 1 1 0 0 7 5",
        "landmark": "Pragati Public School ke paas",
        "email": "bhargava dot smriti dot raj at gmail dot com",
    },
}

# Approved service names as spoken in each language. Keys match knowledge.Service.id.
SERVICE_NAMES = {
    "checkup": ("dental check-ups and consultations", "दांतों की जाँच और कंसल्टेशन", "dental check-up aur consultation"),
    "cavity": ("tooth pain and cavity assessment", "दांत दर्द और कैविटी की जाँच", "daant dard aur cavity ki jaanch"),
    "fillings": ("fillings", "फिलिंग", "filling"),
    "root_canal": ("root canal treatment", "रूट कैनाल ट्रीटमेंट", "root canal treatment"),
    "cleaning": ("teeth cleaning and scaling", "दांतों की सफ़ाई और स्केलिंग", "daanton ki safai aur scaling"),
    "extraction": ("tooth extraction", "दांत निकालने", "daant nikalne"),
    "crowns_bridges": ("crowns and bridges", "क्राउन और ब्रिज", "crown aur bridge"),
    "implants": ("dental implants", "डेंटल इम्प्लांट", "dental implant"),
    "braces_aligners": ("braces and clear aligners", "ब्रेसेस और क्लियर अलाइनर", "braces aur clear aligners"),
    "smile_whitening": ("smile design and teeth whitening", "स्माइल डिज़ाइन और दांतों की व्हाइटनिंग",
                        "smile design aur teeth whitening"),
    "children": ("children's dentistry", "बच्चों के दांतों के इलाज", "bachchon ke daanton ke ilaaj"),
    "gum": ("gum treatment", "मसूड़ों के इलाज", "masoodon ke ilaaj"),
    "xray": ("digital dental X-rays", "डिजिटल डेंटल एक्स-रे", "digital dental X-ray"),
    "same_day": ("same-day tooth or implant consultation, subject to the doctor's assessment",
                 "डॉक्टर के आकलन के अनुसार उसी दिन दांत या इम्प्लांट कंसल्टेशन",
                 "doctor ke assessment ke hisaab se same-day tooth ya implant consultation"),
}

AND = {"en": "and", "hi": "और", "hinglish": "aur"}

PROMISE = {
    "open": {
        "en": "as soon as possible during clinic hours",
        "hi": "क्लिनिक के समय में जल्द से जल्द",
        "hinglish": "clinic hours mein jaldi se jaldi",
    },
    "closed": {
        "en": "on the next working day",
        "hi": "अगले कार्य दिवस पर",
        "hinglish": "agle working day par",
    },
}

LINES = {
    # Emergency: 112 first, always. 112 appears in these emergency lines and nowhere else.
    "emergency": {
        "en": "This sounds like an emergency. Please call 112 now or go to the nearest hospital emergency "
              "department straight away. Please don't wait for the clinic to call you back.",
        "hi": "यह इमरजेंसी लग रही है। कृपया अभी 112 पर कॉल करें या तुरंत नज़दीकी अस्पताल की इमरजेंसी में जाएँ। "
              "क्लिनिक के कॉल का इंतज़ार न करें।",
        "hinglish": "Yeh emergency lag rahi hai. Please abhi 112 par call kariye ya turant nazdeeki hospital ki "
                    "emergency mein jaiye. Clinic ke call ka intezaar mat kariye.",
    },
    "emergency_transfer": {
        "en": "I can also try to connect you to our reception now.",
        "hi": "मैं आपको अभी हमारे रिसेप्शन से जोड़ने की कोशिश भी कर सकती हूँ।",
        "hinglish": "Main aapko abhi hamare reception se connect karne ki koshish bhi kar sakti hoon.",
    },
    "emergency_callback": {
        "en": "If you'd like, I can also ask our team to call you back {promise}.",
        "hi": "आप चाहें तो मैं हमारी टीम से आपको {promise} वापस कॉल करने को भी कह सकती हूँ।",
        "hinglish": "Aap chahein toh main hamari team ko aapko {promise} call back karne ko bhi bol sakti hoon.",
    },
    # Clinical questions: no diagnosis, medicines, remedies or reassurance.
    "clinical": {
        "en": "I'm sorry, I can't diagnose, suggest medicines or home remedies, or say whether something is "
              "serious. A dentist needs to check this. Would you like our team to call you back?",
        "hi": "माफ़ कीजिए, मैं कोई निदान, दवा या घरेलू उपाय नहीं बता सकती, और न ही यह कह सकती हूँ कि यह गंभीर है "
              "या नहीं। इसे डॉक्टर को देखना होगा। क्या आप चाहेंगे कि हमारी टीम आपको वापस कॉल करे?",
        "hinglish": "Maaf kijiye, main koi diagnosis, dawai ya gharelu nuskha nahin bata sakti, aur yeh bhi nahin "
                    "keh sakti ki yeh serious hai ya nahin. Ise doctor ko dekhna hoga. Kya aap chahenge ki hamari "
                    "team aapko call back kare?",
    },
    # Ordinary tooth pain or sensitivity: not an emergency on its own.
    "tooth_pain": {
        "en": "I'm sorry you're in pain. I can ask our team to call you to arrange an appointment. A same-day "
              "consultation may be possible, subject to the doctor's assessment. Would you like a callback?",
        "hi": "आपको दर्द हो रहा है, इसका मुझे खेद है। मैं हमारी टीम से आपको अपॉइंटमेंट के लिए कॉल करने को कह सकती "
              "हूँ। डॉक्टर के आकलन के अनुसार उसी दिन कंसल्टेशन संभव हो सकता है। क्या आप कॉलबैक चाहेंगे?",
        "hinglish": "Aapko dard ho raha hai, iske liye sorry. Main hamari team ko aapko appointment ke liye call "
                    "karne ko bol sakti hoon. Doctor ke assessment ke hisaab se same-day consultation ho sakta "
                    "hai. Kya aap callback chahenge?",
    },
    # Panel schemes: callback only, never eligibility, rates, documents, referrals or promises.
    "panel_cghs": {
        "en": "Smriti Raj Dentistry is CGHS-empanelled.",
        "hi": "स्मृति राज डेंटिस्ट्री सीजीएचएस पैनल में शामिल है।",
        "hinglish": "Smriti Raj Dentistry CGHS-empanelled hai.",
    },
    "panel": {
        "en": "For CGHS, ECHS, CISF, DU or Air India panel questions, our team will call you back. I can't "
              "confirm eligibility, rates, documents or referrals on this call. Would you like a callback?",
        "hi": "सीजीएचएस, ईसीएचएस, सीआईएसएफ़, डीयू या एयर इंडिया पैनल के सवालों के लिए हमारी टीम आपको वापस कॉल "
              "करेगी। मैं इस कॉल पर पात्रता, रेट, दस्तावेज़ या रेफ़रल की पुष्टि नहीं कर सकती। क्या आप कॉलबैक चाहेंगे?",
        "hinglish": "CGHS, ECHS, CISF, DU ya Air India panel ke sawaalon ke liye hamari team aapko call back "
                    "karegi. Main is call par eligibility, rates, documents ya referral confirm nahin kar sakti. "
                    "Kya aap callback chahenge?",
    },
    # Unknown information: never guess.
    "unknown_offer": {
        "en": "I can ask our team to call you back with the right answer. Would you like that?",
        "hi": "मैं हमारी टीम से आपको सही जानकारी के साथ वापस कॉल करने को कह सकती हूँ। क्या आप ऐसा चाहेंगे?",
        "hinglish": "Main hamari team ko aapko sahi jaankari ke saath call back karne ko bol sakti hoon. "
                    "Kya aap aisa chahenge?",
    },
    # Human requests.
    "transfer": {
        "en": "Of course. Let me connect you to our reception now.",
        "hi": "ज़रूर। मैं आपको अभी हमारे रिसेप्शन से जोड़ रही हूँ।",
        "hinglish": "Zaroor. Main aapko abhi hamare reception se connect kar rahi hoon.",
    },
    "transfer_unavailable": {
        "en": "Our reception team can't take a call right now. I can ask them to call you back {promise}. "
              "May I have your name, please?",
        "hi": "हमारी रिसेप्शन टीम अभी कॉल नहीं ले सकती। मैं उनसे आपको {promise} वापस कॉल करने को कह सकती हूँ। "
              "कृपया अपना नाम बताइए।",
        "hinglish": "Hamari reception team abhi call nahin le sakti. Main unhe aapko {promise} call back karne ko "
                    "bol sakti hoon. Please apna naam bataiye.",
    },
    "transfer_failed": {
        "en": "I'm sorry, I couldn't connect you just now. I can ask our team to call you back {promise}. "
              "May I have your name, please?",
        "hi": "माफ़ कीजिए, मैं अभी आपको जोड़ नहीं पाई। मैं हमारी टीम से आपको {promise} वापस कॉल करने को कह सकती "
              "हूँ। कृपया अपना नाम बताइए।",
        "hinglish": "Maaf kijiye, main abhi aapko connect nahin kar paayi. Main hamari team ko aapko {promise} "
                    "call back karne ko bol sakti hoon. Please apna naam bataiye.",
    },
    # Call opening (browser voice agent demo).
    "greeting": {
        "en": "Thank you for calling Smriti Raj Dentistry. This is the clinic's automated assistant.",
        "hi": "स्मृति राज डेंटिस्ट्री में कॉल करने के लिए धन्यवाद। मैं क्लिनिक की ऑटोमेटेड असिस्टेंट हूँ।",
        "hinglish": "Smriti Raj Dentistry mein call karne ke liye thank you. Main clinic ki automated assistant hoon.",
    },
    "closed_now": {
        "en": "The clinic is closed right now.",
        "hi": "क्लिनिक अभी बंद है।",
        "hinglish": "Clinic abhi band hai.",
    },
    "capabilities_transfer": {
        "en": "I can answer questions about the clinic, arrange a callback from our team, or try to connect you "
              "to reception.",
        "hi": "मैं क्लिनिक के बारे में सवालों के जवाब दे सकती हूँ, हमारी टीम से कॉलबैक करवा सकती हूँ, या आपको "
              "रिसेप्शन से जोड़ने की कोशिश कर सकती हूँ।",
        "hinglish": "Main clinic ke baare mein sawaalon ke jawab de sakti hoon, hamari team se callback karwa sakti "
                    "hoon, ya aapko reception se connect karne ki koshish kar sakti hoon.",
    },
    "capabilities_callback": {
        "en": "Reception can't take calls right now, but I can answer questions about the clinic or arrange a "
              "callback from our team.",
        "hi": "रिसेप्शन अभी कॉल नहीं ले सकता, लेकिन मैं क्लिनिक के बारे में सवालों के जवाब दे सकती हूँ या हमारी "
              "टीम से कॉलबैक करवा सकती हूँ।",
        "hinglish": "Reception abhi call nahin le sakta, lekin main clinic ke baare mein sawaalon ke jawab de sakti "
                    "hoon ya hamari team se callback karwa sakti hoon.",
    },
    "recording_notice": {
        "en": "Please note, the outcome of this call is logged for the clinic team, but no audio is recorded.",
        "hi": "कृपया ध्यान दें, इस कॉल का नतीजा क्लिनिक टीम के लिए दर्ज किया जाता है, लेकिन कोई ऑडियो रिकॉर्ड नहीं "
              "होता।",
        "hinglish": "Please dhyaan dein, is call ka result clinic team ke liye note kiya jaata hai, lekin koi audio "
                    "record nahin hota.",
    },
    "how_can_help": {
        "en": "How can I help you today?",
        "hi": "मैं आज आपकी क्या मदद कर सकती हूँ?",
        "hinglish": "Main aaj aapki kya madad kar sakti hoon?",
    },
    "anything_else": {
        "en": "Is there anything else I can help with?",
        "hi": "क्या मैं किसी और चीज़ में आपकी मदद कर सकती हूँ?",
        "hinglish": "Kya main kisi aur cheez mein aapki madad kar sakti hoon?",
    },
    "goodbye": {
        "en": "Thank you for calling Smriti Raj Dentistry. Goodbye.",
        "hi": "स्मृति राज डेंटिस्ट्री में कॉल करने के लिए धन्यवाद। नमस्ते।",
        "hinglish": "Smriti Raj Dentistry mein call karne ke liye thank you. Bye.",
    },
    "not_heard": {
        "en": "Sorry, I didn't catch that. Could you say it again, please?",
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाई। क्या आप दोबारा बता सकते हैं?",
        "hinglish": "Sorry, main samajh nahin paayi. Kya aap dobara bata sakte hain?",
    },
    "end_offer_callback": {
        "en": "Before you go, I can ask our team to call you back {promise}. Would you like that?",
        "hi": "जाने से पहले, मैं हमारी टीम से आपको {promise} वापस कॉल करने को कह सकती हूँ। क्या आप ऐसा चाहेंगे?",
        "hinglish": "Jaane se pehle, main hamari team ko aapko {promise} call back karne ko bol sakti hoon. "
                    "Kya aap aisa chahenge?",
    },
    "callback_request": {
        "en": "Of course. May I have your name, please?",
        "hi": "ज़रूर। कृपया अपना नाम बताइए।",
        "hinglish": "Zaroor. Please apna naam bataiye.",
    },
    "callback_declined": {
        "en": "No problem.",
        "hi": "कोई बात नहीं।",
        "hinglish": "Koi baat nahin.",
    },
    "ask_name_again": {
        "en": "Sorry, I didn't get your name. Could you say just your name, please?",
        "hi": "माफ़ कीजिए, मुझे आपका नाम समझ नहीं आया। कृपया सिर्फ़ अपना नाम बताइए।",
        "hinglish": "Sorry, mujhe aapka naam samajh nahin aaya. Please sirf apna naam bataiye.",
    },
    "ask_reason_appointment": {
        "en": "What would you like the appointment for?",
        "hi": "आप किस लिए अपॉइंटमेंट चाहते हैं?",
        "hinglish": "Aap kis cheez ke liye appointment chahte hain?",
    },
    "ask_reason": {
        "en": "Briefly, what would you like our team to call you about?",
        "hi": "संक्षेप में बताइए, हमारी टीम आपको किस बारे में कॉल करे?",
        "hinglish": "Short mein bataiye, hamari team aapko kis baare mein call kare?",
    },
    "confirm_intro_number": {
        "en": "Just to confirm, your name is {name}, and we should call you on {phone}.",
        "hi": "पुष्टि के लिए, आपका नाम {name} है, और हम आपको {phone} पर कॉल करें।",
        "hinglish": "Confirm karne ke liye, aapka naam {name} hai, aur hum aapko {phone} par call karein.",
    },
    "confirm_intro_caller_number": {
        "en": "Just to confirm, your name is {name}, and we should call you on the number you're calling from.",
        "hi": "पुष्टि के लिए, आपका नाम {name} है, और हम आपको उसी नंबर पर कॉल करें जिससे आप कॉल कर रहे हैं।",
        "hinglish": "Confirm karne ke liye, aapka naam {name} hai, aur hum aapko usi number par call karein jisse "
                    "aap call kar rahe hain.",
    },
    "confirm_reason": {
        "en": "The reason is: {reason}.",
        "hi": "कॉल का कारण: {reason}।",
        "hinglish": "Call ka reason: {reason}.",
    },
    "confirm_question": {
        "en": "Is that right?",
        "hi": "क्या यह सही है?",
        "hinglish": "Kya yeh sahi hai?",
    },
    "confirm_yes_no": {
        "en": "Please say yes if that's right, or no to change it.",
        "hi": "अगर यह सही है तो हाँ कहिए, या बदलने के लिए नहीं कहिए।",
        "hinglish": "Agar yeh sahi hai toh haan boliye, ya change karne ke liye nahin boliye.",
    },
    "details_retry": {
        "en": "Let's correct that. May I have your name, please?",
        "hi": "चलिए इसे ठीक करते हैं। कृपया अपना नाम बताइए।",
        "hinglish": "Chaliye ise theek karte hain. Please apna naam bataiye.",
    },
    "callback_already": {
        "en": "I've already passed a callback request to our team on this call, so they will call you {promise}.",
        "hi": "मैंने इस कॉल पर पहले ही हमारी टीम को कॉलबैक का अनुरोध भेज दिया है, इसलिए वे आपको {promise} कॉल करेंगे।",
        "hinglish": "Maine is call par pehle hi hamari team ko callback request bhej di hai, isliye woh aapko "
                    "{promise} call karenge.",
    },
    "callback_not_saved": {
        "en": "I'm sorry, I couldn't save that request just now. Please try again in a moment.",
        "hi": "माफ़ कीजिए, मैं अभी यह अनुरोध सेव नहीं कर पाई। कृपया थोड़ी देर में फिर कोशिश करें।",
        "hinglish": "Sorry, main abhi yeh request save nahin kar paayi. Please thodi der mein phir try kariye.",
    },
    # Phase 3.1: latency.
    "one_moment": {
        "en": "One moment, please.",
        "hi": "एक पल, कृपया।",
        "hinglish": "Ek pal, please.",
    },
    "low_confidence_retry": {
        "en": "I may not have caught that clearly. Please say that again, or type your message.",
        "hi": "शायद मैं ठीक से समझ नहीं पाई। कृपया फिर से बोलिए, या अपना संदेश टाइप कीजिए।",
        "hinglish": "Shayad main theek se samajh nahin paayi. Please phir se boliye, ya apna message type kijiye.",
    },
    # Phase 3: expanded answering and lead qualification.
    "services_all": {
        "en": "We offer {services}.",
        "hi": "हमारे यहाँ {services} की सुविधा है।",
        "hinglish": "Hamare clinic mein {services} ki suvidha hai.",
    },
    "offer_short": {
        "en": "Would you like a callback?",
        "hi": "क्या आप कॉलबैक चाहेंगे?",
        "hinglish": "Kya aap callback chahenge?",
    },
    "greeting_reply": {
        "en": "Hello! How can I help you today?",
        "hi": "नमस्ते! मैं आज आपकी क्या मदद कर सकती हूँ?",
        "hinglish": "Namaste! Main aaj aapki kya madad kar sakti hoon?",
    },
    "ask_reason_reschedule": {
        "en": "Which appointment would you like to move, and when would suit you instead?",
        "hi": "आप कौन सी अपॉइंटमेंट बदलना चाहते हैं, और आपके लिए कब ठीक रहेगा?",
        "hinglish": "Aap kaunsa appointment shift karna chahte hain, aur aapke liye kab theek rahega?",
    },
    "ask_reason_cancel": {
        "en": "Which appointment would you like to cancel? The date or the doctor's name is enough.",
        "hi": "आप कौन सी अपॉइंटमेंट कैंसल करना चाहते हैं? तारीख़ या डॉक्टर का नाम काफ़ी है।",
        "hinglish": "Aap kaunsa appointment cancel karna chahte hain? Date ya doctor ka naam kaafi hai.",
    },
    "ask_reason_status": {
        "en": "Which appointment are you asking about? The date or the doctor's name is enough.",
        "hi": "आप किस अपॉइंटमेंट के बारे में पूछ रहे हैं? तारीख़ या डॉक्टर का नाम काफ़ी है।",
        "hinglish": "Aap kis appointment ke baare mein pooch rahe hain? Date ya doctor ka naam kaafi hai.",
    },
    "ask_patient_type": {
        "en": "Have you visited Smriti Raj Dentistry before, or would this be your first visit?",
        "hi": "क्या आप पहले स्मृति राज डेंटिस्ट्री आ चुके हैं, या यह आपकी पहली विज़िट होगी?",
        "hinglish": "Kya aap pehle Smriti Raj Dentistry aa chuke hain, ya yeh aapki pehli visit hogi?",
    },
    "ask_doctor": {
        "en": "Do you have a preferred doctor? You can say Doctor Raj Tiwary, Doctor Smriti Raj, or no preference.",
        "hi": "क्या आप किसी खास डॉक्टर से मिलना चाहेंगे? आप डॉक्टर राज तिवारी, डॉक्टर स्मृति राज, या कोई भी कह सकते हैं।",
        "hinglish": "Kya aap kisi khaas doctor se milna chahenge? Aap Doctor Raj Tiwary, Doctor Smriti Raj, ya koi bhi "
                    "bol sakte hain.",
    },
    "ask_time": {
        "en": "Which day and time would suit you best?",
        "hi": "आपके लिए कौन सा दिन और समय सबसे अच्छा रहेगा?",
        "hinglish": "Aapke liye kaunsa din aur time sabse achha rahega?",
    },
    "confirm_preferences": {
        "en": "{patient_type}. Preferred doctor: {doctor}. Preferred time: {time}.",
        "hi": "{patient_type}। पसंदीदा डॉक्टर: {doctor}। पसंदीदा समय: {time}।",
        "hinglish": "{patient_type}. Preferred doctor: {doctor}. Preferred time: {time}.",
    },
    # Callback detail capture.
    "ask_name": {
        "en": "May I have your name, please?",
        "hi": "कृपया अपना नाम बताइए।",
        "hinglish": "Please apna naam bataiye.",
    },
    "ask_phone": {
        "en": "Which 10-digit mobile number should we call you on?",
        "hi": "हम आपको किस दस अंकों वाले मोबाइल नंबर पर कॉल करें?",
        "hinglish": "Hum aapko kis 10-digit mobile number par call karein?",
    },
    "ask_use_caller_number": {
        "en": "Should we call you back on the number you're calling from?",
        "hi": "क्या हम आपको उसी नंबर पर वापस कॉल करें जिससे आप अभी कॉल कर रहे हैं?",
        "hinglish": "Kya hum aapko usi number par call back karein jisse aap abhi call kar rahe hain?",
    },
    "invalid_phone": {
        "en": "Sorry, that doesn't sound like a 10-digit Indian mobile number. Could you say it again, please?",
        "hi": "माफ़ कीजिए, यह दस अंकों का भारतीय मोबाइल नंबर नहीं लग रहा। क्या आप इसे दोबारा बता सकते हैं?",
        "hinglish": "Sorry, yeh 10-digit Indian mobile number nahin lag raha. Kya aap ise dobara bata sakte hain?",
    },
    "confirm_details": {
        "en": "Just to confirm, your name is {name} and we should call you on {phone}. Is that right?",
        "hi": "पुष्टि के लिए, आपका नाम {name} है और हम आपको {phone} पर कॉल करें। क्या यह सही है?",
        "hinglish": "Confirm karne ke liye, aapka naam {name} hai aur hum aapko {phone} par call karein. "
                    "Kya yeh sahi hai?",
    },
    "confirm_details_caller_number": {
        "en": "Just to confirm, your name is {name} and we should call you on the number you're calling from. "
              "Is that right?",
        "hi": "पुष्टि के लिए, आपका नाम {name} है और हम आपको उसी नंबर पर कॉल करें जिससे आप कॉल कर रहे हैं। "
              "क्या यह सही है?",
        "hinglish": "Confirm karne ke liye, aapka naam {name} hai aur hum aapko usi number par call karein jisse "
                    "aap call kar rahe hain. Kya yeh sahi hai?",
    },
    "callback_created": {
        "en": "Thank you, {name}. Our team will call you back {promise}.",
        "hi": "धन्यवाद, {name}। हमारी टीम आपको {promise} वापस कॉल करेगी।",
        "hinglish": "Thank you, {name}. Hamari team aapko {promise} call back karegi.",
    },
    # Approved answers.
    "hours": {
        "en": "We're open Monday to Saturday, from 9 AM to 8 PM. The clinic is closed on Sunday.",
        "hi": "क्लिनिक सोमवार से शनिवार, सुबह 9 बजे से रात 8 बजे तक खुला रहता है। रविवार को क्लिनिक बंद रहता है।",
        "hinglish": "Clinic Monday se Saturday, subah 9 baje se raat 8 baje tak khula rehta hai. Sunday ko clinic "
                    "band rehta hai.",
    },
    "address": {
        "en": "We're at {address}, {landmark}.",
        "hi": "हमारा क्लिनिक {address} पर है, {landmark}।",
        "hinglish": "Hamara clinic {address} par hai, {landmark}.",
    },
    "contact": {
        "en": "Our reception number is plus 9 1, " + _PHONE_RECEPTION + ". You can also call plus 9 1, "
              + _PHONE_ALTERNATE + ", or email {email}.",
        "hi": "हमारा रिसेप्शन नंबर है प्लस 9 1, " + _PHONE_RECEPTION + "। आप प्लस 9 1, " + _PHONE_ALTERNATE
              + " पर भी कॉल कर सकते हैं, या {email} पर ईमेल कर सकते हैं।",
        "hinglish": "Hamara reception number hai plus 9 1, " + _PHONE_RECEPTION + ". Aap plus 9 1, "
                    + _PHONE_ALTERNATE + " par bhi call kar sakte hain, ya {email} par email kar sakte hain.",
    },
    "doctors": {
        "en": "Our doctors are Doctor Raj Tiwary, a periodontist and implantologist, and Doctor Smriti Raj, who "
              "specialises in pediatric dentistry and orthodontics. We also have specialist support for "
              "endodontics, oral surgery, prosthodontics and orthodontics.",
        "hi": "हमारे डॉक्टर हैं डॉक्टर राज तिवारी, जो पेरियोडॉन्टिस्ट और इम्प्लांटोलॉजिस्ट हैं, और डॉक्टर स्मृति राज, "
              "जो बच्चों की दंत चिकित्सा और ऑर्थोडॉन्टिक्स में विशेषज्ञ हैं। एंडोडॉन्टिक्स, ओरल सर्जरी, "
              "प्रोस्थोडॉन्टिक्स और ऑर्थोडॉन्टिक्स के लिए स्पेशलिस्ट सपोर्ट भी उपलब्ध है।",
        "hinglish": "Hamare doctors hain Doctor Raj Tiwary, jo periodontist aur implantologist hain, aur Doctor "
                    "Smriti Raj, jo pediatric dentistry aur orthodontics mein specialist hain. Endodontics, oral "
                    "surgery, prosthodontics aur orthodontics ke liye specialist support bhi hai.",
    },
    "consultation_fee": {
        "en": f"The initial consultation fee is {_FEE} rupees. Treatment costs are confirmed by the doctor after "
              "an assessment, so I can't quote them.",
        "hi": f"शुरुआती कंसल्टेशन फ़ीस {_FEE} रुपये है। इलाज का खर्च डॉक्टर जाँच के बाद ही बताते हैं, इसलिए मैं वह "
              "नहीं बता सकती।",
        "hinglish": f"Initial consultation fee {_FEE} rupees hai. Treatment ka kharcha doctor assessment ke baad "
                    "hi batate hain, isliye main woh nahin bata sakti.",
    },
    "payment": {
        "en": "You can pay by cash, UPI or card.",
        "hi": "आप कैश, यूपीआई या कार्ड से भुगतान कर सकते हैं।",
        "hinglish": "Aap cash, UPI ya card se payment kar sakte hain.",
    },
    "services": {
        "en": "Yes, we offer {services}.",
        "hi": "जी हाँ, हमारे यहाँ {services} की सुविधा है।",
        "hinglish": "Ji haan, hamare clinic mein {services} ki suvidha hai.",
    },
}

# The first sentence of an unknown-information reply, by topic. "unknown_offer" follows it.
UNKNOWN_LEADS = {
    "doctor_schedule": {
        "en": "I don't have the doctors' schedules, and I don't want to guess.",
        "hi": "मेरे पास डॉक्टरों का शेड्यूल नहीं है, और मैं अंदाज़ा नहीं लगाना चाहती।",
        "hinglish": "Mere paas doctors ka schedule nahin hai, aur main guess nahin karna chahti.",
    },
    "treatment_cost": {
        "en": f"I can't quote treatment prices; the doctor confirms them after an assessment. The initial "
              f"consultation fee is {_FEE} rupees.",
        "hi": f"मैं इलाज की कीमत नहीं बता सकती; डॉक्टर जाँच के बाद ही बताते हैं। शुरुआती कंसल्टेशन फ़ीस {_FEE} "
              "रुपये है।",
        "hinglish": f"Main treatment ki price nahin bata sakti; doctor assessment ke baad hi batate hain. "
                    f"Initial consultation fee {_FEE} rupees hai.",
    },
    "insurance": {
        "en": "I don't have information about insurance, and I don't want to guess.",
        "hi": "मेरे पास बीमा के बारे में जानकारी नहीं है, और मैं अंदाज़ा नहीं लगाना चाहती।",
        "hinglish": "Mere paas insurance ke baare mein jaankari nahin hai, aur main guess nahin karna chahti.",
    },
    "appointment_request": {
        "en": "I can't book appointments on this call.",
        "hi": "मैं इस कॉल पर अपॉइंटमेंट बुक नहीं कर सकती।",
        "hinglish": "Main is call par appointment book nahin kar sakti.",
    },
    "appointment_availability": {
        "en": "I can't see the appointment diary on this call, so I won't guess a time.",
        "hi": "मैं इस कॉल पर अपॉइंटमेंट डायरी नहीं देख सकती, इसलिए कोई समय अंदाज़े से नहीं बताऊँगी।",
        "hinglish": "Main is call par appointment diary nahin dekh sakti, isliye koi time guess nahin karungi.",
    },
    "treatment_suitability": {
        "en": "I can't say which treatment is right for you; only the doctor can decide that after an assessment.",
        "hi": "कौन सा इलाज आपके लिए सही है, यह मैं नहीं बता सकती; यह डॉक्टर जाँच के बाद ही तय कर सकते हैं।",
        "hinglish": "Kaunsa treatment aapke liye sahi hai, yeh main nahin bata sakti; yeh doctor assessment ke "
                    "baad hi decide kar sakte hain.",
    },
    "reschedule_request": {
        "en": "I can't change bookings on this call, but our team can call you to move your appointment.",
        "hi": "मैं इस कॉल पर बुकिंग नहीं बदल सकती, लेकिन हमारी टीम आपको अपॉइंटमेंट बदलने के लिए कॉल कर सकती है।",
        "hinglish": "Main is call par booking change nahin kar sakti, lekin hamari team aapko appointment shift karne ke "
                    "liye call kar sakti hai.",
    },
    "cancellation_request": {
        "en": "I can't cancel bookings on this call, but I can pass your cancellation request to our team.",
        "hi": "मैं इस कॉल पर बुकिंग कैंसल नहीं कर सकती, लेकिन आपका कैंसलेशन का अनुरोध हमारी टीम तक पहुँचा सकती हूँ।",
        "hinglish": "Main is call par booking cancel nahin kar sakti, lekin aapki cancellation request hamari team tak "
                    "pahuncha sakti hoon.",
    },
    "booking_status": {
        "en": "I can't check bookings on this call, so I won't guess. Our team can confirm your appointment status.",
        "hi": "मैं इस कॉल पर बुकिंग नहीं देख सकती, इसलिए अंदाज़ा नहीं लगाऊँगी। हमारी टीम आपकी अपॉइंटमेंट की स्थिति बता "
              "सकती है।",
        "hinglish": "Main is call par booking check nahin kar sakti, isliye guess nahin karungi. Hamari team aapke "
                    "appointment ka status confirm kar sakti hai.",
    },
    "missed_call": {
        "en": "I can't see the clinic's call list, but our team can call you back.",
        "hi": "मैं क्लिनिक की कॉल लिस्ट नहीं देख सकती, लेकिन हमारी टीम आपको वापस कॉल कर सकती है।",
        "hinglish": "Main clinic ki call list nahin dekh sakti, lekin hamari team aapko call back kar sakti hai.",
    },
    "website_enquiry": {
        "en": "I can't see website or contact-form messages, but our team can follow up with you.",
        "hi": "मैं वेबसाइट या कॉन्टैक्ट फ़ॉर्म के संदेश नहीं देख सकती, लेकिन हमारी टीम आपसे संपर्क कर सकती है।",
        "hinglish": "Main website ya contact form ke messages nahin dekh sakti, lekin hamari team aapse contact kar "
                    "sakti hai.",
    },
    "complaint": {
        "en": "I'm sorry to hear that. I'll make sure a team member gets back to you about it.",
        "hi": "यह सुनकर मुझे खेद है। मैं ध्यान रखूँगी कि हमारी टीम का कोई सदस्य इस बारे में आपसे संपर्क करे।",
        "hinglish": "Yeh sunkar mujhe afsos hai. Main dhyaan rakhungi ki hamari team ka koi member is baare mein aapse "
                    "contact kare.",
    },
    "patient_records": {
        "en": "I can't access patient records on this call, but our team can help with that.",
        "hi": "मैं इस कॉल पर मरीज़ों के रिकॉर्ड नहीं देख सकती, लेकिन हमारी टीम इसमें मदद कर सकती है।",
        "hinglish": "Main is call par patient records nahin dekh sakti, lekin hamari team isme madad kar sakti hai.",
    },
    "default": {
        "en": "I'm sorry, I don't have that information, and I don't want to guess.",
        "hi": "माफ़ कीजिए, मेरे पास यह जानकारी नहीं है, और मैं अंदाज़ा नहीं लगाना चाहती।",
        "hinglish": "Maaf kijiye, mere paas yeh jaankari nahin hai, aur main guess nahin karna chahti.",
    },
}

# Appointment topics end with this offer instead of "unknown_offer".
APPOINTMENT_OFFER = {
    "en": "Our team can call you back to arrange a time. Would you like that?",
    "hi": "हमारी टीम आपको समय तय करने के लिए वापस कॉल कर सकती है। क्या आप ऐसा चाहेंगे?",
    "hinglish": "Hamari team aapko time fix karne ke liye call back kar sakti hai. Kya aap aisa chahenge?",
}

# How a callback appears in the reception queue (staff-facing, English).
STAFF_CATEGORY_LABELS = {
    "appointment": "Appointment request",
    "enquiry": "Enquiry",
    "panel": "Panel enquiry (CGHS, ECHS, CISF, DU, Air India)",
    "human_request": "Asked to speak to reception",
    "urgent": "URGENT: caller told to call 112",
    "other": "Callback request",
}
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}

# The intent a callback was taken for, as the reception queue shows it (staff-facing, English).
# Falls back to STAFF_CATEGORY_LABELS for anything not listed.
STAFF_INTENT_LABELS = {
    "appointment_request": "Appointment request",
    "appointment_availability": "Appointment request",
    "doctor_schedule": "Appointment request (asked about doctor schedule)",
    "how_to_book": "Appointment request",
    "tooth_pain": "Appointment request (tooth pain or sensitivity)",
    "reschedule_request": "Reschedule request",
    "cancellation_request": "Cancellation request",
    "booking_status": "Booking status enquiry (not verified on the call)",
    "missed_call": "Missed-call callback",
    "website_enquiry": "Website or contact-form enquiry",
    "complaint": "Complaint: needs staff follow-up",
    "patient_records": "Patient records request",
    "treatment_cost": "Treatment price enquiry",
    "clinical_question": "Clinical question: for the doctor (no advice given)",
}

# Lead details, as read back to the caller and written to staff notes.
PATIENT_TYPES = {
    "new": {"en": "New patient", "hi": "नए मरीज़", "hinglish": "Naye patient", "staff": "New patient"},
    "existing": {"en": "Existing patient", "hi": "पहले आ चुके मरीज़", "hinglish": "Pehle aa chuke patient",
                 "staff": "Existing patient"},
    "unknown": {"en": "Visit history not given", "hi": "पिछली विज़िट की जानकारी नहीं दी", "hinglish": "Pichhli visit ki "
                "jaankari nahin di", "staff": "New or existing: not given"},
}
DOCTOR_CHOICES = {
    "raj_tiwary": {"en": "Doctor Raj Tiwary", "hi": "डॉक्टर राज तिवारी", "hinglish": "Doctor Raj Tiwary",
                   "staff": "Dr. Raj Tiwary"},
    "smriti_raj": {"en": "Doctor Smriti Raj", "hi": "डॉक्टर स्मृति राज", "hinglish": "Doctor Smriti Raj",
                   "staff": "Dr. Smriti Raj"},
    "no_preference": {"en": "No preference", "hi": "कोई भी", "hinglish": "Koi bhi", "staff": "No preference"},
}

# One-click caller phrases for the browser voice agent demo. They go through the same policy as
# anything typed or spoken; `language` switches the call language first.
DEMO_SCENARIOS = (
    {"id": "book", "label": "Book a consultation", "language": None, "text": "I want to book a consultation."},
    {"id": "hours", "label": "Ask clinic hours", "language": None, "text": "What are your opening hours?"},
    {"id": "sunday", "label": "Ask Sunday availability", "language": None, "text": "Are you open on Sunday?"},
    {"id": "human", "label": "Ask for a human", "language": None, "text": "Can I speak to someone at reception?"},
    {"id": "panel", "label": "Ask about CGHS/panel", "language": None,
     "text": "Do you accept CGHS? What documents do I need?"},
    {"id": "clinical", "label": "Clinical question — safe callback", "language": None,
     "text": "I have tooth pain. Which painkiller should I take?"},
    {"id": "urgent", "label": "Urgent symptom", "language": None,
     "text": "My face is swollen and the swelling is spreading to my eye."},
    {"id": "hindi", "label": "Hindi example", "language": "hi", "text": "रविवार को क्लिनिक खुला है क्या?"},
    {"id": "hinglish", "label": "Hinglish example", "language": "hinglish", "text": "Sunday ko clinic khula hai kya?"},
)


def line(key: str, language: str, **params) -> str:
    return LINES[key][language].format(**params)


def facts(language: str) -> dict:
    return FACTS[language]


def join(items: list[str], language: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {AND[language]} " + items[-1]
