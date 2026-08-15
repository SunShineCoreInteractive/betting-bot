import os
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Stats-Based Tipster System Active 24/7!", 200

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
    url = f"https://{API_HOST}/odds?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("response", [])
            if data and data[0].get("bookmakers"):
                for bm in data[0]["bookmakers"]:
                    for b in bm.get("bets", []):
                        if b.get("name") in ["Match Winner", "Goals Over/Under", "Both Teams Score"]:
                            values = b.get("values", [])
                            if values:
                                return values[0].get("odd")
    except Exception as e:
        print(f"⚠️ Σφάλμα Odds Fetch: {e}", flush=True)
    return None

def fetch_team_statistics(team_id, league_id, season):
    url = f"https://{API_HOST}/teams/statistics?team={team_id}&league={league_id}&season={season}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("response", {})
    except Exception as e:
        print(f"⚠️ Σφάλμα Team Stats Fetch: {e}", flush=True)
    return None

def get_avg_yellow_cards(stats):
    if not stats:
        return None
    try:
        cards = stats.get("cards", {}).get("yellow", {})
        total = sum((bucket.get("total") or 0) for bucket in cards.values())
        played = stats.get("fixtures", {}).get("played", {}).get("total", 0)
        if played > 0:
            return total / played
    except Exception as e:
        print(f"⚠️ Σφάλμα υπολογισμού καρτών: {e}", flush=True)
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

def fetch_fixture_statistics(fixture_id):
    """Live στατιστικά αγώνα (κόρνερ, τελικές, επιθέσεις) για το LIVE κανάλι."""
    url = f"https://{API_HOST}/fixtures/statistics?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("response", [])
    except Exception as e:
        print(f"⚠️ Σφάλμα Fixture Stats Fetch: {e}", flush=True)
    return []

# --- PRE-MATCH ENGINE (MAIN, SPECIAL, PAROLI) ---
def continuous_prematch_engine():
    while True:
        fixtures = fetch_upcoming_fixtures()
        now_utc = datetime.now(timezone.utc)
        window_end = now_utc + timedelta(hours=4)

        print(f"[{now_utc.strftime('%H:%M:%S')}] 🤖 Pre-Match Engine: Σκανάρισμα {len(fixtures)} αγώνων ημέρας...", flush=True)
        paroli_candidates = []

        for fix in fixtures:
            fixture_id = fix.get("fixture", {}).get("id")
            status = fix.get("fixture", {}).get("status", {}).get("short")
            fixture_date_str = fix.get("fixture", {}).get("date")
            if status != "NS" or not fixture_date_str:
                continue

            fixture_time = datetime.fromisoformat(fixture_date_str.replace("Z", "+00:00"))
            if not (now_utc <= fixture_time <= window_end):
                continue

            key_main = f"main_{fixture_id}"
            key_spec = f"spec_{fixture_id}"
            if key_main in processed_events and key_spec in processed_events:
                continue

            teams = fix.get("teams", {})
            home = teams.get("home", {}).get("name", "Home")
            away = teams.get("away", {}).get("name", "Away")
            home_id = teams.get("home", {}).get("id")
            away_id = teams.get("away", {}).get("id")
            league = fix.get("league", {}).get("name", "League")
            country = fix.get("league", {}).get("country", "World")
            league_id = fix.get("league", {}).get("id")
            season = fix.get("league", {}).get("season")
            league_info = f"{country} - {league}"
            match_time = fixture_time.strftime('%H:%M')

            # --- MAIN: 1X2 / O-U / GG βάσει /predictions ---
            if key_main not in processed_events:
                pred_data = fetch_prediction(fixture_id)
                if pred_data:
                    predictions = pred_data.get("predictions", {})
                    advice = predictions.get("advice")
                    percent = predictions.get("percent", {})
                    if advice:
                        odd_val = fetch_odds(fixture_id)
                        odd_display = f"@{odd_val}" if odd_val else "μη διαθέσιμη"
                        msg = (
                            f"🎯 *[MAIN - PRE MATCH PICK]*\n"
                            f"🌍 **Πρωτάθλημα:** {league_info}\n"
                            f"⏰ **Ώρα:** {match_time}\n"
                            f"⚔️ **{home} vs {away}**\n\n"
                            f"📌 **Πρόταση:** {advice}\n"
                            f"💰 **Απόδοση:** {odd_display}\n"
                            f"📊 **Πιθανότητες:** 1: {percent.get('home','N/A')} | X: {percent.get('draw','N/A')} | 2: {percent.get('away','N/A')}"
                        )
                        send_telegram("MAIN", msg)
                        pending_bets[f"{fixture_id}_main"] = {
                            "channel": "MAIN", "home": home, "away": away,
                            "league_info": league_info, "advice": advice, "odd": odd_val
                        }
                        key_paroli_item = f"paroli_item_{fixture_id}"
                        if key_paroli_item not in processed_events and len(paroli_candidates) < 3:
                            odd_txt = f" (@{odd_val})" if odd_val else ""
                            paroli_candidates.append(f"• **[{league_info}] {home} vs {away}**: {advice}{odd_txt}")
                            processed_events.add(key_paroli_item)
                processed_events.add(key_main)

            # --- SPECIAL: Κάρτες & Κόρνερ βάσει πραγματικού ιστορικού ---
            if key_spec not in processed_events and home_id and away_id and league_id and season:
                home_stats = fetch_team_statistics(home_id, league_id, season)
                away_stats = fetch_team_statistics(away_id, league_id, season)

                spec_lines = []

                home_cards = get_avg_yellow_cards(home_stats)
                away_cards = get_avg_yellow_cards(away_stats)
                if home_cards is not None and away_cards is not None:
                    combined = home_cards + away_cards
                    if combined >= 6:
                        line = "Over 5.5"
                    elif combined >= 5:
                        line = "Over 4.5"
                    elif combined >= 4:
                        line = "Over 3.5"
                    else:
                        line = None
                    if line:
                        spec_lines.append(f"🟨 **Κάρτες:** {line} (μέσος όρος: {combined:.1f}/αγώνα)")

                home_corners = get_avg_corners(home_stats)
                away_corners = get_avg_corners(away_stats)
                if home_corners is not None and away_corners is not None:
                    combined_c = home_corners + away_corners
                    if combined_c >= 11:
                        line_c = "Over 10.5"
                    elif combined_c >= 9:
                        line_c = "Over 8.5"
                    elif combined_c >= 7:
                        line_c = "Over 6.5"
                    else:
                        line_c = None
                    if line_c:
                        spec_lines.append(f"🚩 **Κόρνερ:** {line_c} (μέσος όρος: {combined_c:.1f}/αγώνα)")

                if spec_lines:
                    msg = (
                        f"🔥 *[SPECIAL - PRE MATCH]*\n"
                        f"🌍 **Πρωτάθλημα:** {league_info}\n"
                        f"⏰ **Ώρα:** {match_time}\n"
                        f"⚔️ **{home} vs {away}**\n\n"
                        + "\n".join(spec_lines)
                    )
                    send_telegram("SPECIAL", msg)
                processed_events.add(key_spec)

        if len(paroli_candidates) >= 2:
            paroli_msg = (
                f"🎟 *[PAROLI - TRIADA]*\n\n"
                f"Τα πιο δυνατά στατιστικά σημεία της περιόδου:\n\n"
                + "\n".join(paroli_candidates)
            )
            send_telegram("PAROLI", paroli_msg)

        time.sleep(900)  # Έλεγχος κάθε 15 λεπτά

