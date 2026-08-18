"""
Στέλνει μηνύματα στα 12 κανάλια Telegram (ένα ανά τύπο market).
Το send_message επιστρέφει το message_id (όχι μόνο True/False), ώστε
αργότερα να μπορούμε να ΕΠΕΞΕΡΓΑΣΤΟΥΜΕ το ίδιο μήνυμα προσθέτοντας
✅ ΚΕΡΔΙΣΕ / ❌ ΕΧΑΣΕ, αντί να στέλνουμε νέο μήνυμα.
"""

import logging
import requests

import config

logger = logging.getLogger("telegram_sender")


def send_message(channel_key, text):
    """
    channel_key: ένα από τα κλειδιά του config.BET_TYPE_CHANNELS
    Επιστρέφει το message_id (int) αν πέτυχε, αλλιώς None.
    """
    chat_id = config.BET_TYPE_CHANNELS.get(channel_key)
    if not chat_id:
        logger.error("Άγνωστο κανάλι: %s", channel_key)
        return None

    url = f"{config.TELEGRAM_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json().get("result", {}).get("message_id")
    except requests.RequestException as e:
        logger.error("Αποτυχία αποστολής στο %s: %s", channel_key, e)
        return None


def edit_message_add_result(channel_key, message_id, original_text, won):
    """
    Προσθέτει ✅ ΚΕΡΔΙΣΕ / ❌ ΕΧΑΣΕ / 🔄 ΑΚΥΡΟ στο ΤΕΛΟΣ του ήδη σταλμένου
    μηνύματος, αντί να στέλνει καινούριο -- έτσι δεν "γεμίζει" το κανάλι.
    won: True/False/"PUSH" (ισοπαλία σε DNB/ακέραιο Ασιατικό Χάντικαπ -- επιστροφή)
    """
    chat_id = config.BET_TYPE_CHANNELS.get(channel_key)
    if not chat_id or not message_id:
        return False

    if won == "PUSH":
        emoji_line = "🔄 <b>ΑΚΥΡΟ (Επιστροφή Ποντάρισματος)</b>"
    elif won:
        emoji_line = "✅ <b>ΚΕΡΔΙΣΕ</b>"
    else:
        emoji_line = "❌ <b>ΕΧΑΣΕ</b>"
    new_text = f"{original_text}\n\n{emoji_line}"

    url = f"{config.TELEGRAM_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Αποτυχία επεξεργασίας μηνύματος %s στο %s: %s", message_id, channel_key, e)
        return False


def format_prediction(league_name, home, away, kickoff_str, market, model_prob, odds, edge, basis, source=""):
    """Ενιαία μορφή μηνύματος για όλα τα κανάλια markets (χωρίς πλέον ΜΟΝΑ/ΠΑΡΟΛΙ/LIVE labels)."""
    source_line = f"🏦 {source}\n" if source else ""
    return (
        f"📊 <b>{market}</b>\n\n"
        f"{league_name}\n"
        f"{home} vs {away}\n"
        f"Έναρξη: {kickoff_str}\n\n"
        f"Εκτίμηση: {model_prob*100:.0f}% | Απόδοση: {odds:.2f}\n"
        f"{source_line}"
        f"Edge: +{edge*100:.1f}%\n\n"
        f"📈 Βάση ανάλυσης:\n{basis}"
    )


def format_combo_bets(league_name, home, away, kickoff_str, legs_desc, combined_prob, fair_odds):
    lines = "\n".join(f"• {d}" for d in legs_desc)
    return (
        f"🧩 <b>COMBO BET</b>\n\n"
        f"{league_name}\n"
        f"{home} vs {away}\n"
        f"Έναρξη: {kickoff_str}\n\n"
        f"Συνδυασμός:\n{lines}\n\n"
        f"Συνολική εκτίμηση (με προσαρμογή συσχέτισης): {combined_prob*100:.0f}%\n"
        f"Ισοδύναμη «δίκαιη» απόδοση: ~{fair_odds:.2f}\n\n"
        f"⚠️ Μοντέλο βάσει ιστορικών στατιστικών — δεν συγκρίνεται με τιμή "
        f"bookmaker bet builder (δεν διατίθεται μέσω API)"
    )
