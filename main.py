import os
import time
import threading
import requests
from datetime import datetime
from flask import Flask

# --- WEBSERVER ΓΙΑ ΤΟ RENDER (Health Check) ---
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
    "MAIN": -1004451641508,        # 1. Pre-match
    "SPECIAL": -1003976882916,     # 2. Specials
    "PAROLI": -1004400781523,      # 3. Paroli
    "LIVE": -1003946267636,        # 4. Live Value Alerts
    "RED_CARDS": -1003987886550    # 5. Red Cards
}

processed_red_cards = set()

def send_telegram(channel_key, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNELS[channel_key], "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Σφάλμα Telegram: {e}", flush=True)

def fetch_live_fixtures():
    url = f"https://{API_HOST}/fixtures?live=all"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("response", [])
        else:
            print(f"⚠️ API Status Error: {res.status_code}", flush=True)
    except Exception as e:
        print(f"⚠️ Σφάλμα API Fetch: {e}", flush=True)
    return []

def continuous_live_engine():
    while True:
        fixtures = fetch_live_fixtures()
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"[{now_str}] 📡 API Engine: Σκανάρισμα σε {len(fixtures)} ζωντανούς αγώνες.", flush=True)

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            teams = fix.get("teams", {})
            home = teams.get("home", {}).get("name", "Home")
            away = teams.get("away", {}).get("name", "Away")
            
            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", 0)
            goals = fix.get("goals", {})
            score_str = f"{goals.get('home', 0)} - {goals.get('away', 0)}"

            # Έλεγχος Καρτών / Events
            events = fix.get("events", [])
            for event in events:
                if event.get("type") == "Card" and event.get("detail") in ["Red Card", "Yellow 2nd Card"]:
                    team_name = event.get("team", {}).get("name")
                    player = event.get("player", {}).get("name", "Player")
                    key = f"{fixture_id}_red_{event.get('time', {}).get('elapsed')}_{team_name}"

                    if key not in processed_red_cards:
                        msg = f"🔴 *[RED CARD ALERT]*\n\n⚔️ **{home} vs {away}** ({elapsed}')\n🚨 **Αποβολή:** {team_name} ({player})\n🔢 **Σκορ:** {score_str}\n\n⚡ *Instant Official Feed*"
                        send_telegram("RED_CARDS", msg)
                        processed_red_cards.add(key)

        time.sleep(15)  # Κλήση κάθε 15 δευτερόλεπτα (εντός ορίων Pro Plan)

if __name__ == "__main__":
    print("🚀 Εκκίνηση Επίσημου API-Football Engine...", flush=True)
    send_telegram("RED_CARDS", "🧪 *[OFFICIAL API ENGINE ONLINE]* Το σύστημα είναι συνδεδεμένο και τρέχει 24/7!")
    
    t1 = threading.Thread(target=continuous_live_engine, daemon=True)
    t1.start()
    
    run_flask()
