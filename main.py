import os
import time
import schedule
import threading
import requests
import yfinance as yf
from datetime import datetime
import anthropic

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8688782085:AAFKvXMCClaeKBt-Yd4paRQJi6YBIH0GUxY")
CHAT_ID = os.environ.get("CHAT_ID", "8654742500")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "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")

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

PORTFOLIO = {
    "TTE.PA":  {"name": "TotalEnergies", "parts": 233, "entry": 72.70, "stop": 75.95, "target": 85.00, "currency": "EUR"},
    "SHEL.AS": {"name": "Shell",         "parts": 645, "entry": 39.48, "stop": 37.50, "target": 44.00, "currency": "EUR"},
    "INSW":    {"name": "Int Seaways",   "parts": 171, "entry": 71.80, "stop": 66.00, "target": 82.00, "currency": "USD"},
    "EXV1.DE": {"name": "EXV1 Banques",  "parts": 445, "entry": 33.78, "stop": 30.00, "target": 36.00, "currency": "EUR"},
    "NVDA":    {"name": "NVIDIA",        "parts": 81,  "entry": 185.0, "stop": 170.0, "target": 210.0, "currency": "USD"},
    "PLTR":    {"name": "Palantir",      "parts": 8,   "entry": 154.0, "stop": 156.0, "target": 175.0, "currency": "USD"},
}

EVENTS = [
    {"date": "24/03/2026", "label": "AGO Attijariwafa BVC",    "action": "Vendre 50% ATW si +8%"},
    {"date": "26/03/2026", "label": "AGO IAM Maroc Telecom",   "action": "Dividende IAM"},
    {"date": "29/04/2026", "label": "Resultats TotalEnergies", "action": "Vendre 1/3 TTE a l annonce"},
    {"date": "30/04/2026", "label": "FOMC Decision taux",      "action": "Adapter selon decision Fed"},
    {"date": "07/05/2026", "label": "Resultats Shell",         "action": "Vendre 1/3 si >45 EUR"},
    {"date": "27/05/2026", "label": "Resultats NVIDIA",        "action": "Vendre si +20%"},
]

def send_telegram(message):
    url = "https://api.telegram.org/bot{}/sendMessage".format(TELEGRAM_TOKEN)
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print("Erreur Telegram: {}".format(e))

def get_prices():
    prices = {}
    for ticker in PORTFOLIO:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d", interval="5m")
            if not hist.empty:
                price = round(float(hist["Close"].iloc[-1]), 2)
                prev = round(float(hist["Close"].iloc[0]), 2)
                change = round(((price - prev) / prev) * 100, 2)
                prices[ticker] = {"price": price, "change": change}
            else:
                prices[ticker] = {"price": None, "change": None}
        except Exception:
            prices[ticker] = {"price": None, "change": None}
    return prices

