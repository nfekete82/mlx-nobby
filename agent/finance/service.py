"""Native finance tools shared by Chat, AgentRuntime and API callers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import re
import time

from .analytics import technicals, performance, scoring, cases
from .contracts import FinanceError, symbol, number
from .providers import EcbFxProvider, ProviderChain, YahooProvider
from backend.finance_intent import (
    TOOLS, symbols_from_prompt, explicit_company_query, market_constraints, context_symbols,
)
from .tracking import RecommendationStore, evaluate_snapshot
from .portfolio import analyze_portfolio, parse_positions


class FinanceService:
    def __init__(self, provider=None, store=None, clock=time.time, fx_provider=None):
        self.clock = clock
        injected_provider = provider is not None
        self.provider = provider or ProviderChain(YahooProvider(clock=clock), clock=clock)
        # Tests/custom providers stay network-isolated unless an FX provider is explicitly injected.
        self.fx_provider = fx_provider if fx_provider is not None else (
            None if injected_provider else EcbFxProvider(clock=clock)
        )
        self.store = store or RecommendationStore(Path.home() / '.config/mlx-web/finance/recommendations.json')
        self._capacity = threading.BoundedSemaphore(4)

    def _display_fx(self, *currencies):
        unique = []
        for value in currencies:
            currency = str(value or '').strip().upper()
            if currency and currency not in unique:
                unique.append(currency)
        rates, missing = {}, []
        for currency in unique:
            if currency == 'EUR':
                rates[currency] = {
                    'base_currency': 'EUR', 'quote_currency': 'EUR', 'rate': 1.0,
                    'source': 'identity', 'source_url': None, 'as_of': None,
                    'rate_basis': 'identity'
                }
                continue
            if self.fx_provider is None:
                missing.append(currency)
                continue
            try:
                rates[currency] = self.fx_provider.rate_to_eur(currency)
            except FinanceError as exc:
                missing.append(currency)
        status = 'available' if rates and not missing else 'partial' if rates else 'unavailable'
        return {
            'target_currency': 'EUR',
            'rates': rates,
            'missing_currencies': missing,
            'status': status,
            'presentation_only': True,
        }

    def _attach_display_fx(self, report, *currencies):
        report['display_fx'] = self._display_fx(*currencies)
        return report

    def _analysis(self, instrument):
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='finance') as pool:
            futures = {kind: pool.submit(self.provider.get, kind, instrument)
                       for kind in ('quote', 'history', 'fundamentals', 'news')}
            data, missing = {}, []
            for kind, future in futures.items():
                try:
                    data[kind] = future.result()
                except FinanceError as exc:
                    if str(exc) == 'provider_identity_conflict' or kind == 'quote':
                        raise
                    data[kind] = {}
                    missing.append({'type': kind, 'code': str(exc)})
        technical = technicals(data['history'])
        report = {'kind': 'analysis', 'instrument': instrument.as_dict(), 'timestamp': self.clock(),
                  'quote': data['quote'], 'performance': performance(data['history']),
                  'fundamentals': data['fundamentals'], 'technicals': technical,
                  'news': data['news'], 'sentiment': {'status': 'unavailable', 'source': None},
                  'assessment': scoring(data['fundamentals'], technical, data['quote'], self.clock()),
                  'cases': cases(data['fundamentals'], technical), 'missing': missing,
                  'sources': {kind: {'provider': value.get('source'), 'url': value.get('source_url'),
                                    'retrieved_at': value.get('retrieved_at'), 'as_of': value.get('as_of')}
                              for kind, value in data.items()},
                  'untrusted_external_content': True}
        self._attach_display_fx(report, instrument.currency, data['fundamentals'].get('reporting_currency'))
        return report, data['history']

    def execute(self, action, *, prompt='', options=None, owner=None):
        if action not in TOOLS:
            raise FinanceError('unknown_finance_tool')
        if len(str(prompt)) > 10000:
            raise FinanceError('finance_input_too_large')
        if options is not None and not isinstance(options, dict):
            raise FinanceError('invalid_finance_options')
        if options and 'track' in options and type(options['track']) is not bool:
            raise FinanceError('invalid_finance_options')
        if not self._capacity.acquire(blocking=False):
            raise FinanceError('finance_busy')
        try:
            return self._execute(action, prompt, options or {}, owner)
        finally:
            self._capacity.release()

    def _execute(self, action, prompt, options, owner):
        exchange, currency = market_constraints(prompt)
        exchange, currency = options.get('exchange', exchange), options.get('currency', currency)
        if exchange is not None and (not isinstance(exchange, str) or not 1 <= len(exchange) <= 40):
            raise FinanceError('invalid_exchange')
        if currency is not None and currency not in {'USD', 'EUR', 'GBP', 'JPY', 'CHF', 'CAD', 'AUD', 'HKD', 'INR'}:
            raise FinanceError('invalid_currency')
        tickers = options.get('symbols')
        if tickers is None:
            tickers = [options['symbol']] if options.get('symbol') else symbols_from_prompt(prompt)
        if not isinstance(tickers, list) or len(tickers) > 10 or any(not isinstance(t, str) for t in tickers):
            raise FinanceError('invalid_symbol')
        if not tickers:
            company_query = explicit_company_query(prompt)
            if company_query:
                tickers = [company_query]
        if action == 'finance_recommendation_performance':
            snapshots = self.store.list(owner, symbol(tickers[0]) if tickers else None)
            # A bounded page; historic snapshots remain untouched in the ledger.
            results = []
            for snapshot in snapshots[-20:]:
                saved = snapshot['instrument']
                try:
                    instrument = self.provider.resolve(saved['symbol'], saved['exchange'], saved['currency'])
                    quote = self.provider.get('quote', instrument)
                    history = self.provider.get('history', instrument)
                    benchmark = None
                    if saved['currency'] == 'USD' and saved['exchange'] in {'NASDAQ', 'NYSE', 'NYSE ARCA'}:
                        try:
                            benchmark = self.provider.get('history', self.provider.resolve('SPY', currency='USD'))
                        except FinanceError:
                            pass
                    results.append(evaluate_snapshot(snapshot, quote, history, benchmark))
                except FinanceError as exc:
                    results.append({'id': snapshot['id'], 'status': 'unavailable', 'code': str(exc)})
            evaluated = [row for row in results if row.get('status') == 'evaluated' and not row.get('stale') and row.get('return') is not None]
            hits = [row['hit'] for row in evaluated if row.get('hit') is not None]
            return {'kind': 'tracking', 'items': results, 'total': len(snapshots), 'limit': 20,
                    'statistics': {'evaluated': len(evaluated), 'hit_rate': sum(hits) / len(hits) if hits else None,
                        'average_return': sum(row['return'] for row in evaluated) / len(evaluated) if evaluated else None,
                        'recommendations': {label: sum(row['recommendation'] == label for row in evaluated)
                            for label in ('Strong Buy', 'Buy', 'Hold', 'Reduce', 'Sell', 'insufficient data')}},
                    'statistics_scope': 'latest 20 snapshots; unadjusted quote price changes, not total returns; repeated analyses are not independent trades'}
        if action == 'finance_portfolio_analysis':
            positions = options.get('positions', parse_positions(prompt))
            if not isinstance(positions, list) or not 1 <= len(positions) <= 10:
                return {'kind': 'portfolio', 'status': 'positions_required', 'example': 'AMD: 10, NVDA: 5',
                        'positions': [], 'risk': 'insufficient data'}
            if any(not isinstance(p, dict) or not isinstance(p.get('symbol'), str) or number(p.get('quantity')) is None or not 0 < p['quantity'] <= 1e12 for p in positions):
                raise FinanceError('invalid_quantity')
            reports, histories = [], {}
            for position in positions:
                instrument = self.provider.resolve(position['symbol'], position.get('exchange', exchange), position.get('currency', currency))
                report, history = self._analysis(instrument)
                reports.append(report)
                histories[instrument.symbol] = history
            return {'kind': 'portfolio', **analyze_portfolio(positions, reports, histories)}
        if not tickers and re.fullmatch(r'[A-Z0-9][A-Z0-9.^=-]{0,19}', str(prompt).strip()):
            tickers = [symbol(prompt)]
        if not tickers:
            raise FinanceError('symbol_required')
        if action == 'finance_compare' and len(set(tickers)) < 2:
            raise FinanceError('comparison_symbols_required')
        if action != 'finance_compare' and len(tickers) != 1:
            raise FinanceError('single_symbol_required')
        instruments = [self.provider.resolve(ticker, exchange, currency) for ticker in dict.fromkeys(tickers)]
        instruments = list({instrument.identity(): instrument for instrument in instruments}.values())
        if action == 'finance_compare' and len(instruments) < 2:
            raise FinanceError('comparison_symbols_required')
        if action == 'finance_quote':
            instrument = instruments[0]
            # A quote must not wait for five years of daily candles. The
            # frontend requests finance_history independently for its chart.
            report = {'kind': 'quote', 'instrument': instrument.as_dict(),
                      'quote': self.provider.get('quote', instrument),
                      'history_status': 'deferred'}
            return self._attach_display_fx(report, instrument.currency)
        if action == 'finance_history':
            history = self.provider.get('history', instruments[0])
            report = {'kind': 'history', 'instrument': instruments[0].as_dict(), 'history': history,
                      'performance': performance(history), 'technicals': technicals(history)}
            return self._attach_display_fx(report, instruments[0].currency)
        reports = []
        for instrument in instruments:
            report, _ = self._analysis(instrument)
            if owner and options.get('track', True):
                try:
                    report['recommendation_id'] = self.store.append(report, owner)
                except (FinanceError, OSError):
                    report['tracking_status'] = 'unavailable'
            reports.append(report)
        if action == 'finance_analyze':
            return reports[0]
        ranking = sorted(reports, key=lambda report: (report['assessment']['score'] is not None, report['assessment']['score'] or 0), reverse=True)
        return {'kind': 'comparison', 'reports': reports, 'ranking': [r['instrument']['symbol'] for r in ranking if r['assessment']['score'] is not None],
                'ranking_status': 'partial' if any(r['assessment']['score'] is None for r in reports) else 'complete',
                'price_comparison': 'EUR is presentation-only using ECB daily reference rates; original listing currency is retained'}


_SERVICE = None
_SERVICE_LOCK = threading.Lock()


def service():
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = FinanceService()
        return _SERVICE


def execute_tool(action, goal, query=None, instruction=None, files=None, options=None):
    from agent.run_state import current_run_context
    context = current_run_context()
    # Chat ownership is bound by the existing RunContext, never model-supplied options.
    owner = context.chat_id if context else None
    if options is not None and not isinstance(options, dict):
        raise FinanceError("invalid_finance_options")
    options = dict(options) if options is not None else None
    request_text = query or goal
    if (
        action in {'finance_quote', 'finance_analyze', 'finance_history'}
        and not symbols_from_prompt(request_text)
        and not explicit_company_query(request_text)
        and not (options or {}).get('symbol')
        and not (options or {}).get('symbols')
    ):
        previous = context_symbols(context.conversation if context else None)
        if previous:
            options = (options or {}) | {'symbols': previous}
    return service().execute(action, prompt=query or goal, options=options, owner=owner)
