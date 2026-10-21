"""Voice Agent Phase 1: approved knowledge, runtime call context and safety policy.

Groundwork for a later virtual receptionist. Nothing here places or receives a call,
listens to a microphone, talks to an LLM, books an appointment or writes to the
database. The website assistant (app/knowledge.py, app/services/assistant.py) and the
demo clinic configuration are separate and are not used or changed by this package.

  knowledge.py  approved clinic facts, kept apart from the demo database values
  context.py    runtime call context: IST time, open/closed, transfer window, caller number
  phone.py      Indian mobile-number normalisation and spoken/masked forms
  wording.py    every spoken line in English, Hindi and Hinglish
  policy.py     rule-based classifier and the emergency, clinical, unknown, transfer and callback paths
  prompt.py     system prompt renderer for a later LLM (not connected)
  schemas.py    typed results, callback details and tool contracts
"""
