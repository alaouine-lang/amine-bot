"""Ligne de commande du système swing.

Exemples :
  python -m swing download
  python -m swing backtest --strategy momentum --start 2012-01-01 --split 2021-01-01
  python -m swing screen --strategy momentum --capital 130000
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

from . import universe
from .backtest import BacktestConfig, run_backtest
from .data import DEFAULT_START, data_dir, load_prices
from .screener import append_to_journal, screen
from .strategies import STRATEGIES, get_strategy

PCT_KEYS = {"exposition_moyenne", "rendement_total", "cagr", "volatilite", "max_drawdown", "taux_reussite", "gain_moyen", "perte_moyenne"}
LABELS = {
    "debut": "Début",
    "fin": "Fin",
    "rendement_total": "Rendement total",
    "cagr": "Rendement annuel (CAGR)",
    "volatilite": "Volatilité annuelle",
    "sharpe": "Ratio de Sharpe",
    "max_drawdown": "Perte max (drawdown)",
    "calmar": "Ratio de Calmar",
    "exposition_moyenne": "Capital investi (moyenne)",
    "nb_trades": "Nombre de trades",
    "taux_reussite": "Taux de réussite",
    "gain_moyen": "Gain moyen (gagnants)",
    "perte_moyenne": "Perte moyenne (perdants)",
    "profit_factor": "Profit factor",
    "r_moyen": "Gain moyen en R",
    "duree_moyenne_jours": "Durée moyenne (jours)",
}


def _fmt(key: str, value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and math.isnan(value):
        return "-"
    if key in PCT_KEYS:
        return f"{value * 100:,.1f} %"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _print_table(columns: dict[str, dict]) -> None:
    names = list(columns)
    keys = [k for k in LABELS if any(k in columns[n] for n in names)]
    width = max(len(LABELS[k]) for k in keys) + 2
    print(" " * width + "".join(f"{n:>18}" for n in names))
    for k in keys:
        print(f"{LABELS[k]:<{width}}" + "".join(f"{_fmt(k, columns[n].get(k)):>18}" for n in names))


def _load(args) -> dict:
    tickers = args.tickers.split(",") if args.tickers else universe.all_tickers()
    if universe.BENCHMARK not in tickers:
        tickers.append(universe.BENCHMARK)
    data = load_prices(tickers, start=DEFAULT_START, refresh=args.refresh, offline=args.offline)
    missing = sorted(set(tickers) - set(data))
    if missing:
        print(f"⚠️  Pas de données pour : {', '.join(missing)}")
    if universe.BENCHMARK not in data:
        sys.exit(f"Impossible de charger l'indice de référence {universe.BENCHMARK}.")
    return data


def cmd_download(args) -> None:
    data = _load(args)
    print(f"✅ {len(data)} tickers en cache dans {data_dir() / 'cache'}")


def cmd_backtest(args) -> None:
    data = _load(args)
    strategy = get_strategy(args.strategy)
    cfg = BacktestConfig(
        initial_capital=args.capital,
        risk_per_trade=args.risk,
        max_positions=args.max_positions,
    )
    result = run_backtest(data, strategy, universe.BENCHMARK, cfg, start=args.start, end=args.end)

    print(f"\n=== Backtest : {strategy.name} | {len(data)} actifs | capital {args.capital:,.0f} $ ===\n")
    cols = {"Période complète": result.metrics(), "S&P 500 (SPY)": result.benchmark_metrics()}
    if args.split:
        cols = {
            "Entraînement": result.metrics(end=args.split),
            "Test (inédit)": result.metrics(start=args.split),
            "SPY (test)": result.benchmark_metrics(start=args.split),
            "Période complète": result.metrics(),
        }
    _print_table(cols)

    trades = result.trades_frame()
    if not trades.empty:
        print("\nRaisons de sortie :", trades["exit_reason"].value_counts().to_dict())
    print(
        "\nRappels : cours de l'univers ACTUEL (biais du survivant → résultats optimistes) ;"
        "\nles performances passées ne préjugent pas des performances futures."
    )

    if args.save:
        out = Path(data_dir()).parent / "reports"
        out.mkdir(parents=True, exist_ok=True)
        stem = f"backtest_{strategy.name}_{result.equity.index[0].date()}_{result.equity.index[-1].date()}"
        trades.to_csv(out / f"{stem}_trades.csv", index=False)
        result.equity.to_frame("equity").join(result.benchmark).to_csv(out / f"{stem}_equity.csv")
        print(f"\n💾 Résultats enregistrés dans {out}")


def cmd_optimize(args) -> None:
    from .optimize import optimize

    data = _load(args)
    cfg = BacktestConfig(initial_capital=args.capital, risk_per_trade=args.risk)

    def progress(n, total):
        print(f"\r  combinaison {n}/{total}", end="", flush=True)

    print(f"Optimisation de {args.strategy} sur {args.start} → {args.split} (entraînement uniquement)…")
    cands = optimize(data, args.strategy, split=args.split, start=args.start, base_config=cfg, progress=progress)
    print("\n")
    header = f"{'#':>3}  {'Paramètres':<62}{'Sharpe ent.':>12}{'CAGR ent.':>11}{'Sharpe test':>13}{'CAGR test':>11}{'DD test':>10}"
    print(header)
    print("-" * len(header))
    for i, c in enumerate(cands[: args.top], 1):
        params = ", ".join(f"{k.replace('cfg.', '')}={v}" for k, v in c.params.items())
        print(
            f"{i:>3}  {params:<62}{_fmt('sharpe', c.train.get('sharpe')):>12}{_fmt('cagr', c.train.get('cagr')):>11}"
            f"{_fmt('sharpe', c.test.get('sharpe')):>13}{_fmt('cagr', c.test.get('cagr')):>11}{_fmt('max_drawdown', c.test.get('max_drawdown')):>10}"
        )
    print(
        "\nLe classement se fait UNIQUEMENT sur l'entraînement. Les colonnes « test » montrent"
        "\nce que chaque réglage aurait donné ensuite, sur des années jamais vues."
    )


def cmd_live(args) -> None:
    from .live import paper_dir, run_daily, send_telegram

    data = _load(args)
    report, state = run_daily(data, capital=args.capital, force_signal=args.force_signal)
    text = report.message(state)
    # Telegram d'abord : un problème d'affichage local ne doit jamais empêcher l'envoi
    status = None
    if not args.no_telegram:
        sent, why = send_telegram(text)
        status = "envoyé" if sent else f"non envoyé — {why}"
    print(text.replace("<b>", "").replace("</b>", ""))
    if status:
        print("\n📨 Telegram : " + status)
    print(f"\n📁 Fichiers du paper trading : {paper_dir()}")


def cmd_telegram_test(args) -> None:
    import os

    import requests

    from .config import diagnose

    print(diagnose())
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("CHAT_ID")
    if not token:
        sys.exit("\nAucun token chargé.")
    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
    except Exception as e:
        sys.exit(f"\nErreur réseau : {type(e).__name__}")
    if me.status_code == 401:
        sys.exit(
            "\n❌ Telegram refuse ce token (401). Il a été révoqué ou contient une erreur."
            "\n   Dans BotFather : /mybots → votre bot → API Token, copiez le token affiché et remplacez-le dans .env."
        )
    if not me.ok:
        sys.exit(f"\n❌ Réponse inattendue de Telegram : {me.status_code}")
    print(f"\n✅ Token valide : bot @{me.json()['result'].get('username')}")
    from .live import send_telegram

    ok, why = send_telegram("✅ Test du système swing : la connexion Telegram fonctionne.")
    print("📨 Message de test : " + ("envoyé" if ok else why))


def cmd_screen(args) -> None:
    data = _load(args)
    strategy = get_strategy(args.strategy)
    proposals = screen(data, strategy, universe.BENCHMARK, capital=args.capital, risk_per_trade=args.risk)
    last = data[universe.BENCHMARK].index[-1].date()
    print(f"\n=== Screener {strategy.name} — séance du {last} ===\n")
    if not proposals:
        print("Aucun signal d'entrée aujourd'hui.")
    else:
        print(f"{'Ticker':<7}{'Catégorie':<18}{'Clôture':>10}{'Stop':>10}{'Risque':>9}{'Quantité':>10}{'Montant':>12}{'Score':>9}")
        for p in proposals[: args.top]:
            print(
                f"{p.ticker:<7}{p.category:<18}{p.close:>10.2f}{p.stop:>10.2f}"
                f"{p.risk_pct * 100:>8.1f}%{p.shares:>10}{p.position_value:>12,.0f}{p.score:>9.3f}"
            )
    if not args.no_journal:
        path = append_to_journal(proposals)
        print(f"\n📒 Journal mis à jour : {path}")
    print("\nCe sont des signaux quantitatifs à valider : la décision finale vous appartient.")


def _utf8_console() -> None:
    """Évite le plantage sur les emojis quand Windows écrit dans un fichier (encodage cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> None:
    _utf8_console()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    from .config import load_env

    load_env()
    parser = argparse.ArgumentParser(prog="python -m swing", description="Système de swing trading")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--tickers", help="Liste de tickers séparés par des virgules (défaut : tout l'univers)")
        p.add_argument("--refresh", action="store_true", help="Forcer le re-téléchargement des cours")
        p.add_argument("--offline", action="store_true", help="Utiliser uniquement le cache local")

    p = sub.add_parser("download", help="Télécharger les cours dans le cache")
    common(p)
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("backtest", help="Tester une stratégie sur l'historique")
    common(p)
    p.add_argument("--strategy", choices=list(STRATEGIES), default="momentum")
    p.add_argument("--start", default="2012-01-01")
    p.add_argument("--end")
    p.add_argument("--split", help="Date de séparation entraînement / test (ex. 2021-01-01)")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--risk", type=float, default=0.01, help="Part du capital risquée par trade (0.01 = 1 %%)")
    p.add_argument("--max-positions", type=int, default=8)
    p.add_argument("--save", action="store_true", help="Enregistrer trades et courbe de capital en CSV")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("optimize", help="Chercher les meilleurs réglages sur la période d'entraînement")
    common(p)
    p.add_argument("--strategy", choices=list(STRATEGIES), default="momentum")
    p.add_argument("--start", default="2012-01-01")
    p.add_argument("--split", default="2021-01-01")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--risk", type=float, default=0.01)
    p.add_argument("--top", type=int, default=10)
    p.set_defaults(func=cmd_optimize)

    p = sub.add_parser("live", help="Paper trading quotidien de la stratégie retenue (à lancer chaque soir)")
    common(p)
    p.add_argument("--capital", type=float, default=50_000.0, help="Capital fictif de départ (1re exécution)")
    p.add_argument("--force-signal", action="store_true", help="Calculer les cibles même hors fin de mois")
    p.add_argument("--no-telegram", action="store_true")
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("telegram-test", help="Vérifier le token et le chat ID Telegram (sans les afficher)")
    p.set_defaults(func=cmd_telegram_test)

    p = sub.add_parser("screen", help="Signaux d'entrée de la dernière séance")
    common(p)
    p.add_argument("--strategy", choices=list(STRATEGIES), default="momentum")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--risk", type=float, default=0.01)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--no-journal", action="store_true", help="Ne pas écrire dans le journal")
    p.set_defaults(func=cmd_screen)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
