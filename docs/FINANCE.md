# Finance Intelligence

Finance is a native, deterministic analysis layer. Chat, AgentRuntime and the
Finance API use the same ToolRegistry and PermissionEngine. There are no order,
brokerage, trading-account or cloud-model integrations.

## Routing and tools

`backend/finance_intent.py` is the side-effect-free DE/EN decision layer. Explicit
stock prices, analyses, comparisons, portfolios and histories bypass generic
web search and LLM routing. Programming, workspace and creative instructions
retain their existing paths. General finance concepts stay normal knowledge
questions; explicit company news uses existing web search for context.
Attached documents retain the existing document-analysis path. Follow-ups such as
“Welche Risiken hat diese Aktie?” use only a single, unambiguous instrument from
the most recent user Finance request. Ambiguous comparisons never implicitly
select one of the compared tickers.

| Tool | Behavior | Example |
| --- | --- | --- |
| `finance_quote` | Identified last reported price | `Wie steht AMD gerade?` |
| `finance_analyze` | Fundamentals, daily indicators, cases, rules-based assessment | `Analysiere AMD fundamental und technisch.` |
| `finance_compare` | Analyses and ranking of adequately rated instruments | `AMD oder NVIDIA?` |
| `finance_portfolio_analysis` | Local quantities, weights, concentration, sectors, correlation | `Analysiere mein Portfolio: AMD: 10, NVDA: 5` |
| `finance_history` | Historical prices, calendar-period returns, daily indicators | `AMD Kursverlauf` |
| `finance_recommendation_performance` | Immutable earlier analyses in the bound chat | `Wie hat sich deine frühere Empfehlung entwickelt?` |

No finance tool requires a model call. Model-directed AgentRuntime tools are READ
with declared network access, and remain subject to cancellation and permissions.
The native chat output presents tool values directly through the existing
Markdown renderer, without LLM rewriting. News content is untrusted data.

## Providers and market identity

`agent/finance/contracts.py` defines `MarketDataProvider` and immutable
`Instrument(symbol, exchange, currency, name)`. `providers.py` implements a
keyless Yahoo Finance provider and injectable `ProviderChain`. There are no new
Python dependencies, required paid APIs, keys or secrets.

Yahoo chart supplies quotes and daily history; quoteSummary supplies available
fundamentals; search supplies ticker-relevant dated news. These are unofficial
public interfaces with no availability or real-time SLA. A provider access
restriction (including fundamentals HTTP 401), absent values or invalid payload
is reported explicitly. Do not treat missing values as zero. No cookie/crumb or
credential bypass is attempted.

Aliases AMD, NVIDIA and Broadcom resolve to AMD, NVDA and AVGO, then chart
metadata verifies the actual listing. Other explicit symbols are validated.
Company-name search requires a unique equity/ETF match. Ambiguous results fail
rather than taking the first exchange returned.

AMD is the US listing, normally NASDAQ/USD. Asking for Stuttgart/EUR with AMD
fails `market_selection_required`; provide the explicit ticker for that listing.
No implicit mapping to another venue or currency is performed. Provider results
must match all three identity fields. Fallbacks may supply missing data only for
the exact same instrument. Identity conflicts stop analysis and cannot trigger
fallback to a conveniently available different market.

Quotes include source, source URL, retrieval time, price timestamp, regular
price, session, daily percentage change and available 52-week bounds. A regular
price is never relabeled as pre-market or after-hours. Extended metadata is
used only when its own price and newer timestamp are both present. When extended quote metadata is absent, completed one-minute chart bars may
provide the last extended-session close, but only inside explicit provider
pre/post trading-period bounds. The output labels this price basis and the
provider bar-start timestamp. In-progress minute bars are excluded. Otherwise
regular-session data remains explicitly labeled. The regular trading period
indicates whether the regular market is open; the delay is `unknown` unless a
provider supplies a reliable delay declaration.

Freshness is recalculated from the price timestamp on every cached response.
Quotes older than 900 seconds are marked stale, including closed-market quotes.
A closed market does not turn an old close into a live price. Future or missing
timestamps and invalid prices are rejected. Indicators and news keep their own
dates; fetch time is not an observation date.

## Performance, caching and errors

| Dataset | TTL |
| --- | ---: |
| Quote | 30 s |
| Daily history | 300 s |
| Fundamentals | 3600 s |
| News | 600 s |
| Symbol search | 86400 s |

The provider cache is in-process, bounded to 256 responses and 256 negative-cache entries and returns detached
copies. Transport permits only fixed HTTPS Yahoo hosts, validated ticker path
components and encoded query parameters. Redirects are blocked, responses are
limited to 2 MB, each request has a 4-second timeout, and transient network/5xx
errors get one bounded retry. HTTP 401/404 are not retried; failures are negatively cached for at most 60 seconds. HTTP 429 activates a
60-second cooldown. A rolling 60-request/minute limiter protects the process.

