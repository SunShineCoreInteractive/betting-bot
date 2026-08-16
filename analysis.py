"""
Το "μυαλό" του συστήματος -- Φάση 1.

Markets που καλύπτονται τώρα: Goals Over/Under, BTTS, Team Over/Under, Handicap (Asian).
Corners / Κάρτες / Παίκτες: Φάση 2 (χρειάζονται per-fixture στατιστικά, πιο ακριβό σε calls).

Μέθοδος: Poisson goal model.
  1. Υπολογίζουμε τη "δυνατότητα επίθεσης" και "αδυναμία άμυνας" κάθε ομάδας
     από τον μέσο όρο γκολ που έβαλε/δέχτηκε στους τελευταίους Ν αγώνες.
  2. Εκτιμούμε το αναμενόμενο γκολ (expected goals) κάθε ομάδας για ΑΥΤΟΝ
     τον αγώνα, συνδυάζοντας επίθεση-Α με άμυνα-Β (και αντίστροφα).
  3. Από το expected goals, η κατανομή Poisson δίνει την πιθανότητα για
     οποιοδήποτε σκορ / Over-Under / BTTS.
  4. Συγκρίνουμε με το implied probability της απόδοσης bookmaker -> edge.
"""

import math
import logging
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger("analysis")


@dataclass
class Prediction:
    market: str          # π.χ. "Over 2.5 Goals", "BTTS Yes"
    model_prob: float     # η δική μας εκτίμηση (0-1)
    odds: Optional[float] = None
    implied_prob: Optional[float] = None
    edge: Optional[float] = None
    basis: str = ""       # σύντομη εξήγηση
    source: str = ""      # ποια στοιχηματική δίνει αυτή την απόδοση
    player_id: Optional[int] = None   # μόνο για markets σκόρερ


# ── Poisson βοηθητικά ────────────────────────────────────────────

def _poisson_pmf(k, lam):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _poisson_cdf(k, lam):
    return sum(_poisson_pmf(i, lam) for i in range(0, k + 1))


def prob_over(line, lam_home, lam_away, max_goals=10):
    """P(σύνολο γκολ > line) δεδομένων δύο ανεξάρτητων Poisson (home, away)."""
    threshold = math.floor(line)  # π.χ. line=2.5 -> threshold=2 (over σημαίνει >=3)
    p_under_or_equal = 0.0
    for total in range(0, threshold + 1):
        # P(home + away == total)
        p_total = 0.0
        for h in range(0, total + 1):
            a = total - h
            if a < 0 or a > max_goals:
                continue
            p_total += _poisson_pmf(h, lam_home) * _poisson_pmf(a, lam_away)
        p_under_or_equal += p_total
    return max(0.0, min(1.0, 1 - p_under_or_equal))


def prob_btts_yes(lam_home, lam_away):
    p_home_scores = 1 - _poisson_pmf(0, lam_home)
    p_away_scores = 1 - _poisson_pmf(0, lam_away)
    return p_home_scores * p_away_scores


def prob_match_result(lam_home, lam_away, max_goals=10):
    """Επιστρέφει (p_home_win, p_draw, p_away_win) -- 1-Χ-2."""
    p_home_win, p_draw, p_away_win = 0.0, 0.0, 0.0
    for h in range(0, max_goals + 1):
        for a in range(0, max_goals + 1):
            p = _poisson_pmf(h, lam_home) * _poisson_pmf(a, lam_away)
            if h > a:
                p_home_win += p
            elif h == a:
                p_draw += p
            else:
                p_away_win += p
    return p_home_win, p_draw, p_away_win


def prob_match_result_live(score_home, score_away, lam_home_remaining, lam_away_remaining, max_goals=10):
    """1-Χ-2 στο live -- προσθέτει τα εναπομείναντα αναμενόμενα γκολ στο ήδη υπάρχον σκορ."""
    p_home_win, p_draw, p_away_win = 0.0, 0.0, 0.0
    for h_add in range(0, max_goals + 1):
        for a_add in range(0, max_goals + 1):
            p = _poisson_pmf(h_add, lam_home_remaining) * _poisson_pmf(a_add, lam_away_remaining)
            final_h = (score_home or 0) + h_add
            final_a = (score_away or 0) + a_add
            if final_h > final_a:
                p_home_win += p
            elif final_h == final_a:
                p_draw += p
            else:
                p_away_win += p
    return p_home_win, p_draw, p_away_win


