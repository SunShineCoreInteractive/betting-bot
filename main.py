import os
import time
import threading
from datetime import datetime
import cloudscraper
from flask import Flask

# --- WEBSERVER ΓΙΑ ΤΟ RENDER (Λύνει το Port Scan Timeout) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "All Betting Engines Active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- CONFIGURATION TELEGRAM ---
TELEGRAM_TOKEN = "8881899162:AAGEO_aWsZfBMCUDc3lLTfq-_QUXlhZSW-0"

CHANNELS = {
    "MAIN": -1004451641508,        # 1. 1X2, O/U, G/G
    "SPECIAL": -1003976882916,     # 2. Ειδικά (Κάρτες/Κόρνερ)
    "PAROLI": -1004400781523,      # 3. Παρολί
    "LIVE": -1003946267636,        # 4. Live Value Alerts
    "RED_CARDS": -1003987886550    # 5. Red Cards Feed
}

processed_matches = set()

# Bypasser για τα 403 Blocks
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def send_telegram(channel_key, text):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNELS[channel_key], "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Σφάλμα Telegram: {e}")

# --- API FETCHERS ---
def fetch_scheduled_events():
    url = "https://api.sofascore.com/api/v1/sport/football/scheduled-events/today"
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            return res.json().get("events", [])
    except Exception as e:
        print(f"⚠️ Σφάλμα Pre-Match Fetch: {e}")
    return []

def fetch_live_events():
    url = "https://api.sofascore.com/api/v1/sport/football/events/live"
    try:
        res = scraper.get(url, timeout=10)
        if res.status_code == 200:
            return res.json().get("events", [])
    except Exception as e:
        print(f"⚠️ Σφάλμα Live Fetch: {e}")
    return []

# --- ENGINES ---
def continuous_prematch_engine():
    """Κανάλια 1, 2, 3: Pre-Match, Specials & Paroli"""
    while True:
        events = fetch_scheduled_events()
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"[{now_str}] 📋 Pre-Match Engine: Σκανάρισμα σε {len(events)} αγώνες.")
        time.sleep(300)

def continuous_live_engine():
    """Κανάλια 4 & 5: Live Value Alerts & Red Cards"""
    while True:
        events = fetch_live_events()
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"[{now_str}] 📡 Live Engine: Σκανάρισμα σε {len(events)} ζωντανούς αγώνες.")

        for event in events:
            match_id = event.get("id")
            home = event.get("homeTeam", {}).get("name", "Home")
            away = event.get("awayTeam", {}).get("name", "Away")
            minute = event.get("time", {}).get("played", 0)
            
            home_reds = event.get("homeScore", {}).get("redCards", 0)
            away_reds = event.get("awayScore", {}).get("redCards", 0)
            score = f"{event.get('homeScore', {}).get('current', 0)} - {event.get('awayScore', {}).get('current', 0)}"

            # Κανάλι 5: Red Cards
            if home_reds > 0 or away_reds > 0:
                key = f"{match_id}_red"
                if key not in processed_matches:
                    msg = f"🔴 *[RED CARD ALERT]*\n\n⚔️ **{home} vs {away}** ({minute}')\n🔢 **Σκορ:** {score}"
                    send_telegram("RED_CARDS", msg)
                    processed_matches.add(key)

        time.sleep(15)

if __name__ == "__main__":
    print("🚀 Εκκίνηση Πλήρους Συστήματος...")
    
    # Αποστολή επιβεβαίωσης έναρξης στα κανάλια
    send_telegram("RED_CARDS", "🧪 *[SYSTEM ONLINE]* Το σύστημα είναι live 24/7 στο Render!")
    
    t1 = threading.Thread(target=continuous_prematch_engine, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=continuous_live_engine, daemon=True)
    t2.start()
    
    # Εκκίνηση του Web Server (πράσινο φως στο Render)
    run_flask()
