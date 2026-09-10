#!/usr/bin/env python3
"""Portfolio Server for Render - Multi-portfolio with tabs"""

import http.server
import json
import urllib.request
import urllib.error
import re
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

PORT = int(os.environ.get("PORT", 10000))

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Google Finance quote pages, keyed by our internal symbol -> (google ticker, exchange).
# Yahoo feeds Render's datacenter IP stale (previous-close) data, which made every
# day-change read 0.00%. Google Finance is not IP-gated, so we scrape its quote
# pages instead — they return a fresh price + signed day change. Exchanges below
# were resolved empirically (see resolve test). PSH.AS is intentionally omitted
# (no clean Google listing) and falls back to Yahoo.
GF_MAP = {
    "AAL": ("AAL", "NASDAQ"), "AMZN": ("AMZN", "NASDAQ"), "CROX": ("CROX", "NASDAQ"),
    "KSPI": ("KSPI", "NASDAQ"), "MSFT": ("MSFT", "NASDAQ"), "PDD": ("PDD", "NASDAQ"),
    "WDAY": ("WDAY", "NASDAQ"),
    "AMR": ("AMR", "NYSE"), "BN": ("BN", "NYSE"), "CNR": ("CNR", "NYSE"),
    "MIAX": ("MIAX", "NYSE"), "NE": ("NE", "NYSE"), "RIG": ("RIG", "NYSE"),
    "SNAP": ("SNAP", "NYSE"), "SOC": ("SOC", "NYSE"), "TDW": ("TDW", "NYSE"),
    "UBER": ("UBER", "NYSE"), "VAL": ("VAL", "NYSE"),
    "CNSWF": ("CNSWF", "OTCMKTS"), "LMGIF": ("LMGIF", "OTCMKTS"),
    "PNPFF": ("PNPFF", "OTCMKTS"), "TAVHY": ("TAVHY", "OTCMKTS"),
    "TOITF": ("TOITF", "OTCMKTS"), "PSHZF": ("PSHZF", "OTCMKTS"),
    "DBO.TO": ("DBO", "TSE"), "TGO.TO": ("TGO", "TSE"), "CPH.TO": ("CPH", "TSE"),
    "1970.HK": ("1970", "HKG"),
    "UMG.AS": ("UMG", "AMS"),
}

# Day-% proxy: for a holding priced elsewhere, borrow a fresh day-change % from an
# equivalent listing that IS on Google. Empty now that Pershing Square is priced
# directly off its USD OTC line PSHZF — the Amsterdam EUR line PSH.AS got delisted
# on Yahoo (2026-08-20), which was silently dropping the whole ~$158K position.
DAYPCT_PROXY = {}

_RE_PRICE = re.compile(r'class="ujg0He"><div class="N6SYTe"><span jsname="Pdsbrc"[^>]*><span>([^<]+)</span>')
_RE_PCT = re.compile(r'jsname="vY9t3b"[^>]*><span[^>]*>([+\-]?[0-9.]+)%')
_RE_AMT = re.compile(r'jsname="xnruHf"[^>]*><span>([+\-]?[0-9.,]+)</span>')

# ============== PORTFOLIO 1: ANNABAY ==============
ANNABAY_HOLDINGS = {
    "RIG": {"name": "Transocean Ltd", "qty": 25000, "cost": 97500},
    "PSHZF": {"name": "Pershing Square Holdings", "qty": 3000, "cost": 191324},  # USD OTC line; PSH.AS (EUR) delisted on Yahoo 2026-08-20. Statement values it in USD.
    "MSFT": {"name": "Microsoft Corp", "qty": 550, "cost": 207218},  # per 10.09.2026 statement (was 700 @ 263732)
    "CROX": {"name": "Crocs Inc", "qty": 1200, "cost": 91200},  # per 10.09.2026 statement (was 1500 @ 114000)
    "CNSWF": {"name": "Constellation Software", "qty": 100, "cost": 247899},
    "PDD": {"name": "PDD Holdings", "qty": 2000, "cost": 196000},
    "UBER": {"name": "Uber Technologies", "qty": 3000, "cost": 234500},
    "AMR": {"name": "Alpha Metallurgical Resources", "qty": 1500, "cost": 238500},  # per 10.09.2026 statement (was 1750 @ 278250)
    "BN": {"name": "Brookfield Corp", "qty": 6000, "cost": 271220},
    "CNR": {"name": "Core Natural Resources", "qty": 1000, "cost": 75500},
    "MIAX": {"name": "Miami International Holdings", "qty": 2500, "cost": 105000},
    "SNAP": {"name": "Snap Inc", "qty": 20000, "cost": 78800},
    # EUR-quoted (Euronext Amsterdam); priced native EUR via Google, fx_rate = EUR->USD. New on 10.09.2026 statement.
    "UMG.AS": {"name": "Universal Music Group", "qty": 6500, "cost": 112421, "currency": "EUR", "fx_rate": 1.1642},
}
ANNABAY_OPTIONS = {
    # WDAY Call JAN28 $150 closed/sold — no longer on 10.09.2026 statement.
    "SOC": {"name": "Call Sable Offshore JAN27 $12.5", "contracts": 100, "cost": 67000, "strike": 12.5, "expiry": "15.01.2027", "market_value": 1450},  # 10.09 statement mark $0.15
}
ANNABAY_FOREIGN = {
    "DBO.TO": {"name": "D-Box Technologies", "qty": 125000, "cost": 73893, "currency": "CAD", "fx_rate": 1.3800},
    "CPH.TO": {"name": "Cipher Pharmaceuticals", "qty": 7500, "cost": 78091, "currency": "CAD", "fx_rate": 1.3800},
    "TGO.TO": {"name": "Terago Inc", "qty": 150000, "cost": 97551, "currency": "CAD", "fx_rate": 1.3800},
    "1970.HK": {"name": "IMAX China Holding", "qty": 13000, "cost": 12782, "currency": "HKD", "fx_rate": 7.840773},
}
# Per 10.09.2026 statement: USD current acct $251'362; EUR current acct 1'089 (= $1'268 @ 1.1642)
ANNABAY_CASH = {"USD": 251362, "EUR": 1268}

