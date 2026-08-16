"""
Ο μαέστρος. Τρέχει συνέχεια (24ωρο loop) και:
  - κάθε PREMATCH_CHECK_INTERVAL_MIN λεπτά -> ελέγχει αγώνες στο pre-match παράθυρο
  - κάθε LIVE_CHECK_INTERVAL_MIN λεπτά     -> ελέγχει ζωντανούς αγώνες

Εκτελείται σαν Render "Background Worker" (συνεχής διεργασία, όχι cron).
"""

import time
import logging
from datetime import datetime, timezone

import config
import api_football
import league_classifier
import analysis
import odds_parser
import telegram_sender
import sent_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

# Γεμίζει στο startup
ALLOWED_LEAGUE_IDS = set()


def startup():
    global ALLOWED_LEAGUE_IDS
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


def _fixture_basics(fixture):
    return {
        "id": fixture["fixture"]["id"],
        "league_name": fixture["league"]["name"],
        "league_id": fixture["league"]["id"],
        "season": fixture["league"]["season"],
        "home_id": fixture["teams"]["home"]["id"],
        "home_name": fixture["teams"]["home"]["name"],
        "away_id": fixture["teams"]["away"]["id"],
        "away_name": fixture["teams"]["away"]["name"],
        "kickoff": fixture["fixture"]["date"],
    }


def _kickoff_str(iso_date):
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return dt.strftime("%H:%M")


def _get_predictions_for_fixture(fx):
    """Pre-match μοντέλο goals/BTTS. Επιστρέφει predictions."""
    home_recent = api_football.get_team_recent_fixtures(fx["home_id"])
    away_recent = api_football.get_team_recent_fixtures(fx["away_id"])

    home_form = analysis.team_form_from_fixtures(home_recent, fx["home_id"])
    away_form = analysis.team_form_from_fixtures(away_recent, fx["away_id"])
    sample_size = min(home_form["sample_size"], away_form["sample_size"])

    lam_home, lam_away = analysis.compute_expected_goals(home_form, away_form)

    odds_response = api_football.get_prematch_odds(fx["id"])
    odds_lookup = odds_parser.parse_goals_and_btts_odds(
        odds_response[0] if odds_response else {}
    )

    predictions = analysis.analyze_fixture_goals_markets(
        lam_home, lam_away, odds_lookup, sample_size
    )
    return predictions


def _get_live_predictions_for_fixture(fx, score_home, score_away, elapsed_minutes):
    """Live μοντέλο -- λαμβάνει υπόψη τρέχον σκορ + χρόνο που απομένει."""
    home_recent = api_football.get_team_recent_fixtures(fx["home_id"])
    away_recent = api_football.get_team_recent_fixtures(fx["away_id"])

    home_form = analysis.team_form_from_fixtures(home_recent, fx["home_id"])
    away_form = analysis.team_form_from_fixtures(away_recent, fx["away_id"])
    sample_size = min(home_form["sample_size"], away_form["sample_size"])

    lam_home_full, lam_away_full = analysis.compute_expected_goals(home_form, away_form)

    odds_response = api_football.get_live_odds(fx["id"])
    odds_lookup = odds_parser.parse_goals_and_btts_odds(
        odds_response[0] if odds_response else {}
    )

    predictions = analysis.analyze_fixture_goals_markets_live(
        score_home, score_away, elapsed_minutes,
        lam_home_full, lam_away_full, odds_lookup, sample_size,
    )
    return predictions


# ── Pre-match κύκλος (Μονά / Παρολί / Bet Builder) ───────────────

def run_prematch_check():
    fixtures = api_football.get_fixtures_in_window(
        config.PREMATCH_WINDOW_HOURS, ALLOWED_LEAGUE_IDS
    )
    logger.info("Pre-match παράθυρο: %s αγώνες", len(fixtures))

    fixture_ids_in_window = {f["fixture"]["id"] for f in fixtures}
    for ch in ("singles", "bet_builder"):
        sent_tracker.clear_expired_prematch(ch, fixture_ids_in_window)
    sent_tracker.clear_expired_parlay("parlay", fixture_ids_in_window)

    parlay_pool = []  # [(fx, Prediction), ...] υποψήφιοι από διαφορετικούς αγώνες

    for raw_fx in fixtures:
        fx = _fixture_basics(raw_fx)
        kickoff_str = _kickoff_str(fx["kickoff"])

        try:
            predictions = _get_predictions_for_fixture(fx)
        except Exception:
            logger.exception("Σφάλμα ανάλυσης fixture %s", fx["id"])
            continue

        if not predictions:
            continue

        # ── Μονά (1 μόνο μήνυμα/αγώνα -- η γραμμή με το μεγαλύτερο edge) ──
        best_single = max(predictions, key=lambda p: p.edge or 0)
        if not sent_tracker.already_sent("singles", fx["id"], "any"):
            text = telegram_sender.format_single(
                fx["league_name"], fx["home_name"], fx["away_name"], kickoff_str,
                best_single.market, best_single.model_prob, best_single.odds,
                best_single.edge, best_single.basis,
            )
            if telegram_sender.send_message("singles", text):
                sent_tracker.mark_sent("singles", fx["id"], "any")
                logger.info("Μονό στάλθηκε: %s %s vs %s", best_single.market, fx["home_name"], fx["away_name"])

        # συλλογή για Παρολί (pool, ξεχωριστά ανά αγώνα)
        for pred in predictions:
            parlay_pool.append((fx, kickoff_str, pred))

        # ── Bet Builder (ίδιος αγώνας, 2-3 legs) ──
        eligible_bb = [p for p in predictions if p.model_prob >= config.BET_BUILDER_MIN_LEG_PROB]
        # απόφευξε αντιφατικά/επικαλυπτόμενα markets (π.χ. δύο διαφορετικές Over γραμμές μαζί)
        non_redundant = []
        seen_families = set()
        for p in sorted(eligible_bb, key=lambda x: -x.model_prob):
            family = p.market.split()[0]  # π.χ. "Over", "BTTS"
            if family in seen_families:
                continue
            seen_families.add(family)
            non_redundant.append(p)

        if len(non_redundant) >= config.BET_BUILDER_MIN_LEGS:
            legs = non_redundant[: config.BET_BUILDER_MAX_LEGS]
            combined_prob, fair_odds = analysis.combine_bet_builder(legs)
            key = tuple(sorted(p.market for p in legs))
            if combined_prob >= config.BET_BUILDER_MIN_COMBINED_PROB and \
               not sent_tracker.already_sent("bet_builder", fx["id"], key):
                legs_desc = [f"{p.market} — εκτίμηση {p.model_prob*100:.0f}%" for p in legs]
                text = telegram_sender.format_bet_builder(
                    fx["league_name"], fx["home_name"], fx["away_name"], kickoff_str,
                    legs_desc, combined_prob, fair_odds,
                )
                if telegram_sender.send_message("bet_builder", text):
                    sent_tracker.mark_sent("bet_builder", fx["id"], key)
                    logger.info("Bet Builder στάλθηκε: %s vs %s", fx["home_name"], fx["away_name"])

    # ── Παρολί (2-3 legs, ΔΙΑΦΟΡΕΤΙΚΟΙ αγώνες) ──
    run_parlay_from_pool(parlay_pool, fixture_ids_in_window)


