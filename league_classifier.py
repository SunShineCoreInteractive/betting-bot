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
    r"^1\.\s*divisjon\b", r"^1\.\s*division\b",   # Νορβηγία/Δανία: "1. divisjon/Division" = tier2
]

# Λέξεις-κλειδιά που δείχνουν 3η κατηγορία ΚΑΙ ΚΑΤΩ -- αυτές αποκλείονται ΕΝΤΕΛΩΣ
# (πιο ειδικές από το γενικό TIER2_PATTERNS, ώστε να μην μπερδεύονται π.χ. με
# "2. Bundesliga"/"2. Liga" της Γερμανίας/Πολωνίας που ΕΙΝΑΙ tier2)
TIER3_PLUS_PATTERNS = [
    r"^[2-9]\.\s*divisjon\b",   # Νορβηγία: "2. divisjon" και πάνω = tier3+
    r"^[2-9]\.\s*division\b",  # Δανία: "2. Division" και πάνω = tier3+
    r"^(3|4|5)\.\s*(liga|lig|bundesliga)\b",
    r"\bthird\s*division\b", r"\bfourth\s*division\b",
    r"\bregionalliga\b", r"\boberliga\b", r"\blandesliga\b",
    r"\bbezirksliga\b", r"\bkreisliga\b",
    r"\bserie\s*c\b", r"\bserie\s*d\b",   # Ιταλία: Serie C/D = tier3/tier4
]

# Ρητές χώρες όπου θέλουμε ΜΟΝΟ tier 1 (ζητήθηκε ρητά)
TIER1_ONLY_COUNTRIES = {
    "usa", "canada", "mexico",                          # Βόρεια Αμερική
    "peru", "uruguay", "bolivia", "paraguay", "venezuela",
    "ecuador", "colombia", "chile",                       # Νότια Αμερική (ζητημένες)
    "australia", "japan", "china",
    "qatar", "united-arab-emirates", "saudi-arabia",
}

# Χώρες από τη ρητή λίστα ΧΩΡΙΣ κύπελλο (ζητήθηκε ρητά μόνο tier1, χωρίς αναφορά σε κύπελλο)
TIER1_ONLY_NO_CUP = {"australia", "japan", "china"}

# Ολόκληρη η Ευρώπη (μέλη UEFA) -- εδώ θέλουμε tier1 + tier2 + κύπελλο για ΟΛΕΣ.
# Ονόματα όπως τα επιστρέφει το API-Football (country.name), lowercase + κενά->παύλες.
# ΠΡΟΣ ΕΠΙΒΕΒΑΙΩΣΗ στο πρώτο πραγματικό log πριν το θεωρήσουμε τελικό.
EUROPE_COUNTRIES = {
    "england", "spain", "italy", "germany", "france", "portugal",
    "netherlands", "belgium", "turkey", "greece", "scotland",
    "switzerland", "austria", "sweden", "norway", "denmark", "poland",
    "wales", "northern-ireland", "republic-of-ireland", "ireland",
    "russia", "ukraine", "czech-republic", "slovakia", "hungary",
    "romania", "bulgaria", "serbia", "croatia", "slovenia",
    "bosnia-and-herzegovina", "north-macedonia", "albania", "montenegro",
    "kosovo", "moldova", "belarus", "lithuania", "latvia", "estonia",
    "finland", "iceland", "luxembourg", "malta", "cyprus", "georgia",
    "armenia", "azerbaijan", "kazakhstan", "andorra", "san-marino",
    "faroe-islands", "gibraltar", "liechtenstein",
}

# Λέξεις που δείχνουν διεθνή/ηπειρωτική διοργάνωση club-level
INTERNATIONAL_CLUB_KEYWORDS = [
    "champions league", "europa league", "conference league",
    "libertadores", "sudamericana", "concacaf champions",
    "caf champions league", "caf confederation", "afc champions",
]

# Λέξεις που δείχνουν φιλικό αγώνα -- αποκλείονται εντελώς, σε οποιαδήποτε μορφή
FRIENDLY_KEYWORDS = ["friendlies", "friendly"]

# Λέξεις που δείχνουν διοργάνωση εθνικών ομάδων
NATIONAL_TEAM_KEYWORDS = [
    "world cup", "euro championship", "european championship",
    "copa america", "africa cup", "nations league", "qualification",
    "confederations cup", "asian cup", "gold cup",
]

EUROPE_CONTINENT_COUNTRIES = None  # γεμίζει δυναμικά από το API αν χρειαστεί


def _main_segment(name: str) -> str:
    """
    Κόβει το όνομα πριν από τυχόν 'όμιλο/group' (π.χ. 'Girone 2', '- Group A'),
    ώστε αριθμοί ομίλων να μην μπερδεύονται με τον αριθμό κατηγορίας.
    'Norway 3. Division - Girone 2' -> 'Norway 3. Division'
    """
    for sep in (" - ", " – ", " — "):
        if sep in name:
            return name.split(sep)[0]
    return name


def _is_tier2(name: str) -> bool:
    name_l = _main_segment(name).lower().strip()
    return any(re.search(p, name_l) for p in TIER2_PATTERNS)


def _is_tier3_plus(name: str) -> bool:
    name_l = _main_segment(name).lower().strip()
    return any(re.search(p, name_l) for p in TIER3_PLUS_PATTERNS)


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

        # Φιλικοί αγώνες -- αποκλείονται εντελώς, σε οποιαδήποτε κατηγορία
        if _matches_any(name_l, FRIENDLY_KEYWORDS):
            continue

        # Διεθνείς διοργανώσεις (χωρίς συγκεκριμένη χώρα, ή World)
        if _matches_any(name_l, INTERNATIONAL_CLUB_KEYWORDS):
            result["international_club"].append(league_id)
            continue

        if _matches_any(name_l, NATIONAL_TEAM_KEYWORDS) or country_name == "world":
            result["national_team"].append(league_id)
            continue

        in_europe = country_name in EUROPE_COUNTRIES
        in_explicit_list = country_name in TIER1_ONLY_COUNTRIES

        # Αγνόησε εντελώς χώρες που δεν είναι ούτε Ευρώπη ούτε στη ρητή λίστα
        if not in_europe and not in_explicit_list:
            continue

        if is_cup_type:
            wants_cup = in_europe or (in_explicit_list and country_name not in TIER1_ONLY_NO_CUP)
            if wants_cup:
                result["domestic_cups"].append(league_id)
            continue

        # Domestic league -- tier 1 ή tier 2. Ρητά αποκλείουμε tier3+ ΠΡΩΤΑ,
        # πριν καν ελέγξουμε tier2 (ώστε π.χ. "2. divisjon" Νορβηγίας να μην
        # περάσει ποτέ ως tier2 απλά και μόνο επειδή περιέχει το "2").
        if _is_tier3_plus(name_l):
            continue

        if in_explicit_list:
            if not _is_tier2(name_l):
                result["tier1"].append(league_id)
            # tier2 αγνοείται ρητά για τις χώρες της ρητής λίστας
        elif in_europe:
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
