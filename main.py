"""
Ο μαέστρος. Τρέχει συνέχεια (24ωρο loop) και:
  - κάθε PREMATCH_CHECK_INTERVAL_MIN λεπτά -> ελέγχει αγώνες στο pre-match παράθυρο
  - κάθε LIVE_CHECK_INTERVAL_MIN λεπτά     -> ελέγχει ζωντανούς αγώνες

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

    # Μία φορά, καταγράφουμε όλα τα διαθέσιμα bookmakers στα Logs -- έτσι
    # μπορείς να δεις αν υπάρχει Stoiximan/Novibet/κλπ χωρίς κανένα άλλο εργαλείο.
    try:
        bookmakers = api_football.get_bookmakers()
        names = sorted(b["name"] for b in bookmakers if b.get("name"))
        logger.info("Διαθέσιμα bookmakers (%s): %s", len(names), ", ".join(names))
    except Exception:
        logger.exception("Δεν κατάφερα να τραβήξω τη λίστα bookmakers")


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
                results_tracker.add_pending(
                    "singles",
                    f"{fx['league_name']}\n{fx['home_name']} vs {fx['away_name']} — {best_single.market}",
                    [{"fixture_id": fx["id"], "market": best_single.market}],
                )
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
                    bb_desc = (
                        f"{fx['league_name']}\n{fx['home_name']} vs {fx['away_name']}\n"
                        + " + ".join(p.market for p in legs)
                    )
                    results_tracker.add_pending(
                        "bet_builder", bb_desc, [{"fixture_id": fx["id"], "market": p.market} for p in legs]
                    )
                    logger.info("Bet Builder στάλθηκε: %s vs %s", fx["home_name"], fx["away_name"])

    # ── Παρολί (2-3 legs, ΔΙΑΦΟΡΕΤΙΚΟΙ αγώνες) ──
    run_parlay_from_pool(parlay_pool, fixture_ids_in_window)


def run_parlay_from_pool(parlay_pool, fixture_ids_in_window):
    sent_tracker.clear_expired_parlay("parlay", fixture_ids_in_window)
    sent_tracker.clear_expired_prematch("parlay_legs_used", fixture_ids_in_window)

    # ένα leg ανά αγώνα -- κρατάμε το καλύτερο (μεγαλύτερο edge) ανά fixture,
    # ΕΞΑΙΡΩΝΤΑΣ αγώνες που έχουν ήδη χρησιμοποιηθεί σε προηγούμενο Παρολί
    # (ώστε το ίδιο ματς να μην ξαναμπαίνει σε νέο συνδυασμό κάθε 5 λεπτά)
    best_per_fixture = {}
    for fx, kickoff_str, pred in parlay_pool:
        if sent_tracker.already_sent("parlay_legs_used", fx["id"], "used"):
            continue
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

    if combined_prob < config.PARLAY_MIN_COMBINED_PROB:
        return  # δεν φτάνει το ελάχιστο 50% -- δεν στέλνουμε

    combined_edge = combined_prob - (1 / combined_odds if combined_odds else 1)

    legs_desc = [
        f"{fx['league_name']}: {fx['home_name']} vs {fx['away_name']} — {pred.market} ({pred.odds:.2f})"
        for fx, _, pred in combo
    ]
    text = telegram_sender.format_parlay(legs_desc, combined_odds, combined_prob, combined_edge)
    if telegram_sender.send_message("parlay", text):
        sent_tracker.mark_sent("parlay", combo_key, "parlay")
        for fx, _, _ in combo:
            sent_tracker.mark_sent("parlay_legs_used", fx["id"], "used")
        parlay_desc = "\n".join(legs_desc)
        results_tracker.add_pending(
            "parlay", parlay_desc, [{"fixture_id": fx["id"], "market": pred.market} for fx, _, pred in combo]
        )
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
            results_tracker.add_pending(
                "live",
                f"{fx['league_name']}\n{fx['home_name']} vs {fx['away_name']} — {best.market} (LIVE)",
                [{
                    "fixture_id": fx["id"],
                    "market": best.market,
                    "elapsed_at_send": minute,
                    "home_team_id": fx["home_id"],
                }],
            )
            logger.info("Live στάλθηκε: %s %s vs %s", best.market, fx["home_name"], fx["away_name"])

    sent_tracker.clear_finished_live("live", live_ids)


# ── Έλεγχος αποτελεσμάτων (ΚΕΡΔΙΣΕ/ΕΧΑΣΕ follow-up) ─────────────

def check_results():
    pending = results_tracker.get_pending()

    # Μαζεύουμε ΟΛΑ τα fixture_id που χρειάζονται έλεγχο (χωρίς διπλότυπα),
    # και τα ελέγχουμε σε ομάδες των 20 -- αντί για 1 κλήση/leg.
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
                continue  # ήδη γνωστό αποτέλεσμα για αυτό το leg

            fixture_id = leg["fixture_id"]
            market = leg["market"]
            raw_fx = fixtures_by_id.get(fixture_id)
            if not raw_fx:
                continue
            status = raw_fx["fixture"]["status"]["short"]
            if status not in ("FT", "AET", "PEN"):
                continue  # δεν έχει τελειώσει ακόμα

            if market.startswith("Next Goal"):
                try:
                    events = api_football.get_fixture_events(fixture_id)
                except Exception:
                    logger.exception("Σφάλμα ανάκτησης events fixture %s", fixture_id)
                    continue
                won = analysis.evaluate_next_goal_result(
                    market, events, leg.get("elapsed_at_send"), leg.get("home_team_id")
                )
            else:
                score_home = raw_fx["goals"]["home"]
                score_away = raw_fx["goals"]["away"]
                won = analysis.evaluate_market_result(market, score_home, score_away)

            entry["results"][i] = won

        leg_results = [entry["results"].get(i) for i in range(len(entry["legs"]))]
        if all(r is not None for r in leg_results):
            overall_won = all(leg_results)
            text = telegram_sender.format_result(entry["description"], overall_won)
            telegram_sender.send_message(entry["channel"], text)
            results_tracker.remove(entry["id"])
            logger.info("Αποτέλεσμα στάλθηκε (%s): %s", "ΚΕΡΔΙΣΕ" if overall_won else "ΕΧΑΣΕ", entry["description"][:60])

    results_tracker.cleanup_stale()


# ── Scheduler loop ────────────────────────────────────────────

def main_loop():
    startup()

    last_prematch_run = 0
    last_live_run = 0
    last_results_run = 0

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

        if now - last_results_run >= config.RESULTS_CHECK_INTERVAL_MIN * 60:
            try:
                check_results()
            except Exception:
                logger.exception("Σφάλμα στον έλεγχο αποτελεσμάτων")
            last_results_run = now

        logger.info("API calls σήμερα μέχρι στιγμής: %s", api_football.get_daily_call_count())
        time.sleep(20)


if __name__ == "__main__":
    main_loop()
