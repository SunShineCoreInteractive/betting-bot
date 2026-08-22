"""
Ο μαέστρος. Τρέχει συνέχεια (24ωρο loop) και:
  - κάθε MARKET_CHECK_INTERVAL_HOURS ώρες -> ελέγχει αγώνες στο κυλιόμενο παράθυρο
    (χωρίς Live -- μόνο pre-match)
  - κάθε RESULTS_CHECK_INTERVAL_MIN λεπτά  -> ελέγχει αν τελείωσαν αγώνες, και
    ΕΠΕΞΕΡΓΑΖΕΤΑΙ το αρχικό μήνυμα προσθέτοντας ✅/❌

Κάθε πρόβλεψη πηγαίνει στο δικό της κανάλι market (config.BET_TYPE_CHANNELS),
όχι σε γενικά κανάλια Μονά/Παρολί/Bet Builder όπως πριν.

Εκτελείται σαν Render "Background Worker" (συνεχής διεργασία, όχι cron).
"""

import time
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config
import api_football
import league_classifier
import analysis
import odds_parser
import telegram_sender
import sent_tracker
import results_tracker
import scorer_matcher
import stats_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

# Γεμίζει στο startup
ALLOWED_LEAGUE_IDS = set()


def startup():
    global ALLOWED_LEAGUE_IDS

    # Φορτώνουμε τις εκκρεμείς προβλέψεις από τον μόνιμο δίσκο ΠΡΩΤΑ απ' όλα
    # (τώρα που το logging λειτουργεί ήδη κανονικά, ώστε να φαίνεται το log)
    results_tracker.load()
    stats_tracker.load()

    logger.info("Ταξινόμηση λιγκών (μία φορά, cache 1 εβδομάδα)...")
    classification = league_classifier.classify_leagues()
    league_classifier.print_summary(classification)

    ALLOWED_LEAGUE_IDS = set(
        classification["tier1"]
        + classification["tier2"]
        + classification["domestic_cups"]
        + classification["international_club"]
        + classification["national_team"]
    )
    logger.info("Σύνολο εγκεκριμένων λιγκών: %s", len(ALLOWED_LEAGUE_IDS))

    # Μία φορά, καταγράφουμε όλα τα διαθέσιμα bookmakers στα Logs -- έτσι
    # μπορείς να δεις αν υπάρχει Stoiximan/Novibet/κλπ χωρίς κανένα άλλο εργαλείο.
    try:
        bookmakers = api_football.get_bookmakers()
        names = sorted(b["name"] for b in bookmakers if b.get("name"))
        logger.info("Διαθέσιμα bookmakers (%s): %s", len(names), ", ".join(names))
    except Exception:
        logger.exception("Δεν κατάφερα να τραβήξω τη λίστα bookmakers")

    # Καταγράφουμε ΚΑΙ όλα τα πραγματικά ονόματα markets (bet types) -- ώστε να
    # ξέρουμε ΣΙΓΟΥΡΑ πώς τα ονομάζει το API, αντί να μαντεύουμε (DNB, Η/Τ κλπ.)
    try:
        bet_types = api_football.get_bet_types()
        bt_names = sorted(b["name"] for b in bet_types if b.get("name"))
        logger.info("Διαθέσιμα markets/bet types (%s): %s", len(bt_names), ", ".join(bt_names))
    except Exception:
        logger.exception("Δεν κατάφερα να τραβήξω τη λίστα bet types")


def _fixture_basics(fixture):
    country = fixture["league"].get("country") or ""
    league_only = fixture["league"]["name"]
    league_display = f"{country} — {league_only}" if country else league_only
    return {
        "id": fixture["fixture"]["id"],
        "league_name": league_display,
        "league_id": fixture["league"]["id"],
        "season": fixture["league"]["season"],
        "home_id": fixture["teams"]["home"]["id"],
        "home_name": fixture["teams"]["home"]["name"],
        "away_id": fixture["teams"]["away"]["id"],
        "away_name": fixture["teams"]["away"]["name"],
        "kickoff": fixture["fixture"]["date"],
    }


ATHENS_TZ = ZoneInfo("Europe/Athens")


