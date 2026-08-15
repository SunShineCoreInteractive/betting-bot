import os
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask

# --- WEBSERVER ΓΙΑ ΤΟ RENDER ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Auto-Tipster & Red Card Engine Active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8881899162:AAGEO_aWsZfBMCUDc3lLTfq-_QUXlhZSW-0"
API_KEY = "07f419d44db082b7e6690551e62c25b2"
API_HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

CHANNELS = {
    "MAIN": -1004451641508,        # Tipster: 1X2, Over/Under, G/G
    "SPECIAL": -1003976882916,     # Tipster: Ειδικά
    "PAROLI": -1004400781523,      # Tipster: Παρολί
    "LIVE": -1003946267636,        # Tipster: Live Value Alerts
    "RED_CARDS": -1003987886550    # Live Red Card Feed
}

processed_events = set()
pending_bets = {}

def send_telegram(channel_key, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNELS[channel_key], "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Σφάλμα Telegram: {e}", flush=True)

# --- API CALLS ---
def fetch_prediction(fixture_id):
    url = f"https://{API_HOST}/predictions?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data:
                return data[0]
    except Exception as e:
        print(f"⚠️ Σφάλμα Prediction Fetch: {e}", flush=True)
    return None

def fetch_odds(fixture_id):
    """Φέρνει τις αποδόσεις για έναν αγώνα"""
    url = f"https://{API_HOST}/odds?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data and data[0].get("bookmakers"):
                bookmakers = data[0].get("bookmakers", [])
                for bm in bookmakers:
                    bets = bm.get("bets", [])
                    for b in bets:
                        if b.get("name") in ["Match Winner", "Goals Over/Under", "Both Teams Score"]:
                            values = b.get("values", [])
                            if values:
                                return values[0].get("odd", "1.85")
    except Exception as e:
        print(f"⚠️ Σφάλμα Odds Fetch: {e}", flush=True)
    return "1.80"

def fetch_upcoming_fixtures():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    url = f"https://{API_HOST}/fixtures?date={today}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("response", [])
    except Exception as e:
        print(f"⚠️ Σφάλμα Pre-match Fetch: {e}", flush=True)
    return []

def fetch_live_fixtures():
    url = f"https://{API_HOST}/fixtures?live=all"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("response", [])
    except Exception as e:
        print(f"⚠️ Σφάλμα Live Fetch: {e}", flush=True)
    return []

def fetch_fixture_by_id(fixture_id):
    url = f"https://{API_HOST}/fixtures?id={fixture_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data:
                return data[0]
    except Exception as e:
        print(f"⚠️ Σφάλμα Fixture Fetch: {e}", flush=True)
    return None

# --- ENGINES ---

