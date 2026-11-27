"""Univers d'actifs surveillés : actions US liquides, ETF sectoriels, matières premières.

ATTENTION (biais du survivant) : cette liste est composée d'entreprises qui existent
et sont grandes AUJOURD'HUI. Un backtest sur le passé avec cette liste est donc
optimiste : il ignore les entreprises qui ont chuté ou disparu entre-temps.
Les résultats de backtest doivent être lus avec cette réserve.
"""

BENCHMARK = "SPY"

STOCKS = {
    "tech": [
        "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "INTC", "CSCO",
        "QCOM", "TXN", "IBM", "NOW", "INTU", "AMAT", "MU", "LRCX", "KLAC", "ADI",
        "PANW", "CRWD", "SNPS", "CDNS", "ANET", "PLTR",
    ],
    "communication": ["GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "T", "CMCSA"],
    "consumer_disc": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "BKNG", "TJX", "CMG",
        "ORLY", "MAR", "GM", "F",
    ],
    "consumer_staples": ["PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL", "KMB", "GIS"],
    "health": [
        "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN",
        "GILD", "ISRG", "VRTX", "REGN", "BMY", "CVS", "MDT", "SYK",
    ],
    "financials": [
        "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "V", "MA",
        "PYPL", "SPGI", "CME", "ICE", "COF", "USB", "PNC", "BRK-B",
    ],
    "industrials": [
        "CAT", "DE", "HON", "GE", "UNP", "UPS", "RTX", "LMT", "NOC", "GD", "BA",
        "MMM", "ETN", "EMR", "ITW", "FDX", "WM", "CSX",
    ],
    "energy": ["XOM", "CVX", "COP", "EOG", "SLB", "OXY", "PSX", "MPC", "VLO", "KMI", "WMB"],
    "materials": ["LIN", "APD", "SHW", "FCX", "NEM", "NUE", "CCJ"],
    "utilities": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE"],
    "real_estate": ["PLD", "AMT", "EQIX", "SPG", "O", "PSA"],
}

ETFS = {
    "index": ["SPY", "QQQ", "IWM", "DIA"],
    "sectors": [
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
        "SMH", "IBB", "XBI", "KRE", "ITA", "XHB", "XOP",
    ],
    "commodities": ["GLD", "SLV", "GDX", "GDXJ", "USO", "UNG", "CPER", "DBA", "DBC", "URA", "PPLT"],
    "bonds": ["TLT", "IEF", "HYG"],
}


def all_tickers() -> list[str]:
    """Tous les tickers, sans doublon, dans un ordre stable."""
    seen: dict[str, None] = {}
    for group in (STOCKS, ETFS):
        for tickers in group.values():
            for t in tickers:
                seen.setdefault(t, None)
    seen.setdefault(BENCHMARK, None)
    return list(seen)


def category_of(ticker: str) -> str:
    """Catégorie d'un ticker (ex. 'tech', 'commodities'), ou 'unknown'."""
    for group in (STOCKS, ETFS):
        for name, tickers in group.items():
            if ticker in tickers:
                return name
    return "unknown"


# Familles d'ETF fortement corrélés entre eux (pour limiter la concentration)
ETF_FAMILIES = {
    "us_large": ["SPY", "DIA", "QQQ", "XLK", "SMH", "XLC"],
    "us_small": ["IWM", "KRE"],
    "financials": ["XLF"],
    "energy": ["XLE", "XOP", "USO", "UNG"],
    "health": ["XLV", "IBB", "XBI"],
    "industrials": ["XLI", "ITA"],
    "consumer": ["XLY", "XLP", "XHB"],
    "defensive_eq": ["XLU", "XLRE"],
    "materials": ["XLB", "CPER", "URA"],
    "precious_metals": ["GLD", "SLV", "GDX", "GDXJ", "PPLT"],
    "agri_broad": ["DBA", "DBC"],
    "bonds": ["TLT", "IEF", "HYG"],
}


def group_of(ticker: str) -> str:
    """Famille de corrélation : famille d'ETF, sinon secteur de l'action."""
    for name, tickers in ETF_FAMILIES.items():
        if ticker in tickers:
            return name
    return category_of(ticker)
