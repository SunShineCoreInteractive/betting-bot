"""
Ξεχωριστός "αγγελιοφόρος" για το Basketball API (v1.basketball.api-sports.io).
Εντελώς διαφορετικό key/budget από το ποδόσφαιρο (100 κλήσεις/μέρα, δωρεάν
πλάνο) -- γι' αυτό έχει δικό του throttling, δικό του μετρητή, και πολύ πιο
προσεκτικό caching.
"""

import time
import logging
from datetime import datetime, timezone

import requests

import config

logger = logging.getLogger("api_basketball")

_session = requests.Session()
_session.headers.update(config.API_BASKETBALL_HEADERS)

_cache = {}

_daily_call_count = 0
_daily_count_date = None

MIN_SECONDS_BETWEEN_CALLS = 1.0  # πολύ πιο αργό tempo -- δεν βιαζόμαστε με 100/μέρα
_last_call_time = 0.0


def _track_call():
    global _daily_call_count, _daily_count_date
    today = datetime.now(timezone.utc).date()
    if _daily_count_date != today:
        _daily_count_date = today
        _daily_call_count = 0
    _daily_call_count += 1


def get_daily_call_count():
    return _daily_call_count


def budget_is_low():
    remaining = config.BASKETBALL_DAILY_CALL_BUDGET - _daily_call_count
    return remaining < 10  # πολύ στενό περιθώριο ασφαλείας λόγω μικρού budget


def _throttle():
    global _last_call_time
    elapsed = time.time() - _last_call_time
    wait = MIN_SECONDS_BETWEEN_CALLS - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_call_time = time.time()


def _get(endpoint, params=None, cache_key=None, cache_hours=0):
    if cache_key and cache_key in _cache:
        ts, data = _cache[cache_key]
        if (time.time() - ts) < cache_hours * 3600:
            return data

    if budget_is_low():
        logger.warning("Χαμηλό ημερήσιο budget μπάσκετ -- παραλείπεται η κλήση %s", endpoint)
        return []

    _throttle()
    url = f"{config.API_BASKETBALL_BASE_URL}/{endpoint}"
    resp = _session.get(url, params=params or {}, timeout=20)
    _track_call()
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("errors"):
        logger.warning("API-Basketball errors στο %s: %s", endpoint, payload["errors"])

    data = payload.get("response", [])

    if cache_key:
        _cache[cache_key] = (time.time(), data)

    return data


def get_all_leagues():
    """Cache πολύ μεγάλο -- οι λίγκες μπάσκετ δεν αλλάζουν συχνά."""
    return _get("leagues", cache_key="bball_all_leagues", cache_hours=24 * 30)


def resolve_league_id(name_query):
    """
    Ψάχνει στη λίστα λιγκών για κάτι που ταιριάζει (π.χ. 'NBA', 'Euroleague').
    Επιστρέφει το πρώτο league_id που ταιριάζει, ή None.
    """
    leagues = get_all_leagues()
    query_l = name_query.lower()
    for entry in leagues:
        name = entry.get("name", "")
        if query_l in name.lower():
            return entry["id"]
    return None


def get_games_by_date(league_id, season, date_str):
    """Όλοι οι αγώνες μιας λίγκας σε συγκεκριμένη ημερομηνία (YYYY-MM-DD)."""
    return _get("games", params={"league": league_id, "season": season, "date": date_str})


def get_team_statistics(team_id, league_id, season):
    """Στατιστικά ομάδας (πόντοι υπέρ/κατά, μέσος όρος) -- cache 3 μέρες."""
    cache_key = f"bball_team_stats_{team_id}_{league_id}_{season}"
    return _get(
        "statistics",
        params={"team": team_id, "league": league_id, "season": season},
        cache_key=cache_key, cache_hours=config.BASKETBALL_TEAM_STATS_CACHE_HOURS,
    )


def get_odds_by_game(game_id):
    """Αποδόσεις για συγκεκριμένο αγώνα."""
    return _get("odds", params={"game": game_id})


def get_game_by_id(game_id):
    """Τρέχουσα κατάσταση συγκεκριμένου αγώνα -- για έλεγχο αποτελέσματος."""
    return _get("games", params={"id": game_id})
