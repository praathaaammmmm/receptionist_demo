# Smriti Raj Dentistry — AI Dental Front Desk Demo

## Phase 1: Booking Foundation · Phase 2: Appointment Assistant and Callback Tasks · Phase 3: Voice-Call Simulation · Phase 5: Doctor Consultation Workspace · Phase 6: Doctor Schedule Calendar · Phase 7: Patient Timeline · Phase 8: QR Appointment Check-in · Phase 9: Waitlist and Cancellation Fill · Phase 10: Notification Centre · Phase 11: Admin Analytics · Phase 12: Procedure Follow-up Scheduler · Phase 13: Navigation, Button and Settings UX · Doctor Workspace upgrade · Voice Agent Phase 1: Knowledge and Safety Policy · Voice Agent Phase 2: Browser Voice Agent Demo · Voice Agent Phase 3: Microphone Transcription and Controlled AI Answering · Voice Agent Phase 3.1: Latency and Speech Quality

A single-clinic appointment system for the Smriti Raj Dentistry reception desk: register and search patients, view doctor
availability, create bookings, and manage them from a dashboard.

> **Demo only.** All seeded records are sample data and are labelled "Demo" in the UI.
> Do not enter real patient information. This is not a production medical system and gives no
> clinical advice. There is no voice, WhatsApp or AI model call. The patient assistant is a
> deterministic guided flow, not a live AI.

## Setup and run

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000> for the reception dashboard and <http://127.0.0.1:8000/assistant> for
the public patient assistant. If port 8000 is busy, add `--port 8010` and open that port instead.

The voice-call simulation is at <http://127.0.0.1:8000/call-demo>.

Upgrading an existing database needs no manual step: the new `callback_tasks` and `call_logs`
tables are created on the next start.

The first start creates `data/clinic_demo.db` (SQLite) and seeds the clinic, 3 doctors, 4 services,
a few sample patients/bookings and consultation slots for the next 7 days. The slot window rolls
forward automatically each day.

**Reset the demo** (developer-only; *demo data only — never run against real patient data*):

```bash
.venv/bin/python scripts/reset_demo.py --yes
```

This deletes every patient, booking, callback task and call log, then restores the seeded clinic,
doctors, services, sample bookings and slots. It works while the app is running, undoes Settings
edits, refuses to run against a non-SQLite database, and is not available from any page or API.

**Presenting the demo:** see [docs/demo-runbook.md](docs/demo-runbook.md) for the five-minute
script, expected outcomes, audio fallback and owner checklist.

## Tests

```bash
.venv/bin/python -m pytest
```

Each test runs against its own temporary database. Phase 2 (`tests/test_assistant.py`) covers: an
assistant booking saved as `AI_DEMO` and visible on the dashboard, exactly three slots offered, the
slot-conflict message with fresh options, callbacks created for "speak to a person", CGHS/ECHS,
clinical and unsupported questions, callback status transitions, completing a task from the
dashboard, and the rate limit. Phase 1 covered: creating a patient, duplicate mobile
rejection, creating an appointment, rejecting a duplicate doctor/time booking (service check and
database index), cancelling an appointment and freeing its slot, status rules, doctor-hours edits,
and a render check of every screen. Phase 13 (`tests/test_ux.py`) pins the grouped menu and its
active states, the Demo tags, dashboard quick actions, More menus and confirmations, breadcrumbs,
the Settings sections and placeholders, and that a Settings availability change reaches the
calendar. `tests/test_doctor_workspace.py` covers the doctor's day counts and filters, the next-patient
choice and masking, flags, the consultation lifecycle, ownership, previous/next navigation, the
follow-up handoff and its privacy, the separate procedure path, operational-only patient context, and
calendar/timeline links. `tests/test_patient_care.py` covers flags and their timeline entries,
private-note isolation across reception pages and APIs, safe callbacks, follow-up requests with
preferences, closing and reopening them, reception scheduling, and that doctors cannot edit identity
fields, delete records or act on another doctor's patients.

## Patient assistant (Phase 2)

`/assistant` is a public, mobile-first page where a patient can ask approved clinic questions, see
three available consultation times, make a booking request, or ask for a call from the front desk.

- **How it works:** `app/services/assistant.py` classifies each message with fixed rules and acts
  only through the existing patient, availability, appointment and callback services. No AI model
  is called and no API key is needed. `ASSISTANT_MODE = "guided"` in `app/knowledge.py` records this.
- **Approved knowledge:** `app/knowledge.py` holds the only answers the assistant may give (hours,
  booking guidance, service wording, CGHS/ECHS wording, safety copy). Address, phone, doctors,
  services and demo fees are read from the database, so edits on the Settings page flow through.
- **Never answered:** symptoms, medicines, suitability, outcomes, treatment costs and scheme
  eligibility. These, and anything unrecognised, become a callback task once the patient gives a
  name and mobile number. The assistant says "Our staff will contact you during clinic hours." and
  nothing more; no call is placed by the system.
- **Bookings:** saved as `PENDING` with source `AI_DEMO`, through the same service as staff
  bookings. If the mobile number already belongs to a patient the booking is attached to that
  record; the assistant never shows stored patient details back to the visitor.
- **Callback tasks:** stored in `callback_tasks` (`OPEN → IN_PROGRESS → COMPLETED`, completed is
  final). The dashboard shows counts and a "Callback tasks" section where staff add a note and
  move tasks forward.
- **Protection:** `/api/assistant/message` is rate-limited per client address (40 messages a minute,
  set in `app/config.py`), message length is capped, and the conversation state sent by the browser
  is re-validated on every turn.

**Not production-ready:** the reception screens and the staff JSON API (`/api/patients`,
`/api/appointments`, `/api/callbacks`, ...) have no login. Before the assistant page is exposed on
the public internet, put the staff routes behind authentication or a private network. The rate
limiter is in-memory and per-process, and sees one address if the app sits behind a proxy.

## Voice-call simulation (Phase 3)

`/call-demo` is a call-screen page for presenting how an after-hours phone call could be handled.
**It is a local browser simulation, not telephony.** It does not receive or place real calls, has
no phone number or telephony account, does not use the microphone, records no audio and calls no
AI provider. The "after hours" status is part of the simulation, not a reading of the clock.

- **Same engine as the website assistant:** each caller turn goes to
  `POST /api/call-demo/{id}/message`, which calls `app/services/assistant.py` unchanged. Approved
  answers, the three-slot offer, bookings, closed-day handling and callback tasks behave identically.
- **Driving the demo:** press *Start demo call*, then type what the caller says or use the five
  caller-phrase buttons (booking, opening hours, speak to a person, tooth pain and medicine, Sunday).
  A phrase button starts a call if none is active. *Reset demo call* ends the current call and
  clears the screen.
- **Languages: English, हिंदी, Hinglish.** Choose the call language before starting; the choice is
  remembered in this browser (local storage). During a call, *Change language* switches it and the
  next assistant reply uses the new language. The language is shown in the call screen and
  transcript and stored on the call log (`call_logs.language`, the latest one chosen). Only the
  wording changes: booking, callback, waitlist, availability, Sunday-closure and safety rules are
  identical in every language. The approved English, Hindi (Devanagari) and Hinglish (Roman Hindi)
  wording lives in `app/knowledge_translations.py`; dates, times, numbers, references, doctor and
  service names are inserted unchanged (Hindi only writes weekday and month names in Hindi). Caller
  phrases are shown in the chosen language and send the same English phrase. The website assistant
  stays in English. Hinglish is displayed in Roman Hindi and voiced by the Hindi local model: every
  Hinglish message has a second, reviewed Devanagari version (`hinglish_speech`) stored next to it,
  which is what is read aloud (no run-time transliteration). Each reply message carries `text` for
  the transcript and `speech_text` for the voice. Seeded clinic, doctor and service names have
  approved Devanagari pronunciations (`SPEECH_NAMES`); digits, times and references stay digits.
  **All Hindi and Hinglish wording, including the speech text, is a demo draft and needs review by
  the clinic before any production use.**