def prob_team_over(line, lam_team):
    threshold = math.floor(line)
    return max(0.0, min(1.0, 1 - _poisson_cdf(threshold, lam_team)))


def prob_handicap_home(handicap, lam_home, lam_away, max_goals=10):
    """
    P(home καλύπτει το ασιατικό handicap).
    handicap θετικό = το home team ξεκινάει με "μειονέκτημα" (favorite),
    handicap αρνητικό = το home team ξεκινάει με "πλεονέκτημα" (underdog).
    Χρησιμοποιούμε τη σύμβαση: home_score + handicap > away_score -> win.
    """
    p_win = 0.0
    for h in range(0, max_goals + 1):
        for a in range(0, max_goals + 1):
            if h + handicap > a:
                p_win += _poisson_pmf(h, lam_home) * _poisson_pmf(a, lam_away)
    return max(0.0, min(1.0, p_win))


# ── Εκτίμηση expected goals από πρόσφατη φόρμα ──────────────────

def compute_expected_goals(team_stats_home, team_stats_away, league_avg_goals=2.6):
    """
    team_stats_* : dict με τουλάχιστον
        {"avg_scored": float, "avg_conceded": float, "sample_size": int}
    Επιστρέφει (lam_home, lam_away) -- expected goals για ΑΥΤΟΝ τον αγώνα.
    """
    league_avg_half = league_avg_goals / 2  # μέσος όρος ανά ομάδα/ματς

    home_attack = team_stats_home["avg_scored"] / league_avg_half
    home_defense = team_stats_home["avg_conceded"] / league_avg_half
    away_attack = team_stats_away["avg_scored"] / league_avg_half
    away_defense = team_stats_away["avg_conceded"] / league_avg_half

    lam_home = home_attack * away_defense * league_avg_half
    lam_away = away_attack * home_defense * league_avg_half

    return max(0.05, lam_home), max(0.05, lam_away)


def team_form_from_fixtures(recent_fixtures, team_id):
    """
    Παίρνει τη λίστα πρόσφατων αγώνων μιας ομάδας (από api_football.get_team_recent_fixtures)
    και υπολογίζει avg_scored / avg_conceded / sample_size.
    """
    scored, conceded, n = 0, 0, 0
    for f in recent_fixtures:
        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]
        if goals_home is None or goals_away is None:
            continue  # αγώνας χωρίς τελικό σκορ ακόμα
        if team_id == home_id:
            scored += goals_home
            conceded += goals_away
            n += 1
        elif team_id == away_id:
            scored += goals_away
            conceded += goals_home
            n += 1

    if n == 0:
        return {"avg_scored": 1.3, "avg_conceded": 1.3, "sample_size": 0}

    return {"avg_scored": scored / n, "avg_conceded": conceded / n, "sample_size": n}


# ── Odds βοηθητικά ───────────────────────────────────────────────

def implied_probability(decimal_odds):
    if not decimal_odds or decimal_odds <= 1.0:
        return None
    return 1 / decimal_odds


def calculate_edge(model_prob, decimal_odds):
    implied = implied_probability(decimal_odds)
    if implied is None:
        return None
    return model_prob - implied


def is_value_bet(model_prob, decimal_odds, threshold=None):
    threshold = threshold if threshold is not None else config.VALUE_EDGE_THRESHOLD
    edge = calculate_edge(model_prob, decimal_odds)
    return edge is not None and edge >= threshold, edge


# ── Συνδυασμοί (Παρολί / Bet Builder) ────────────────────────────

def combine_parlay(legs):
    """
    legs: list of Prediction, ΚΑΘΕ ένα από διαφορετικό αγώνα.
    Υπολογίζει συνδυασμένη πιθανότητα (πολλαπλασιαστική -- ανεξάρτητα ματς)
    και συνδυασμένη απόδοση.
    """
    combined_prob = 1.0
    combined_odds = 1.0
    for leg in legs:
        combined_prob *= leg.model_prob
        combined_odds *= (leg.odds or 0)
    return combined_prob, combined_odds