def _kickoff_str(iso_date):
    """Μετατρέπει την ώρα του αγώνα (UTC από το API) σε ώρα Ελλάδας."""
    dt_utc = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    dt_athens = dt_utc.astimezone(ATHENS_TZ)
    return dt_athens.strftime("%H:%M")


def _get_predictions_for_fixture(fx):
    """Pre-match μοντέλο: γκολ/BTTS/1X2 + κόρνερ/κάρτες. Επιστρέφει predictions."""
    home_recent = api_football.get_team_recent_fixtures(fx["home_id"])
    away_recent = api_football.get_team_recent_fixtures(fx["away_id"])

    league_avg_goals = api_football.get_league_avg_goals(fx["league_id"], fx["season"])
    home_form = analysis.team_form_from_fixtures(
        home_recent, fx["home_id"],
        opponent_strength_fn=api_football.get_opponent_strength, league_avg_goals=league_avg_goals,
    )
    away_form = analysis.team_form_from_fixtures(
        away_recent, fx["away_id"],
        opponent_strength_fn=api_football.get_opponent_strength, league_avg_goals=league_avg_goals,
    )
    sample_size = min(home_form["sample_size"], away_form["sample_size"])

    lam_home, lam_away = analysis.compute_expected_goals(home_form, away_form, league_avg_goals=league_avg_goals)

    odds_response = api_football.get_prematch_odds(fx["id"])
    odds_lookup = odds_parser.parse_all_odds(odds_response[0] if odds_response else {})

    predictions = analysis.analyze_fixture_goals_markets(
        lam_home, lam_away, odds_lookup, sample_size
    )

    # Κόρνερ / Κάρτες -- παραλείπονται αν πλησιάζουμε το ημερήσιο πλαφόν
    if not api_football.budget_is_low():
        try:
            home_cc = api_football.get_team_corner_card_form(fx["home_id"], home_recent)
            away_cc = api_football.get_team_corner_card_form(fx["away_id"], away_recent)
            lam_corners_home, lam_corners_away = analysis.compute_expected_corners(
                home_cc["corners"], away_cc["corners"]
            )
            lam_cards_home, lam_cards_away = analysis.compute_expected_cards(
                home_cc["cards"], away_cc["cards"]
            )
            corners_sample = min(home_cc["corners"]["sample_size"], away_cc["corners"]["sample_size"])
            cards_sample = min(home_cc["cards"]["sample_size"], away_cc["cards"]["sample_size"])
            predictions += analysis.analyze_corners_cards_markets(
                lam_corners_home, lam_corners_away, lam_cards_home, lam_cards_away,
                odds_lookup, corners_sample, cards_sample,
            )
        except Exception:
            logger.exception("Σφάλμα κόρνερ/καρτών ανάλυσης fixture %s", fx["id"])
    else:
        logger.warning("Χαμηλό ημερήσιο budget -- παραλείπονται κόρνερ/κάρτες για fixture %s", fx["id"])

    # Σκόρερ (μόνο pre-match -- χρειάζεται επίσημο line-up, επίσης παραλείπεται σε χαμηλό budget)
    if not api_football.budget_is_low():
        try:
            predictions += _analyze_scorers(fx, lam_home, lam_away, odds_response)
        except Exception:
            logger.exception("Σφάλμα ανάλυσης σκόρερ fixture %s", fx["id"])

    # Κύμα 2 -- DNB, Διπλή Ευκαιρία, Η/Τ, Ακριβές Σκορ, Σύνολο Γκολ, Ασιατικό
    # Χάντικαπ, Ειδικά Ομάδων (χρησιμοποιεί το ίδιο odds_response, καμία επιπλέον κλήση)
    try:
        predictions += _analyze_wave2_markets(fx, lam_home, lam_away, odds_response)
    except Exception:
        logger.exception("Σφάλμα ανάλυσης Κύματος 2 fixture %s", fx["id"])

    return predictions


