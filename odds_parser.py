"""
Το raw response του API-Football για odds είναι "βαθύ" (πολλά bookmakers,
πολλά markets το καθένα). Εδώ το μετατρέπουμε σε ένα απλό dict
{"Over 2.5 Goals": {"odds": 1.85, "source": "Bet365"}, ...}.

Αν έστω μία από τις PREFERRED_BOOKMAKERS (config.py) έχει τιμή για ένα market,
χρησιμοποιούμε ΜΟΝΟ αυτές (μέσο όρο αν είναι παραπάνω από μία). Αλλιώς πέφτουμε
πίσω στον μέσο όρο ΟΛΩΝ των διαθέσιμων bookmakers, με ένδειξη ότι είναι
"μέσος όρος αγοράς" (όχι συγκεκριμένη στοιχηματική).
"""

import statistics

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
                label = str(val.get("value") or "")  # ασφάλεια -- μερικά bookmakers δίνουν αριθμό αντί για κείμενο
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
    Χρησιμοποιούμε ΔΙΑΜΕΣΟ (median) αντί για μέσο όρο -- πολύ πιο ανθεκτικό σε
    ακραίες/"χαλασμένες" τιμές που εμφανίζονται καμιά φορά σε λιγότερο "ρευστά"
    markets (π.χ. κόρνερ σε μικρότερες λίγκες).
    """
    if not entries:
        return None

    preferred_entries = [(odd, name) for odd, name in entries if _matches_preferred(name)]

    if preferred_entries:
        odds_values = [odd for odd, _ in preferred_entries]
        names = sorted(set(name for _, name in preferred_entries))
        median_odd = statistics.median(odds_values)
        source = names[0] if len(names) == 1 else f"{', '.join(names)} (διάμεσος)"
        return {"odds": median_odd, "source": source}

    odds_values = [odd for odd, _ in entries]
    median_odd = statistics.median(odds_values)
    return {"odds": median_odd, "source": f"Διάμεσος αγοράς ({len(entries)} bookmakers)"}


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
                label = str(val.get("value") or "")
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


ANYTIME_SCORER_BET_NAMES = {"anytime goalscorer", "goalscorer anytime", "to score anytime", "player to score"}
FIRST_SCORER_BET_NAMES = {"first goalscorer", "first player to score"}


def parse_scorer_odds_raw(fixture_odds_response, bet_names):
    """
    Επιστρέφει {player_name_label: {"odds": float, "source": str}} -- ΧΩΡΙΣ ταίριασμα
    σε player_id ακόμα (αυτό γίνεται στο main.py με το scorer_matcher).
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
            if bet_name_l not in bet_names:
                continue
            for val in bet.get("values", []):
                label = str(val.get("value") or "")  # ασφάλεια -- μερικά bookmakers δίνουν αριθμό αντί για κείμενο
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue
                collected.setdefault(label, []).append((odd, bm_name))

    for label, entries in collected.items():
        picked = _pick_odds(entries)
        if picked:
            result[label] = picked

    return result


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


# ══════════════════ ΚΥΜΑ 2 — Parsing νέων markets ═══════════════

DNB_BET_NAMES = {"draw no bet"}
DOUBLE_CHANCE_BET_NAMES = {"double chance"}
HTFT_BET_NAMES = {"ht/ft", "half time/full time", "halftime/fulltime"}
CORRECT_SCORE_BET_NAMES = {"exact score", "correct score"}
ASIAN_HANDICAP_BET_NAMES = {"asian handicap"}
TEAM_GOALS_BET_NAMES = {"home team total goals", "away team total goals", "team total goals"}
CLEAN_SHEET_BET_NAMES = {"clean sheet - home", "clean sheet - away", "clean sheet"}


def parse_dnb_odds(raw):
    collected = _collect_values(raw, DNB_BET_NAMES)
    result = {}
    label_map = {"home": "DNB Home", "away": "DNB Away"}
    for label, entries in collected.items():
        key = label_map.get(label.lower())
        if key:
            picked = _pick_odds(entries)
            if picked:
                result[key] = picked
    return result


def parse_double_chance_odds(raw):
    collected = _collect_values(raw, DOUBLE_CHANCE_BET_NAMES)
    result = {}
    # Το API-Football συνήθως δίνει labels όπως "Home/Draw", "Draw/Away", "Home/Away"
    label_map = {
        "home/draw": "Double Chance: 1X", "1x": "Double Chance: 1X",
        "draw/away": "Double Chance: X2", "x2": "Double Chance: X2",
        "home/away": "Double Chance: 12", "12": "Double Chance: 12",
    }
    for label, entries in collected.items():
        key = label_map.get(label.lower().replace(" ", ""))
        if key:
            picked = _pick_odds(entries)
            if picked:
                result[key] = picked
    return result