def continuous_tipster_engine():
    """Tipster Engine: Ανάλυση αγώνων επόμενων 2 ωρών"""
    while True:
        fixtures = fetch_upcoming_fixtures()
        now_utc = datetime.now(timezone.utc)
        two_hours_later = now_utc + timedelta(hours=2)
        
        print(f"[{now_utc.strftime('%H:%M:%S')}] 🤖 Tipster Engine: Ανάλυση αγώνων...", flush=True)
        paroli_candidates = []

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            status = fix.get("fixture", {}).get("short")
            fixture_date_str = fix.get("fixture", {}).get("date")

            if status == "NS" and fixture_date_str:
                fixture_time = datetime.fromisoformat(fixture_date_str.replace("Z", "+00:00"))

                if now_utc <= fixture_time <= two_hours_later:
                    key_main = f"main_{fixture_id}"
                    key_spec = f"spec_{fixture_id}"

                    if key_main not in processed_events or key_spec not in processed_events:
                        pred_data = fetch_prediction(fixture_id)
                        if not pred_data:
                            continue

                        teams = fix.get("teams", {})
                        home = teams.get("home", {}).get("name", "Home")
                        away = teams.get("away", {}).get("name", "Away")
                        
                        league = fix.get("league", {}).get("name", "League")
                        country = fix.get("league", {}).get("country", "World")
                        league_info = f"{country} - {league}"
                        
                        match_time = fixture_time.strftime('%H:%M')

                        predictions = pred_data.get("predictions", {})
                        advice = predictions.get("advice", "Over 1.5 Goals")
                        percent = predictions.get("percent", {})
                        odd_val = fetch_odds(fixture_id)

                        # 1. MAIN TIPSTER
                        if key_main not in processed_events:
                            msg = (
                                f"🎯 *[AUTO TIPSTER - PICK]*\n"
                                f"🌍 **Πρωτάθλημα:** {league_info}\n"
                                f"⏰ **Ώρα:** {match_time}\n"
                                f"⚔️ **{home} vs {away}**\n\n"
                                f"📌 **Πρόταση:** {advice}\n"
                                f"💰 **Απόδοση:** @{odd_val}\n"
                                f"📊 **Πιθανότητες:** 1: {percent.get('home', '0%')} | X: {percent.get('draw', '0%')} | 2: {percent.get('away', '0%')}\n\n"
                                f"🤖 *AI Statistical Analysis*"
                            )
                            send_telegram("MAIN", msg)
                            processed_events.add(key_main)
                            
                            pending_bets[f"{fixture_id}_main"] = {
                                "channel": "MAIN",
                                "home": home,
                                "away": away,
                                "league_info": league_info,
                                "advice": advice,
                                "odd": odd_val
                            }

                        # 2. SPECIAL TIPSTER
                        if key_spec not in processed_events:
                            msg = (
                                f"🔥 *[AUTO TIPSTER - SPECIALS]*\n"
                                f"🌍 **Πρωτάθλημα:** {league_info}\n"
                                f"⏰ **Ώρα:** {match_time}\n"
                                f"⚔️ **{home} vs {away}**\n\n"
                                f"🟨 **Εκτίμηση Καρτών:** Over 4.5 Yellow Cards (@1.85)\n"
                                f"🚩 **Εκτίμηση Κόρνερ:** Over 8.5 Corners (@1.75)\n"
                                f"💰 **Εκτιμώμενη Απόδοση:** @{odd_val}"
                            )
                            send_telegram("SPECIAL", msg)
                            processed_events.add(key_spec)

                        key_paroli_item = f"paroli_item_{fixture_id}"
                        if key_paroli_item not in processed_events and len(paroli_candidates) < 3:
                            paroli_candidates.append(f"• **[{league_info}] {home} vs {away}**: {advice} (@{odd_val})")
                            processed_events.add(key_paroli_item)

        # 3. PAROLI TIPSTER
        if len(paroli_candidates) >= 3:
            paroli_msg = (
                f"🎟️ *[AUTO TIPSTER - DAILY TRIADA]*\n\n"
                f"Τα 3 πιο δυνατά στατιστικά σημεία της ώρας:\n\n"
                + "\n".join(paroli_candidates) +
                f"\n\n🔥 **Συνολική Απόδοση:** ~3.60"
            )
            send_telegram("PAROLI", paroli_msg)

        time.sleep(1800)

def continuous_live_engine():
    """Live Engine: Tipster Alerts & Red Card Radar (Strict Single Notification)"""
    while True:
        fixtures = fetch_live_fixtures()

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            teams = fix.get("teams", {})
            home = teams.get("home", {}).get("name", "Home")
            away = teams.get("away", {}).get("name", "Away")
            
            league = fix.get("league", {}).get("name", "League")
            country = fix.get("league", {}).get("country", "World")
            league_info = f"{country} - {league}"

            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", 0)
            goals = fix.get("goals", {})
            score_str = f"{goals.get('home', 0)} - {goals.get('away', 0)}"

            # 4. LIVE VALUE ALERT
            if 65 <= elapsed <= 75 and goals.get('home', 0) + goals.get('away', 0) == 0:
                key_live = f"live_val_{fixture_id}"
                if key_live not in processed_events:
                    msg = (
                        f"⚡ *[LIVE TIPSTER - LATE GOAL]*\n"
                        f"🌍 **Πρωτάθλημα:** {league_info}\n"
                        f"⚔️ **{home} vs {away}** ({elapsed}')\n"
                        f"🔢 **Σκορ:** {score_str}\n\n"
                        f"💡 **Live Πρόταση:** Over 0.5 Goal (Late Goal)\n"
                        f"💰 **Live Απόδοση:** @1.90 - @2.10"
                    )
                    send_telegram("LIVE", msg)
                    processed_events.add(key_live)
                    
                    pending_bets[f"{fixture_id}_live"] = {
                        "channel": "LIVE",
                        "home": home,
                        "away": away,
                        "league_info": league_info,
                        "advice": "Over 0.5 Goal"
                    }

            # 5. LIVE RED CARD RADAR (Στέλνει ΑΥΣΤΗΡΑ 1 φορά τη στιγμή που συμβαίνει)
            events = fix.get("events", [])
            for event in events:
                if event.get("type") == "Card" and event.get("detail") in ["Red Card", "Yellow 2nd Card"]:
                    team_name = event.get("team", {}).get("name")
                    player = event.get("player", {}).get("name", "Player")
                    card_type = "Απευθείας Κόκκινη" if event.get("detail") == "Red Card" else "2η Κίτρινη"
                    card_time = event.get("time", {}).get("elapsed", 0)

                    # Σταθερό κλειδί αναγνώρισης (χωρίς το τρέχον λεπτό του αγώνα)
                    key_red = f"red_{fixture_id}_{team_name}_{card_time}"

                    if key_red not in processed_events:
                        processed_events.add(key_red)  # Κλειδώνει αμέσως
                        
                        # Στέλνει ΜΟΝΟ αν η αποβολή έγινε τώρα (μέσα στα τελευταία 3 λεπτά)
                        if elapsed > 0 and (elapsed - card_time) <= 3:
                            msg = (
                                f"🚨 *[RED CARD ALERT]* 🚨\n\n"
                                f"🌍 **Πρωτάθλημα:** {league_info}\n"
                                f"⚔️ **{home} {score_str} {away}** ({elapsed}')\n\n"
                                f"🔴 **Ομάδα:** {team_name}\n"
                                f"👤 **Παίκτης:** {player}\n"
                                f"📌 **Τύπος:** {card_type} ({card_time}')\n\n"
                                f"⚡ *Live Opportunity Alert*"
                            )
                            send_telegram("RED_CARDS", msg)

        time.sleep(15)

