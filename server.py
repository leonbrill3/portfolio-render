#!/usr/bin/env python3
"""Portfolio Server for Render - serves HTML and updates prices on demand"""

import http.server
import json
import urllib.request
import os
from datetime import datetime

PORT = int(os.environ.get("PORT", 10000))

# Portfolio holdings
HOLDINGS = {
    "RIG": {"name": "Transocean Ltd", "qty": 25000, "purchase_price": 3.90, "purchase_date": "16.12.2025", "cost": 97500},
    "PSH.AS": {"name": "Pershing Square Holdings", "qty": 3000, "purchase_price": 63.77, "purchase_date": "25.02.2026", "cost": 191310, "currency": "EUR", "fx_rate": 1.163},
    "MSFT": {"name": "Microsoft Corp", "qty": 300, "purchase_price": 375.00, "purchase_date": "24.03.2026", "cost": 112500},
    "CROX": {"name": "Crocs Inc", "qty": 1500, "purchase_price": 76.00, "purchase_date": "19.03.2026", "cost": 114000},
    "CNSWF": {"name": "Constellation Software", "qty": 100, "purchase_price": 2478.99, "purchase_date": "19.03.2026", "cost": 247899},
    "PDD": {"name": "PDD Holdings", "qty": 1000, "purchase_price": 114.00, "purchase_date": "10.12.2025", "cost": 114000},
    "UBER": {"name": "Uber Technologies", "qty": 3000, "purchase_price": 78.17, "purchase_date": "11.02.2026", "cost": 234510},
    "AMR": {"name": "Alpha Metallurgical Resources", "qty": 1750, "purchase_price": 159.00, "purchase_date": "26.02.2026", "cost": 278250},
    "BN": {"name": "Brookfield Corp", "qty": 6000, "purchase_price": 45.20, "purchase_date": "10.10.2025", "cost": 271200},
    "CNR": {"name": "Core Natural Resources", "qty": 1000, "purchase_price": 75.50, "purchase_date": "31.10.2025", "cost": 75500},
    "MIAX": {"name": "Miami International Holdings", "qty": 2500, "purchase_price": 42.00, "purchase_date": "26.01.2026", "cost": 105000},
    "SNAP": {"name": "Snap Inc", "qty": 20000, "purchase_price": 4.00, "purchase_date": "28.03.2026", "cost": 80000},
}

OPTIONS = {
    "WDAY": {"name": "Call Workday-A JAN28 $150", "contracts": 25, "cost_price": 40.00, "cost": 100000, "strike": 150, "expiry": "21.01.2028", "trade_date": "11.02.2026"},
    "SOC": {"name": "Call Sable Offshore JAN27 $12.5", "contracts": 100, "cost_price": 6.70, "cost": 67000, "strike": 12.5, "expiry": "15.01.2027", "trade_date": "15.10.2025"},
}

FOREIGN_HOLDINGS = {
    "DBO.TO": {"name": "D-Box Technologies (CAD)", "qty": 125000, "purchase_price": 0.80, "purchase_date": "11.02.2026", "cost": 73893, "currency": "CAD", "fx_rate": 1.376},
    "TGO.TO": {"name": "Terago Inc (CAD)", "qty": 150000, "purchase_price": 0.90, "purchase_date": "01.04.2026", "cost": 97816, "currency": "CAD", "fx_rate": 1.376},
    "1970.HK": {"name": "IMAX China Holding (HKD)", "qty": 13000, "purchase_price": 7.60, "purchase_date": "13.10.2025", "cost": 12782, "currency": "HKD", "fx_rate": 7.8266},
}

CASH = {"USD": 162163, "EUR": 201350}

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
    all_symbols = list(HOLDINGS.keys()) + list(OPTIONS.keys()) + list(FOREIGN_HOLDINGS.keys())
    for symbol in all_symbols:
        data = fetch_price_yahoo(symbol)
        if data:
            prices[symbol] = data
            print(f"  {symbol}: {data['price']}")
    return prices

