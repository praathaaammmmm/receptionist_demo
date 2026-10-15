# Smriti Raj Dentistry — AI Dental Front Desk Demo

## Phase 1: Booking Foundation · Phase 2: Appointment Assistant and Callback Tasks · Phase 3: Voice-Call Simulation · Phase 5: Doctor Consultation Workspace · Phase 6: Doctor Schedule Calendar · Phase 7: Patient Timeline · Phase 8: QR Appointment Check-in · Phase 9: Waitlist and Cancellation Fill · Phase 10: Notification Centre · Phase 11: Admin Analytics · Phase 12: Procedure Follow-up Scheduler · Phase 13: Navigation, Button and Settings UX

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
calendar.

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
- **Natural voice (optional, recommended for presenting):** a locally generated neural voice
  ([Piper](https://github.com/OHF-Voice/piper1-gpl)) that sounds far smoother than a browser's
  built-in robot voice and works the same in every browser, Firefox included. One-time setup:

  ```bash
  .venv/bin/pip install -r requirements-voice.txt
  .venv/bin/python scripts/download_voice.py        # about 60 MB into ./voices
  ```

  Restart the app afterwards. Audio is generated on this computer by the demo server
  (`POST /api/call-demo/speech`); nothing is sent to a cloud service and nothing is stored. The
  default voice is `en_GB-cori-medium` (British English; Piper has no Indian-English voice). To try
  another, run `python scripts/download_voice.py en_US-lessac-medium` and start the app with
  `CALL_DEMO_VOICE=en_US-lessac-medium`. Without the voice pack the page falls back as below.
- **Browser voice (fallback):** replies are read aloud by the browser's own speech synthesis, after the first click
  (never autoplay). *Test speaker* says "Hello. This is the Smriti Raj Dentistry appointment
  assistant." and the audio status shows "Voice ready", "Muted", "Browser voice unavailable" or
  "Audio requires a click to start". An English (India) voice is used when the browser has one.
  *Mute voice* turns speech off. The transcript works whether or not speech does.
- **Text simulation mode:** without the voice pack, Firefox runs the call demo without speech,
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
    tts.py             optional local voice for the call demo (Piper)
    errors.py          staff-friendly error types
  routes/
    api.py             JSON booking API under /api (docs at /docs)
    pages.py           server-rendered reception screens
    assistant.py       public /assistant page and its message endpoint
    calls.py           /call-demo page and its endpoints
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
| GET | `/api/call-demo/voice` | Whether the optional local voice pack is installed |
| POST | `/api/call-demo/speech` | WAV audio for one reply, generated locally (rate-limited) |

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