- **Local voices (recommended for presenting):** replies are spoken by downloaded
  [Piper](https://github.com/OHF-Voice/piper1-gpl) voice packs, generated on this computer and
  played as ordinary audio, so they work the same in every browser, Firefox included:

  | Language | Voice pack | Speaker |
  | --- | --- | --- |
  | English | `en_GB-cori-medium` | single speaker (British English) |
  | हिंदी | `hi_IN-priyamvada-medium` | single speaker |
  | Hinglish | `hi_IN-priyamvada-medium` | single speaker (reads the Devanagari speech text) |

  One-time setup (packs already in `./voices` are kept, not downloaded again; `./voices` is ignored by Git):

  ```bash
  .venv/bin/pip install -r requirements-voice.txt
  .venv/bin/python scripts/download_voice.py --all-demo-languages   # about 60-80 MB per pack
  ```

  Restart the app afterwards. Each pack loads on first use only. Change them with
  `CALL_DEMO_VOICE_ENGLISH`, `CALL_DEMO_VOICE_ENGLISH_SPEAKER` (for example `en_US-l2arctic-medium` with speaker `SVBI` for an Indian accent) and
  `CALL_DEMO_VOICE_HINDI`; `python scripts/voice_samples.py` writes labelled samples to
  `voices/samples/`. The audio panel shows the active voice ("Local English voice", "Local Hindi
  voice", "Hinglish conversation · Hindi local voice") with *Test English voice*, *Test Hindi voice*
  and *Test Hinglish voice*. If a language's
  pack is missing, the page says "This local voice pack is not installed. The conversation remains
  available as text." and that language runs as text only; Hindi is never read by an English voice.
- **Browser voice (fallback, English only):** only when the local English pack is
  missing, replies are read aloud by the browser's own speech synthesis, after the first click
  (never autoplay). *Test English voice* says "Hello. This is the Smriti Raj Dentistry appointment
  assistant." and the audio status shows "Voice ready", "Muted", "Browser voice unavailable" or
  "Audio requires a click to start". An English (India) voice is used when the browser has one.
  *Mute voice* turns speech off. The transcript works whether or not speech does.
- **Text simulation mode:** without the English voice pack, Firefox runs the call demo without speech,
  because browser speech there (especially on Linux) is unreliable. The audio status reads "Text simulation mode —
  the conversation transcript remains fully functional." and the speaker test and mute control are
  shown but inactive, with the reason on hover. Other browsers switch to the same mode if they
  have no speech voice, or for the rest of a call if speech fails to start once; a new call tries
  again. Nothing else about the call changes.
- **If you hear nothing:** the browser needs at least one speech voice. Chrome, Edge and Safari on
  Windows and macOS include them. On Linux, Firefox and Chromium-based browsers (including Brave)
  rely on the system `speech-dispatcher` service with a voice such as `espeak-ng`; without it the
  page shows "Browser voice unavailable". Chromium-based browsers on Linux may also need to be
  started with `--enable-speech-dispatcher`.
- **Call log:** every simulated call is stored in `call_logs` with channel `VOICE_DEMO`, caller
  name and mobile when given, start and end time, an outcome (`BOOKING_CREATED`, `CALLBACK_CREATED`,
  `FAQ_ANSWERED` or `ENDED`, in that order of precedence) and a link to the booking or callback
  task it produced. The dashboard lists the most recent calls under "AI call activity", each
  tagged "Demo call".
- **Bookings and callbacks made on a call** are ordinary records: bookings keep source `AI_DEMO`,
  and the call log is what marks them as having come through the voice demo.
- **Back to dashboard:** the call demo and the website assistant both have *Back to dashboard* in
  the header. With no conversation in progress it goes straight to `/`. During a live call, or a
  chat with messages that has not ended in a booking, callback or waitlist request, it asks "Leave
  this conversation? Your active demo conversation will end." *Stay here* cancels; *Leave dashboard*
  ends the call through the normal end flow (so its outcome is recorded) and opens the dashboard.
  Opening the page without starting a call creates no call log. After a booking, callback or ended
  call the transcript also offers *Back to dashboard* and *Start another demo call* (*Start another
  conversation* on the assistant).

## Doctor consultation workspace (Phase 5)

`/doctor` shows what happens after a booking, with clinical decisions kept in the doctor's hands.
**Demo only: this is not a medical record, a diagnosis tool or a prescription system.**

- **Doctor switcher:** there is no login in the demo; a doctor is chosen from the three seeded
  ones. Every action is checked against that doctor's own list, so one doctor's screen cannot
  change another doctor's appointment.
- **Today's list:** the doctor's confirmed, arrived, completed and no-show appointments for today,
  with patient, mobile, service, booking source, time and status. Unconfirmed bookings stay with
  reception and appear only as a count.
- **Status workflow:** `CONFIRMED → ARRIVED → COMPLETED`, and `CONFIRMED` or `ARRIVED → NO_SHOW`.
  These are validated on the server in the same transition table as before; `PENDING → CONFIRMED`
  and cancelling a pending or confirmed booking are unchanged. Completed, no-show and cancelled are
  final. The workspace can set only arrived, completed and no-show; confirming and cancelling stay
  at reception.
- **Doctor-entered consultation outcome:** a short summary, a next step (no follow-up, follow-up
  consultation, procedure discussion) and an optional note, once the patient has arrived.
- **Draft treatment recommendation:** after completion, the doctor can pick one of four demo
  procedures (`DEMO_PROCEDURES` in `app/config.py`) and add a note. It is saved as `DRAFT`. There
  is no approval step, and no route outside the doctor workspace can create or change one.
- **What reception sees:** the new statuses, plus read-only "Next step" and "Doctor
  recommendation" markers on the dashboard and patient list. The doctor's summary and notes are
  not shown to reception, and the assistant has no access to any of it.

**Workspace upgrade (daily clinical view).**

- **Day summary:** counts for Upcoming, Arrived / waiting, In consultation, Completed and No-show
  (each opens that filter), a **Next patient** card and a **Today's schedule** timeline.
  - The card shows whoever is in consultation, otherwise the first patient waiting, otherwise the
    next one expected.
  - It shows time, service, mobile (masked to the last four digits), booking source, arrival or QR
    check-in, and the right primary action.
  - It also shows operational flags only: open callback, follow-up visit, follow-up due, from
    waitlist, previous no-show.
  - Age is not shown because the demo records no date of birth.
- **Queue:** filters for All today, Upcoming, Waiting / arrived, In consultation, Completed and
  No-show (`/doctor?doctor_id=…&show=waiting`). Each row has an arrival indicator, source badge, one
  quick action, **Open consultation**, and a More menu with View in calendar and No-show.
- **Lifecycle:** `Confirmed → Arrived → In consultation → Completed`.
  - **Start consultation** (`POST /doctor/{doctor_id}/appointments/{id}/start`) works only for this
    doctor's own arrived patients.
  - It records a `ConsultationStart` row and a "Consultation started" timeline entry. The
    appointment status itself stays `ARRIVED`, so reception, check-in, analytics and the transition
    rules are unchanged.
  - Outcomes can be saved once arrived, during consultation and after completion.
  - Completing without a saved outcome asks a distinct, explicit confirmation.
- **Consultation view:**
  - Header with stage, time, service, source and arrival.
  - Back to today's schedule, previous/next patient, patient timeline and View in calendar.
  - A stage stepper, plus sections for Consultation, Treatment / recommendation and Patient context.
  - Patient context is operational only: other visits with status and date, no-show and
    cancellation counts, callback counts, waitlist origin, earlier recommendation names and states,
    and arrival. It never shows another visit's summary or notes.
- **Follow-up handoff:**
  - A visible "Not sent → Ready for reception → Scheduled" stepper.
  - Saving an outcome still sends nothing; the doctor sends the follow-up explicitly once the
    consultation is completed.
  - Procedure recommendations show "Draft → Ready for reception → Scheduled" and stay a separate path.
- **Calendar:** `/doctor/calendar?doctor_id=…&appointment_id=…` opens the week holding that
  appointment and highlights it; every calendar booking opens its consultation directly.

**Doctor patient controls (Patient overview).** Each consultation has a Patient overview panel. Every
action goes through one of the doctor's own appointments; another doctor gets 403.

- **Patient information:** name, mobile, email, registration date, this booking's source and
  waitlist origin. These are read-only; reception keeps contact and registration details.
- **Visits with this doctor:** completed, cancelled and no-show counts, the next booked appointment
  with them, recent visits, and a link to the full timeline.
- **Operational flags** (per doctor and patient): "Needs follow-up", "Priority review" and "Do not
  schedule without doctor review", set and cleared with checkboxes.
  - Each change is a "Doctor flag set/cleared" timeline event carrying the flag name and doctor only.
  - Reception sees each active flag with a fixed plain meaning on the dashboard, patient page and
    Follow-ups. There is no free text, so no reasoning can be attached.
  - The flags are advisory: booking is not blocked automatically.
- **Private doctor notes:** one note per doctor and patient, with author and last-updated time,
  shown only in that doctor's own workspace and labelled "Private doctor notes — not visible to
  reception or patient." No reception page, timeline, API, notification, call screen or assistant
  reads the `doctor_patient_notes` table.
- **Care actions:**
  - **Callback request for reception:** only fixed reasons are allowed ("Please call to arrange
    follow-up", "Please confirm appointment", "Please ask patient to contact clinic"), and no
    acknowledgement is queued to the patient.
  - **Follow-up request:** once the patient has arrived, with no outcome or procedure needed, and an
    optional preferred length (15/30/45 min) and timeframe (1 week, 2 weeks, 1 month or a date).
  - **Mark a waiting request as no longer needed:** this sets it to Closed, and it can be reopened later.
  - The doctor sees each request as Waiting, Scheduled (with the booked time) or Closed.
- **Scheduling:** reception books follow-ups through the existing Follow-ups flow. The preference is
  shown there, but slots keep the doctor's standard length, and nothing is booked automatically.

## Doctor schedule calendar (Phase 6)

The doctor calendar lives at `/doctor/calendar`: seven days for the selected doctor, starting
today, with previous/next week links. It is reached from the **Doctor calendar** item in the main
menu or the **Weekly schedule** tab inside the doctor workspace; both open the same page. (The
earlier address `/doctor?view=schedule` redirects to it.)

- **What it shows:** each day's consulting hours, free consultation slots, every appointment
  coloured by status (pending, confirmed, arrived, completed, no-show, cancelled), the clinic-closed
  Sunday, days the doctor does not consult, and blocked periods. It reads the same slots and
  appointments as the booking engine, so a booking made by reception, the assistant or the call
  demo appears on the next page load and its slot stops showing as free.
- **Weeks:** week 0 is today plus six days, which is exactly the bookable window. Later weeks show
  working hours and "Slots open 7 days ahead"; earlier weeks show what happened.
- **Blocked time:** the doctor can block a future day, or part of one, as Leave, Personal, Training
  or Other. Blocked slots are reported as `BLOCKED` (never available) to the staff booking and
  availability screens, the assistant and the call demo, and booking one is refused on the server.
- **Appointments come first:** time with a pending, confirmed or arrived appointment cannot be
  blocked ("This time cannot be blocked because it has a scheduled patient appointment."). Nothing
  is ever moved or cancelled automatically.
- **Removing a block:** allowed for future blocks on the doctor's own schedule; the slots become
  bookable again at once.
- **Sunday:** stays closed clinic-wide. It cannot be blocked or unblocked from a doctor's schedule.
- **Not included:** external calendar sync, rooms/chairs/equipment, drag-and-drop or automatic
  rescheduling, recurring leave, and doctor login (the demo-only switcher is still used).

## Patient timeline (Phase 7)

Each patient has a detail page at `/patients/{id}` with a **Details** section and a read-only
**Timeline** section, newest first (`/patients/{id}/timeline` shows the same page). Ways in:

- **Patients page:** a **View timeline** action on every patient, and the patient's name.
- **Dashboard:** the **Recent patient activity** panel (the six latest events across all patients,
  each linking to that patient's timeline), plus patient names on bookings, pending cards and
  callback tasks.

- **Each event shows:** an icon, who recorded it, the time, the resulting status where there is
  one, and a link to the related booking, callback task or call activity.
- **Events:** patient registered; appointment booked, confirmed, arrived, completed, cancelled, no-show; callback
  requested, started, completed; simulated AI call; consultation outcome recorded; doctor
  recommendation drafted. Each has a timestamp and a source: **Staff**, **Website AI**,
  **Voice Demo** or **Doctor** (sample web-form bookings show as **Website**).
- **Built from existing records:** nothing is copied. Bookings, callbacks, calls, outcomes and
  recommendations are read where they already live; callback tasks and calls are matched to the
  patient by mobile number. The only new storage is `timeline_events`, a small log of *when* a
  status changed and who changed it, because no other table kept that.
- **Reception-safe:** doctor entries show only the next step and the recommended procedure. The
  timeline code never reads the doctor's consultation summary or notes, so they cannot appear.
- **Links:** each event links to the booking, callback task or AI call activity on the dashboard
  when it is listed there.
- **Older data:** a status changed before this phase has no recorded time; it is shown as "Time
  not recorded" rather than given an invented one.
- **Not recorded:** website-assistant chats that only answered a question (no name or number is
  collected), and who at reception made a change (there is no staff login).
- **Extending it:** a QR check-in or a notification can be added later by writing one
  `timeline_events` row with a new `kind` and adding its title in `app/services/timeline.py`.

## QR appointment check-in (Phase 8)

A confirmed booking can be given a demo check-in QR. At arrival, reception scans or types the code
on the **QR check-in** screen and confirms the arrival, which marks the booking `ARRIVED`.

- **Generating:** *Generate check-in QR* appears on confirmed bookings from today onwards, on the
  dashboard and on the patient detail page. It opens a printable card labelled "Demo appointment
  check-in QR" with *Print card* and *Download QR* (SVG). One booking has one code.
- **What the QR contains:** only a 32-character random token. No name, number, doctor, date or
  booking reference is encoded; everything is looked up on the server. The printed card shows the
  clinic name, the code and the valid date, and no patient details.
- **Checking in (`/check-in`):** paste or type the code (always available) or use *Scan with
  camera* where the browser can decode QR codes itself. A valid code shows the booking on this
  staff screen; reception presses *Mark patient arrived*. There is no patient self-check-in.
- **Rules, enforced on the server:** only `CONFIRMED → ARRIVED`; only on the appointment's own
  date; within the check-in window (`CHECKIN_OPENS_MINUTES_BEFORE` / `CHECKIN_CLOSES_MINUTES_AFTER`
  in `app/config.py` — the demo opens at the start of the day so it can be shown at any hour, and
  closes 60 minutes after the start time). A second scan says "Patient already checked in" and
  changes nothing.
- **Refusals reveal nothing:** an unknown, cancelled, finished, wrong-day or expired code shows a
  short message only, never whose booking it was. The code travels in a form post, not in a URL.
- **What updates:** the dashboard and doctor workspace show `ARRIVED` at once, and the patient
  timeline gains "QR check-in at reception" and "Patient arrived". The check-in is one structured
  `timeline_events` row (`QR_CHECKIN`, with time, patient and appointment), ready for later analytics.
- **Not included:** sending the QR by WhatsApp or email, patient self-check-in, payments, offers
  or treatment approval by QR, and staff login.

## Waitlist and cancellation fill (Phase 9)

`/waitlist` (menu item **Waitlist**) lets reception keep a list of patients who want a consultation
time that is not available, and fill cancelled slots from it. **Nothing is automatic:** the system
never contacts a patient, reserves a slot or books by itself.

- **Adding someone:** an existing patient or a new one (name and mobile), the requested service,
  an optional preferred doctor, a date range, morning / afternoon / any time, how they prefer to be
  contacted, and an optional staff note. Entries start as `WAITING`.
- **From the assistant:** when no time suits, the website assistant and call demo offer **Join
  waitlist**. It records the request and says staff will be in touch; nothing is booked.
- **Newly available slots:** when a booking is cancelled and its slot is still free and in the
  future, it is listed with the waiting patients it suits: the preferred doctor (or any), the date
  range and the time of day. The requested service is shown but not used to filter. This list is
  worked out from cancelled bookings on the fly; a slot leaves it as soon as it is booked or blocked.
- **Offer, then book:** *Mark offered* records that reception has told the patient about the slot
  (`OFFERED`). It reserves nothing, so the same slot can be offered to two people. *Book this slot*
  needs the "Patient has accepted this time" box ticked, then creates a normal `PENDING` booking
  through the usual booking rules and marks the entry `BOOKED`. If someone else took the slot
  first, the usual "This slot has just been booked" refusal appears and the entry stays offered.
- **Other actions:** *Offer declined* returns an entry to `WAITING`; *Close* ends it.
- **Dashboard and timeline:** the dashboard has a Waitlist panel with waiting, offered and newly
  available counts. The patient timeline shows "Joined the waitlist", "Waitlist slot offered" and
  "Booked from the waitlist".
- **Not included:** any outreach (no WhatsApp, SMS or email is sent; the contact preference is a
  note for reception), automatic rebooking, holding a slot for a patient, and priority ordering
  beyond oldest-first.

## Notification centre (Phase 10)

`/notifications` (menu item **Notifications**) is an outbox showing the messages a clinic would
send. **Demo notification simulation — no messages are sent.** There is no WhatsApp, email or SMS
client in this app, no provider key and no webhook; the code makes no network call. A test blocks
every network route and runs the whole flow to prove it.

- **What creates an entry** (one per event, always `QUEUED`):
  confirming a booking → appointment confirmation; cancelling → cancellation update; a confirmed
  booking starting within 24 hours → reminder; marking a waitlist patient as offered → slot offer;
  a new callback task → callback acknowledgement.
- **Reminders have no scheduler:** due reminders are queued when staff open the dashboard or the
  notification centre.
- **Channel:** WhatsApp by default; Email when a waitlist patient prefers email and has an address.
- **Each entry shows:** patient (linked to their timeline), channel, type, status, created time,
  the related booking, callback or waitlist entry, and a message preview. Contact details are
  masked in the list. Search by patient, type or message; filter by status, channel and type.
- **Staff actions (simulated):** *Send* (`QUEUED → SENT`), *Mark delivered* (`SENT → DELIVERED`),
  *Mark failed* (from queued or sent), *Retry* (`FAILED → QUEUED`, and the entry's attempt number
  goes up). Delivered is final.
- **Templates:** edit the wording in `app/notification_templates.py`. They contain no prices and no
  clinical advice; keep it that way.
- **Dashboard and timeline:** the dashboard has a Notifications panel with queued, sent, delivered
  and failed counts. The patient timeline shows each notification's type, channel and status
  (queued, sent, delivered, failed, retried), never the message text or staff notes.

## Admin analytics (Phase 11)

`/analytics` (menu item **Analytics**) gives the clinic owner an aggregated view of the sample
data, with filters for **Today**, **This week** (Monday to Sunday) and **All demo data**. Every
section is labelled as demo/sample data, and the page explains how each figure is calculated.

- **Appointment funnel:** of the bookings *created* in the period, how many have so far been
  confirmed, arrived and completed, and how many ended as no-shows or cancellations.
- **Bookings by source:** Staff, Website AI assistant, Voice demo and Waitlist replacement (plus
  "Website form (sample)" for the seeded sample booking). Voice-demo bookings are recognised by
  their linked call log and waitlist replacements by their waitlist entry, not by the stored
  booking source, which is the same `AI_DEMO` for both assistant channels.
- **Operations:** callback tasks by status; simulated AI call outcomes; waitlist statuses;
  notification statuses; arrivals and how many were by QR check-in; consultation outcomes by
  next-step category and the number of draft recommendations.
- **Only what is stored:** every number is a count of existing records. There are no revenue,
  satisfaction, forecast or real conversion figures, because the demo does not record them.
  Percentages are shares of the sample bookings in the period.
- **Privacy:** aggregated counts only. The analytics code never reads patient names, numbers,
  emails or notes, or a doctor's written summary or notes; there is no per-patient or per-doctor
  breakdown.
- **Charts:** plain HTML/CSS bars and tables with the value beside each bar; no chart library.

## Procedure follow-up scheduler (Phase 12)

After a consultation, a doctor's draft recommendation can be released to reception, who book a
**"Procedure discussion / follow-up"** appointment for it. This is a discussion appointment in a
normal consultation slot. **It is not treatment delivery**, and no room, chair, equipment, lab,
payment or insurance step is scheduled.

- **States:** `DRAFT → READY_FOR_SCHEDULING → SCHEDULED`. Only the doctor who created the
  recommendation can release it (*Mark ready for scheduling* in the doctor workspace). Reception
  and the assistant cannot create, edit, approve or release one.
- **Reception (`/follow-ups`, menu item Follow-ups):** lists released recommendations with the
  patient, doctor, procedure label, state and created date. The doctor's written note is never
  shown or even loaded there. *Schedule follow-up* offers the recommending doctor's free slots by
  day, with an optional scheduling note.
- **Booking:** made through the normal booking service, so slot conflicts, closed days, blocked
  time and past times are refused as usual, and the calendar, notifications, timeline and analytics
  treat it like any other booking (`PENDING`, source `STAFF`). It is booked under the matching
  existing service (`PROCEDURE_SERVICES` in `app/config.py`) and labelled in its booking note.
- **Linkage:** the booking is linked to the recommendation, which becomes `SCHEDULED`. One
  recommendation can have one follow-up; a second attempt is refused. The link is shown read-only
  in the doctor workspace, on the patient page and timeline, and on reception's lists.
- **Consultation follow-ups (no recommendation needed):** saving an outcome with the next step
  "Follow-up consultation" does **not** tell reception anything. Once the consultation is
  completed, the doctor presses *Send follow-up to reception for scheduling*. That creates a
  "Consultation follow-up" item on reception's Follow-ups list showing the patient, doctor, state
  and date, never the doctor's summary or note. Reception books it with the same doctor through
  the normal booking rules; it can be sent once and booked once. The doctor workspace explains
  this next to the outcome form.
- **Dashboard, timeline, analytics:** the dashboard shows "Procedure follow-ups awaiting
  scheduling" and "Consultation follow-ups awaiting scheduling". The timeline gains "Doctor marked recommendation ready" and "Procedure follow-up
  scheduled". Analytics counts recommendations by state and follow-ups booked, without procedure
  names or notes.

## Voice Agent Phase 1: knowledge, runtime context and safety policy

**Policy and knowledge groundwork.** There is no live phone number, LLM, telephony or live
booking. Nothing in `app/voice_agent/` places or receives a call, talks to a model or writes to
the database; the browser demo below is its only user. The website
assistant, the call demo and the dashboard's demo doctors, services and fees are unchanged and
are not merged with it.

- **Approved knowledge** (`app/voice_agent/knowledge.py`): the clinic's address, landmark,
  hours, phone numbers, email, doctors, specialist support, services, the 500 rupee initial
  consultation fee, payment methods and CGHS empanelment, as structured fields. Treatment prices
  are never quoted. CGHS, ECHS, CISF, DU and Air India questions become panel callbacks.
- **Runtime context** (`context.py`): IST time, `clinic_open_now` (Monday to Saturday,
  9:00 AM to 8:00 PM), `transfer_available` (9:30 AM to 7:30 PM, or a staff-availability
  override) and an optional caller number that is never read out or put in a prompt.
- **Policy** (`policy.py`): rule-based, in English, Hindi and Hinglish. Urgent symptoms get
  "call 112" first; clinical questions get no diagnosis, medicines, remedies or reassurance;
  ordinary tooth pain gets an appointment callback; anything not approved returns a structured
  `UnknownInformation` result with a callback offer instead of a guess. A request for a person is
  transferred only when transfer is available and otherwise goes straight to callback capture.
- **Callbacks**: a 10-digit Indian mobile (6 to 9 first; a leading +91 or 0 is ignored),
  created only after the caller confirms name and number, at most one per call plus one separate
  urgent escalation. Callers are promised "as soon as possible during clinic hours" or "on the
  next working day", never a number of minutes.
- **Prompt and tools** (`prompt.py`, `schemas.py`): `render_system_prompt(context)` builds the
  system prompt a later LLM would use, and `create_callback`, `transfer_to_reception` and
  `end_call` are typed contracts only. Nothing calls them yet.

Tests: `tests/test_voice_agent_policy.py`. **Every clinic detail and all Hindi/Hinglish wording
still need owner review before production** (see `PENDING_OWNER_REVIEW` in
`app/voice_agent/knowledge.py`).

## Voice Agent Phase 2: browser voice agent demo (`/voice-agent-demo`)

A presentation-ready owner demo, separate from `/assistant` and `/call-demo` (both unchanged).
Open it from the dashboard's **AI call activity** card (**Voice agent demo**). It is a browser-based interactive prototype on sample
data: it is not connected to a live clinic phone number, gives no medical advice, and records
workflow outcomes but no audio. No Pipecat, telephony, LLM or booking is involved.

```text
Chromium microphone or typed text → Phase 1 policy (app/voice_agent) → existing callback and
call-log services → local Piper voice reply → dashboard
```

- **Conversation:** `app/voice_agent/conversation.py` is a deterministic state machine over the
  Phase 1 `CallSession`, policy and wording: greeting (by transfer availability), recording
  notice, FAQ answers, unknown-information fallback, human request, simulated transfer failure
  → callback details, appointment enquiry → appointment callback, panel/CGHS → panel callback,
  clinical question → safe callback (never 112), urgent symptom → 112 instruction plus an
  optional urgent callback, then name, number (or the calling number), reason, read-back and
  confirmation, closing. English, Hindi and Hinglish; Hinglish is shown in Roman script and
  spoken by the Hindi voice from the Hindi version of the same approved line.
- **API:** `POST /api/voice-agent-demo/start` (optional demo-only simulation: `transfer`
  `auto|available|unavailable`, `caller_id` `unknown|present`, `clinic` `auto|open|closed`),
  `POST /api/voice-agent-demo/{session_id}/message` and `POST /api/voice-agent-demo/{session_id}/end`.
  Each call is an independent in-memory session with a fresh IST context. Loading the page or
  starting a call writes nothing; a confirmed callback is created through
  `services/callbacks.create_callback` (source `AI_DEMO`), and the call is logged once, when it
  ends, as channel `VOICE_AGENT`. Ending twice changes nothing; replies after the end are refused.
- **Transfers are always simulated:** there is no reception line, so an attempted transfer goes
  unanswered and the agent moves straight to callback details.
- **Microphone:** replaced in Phase 3 by push-to-talk with server-side transcription (below).
- **Audio:** the existing local Piper voices (`/api/call-demo/speech`) and the existing
  `call-audio.js` cancellation. End call silences audio immediately, aborts any pending speech
  request, drops late replies and disables input.
- **Tests:** `tests/test_voice_agent_demo.py` (API and conversation) and
  `tests/test_voice_agent_browser.py`, which drives headless Chromium through
  `tests/js/voice_agent_browser.js` (typed flow, microphone transcription, End call silence,
  late replies, 390px layout, saved language). The browser checks are skipped
  without Node.js and Chromium; the End-call audio check also needs the English voice pack.

## Voice Agent Phase 3: microphone transcription and controlled AI answering

Still a browser demo on sample data: no telephony, Pipecat, live phone routing or booking.

```text
Chromium microphone (MediaRecorder, one phrase per tap) → POST /api/voice-agent-demo/transcribe
→ local faster-whisper on this server (audio kept in memory, then discarded) → editable "You said: …"
→ Send → safety rules → optional language model picks approved answers → approved wording → Piper voice
```

**Microphone transcription.** Browser speech recognition is no longer used. The page records one
phrase per turn, the server transcribes it with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) and returns text. (Since Phase 3.1 the
turn ends on silence and clear transcripts are sent at once; only uncertain ones are held for review.)
Typed input always works.

```bash
.venv/bin/pip install -r requirements-voice.txt          # faster-whisper (and the optional Anthropic SDK)
.venv/bin/python scripts/download_stt_model.py           # large-v3-turbo, about 1.6 GB, once; never at startup
# optional GPU speed-up (NVIDIA): .venv/bin/pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

| Setting | Default | Meaning |
|---|---|---|
| `VOICE_AGENT_STT_MODEL` | `large-v3-turbo` | faster-whisper model name (`small` is faster but weaker in Hindi) |
| `VOICE_AGENT_STT_DIR` | `./models/stt` | where `download_stt_model.py` puts models (ignored by Git) |
| `VOICE_AGENT_STT_DEVICE` | `auto` | `auto` tries the GPU, then the CPU; or `cpu` / `cuda` |
| `VOICE_AGENT_STT_COMPUTE_TYPE` | blank | blank: `int8` on CPU, `float16` on GPU |
| `VOICE_AGENT_STT_MAX_SECONDS` / `_MAX_BYTES` | `30` / 2 MB | longest recording accepted |

- **Privacy:** the recording is decoded and transcribed in memory and dropped when the request
  ends. It is never written to a file, the database or a log, and it is not sent to Google or
  any other speech service. Only the text comes back (`"stored": false`).
- **Languages:** English and Hindi use Whisper's own modes. **Hinglish has no separate model:** it
  uses the same multilingual model in English mode with a Roman-Hinglish spelling hint, so mixed
  speech comes back in Roman script. The selected language stays Hinglish whatever script the
  transcript uses, and replies are in Roman Hinglish.
- **Low confidence:** uncertain transcripts show "I may not have caught that correctly. Please try
  again or type your message."
- **Matching only:** Devanagari spellings of English words (संडे, क्लिनिक, अपॉइंटमेंट…) are read in
  Roman script for intent matching only; what the caller sees, and what staff receive, is the
  original transcript.
- **No model installed:** the page says so and offers typed input only.
- **Adapter:** `app/services/stt.py` defines the `SpeechToText` shape (`status()`, `transcribe()`);
  a production or Pipecat provider can replace `LocalWhisper` in `app.state.transcriber` without
  changing the page or the conversation.

**Controlled AI answering.** An optional language model *understands* the caller; it never writes
what the agent says.

```bash
# local (no key): Ollama with qwen3:8b already pulled
VOICE_AGENT_LLM_PROVIDER=ollama VOICE_AGENT_LLM_MODEL=qwen3:8b .venv/bin/uvicorn app.main:app --port 8001
# or Claude: VOICE_AGENT_LLM_PROVIDER=anthropic with ANTHROPIC_API_KEY set (model claude-opus-5-5 by default)
```

- The model receives the rendered Phase 1 system prompt (approved knowledge, runtime context,
  safety rules, tool contracts), the selected language, the call state, recent turns and the
  original transcript. It must return JSON: an intent from a fixed list, up to two approved answer
  ids, and any preferred doctor or time. Unknown ids or intents are rejected.
- The spoken reply is always the approved wording for those ids, so the model cannot invent
  facts, quote treatment prices, promise schedules, claim bookings or give advice.
- **Deterministic first:** urgent symptoms and 112, clinical questions, tooth pain, treatment
  suitability and explicit requests (a person, panel, reschedule, cancel, booking status and
  similar) never reach the model. Phone validation, callback confirmation, the one-callback rule,
  transfers and ending the call stay in code.
- Any error, timeout (`VOICE_AGENT_LLM_TIMEOUT_SECONDS`, default 12) or invalid reply falls back to
  the rule-based policy for that turn. `VOICE_AGENT_LLM_PROVIDER=none` (the default) uses rules only.
- **Demo details** on the page show the AI response source (Approved knowledge, Callback required,
  Safety fallback or Emergency escalation) and what understood the caller. The prompt, raw
  knowledge, keys and tool payloads are never shown.

**Knowledge base.** `app/voice_agent/knowledge_base.py` holds every answer in the owner-review
categories (clinic profile, location and directions, hours and closures, contact details, doctors,
services, visit logistics, appointment policies, fees and payments, panels and insurance, safe
general answers, callback-required topics, clinical refusal topics, urgent symptom topics,
language translations). Each entry is marked `approved_brief`, `system_fact`,
`owner_approval_required` (drafted for the demo) or `not_provided` (the agent says it doesn't know
and offers a callback: parking, accessibility, walk-ins, holidays, WhatsApp, cancellation policy).
Appointment enquiries also collect new or existing patient, preferred doctor and preferred time.
Reschedule, cancellation, booking status, missed call, website enquiry, complaint and records
requests become callbacks labelled with that intent, with the lead details in the staff notes.

Tests: `tests/test_voice_agent_phase3.py`, plus the browser checks (fake microphone and
transcriber; with the model installed, real Chromium-to-Whisper transcription in all three languages).

## Voice Agent Phase 3.1: latency and speech-recognition quality

No new features; the same safety rules, approved answers, callback rules, LLM limits and routes.

- **Ends on silence.** Tap to speak; the browser watches the microphone level (no cloud service) and ends
  the turn about 0.8 s after you stop talking (15 s at most). "Stop listening" ends it early. Silent or
  near-silent recordings are never uploaded. Stages: Listening… → I heard you. Understanding… →
  Thinking… → Preparing voice… → Speaking.
- **Clear speech goes straight through; unclear speech never acts.** A confident transcript is sent at
  once. A low-confidence one is shown for review ("Send this", "Try again", "Type instead") with "I may
  not have caught that clearly. Please say that again, or type your message." The server also refuses to
  act on unreviewed low-confidence speech: no language model, no callback, no transfer, no emergency path.
- **Speech-to-text.** `large-v3-turbo` stays loaded (warmed at start-up in the background, never
  downloaded), on the GPU with `float16` when CUDA is available (`int8` on CPU), one pass at temperature 0
  without timestamps, silence trimmed by VAD, and a clinic vocabulary hint (Smriti Raj Dentistry, Dwarka,
  the doctors, appointment, callback, consultation, root canal, implant, braces, aligners, CGHS, reception,
  periodontist, orthodontist; Devanagari forms for Hindi). The transcript is never rewritten.
- **Answer selection.** Clear rule matches answer at once; the language model is asked only when the rules
  cannot place the words, with a short fixed prompt (cached by the model), the current words only, a 1.5 s
  limit (`VOICE_AGENT_LLM_TIMEOUT_SECONDS`) and the rules as an immediate fallback. Ollama is warmed at
  start-up and kept loaded.
- **Speech.** Piper voices stay loaded; replies are spoken sentence by sentence (the next sentence is
  generated while the first plays) by `POST /api/voice-agent-demo/speech`, in a worker thread that stops
  when the page cancels. Approved fixed phrases (greeting, "One moment, please.", the retry line, closing
  lines) are pre-generated and cached per language and voice; nothing containing a caller's name, number
  or words is cached. "One moment, please." plays only if a reply takes longer than 1.2 s.
- **Only the latest turn plays.** Every turn has its own id; a newer turn, mute or End call cancels the
  recording, transcription, reply request and audio, and nothing late can appear or speak.
- **Turn timing** (developer panel on the page): speech ended → transcript, transcript → answer, answer →
  audio ready, speech ended → audio playing, plus which path answered (rule, llm or fallback). Kept in the
  page for the current turn only; never stored.

Tests: `tests/test_voice_agent_latency.py`, `tests/js/voice_agent_audio_harness.js`, and the browser checks.

## Voice agent demo: reference voice (consented local experiment)

An optional, demo-only voice on `/voice-agent-demo` that resembles an authorised speaker. The standard
Piper voices stay the default and are unchanged. Speech-to-text, the language model, knowledge,
callbacks, safety paths, logging and languages are untouched. **Not production-ready.**

- **Consent:** use only a recording whose speaker has explicitly agreed to their voice being cloned for
  this demo. For this demo the agreed speaker is the receptionist in
  `~/Downloads/WhatsApp Audio 2026-10-19 at 1.42.17 AM.mp4`. The caller's lines in that recording are
  excluded. The recording is not copied into the project or committed (`*.mp4` is ignored by Git).
- **Reference clips:** `scripts/prepare_reference_voice.py` cuts the speaker's own segments into mono
  24 kHz WAV clips in `voices/reference/` (ignored by Git, never served by any route). The clips used:
  ```bash
  .venv/bin/python scripts/prepare_reference_voice.py --source "<authorised recording>" \
    --clip hi_1=10.46-14.42,18.98-23.74,28.55-30.87 \
    --clip hi_2=48.58-53.08,61.31-63.93,97.20-99.92,129.25-132.69 \
    --clip mix_1=1.20-5.50,40.22-42.48,99.92-105.66
  ```
- **Model:** Chatterbox Multilingual (Resemble AI; the code and weights are MIT-licensed per the model card;
  every output carries Resemble's PerTh watermark). It runs in its own environment `.venv-refvoice`
  (Python 3.11; ignored by Git) as a local worker on 127.0.0.1:8765, so the main app never loads PyTorch.
  The weights (about 3 GB) download once to the Hugging Face cache, outside the project. Setup and run:
  see `scripts/reference_voice_worker.py`. English uses the `mix_1` clip and Hindi uses `hi_1`.
  Hinglish is spoken from the Hindi version of each line, as with the standard voice.
- **Selector:** "Standard local voice" (default) or "Reference voice (authorised demo)". It is shown only
  when the clips are present and the worker is ready.
- **Fallback:** if the reference voice cannot speak a sentence (no clips, worker not running, language
  not supported, slower than `VOICE_AGENT_REFERENCE_TIMEOUT_SECONDS` (default 6), failed or cancelled),
  the standard voice speaks it. The page then shows "Reference voice is unavailable for this reply.
  Using the standard local voice." and labels it "Speaking (standard voice)". Sentences containing the
  emergency number 112 always use the standard voice, because the cloning model misread "112" in
  testing. Numbers are spelled out for the reference voice; that text is not stored.
- **Privacy:** nothing leaves this machine. Reference speech is generated on request, never cached, and
  never stored. Neither the reference clips nor the generated audio go into the database.
- **Evaluation (internal, not in the UI):** `scripts/evaluate_reference_voice.py generate` (main env), then
  `compare` (reference env). Outputs go to `voices/reference/eval/` for listening; delete them afterwards.

## Changing the demo values

- **Before first run:** edit the seed values in `app/config.py` (clinic name, address, phone,
  currency, doctors, working hours, consultation duration, services and fees, sample patients).
- **Closed days:** `CLINIC_CLOSED_WEEKDAYS` in `app/config.py` (Sunday in this demo) is a clinic-wide
  rule. No slots are created or bookable on those days whatever a doctor's working days say; staff
  screens mark them "Clinic closed" and the assistant explains the closure. Restart after changing
  it, and keep `CLINIC_HOURS` in `app/knowledge.py` in step.
- **While running:** use the **Settings** page. It has five sections — Clinic profile, Doctors and
  availability, Services and demo fees, Clinic schedule and closed days (read-only), Demo data — and
  each explains what it affects. Seeded placeholder values are tagged "awaiting owner approval".
  Saving a doctor rebuilds their slots from today; existing bookings are kept and keep their time
  blocked. There is deliberately no reset control in the app.

## Interface

Server-rendered Jinja templates with one stylesheet (`app/static/css/app.css`) and two small
scripts; no frontend framework or build step. Colours, type, radii and motion timings are CSS
variables at the top of the stylesheet. Fonts (Fraunces, Instrument Sans) load from Google Fonts;
offline, the page falls back to system serif/sans fonts and everything else works unchanged.
Animations are disabled for visitors who prefer reduced motion.

**Navigation (Phase 13).** The left menu is grouped: *Overview* (Dashboard), *Reception* (Book
appointment, Patients, QR check-in, Waitlist), *Clinical* (Doctor workspace, Doctor calendar,
Follow-ups), *Communication* (Notifications, plus Patient assistant and Call demo, both tagged
"Demo" because they are the patient-facing simulations) and *Insights* (Analytics), with Settings at
the bottom. Groups collapse on desktop and the choice is remembered in the browser (`localStorage`);
the group holding the current page always stays open and is highlighted. Below 1080px the menu
becomes a top bar with a **Menu** button that opens a drawer (Escape closes it). Patient detail,
doctor schedule, follow-up scheduling and the check-in pages show breadcrumbs. Every URL is
unchanged. Availability is no longer a menu item; it is linked from the booking page and the
dashboard's "Available slots" card.

**Buttons and actions.** One system everywhere: `.btn-primary` (teal, the main action),
`.btn` (outline, secondary), `.btn-danger` (cancellation and no-show only) and `.btn-ghost` (quiet
links). Destructive and secondary row actions sit in a small **More** menu. Cancel, no-show,
check-in, mark arrived, mark completed and completing a callback ask for confirmation first
(`data-confirm`); ordinary saves do not. Submitting a form shows a busy spinner and ignores repeat
clicks, and after the page reloads the changed item is scrolled into view, highlighted, and the
result is shown beside it. All of this lives in `app/static/js/app.js`; without JavaScript every
form still posts normally. Transitions are 150–250ms.

## Project layout

```
app/
  config.py            editable seed/config values
  knowledge.py         approved answers for the patient assistant
  notification_templates.py   wording for the simulated notification outbox
  ratelimit.py         in-memory limiter for the public endpoint
  models.py            SQLAlchemy tables
  database.py          engine + request session
  seed.py              first-run demo data
  services/            business logic (no web code)
    patients.py        create / search / duplicate check
    availability.py    slot generation and availability
    appointments.py    booking rules, status changes, dashboard counts
    clinic.py          clinic / doctor / service settings
    callbacks.py       callback tasks and status rules
    assistant.py       guided patient conversation (no AI model)
    consultations.py   doctor workspace: arrival, outcome, draft recommendations
    schedule.py        doctor weekly calendar and blocked periods
    timeline.py        read-only patient timeline for reception
    checkin.py         QR check-in tokens and validation
    waitlist.py        waitlist entries, cancellation matches, offers and bookings
    notifications.py   simulated notification outbox (sends nothing)
    analytics.py       aggregated owner analytics (counts only)
    followups.py       procedure follow-up scheduling for released recommendations
    calls.py           call log for the voice-call simulation
    tts.py             local voices for the call demo (Piper, one pack per language)
    call_language.py   words call-demo replies in English, Hindi or Hinglish
    voice_agent_demo.py  sessions for the browser voice agent demo (callbacks + call log)
    stt.py             speech-to-text adapter (local faster-whisper, in memory)
    reference_voice.py optional consented reference voice (local worker, Piper fallback)
    errors.py          staff-friendly error types
  voice_agent/         voice receptionist: knowledge base, context, policy, wording, prompt, conversation, LLM router
  routes/
    api.py             JSON booking API under /api (docs at /docs)
    pages.py           server-rendered reception screens
    assistant.py       public /assistant page and its message endpoint
    calls.py           /call-demo page and its endpoints
    voice_agent.py     /voice-agent-demo page and its session API
    doctor.py          /doctor workspace and its form actions
    checkin.py         /check-in screen and QR card
    waitlist.py        /waitlist screen and staff API
    notifications.py   /notifications outbox screen and staff API
    analytics.py       /analytics owner page and API
    followups.py       /follow-ups reception screen and API
  templates/, static/  HTML, CSS, JavaScript
tests/
```

Routes and templates only call `app/services`. Phase 2 (AI assistant) can use the same service
functions or the JSON API, passing `source: "AI_DEMO"`.

### Booking API (used by the UI)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/doctors`, `/api/services`, `/api/clinic` | Reference data |
| GET | `/api/patients?q=` | Search by name or mobile |
| POST | `/api/patients` | Register a patient (409 if the mobile number exists) |
| GET | `/api/doctors/{id}/slots?date=YYYY-MM-DD` | Slots with start, duration, availability |
| POST | `/api/appointments` | Create a `PENDING` booking (409 if the slot is taken) |
| POST | `/api/appointments/{id}/status` | `CONFIRMED` or `CANCELLED` |
| GET | `/api/appointments?scope=today\|upcoming` | Booking lists |
| GET | `/api/dashboard/summary` | Dashboard counts |
| POST | `/api/assistant/message` | One turn of the patient assistant (public, rate-limited) |
| GET | `/api/callbacks?status=` | Callback tasks |
| POST | `/api/callbacks` | Create a callback task |
| POST | `/api/callbacks/{id}/status` | `IN_PROGRESS` or `COMPLETED`, optional `notes` |
| GET | `/api/callbacks/summary` | Callback counts by status |
| POST | `/api/call-demo/start` | Start a simulated call and get the greeting (rate-limited) |
| POST | `/api/call-demo/{id}/message` | One caller turn, same body as the assistant (rate-limited) |
| POST | `/api/call-demo/{id}/end` | End the call and record its outcome |
| GET | `/api/calls` | Recent simulated calls |
| GET | `/api/appointments/{id}/consultation` | Read-only doctor outcome and draft recommendations |
| GET | `/api/doctors/{id}/schedule?start=YYYY-MM-DD` | Read-only week: appointments, free slots, blocks |
| GET | `/api/patients/{id}/timeline` | Read-only, reception-safe patient history, newest first |
| POST | `/api/appointments/{id}/checkin-token` | Create or return the booking's check-in token |
| POST | `/api/check-in/lookup` | What reception may do with a token (changes nothing) |
| POST | `/api/check-in/arrive` | Staff-confirmed check-in: `CONFIRMED → ARRIVED` |
| GET/POST | `/api/waitlist` | List waitlist entries (optional `?status=`) or add one |
| GET | `/api/waitlist/opportunities` | Cancelled slots that are still free, with matching waiting patients |
| GET | `/api/waitlist/summary` | Waiting, offered and newly-available counts |
| POST | `/api/waitlist/{id}/offer` | Mark a waiting entry as offered a slot (reserves nothing) |
| POST | `/api/waitlist/{id}/status` | Return an offered entry to `WAITING`, or `CLOSED` |
| POST | `/api/waitlist/{id}/book` | Book the offered slot once the patient has accepted |
| GET | `/api/notifications?q=&status=&channel=&type=` | Simulated outbox, newest first, contacts masked |
| GET | `/api/notifications/summary` | Counts by status |
| GET | `/api/follow-ups` | Recommendations awaiting scheduling and recently scheduled (no doctor notes) |
| POST | `/api/follow-ups/{id}/schedule` | Book the follow-up for a released recommendation |
| GET | `/api/follow-ups/consultation` | Consultation follow-ups a doctor has sent to reception (no clinical text) |
| POST | `/api/follow-ups/consultation/{id}/schedule` | Book a consultation follow-up |
| GET | `/api/analytics?range=today\|week\|all` | Aggregated sample-data counts; no patient or doctor free text |
| POST | `/api/notifications/{id}/{send\|deliver\|fail\|retry}` | Simulated staff action (changes status only) |
| GET | `/api/call-demo/voice` | Which local voice pack each language uses and whether it is installed |
| POST | `/api/call-demo/speech` | WAV audio for one reply in `language` (`en`, `hi`, `hinglish`), generated locally (rate-limited) |

### Moving to PostgreSQL later

Set `DATABASE_URL` (for example `postgresql+psycopg://user:pass@host/dbname`) and install a driver.
The models use portable column types, and the "one active booking per doctor and start time" rule
is a partial unique index declared for both SQLite and PostgreSQL. Add Alembic migrations and
timezone-aware timestamps before any real deployment.

## Acceptance checklist

1. **Dashboard** — `/` shows today's bookings, upcoming bookings and three counts (today's
   bookings, pending bookings, available slots). Seeded rows carry a "Demo" tag.
2. **Register a patient** — Patients → fill name and mobile → *Register patient*. The patient
   appears in the list.
3. **Duplicate patient** — register the same mobile number again → a message says the patient is
   already registered and offers to book for them.
4. **Search** — from the dashboard search box, find a patient by part of their name, then by part
   of their mobile number.
5. **Availability** — *Book appointment* → *See all open slots* (or `/availability`) → pick a doctor and date → each slot shows start time,
   duration and Available / Booked / Past.
6. **Create a booking** — dashboard quick action *Create booking* (or *Book appointment* in the menu) → select or add a patient → doctor → date → slot →
   reason → *Create booking*. You land on the dashboard with the new booking highlighted, status
   `PENDING`; the pending count goes up and available slots go down.
7. **Slot conflict** — open *Create booking* in two tabs, pick the same doctor/date/slot in both,
   submit one then the other → the second shows "This slot has just been booked. Please choose
   another available time." and the slot list refreshes.
8. **Confirm** — on the dashboard press *Confirm* → status becomes `CONFIRMED`, pending count drops.
9. **Cancel** — open the row's *More* menu → *Cancel booking* → confirm → the booking is cancelled and the same slot shows as Available
   again under Availability.
10. **Settings** — *Doctors and availability* tab → change a doctor's hours → *View calendar* shows the new slots.
11. **Mobile** — narrow the browser to phone width; all screens remain usable.
12. **Assistant FAQ** — open `/assistant`, choose "What are your opening hours?" → an approved
    answer, and no callback task appears on the dashboard.
13. **Assistant booking** — "I want to book a consultation." → answer the steps → three times are
    offered → confirm. The dashboard shows the booking as `PENDING` with an `AI_DEMO` tag.
14. **Assistant slot conflict** — reach the "Confirm booking" step, book the same slot from the
    staff screen, then confirm → the slot-taken message and three fresh times.
15. **Callback** — "I want to speak to a person." → give a name and mobile → the assistant says
    staff will be in touch, and an `OPEN` task appears under "Callback tasks".
16. **Safety** — ask "Which antibiotic should I take?" or "Am I covered under CGHS?" → no advice
    or approval is given; a callback is offered instead.
17. **Complete a callback** — on the dashboard add a note, press *Mark in progress*, then
    *Mark completed*; the counts update and the task shows as completed.
18. **Call demo, booking** — open `/call-demo`, press the booking phrase, answer the steps and
    confirm. End the call: the outcome shows `BOOKING_CREATED`, and the dashboard lists the call
    under "AI call activity" with a link to the booking.
19. **Call demo, safety** — press the tooth-pain phrase → no advice, a callback is offered; press
    the Sunday phrase → the clinic-closed explanation; press the person phrase → an `OPEN`
    callback task.
20. **Call demo, reset** — *Reset demo call* clears the transcript, timer and caller details; a
    call ended with nothing done is logged as `ENDED`.

## Placeholder details awaiting owner approval

Only the clinic name is real. Everything else is sample data and must be supplied or approved by
the clinic owner before this is shown as anything other than a demo:

- Clinic address, phone number and email
- Opening hours stated by the assistant (`CLINIC_HOURS` in `app/knowledge.py`)
- The clinic website link and every approved answer in `app/knowledge.py`, including the
  CGHS/ECHS wording and the promise "Our staff will contact you during clinic hours."
- Whether the clinic handles CGHS/ECHS enquiries at all
- Doctor names, specialities, working days, hours and consultation length
- Service consultation fees (demo values, not real prices) and the currency symbol
- Use of the clinic's name and brand colours in this interface
- The voice-agent knowledge and wording in `app/voice_agent/` (see Voice Agent Phase 1)

## Assumptions and limits

- One clinic, one shared reception login-free screen (no authentication in this phase).
- Times are stored as clinic-local time without a timezone.
- Mobile numbers are compared digits-only; `+1 555…` and `555…` count as different numbers.
- Every slot is a consultation of the doctor's configured duration; the chosen service is recorded
  as the reason for the visit and does not change the slot length (no procedure scheduling yet).
- A booking can go `PENDING → CONFIRMED`, and either can be `CANCELLED`. Cancelled is final;
  rebook the slot instead.
- "Upcoming bookings" lists active bookings from tomorrow onwards; today's list also shows
  cancelled ones (struck through).