def combine_bet_builder(legs):
    """
    legs: list of Prediction, ΟΛΑ από τον ΙΔΙΟ αγώνα (άρα πιθανώς συσχετισμένα).
    Εφαρμόζουμε "ποινή συσχέτισης" -- συντηρητική προσαρμογή γιατί δεν είναι
    στατιστικά ανεξάρτητα events.
    """
    combined_prob = 1.0
    for i, leg in enumerate(legs):
        penalty = config.BET_BUILDER_CORRELATION_PENALTY ** i
        combined_prob *= leg.model_prob * penalty
    fair_odds = (1 / combined_prob) if combined_prob > 0 else None
    return combined_prob, fair_odds


# ── Κύρια συνάρτηση ανάλυσης ενός αγώνα (Φάση 1 markets) ────────

def analyze_fixture_goals_markets(lam_home, lam_away, odds_lookup, sample_size):
    """
    odds_lookup: dict {"Over 2.5": 1.85, "Under 2.5": 1.95, "BTTS Yes": 1.65, ...}
                 (γεμίζει από το parsing των prematch/live odds -- δες telegram_sender/main)
    Επιστρέφει λίστα από Prediction που περνάνε το φίλτρο value edge.
    Αν sample_size < MIN_SAMPLE_SIZE, δεν βγάζει καμία πρόβλεψη (όχι αρκετό ιστορικό).
    """
    if sample_size < config.MIN_SAMPLE_SIZE:
        return []

    predictions = []

    lines_to_check = [1.5, 2.5, 3.5]
    for line in lines_to_check:
        p_over = prob_over(line, lam_home, lam_away)
        market_name = f"Over {line} Goals"
        odds_info = odds_lookup.get(market_name)
        if odds_info:
            odds = odds_info["odds"]
            ok, edge = is_value_bet(p_over, odds)
            if ok:
                predictions.append(Prediction(
                    market=market_name, model_prob=p_over, odds=odds,
                    implied_prob=implied_probability(odds), edge=edge,
                    basis=f"Εκτιμώμενα γκολ αγώνα: {lam_home + lam_away:.2f}",
                    source=odds_info["source"],
                ))

    p_btts = prob_btts_yes(lam_home, lam_away)
    odds_info = odds_lookup.get("BTTS Yes")
    if odds_info:
        odds = odds_info["odds"]
        ok, edge = is_value_bet(p_btts, odds)
        if ok:
            predictions.append(Prediction(
                market="BTTS Yes", model_prob=p_btts, odds=odds,
                implied_prob=implied_probability(odds), edge=edge,
                basis=f"xG home {lam_home:.2f} / away {lam_away:.2f}",
                source=odds_info["source"],
            ))

    p_home_win, p_draw, p_away_win = prob_match_result(lam_home, lam_away)
    for market_name, p in [("Home Win", p_home_win), ("Draw", p_draw), ("Away Win", p_away_win)]:
        odds_info = odds_lookup.get(market_name)
        if odds_info:
            odds = odds_info["odds"]
            ok, edge = is_value_bet(p, odds)
            if ok:
                predictions.append(Prediction(
                    market=market_name, model_prob=p, odds=odds,
                    implied_prob=implied_probability(odds), edge=edge,
                    basis=f"xG home {lam_home:.2f} / away {lam_away:.2f}",
                    source=odds_info["source"],
                ))

    return predictions


# ── Αξιολόγηση αποτελέσματος (μετά το τέλος του αγώνα) ──────────

def evaluate_market_result(market_name, score_home, score_away):
    """
    Επιστρέφει True (κέρδισε) / False (έχασε) / None (δεν αναγνωρίζεται το market).
    Λειτουργεί με τελικό σκορ (μετά τη λήξη).
    """
    if score_home is None or score_away is None:
        return None

    if market_name.startswith("Over"):
        try:
            line = float(market_name.split()[1])
        except (IndexError, ValueError):
            return None
        return (score_home + score_away) > line

    if market_name == "BTTS Yes":
        return score_home > 0 and score_away > 0

    if market_name == "Home Win":
        return score_home > score_away
    if market_name == "Draw":
        return score_home == score_away
    if market_name == "Away Win":
        return score_away > score_home

    return None