# ============== PORTFOLIO 2: SCHWAB 1 ==============
SCHWAB1_HOLDINGS = {
    "BN": {"name": "Brookfield Corp F Class A", "qty": 3000, "cost": 60860},
    "CNR": {"name": "Core Natural Resources", "qty": 1108, "cost": 82985},
    "PNPFF": {"name": "Pinetree Capital Ltd", "qty": 5700, "cost": 47502},
    "SOC": {"name": "Sable Offshore Corp", "qty": 0, "cost": 0},  # Stock position shows dash
    "TAVHY": {"name": "TAV Havalimanlari", "qty": 7000, "cost": 110847},
    "TDW": {"name": "Tidewater Inc", "qty": 0, "cost": 0},  # Stock position shows dash
    "TOITF": {"name": "Topicus.com Inc", "qty": 500, "cost": 25003},
}
SCHWAB1_OPTIONS = {
    "SOC": {"name": "Call Sable Offshore JAN28 $10", "contracts": 50, "cost": 11383, "strike": 10, "expiry": "21.01.2028", "market_value": 17600},
    "TDW": {"name": "Call Tidewater JAN27 $60", "contracts": 100, "cost": 81315, "strike": 60, "expiry": "15.01.2027", "market_value": 126000},
}
SCHWAB1_CASH = {"USD": -129910}  # Margin balance per 25.06.2026 statement

# ============== PORTFOLIO 3: SCHWAB 2 ==============
# Reconciled to Schwab statement 25.06.2026 (T-bill sold, AMZN bought, cash +$302,594)
SCHWAB2_HOLDINGS = {
    "UBER": {"name": "Uber Technologies", "qty": 2500, "cost": 176999},
    "MSFT": {"name": "Microsoft Corp", "qty": 500, "cost": 189050},
    "AMZN": {"name": "Amazon.com Inc", "qty": 700, "cost": 160202},
    "PDD": {"name": "PDD Holdings ADR", "qty": 2000, "cost": 169970},
    "MIAX": {"name": "Miami Intl Holdings Inc", "qty": 3513.8523, "cost": 143105},
    "KSPI": {"name": "Kaspi KZ JSC", "qty": 1500, "cost": 122000},
    "AMR": {"name": "Alpha Metallurgical Resources", "qty": 750, "cost": 131999},
    "CNR": {"name": "Core Natural Resources", "qty": 1500, "cost": 125165},
    "TAVHY": {"name": "TAV Havalimanlari", "qty": 5000, "cost": 112227},
    "TOITF": {"name": "Topicus.com Inc", "qty": 1500, "cost": 104229},
}
SCHWAB2_TBILLS = {}  # 912797TF4 sold / matured; no fixed income on 25.06.2026 statement
SCHWAB2_CASH = {"USD": 302594}  # Cash & money market per 25.06.2026 statement

# ============== PORTFOLIO 4: MORGAN STANLEY ==============
MS_HOLDINGS = {
    "MSFT": {"name": "Microsoft Corp", "qty": 500, "cost": 78555},
    "AMZN": {"name": "Amazon.com Inc", "qty": 700, "cost": 76510},
    "VAL": {"name": "Valaris Ltd", "qty": 1800, "cost": 55800},
    "NE": {"name": "Noble Corp", "qty": 3000, "cost": 59190},
    "SNAP": {"name": "Snap Inc", "qty": 20000, "cost": 99230},
    "LMGIF": {"name": "Lumine Group Inc", "qty": 1501, "cost": 21888},
    "AAL": {"name": "American Airlines", "qty": 2, "cost": 36},
}
# Note: PSTH and ESC Pershing Square are not publicly traded
MS_CASH = {"USD": 2135}

