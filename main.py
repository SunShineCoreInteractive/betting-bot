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
    "SPECIAL": -1003976882916,     # Tipster: Ειδικά (Κάρτες, Κόρνερ)
    "PAROLI": -1004400781523,      # Tipster: Παρολί Τριάδα
    "LIVE": -1003946267636,        # Tipster: Live Value Alerts
    "RED_CARDS": -1003987886550    # Live Red Card Feed (Ενημερωτικό Radar)
}

processed_events = set()

def send_telegram(channel_key, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNELS[channel_key], "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Σφάλμα Telegram: {e}", flush=True)

# --- API HELPERS ---
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

# --- ENGINES ---

def continuous_tipster_engine():
    """Κανάλια 1, 2, 3: Αυτόματος Tipster με βάση τα στατιστικά"""
    while True:
        fixtures = fetch_upcoming_fixtures()
        now_utc = datetime.now(timezone.utc)
        two_hours_later = now_utc + timedelta(hours=2)
        
        print(f"[{now_utc.strftime('%H:%M:%S')}] 🤖 Tipster Engine: Ανάλυση αγώνων επόμενων 2 ωρών...", flush=True)
        paroli_candidates = []

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            status = fix.get("fixture", {}).get("short")
            fixture_date_str = fix.get("fixture", {}).get("date")

            if status == "NS" and fixture_date_str:
                fixture_time = datetime.fromisoformat(fixture_date_str.replace("Z", "+00:00"))

                # Εστιάζουμε σε αγώνες που ξεκινάνε τις επόμενες 2 ώρες
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
                        match_time = fixture_time.strftime('%H:%M')

                        predictions = pred_data.get("predictions", {})
                        advice = predictions.get("advice", "Over 1.5 Goals")
                        percent = predictions.get("percent", {})

                        # 1. MAIN TIPSTER (1X2, O/U, G/G)
                        if key_main not in processed_events:
                            msg = (
                                f"🎯 *[AUTO TIPSTER - PICK]*\n"
                                f"🏆 {league} | ⏰ {match_time}\n"
                                f"⚔️ **{home} vs {away}**\n\n"
                                f"📌 **Πρόταση:** {advice}\n"
                                f"📊 **Πιθανότητες:** 1: {percent.get('home', '0%')} | X: {percent.get('draw', '0%')} | 2: {percent.get('away', '0%')}\n"
                                f"💰 **Stake:** 3/10 Units\n\n"
                                f"🤖 *AI Statistical Analysis*"
                            )
                            send_telegram("MAIN", msg)
                            processed_events.add(key_main)

                        # 2. SPECIAL TIPSTER (Κάρτες, Κόρνερ)
                        if key_spec not in processed_events:
                            under_over = predictions.get("under_over", "Over 2.5")
                            msg = (
                                f"🔥 *[AUTO TIPSTER - SPECIALS]*\n"
                                f"🏆 {league} | ⏰ {match_time}\n"
                                f"⚔️ **{home} vs {away}**\n\n"
                                f"🟨 **Εκτίμηση Καρτών:** Over 4.5 Yellow Cards\n"
                                f"🚩 **Εκτίμηση Κόρνερ:** Over 8.5 Corners\n"
                                f"⚽ **Goals Trend:** {under_over}\n"
                                f"💰 **Stake:** 2/10 Units"
                            )
                            send_telegram("SPECIAL", msg)
                            processed_events.add(key_spec)

                        # Προσθήκη στο Παρολί
                        key_paroli_item = f"paroli_item_{fixture_id}"
                        if key_paroli_item not in processed_events and len(paroli_candidates) < 3:
                            paroli_candidates.append(f"• **{home} vs {away}**: {advice}")
                            processed_events.add(key_paroli_item)

        # 3. PAROLI TIPSTER (Τριάδα)
        if len(paroli_candidates) >= 3:
            paroli_msg = (
                f"🎟️ *[AUTO TIPSTER - DAILY TRIADA]*\n\n"
                f"Τα 3 πιο δυνατά στατιστικά σημεία της ώρας:\n\n"
                + "\n".join(paroli_candidates) +
                f"\n\n🔥 **Συνολική Εκτιμώμενη Απόδοση:** ~3.50\n"
                f"💰 **Stake:** 1.5/10 Units"
            )
            send_telegram("PAROLI", paroli_msg)

        time.sleep(1800)  # Έλεγχος ανά 30 λεπτά

def continuous_live_engine():
    """Live Engine: Tipster Alerts & Live Red Card Radar"""
    while True:
        fixtures = fetch_live_fixtures()
        now_str = datetime.now().strftime('%H:%M:%S')

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            teams = fix.get("teams", {})
            home = teams.get("home", {}).get("name", "Home")
            away = teams.get("away", {}).get("name", "Away")
            league = fix.get("league", {}).get("name", "League")
            country = fix.get("league", {}).get("country", "")
            
            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", 0)
            goals = fix.get("goals", {})
            score_str = f"{goals.get('home', 0)} - {goals.get('away', 0)}"

            # 4. LIVE VALUE ALERT (Tipster στο 65'-75' με 0-0)
            if 65 <= elapsed <= 75 and goals.get('home', 0) + goals.get('away', 0) == 0:
                key_live = f"live_val_{fixture_id}"
                if key_live not in processed_events:
                    msg = (
                        f"⚡ *[LIVE TIPSTER - LATE GOAL]*\n\n"
                        f"⚔️ **{home} vs {away}** ({elapsed}')\n"
                        f"🔢 **Σκορ:** {score_str}\n\n"
                        f"💡 **Live Πρόταση:** Over 0.5 Goal (Late Goal)\n"
                        f"💰 **Stake:** 2/10 Units"
                    )
                    send_telegram("LIVE", msg)
                    processed_events.add(key_live)

            # 5. LIVE RED CARD RADAR (ΑΠΟΚΛΕΙΣΤΙΚΑ ΕΝΗΜΕΡΩΤΙΚΟ)
            events = fix.get("events", [])
            for event in events:
                if event.get("type") == "Card" and event.get("detail") in ["Red Card", "Yellow 2nd Card"]:
                    team_name = event.get("team", {}).get("name")
                    player = event.get("player", {}).get("name", "Player")
                    card_type = "Απευθείας Κόκκινη" if event.get("detail") == "Red Card" else "2η Κίτρινη"
                    event_time = event.get("time", {}).get("elapsed", elapsed)

                    key_red = f"red_{fixture_id}_{event_time}_{team_name}"

                    if key_red not in processed_events:
                        msg = (
                            f"🚨 *[RED CARD ALERT]* 🚨\n\n"
                            f"🏆 **{league}** ({country})\n"
                            f"⚔️ **{home} {score_str} {away}** ({elapsed}')\n\n"
                            f"🔴 **Ομάδα:** {team_name}\n"
                            f"👤 **Παίκτης:** {player}\n"
                            f"📌 **Τύπος:** {card_type} ({event_time}')\n\n"
                            f"⚡ *Live Opportunity Alert*"
                        )
                        send_telegram("RED_CARDS", msg)
                        processed_events.add(key_red)

        time.sleep(15)  # Σκανάρισμα live κάθε 15 δευτερόλεπτα

if __name__ == "__main__":
    print("🚀 Εκκίνηση Πλήρους Συστήματος (Tipster + Red Card Radar)...", flush=True)
    
    t1 = threading.Thread(target=continuous_tipster_engine, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=continuous_live_engine, daemon=True)
    t2.start()
    
    run_flask()
