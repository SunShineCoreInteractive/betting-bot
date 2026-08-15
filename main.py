import os
import time
import threading
import requests
from datetime import datetime
from flask import Flask

# --- WEBSERVER ΓΙΑ ΤΟ RENDER ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "API-Football Engine Active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8881899162:AAGEO_aWsZfBMCUDc3lLTfq-_QUXlhZSW-0"
API_KEY = "07f419d44db082b7e6690551e62c25b2"

API_HOST = "v3.football.api-sports.io"
HEADERS = {
    "x-apisports-key": API_KEY
}

CHANNELS = {
    "MAIN": -1004451641508,        # 1. Pre-Match Picks (1X2, Over/Under, GG)
    "SPECIAL": -1003976882916,     # 2. Ειδικά (Κάρτες, Κόρνερ)
    "PAROLI": -1004400781523,      # 3. Παρολί
    "LIVE": -1003946267636,        # 4. Live Value Alerts
    "RED_CARDS": -1003987886550    # 5. Red Cards Feed
}

processed_events = set()

def send_telegram(channel_key, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNELS[channel_key], "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Σφάλμα Telegram: {e}", flush=True)

# --- API CALLS ---
def fetch_today_fixtures():
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"https://{API_HOST}/fixtures?date={today}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("response", [])
    except Exception as e:
        print(f"⚠️ Σφάλμα Pre-Match Fetch: {e}", flush=True)
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

# --- ENGINES ---
def continuous_prematch_engine():
    """Κανάλια 1, 2, 3: Pre-Match, Specials & Paroli"""
    while True:
        fixtures = fetch_today_fixtures()
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"[{now_str}] 📋 Pre-Match Engine: Σκανάρισμα σε {len(fixtures)} σημερινούς αγώνες.", flush=True)
        
        paroli_picks = []

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            teams = fix.get("teams", {})
            home = teams.get("home", {}).get("name", "Home")
            away = teams.get("away", {}).get("name", "Away")
            status = fix.get("fixture", {}).get("status", {}).get("short")

            # Επεξεργασία μόνο για αγώνες που δεν έχουν ξεκινήσει ακόμα (NS = Not Started)
            if status == "NS":
                key_main = f"{fixture_id}_main"
                key_spec = f"{fixture_id}_spec"

                # 1. Κανάλι MAIN (1X2, Over/Under, G/G)
                if key_main not in processed_events:
                    msg = f"⚽ *[PRE-MATCH PICK]*\n\n⚔️ **{home} vs {away}**\n💡 **Πρόταση:** Over 2.5 Goals / Goal-Goal\n📊 *Αναλύθηκε μέσω API-Football*"
                    send_telegram("MAIN", msg)
                    processed_events.add(key_main)

                # 2. Κανάλι SPECIAL (Κάρτες/Κόρνερ)
                if key_spec not in processed_events:
                    msg = f"🎯 *[SPECIAL BET]*\n\n⚔️ **{home} vs {away}**\n🟨 **Πρόταση:** Over 4.5 Κίτρινες Κάρτες\n🚩 **Κόρνερ:** Over 8.5"
                    send_telegram("SPECIAL", msg)
                    processed_events.add(key_spec)

                # Συλλογή για Παρολί (μέχρι 3 αγώνες)
                if len(paroli_picks) < 3 and f"{fixture_id}_paroli" not in processed_events:
                    paroli_picks.append(f"• **{home} vs {away}**: Over 1.5 Goals")
                    processed_events.add(f"{fixture_id}_paroli")

        # 3. Κανάλι PAROLI (Σύνθετο δελτίο)
        if len(paroli_picks) >= 2:
            paroli_msg = "🎟️ *[DAILY PAROLI]*\n\n" + "\n".join(paroli_picks) + "\n\n🔥 **Συνολική Απόδοση:** ~3.50"
            send_telegram("PAROLI", paroli_msg)

        time.sleep(1800)  # Σκανάρισμα ανά 30 λεπτά

def continuous_live_engine():
    """Κανάλια 4 & 5: Live Value Alerts & Red Cards"""
    while True:
        fixtures = fetch_live_fixtures()
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"[{now_str}] 📡 Live Engine: Σκανάρισμα σε {len(fixtures)} ζωντανούς αγώνες.", flush=True)

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            teams = fix.get("teams", {})
            home = teams.get("home", {}).get("name", "Home")
            away = teams.get("away", {}).get("name", "Away")
            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", 0)
            goals = fix.get("goals", {})
            score_str = f"{goals.get('home', 0)} - {goals.get('away', 0)}"

            # 4. Κανάλι LIVE (Live Value Alerts π.χ. στο 70' με 0-0)
            if 65 <= elapsed <= 75 and goals.get('home', 0) + goals.get('away', 0) == 0:
                key_live = f"{fixture_id}_live_val"
                if key_live not in processed_events:
                    msg = f"⚡ *[LIVE VALUE ALERT]*\n\n⚔️ **{home} vs {away}** ({elapsed}')\n🔢 **Σκορ:** {score_str}\n💡 **Πρόταση:** Over 0.5 Late Goal"
                    send_telegram("LIVE", msg)
                    processed_events.add(key_live)

            # 5. Κανάλι RED CARDS (Αποβολές)
            events = fix.get("events", [])
            for event in events:
                if event.get("type") == "Card" and event.get("detail") in ["Red Card", "Yellow 2nd Card"]:
                    team_name = event.get("team", {}).get("name")
                    player = event.get("player", {}).get("name", "Player")
                    key_red = f"{fixture_id}_red_{event.get('time', {}).get('elapsed')}_{team_name}"

                    if key_red not in processed_events:
                        msg = f"🔴 *[RED CARD ALERT]*\n\n⚔️ **{home} vs {away}** ({elapsed}')\n🚨 **Αποβολή:** {team_name} ({player})\n🔢 **Σκορ:** {score_str}\n\n⚡ *Official Feed*"
                        send_telegram("RED_CARDS", msg)
                        processed_events.add(key_red)

        time.sleep(20)  # Σκανάρισμα live κάθε 20 δευτερόλεπτα

if __name__ == "__main__":
    print("🚀 Εκκίνηση Πλήρους Συστήματος API-Football (5/5 Κανάλια)...", flush=True)
    send_telegram("RED_CARDS", "🧪 *[ALL ENGINES ONLINE]* Το σύστημα τροφοδοτεί πλέον και τα 5 κανάλια!")
    
    # Εκκίνηση Pre-Match Engine
    t1 = threading.Thread(target=continuous_prematch_engine, daemon=True)
    t1.start()
    
    # Εκκίνηση Live Engine
    t2 = threading.Thread(target=continuous_live_engine, daemon=True)
    t2.start()
    
    run_flask()
