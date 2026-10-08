"""Long-only decision support. No holdings leave the local process."""
import re
import statistics
from .contracts import FinanceError, number
from .analytics import history_prices


def parse_positions(prompt):
    # Explicit quantities only; never invent an equal-weight portfolio.
    positions = []
    for match in re.finditer(r'\b([A-Z][A-Z0-9-]{0,9}(?:\.[A-Z]{1,3})?)\s*[:=]\s*(\d+(?:[.,]\d+)?)\b', str(prompt)):
        positions.append({'symbol': match.group(1), 'quantity': float(match.group(2).replace(',', '.'))})
    return positions


def correlation(histories):
    returns = {}
    for ticker, history in histories.items():
        bars, values = history_prices(history)
        returns[ticker] = {bar['timestamp'] // 86400: values[i] / values[i - 1] - 1 for i, bar in enumerate(bars) if i}
    output = []
    for i, left in enumerate(returns):
        for right in list(returns)[i + 1:]:
            days = sorted(returns[left].keys() & returns[right].keys())[-252:]
            a, b = [returns[left][d] for d in days], [returns[right][d] for d in days]
            value = None
            if len(days) >= 30 and statistics.pstdev(a) > 0 and statistics.pstdev(b) > 0:
                value = statistics.correlation(a, b)
            output.append({'left': left, 'right': right, 'value': value, 'observations': len(days),
                           'method': 'Pearson aligned daily returns; minimum 30 observations'})
    return output


def analyze_portfolio(positions, reports, histories):
    if not isinstance(positions, list) or not 1 <= len(positions) <= 10:
        raise FinanceError('portfolio_positions_required')
    if len({r['instrument']['symbol'] for r in reports}) != len(reports):
        raise FinanceError('duplicate_positions')
    rows = []
    currencies = set()
    for position, report in zip(positions, reports):
        quantity = number(position.get('quantity'))
        if quantity is None or not 0 < quantity <= 1e12:
            raise FinanceError('invalid_quantity')
        quote = report['quote']
        value = quantity * quote['price']
        rate_info = (report.get('display_fx', {}).get('rates', {}) or {}).get(quote['currency'], {})
        eur_rate = number(rate_info.get('rate'))
        display_price = quote['price'] * eur_rate if eur_rate is not None else None
        display_value = value * eur_rate if eur_rate is not None else None
        rows.append({'instrument': report['instrument'], 'quantity': quantity, 'value': value,
                     'currency': quote['currency'], 'display_currency': 'EUR',
                     'display_rate': eur_rate, 'display_price': display_price, 'display_value': display_value,
                     'sector': report['fundamentals'].get('sector') or 'unknown', 'assessment': report['assessment'],
                     'stale': quote['stale'], 'timestamp': quote['timestamp'], 'price': quote['price'],
                     'risks': report['cases']['risks'], 'source': quote.get('source'), 'source_url': quote.get('source_url')})
        currencies.add(quote['currency'])
    display_total = (
        sum(row['display_value'] for row in rows)
        if rows and all(number(row.get('display_value')) is not None for row in rows)
        else None
    )
    if display_total is not None and display_total > 0:
        for row in rows:
            row['display_weight'] = row['display_value'] / display_total
    # Keep native totals only for one original currency. When every position has
    # an ECB display rate, derive cross-currency exposure from those EUR values.
    mixed = len(currencies) != 1
    native_total = None if mixed else sum(row['value'] for row in rows)
    has_eur_valuation = display_total is not None and display_total > 0
    if mixed and not has_eur_valuation:
        return {'positions': rows, 'status': 'currency_conversion_required', 'weights': None,
                'total_value': None, 'currency': None, 'display_total_value': None,
                'display_currency': 'EUR', 'sectors': None, 'max_weight': None,
                'concentration_hhi': None, 'concentration_risk': 'insufficient data',
                'correlations': correlation(histories), 'risk': 'insufficient data'}
    total = display_total if mixed else native_total
    if number(total) is None or total <= 0:
        raise FinanceError('invalid_portfolio_value')
    sectors = {}
    for row in rows:
        # Original quote and native position value remain unchanged.
        row['weight'] = row['display_value'] / total if mixed else row['value'] / total
        sectors[row['sector']] = sectors.get(row['sector'], 0) + row['weight']
    maximum = max(row['weight'] for row in rows)
    ranked = sorted((row for row in rows if row['assessment']['score'] is not None),
                    key=lambda row: row['assessment']['score'], reverse=True)
    return {'positions': rows, 'ranking': [row['instrument']['symbol'] for row in ranked],
            'ranking_status': 'complete' if len(ranked) == len(rows) else 'partial' if ranked else 'insufficient data',
            'status': 'partial' if any(row['stale'] for row in rows) else 'analyzed',
            'total_value': native_total, 'currency': None if mixed else next(iter(currencies)),
            'display_total_value': display_total, 'display_currency': 'EUR',
            'valuation_basis': 'indicative_ecb_eur' if mixed else 'original_listing_currency',
            'sectors': sectors, 'max_weight': maximum,
            'concentration_hhi': sum(row['weight'] ** 2 for row in rows),
            'concentration_risk': 'high' if maximum > .40 else 'moderate' if maximum > .20 else 'lower',
            'correlations': correlation(histories),
            'risk': 'insufficient data' if any(row['assessment']['score'] is None for row in rows) else 'heuristic',
            'limitations': ['long-only; ECB FX is presentation-only, no cash, tax or derivatives model',
                            'risk is not a calibrated portfolio VaR']}
