"""
Parsing αποδόσεων μπάσκετ -- ίδια λογική με το ποδόσφαιρο (προτίμηση σε
συγκεκριμένες στοιχηματικές, διάμεσος αντί για μέσο όρο), αλλά προσαρμοσμένο
στη δομή του API-Basketball.
"""

import statistics

import config

TOTAL_POINTS_BET_NAMES = {"over/under", "total points", "over/under line"}
WINNER_BET_NAMES = {"home/away", "match winner", "moneyline", "winner"}


def _matches_preferred(bookmaker_name):
    name_l = (bookmaker_name or "").lower()
    return any(pref in name_l for pref in config.PREFERRED_BOOKMAKERS)


def _pick_odds(entries):
    if not entries:
        return None
    preferred = [(o, n) for o, n in entries if _matches_preferred(n)]
    if preferred:
        values = [o for o, _ in preferred]
        names = sorted(set(n for _, n in preferred))
        source = names[0] if len(names) == 1 else f"{', '.join(names)} (διάμεσος)"
        return {"odds": statistics.median(values), "source": source}
    values = [o for o, _ in entries]
    return {"odds": statistics.median(values), "source": f"Διάμεσος αγοράς ({len(entries)} bookmakers)"}


def parse_game_odds(raw_odds_response):
    """
    raw_odds_response: το response[0] του /odds?game=X (δομή API-Basketball:
    bookmakers -> bets -> values, παρόμοια με το football API).
    Επιστρέφει {"Over 215.5 Points": {...}, "Home Win": {...}, "Away Win": {...}}
    """
    result = {}
    if not raw_odds_response:
        return result

    bookmakers = raw_odds_response.get("bookmakers", [])
    ou_collected, winner_collected = {}, {}

    for bm in bookmakers:
        bm_name = bm.get("name", "")
        for bet in bm.get("bets", []):
            bet_name_l = bet.get("name", "").lower()
            for val in bet.get("values", []):
                label = (val.get("value") or "")
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue

                if bet_name_l in TOTAL_POINTS_BET_NAMES and label.lower().startswith("over"):
                    ou_collected.setdefault(label, []).append((odd, bm_name))
                elif bet_name_l in WINNER_BET_NAMES:
                    winner_collected.setdefault(label, []).append((odd, bm_name))

    for label, entries in ou_collected.items():
        picked = _pick_odds(entries)
        if picked:
            result[f"{label} Points"] = picked

    winner_map = {"home": "Home Win", "away": "Away Win"}
    for label, entries in winner_collected.items():
        key = winner_map.get(label.lower())
        if key:
            picked = _pick_odds(entries)
            if picked:
                result[key] = picked

    return result
