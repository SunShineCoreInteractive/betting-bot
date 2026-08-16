"""
Ο "αγγελιοφόρος" -- όλες οι κλήσεις προς το API-Football περνάνε από εδώ.
Κάθε συνάρτηση κάνει ΕΝΑ συγκεκριμένο "ερώτημα" στο API και επιστρέφει
καθαρά δεδομένα (python dicts/lists), έτοιμα για το analysis.py.
"""

import time
import logging
from datetime import datetime, timedelta, timezone

import requests

import config

logger = logging.getLogger("api_football")

_session = requests.Session()
_session.headers.update(config.API_HEADERS)

# Απλό in-memory cache: {cache_key: (timestamp, data)}
_cache = {}

# Μετρητής κλήσεων της ημέρας (για να το βλέπεις στα logs, όχι hard limit)
_daily_call_count = 0
_daily_count_date = None

# ── Throttling ──────────────────────────────────────────────────
# Το πλάνο Pro του API-Football έχει όριο κλήσεων ΑΝΑ ΛΕΠΤΟ (ξεχωριστό από το
# ημερήσιο). Αν αναλύουμε πολλούς αγώνες σε ένα κύκλο (π.χ. πολλά live match
# ταυτόχρονα), οι κλήσεις πέφτουν όλες μαζί μέσα σε 1-2 δευτερόλεπτα και
# σκάει το ανά-λεπτό όριο. Εδώ επιβάλλουμε ελάχιστο διάστημα ανάμεσα σε
# διαδοχικές κλήσεις, ώστε να "απλώνονται" ομαλά.
MIN_SECONDS_BETWEEN_CALLS = 0.6   # ~100 κλήσεις/λεπτό μέγιστο -- πιο συντηρητικό (το πλάνο Pro επιτρέπει 300/λεπτό, αλλά ο περιορισμός μετράει και ανά IP, οπότε κρατάμε απόσταση ασφαλείας)
_last_call_time = 0.0
MAX_RETRIES_ON_RATE_LIMIT = 3


def _track_call():
    global _daily_call_count, _daily_count_date
    today = datetime.now(timezone.utc).date()
    if _daily_count_date != today:
        _daily_count_date = today
        _daily_call_count = 0
    _daily_call_count += 1
    if _daily_call_count % 50 == 0:
        logger.info("API-Football calls σήμερα: %s", _daily_call_count)


def get_daily_call_count():
    return _daily_call_count


def _throttle():
    """Περιμένει όσο χρειάζεται ώστε να μην ξεπεράσουμε το ανά-λεπτό όριο του API."""
    global _last_call_time
    elapsed = time.time() - _last_call_time
    wait = MIN_SECONDS_BETWEEN_CALLS - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_call_time = time.time()


def _get(endpoint, params=None, cache_key=None, cache_hours=0, _retry_count=0):
    """Βασική GET κλήση με προαιρετικό caching."""
    if cache_key and cache_key in _cache:
        ts, data = _cache[cache_key]
        if (time.time() - ts) < cache_hours * 3600:
            return data

    _throttle()
    url = f"{config.API_FOOTBALL_BASE_URL}/{endpoint}"
    resp = _session.get(url, params=params or {}, timeout=20)

    if resp.status_code == 429:
        if _retry_count >= MAX_RETRIES_ON_RATE_LIMIT:
            logger.error("Rate limit (HTTP 429) -- εξαντλήθηκαν οι προσπάθειες για %s", endpoint)
            resp.raise_for_status()
        wait = 3 * (_retry_count + 1)  # 3s, 6s, 9s
        logger.warning("HTTP 429 (rate limit) στο %s -- αναμονή %ss και retry...", endpoint, wait)
        time.sleep(wait)
        return _get(endpoint, params=params, cache_key=cache_key, cache_hours=cache_hours,
                     _retry_count=_retry_count + 1)

    _track_call()
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("errors"):
        logger.warning("API-Football errors στο %s: %s", endpoint, payload["errors"])
        if "rateLimit" in payload["errors"] and _retry_count < MAX_RETRIES_ON_RATE_LIMIT:
            # "Μαλακή" μορφή σφάλματος rate-limit (HTTP 200 αλλά errors.rateLimit)
            logger.warning("Rate limit (soft) -- αναμονή 3s και retry...")
            time.sleep(3)
            return _get(endpoint, params=params, cache_key=cache_key, cache_hours=cache_hours,
                         _retry_count=_retry_count + 1)

    data = payload.get("response", [])

    if cache_key:
        _cache[cache_key] = (time.time(), data)

    return data