Four independent datasets run concurrently per analysis. Four top-level finance
requests may run concurrently; excess requests fail `finance_busy`. Comparisons
and portfolios accept at most ten instruments. Instruments are processed
sequentially to keep fan-out bounded. The web Finance API allows 360 seconds for
a worst-case bounded batch including twenty tracking snapshots; ordinary quotes avoid all fundamentals/news requests.
No extra web searches or LLM calls are made for finance data.

## Indicators and fundamentals

The provider supplies two years of daily history. In-progress bars are excluded.
The selected basis is adjusted close only if every accepted bar supplies it;
otherwise all indicators use raw close. No mixing or gap interpolation occurs.

- SMA/EMA 20/50/200 require sufficient observations. EMA uses an SMA seed.
- RSI 14 uses Wilder smoothing; flat prices produce RSI 50.
- MACD is EMA12 minus EMA26, with an EMA9 signal.
- Volatility uses sample standard deviation of the last 20 log returns,
  annualized with sqrt(252). Momentum is the 20-observation return.
- Trend is the latest completed close relative to SMA200.
- Support/resistance is explicitly the envelope of 20 completed closing prices,
  not a prediction, intraday pivot or validated support model.
- 1W/1M/3M/6M/1Y performance uses the last observation at or before the calendar
  cutoff. Actual dates and basis accompany the percentages.

Fundamentals preserve provider raw values for capitalization, revenue/growth,
EPS/growth, free cash flow, margins, debt, debt/equity, P/E, forward P/E, PEG and
price/sales. Reporting currency is separate from listing currency. `as_of` is
the provider's most recent reported quarter end when available, **not** a filing
date or proof that every metric belongs to that quarter. Values mix latest
reported/TTM metrics as indicated; unavailable periods stay unknown.

News requires explicit related-ticker metadata, a valid HTTPS link, publisher
and timestamp within the past seven days. Search snippets never supply prices
or sentiment. Macro context, future catalysts and reliable sentiment currently
remain unavailable without an independently verifiable source. Cases and risk
flags derive only from observed growth, valuation, trend and volatility.

## Deterministic scoring

`analytics.py` owns `finance-rules-1`, the thresholds, weights and mapping. This
is a transparent heuristic, **not** an empirically calibrated investment model.

| Component | Weight | Method |
| --- | ---: | --- |
| Fundamental | 20 | Mean of profit margin (0–30%) and inverse debt/equity (0–200%) |
| Growth | 20 | Mean of revenue growth (-10–40%) and EPS growth (-20–50%) |
| Valuation | 20 | Inverse positive trailing P/E (10–50); nonpositive P/E unavailable |
| Technical | 15 | Mean of trend (up 80, flat 50, down 20) and RSI (30–70) |
| Momentum | 10 | Linear 20-day return (-15–15%) |
| Sentiment | 5 | Verified -1–1 observation, dated within seven days; native source unavailable |
| Risk | 10 | Inverse annual volatility (15–80%) |

Linear scores are clamped to 0–100. Components requiring two inputs require
both. Only available components contribute; the weighted score is normalized
by covered weights. Coverage must reach 70%, and Fundamental, Growth and
Valuation must all exist. The quote must not be stale; quarter-end must be known
and at most 180 days old; history must be at most seven days old. Otherwise the
score is null and the recommendation is `insufficient data`.

85–100 Strong Buy, 70–84 Buy, 55–69 Hold, 40–54 Reduce, 0–39 Sell. The horizon is
3–12 months. Confidence starts as covered weight/100, is multiplied by .85 when
quote delay is unknown, and is capped at .35 when quality gates fail. It measures
data completeness/freshness, **not** a probability of profit. Subscores may still
be shown with an insufficient overall score. The rules are shared by API, chat,
tracking and agents, with no free-form LLM rating.

## Tracking and portfolio privacy

Analysis and comparison snapshots in a bound chat are appended to
`~/.config/mlx-web/finance/recommendations.json` using the existing atomic-write
helper, a process lock, private directory and mode 0600 files. The snapshot
contains listing, timestamp, quote, fundamentals, indicators, score/subscores,
confidence, horizon, rule version and sources. There is no update API for old
recommendations. A corrupt store is never silently replaced. Persistence failure
keeps analysis available and reports tracking unavailable. The store is bounded
to 10,000 snapshots and then rejects new snapshots without deleting history.
Only one Agent process should own this JSON store.

