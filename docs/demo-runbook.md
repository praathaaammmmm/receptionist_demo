# Smriti Raj Dentistry — AI Dental Front Desk: demo runbook

For the person presenting the demo to the clinic owner. Five minutes, one laptop, no internet
needed once set up.

> **This is a demonstration with sample data.** It is not connected to a phone line, does not
> record anything, does not use a live AI model, has no login, and must not hold real patient
> information. Do not describe it as production-ready.

## 1. Before the meeting (2 minutes)

Run these from the project folder.

```bash
# 1. Restore clean sample data.  DEMO DATA ONLY — never run against real patient data.
.venv/bin/python scripts/reset_demo.py --yes

# 2. Start the app (leave this terminal open).
.venv/bin/uvicorn app.main:app --port 8010
```

Then open these three tabs, in this order:

| Tab | URL | Used for |
| --- | --- | --- |
| 1 | <http://127.0.0.1:8010/assistant> | Patient website assistant |
| 2 | <http://127.0.0.1:8010/call-demo> | After-hours call simulation |
| 3 | <http://127.0.0.1:8010/> | Reception dashboard |

Pre-flight checks:

- **Browser:** Firefox or any current Chromium-based browser (Chrome, Edge, Brave). The final
  walkthrough in section 6 was run in Firefox.
- **Window size:** a normal laptop window (1366×768 or larger). For tab 1, optionally narrow the
  window or use the browser's phone view to show it as a patient would see it on a mobile.
- **Sound:** on tab 2 press **Test speaker**. You should hear "Hello. This is the Smriti Raj
  Dentistry appointment assistant." and see "Voice ready". If not, see section 4; the demo works
  without sound.
- **Dashboard:** tab 3 shows 4 sample bookings, 0 open callback tasks and no AI call activity.
- **Not on a Sunday:** the clinic is closed on Sundays in the demo, so "today" has no slots then.
  Everything still works; bookings land on Monday.

The reset is a developer command only. It is not available from any screen, and it also undoes any
edits made on the Settings page.

## 2. Five-minute script

Say the line in *italics*, do the clicks, and point at the outcome.

### Minute 1 — A patient asks a question (tab 1)

*"This is what a patient sees on the clinic website, any time of day."*

1. Click **"What are your opening hours?"**
   - **See:** "Smriti Raj Dentistry is open Monday to Saturday from 9:00 AM to 8:00 PM. The clinic
     is closed on Sunday."
2. Type **Can I come on Sunday?** and press Send.
   - **See:** "Smriti Raj Dentistry is closed on Sunday. The next available appointments are on
     Monday."

*"It only answers from information the clinic has approved."*

### Minute 2 — The patient books (tab 1)

1. Click **Book a consultation**.
2. Click **New patient** → type **Anita Example** → type **5551110001** → click **Skip** (email).
3. Click **General Consultation** → **No preference** → **Earliest available**.
   - **See:** exactly three available times.
4. Click the first time, then **Confirm booking**.
   - **See:** a "Booking request" card with a reference number and status **PENDING**.

*"The booking is a request. Your front desk confirms it."*

### Minute 3 — A medical question is handed to staff (tab 1)

1. Click **Ask something else**, then type **My gums are bleeding, what medicine should I take?**
   - **See:** "I'm not able to answer clinical or medical questions, and I can't suggest a
     diagnosis or treatment…" and a request for a name.
2. Type **Anita Example**, then **5551110001**.
   - **See:** a "Callback request" card, status **OPEN**, and "Our staff will contact you during
     clinic hours."

*"It never gives medical advice. It creates a task for your staff instead."*

### Minute 4 — The same thing on an after-hours phone call (tab 2)

*"This screen simulates a call to the clinic after closing time. It is a simulation, not a real
phone line."*

1. Click **"I need to book a consultation."** (this starts the call).
2. Click **New patient** → type **Vikas Example** → type **5551110002** → **Skip** →
   **Root Canal Treatment** → **No preference** → **Earliest available**.
