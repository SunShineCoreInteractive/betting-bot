"""
Ταξινομεί αυτόματα τις λίγκες του API-Football σε:
  - tier 1 (κύρια λίγκα κάθε χώρας)
  - tier 2 (δεύτερη κατηγορία)
  - domestic cups (κύπελλα χωρών)
  - international (Champions League, εθνικές ομάδες, κλπ.)

χωρίς να χρειάζεται χειροκίνητη λίστα με ~180 IDs.
Το αποτέλεσμα πρέπει να περνάει από έλεγχο (print_summary) πριν το go-live.
"""

import re
import logging

import api_football

logger = logging.getLogger("league_classifier")

# Λέξεις-κλειδιά που δείχνουν 2η κατηγορία (case-insensitive, οποιαδήποτε γλώσσα/format)
TIER2_PATTERNS = [
    r"\b2\b", r"\bii\b", r"\bb\b", r"second", r"championship",
    r"segunda", r"2\.\s*liga", r"1\.\s*lig\b", r"serie\s*b",
    r"division\s*2", r"liga\s*2", r"challenger", r"nationale\s*2",
    r"eerste\s*divisie", r"obos", r"superettan", r"i\s*liga\b",
]

# Ρητές χώρες όπου θέλουμε ΜΟΝΟ tier 1 (ζητήθηκε ρητά)
TIER1_ONLY_COUNTRIES = {
    "usa", "canada", "mexico",                          # Βόρεια Αμερική
    "peru", "uruguay", "bolivia", "paraguay", "venezuela",
    "ecuador", "colombia", "chile",                       # Νότια Αμερική (ζητημένες)
    "australia", "japan", "china",
    "qatar", "united-arab-emirates", "saudi-arabia",
}

# Χώρες όπου θέλουμε ρητά και κύπελλο (πέρα από tier1/tier2)
CUP_REQUIRED_COUNTRIES = TIER1_ONLY_COUNTRIES | {"__all_europe__"}

# Λέξεις που δείχνουν διεθνή/ηπειρωτική διοργάνωση club-level
INTERNATIONAL_CLUB_KEYWORDS = [
    "champions league", "europa league", "conference league",
    "libertadores", "sudamericana", "concacaf champions",
    "caf champions league", "caf confederation", "afc champions",
]

# Λέξεις που δείχνουν διοργάνωση εθνικών ομάδων
NATIONAL_TEAM_KEYWORDS = [
    "world cup", "euro championship", "european championship",
    "copa america", "africa cup", "nations league", "qualification",
    "friendlies", "confederations cup", "asian cup", "gold cup",
]

EUROPE_CONTINENT_COUNTRIES = None  # γεμίζει δυναμικά από το API αν χρειαστεί


def _is_tier2(name: str) -> bool:
    name_l = name.lower()
    return any(re.search(p, name_l) for p in TIER2_PATTERNS)


def _is_cup(league_entry) -> bool:
    return league_entry["league"]["type"] == "Cup"


def _matches_any(name_l, keywords):
    return any(k in name_l for k in keywords)


def classify_leagues():
    """
    Επιστρέφει dict:
      {
        "tier1": [league_id, ...],
        "tier2": [league_id, ...],
        "domestic_cups": [league_id, ...],
        "international_club": [league_id, ...],
        "national_team": [league_id, ...],
        "meta": {league_id: {"name":.., "country":.., "type":..}}
      }
    """
    all_leagues = api_football.get_all_leagues()

    result = {
        "tier1": [],
        "tier2": [],
        "domestic_cups": [],
        "international_club": [],
        "national_team": [],
        "meta": {},
    }

    for entry in all_leagues:
        league = entry["league"]
        country = entry.get("country", {})
        league_id = league["id"]
        name = league["name"]
        name_l = name.lower()
        country_name = (country.get("name") or "").lower().replace(" ", "-")
        is_cup_type = _is_cup(entry)

        result["meta"][league_id] = {
            "name": name,
            "country": country.get("name"),
            "type": league["type"],
        }

        # Διεθνείς διοργανώσεις (χωρίς συγκεκριμένη χώρα, ή World)
        if _matches_any(name_l, INTERNATIONAL_CLUB_KEYWORDS):
            result["international_club"].append(league_id)
            continue

        if _matches_any(name_l, NATIONAL_TEAM_KEYWORDS) or country_name == "world":
            result["national_team"].append(league_id)
            continue

        if is_cup_type:
            # Κύπελλο χώρας -- το κρατάμε αν είναι Ευρώπη ή στη ρητή λίστα χωρών
            result["domestic_cups"].append(league_id)
            continue

        # Domestic league -- tier 1 ή tier 2
        if country_name in TIER1_ONLY_COUNTRIES:
            if not _is_tier2(name_l):
                result["tier1"].append(league_id)
            # tier2 αγνοείται ρητά για αυτές τις χώρες
        else:
            if _is_tier2(name_l):
                result["tier2"].append(league_id)
            else:
                result["tier1"].append(league_id)

    return result


def print_summary(classification):
    """Ανθρώπινη σύνοψη προς έλεγχο πριν το go-live -- ΔΕΝ τρέχει αυτόματα, το καλείς εσύ χειροκίνητα."""
    meta = classification["meta"]
    for key in ["tier1", "tier2", "domestic_cups", "international_club", "national_team"]:
        ids = classification[key]
        print(f"\n=== {key} ({len(ids)}) ===")
        for lid in ids:
            m = meta[lid]
            print(f"  [{lid}] {m['name']} -- {m['country']}")
