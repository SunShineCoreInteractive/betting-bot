"""
Μετράει πόσες προβλέψεις κέρδισαν/έχασαν, ανά κανάλι, από την τελευταία φορά
που στάλθηκε απολογισμός. Στέλνει περιοδικά συνοπτικό μήνυμα στο κανάλι
"Statistics Bet". Ίδιος τρόπος μόνιμης αποθήκευσης με το results_tracker.py
-- επιβιώνει σε redeploy.
"""

import os
import json
import time
import logging

import config

logger = logging.getLogger("stats_tracker")

_stats = {"period_start": time.time(), "by_channel": {}}

_STORAGE_PATH = os.path.join(config.PERSISTENT_DATA_DIR, "stats_tracker.json")


def _save():
    try:
        os.makedirs(config.PERSISTENT_DATA_DIR, exist_ok=True)
        with open(_STORAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(_stats, f, ensure_ascii=False)
    except Exception:
        logger.exception("Δεν κατάφερα να αποθηκεύσω στατιστικά στο δίσκο -- συνεχίζω χωρίς μονιμότητα")


def load():
    """Καλείται ρητά από main.py στο startup(), ΑΦΟΥ έχει ρυθμιστεί το logging."""
    global _stats
    try:
        if not os.path.exists(_STORAGE_PATH):
            logger.info("Δεν βρέθηκαν προηγούμενα στατιστικά -- ξεκινάμε νέα περίοδο μέτρησης")
            return
        with open(_STORAGE_PATH, "r", encoding="utf-8") as f:
            _stats = json.load(f)
        logger.info("Φορτώθηκαν στατιστικά από το δίσκο (περίοδος από %s)", _stats.get("period_start"))
    except Exception:
        logger.exception("Δεν κατάφερα να φορτώσω στατιστικά από το δίσκο -- ξεκινάμε καθαρά")


def record_result(channel_key, won):
    """won: True/False -- αγνοούμε 'PUSH' (δεν μετράει ούτε ως κέρδος ούτε ως χάσιμο)."""
    if won not in (True, False):
        return
    ch = _stats["by_channel"].setdefault(channel_key, {"won": 0, "lost": 0})
    ch["won" if won else "lost"] += 1
    _save()


def get_and_reset_summary():
    """Παίρνει "φωτογραφία" των τρεχόντων στατιστικών και μηδενίζει τον μετρητή
    για τη ΕΠΟΜΕΝΗ περίοδο (ώστε ο επόμενος απολογισμός να δείχνει μόνο τα
    ΝΕΑ αποτελέσματα, όχι σωρευτικά από την αρχή του χρόνου)."""
    global _stats
    snapshot = _stats
    _stats = {"period_start": time.time(), "by_channel": {}}
    _save()
    return snapshot