def evaluate_stat_market_result(market_name, total_stat_value):
    """
    Για markets τύπου 'Over 9.5 Corners' / 'Over 3.5 Cards' -- total_stat_value
    είναι το τελικό άθροισμα (και των δύο ομάδων) κόρνερ ή καρτών.
    """
    if total_stat_value is None:
        return None
    for suffix in ("Corners", "Cards"):
        if market_name.endswith(suffix) and market_name.startswith("Over"):
            try:
                line = float(market_name.split()[1])
            except (IndexError, ValueError):
                return None
            return total_stat_value > line
    return None


# ── Σκόρερ (Φάση 2β) ──────────────────────────────────────────────

def compute_player_expected_goals(player_stats, team_avg_goals_per_match, team_lam_this_match):
    """
    Εκτιμά το αναμενόμενο γκολ ενός παίκτη ΓΙ' ΑΥΤΟΝ τον αγώνα, με βάση το
    ιστορικό "μερίδιό" του πάνω στα γκολ της ομάδας.
    """
    if player_stats["minutes"] < config.SCORER_MIN_MINUTES or team_avg_goals_per_match <= 0:
        return 0.0

    player_goals_per_90 = player_stats["goals"] / (player_stats["minutes"] / 90)
    team_goals_per_90 = team_avg_goals_per_match  # προσέγγιση: ~90λεπτος αγώνας

    share = player_goals_per_90 / team_goals_per_90 if team_goals_per_90 > 0 else 0
    share = max(0.0, min(share, 1.0))  # ασφάλεια -- ένας παίκτης δεν παίρνει >100% των γκολ

    return team_lam_this_match * share


def prob_anytime_scorer(player_lam):
    return 1 - _poisson_pmf(0, player_lam)


def prob_first_scorer(player_lam, total_match_lam):
    if total_match_lam <= 0:
        return 0.0
    return player_lam / total_match_lam


def evaluate_scorer_result(market_name, events, player_id):
    """
    market_name: "Anytime Goalscorer: <name>" ή "First Goalscorer: <name>"
    events: το τελικό χρονολόγιο γεγονότων (api_football.get_fixture_events)
    """
    goal_events = [e for e in events if e.get("type") == "Goal"]
    if not goal_events:
        return False  # κανένα γκολ -> κανείς δεν σκόραρε

    scorers = [e.get("player", {}).get("id") for e in goal_events]

    if market_name.startswith("Anytime Goalscorer"):
        return player_id in scorers

    if market_name.startswith("First Goalscorer"):
        goal_events_sorted = sorted(
            goal_events,
            key=lambda e: (
                (e.get("time", {}).get("elapsed") or 0),
                (e.get("time", {}).get("extra") or 0),
            ),
        )
        return goal_events_sorted[0].get("player", {}).get("id") == player_id

    return None


# ── Κόρνερ / Κάρτες (Φάση 2) ──────────────────────────────────────

def compute_expected_corners(home_corner_form, away_corner_form):
    """Ίδια λογική επίθεσης/άμυνας με τα γκολ -- ίδια πεδία (avg_scored/avg_conceded)."""
    return compute_expected_goals(home_corner_form, away_corner_form, league_avg_goals=config.LEAGUE_AVG_CORNERS)


def compute_expected_cards(home_cards_form, away_cards_form):
    """Οι κάρτες ΔΕΝ έχουν 'άμυνα' -- είναι απλά η δική της τάση κάθε ομάδας."""
    return home_cards_form["avg"], away_cards_form["avg"]