3. Click the first time, then **Confirm booking**.
   - **See:** the caller's name and number appear on the left, the timer running, and a "Booking
     request" card in the transcript.
4. Click **End call**.
   - **See:** "Outcome recorded for this demo call: BOOKING_CREATED".

Optional, if there is time: click **"I have severe tooth pain; what medicine should I take?"** to
show the same refusal on a call, then **Reset demo call**.

### Minute 5 — What the front desk sees (tab 3)

Reload the dashboard.

- **Counts** at the top: today's bookings, pending bookings, available slots, open callback tasks.
- **Pending confirmation:** Anita Example and Vikas Example, each with a **Confirm** button.
  Press **Confirm** on one. **See:** "Booking confirmed."
- **Callback tasks:** Anita Example with the question she asked, status **OPEN**. Type a short
  note, press **Mark in progress**, then **Mark completed** and confirm.
- **AI call activity:** the simulated call, tagged **VOICE_DEMO** and **Demo call**, outcome
  **BOOKING CREATED**, linked to its booking.
- **Today's / Upcoming bookings:** both new bookings carry an **AI_DEMO** tag.

*"Nothing is lost between the website, the phone and your reception desk."*

### Optional extra minute — After the booking: the doctor's side (tab 3)

*"Booking is only the start. This is what the doctor sees, and the doctor stays in charge of every
clinical decision."*

1. On the dashboard, make sure the booking you want to follow is **Confirmed** (press **Confirm**).
2. Click **Doctor workspace** in the left menu and choose that booking's doctor.
   - **See:** the patient on today's list with status **CONFIRMED**. Unconfirmed bookings are not
     listed; reception confirms them first.
3. In the **Next patient** card press **Mark arrived** (confirm), then **Start consultation**.
   **See:** the consultation opens at the stage "In consultation". Type a one-line summary, choose
   a next step and press **Save outcome**.
4. Press **Mark completed** and confirm. Under "Draft treatment recommendation" choose a procedure and press
   **Save draft recommendation**.
   - **See:** the recommendation listed with a **DRAFT** label.
5. Go back to the **Dashboard**.
   - **See:** the booking shows **COMPLETED**, "Next step: …" and "Doctor recommendation: … ·
     DRAFT". Reception can read these but has no way to change them, and never sees the doctor's
     summary or note.

Only works for bookings dated today, so do this when the booking landed on today's date.

**Consultation follow-up (30 seconds):** in the Doctor workspace, save the outcome with next step
"Follow-up consultation" and mark the consultation completed. Point at the "Follow-up with
reception" box: saving alone sends nothing. Press **Send follow-up to reception for scheduling**.
On **Follow-ups**, reception sees "Consultation follow-up" for that patient and books it.

