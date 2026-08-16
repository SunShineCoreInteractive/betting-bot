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


def _get(endpoint, params=None, cache_key=None, cache_hours=0):
    """Βασική GET κλήση με προαιρετικό caching."""
    if cache_key and cache_key in _cache:
        ts, data = _cache[cache_key]
        if (time.time() - ts) < cache_hours * 3600:
            return data

    url = f"{config.API_FOOTBALL_BASE_URL}/{endpoint}"
    resp = _session.get(url, params=params or {}, timeout=20)
    _track_call()
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("errors"):
        logger.warning("API-Football errors στο %s: %s", endpoint, payload["errors"])

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
