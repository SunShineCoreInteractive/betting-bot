"""
Θυμάται τι έστειλε το πρόγραμμα (ποιος αγώνας, ποιο market, ποιο κανάλι) και,
όταν ο/οι αγώνας/ες τελειώσουν, ΕΠΕΞΕΡΓΑΖΕΤΑΙ το ίδιο μήνυμα προσθέτοντας
✅ ΚΕΡΔΙΣΕ / ❌ ΕΧΑΣΕ, αντί να στέλνει νέο μήνυμα.

Λειτουργεί και για συνδυασμούς (Combo Bets): το αποτέλεσμα ενημερώνεται
μόνο όταν ΟΛΟΙ οι αγώνες του συνδυασμού έχουν τελειώσει, και είναι "ΚΕΡΔΙΣΕ"
μόνο αν κερδίσουν ΟΛΕΣ οι επιλογές.

ΜΟΝΙΜΗ ΑΠΟΘΗΚΕΥΣΗ: η λίστα εκκρεμών προβλέψεων γράφεται σε αρχείο (Render
Disk) μετά από κάθε αλλαγή, ώστε να ΕΠΙΒΙΩΝΕΙ σε redeploy/restart -- πριν,
κάθε redeploy "ξέχναγε" τις εκκρεμείς προβλέψεις και δεν έπαιρναν ποτέ
ΚΕΡΔΙΣΕ/ΕΧΑΣΕ.
"""

import os
import json
import time
import logging

import config

logger = logging.getLogger("results_tracker")

_pending = []
_next_id = 1

_STORAGE_PATH = os.path.join(config.PERSISTENT_DATA_DIR, "results_tracker.json")


def _save():
    """Γράφει την τρέχουσα κατάσταση στο δίσκο. Αν ο δίσκος δεν υπάρχει
    (π.χ. δεν έχει προστεθεί Render Disk ακόμα), απλά το προσπερνάει σιωπηλά
    -- το σύστημα συνεχίζει να δουλεύει, απλά χωρίς μονιμότητα."""
    try:
        os.makedirs(config.PERSISTENT_DATA_DIR, exist_ok=True)
        # Το "results" dict έχει int κλειδιά -- το JSON θέλει string κλειδιά
        serializable = []
        for entry in _pending:
            entry_copy = dict(entry)
            entry_copy["results"] = {str(k): v for k, v in entry["results"].items()}
            serializable.append(entry_copy)

        with open(_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump({"next_id": _next_id, "pending": serializable}, f, ensure_ascii=False)
    except Exception:
        logger.exception("Δεν κατάφερα να αποθηκεύσω στο δίσκο (%s) -- συνεχίζω χωρίς μονιμότητα", _STORAGE_PATH)


def _load():
    global _pending, _next_id
    try:
        if not os.path.exists(_STORAGE_PATH):
            logger.info("Δεν βρέθηκε προηγούμενη αποθήκευση (%s) -- ξεκινάμε καθαρά", _STORAGE_PATH)
            return
        with open(_STORAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _next_id = data.get("next_id", 1)
        loaded = data.get("pending", [])
        for entry in loaded:
            entry["results"] = {int(k): v for k, v in entry.get("results", {}).items()}
        _pending = loaded
        logger.info("Φορτώθηκαν %s εκκρεμείς προβλέψεις από το δίσκο (επιβίωσαν το redeploy)", len(_pending))
    except Exception:
        logger.exception("Δεν κατάφερα να φορτώσω από το δίσκο (%s) -- ξεκινάμε καθαρά", _STORAGE_PATH)


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
    _save()
    return entry["id"]


def get_pending():
    return list(_pending)


def save():
    """Δημόσια συνάρτηση -- κάλεσέ την αφού αλλάξεις entry['results'][i] απευθείας,
    ώστε να αποθηκευτεί η πρόοδος ακόμα κι αν δεν έχει ολοκληρωθεί όλο το entry."""
    _save()


def remove(entry_id):
    global _pending
    _pending = [p for p in _pending if p["id"] != entry_id]
    _save()


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
        _save()


# Φορτώνουμε ό,τι υπάρχει ήδη στο δίσκο κατά την εκκίνηση
_load()