def analyze_corners_cards_markets(lam_corners_home, lam_corners_away,
                                   lam_cards_home, lam_cards_away,
                                   odds_lookup, corners_sample, cards_sample):
    predictions = []

    if corners_sample >= config.MIN_SAMPLE_SIZE_CORNERS_CARDS:
        for line in config.CORNER_LINES:
            p_over = prob_over(line, lam_corners_home, lam_corners_away)
            market_name = f"Over {line} Corners"
            odds_info = odds_lookup.get(market_name)
            if odds_info:
                odds = odds_info["odds"]
                ok, edge = is_value_bet(p_over, odds)
                if ok:
                    predictions.append(Prediction(
                        market=market_name, model_prob=p_over, odds=odds,
                        implied_prob=implied_probability(odds), edge=edge,
                        basis=f"Εκτιμώμενα κόρνερ αγώνα: {lam_corners_home + lam_corners_away:.1f}",
                        source=odds_info["source"],
                    ))

    if cards_sample >= config.MIN_SAMPLE_SIZE_CORNERS_CARDS:
        for line in config.CARD_LINES:
            p_over = prob_over(line, lam_cards_home, lam_cards_away)
            market_name = f"Over {line} Cards"
            odds_info = odds_lookup.get(market_name)
            if odds_info:
                odds = odds_info["odds"]
                ok, edge = is_value_bet(p_over, odds)
                if ok:
                    predictions.append(Prediction(
                        market=market_name, model_prob=p_over, odds=odds,
                        implied_prob=implied_probability(odds), edge=edge,
                        basis=f"Εκτιμώμενες κάρτες αγώνα: {lam_cards_home + lam_cards_away:.1f}",
                        source=odds_info["source"],
                    ))

    return predictions


def analyze_corners_cards_markets_live(
    current_corners_home, current_corners_away, current_cards_home, current_cards_away,
    elapsed_minutes, lam_corners_home_full, lam_corners_away_full,
    lam_cards_home_full, lam_cards_away_full,
    odds_lookup, corners_sample, cards_sample,
):
    predictions = []
    elapsed = min(elapsed_minutes or 0, 90)
    remaining_fraction = max(0.0, (90 - elapsed) / 90)
    if remaining_fraction <= 0:
        return predictions

    if corners_sample >= config.MIN_SAMPLE_SIZE_CORNERS_CARDS:
        lam_home_rem = lam_corners_home_full * remaining_fraction
        lam_away_rem = lam_corners_away_full * remaining_fraction
        current_total = (current_corners_home or 0) + (current_corners_away or 0)
        for line in config.CORNER_LINES:
            needed = line - current_total
            if needed <= 0:
                continue
            p_over = prob_over(needed, lam_home_rem, lam_away_rem)
            market_name = f"Over {line} Corners"
            odds_info = odds_lookup.get(market_name)
            if odds_info:
                odds = odds_info["odds"]
                ok, edge = is_value_bet(p_over, odds)
                if ok:
                    predictions.append(Prediction(
                        market=market_name, model_prob=p_over, odds=odds,
                        implied_prob=implied_probability(odds), edge=edge,
                        basis=f"{elapsed}': {int(current_total)} κόρνερ μέχρι τώρα, χρειάζονται {needed:.1f} ακόμα",
                        source=odds_info["source"],
                    ))

    if cards_sample >= config.MIN_SAMPLE_SIZE_CORNERS_CARDS:
        lam_home_rem = lam_cards_home_full * remaining_fraction
        lam_away_rem = lam_cards_away_full * remaining_fraction
        current_total = (current_cards_home or 0) + (current_cards_away or 0)
        for line in config.CARD_LINES:
            needed = line - current_total
            if needed <= 0:
                continue
            p_over = prob_over(needed, lam_home_rem, lam_away_rem)
            market_name = f"Over {line} Cards"
            odds_info = odds_lookup.get(market_name)
            if odds_info:
                odds = odds_info["odds"]
                ok, edge = is_value_bet(p_over, odds)
                if ok:
                    predictions.append(Prediction(
                        market=market_name, model_prob=p_over, odds=odds,
                        implied_prob=implied_probability(odds), edge=edge,
                        basis=f"{elapsed}': {int(current_total)} κάρτες μέχρι τώρα, χρειάζονται {needed:.1f} ακόμα",
                        source=odds_info["source"],
                    ))

    return predictions


# ── Επόμενο Γκολ (live) ──────────────────────────────────────────

