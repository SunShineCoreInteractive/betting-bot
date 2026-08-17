"""
Θυμάται τι έστειλε το πρόγραμμα (ποιος αγώνας, ποιο market, ποιο κανάλι) και,
όταν ο/οι αγώνας/ες τελειώσουν, ΕΠΕΞΕΡΓΑΖΕΤΑΙ το ίδιο μήνυμα προσθέτοντας
✅ ΚΕΡΔΙΣΕ / ❌ ΕΧΑΣΕ, αντί να στέλνει νέο μήνυμα.

Λειτουργεί και για συνδυασμούς (Combo Bets): το αποτέλεσμα ενημερώνεται
μόνο όταν ΟΛΟΙ οι αγώνες του συνδυασμού έχουν τελειώσει, και είναι "ΚΕΡΔΙΣΕ"
μόνο αν κερδίσουν ΟΛΕΣ οι επιλογές.
"""

import time
import logging

logger = logging.getLogger("results_tracker")

_pending = []
_next_id = 1


def add_pending(channel, message_id, original_text, legs):
    """
    channel: κλειδί από το config.BET_TYPE_CHANNELS (π.χ. "1x2", "gg_ng")
    message_id: το Telegram message_id που επιστράφηκε όταν στάλθηκε το μήνυμα
                -- χρειάζεται για να το επεξεργαστούμε αργότερα
    original_text: το ΠΛΗΡΕΣ κείμενο του μηνύματος όπως στάλθηκε (θα προστεθεί
                    το emoji ΣΤΟ ΤΕΛΟΣ αυτού, όχι σε ξεχωριστό μήνυμα)
    legs: λίστα από dicts {"fixture_id":, "market":, "elapsed_at_send": None, "home_team_id": None}
    """
    global _next_id
    entry = {
        "id": _next_id,
        "channel": channel,
        "message_id": message_id,
        "original_text": original_text,
        "legs": legs,
        "results": {},   # index στο legs -> True/False/None (άγνωστο ακόμα)
        "sent_at": time.time(),
    }
    _pending.append(entry)
    _next_id += 1
    return entry["id"]


def get_pending():
    return list(_pending)


def remove(entry_id):
    global _pending
    _pending = [p for p in _pending if p["id"] != entry_id]


def cleanup_stale(max_age_hours=48):
    """Ασφάλεια: αν κάποιος αγώνας ποτέ δεν πάρει τελικό status (π.χ. αναβλήθηκε),
    μην κρατάμε τη μνήμη για πάντα."""
    global _pending
    cutoff = time.time() - max_age_hours * 3600
    before = len(_pending)
    _pending = [p for p in _pending if p["sent_at"] > cutoff]
    removed = before - len(_pending)
    if removed:
        logger.info("Καθαρίστηκαν %s παλιές/ξεχασμένες εγγραφές αποτελεσμάτων", removed)
