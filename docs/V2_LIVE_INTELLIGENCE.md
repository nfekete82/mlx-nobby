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