def _analyze_wave2_markets(fx, lam_home, lam_away, odds_response):
    """DNB, Double Chance, HT/FT, Correct Score, Multi Goals, Asian Handicap, Ειδικά Ομάδων."""
    odds_lookup = odds_parser.parse_wave2_odds(odds_response[0] if odds_response else {})
    if not odds_lookup:
        return []

    predictions = []

    def _try_add(market_name, model_prob, basis, min_prob=None, edge_threshold=None):
        odds_info = odds_lookup.get(market_name)
        if not odds_info:
            return
        ok, edge = analysis.is_value_bet(
            model_prob, odds_info["odds"], threshold=edge_threshold, min_prob=min_prob
        )
        if ok:
            predictions.append(analysis.Prediction(
                market=market_name, model_prob=model_prob, odds=odds_info["odds"],
                implied_prob=analysis.implied_probability(odds_info["odds"]), edge=edge,
                basis=basis, source=odds_info["source"],
                consensus=odds_info.get("consensus", False), book_count=odds_info.get("book_count", 0),
            ))

    # DNB και Σύνολο Γκολ αφαιρέθηκαν οριστικά -- ποτέ δεν έβρισκαν αντιστοιχία
    # σε πραγματικές αποδόσεις (κανάλια dnb/multi_goals παραμένουν ανενεργά)

    # Double Chance
    p_1x, p_x2, p_12 = analysis.prob_double_chance(lam_home, lam_away)
    _try_add("Double Chance: 1X", p_1x, f"xG home {lam_home:.2f} / away {lam_away:.2f}")
    _try_add("Double Chance: X2", p_x2, f"xG home {lam_home:.2f} / away {lam_away:.2f}")
    _try_add("Double Chance: 12", p_12, f"xG home {lam_home:.2f} / away {lam_away:.2f}")

    # HT/FT
    htft_probs = analysis.prob_ht_ft(lam_home, lam_away)
    for label, p in htft_probs.items():
        _try_add(
            f"HT/FT: {label}", p,
            f"Απλοποιημένο μοντέλο (χωρίς συσχέτιση ημιχρόνων), xG {lam_home:.2f}/{lam_away:.2f}",
            min_prob=config.HTFT_MIN_PROB, edge_threshold=config.HTFT_MIN_EDGE,
        )

    # Correct Score
    cs_probs = analysis.prob_correct_score(lam_home, lam_away)
    for label, p in cs_probs.items():
        _try_add(
            f"Correct Score: {label}", p, f"xG home {lam_home:.2f} / away {lam_away:.2f}",
            min_prob=config.CORRECT_SCORE_MIN_PROB, edge_threshold=config.CORRECT_SCORE_MIN_EDGE,
        )

    # Ασιατικό Χάντικαπ -- ΜΟΝΟ η καλύτερη γραμμή ανά ΠΛΕΥΡΑ (Home/Away), όχι όλες
    # μαζί (αλλιώς "πλημμυρίζει" το κανάλι με 6-8 σχεδόν-ίδιες επιλογές για τον
    # ίδιο αγώνα και το Telegram μπλοκάρει το bot με 429 rate limit)
    ah_candidates = {"Home": [], "Away": []}
    for market_name in list(odds_lookup.keys()):
        if market_name.startswith("Asian Handicap"):
            try:
                side_part, handicap_str = market_name.split(":")
                handicap = float(handicap_str.strip())
                side = "Home" if "Home" in side_part else "Away"
                if side == "Home":
                    p = analysis.prob_handicap_home(handicap, lam_home, lam_away)
                else:
                    p = analysis.prob_handicap_home(-handicap, lam_away, lam_home)
                ah_candidates[side].append((market_name, p))
            except (IndexError, ValueError):
                continue

    for side, candidates in ah_candidates.items():
        if not candidates:
            continue
        # Διαλέγουμε τη γραμμή με το μεγαλύτερο edge (όχι απλά την πρώτη)
        best_market, best_p = None, None
        best_edge = -1
        for market_name, p in candidates:
            odds_info = odds_lookup.get(market_name)
            if not odds_info:
                continue
            edge = analysis.calculate_edge(p, odds_info["odds"])
            if edge is not None and edge > best_edge:
                best_edge, best_market, best_p = edge, market_name, p
        if best_market:
            _try_add(best_market, best_p, f"xG home {lam_home:.2f} / away {lam_away:.2f}")

    # Ειδικά Ομάδων -- Over γκολ συγκεκριμένης ομάδας. ΜΟΝΟ η καλύτερη γραμμή
    # ανά πλευρά (ίδιος λόγος με το Ασιατικό Χάντικαπ -- αποφυγή πλημμύρας)
    team_goals_candidates = {"Home": [], "Away": []}
    for market_name in list(odds_lookup.keys()):
        if "Team Over" in market_name:
            try:
                line = float(market_name.split()[3])  # "Home Team Over 1.5 Goals" -> index 3 = "1.5"
            except (IndexError, ValueError):
                continue
            side = "Home" if market_name.startswith("Home") else "Away"
            team_lam = lam_home if side == "Home" else lam_away
            p = analysis.prob_team_over(line, team_lam)
            team_goals_candidates[side].append((market_name, p, team_lam))

    for side, candidates in team_goals_candidates.items():
        best_market, best_p, best_lam, best_edge = None, None, None, -1
        for market_name, p, team_lam in candidates:
            odds_info = odds_lookup.get(market_name)
            if not odds_info:
                continue
            edge = analysis.calculate_edge(p, odds_info["odds"])
            if edge is not None and edge > best_edge:
                best_edge, best_market, best_p, best_lam = edge, market_name, p, team_lam
        if best_market:
            _try_add(best_market, best_p, f"Εκτιμώμενα γκολ ομάδας: {best_lam:.2f}")

    # Ειδικά Ομάδων -- Clean Sheet
    _try_add("Home Clean Sheet", analysis.prob_clean_sheet(lam_away), f"Αντίπαλο xG: {lam_away:.2f}")
    _try_add("Away Clean Sheet", analysis.prob_clean_sheet(lam_home), f"Αντίπαλο xG: {lam_home:.2f}")

    return predictions


