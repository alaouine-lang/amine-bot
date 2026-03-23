#!/usr/bin/env python3
"""
AMINE INTEL BOT — Version finale configurée
============================================
Token, Chat ID et clé Anthropic déjà intégrés.
"""

import os
import time
import schedule
import threading
import requests
import yfinance as yf
from datetime import datetime

try:import anthropic
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
except ImportError:
    os.system("pip install anthropic")
    from anthropic import Anthropic

# ============================================================
# ✅ CONFIGURATION — DÉJÀ REMPLIE
# ============================================================
TELEGRAM_TOKEN = "8688782085:AAFKvXMCClaeKBt-Yd4paRQJi6YBIH0GUxY"
CHAT_ID        = "8654742500"
ANTHROPIC_KEY  = "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"
# ============================================================


PORTFOLIO = {
    "TTE.PA":  {"name": "TotalEnergies", "parts": 233, "entry": 72.70, "stop": 75.95, "target": 85.00, "currency": "€"},
    "SHEL.AS": {"name": "Shell",         "parts": 645, "entry": 39.48, "stop": 37.50, "target": 44.00, "currency": "€"},
    "INSW":    {"name": "Int'l Seaways", "parts": 171, "entry": 71.80, "stop": 66.00, "target": 82.00, "currency": "$"},
    "EXV1.DE": {"name": "EXV1 Banques",  "parts": 445, "entry": 33.78, "stop": 30.00, "target": 36.00, "currency": "€"},
    "NVDA":    {"name": "NVIDIA",        "parts": 81,  "entry": 185.0, "stop": 170.0, "target": 210.0, "currency": "$"},
    "PLTR":    {"name": "Palantir",      "parts": 8,   "entry": 154.0, "stop": 148.0, "target": 175.0, "currency": "$"},
}

EVENTS = [
    {"date": "24/03/2026", "label": "AGO Attijariwafa BVC",    "action": "Vendre 50% ATW si +8%"},
    {"date": "26/03/2026", "label": "AGO IAM Maroc Telecom",   "action": "Dividende IAM"},
    {"date": "29/04/2026", "label": "Résultats TotalEnergies", "action": "Vendre 1/3 TTE à l'annonce"},
    {"date": "30/04/2026", "label": "FOMC Décision taux",      "action": "Adapter selon décision Fed"},
    {"date": "07/05/2026", "label": "Résultats Shell",         "action": "Vendre 1/3 si >45€"},
    {"date": "27/05/2026", "label": "Résultats NVIDIA",        "action": "Vendre si +20%"},
]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Erreur Telegram: {e}")

