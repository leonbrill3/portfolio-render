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
    "WDAY": ("WDAY", "NASDAQ"), "META": ("META", "NASDAQ"), "RDI": ("RDI", "NASDAQ"),
    "METC": ("METC", "NASDAQ"),
    "AMR": ("AMR", "NYSE"), "BN": ("BN", "NYSE"), "CNR": ("CNR", "NYSE"),
    "MIAX": ("MIAX", "NYSE"), "NE": ("NE", "NYSE"), "RIG": ("RIG", "NYSE"),
    "SNAP": ("SNAP", "NYSE"), "SOC": ("SOC", "NYSE"), "TDW": ("TDW", "NYSE"),
    "TPB": ("TPB", "NYSE"),
    "TME": ("TME", "NYSE"), "UBER": ("UBER", "NYSE"), "VAL": ("VAL", "NYSE"),
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
    "MIAX": {"name": "Miami International Holdings", "qty": 4500, "cost": 165000},  # bought +2000 @ $30 (2026-10-12), was 2500 @ 105000
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
# 2026-10-12: bought 2000 MIAX @ $30 = -$60'000 USD -> 251362 - 60000 = 191362
ANNABAY_CASH = {"USD": 191362, "EUR": 1268}

# ============== PORTFOLIO 2: SCHWAB 1 ==============
# Reconciled to Schwab Positions 10.12.2026 (Total cost basis $361,404.03, MV $666,744.65).
SCHWAB1_HOLDINGS = {
    "BN": {"name": "Brookfield Corp F Class A", "qty": 3000, "cost": 60860},
    "CNR": {"name": "Core Natural Resources", "qty": 999, "cost": 71996},  # was 1108 @ 82985
    # PNPFF (Pinetree) no longer held per 10.12.2026.
    "SOC": {"name": "Sable Offshore Corp", "qty": 0, "cost": 0},  # Stock position shows dash
    "TAVHY": {"name": "TAV Havalimanlari", "qty": 7000, "cost": 110847},
    "TDW": {"name": "Tidewater Inc", "qty": 0, "cost": 0},  # Stock position shows dash
    "TOITF": {"name": "Topicus.com Inc", "qty": 500, "cost": 25003},
}
SCHWAB1_OPTIONS = {
    "SOC": {"name": "Call Sable Offshore JAN28 $10", "contracts": 50, "cost": 11383, "strike": 10, "expiry": "21.01.2028", "market_value": 2775},  # 10.12 mark $0.555
    "TDW": {"name": "Call Tidewater JAN27 $60", "contracts": 100, "cost": 81315, "strike": 60, "expiry": "15.01.2027", "market_value": 273500},  # 10.12 mark $27.35
}
SCHWAB1_CASH = {"USD": -124741}  # Cash & Cash Investments (margin) per 10.12.2026 Positions

# ============== PORTFOLIO 3: SCHWAB 2 ==============
# Reconciled to Schwab Positions 10.12.2026. Cost bases tie to Schwab Total cost basis $2,281,090.90.
SCHWAB2_HOLDINGS = {
    "UBER": {"name": "Uber Technologies", "qty": 3500, "cost": 243042},
    "MSFT": {"name": "Microsoft Corp", "qty": 500, "cost": 186335},
    "AMR": {"name": "Alpha Metallurgical Resources", "qty": 1250, "cost": 209904},  # was 1000 @ 166129
    "CNR": {"name": "Core Natural Resources", "qty": 2000, "cost": 164540},
    "META": {"name": "Meta Platforms Inc", "qty": 300, "cost": 164700},
    "AMZN": {"name": "Amazon.com Inc", "qty": 700, "cost": 160202},
    "PDD": {"name": "PDD Holdings ADR", "qty": 2000, "cost": 169970},
    "MIAX": {"name": "Miami Intl Holdings Inc", "qty": 6000.0023, "cost": 235530},  # was 3513.8523 @ 143105
    "KSPI": {"name": "Kaspi KZ JSC", "qty": 1500, "cost": 122000},
    "TPB": {"name": "Turning Point Brands Inc", "qty": 2500, "cost": 161020},  # new on 10.12.2026 Positions
    "TOITF": {"name": "Topicus.com Inc", "qty": 2000, "cost": 136486},
    "TAVHY": {"name": "TAV Havalimanlari", "qty": 5000, "cost": 112227},
    "TME": {"name": "Tencent Music Entmt", "qty": 10000, "cost": 88850},
    "RDI": {"name": "Reading Intl Class A", "qty": 10051, "cost": 17187},
    # METC (Ramaco) stock line shows 0 shares / dash — held only via the call below.
}
SCHWAB2_OPTIONS = {
    "METC": {"name": "Call Ramaco Res JAN28 $8", "contracts": 300, "cost": 109099, "strike": 8, "expiry": "21.01.2028", "market_value": 101250},  # 10.12 mark $3.375 (was 75 ct @ 32300)
}
SCHWAB2_TBILLS = {}  # No fixed income
SCHWAB2_CASH = {"USD": -914895}  # Cash & Cash Investments (margin) per 10.12.2026 Positions

# ============== PORTFOLIO 4: MORGAN STANLEY ==============
# Reconciled to Morgan Stanley holdings 10.09.2026 (Total Cost $392,120.58, MV $846,706.98)
MS_HOLDINGS = {
    "MSFT": {"name": "Microsoft Corp", "qty": 500, "cost": 78555},
    "AMZN": {"name": "Amazon.com Inc", "qty": 800, "cost": 99310},  # was 700 @ 76510
    "VAL": {"name": "Valaris Ltd", "qty": 1800, "cost": 55800},
    "NE": {"name": "Noble Corp", "qty": 3000, "cost": 59190},
    "SNAP": {"name": "Snap Inc", "qty": 20000, "cost": 99230},
    "AAL": {"name": "American Airlines", "qty": 2, "cost": 36},
    # Lumine Group (LMGIF) no longer held per 10.09.2026.
}
# Note: PSTH and ESC Pershing Square are not publicly traded
MS_CASH = {"USD": 3757}  # Cash/MMF/BDP total $3,756.69 per 10.09.2026

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
        "options": SCHWAB2_OPTIONS,
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
            <a href="/tax" class="update-btn" style="text-decoration:none;">Tax Planner</a>
            <a href="/str" class="update-btn" style="text-decoration:none;">RE Shelter</a>
            <a href="/markets" class="update-btn" style="text-decoration:none;">STR Markets</a>
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


