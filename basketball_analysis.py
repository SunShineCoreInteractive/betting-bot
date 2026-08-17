"""
Στατιστικό μοντέλο για μπάσκετ. Σε αντίθεση με το ποδόσφαιρο (λίγα γκολ,
μοντέλο Poisson), το μπάσκετ έχει πολλούς πόντους -- χρησιμοποιούμε Κανονική
Κατανομή (Normal Distribution), πιο κατάλληλη για μεγάλα νούμερα.
"""

import math
import logging
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger("basketball_analysis")


@dataclass
class BballPrediction:
    market: str
    model_prob: float
    odds: Optional[float] = None
    implied_prob: Optional[float] = None
    edge: Optional[float] = None
    basis: str = ""
    source: str = ""


def _normal_cdf(x, mean=0.0, std=1.0):
    return 0.5 * (1 + math.erf((x - mean) / (std * math.sqrt(2))))


def team_scoring_form(recent_games, team_id):
    """
    recent_games: λίστα αγώνων από το API-Basketball (ήδη τελειωμένων).
    Επιστρέφει avg_scored / avg_allowed / sample_size.
    """
    scored, allowed, n = 0, 0, 0
    for g in recent_games:
        home_id = g["teams"]["home"]["id"]
        away_id = g["teams"]["away"]["id"]
        home_pts = g["scores"]["home"]["total"]
        away_pts = g["scores"]["away"]["total"]
        if home_pts is None or away_pts is None:
            continue
        if team_id == home_id:
            scored += home_pts
            allowed += away_pts
            n += 1
        elif team_id == away_id:
            scored += away_pts
            allowed += home_pts
            n += 1

    if n == 0:
        return {"avg_scored": 100.0, "avg_allowed": 100.0, "sample_size": 0}

    return {"avg_scored": scored / n, "avg_allowed": allowed / n, "sample_size": n}


def compute_expected_points(home_form, away_form, league_avg_points=105.0):
    """Ίδια λογική επίθεσης/άμυνας με το ποδόσφαιρο, προσαρμοσμένη σε πόντους μπάσκετ."""
    home_attack = home_form["avg_scored"] / league_avg_points
    home_defense = home_form["avg_allowed"] / league_avg_points
    away_attack = away_form["avg_scored"] / league_avg_points
    away_defense = away_form["avg_allowed"] / league_avg_points

    expected_home = home_attack * away_defense * league_avg_points
    expected_away = away_attack * home_defense * league_avg_points

    return expected_home, expected_away


def prob_over_points(line, total_expected, std=None):
    std = std or config.BASKETBALL_STD_TOTAL_POINTS
    return 1 - _normal_cdf(line, total_expected, std)


def prob_home_win(expected_home, expected_away, std=None):
    std = std or config.BASKETBALL_STD_POINT_DIFF
    mean_diff = expected_home - expected_away
    return 1 - _normal_cdf(0, mean_diff, std)


def implied_probability(decimal_odds):
    if not decimal_odds or decimal_odds <= 1.0:
        return None
    return 1 / decimal_odds


def is_value_bet(model_prob, decimal_odds, threshold=None):
    threshold = threshold if threshold is not None else config.VALUE_EDGE_THRESHOLD
    if model_prob < config.MIN_MODEL_PROBABILITY:
        return False, None
    implied = implied_probability(decimal_odds)
    if implied is None:
        return False, None
    edge = model_prob - implied
    return edge >= threshold, edge


def analyze_game(expected_home, expected_away, sample_size, odds_lookup):
    """odds_lookup: {"Over 215.5 Points": {"odds":, "source":}, "Home Win": {...}, "Away Win": {...}}"""
    predictions = []
    if sample_size < config.BASKETBALL_MIN_SAMPLE_SIZE:
        return predictions

    total_expected = expected_home + expected_away

    for market_name, odds_info in odds_lookup.items():
        if market_name.startswith("Over"):
            try:
                line = float(market_name.split()[1])
            except (IndexError, ValueError):
                continue
            p = prob_over_points(line, total_expected)
            ok, edge = is_value_bet(p, odds_info["odds"])
            if ok:
                predictions.append(BballPrediction(
                    market=market_name, model_prob=p, odds=odds_info["odds"],
                    implied_prob=implied_probability(odds_info["odds"]), edge=edge,
                    basis=f"Εκτιμώμενοι πόντοι αγώνα: {total_expected:.1f}",
                    source=odds_info["source"],
                ))
        elif market_name == "Home Win":
            p = prob_home_win(expected_home, expected_away)
            ok, edge = is_value_bet(p, odds_info["odds"])
            if ok:
                predictions.append(BballPrediction(
                    market=market_name, model_prob=p, odds=odds_info["odds"],
                    implied_prob=implied_probability(odds_info["odds"]), edge=edge,
                    basis=f"Εκτιμώμενο σκορ: {expected_home:.0f}-{expected_away:.0f}",
                    source=odds_info["source"],
                ))
        elif market_name == "Away Win":
            p = 1 - prob_home_win(expected_home, expected_away)
            ok, edge = is_value_bet(p, odds_info["odds"])
            if ok:
                predictions.append(BballPrediction(
                    market=market_name, model_prob=p, odds=odds_info["odds"],
                    implied_prob=implied_probability(odds_info["odds"]), edge=edge,
                    basis=f"Εκτιμώμενο σκορ: {expected_home:.0f}-{expected_away:.0f}",
                    source=odds_info["source"],
                ))

    return predictions


def evaluate_market_result(market_name, home_pts, away_pts):
    if home_pts is None or away_pts is None:
        return None
    if market_name.startswith("Over"):
        try:
            line = float(market_name.split()[1])
        except (IndexError, ValueError):
            return None
        return (home_pts + away_pts) > line
    if market_name == "Home Win":
        return home_pts > away_pts
    if market_name == "Away Win":
        return away_pts > home_pts
    return None
