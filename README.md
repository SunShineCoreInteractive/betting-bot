# Auto Bet — Σύστημα Στατιστικής Ανάλυσης Στοιχήματος

Αυτόματο σύστημα που αναλύει αγώνες ποδοσφαίρου μέσω API-Football και στέλνει
προβλέψεις σε 4 κανάλια Telegram όταν εντοπίζει στατιστική "ευκαιρία" (value bet).

## Τι κάνει (Φάση 1)

- **Auto Bet (Μονά)** — μονές επιλογές, έλεγχος κάθε 5', αγώνες που ξεκινούν
  εντός της επόμενης ώρας
- **Auto Bet (Παρολί)** — 2-3 επιλογές από διαφορετικούς αγώνες
- **Auto Bet (Bet Builder)** — 2-3 επιλογές από τον ΙΔΙΟ αγώνα
- **Auto Bet (Live)** — μονές επιλογές σε ζωντανούς αγώνες, έλεγχος κάθε 1'

**Markets Φάσης 1:** Over/Under Γκολ (1.5 / 2.5 / 3.5), BTTS (Και Οι Δύο Σκοράρουν).
Κόρνερ / Κάρτες / Παίκτες θα προστεθούν σε επόμενη φάση.

**Λίγκες:** Αυτόματη ανίχνευση tier 1 / tier 2 / κύπελλα / διεθνείς διοργανώσεις
από το ίδιο το API (βλ. `league_classifier.py`) — τρέξε το startup log μία φορά
και έλεγξε τη λίστα πριν αφήσεις το σύστημα να στέλνει live.

## Δομή αρχείων

| Αρχείο | Τι κάνει |
|---|---|
| `config.py` | Όλες οι ρυθμίσεις (συχνότητες, κατώφλια, κανάλια) |
| `api_football.py` | Κλήσεις προς το API-Football, με caching |
| `league_classifier.py` | Αυτόματη ταξινόμηση λιγκών σε tier1/tier2/cups/διεθνή |
| `analysis.py` | Το στατιστικό μοντέλο (Poisson goal model) |
| `odds_parser.py` | Μετατρέπει raw odds response σε απλό dict |
| `telegram_sender.py` | Στέλνει μηνύματα, φτιάχνει το format τους |
| `sent_tracker.py` | Μνήμη ώστε να μην ξαναστέλνει το ίδιο δύο φορές |
| `main.py` | Ο scheduler loop — το πρόγραμμα που τρέχει συνέχεια |

## Πώς να το ανεβάσεις στο GitHub

1. Πήγαινε στο repo σου στο GitHub (web browser)
2. **Add file → Upload files**
3. Σύρε μέσα ΟΛΑ τα αρχεία αυτού του φακέλου (εκτός από τυχόν `.env` αν το
   έφτιαξες τοπικά — δεν χρειάζεται να ανέβει, το `.gitignore` το προστατεύει
   ούτως ή άλλως)
4. **Commit changes**

## Πώς να το στήσεις στο Render

1. Render Dashboard → **New +** → **Background Worker** (όχι Web Service —
   αυτό το πρόγραμμα δεν εξυπηρετεί ιστοσελίδα, απλά τρέχει συνέχεια στο παρασκήνιο)
2. Συνδέσε το GitHub repo σου
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `python main.py`
5. **Environment** (Settings → Environment → Add Environment Variable):
   - `API_FOOTBALL_KEY` = το κλειδί σου
   - `TELEGRAM_BOT_TOKEN` = το token του bot σου
6. **Create Background Worker**

Το Render θα κάνει build και θα ξεκινήσει αυτόματα. Στα **Logs** θα βλέπεις
σε πραγματικό χρόνο τι κάνει (πόσους αγώνες βρήκε, τι έστειλε, πόσα API calls
έχει κάνει σήμερα).

## Πρώτος έλεγχος πριν το αφήσεις χωρίς επίβλεψη

Στα πρώτα logs μετά το deploy, θα δεις μια λίστα με όλες τις λίγκες που
ταξινομήθηκαν ως tier1 / tier2 / domestic_cups / international_club / national_team.
**Έλεγξέ τη** — αν κάτι λείπει ή μπήκε λάθος, πες μου να διορθώσουμε τη
λογική ταξινόμησης στο `league_classifier.py`.

## Επόμενα βήματα (Φάση 2)

- Κόρνερ, Κάρτες, Παίκτες markets
- Πιο εξελιγμένο live μοντέλο (προσαρμογή με βάση το τρέχον σκορ/λεπτό αγώνα,
  όχι μόνο το pre-match στατιστικό προφίλ)
- Asian Handicap markets (η βάση `prob_handicap_home` υπάρχει ήδη στο
  `analysis.py`, λείπει μόνο η ενσωμάτωση στο μήνυμα)
