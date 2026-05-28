#!/usr/bin/env python3
"""Portfolio Server for Render - Multi-portfolio with tabs"""

import http.server
import json
import urllib.request
import os
from datetime import datetime

PORT = int(os.environ.get("PORT", 10000))

# ============== PORTFOLIO 1: ANNABAY ==============
ANNABAY_HOLDINGS = {
    "RIG": {"name": "Transocean Ltd", "qty": 25000, "cost": 97500},
    "PSH.AS": {"name": "Pershing Square Holdings", "qty": 3000, "cost": 191310, "currency": "EUR", "fx_rate": 1.163},
    "MSFT": {"name": "Microsoft Corp", "qty": 300, "cost": 112500},
    "CROX": {"name": "Crocs Inc", "qty": 1500, "cost": 114000},
    "CNSWF": {"name": "Constellation Software", "qty": 100, "cost": 247899},
    "PDD": {"name": "PDD Holdings", "qty": 1000, "cost": 114000},
    "UBER": {"name": "Uber Technologies", "qty": 3000, "cost": 234510},
    "AMR": {"name": "Alpha Metallurgical Resources", "qty": 1750, "cost": 278250},
    "BN": {"name": "Brookfield Corp", "qty": 6000, "cost": 271200},
    "CNR": {"name": "Core Natural Resources", "qty": 1000, "cost": 75500},
    "MIAX": {"name": "Miami International Holdings", "qty": 2500, "cost": 105000},
    "SNAP": {"name": "Snap Inc", "qty": 20000, "cost": 80000},
}
ANNABAY_OPTIONS = {
    "WDAY": {"name": "Call Workday JAN28 $150", "contracts": 25, "cost": 100000, "strike": 150, "expiry": "21.01.2028"},
    "SOC": {"name": "Call Sable Offshore JAN27 $12.5", "contracts": 100, "cost": 67000, "strike": 12.5, "expiry": "15.01.2027"},
}
ANNABAY_FOREIGN = {
    "DBO.TO": {"name": "D-Box Technologies", "qty": 125000, "cost": 73893, "currency": "CAD", "fx_rate": 1.376},
    "TGO.TO": {"name": "Terago Inc", "qty": 150000, "cost": 97816, "currency": "CAD", "fx_rate": 1.376},
    "1970.HK": {"name": "IMAX China Holding", "qty": 13000, "cost": 12782, "currency": "HKD", "fx_rate": 7.8266},
}
ANNABAY_CASH = {"USD": 162163, "EUR": 201350}

# ============== PORTFOLIO 2: SCHWAB 1 ==============
SCHWAB1_HOLDINGS = {
    "BN": {"name": "Brookfield Corp F Class A", "qty": 3000, "cost": 60860},
    "CNR": {"name": "Core Natural Resources", "qty": 1108, "cost": 82984},
    "PNPFF": {"name": "Pinetree Capital Ltd", "qty": 5700, "cost": 47502},
    "SOC": {"name": "Sable Offshore Corp", "qty": 0, "cost": 0},  # Stock position shows dash
    "TAVHY": {"name": "TAV Havalimanlari", "qty": 7000, "cost": 110846},
    "TDW": {"name": "Tidewater Inc", "qty": 0, "cost": 0},  # Stock position shows dash
    "TOITF": {"name": "Topicus.com Inc", "qty": 500, "cost": 25003},
}
SCHWAB1_OPTIONS = {
    "SOC": {"name": "Call Sable Offshore JAN28 $10", "contracts": 50, "cost": 11383, "strike": 10, "expiry": "21.01.2028"},
    "TDW": {"name": "Call Tidewater JAN27 $60", "contracts": 100, "cost": 81315, "strike": 60, "expiry": "15.01.2027"},
}
SCHWAB1_CASH = {"USD": -128904}  # Margin balance

