"""Reproducible daily indicators and an explicitly heuristic scoring policy."""
import math
import statistics
from .contracts import number, FinanceError

WEIGHTS = {'fundamental': 20, 'growth': 20, 'valuation': 20, 'technical': 15,
           'momentum': 10, 'sentiment': 5, 'risk': 10}
SCORING_VERSION = 'finance-rules-1'
HORIZON = '3–12 months'


def ema_series(values, period):
    if len(values) < period:
        return []
    average = statistics.mean(values[:period])
    result = [average]
    alpha = 2 / (period + 1)
    for value in values[period:]:
        average = alpha * value + (1 - alpha) * average
        result.append(average)
    return result


def history_prices(history):
    bars = history.get('bars', [])
    if not bars:
        return [], []
    basis = history.get('price_basis', 'close')
    if basis not in {'close', 'adjusted_close'}:
        raise FinanceError('invalid_history')
    stamps = [number(bar.get('timestamp')) for bar in bars]
    values = [number(bar.get(basis)) for bar in bars]
    if any(stamp is None for stamp in stamps) or any(v is None or v <= 0 for v in values):
        raise FinanceError('invalid_history')
    if stamps != sorted(set(stamps)):
        raise FinanceError('invalid_history')
    return bars, values


def technicals(history):
    bars, values = history_prices(history)
    result = {'observations': len(values), 'price_basis': history.get('price_basis'),
              'as_of': bars[-1]['timestamp'] if bars else None,
              'sma': {}, 'ema': {}, 'rsi14': None, 'macd': None, 'volatility_annual': None,
              'trend': None, 'momentum_20': None, 'support': None, 'resistance': None}
    for period in (20, 50, 200):
        result['sma'][str(period)] = statistics.mean(values[-period:]) if len(values) >= period else None
        exponential = ema_series(values, period)
        result['ema'][str(period)] = exponential[-1] if exponential else None
    if len(values) >= 15:
        changes = [b - a for a, b in zip(values, values[1:])]
        gain = statistics.mean(max(change, 0) for change in changes[:14])
        loss = statistics.mean(max(-change, 0) for change in changes[:14])
        for change in changes[14:]:
            gain = (gain * 13 + max(change, 0)) / 14
            loss = (loss * 13 + max(-change, 0)) / 14
        result['rsi14'] = 50 if gain == loss == 0 else (100 if loss == 0 else 100 - 100 / (1 + gain / loss))
    if len(values) >= 34:
        short, long = ema_series(values, 12), ema_series(values, 26)
        macd = [a - b for a, b in zip(short[-len(long):], long)]
        signal = ema_series(macd, 9)[-1]
        result['macd'] = {'value': macd[-1], 'signal': signal, 'histogram': macd[-1] - signal}
    if len(values) >= 21:
        returns = [math.log(b / a) for a, b in zip(values[-21:-1], values[-20:])]
        result['volatility_annual'] = statistics.stdev(returns) * math.sqrt(252)
        result['momentum_20'] = values[-1] / values[-21] - 1
        # Trailing closing-price envelope, not a prediction or an intraday pivot.
        result['support'] = min(values[-20:])
        result['resistance'] = max(values[-20:])
        result['support_method'] = '20 completed daily closing prices; trailing envelope'
    sma = result['sma']['200']
    if sma is not None:
        result['trend'] = 'up' if values[-1] > sma else 'down' if values[-1] < sma else 'flat'
    return result


def performance(history):
    bars, values = history_prices(history)
    result = {}
    for label, days in {'1W': 7, '1M': 30, '3M': 91, '6M': 182, '1Y': 365}.items():
        eligible = [i for i, bar in enumerate(bars) if bar['timestamp'] <= bars[-1]['timestamp'] - days * 86400]
        index = eligible[-1] if eligible else None
        result[label] = {'percent': (values[-1] / values[index] - 1) * 100 if index is not None else None,
                         'from': bars[index]['timestamp'] if index is not None else None,
                         'to': bars[-1]['timestamp'] if bars else None,
                         'basis': history.get('price_basis')}
    return result


