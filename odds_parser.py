"""
Το raw response του API-Football για odds είναι "βαθύ" (πολλά bookmakers,
πολλά markets το καθένα). Εδώ το μετατρέπουμε σε ένα απλό dict
{"Over 2.5 Goals": 1.85, "BTTS Yes": 1.65, ...} παίρνοντας τον ΜΕΣΟ ΟΡΟ
όλων των bookmakers που το προσφέρουν (πιο σταθερό από ένα μόνο bookmaker).
"""

GOALS_OU_BET_NAMES = {"goals over/under", "over/under"}
BTTS_BET_NAMES = {"both teams score", "both teams to score"}
MATCH_WINNER_BET_NAMES = {"match winner", "fulltime result", "1x2", "full time result"}
NEXT_GOAL_BET_NAMES = {"next goal"}


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

    winner_values = _collect_values(fixture_odds_response, MATCH_WINNER_BET_NAMES)
    label_map = {"home": "Home Win", "draw": "Draw", "away": "Away Win"}
    for label, odds_list in winner_values.items():
        key = label_map.get(label.lower())
        if key:
            result[key] = sum(odds_list) / len(odds_list)

    next_goal_values = _collect_values(fixture_odds_response, NEXT_GOAL_BET_NAMES)
    next_goal_map = {
        "home": "Next Goal Home", "home team": "Next Goal Home",
        "away": "Next Goal Away", "away team": "Next Goal Away",
        "no goal": "Next Goal No Goal", "none": "Next Goal No Goal",
        "neither": "Next Goal No Goal", "no more goals": "Next Goal No Goal",
    }
    for label, odds_list in next_goal_values.items():
        key = next_goal_map.get(label.lower())
        if key:
            result[key] = sum(odds_list) / len(odds_list)

    return result