**Procedure follow-up (45 seconds, continues the doctor's side):** in the Doctor workspace, on the
draft recommendation press **Mark ready for scheduling**. Go to the Dashboard. **See:** "Procedure
follow-ups awaiting scheduling: 1". Open **Follow-ups**, press **Schedule follow-up**, pick a day
and a time, press **Book follow-up**. **See:** a new booking labelled "Procedure discussion /
follow-up". Say: the doctor decides and releases it; reception only books a discussion appointment
and never sees the doctor's notes; this is not scheduling the treatment itself.

**Doctor calendar (30 seconds, if asked about leave):** click **Doctor calendar** in the left
menu (or the **Weekly schedule** tab in the Doctor workspace).
Point at the week: free slots, bookings coloured by status, Sunday marked closed. Under "Block
time" pick a date two days ahead, leave the times empty, choose **Leave** and press **Block this
time**. **See:** the day shows "Blocked · Leave" and its free slots disappear; the patient assistant
will no longer offer that doctor on that day. Trying to block a day that already has a patient
booked shows "This time cannot be blocked because it has a scheduled patient appointment."

**QR check-in (45 seconds):** on the Dashboard, on a **Confirmed** booking for today press
**Generate check-in QR**. **See:** a card labelled "Demo appointment check-in QR". Copy the code
under the QR, click **QR check-in** in the left menu, paste it and press **Find booking**.
**See:** the patient's booking. Press **Mark patient arrived** and confirm. **See:** "Checked in"; the
dashboard and the doctor's list now show ARRIVED. Paste the same code again to show "Patient
already checked in". Say: the QR holds only a random code, and reception always confirms.

**Waitlist (1 minute, if asked "what happens when someone cancels?"):** click **Waitlist**, add
a patient with a preferred doctor and "Morning". On the Dashboard, open **More** on a morning booking and **Cancel booking** for
that doctor. **See:** the Waitlist panel shows 1 newly available slot; press **Review**. **See:**
the freed time with the waiting patient beside it. Press **Mark offered**, tick **Patient has
accepted this time**, press **Book this slot**. **See:** a normal PENDING booking on the dashboard.
Say: nothing is sent or booked automatically; reception decides each step.

**Notification centre (45 seconds):** on the Dashboard press **Confirm** on a pending booking,
then click **Notifications**. **See:** an "Appointment confirmation" entry, WhatsApp, QUEUED. Click
**Preview** to show the wording, then **Send** and **Mark delivered**. Cancel a different booking
and return: **See:** a "Cancellation update". Say clearly: this is a simulation, **no messages are
sent**; it shows what an outbox would look like once a messaging service is connected.

**Analytics (30 seconds, for the owner):** click **Analytics**. **See:** the appointment funnel
(created, confirmed, arrived, completed, no-shows, cancellations), bookings by source, and counts
for callbacks, calls, waitlist, notifications and check-ins. Point at "Voice demo" and "Website AI
assistant" showing the bookings just made. Say: these are counts of today's sample activity, not
real clinic results, and no patient is named anywhere on this page.

**Patient timeline (20 seconds, a good closing shot):** on the Dashboard, look at **Recent
patient activity** and click a patient's name, for example Anita Example (or use **View timeline**
on the Patients page). **See:** one page with everything that happened to that patient, newest
first, each line tagged Staff, Website AI, Voice Demo or Doctor: booked through the website
assistant, confirmed by reception, the callback she asked for, and any doctor steps. Doctor lines
show only the next step and the recommended procedure, never the doctor's notes.

### If asked: "What if two people pick the same time?"

1. On tab 3 click **Create booking**, pick any patient, doctor and day, and select a time. Do not
   submit yet.
2. In a second tab open **Create booking** again and book that same doctor, day and time.
3. Return to the first tab and press **Create booking**.
   - **See:** "This slot has just been booked. Please choose another available time." The slot
     list refreshes and shows the time as Booked.

## 3. Things to say plainly

- The call screen is a **simulation in a browser**. It does not receive real calls and nothing is
  recorded.
- The assistant is a **guided, rule-based demo**. No AI model is running behind it yet.
- It gives **no medical advice**. Clinical, unsupported and CGHS/ECHS questions become callback
  tasks for staff.
- All names, numbers, doctors, hours and fees on screen are **sample data** until the clinic
  supplies the real ones.
- The doctor workspace is **not a medical record**. It does not diagnose or prescribe; treatment
  decisions are entered and controlled by the doctor, never by the assistant or reception.

## 4. If sound does not work

The transcript is the proof in this demo; sound is an extra.

1. Carry on without it. Every step above works silently, and the page will say either "Muted" or
   "Text simulation mode — the conversation transcript remains fully functional."
2. If the status says "Audio requires a click to start", click anywhere on the page, then
   **Test speaker**.
3. If the voice pack is missing (a fresh machine), install it once and restart the app:

   ```bash
   .venv/bin/pip install -r requirements-voice.txt
   .venv/bin/python scripts/download_voice.py
   ```

4. Check the laptop volume and output device. The voice is generated on this computer; it does not
   need the internet.

## 5. Limitations and what comes next (for the owner)

**What this demo is not**

- Not connected to the clinic's phone number, WhatsApp or website.
- No staff or doctor login, and no security suitable for real patient records. The doctor
  workspace uses a simple switcher to choose the doctor.
- Not an electronic medical record: no diagnosis, prescriptions, billing, insurance approval or
  procedure scheduling. Draft recommendations stay drafts; there is no approval step yet.