Tracking reads only the bound chat, displays at most its latest twenty snapshots,
and never mutates them. Price performance uses the exact saved quote as its anchor, explicitly
unadjusted for dividends/splits/fees/taxes. Daily-history returns, benchmark
comparison, alpha and drawdown are separate metrics with their actual date window,
which may start before the recommendation quote. Daily-window alpha requires a
USD US-listed instrument, SPY data, identical basis and aligned daily dates.
Quote-anchored alpha remains unavailable without an exact benchmark quote anchor. Missing or
truncated history produces unavailable metrics rather than fabricated returns.
Max drawdown uses the observed daily path; completeness is separately indicated.
BUY/SELL price-change hit classification starts after at least 90 days, requires
verified adjustment factors without detected corporate actions, and excludes
stale prices. Hold has no hit label.
Statistics exclude stale and unevaluable results. They describe snapshots,
including repeated analyses, not independent trades or a backtest.

Portfolio quantities remain local. Only tickers are sent to the data provider,
never sizes, portfolio names, chat contents or aggregate holdings. Long-only
positive quantities are required. Mixed currencies are not aggregated without
FX data. Available sectors include an explicit unknown bucket. Correlation uses
Pearson correlation of aligned daily returns, minimum 30 overlapping observations,
maximum 252. Concentration uses HHI and maximum weight (>40% high, >20% moderate).
Ranking includes only positions with an adequate score; unrated positions are
explicitly excluded and ranking completeness is reported. Overall risk is
insufficient when position assessments lack data. There is no
calibrated VaR, cash, short-selling, tax or derivative model.

## API

POST `/api/finance/{tool}` on the Agent, proxied through
`/api/mlx/finance/{tool}` on the web app. Allowed suffixes are `quote`, `analyze`,
`compare`, `portfolio_analysis`, `history`, `recommendation_performance`.

```json
{"prompt":"Analysiere AMD","chat_id":"my-chat","options":{"symbol":"AMD","exchange":"NASDAQ","currency":"USD","track":true}}
```

Options support `symbol`, `symbols`, `exchange`, `currency`, `track`, and for
portfolios `positions: [{"symbol":"AMD","quantity":10}]`. Chat ownership comes
from the bound RunContext, not model-supplied tool options. The existing local
web/Agent access policy applies. This is local storage scoping, not multi-user
authentication. No changes to the stateless `/v1/chat/completions` protocol or
automatic finance-tool execution for external clients.

## TradingAgents decision

Reviewed upstream on 2026-10-08:
[README](https://github.com/TauricResearch/TradingAgents),
[dependencies](https://github.com/TauricResearch/TradingAgents/blob/main/pyproject.toml),
[graph](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/graph/trading_graph.py),
[configuration](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/default_config.py).
TradingAgents supports OpenAI-compatible endpoints and independent model tiers,
so a local MLX adapter is technically possible. Its LangGraph orchestration,
LangChain clients, own dataflows, memory/checkpoints and LLM-derived ratings
would duplicate this repository's existing runtime and deterministic rules.
We deliberately do not integrate it for this release. Native deterministic cases
remain the source of truth, with no extra Qwen analyst/debate calls. A future
optional debate adapter must consume native evidence without changing scores,
sending holdings externally or enabling order execution.

## Validation and troubleshooting

`test-venv/bin/python -m pytest -q tests/test_finance.py` covers routing, quotes,
identity/currencies, sessions, freshness, cache, retries/rate limits, safe
fallback/conflicts, fundamentals/news, known indicator vectors, score boundaries,
confidence, comparison, portfolio, immutable persistence, tracking/alpha,
permissions, chat, API and the web proxy. All provider transports and times are
controlled; no external network calls belong in deterministic CI.
`node --test tests/test_finance_ui.mjs tests/test_help_content.mjs tests/test_help_ui.mjs`
checks bilingual display, stale/insufficient data, untrusted text, production
asset wiring and help topics. Browser acceptance also exercises the production
Finance asset in both desktop/mobile viewports.

- `market_selection_required`: provide the ticker for the requested exchange.
- `provider_identity_conflict`: do not trust the result; investigate the provider
  mapping. No automatic alternative listing is used.
- `provider_rate_limited`: wait at least sixty seconds; repeated calls cannot
  defeat the cooldown.
- `fundamentals_unavailable` or an undated quarter: quotes/technicals may work,
  but a score remains unavailable until sufficient dated inputs exist.
- `stale_quote`: inspect the observation time and trading session. Market closure
  and upstream delays are visible limitations, not a reason to invent live prices.
- `positions_required`: provide explicit `TICKER: quantity` pairs or API positions.
- Tracking unavailable: check private store permissions/corruption/capacity;
  preserve the ledger and do not silently reset it.