def _linear(value, low, high, inverse=False):
    value = number(value)
    if value is None:
        return None
    score = min(100, max(0, (value - low) / (high - low) * 100))
    return 100 - score if inverse else score


def _mean_if_complete(*values):
    return statistics.mean(values) if all(v is not None for v in values) else None


def recommendation(score):
    if score is None:
        return 'insufficient data'
    return next(label for threshold, label in ((85, 'Strong Buy'), (70, 'Buy'), (55, 'Hold'), (40, 'Reduce'), (0, 'Sell')) if score >= threshold)


def scoring(fundamentals, technical, quote, now, sentiment=None):
    f = fundamentals.get('values', {})
    pe = number(f.get('pe'))
    # Negative earnings are not a cheap positive P/E.
    valuation = _linear(pe, 10, 50, True) if pe is not None and pe > 0 else None
    subscores = {
        'fundamental': _mean_if_complete(_linear(f.get('profit_margin'), 0, .30), _linear(f.get('debt_to_equity'), 0, 200, True)),
        'growth': _mean_if_complete(_linear(f.get('revenue_growth'), -.10, .40), _linear(f.get('eps_growth'), -.20, .50)),
        'valuation': valuation,
        'technical': _mean_if_complete({'up': 80, 'flat': 50, 'down': 20}.get(technical.get('trend')),
                                      _linear(technical.get('rsi14'), 30, 70)),
        'momentum': _linear(technical.get('momentum_20'), -.15, .15),
        'sentiment': None,
        'risk': _linear(technical.get('volatility_annual'), .15, .80, True),
    }
    if sentiment and sentiment.get('source') and number(sentiment.get('as_of')) is not None and 0 <= now - sentiment['as_of'] < 7 * 86400:
        subscores['sentiment'] = _linear(sentiment.get('value'), -1, 1)
    covered = sum(WEIGHTS[key] for key, value in subscores.items() if value is not None)
    reasons = []
    if covered < 70 or any(subscores[k] is None for k in ('fundamental', 'growth', 'valuation')):
        reasons.append('insufficient_score_coverage')
    if quote.get('stale'):
        reasons.append('stale_quote')
    as_of = number(fundamentals.get('as_of'))
    if as_of is None or not 0 <= now - as_of <= 180 * 86400:
        reasons.append('fundamentals_date_unverified')
    technical_date = number(technical.get('as_of'))
    if technical_date is None or not 0 <= now - technical_date <= 7 * 86400:
        reasons.append('stale_history')
    confidence = covered / 100
    if quote.get('delay_status') == 'unknown':
        confidence *= .85
    if reasons:
        confidence = min(confidence, .35)
    score = None if reasons else round(sum(WEIGHTS[key] * value for key, value in subscores.items() if value is not None) / covered)
    return {'score': score, 'subscores': subscores, 'weights': dict(WEIGHTS), 'coverage': covered / 100,
            'recommendation': recommendation(score), 'confidence': round(confidence, 2),
            'confidence_meaning': 'data completeness and freshness, not probability of profit',
            'reasons': reasons, 'horizon': HORIZON, 'rules_version': SCORING_VERSION,
            'method': 'heuristic linear thresholds; uncalibrated, no backtested profitability claim'}


def cases(fundamentals, technical):
    f = fundamentals.get('values', {})
    bull, bear, risk = [], [], ['market_risk', 'heuristic_model_risk']
    if number(f.get('revenue_growth')) is not None:
        (bull if f['revenue_growth'] > 0 else bear).append('positive_revenue_growth' if f['revenue_growth'] > 0 else 'nonpositive_revenue_growth')
    if technical.get('trend'):
        (bull if technical['trend'] == 'up' else bear).append('above_sma200' if technical['trend'] == 'up' else 'not_above_sma200')
    if number(f.get('pe')) is not None and f['pe'] > 40:
        bear.append('high_pe')
        risk.append('valuation_risk')
    if number(technical.get('volatility_annual')) is not None and technical['volatility_annual'] > .50:
        risk.append('high_volatility')
    if not f:
        risk.append('missing_fundamentals')
    return {'bull': bull, 'bear': bear, 'risks': risk, 'catalysts': [],
            'catalysts_status': 'no independently verified forward event calendar'}
