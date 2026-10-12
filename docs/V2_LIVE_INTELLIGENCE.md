# MLX Nobby 2.0 — Live Intelligence (initial implementation)

## Implemented

- Chat streaming inspects the latest user question for German inflation-related intents.
- When matched, it requests Germany's published annual CPI inflation observations from the World Bank public API, with a six-second timeout.
- The result is injected as a system-level data context including source link and UTC retrieval date.
- On fetch failure, the model receives an explicit refusal to invent current inflation figures.
- Local chat content and workspace data are not sent to the provider: the request URL is static.

## Known limitations — not a complete 2.0 release

- Annual World Bank CPI series is not an exact monthly German CPI comparison; this integration **must not** claim to calculate an exact 36-month wage adjustment.
- Destatis/GENESIS monthly source is linked but automated monthly retrieval and deterministic CPI index computations still need to be implemented.
- General web search, finance-provider routing, source citations in the UI, robust prompt-injection handling, live end-to-end browser verification and broader integration tests are future milestones.
- The feature's tests are offline and use fixture data.

## Verify

`python -m unittest tests.test_live_intelligence`

Do not tag `v2.0.0` until release criteria, actual live endpoint and regression suite have been verified.

## Follow-up: source consistency

- Requested explicit years now determine the extracted observations rather than silently showing the latest three years.
- The CPI context supplies one machine-readable bar-chart dataset from the same fetched observations as the text, with two-decimal source precision.
- Inference instructions explicitly prohibit attributing World Bank values to Destatis or fabricating higher-precision Destatis values and extra sources.
- **Not yet enforced end to end:** an LLM can still ignore its instructions or invent a second chart; a server-owned chart rendering payload and source validation are required for hard guarantees.
- New offline fixtures test requested-year selection and no-data behavior; live endpoints and browser UI still require real-world validation.

## Automatic public web research (experimental)

The chat endpoint now recognizes explicit freshness intent (e.g. "heute", "aktuell", current year, news, recent releases, prices, leadership). It performs a bounded public search before local inference: DuckDuckGo Lite result titles/links for ordinary questions, Google News RSS for news prompts. Retrieval is best-effort with a 5-second request timeout and a 160 KB response limit. No search credentials are required. World Bank inflation retrieval remains separate.

**Privacy:** Only the current user question (8–260 characters) is eligible for outbound search. No conversation history, knowledge-base documents or system prompts are sent. A conservative denylist blocks local addresses, private language, credentials, repository/workspace and other potentially personal requests. This heuristic is not a data-loss-prevention guarantee: avoid entering sensitive content into public questions, and consider an explicit external-search consent control before production.

**Quality limits:** Search responses are *titles and links*, not independently read or verified article bodies; the model is told to distinguish search results from verified facts. The current implementation is **not** a general-purpose fact checker and cannot guarantee that it detects every uncertain answer, or that it rejects every misleading search result. HTML selectors and endpoints are provider dependent and need live browser/integration testing. Network failure is surfaced as unverified, never replaced by fictional results.

Run offline regression tests with `python -m unittest tests.test_web_research tests.test_live_intelligence`, and syntax checks via `python -m py_compile backend/web_research.py backend/live_intelligence.py backend/app.py` before Docker rebuild.
