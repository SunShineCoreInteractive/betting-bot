"""
Το raw response του API-Football για odds είναι "βαθύ" (πολλά bookmakers,
πολλά markets το καθένα). Εδώ το μετατρέπουμε σε ένα απλό dict
{"Over 2.5 Goals": {"odds": 1.85, "source": "Bet365"}, ...}.

Αν έστω μία από τις PREFERRED_BOOKMAKERS (config.py) έχει τιμή για ένα market,
χρησιμοποιούμε ΜΟΝΟ αυτές (μέσο όρο αν είναι παραπάνω από μία). Αλλιώς πέφτουμε
πίσω στον μέσο όρο ΟΛΩΝ των διαθέσιμων bookmakers, με ένδειξη ότι είναι
"μέσος όρος αγοράς" (όχι συγκεκριμένη στοιχηματική).
"""

import config

GOALS_OU_BET_NAMES = {"goals over/under", "over/under"}
BTTS_BET_NAMES = {"both teams score", "both teams to score"}
MATCH_WINNER_BET_NAMES = {"match winner", "fulltime result", "1x2", "full time result"}
NEXT_GOAL_BET_NAMES = {"next goal"}


def _matches_preferred(bookmaker_name):
    name_l = (bookmaker_name or "").lower()
    return any(pref in name_l for pref in config.PREFERRED_BOOKMAKERS)


def _collect_values(fixture_odds_response, target_bet_names):
    """
    Επιστρέφει {value_label: [(odd, bookmaker_name), ...]} συγκεντρωμένα
    από όλα τα bookmakers που έχουν αυτό το bet type.
    """
    collected = {}
    if not fixture_odds_response:
        return collected

    bookmakers = fixture_odds_response.get("bookmakers", [])
    for bm in bookmakers:
        bm_name = bm.get("name", "")
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
                collected.setdefault(label, []).append((odd, bm_name))
    return collected


def _pick_odds(entries):
    """
    entries: [(odd, bookmaker_name), ...] για ΕΝΑ market/outcome.
    Επιστρέφει {"odds": float, "source": str} -- προτιμώντας τις PREFERRED_BOOKMAKERS.
    """
    if not entries:
        return None

    preferred_entries = [(odd, name) for odd, name in entries if _matches_preferred(name)]

    if preferred_entries:
        odds_values = [odd for odd, _ in preferred_entries]
        names = sorted(set(name for _, name in preferred_entries))
        avg_odd = sum(odds_values) / len(odds_values)
        source = names[0] if len(names) == 1 else f"{', '.join(names)} (μ.ό.)"
        return {"odds": avg_odd, "source": source}

    odds_values = [odd for odd, _ in entries]
    avg_odd = sum(odds_values) / len(odds_values)
    return {"odds": avg_odd, "source": f"Μέσος όρος αγοράς ({len(entries)} bookmakers)"}


def _parse_over_under_category(fixture_odds_response, name_keyword, category_label):
    """
    Γενική συνάρτηση για markets τύπου 'Over/Under X <κατηγορία>' (κόρνερ, κάρτες κλπ).
    name_keyword: λέξη-κλειδί που πρέπει να περιέχει το όνομα του bet type (π.χ. "corner").
    category_label: πώς θα ονομαστεί στο τελικό dict (π.χ. "Corners").
    """
    result = {}
    if not fixture_odds_response:
        return result

    bookmakers = fixture_odds_response.get("bookmakers", [])
    collected = {}
    for bm in bookmakers:
        bm_name = bm.get("name", "")
        for bet in bm.get("bets", []):
            bet_name_l = bet.get("name", "").lower()
            if name_keyword not in bet_name_l:
                continue
            for val in bet.get("values", []):
                label = (val.get("value") or "")
                if not (label.lower().startswith("over") or label.lower().startswith("under")):
                    continue  # ασφάλεια -- αγνόησε π.χ. team-based κάρτες markets
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue
                collected.setdefault(label, []).append((odd, bm_name))

    for label, entries in collected.items():
        picked = _pick_odds(entries)
        if picked:
            result[f"{label} {category_label}"] = picked

    return result


def parse_corners_odds(fixture_odds_response):
    return _parse_over_under_category(fixture_odds_response, "corner", "Corners")


def parse_cards_odds(fixture_odds_response):
    return _parse_over_under_category(fixture_odds_response, "card", "Cards")


def parse_goals_and_btts_odds(fixture_odds_response):
    """
    Επιστρέφει dict market_name -> {"odds": float, "source": str}, έτοιμο
    για το analysis.py.
    """
    result = {}

    ou_values = _collect_values(fixture_odds_response, GOALS_OU_BET_NAMES)
    for label, entries in ou_values.items():
        picked = _pick_odds(entries)
        if picked:
            result[f"{label} Goals"] = picked

    btts_values = _collect_values(fixture_odds_response, BTTS_BET_NAMES)
    btts_label_map = {"yes": "BTTS Yes", "no": "BTTS No"}
    for label, entries in btts_values.items():
        key = btts_label_map.get(label.lower())
        if key:
            picked = _pick_odds(entries)
            if picked:
                result[key] = picked

    winner_values = _collect_values(fixture_odds_response, MATCH_WINNER_BET_NAMES)
    winner_label_map = {"home": "Home Win", "draw": "Draw", "away": "Away Win"}
    for label, entries in winner_values.items():
        key = winner_label_map.get(label.lower())
        if key:
            picked = _pick_odds(entries)
            if picked:
                result[key] = picked

    next_goal_values = _collect_values(fixture_odds_response, NEXT_GOAL_BET_NAMES)
    next_goal_map = {
        "home": "Next Goal Home", "home team": "Next Goal Home",
        "away": "Next Goal Away", "away team": "Next Goal Away",
        "no goal": "Next Goal No Goal", "none": "Next Goal No Goal",
        "neither": "Next Goal No Goal", "no more goals": "Next Goal No Goal",
    }
    for label, entries in next_goal_values.items():
        key = next_goal_map.get(label.lower())
        if key:
            picked = _pick_odds(entries)
            if picked:
                result[key] = picked

    return result


def parse_all_odds(fixture_odds_response):
    """Ενοποιημένο dict -- γκολ/BTTS/1X2/Επόμενο Γκολ/Κόρνερ/Κάρτες μαζί."""
    result = parse_goals_and_btts_odds(fixture_odds_response)
    result.update(parse_corners_odds(fixture_odds_response))
    result.update(parse_cards_odds(fixture_odds_response))
    return result
