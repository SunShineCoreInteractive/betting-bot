"""
Το raw response του API-Football για odds είναι "βαθύ" (πολλά bookmakers,
πολλά markets το καθένα). Εδώ το μετατρέπουμε σε ένα απλό dict
{"Over 2.5 Goals": 1.85, "BTTS Yes": 1.65, ...} παίρνοντας τον ΜΕΣΟ ΟΡΟ
όλων των bookmakers που το προσφέρουν (πιο σταθερό από ένα μόνο bookmaker).
"""

GOALS_OU_BET_NAMES = {"goals over/under", "over/under"}
BTTS_BET_NAMES = {"both teams score", "both teams to score"}


def _collect_values(fixture_odds_response, target_bet_names):
    """
    fixture_odds_response: το response[0] του /odds call για ΕΝΑ fixture
    (dict με "bookmakers": [...]).
    Επιστρέφει {value_label: [odd1, odd2, ...]} συγκεντρωμένα από όλα τα bookmakers.
    """
    collected = {}
    if not fixture_odds_response:
        return collected

    bookmakers = fixture_odds_response.get("bookmakers", [])
    for bm in bookmakers:
        for bet in bm.get("bets", []):
            bet_name_l = bet.get("name", "").lower()
            if bet_name_l not in target_bet_names:
                continue
            for val in bet.get("values", []):
                label = val.get("value")
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue
                collected.setdefault(label, []).append(odd)
    return collected


def parse_goals_and_btts_odds(fixture_odds_response):
    """
    Επιστρέφει dict έτοιμο για analysis.analyze_fixture_goals_markets:
      {"Over 2.5 Goals": 1.85, "Under 2.5 Goals": 1.95, "BTTS Yes": 1.65, ...}
    """
    result = {}

    ou_values = _collect_values(fixture_odds_response, GOALS_OU_BET_NAMES)
    for label, odds_list in ou_values.items():
        # label π.χ. "Over 2.5" ή "Under 2.5"
        avg_odd = sum(odds_list) / len(odds_list)
        result[f"{label} Goals"] = avg_odd

    btts_values = _collect_values(fixture_odds_response, BTTS_BET_NAMES)
    for label, odds_list in btts_values.items():
        avg_odd = sum(odds_list) / len(odds_list)
        if label.lower() == "yes":
            result["BTTS Yes"] = avg_odd
        elif label.lower() == "no":
            result["BTTS No"] = avg_odd

    return result