# ── Λίγκες ─────────────────────────────────────────────────────

def get_all_leagues():
    """Όλες οι λίγκες/κύπελλα που καλύπτει το API (cache 1 εβδομάδα)."""
    return _get("leagues", cache_key="all_leagues", cache_hours=config.LEAGUE_CACHE_HOURS)


# ── Τύποι στοιχημάτων (bet types) ─────────────────────────────

def get_bet_types():
    """Λίστα όλων των διαθέσιμων τύπων στοιχήματος (id + name), cache 1 εβδομάδα."""
    return _get("odds/bets", cache_key="bet_types", cache_hours=config.BET_TYPES_CACHE_HOURS)


def get_bookmakers():
    """Λίστα όλων των bookmakers που καλύπτει το πλάνο σου, cache 1 εβδομάδα."""
    return _get("odds/bookmakers", cache_key="bookmakers", cache_hours=config.BET_TYPES_CACHE_HOURS)


# ── Αγώνες ─────────────────────────────────────────────────────

def get_fixtures_by_date(date_str, league_ids=None):
    """
    Όλοι οι αγώνες μιας συγκεκριμένης ημερομηνίας (YYYY-MM-DD).
    Αν δοθούν league_ids, φιλτράρουμε μετά client-side (το API δεν δέχεται
    πολλαπλά league IDs σε ένα call).
    """
    fixtures = _get("fixtures", params={"date": date_str})
    if league_ids:
        league_id_set = set(league_ids)
        fixtures = [f for f in fixtures if f["league"]["id"] in league_id_set]
    return fixtures


def get_fixtures_in_window(hours_ahead, league_ids=None):
    """
    Αγώνες που ξεκινούν μέσα στις επόμενες `hours_ahead` ώρες από τώρα.
    Χρησιμοποιείται για το pre-match παράθυρο ελέγχου.
    """
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    candidates = get_fixtures_by_date(today_str, league_ids)
    # Αν το παράθυρο μπορεί να περάσει τα μεσάνυχτα UTC, τραβάμε και αύριο
    if now.hour >= 24 - int(hours_ahead) - 1:
        candidates += get_fixtures_by_date(tomorrow_str, league_ids)

    window_end = now + timedelta(hours=hours_ahead)
    result = []
    for f in candidates:
        kickoff = datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
        if now <= kickoff <= window_end and f["fixture"]["status"]["short"] == "NS":
            result.append(f)
    return result


def get_live_fixtures():
    """Όλοι οι αγώνες που παίζονται αυτή τη στιγμή (χωρίς league filter -- μία κλήση)."""
    return _get("fixtures", params={"live": "all"})


# ── Odds ─────────────────────────────────────────────────────

def get_prematch_odds(fixture_id):
    """Pre-match αποδόσεις για συγκεκριμένο αγώνα (όλα τα bookmakers/markets)."""
    return _get("odds", params={"fixture": fixture_id})


def get_live_odds(fixture_id=None):
    """Live αποδόσεις. Χωρίς fixture_id φέρνει όλα τα ζωντανά odds σε ένα call."""
    params = {"fixture": fixture_id} if fixture_id else {}
    return _get("odds/live", params=params)


def get_fixture_by_id(fixture_id):
    """Τρέχουσα κατάσταση ενός συγκεκριμένου fixture (για έλεγχο αποτελέσματος)."""
    return _get("fixtures", params={"id": fixture_id})


def get_fixtures_by_ids(fixture_ids):
    """
    Τρέχουσα κατάσταση ΠΟΛΛΩΝ fixtures σε 1 κλήση (έως 20 -- όριο του API).
    Επιστρέφει dict {fixture_id: raw_fixture_data}.
    """
    if not fixture_ids:
        return {}
    ids_param = "-".join(str(fid) for fid in fixture_ids[:20])
    results = _get("fixtures", params={"ids": ids_param})
    return {r["fixture"]["id"]: r for r in results}


def get_fixture_events(fixture_id):
    """Χρονολόγιο γεγονότων ενός αγώνα (γκολ, κάρτες, κλπ) -- για έλεγχο 'Επόμενο Γκολ'."""
    return _get("fixtures/events", params={"fixture": fixture_id})


