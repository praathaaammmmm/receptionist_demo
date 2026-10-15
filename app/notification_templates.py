"""Editable message templates for the demo Notification Centre.

DEMO SIMULATION: nothing in this app sends a message. These templates only
produce the preview text shown in the outbox.

Wording rules for anyone editing these:
- no treatment prices or fees, no clinical advice, no promises about outcomes;
- only the placeholders below are available:
  {patient} {clinic} {phone} {date} {time} {doctor} {service}
"""

CHANNELS = {"WHATSAPP": "WhatsApp", "EMAIL": "Email"}

TEMPLATES = {
    "APPOINTMENT_CONFIRMATION": {
        "label": "Appointment confirmation",
        "subject": "Your appointment at {clinic} is confirmed",
        "body": (
            "Hello {patient}, your appointment at {clinic} is confirmed for {date} at {time} with {doctor}. "
            "Please arrive 10 minutes early. To change or cancel it, call us on {phone}."
        ),
    },
    "APPOINTMENT_REMINDER": {
        "label": "Appointment reminder",
        "subject": "Reminder: your appointment at {clinic}",
        "body": (
            "Hello {patient}, this is a reminder of your appointment at {clinic} on {date} at {time} with {doctor}. "
            "If you can no longer attend, please call us on {phone}."
        ),
    },
    "APPOINTMENT_CANCELLATION": {
        "label": "Cancellation update",
        "subject": "Your appointment at {clinic} has been cancelled",
        "body": (
            "Hello {patient}, your appointment at {clinic} on {date} at {time} with {doctor} has been cancelled. "
            "To book another time, call us on {phone}."
        ),
    },
    "WAITLIST_OFFER": {
        "label": "Waitlist slot offer",
        "subject": "A consultation time is available at {clinic}",
        "body": (
            "Hello {patient}, a consultation time has become available at {clinic}: {date} at {time} with {doctor}. "
            "It is not reserved for you yet. If you would like it, please call us on {phone}."
        ),
    },
    "CALLBACK_ACKNOWLEDGEMENT": {
        "label": "Callback acknowledgement",
        "subject": "We have received your request",
        "body": (
            "Hello {patient}, {clinic} has received your request for a call. "
            "Our staff will contact you during clinic hours."
        ),
    },
}

# Confirmed appointments starting within this many hours get a reminder queued.
REMINDER_HOURS_BEFORE = 24
