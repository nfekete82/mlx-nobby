/* Finance Intelligence: safe plain-text summaries plus native visual cards. */
(() => {
    'use strict';

    const language = () => window.MLXI18n?.getLanguage?.() === 'de' ? 'de' : 'en';
    const localText = (de, en) => language() === 'de' ? de : en;
    const locale = () => language() === 'de' ? 'de-DE' : 'en-US';
    const numeric = value => typeof value === 'number' && Number.isFinite(value);
    const safe = value => String(value ?? '').replace(/[\\`*_{}\[\]<>|]/g, ' ').replace(/[\r\n]/g, ' ').trim();
    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

    const format = (value, options = {}) => numeric(value)
        ? new Intl.NumberFormat(locale(), options).format(value)
        : localText('—', '—');
    const num = value => format(value, { maximumFractionDigits: 2 });
    const price = value => format(value, {
        minimumFractionDigits: numeric(value) && Math.abs(value) >= 1 ? 2 : 4,
        maximumFractionDigits: numeric(value) && Math.abs(value) >= 1 ? 2 : 4
    });
    const compact = value => numeric(value)
        ? new Intl.NumberFormat(locale(), { notation: 'compact', maximumFractionDigits: 1 }).format(value)
        : localText('—', '—');
    const currencyValue = (value, currency, compactMode = false) => {
        if (!numeric(value) || !currency) return localText('—', '—');
        try {
            return new Intl.NumberFormat(locale(), {
                style: 'currency',
                currency: String(currency).toUpperCase(),
                currencyDisplay: 'narrowSymbol',
                notation: compactMode ? 'compact' : 'standard',
                minimumFractionDigits: compactMode ? 0 : (Math.abs(value) >= 1 ? 2 : 4),
                maximumFractionDigits: compactMode ? 1 : (Math.abs(value) >= 1 ? 2 : 4)
            }).format(value);
        } catch (_) {
            return (compactMode ? compact(value) : price(value)) + ' ' + safe(currency);
        }
    };
    function fxInfo(report, currency) {
        const code = String(currency || '').toUpperCase();
        return report?.display_fx?.rates?.[code] || null;
    }
    function money(report, value, currency, compactMode = false) {
        const code = String(currency || '').toUpperCase();
        if (!numeric(value) || !code) return localText('—', '—');
        const original = currencyValue(value, code, compactMode);
        if (code === 'EUR') return original;
        const fx = fxInfo(report, code);
        if (!numeric(fx?.rate) || fx.rate <= 0) return original;
        const eur = currencyValue(value * fx.rate, 'EUR', compactMode);
        return '≈ ' + eur + ' (' + original + ')';
    }
    function fxLabel(report, currency) {
        const fx = fxInfo(report, currency);
        if (!fx || String(currency || '').toUpperCase() === 'EUR') return '';
        const dateText = fx.date || (numeric(fx.as_of) ? shortDate(fx.as_of) : '');
        return [safe(fx.source || 'ECB'), dateText].filter(Boolean).join(' · ');
    }
    const pct = value => numeric(value)
        ? format(value * 100, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%'
        : localText('—', '—');
    const pctPoints = value => numeric(value)
        ? format(value, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%'
        : localText('—', '—');
    const signedPctPoints = value => numeric(value)
        ? (value > 0 ? '+' : '') + format(value, { minimumFractionDigits: 1, maximumFractionDigits: 2 }) + '%'
        : localText('—', '—');
    const date = stamp => numeric(stamp)
        ? new Intl.DateTimeFormat(locale(), {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        }).format(new Date(stamp * 1000))
        : localText('unbekannt', 'unknown');
    const shortDate = stamp => numeric(stamp)
        ? new Intl.DateTimeFormat(locale(), {
            day: '2-digit', month: '2-digit', year: '2-digit'
        }).format(new Date(stamp * 1000))
        : localText('unbekannt', 'unknown');
    function age(seconds) {
        if (!numeric(seconds) || seconds < 0) return localText('unbekannt', 'unknown');
        if (seconds < 60) return Math.round(seconds) + ' s';
        if (seconds < 3600) {
            const minutes = Math.floor(seconds / 60);
            const rest = Math.round(seconds % 60);
            return minutes + ' min' + (rest ? ' ' + rest + ' s' : '');
        }
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return hours + ' h' + (minutes ? ' ' + minutes + ' min' : '');
    }
    function session(value) {
        return {
            regular: localText('Regulär', 'Regular'),
            'pre-market': 'Pre-Market',
            'after-hours': 'After-Hours'
        }[value] || safe(value || localText('unbekannt', 'unknown'));
    }
    function trend(value) {
        return {
            up: localText('Aufwärts', 'Up'),
            down: localText('Abwärts', 'Down'),
            flat: localText('Seitwärts', 'Flat')
        }[value] || localText('Unbekannt', 'Unknown');
    }
    function safeUrl(value) {
        try {
            const parsed = new URL(String(value || ''));
            return parsed.protocol === 'https:' ? parsed.href : null;
        } catch (_) {
            return null;
        }
    }

    const reasons = {
        insufficient_score_coverage: () => localText('Zu wenig Daten für den Score', 'Insufficient score coverage'),
        stale_quote: () => localText('Veralteter Kurs', 'Stale quote'),
        fundamentals_date_unverified: () => localText('Fundamentaldaten: Datum nicht bestätigt', 'Fundamentals date unverified'),
        stale_history: () => localText('Veraltete oder fehlende Historie', 'Stale or missing history'),
        market_risk: () => localText('Allgemeines Marktrisiko', 'Market risk'),
        heuristic_model_risk: () => localText('Heuristisches, nicht kalibriertes Modell', 'Heuristic, uncalibrated model'),
        positive_revenue_growth: () => localText('Positives Umsatzwachstum', 'Positive revenue growth'),
        nonpositive_revenue_growth: () => localText('Kein positives Umsatzwachstum', 'Nonpositive revenue growth'),
        above_sma200: () => localText('Über SMA 200', 'Above SMA 200'),
        not_above_sma200: () => localText('Nicht über SMA 200', 'Not above SMA 200'),
        high_pe: () => localText('Hohes KGV (>40)', 'High P/E (>40)'),
        valuation_risk: () => localText('Bewertungsrisiko', 'Valuation risk'),
        high_volatility: () => localText('Hohe Volatilität', 'High volatility'),
        missing_fundamentals: () => localText('Fehlende Fundamentaldaten', 'Missing fundamentals')
    };
    const reason = code => reasons[code] ? reasons[code]() : safe(code);

    const errorCopy = {
        symbol_required: () => localText('Bitte einen Ticker oder Unternehmensnamen angeben.', 'Please provide a ticker or company name.'),
        invalid_symbol: () => localText('Ungültiger Ticker oder Unternehmensname.', 'Invalid ticker or company name.'),
        ambiguous_symbol: () => localText('Mehrdeutiges Unternehmen: Bitte Ticker und Börse angeben.', 'Ambiguous company: specify ticker and exchange.'),
        market_selection_required: () => localText('Ticker passt nicht zur angefragten Börse/Währung. Bitte den Börsenticker angeben.', 'Ticker does not match the requested exchange/currency. Specify the exchange ticker.'),
        provider_identity_conflict: () => localText('Widersprüchliche Providerdaten zu Ticker, Börse oder Währung. Keine Bewertung.', 'Conflicting provider ticker, exchange or currency. No rating.'),
        tracking_owner_required: () => localText('Tracking benötigt einen gebundenen Chat.', 'Tracking requires a bound chat.'),
        provider_rate_limited: () => localText('Marktdatenprovider begrenzt Anfragen. Bitte nach einer Minute erneut versuchen.', 'Market data rate limited. Retry after one minute.'),
        provider_timeout: () => localText('Zeitlimit beim Marktdatenprovider erreicht.', 'Market data provider timed out.'),
        finance_busy: () => localText('Finance ist ausgelastet. Bitte erneut versuchen.', 'Finance is busy. Please retry.'),
        comparison_symbols_required: () => localText('Bitte mindestens zwei verschiedene Aktien angeben.', 'Provide at least two different stocks.'),
        single_symbol_required: () => localText('Bitte genau eine Aktie angeben oder einen Vergleich anfordern.', 'Provide one stock or request a comparison.'),
        invalid_quantity: () => localText('Positionen benötigen positive Stückzahlen.', 'Positions require positive quantities.'),
        duplicate_positions: () => localText('Bitte gleiche Positionen zusammenfassen.', 'Please combine duplicate positions.')
    };

    function failure(result) {
        const code = result?.data?.code || result?.error;
        return '**Finance Intelligence**\n\n' + (
            errorCopy[code]
                ? errorCopy[code]()
                : localText(
                    'Marktdaten sind nicht verfügbar. Es werden keine Kurse oder Bewertungen geschätzt.',
                    'Market data is unavailable. Prices and ratings are not estimated.'
                )
        );
    }

    function quoteSummary(report) {
        const q = report.quote || {}, i = report.instrument || {};
        const status = q.stale ? localText('VERALTET', 'STALE') : localText('zuletzt gemeldet', 'last reported');
        return [
            `**${safe(i.name || i.symbol)} (${safe(i.symbol)})**`,
            `${localText('Kurs', 'Price')}: **${money(report, q.price, q.currency)}** · ${safe(q.exchange)} · ${safe(q.currency)} · ${session(q.session)}`,
            `${localText('Stand', 'As of')}: ${date(q.timestamp)} · ${localText('Datenalter', 'Age')}: ${age(q.age_seconds)} · **${status}**`,
            `${localText('Verzögerung', 'Delay')}: ${q.delay_status === 'unknown' ? localText('unbekannt; kein garantierter Echtzeitkurs', 'unknown; no guaranteed live quote') : safe(q.delay_status)}`,
            `${localText('Tagesänderung', 'Day change')}: ${signedPctPoints(q.day_change_percent)} · 52W: ${money(report, q.fifty_two_week_low, q.currency)} – ${money(report, q.fifty_two_week_high, q.currency)}`
        ].join('\n\n');
    }

    function sourceSummary(report) {
        const rows = Object.entries(report.sources || {})
            .filter(([, entry]) => entry?.provider)
            .map(([kind, entry]) => `${safe(kind)}: ${safe(entry.provider)} (${date(entry.retrieved_at)})`);
        if (report.quote?.source) {
            rows.unshift(`${localText('Kurs', 'Quote')}: ${safe(report.quote.source)} · ${safe(report.quote.source_url)}`);
        }
        for (const [currency, fx] of Object.entries(report.display_fx?.rates || {})) {
            if (currency !== 'EUR' && fx?.source) rows.push(`FX ${safe(currency)}→EUR: ${safe(fx.source)} (${safe(fx.date || '')})`);
        }
        return '\n\n**' + localText('Quellen', 'Sources') + '**\n\n' +
            (rows.join('\n\n') || localText('nicht verfügbar', 'unavailable'));
    }

    const metricLabels = {
        market_cap: () => localText('Marktkapitalisierung', 'Market cap'),
        revenue: () => localText('Umsatz', 'Revenue'),
        revenue_growth: () => localText('Umsatzwachstum', 'Revenue growth'),
        eps: () => localText('Gewinn/Aktie', 'EPS'),
        eps_growth: () => localText('EPS-Wachstum', 'EPS growth'),
        free_cash_flow: () => localText('Free Cashflow', 'Free cash flow'),
        profit_margin: () => localText('Gewinnmarge', 'Profit margin'),
        operating_margin: () => localText('Operative Marge', 'Operating margin'),
        debt: () => localText('Verschuldung', 'Debt'),
        debt_to_equity: () => localText('Debt/Equity', 'Debt/equity'),
        pe: () => localText('KGV', 'P/E'),
        forward_pe: () => localText('Forward KGV', 'Forward P/E'),
        peg: () => 'PEG',
        price_sales: () => localText('KUV', 'Price/sales')
    };

    function performanceText(report) {
        return Object.entries(report.performance || {})
            .map(([period, value]) => `${safe(period)}: ${pctPoints(value?.percent)}`)
            .join(' · ');
    }

    function analysisSummary(report) {
        const a = report.assessment || {};
        const assessment = a.score == null
            ? localText('Unzureichende Daten (insufficient data)', 'Insufficient data')
            : `${num(a.score)}/100 · ${safe(a.recommendation)}`;
        return [
            quoteSummary(report),
            performanceText(report),
            `**${localText('Bewertung', 'Assessment')}: ${assessment}**`,
            `${localText('Konfidenz', 'Confidence')}: ${pct(a.confidence)} · ${localText('Horizont', 'Horizon')}: ${safe(a.horizon)}`,
            localText(
                'Konfidenz beschreibt Datenqualität, nicht Gewinnwahrscheinlichkeit. Score: feste heuristische Regeln, keine validierte Handelsstrategie.',
                'Confidence describes data quality, not profit probability. Score: fixed heuristic rules, not a validated trading strategy.'
            ),
            (a.reasons || []).map(reason).join(' · '),
            sourceSummary(report)
        ].filter(Boolean).join('\n\n');
    }

    function summary(result) {
        if (result?.status !== 'completed') return failure(result || {});
        const data = result.data || result;
        if (data.kind === 'quote') return quoteSummary(data) + sourceSummary(data);
        if (data.kind === 'analysis') return analysisSummary(data);
        if (data.kind === 'comparison') {
            return (data.reports || []).map(analysisSummary).join('\n\n---\n\n') +
                '\n\n' + localText('Ranking', 'Ranking') + ': ' +
                ((data.ranking || []).map(safe).join(', ') || localText('unzureichende Daten', 'insufficient data'));
        }
        if (data.kind === 'history') {
            return `**${safe(data.instrument?.symbol)} · ${safe(data.instrument?.exchange)} · ${safe(data.instrument?.currency)}**\n\n${performanceText(data)}\n\n${localText('Historische Schlusskurse, keine Echtzeitkurse.', 'Historical closing prices, not live quotes.')}`;
        }
        if (data.kind === 'portfolio') {
            if (data.status === 'positions_required') {
                return localText(
                    'Bitte Positionen mit Stückzahlen angeben, z. B. „Analysiere mein Portfolio: AMD: 10, NVDA: 5“.',
                    'Provide positions with quantities, e.g. “Analyze my portfolio: AMD: 10, NVDA: 5”.'
                );
            }
            const displayTotal = numeric(data.display_total_value)
                ? currencyValue(data.display_total_value, 'EUR')
                : null;
            const nativeTotal = numeric(data.total_value) && data.currency
                ? currencyValue(data.total_value, data.currency)
                : null;
            const currencyWarning = displayTotal
                ? `${localText('Gesamtwert', 'Total value')}: ≈ ${displayTotal}${nativeTotal && data.currency !== 'EUR' ? ' (' + nativeTotal + ')' : ''}`
                : data.status === 'currency_conversion_required'
                    ? localText('Verschiedene Währungen: EUR-Anzeige derzeit nicht verfügbar.', 'Mixed currencies: EUR display currently unavailable.')
                    : `${localText('Gesamtwert', 'Total value')}: ${nativeTotal || '—'}`;
            return [
                `**${localText('Portfolio-Analyse', 'Portfolio analysis')}**`,
                (data.positions || []).map(p => `${safe(p.instrument?.symbol)}: ${pct(numeric(p.display_weight) ? p.display_weight : p.weight)} · ${numeric(p.display_value) ? '≈ ' + currencyValue(p.display_value, 'EUR', true) + (p.currency !== 'EUR' ? ' (' + currencyValue(p.value, p.currency, true) + ')' : '') : currencyValue(p.value, p.currency, true)}`).join(' · '),
                currencyWarning,
                localText('EUR-Werte sind reine Anzeigeumrechnungen mit EZB-Referenzkurs. Keine Orderausführung, Steuer-, Cash- oder Derivatemodellierung.', 'EUR values are presentation-only conversions using ECB reference rates. No order execution, tax, cash or derivatives modeling.')
            ].filter(Boolean).join('\n\n');
        }
        if (data.kind === 'tracking') {
            const rows = (data.items || []).map(p => [
                `${safe(p.symbol || p.id)} · ${safe(p.recommendation || '')}`,
                `${localText('Kursänderung seit Empfehlung (unbereinigt)', 'Price change since recommendation (unadjusted)')}: ${pct(p.return)}`,
                `${localText('Separates Tageskursfenster', 'Separate daily-close window')}: ${date(p.history_from)} – ${date(p.history_to)}`,
                `${localText('Tageskursrendite', 'Daily-close return')}: ${pct(p.history_return)} · ${localText('Benchmark / Tageskurs-Alpha', 'Benchmark / daily-close alpha')}: ${pct(p.benchmark_return)} / ${pct(p.history_alpha)}`
            ].join(' · '));
            return [
                `**${localText('Frühere Empfehlungen', 'Previous recommendations')}**`,
                rows.join('\n\n') || localText('Keine gespeicherten Analysen.', 'No saved analyses.'),
                localText('Kursänderungen verwenden den gespeicherten Empfehlungskurs und sind keine Gesamtrendite.', 'Price changes use the saved recommendation price and are not total returns.')
            ].join('\n\n');
        }
        return failure(result);
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function metric(label, value, tone = '') {
        const item = el('div', 'finance-metric');
        const labelNode = el('span', 'finance-metric-label', label);
        const valueNode = el('span', 'finance-metric-value' + (tone ? ' ' + tone : ''), value);
        item.append(labelNode, valueNode);
        return item;
    }

    function kv(label, value) {
        const item = el('div', 'finance-kv');
        item.append(el('span', '', label), el('span', '', value));
        return item;
    }

    function toneFor(value) {
        return numeric(value)
            ? value > 0 ? 'finance-positive' : value < 0 ? 'finance-negative' : 'finance-neutral'
            : 'finance-neutral';
    }

    function toolLabel(tool, kind) {
        const labels = {
            finance_quote: localText('Aktienkurs', 'Stock quote'),
            finance_analyze: localText('Aktienanalyse', 'Stock analysis'),
            finance_compare: localText('Aktienvergleich', 'Stock comparison'),
            finance_portfolio_analysis: localText('Portfolioanalyse', 'Portfolio analysis'),
            finance_history: localText('Kursverlauf', 'Price history'),
            finance_recommendation_performance: localText('Empfehlungsverlauf', 'Recommendation performance')
        };
        return labels[tool] || {
            quote: localText('Aktienkurs', 'Stock quote'),
            analysis: localText('Aktienanalyse', 'Stock analysis'),
            comparison: localText('Aktienvergleich', 'Stock comparison'),
            portfolio: localText('Portfolioanalyse', 'Portfolio analysis'),
            history: localText('Kursverlauf', 'Price history'),
            tracking: localText('Empfehlungsverlauf', 'Recommendation performance')
        }[kind] || 'Finance Intelligence';
    }

    function appendInstrumentHeader(card, report, label) {
        const q = report.quote || {}, i = report.instrument || {};
        const header = el('div', 'finance-card-header');
        const title = el('div', 'finance-card-title');
        title.append(
            el('div', 'finance-card-eyebrow', label),
            el('h3', '', i.name || i.symbol || localText('Unbekannte Aktie', 'Unknown stock')),
            el('div', 'finance-card-meta',
                [i.symbol, q.exchange || i.exchange, q.currency || i.currency, session(q.session)]
                    .filter(Boolean).join(' · '))
        );
        const value = el('div', 'finance-card-price');
        value.append(el('strong', '', money(report, q.price, q.currency || i.currency)));
        value.append(el('span', 'finance-change ' + toneFor(q.day_change_percent), signedPctPoints(q.day_change_percent)));
        header.append(title, value);
        card.appendChild(header);

        const freshness = el('div', 'finance-card-section');
        const status = el(
            'span',
            'finance-status ' + (q.stale ? 'is-stale' : 'is-good'),
            q.stale ? localText('Veraltet', 'Stale') : localText('Zuletzt gemeldet', 'Last reported')
        );
        const line = el('div', 'finance-card-freshness',
            `${localText('Stand', 'As of')}: ${date(q.timestamp)} · ${localText('Datenalter', 'Age')}: ${age(q.age_seconds)}`);
        freshness.append(status, line);
        card.appendChild(freshness);
    }

    function appendPerformance(card, report) {
        const entries = Object.entries(report.performance || {}).filter(([, value]) => numeric(value?.percent));
        if (!entries.length) return;
        const section = el('div', 'finance-card-section');
        section.appendChild(el('h4', 'finance-section-title', localText('Performance', 'Performance')));
        const grid = el('div', 'finance-metrics');
        for (const [period, value] of entries) {
            grid.appendChild(metric(period, signedPctPoints(value.percent), toneFor(value.percent)));
        }
        section.appendChild(grid);
        card.appendChild(section);
    }

    function availableFundamentals(report) {
        const values = report.fundamentals?.values || {};
        const rows = [];
        const add = (key, formatter = num) => {
            if (numeric(values[key])) rows.push([metricLabels[key](), formatter(values[key])]);
        };
        const listingCurrency = report.quote?.currency || report.instrument?.currency;
        const reportingCurrency = report.fundamentals?.reporting_currency || listingCurrency;
        add('market_cap', value => money(report, value, listingCurrency, true));
        add('revenue', value => money(report, value, reportingCurrency, true));
        add('revenue_growth', pct);
        add('eps', value => money(report, value, reportingCurrency));
        add('eps_growth', pct);
        add('free_cash_flow', value => money(report, value, reportingCurrency, true));
        add('profit_margin', pct);
        add('operating_margin', pct);
        add('debt', value => money(report, value, reportingCurrency, true));
        add('debt_to_equity', value => num(value) + '%');
        add('pe');
        add('forward_pe');
        add('peg');
        add('price_sales');
        return rows;
    }

    function technicalRows(report) {
        const t = report.technicals || {};
        const rows = [];
        if (t.trend) rows.push([localText('Trend', 'Trend'), trend(t.trend)]);
        if (numeric(t.rsi14)) rows.push(['RSI 14', num(t.rsi14)]);
        const listingCurrency = report.quote?.currency || report.instrument?.currency;
        if (numeric(t.sma?.[200])) rows.push(['SMA 200', money(report, t.sma[200], listingCurrency)]);
        if (numeric(t.ema?.[200])) rows.push(['EMA 200', money(report, t.ema[200], listingCurrency)]);
        if (numeric(t.momentum_20)) rows.push([localText('Momentum 20', 'Momentum 20'), pct(t.momentum_20)]);
        if (numeric(t.volatility_annual)) rows.push([localText('Volatilität', 'Volatility'), pct(t.volatility_annual)]);
        if (numeric(t.macd?.value)) rows.push(['MACD', `${money(report, t.macd.value, listingCurrency)} / ${money(report, t.macd.signal, listingCurrency)}`]);
        return rows;
    }

    function appendAssessment(card, report) {
        const a = report.assessment || {};
        const section = el('div', 'finance-card-section');
        section.appendChild(el('h4', 'finance-section-title', localText('Bewertung', 'Assessment')));
        const box = el('div', 'finance-assessment');
        const score = el('div', 'finance-score');
        score.append(
            el('strong', a.score == null ? 'finance-neutral' : '', a.score == null ? '—' : Math.round(a.score)),
            el('span', '', a.score == null ? localText('Kein Score', 'No score') : '/ 100')
        );
        const copy = el('div', 'finance-assessment-copy');
        copy.appendChild(el('strong', '', a.score == null
            ? localText('Unzureichende Daten', 'Insufficient data')
            : (a.recommendation || localText('Bewertet', 'Rated'))));
        copy.appendChild(el('div', 'finance-card-note',
            `${localText('Konfidenz', 'Confidence')}: ${pct(a.confidence)} · ${localText('Horizont', 'Horizon')}: ${safe(a.horizon || '—')}`));
        const bar = el('div', 'finance-confidence');
        const fill = el('span');
        fill.style.width = (numeric(a.confidence) ? clamp(a.confidence, 0, 1) * 100 : 0) + '%';
        bar.appendChild(fill);
        copy.appendChild(bar);
        box.append(score, copy);
        section.appendChild(box);

        const explanations = (a.reasons || []).map(reason).filter(Boolean);
        if (a.score == null && explanations.length) {
            const warning = el('div', 'finance-quality-warning');
            warning.textContent = localText('Warum kein Score: ', 'Why no score: ') + explanations.join(' · ');
            warning.style.marginTop = '12px';
            section.appendChild(warning);
        }
        card.appendChild(section);
    }

    function appendCoreAnalysis(card, report) {
        const section = el('div', 'finance-card-section');
        const grid = el('div', 'finance-analysis-grid');

        const fundamentals = el('div', 'finance-analysis-panel');
        fundamentals.appendChild(el('h4', 'finance-section-title', localText('Fundamental', 'Fundamentals')));
        const fundamentalRows = availableFundamentals(report);
        if (fundamentalRows.length) {
            for (const [label, value] of fundamentalRows.slice(0, 8)) fundamentals.appendChild(kv(label, value));
        } else {
            fundamentals.appendChild(el('div', 'finance-card-note',
                localText('Keine verifizierten Fundamentaldaten verfügbar.', 'No verified fundamental data available.')));
        }

        const technical = el('div', 'finance-analysis-panel');
        technical.appendChild(el('h4', 'finance-section-title', localText('Technik', 'Technical')));
        const rows = technicalRows(report);
        if (rows.length) {
            for (const [label, value] of rows.slice(0, 7)) technical.appendChild(kv(label, value));
        } else {
            technical.appendChild(el('div', 'finance-card-note',
                localText('Keine ausreichenden technischen Daten verfügbar.', 'Insufficient technical data available.')));
        }
        grid.append(fundamentals, technical);
        section.appendChild(grid);
        card.appendChild(section);
    }

    function appendCases(card, report) {
        const c = report.cases || {};
        const groups = [
            [localText('Bull Case', 'Bull case'), c.bull || [], ''],
            [localText('Bear Case', 'Bear case'), c.bear || [], ''],
            [localText('Risiken', 'Risks'), c.risks || [], '']
        ].filter(([, values]) => values.length);
        if (!groups.length) return;
        const section = el('div', 'finance-card-section');
        const grid = el('div', 'finance-cases-grid');
        for (const [title, values] of groups) {
            const panel = el('div', 'finance-case');
            panel.appendChild(el('h4', 'finance-section-title', title));
            const list = el('ul', 'finance-list');
            for (const value of values) list.appendChild(el('li', '', reason(value)));
            panel.appendChild(list);
            grid.appendChild(panel);
        }
        section.appendChild(grid);
        card.appendChild(section);
    }

    function appendNews(card, report) {
        const items = report.news?.items || [];
        if (!items.length) return;
        const section = el('div', 'finance-card-section');
        section.appendChild(el('h4', 'finance-section-title', localText('Aktuelle News', 'Recent news')));
        for (const item of items.slice(0, 5)) {
            const wrap = el('div', 'finance-news-item');
            const href = safeUrl(item.url);
            if (href) {
                const link = el('a', '', item.title || href);
                link.href = href;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                wrap.appendChild(link);
            } else {
                wrap.appendChild(el('div', '', item.title || localText('Meldung', 'News item')));
            }
            wrap.appendChild(el('div', 'finance-news-meta',
                [item.source, shortDate(item.timestamp)].filter(Boolean).join(' · ')));
            section.appendChild(wrap);
        }
        card.appendChild(section);
    }

    function appendDetails(card, report) {
        const details = el('details', 'finance-details');
        details.appendChild(el('summary', '', localText('Technische Details & Quellen', 'Technical details & sources')));
        const body = el('div', 'finance-details-body');
        const q = report.quote || {}, f = report.fundamentals || {}, t = report.technicals || {}, a = report.assessment || {};
        const detailGrid = el('div', 'finance-analysis-grid');

        const market = el('div', 'finance-analysis-panel');
        market.appendChild(el('h4', 'finance-section-title', localText('Marktdaten', 'Market data')));
        market.append(
            kv(localText('Kursbasis', 'Price basis'), safe(q.price_basis || '—')),
            kv(localText('Verzögerung', 'Delay'), safe(q.delay_status || localText('unbekannt', 'unknown'))),
            kv('52W', `${money(report, q.fifty_two_week_low, q.currency)} – ${money(report, q.fifty_two_week_high, q.currency)}`),
            ...(fxLabel(report, q.currency) ? [kv(localText('EUR-Umrechnung', 'EUR conversion'), fxLabel(report, q.currency))] : []),
            kv(localText('Fundamental-Periode', 'Fundamental period'), safe(f.period || '—')),
            kv(localText('Berichtswährung', 'Reporting currency'), safe(f.reporting_currency || '—')),
            kv(localText('Technik-Stand', 'Technical as of'), date(t.as_of))
        );

        const scoring = el('div', 'finance-analysis-panel');
        scoring.appendChild(el('h4', 'finance-section-title', localText('Scoring', 'Scoring')));
        for (const [key, value] of Object.entries(a.subscores || {})) {
            scoring.appendChild(kv(safe(key), `${num(value)} / 100 · ${num(a.weights?.[key])}%`));
        }
        if (!Object.keys(a.subscores || {}).length) scoring.appendChild(el('div', 'finance-card-note', localText('Keine Teil-Scores verfügbar.', 'No subscores available.')));
        scoring.appendChild(kv(localText('Datenabdeckung', 'Data coverage'), pct(a.coverage)));

        detailGrid.append(market, scoring);
        body.appendChild(detailGrid);

        const sources = el('div', 'finance-source-list');
        sources.style.marginTop = '12px';
        const allSources = [];
        if (q.source) allSources.push([localText('Kurs', 'Quote'), q.source, q.source_url]);
        for (const [kind, source] of Object.entries(report.sources || {})) {
            if (source?.provider) allSources.push([kind, source.provider, source.url]);
        }
        for (const [currency, fx] of Object.entries(report.display_fx?.rates || {})) {
            if (currency !== 'EUR' && fx?.source) {
                allSources.push([localText('FX ' + currency + '→EUR', 'FX ' + currency + '→EUR'), fx.source, fx.source_url]);
            }
        }
        for (const [kind, provider, url] of allSources) {
            const row = el('div');
            row.appendChild(el('span', '', `${safe(kind)}: ${safe(provider)}`));
            const href = safeUrl(url);
            if (href) {
                row.appendChild(document.createTextNode(' · '));
                const link = el('a', '', href);
                link.href = href;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                row.appendChild(link);
            }
            sources.appendChild(row);
        }
        if (!allSources.length) sources.appendChild(el('div', 'finance-card-note', localText('Keine Quellen verfügbar.', 'No sources available.')));
        body.appendChild(sources);
        details.appendChild(body);
        card.appendChild(details);
    }

    function renderQuote(report, tool) {
        const card = el('section', 'finance-card');
        appendInstrumentHeader(card, report, toolLabel(tool, report.kind));
        const q = report.quote || {};
        const section = el('div', 'finance-card-section');
        const grid = el('div', 'finance-metrics');
        grid.append(
            metric(localText('52W Tief', '52W low'), money(report, q.fifty_two_week_low, q.currency)),
            metric(localText('52W Hoch', '52W high'), money(report, q.fifty_two_week_high, q.currency)),
            metric(localText('Datenalter', 'Data age'), age(q.age_seconds)),
            metric(localText('Quelle', 'Source'), safe(q.source || '—'))
        );
        section.appendChild(grid);
        card.appendChild(section);
        appendDetails(card, report);
        return card;
    }

    function renderAnalysis(report, tool) {
        const card = el('section', 'finance-card');
        appendInstrumentHeader(card, report, toolLabel(tool, report.kind));
        appendPerformance(card, report);
        appendAssessment(card, report);
        appendCoreAnalysis(card, report);
        appendCases(card, report);
        appendNews(card, report);
        appendDetails(card, report);
        const footer = el('div', 'finance-card-footer',
            localText(
                'EUR-Werte sind ungefähre Anzeigeumrechnungen mit dem täglichen EZB-Referenzkurs; die Originalwährung steht in Klammern. Konfidenz misst Datenqualität, nicht Gewinnwahrscheinlichkeit.',
                'EUR values are approximate display conversions using the daily ECB reference rate; original currency is shown in parentheses. Confidence measures data quality, not profit probability.'
            ));
        card.appendChild(footer);
        return card;
    }

    function renderComparison(data, tool) {
        const card = el('section', 'finance-card');
        const header = el('div', 'finance-card-header');
        const title = el('div', 'finance-card-title');
        title.append(el('div', 'finance-card-eyebrow', toolLabel(tool, data.kind)), el('h3', '', localText('Aktien im direkten Vergleich', 'Stocks side by side')));
        header.appendChild(title);
        card.appendChild(header);

        const section = el('div', 'finance-card-section');
        const wrap = el('div', 'finance-comparison-wrap');
        const table = el('table', 'finance-comparison');
        const head = el('thead');
        const headRow = el('tr');
        for (const label of [
            localText('Aktie', 'Stock'), localText('Kurs', 'Price'), localText('Tag', 'Day'),
            '1Y', localText('Score', 'Score'), localText('Bewertung', 'Rating'), localText('Konf.', 'Conf.')
        ]) headRow.appendChild(el('th', '', label));
        head.appendChild(headRow);
        table.appendChild(head);
        const body = el('tbody');
        for (const report of data.reports || []) {
            const i = report.instrument || {}, q = report.quote || {}, a = report.assessment || {};
            const row = el('tr');
            const stock = el('td');
            stock.append(el('strong', '', i.symbol || '—'), document.createTextNode(i.name ? ' · ' + i.name : ''));
            row.append(
                stock,
                el('td', '', money(report, q.price, q.currency)),
                el('td', toneFor(q.day_change_percent), signedPctPoints(q.day_change_percent)),
                el('td', toneFor(report.performance?.['1Y']?.percent), signedPctPoints(report.performance?.['1Y']?.percent)),
                el('td', '', a.score == null ? '—' : Math.round(a.score)),
                el('td', '', a.score == null ? localText('Keine Daten', 'No data') : safe(a.recommendation)),
                el('td', '', pct(a.confidence))
            );
            body.appendChild(row);
        }
        table.appendChild(body);
        wrap.appendChild(table);
        section.appendChild(wrap);
        section.appendChild(el('div', 'finance-ranking',
            localText('Ranking (nur bewertbare Aktien): ', 'Ranking (rated stocks only): ') +
            ((data.ranking || []).join(' › ') || localText('unzureichende Daten', 'insufficient data'))));
        card.appendChild(section);
        card.appendChild(el('div', 'finance-card-footer',
            localText('EUR zuerst, Originalwährung in Klammern. Umrechnung ungefähr mit täglichem EZB-Referenzkurs; Börsenplatz und Originalkurs bleiben unverändert.', 'EUR first, original currency in parentheses. Conversion is approximate using the daily ECB reference rate; exchange and original quote remain unchanged.')));
        return card;
    }

    function renderHistory(data, tool) {
        const card = el('section', 'finance-card');
        const headerReport = {kind: 'history', instrument: data.instrument || {}, display_fx: data.display_fx, quote: {
            price: data.history?.bars?.at?.(-1)?.close,
            currency: data.instrument?.currency,
            exchange: data.instrument?.exchange,
            timestamp: data.technicals?.as_of,
            age_seconds: null,
            day_change_percent: null
        }};
        appendInstrumentHeader(card, headerReport, toolLabel(tool, data.kind));
        appendPerformance(card, data);
        card.appendChild(el('div', 'finance-card-footer',
            localText('Historische Schlusskurse; keine Echtzeitkurse.', 'Historical closing prices; not live quotes.')));
        return card;
    }

    function renderPortfolio(data, tool) {
        const card = el('section', 'finance-card');
        const header = el('div', 'finance-card-header');
        const title = el('div', 'finance-card-title');
        title.append(el('div', 'finance-card-eyebrow', toolLabel(tool, data.kind)), el('h3', '', localText('Portfolio-Übersicht', 'Portfolio overview')));
        header.appendChild(title);
        card.appendChild(header);
        const section = el('div', 'finance-card-section');
        if (data.status === 'positions_required') {
            section.appendChild(el('div', 'finance-quality-warning', localText('Bitte Positionen mit Stückzahlen angeben, z. B. AMD: 10, NVDA: 5.', 'Provide positions with quantities, e.g. AMD: 10, NVDA: 5.')));
        } else {
            const grid = el('div', 'finance-metrics');
            for (const position of data.positions || []) {
                const symbol = position.instrument?.symbol || '—';
                const weight = numeric(position.display_weight) ? position.display_weight : position.weight;
                const original = numeric(position.value) && position.currency
                    ? currencyValue(position.value, position.currency, true)
                    : '—';
                const shown = numeric(position.display_value)
                    ? '≈ ' + currencyValue(position.display_value, 'EUR', true) +
                        (position.currency !== 'EUR' && original !== '—' ? ' (' + original + ')' : '')
                    : original;
                grid.appendChild(metric(symbol + (numeric(weight) ? ' · ' + pct(weight) : ''), shown));
            }
            section.appendChild(grid);
            if (numeric(data.display_total_value)) {
                const nativeTotal = numeric(data.total_value) && data.currency
                    ? currencyValue(data.total_value, data.currency, true)
                    : '';
                section.appendChild(el('div', 'finance-ranking',
                    localText('Gesamtwert: ', 'Total value: ') + '≈ ' +
                    currencyValue(data.display_total_value, 'EUR', true) +
                    (nativeTotal && data.currency !== 'EUR' ? ' (' + nativeTotal + ')' : '')));
            }
            if (data.ranking?.length) section.appendChild(el('div', 'finance-ranking', localText('Ranking: ', 'Ranking: ') + data.ranking.join(' › ')));
        }
        card.appendChild(section);
        return card;
    }

    function renderTracking(data, tool) {
        const card = el('section', 'finance-card');
        const header = el('div', 'finance-card-header');
        const title = el('div', 'finance-card-title');
        title.append(el('div', 'finance-card-eyebrow', toolLabel(tool, data.kind)), el('h3', '', localText('Frühere Empfehlungen', 'Previous recommendations')));
        header.appendChild(title);
        card.appendChild(header);
        const section = el('div', 'finance-card-section');
        const items = data.items || [];
        if (!items.length) {
            section.appendChild(el('div', 'finance-card-note', localText('Keine gespeicherten Analysen in diesem Chat.', 'No saved analyses in this chat.')));
        } else {
            const wrap = el('div', 'finance-comparison-wrap');
            const table = el('table', 'finance-comparison');
            const body = el('tbody');
            for (const item of items) {
                const row = el('tr');
                row.append(
                    el('td', '', safe(item.symbol || item.id)),
                    el('td', '', safe(item.recommendation || '—')),
                    el('td', toneFor(item.return), pct(item.return)),
                    el('td', '', item.as_of ? shortDate(item.as_of) : '—')
                );
                body.appendChild(row);
            }
            table.appendChild(body);
            wrap.appendChild(table);
            section.appendChild(wrap);
        }
        card.appendChild(section);
        return card;
    }

    function render(result) {
        if (typeof document === 'undefined' || result?.status !== 'completed') return null;
        const data = result.data || result;
        if (!data?.kind) return null;
        if (data.kind === 'quote') return renderQuote(data, result.tool);
        if (data.kind === 'analysis') return renderAnalysis(data, result.tool);
        if (data.kind === 'comparison') return renderComparison(data, result.tool);
        if (data.kind === 'history') return renderHistory(data, result.tool);
        if (data.kind === 'portfolio') return renderPortfolio(data, result.tool);
        if (data.kind === 'tracking') return renderTracking(data, result.tool);
        return null;
    }

    window.MLXFinance = {
        summary,
        failure,
        render,
        __test: { explicitSafeUrl: safeUrl, price, pct, pctPoints, age, date, money, currencyValue, fxLabel }
    };
})();
