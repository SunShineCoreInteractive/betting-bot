import os
import time
import threading
from datetime import datetime
import cloudscraper
from flask import Flask

# --- FLASK WEBSERVER (Για το Render) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is active and running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- TELEGRAM BOT CONFIG ---
TELEGRAM_TOKEN = "8881899162:AAGEO_aWsZfBMCUDc3lLTfq-_QUXlhZSW-0"

CHANNELS = {
    "MAIN": -1004451641508,
    "SPECIAL": -1003976882916,
    "PAROLI": -1004400781523,
    "LIVE": -1003946267636,
    "RED_CARDS": -1003987886550
}

processed_red_cards = set()

# Δημιουργία Cloudscraper Session
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

def send_telegram(channel_key, text):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNELS[channel_key], "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Σφάλμα Telegram: {e}")

def fetch_live_events():
    url = "https://api.sofascore.com/api/v1/sport/football/events/live"
    try:
        response = scraper.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get("events", [])
        else:
            print(f"⚠️ Status Code: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Σφάλμα Scraper: {e}")
    return []

def continuous_red_card_tracker():
    while True:
        events = fetch_live_events()
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"[{now_str}] 📡 Live Engine: Εντοπίστηκαν {len(events)} ζωντανοί αγώνες.")

        for event in events:
            match_id = event.get("id")
            home = event.get("homeTeam", {}).get("name", "Home")
            away = event.get("awayTeam", {}).get("name", "Away")
            minute = event.get("time", {}).get("played", 0)
            
            home_reds = event.get("homeScore", {}).get("redCards", 0)
            away_reds = event.get("awayScore", {}).get("redCards", 0)
            score = f"{event.get('homeScore', {}).get('current', 0)} - {event.get('awayScore', {}).get('current', 0)}"

            if home_reds > 0:
                key = f"{match_id}_home_red_{home_reds}"
                if key not in processed_red_cards:
                    msg = f"🔴 *[RED CARD ALERT]*\n\n⚔️ **{home} vs {away}** ({minute}')\n🚨 **Αποβολή:** {home}\n🔢 **Τρέχον Σκορ:** {score}\n\n⚡ *Άμεση ενημέρωση συμβάντος!*"
                    send_telegram("RED_CARDS", msg)
                    processed_red_cards.add(key)

            if away_reds > 0:
                key = f"{match_id}_away_red_{away_reds}"
                if key not in processed_red_cards:
                    msg = f"🔴 *[RED CARD ALERT]*\n\n⚔️ **{home} vs {away}** ({minute}')\n🚨 **Αποβολή:** {away}\n🔢 **Τρέχον Σκορ:** {score}\n\n⚡ *Άμεση ενημέρωση συμβάντος!*"
                    send_telegram("RED_CARDS", msg)
                    processed_red_cards.add(key)

        time.sleep(10)

if __name__ == "__main__":
    t1 = threading.Thread(target=continuous_red_card_tracker, daemon=True)
    t1.start()
    run_flask()