def generate_html(prices):
    today = datetime.now().strftime("%B %d, %Y")
    update_time = datetime.now().strftime("%I:%M %p")

    stock_rows = []
    total_stock_cost = 0
    total_stock_value = 0
    total_day_gain = 0
    gainers = []
    losers = []

    for symbol, data in HOLDINGS.items():
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
        return_pct = (gain_loss / data["cost"]) * 100

        total_stock_cost += data["cost"]
        total_stock_value += current_value
        total_day_gain += day_gain

        gain_class = "positive" if gain_loss >= 0 else "negative"
        gain_sign = "+" if gain_loss >= 0 else ""
        day_class = "positive" if day_change >= 0 else "negative"
        day_sign = "+" if day_change >= 0 else ""

        if gain_loss >= 0:
            gainers.append((symbol, data["name"], gain_loss, return_pct))
        else:
            losers.append((symbol, data["name"], gain_loss, return_pct))

        stock_rows.append(f"""
                <tr>
                    <td class="ticker" data-value="{symbol}">{symbol}</td>
                    <td data-value="{data["name"]}">{data["name"]}</td>
                    <td class="number" data-value="{data["qty"]}">{data["qty"]:,}</td>
                    <td data-value="{data["purchase_date"]}">{data["purchase_date"]}</td>
                    <td class="number" data-value="{data["purchase_price"]}">{currency_symbol}{data["purchase_price"]:,.2f}</td>
                    <td class="number" data-value="{data["cost"]}">${data["cost"]:,}</td>
                    <td class="number" data-value="{current_price}">{currency_symbol}{current_price:,.2f}</td>
                    <td class="number {day_class}" data-value="{day_change}">{day_sign}{currency_symbol}{abs(day_change):,.2f}</td>
                    <td class="number {day_class}" data-value="{day_change_pct}">{day_sign}{day_change_pct:.2f}%</td>
                    <td class="number" data-value="{current_value}">${current_value:,.0f}</td>
                    <td class="number {day_class}" data-value="{day_gain}">{day_sign}${abs(day_gain):,.0f}</td>
                    <td class="number {gain_class}" data-value="{gain_loss}">{gain_sign}${gain_loss:,.0f}</td>
                    <td class="{gain_class} percent" data-value="{return_pct}">{gain_sign}{return_pct:.2f}%</td>
                </tr>""")

    for symbol, data in FOREIGN_HOLDINGS.items():
        price_data = prices.get(symbol)
        if not price_data:
            continue

        current_price = price_data["price"]
        day_change = price_data["day_change"]
        day_change_pct = price_data["day_change_pct"]

        current_value_usd = (data["qty"] * current_price) / data["fx_rate"]
        day_gain_usd = (data["qty"] * day_change) / data["fx_rate"]
        gain_loss = current_value_usd - data["cost"]
        return_pct = (gain_loss / data["cost"]) * 100

        total_stock_cost += data["cost"]
        total_stock_value += current_value_usd
        total_day_gain += day_gain_usd

        gain_class = "positive" if gain_loss >= 0 else "negative"
        gain_sign = "+" if gain_loss >= 0 else ""
        day_class = "positive" if day_change >= 0 else "negative"
        day_sign = "+" if day_change >= 0 else ""

        currency_symbol = "C$" if data["currency"] == "CAD" else "HK$"

        if gain_loss >= 0:
            gainers.append((symbol, data["name"], gain_loss, return_pct))
        else:
            losers.append((symbol, data["name"], gain_loss, return_pct))

        stock_rows.append(f"""
                <tr>
                    <td class="ticker" data-value="{symbol}">{symbol}</td>
                    <td data-value="{data["name"]}">{data["name"]}</td>
                    <td class="number" data-value="{data["qty"]}">{data["qty"]:,}</td>
                    <td data-value="{data["purchase_date"]}">{data["purchase_date"]}</td>
                    <td class="number" data-value="{data["purchase_price"]}">{currency_symbol}{data["purchase_price"]:.2f}</td>
                    <td class="number" data-value="{data["cost"]}">${data["cost"]:,}</td>
                    <td class="number" data-value="{current_price}">{currency_symbol}{current_price:.2f}</td>
                    <td class="number {day_class}" data-value="{day_change}">{day_sign}{currency_symbol}{abs(day_change):.2f}</td>
                    <td class="number {day_class}" data-value="{day_change_pct}">{day_sign}{day_change_pct:.2f}%</td>
                    <td class="number" data-value="{current_value_usd}">${current_value_usd:,.0f}</td>
                    <td class="number {day_class}" data-value="{day_gain_usd}">{day_sign}${abs(day_gain_usd):,.0f}</td>
                    <td class="number {gain_class}" data-value="{gain_loss}">{gain_sign}${gain_loss:,.0f}</td>
                    <td class="{gain_class} percent" data-value="{return_pct}">{gain_sign}{return_pct:.2f}%</td>
                </tr>""")

    option_rows = []
    total_option_cost = 0
    total_option_value = 0
    total_option_day_gain = 0

    for symbol, data in OPTIONS.items():
        price_data = prices.get(symbol)
        if not price_data:
            continue

        underlying_price = price_data["price"]
        underlying_day_change = price_data["day_change"]

        intrinsic_per_share = max(0, underlying_price - data["strike"])
        intrinsic_value = intrinsic_per_share * 100 * data["contracts"]

        expiry_parts = data["expiry"].split(".")
        expiry_date = datetime(int(expiry_parts[2]), int(expiry_parts[1]), int(expiry_parts[0]))
        days_to_expiry = (expiry_date - datetime.now()).days

        if days_to_expiry > 365:
            moneyness = underlying_price / data["strike"]
            if moneyness < 0.7:
                time_value_per_share = data["strike"] * 0.05
            elif moneyness < 0.9:
                time_value_per_share = data["strike"] * 0.12
            elif moneyness < 1.1:
                time_value_per_share = data["strike"] * 0.20
            else:
                time_value_per_share = data["strike"] * 0.15
        elif days_to_expiry > 180:
            moneyness = underlying_price / data["strike"]
            if moneyness < 0.8:
                time_value_per_share = data["strike"] * 0.03
            elif moneyness < 1.0:
                time_value_per_share = data["strike"] * 0.08
            else:
                time_value_per_share = data["strike"] * 0.10
        else:
            if intrinsic_per_share > 0:
                time_value_per_share = data["strike"] * 0.02
            else:
                time_value_per_share = data["strike"] * 0.01

        time_value = time_value_per_share * 100 * data["contracts"]
        est_value = intrinsic_value + time_value

        if intrinsic_per_share > 0:
            delta = min(0.85, 0.5 + (intrinsic_per_share / data["strike"]) * 0.5)
        else:
            delta = max(0.15, 0.5 - abs(underlying_price - data["strike"]) / data["strike"] * 0.5)
        option_day_gain = underlying_day_change * delta * 100 * data["contracts"]

        gain_loss = est_value - data["cost"]
        return_pct = (gain_loss / data["cost"]) * 100

        total_option_cost += data["cost"]
        total_option_value += est_value
        total_option_day_gain += option_day_gain

        gain_class = "positive" if gain_loss >= 0 else "negative"
        gain_sign = "+" if gain_loss >= 0 else ""
        day_class = "positive" if option_day_gain >= 0 else "negative"
        day_sign = "+" if option_day_gain >= 0 else ""

        itm_otm = "ITM" if underlying_price > data["strike"] else "OTM"

        if gain_loss >= 0:
            gainers.append((f"{symbol} Call", data["name"], gain_loss, return_pct))
        else:
            losers.append((f"{symbol} Call", data["name"], gain_loss, return_pct))

        option_rows.append(f"""
                <tr>
                    <td class="ticker" data-value="{symbol}">{symbol}</td>
                    <td data-value="{data["name"]}">{data["name"]}</td>
                    <td class="number" data-value="{data["contracts"]}">{data["contracts"]}</td>
                    <td data-value="{data["trade_date"]}">{data["trade_date"]}</td>
                    <td data-value="{data["expiry"]}">{data["expiry"]}</td>
                    <td class="number" data-value="{data["cost_price"]}">${data["cost_price"]:.2f}</td>
                    <td class="number" data-value="{data["cost"]}">${data["cost"]:,}</td>
                    <td class="number" data-value="{underlying_price}">${underlying_price:.2f} ({itm_otm})</td>
                    <td class="number {day_class}" data-value="{underlying_day_change}">{'+' if underlying_day_change >= 0 else ''}${underlying_day_change:.2f}</td>
                    <td class="number" data-value="{est_value}">${est_value:,.0f}</td>
                    <td class="number {day_class}" data-value="{option_day_gain}">{day_sign}${abs(option_day_gain):,.0f}</td>
                    <td class="number {gain_class}" data-value="{gain_loss}">{gain_sign}${gain_loss:,.0f}</td>
                    <td class="{gain_class} percent" data-value="{return_pct}">{gain_sign}{return_pct:.2f}%</td>
                </tr>""")

    stock_gain = total_stock_value - total_stock_cost
    stock_return = (stock_gain / total_stock_cost * 100) if total_stock_cost > 0 else 0
    option_gain = total_option_value - total_option_cost
    option_return = (option_gain / total_option_cost * 100) if total_option_cost > 0 else 0

    total_cash = sum(CASH.values())
    total_portfolio = total_stock_value + total_option_value + total_cash
    total_investment_cost = total_stock_cost + total_option_cost
    net_gain = stock_gain + option_gain
    net_return = (net_gain / total_investment_cost * 100) if total_investment_cost > 0 else 0

    stock_gain_class = "positive" if stock_gain >= 0 else "negative"
    option_gain_class = "positive" if option_gain >= 0 else "negative"
    net_gain_class = "positive" if net_gain >= 0 else "negative"

    gainers.sort(key=lambda x: x[2], reverse=True)
    losers.sort(key=lambda x: x[2])

    gainer_rows = ""
    for sym, name, gl, ret in gainers[:5]:
        gainer_rows += f'<tr><td class="ticker">{sym}</td><td>{name}</td><td class="number positive">+${gl:,.0f}</td><td class="positive">+{ret:.2f}%</td></tr>\n'

    loser_rows = ""
    for sym, name, gl, ret in losers[:5]:
        loser_rows += f'<tr><td class="ticker">{sym}</td><td>{name}</td><td class="number negative">${gl:,.0f}</td><td class="negative">{ret:.2f}%</td></tr>\n'

    total_all_day_gain = total_day_gain + total_option_day_gain
    day_gain_class = "positive" if total_all_day_gain >= 0 else "negative"
    day_pct = (total_all_day_gain / (total_portfolio - total_all_day_gain) * 100) if total_portfolio > 0 else 0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portfolio Analysis - Annabay</title>
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
        h1 {{ text-align: center; color: #00d4ff; margin-bottom: 10px; font-size: 2.5em; }}
        .update-time {{ text-align: center; color: #00ff88; margin-bottom: 30px; font-size: 0.9em; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 25px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .card h3 {{ color: #888; font-size: 0.9em; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }}
        .card .value {{ font-size: 1.8em; font-weight: bold; }}
        .card .value.positive {{ color: #00ff88; }}
        .card .value.negative {{ color: #ff4757; }}
        .card .value.neutral {{ color: #00d4ff; }}
        .table-container {{ overflow-x: auto; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.03);
            border-radius: 15px;
            overflow: hidden;
            margin-bottom: 30px;
            min-width: 1200px;
        }}
        th, td {{ padding: 12px 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.05); }}
        th {{
            background: rgba(0,212,255,0.1);
            color: #00d4ff;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75em;
            cursor: pointer;
            user-select: none;
            white-space: nowrap;
            position: relative;
        }}
        th:hover {{ background: rgba(0,212,255,0.2); }}
        th.sorted-asc::after {{ content: ' ▲'; font-size: 0.8em; }}
        th.sorted-desc::after {{ content: ' ▼'; font-size: 0.8em; }}
        tr:hover {{ background: rgba(255,255,255,0.05); }}
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff4757; }}
        .ticker {{ font-weight: bold; color: #00d4ff; }}
        .section-title {{
            color: #00d4ff;
            margin: 30px 0 15px 0;
            font-size: 1.5em;
            border-bottom: 2px solid rgba(0,212,255,0.3);
            padding-bottom: 10px;
        }}
        .number {{ font-family: 'SF Mono', Monaco, Consolas, monospace; font-size: 0.9em; }}
        .date-info {{ text-align: center; color: #666; font-size: 0.9em; margin-top: 20px; }}
        .percent {{ font-size: 0.85em; }}
        .update-btn {{
            background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
            border: none;
            color: #1a1a2e;
            padding: 12px 30px;
            font-size: 1em;
            font-weight: bold;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        .update-btn:hover {{
            transform: scale(1.05);
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.5);
        }}
        .header-row {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 20px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }}
        @media (max-width: 768px) {{
            th, td {{ padding: 8px 5px; font-size: 0.75em; }}
            h1 {{ font-size: 1.8em; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Portfolio Analysis</h1>
        <div class="header-row">
            <p class="update-time" style="margin: 0;">Last Updated: {today} at {update_time}</p>
            <button class="update-btn" onclick="updatePrices()">Update Prices</button>
        </div>

        <div class="summary-cards">
            <div class="card">
                <h3>Total Portfolio Value</h3>
                <div class="value neutral number">${total_portfolio:,.0f}</div>
            </div>
            <div class="card">
                <h3>Today's Gain/Loss</h3>
                <div class="value {day_gain_class} number">{'+' if total_all_day_gain >= 0 else ''}${total_all_day_gain:,.0f} <span style="font-size: 0.6em;">({'+' if day_pct >= 0 else ''}{day_pct:.2f}%)</span></div>
            </div>
            <div class="card">
                <h3>Total Investment Cost</h3>
                <div class="value neutral number">${total_investment_cost:,}</div>
            </div>
            <div class="card">
                <h3>Total Gain/Loss</h3>
                <div class="value {net_gain_class} number">{'+' if net_gain >= 0 else ''}${net_gain:,.0f}</div>
            </div>
            <div class="card">
                <h3>Total Return</h3>
                <div class="value {net_gain_class} number">{'+' if net_return >= 0 else ''}{net_return:.2f}%</div>
            </div>
        </div>

        <h2 class="section-title">Stocks & Similar Instruments</h2>
        <div class="table-container">
        <table id="stocks-table" class="sortable">
            <thead>
                <tr>
                    <th data-col="0">Symbol</th>
                    <th data-col="1">Security</th>
                    <th data-col="2">Qty</th>
                    <th data-col="3">Purchase Date</th>
                    <th data-col="4">Buy Price</th>
                    <th data-col="5">Cost</th>
                    <th data-col="6">Price</th>
                    <th data-col="7">Day Chg</th>
                    <th data-col="8">Day %</th>
                    <th data-col="9">Value</th>
                    <th data-col="10">Day Gain</th>
                    <th data-col="11">Gain/Loss</th>
                    <th data-col="12">Return %</th>
                </tr>
            </thead>
            <tbody>
                {''.join(stock_rows)}
            </tbody>
            <tfoot>
                <tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                    <td colspan="5">TOTAL STOCKS</td>
                    <td class="number">${total_stock_cost:,}</td>
                    <td colspan="3"></td>
                    <td class="number">${total_stock_value:,.0f}</td>
                    <td class="number {day_gain_class}">{'+' if total_day_gain >= 0 else ''}${total_day_gain:,.0f}</td>
                    <td class="number {stock_gain_class}">{'+' if stock_gain >= 0 else ''}${stock_gain:,.0f}</td>
                    <td class="{stock_gain_class} percent">{'+' if stock_return >= 0 else ''}{stock_return:.2f}%</td>
                </tr>
            </tfoot>
        </table>
        </div>

        <h2 class="section-title">Options (Derivatives)</h2>
        <div class="table-container">
        <table id="options-table" class="sortable">
            <thead>
                <tr>
                    <th data-col="0">Symbol</th>
                    <th data-col="1">Description</th>
                    <th data-col="2">Contracts</th>
                    <th data-col="3">Trade Date</th>
                    <th data-col="4">Expiry</th>
                    <th data-col="5">Cost Price</th>
                    <th data-col="6">Cost</th>
                    <th data-col="7">Underlying</th>
                    <th data-col="8">Day Chg</th>
                    <th data-col="9">Est. Value</th>
                    <th data-col="10">Day Gain</th>
                    <th data-col="11">Gain/Loss</th>
                    <th data-col="12">Return %</th>
                </tr>
            </thead>
            <tbody>
                {''.join(option_rows)}
            </tbody>
            <tfoot>
                <tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                    <td colspan="6">TOTAL OPTIONS</td>
                    <td class="number">${total_option_cost:,}</td>
                    <td colspan="2"></td>
                    <td class="number">${total_option_value:,.0f}</td>
                    <td class="number {day_gain_class}">{'+' if total_option_day_gain >= 0 else ''}${total_option_day_gain:,.0f}</td>
                    <td class="number {option_gain_class}">{'+' if option_gain >= 0 else ''}${option_gain:,.0f}</td>
                    <td class="{option_gain_class} percent">{'+' if option_return >= 0 else ''}{option_return:.2f}%</td>
                </tr>
            </tfoot>
        </table>
        </div>

        <h2 class="section-title">Cash Holdings</h2>
        <table>
            <thead>
                <tr><th>Currency</th><th>Value (USD)</th></tr>
            </thead>
            <tbody>
                <tr><td class="ticker">USD</td><td class="number">${CASH['USD']:,}</td></tr>
                <tr><td class="ticker">EUR</td><td class="number">${CASH['EUR']:,}</td></tr>
            </tbody>
            <tfoot>
                <tr style="background: rgba(0,212,255,0.1); font-weight: bold;">
                    <td>TOTAL CASH</td>
                    <td class="number">${total_cash:,}</td>
                </tr>
            </tfoot>
        </table>

        <h2 class="section-title">Top Gainers</h2>
        <table>
            <thead><tr><th>Symbol</th><th>Security</th><th>Gain/Loss</th><th>Return %</th></tr></thead>
            <tbody>{gainer_rows}</tbody>
        </table>

        <h2 class="section-title">Top Losers</h2>
        <table>
            <thead><tr><th>Symbol</th><th>Security</th><th>Gain/Loss</th><th>Return %</th></tr></thead>
            <tbody>{loser_rows}</tbody>
        </table>

        <p class="date-info">
            <strong>Prices Updated:</strong> {today} at {update_time}<br>
            <em>Data from Yahoo Finance. Options estimated using intrinsic value + time value. Click column headers to sort.</em>
        </p>
    </div>

    <script>
    document.addEventListener('DOMContentLoaded', function() {{
        document.querySelectorAll('table.sortable').forEach(function(table) {{
            const headers = table.querySelectorAll('th[data-col]');
            let currentSort = {{ col: null, asc: true }};

            headers.forEach(function(header) {{
                header.addEventListener('click', function() {{
                    const col = parseInt(this.getAttribute('data-col'));
                    const tbody = table.querySelector('tbody');
                    const rows = Array.from(tbody.querySelectorAll('tr'));

                    if (currentSort.col === col) {{
                        currentSort.asc = !currentSort.asc;
                    }} else {{
                        currentSort.col = col;
                        currentSort.asc = true;
                    }}

                    headers.forEach(h => h.classList.remove('sorted-asc', 'sorted-desc'));
                    this.classList.add(currentSort.asc ? 'sorted-asc' : 'sorted-desc');

                    rows.sort(function(a, b) {{
                        const aCell = a.cells[col];
                        const bCell = b.cells[col];
                        let aVal = aCell.getAttribute('data-value') || aCell.textContent.trim();
                        let bVal = bCell.getAttribute('data-value') || bCell.textContent.trim();

                        const aNum = parseFloat(aVal.replace(/[,$%]/g, ''));
                        const bNum = parseFloat(bVal.replace(/[,$%]/g, ''));

                        if (!isNaN(aNum) && !isNaN(bNum)) {{
                            return currentSort.asc ? aNum - bNum : bNum - aNum;
                        }}
                        return currentSort.asc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
                    }});

                    rows.forEach(row => tbody.appendChild(row));
                }});
            }});
        }});
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