def parse_ht_ft_odds(raw):
    collected = _collect_values(raw, HTFT_BET_NAMES)
    result = {}
    for label, entries in collected.items():
        # Κανονικοποίηση label σε μορφή "1/1", "X/2" κλπ.
        norm = (
            label.replace("Home", "1").replace("Draw", "X").replace("Away", "2")
            .replace(" ", "").replace("-", "/")
        )
        picked = _pick_odds(entries)
        if picked:
            result[f"HT/FT: {norm}"] = picked
    return result


def parse_correct_score_odds(raw):
    collected = _collect_values(raw, CORRECT_SCORE_BET_NAMES)
    result = {}
    for label, entries in collected.items():
        norm = label.replace(":", "-").replace(" ", "")
        picked = _pick_odds(entries)
        if picked:
            result[f"Correct Score: {norm}"] = picked
    return result


def parse_asian_handicap_odds(raw):
    collected = _collect_values(raw, ASIAN_HANDICAP_BET_NAMES)
    result = {}
    for label, entries in collected.items():
        # label π.χ. "Home -1.5" ή "Away +1.5"
        parts = label.split()
        if len(parts) != 2:
            continue
        side, handicap = parts
        picked = _pick_odds(entries)
        if picked:
            result[f"Asian Handicap {side}: {handicap}"] = picked
    return result


def parse_team_goals_odds(raw):
    """Over/Under γκολ συγκεκριμένης ομάδας."""
    result = {}
    if not raw:
        return result
    bookmakers = raw.get("bookmakers", [])
    collected = {}
    for bm in bookmakers:
        bm_name = bm.get("name", "")
        for bet in bm.get("bets", []):
            bet_name_l = bet.get("name", "").lower()
            if "team" not in bet_name_l or "total" not in bet_name_l:
                continue
            side = "Home" if "home" in bet_name_l else ("Away" if "away" in bet_name_l else None)
            if not side:
                continue
            for val in bet.get("values", []):
                label = str(val.get("value") or "")
                if not label.lower().startswith("over"):
                    continue
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue
                key = (side, label)
                collected.setdefault(key, []).append((odd, bm_name))

    for (side, label), entries in collected.items():
        picked = _pick_odds(entries)
        if picked:
            result[f"{side} Team {label} Goals"] = picked
    return result


def parse_clean_sheet_odds(raw):
    result = {}
    if not raw:
        return result
    bookmakers = raw.get("bookmakers", [])
    collected = {}
    for bm in bookmakers:
        bm_name = bm.get("name", "")
        for bet in bm.get("bets", []):
            bet_name_l = bet.get("name", "").lower()
            if "clean sheet" not in bet_name_l:
                continue
            side = "Home" if "home" in bet_name_l else ("Away" if "away" in bet_name_l else None)
            if not side:
                continue
            for val in bet.get("values", []):
                label = str(val.get("value") or "").lower()
                if label != "yes":
                    continue
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue
                collected.setdefault(side, []).append((odd, bm_name))

    for side, entries in collected.items():
        picked = _pick_odds(entries)
        if picked:
            result[f"{side} Clean Sheet"] = picked
    return result


def parse_multi_goals_odds(raw):
    """
    Σύνολο γκολ σε εύρος (π.χ. 'Multi Goals' market: '2-3', '4-6' κλπ).
    Δεν είμαστε 100% σίγουροι για το ακριβές όνομα bet type στο API-Football --
    matching με keyword "goal" στο όνομα ΚΑΙ label της μορφής "N-M".
    """
    import re
    result = {}
    if not raw:
        return result
    bookmakers = raw.get("bookmakers", [])
    collected = {}
    for bm in bookmakers:
        bm_name = bm.get("name", "")
        for bet in bm.get("bets", []):
            bet_name_l = bet.get("name", "").lower()
            if "goal" not in bet_name_l or "over" in bet_name_l or "under" in bet_name_l:
                continue  # αποφεύγουμε clash με Goals O/U
            for val in bet.get("values", []):
                label = str(val.get("value") or "").strip()
                if not re.fullmatch(r"\d+-\d+", label):
                    continue
                try:
                    odd = float(val.get("odd"))
                except (TypeError, ValueError):
                    continue
                collected.setdefault(label, []).append((odd, bm_name))

    for label, entries in collected.items():
        picked = _pick_odds(entries)
        if picked:
            result[f"Multi Goals: {label}"] = picked
    return result


def parse_wave2_odds(raw):
    """Ενοποιημένο dict για όλα τα markets Κύματος 2."""
    result = {}
    result.update(parse_dnb_odds(raw))
    result.update(parse_double_chance_odds(raw))
    result.update(parse_ht_ft_odds(raw))
    result.update(parse_correct_score_odds(raw))
    result.update(parse_asian_handicap_odds(raw))
    result.update(parse_team_goals_odds(raw))
    result.update(parse_clean_sheet_odds(raw))
    result.update(parse_multi_goals_odds(raw))
    return result