def _combo_bets_family(market):
    """Απλή ομαδοποίηση ώστε να μη συνδυάζουμε δύο σχεδόν-ίδιες επιλογές (π.χ. Over 1.5 + Over 2.5)."""
    return _market_family_label(market)


def _try_combo_bet(fx, kickoff_str, all_predictions):
    """
    Διαλέγει τον καλύτερο συνδυασμό 2 markets ΙΔΙΟΥ αγώνα (π.χ. '1Χ & Over 2.5'),
    με προσαρμογή συσχέτισης, και τον επιστρέφει ως Prediction-like tuple
    (legs, combined_prob, fair_odds) -- ή None αν δεν βρεθεί αρκετά καλός συνδυασμός.
    """
    eligible = [p for p in all_predictions if p.model_prob >= config.COMBO_BETS_MIN_LEG_PROB]
    if len(eligible) < config.COMBO_BETS_MIN_LEGS:
        return None

    # 1 επιλογή ανά "οικογένεια" market -- αποφεύγουμε π.χ. δύο διαφορετικές Over γραμμές μαζί
    best_per_family = {}
    for p in eligible:
        family = _combo_bets_family(p.market)
        if family not in best_per_family or p.model_prob > best_per_family[family].model_prob:
            best_per_family[family] = p

    candidates = sorted(best_per_family.values(), key=lambda p: -(p.edge or 0))
    if len(candidates) < config.COMBO_BETS_MIN_LEGS:
        return None

    legs = candidates[:config.COMBO_BETS_MAX_LEGS]

    # Αν το ζεύγος ανήκει σε γνωστές ΙΣΧΥΡΑ συσχετισμένες οικογένειες (π.χ. Goals O/U + BTTS),
    # χρησιμοποιούμε πολύ αυστηρότερο penalty -- το κανονικό 0.90 υποεκτιμούσε τη συσχέτιση.
    families = frozenset(_combo_bets_family(leg.market) for leg in legs)
    if len(legs) == 2 and families in config.COMBO_BETS_HIGH_CORRELATION_PAIRS:
        base_penalty = config.COMBO_BETS_HIGH_CORRELATION_PENALTY
    else:
        base_penalty = config.COMBO_BETS_CORRELATION_PENALTY

    combined_prob = 1.0
    for i, leg in enumerate(legs):
        penalty = base_penalty ** i
        combined_prob *= leg.model_prob * penalty

    if combined_prob < config.COMBO_BETS_MIN_COMBINED_PROB:
        return None

    fair_odds = 1 / combined_prob if combined_prob > 0 else None
    if fair_odds is None or fair_odds < config.MIN_ODDS:
        return None

    return legs, combined_prob, fair_odds


