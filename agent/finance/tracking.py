"""Immutable local analysis snapshots using the existing atomic persistence helper."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import uuid
from agent.batch_state import atomic_write_with
from .contracts import FinanceError, number
from .analytics import history_prices


class RecommendationStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            result = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, OSError):
            # Never overwrite a corrupt recommendation ledger.
            raise FinanceError('tracking_store_invalid') from None

    def append(self, report, owner):
        if not owner:
            raise FinanceError('tracking_owner_required')
        snapshot = deepcopy(report)
        identifier = uuid.uuid4().hex
        snapshot.update(id=identifier, owner=owner)
        with self._lock:
            items = self._load()
            if len(items) >= 10000:
                raise FinanceError('tracking_store_full')
            items[identifier] = snapshot
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            def write(temporary):
                with temporary.open('w', encoding='utf-8') as stream:
                    temporary.chmod(0o600)
                    json.dump(items, stream, ensure_ascii=False, allow_nan=False)
            atomic_write_with(self.path, write)
            self.path.chmod(0o600)
        return identifier

    def list(self, owner, ticker=None):
        if not owner:
            raise FinanceError('tracking_owner_required')
        with self._lock:
            items = self._load()
            return deepcopy(sorted((value for value in items.values() if value.get('owner') == owner
                and (not ticker or value.get('instrument', {}).get('symbol') == ticker)), key=lambda value: value['timestamp']))


def evaluate_snapshot(snapshot, quote, history, benchmark=None):
    instrument = snapshot['instrument']
    if any(quote.get(k) != instrument.get(k) for k in ('symbol', 'exchange', 'currency')):
        raise FinanceError('provider_identity_conflict')
    entry = number(snapshot.get('quote', {}).get('price'))
    start, end = snapshot.get('quote', {}).get('timestamp'), quote.get('timestamp')
    if entry is None or entry <= 0 or not start or not end or end <= start:
        return {'id': snapshot['id'], 'status': 'insufficient data'}
    bars, values = history_prices(history)
    # Include the last completed observation before entry as the drawdown baseline.
    previous = [i for i, bar in enumerate(bars) if bar['timestamp'] <= start]
    baseline = previous[-1] if previous else None
    selected = [value for index, (bar, value) in enumerate(zip(bars, values))
                if baseline is not None and index >= baseline and bar['timestamp'] <= end]
    peak, drawdown = None, None
    # Only compare drawdown within one history basis; never mix adjusted bars and spot entry.
    if len(selected) >= 2:
        peak, drawdown = selected[0], 0
        for value in selected:
            peak = max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
    # Performance and alpha use matched completed daily bars and one price basis.
    # Spot price change remains separate; adjusted history may reflect distributions/splits.
    before = [i for i, bar in enumerate(bars) if bar['timestamp'] <= start]
    after = [i for i, bar in enumerate(bars) if bar['timestamp'] <= end]
    comparable = bool(before and after and start - bars[before[-1]]['timestamp'] <= 4 * 86400
                      and end - bars[after[-1]]['timestamp'] <= 4 * 86400)
    history_return = values[after[-1]] / values[before[-1]] - 1 if comparable else None
    benchmark_return = None
    if benchmark and benchmark.get('currency') == instrument.get('currency') and benchmark.get('price_basis') == history.get('price_basis') and comparable:
        bbars, bvalues = history_prices(benchmark)
        first_stamp, last_stamp = bars[before[-1]]['timestamp'], bars[after[-1]]['timestamp']
        first_day, last_day = first_stamp // 86400, last_stamp // 86400
        lookup = {bar['timestamp'] // 86400: value for bar, value in zip(bbars, bvalues)}
        if first_day in lookup and last_day in lookup:
            benchmark_return = lookup[last_day] / lookup[first_day] - 1
    spot_gain = quote['price'] / entry - 1
    gain = history_return
    original = snapshot['assessment']['recommendation']
    horizon_complete = end - start >= 90 * 86400
    hit = (gain > 0 if original in ('Buy', 'Strong Buy') else gain < 0 if original in ('Sell', 'Reduce') else None) if horizon_complete and gain is not None else None
    return {'id': snapshot['id'], 'status': 'evaluated', 'symbol': instrument['symbol'], 'recommendation': original,
            'return': gain, 'return_basis': history.get('price_basis'), 'spot_price_change': spot_gain,
            'benchmark_return': benchmark_return, 'alpha': gain - benchmark_return if benchmark_return is not None and gain is not None else None,
            'alpha_basis': 'matched daily dates and identical history basis; no fees/taxes/FX',
            'max_drawdown': drawdown, 'drawdown_basis': history.get('price_basis'),
            'drawdown_complete': bool(bars and bars[0]['timestamp'] <= start and bars[-1]['timestamp'] >= end - 4 * 86400),
            'hit': hit, 'horizon_complete': horizon_complete, 'stale': quote.get('stale'), 'as_of': end}
