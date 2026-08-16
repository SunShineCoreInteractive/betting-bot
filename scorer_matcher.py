"""
Ταιριάζει τα ονόματα παικτών όπως εμφανίζονται στις αποδόσεις (π.χ. "M. Salah")
με τα ονόματα παικτών από τη βάση μας (π.χ. "Mohamed Salah") -- δεν είναι πάντα
πανομοιότυπα, οπότε χρειάζεται "ασαφές" (fuzzy) ταίριασμα.
"""

import difflib
import re

import config


def _normalize(name):
    name = name.lower().strip()
    name = re.sub(r"[.\-']", " ", name)
    name = re.sub(r"\s+", " ", name)
    return name


def _last_name(name):
    parts = _normalize(name).split()
    return parts[-1] if parts else ""


def find_best_match(odds_label, roster_names):
    """
    odds_label: το όνομα όπως εμφανίζεται στην απόδοση (π.χ. "M. Salah")
    roster_names: dict {player_id: player_name} από τη βάση μας
    Επιστρέφει (player_id, score) ή (None, 0) αν δεν βρεθεί αρκετά καλό ταίριασμα.
    """
    label_norm = _normalize(odds_label)
    label_last = _last_name(odds_label)

    best_id, best_score = None, 0.0

    for pid, roster_name in roster_names.items():
        roster_norm = _normalize(roster_name)
        roster_last = _last_name(roster_name)

        # Βασικό σκορ: ομοιότητα ολόκληρου ονόματος
        score = difflib.SequenceMatcher(None, label_norm, roster_norm).ratio()

        # Bonus αν τα επώνυμα ταιριάζουν ακριβώς -- πολύ ισχυρό σήμα
        if label_last and roster_last and label_last == roster_last:
            score = max(score, 0.85)

        if score > best_score:
            best_score, best_id = score, pid

    if best_score >= config.SCORER_NAME_MATCH_THRESHOLD:
        return best_id, best_score
    return None, 0.0