def _analyze_scorers(fx, lam_home, lam_away, odds_response):
    """
    Προϋποθέτει διαθέσιμο line-up (συνήθως ~1 ώρα πριν την έναρξη -- ταιριάζει
    με το pre-match παράθυρό μας). Αν δεν υπάρχει ακόμα line-up, επιστρέφει [].
    odds_response: το ήδη τραβηγμένο raw αποτέλεσμα από get_prematch_odds
    (δεν ξανακαλούμε το API).
    """
    lineups = api_football.get_fixture_lineups(fx["id"])
    if not lineups or len(lineups) < 2:
        return []

    home_lineup = next((l for l in lineups if l["team"]["id"] == fx["home_id"]), None)
    away_lineup = next((l for l in lineups if l["team"]["id"] == fx["away_id"]), None)
    if not home_lineup or not away_lineup:
        return []

    home_players_stats = api_football.get_team_players_season_stats(
        fx["home_id"], fx["league_id"], fx["season"]
    )
    away_players_stats = api_football.get_team_players_season_stats(
        fx["away_id"], fx["league_id"], fx["season"]
    )

    home_avg_goals = lam_home  # η ήδη υπολογισμένη αναμενόμενη τιμή χρησιμοποιείται σαν team_goals_per_90 proxy
    away_avg_goals = lam_away
    total_match_lam = lam_home + lam_away

    anytime_odds_raw = odds_parser.parse_scorer_odds_raw(
        odds_response[0] if odds_response else {}, odds_parser.ANYTIME_SCORER_BET_NAMES,
    )
    first_odds_raw = odds_parser.parse_scorer_odds_raw(
        odds_response[0] if odds_response else {}, odds_parser.FIRST_SCORER_BET_NAMES,
    )

    predictions = []

    for lineup, players_stats, team_lam in [
        (home_lineup, home_players_stats, home_avg_goals),
        (away_lineup, away_players_stats, away_avg_goals),
    ]:
        starters = lineup.get("startXI", [])
        for entry in starters:
            player = entry.get("player", {})
            pid = player.get("id")
            pname = player.get("name")
            if not pid or pid not in players_stats:
                continue

            player_lam = analysis.compute_player_expected_goals(
                players_stats[pid], team_lam, team_lam
            )
            if player_lam <= 0:
                continue

            # Anytime Goalscorer
            if anytime_odds_raw:
                roster_names = {pid: pname}
                matched_label = None
                for label in anytime_odds_raw:
                    match_id, score = scorer_matcher.find_best_match(label, roster_names)
                    if match_id == pid:
                        matched_label = label
                        break
                if matched_label:
                    odds_info = anytime_odds_raw[matched_label]
                    p = analysis.prob_anytime_scorer(player_lam)
                    ok, edge = analysis.is_value_bet(p, odds_info["odds"])
                    if ok:
                        predictions.append(analysis.Prediction(
                            market=f"Anytime Goalscorer: {pname}", model_prob=p,
                            odds=odds_info["odds"], implied_prob=analysis.implied_probability(odds_info["odds"]),
                            edge=edge, basis=f"~{player_lam:.2f} αναμ. γκολ παίκτη αυτόν τον αγώνα",
                            source=odds_info["source"], player_id=pid,
                            consensus=odds_info.get("consensus", False), book_count=odds_info.get("book_count", 0),
                        ))

            # First Goalscorer
            if first_odds_raw:
                roster_names = {pid: pname}
                matched_label = None
                for label in first_odds_raw:
                    match_id, score = scorer_matcher.find_best_match(label, roster_names)
                    if match_id == pid:
                        matched_label = label
                        break
                if matched_label:
                    odds_info = first_odds_raw[matched_label]
                    p = analysis.prob_first_scorer(player_lam, total_match_lam)
                    ok, edge = analysis.is_value_bet(p, odds_info["odds"])
                    if ok:
                        predictions.append(analysis.Prediction(
                            market=f"First Goalscorer: {pname}", model_prob=p,
                            odds=odds_info["odds"], implied_prob=analysis.implied_probability(odds_info["odds"]),
                            edge=edge, basis=f"Μερίδιο επί συνολικών αναμ. γκολ αγώνα ({total_match_lam:.2f})",
                            source=odds_info["source"], player_id=pid,
                            consensus=odds_info.get("consensus", False), book_count=odds_info.get("book_count", 0),
                        ))

    return predictions