def get_fixture_statistics(fixture_id, live=False):
    """
    Στατιστικά αγώνα (κόρνερ, κάρτες, κλπ) ανά ομάδα.
    live=False -> μόνιμο cache (τελειωμένος αγώνας, δεν αλλάζει ποτέ).
    live=True  -> χωρίς cache (ζωντανός αγώνας, αλλάζει συνέχεια).
    """
    if live:
        return _get("fixtures/statistics", params={"fixture": fixture_id})
    return _get(
        "fixtures/statistics", params={"fixture": fixture_id},
        cache_key=f"fx_stats_{fixture_id}", cache_hours=config.CORNER_CARD_STATS_CACHE_HOURS,
    )


def _extract_stat_value(team_statistics, stat_type):
    for item in team_statistics.get("statistics", []):
        if item.get("type") == stat_type:
            return item.get("value")
    return None


def get_team_corner_card_form(team_id, recent_fixtures):
    """
    recent_fixtures: λίστα από το get_team_recent_fixtures (ήδη τραβηγμένη, δεν
    κάνει νέα κλήση για τη λίστα -- μόνο για τα per-fixture στατιστικά).
    Επιστρέφει:
      {
        "corners": {"avg_scored": .., "avg_conceded": .., "sample_size": ..},
        "cards": {"avg": .., "sample_size": ..},
      }
    """
    finished = [
        f for f in recent_fixtures
        if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")
    ][: config.CORNERS_CARDS_LOOKBACK]

    corners_for, corners_against, cards_for = [], [], []

    for f in finished:
        fid = f["fixture"]["id"]
        try:
            stats = get_fixture_statistics(fid)
        except Exception:
            logger.exception("Σφάλμα στατιστικών fixture %s", fid)
            continue
        if not stats or len(stats) < 2:
            continue

        team_stats = next((s for s in stats if s["team"]["id"] == team_id), None)
        opp_stats = next((s for s in stats if s["team"]["id"] != team_id), None)
        if not team_stats:
            continue

        corners = _extract_stat_value(team_stats, "Corner Kicks")
        if corners is not None:
            corners_for.append(corners)

        if opp_stats:
            opp_corners = _extract_stat_value(opp_stats, "Corner Kicks")
            if opp_corners is not None:
                corners_against.append(opp_corners)

        yellow = _extract_stat_value(team_stats, "Yellow Cards") or 0
        red = _extract_stat_value(team_stats, "Red Cards") or 0
        cards_for.append(yellow + red)

    return {
        "corners": {
            "avg_scored": (sum(corners_for) / len(corners_for)) if corners_for else 5.0,
            "avg_conceded": (sum(corners_against) / len(corners_against)) if corners_against else 5.0,
            "sample_size": len(corners_for),
        },
        "cards": {
            "avg": (sum(cards_for) / len(cards_for)) if cards_for else 2.0,
            "sample_size": len(cards_for),
        },
    }


# ── Ομάδες / Στατιστικά / Φόρμα ────────────────────────────────

def get_team_recent_fixtures(team_id, last=None):
    """Οι τελευταίοι Ν ολοκληρωμένοι αγώνες μιας ομάδας (για υπολογισμό φόρμας)."""
    last = last or config.RECENT_FIXTURES_LOOKBACK
    cache_key = f"recent_fixtures_{team_id}_{last}"
    return _get(
        "fixtures",
        params={"team": team_id, "last": last},
        cache_key=cache_key,
        cache_hours=config.TEAM_STATS_CACHE_HOURS,
    )


def get_team_statistics(team_id, league_id, season):
    """Συγκεντρωτικά στατιστικά ομάδας για συγκεκριμένη λίγκα/σεζόν (goals for/against κλπ)."""
    cache_key = f"team_stats_{team_id}_{league_id}_{season}"
    return _get(
        "teams/statistics",
        params={"team": team_id, "league": league_id, "season": season},
        cache_key=cache_key,
        cache_hours=config.TEAM_STATS_CACHE_HOURS,
    )


def get_head_to_head(team1_id, team2_id, last=10):
    """Ιστορικές αναμετρήσεις μεταξύ δύο ομάδων."""
    cache_key = f"h2h_{min(team1_id, team2_id)}_{max(team1_id, team2_id)}"
    return _get(
        "fixtures/headtohead",
        params={"h2h": f"{team1_id}-{team2_id}", "last": last},
        cache_key=cache_key,
        cache_hours=config.TEAM_STATS_CACHE_HOURS,
    )