def get_prices():
    prices = {}
    for ticker, info in PORTFOLIO.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d", interval="5m")
            if not hist.empty:
                price  = round(hist["Close"].iloc[-1], 2)
                change = round(((price - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100, 2)
                prices[ticker] = {"price": price, "change": change}
        except:
            prices[ticker] = {"price": None, "change": None}
    return prices

def get_brent():
    try:
        b = yf.Ticker("BZ=F")
        h = b.history(period="1d", interval="5m")
        return round(h["Close"].iloc[-1], 2) if not h.empty else None
    except:
        return None

def get_iran_news():
    try:
        import re
        rss = requests.get(
            "https://news.google.com/rss/search?q=Iran+war+Strait+Hormuz+oil&hl=fr&gl=FR&ceid=FR:fr",
            timeout=10
        ).text
        titles = re.findall(r'<title>(.*?)</title>', rss)[2:6]
        return [re.sub(r'<[^>]+>', '', t) for t in titles]
    except:
        return ["News indisponibles"]

def get_days_until(date_str):
    d, m, y = date_str.split("/")
    return (datetime(int(y), int(m), int(d)) - datetime.now()).days

def format_portfolio(prices, brent):
    lines = ["📊 <b>PORTEFEUILLE AMINE</b>\n"]
    if brent:
        pct = round(((brent - 72.48) / 72.48) * 100, 1)
        lines.append(f"🛢️ Brent: <b>${brent}</b> ({pct:+.1f}% depuis guerre)\n")
    lines.append("─────────────────")
    for ticker, info in PORTFOLIO.items():
        pd = prices.get(ticker, {})
        price  = pd.get("price")
        change = pd.get("change")
        pos    = PORTFOLIO[ticker]
        if price:
            pnl      = (price - pos["entry"]) * pos["parts"]
            dist_stop = ((price - pos["stop"]) / price) * 100
            dist_tgt  = ((pos["target"] - price) / price) * 100
            emoji = "🟢" if pnl > 0 else "🔴"
            alert = "🚨" if abs(dist_stop) < 2 else ("⚠️" if abs(dist_stop) < 5 else "")
            lines.append(
                f"{emoji}{alert} <b>{info['name']}</b>\n"
                f"   {price}{info['currency']} ({change:+.1f}%) | P&L: {pnl:+.0f}{info['currency']}\n"
                f"   Stop: {pos['stop']}{info['currency']} ({dist_stop:.1f}%) | Target: {pos['target']}{info['currency']} ({dist_tgt:.1f}%)"
            )
        else:
            lines.append(f"⚪ <b>{info['name']}</b> — cours indisponible")
    return "\n".join(lines)

def analyze(prices, brent, news, mode="morning"):
    pos_text = []
    alerts   = []
    for ticker, info in PORTFOLIO.items():
        pd    = prices.get(ticker, {})
        price = pd.get("price")
        pos   = PORTFOLIO[ticker]
        if price:
            pnl       = (price - pos["entry"]) * pos["parts"]
            dist_stop = ((price - pos["stop"]) / price) * 100
            dist_tgt  = ((pos["target"] - price) / price) * 100
            pos_text.append(f"{info['name']}: {price}{info['currency']} | P&L:{pnl:+.0f} | Stop:{dist_stop:.1f}% | Target:{dist_tgt:.1f}%")
            if abs(dist_stop) < 2:
                alerts.append(f"🚨 {info['name']} à {abs(dist_stop):.1f}% du STOP!")
            if dist_tgt < 2:
                alerts.append(f"🎯 {info['name']} à {dist_tgt:.1f}% du TARGET!")

    upcoming = [f"J-{get_days_until(e['date'])}: {e['label']} → {e['action']}"
                for e in EVENTS if 0 <= get_days_until(e['date']) <= 7]

    prompts = {
        "morning": f"""Tu es l'analyste d'Amine Chaoui (130K€ IBKR). Guerre Iran J+23, Brent {brent}$.

POSITIONS:
{chr(10).join(pos_text)}

NEWS:
{chr(10).join(news[:4])}

ALERTES: {chr(10).join(alerts) if alerts else 'Aucune'}
ÉVÉNEMENTS SEMAINE: {chr(10).join(upcoming) if upcoming else 'Aucun'}

Briefing matin en français avec emojis (max 250 mots):
1. Score portefeuille /10
2. Macro en 2 lignes
3. Top 3 actions concrètes aujourd'hui
4. Risque principal
5. Opportunité du jour""",

        "evening": f"""Bilan fin de journée pour Amine.
POSITIONS: {chr(10).join(pos_text)}
NEWS: {chr(10).join(news[:3])}
ALERTES: {chr(10).join(alerts) if alerts else 'Aucune'}

Bilan en français (max 200 mots):
1. Performance du jour
2. Ce qui a bien/mal marché
3. Plan pour demain
4. Ordres à préparer""",

        "alert": f"""ALERTE URGENTE portefeuille Amine!
ALERTES: {chr(10).join(alerts)}
BRENT: {brent}$
POSITIONS: {chr(10).join(pos_text)}

3 lignes max: Que s'est-il passé? Risque? Action MAINTENANT?""",

        "iran": f"""Scan géopolitique Iran pour Amine.
BRENT: {brent}$ | NEWS: {chr(10).join(news[:5])}
TTE: {prices.get('TTE.PA',{}).get('price','N/A')}€ stop 75.95€ target 85€
SHELL: {prices.get('SHEL.AS',{}).get('price','N/A')}€ stop 37.50€ target 44€
INSW: {prices.get('INSW',{}).get('price','N/A')}$ stop 66$ target 82$

5 points: 1-Hormuz maintenant 2-Impact Brent 3-Signal TTE 4-Signal SHELL 5-Signal INSW"""
    }

    try:
        r = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompts.get(mode, prompts["morning"])}]
        )
        return r.content[0].text
    except Exception as e:
        return f"Erreur IA: {e}"

def check_alerts():
    prices = get_prices()
    brent  = get_brent()
    alerts = []
    for ticker, info in PORTFOLIO.items():
        price = prices.get(ticker, {}).get("price")
        pos   = PORTFOLIO[ticker]
        if price:
            dist_stop = ((price - pos["stop"]) / price) * 100
            dist_tgt  = ((pos["target"] - price) / price) * 100
            if abs(dist_stop) < 1.5:
                alerts.append(f"🚨 {info['name']}: STOP à {abs(dist_stop):.1f}%!")
            if dist_tgt < 1.5:
                alerts.append(f"🎯 {info['name']}: TARGET à {dist_tgt:.1f}%!")
    if alerts:
        news = get_iran_news()
        a    = analyze(prices, brent, news, "alert")
        send_telegram(f"⚡ <b>ALERTE</b>\n\n" + "\n".join(alerts) + f"\n\n{a}")