def run_parlay_from_pool(parlay_pool, fixture_ids_in_window):
    sent_tracker.clear_expired_parlay("parlay", fixture_ids_in_window)

    # ένα leg ανά αγώνα -- κρατάμε το καλύτερο (μεγαλύτερο edge) ανά fixture
    best_per_fixture = {}
    for fx, kickoff_str, pred in parlay_pool:
        current = best_per_fixture.get(fx["id"])
        if current is None or (pred.edge or 0) > (current[2].edge or 0):
            best_per_fixture[fx["id"]] = (fx, kickoff_str, pred)

    candidates = sorted(best_per_fixture.values(), key=lambda t: -(t[2].edge or 0))

    if len(candidates) < config.PARLAY_MIN_LEGS:
        return

    combo = candidates[: config.PARLAY_MAX_LEGS]
    combo_key = tuple(sorted(f["id"] for f, _, _ in combo))

    if sent_tracker.already_sent("parlay", combo_key, "parlay"):
        return

    legs = [pred for _, _, pred in combo]
    combined_prob, combined_odds = analysis.combine_parlay(legs)
    combined_edge = combined_prob - (1 / combined_odds if combined_odds else 1)

    legs_desc = [
        f"{fx['home_name']} vs {fx['away_name']} — {pred.market} ({pred.odds:.2f})"
        for fx, _, pred in combo
    ]
    text = telegram_sender.format_parlay(legs_desc, combined_odds, combined_prob, combined_edge)
    if telegram_sender.send_message("parlay", text):
        sent_tracker.mark_sent("parlay", combo_key, "parlay")
        logger.info("Παρολί στάλθηκε: %s επιλογές", len(combo))


# ── Live κύκλος ────────────────────────────────────────────────

def run_live_check():
    live_fixtures = api_football.get_live_fixtures()
    logger.info("Live fixtures: %s", len(live_fixtures))

    live_ids = set()
    for raw_fx in live_fixtures:
        if raw_fx["league"]["id"] not in ALLOWED_LEAGUE_IDS:
            continue
        fx = _fixture_basics(raw_fx)
        live_ids.add(fx["id"])

        minute = raw_fx["fixture"]["status"]["elapsed"]
        score_home = raw_fx["goals"]["home"]
        score_away = raw_fx["goals"]["away"]

        try:
            predictions = _get_live_predictions_for_fixture(fx, score_home, score_away, minute)
        except Exception:
            logger.exception("Σφάλμα live ανάλυσης fixture %s", fx["id"])
            continue

        if not predictions:
            continue

        # 1 μόνο μήνυμα ανά αγώνα -- η γραμμή με το μεγαλύτερο edge
        best = max(predictions, key=lambda p: p.edge or 0)

        if sent_tracker.already_sent("live", fx["id"], "any"):
            continue
        text = telegram_sender.format_live(
            fx["league_name"], minute, fx["home_name"], fx["away_name"],
            score_home, score_away, best.market, best.model_prob,
            best.odds, best.edge, best.basis,
        )
        if telegram_sender.send_message("live", text):
            sent_tracker.mark_sent("live", fx["id"], "any")
            logger.info("Live στάλθηκε: %s %s vs %s", best.market, fx["home_name"], fx["away_name"])

    sent_tracker.clear_finished_live("live", live_ids)


# ── Scheduler loop ────────────────────────────────────────────

def main_loop():
    startup()

    last_prematch_run = 0
    last_live_run = 0

    while True:
        now = time.time()

        if now - last_live_run >= config.LIVE_CHECK_INTERVAL_MIN * 60:
            try:
                run_live_check()
            except Exception:
                logger.exception("Σφάλμα στον live κύκλο")
            last_live_run = now

        if now - last_prematch_run >= config.PREMATCH_CHECK_INTERVAL_MIN * 60:
            try:
                run_prematch_check()
            except Exception:
                logger.exception("Σφάλμα στον pre-match κύκλο")
            last_prematch_run = now

        logger.info("API calls σήμερα μέχρι στιγμής: %s", api_football.get_daily_call_count())
        time.sleep(20)


if __name__ == "__main__":
    main_loop()
