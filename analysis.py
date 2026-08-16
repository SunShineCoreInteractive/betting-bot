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
        odds = odds_lookup.get(market_name)
        if odds:
            ok, edge = is_value_bet(p_over, odds)
            if ok:
                predictions.append(Prediction(
                    market=market_name, model_prob=p_over, odds=odds,
                    implied_prob=implied_probability(odds), edge=edge,
                    basis=f"Εκτιμώμενα γκολ αγώνα: {lam_home + lam_away:.2f}",
                ))

    p_btts = prob_btts_yes(lam_home, lam_away)
    odds_btts = odds_lookup.get("BTTS Yes")
    if odds_btts:
        ok, edge = is_value_bet(p_btts, odds_btts)
        if ok:
            predictions.append(Prediction(
                market="BTTS Yes", model_prob=p_btts, odds=odds_btts,
                implied_prob=implied_probability(odds_btts), edge=edge,
                basis=f"xG home {lam_home:.2f} / away {lam_away:.2f}",
            ))

    return predictions