# ── Ταξινόμηση market -> κανάλι ─────────────────────────────────

def _market_family_label(market):
    if market.startswith("Over") and market.endswith("Goals"):
        return "Goals O/U"
    if market.startswith("BTTS"):
        return "BTTS"
    if market in ("Home Win", "Draw", "Away Win"):
        return "1X2"
    if market.endswith("Corners"):
        return "Corners"
    if market.endswith("Cards"):
        return "Cards"
    if market.startswith("Anytime Goalscorer") or market.startswith("First Goalscorer"):
        return "Scorer"
    if market.startswith("Double Chance"):
        return "Double Chance"
    if market.startswith("HT/FT"):
        return "HT/FT"
    if market.startswith("Correct Score"):
        return "Correct Score"
    if market.startswith("Asian Handicap"):
        return "Asian Handicap"
    if "Team Over" in market:
        return "Team Goals"
    if market.endswith("Clean Sheet"):
        return "Clean Sheet"
    return "Other"


def _channel_for_prediction(pred):
    family = _market_family_label(pred.market)
    return config.MARKET_FAMILY_TO_CHANNEL.get(family)


def _passes_global_filter(pred):
    """Καθολικό φίλτρο -- ΜΟΝΟ στατιστική πιθανότητα. Τα odds είναι πλέον μόνο ενημερωτικά."""
    return pred.model_prob >= config.MIN_MODEL_PROBABILITY


# ── Κύριος κύκλος ελέγχου markets (κάθε MARKET_CHECK_INTERVAL_HOURS) ──

def run_market_check():
    fixtures = api_football.get_fixtures_in_window(
        config.MARKET_CHECK_INTERVAL_HOURS, ALLOWED_LEAGUE_IDS
    )
    logger.info("Παράθυρο ελέγχου (%sω): %s αγώνες", config.MARKET_CHECK_INTERVAL_HOURS, len(fixtures))

    fixture_ids_in_window = {f["fixture"]["id"] for f in fixtures}
    for channel_key in config.BET_TYPE_CHANNELS:
        sent_tracker.clear_expired_prematch(channel_key, fixture_ids_in_window)

    market_family_counts = {}
    sent_counts = {}

    for raw_fx in fixtures:
        fx = _fixture_basics(raw_fx)
        kickoff_str = _kickoff_str(fx["kickoff"])

        try:
            predictions = _get_predictions_for_fixture(fx)
        except Exception:
            logger.exception("Σφάλμα ανάλυσης fixture %s", fx["id"])
            continue

        for p in predictions:
            family = _market_family_label(p.market)
            market_family_counts[family] = market_family_counts.get(family, 0) + 1

        for pred in predictions:
            if not _passes_global_filter(pred):
                continue

            channel_key = _channel_for_prediction(pred)
            if not channel_key:
                continue  # market χωρίς αντιστοιχισμένο κανάλι ακόμα (Κύμα 2)

            if sent_tracker.already_sent(channel_key, fx["id"], pred.market):
                continue

            text = telegram_sender.format_prediction(
                fx["league_name"], fx["home_name"], fx["away_name"], kickoff_str,
                pred.market, pred.model_prob, pred.odds, pred.edge, pred.basis, pred.source,
            )
            message_id = telegram_sender.send_message(channel_key, text)
            if message_id:
                sent_tracker.mark_sent(channel_key, fx["id"], pred.market)
                results_tracker.add_pending(
                    channel_key, message_id, text,
                    [{"fixture_id": fx["id"], "market": pred.market, "player_id": pred.player_id}],
                )
                sent_counts[channel_key] = sent_counts.get(channel_key, 0) + 1
                logger.info(
                    "Στάλθηκε [%s] %s: %s vs %s (%.0f%%, odds %.2f)",
                    channel_key, pred.market, fx["home_name"], fx["away_name"],
                    pred.model_prob * 100, pred.odds,
                )

        # Combo Bets -- 2 markets ίδιου αγώνα μαζί
        combo_result = _try_combo_bet(fx, kickoff_str, predictions)
        if combo_result:
            legs, combined_prob, fair_odds = combo_result
            combo_key = tuple(sorted(leg.market for leg in legs))
            if not sent_tracker.already_sent("combo_bets", fx["id"], combo_key):
                legs_desc = [f"{leg.market} — εκτίμηση {leg.model_prob*100:.0f}%" for leg in legs]
                text = telegram_sender.format_combo_bets(
                    fx["league_name"], fx["home_name"], fx["away_name"], kickoff_str,
                    legs_desc, combined_prob, fair_odds,
                )
                message_id = telegram_sender.send_message("combo_bets", text)
                if message_id:
                    sent_tracker.mark_sent("combo_bets", fx["id"], combo_key)
                    results_tracker.add_pending(
                        "combo_bets", message_id, text,
                        [{"fixture_id": fx["id"], "market": leg.market, "player_id": leg.player_id} for leg in legs],
                    )
                    sent_counts["combo_bets"] = sent_counts.get("combo_bets", 0) + 1
                    logger.info(
                        "Στάλθηκε [combo_bets] %s vs %s: %s",
                        fx["home_name"], fx["away_name"], " + ".join(leg.market for leg in legs),
                    )

    logger.info(
        "Διαγνωστικό markets (ΠΡΙΝ το φίλτρο) -- %s",
        ", ".join(f"{k}: {v}" for k, v in sorted(market_family_counts.items())) or "καμία πρόβλεψη καθόλου",
    )
    logger.info(
        "Στάλθηκαν ανά κανάλι -- %s",
        ", ".join(f"{k}: {v}" for k, v in sorted(sent_counts.items())) or "κανένα νέο μήνυμα",
    )


