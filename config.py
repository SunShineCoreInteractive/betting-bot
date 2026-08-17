"""
Κεντρικές ρυθμίσεις του συστήματος.
Τα μυστικά (API key, Telegram token) διαβάζονται από Environment Variables
-- ΠΟΤΕ δεν είναι γραμμένα εδώ μέσα. Τα βάζεις στο Render (Settings -> Environment).
"""

import os

# ── API-Football ──────────────────────────────────────────────
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
API_FOOTBALL_HOST = "v3.football.api-sports.io"
API_FOOTBALL_BASE_URL = f"https://{API_FOOTBALL_HOST}"
API_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}

# ── Telegram ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_BASE = "https://api.telegram.org"

TELEGRAM_CHANNELS = {
    "singles":     -1004451641508,   # Auto Bet (Μονά)
    "parlay":      -1004400781523,   # Auto Bet (Παρολί)
    "bet_builder": -1003976882916,   # Auto Bet (Bet Builder)
    "live":        -1003946267636,   # Auto Bet (Live)
}

# ── Συχνότητες ελέγχου (λεπτά) ──────────────────────────────────
PREMATCH_CHECK_INTERVAL_MIN = 5
LIVE_CHECK_INTERVAL_MIN = 1
RESULTS_CHECK_INTERVAL_MIN = 5   # πόσο συχνά ελέγχουμε αν τελείωσαν αγώνες για ΚΕΡΔΙΣΕ/ΕΧΑΣΕ

# Το "παράθυρο" pre-match: πόσες ώρες πριν την έναρξη αρχίζουμε να κοιτάμε έναν αγώνα
PREMATCH_WINDOW_HOURS = 1

# ── Στατιστικά κριτήρια ──────────────────────────────────────────
MIN_SAMPLE_SIZE = 6            # ελάχιστος αριθμός πρόσφατων αγώνων ανά ομάδα για αξιόπιστη ανάλυση
VALUE_EDGE_THRESHOLD = 0.05    # ελάχιστο edge (5%) ώστε μια μονή επιλογή να θεωρείται "ευκαιρία"
MIN_MODEL_PROBABILITY = 0.50   # καθολικό ελάχιστο (το χαμηλότερο απ' όλα τα κανάλια) -- τα ειδικά όρια ανά κανάλι εφαρμόζονται ξεχωριστά παρακάτω

# ── Όρια ΑΝΑ ΚΑΝΑΛΙ (πιθανότητα + εύρος απόδοσης) ────────────────
SINGLES_MIN_PROB = 0.60
SINGLES_ODDS_MIN = 1.30
SINGLES_ODDS_MAX = 3.50

LIVE_MIN_PROB = 0.60
LIVE_ODDS_MIN = 1.30
LIVE_ODDS_MAX = 5.00

PARLAY_COMBINED_ODDS_MIN = 2.00
PARLAY_COMBINED_ODDS_MAX = 7.00

BET_BUILDER_ODDS_MIN = 2.50
BET_BUILDER_ODDS_MAX = 10.00

BET_BUILDER_MIN_LEG_PROB = 0.55   # ελάχιστη εκτίμηση ανά επιλογή στο Bet Builder
BET_BUILDER_MIN_LEGS = 2
BET_BUILDER_MAX_LEGS = 3
BET_BUILDER_CORRELATION_PENALTY = 0.90   # πολλαπλασιαστής ανά επιπλέον leg (συντηρητική προσαρμογή)
BET_BUILDER_MIN_COMBINED_PROB = 0.10     # χαμηλό επίτηδες -- ο πραγματικός φύλακας είναι το εύρος απόδοσης (BET_BUILDER_ODDS_MIN/MAX), αφού odds = 1/prob

PARLAY_MIN_LEGS = 2
PARLAY_MAX_LEGS = 3
PARLAY_MIN_COMBINED_PROB = 0.48   # ελάχιστη συνολική εκτίμηση για να σταλεί το Παρολί

# Πόσους πρόσφατους αγώνες τραβάμε ανά ομάδα για τη στατιστική βάση
RECENT_FIXTURES_LOOKBACK = 10

# Cache διάρκειας (ώρες) για δεδομένα που δεν χρειάζεται να ξαναζητάμε συνέχεια
LEAGUE_CACHE_HOURS = 168      # 1 εβδομάδα
TEAM_STATS_CACHE_HOURS = 24   # 1 μέρα
BET_TYPES_CACHE_HOURS = 168   # 1 εβδομάδα

# Φάση 1 markets: μόνο αυτά αναλύουμε αυτή τη στιγμή.
# Κόρνερ / Κάρτες / Παίκτες προστίθενται σε επόμενη φάση.
ACTIVE_MARKET_GROUPS = ["goals_over_under", "btts", "handicap", "team_goals"]

# Ανώτατο "λογικό" όριο συνολικών αναμενόμενων γκολ ενός αγώνα. Αν το μοντέλο
# βγάλει κάτι πιο ψηλό (συνήθως λόγω λίγων/ασταθών δεδομένων σε μικρές λίγκες),
# ΔΕΝ στέλνουμε πρόβλεψη -- προτιμάμε καμία πρόβλεψη από αναξιόπιστη.
MAX_PLAUSIBLE_TOTAL_GOALS = 5.0

# Προτιμώμενες στοιχηματικές ...
PREFERRED_BOOKMAKERS = [
    "novibet", "stoiximan", "pamestoixima", "pame stoixima", "elabet",
    "superbet", "netbet", "winmasters", "interwetten", "bwin", "vistabet",
    "sportingbet", "fonbet", "betsson", "efbet", "bet365",
]

# ── Κόρνερ / Κάρτες (Φάση 2) ─────────────────────────────────────
CORNERS_CARDS_LOOKBACK = 6          # λιγότεροι αγώνες από τα γκολ, γιατί κοστίζει 1 call/αγώνα/ομάδα
CORNER_CARD_STATS_CACHE_HOURS = 24 * 90   # τα στατιστικά τελειωμένου αγώνα δεν αλλάζουν ποτέ -- μόνιμο cache
MIN_SAMPLE_SIZE_CORNERS_CARDS = 4
LEAGUE_AVG_CORNERS = 10.0           # τυπικός μέσος όρος συνολικών κόρνερ/αγώνα
CORNER_LINES = [8.5, 9.5, 10.5]
CARD_LINES = [2.5, 3.5, 4.5]

# Ημερήσιο πλαφόν του πλάνου σου (Pro = 7.500). Όταν πλησιάζουμε το όριο,
# σταματάμε αυτόματα τα "ακριβά" markets (κόρνερ/κάρτες/σκόρερ) για να μην
# αφήσουμε ολόκληρο το σύστημα χωρίς καθόλου προβλέψεις μέχρι το reset (00:00 UTC).
DAILY_CALL_BUDGET = 7500
DAILY_BUDGET_SAFETY_MARGIN = 500   # όταν απομένουν λιγότερα από αυτά, κόβουμε τα non-core markets

# ── Σκόρερ (Φάση 2β) ─────────────────────────────────────────────
PLAYER_STATS_CACHE_HOURS = 24
SCORER_MIN_MINUTES = 450          # ελάχιστα λεπτά συμμετοχής season για αξιόπιστη εκτίμηση (~5 αγώνες)
SCORER_NAME_MATCH_THRESHOLD = 0.72   # ελάχιστη ομοιότητα ονόματος (0-1) για ταίριασμα με το market
