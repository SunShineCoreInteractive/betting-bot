"""
Κεντρικές ρυθμίσεις του συστήματος.
Τα μυστικά (API key, Telegram token) διαβάζονται από Environment Variables
-- ΠΟΤΕ δεν είναι γραμμένα εδώ μέσα. Τα βάζεις στο Render (Settings -> Environment).

ΝΕΑ ΑΡΧΙΤΕΚΤΟΝΙΚΗ (Αύγουστος 2026):
  - 12 κανάλια, ένα ανά τύπο market (όχι πια Μονά/Παρολί/Bet Builder/Live)
  - Χωρίς Live -- μόνο pre-match, έλεγχος κάθε λίγες ώρες σε κυλιόμενο παράθυρο
  - Αποτέλεσμα (ΚΕΡΔΙΣΕ/ΕΧΑΣΕ) γίνεται με ΕΠΕΞΕΡΓΑΣΙΑ του ίδιου μηνύματος (emoji),
    όχι νέο μήνυμα
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

# 12 κανάλια, ένα ανά τύπο market -- IDs επιβεβαιωμένα από το πραγματικό
# Telegram (getUpdates), όχι από το Word (είχε 1 λάθος διπλότυπο).
BET_TYPE_CHANNELS = {
    "1x2":              -1004451641508,   # 1-Χ-2 (Τελικό Αποτέλεσμα)
    "gg_ng":            -1003976882916,   # G/G & N/G (Goal / No Goal)
    "ou":               -1003946267636,   # O/U (Over/Under Τερμάτων)
    "double_chance":    -1004400781523,   # Καλύψεις & Συνδυαστικά (Διπλή Ευκαιρία)
    "dnb":              -1003302802436,   # Draw No Bet
    "combo_bets":       -1004337264902,   # Combo Bets (συνδυασμός 2 markets ίδιου αγώνα)
    "eidika_hmixrono":  -1004348467425,   # Ειδικά Αγορών & Ημιχρόνου (Η/Τ, Ο/U Ημιχρόνου)
    "multi_goals":      -1004357352301,   # Σύνολο Γκολ (εύρος τερμάτων, π.χ. 2-3 γκολ)
    "asian_handicap":   -1004356999932,   # Ασιατικό Χάντικαπ
    "eidika_omadon":    -1004385747147,   # Ειδικά Ομάδων (Over/Under ομάδας, Clean Sheet)
    "eidika_paikton":   -1003968258879,   # Ειδικά Παίκτες & Στατιστικά (Σκόρερ)
    "stats_agona":      -1003962743877,   # Στατιστικά Αγώνα (Κάρτες, Κόρνερ, Σουτ, Πέναλτι)
}

# Ποιο κανάλι αντιστοιχεί σε κάθε "οικογένεια" market που ήδη υπολογίζουμε
MARKET_FAMILY_TO_CHANNEL = {
    "1X2": "1x2",
    "BTTS": "gg_ng",
    "Goals O/U": "ou",
    "Corners": "stats_agona",
    "Cards": "stats_agona",
    "Scorer": "eidika_paikton",
    "DNB": "dnb",
    "Double Chance": "double_chance",
    "HT/FT": "eidika_hmixrono",
    "Correct Score": "eidika_hmixrono",
    "Multi Goals": "multi_goals",
    "Asian Handicap": "asian_handicap",
    "Team Goals": "eidika_omadon",
    "Clean Sheet": "eidika_omadon",
}

# ── Συχνότητα ελέγχου (ΧΩΡΙΣ Live -- μόνο pre-match) ─────────────
# Κάθε τόσες ώρες ελέγχουμε ΤΟ ΙΔΙΟ διάστημα ωρών μπροστά (κυλιόμενο παράθυρο).
# π.χ. αν τρέξει 09:00, καλύπτει αγώνες 09:00-12:00. Επόμενος έλεγχος στις 12:00,
# καλύπτει 12:00-15:00. Άρα το παράθυρο = το ίδιο νούμερο με το interval.
MARKET_CHECK_INTERVAL_HOURS = 3
RESULTS_CHECK_INTERVAL_MIN = 5   # πόσο συχνά ελέγχουμε αν τελείωσαν αγώνες, για επεξεργασία emoji

# ── Στατιστικά κριτήρια ──────────────────────────────────────────
MIN_SAMPLE_SIZE = 6            # ελάχιστος αριθμός πρόσφατων αγώνων ανά ομάδα για αξιόπιστη ανάλυση
VALUE_EDGE_THRESHOLD = 0.05    # ελάχιστο edge (5%) ώστε μια επιλογή να θεωρείται "ευκαιρία"

# Καθολικό όριο πιθανότητας -- στόχος 60%, επιτρέπεται να πέσει λίγο παρακάτω
# αν δεν βγαίνει τίποτα στο 60%, αλλά ΠΟΤΕ κάτω από αυτό το σκληρό όριο.
MIN_MODEL_PROBABILITY = 0.55
TARGET_MODEL_PROBABILITY = 0.60   # μόνο για αναφορά/λογική ταξινόμησης, όχι hard cutoff

# Αποδόσεις -- ελάχιστο 1.20, ΧΩΡΙΣ ανώτατο όριο (ο χρήστης θα κρίνει ο ίδιος)
MIN_ODDS = 1.20

# ── Μόνιμη αποθήκευση (Render Disk) -- ώστε οι εκκρεμείς προβλέψεις προς
# έλεγχο αποτελέσματος να ΕΠΙΒΙΩΝΟΥΝ σε κάθε redeploy, όχι να χάνονται.
PERSISTENT_DATA_DIR = os.environ.get("PERSISTENT_DATA_DIR", "/var/data")

# Πόσους πρόσφατους αγώνες τραβάμε ανά ομάδα για τη στατιστική βάση
RECENT_FIXTURES_LOOKBACK = 10

# Cache διάρκειας (ώρες) για δεδομένα που δεν χρειάζεται να ξαναζητάμε συνέχεια
LEAGUE_CACHE_HOURS = 168      # 1 εβδομάδα
TEAM_STATS_CACHE_HOURS = 24   # 1 μέρα
BET_TYPES_CACHE_HOURS = 168   # 1 εβδομάδα

# Ανώτατο "λογικό" όριο συνολικών αναμενόμενων γκολ ενός αγώνα. Αν το μοντέλο
# βγάλει κάτι πιο ψηλό (συνήθως λόγω λίγων/ασταθών δεδομένων σε μικρές λίγκες),
# ΔΕΝ στέλνουμε πρόβλεψη -- προτιμάμε καμία πρόβλεψη από αναξιόπιστη.
MAX_PLAUSIBLE_TOTAL_GOALS = 5.0

# Προτιμώμενες στοιχηματικές -- αν υπάρχει odds από αυτές, χρησιμοποιούμε ΜΟΝΟ
# αυτές (διάμεσος μεταξύ τους), αλλιώς πέφτουμε πίσω στη διάμεσο όλων.
PREFERRED_BOOKMAKERS = [
    "novibet", "stoiximan", "pamestoixima", "pame stoixima", "elabet",
    "superbet", "netbet", "winmasters", "interwetten", "bwin", "vistabet",
    "sportingbet", "fonbet", "betsson", "efbet", "bet365",
]

# ── Κόρνερ / Κάρτες ────────────────────────────────────────────
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

# ── Σκόρερ ─────────────────────────────────────────────────────
PLAYER_STATS_CACHE_HOURS = 24
SCORER_MIN_MINUTES = 450          # ελάχιστα λεπτά συμμετοχής season για αξιόπιστη εκτίμηση (~5 αγώνες)
SCORER_NAME_MATCH_THRESHOLD = 0.72   # ελάχιστη ομοιότητα ονόματος (0-1) για ταίριασμα με το market

# ── Combo Bets (ίδιος αγώνας, 2 markets μαζί, π.χ. "1Χ & Over 2.5") ──
COMBO_BETS_MIN_LEG_PROB = 0.55
COMBO_BETS_MIN_LEGS = 2
COMBO_BETS_MAX_LEGS = 2
COMBO_BETS_CORRELATION_PENALTY = 0.90
COMBO_BETS_MIN_COMBINED_PROB = 0.30

# ── Ειδικά όρια για markets με ΠΟΛΛΕΣ πιθανές εκβάσεις ────────────
# Το Ακριβές Σκορ (~36 πιθανά σκορ) και το Η/Τ (9 συνδυασμοί) έχουν ΔΟΜΙΚΑ
# χαμηλότερη μέγιστη πιθανότητα ανά έκβαση απ' ό,τι π.χ. το Over/Under (2
# εκβάσεις) -- το καθολικό όριο 55% θα τα απέκλειε ΠΑΝΤΑ. Αντισταθμίζουμε
# με χαμηλότερο όριο πιθανότητας αλλά ΨΗΛΟΤΕΡΟ απαιτούμενο edge.
CORRECT_SCORE_MIN_PROB = 0.08
CORRECT_SCORE_MIN_EDGE = 0.02   # χαμηλότερο απ' ό,τι το καθολικό -- το edge δεν μπορεί ποτέ να ξεπεράσει το ίδιο το model_prob
HTFT_MIN_PROB = 0.15
HTFT_MIN_EDGE = 0.04

# ── Παλιές ρυθμίσεις Live (ΔΕΝ χρησιμοποιούνται πια -- το Live αφαιρέθηκε).
# Παραμένουν εδώ μόνο ώστε οι σχετικές (αχρησιμοποίητες πλέον) συναρτήσεις στο
# analysis.py/api_football.py να μη σκάνε αν κάποιος τις ξανακαλέσει στο μέλλον.
RED_CARD_OWN_REDUCTION_PER_CARD = 0.25
RED_CARD_OPPONENT_BOOST_PER_CARD = 0.30
RED_CARD_MAX_REDUCTION = 0.50
RED_CARD_MAX_BOOST = 0.60
RED_CARD_EVENTS_CACHE_SECONDS = 180