def prob_next_goal(lam_home_remaining, lam_away_remaining):
    """
    Επιστρέφει (p_home_next, p_away_next, p_no_goal) για το υπόλοιπο του αγώνα.
    Λογική: δύο ανεξάρτητες "γεννήτριες" γκολ -- η πιθανότητα να έρθει πρώτο
    το γκολ της home είναι ανάλογη του μεριδίου της στο συνολικό αναμενόμενο
    γκολ, εφόσον μπει έστω ένα ακόμα γκολ στον αγώνα.
    """
    total_remaining = lam_home_remaining + lam_away_remaining
    if total_remaining <= 0:
        return 0.0, 0.0, 1.0

    p_no_goal = _poisson_pmf(0, total_remaining)
    p_at_least_one = 1 - p_no_goal

    p_home_next = p_at_least_one * (lam_home_remaining / total_remaining)
    p_away_next = p_at_least_one * (lam_away_remaining / total_remaining)
    return p_home_next, p_away_next, p_no_goal


def evaluate_next_goal_result(market_name, events, elapsed_at_send, home_team_id):
    """
    events: λίστα από το api_football.get_fixture_events (τελικό, μετά τη λήξη).
    elapsed_at_send: το λεπτό του αγώνα τη στιγμή που στάλθηκε η πρόβλεψη.
    Επιστρέφει True/False (None δεν επιστρέφεται εδώ -- caller κρίνει βάσει status).
    """
    goal_events = [
        e for e in events
        if e.get("type") == "Goal"
        and (e.get("time", {}).get("elapsed") or 0) > (elapsed_at_send or 0)
    ]
    goal_events.sort(key=lambda e: (
        e.get("time", {}).get("elapsed") or 0,
        e.get("time", {}).get("extra") or 0,
    ))

    if not goal_events:
        actual = "No Goal"
    else:
        first_goal_team_id = goal_events[0].get("team", {}).get("id")
        actual = "Home" if first_goal_team_id == home_team_id else "Away"

    if market_name == "Next Goal Home":
        return actual == "Home"
    if market_name == "Next Goal Away":
        return actual == "Away"
    if market_name == "Next Goal No Goal":
        return actual == "No Goal"
    return None


# ── Live ανάλυση (Φάση 1) -- ΣΩΣΤΗ εκδοχή που κοιτάει σκορ + χρόνο ──────