def get_avg_corners(stats):
    """Αν το API δεν δίνει κόρνερ για το συγκεκριμένο πρωτάθλημα, επιστρέφει None."""
    if not stats:
        return None
    try:
        # Το API-Football δεν εκθέτει πάντα corners στο /teams/statistics.
        # Ελέγχουμε αν υπάρχει το πεδίο· αν όχι, δεν επινοούμε τίποτα.
        corners = stats.get("corners")  # δεν υπάρχει σε όλα τα plans/leagues
        if corners is None:
            return None
        total = corners.get("total")
        played = stats.get("fixtures", {}).get("played", {}).get("total", 0)
        if total is not None and played > 0:
            return total / played
    except Exception as e:
        print(f"⚠️ Σφάλμα υπολογισμού κόρνερ: {e}", flush=True)
    return None

# --- LIVE ENGINE (LIVE picks + RED CARDS) ---
def continuous_live_engine():
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
            home_goals = goals.get("home", 0)
            away_goals = goals.get("away", 0)
            score_str = f"{home_goals} - {away_goals}"

            # --- LIVE picks βάσει πραγματικών live στατιστικών του αγώνα ---
            key_live = f"live_{fixture_id}_{elapsed // 5}"  # ελέγχει ξανά κάθε ~5 λεπτά μέσα στον αγώνα
            if elapsed >= 55 and key_live not in processed_events:
                stats = fetch_fixture_statistics(fixture_id)
                shots_on_target_total = 0
                dangerous_attacks_total = 0
                for team_stats in stats:
                    for s in team_stats.get("statistics", []):
                        if s.get("type") == "Shots on Goal" and s.get("value"):
                            shots_on_target_total += int(s["value"])
                        if s.get("type") == "Dangerous Attacks" and s.get("value"):
                            dangerous_attacks_total += int(s["value"])

                total_goals = home_goals + away_goals
                pick = None
                if total_goals == 0 and shots_on_target_total >= 8:
                    pick = "Over 0.5 Goal (Late Goal) — πίεση με πολλές τελικές, ακόμα 0-0"
                elif total_goals == 1 and shots_on_target_total >= 10 and elapsed < 80:
                    pick = "Over 1.5 Goals — έντονη επιθετική δραστηριότητα"

                if pick:
                    msg = (
                        f"⚡ *[LIVE PICK]*\n"
                        f"🌍 **Πρωτάθλημα:** {league_info}\n"
                        f"⚔️ **{home} vs {away}** ({elapsed}')\n"
                        f"🔢 **Σκορ:** {score_str}\n"
                        f"🎯 **Τελικές στο στόχο:** {shots_on_target_total}\n\n"
                        f"💡 **Πρόταση:** {pick}"
                    )
                    send_telegram("LIVE", msg)
                    pending_bets[f"{fixture_id}_live_{elapsed}"] = {
                        "channel": "LIVE", "home": home, "away": away,
                        "league_info": league_info, "advice": pick, "odd": None
                    }
                processed_events.add(key_live)

            # --- RED CARDS RADAR (ενημερωτικό) ---
            events = fix.get("events", [])
            for event in events:
                if event.get("type") == "Card" and event.get("detail") in ["Red Card", "Yellow 2nd Card"]:
                    team_name = event.get("team", {}).get("name")
                    player = event.get("player", {}).get("name", "Player")
                    card_type = "Απευθείας Κόκκινη" if event.get("detail") == "Red Card" else "2η Κίτρινη"
                    card_time = event.get("time", {}).get("elapsed", 0)
                    key_red = f"red_{fixture_id}_{team_name}_{card_time}"
                    if key_red not in processed_events:
                        processed_events.add(key_red)
                        if elapsed > 0 and (elapsed - card_time) <= 3:
                            msg = (
                                f"🚨 *[RED CARD ALERT]* 🚨\n\n"
                                f"🌍 **Πρωτάθλημα:** {league_info}\n"
                                f"⚔️ **{home} {score_str} {away}** ({elapsed}')\n\n"
                                f"🔴 **Ομάδα:** {team_name}\n"
                                f"👤 **Παίκτης:** {player}\n"
                                f"📌 **Τύπος:** {card_type} ({card_time}')"
                            )
                            send_telegram("RED_CARDS", msg)
        time.sleep(15)