# All portfolios config
PORTFOLIOS = {
    "annabay": {
        "name": "Annabay",
        "holdings": ANNABAY_HOLDINGS,
        "options": ANNABAY_OPTIONS,
        "foreign": ANNABAY_FOREIGN,
        "tbills": {},
        "cash": ANNABAY_CASH,
    },
    "schwab1": {
        "name": "Schwab 1",
        "holdings": SCHWAB1_HOLDINGS,
        "options": SCHWAB1_OPTIONS,
        "foreign": {},
        "tbills": {},
        "cash": SCHWAB1_CASH,
    },
    "schwab2": {
        "name": "Schwab 2",
        "holdings": SCHWAB2_HOLDINGS,
        "options": {},
        "foreign": {},
        "tbills": SCHWAB2_TBILLS,
        "cash": SCHWAB2_CASH,
    },
    "morgan": {
        "name": "Morgan Stanley",
        "holdings": MS_HOLDINGS,
        "options": {},
        "foreign": {},
        "tbills": {},
        "cash": MS_CASH,
    },
}

def _google_quote(gticker, exchange):
    """Scrape one Google Finance quote page -> price dict (local currency), or None."""
    url = f"https://www.google.com/finance/quote/{gticker}:{exchange}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
            m = _RE_PRICE.search(html)
            if not m:
                raise ValueError("price not found")
            price = float(re.sub(r"[^0-9.]", "", m.group(1)))
            tail = html[m.end():m.end() + 600]
            pm = _RE_PCT.search(tail)
            am = _RE_AMT.search(tail)
            day_change_pct = float(pm.group(1)) if pm else 0.0
            if am:
                day_change = float(am.group(1).replace(",", ""))
            elif pm:
                day_change = price - price / (1 + day_change_pct / 100) if day_change_pct else 0.0
            else:
                day_change = 0.0
            return {"price": price, "prev_close": price - day_change,
                    "day_change": day_change, "day_change_pct": day_change_pct}
        except Exception as e:
            if attempt == 2:
                print(f"Google fetch failed for {gticker}:{exchange}: {e}")
            time.sleep(0.5)
    return None


def fetch_price_google(symbol):
    """Google Finance price for a portfolio symbol (local currency — same as Yahoo
    gave — so downstream fx logic is unchanged)."""
    entry = GF_MAP.get(symbol)
    return _google_quote(*entry) if entry else None


