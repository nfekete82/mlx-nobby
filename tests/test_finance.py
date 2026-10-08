"""Deterministic, offline finance contracts. All clocks and transports are injected."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.finance_intent import (
    finance_intent, symbols_from_prompt, explicit_company_query, market_constraints, TOOLS,
)
from agent.finance.contracts import FinanceError, Instrument, freshness, symbol
from agent.finance.providers import YahooProvider, ProviderChain
from agent.finance.analytics import technicals, performance, scoring, recommendation, WEIGHTS, ema_series
from agent.finance.portfolio import analyze_portfolio, parse_positions, correlation
from agent.finance.tracking import RecommendationStore, evaluate_snapshot
from agent.finance.service import FinanceService
from agent.finance.api import install_routes
from agent.permissions import PermissionEngine, ToolPermissionError
from agent.run_state import RunContext
from agent.tool_registry import Tool, ToolRegistry

NOW = 1780500000
INSTRUMENT = Instrument('AMD', 'NASDAQ', 'USD', 'Advanced Micro Devices')


def history(ticker='AMD', currency='USD'):
    return {'symbol': ticker, 'exchange': 'NASDAQ', 'currency': currency,
            'bars': [{'timestamp': NOW - (260 - i) * 86400, 'close': 100 + i, 'adjusted_close': 100 + i} for i in range(260)],
            'price_basis': 'adjusted_close', 'source': 'fixture', 'retrieved_at': NOW}


class Provider:
    name = 'fixture'
    def __init__(self):
        self.calls = []
    def resolve(self, ticker, exchange=None, currency=None):
        return Instrument(ticker.upper(), exchange or 'NASDAQ', currency or 'USD', ticker)
    def quote(self, i):
        self.calls.append(('quote', i.symbol))
        return i.as_dict() | {'price': 359, 'timestamp': NOW - 20, 'session': 'regular', 'delay_status': 'delayed', 'source': self.name}
    def history(self, i):
        return history(i.symbol, i.currency) | i.as_dict()
    def fundamentals(self, i):
        return i.as_dict() | {'values': {'profit_margin': .25, 'debt_to_equity': 30, 'revenue_growth': .30,
                'eps_growth': .40, 'pe': 20, 'eps': 3.5}, 'as_of': NOW - 86400, 'sector': 'Technology', 'source': self.name}
    def news(self, i):
        return {'items': [], 'source': self.name}


@pytest.fixture
def service(tmp_path):
    provider = Provider()
    return FinanceService(ProviderChain(provider, clock=lambda: NOW), RecommendationStore(tmp_path / 'finance.json'), clock=lambda: NOW)


@pytest.mark.parametrize('prompt,expected', [
    ('AMD Kurs', 'finance_quote'), ('Wie steht AMD gerade?', 'finance_quote'),
    ('How is AMD trading at the moment?', 'finance_quote'), ('AMD stock price', 'finance_quote'),
    ('Analysiere AMD', 'finance_analyze'), ('Analysiere AMD fundamental und technisch.', 'finance_analyze'),
    ('Ist AMD aktuell attraktiv?', 'finance_analyze'), ('Welche Risiken siehst du bei AMD?', 'finance_analyze'),
    ('Analyze AMD risks', 'finance_analyze'), ('analysiere western digital vollständig', 'finance_analyze'),
    ('Analysiere Example Storage Systems vollständig', 'finance_analyze'),
    ('Analysiere den Vertrag vollständig', None),
    ('AMD oder NVIDIA?', 'finance_compare'),
    ('Vergleiche AMD, NVIDIA und Broadcom', 'finance_compare'), ('Compare AMD and NVIDIA', 'finance_compare'),
    ('Analysiere mein Portfolio', 'finance_portfolio_analysis'), ('Analyze my portfolio', 'finance_portfolio_analysis'),
    ('Wie hat sich deine frühere Empfehlung entwickelt?', 'finance_recommendation_performance'),
    ('Performance AMD 1Y', 'finance_history'), ('AMD Nachrichten heute', 'web_search'),
    ('Was bedeutet ein KGV?', None), ('Erkläre RSI', None), ('Implementiere AMD stock price in Python', None),
    ('Erzähle eine Story über Apple', None), ('Ändere die Aktie im Workspace', None), ('How is NVIDIA GPU memory allocated?', None),
])
def test_routing(prompt, expected):
    assert finance_intent(prompt) == expected


def test_symbols_constraints():
    assert symbols_from_prompt('Vergleiche AMD, NVIDIA und Broadcom') == ['AMD', 'NVDA', 'AVGO']
    assert symbols_from_prompt('AMD.DE Kurs in EUR') == ['AMD.DE']
    assert symbols_from_prompt('Analysiere IBM') == ['IBM']
    assert symbols_from_prompt('analysiere western digital vollständig') == ['WDC']
    assert explicit_company_query('Analysiere Example Storage Systems vollständig') == 'Example Storage Systems'
    assert explicit_company_query('Analysiere dieses Dokument vollständig') is None
    assert explicit_company_query('Analysiere meinen PC vollständig') is None
    assert market_constraints('AMD auf Stuttgart in EUR') == ('STUTTGART', 'EUR')


@pytest.mark.parametrize('value', ['../AMD', 'AMD?url=x', 'http://evil', 'AMD\nNVDA', 'AMD;ls', 'AMD$(id)', ''])
def test_symbol_injection(value):
    with pytest.raises(FinanceError):
        symbol(value)


def chart(meta=None):
    return {'chart': {'result': [{'meta': {'symbol': 'AMD', 'exchangeName': 'NMS', 'currency': 'USD',
           'instrumentType': 'EQUITY', 'regularMarketPrice': 100.125, 'regularMarketTime': NOW - 20,
           'chartPreviousClose': 99, **(meta or {})}, 'timestamp': [NOW - 86400, NOW - 2],
           'indicators': {'quote': [{'close': [95, None]}], 'adjclose': [{'adjclose': [94, None]}]}}], 'error': None}}


def yahoo(transport=None, clock=None):
    return YahooProvider(transport=transport or (lambda url, timeout: chart()), clock=clock or (lambda: NOW), monotonic=lambda: NOW)


def test_provider_quote_identity_freshness_history():
    p = yahoo()
    i = p.resolve('AMD')
    assert i.identity() == ('AMD', 'NASDAQ', 'USD')
    quote = p.quote(i)
    assert quote['price'] == 100.125
    assert quote['timestamp'] == NOW - 20
    assert quote['age_seconds'] == 20 and not quote['stale']
    assert quote['session'] == 'regular' and quote['delay_status'] == 'unknown'
    assert quote['day_change_percent'] == pytest.approx((100.125 / 99 - 1) * 100)
    assert p.history(i)['bars'] == [{'timestamp': NOW - 86400, 'close': 95, 'adjusted_close': 94}]


@pytest.mark.parametrize('metadata,session,price', [
    ({'preMarketPrice': 103, 'preMarketTime': NOW - 10}, 'pre-market', 103),
    ({'postMarketPrice': 102, 'postMarketTime': NOW - 5}, 'after-hours', 102),
    ({'postMarketPrice': 102}, 'regular', 100.125),
    ({'preMarketPrice': 103, 'preMarketTime': NOW - 100}, 'regular', 100.125),
])
def test_provider_sessions(metadata, session, price):
    q = yahoo(lambda url, timeout: chart(metadata)).quote(INSTRUMENT)
    assert q['session'] == session and q['price'] == price


@pytest.mark.parametrize('meta', [{'currency': 'EUR'}, {'exchangeName': 'STU'}, {'symbol': 'NVDA'}])
def test_quote_provider_conflicts(meta):
    with pytest.raises(FinanceError, match='provider_identity_conflict'):
        yahoo(lambda url, timeout: chart(meta)).quote(INSTRUMENT)


@pytest.mark.parametrize('exchange,currency', [('STUTTGART', 'EUR'), ('XETRA', 'EUR'), ('NASDAQ', 'EUR')])
def test_no_arbitrary_listing(exchange, currency):
    with pytest.raises(FinanceError, match='market_selection_required'):
        yahoo().resolve('AMD', exchange, currency)


def test_unique_search_resolution():
    def transport(url, timeout):
        return {'quotes': [{'quoteType': 'EQUITY', 'symbol': 'AMD', 'exchange': 'NMS'}]} if '/search?' in url else chart()
    assert yahoo(transport).resolve('Advanced Devices Incorporated').symbol == 'AMD'
    with pytest.raises(FinanceError, match='ambiguous_symbol'):
        yahoo(lambda u, t: {'quotes': []}).resolve('Unknown corporation name')


def test_retry_cache_rate_limit():
    calls = []
    def transport(url, timeout):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise URLError('timeout')
        return chart()
    p = yahoo(transport)
    p.quote(INSTRUMENT)
    p.quote(INSTRUMENT)
    assert len(calls) == 2 and calls[0][1] == 4
    def throttled(url, timeout):
        raise HTTPError(url, 429, 'throttle', {}, None)
    p = yahoo(throttled)
    with pytest.raises(FinanceError, match='provider_rate_limited'):
        p.quote(INSTRUMENT)
    assert p._cooldown == NOW + 60
    with pytest.raises(FinanceError, match='provider_rate_limited'):
        p.quote(INSTRUMENT)


def test_unauthorized_no_retry_and_bad_payload():
    calls = []
    def unauthorized(url, timeout):
        calls.append(url)
        raise HTTPError(url, 401, 'unauthorized', {}, None)
    with pytest.raises(FinanceError):
        yahoo(unauthorized).fundamentals(INSTRUMENT)
    assert len(calls) == 1
    with pytest.raises(FinanceError):
        yahoo(lambda u, t: []).quote(INSTRUMENT)


def test_cache_age_not_fetch_age():
    time = [NOW]
    p = yahoo(clock=lambda: time[0])
    assert not p.quote(INSTRUMENT)['stale']
    time[0] += 1000
    assert p.quote(INSTRUMENT)['stale']
    assert p.quote(INSTRUMENT)['age_seconds'] == 1020


@pytest.mark.parametrize('timestamp', [None, NOW + 1000, -1, float('nan')])
def test_bad_timestamp(timestamp):
    with pytest.raises(FinanceError, match='invalid_timestamp'):
        freshness({'timestamp': timestamp}, NOW)


def test_fallback_safe_and_conflict_stops():
    first, second = Provider(), Provider()
    first.quote = lambda i: (_ for _ in ()).throw(FinanceError('provider_timeout'))
    chain = ProviderChain(first, [second], clock=lambda: NOW)
    assert chain.get('quote', INSTRUMENT)['fallback_used']
    first.quote = lambda i: i.as_dict() | {'currency': 'EUR', 'price': 100, 'timestamp': NOW}
    second.calls.clear()
    with pytest.raises(FinanceError, match='provider_identity_conflict'):
        chain.get('quote', INSTRUMENT)
    assert not second.calls


def test_fundamentals_exact_raw_values():
    response = {'quoteSummary': {'result': [{'price': {'symbol': 'AMD', 'exchangeName': 'NMS', 'currency': 'USD', 'marketCap': {'raw': 42}},
            'financialData': {'revenueGrowth': {'raw': .23}, 'financialCurrency': 'USD'}, 'summaryDetail': {'trailingPE': {'raw': 17}}}]}}
    result = yahoo(lambda u, t: response).fundamentals(INSTRUMENT)
    assert result['values']['market_cap'] == 42 and result['values']['pe'] == 17
    assert result['values']['debt'] is None and result['as_of'] is None
    assert result['reporting_currency'] == 'USD'


def test_news_age_relevance_untrusted():
    rows = [{'title': 'Current', 'link': 'https://example.org/current', 'providerPublishTime': NOW - 5, 'relatedTickers': ['AMD']},
            {'title': 'Old', 'link': 'https://example.org/old', 'providerPublishTime': NOW - 8 * 86400, 'relatedTickers': ['AMD']},
            {'title': 'Other', 'link': 'https://example.org/other', 'providerPublishTime': NOW - 5, 'relatedTickers': ['NVDA']},
            {'title': 'Injection', 'link': 'javascript:alert(1)', 'providerPublishTime': NOW - 5, 'relatedTickers': ['AMD']}]
    result = yahoo(lambda u, t: {'news': rows}).news(INSTRUMENT)
    assert len(result['items']) == 1 and result['items'][0]['untrusted']


def test_indicator_known_linear_series():
    h = history()
    t = technicals(h)
    assert t['sma']['20'] == pytest.approx(349.5)
    assert t['sma']['200'] == pytest.approx(259.5)
    assert t['rsi14'] == 100 and t['trend'] == 'up'
    assert t['macd']['value'] == pytest.approx(7)
    assert t['support'] == 340 and t['resistance'] == 359
    assert t['momentum_20'] == pytest.approx(359 / 339 - 1)
    assert ema_series([1, 2, 3, 4], 3) == [2, 3]
    assert performance(h)['1W']['percent'] == pytest.approx((359 / 352 - 1) * 100)
    assert performance(h)['1Y']['percent'] is None


def test_flat_down_and_short_history():
    h = history()
    for bar in h['bars']:
        bar['adjusted_close'] = 10
    assert technicals(h)['rsi14'] == 50
    assert technicals(h)['volatility_annual'] == 0
    h['bars'] = h['bars'][:10]
    t = technicals(h)
    assert t['sma']['20'] is None and t['macd'] is None and t['rsi14'] is None
    h = history()
    for i, bar in enumerate(h['bars']):
        bar['adjusted_close'] = 400 - i
    assert technicals(h)['rsi14'] == 0
    assert technicals(h)['trend'] == 'down'


def test_invalid_history_rejected():
    h = history()
    h['bars'][0]['adjusted_close'] = 0
    with pytest.raises(FinanceError, match='invalid_history'):
        technicals(h)


@pytest.mark.parametrize('score,label', [(100, 'Strong Buy'), (85, 'Strong Buy'), (84, 'Buy'), (70, 'Buy'),
        (69, 'Hold'), (55, 'Hold'), (54, 'Reduce'), (40, 'Reduce'), (39, 'Sell'), (0, 'Sell'), (None, 'insufficient data')])
def test_recommendation_boundaries(score, label):
    assert recommendation(score) == label


def test_deterministic_scoring_confidence():
    p = Provider()
    q = freshness(p.quote(INSTRUMENT), NOW)
    result = scoring(p.fundamentals(INSTRUMENT), technicals(history()), q, NOW)
    assert sum(WEIGHTS.values()) == 100 and result['score'] is not None
    assert result == scoring(p.fundamentals(INSTRUMENT), technicals(history()), q, NOW)
    assert result['subscores']['sentiment'] is None and result['coverage'] == .95
    assert result['recommendation'] == recommendation(result['score'])
    insufficient = scoring({}, technicals(history()), q, NOW)
    assert insufficient['score'] is None and insufficient['confidence'] <= .35
    assert scoring(p.fundamentals(INSTRUMENT), technicals(history()), q | {'stale': True}, NOW)['score'] is None
    f = p.fundamentals(INSTRUMENT)
    f['as_of'] = None
    assert scoring(f, technicals(history()), q, NOW)['score'] is None
    f = p.fundamentals(INSTRUMENT)
    f['values']['pe'] = -10
    assert scoring(f, technicals(history()), q, NOW)['subscores']['valuation'] is None


def test_service_tracking_compare_and_portfolio(service):
    report = service.execute('finance_analyze', prompt='Analysiere AMD', owner='chat1')
    assert report['assessment']['score'] is not None and report['recommendation_id']
    assert service.store.list('chat2') == []
    compared = service.execute('finance_compare', prompt='AMD oder NVIDIA?', owner='chat1')
    assert len(compared['reports']) == 2 and len(compared['ranking']) == 2
    p = service.execute('finance_portfolio_analysis', prompt='Analysiere mein Portfolio: AMD: 10, NVDA: 5')
    assert p['positions'][0]['weight'] == pytest.approx(2 / 3)
    assert p['concentration_risk'] == 'high'
    assert p['sectors']['Technology'] == 1
    assert p['correlations'][0]['value'] == pytest.approx(1)
    assert service.execute('finance_portfolio_analysis', prompt='Analysiere mein Portfolio')['status'] == 'positions_required'


def test_partial_data_cannot_invent_rating(service):
    primary = service.provider.providers[0]
    primary.fundamentals = lambda i: (_ for _ in ()).throw(FinanceError('fundamentals_unavailable'))
    report = service.execute('finance_analyze', prompt='Analysiere AMD')
    assert report['assessment']['score'] is None
    assert report['assessment']['recommendation'] == 'insufficient data'
    assert report['missing'][0]['type'] == 'fundamentals'
    assert report['sentiment']['status'] == 'unavailable'


def test_service_provider_conflict_not_hidden(service):
    primary = service.provider.providers[0]
    primary.fundamentals = lambda i: i.as_dict() | {'currency': 'EUR'}
    with pytest.raises(FinanceError, match='provider_identity_conflict'):
        service.execute('finance_analyze', prompt='AMD analysis')


def test_portfolio_mixed_currency_and_duplicates(service):
    result = service.execute('finance_portfolio_analysis', options={'positions': [
        {'symbol': 'AMD', 'quantity': 10}, {'symbol': 'NVDA', 'quantity': 5, 'currency': 'EUR'}]})
    assert result['total_value'] is None and result['status'] == 'currency_conversion_required'
    with pytest.raises(FinanceError, match='duplicate_positions'):
        service.execute('finance_portfolio_analysis', options={'positions': [{'symbol': 'AMD', 'quantity': 10}, {'symbol': 'AMD', 'quantity': 5}]})
    with pytest.raises(FinanceError, match='invalid_quantity'):
        service.execute('finance_portfolio_analysis', options={'positions': [{'symbol': 'AMD', 'quantity': -1}]})
    assert parse_positions('Portfolio: AMD: 10, NVDA: 5') == [{'symbol': 'AMD', 'quantity': 10.0}, {'symbol': 'NVDA', 'quantity': 5.0}]


def test_snapshot_immutable_persistence_corruption(service):
    report = service.execute('finance_analyze', prompt='AMD analysis', owner='chat1')
    report['quote']['price'] = 999
    assert service.store.list('chat1')[0]['quote']['price'] == 359
    store = RecommendationStore(service.store.path)
    assert store.list('chat1')[0]['instrument']['symbol'] == 'AMD'
    assert service.store.path.stat().st_mode & 0o777 == 0o600
    service.store.path.write_text('corrupt')
    with pytest.raises(FinanceError, match='tracking_store_invalid'):
        store.append(report, 'chat1')
    assert service.store.path.read_text() == 'corrupt'


def test_tracking_performance_does_not_rewrite(service):
    report = service.execute('finance_analyze', prompt='AMD analysis', owner='chat1')
    snapshot = service.store.list('chat1')[0]
    snapshot['quote']['timestamp'] -= 100 * 86400
    snapshot['quote']['price'] = 100
    q = freshness(Provider().quote(INSTRUMENT), NOW)
    outcome = evaluate_snapshot(snapshot, q, history())
    assert outcome['spot_price_change'] == pytest.approx(2.59) and outcome['horizon_complete']
    assert outcome['return'] == pytest.approx(2.59)
    assert outcome['history_return'] == pytest.approx(359 / 259 - 1)
    assert outcome['max_drawdown'] == 0
    assert outcome['benchmark_return'] is None
    before = service.store.path.read_bytes()
    data = service.execute('finance_recommendation_performance', owner='chat1')
    assert len(data['items']) == 1 and service.store.path.read_bytes() == before
    with pytest.raises(FinanceError, match='provider_identity_conflict'):
        evaluate_snapshot(snapshot, q | {'currency': 'EUR'}, history())


def test_registry_permissions_api(service, monkeypatch):
    import importlib
    module = importlib.import_module('agent.finance.service')
    monkeypatch.setattr(module, '_SERVICE', service)
    from agent import app as application
    registry = application.AGENT_TOOL_REGISTRY
    assert set(TOOLS) <= registry.names(permission='READ')
    context = RunContext.start(chat_id='chat1', workspace_bound=True)
    assert registry.execute('finance_quote', run_context=context, goal='AMD Kurs')['quote']['price'] == 359
    context.cancel()
    with pytest.raises(ToolPermissionError):
        registry.execute('finance_quote', run_context=context, goal='AMD Kurs')
    app = FastAPI()
    install_routes(app, registry)
    client = TestClient(app)
    response = client.post('/api/finance/quote', json={'options': {'symbol': 'AMD'}})
    assert response.status_code == 200 and response.json()['quote']['currency'] == 'USD'
    assert client.post('/api/finance/execute_order', json={}).status_code == 404
    assert client.post('/api/finance/quote', json={'options': {'symbol': '../AMD'}}).status_code in (422, 503)
    assert client.post('/api/finance/quote', json={'unknown': 1}).status_code == 422


def test_chat_route_bypasses_models_and_web(service, monkeypatch):
    import importlib
    from agent import app as application
    monkeypatch.setattr(importlib.import_module('agent.finance.service'), '_SERVICE', service)
    monkeypatch.setattr(application, 'semantic_intent_classifier', lambda *a, **kw: pytest.fail('No LLM router for finance'))
    monkeypatch.setattr(application, 'tool_web_search', lambda *a: pytest.fail('No web price lookup'))
    result = application.preflight_chat_action(application.ChatActionRequest(prompt='Wie steht AMD gerade?'))
    assert result['intent'] == 'finance_quote'
    result = application.run_chat_action(application.ChatActionRequest(prompt='Analysiere AMD', chat_id='chat1'))
    assert result['tool'] == 'finance_analyze' and result['status'] == 'completed'
    assert result['data']['recommendation_id']


def test_web_proxy_has_only_finance_tools(monkeypatch):
    from backend import app as web
    monkeypatch.setattr(web, 'agent_json_request', lambda method, path, **kw: {'path': path, 'request': kw['payload']})
    result = web.mlx_finance_request('quote', {'options': {'symbol': 'AMD'}})
    assert result['path'] == '/api/finance/quote'
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        web.mlx_finance_request('../shell', {})


def test_tracking_alpha_uses_same_history_dates_and_basis(service):
    service.execute('finance_analyze', prompt='AMD analysis', owner='chat1')
    snapshot = service.store.list('chat1')[0]
    snapshot['quote']['timestamp'] -= 100 * 86400
    q = freshness(Provider().quote(INSTRUMENT), NOW)
    benchmark = history('SPY')
    outcome = evaluate_snapshot(snapshot, q, history(), benchmark)
    assert outcome['alpha'] is None
    assert outcome['history_alpha'] == 0
    benchmark['price_basis'] = 'close'
    assert evaluate_snapshot(snapshot, q, history(), benchmark)['history_alpha'] is None


def test_capacity_bounded_and_release_after_error(service):
    for _ in range(4):
        service._capacity.acquire()
    with pytest.raises(FinanceError, match='finance_busy'):
        service.execute('finance_quote', prompt='AMD Kurs')
    for _ in range(4):
        service._capacity.release()
    with pytest.raises(FinanceError, match='symbol_required'):
        service.execute('finance_quote')
    assert service.execute('finance_quote', prompt='AMD Kurs')['kind'] == 'quote'


@pytest.mark.parametrize('payload', [{'chart': None}, {'chart': {'result': [None]}}, {'chart': {'result': []}}])
def test_malformed_provider_payload_is_safe(payload):
    with pytest.raises(FinanceError):
        yahoo(lambda u, t: payload).quote(INSTRUMENT)


def test_scoring_known_policy_vector():
    f = {'as_of': NOW - 86400, 'values': {'profit_margin': .15, 'debt_to_equity': 100,
        'revenue_growth': .15, 'eps_growth': .15, 'pe': 30}}
    t = {'trend': 'up', 'rsi14': 50, 'momentum_20': 0, 'volatility_annual': .475, 'as_of': NOW - 86400}
    assessment = scoring(f, t, {'stale': False, 'delay_status': 'delayed'}, NOW)
    assert assessment['score'] == 52 and assessment['recommendation'] == 'Reduce'
    assert assessment['confidence'] == .95
    assert assessment['weights'] == {'fundamental': 20, 'growth': 20, 'valuation': 20, 'technical': 15,
                                     'momentum': 10, 'sentiment': 5, 'risk': 10}


def test_negative_cache_avoids_repeated_restricted_fundamentals():
    calls = []
    def unauthorized(url, timeout):
        calls.append(url)
        raise HTTPError(url, 401, 'restricted', {}, None)
    provider = yahoo(unauthorized)
    for _ in range(3):
        with pytest.raises(FinanceError, match='provider_unavailable'):
            provider.fundamentals(INSTRUMENT)
    assert len(calls) == 1


def test_rate_limit_counts_actual_retries():
    provider = yahoo(lambda u, t: (_ for _ in ()).throw(URLError('timeout')))
    with pytest.raises(FinanceError):
        provider.quote(INSTRUMENT)
    assert len(provider._requests) == 2


def test_canonical_duplicate_compare_rejected(service):
    with pytest.raises(FinanceError, match='comparison_symbols_required'):
        service.execute('finance_compare', options={'symbols': ['AMD', 'amd']})


def test_followup_uses_only_unambiguous_recent_instrument(service, monkeypatch):
    import importlib
    from agent import app as application
    monkeypatch.setattr(importlib.import_module('agent.finance.service'), '_SERVICE', service)
    context = [{'role': 'user', 'content': 'Analysiere AMD'}, {'role': 'assistant', 'content': 'AMD analysis'}]
    prompt = 'Welche Risiken hat diese Aktie?'
    assert finance_intent(prompt, context) == 'finance_analyze'
    result = application.run_chat_action(application.ChatActionRequest(prompt=prompt, conversation_context=context))
    assert result['data']['instrument']['symbol'] == 'AMD'
    ambiguous = [{'role': 'user', 'content': 'Vergleiche AMD und NVIDIA'}]
    result = application.run_chat_action(application.ChatActionRequest(prompt=prompt, conversation_context=ambiguous))
    assert result['status'] == 'failed' and result['data']['code'] == 'symbol_required'
    assert finance_intent('Wie steht sie gerade?', context) == 'finance_quote'
    assert finance_intent('Wie steht sie gerade?') is None

    # A newly named company must never inherit AMD from the earlier context.
    named = 'Analysiere Western Digital vollständig'
    assert finance_intent(named, context) == 'finance_analyze'
    result = application.run_chat_action(application.ChatActionRequest(prompt=named, conversation_context=context))
    assert result['data']['instrument']['symbol'] == 'WDC'


def test_runtime_tool_execution_shares_registry(service, monkeypatch):
    import importlib
    from agent import app as application
    monkeypatch.setattr(importlib.import_module('agent.finance.service'), '_SERVICE', service)
    context = RunContext.start(chat_id='chat1', workspace_bound=True)
    runtime = application.agent_runtime(context)
    result = runtime._execute_tool('finance_quote', 'IBM Kurs', query='IBM')
    assert result['instrument']['symbol'] == 'IBM'


@pytest.mark.parametrize('period,label', [('pre', 'pre-market'), ('post', 'after-hours')])
def test_extended_session_candles_have_explicit_basis(period, label):
    data = chart({'regularMarketTime': NOW - 2000, 'currentTradingPeriod': {
        period: {'start': NOW - 1000, 'end': NOW + 1000}}})
    result = data['chart']['result'][0]
    result['timestamp'] = [NOW - 120, NOW - 30]
    result['indicators'] = {'quote': [{'close': [105.25, 999]}]}
    q = yahoo(lambda u, t: data).quote(INSTRUMENT)
    assert q['price'] == 105.25 and q['session'] == label
    assert q['price_basis'] == 'completed_minute_close' and q['timestamp_basis'] == 'bar_start'
    assert q['timestamp'] == NOW - 120


def test_unidentified_intraday_bars_cannot_change_listing_quote():
    data = chart({'regularMarketTime': NOW - 2000})
    result = data['chart']['result'][0]
    result['timestamp'] = [NOW - 120]
    result['indicators'] = {'quote': [{'close': [999]}]}
    q = yahoo(lambda u, t: data).quote(INSTRUMENT)
    assert q['price'] == 100.125 and q['session'] == 'regular'


def test_tracking_entry_loss_cannot_be_masked_by_daily_close_gain(service):
    service.execute('finance_analyze', prompt='AMD analysis', owner='chat1')
    snapshot = service.store.list('chat1')[0]
    snapshot['quote'].update(timestamp=NOW - 100 * 86400, price=500)
    snapshot['assessment']['recommendation'] = 'Buy'
    result = evaluate_snapshot(snapshot, freshness(Provider().quote(INSTRUMENT), NOW), history())
    assert result['return'] == pytest.approx(359 / 500 - 1)
    assert result['return'] < 0 and result['history_return'] > 0
    assert result['quote_from'] == snapshot['quote']['timestamp'] and result['hit'] is False
    assert result['return_basis'] == 'quote_price_change_unadjusted'


def test_tracking_corporate_actions_cannot_generate_price_hit(service):
    service.execute('finance_analyze', prompt='AMD analysis', owner='chat1')
    snapshot = service.store.list('chat1')[0]
    snapshot['quote']['timestamp'] -= 100 * 86400
    snapshot['assessment']['recommendation'] = 'Sell'
    h = history()
    for row in h['bars'][:-50]:
        row['adjusted_close'] = row['close'] * .5
    result = evaluate_snapshot(snapshot, freshness(Provider().quote(INSTRUMENT), NOW), h)
    assert result['corporate_actions'] == 'detected' and result['hit'] is None


def test_portfolio_ranking_excludes_positions_without_evidence(service):
    provider = service.provider.providers[0]
    original = provider.fundamentals
    def fundamentals(instrument):
        if instrument.symbol == 'AMD':
            raise FinanceError('fundamentals_unavailable')
        return original(instrument)
    provider.fundamentals = fundamentals
    result = service.execute('finance_portfolio_analysis', prompt='Portfolio: AMD: 10, NVDA: 5')
    assert result['ranking'] == ['NVDA'] and result['ranking_status'] == 'partial'
    provider.fundamentals = lambda i: (_ for _ in ()).throw(FinanceError('fundamentals_unavailable'))
    result = service.execute('finance_portfolio_analysis', prompt='Portfolio: AMD: 10, NVDA: 5')
    assert result['ranking'] == [] and result['ranking_status'] == 'insufficient data'
