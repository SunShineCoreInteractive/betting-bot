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
    consensus: bool = False   # True αν ≥ODDS_CONSENSUS_MIN_BOOKS συμφωνούν εντός spread
    book_count: int = 0       # πόσα bookmakers μέσα στο spread γύρω από τη διάμεσο


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
    
    Εφαρμόζει:
      1. HOME_ADVANTAGE_FACTOR: η home ομάδα σκοράρει παραπάνω, η away λιγότερο
      2. OVERDISPERSION_CORRECTION: Poisson δεν είναι perfect για ποδόσφαιρο
    """
    league_avg_half = league_avg_goals / 2  # μέσος όρος ανά ομάδα/ματς

    home_attack = team_stats_home["avg_scored"] / league_avg_half
    home_defense = team_stats_home["avg_conceded"] / league_avg_half
    away_attack = team_stats_away["avg_scored"] / league_avg_half
    away_defense = team_stats_away["avg_conceded"] / league_avg_half

    lam_home = home_attack * away_defense * league_avg_half
    lam_away = away_attack * home_defense * league_avg_half
    
    # Home advantage: η home ομάδα έχει ~12% περισσότερα αναμενόμενα γκολ
    lam_home *= config.HOME_ADVANTAGE_FACTOR
    lam_away /= config.HOME_ADVANTAGE_FACTOR
    
    # Overdispersion correction: το ποδόσφαιρο έχει περισσότερες "εκπλήξεις" 
    # από το Poisson -- αυξάνουμε ελαφρώς τα expected goals για να το αντισταθμίσουμε
    overdispersion = getattr(config, 'OVERDISPERSION_CORRECTION', 1.0)
    lam_home *= overdispersion
    lam_away *= overdispersion

    return max(0.05, lam_home), max(0.05, lam_away)


def team_form_from_fixtures(recent_fixtures, team_id, opponent_strength_fn=None, league_avg_goals=2.6):
    """
    Παίρνει τη λίστα πρόσφατων αγώνων μιας ομάδας (από api_football.get_team_recent_fixtures)
    και υπολογίζει avg_scored / avg_conceded / sample_size.

    Με FORM_DECAY_FACTOR: ο πιο πρόσφατος αγώνας έχει βάρος 1.0,
    ο προηγούμενος 0.90, ο πριν από αυτόν 0.90^2, κ.λπ.
    Αυτό δίνει μεγαλύτερη βαρύτητα σε πρόσφατες τάσεις.

    opponent_strength_fn(opponent_id, league_id, season) -> (attack_avg, defense_avg) | None:
    αν δοθεί, κάθε goals_scored/conceded σταθμίζεται με τη δύναμη ΤΟΥ ΣΥΓΚΕΚΡΙΜΕΝΟΥ αντιπάλου
    εκείνου του αγώνα -- ένα γκολ σε δυνατή άμυνα μετράει παραπάνω από ένα γκολ σε αδύναμη.
    Χωρίς αυτό (None ή αποτυχία lookup), fallback στην παλιά raw συμπεριφορά (βάρος 1.0).
    """
    league_avg_half = league_avg_goals / 2
    scored_weighted, conceded_weighted, weight_sum = 0, 0, 0

    for idx, f in enumerate(recent_fixtures):
        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]
        if goals_home is None or goals_away is None:
            continue  # αγώνας χωρίς τελικό σκορ ακόμα

        # Βάρος που φθίνει με την ηλικία του αγώνα
        weight = (config.FORM_DECAY_FACTOR ** idx)

        if team_id == home_id:
            team_scored, team_conceded, opponent_id = goals_home, goals_away, away_id
        elif team_id == away_id:
            team_scored, team_conceded, opponent_id = goals_away, goals_home, home_id
        else:
            continue

        # Opponent adjustment: αν ο αντίπαλος έχει καλή άμυνα (defense_avg χαμηλό),
        # ένα γκολ εναντίον του αξίζει παραπάνω -- αναπροσαρμόζουμε αναλογικά με το league average.
        adj_factor = 1.0
        if opponent_strength_fn is not None:
            opp_league_id = f["league"]["id"]
            opp_season = f["league"]["season"]
            strength = opponent_strength_fn(opponent_id, opp_league_id, opp_season)
            if strength is not None:
                opp_defense, opp_attack = strength[1], strength[0]
                # scored ενάντια σε καλή άμυνα (defense_avg < league_avg_half) -> ανεβαίνει
                scored_adj = team_scored * (league_avg_half / opp_defense) if opp_defense > 0 else team_scored
                # conceded από δυνατή επίθεση (attack_avg > league_avg_half) -> μειώνεται σχετικά
                conceded_adj = team_conceded * (league_avg_half / opp_attack) if opp_attack > 0 else team_conceded
                scored_weighted += scored_adj * weight
                conceded_weighted += conceded_adj * weight
                weight_sum += weight
                continue

        scored_weighted += team_scored * weight
        conceded_weighted += team_conceded * weight
        weight_sum += weight

    if weight_sum == 0:
        return {"avg_scored": 1.3, "avg_conceded": 1.3, "sample_size": 0}

    # Η μέση τιμή βασίζεται στο weighted άθροισμα / το άθροισμα των βαρών
    n_unweighted = int(weight_sum)  # περίπου πόσοι αγώνες "μετράνε"
    return {
        "avg_scored": scored_weighted / weight_sum,
        "avg_conceded": conceded_weighted / weight_sum,
        "sample_size": max(n_unweighted, 1)  # τουλάχιστον 1 για να μην σπάσει το MIN_SAMPLE_SIZE check
    }


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


def is_value_bet(model_prob, decimal_odds, threshold=None, min_prob=None):
    threshold = threshold if threshold is not None else config.VALUE_EDGE_THRESHOLD
    min_prob = min_prob if min_prob is not None else config.MIN_MODEL_PROBABILITY
    if model_prob < min_prob:
        return False, None  # κάτω από το ελάχιστο σιγουριάς -- δεν στέλνεται, ό,τι edge κι αν έχει
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


# ══════════════════ ΚΥΜΑ 2 — Νέα markets ═══════════════════════

# ── DNB (Draw No Bet) ────────────────────────────────────────────

def prob_dnb(lam_home, lam_away):
    """
    Επιστρέφει (p_dnb_home, p_dnb_away) -- πιθανότητα να "κερδίσει" το στοίχημα
    ΔΕΔΟΜΕΝΟΥ ότι δεν είναι ισοπαλία (σε ισοπαλία επιστρέφεται το ποντάρισμα,
    οπότε το μοντέλο υπολογίζει value μόνο πάνω στο "ποιος κερδίζει αν κερδίσει κάποιος").
    """
    p_home, p_draw, p_away = prob_match_result(lam_home, lam_away)
    denom = p_home + p_away
    if denom <= 0:
        return 0.0, 0.0
    return p_home / denom, p_away / denom


# ── Διπλή Ευκαιρία (Double Chance) ───────────────────────────────

def prob_double_chance(lam_home, lam_away):
    """Επιστρέφει (p_1X, p_X2, p_12)."""
    p_home, p_draw, p_away = prob_match_result(lam_home, lam_away)
    return p_home + p_draw, p_draw + p_away, p_home + p_away


# ── Ημίχρονο / Τελικό (HT/FT) ────────────────────────────────────

# Εμπειρικό μερίδιο γκολ που πέφτει στο 1ο ημίχρονο (τα ματς έχουν συνήθως
# λίγο περισσότερα γκολ στο 2ο ημίχρονο). Απλοποίηση: ίδιο ποσοστό και για
# τις δύο ομάδες, χωρίς συσχέτιση ανάμεσα στα δύο ημίχρονα.
FIRST_HALF_GOAL_SHARE = 0.45


def prob_ht_ft(lam_home, lam_away):
    """
    Επιστρέφει dict {"1/1": p, "1/X": p, ..., "2/2": p} -- 9 συνδυασμοί.
    ΑΠΛΟΠΟΙΗΣΗ: το 1ο ημίχρονο και το τελικό αποτέλεσμα αντιμετωπίζονται σαν
    ανεξάρτητα Poisson (στην πραγματικότητα έχουν κάποια συσχέτιση -- δεν την
    αποτυπώνουμε, το σημειώνουμε ρητά ως γνωστό περιορισμό).
    """
    lam_home_1h = lam_home * FIRST_HALF_GOAL_SHARE
    lam_away_1h = lam_away * FIRST_HALF_GOAL_SHARE

    ht_home, ht_draw, ht_away = prob_match_result(lam_home_1h, lam_away_1h)
    ft_home, ft_draw, ft_away = prob_match_result(lam_home, lam_away)

    ht_map = {"1": ht_home, "X": ht_draw, "2": ht_away}
    ft_map = {"1": ft_home, "X": ft_draw, "2": ft_away}

    result = {}
    for ht_label, ht_p in ht_map.items():
        for ft_label, ft_p in ft_map.items():
            result[f"{ht_label}/{ft_label}"] = ht_p * ft_p
    return result


# ── Ακριβές Σκορ (Correct Score) ─────────────────────────────────

def prob_correct_score(lam_home, lam_away, max_goals=5):
    """Επιστρέφει dict {"2-1": p, "0-0": p, ...} για σκορ έως max_goals-max_goals."""
    result = {}
    for h in range(0, max_goals + 1):
        for a in range(0, max_goals + 1):
            result[f"{h}-{a}"] = _poisson_pmf(h, lam_home) * _poisson_pmf(a, lam_away)
    return result


# ── Σύνολο Γκολ σε εύρος (Multi Goals) ───────────────────────────

def prob_goals_in_range(low, high, lam_home, lam_away, max_goals=12):
    """P(low <= σύνολο γκολ <= high)."""
    total_p = 0.0
    for h in range(0, max_goals + 1):
        for a in range(0, max_goals + 1):
            total = h + a
            if low <= total <= high:
                total_p += _poisson_pmf(h, lam_home) * _poisson_pmf(a, lam_away)
    return total_p


# ── Ειδικά Ομάδων: Clean Sheet ───────────────────────────────────

def prob_clean_sheet(lam_opponent):
    """P(η ομάδα δεν δέχεται γκολ) = P(ο αντίπαλος βάζει 0 γκολ)."""
    return _poisson_pmf(0, lam_opponent)


# ── Αξιολόγηση αποτελεσμάτων Κύματος 2 ───────────────────────────

def evaluate_wave2_market_result(market_name, score_home, score_away):
    """Αξιολογεί markets Κύματος 2. Επιστρέφει True/False/None."""
    if score_home is None or score_away is None:
        return None

    if market_name.startswith("DNB"):
        if score_home == score_away:
            return "PUSH"  # ισοπαλία -- επιστροφή ποντάρισματος, όχι κέρδος/χάσιμο
        if market_name.endswith("Home"):
            return score_home > score_away
        if market_name.endswith("Away"):
            return score_away > score_home

    if market_name.startswith("Double Chance"):
        if market_name.endswith("1X"):
            return score_home >= score_away
        if market_name.endswith("X2"):
            return score_away >= score_home
        if market_name.endswith("12"):
            return score_home != score_away

    if market_name.startswith("HT/FT"):
        # Χρειάζεται και το ημιχρονικό σκορ -- αξιολογείται ξεχωριστά, βλ. check_results
        return None

    if market_name.startswith("Correct Score"):
        try:
            label = market_name.split(":")[1].strip()
            h, a = label.split("-")
            return int(h) == score_home and int(a) == score_away
        except (IndexError, ValueError):
            return None

    if market_name.startswith("Multi Goals"):
        try:
            label = market_name.split(":")[1].strip()
            low, high = label.split("-")
            total = score_home + score_away
            return int(low) <= total <= int(high)
        except (IndexError, ValueError):
            return None

    if market_name.startswith("Home Clean Sheet"):
        return score_away == 0
    if market_name.startswith("Away Clean Sheet"):
        return score_home == 0

    if market_name.startswith("Home Team Over"):
        try:
            line = float(market_name.split()[-2])
        except (IndexError, ValueError):
            return None
        return score_home > line
    if market_name.startswith("Away Team Over"):
        try:
            line = float(market_name.split()[-2])
        except (IndexError, ValueError):
            return None
        return score_away > line

    if market_name.startswith("Asian Handicap"):
        try:
            handicap = float(market_name.split()[-1])
        except (IndexError, ValueError):
            return None
        adjusted_diff = (score_home + handicap) - score_away
        if handicap == int(handicap) and adjusted_diff == 0:
            return None  # push (ακέραιο χάντικαπ, ακριβές ισοφάρισμα) -- επιστροφή ποντάρισματος
        return adjusted_diff > 0

    return None


def evaluate_ht_ft_result(market_name, ht_home, ht_away, ft_home, ft_away):
    """
    market_name: "HT/FT: 1/1", "HT/FT: X/2" κλπ.
    Χρειάζεται ΚΑΙ το ημιχρονικό ΚΑΙ το τελικό σκορ (διαφορετικά από τα άλλα
    markets που χρειάζονται μόνο το τελικό).
    """
    if ht_home is None or ht_away is None or ft_home is None or ft_away is None:
        return None

    def _result_label(h, a):
        if h > a:
            return "1"
        if h == a:
            return "X"
        return "2"

    try:
        expected = market_name.split(":")[1].strip()
    except IndexError:
        return None

    actual = f"{_result_label(ht_home, ht_away)}/{_result_label(ft_home, ft_away)}"
    return actual == expected


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

def apply_red_card_adjustment(lam_home_remaining, lam_away_remaining, home_reds, away_reds):
    """
    Προσαρμόζει το εναπομείναν αναμενόμενο γκολ όταν υπάρχουν κόκκινες κάρτες.
    Η ομάδα με λιγότερους παίκτες σκοράρει λιγότερο -- η αντίπαλη σκοράρει
    περισσότερο, αφού παίζει έναντι αδύναμης άμυνας/λιγότερων παικτών.
    Εμπειρική εκτίμηση, όχι επιστημονικά τεκμηριωμένη -- βλ. config για τα ποσοστά.
    """
    net = (home_reds or 0) - (away_reds or 0)
    if net == 0:
        return lam_home_remaining, lam_away_remaining, ""

    if net > 0:
        # Η home ομάδα έχει περισσότερες κόκκινες -- μειονεκτεί
        reduction = min(config.RED_CARD_MAX_REDUCTION, net * config.RED_CARD_OWN_REDUCTION_PER_CARD)
        boost = min(config.RED_CARD_MAX_BOOST, net * config.RED_CARD_OPPONENT_BOOST_PER_CARD)
        lam_home_remaining *= (1 - reduction)
        lam_away_remaining *= (1 + boost)
        note = f"⚠️ Κόκκινη κάρτα home ({net}) -- προσαρμοσμένο αναμενόμενο γκολ"
    else:
        n = -net
        reduction = min(config.RED_CARD_MAX_REDUCTION, n * config.RED_CARD_OWN_REDUCTION_PER_CARD)
        boost = min(config.RED_CARD_MAX_BOOST, n * config.RED_CARD_OPPONENT_BOOST_PER_CARD)
        lam_away_remaining *= (1 - reduction)
        lam_home_remaining *= (1 + boost)
        note = f"⚠️ Κόκκινη κάρτα away ({n}) -- προσαρμοσμένο αναμενόμενο γκολ"

    return lam_home_remaining, lam_away_remaining, note


def analyze_fixture_goals_markets_live(
    score_home, score_away, elapsed_minutes,
    lam_home_full, lam_away_full, odds_lookup, sample_size,
    home_red_cards=0, away_red_cards=0,
):
    """
    Σε αντίθεση με το analyze_fixture_goals_markets (pre-match), εδώ:
      1. Παίρνουμε υπόψη τα γκολ που έχουν ΗΔΗ σκοραριστεί
      2. Προσαρμόζουμε το αναμενόμενο γκολ στον χρόνο που ΑΠΟΜΕΝΕΙ, όχι σε
         ολόκληρο το ματς
      3. Προσαρμόζουμε ΚΑΙ για κόκκινες κάρτες (αν υπάρχουν)
      4. Αν το μοντέλο δίνει εξωπραγματικά ψηλό σύνολο (πιθανό σημάδι
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

    lam_home_remaining, lam_away_remaining, red_card_note = apply_red_card_adjustment(
        lam_home_remaining, lam_away_remaining, home_red_cards, away_red_cards
    )

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
                        + (f"\n{red_card_note}" if red_card_note else "")
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
            basis = f"{elapsed}': home ήδη σκόραρε, χρειάζεται away (xG remaining {lam_away_remaining:.2f})" + (f"\n{red_card_note}" if red_card_note else "")
        elif already_away:
            p_btts = 1 - _poisson_pmf(0, lam_home_remaining)
            basis = f"{elapsed}': away ήδη σκόραρε, χρειάζεται home (xG remaining {lam_home_remaining:.2f})" + (f"\n{red_card_note}" if red_card_note else "")
        else:
            p_home_scores = 1 - _poisson_pmf(0, lam_home_remaining)
            p_away_scores = 1 - _poisson_pmf(0, lam_away_remaining)
            p_btts = p_home_scores * p_away_scores
            basis = f"{elapsed}': κανείς δεν έχει σκοράρει ακόμα, εκτίμηση στον χρόνο που απομένει" + (f"\n{red_card_note}" if red_card_note else "")

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
                            + (f"\n{red_card_note}" if red_card_note else "")
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
                        basis=f"{elapsed}': εναπομείναντα xG {lam_home_remaining:.2f}/{lam_away_remaining:.2f}" + (f"\n{red_card_note}" if red_card_note else ""),
                        source=odds_info["source"],
                    ))

    return predictions