# --- SETTLEMENT ENGINE (WON/LOST) ---
def result_settlement_engine():
    while True:
        if pending_bets:
            print(f"🔄 Result Settlement: Έλεγχος {len(pending_bets)} εκκρεμών...", flush=True)
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
                        odd_val = bet_info.get("odd")
                        odd_display = f"@{odd_val}" if odd_val else ""

                        is_won = None
                        if "Over 0.5" in advice:
                            is_won = total_goals > 0
                        elif "Over 1.5" in advice:
                            is_won = total_goals > 1
                        elif "Over 2.5" in advice:
                            is_won = total_goals > 2
                        elif "Home" in advice:
                            is_won = home_goals > away_goals
                        elif "Away" in advice:
                            is_won = away_goals > home_goals

                        if is_won is None:
                            result_msg = (
                                f"⚠️ *[RESULT UNVERIFIED]*\n"
                                f"🌍 **Πρωτάθλημα:** {league_info}\n"
                                f"⚔️ **{home} vs {away}**\n"
                                f"🔢 **Τελικό Σκορ:** {score_str}\n"
                                f"📌 **Πρόταση:** {advice}\n\n"
                                f"ℹ️ Χειροκίνητος έλεγχος απαιτείται"
                            )
                        else:
                            emoji = f"✅ [BET WON {odd_display}]" if is_won else f"❌ [BET LOST {odd_display}]"
                            result_msg = (
                                f"{emoji}\n"
                                f"🌍 **Πρωτάθλημα:** {league_info}\n"
                                f"⚔️ **{home} vs {away}**\n"
                                f"🔢 **Τελικό Σκορ:** {score_str}\n"
                                f"📌 **Πρόταση:** {advice}"
                            )
                        send_telegram(channel, result_msg)
                        completed_keys.append(bet_key)
            for k in completed_keys:
                pending_bets.pop(k, None)
        time.sleep(600)

if __name__ == "__main__":
    print("🚀 Εκκίνηση Πλήρους Συστήματος (Stats-Based)...", flush=True)
    threading.Thread(target=continuous_prematch_engine, daemon=True).start()
    threading.Thread(target=continuous_live_engine, daemon=True).start()
    threading.Thread(target=result_settlement_engine, daemon=True).start()
    run_flask()