def morning():
    prices = get_prices(); brent = get_brent(); news = get_iran_news()
    send_telegram(format_portfolio(prices, brent))
    time.sleep(2)
    send_telegram(f"🌅 <b>BRIEFING MATIN</b>\n\n{analyze(prices, brent, news, 'morning')}")

def evening():
    prices = get_prices(); brent = get_brent(); news = get_iran_news()
    send_telegram(format_portfolio(prices, brent))
    time.sleep(2)
    send_telegram(f"🌆 <b>BILAN SOIR</b>\n\n{analyze(prices, brent, news, 'evening')}")

def night_iran():
    prices = get_prices(); brent = get_brent(); news = get_iran_news()
    send_telegram(f"🌙 <b>SCAN IRAN 22H</b>\n\n{analyze(prices, brent, news, 'iran')}")

def handle_commands():
    offset = 0
    while True:
        try:
            url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            data = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35).json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg    = update.get("message", {})
                text   = msg.get("text", "").strip().lower()
                cid    = str(msg.get("chat", {}).get("id", ""))
                if cid != CHAT_ID:
                    continue
                prices = get_prices()
                brent  = get_brent()
                if text in ["/check", "check"]:
                    send_telegram(format_portfolio(prices, brent))
                elif text in ["/scan", "scan"]:
                    send_telegram("🔍 Analyse en cours...")
                    news = get_iran_news()
                    send_telegram(f"⚡ <b>SCAN COMPLET</b>\n\n{analyze(prices, brent, news, 'morning')}")
                elif text in ["/iran", "iran"]:
                    send_telegram("🌍 Scan Iran...")
                    news = get_iran_news()
                    send_telegram(f"🌍 <b>SCAN IRAN</b>\n\n{analyze(prices, brent, news, 'iran')}")
                elif text in ["/agenda", "agenda"]:
                    lines = ["📅 <b>AGENDA CATALYSEURS</b>\n"]
                    for e in EVENTS:
                        d = get_days_until(e["date"])
                        if d >= 0:
                            em = "🔴" if d <= 2 else ("🟡" if d <= 7 else "⚪")
                            lines.append(f"{em} J-{d} | <b>{e['label']}</b>\n   → {e['action']}")
                    send_telegram("\n".join(lines))
                elif text in ["/brent", "brent"]:
                    if brent:
                        pct = round(((brent - 72.48) / 72.48) * 100, 1)
                        send_telegram(f"🛢️ <b>BRENT</b>\n\nPrix: <b>${brent}</b>\nDepuis guerre: <b>{pct:+.1f}%</b>\nPré-guerre: $72.48")
                elif text in ["/help", "help", "/start", "start"]:
                    send_telegram(
                        "🤖 <b>AMINE INTEL BOT</b>\n\n"
                        "Commandes:\n\n"
                        "/check — Cours en temps réel\n"
                        "/scan — Analyse IA complète\n"
                        "/iran — Scan géopolitique\n"
                        "/agenda — Calendrier catalyseurs\n"
                        "/brent — Prix Brent live\n"
                        "/help — Cette aide\n\n"
                        "⏰ Briefings auto: 9h15, 17h30, 22h00\n"
                        "🔔 Alertes stops: toutes les 30min"
                    )
        except Exception as e:
            print(f"Erreur cmd: {e}")
            time.sleep(5)

def main():
    print("=" * 45)
    print("  AMINE INTEL BOT — Démarrage")
    print("=" * 45)
    send_telegram(
        "🤖 <b>AMINE INTEL BOT ACTIVÉ ✅</b>\n\n"
        "⏰ Briefings: 9h15 • 17h30 • 22h00\n"
        "🔔 Alertes stops: toutes les 30min\n\n"
        "Tape /help pour voir les commandes\n"
        "Tape /check pour voir tes positions maintenant"
    )
    schedule.every().day.at("09:15").do(morning)
    schedule.every().day.at("17:30").do(evening)
    schedule.every().day.at("22:00").do(night_iran)
    schedule.every(30).minutes.do(check_alerts)
    threading.Thread(target=handle_commands, daemon=True).start()
    print("✅ Bot actif — en attente des commandes...")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