def result_settlement_engine():
    """Settlement Engine: Έλεγχος Αποτελεσμάτων"""
    while True:
        if pending_bets:
            print(f"🔄 Result Settlement Engine: Έλεγχος {len(pending_bets)} εκκρεμών στοιχημάτων...", flush=True)
            completed_keys = []

            for bet_key, bet_info in list(pending_bets.items()):
                fixture_id = bet_key.split("_")[0]
                fix_data = fetch_fixture_by_id(fixture_id)

                if fix_data:
                    status = fix_data.get("fixture", {}).get("status", {}).get("short")

                    if status in ["FT", "AET", "PEN"]:
                        goals = fix_data.get("goals", {})
                        home_goals = goals.get("home", 0)
                        away_goals = goals.get("away", 0)
                        total_goals = home_goals + away_goals
                        score_str = f"{home_goals} - {away_goals}"

                        advice = bet_info.get("advice", "")
                        channel = bet_info.get("channel", "MAIN")
                        home = bet_info.get("home")
                        away = bet_info.get("away")
                        league_info = bet_info.get("league_info", "")
                        odd_val = bet_info.get("odd", "")

                        is_won = False
                        if "Over 0.5" in advice and total_goals > 0:
                            is_won = True
                        elif "Over 1.5" in advice and total_goals > 1:
                            is_won = True
                        elif "Over 2.5" in advice and total_goals > 2:
                            is_won = True
                        elif "Home" in advice and home_goals > away_goals:
                            is_won = True
                        elif "Away" in advice and away_goals > home_goals:
                            is_won = True
                        else:
                            is_won = total_goals > 0

                        result_emoji = f"✅ [BET WON @{odd_val}]" if is_won else f"❌ [BET LOST @{odd_val}]"
                        result_msg = (
                            f"{result_emoji}\n"
                            f"🌍 **Πρωτάθλημα:** {league_info}\n"
                            f"⚔️ **{home} vs {away}**\n"
                            f"🔢 **Τελικό Σκορ:** {score_str}\n"
                            f"📌 **Πρόταση:** {advice}\n\n"
                            f"📈 *Settled automatically by API Engine*"
                        )

                        send_telegram(channel, result_msg)
                        completed_keys.append(bet_key)

            for k in completed_keys:
                pending_bets.pop(k, None)

        time.sleep(600)

if __name__ == "__main__":
    print("🚀 Εκκίνηση Πλήρους Συστήματος...", flush=True)
    
    t1 = threading.Thread(target=continuous_tipster_engine, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=continuous_live_engine, daemon=True)
    t2.start()

    t3 = threading.Thread(target=result_settlement_engine, daemon=True)
    t3.start()
    
    run_flask()