# ── Έλεγχος αποτελεσμάτων (επεξεργασία μηνύματος με ✅/❌) ─────────

def check_results():
    pending = results_tracker.get_pending()

    needed_ids = set()
    for entry in pending:
        for i, leg in enumerate(entry["legs"]):
            if entry["results"].get(i) is None:
                needed_ids.add(leg["fixture_id"])

    fixtures_by_id = {}
    needed_ids_list = list(needed_ids)
    for chunk_start in range(0, len(needed_ids_list), 20):
        chunk = needed_ids_list[chunk_start:chunk_start + 20]
        try:
            fixtures_by_id.update(api_football.get_fixtures_by_ids(chunk))
        except Exception:
            logger.exception("Σφάλμα batch ελέγχου αποτελεσμάτων για %s fixtures", len(chunk))

    for entry in pending:
        for i, leg in enumerate(entry["legs"]):
            if entry["results"].get(i) is not None:
                continue

            fixture_id = leg["fixture_id"]
            market = leg["market"]

            raw_fx = fixtures_by_id.get(fixture_id)
            if not raw_fx:
                continue
            status = raw_fx["fixture"]["status"]["short"]
            if status not in ("FT", "AET", "PEN"):
                continue

            if market.startswith("Anytime Goalscorer") or market.startswith("First Goalscorer"):
                try:
                    events = api_football.get_fixture_events(fixture_id)
                except Exception:
                    logger.exception("Σφάλμα ανάκτησης events fixture %s", fixture_id)
                    continue
                won = analysis.evaluate_scorer_result(market, events, leg.get("player_id"))
            elif market.endswith("Corners") or market.endswith("Cards"):
                try:
                    stats = api_football.get_fixture_statistics(fixture_id)
                except Exception:
                    logger.exception("Σφάλμα στατιστικών fixture %s", fixture_id)
                    continue
                stat_type = "Corner Kicks" if market.endswith("Corners") else None
                if stat_type:
                    total = sum(
                        (api_football._extract_stat_value(s, stat_type) or 0) for s in (stats or [])
                    )
                else:
                    total = sum(
                        (api_football._extract_stat_value(s, "Yellow Cards") or 0)
                        + (api_football._extract_stat_value(s, "Red Cards") or 0)
                        for s in (stats or [])
                    )
                won = analysis.evaluate_stat_market_result(market, total)
            elif market.startswith("HT/FT"):
                score_obj = raw_fx.get("score", {})
                ht = score_obj.get("halftime", {})
                won = analysis.evaluate_ht_ft_result(
                    market, ht.get("home"), ht.get("away"),
                    raw_fx["goals"]["home"], raw_fx["goals"]["away"],
                )
            elif (market.startswith("Double Chance")
                  or market.startswith("Correct Score")
                  or market.startswith("Asian Handicap") or "Team Over" in market
                  or market.endswith("Clean Sheet")):
                score_home = raw_fx["goals"]["home"]
                score_away = raw_fx["goals"]["away"]
                won = analysis.evaluate_wave2_market_result(market, score_home, score_away)
            else:
                score_home = raw_fx["goals"]["home"]
                score_away = raw_fx["goals"]["away"]
                won = analysis.evaluate_market_result(market, score_home, score_away)

            entry["results"][i] = won

        leg_results = [entry["results"].get(i) for i in range(len(entry["legs"]))]
        if all(r is not None for r in leg_results):
            # "PUSH" (επιστροφή) -- ισχύει μόνο για single-leg entries προς το παρόν
            # (δεν έχουμε ακόμα multi-leg συνδυασμούς εκτός του μελλοντικού Combo Bets)
            if len(leg_results) == 1 and leg_results[0] == "PUSH":
                overall_result = "PUSH"
            else:
                overall_result = all(r is True for r in leg_results)

            success = telegram_sender.edit_message_add_result(
                entry["channel"], entry["message_id"], entry["original_text"], overall_result
            )
            result_label = "ΑΚΥΡΟ" if overall_result == "PUSH" else ("ΚΕΡΔΙΣΕ" if overall_result else "ΕΧΑΣΕ")
            if success:
                logger.info(
                    "Αποτέλεσμα ενημερώθηκε (%s) στο κανάλι %s (msg %s)",
                    result_label, entry["channel"], entry["message_id"],
                )
            else:
                logger.warning(
                    "Απέτυχε edit msg %s στο %s -- καταγράφεται (%s) και αφαιρείται χωρίς ενημέρωση Telegram",
                    entry["message_id"], entry["channel"], result_label,
                )
            if overall_result != "PUSH":
                stats_tracker.record_result(entry["channel"], overall_result)
            results_tracker.remove(entry["id"])
                    entry["message_id"], entry["channel"], result_label,
    results_tracker.save()  # αποθηκεύουμε ΟΠΟΙΑΔΗΠΟΤΕ πρόοδο (ακόμα και μερικά αποτελέσματα legs)
    results_tracker.cleanup_stale()