def analyze_fixture_goals_markets_live(
    score_home, score_away, elapsed_minutes,
    lam_home_full, lam_away_full, odds_lookup, sample_size,
):
    """
    Σε αντίθεση με το analyze_fixture_goals_markets (pre-match), εδώ:
      1. Παίρνουμε υπόψη τα γκολ που έχουν ΗΔΗ σκοραριστεί
      2. Προσαρμόζουμε το αναμενόμενο γκολ στον χρόνο που ΑΠΟΜΕΝΕΙ, όχι σε
         ολόκληρο το ματς
      3. Αν το μοντέλο δίνει εξωπραγματικά ψηλό σύνολο (πιθανό σημάδι
         αναξιόπιστων δεδομένων), δεν στέλνουμε καμία πρόβλεψη
    """
    if sample_size < config.MIN_SAMPLE_SIZE:
        return []

    total_full_match = lam_home_full + lam_away_full
    if total_full_match > config.MAX_PLAUSIBLE_TOTAL_GOALS:
        logger.warning(
            "Live: μη ρεαλιστικό expected goals (%.2f) -- παραλείπεται", total_full_match
        )
        return []

    elapsed = min(elapsed_minutes or 0, 90)
    remaining_fraction = max(0.0, (90 - elapsed) / 90)

    lam_home_remaining = lam_home_full * remaining_fraction
    lam_away_remaining = lam_away_full * remaining_fraction

    current_total = (score_home or 0) + (score_away or 0)

    predictions = []

    for line in [1.5, 2.5, 3.5]:
        needed = line - current_total
        if needed <= 0:
            continue  # ήδη καλυμμένο -- δεν έχει νόημα ως "πρόβλεψη"
        if remaining_fraction <= 0:
            continue  # δεν απομένει χρόνος

        p_over = prob_over(needed, lam_home_remaining, lam_away_remaining)
        market_name = f"Over {line} Goals"
        odds_info = odds_lookup.get(market_name)
        if odds_info:
            odds = odds_info["odds"]
            ok, edge = is_value_bet(p_over, odds)
            if ok:
                predictions.append(Prediction(
                    market=market_name, model_prob=p_over, odds=odds,
                    implied_prob=implied_probability(odds), edge=edge,
                    basis=(
                        f"Τρέχον σκορ {int(score_home or 0)}-{int(score_away or 0)}, "
                        f"{elapsed}' -- χρειάζονται {needed:.1f} ακόμα γκολ, "
                        f"εκτιμώμενα στον χρόνο που απομένει: "
                        f"{lam_home_remaining + lam_away_remaining:.2f}"
                    ),
                    source=odds_info["source"],
                ))

    # BTTS -- λαμβάνει υπόψη αν κάποια ομάδα έχει ήδη σκοράρει
    already_home = (score_home or 0) > 0
    already_away = (score_away or 0) > 0
    odds_info_btts = odds_lookup.get("BTTS Yes")
    if odds_info_btts and not (already_home and already_away) and remaining_fraction > 0:
        if already_home:
            p_btts = 1 - _poisson_pmf(0, lam_away_remaining)
            basis = f"{elapsed}': home ήδη σκόραρε, χρειάζεται away (xG remaining {lam_away_remaining:.2f})"
        elif already_away:
            p_btts = 1 - _poisson_pmf(0, lam_home_remaining)
            basis = f"{elapsed}': away ήδη σκόραρε, χρειάζεται home (xG remaining {lam_home_remaining:.2f})"
        else:
            p_home_scores = 1 - _poisson_pmf(0, lam_home_remaining)
            p_away_scores = 1 - _poisson_pmf(0, lam_away_remaining)
            p_btts = p_home_scores * p_away_scores
            basis = f"{elapsed}': κανείς δεν έχει σκοράρει ακόμα, εκτίμηση στον χρόνο που απομένει"

        odds = odds_info_btts["odds"]
        ok, edge = is_value_bet(p_btts, odds)
        if ok:
            predictions.append(Prediction(
                market="BTTS Yes", model_prob=p_btts, odds=odds,
                implied_prob=implied_probability(odds), edge=edge, basis=basis,
                source=odds_info_btts["source"],
            ))

    # 1-Χ-2 live -- βάσει τρέχοντος σκορ + εναπομείναντος χρόνου
    if remaining_fraction > 0:
        p_home_win, p_draw, p_away_win = prob_match_result_live(
            score_home, score_away, lam_home_remaining, lam_away_remaining
        )
        for market_name, p in [("Home Win", p_home_win), ("Draw", p_draw), ("Away Win", p_away_win)]:
            odds_info = odds_lookup.get(market_name)
            if odds_info:
                odds = odds_info["odds"]
                ok, edge = is_value_bet(p, odds)
                if ok:
                    predictions.append(Prediction(
                        market=market_name, model_prob=p, odds=odds,
                        implied_prob=implied_probability(odds), edge=edge,
                        basis=(
                            f"{elapsed}': τρέχον σκορ {int(score_home or 0)}-{int(score_away or 0)}, "
                            f"εναπομείναντα xG {lam_home_remaining:.2f}/{lam_away_remaining:.2f}"
                        ),
                        source=odds_info["source"],
                    ))

        # Επόμενο Γκολ
        p_home_next, p_away_next, p_no_goal = prob_next_goal(lam_home_remaining, lam_away_remaining)
        for market_name, p in [
            ("Next Goal Home", p_home_next),
            ("Next Goal Away", p_away_next),
            ("Next Goal No Goal", p_no_goal),
        ]:
            odds_info = odds_lookup.get(market_name)
            if odds_info:
                odds = odds_info["odds"]
                ok, edge = is_value_bet(p, odds)
                if ok:
                    predictions.append(Prediction(
                        market=market_name, model_prob=p, odds=odds,
                        implied_prob=implied_probability(odds), edge=edge,
                        basis=f"{elapsed}': εναπομείναντα xG {lam_home_remaining:.2f}/{lam_away_remaining:.2f}",
                        source=odds_info["source"],
                    ))

    return predictions
