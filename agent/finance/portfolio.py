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
        rows.append({'instrument': report['instrument'], 'quantity': quantity, 'value': value,
                     'sector': report['fundamentals'].get('sector') or 'unknown', 'assessment': report['assessment'],
                     'stale': quote['stale'], 'timestamp': quote['timestamp'], 'price': quote['price'],
                     'risks': report['cases']['risks'], 'source': quote.get('source'), 'source_url': quote.get('source_url')})
        currencies.add(quote['currency'])
    # No implicit currency conversion or aggregation of incomparable amounts.
    if len(currencies) != 1:
        return {'positions': rows, 'status': 'currency_conversion_required', 'weights': None,
                'total_value': None, 'correlations': correlation(histories), 'risk': 'insufficient data'}
    total = sum(row['value'] for row in rows)
    if number(total) is None or total <= 0:
        raise FinanceError('invalid_portfolio_value')
    sectors = {}
    for row in rows:
        row['weight'] = row['value'] / total
        sectors[row['sector']] = sectors.get(row['sector'], 0) + row['weight']
    maximum = max(row['weight'] for row in rows)
    ranked = sorted((row for row in rows if row['assessment']['score'] is not None),
                    key=lambda row: row['assessment']['score'], reverse=True)
    return {'positions': rows, 'ranking': [row['instrument']['symbol'] for row in ranked],
            'ranking_status': 'complete' if len(ranked) == len(rows) else 'partial' if ranked else 'insufficient data',
            'status': 'partial' if any(row['stale'] for row in rows) else 'analyzed',
            'total_value': total, 'currency': next(iter(currencies)), 'sectors': sectors,
            'max_weight': maximum, 'concentration_hhi': sum(row['weight'] ** 2 for row in rows),
            'concentration_risk': 'high' if maximum > .40 else 'moderate' if maximum > .20 else 'lower',
            'correlations': correlation(histories), 'risk': 'insufficient data' if any(row['assessment']['score'] is None for row in rows) else 'heuristic',
            'limitations': ['long-only; no FX, cash, tax or derivatives model', 'risk is not a calibrated portfolio VaR']}
