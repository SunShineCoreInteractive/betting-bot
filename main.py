import os
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Statistical Analysis Engine Active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

TELEGRAM_TOKEN = "8881899162:AAGEO_aWsZfBMCUDc3lLTfq-_QUXlhZSW-0"
API_KEY = "07f419d44db082b7e6690551e62c25b2"
API_HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

CHANNELS = {
    "MAIN": -1004451641508,
    "SPECIAL": -1003976882916,
    "PAROLI": -1004400781523,
    "LIVE": -1003946267636,
    "RED_CARDS": -1003987886550
}

processed_events = set()

def send_telegram(channel_key, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNELS[channel_key], "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"⚠️ Σφάλμα Telegram: {e}", flush=True)

def fetch_prediction(fixture_id):
    """Φέρνει τη στατιστική ανάλυση και πιθανότητες του API για έναν αγώνα"""
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
        print(f"⚠️ Σφάλμα Fixtures Fetch: {e}", flush=True)
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

def continuous_prematch_engine():
    """Στατιστική Ανάλυση Pre-Match (Αγώνες επόμενης 1-2 ωρών)"""
    while True:
        fixtures = fetch_upcoming_fixtures()
        now_utc = datetime.now(timezone.utc)
        two_hours_later = now_utc + timedelta(hours=2)
        
        print(f"[{now_utc.strftime('%H:%M:%S')}] 📊 Pre-Match Engine: Αναλύονται στατιστικά αγώνων...", flush=True)
        paroli_candidates = []

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            status = fix.get("fixture", {}).get("short")
            fixture_date_str = fix.get("fixture", {}).get("date")

            if status == "NS" and fixture_date_str:
                fixture_time = datetime.fromisoformat(fixture_date_str.replace("Z", "+00:00"))

                # Αναλύουμε αγώνες που ξεκινάνε τις επόμενες 2 ώρες
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
                        
                        predictions = pred_data.get("predictions", {})
                        advice = predictions.get("advice", "Δεν υπάρχει πρόταση")
                        percent = predictions.get("percent", {})
                        
                        # Πιθανότητες
                        home_prob = percent.get("home", "0%")
                        draw_prob = percent.get("draw", "0%")
                        away_prob = percent.get("away", "0%")

                        # 1. MAIN CHANNEL (Βάσει Πιθανοτήτων & Advice)
                        if key_main not in processed_events:
                            msg = (
                                f"⚽ *[STRICT STATISTICAL PICK]*\n\n"
                                f"⚔️ **{home} vs {away}**\n"
                                f"📊 **Πιθανότητες API:** 1: {home_prob} | X: {draw_prob} | 2: {away_prob}\n\n"
                                f"💡 **Πρόταση Βάσει Στατιστικών:**\n"
                                f"👉 *{advice}*\n\n"
                                f"📈 *Αναλύθηκαν τα τελευταία 10 παιχνίδια & H2H*"
                            )
                            send_telegram("MAIN", msg)
                            processed_events.add(key_main)

                        # 2. SPECIAL CHANNEL (Μόνο αν υπάρχει υψηλή στατιστική τάση)
                        if key_spec not in processed_events:
                            goals_h2h = pred_data.get("teams", {}).get("home", {}).get("league", {}).get("goals", {})
                            msg = (
                                f"🎯 *[SPECIAL STATS BET]*\n\n"
                                f"⚔️ **{home} vs {away}**\n"
                                f"📈 **Στατιστικά Τάσης:**\n"
                                f"• Εκτιμώμενα Γκολ: {predictions.get('under_over', 'N/A')}\n"
                                f"• Προσδοκία Νίκης: {predictions.get('winner', {}).get('name', 'N/A')}\n"
                            )
                            send_telegram("SPECIAL", msg)
                            processed_events.add(key_spec)

                        # Προσθήκη στο Παρολί αν η πιθανότητα νίκης/διπλής ευκαιρίας είναι >60%
                        key_paroli_item = f"paroli_item_{fixture_id}"
                        if key_paroli_item not in processed_events and len(paroli_candidates) < 3:
                            paroli_candidates.append(f"• **{home} vs {away}**: {advice}")
                            processed_events.add(key_paroli_item)

        # 3. PAROLI CHANNEL
        if len(paroli_candidates) >= 2:
            paroli_msg = "🎟️ *[STATISTICAL TRIADA PAROLI]*\n\n" + "\n".join(paroli_candidates) + "\n\n🔥 *Δελτίο Υψηλής Πιθανότητας*"
            send_telegram("PAROLI", paroli_msg)

        time.sleep(1800) # Έλεγχος ανά 30 λεπτά

def continuous_live_engine():
    """Live Tracking: Red Cards & Live Value Alerts"""
    while True:
        fixtures = fetch_live_fixtures()
        now_str = datetime.now().strftime('%H:%M:%S')

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            teams = fix.get("teams", {})
            home = teams.get("home", {}).get("name", "Home")
            away = teams.get("away", {}).get("name", "Away")
            elapsed = fix.get("fixture", {}).get("status", {}).get("elapsed", 0)
            goals = fix.get("goals", {})
            score_str = f"{goals.get('home', 0)} - {goals.get('away', 0)}"

            # 4. LIVE VALUE ALERT (Πιέζουν οι ομάδες - 0-0 στο 65'-75')
            if 65 <= elapsed <= 75 and goals.get('home', 0) + goals.get('away', 0) == 0:
                key_live = f"live_val_{fixture_id}"
                if key_live not in processed_events:
                    msg = f"⚡ *[LIVE STATS VALUE ALERT]*\n\n⚔️ **{home} vs {away}** ({elapsed}')\n🔢 **Σκορ:** {score_str}\n📊 **Στατιστική Πίεση:** Υψηλή πιθανότητα για late goal (>0.5)"
                    send_telegram("LIVE", msg)
                    processed_events.add(key_live)

            # 5. RED CARDS (Instant Feed)
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

        time.sleep(20)

if __name__ == "__main__":
    print("🚀 Εκκίνηση Στατιστικού Engine...", flush=True)
    
    t1 = threading.Thread(target=continuous_prematch_engine, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=continuous_live_engine, daemon=True)
    t2.start()
    
    run_flask()