# --- Family Tax Planner page ----------------------------------------------
# Self-contained interactive page at /tax. All defaults are the reconciled
# 2026 numbers; edit them here (like the holdings above) when statements
# change, or tweak live in the browser for what-if planning.
def generate_tax_html():
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Family Tax Planner 2026</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%); min-height:100vh; padding:20px; color:#e0e0e0; }
.container { max-width:1500px; margin:0 auto; }
h1 { text-align:center; color:#00d4ff; margin-bottom:6px; font-size:2em; }
.sub { text-align:center; color:#888; font-size:.85em; margin-bottom:18px; }
a.back { color:#00d4ff; text-decoration:none; font-size:.9em; }
.levers { background:rgba(255,255,255,.05); border:1px solid rgba(0,212,255,.3); border-radius:12px; padding:18px; margin-bottom:18px; }
.levers h2 { color:#00d4ff; font-size:1em; text-transform:uppercase; letter-spacing:1px; margin-bottom:14px; }
.lever { margin-bottom:14px; }
.lever label { display:block; font-size:.85em; color:#bbb; margin-bottom:4px; }
.lever .val { color:#00ff88; font-weight:bold; font-family:'SF Mono',Monaco,monospace; }
input[type=range] { width:100%; accent-color:#00d4ff; }
input[type=number] { background:rgba(255,255,255,.08); border:1px solid rgba(0,212,255,.3); color:#e0e0e0;
  border-radius:6px; padding:5px 8px; width:120px; font-family:'SF Mono',Monaco,monospace; font-size:.85em; }
.toggles { display:flex; gap:24px; flex-wrap:wrap; margin-top:6px; }
.toggles label { font-size:.85em; color:#bbb; cursor:pointer; }
.family { background:linear-gradient(135deg,#00d4ff22,#0099cc22); border:2px solid #00d4ff; border-radius:12px;
  padding:18px; margin-bottom:20px; text-align:center; }
.family .big { font-size:2.4em; color:#00d4ff; font-weight:bold; font-family:'SF Mono',Monaco,monospace; }
.family .saved { color:#00ff88; font-size:1em; margin-top:6px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:16px; }
.panel { background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1); border-radius:12px; padding:18px; }
.panel h2 { color:#00d4ff; font-size:1.1em; margin-bottom:4px; }
.panel .owe { font-size:1.8em; font-weight:bold; font-family:'SF Mono',Monaco,monospace; margin-bottom:12px; }
.row { display:flex; justify-content:space-between; align-items:center; padding:3px 0; font-size:.85em; }
.row label { color:#aaa; }
.grp { color:#00d4ff; font-size:.72em; text-transform:uppercase; letter-spacing:1px; margin:12px 0 4px; border-bottom:1px solid rgba(0,212,255,.2); padding-bottom:3px; }
.out { border-top:1px dashed rgba(255,255,255,.15); margin-top:10px; padding-top:8px; }
.out .row { font-family:'SF Mono',Monaco,monospace; }
.pos { color:#00ff88; } .neg { color:#ff4757; } .mut { color:#888; font-size:.78em; }
.note { font-size:.78em; color:#e0b000; margin-top:8px; }
.warn { background:rgba(255,71,87,.12); border:1px solid #ff4757; border-radius:8px; padding:10px; margin-top:12px; font-size:.82em; }
</style>
</head>
<body>
<div class="container">
<div style="text-align:left;margin-bottom:8px;"><a class="back" href="/">&larr; Portfolio</a> &nbsp;|&nbsp; <a class="back" href="/str">RE Shelter Planner</a> &nbsp;|&nbsp; <a class="back" href="/markets">STR Markets</a></div>
<h1>Family Tax Planner &mdash; 2026</h1>
<div class="sub">Planning estimate (2025 brackets). Not a filed return. Pabrai figures are an estimate until the 2026 K-1 arrives.</div>

<div class="levers">
<h2>Master Levers</h2>
<div class="lever">
  <label>Trustee fee (Trust &rarr; Leon): <span class="val" id="feeV"></span></label>
  <input type="range" id="feeR" min="0" max="400000" step="1000" oninput="document.getElementById('fee').value=this.value;calc()">
  <input type="number" id="fee" value="168300" oninput="document.getElementById('feeR').value=this.value;calc()">
</div>
<div class="toggles">
  <label><input type="checkbox" id="seTax" onchange="calc()"> Trustee fee is self-employment income (+ SE/Medicare tax)</label>
</div>
<div class="mut" style="margin-top:8px;">Gains sent to Josh are set in his panel (short-term / long-term), with live harvesting headroom.</div>
</div>

<div class="family">
  <div class="mut" style="text-transform:uppercase;letter-spacing:1px;">Total Family Federal Tax</div>
  <div class="big" id="famTax">$0</div>
  <div id="famDue" style="color:#e0e0e0;font-size:.95em;margin-top:4px;"></div>
  <div class="saved" id="saved"></div>
</div>

<div class="grid">

<div class="panel">
  <h2>Leon &amp; Lisa <span class="mut">(MFJ)</span></h2>
  <div class="owe" id="llOwe">$0</div>
  <div class="grp">Income</div>
  <div class="row"><label>Lisa wages (W-2)</label><input type="number" id="ll_wages" value="104090" oninput="calc()"></div>
  <div class="row"><label>Leon consulting (LB Ed)</label><input type="number" id="ll_consult" value="0" oninput="calc()"></div>
  <div class="row"><label>Trustee fee (from lever)</label><span id="ll_fee" class="mut"></span></div>
  <div class="row"><label>Personal Schwab ST gain</label><input type="number" id="ll_st" value="34502" oninput="calc()"></div>
  <div class="row"><label>Personal Schwab LT gain</label><input type="number" id="ll_lt" value="0" oninput="calc()"></div>
  <div class="row"><label>Interest / dividends</label><input type="number" id="ll_divint" value="2091" oninput="calc()"></div>
  <div class="row"><label>House sale taxable gain</label><input type="number" id="ll_house" value="0" oninput="calc()"></div>
  <div class="grp">Deduction (uses the larger of standard or itemized)</div>
  <div class="row"><label>Standard deduction (MFJ)</label><input type="number" id="ll_ded" value="31500" oninput="calc()"></div>
  <div class="row"><label>Itemized: mortgage/SALT/charity</label><input type="number" id="ll_item" value="25848" oninput="calc()"></div>
  <div class="row"><label>Personal Schwab margin interest</label><input type="number" id="ll_margin" value="4725" oninput="calc()"></div>
  <div class="mut">Margin interest = investment-interest expense; only helps if itemizing beats the standard deduction.</div>
  <div class="grp">Credits</div>
  <div class="row"><label>Child tax credit (kids under 17)</label><input type="number" id="ll_ctc" value="4000" oninput="calc()"></div>
  <div class="mut">$2,000/child (2024). Phases out over $400k MAGI. 2025 may be $2,200/child.</div>
  <div class="grp">Payments already made</div>
  <div class="row"><label>Lisa withholding (paycheck)</label><input type="number" id="ll_wh" value="12448" oninput="calc()"></div>
  <div class="row"><label>Leon estimated payments made</label><input type="number" id="ll_est" value="0" oninput="calc()"></div>
  <div class="out" id="ll_out"></div>
</div>

<div class="panel">
  <h2>JKL Trust</h2>
  <div class="owe" id="trOwe">$0</div>
  <div class="grp">Income &mdash; own accounts</div>
  <div class="row"><label>Interest (Schwab)</label><input type="number" id="t_int" value="1473" oninput="calc()"></div>
  <div class="row"><label>Dividends (MS)</label><input type="number" id="t_div" value="3910" oninput="calc()"></div>
  <div class="row"><label>Net short-term gain</label><input type="number" id="t_st" value="-2963" oninput="calc()"></div>
  <div class="row"><label>Net long-term gain</label><input type="number" id="t_lt" value="6950" oninput="calc()"></div>
  <div class="row"><label>Loan interest received (Leon/CKS notes)</label><input type="number" id="t_loanint" value="0" oninput="calc()"></div>
  <div class="grp">Income &mdash; Pabrai K-1 (estimate)</div>
  <div class="row"><label>Interest</label><input type="number" id="p_int" value="1334" oninput="calc()"></div>
  <div class="row"><label>Dividends</label><input type="number" id="p_div" value="20359" oninput="calc()"></div>
  <div class="row"><label>Short-term gain</label><input type="number" id="p_st" value="30323" oninput="calc()"></div>
  <div class="row"><label>Long-term gain</label><input type="number" id="p_lt" value="155664" oninput="calc()"></div>
  <div class="grp">Deductions</div>
  <div class="row"><label>Trustee fee (from lever)</label><span id="t_fee" class="mut"></span></div>
  <div class="row"><label>Margin interest</label><input type="number" id="t_margin" value="9276" oninput="calc()"></div>
  <div class="row"><label>Advisory fee</label><input type="number" id="t_adv" value="3490" oninput="calc()"></div>
  <div class="row"><label>Legal (Perlman)</label><input type="number" id="t_legal" value="3501" oninput="calc()"></div>
  <div class="row"><label>Accounting (Perrysimon)</label><input type="number" id="t_acct" value="11000" oninput="calc()"></div>
  <div class="out" id="tr_out"></div>
  <div class="mut" style="margin-top:6px;">CKS car loan $63,333 = asset (not deducted).</div>
</div>

<div class="panel">
  <h2>Joshua Brill <span class="mut">(Single)</span></h2>
  <div class="owe" id="jOwe">$0</div>
  <div class="grp">Received so far (locked)</div>
  <div class="row"><label>Short-term gain received</label><input type="number" id="j_st_r" value="0" oninput="calc()"></div>
  <div class="row"><label>Long-term gain received</label><input type="number" id="j_lt_r" value="21483" oninput="calc()"></div>
  <div class="row" style="color:#00ff88;font-weight:bold;"><label style="color:#00ff88;">Est. tax on amount received (locked)</label><span id="j_tax_r"></span></div>
  <div class="grp">Additional expected (planning)</div>
  <div class="row"><label>More short-term gain</label><input type="number" id="j_st_a" value="0" oninput="calc()"></div>
  <div class="row"><label>More long-term gain</label><input type="number" id="j_lt_a" value="0" oninput="calc()"></div>
  <div class="grp">Other / deduction</div>
  <div class="row"><label>Other income</label><input type="number" id="j_other" value="0" oninput="calc()"></div>
  <div class="row"><label>Itemized (mortgage + SALT)</label><input type="number" id="j_ded" value="34315" oninput="calc()"></div>
  <div class="out" id="j_out"></div>
  <div id="j_headroom" style="background:rgba(0,255,136,.1);border:1px solid #00ff88;border-radius:8px;padding:10px;margin-top:12px;font-size:.82em;line-height:1.5;"></div>
</div>

</div>
<div id="advice"></div>
</div>

<script>
// ---- 2025 brackets (editable constants) ----
var B = {
  mfj:   { ord:[[23850,.10],[96950,.12],[206700,.22],[394600,.24],[501050,.32],[751600,.35],[1e15,.37]],
           cg:[[96700,0],[600050,.15],[1e15,.20]], niit:250000 },
  single:{ ord:[[11925,.10],[48475,.12],[103350,.22],[197300,.24],[250525,.32],[626350,.35],[1e15,.37]],
           cg:[[48350,0],[533400,.15],[1e15,.20]], niit:200000 },
  trust: { ord:[[3150,.10],[11450,.24],[15650,.35],[1e15,.37]],
           cg:[[3250,0],[15900,.15],[1e15,.20]], niit:15650 }
};
function num(id){ return parseFloat(document.getElementById(id).value)||0; }
function money(x){ return (x<0?'-$':'$')+Math.abs(Math.round(x)).toLocaleString('en-US'); }
function bt(x,br){ var t=0,p=0; for(var i=0;i<br.length;i++){ var c=br[i][0],r=br[i][1]; if(x>p){t+=(Math.min(x,c)-p)*r;p=c;} else break; } return t; }
function cgStack(ord,pref,br){ var t=0,p=0,s=ord,e=ord+pref; for(var i=0;i<br.length;i++){ var c=br[i][0],r=br[i][1]; var lo=Math.max(s,p),hi=Math.min(e,c); if(hi>lo)t+=(hi-lo)*r; p=c; if(p>=e)break; } return t; }
function netCap(st,lt){ // -> {stOrd, ltPref, loss}
  if(st>=0&&lt>=0) return {stOrd:st,ltPref:lt,loss:0};
  if(st<0){ var nl=lt+st; return nl>=0?{stOrd:0,ltPref:nl,loss:0}:{stOrd:0,ltPref:0,loss:nl}; }
  var ns=st+lt; return ns>=0?{stOrd:ns,ltPref:0,loss:0}:{stOrd:0,ltPref:0,loss:ns};
}
// generic filer: ordinary (fully-ordinary $), pref (qual div + LT), deduction, brackets, nii
function filer(ordinary,pref,ded,br,nii,se){
  var ordTax0=Math.max(0,ordinary-ded);
  var excess=Math.max(0,ded-ordinary);
  var prefTax0=Math.max(0,pref-excess);
  var taxable=ordTax0+prefTax0;
  var ordTax=bt(ordTax0,br.ord);
  var cgTax=cgStack(ordTax0,prefTax0,br.cg);
  var magi=ordinary+pref;
  var niit=0.038*Math.max(0,Math.min(nii,magi-br.niit));
  return {taxable:taxable, ord:ordTax, cg:cgTax, niit:niit, se:(se||0), tax:ordTax+cgTax+niit+(se||0), ordTax0:ordTax0, prefTax0:prefTax0};
}

function scenario(fee,seOn){
  // ---- TRUST ----
  var trustInt=num('t_int')+num('p_int')+num('t_loanint');
  var trustDiv=num('t_div')+num('p_div');           // treat dividends as qualified (preferential)
  var trustST=num('t_st')+num('p_st');
  var trustLT=num('t_lt')+num('p_lt');
  var trustDed=fee+num('t_margin')+num('t_adv')+num('t_legal')+num('t_acct');
  var cap=netCap(trustST,trustLT);
  var trustOrd=trustInt+cap.stOrd;                  // ordinary-rate income
  var trustPref=trustDiv+cap.ltPref;                // qualified div + LT gain
  var ordAfter=Math.max(0,trustOrd-trustDed);
  var excessDed=Math.max(0,trustDed-trustOrd);
  var prefAfter=Math.max(0,trustPref-excessDed);
  // gains sent to Josh reduce the trust's retained income (distribution deduction):
  // short-term off the ordinary bucket, long-term off the preferential bucket
  var jstR=num('j_st_r'), jltR=num('j_lt_r'), jstA=num('j_st_a'), jltA=num('j_lt_a');
  var jst=jstR+jstA, jlt=jltR+jltA;
  var trOrd=Math.max(0,ordAfter-jst);
  var trPref=Math.max(0,prefAfter-jlt);
  var ex=100; var trOrdT=Math.max(0,trOrd-ex); var exRem=Math.max(0,ex-trOrd); var trPrefT=Math.max(0,trPref-exRem);
  var trOrdTax=bt(trOrdT,B.trust.ord);
  var trCg=cgStack(trOrdT,trPrefT,B.trust.cg);
  var trNII=trOrdT+trPrefT;
  var trNiit=0.038*Math.max(0,trNII-B.trust.niit);
  var trustTax=trOrdTax+trCg+trNiit;

  // ---- JOSH ---- (short-term = ordinary, long-term = preferential)
  var josh=filer(jst+num('j_other'),jlt,num('j_ded'),B.single,jst+jlt,0);
  var joshR=filer(jstR+num('j_other'),jltR,num('j_ded'),B.single,jstR+jltR,0);

  // ---- LEON & LISA ----
  var llOrd=num('ll_wages')+num('ll_consult')+fee+Math.max(0,num('ll_st'))+num('ll_divint');
  var llPref=Math.max(0,num('ll_lt'))+num('ll_house');
  var seV=seOn?(fee*0.9235*0.029):0;                // Medicare portion (over SS wage base)
  var llNII=num('ll_divint')+Math.max(0,num('ll_st'))+Math.max(0,num('ll_lt'));
  var marginDed=Math.min(num('ll_margin'),llNII);   // investment interest limited to net investment income
  var itemized=num('ll_item')+marginDed;
  var llDed=Math.max(num('ll_ded'),itemized);
  var ll=filer(llOrd,llPref,llDed,B.mfj,llNII,seV);
  ll.dedUsed=llDed; ll.itemizing=(itemized>num('ll_ded'));
  var ctc=num('ll_ctc'); var llMagi=llOrd+llPref;
  if(llMagi>400000){ ctc=Math.max(0, ctc-50*Math.ceil((llMagi-400000)/1000)); }
  ll.ctc=ctc;
  ll.tax=Math.max(0,ll.ord+ll.cg-ctc)+ll.niit+ll.se;

  return {trust:{tax:trustTax,ord:trOrdTax,cg:trCg,niit:trNiit,taxable:trOrdT+trPrefT},
          josh:josh, joshR:joshR, ll:ll, family:trustTax+josh.tax+ll.tax, jst:jst, jlt:jlt, jstR:jstR, jltR:jltR};
}

function calc(){
  var fee=num('fee');
  var seOn=document.getElementById('seTax').checked;
  document.getElementById('feeV').textContent=money(fee);
  document.getElementById('feeR').value=fee;
  document.getElementById('ll_fee').textContent=money(fee);
  document.getElementById('t_fee').textContent=money(fee);

  var s=scenario(fee,seOn);
  var llWh=num('ll_wh'), llEst=num('ll_est');
  var llDue=s.ll.tax-llWh-llEst;

  document.getElementById('famTax').textContent=money(s.family);
  document.getElementById('famDue').textContent="After Lisa's withholding & estimates: "+money(s.family-llWh-llEst)+" to pay";
  document.getElementById('saved').textContent='';

  document.getElementById('llOwe').textContent=money(llDue);
  document.getElementById('trOwe').textContent=money(s.trust.tax);
  document.getElementById('jOwe').textContent=money(s.josh.tax);

  document.getElementById('ll_out').innerHTML=
    row('Deduction used ('+(s.ll.itemizing?'itemized':'standard')+')',s.ll.dedUsed)+row('Taxable income',s.ll.taxable)+row('Ordinary tax',s.ll.ord)+row('Cap-gains tax',s.ll.cg)+row('NIIT (3.8%)',s.ll.niit)+(s.ll.se>0?row('SE/Medicare',s.ll.se):'')+(s.ll.ctc>0?row('Less: child tax credit',-s.ll.ctc):'')+rowB('Total tax',s.ll.tax)+row('Less: Lisa withholding',-llWh)+(llEst>0?row('Less: estimated payments',-llEst):'')+rowB('Balance due',llDue);
  document.getElementById('tr_out').innerHTML=
    row('Gain kept in trust',s.trust.taxable)+row('Ordinary tax',s.trust.ord)+row('Cap-gains tax',s.trust.cg)+row('NIIT (3.8%)',s.trust.niit)+rowB('Total tax',s.trust.tax);

  document.getElementById('j_tax_r').textContent=money(s.joshR.tax);
  var jtot=s.jst+s.jlt;
  var blended=jtot>0?(s.josh.tax/jtot*100):0;
  var addlTax=s.josh.tax-s.joshR.tax;
  document.getElementById('j_out').innerHTML=
    row('Total short-term (recd + planned)',s.jst)+row('Total long-term (recd + planned)',s.jlt)+row('Taxable income',s.josh.taxable)+row('Tax on received (locked)',s.joshR.tax)+row('Added tax from planned',addlTax)+rowB('Total tax',s.josh.tax)+rowP('Blended rate (total)',blended);

  // Harvesting headroom
  var stRoom=Math.max(0,82790-s.jst);
  var totalRoom=Math.max(0,200000-jtot);
  var hr='<b>Harvesting headroom</b><br>Josh: <b>'+blended.toFixed(1)+'%</b> blended on '+money(jtot)+' of gains.<br>';
  hr+='&bull; Trust can still realize &amp; send Josh <b>'+money(totalRoom)+'</b> more before his NIIT line ($200k) &mdash; keeps him ~8&ndash;12%.<br>';
  hr+='&bull; Of that, keep <b>short-term under '+money(stRoom)+'</b> (stays &le;12%); send the rest as <b>long-term</b>.';
  if(jtot>200000){ hr+='<br><span style="color:#ff4757;">&bull; Over $200k &mdash; Josh now pays 3.8% NIIT on the excess.</span>'; }
  document.getElementById('j_headroom').innerHTML=hr;
}
function row(l,v){ return '<div class="row"><label>'+l+'</label><span>'+money(v)+'</span></div>'; }
function rowB(l,v){ return '<div class="row" style="font-weight:bold;color:#00d4ff;border-top:1px solid rgba(0,212,255,.25);margin-top:4px;padding-top:4px;"><label style="color:#00d4ff;">'+l+'</label><span>'+money(v)+'</span></div>'; }
function rowP(l,v){ return '<div class="row" style="font-weight:bold;color:#00ff88;border-top:1px solid rgba(0,255,136,.25);margin-top:4px;padding-top:4px;"><label style="color:#00ff88;">'+l+'</label><span>'+v.toFixed(1)+'%</span></div>'; }
calc();
</script>
</body>
</html>"""


# --- STR Market Comparison page --------------------------------------------
def generate_markets_html():
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>STR Market Comparison</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%); min-height:100vh; padding:20px; color:#e0e0e0; }
.container { max-width:1500px; margin:0 auto; }
h1 { text-align:center; color:#00d4ff; margin-bottom:6px; font-size:2em; }
.sub { text-align:center; color:#888; font-size:.85em; margin-bottom:16px; }
a.back { color:#00d4ff; text-decoration:none; font-size:.9em; }
.controls { display:flex; gap:16px; flex-wrap:wrap; justify-content:center; margin-bottom:14px; align-items:center; }
.controls label { font-size:.82em; color:#aaa; margin-right:4px; }
select { background:rgba(255,255,255,.08); border:1px solid rgba(0,212,255,.3); color:#e0e0e0; border-radius:6px; padding:6px 10px; font-size:.85em; }
.legend { text-align:center; font-size:.78em; color:#888; margin-bottom:10px; }
.badge { padding:2px 8px; border-radius:10px; font-size:.75em; font-weight:bold; white-space:nowrap; }
.great { background:rgba(0,255,136,.15); color:#00ff88; border:1px solid #00ff88; }
.workable { background:rgba(224,176,0,.15); color:#e0b000; border:1px solid #e0b000; }
.avoid { background:rgba(255,71,87,.15); color:#ff4757; border:1px solid #ff4757; }
.tablewrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; background:rgba(255,255,255,.03); border-radius:10px; overflow:hidden; }
th,td { padding:8px 10px; text-align:left; border-bottom:1px solid rgba(255,255,255,.06); font-size:.84em; white-space:nowrap; }
th { background:rgba(0,212,255,.1); color:#00d4ff; text-transform:uppercase; font-size:.7em; cursor:pointer; user-select:none; position:sticky; top:0; }
th:hover { background:rgba(0,212,255,.2); }
th::after { content:' \2195'; opacity:.3; }
td.note { white-space:normal; color:#bbb; font-size:.8em; min-width:230px; }
tr:hover td { background:rgba(255,255,255,.04); }
.num { font-family:'SF Mono',Monaco,monospace; text-align:right; }
.count { text-align:center; color:#888; font-size:.8em; margin-top:10px; }
</style>
</head>
<body>
<div class="container">
<div style="margin-bottom:8px;"><a class="back" href="/">&larr; Portfolio</a> &nbsp;|&nbsp; <a class="back" href="/tax">Tax Planner</a> &nbsp;|&nbsp; <a class="back" href="/str">RE Shelter</a></div>
<h1>STR Market Comparison</h1>
<div class="sub">Non-owner-occupied investment STR (&le;7-day avg stays) across your target states. Click a column to sort; filter by state/tier. Verify any specific parcel before buying &mdash; rules change fast.</div>

<div class="controls">
  <div><label>State</label><select id="fState" onchange="render()"><option value="">All</option></select></div>
  <div><label>Verdict</label><select id="fTier" onchange="render()"><option value="">All</option><option value="great">Great</option><option value="workable">Workable</option><option value="avoid">Avoid</option></select></div>
</div>
<div class="legend"><span class="badge great">GREAT</span> non-owner STR clearly legal + good economics &nbsp; <span class="badge workable">WORKABLE</span> legal but zone/cap/fee caveat &nbsp; <span class="badge avoid">AVOID</span> banned / capped-out / min-stay</div>

<div class="tablewrap">
<table>
<thead><tr>
<th onclick="sortBy('m')">Market</th>
<th onclick="sortBy('s')">State</th>
<th onclick="sortBy('it')">State inc. tax</th>
<th onclick="sortBy('tier')">Verdict</th>
<th onclick="sortBy('pt')">Property tax /$1M</th>
<th onclick="sortBy('lt')">Lodging tax</th>
<th onclick="sortBy('ins')">Insurance</th>
<th onclick="sortBy('note')">Notes</th>
</tr></thead>
<tbody id="tbody"></tbody>
</table>
</div>
<div class="count" id="count"></div>
</div>

<script>
var DATA=[
{m:"Orlando/Kissimmee-Davenport",s:"FL",it:0,tier:"great",pt:18,lt:13.5,ins:"Low",note:"Year-round Disney demand, inland low insurance. Top overall pick."},
{m:"Fort Lauderdale",s:"FL",it:0,tier:"great",pt:19,lt:13,ins:"High",note:"No minimum stay, non-owner legal citywide, simple registration."},
{m:"Cape Coral",s:"FL",it:0,tier:"great",pt:17,lt:12,ins:"High",note:"New 2026 registration, no min stay, canal-home demand."},
{m:"Pensacola Beach",s:"FL",it:0,tier:"workable",pt:14,lt:12,ins:"High",note:"No min stay; lowest FL property tax; leased land; watch SRIA registry."},
{m:"Anna Maria Island",s:"FL",it:0,tier:"workable",pt:16,lt:12.5,ins:"High",note:"Nightly OK; verify Holmes Beach 7-day vs 30-day zone."},
{m:"City of Miami",s:"FL",it:0,tier:"workable",pt:20,lt:13,ins:"High",note:"Only T4/T5/T6 zones; T3 residential banned. Buy the zone."},
{m:"Sarasota / Siesta Key",s:"FL",it:0,tier:"workable",pt:16,lt:12.5,ins:"High",note:"RMF multifamily only; single-family banned on the key."},
{m:"Amelia Island",s:"FL",it:0,tier:"workable",pt:15,lt:12,ins:"Mod",note:"R-3 zone only (or grandfathered). Lower tax/insurance than S. FL."},
{m:"Fort Myers Beach",s:"FL",it:0,tier:"workable",pt:17,lt:12,ins:"High",note:"Register + inspection; post-Ian rebuild market."},
{m:"Miami Beach",s:"FL",it:0,tier:"avoid",pt:20,lt:17,ins:"High",note:"Residential ban + heavy fines; condo-hotel/RM-3 only."},
{m:"Clearwater / St. Pete Beach",s:"FL",it:0,tier:"avoid",pt:19,lt:13,ins:"High",note:"30-31 day minimum in residential zones."},
{m:"Sanibel",s:"FL",it:0,tier:"avoid",pt:17,lt:12,ins:"High",note:"~4-week minimum stay."},
{m:"Florida Keys",s:"FL",it:0,tier:"avoid",pt:18,lt:13,ins:"High",note:"28-day minimum + hard caps."},
{m:"Naples (city)",s:"FL",it:0,tier:"avoid",pt:18,lt:12,ins:"High",note:"30-day minimum; 3 short rentals/yr."},
{m:"Daytona / Volusia",s:"FL",it:0,tier:"avoid",pt:18,lt:12.5,ins:"High",note:"County ban; tourist districts only; $15k fines."},
{m:"Teton Village",s:"WY",it:0,tier:"great",pt:4,lt:5,ins:"Mod",note:"Approved resort zone; best tax combo on the board; elite/pricey."},
{m:"Cody",s:"WY",it:0,tier:"great",pt:6,lt:7,ins:"Mod",note:"Legal most city zones (not R-2); Yellowstone east gate."},
{m:"Alpine / Star Valley",s:"WY",it:0,tier:"workable",pt:5,lt:7,ins:"Mod",note:"Legal but 2026 rules tightening; check exact town."},
{m:"Pinedale",s:"WY",it:0,tier:"workable",pt:5,lt:7,ins:"Mod",note:"County only (town banned new STRs); thin seasonal market."},
{m:"Town of Jackson",s:"WY",it:0,tier:"avoid",pt:4,lt:5,ins:"Mod",note:"60-night cap outside Lodging Overlay."},
{m:"Teton County (general)",s:"WY",it:0,tier:"avoid",pt:4,lt:5,ins:"Mod",note:"STR only in named resort zones; otherwise banned."},
{m:"Vail",s:"CO",it:4.4,tier:"great",pt:5,lt:10.5,ins:"Mod",note:"Uncapped, town-wide; +$1,200/bedroom/yr fee; two seasons."},
{m:"Keystone",s:"CO",it:4.4,tier:"great",pt:5,lt:12,ins:"Mod",note:"No cap, $285/yr. Best-in-Summit for investors."},
{m:"Dillon",s:"CO",it:4.4,tier:"great",pt:5,lt:12,ins:"Mod",note:"No cap, no waitlist."},
{m:"Copper Mountain",s:"CO",it:4.4,tier:"great",pt:5,lt:16,ins:"Mod",note:"No cap; +4% CMRA surcharge; mostly condos, check HOA."},
{m:"Mountain Village (Telluride)",s:"CO",it:4.4,tier:"great",pt:5,lt:14.7,ins:"Mod",note:"No cap, no dedicated STR tax. Rare fully-open resort."},
{m:"Mt. Crested Butte",s:"CO",it:4.4,tier:"great",pt:5,lt:14,ins:"Mod",note:"No cap, no zoning restriction."},
{m:"Grand Lake",s:"CO",it:4.4,tier:"great",pt:5,lt:12,ins:"Mod",note:"No cap; summer-heavy seasonal demand (west of RMNP)."},
{m:"Breckenridge",s:"CO",it:4.4,tier:"workable",pt:5,lt:12.3,ins:"Mod",note:"Resort Zone / Zone 1 only; Zone 2/3 capped-out."},
{m:"Steamboat Springs",s:"CO",it:4.4,tier:"workable",pt:5,lt:18.4,ins:"Mod",note:"Green overlay zone only; punitive 9% STR tax."},
{m:"Winter Park / Fraser",s:"CO",it:4.4,tier:"workable",pt:5,lt:12,ins:"Mod",note:"No cap; steep per-bedroom workforce fees ($350-400/bdrm)."},
{m:"Silverthorne",s:"CO",it:4.4,tier:"workable",pt:5,lt:13,ins:"Mod",note:"3-zone cap; confirm capacity before buying."},
{m:"Glenwood Springs",s:"CO",it:4.4,tier:"workable",pt:5,lt:11.6,ins:"Mod",note:"Under 5% cap now; 250-ft buffer between STRs; year-round."},
{m:"Estes Park",s:"CO",it:4.4,tier:"workable",pt:5,lt:11.5,ins:"High",note:"Residential license by lottery; unhosted now allowed."},
{m:"Durango",s:"CO",it:4.4,tier:"workable",pt:5,lt:14.65,ins:"Mod",note:"Allowed zones only; EN-1/EN-2 capped; buy commercial/mixed-use."},
{m:"Frisco",s:"CO",it:4.4,tier:"avoid",pt:5,lt:13,ins:"Mod",note:"At cap, waitlist ~12-14 mo."},
{m:"Boulder",s:"CO",it:4.4,tier:"avoid",pt:6,lt:0,ins:"Mod",note:"Owner-occupied primary residence only."},
{m:"Telluride town (residential)",s:"CO",it:4.4,tier:"avoid",pt:5,lt:17.2,ins:"Mod",note:"29-night/yr cap in residential zone."},
{m:"Crested Butte town",s:"CO",it:4.4,tier:"avoid",pt:5,lt:14,ins:"Mod",note:"Unlimited license hard-capped and scarce."},
{m:"Big Sky",s:"MT",it:5.9,tier:"great",pt:19,lt:12,ins:"Wildfire",note:"Unincorporated, unregulated; premium ski. 1.9% property tax is the drag."},
{m:"Kalispell / Flathead Lake",s:"MT",it:5.9,tier:"great",pt:6,lt:8,ins:"Wildfire",note:"Permissive; low property tax; lake + Glacier demand; dodge downtown cap."},
{m:"Gardiner",s:"MT",it:5.9,tier:"great",pt:6,lt:11,ins:"High",note:"Permissive new county rules; buy detached (no shared wall); flood risk."},
{m:"Whitefish",s:"MT",it:5.9,tier:"workable",pt:19,lt:8,ins:"Wildfire",note:"Resort zones (WRR/WRB) only; check covenants; insurance-heavy."},
{m:"West Yellowstone",s:"MT",it:5.9,tier:"workable",pt:7,lt:11,ins:"Wildfire",note:"B-3 Central Business zone only."},
{m:"Missoula",s:"MT",it:5.9,tier:"workable",pt:9,lt:8,ins:"Mod",note:"Zoned + registration (2026 code); year-round hub demand."},
{m:"Red Lodge",s:"MT",it:5.9,tier:"workable",pt:19,lt:8,ins:"Mod",note:"20% cap; permit does NOT transfer on sale."},
{m:"Bozeman",s:"MT",it:5.9,tier:"avoid",pt:19,lt:8,ins:"Mod",note:"Non-owner (Type 3) STRs banned since 2023."},
{m:"St. George",s:"UT",it:4.55,tier:"great",pt:9,lt:6.5,ins:"Low",note:"STR overlay communities; lowest guest tax; year-round sun."},
{m:"Brian Head",s:"UT",it:4.55,tier:"workable",pt:8,lt:10,ins:"Mod",note:"Broadly open, no cap; small, seasonal ski market."},
{m:"Bryce Canyon area",s:"UT",it:4.55,tier:"workable",pt:10,lt:11,ins:"Low",note:"CUP-based, no cap; small seasonal market."},
{m:"Park City / Summit",s:"UT",it:4.55,tier:"workable",pt:8,lt:9.55,ins:"Mod",note:"Resort Overlay or already-licensed condo only; SFH mostly banned."},
{m:"Heber / Midway",s:"UT",it:4.55,tier:"workable",pt:10,lt:11,ins:"Mod",note:"TROD overlay only (boundaries shrank Sept 2026); Deer Valley East."},
{m:"Ogden / Snowbasin",s:"UT",it:4.55,tier:"workable",pt:10,lt:12,ins:"Mod",note:"3-year ownership rule in residential; commercial zones only for fast start."},
{m:"Moab",s:"UT",it:4.55,tier:"avoid",pt:9,lt:9.07,ins:"Low",note:"Ban / moratorium on new STRs."},
{m:"Springdale / Zion",s:"UT",it:4.55,tier:"avoid",pt:10,lt:12,ins:"Low",note:"Commercial-only; 5 permits/yr in even-year March window."},
{m:"Lake Arrowhead",s:"CA",it:13.3,tier:"great",pt:11,lt:7,ins:"Wildfire",note:"Uncapped, no owner-occ; only wide-open CA market. Budget wildfire insurance."},
{m:"San Diego",s:"CA",it:13.3,tier:"workable",pt:11,lt:12.75,ins:"Low",note:"Tier 3 license, no day cap, but cap nearly exhausted; act fast."},
{m:"Big Bear Lake",s:"CA",it:13.3,tier:"workable",pt:12,lt:13,ins:"Wildfire",note:"No cap (rare), 2/owner; high FAIR-Plan insurance erodes cash flow."},
{m:"Mammoth Lakes",s:"CA",it:13.3,tier:"workable",pt:12,lt:15,ins:"Wildfire",note:"STR-zoned condos only (not SFH); highest guest tax (15%)."},
{m:"Placer / North Tahoe",s:"CA",it:13.3,tier:"workable",pt:12,lt:10,ins:"Wildfire",note:"~500 permits left before a 30-night minimum triggers; closing fast."},
{m:"Palm Springs",s:"CA",it:13.3,tier:"workable",pt:13,lt:11.5,ins:"Low",note:"20% neighborhood density cap; low insurance; winter/shoulder market."},
{m:"South Lake Tahoe",s:"CA",it:13.3,tier:"avoid",pt:12,lt:14,ins:"Wildfire",note:"900 residential cap reached; waitlist only."},
{m:"Truckee",s:"CA",it:13.3,tier:"avoid",pt:12,lt:13.25,ins:"Wildfire",note:"Capped; permits non-transferable; 365-day blackout after purchase."},
{m:"Santa Barbara",s:"CA",it:13.3,tier:"avoid",pt:12,lt:12,ins:"Wildfire",note:"Whole-home non-owner STR being zoned/legislated out."},
{m:"Napa",s:"CA",it:13.3,tier:"avoid",pt:12,lt:12,ins:"Wildfire",note:"Prohibited in unincorporated residential/ag zones."},
{m:"Sonoma",s:"CA",it:13.3,tier:"avoid",pt:12,lt:12,ins:"Wildfire",note:"~91% of properties excluded; countywide cap near limit."},
{m:"Monterey / Carmel",s:"CA",it:13.3,tier:"avoid",pt:12,lt:10.5,ins:"Wildfire",note:"Residential whole-home ban in progress."},
{m:"Killington",s:"VT",it:8.75,tier:"great",pt:20,lt:13,ins:"Low",note:"Uncapped, no owner-occ; biggest Eastern ski. ~2% property tax is the knock."},
{m:"Jay Peak",s:"VT",it:8.75,tier:"great",pt:17,lt:12,ins:"Low",note:"Least regulated VT town; thin $1M market, very seasonal."},
{m:"Warren (Sugarbush)",s:"VT",it:8.75,tier:"workable",pt:19,lt:12,ins:"Low",note:"Allowed w/ registration; absentee-owner renewal discipline needed."},
{m:"Manchester",s:"VT",it:8.75,tier:"workable",pt:17,lt:12,ins:"Low",note:"Village registers; Town unrestricted. Stratton + summer demand."},
{m:"Winhall (Stratton)",s:"VT",it:8.75,tier:"workable",pt:15,lt:13,ins:"Low",note:"Legal, uncapped, but $500/bedroom annual fee."},
{m:"Dover (Mount Snow)",s:"VT",it:8.75,tier:"workable",pt:15,lt:13,ins:"Low",note:"$125/yr, no cap; softer southern-VT demand."},
{m:"Stowe",s:"VT",it:8.75,tier:"avoid",pt:14,lt:13,ins:"Low",note:"New non-resident licenses effectively banned (850 cap)."},
{m:"Burlington",s:"VT",it:8.75,tier:"avoid",pt:16,lt:13,ins:"Mod",note:"Owner-occupied (primary residence) required."},
{m:"Woodstock",s:"VT",it:8.75,tier:"avoid",pt:20,lt:12,ins:"Low",note:"Hard cap, full; highest property tax in VT."},
{m:"Catskills - Hunter",s:"NY",it:10.9,tier:"great",pt:12.5,lt:10,ins:"Low",note:"Non-owner legal, no min-stay; 250-permit cap; ski + summer."},
{m:"Thousand Islands / Alexandria Bay",s:"NY",it:10.9,tier:"great",pt:17,lt:11,ins:"Mod",note:"Very permissive; short summer season; self-remit 3% county tax."},
{m:"Saratoga Springs",s:"NY",it:10.9,tier:"workable",pt:15,lt:15,ins:"Low",note:"Non-owner now legal but 150-night/yr cap; year-round demand."},
{m:"Finger Lakes",s:"NY",it:10.9,tier:"workable",pt:12,lt:11,ins:"Low",note:"Town-by-town; pick a permissive town (some bans e.g. Skaneateles)."},
{m:"Lake Placid",s:"NY",it:10.9,tier:"avoid",pt:14,lt:13,ins:"Low",note:"90-day cap + residential unhosted ban."},
{m:"Lake George (town)",s:"NY",it:10.9,tier:"avoid",pt:15,lt:11.5,ins:"Mod",note:"Moratorium on new STRs."},
{m:"Cooperstown",s:"NY",it:10.9,tier:"avoid",pt:16,lt:12,ins:"Low",note:"Owner-occupancy required in the village."},
{m:"Hamptons / Montauk",s:"NY",it:10.9,tier:"avoid",pt:18,lt:13,ins:"High",note:"14-day minimum stay makes the loophole illegal."},
{m:"Cape Cod (mid-Cape)",s:"MA",it:5,tier:"great",pt:7,lt:14.45,ins:"High",note:"Non-owner legal, lowest property tax; summer only; coastal insurance."},
{m:"Berkshires",s:"MA",it:5,tier:"workable",pt:13,lt:11.7,ins:"Mod",note:"Legal but annual-day caps (Lenox 75, Great Barrington 150)."},
{m:"Nantucket",s:"MA",it:5,tier:"avoid",pt:4,lt:14.45,ins:"High",note:"Entity-ownership ban + legal uncertainty."},
{m:"Martha's Vineyard",s:"MA",it:5,tier:"avoid",pt:4,lt:14.45,ins:"High",note:"STR legality unsettled; too risky for a depreciation play."}
];
var sortKey="tier", sortDir=1;
var tierRank={great:0,workable:1,avoid:2};
function fmtMoney(k){ return k>0 ? "$"+k+"k" : "--"; }
function fmtPct(p){ return p>0 ? p+"%" : "--"; }
function populateStates(){
  var sel=document.getElementById('fState'); var states=[];
  DATA.forEach(function(d){ if(states.indexOf(d.s)<0) states.push(d.s); });
  states.sort();
  states.forEach(function(s){ var o=document.createElement('option'); o.value=s; o.textContent=s; sel.appendChild(o); });
}
function sortBy(k){ if(sortKey===k) sortDir=-sortDir; else { sortKey=k; sortDir=1; } render(); }
function render(){
  var fs=document.getElementById('fState').value, ft=document.getElementById('fTier').value;
  var rows=DATA.filter(function(d){ return (!fs||d.s===fs) && (!ft||d.tier===ft); });
  rows.sort(function(a,b){
    var av,bv;
    if(sortKey==='tier'){ av=tierRank[a.tier]; bv=tierRank[b.tier]; }
    else { av=a[sortKey]; bv=b[sortKey]; }
    if(typeof av==='string'){ return sortDir*av.localeCompare(bv); }
    return sortDir*(av-bv);
  });
  var tb=document.getElementById('tbody'); tb.innerHTML='';
  rows.forEach(function(d){
    var tr=document.createElement('tr');
    tr.innerHTML='<td>'+d.m+'</td><td>'+d.s+'</td><td class="num">'+(d.it===0?'0%':d.it+'%')+'</td>'
      +'<td><span class="badge '+d.tier+'">'+d.tier.toUpperCase()+'</span></td>'
      +'<td class="num">'+fmtMoney(d.pt)+'</td><td class="num">'+fmtPct(d.lt)+'</td><td>'+d.ins+'</td><td class="note">'+d.note+'</td>';
    tb.appendChild(tr);
  });
  document.getElementById('count').textContent=rows.length+' markets shown';
}
populateStates(); render();
</script>
</body>
</html>"""


# --- Real Estate Shelter Planner page -------------------------------------
def generate_str_html():
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Real Estate Shelter Planner</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%); min-height:100vh; padding:20px; color:#e0e0e0; }
.container { max-width:1200px; margin:0 auto; }
h1 { text-align:center; color:#00d4ff; margin-bottom:6px; font-size:2em; }
.sub { text-align:center; color:#888; font-size:.85em; margin-bottom:18px; }
a.back { color:#00d4ff; text-decoration:none; font-size:.9em; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }
.panel { background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1); border-radius:12px; padding:18px; margin-bottom:16px; }
.panel h2 { color:#00d4ff; font-size:1.1em; margin-bottom:12px; }
.row { display:flex; justify-content:space-between; align-items:center; padding:4px 0; font-size:.88em; }
.row label { color:#aaa; }
input[type=number] { background:rgba(255,255,255,.08); border:1px solid rgba(0,212,255,.3); color:#e0e0e0;
  border-radius:6px; padding:5px 8px; width:130px; font-family:'SF Mono',Monaco,monospace; font-size:.85em; text-align:right; }
.out .row { font-family:'SF Mono',Monaco,monospace; }
.big { font-size:1.9em; font-weight:bold; font-family:'SF Mono',Monaco,monospace; color:#00ff88; }
.card { background:linear-gradient(135deg,#00ff8822,#00cc6622); border:2px solid #00ff88; border-radius:12px; padding:16px; text-align:center; margin-bottom:16px; }
.mut { color:#888; font-size:.8em; }
.grp { color:#00d4ff; font-size:.72em; text-transform:uppercase; letter-spacing:1px; margin:10px 0 4px; border-bottom:1px solid rgba(0,212,255,.2); padding-bottom:3px; }
.rowB { font-weight:bold; color:#00d4ff; border-top:1px solid rgba(0,212,255,.25); margin-top:4px; padding-top:4px; }
.win { color:#00ff88; font-weight:bold; }
</style>
</head>
<body>
<div class="container">
<div style="margin-bottom:8px;"><a class="back" href="/">&larr; Portfolio</a> &nbsp;|&nbsp; <a class="back" href="/tax">Tax Planner</a> &nbsp;|&nbsp; <a class="back" href="/markets">STR Markets</a></div>
<h1>Real Estate Shelter Planner</h1>
<div class="sub">Short-term rental + 100% bonus depreciation (2025). Planning estimate &mdash; confirm with your CPA.</div>

<div class="card">
  <div class="mut" style="text-transform:uppercase;letter-spacing:1px;">Year-1 tax saved</div>
  <div class="big" id="saved">$0</div>
  <div id="shelterLine" class="mut"></div>
</div>

<div class="grid">
<div class="panel">
  <h2>The property</h2>
  <div class="row"><label>Purchase price</label><input type="number" id="price" value="1000000" oninput="calc()"></div>
  <div class="row"><label>Down payment %</label><input type="number" id="downpct" value="25" oninput="calc()"></div>
  <div class="row"><label>Land % (not depreciable)</label><input type="number" id="landpct" value="25" oninput="calc()"></div>
  <div class="row"><label>Cost-seg % of building (bonus)</label><input type="number" id="segpct" value="25" oninput="calc()"></div>
  <div class="row"><label>Mortgage rate %</label><input type="number" id="rate" value="7" oninput="calc()"></div>
  <div class="row"><label>Annual rental income</label><input type="number" id="rental" value="50000" oninput="calc()"></div>
  <div class="row"><label>Operating expenses (tax/ins/mgmt)</label><input type="number" id="opex" value="18000" oninput="calc()"></div>
  <div class="out" id="prop_out" style="margin-top:8px;"></div>
</div>

<div class="panel">
  <h2>Tax impact</h2>
  <div class="row"><label>Your ordinary taxable income</label><input type="number" id="income" value="277483" oninput="calc()"></div>
  <div class="out" id="tax_out" style="margin-top:8px;"></div>
</div>
</div>

<div class="panel">
  <h2>Right-size it &mdash; how much property to shelter a target</h2>
  <div class="row"><label>Income you want to shelter</label><input type="number" id="rs_income" value="168300" oninput="calc()"></div>
  <div class="out" id="rs_out" style="margin-top:8px;"></div>
</div>

<div class="panel">
  <h2>Down payment: stocks vs. STR (10-year)</h2>
  <div class="row"><label>Stock market return %/yr</label><input type="number" id="stockret" value="10" oninput="calc()"></div>
  <div class="row"><label>Property appreciation %/yr</label><input type="number" id="apprec" value="4" oninput="calc()"></div>
  <div class="out" id="cmp_out" style="margin-top:8px;"></div>
  <div class="mut" style="margin-top:8px;">STR = your down payment + 10yr appreciation on the full price + ~mortgage paydown + year-1 tax saving reinvested. Leverage + the tax shelter are why the slice of cash in the STR typically outgrows the same cash in stocks &mdash; at the cost of effort, illiquidity, and leverage risk.</div>
</div>
</div>

<script>
var MFJ=[[23850,.10],[96950,.12],[206700,.22],[394600,.24],[501050,.32],[751600,.35],[1e15,.37]];
function num(id){return parseFloat(document.getElementById(id).value)||0;}
function money(x){return (x<0?'-$':'$')+Math.abs(Math.round(x)).toLocaleString('en-US');}
function bt(x,br){var t=0,p=0;for(var i=0;i<br.length;i++){var c=br[i][0],r=br[i][1];if(x>p){t+=(Math.min(x,c)-p)*r;p=c;}else break;}return t;}
function row(l,v){return '<div class="row"><label>'+l+'</label><span>'+money(v)+'</span></div>';}
function rowB(l,v){return '<div class="row rowB"><label style="color:#00d4ff;">'+l+'</label><span>'+money(v)+'</span></div>';}

function calc(){
  var price=num('price'), downpct=num('downpct')/100, landpct=num('landpct')/100, segpct=num('segpct')/100;
  var rate=num('rate')/100, rental=num('rental'), opex=num('opex');
  var down=price*downpct, loan=price-down, building=price*(1-landpct);
  var bonus=building*segpct;
  var remBuilding=building-bonus, regDep=remBuilding/27.5*0.5;   // ~half-year
  var interest=loan*rate;
  var deductions=bonus+regDep+opex+interest;
  var loss=Math.max(0,deductions-rental);                        // year-1 tax loss

  document.getElementById('prop_out').innerHTML=
    row('Down payment',down)+row('Mortgage',loan)+row('Building basis',building)
    +'<div class="grp">Year-1 deductions</div>'
    +row('Bonus depreciation (100%)',bonus)+row('Regular depreciation (~half yr)',regDep)+row('Mortgage interest',interest)+row('Operating expenses',opex)
    +row('Less: rental income',-rental)+rowB('Year-1 tax loss',loss);

  var income=num('income');
  var taxBefore=bt(income,MFJ), taxAfter=bt(Math.max(0,income-loss),MFJ);
  var saved=taxBefore-taxAfter, sheltered=Math.min(loss,income);
  document.getElementById('saved').textContent=money(saved);
  document.getElementById('shelterLine').textContent='Shelters '+money(sheltered)+' of income on '+money(down)+' down (controls '+money(price)+' of real estate)';
  document.getElementById('tax_out').innerHTML=
    row('Tax before shelter',taxBefore)+row('Tax after shelter',taxAfter)+rowB('Ordinary tax saved',saved)
    +'<div class="mut" style="margin-top:6px;">Plus ~3.8% NIIT savings on any sheltered investment income (not shown).</div>';

  // right-size
  var lossPerDollar=price>0?loss/price:0.2;
  var target=num('rs_income');
  var propNeeded=lossPerDollar>0?target/lossPerDollar:0;
  var downNeeded=propNeeded*downpct;
  document.getElementById('rs_out').innerHTML=
    row('STR purchase needed',propNeeded)+rowB('Down payment needed',downNeeded)
    +'<div class="mut" style="margin-top:6px;">At your current assumptions ('+(lossPerDollar*100).toFixed(0)+'c of year-1 loss per $1 of price).</div>';

  // stocks vs STR on the down payment, 10 yr
  var sret=num('stockret')/100, apr=num('apprec')/100;
  var stocksEnd=down*Math.pow(1+sret,10);
  var apprecTotal=price*(Math.pow(1+apr,10)-1);
  var paydown=loan*0.14;                                         // ~14% of loan over 10 yr
  var taxReinvest=saved*Math.pow(1+sret,9);
  var strEquity=down+apprecTotal+paydown;
  var strTotal=strEquity+taxReinvest;
  var diff=strTotal-stocksEnd;
  document.getElementById('cmp_out').innerHTML=
    row('Same cash in stocks (10 yr)',stocksEnd)
    +'<div class="grp">Same cash as STR down payment</div>'
    +row('Your equity (down + apprec + paydown)',strEquity)+row('+ year-1 tax saved, reinvested',taxReinvest)+rowB('STR total (10 yr)',strTotal)
    +'<div class="row rowB"><label class="win">STR advantage</label><span class="win">'+money(diff)+'</span></div>';
}
calc();
</script>
</body>
</html>"""


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
        elif self.path == '/tax':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(generate_tax_html().encode())
        elif self.path == '/str':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(generate_str_html().encode())
        elif self.path == '/markets':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(generate_markets_html().encode())
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
