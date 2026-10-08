"""Keyless Yahoo market data with bounded transport and identity-safe fallbacks.

The endpoints are unofficial and may restrict access. Missing data stays missing.
No user URLs, cookies, credentials, portfolio sizes or prompts are sent upstream.
"""
from collections import OrderedDict
from copy import deepcopy
from functools import wraps
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .contracts import FinanceError, Instrument, freshness, number, symbol, validate_identity
from backend.finance_intent import ALIASES

EXCHANGES = {'NMS': 'NASDAQ', 'NGM': 'NASDAQ', 'NCM': 'NASDAQ', 'NYQ': 'NYSE',
             'NasdaqGS': 'NASDAQ', 'NasdaqGM': 'NASDAQ', 'NasdaqCM': 'NASDAQ', 'NYSE': 'NYSE',
             'PCX': 'NYSE ARCA', 'GER': 'XETRA', 'STU': 'STUTTGART', 'LSE': 'LSE'}
TTL = {'quote': 30, 'history': 300, 'fundamentals': 3600, 'news': 600, 'resolve': 86400}
MAX_BYTES = 2_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise FinanceError('provider_redirect_blocked')


def fetch_json(url, timeout):
    request = Request(url, headers={'User-Agent': 'MLX-Nobby/Finance', 'Accept': 'application/json'})
    with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise FinanceError('provider_response_too_large')
    return json.loads(raw)