def fetch_price_yahoo(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta["regularMarketPrice"]
            # Get yesterday's close from the actual chart data (second to last value)
            closes = result["indicators"]["quote"][0].get("close", [])
            prev_close = None
            if len(closes) >= 2:
                # Find the most recent non-null close before today
                for c in reversed(closes[:-1]):
                    if c is not None:
                        prev_close = c
                        break
            if prev_close is None:
                prev_close = meta.get("chartPreviousClose", price)
            day_change = price - prev_close
            day_change_pct = (day_change / prev_close * 100) if prev_close else 0
            return {"price": price, "prev_close": prev_close, "day_change": day_change, "day_change_pct": day_change_pct}
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def fetch_all_prices():
    prices = {}
    all_symbols = set()
    for p in PORTFOLIOS.values():
        all_symbols.update(p["holdings"].keys())
        all_symbols.update(p["options"].keys())
        all_symbols.update(p["foreign"].keys())

    wanted = [s for s in all_symbols if not s.startswith("91279")]  # skip T-bills

    # Primary source: Google Finance (fresh prices from the cloud). Fetch the
    # mapped symbols AND the day-% proxy listings (e.g. PSHZF) concurrently in one
    # batch — fetching a proxy on its own *after* the batch gets throttled by
    # Google on Render, so it must ride along with the rest.
    google_syms = [s for s in wanted if s in GF_MAP]
    proxies = {sym: (gt, exch) for sym, (gt, exch) in DAYPCT_PROXY.items()}  # sym -> (gt,exch)
    proxy_out = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        gfuts = {s: pool.submit(fetch_price_google, s) for s in google_syms}
        pfuts = {sym: pool.submit(_google_quote, gt, exch) for sym, (gt, exch) in proxies.items()}
        for s, f in gfuts.items():
            d = f.result()
            if d:
                prices[s] = d
        for sym, f in pfuts.items():
            proxy_out[sym] = f.result()

    # Fallback source: Yahoo, for anything Google doesn't cover (e.g. PSH.AS) or
    # that momentarily failed. Yahoo may be stale on Render but keeps the holding
    # present with an approximately-correct value.
    for symbol in wanted:
        if symbol in prices:
            continue
        data = fetch_price_yahoo(symbol)
        if data:
            prices[symbol] = data

    # Overlay the fresh proxy day-change % onto the Yahoo-priced holding — keeps
    # the (EUR) price, fixes the 0.00%.
    for symbol, proxy in proxy_out.items():
        if symbol in prices and proxy:
            price = prices[symbol]["price"]
            pct = proxy["day_change_pct"]
            dc = price * pct / 100.0
            prices[symbol].update(day_change_pct=pct, day_change=dc, prev_close=price - dc)
            print(f"  proxy {symbol}: day% {pct:+.2f} from {proxies[symbol][0]}", flush=True)
        elif symbol in prices:
            print(f"  proxy {symbol}: FAILED (kept Yahoo day%)", flush=True)

    print(f"fetched {len(prices)} symbols", flush=True)
    return prices

def calc_option_value(underlying_price, strike, expiry_str, contracts):
    intrinsic_per_share = max(0, underlying_price - strike)
    intrinsic_value = intrinsic_per_share * 100 * contracts

    expiry_parts = expiry_str.split(".")
    expiry_date = datetime(int(expiry_parts[2]), int(expiry_parts[1]), int(expiry_parts[0]))
    days_to_expiry = (expiry_date - datetime.now()).days

    if days_to_expiry > 365:
        moneyness = underlying_price / strike
        if moneyness < 0.7:
            time_value_per_share = strike * 0.05
        elif moneyness < 0.9:
            time_value_per_share = strike * 0.12
        elif moneyness < 1.1:
            time_value_per_share = strike * 0.20
        else:
            time_value_per_share = strike * 0.15
    elif days_to_expiry > 180:
        moneyness = underlying_price / strike
        if moneyness < 0.8:
            time_value_per_share = strike * 0.03
        elif moneyness < 1.0:
            time_value_per_share = strike * 0.08
        else:
            time_value_per_share = strike * 0.10
    else:
        time_value_per_share = strike * 0.02 if intrinsic_per_share > 0 else strike * 0.01

    time_value = time_value_per_share * 100 * contracts
    est_value = intrinsic_value + time_value

    if intrinsic_per_share > 0:
        delta = min(0.85, 0.5 + (intrinsic_per_share / strike) * 0.5)
    else:
        delta = max(0.15, 0.5 - abs(underlying_price - strike) / strike * 0.5)

    return est_value, delta

def generate_portfolio_html(portfolio_id, portfolio, prices):
    stock_rows = []
    total_stock_cost = 0
    total_stock_value = 0
    total_day_gain = 0

    # Regular holdings
    for symbol, data in portfolio["holdings"].items():
        if data["qty"] == 0:
            continue
        price_data = prices.get(symbol)
        if not price_data:
            continue

        current_price = price_data["price"]
        day_change = price_data["day_change"]
        day_change_pct = price_data["day_change_pct"]

        currency_symbol = "$"
        if data.get("currency") == "EUR":
            currency_symbol = "€"
            current_value = (data["qty"] * current_price) * data.get("fx_rate", 1)
            day_gain = (data["qty"] * day_change) * data.get("fx_rate", 1)
        else:
            current_value = data["qty"] * current_price
            day_gain = data["qty"] * day_change

        gain_loss = current_value - data["cost"]
        return_pct = (gain_loss / data["cost"]) * 100 if data["cost"] > 0 else 0

        total_stock_cost += data["cost"]
        total_stock_value += current_value
        total_day_gain += day_gain

        gain_class = "positive" if gain_loss >= 0 else "negative"
        gain_sign = "+" if gain_loss >= 0 else ""
        day_class = "positive" if day_change >= 0 else "negative"
        day_sign = "+" if day_change >= 0 else ""

        stock_rows.append(f"""<tr>
            <td class="ticker">{symbol}</td>
            <td>{data["name"]}</td>
            <td class="number">{data["qty"]:,}</td>
            <td class="number">${data["cost"]:,}</td>
            <td class="number">{currency_symbol}{current_price:,.2f}</td>
            <td class="number {day_class}">{day_sign}{day_change_pct:.2f}%</td>
            <td class="number">${current_value:,.0f}</td>
            <td class="number {day_class}">{day_sign}${abs(day_gain):,.0f}</td>
            <td class="number {gain_class}">{gain_sign}${gain_loss:,.0f}</td>
            <td class="{gain_class} percent">{gain_sign}{return_pct:.2f}%</td>
        </tr>""")

    # Foreign holdings
    for symbol, data in portfolio.get("foreign", {}).items():
        price_data = prices.get(symbol)
        if not price_data:
            continue

        current_price = price_data["price"]
        day_change = price_data["day_change"]
        day_change_pct = price_data["day_change_pct"]

        current_value_usd = (data["qty"] * current_price) / data["fx_rate"]
        day_gain_usd = (data["qty"] * day_change) / data["fx_rate"]
        gain_loss = current_value_usd - data["cost"]
        return_pct = (gain_loss / data["cost"]) * 100 if data["cost"] > 0 else 0

        total_stock_cost += data["cost"]
        total_stock_value += current_value_usd
        total_day_gain += day_gain_usd

        gain_class = "positive" if gain_loss >= 0 else "negative"
        gain_sign = "+" if gain_loss >= 0 else ""
        day_class = "positive" if day_change >= 0 else "negative"
        day_sign = "+" if day_change >= 0 else ""

        currency_symbol = "C$" if data["currency"] == "CAD" else "HK$"

        stock_rows.append(f"""<tr>
            <td class="ticker">{symbol}</td>
            <td>{data["name"]}</td>
            <td class="number">{data["qty"]:,}</td>
            <td class="number">${data["cost"]:,}</td>
            <td class="number">{currency_symbol}{current_price:.2f}</td>
            <td class="number {day_class}">{day_sign}{day_change_pct:.2f}%</td>
            <td class="number">${current_value_usd:,.0f}</td>
            <td class="number {day_class}">{day_sign}${abs(day_gain_usd):,.0f}</td>
            <td class="number {gain_class}">{gain_sign}${gain_loss:,.0f}</td>
            <td class="{gain_class} percent">{gain_sign}{return_pct:.2f}%</td>
        </tr>""")

    # Options
    option_rows = []
    total_option_cost = 0
    total_option_value = 0
    total_option_day_gain = 0

    for symbol, data in portfolio.get("options", {}).items():
        price_data = prices.get(symbol)
        if not price_data:
            continue

        underlying_price = price_data["price"]
        underlying_day_change = price_data["day_change"]

        est_value, delta = calc_option_value(underlying_price, data["strike"], data["expiry"], data["contracts"])
        # Prefer the actual Schwab option market value when provided (the heuristic
        # can't match live option premiums); keep delta only for the day-change estimate.
        if data.get("market_value") is not None:
            est_value = data["market_value"]
        option_day_gain = underlying_day_change * delta * 100 * data["contracts"]

        gain_loss = est_value - data["cost"]
        return_pct = (gain_loss / data["cost"]) * 100 if data["cost"] > 0 else 0

        total_option_cost += data["cost"]
        total_option_value += est_value
        total_option_day_gain += option_day_gain

        gain_class = "positive" if gain_loss >= 0 else "negative"
        gain_sign = "+" if gain_loss >= 0 else ""
        day_class = "positive" if option_day_gain >= 0 else "negative"
        day_sign = "+" if option_day_gain >= 0 else ""

        itm_otm = "ITM" if underlying_price > data["strike"] else "OTM"

        option_rows.append(f"""<tr>
            <td class="ticker">{symbol}</td>
            <td>{data["name"]}</td>
            <td class="number">{data["contracts"]}</td>
            <td class="number">${data["cost"]:,}</td>
            <td class="number">${underlying_price:.2f} ({itm_otm})</td>
            <td class="number {day_class}">{day_sign}${abs(option_day_gain):,.0f}</td>
            <td class="number">${est_value:,.0f}</td>
            <td class="number {gain_class}">{gain_sign}${gain_loss:,.0f}</td>
            <td class="{gain_class} percent">{gain_sign}{return_pct:.2f}%</td>
        </tr>""")

    # T-Bills
    tbill_rows = []
    total_tbill_value = 0
    for symbol, data in portfolio.get("tbills", {}).items():
        # T-bills trade near par, assume ~$100 per $100 face
        current_value = data["qty"] * 0.998  # Slight discount
        total_tbill_value += current_value
        gain_loss = current_value - data["cost"]
        return_pct = (gain_loss / data["cost"]) * 100 if data["cost"] > 0 else 0
        gain_class = "positive" if gain_loss >= 0 else "negative"
        gain_sign = "+" if gain_loss >= 0 else ""

        tbill_rows.append(f"""<tr>
            <td class="ticker">{symbol}</td>
            <td>{data["name"]}</td>
            <td class="number">{data["qty"]:,}</td>
            <td class="number">${data["cost"]:,}</td>
            <td class="number">${current_value:,.0f}</td>
            <td class="number {gain_class}">{gain_sign}${gain_loss:,.0f}</td>
            <td class="{gain_class} percent">{gain_sign}{return_pct:.2f}%</td>
        </tr>""")

    # Totals
    total_cash = sum(portfolio["cash"].values())
    stock_gain = total_stock_value - total_stock_cost
    option_gain = total_option_value - total_option_cost
    total_investment = total_stock_cost + total_option_cost
    total_value = total_stock_value + total_option_value + total_tbill_value + total_cash
    total_day = total_day_gain + total_option_day_gain
    net_gain = stock_gain + option_gain
    net_return = (net_gain / total_investment * 100) if total_investment > 0 else 0

    day_class = "positive" if total_day >= 0 else "negative"
    gain_class = "positive" if net_gain >= 0 else "negative"
    stock_gain_class = "positive" if stock_gain >= 0 else "negative"

    # Build HTML sections
    stocks_table = ""
    if stock_rows:
        stock_return_pct = (stock_gain / total_stock_cost * 100) if total_stock_cost > 0 else 0
        stocks_table = f"""
        <h3 class="section-title">Equities</h3>
        <div class="table-container">
        <table class="sortable">
            <thead><tr>
                <th class="sortable" data-type="string">Symbol</th><th class="sortable" data-type="string">Name</th><th class="sortable" data-type="number">Qty</th><th class="sortable" data-type="number">Cost</th><th class="sortable" data-type="number">Price</th><th class="sortable" data-type="number">Day %</th><th class="sortable" data-type="number">Value</th><th class="sortable" data-type="number">Day $</th><th class="sortable" data-type="number">Gain/Loss</th><th class="sortable" data-type="number">Return</th>
            </tr></thead>
            <tbody>{''.join(stock_rows)}</tbody>
            <tfoot><tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                <td colspan="3">Total Equities</td>
                <td class="number">${total_stock_cost:,}</td>
                <td colspan="2"></td>
                <td class="number">${total_stock_value:,.0f}</td>
                <td class="number {day_class}">{'+' if total_day_gain >= 0 else ''}${total_day_gain:,.0f}</td>
                <td class="number {stock_gain_class}">{'+' if stock_gain >= 0 else ''}${stock_gain:,.0f}</td>
                <td class="{stock_gain_class} percent">{'+' if stock_return_pct >= 0 else ''}{stock_return_pct:.2f}%</td>
            </tr></tfoot>
        </table>
        </div>"""

    options_table = ""
    if option_rows:
        option_gain_class = "positive" if option_gain >= 0 else "negative"
        options_table = f"""
        <h3 class="section-title">Options</h3>
        <div class="table-container">
        <table class="sortable">
            <thead><tr>
                <th class="sortable" data-type="string">Symbol</th><th class="sortable" data-type="string">Description</th><th class="sortable" data-type="number">Contracts</th><th class="sortable" data-type="number">Cost</th><th class="sortable" data-type="number">Underlying</th><th class="sortable" data-type="number">Day $</th><th class="sortable" data-type="number">Est Value</th><th class="sortable" data-type="number">Gain/Loss</th><th class="sortable" data-type="number">Return</th>
            </tr></thead>
            <tbody>{''.join(option_rows)}</tbody>
            <tfoot><tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                <td colspan="3">Total Options</td>
                <td class="number">${total_option_cost:,}</td>
                <td colspan="2"></td>
                <td class="number">${total_option_value:,.0f}</td>
                <td class="number {option_gain_class}">{'+' if option_gain >= 0 else ''}${option_gain:,.0f}</td>
                <td></td>
            </tr></tfoot>
        </table>
        </div>"""

    tbills_table = ""
    if tbill_rows:
        tbills_table = f"""
        <h3 class="section-title">Fixed Income</h3>
        <div class="table-container">
        <table>
            <thead><tr>
                <th>Symbol</th><th>Name</th><th>Face Value</th><th>Cost</th><th>Value</th><th>Gain/Loss</th><th>Return</th>
            </tr></thead>
            <tbody>{''.join(tbill_rows)}</tbody>
            <tfoot><tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                <td colspan="4">Total Fixed Income</td>
                <td class="number">${total_tbill_value:,.0f}</td>
                <td colspan="2"></td>
            </tr></tfoot>
        </table>
        </div>"""

    cash_section = f"""
        <h3 class="section-title">Cash</h3>
        <table style="max-width: 400px;">
            <thead><tr><th>Currency</th><th>Amount</th></tr></thead>
            <tbody>"""
    for curr, amt in portfolio["cash"].items():
        cash_class = "negative" if amt < 0 else ""
        cash_section += f'<tr><td class="ticker">{curr}</td><td class="number {cash_class}">${amt:,}</td></tr>'
    cash_section += f"""</tbody>
            <tfoot><tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                <td>Total Cash</td><td class="number {'negative' if total_cash < 0 else ''}">${total_cash:,}</td>
            </tr></tfoot>
        </table>"""

    return f"""
    <div class="portfolio-content" id="{portfolio_id}" style="display: none;"
         data-total="{total_value:.0f}" data-day="{total_day:.0f}">
        <div class="summary-cards">
            <div class="card">
                <h3>Total Value</h3>
                <div class="value neutral number">${total_value:,.0f}</div>
            </div>
            <div class="card">
                <h3>Today's Change</h3>
                <div class="value {day_class} number">{'+' if total_day >= 0 else ''}${total_day:,.0f}</div>
            </div>
            <div class="card">
                <h3>Total Cost</h3>
                <div class="value neutral number">${total_investment:,}</div>
            </div>
            <div class="card">
                <h3>Total Gain/Loss</h3>
                <div class="value {gain_class} number">{'+' if net_gain >= 0 else ''}${net_gain:,.0f}</div>
            </div>
            <div class="card">
                <h3>Total Return</h3>
                <div class="value {gain_class} number">{'+' if net_return >= 0 else ''}{net_return:.2f}%</div>
            </div>
        </div>
        {stocks_table}
        {options_table}
        {tbills_table}
        {cash_section}
    </div>"""

def generate_html(prices):
    # Use Eastern time for display
    from datetime import timezone, timedelta
    eastern = timezone(timedelta(hours=-4))  # EDT (summer)
    now_et = datetime.now(eastern)
    today = now_et.strftime("%B %d, %Y")
    update_time = now_et.strftime("%I:%M %p")

    # Generate tab buttons
    tabs_html = ""
    for pid, p in PORTFOLIOS.items():
        tabs_html += f'<button class="tab-btn" data-portfolio="{pid}">{p["name"]}</button>'

    # Generate all portfolio contents
    portfolios_html = ""
    for pid, p in PORTFOLIOS.items():
        portfolios_html += generate_portfolio_html(pid, p, prices)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portfolio Analysis</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 20px;
            color: #e0e0e0;
        }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        h1 {{ text-align: center; color: #00d4ff; margin-bottom: 10px; font-size: 2.2em; }}
        .header-row {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 20px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .update-time {{ color: #00ff88; font-size: 0.9em; }}
        .update-btn {{
            background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
            border: none;
            color: #1a1a2e;
            padding: 10px 25px;
            font-size: 0.9em;
            font-weight: bold;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        .update-btn:hover {{ transform: scale(1.05); box-shadow: 0 0 15px rgba(0, 212, 255, 0.5); }}

        .portfolio-header {{
            text-align: center;
            margin-bottom: 20px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
        }}
        .portfolio-header .label {{ color: #888; font-size: 0.9em; }}
        .portfolio-header .amount {{ font-size: 2em; color: #00d4ff; font-weight: bold; font-family: 'SF Mono', Monaco, monospace; }}
        .portfolio-header .day-change {{ font-size: 1em; margin-left: 15px; }}

        .tabs {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-bottom: 25px;
            flex-wrap: wrap;
        }}
        .tab-btn {{
            background: rgba(255,255,255,0.05);
            border: 2px solid rgba(0,212,255,0.3);
            color: #e0e0e0;
            padding: 12px 30px;
            font-size: 1em;
            font-weight: 600;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        .tab-btn:hover {{ background: rgba(0,212,255,0.1); border-color: #00d4ff; }}
        .tab-btn.active {{
            background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
            color: #1a1a2e;
            border-color: #00d4ff;
        }}

        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }}
        .card {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .card h3 {{ color: #888; font-size: 0.8em; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }}
        .card .value {{ font-size: 1.5em; font-weight: bold; }}
        .card .value.positive {{ color: #00ff88; }}
        .card .value.negative {{ color: #ff4757; }}
        .card .value.neutral {{ color: #00d4ff; }}

        .section-title {{
            color: #00d4ff;
            margin: 25px 0 12px 0;
            font-size: 1.2em;
            border-bottom: 2px solid rgba(0,212,255,0.3);
            padding-bottom: 8px;
        }}
        .table-container {{ overflow-x: auto; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.03);
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        th, td {{ padding: 10px 8px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.05); }}
        th {{
            background: rgba(0,212,255,0.1);
            color: #00d4ff;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.7em;
            white-space: nowrap;
        }}
        tr:hover {{ background: rgba(255,255,255,0.05); }}
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff4757; }}
        .ticker {{ font-weight: bold; color: #00d4ff; }}
        .number {{ font-family: 'SF Mono', Monaco, Consolas, monospace; font-size: 0.85em; }}
        .percent {{ font-size: 0.8em; }}

        th.sortable {{ cursor: pointer; user-select: none; }}
        th.sortable:hover {{ background: rgba(0,212,255,0.2); }}
        th.sortable::after {{ content: ' ⇅'; opacity: 0.3; font-size: 0.8em; }}
        th.sortable.asc::after {{ content: ' ↑'; opacity: 1; }}
        th.sortable.desc::after {{ content: ' ↓'; opacity: 1; }}

        .date-info {{ text-align: center; color: #666; font-size: 0.85em; margin-top: 25px; }}

        @media (max-width: 768px) {{
            th, td {{ padding: 6px 4px; font-size: 0.7em; }}
            h1 {{ font-size: 1.6em; }}
            .tab-btn {{ padding: 8px 15px; font-size: 0.85em; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Portfolio Analysis</h1>
        <div class="header-row">
            <span class="update-time">Last Updated: {today} at {update_time}</span>
            <button class="update-btn" onclick="updatePrices()">Update Prices</button>
        </div>

        <div class="portfolio-header">
            <span class="label">PORTFOLIO VALUE</span><br>
            <span class="amount" id="header-total">$0</span>
            <span class="day-change" id="header-day">$0 today</span>
        </div>

        <div class="tabs">
            {tabs_html}
        </div>

        {portfolios_html}

        <p class="date-info">
            Data from Yahoo Finance. Options estimated using intrinsic + time value.<br>
            Prices updated: {today} at {update_time}
        </p>
    </div>

    <script>
    document.addEventListener('DOMContentLoaded', function() {{
        const tabs = document.querySelectorAll('.tab-btn');
        const contents = document.querySelectorAll('.portfolio-content');

        function formatNumber(num) {{
            return num.toLocaleString('en-US');
        }}

        function showPortfolio(id) {{
            contents.forEach(c => c.style.display = 'none');
            tabs.forEach(t => t.classList.remove('active'));
            const el = document.getElementById(id);
            el.style.display = 'block';
            document.querySelector('[data-portfolio="' + id + '"]').classList.add('active');

            // Update header with this portfolio's totals
            const total = parseFloat(el.dataset.total);
            const day = parseFloat(el.dataset.day);
            document.getElementById('header-total').textContent = '$' + formatNumber(Math.round(total));
            const dayEl = document.getElementById('header-day');
            const sign = day >= 0 ? '+' : '';
            dayEl.textContent = sign + '$' + formatNumber(Math.round(Math.abs(day))) + ' today';
            dayEl.className = 'day-change ' + (day >= 0 ? 'positive' : 'negative');
        }}

        tabs.forEach(tab => {{
            tab.addEventListener('click', function() {{
                showPortfolio(this.getAttribute('data-portfolio'));
            }});
        }});

        // Show saved tab or first portfolio by default
        const savedTab = localStorage.getItem('activePortfolio') || 'annabay';
        showPortfolio(savedTab);
    }});

    function updatePrices() {{
        const btn = document.querySelector('.update-btn');
        btn.textContent = 'Updating...';
        btn.disabled = true;
        // Save current tab before reload
        const activeTab = document.querySelector('.tab-btn.active');
        if (activeTab) {{
            localStorage.setItem('activePortfolio', activeTab.dataset.portfolio);
        }}
        fetch('/update')
            .then(r => r.text())
            .then(() => location.reload())
            .catch(() => {{
                btn.textContent = 'Update Prices';
                btn.disabled = false;
            }});
    }}

    // Table sorting
    document.querySelectorAll('th.sortable').forEach(th => {{
        th.addEventListener('click', function() {{
            const table = this.closest('table');
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const colIndex = Array.from(this.parentNode.children).indexOf(this);
            const type = this.dataset.type;
            const isAsc = this.classList.contains('asc');

            // Clear other sort indicators in this table
            this.parentNode.querySelectorAll('th').forEach(h => h.classList.remove('asc', 'desc'));

            // Set new sort direction
            this.classList.add(isAsc ? 'desc' : 'asc');

            rows.sort((a, b) => {{
                let aVal = a.children[colIndex].textContent.trim();
                let bVal = b.children[colIndex].textContent.trim();

                if (type === 'number') {{
                    // Extract numbers, handling $, %, +, -, commas
                    aVal = parseFloat(aVal.replace(/[$,%+,]/g, '')) || 0;
                    bVal = parseFloat(bVal.replace(/[$,%+,]/g, '')) || 0;
                    return isAsc ? bVal - aVal : aVal - bVal;
                }} else {{
                    return isAsc ? bVal.localeCompare(aVal) : aVal.localeCompare(bVal);
                }}
            }});

            rows.forEach(row => tbody.appendChild(row));
        }});
    }});
    </script>
</body>
</html>"""
    return html


# --- Price cache + background refresh -------------------------------------
# Refreshing on every request is slow (26 page fetches) and hammers the source.
# Cache the rendered HTML and refresh in the background, at most once per TTL.
REFRESH_TTL = 60  # seconds
_cache = {"html": None, "ts": 0.0}
_refresh_lock = threading.Lock()


def refresh_prices():
    if not _refresh_lock.acquire(blocking=False):
        return  # a refresh is already running
    try:
        prices = fetch_all_prices()
        if prices:
            _cache["html"] = generate_html(prices)
            _cache["ts"] = time.time()
    finally:
        _refresh_lock.release()


def maybe_refresh(force=False):
    if force or _cache["html"] is None or (time.time() - _cache["ts"]) > REFRESH_TTL:
        threading.Thread(target=refresh_prices, daemon=True).start()


class PortfolioHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/', '', '/update'):
            if _cache["html"] is None:
                refresh_prices()            # first visitor: fetch synchronously
            else:
                maybe_refresh(force=self.path == '/update')

            if self.path == '/update':
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'OK')
            else:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write((_cache["html"] or "Loading prices, refresh in a moment...").encode())
        elif self.path == '/healthz':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format%args}")


if __name__ == '__main__':
    print(f"Starting portfolio server on port {PORT}...")
    # Bind the port first so Render marks the deploy live immediately, then warm
    # the price cache in the background (the 26 page fetches take a few seconds).
    server = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), PortfolioHandler)
    print(f"Server running on http://0.0.0.0:{PORT}")
    threading.Thread(target=refresh_prices, daemon=True).start()
    server.serve_forever()
