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
    "MAIN": -1004451641508,        # 1. Pre-Match Picks
    "SPECIAL": -1003976882916,     # 2. Ειδικά
    "PAROLI": -1004400781523,      # 3. Παρολί
    "LIVE": -1003946267636,        # 4. Live Value Alerts
    "RED_CARDS": -1003987886550    # 5. Red Cards
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
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
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
    """Κανάλια 1, 2, 3: Pre-Match, Specials & Paroli (Μόνο για αγώνες επόμενης 1 ώρας)"""
    while True:
        fixtures = fetch_today_fixtures()
        now_utc = datetime.now(timezone.utc)
        one_hour_later = now_utc + timedelta(hours=1)
        now_str = datetime.now().strftime('%H:%M:%S')
        
        print(f"[{now_str}] 📋 Pre-Match Engine: Έλεγχος αγώνων που ξεκινάνε την επόμενη 1 ώρα...", flush=True)
        
        paroli_candidates = []

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            status = fix.get("fixture", {}).get("short")
            fixture_date_str = fix.get("fixture", {}).get("date")

            if status == "NS" and fixture_date_str:
                # Μετατροπή ημερομηνίας αγώνα σε UTC datetime
                fixture_time = datetime.fromisoformat(fixture_date_str.replace("Z", "+00:00"))

                # Φίλτρο: Αγώνες που ξεκινάνε μεταξύ ΤΩΡΑ και ΕΠΟΜΕΝΗΣ 1 ΩΡΑΣ
                if now_utc <= fixture_time <= one_hour_later:
                    teams = fix.get("teams", {})
                    home = teams.get("home", {}).get("name", "Home")
                    away = teams.get("away", {}).get("name", "Away")
                    time_str = fixture_time.strftime('%H:%M UTC')

                    key_main = f"main_{fixture_id}"
                    key_spec = f"spec_{fixture_id}"

                    # 1. Κανάλι MAIN (Πολλαπλές προτάσεις ανά αγώνα)
                    if key_main not in processed_events:
                        msg = (
                            f"⏰ *[MATCH IN 1 HOUR]* ({time_str})\n"
                            f"⚔️ **{home} vs {away}**\n\n"
                            f"💡 **Προτάσεις:**\n"
                            f"• Over 2.5 Goals\n"
                            f"• Both Teams To Score (Goal/Goal)\n"
                            f"• 1X (Home Win or Draw)\n\n"
                            f"📊 *Official API Feed*"
                        )
                        send_telegram("MAIN", msg)
                        processed_events.add(key_main)

                    # 2. Κανάλι SPECIAL (Πολλαπλές ειδικές προτάσεις ανά αγώνα)
                    if key_spec not in processed_events:
                        msg = (
                            f"🎯 *[SPECIAL BETS - 1 HOUR LEFT]*\n"
                            f"⚔️ **{home} vs {away}**\n\n"
                            f"🟨 **Κάρτες:** Over 4.5 Κίτρινες Κάρτες\n"
                            f"🚩 **Κόρνερ:** Over 8.5 Συνολικά Κόρνερ\n"
                            f"⚽ **Anytime Scorer:** Πρώτο Ημίχρονο Over 0.5 Goal"
                        )
                        send_telegram("SPECIAL", msg)
                        processed_events.add(key_spec)

                    # Συλλογή για Παρολί
                    key_paroli_item = f"paroli_item_{fixture_id}"
                    if key_paroli_item not in processed_events and len(paroli_candidates) < 3:
                        paroli_candidates.append(f"• **{home} vs {away}**: Over 1.5 Goals")
                        processed_events.add(key_paroli_item)

        # 3. Κανάλι PAROLI (Σύνθεση όταν υπάρχουν διαθέσιμοι αγώνες 1 ώρας)
        if len(paroli_candidates) >= 2:
            paroli_msg = "🎟️ *[PAROLI - UPCOMING MATCHES]*\n\n" + "\n".join(paroli_candidates) + "\n\n🔥 **Συνολική Απόδοση:** ~3.20"
            send_telegram("PAROLI", paroli_msg)

        # Έλεγχος ανά 15 λεπτά για να πιάνει συνεχώς το παράθυρο της 1 ώρας
        time.sleep(900)

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

            # 4. Κανάλι LIVE (Alert στο 65'-75' με 0-0)
            if 65 <= elapsed <= 75 and goals.get('home', 0) + goals.get('away', 0) == 0:
                key_live = f"live_val_{fixture_id}"
                if key_live not in processed_events:
                    msg = f"⚡ *[LIVE VALUE ALERT]*\n\n⚔️ **{home} vs {away}** ({elapsed}')\n🔢 **Σκορ:** {score_str}\n💡 **Πρόταση:** Over 0.5 Late Goal"
                    send_telegram("LIVE", msg)
                    processed_events.add(key_live)

            # 5. Κανάλι RED CARDS (Αποβολές - Στέλνει αμέσως τη στιγμή της κόκκινης)
            events = fix.get("events", [])
            for event in events:
                if event.get("type") == "Card" and event.get("detail") in ["Red Card", "Yellow 2nd Card"]:
                    team_name = event.get("team", {}).get("name")
                    player = event.get("player", {}).get("name", "Player")
                    event_time = event.get("time", {}).get("elapsed", elapsed)
                    key_red = f"red_{fixture_id}_{event_time}_{team_name}"

                    if key_red not in processed_events:
                        msg = f"🔴 *[RED CARD ALERT]*\n\n⚔️ **{home} vs {away}** ({elapsed}')\n🚨 **Αποβολή:** {team_name} ({player})\n🔢 **Σκορ:** {score_str}\n\n⚡ *Official Feed*"
                        send_telegram("RED_CARDS", msg)
                        processed_events.add(key_red)

        time.sleep(20)  # Live σκανάρισμα κάθε 20 δευτερόλεπτα

if __name__ == "__main__":
    print("🚀 Εκκίνηση Πλήρους Συστήματος API-Football (1-Hour Window Engine)...", flush=True)
    
    t1 = threading.Thread(target=continuous_prematch_engine, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=continuous_live_engine, daemon=True)
    t2.start()
    
    run_flask()