def provider_contract(function):
    @wraps(function)
    def validated(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (KeyError, IndexError, TypeError, AttributeError, OverflowError):
            raise FinanceError('invalid_provider_response') from None
    return validated


class YahooProvider:
    name = 'Yahoo Finance'

    def __init__(self, transport=fetch_json, clock=time.time, monotonic=time.monotonic):
        self.transport, self.clock, self.monotonic = transport, clock, monotonic
        self._cache = OrderedDict()
        self._failures = OrderedDict()
        self._lock = threading.RLock()
        self._cooldown = 0
        self._requests = []

    def _failure(self, key, code):
        with self._lock:
            self._failures[key] = (self.monotonic() + min(60, TTL[key[0]]), code)
            while len(self._failures) > 256:
                self._failures.popitem(last=False)
        return FinanceError(code)

    def _get(self, kind, path, parameters, host='query1.finance.yahoo.com'):
        # Only constant hosts and validated symbol components reach this method.
        url = 'https://' + host + path + '?' + urlencode(parameters)
        key = (kind, url)
        with self._lock:
            cached = self._cache.get(key)
            now = self.monotonic()
            if cached and now - cached[0] < TTL[kind]:
                self._cache.move_to_end(key)
                return deepcopy(cached[1])
            failed = self._failures.get(key)
            if failed and now < failed[0]:
                raise FinanceError(failed[1])
        result = None
        for attempt in range(2):
            with self._lock:
                now = self.monotonic()
                self._requests = [stamp for stamp in self._requests if now - stamp < 60]
                if now < self._cooldown or len(self._requests) >= 60:
                    raise FinanceError('provider_rate_limited')
                self._requests.append(now)
            try:
                result = self.transport(url, 4)
                if not isinstance(result, dict):
                    raise FinanceError('invalid_provider_response')
                break
            except HTTPError as exc:
                if exc.code == 429:
                    with self._lock:
                        self._cooldown = self.monotonic() + 60
                    raise FinanceError('provider_rate_limited') from None
                if exc.code < 500 or attempt:
                    raise self._failure(key, 'provider_unavailable') from None
            except (URLError, TimeoutError, OSError):
                if attempt:
                    raise self._failure(key, 'provider_timeout') from None
            except (ValueError, TypeError) as exc:
                if isinstance(exc, FinanceError):
                    raise
                raise FinanceError('invalid_provider_response') from None
        with self._lock:
            self._failures.pop(key, None)
            self._cache[key] = (self.monotonic(), deepcopy(result))
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
        return result

    def _chart(self, ticker):
        data = self._get('history', '/v8/finance/chart/' + quote(symbol(ticker), safe=''),
                         {'range': '2y', 'interval': '1d', 'includePrePost': 'false'})
        try:
            chart = data['chart']
            if chart.get('error'):
                raise FinanceError('symbol_not_found')
            result = chart['result'][0]
            if not isinstance(result, dict):
                raise TypeError()
            return result
        except (KeyError, IndexError, TypeError):
            raise FinanceError('invalid_provider_response') from None

    @provider_contract
    def resolve(self, query, exchange=None, currency=None):
        query = str(query).strip()
        ticker = ALIASES.get(query.lower())
        if not ticker:
            # Explicit tickers resolve through chart; company names through unique search results.
            try:
                ticker = symbol(query)
            except FinanceError:
                if len(query) > 80 or not query or any(c in query for c in '\n\r<>/\\'):
                    raise FinanceError('invalid_symbol') from None
                data = self._get('resolve', '/v1/finance/search', {'q': query, 'quotesCount': 10, 'newsCount': 0})
                candidates = [item for item in data.get('quotes', []) if item.get('quoteType') in ('EQUITY', 'ETF')
                              and (not exchange or EXCHANGES.get(item.get('exchange'), item.get('exchange')) == exchange)]
                if len(candidates) != 1:
                    raise FinanceError('ambiguous_symbol')
                ticker = symbol(candidates[0]['symbol'])
        meta = self._chart(ticker).get('meta', {})
        actual = symbol(meta.get('symbol', ''))
        if actual != ticker or meta.get('instrumentType') not in ('EQUITY', 'ETF', 'INDEX'):
            raise FinanceError('provider_identity_conflict')
        instrument = Instrument(actual, EXCHANGES.get(meta.get('exchangeName'), meta.get('exchangeName') or ''),
                                meta.get('currency') or '', str(meta.get('longName') or meta.get('shortName') or actual)[:160])
        if (exchange and instrument.exchange != exchange) or (currency and instrument.currency != currency):
            raise FinanceError('market_selection_required')
        return instrument

    @provider_contract
    def quote(self, instrument):
        data = self._get('quote', '/v8/finance/chart/' + quote(instrument.symbol, safe=''),
                         {'range': '1d', 'interval': '1m', 'includePrePost': 'true'})
        try:
            result = data['chart']['result'][0]
            meta = result['meta']
        except (KeyError, TypeError, IndexError):
            raise FinanceError('provider_unavailable') from None
        base = dict(symbol=meta.get('symbol'), exchange=EXCHANGES.get(meta.get('exchangeName'), meta.get('exchangeName')),
                    currency=meta.get('currency'))
        validate_identity(instrument, base)
        price, stamp, session = number(meta.get('regularMarketPrice')), number(meta.get('regularMarketTime')), 'regular'
        # Never label regularMarketPrice as extended trading. Use extended metadata only if both fields exist.
        for prefix, label in (('pre', 'pre-market'), ('post', 'after-hours')):
            candidate, timestamp = number(meta.get(prefix + 'MarketPrice')), number(meta.get(prefix + 'MarketTime'))
            if candidate is not None and timestamp is not None and stamp is not None and timestamp > stamp:
                price, stamp, session = candidate, timestamp, label
        basis = 'last_reported_trade'
        periods = meta.get('currentTradingPeriod', {})
        closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
        # Yahoo does not always include extended quote metadata. Its completed
        # minute candles may still provide an explicitly identifiable session.
        for timestamp, close in zip(result.get('timestamp', []), closes):
            timestamp, close = number(timestamp), number(close)
            if timestamp is None or close is None or close <= 0 or timestamp + 60 > self.clock():
                continue
            if stamp is not None and timestamp <= stamp:
                continue
            for key, label in (('pre', 'pre-market'), ('post', 'after-hours')):
                start, end = number(periods.get(key, {}).get('start')), number(periods.get(key, {}).get('end'))
                if start is not None and end is not None and start <= timestamp < end:
                    price, stamp, session, basis = close, timestamp, label, 'completed_minute_close'
        if price is None or price <= 0:
            raise FinanceError('quote_missing')
        previous = number(meta.get('previousClose')) or number(meta.get('chartPreviousClose'))
        now = self.clock()
        regular = meta.get('currentTradingPeriod', {}).get('regular', {})
        start, end = number(regular.get('start')), number(regular.get('end'))
        market_open = bool(start is not None and end is not None and start <= now < end)
        return freshness(base | dict(price=price, timestamp=stamp, session=session, market_open=market_open,
             regular_price=number(meta.get('regularMarketPrice')), price_basis=basis,
             timestamp_basis='bar_start' if basis == 'completed_minute_close' else 'reported_trade_time',
             day_change_percent=(price / previous - 1) * 100 if previous and previous > 0 else None,
             fifty_two_week_high=number(meta.get('fiftyTwoWeekHigh')), fifty_two_week_low=number(meta.get('fiftyTwoWeekLow')),
             delay_status='unknown', source=self.name, source_url='https://finance.yahoo.com/quote/' + instrument.symbol,
             retrieved_at=now), now)

    @provider_contract
    def history(self, instrument):
        chart = self._chart(instrument.symbol)
        meta = chart.get('meta', {})
        validate_identity(instrument, dict(symbol=meta.get('symbol'), currency=meta.get('currency'),
                          exchange=EXCHANGES.get(meta.get('exchangeName'), meta.get('exchangeName'))))
        try:
            quotes = chart['indicators']['quote'][0]
            adjusted = chart.get('indicators', {}).get('adjclose', [{}])[0].get('adjclose') or []
            bars = []
            for i, timestamp in enumerate(chart.get('timestamp', [])):
                close = number(quotes.get('close', [])[i])
                adj = number(adjusted[i]) if i < len(adjusted) else None
                stamp = number(timestamp)
                if close and close > 0 and stamp and stamp <= self.clock():
                    # In-progress daily bars are excluded from deterministic daily indicators.
                    end = number(meta.get('currentTradingPeriod', {}).get('regular', {}).get('end'))
                    if end and self.clock() < end and stamp >= end - 86400:
                        continue
                    bars.append({'timestamp': stamp, 'close': close, 'adjusted_close': adj})
        except (IndexError, TypeError, KeyError):
            raise FinanceError('invalid_provider_response') from None
        if len({bar['timestamp'] for bar in bars}) != len(bars):
            raise FinanceError('invalid_history')
        return instrument.as_dict() | dict(bars=sorted(bars, key=lambda bar: bar['timestamp']), source=self.name,
            source_url='https://finance.yahoo.com/quote/' + instrument.symbol + '/history/', retrieved_at=self.clock(),
            price_basis='adjusted_close' if bars and all(b['adjusted_close'] is not None for b in bars) else 'close')

    @provider_contract
    def fundamentals(self, instrument):
        data = self._get('fundamentals', '/v10/finance/quoteSummary/' + quote(instrument.symbol, safe=''),
                         {'modules': 'price,summaryDetail,defaultKeyStatistics,financialData,assetProfile'}, 'query2.finance.yahoo.com')
        try:
            result = data['quoteSummary']['result'][0]
            price = result['price']
            validate_identity(instrument, dict(symbol=price.get('symbol'), currency=price.get('currency'),
                exchange=EXCHANGES.get(price.get('exchange') or price.get('exchangeName'), price.get('exchange') or price.get('exchangeName'))))
        except (KeyError, TypeError, IndexError):
            raise FinanceError('fundamentals_unavailable') from None
        financial = result.get('financialData', {})
        reporting_currency = financial.get('financialCurrency')
        fields = {'market_cap': ('price', 'marketCap'), 'revenue': ('financialData', 'totalRevenue'),
            'revenue_growth': ('financialData', 'revenueGrowth'), 'eps': ('defaultKeyStatistics', 'trailingEps'),
            'eps_growth': ('financialData', 'earningsGrowth'), 'free_cash_flow': ('financialData', 'freeCashflow'),
            'profit_margin': ('financialData', 'profitMargins'), 'operating_margin': ('financialData', 'operatingMargins'),
            'debt': ('financialData', 'totalDebt'), 'debt_to_equity': ('financialData', 'debtToEquity'),
            'pe': ('summaryDetail', 'trailingPE'), 'forward_pe': ('summaryDetail', 'forwardPE'),
            'peg': ('defaultKeyStatistics', 'pegRatio'), 'price_sales': ('summaryDetail', 'priceToSalesTrailing12Months')}
        values = {name: number(result.get(module, {}).get(field)) for name, (module, field) in fields.items()}
        return instrument.as_dict() | dict(values=values, sector=str(result.get('assetProfile', {}).get('sector') or '')[:80],
            reporting_currency=reporting_currency, period='latest reported quarter / TTM; as_of is quarter end, not filing date',
            as_of=number(result.get('defaultKeyStatistics', {}).get('mostRecentQuarter')), source=self.name, source_url='https://finance.yahoo.com/quote/' + instrument.symbol + '/financials/',
            retrieved_at=self.clock())

    @provider_contract
    def news(self, instrument):
        data = self._get('news', '/v1/finance/search', {'q': instrument.symbol, 'quotesCount': 0, 'newsCount': 8})
        items = []
        for row in data.get('news', [])[:20]:
            timestamp = number(row.get('providerPublishTime'))
            url = str(row.get('link') or '')
            parsed = urlsplit(url)
            if timestamp is None or not 0 <= self.clock() - timestamp <= 7 * 86400:
                continue
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                continue
            # Search results without explicit ticker relevance are context, not company evidence.
            if instrument.symbol not in row.get('relatedTickers', []):
                continue
            items.append(dict(title=str(row.get('title') or '')[:240], timestamp=timestamp, url=url,
                              source=str(row.get('publisher') or self.name)[:80], untrusted=True))
        return {'items': items[:8], 'source': self.name, 'window_days': 7, 'retrieved_at': self.clock()}


class ProviderChain:
    """Try alternatives only for missing/failed data, never for identity conflicts."""
    def __init__(self, primary, fallbacks=(), clock=time.time):
        self.providers = (primary, *fallbacks)
        self.clock = clock

    def resolve(self, query, exchange=None, currency=None):
        return self.providers[0].resolve(query, exchange, currency)

    def get(self, kind, instrument):
        errors = []
        for provider in self.providers:
            try:
                data = getattr(provider, kind)(instrument)
                if kind != 'news':
                    validate_identity(instrument, data)
                if kind == 'quote':
                    if number(data.get('price')) is None or data['price'] <= 0:
                        raise FinanceError('quote_missing')
                    data = freshness(data, self.clock())
                return data | {'fallback_used': bool(errors), 'provider_errors': errors}
            except FinanceError as exc:
                if str(exc) == 'provider_identity_conflict':
                    raise
                errors.append({'provider': provider.name, 'code': str(exc)})
        raise FinanceError(errors[-1]['code'] if errors else 'provider_unavailable')