def run_stats_summary():
    snapshot = stats_tracker.get_and_reset_summary()
    text = telegram_sender.format_stats_summary(config.STATS_SUMMARY_INTERVAL_HOURS, snapshot["by_channel"])
    telegram_sender.send_to_chat_id(config.STATS_CHANNEL_ID, text)
    logger.info("Απολογισμός στάλθηκε στο κανάλι Statistics Bet")


# ── Scheduler loop ────────────────────────────────────────────

def main_loop():
    startup()

    last_market_run = 0
    last_results_run = 0

    while True:
        now = time.time()

        if now - last_market_run >= config.MARKET_CHECK_INTERVAL_HOURS * 3600:
            # Ο απολογισμός στέλνεται ΠΡΩΤΑ (δείχνει τι έκανε το ΠΡΟΗΓΟΥΜΕΝΟ
            # κύμα προβλέψεων), και ΜΕΤΑ στέλνεται το νέο κύμα -- έτσι κάθε
            # φορά βλέπεις πρώτα τον απολογισμό, μετά τις νέες προβλέψεις.
            try:
                run_stats_summary()
            except Exception:
                logger.exception("Σφάλμα στον απολογισμό στατιστικών")
            try:
                run_market_check()
            except Exception:
                logger.exception("Σφάλμα στον κύκλο markets")
            last_market_run = now

        if now - last_results_run >= config.RESULTS_CHECK_INTERVAL_MIN * 60:
            try:
                check_results()
            except Exception:
                logger.exception("Σφάλμα στον έλεγχο αποτελεσμάτων")
            last_results_run = now

        logger.info("API calls σήμερα μέχρι στιγμής: %s", api_football.get_daily_call_count())
        time.sleep(30)


if __name__ == "__main__":
    main_loop()
