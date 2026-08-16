"""
Θυμάται τι έστειλε το πρόγραμμα (ποιος αγώνας, ποιο market, ποιο κανάλι) και,
όταν ο/οι αγώνας/ες τελειώσουν, στέλνει follow-up μήνυμα: ΚΕΡΔΙΣΕ / ΕΧΑΣΕ.

Λειτουργεί και για συνδυασμούς (Παρολί/Bet Builder): το αποτέλεσμα στέλνεται
μόνο όταν ΟΛΟΙ οι αγώνες του συνδυασμού έχουν τελειώσει, και είναι "ΚΕΡΔΙΣΕ"
μόνο αν κερδίσουν ΟΛΕΣ οι επιλογές.
"""

import time
import logging

logger = logging.getLogger("results_tracker")

_pending = []
_next_id = 1


def add_pending(channel, description, legs):
    """
    legs: λίστα από (fixture_id, market_name)
    description: το κείμενο που θα εμφανιστεί στο follow-up μήνυμα
                 (π.χ. "Arsenal vs Brighton — BTTS Yes")
    """
    global _next_id
    entry = {
        "id": _next_id,
        "channel": channel,
        "description": description,
        "legs": legs,
        "results": {},   # fixture_id -> True/False/None (άγνωστο ακόμα)
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