def get_brent():
    try:
        b = yf.Ticker("BZ=F")
        h = b.history(period="1d", interval="5m")
        if not h.empty:
            return round(float(h["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return None

def get_iran_news():
    try:
        import re
        rss = requests.get(
            "https://news.google.com/rss/search?q=Iran+war+Strait+Hormuz+oil&hl=fr&gl=FR&ceid=FR:fr",
            timeout=10
        ).text
        titles = re.findall(r"<title>(.*?)</title>", rss)[2:6]
        return [re.sub(r"<[^>]+>", "", t) for t in titles]
    except Exception:
        return ["News indisponibles"]

def get_days_until(date_str):
    d, m, y = date_str.split("/")
    return (datetime(int(y), int(m), int(d)) - datetime.now()).days

def format_portfolio(prices, brent):
    lines = ["PORTEFEUILLE AMINE\n"]
    if brent:
        pct = round(((brent - 72.48) / 72.48) * 100, 1)
        lines.append("Brent: <b>$" + str(brent) + "</b> (" + str(pct) + "% depuis guerre)\n")
    lines.append("-----------------")
    for ticker, info in PORTFOLIO.items():
        pd = prices.get(ticker, {})
        price = pd.get("price")
        change = pd.get("change")
        pos = PORTFOLIO[ticker]
        sym = "EUR" if info["currency"] == "EUR" else "USD"
        sign = "E" if sym == "EUR" else "$"
        if price:
            pnl = round((price - pos["entry"]) * pos["parts"], 0)
            dist_stop = round(((price - pos["stop"]) / price) * 100, 1)
            emoji = "verde" if pnl > 0 else "rouge"
            alert = "URGENT " if abs(dist_stop) < 2 else ("ATTENTION " if abs(dist_stop) < 5 else "")
            green = "\U0001f7e2" if pnl > 0 else "\U0001f534"
            warn = "\U0001f6a8" if abs(dist_stop) < 2 else ("\u26a0\ufe0f" if abs(dist_stop) < 5 else "")
            ch_str = str(change) if change is not None else "N/A"
            lines.append(
                green + warn + " <b>" + info["name"] + "</b>\n"
                "   " + str(price) + sign + " (" + ch_str + "%) | P&L: " + str(pnl) + sign + "\n"
                "   Stop: " + str(pos["stop"]) + sign + " (" + str(dist_stop) + "%) | Target: " + str(pos["target"]) + sign
            )
        else:
            lines.append("\u26aa <b>" + info["name"] + "</b> - cours indisponible")
    return "\n".join(lines)

def analyze(prices, brent, news, mode="morning"):
    pos_lines = []
    alerts = []
    for ticker, info in PORTFOLIO.items():
        pd = prices.get(ticker, {})
        price = pd.get("price")
        pos = PORTFOLIO[ticker]
        if price:
            pnl = round((price - pos["entry"]) * pos["parts"], 0)
            dist_stop = round(((price - pos["stop"]) / price) * 100, 1)
            dist_tgt = round(((pos["target"] - price) / price) * 100, 1)
            pos_lines.append(
                info["name"] + ": " + str(price) + " | P&L:" + str(pnl) +
                " | Stop:" + str(dist_stop) + "% | Target:" + str(dist_tgt) + "%"
            )
            if abs(dist_stop) < 2:
                alerts.append("URGENT " + info["name"] + " a " + str(abs(dist_stop)) + "% du STOP!")
            if dist_tgt < 2:
                alerts.append("TARGET " + info["name"] + " a " + str(dist_tgt) + "% du TARGET!")

    upcoming = []
    for e in EVENTS:
        d = get_days_until(e["date"])
        if 0 <= d <= 7:
            upcoming.append("J-" + str(d) + ": " + e["label"] + " -> " + e["action"])

    pos_text = "\n".join(pos_lines) if pos_lines else "Cours indisponibles (marche ferme)"
    alerts_text = "\n".join(alerts) if alerts else "Aucune"
    events_text = "\n".join(upcoming) if upcoming else "Aucun dans 7 jours"
    news_text = "\n".join(news[:4]) if news else "Indisponibles"
    brent_str = str(brent) if brent else "N/A"

    if mode == "morning":
        prompt = (
            "Tu es l analyste d Amine Chaoui (130K EUR IBKR). Guerre Iran J+23, Brent " + brent_str + "$.\n\n"
            "POSITIONS:\n" + pos_text + "\n\n"
            "NEWS:\n" + news_text + "\n\n"
            "ALERTES: " + alerts_text + "\n"
            "EVENEMENTS SEMAINE: " + events_text + "\n\n"
            "Briefing matin en francais avec emojis (max 250 mots):\n"
            "1. Score portefeuille /10\n"
            "2. Macro en 2 lignes\n"
            "3. Top 3 actions concretes aujourd hui\n"
            "4. Risque principal\n"
            "5. Opportunite du jour"
        )
    elif mode == "evening":
        prompt = (
            "Bilan fin de journee pour Amine.\n"
            "POSITIONS: " + pos_text + "\n"
            "NEWS: " + news_text + "\n"
            "ALERTES: " + alerts_text + "\n\n"
            "Bilan en francais (max 200 mots):\n"
            "1. Performance du jour\n"
            "2. Ce qui a bien/mal marche\n"
            "3. Plan pour demain\n"
            "4. Ordres a preparer"
        )
    elif mode == "alert":
        prompt = (
            "ALERTE URGENTE portefeuille Amine!\n"
            "ALERTES: " + alerts_text + "\n"
            "BRENT: " + brent_str + "$\n"
            "POSITIONS: " + pos_text + "\n\n"
            "3 lignes max: Que s est-il passe? Risque? Action MAINTENANT?"
        )
    else:
        prompt = (
            "Scan geopolitique Iran pour Amine.\n"
            "BRENT: " + brent_str + "$ | NEWS: " + news_text + "\n\n"
            "5 points: 1-Hormuz maintenant 2-Impact Brent 3-Signal TTE 4-Signal SHELL 5-Signal INSW"
        )

    try:
        r = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return r.content[0].text
    except Exception as e:
        return "Erreur IA: " + str(e)

def check_alerts():
    prices = get_prices()
    brent = get_brent()
    alerts = []
    for ticker, info in PORTFOLIO.items():
        price = prices.get(ticker, {}).get("price")
        pos = PORTFOLIO[ticker]
        if price:
            dist_stop = round(((price - pos["stop"]) / price) * 100, 1)
            dist_tgt = round(((pos["target"] - price) / price) * 100, 1)
            if abs(dist_stop) < 1.5:
                alerts.append("\U0001f6a8 " + info["name"] + ": STOP a " + str(abs(dist_stop)) + "%!")
            if dist_tgt < 1.5:
                alerts.append("\U0001f3af " + info["name"] + ": TARGET a " + str(dist_tgt) + "%!")
    if alerts:
        news = get_iran_news()
        a = analyze(prices, brent, news, "alert")
        send_telegram("\u26a1 <b>ALERTE</b>\n\n" + "\n".join(alerts) + "\n\n" + a)

def morning():
    prices = get_prices()
    brent = get_brent()
    news = get_iran_news()
    send_telegram(format_portfolio(prices, brent))
    time.sleep(2)
    send_telegram("\U0001f305 <b>BRIEFING MATIN</b>\n\n" + analyze(prices, brent, news, "morning"))

def evening():
    prices = get_prices()
    brent = get_brent()
    news = get_iran_news()
    send_telegram(format_portfolio(prices, brent))
    time.sleep(2)
    send_telegram("\U0001f306 <b>BILAN SOIR</b>\n\n" + analyze(prices, brent, news, "evening"))

def night_iran():
    prices = get_prices()
    brent = get_brent()
    news = get_iran_news()
    send_telegram("\U0001f319 <b>SCAN IRAN 22H</b>\n\n" + analyze(prices, brent, news, "iran"))

def handle_commands():
    offset = 0
    while True:
        try:
            url = "https://api.telegram.org/bot{}/getUpdates".format(TELEGRAM_TOKEN)
            data = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35).json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip().lower()
                cid = str(msg.get("chat", {}).get("id", ""))
                if cid != str(CHAT_ID):
                    continue
                prices = get_prices()
                brent = get_brent()
                if text in ["/check", "check"]:
                    send_telegram(format_portfolio(prices, brent))
                elif text in ["/scan", "scan"]:
                    send_telegram("\U0001f50d Analyse en cours...")
                    news = get_iran_news()
                    send_telegram("\u26a1 <b>SCAN COMPLET</b>\n\n" + analyze(prices, brent, news, "morning"))
                elif text in ["/iran", "iran"]:
                    send_telegram("\U0001f30d Scan Iran...")
                    news = get_iran_news()
                    send_telegram("\U0001f30d <b>SCAN IRAN</b>\n\n" + analyze(prices, brent, news, "iran"))
                elif text in ["/agenda", "agenda"]:
                    lines = ["\U0001f4c5 <b>AGENDA CATALYSEURS</b>\n"]
                    for e in EVENTS:
                        d = get_days_until(e["date"])
                        if d >= 0:
                            em = "\U0001f534" if d <= 2 else ("\U0001f7e1" if d <= 7 else "\u26aa")
                            lines.append(em + " J-" + str(d) + " | <b>" + e["label"] + "</b>\n   -> " + e["action"])
                    send_telegram("\n".join(lines))
                elif text in ["/brent", "brent"]:
                    if brent:
                        pct = round(((brent - 72.48) / 72.48) * 100, 1)
                        send_telegram(
                            "\U0001f6e2\ufe0f <b>BRENT</b>\n\n"
                            "Prix: <b>$" + str(brent) + "</b>\n"
                            "Depuis guerre: <b>" + str(pct) + "%</b>\n"
                            "Pre-guerre: $72.48"
                        )
                    else:
                        send_telegram("\U0001f6e2\ufe0f Brent indisponible (marche ferme)")
                elif text in ["/help", "help", "/start", "start"]:
                    send_telegram(
                        "\U0001f916 <b>AMINE INTEL BOT</b>\n\n"
                        "Commandes:\n\n"
                        "/check - Cours en temps reel\n"
                        "/scan - Analyse IA complete\n"
                        "/iran - Scan geopolitique\n"
                        "/agenda - Calendrier catalyseurs\n"
                        "/brent - Prix Brent live\n"
                        "/help - Cette aide\n\n"
                        "\u23f0 Briefings auto: 9h15, 17h30, 22h00\n"
                        "\U0001f514 Alertes stops: toutes les 30min"
                    )
        except Exception as e:
            print("Erreur cmd: {}".format(e))
            time.sleep(5)

def main():
    print("AMINE INTEL BOT - Demarrage")
    send_telegram(
        "\U0001f916 <b>AMINE INTEL BOT ACTIVE</b>\n\n"
        "\u2705 Surveillance active\n"
        "\u23f0 Briefings: 9h15, 17h30, 22h00\n"
        "\U0001f514 Alertes stops: toutes les 30min\n\n"
        "Tape /help pour les commandes\n"
        "Tape /check pour tes positions"
    )
    schedule.every().day.at("09:15").do(morning)
    schedule.every().day.at("17:30").do(evening)
    schedule.every().day.at("22:00").do(night_iran)
    schedule.every(30).minutes.do(check_alerts)
    t = threading.Thread(target=handle_commands, daemon=True)
    t.start()
    print("Bot actif - en attente...")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
