/* Finance uses the existing Markdown renderer and bilingual help conventions. */
(() => {
    'use strict';
    const localText = (de, en) => window.MLXI18n?.getLanguage?.() === 'de' ? de : en;
    const safe = value => String(value ?? '').replace(/[\\`*_{}\[\]<>|]/g, ' ').replace(/[\r\n]/g, ' ');
    const numeric = value => typeof value === 'number' && Number.isFinite(value);
    const num = value => numeric(value) ? new Intl.NumberFormat(window.MLXI18n?.getLanguage?.() === 'de' ? 'de-DE' : 'en-US', { maximumFractionDigits: 4 }).format(value) : localText('nicht verfügbar', 'unavailable');
    const pct = value => numeric(value) ? num(value * 100) + '%' : num(value);
    const date = stamp => numeric(stamp) ? new Date(stamp * 1000).toISOString() : localText('unbekannt', 'unknown');
    const reasons = {
        insufficient_score_coverage: () => localText('Zu wenig Daten für den Score', 'Insufficient score coverage'),
        stale_quote: () => localText('Veralteter Kurs', 'Stale quote'),
        fundamentals_date_unverified: () => localText('Fundamentaldaten: Datum nicht bestätigt', 'Fundamentals date unverified'),
        stale_history: () => localText('Veraltete oder fehlende Historie', 'Stale or missing history'),
        market_risk: () => localText('Allgemeines Marktrisiko', 'Market risk'),
        heuristic_model_risk: () => localText('Heuristisches, nicht kalibriertes Modell', 'Heuristic, uncalibrated model'),
        positive_revenue_growth: () => localText('Positives Umsatzwachstum', 'Positive revenue growth'),
        nonpositive_revenue_growth: () => localText('Kein positives Umsatzwachstum', 'Nonpositive revenue growth'),
        above_sma200: () => localText('Über SMA 200', 'Above SMA 200'), not_above_sma200: () => localText('Nicht über SMA 200', 'Not above SMA 200'),
        high_pe: () => localText('Hohes KGV (>40)', 'High P/E (>40)'), valuation_risk: () => localText('Bewertungsrisiko', 'Valuation risk'),
        high_volatility: () => localText('Hohe Volatilität', 'High volatility'), missing_fundamentals: () => localText('Fehlende Fundamentaldaten', 'Missing fundamentals')
    };
    const reason = code => reasons[code] ? reasons[code]() : safe(code);
    const errorCopy = {
        symbol_required: () => localText('Bitte einen Ticker angeben.', 'Please provide a ticker.'),
        invalid_symbol: () => localText('Ungültiger Ticker.', 'Invalid ticker.'),
        ambiguous_symbol: () => localText('Mehrdeutiges Unternehmen: Bitte Ticker und Börse angeben.', 'Ambiguous company: specify ticker and exchange.'),
        market_selection_required: () => localText('Ticker passt nicht zur angefragten Börse/Währung. Bitte den Börsenticker angeben (z. B. AMD statt AMD.DE).', 'Ticker does not match the requested exchange/currency. Specify the exchange ticker (e.g. AMD versus AMD.DE).'),
        provider_identity_conflict: () => localText('Widersprüchliche Providerdaten zu Ticker, Börse oder Währung. Keine Bewertung.', 'Conflicting provider ticker, exchange or currency. No rating.'),
        tracking_owner_required: () => localText('Tracking benötigt einen gebundenen Chat.', 'Tracking requires a bound chat.'),
        provider_rate_limited: () => localText('Marktdatenprovider begrenzt Anfragen. Bitte nach einer Minute erneut versuchen.', 'Market data rate limited. Retry after one minute.'),
        provider_timeout: () => localText('Zeitlimit beim Marktdatenprovider erreicht.', 'Market data provider timed out.'),
        finance_busy: () => localText('Finance ist ausgelastet. Bitte erneut versuchen.', 'Finance is busy. Please retry.'),
        comparison_symbols_required: () => localText('Bitte mindestens zwei verschiedene Ticker angeben.', 'Provide at least two different tickers.'),
        single_symbol_required: () => localText('Bitte einen Ticker angeben oder einen Vergleich anfordern.', 'Provide one ticker or request a comparison.'),
        invalid_quantity: () => localText('Positionen benötigen positive Stückzahlen.', 'Positions require positive quantities.'),
        duplicate_positions: () => localText('Bitte gleiche Positionen zusammenfassen.', 'Please combine duplicate positions.')
    };
    function failure(result) {
        const code = result.data?.code || result.error;
        return '**Finance Intelligence**\n\n' + (errorCopy[code] ? errorCopy[code]() : localText('Marktdaten sind nicht verfügbar. Es werden keine Kurse oder Bewertungen geschätzt.', 'Market data is unavailable. Prices and ratings are not estimated.'));
    }
    function quote(report) {
        const q = report.quote || {}, i = report.instrument || {};
        const status = q.stale ? localText('VERALTET', 'STALE') : localText('zuletzt gemeldet', 'last reported');
        const session = {regular: localText('Regulär', 'Regular'), 'pre-market': 'Pre-Market', 'after-hours': 'After-Hours'}[q.session] || safe(q.session);
        return [
            `**${safe(i.name || i.symbol)} (${safe(i.symbol)})**`,
            `${localText('Kurs', 'Price')}: **${num(q.price)} ${safe(q.currency)}** · ${safe(q.exchange)} · ${session}`,
            q.price_basis === 'completed_minute_close' ? localText('Kursbasis: letzter abgeschlossener Minutenschluss; Zeitstempel ist der Bar-Beginn.', 'Price basis: last completed minute close; timestamp is bar start.') : '',
            `${localText('Stand', 'As of')}: ${date(q.timestamp)} · ${localText('Datenalter', 'Age')}: ${num(q.age_seconds)} s · **${status}**`,
            `${localText('Verzögerung', 'Delay')}: ${q.delay_status === 'unknown' ? localText('unbekannt; kein garantierter Echtzeitkurs', 'unknown; no guaranteed live quote') : safe(q.delay_status)} · ${q.market_open ? localText('regulärer Markt offen', 'regular market open') : localText('regulärer Markt geschlossen/Status unbekannt', 'regular market closed/status unknown')}`,
            `${localText('Tagesänderung', 'Day change')}: ${numeric(q.day_change_percent) ? num(q.day_change_percent) + '%' : num(null)} · 52W: ${num(q.fifty_two_week_low)} – ${num(q.fifty_two_week_high)}`
        ].filter(Boolean).join('\n\n');
    }
    function sources(report) {
        const rows = Object.entries(report.sources || {}).filter(([, s]) => s.provider)
            .map(([kind, s]) => `${safe(kind)}: ${safe(s.provider)} (${date(s.retrieved_at)})`);
        if (report.quote?.source) rows.unshift(`${localText('Kurs', 'Quote')}: ${safe(report.quote.source)} · ${safe(report.quote.source_url)}`);
        return '\n\n**' + localText('Quellen', 'Sources') + '**\n\n' + (rows.join('\n\n') || localText('nicht verfügbar', 'unavailable'));
    }
    const metricLabels = {
        market_cap: () => localText('Marktkapitalisierung', 'Market cap'), revenue: () => localText('Umsatz', 'Revenue'),
        revenue_growth: () => localText('Umsatzwachstum', 'Revenue growth'), eps: () => localText('Gewinn/Aktie', 'EPS'),
        eps_growth: () => localText('EPS-Wachstum', 'EPS growth'), free_cash_flow: () => localText('Free Cashflow', 'Free cash flow'),
        profit_margin: () => localText('Gewinnmarge', 'Profit margin'), operating_margin: () => localText('Operative Marge', 'Operating margin'),
        debt: () => localText('Verschuldung', 'Debt'), debt_to_equity: () => localText('Debt/Equity (%)', 'Debt/equity (%)'),
        pe: () => localText('KGV', 'P/E'), forward_pe: () => localText('Forward KGV', 'Forward P/E'), peg: () => localText('PEG', 'PEG'), price_sales: () => localText('KUV', 'Price/sales')
    };
    function performance(report) {
        return Object.entries(report.performance || {}).map(([period, value]) => `${safe(period)}: ${numeric(value.percent) ? num(value.percent) + '%' : num(null)}`).join(' · ');
    }
    function analysis(report) {
        const a = report.assessment || {}, f = report.fundamentals || {}, t = report.technicals || {}, c = report.cases || {};
        const metrics = Object.entries(metricLabels).map(([key, label]) => `${label()}: ${['revenue_growth', 'eps_growth', 'profit_margin', 'operating_margin'].includes(key) ? pct(f.values?.[key]) : num(f.values?.[key])}`);
        const news = (report.news?.items || []).map(item => `${date(item.timestamp)} · ${safe(item.source)} · ${safe(item.title)} · ${safe(item.url)}`);
        const assessment = a.score == null ? localText('Unzureichende Daten (insufficient data)', 'Insufficient data') : `${num(a.score)}/100 · ${safe(a.recommendation)}`;
        const lines = [quote(report), performance(report), `**${localText('Bewertung', 'Assessment')}: ${assessment}**`,
            `${localText('Konfidenz', 'Confidence')}: ${pct(a.confidence)} · ${localText('Horizont', 'Horizon')}: ${safe(a.horizon)}`,
            localText('Konfidenz beschreibt Datenqualität, nicht Gewinnwahrscheinlichkeit. Score: feste heuristische Regeln, keine validierte Handelsstrategie.', 'Confidence describes data quality, not profit probability. Score: fixed heuristic rules, not a validated trading strategy.'),
            (a.reasons || []).map(reason).join(' · '),
            `**${localText('Fundamentaldaten', 'Fundamentals')}** · ${localText('Berichtswährung', 'Reporting currency')}: ${safe(f.reporting_currency || localText('unbekannt', 'unknown'))} · ${localText('Periode', 'Period')}: ${safe(f.period || localText('unbekannt', 'unknown'))} · ${date(f.as_of)}`,
            metrics.join(' · '),
            `**${localText('Technisch', 'Technical')}** · ${date(t.as_of)} · ${safe(t.price_basis)} · ${localText('Trend', 'Trend')}: ${safe(({up: localText('aufwärts', 'up'), down: localText('abwärts', 'down'), flat: localText('seitwärts', 'flat')})[t.trend] || localText('unbekannt', 'unknown'))}`,
            [20, 50, 200].map(p => `SMA/EMA ${p}: ${num(t.sma?.[p])}/${num(t.ema?.[p])}`).join(' · '),
            `RSI 14: ${num(t.rsi14)} · MACD: ${num(t.macd?.value)} / ${num(t.macd?.signal)} · ${localText('Volatilität (annualisiert)', 'Annualized volatility')}: ${pct(t.volatility_annual)} · Momentum 20: ${pct(t.momentum_20)}`,
            `${localText('Support/Resistance: Hülle der letzten 20 Tagesschlusskurse', 'Support/resistance: envelope of last 20 daily closes')}: ${num(t.support)}/${num(t.resistance)}`,
            `**News**\n\n${news.join('\n\n') || localText('Keine verifizierten Unternehmensnews der letzten 7 Tage verfügbar.', 'No verified company news from the last 7 days available.')}`,
            localText('Makro-/Branchenkontext, Sentiment und zukünftige Katalysatoren: nicht unabhängig verifiziert. Web-News ergänzen Kontext, ersetzen keine Kursquelle.', 'Macro/sector context, sentiment and future catalysts: not independently verified. Web news adds context, never replaces quote sources.'),
            `**Bull Case**: ${(c.bull || []).map(reason).join('; ') || num(null)}`,
            `**Bear Case**: ${(c.bear || []).map(reason).join('; ') || num(null)}`,
            `**${localText('Risiken', 'Risks')}**: ${(c.risks || []).map(reason).join('; ')}`,
            `**${localText('Teil-Scores', 'Subscores')}**: ${Object.entries(a.subscores || {}).map(([key, value]) => `${safe(key)} ${num(value)} (${num(a.weights?.[key])}%)`).join(' · ')}`,
            `${localText('Datenabdeckung', 'Data coverage')}: ${pct(a.coverage)} · ${safe(a.rules_version)}`,
            report.tracking_status === 'unavailable' ? localText('Lokales Tracking nicht verfügbar; die Analyse wurde nicht gespeichert.', 'Local tracking unavailable; this analysis was not saved.') : '',
            report.recommendation_id ? `${localText('Lokal gespeicherte Analyse', 'Locally saved analysis')}: ${safe(report.recommendation_id)}` : '',
            sources(report)];
        return lines.filter(Boolean).join('\n\n');
    }
    function summary(result) {
        if (result.status !== 'completed') return failure(result);
        const data = result.data || result;
        if (data.kind === 'quote') return quote(data) + sources(data);
        if (data.kind === 'analysis') return analysis(data);
        if (data.kind === 'comparison') return (data.reports || []).map(analysis).join('\n\n---\n\n') + '\n\n' + localText('Ranking (nur bewertbare Aktien)', 'Ranking (rated stocks only)') + ': ' + ((data.ranking || []).map(safe).join(', ') || localText('unzureichende Daten', 'insufficient data'));
        if (data.kind === 'history') return `**${safe(data.instrument?.symbol)} · ${safe(data.instrument?.exchange)} · ${safe(data.instrument?.currency)}**\n\n${performance(data)}\n\n${localText('Basis', 'Basis')}: ${safe(data.history?.price_basis)} · ${date(data.technicals?.as_of)} · ${safe(data.history?.source)}\n\n${localText('Historische Schlusskurse, keine Echtzeitkurse.', 'Historical closing prices, not live quotes.')}`;
        if (data.kind === 'portfolio') {
            const concentration = {high: localText('hoch', 'high'), moderate: localText('mittel', 'moderate'), lower: localText('niedriger', 'lower')};
            if (data.status === 'positions_required') return localText('Bitte Positionen mit Stückzahlen angeben, z. B. „Analysiere mein Portfolio: AMD: 10, NVDA: 5“. Keine Positionen wurden angenommen.', 'Provide positions with quantities, e.g. “Analyze my portfolio: AMD: 10, NVDA: 5”. No positions were assumed.');
            const rows = (data.positions || []).map(p => `${safe(p.instrument?.symbol)} · ${safe(p.instrument?.exchange)} · ${num(p.quantity)} × ${num(p.price)} · ${num(p.value)} ${safe(p.instrument?.currency)} · ${localText('Gewicht', 'Weight')}: ${pct(p.weight)} · ${safe(p.sector)} · ${date(p.timestamp)} · ${safe(p.source)} · ${p.assessment?.score == null ? localText('unzureichende Daten', 'insufficient data') : num(p.assessment.score) + '/100 · ' + safe(p.assessment.recommendation)} · ${localText('Konfidenz', 'Confidence')}: ${pct(p.assessment?.confidence)} · ${(p.risks || []).map(reason).join('; ')}${p.stale ? ' · ' + localText('VERALTET', 'STALE') : ''}`);
            const sectors = Object.entries(data.sectors || {}).map(([sector, weight]) => `${safe(sector)}: ${pct(weight)}`).join(' · ');
            const correlations = (data.correlations || []).map(p => `${safe(p.left)}/${safe(p.right)}: ${num(p.value)} (n=${num(p.observations)})`).join(' · ');
            return `**${localText('Portfolio-Analyse', 'Portfolio analysis')}**\n\n${rows.join('\n\n')}\n\n${data.status === 'currency_conversion_required' ? localText('Verschiedene Währungen: keine Gesamtbewertung ohne FX-Daten.', 'Mixed currencies: no aggregate valuation without FX data.') : `${localText('Gesamtwert', 'Total value')}: ${num(data.total_value)} ${safe(data.currency)} · HHI: ${num(data.concentration_hhi)} · ${localText('Konzentration', 'Concentration')}: ${concentration[data.concentration_risk] || num(null)}`}\n\n${localText('Sektoren', 'Sectors')}: ${sectors}\n\n${localText('Korrelation (tägliche Renditen)', 'Correlation (daily returns)')}: ${correlations}\n\n${localText('Gesamtrisiko', 'Overall risk')}: ${data.risk === 'insufficient data' ? localText('unzureichende Daten', 'insufficient data') : localText('heuristisch', 'heuristic')}\n\n${localText('Nur Long-Positionen; keine Orderausführung, FX-, Steuer-, Cash- oder Derivatemodellierung.', 'Long-only support; no order execution, FX, tax, cash or derivatives modeling.')}`;
        }
        if (data.kind === 'tracking') {
            const rows = (data.items || []).map(p => [
                `${safe(p.symbol || p.id)} · ${safe(p.recommendation || '')}`,
                `${localText('Kursänderung seit Empfehlung (unbereinigt)', 'Price change since recommendation (unadjusted)')}: ${pct(p.return)} · ${date(p.quote_from)} – ${date(p.as_of)}${p.stale ? ' · ' + localText('VERALTET', 'STALE') : ''}`,
                `${localText('Separates Tageskursfenster', 'Separate daily-close window')}: ${date(p.history_from)} – ${date(p.history_to)} · ${safe(p.history_basis)}`,
                `${localText('Tageskursrendite', 'Daily-close return')}: ${pct(p.history_return)} · ${localText('Benchmark / Tageskurs-Alpha', 'Benchmark / daily-close alpha')}: ${pct(p.benchmark_return)} / ${pct(p.history_alpha)}`,
                `${localText('Drawdown im Tageskursfenster', 'Drawdown in daily-close window')}: ${pct(p.max_drawdown)}${p.drawdown_complete === false ? ' · ' + localText('unvollständig', 'partial') : ''}`
            ].join(' · '));
            return [
                `**${localText('Frühere Empfehlungen', 'Previous recommendations')}**`,
                rows.join('\n\n') || localText('Keine gespeicherten Analysen in diesem Chat.', 'No saved analyses in this chat.'),
                `${localText('Durchschnittliche Kursänderung (unbereinigt)', 'Average price change (unadjusted)')}: ${pct(data.statistics?.average_return)} · ${localText('Kursbasierte Trefferquote', 'Price-based hit rate')}: ${pct(data.statistics?.hit_rate)}`,
                localText('Kursänderungen verwenden den gespeicherten Empfehlungskurs und sind keine Gesamtrendite: Dividenden, Splits, Gebühren und Steuern fehlen. Tageskurs-Alpha und Drawdown gehören zum separat datierten Historienfenster. Treffer erst nach 90 Tagen und nur ohne erkannte Corporate Actions; Hold wird nicht gewertet. Letzte 20 Analysen; wiederholte Analysen sind keine unabhängigen Trades.', 'Price changes use the saved recommendation price and are not total returns: dividends, splits, fees and taxes are excluded. Daily-close alpha and drawdown belong to the separately dated history window. Hits require 90 days and no detected corporate actions; Hold is excluded. Latest 20 analyses; repeated analyses are not independent trades.')
            ].join('\n\n');
        }
        return failure(result);
    }
    window.MLXFinance = { summary, failure };
})();