# ============== PORTFOLIO 3: SCHWAB 2 ==============
SCHWAB2_HOLDINGS = {
    "CNR": {"name": "Core Natural Resources", "qty": 1000, "cost": 83880},
    "PDD": {"name": "PDD Holdings ADR", "qty": 1000, "cost": 93750},
    "TAVHY": {"name": "TAV Havalimanlari", "qty": 5000, "cost": 112227},
    "TOITF": {"name": "Topicus.com Inc", "qty": 1000, "cost": 70527},
    "UBER": {"name": "Uber Technologies", "qty": 1500, "cost": 107879},
}
SCHWAB2_TBILLS = {
    "912797TD9": {"name": "US Treasury Bill 26U", "qty": 500000, "cost": 498661},
    "912797TF4": {"name": "US Treasury Bill 26U", "qty": 500000, "cost": 497964},
}
SCHWAB2_CASH = {"USD": 332402}

# ============== PORTFOLIO 4: MORGAN STANLEY ==============
MS_HOLDINGS = {
    "MSFT": {"name": "Microsoft Corp", "qty": 700, "cost": 78555},
    "AMZN": {"name": "Amazon.com Inc", "qty": 700, "cost": 76510},
    "VAL": {"name": "Valaris Ltd", "qty": 1800000, "cost": 55800},  # 1.8M qty from screenshot
    "NE": {"name": "Noble Corp", "qty": 3000000, "cost": 59190},  # 3M qty from screenshot
    "SNAP": {"name": "Snap Inc", "qty": 20000000, "cost": 99230},  # 20M qty from screenshot
    "LMGIF": {"name": "Lumine Group Inc", "qty": 1501000, "cost": 21888},
    "AAL": {"name": "American Airlines", "qty": 2000, "cost": 36},
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

def fetch_price_yahoo(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta["regularMarketPrice"]
            prev_close = meta.get("previousClose", meta.get("chartPreviousClose", price))
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

    for symbol in all_symbols:
        if symbol.startswith("91279"):  # Skip T-bills
            continue
        data = fetch_price_yahoo(symbol)
        if data:
            prices[symbol] = data
            print(f"  {symbol}: {data['price']}")
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
        stocks_table = f"""
        <h3 class="section-title">Equities</h3>
        <div class="table-container">
        <table class="sortable">
            <thead><tr>
                <th>Symbol</th><th>Name</th><th>Qty</th><th>Cost</th><th>Price</th><th>Day %</th><th>Value</th><th>Day $</th><th>Gain/Loss</th><th>Return</th>
            </tr></thead>
            <tbody>{''.join(stock_rows)}</tbody>
            <tfoot><tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                <td colspan="3">Total Equities</td>
                <td class="number">${total_stock_cost:,}</td>
                <td colspan="2"></td>
                <td class="number">${total_stock_value:,.0f}</td>
                <td class="number {day_class}">{'+' if total_day_gain >= 0 else ''}${total_day_gain:,.0f}</td>
                <td class="number {stock_gain_class}">{'+' if stock_gain >= 0 else ''}${stock_gain:,.0f}</td>
                <td></td>
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
                <th>Symbol</th><th>Description</th><th>Contracts</th><th>Cost</th><th>Underlying</th><th>Day $</th><th>Est Value</th><th>Gain/Loss</th><th>Return</th>
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
    <div class="portfolio-content" id="{portfolio_id}" style="display: none;">
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
    today = datetime.now().strftime("%B %d, %Y")
    update_time = datetime.now().strftime("%I:%M %p")

    # Generate tab buttons
    tabs_html = ""
    for pid, p in PORTFOLIOS.items():
        tabs_html += f'<button class="tab-btn" data-portfolio="{pid}">{p["name"]}</button>'

    # Generate all portfolio contents
    portfolios_html = ""
    for pid, p in PORTFOLIOS.items():
        portfolios_html += generate_portfolio_html(pid, p, prices)

    # Calculate grand totals for overview
    grand_total = 0
    grand_day_change = 0
    for pid, p in PORTFOLIOS.items():
        cash = sum(p["cash"].values())
        stock_val = 0
        stock_day = 0
        for sym, data in p["holdings"].items():
            if data["qty"] == 0:
                continue
            pd = prices.get(sym)
            if pd:
                if data.get("currency") == "EUR":
                    stock_val += data["qty"] * pd["price"] * data.get("fx_rate", 1)
                    stock_day += data["qty"] * pd["day_change"] * data.get("fx_rate", 1)
                else:
                    stock_val += data["qty"] * pd["price"]
                    stock_day += data["qty"] * pd["day_change"]
        for sym, data in p.get("foreign", {}).items():
            pd = prices.get(sym)
            if pd:
                stock_val += (data["qty"] * pd["price"]) / data["fx_rate"]
                stock_day += (data["qty"] * pd["day_change"]) / data["fx_rate"]
        for sym, data in p.get("options", {}).items():
            pd = prices.get(sym)
            if pd:
                est_val, delta = calc_option_value(pd["price"], data["strike"], data["expiry"], data["contracts"])
                stock_val += est_val
                stock_day += pd["day_change"] * delta * 100 * data["contracts"]
        for sym, data in p.get("tbills", {}).items():
            stock_val += data["qty"] * 0.998
        grand_total += stock_val + cash
        grand_day_change += stock_day

    grand_day_class = "positive" if grand_day_change >= 0 else "negative"

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

        .grand-total {{
            text-align: center;
            margin-bottom: 20px;
            padding: 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
        }}
        .grand-total .label {{ color: #888; font-size: 0.9em; }}
        .grand-total .amount {{ font-size: 2em; color: #00d4ff; font-weight: bold; font-family: 'SF Mono', Monaco, monospace; }}
        .grand-total .day-change {{ font-size: 1em; margin-left: 15px; }}

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

        <div class="grand-total">
            <span class="label">COMBINED PORTFOLIO VALUE</span><br>
            <span class="amount">${grand_total:,.0f}</span>
            <span class="day-change {grand_day_class}">{'+' if grand_day_change >= 0 else ''}${grand_day_change:,.0f} today</span>
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

        function showPortfolio(id) {{
            contents.forEach(c => c.style.display = 'none');
            tabs.forEach(t => t.classList.remove('active'));
            document.getElementById(id).style.display = 'block';
            document.querySelector('[data-portfolio="' + id + '"]').classList.add('active');
        }}

        tabs.forEach(tab => {{
            tab.addEventListener('click', function() {{
                showPortfolio(this.getAttribute('data-portfolio'));
            }});
        }});

        // Show first portfolio by default
        showPortfolio('annabay');
    }});

    function updatePrices() {{
        const btn = document.querySelector('.update-btn');
        btn.textContent = 'Updating...';
        btn.disabled = true;
        fetch('/update')
            .then(r => r.text())
            .then(() => location.reload())
            .catch(() => {{
                btn.textContent = 'Update Prices';
                btn.disabled = false;
            }});
    }}
    </script>
</body>
</html>"""
    return html


class PortfolioHandler(http.server.BaseHTTPRequestHandler):
    cached_html = None

    def do_GET(self):
        if self.path == '/update' or self.path == '/' or self.path == '':
            print("Fetching prices...")
            prices = fetch_all_prices()
            if prices:
                PortfolioHandler.cached_html = generate_html(prices)

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
                if PortfolioHandler.cached_html:
                    self.wfile.write(PortfolioHandler.cached_html.encode())
                else:
                    self.wfile.write(b'Error fetching prices')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format%args}")


if __name__ == '__main__':
    print(f"Starting portfolio server on port {PORT}...")
    print("Fetching initial prices...")
    prices = fetch_all_prices()
    if prices:
        PortfolioHandler.cached_html = generate_html(prices)
        print("Initial prices loaded!")

    server = http.server.HTTPServer(('0.0.0.0', PORT), PortfolioHandler)
    print(f"Server running on http://0.0.0.0:{PORT}")
    server.serve_forever()
