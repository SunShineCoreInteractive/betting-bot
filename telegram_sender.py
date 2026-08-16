"""
Στέλνει μηνύματα στα 4 κανάλια Telegram.
"""

import logging
import requests

import config

logger = logging.getLogger("telegram_sender")


def send_message(channel_key, text):
    """
    channel_key: "singles" | "parlay" | "bet_builder" | "live"
    """
    chat_id = config.TELEGRAM_CHANNELS.get(channel_key)
    if not chat_id:
        logger.error("Άγνωστο κανάλι: %s", channel_key)
        return False

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
        return True
    except requests.RequestException as e:
        logger.error("Αποτυχία αποστολής στο %s: %s", channel_key, e)
        return False


def format_single(league_name, home, away, kickoff_str, market, model_prob, odds, edge, basis, source=""):
    source_line = f"🏦 {source}\n" if source else ""
    return (
        f"⚽ <b>AUTO BET (ΜΟΝΑ)</b>\n\n"
        f"{league_name}\n"
        f"{home} vs {away}\n"
        f"Έναρξη: {kickoff_str}\n\n"
        f"📊 Πρόβλεψη: {market}\n"
        f"Εκτίμηση: {model_prob*100:.0f}% | Απόδοση: {odds:.2f}\n"
        f"{source_line}"
        f"Edge: +{edge*100:.1f}%\n\n"
        f"📈 Βάση ανάλυσης:\n{basis}"
    )


def format_parlay(legs_desc, combined_odds, combined_prob, edge):
    lines = "\n".join(f"{i+1}) {d}" for i, d in enumerate(legs_desc))
    return (
        f"🎯 <b>AUTO BET (ΠΑΡΟΛΙ)</b> — {len(legs_desc)} επιλογές\n\n"
        f"{lines}\n\n"
        f"Συνδυασμένη απόδοση: {combined_odds:.2f}\n"
        f"Εκτίμηση συνόλου: {combined_prob*100:.0f}% | Edge: +{edge*100:.1f}%"
    )


def format_bet_builder(league_name, home, away, kickoff_str, legs_desc, combined_prob, fair_odds):
    lines = "\n".join(f"• {d}" for d in legs_desc)
    return (
        f"🧩 <b>AUTO BET (BET BUILDER)</b>\n\n"
        f"{league_name}\n"
        f"{home} vs {away}\n"
        f"Έναρξη: {kickoff_str}\n\n"
        f"Συνδυασμός:\n{lines}\n\n"
        f"Συνολική εκτίμηση (με προσαρμογή συσχέτισης): {combined_prob*100:.0f}%\n"
        f"Ισοδύναμη «δίκαιη» απόδοση: ~{fair_odds:.2f}\n\n"
        f"⚠️ Μοντέλο βάσει ιστορικών στατιστικών — δεν συγκρίνεται με τιμή "
        f"bookmaker bet builder (δεν διατίθεται μέσω API)"
    )


def format_result(description, won):
    emoji = "✅ ΚΕΡΔΙΣΕ" if won else "❌ ΕΧΑΣΕ"
    return f"{emoji}\n\n{description}"


def format_live(league_name, minute, home, away, score_home, score_away,
                 market, model_prob, odds, edge, basis, source=""):
    source_line = f"🏦 {source}\n" if source else ""
    return (
        f"🔴 <b>AUTO BET (LIVE)</b>\n\n"
        f"{league_name} — {minute}'\n"
        f"{home} {score_home}-{score_away} {away}\n\n"
        f"📊 Πρόβλεψη: {market}\n"
        f"Εκτίμηση: {model_prob*100:.0f}% | Απόδοση: {odds:.2f}\n"
        f"{source_line}"
        f"Edge: +{edge*100:.1f}%\n\n"
        f"📈 Βάση: {basis}"
    )
