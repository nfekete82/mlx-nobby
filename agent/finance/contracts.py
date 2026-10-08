"""Provider-neutral market identities and validated observations."""
from dataclasses import dataclass, asdict
from typing import Protocol
import math
import re


class FinanceError(ValueError):
    """Safe, stable error code; never exposes upstream responses or secrets."""


def number(value):
    if isinstance(value, dict):
        value = value.get('raw')
    return value if type(value) in (int, float) and math.isfinite(value) else None


def symbol(value):
    value = str(value).strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.^=-]{0,19}', value):
        raise FinanceError('invalid_symbol')
    return value


@dataclass(frozen=True)
class Instrument:
    symbol: str
    exchange: str
    currency: str
    name: str = ''

    def __post_init__(self):
        symbol(self.symbol)
        if not self.exchange or not re.fullmatch(r'[A-Z]{3}', self.currency):
            raise FinanceError('instrument_identity_missing')

    def identity(self):
        return self.symbol, self.exchange, self.currency

    def as_dict(self):
        return asdict(self)


class MarketDataProvider(Protocol):
    name: str

    def resolve(self, query: str, exchange: str | None = None, currency: str | None = None) -> Instrument: ...
    def quote(self, instrument: Instrument) -> dict: ...
    def history(self, instrument: Instrument) -> dict: ...
    def fundamentals(self, instrument: Instrument) -> dict: ...
    def news(self, instrument: Instrument) -> dict: ...


def validate_identity(instrument, data):
    if any(data.get(key) != value for key, value in zip(
        ('symbol', 'exchange', 'currency'), instrument.identity()
    )):
        raise FinanceError('provider_identity_conflict')
    return data


def freshness(quote, now):
    result = dict(quote)
    timestamp = number(result.get('timestamp'))
    if timestamp is None or timestamp > now + 60 or timestamp <= 0:
        raise FinanceError('invalid_timestamp')
    age = max(0, now - timestamp)
    result.update(age_seconds=round(age), stale=age > 900,
                  freshness='stale' if age > 900 else 'recent',
                  delay_status=result.get('delay_status', 'unknown'))
    # A recently fetched old quote is still old; a closed market is not live.
    return result
