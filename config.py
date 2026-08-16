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

# Το "παράθυρο" pre-match: πόσες ώρες πριν την έναρξη αρχίζουμε να κοιτάμε έναν αγώνα
PREMATCH_WINDOW_HOURS = 1

# ── Στατιστικά κριτήρια ──────────────────────────────────────────
MIN_SAMPLE_SIZE = 6            # ελάχιστος αριθμός πρόσφατων αγώνων ανά ομάδα για αξιόπιστη ανάλυση
VALUE_EDGE_THRESHOLD = 0.05    # ελάχιστο edge (5%) ώστε μια μονή επιλογή να θεωρείται "ευκαιρία"

BET_BUILDER_MIN_LEG_PROB = 0.60   # ελάχιστη εκτίμηση ανά επιλογή στο Bet Builder
BET_BUILDER_MIN_LEGS = 2
BET_BUILDER_MAX_LEGS = 3
BET_BUILDER_CORRELATION_PENALTY = 0.90   # πολλαπλασιαστής ανά επιπλέον leg (συντηρητική προσαρμογή)
BET_BUILDER_MIN_COMBINED_PROB = 0.40     # ελάχιστο τελικό συνδυασμένο ποσοστό για να σταλεί

PARLAY_MIN_LEGS = 2
PARLAY_MAX_LEGS = 3

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