- Not using a live AI model; it follows fixed rules and approved answers.
- No call recording, no reminders, no payments, no treatment or procedure scheduling.
- Bookings can be made up to 7 days ahead, in fixed consultation slots.
- Procedure follow-ups are discussion appointments only: no treatment, room, chair, equipment,
  payment or insurance scheduling, and recommendations cannot be withdrawn or edited once released.
- The analytics page counts sample records only. It has no revenue, satisfaction or real
  conversion figures, and no history beyond what has been done in the demo.
- The notification centre is a simulation: no WhatsApp, email or SMS is sent, and reminders are
  queued only when staff open the dashboard or the centre.
- The waitlist does not message patients or rebook anyone by itself; reception offers and books.
- The check-in QR is printed or downloaded by reception; nothing is sent to the patient, and
  patients cannot check themselves in.
- The doctor calendar is not linked to Google Calendar or any other calendar, has no rooms or
  equipment, and does not reschedule patients; blocking leave never moves an existing booking.
- The call voice is British English; a natural Indian-English voice needs a different voice source.

**Needs the owner's input before going further**

- Real address, phone, email and opening hours.
- Real doctors, specialities, consulting days, hours and consultation lengths.
- Real consultation fees, or a decision not to quote fees.
- Approved wording for every answer, including CGHS/ECHS and the after-hours greeting.
- Permission to use the clinic's name and colours on a public page.

**Possible next phases** (none of these are built)

1. Staff login and proper protection for patient data.
2. Real clinic details and approved answers in place of the samples.
3. A live AI model behind the same approved-answers and booking rules.
4. A real phone line or WhatsApp number in place of the simulation.
5. Reminders and confirmations sent to patients.
6. Procedure scheduling and longer booking windows.

## 6. Verification record

Run on Wednesday 14 October 2026 against a freshly reset demo database, in Firefox 157 (driven
automatically, sound output silenced), at 1366×768 for staff and call screens and 390 px wide for
the patient assistant.

| Step | Check | Result |
| --- | --- | --- |
| a | Website assistant answers the clinic-hours question | Passed: approved hours text shown |
| b | Website assistant books a consultation | Passed: three times offered, booking #5 saved as PENDING |
| c | Clinical question creates a callback task | Passed: no advice given, callback C-1 created as OPEN |
| d | Call simulation creates a booking | Passed: booking #6, call outcome BOOKING_CREATED |
| e | Dashboard shows booking, callback and AI call activity | Passed: both AI_DEMO bookings, the callback task and the call log listed |
| f | Duplicate booking is refused | Passed: "This slot has just been booked. Please choose another available time." |
| g | Sunday request explains the closure | Passed: "…closed on Sunday. The next available appointments are on Monday." |

Layout: no horizontal scrolling or clipped controls on the dashboard and call demo at 1366×768, or
on the patient assistant at 390 px. The call screen fits one laptop screen without scrolling.

Not verified by a person: what the voice sounds like, and behaviour in browsers other than Firefox.

## 7. One-page owner-demo checklist

**Before**

- [ ] `scripts/reset_demo.py --yes` run; app started; three tabs open
- [ ] Test speaker heard (or decided to present without sound)
- [ ] Dashboard shows 4 sample bookings, 0 callbacks, no call activity

**Show**

- [ ] Opening-hours answer
- [ ] Sunday closure explanation
- [ ] Booking through the website assistant → PENDING
- [ ] Medical question refused → callback task
- [ ] Booking on the simulated call → outcome recorded
- [ ] Dashboard: confirm a booking, complete a callback, AI call activity
- [ ] (If asked) double-booking refused

**Say**

- [ ] Sample data only; simulation, not a real phone line; nothing recorded
- [ ] No medical advice, ever; staff call back
- [ ] Not production-ready; needs login, real details and owner-approved wording

**After**

- [ ] Note the owner's corrections to hours, doctors, fees and wording
- [ ] Agree which next phase matters most
- [ ] Reset the demo again before the next showing
