"""Side-effect-free bilingual finance routing; no LLM or network access."""
import re

ALIASES = {'amd': 'AMD', 'advanced micro devices': 'AMD', 'nvidia': 'NVDA',
           'nvda': 'NVDA', 'broadcom': 'AVGO', 'avgo': 'AVGO',
           'western digital': 'WDC', 'western digital corporation': 'WDC', 'wdc': 'WDC',
           'apple': 'AAPL',
           'aapl': 'AAPL', 'microsoft': 'MSFT', 'msft': 'MSFT', 'tesla': 'TSLA',
           'tsla': 'TSLA', 'amazon': 'AMZN', 'amzn': 'AMZN', 'alphabet': 'GOOGL',
           'google': 'GOOGL', 'meta': 'META'}
TOOLS = ('finance_quote', 'finance_analyze', 'finance_compare',
         'finance_portfolio_analysis', 'finance_history', 'finance_recommendation_performance')


def symbols_from_prompt(prompt):
    value = str(prompt)
    found = []
    for match in re.finditer(r'\b(?:' + '|'.join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True)) + r')\b', value, re.I):
        found.append((match.start(), ALIASES[match.group().lower()]))
    # Unknown upper-case tickers require explicit financial context, never ordinary acronyms.
    if re.search(r'kurs|aktie|stock|ticker|quote|price|analy[sz]|vergleiche|compare', value, re.I):
        for match in re.finditer(r'(?<![\w.])\$?([A-Z][A-Z0-9-]{0,9}(?:\.[A-Z]{1,3})?)(?![\w.])', value):
            if match.group(1) not in {'SMA', 'EMA', 'RSI', 'MACD', 'USD', 'EUR', 'NASDAQ', 'NYSE', 'ETF', 'EPS', 'PE', 'DE', 'EN', 'AI', 'KI'}:
                found.append((match.start(), ALIASES.get(match.group(1).lower(), match.group(1))))
    # Explicit provider symbols take precedence over the unsuffixed alias at the same position.
    ordered = sorted(found, key=lambda item: (item[0], -len(item[1])))
    output, positions = [], set()
    for position, ticker in ordered:
        if position not in positions and ticker not in output:
            output.append(ticker)
        positions.add(position)
    return output[:10]


def explicit_company_query(prompt):
    """Extract one explicitly named company from a strong single-company finance request.

    This is intentionally conservative. It exists so a newly named company can be
    resolved by the market-data provider instead of inheriting the previous ticker.
    """
    raw = str(prompt or '').strip()
    if not raw or len(raw) > 300:
        return None
    patterns = (
        r'^\\s*(?:bitte\\s+)?(?:analysiere|analysier|analyse|analyze|bewerte|evaluate|review)\\s+(.+?)\\s*(prompt, conversation_context=None):
    value = str(prompt or '').lower()
    # Programming, creative and workspace instructions retain their own routing.
    if re.search(r'\b(?:implement\w*|code|python|javascript|workspace|repo|erzähle|story|gedicht|poem|bild|image|video)\b', value):
        return None
    if re.search(r'\b(?:gpu|cpu|hardware|memory|speicher|driver|treiber|pc|computer|macbook|laptop)\b', value) and not re.search(r'kurs|aktie|stock|price|quote|invest|bewert|valuation', value):
        return None
    if re.search(r'\b(?:portfolio|depot)\b', value) and re.search(r'analy[sz]|risk|risik|bewert|review', value):
        return 'finance_portfolio_analysis'
    if re.search(r'empfehlung|recommendation', value) and re.search(r'früher|frueher|previous|entwickelt|performance|rendite', value):
        return 'finance_recommendation_performance'
    tickers = symbols_from_prompt(prompt)
    if not tickers:
        company_query = explicit_company_query(prompt)
        strong_company_name = company_query and (
            company_query.lower() in ALIASES or
            re.search(r'\b[A-ZÄÖÜ][\w&.-]*', company_query)
        )
        if strong_company_name:
            if re.search(r'analy[sz]|bewert|valuation|risik|risk|attraktiv|attractive|kaufen|\bbuy\b|invest', value):
                return 'finance_analyze'
            if re.search(r'histor|verlauf|history|performance|rendite', value):
                return 'finance_history'
            if re.search(r'kurs|price|quote|wie steht|how is', value):
                return 'finance_quote'
        if re.search(r'(?:diese|dieser|this|that)\s+(?:aktie|stock)|\b(?:sie|it)\b', value) and (context_symbols(conversation_context) or re.search(r'aktie|stock', value)):
            if re.search(r'analy[sz]|risik|risk|attraktiv|attractive', value):
                return 'finance_analyze'
            if re.search(r'kurs|price|quote|wie steht|how is', value):
                return 'finance_quote'
        return None
    if re.search(r'\b(?:news|nachrichten|meldungen|earnings|quartalszahlen)\b', value) and not re.search(r'analy[sz]|vergleiche|compare', value):
        return 'web_search'
    if len(tickers) > 1 and re.search(r'vergleich|vergleiche|compare|\bor\b|\boder\b|\bvs\.?\b|versus', value):
        return 'finance_compare'
    if re.search(r'histor|verlauf|history|performance|rendite', value):
        return 'finance_history'
    if re.search(r'analy[sz]|attraktiv|attractive|bewert|valuation|risik|risk|kaufen|\bbuy\b|invest', value):
        return 'finance_analyze'
    if re.search(r'kurs|quote|price|wie steht|how is|trading at|stock', value):
        return 'finance_quote'
    return None


def market_constraints(prompt):
    value = str(prompt).lower()
    exchange = next((name for name in ('NASDAQ', 'NYSE', 'XETRA', 'STUTTGART') if name.lower() in value), None)
    currency = next((name for name in ('USD', 'EUR', 'GBP', 'JPY', 'CHF') if re.search(r'\b' + name.lower() + r'\b', value)), None)
    return exchange, currency


def context_symbols(conversation):
    """A follow-up can use only one instrument from the most recent user request."""
    if not isinstance(conversation, (list, tuple)):
        return []
    for item in reversed(conversation[-10:]):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            item = {'role': item[0], 'content': item[1]}
        if isinstance(item, dict) and item.get('role') == 'user':
            previous = str(item.get('content') or '')[:10000]
            intent = finance_intent(previous)
            tickers = symbols_from_prompt(previous)
            return tickers if intent in {'finance_quote', 'finance_analyze', 'finance_history'} and len(tickers) == 1 else []
    return []
,
        r'^\\s*(?:wie\\s+steht|how\\s+is)\\s+(.+?)\\s*(prompt, conversation_context=None):
    value = str(prompt or '').lower()
    # Programming, creative and workspace instructions retain their own routing.
    if re.search(r'\b(?:implement\w*|code|python|javascript|workspace|repo|erzähle|story|gedicht|poem|bild|image|video)\b', value):
        return None
    if re.search(r'\b(?:gpu|cpu|hardware|memory|speicher|driver|treiber)\b', value) and not re.search(r'kurs|aktie|stock|price|quote|invest|bewert|valuation', value):
        return None
    if re.search(r'\b(?:portfolio|depot)\b', value) and re.search(r'analy[sz]|risk|risik|bewert|review', value):
        return 'finance_portfolio_analysis'
    if re.search(r'empfehlung|recommendation', value) and re.search(r'früher|frueher|previous|entwickelt|performance|rendite', value):
        return 'finance_recommendation_performance'
    tickers = symbols_from_prompt(prompt)
    if not tickers:
        if re.search(r'(?:diese|dieser|this|that)\s+(?:aktie|stock)|\b(?:sie|it)\b', value) and (context_symbols(conversation_context) or re.search(r'aktie|stock', value)):
            if re.search(r'analy[sz]|risik|risk|attraktiv|attractive', value):
                return 'finance_analyze'
            if re.search(r'kurs|price|quote|wie steht|how is', value):
                return 'finance_quote'
        return None
    if re.search(r'\b(?:news|nachrichten|meldungen|earnings|quartalszahlen)\b', value) and not re.search(r'analy[sz]|vergleiche|compare', value):
        return 'web_search'
    if len(tickers) > 1 and re.search(r'vergleich|vergleiche|compare|\bor\b|\boder\b|\bvs\.?\b|versus', value):
        return 'finance_compare'
    if re.search(r'histor|verlauf|history|performance|rendite', value):
        return 'finance_history'
    if re.search(r'analy[sz]|attraktiv|attractive|bewert|valuation|risik|risk|kaufen|\bbuy\b|invest', value):
        return 'finance_analyze'
    if re.search(r'kurs|quote|price|wie steht|how is|trading at|stock', value):
        return 'finance_quote'
    return None


def market_constraints(prompt):
    value = str(prompt).lower()
    exchange = next((name for name in ('NASDAQ', 'NYSE', 'XETRA', 'STUTTGART') if name.lower() in value), None)
    currency = next((name for name in ('USD', 'EUR', 'GBP', 'JPY', 'CHF') if re.search(r'\b' + name.lower() + r'\b', value)), None)
    return exchange, currency


def context_symbols(conversation):
    """A follow-up can use only one instrument from the most recent user request."""
    if not isinstance(conversation, (list, tuple)):
        return []
    for item in reversed(conversation[-10:]):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            item = {'role': item[0], 'content': item[1]}
        if isinstance(item, dict) and item.get('role') == 'user':
            previous = str(item.get('content') or '')[:10000]
            intent = finance_intent(previous)
            tickers = symbols_from_prompt(previous)
            return tickers if intent in {'finance_quote', 'finance_analyze', 'finance_history'} and len(tickers) == 1 else []
    return []
,
        r'^\\s*(?:kurs|preis|quote|price)\\s+(?:von|of\\s+)?(.+?)\\s*(prompt, conversation_context=None):
    value = str(prompt or '').lower()
    # Programming, creative and workspace instructions retain their own routing.
    if re.search(r'\b(?:implement\w*|code|python|javascript|workspace|repo|erzähle|story|gedicht|poem|bild|image|video)\b', value):
        return None
    if re.search(r'\b(?:gpu|cpu|hardware|memory|speicher|driver|treiber)\b', value) and not re.search(r'kurs|aktie|stock|price|quote|invest|bewert|valuation', value):
        return None
    if re.search(r'\b(?:portfolio|depot)\b', value) and re.search(r'analy[sz]|risk|risik|bewert|review', value):
        return 'finance_portfolio_analysis'
    if re.search(r'empfehlung|recommendation', value) and re.search(r'früher|frueher|previous|entwickelt|performance|rendite', value):
        return 'finance_recommendation_performance'
    tickers = symbols_from_prompt(prompt)
    if not tickers:
        if re.search(r'(?:diese|dieser|this|that)\s+(?:aktie|stock)|\b(?:sie|it)\b', value) and (context_symbols(conversation_context) or re.search(r'aktie|stock', value)):
            if re.search(r'analy[sz]|risik|risk|attraktiv|attractive', value):
                return 'finance_analyze'
            if re.search(r'kurs|price|quote|wie steht|how is', value):
                return 'finance_quote'
        return None
    if re.search(r'\b(?:news|nachrichten|meldungen|earnings|quartalszahlen)\b', value) and not re.search(r'analy[sz]|vergleiche|compare', value):
        return 'web_search'
    if len(tickers) > 1 and re.search(r'vergleich|vergleiche|compare|\bor\b|\boder\b|\bvs\.?\b|versus', value):
        return 'finance_compare'
    if re.search(r'histor|verlauf|history|performance|rendite', value):
        return 'finance_history'
    if re.search(r'analy[sz]|attraktiv|attractive|bewert|valuation|risik|risk|kaufen|\bbuy\b|invest', value):
        return 'finance_analyze'
    if re.search(r'kurs|quote|price|wie steht|how is|trading at|stock', value):
        return 'finance_quote'
    return None


def market_constraints(prompt):
    value = str(prompt).lower()
    exchange = next((name for name in ('NASDAQ', 'NYSE', 'XETRA', 'STUTTGART') if name.lower() in value), None)
    currency = next((name for name in ('USD', 'EUR', 'GBP', 'JPY', 'CHF') if re.search(r'\b' + name.lower() + r'\b', value)), None)
    return exchange, currency


def context_symbols(conversation):
    """A follow-up can use only one instrument from the most recent user request."""
    if not isinstance(conversation, (list, tuple)):
        return []
    for item in reversed(conversation[-10:]):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            item = {'role': item[0], 'content': item[1]}
        if isinstance(item, dict) and item.get('role') == 'user':
            previous = str(item.get('content') or '')[:10000]
            intent = finance_intent(previous)
            tickers = symbols_from_prompt(previous)
            return tickers if intent in {'finance_quote', 'finance_analyze', 'finance_history'} and len(tickers) == 1 else []
    return []
,
    )
    candidate = None
    for pattern in patterns:
        match = re.match(pattern, raw, re.I)
        if match:
            candidate = match.group(1).strip()
            break
    if not candidate:
        return None
    candidate = re.sub(
        r'^(?:(?:die|der|das|the)\\s+)?(?:aktie|stock|firma|unternehmen|company)\\s*(?:von|of)?\\s*',
        '', candidate, flags=re.I,
    ).strip()
    candidate = re.sub(
        r'\\s+(?:vollständig|vollstaendig|komplett|fully|completely|fundamental(?:\\s+und\\s+technisch)?|'
        r'technisch|fundamentally|technically|aktuell|gerade|jetzt|today|right\\s+now)\\s*[?.!]*(prompt, conversation_context=None):
    value = str(prompt or '').lower()
    # Programming, creative and workspace instructions retain their own routing.
    if re.search(r'\b(?:implement\w*|code|python|javascript|workspace|repo|erzähle|story|gedicht|poem|bild|image|video)\b', value):
        return None
    if re.search(r'\b(?:gpu|cpu|hardware|memory|speicher|driver|treiber)\b', value) and not re.search(r'kurs|aktie|stock|price|quote|invest|bewert|valuation', value):
        return None
    if re.search(r'\b(?:portfolio|depot)\b', value) and re.search(r'analy[sz]|risk|risik|bewert|review', value):
        return 'finance_portfolio_analysis'
    if re.search(r'empfehlung|recommendation', value) and re.search(r'früher|frueher|previous|entwickelt|performance|rendite', value):
        return 'finance_recommendation_performance'
    tickers = symbols_from_prompt(prompt)
    if not tickers:
        if re.search(r'(?:diese|dieser|this|that)\s+(?:aktie|stock)|\b(?:sie|it)\b', value) and (context_symbols(conversation_context) or re.search(r'aktie|stock', value)):
            if re.search(r'analy[sz]|risik|risk|attraktiv|attractive', value):
                return 'finance_analyze'
            if re.search(r'kurs|price|quote|wie steht|how is', value):
                return 'finance_quote'
        return None
    if re.search(r'\b(?:news|nachrichten|meldungen|earnings|quartalszahlen)\b', value) and not re.search(r'analy[sz]|vergleiche|compare', value):
        return 'web_search'
    if len(tickers) > 1 and re.search(r'vergleich|vergleiche|compare|\bor\b|\boder\b|\bvs\.?\b|versus', value):
        return 'finance_compare'
    if re.search(r'histor|verlauf|history|performance|rendite', value):
        return 'finance_history'
    if re.search(r'analy[sz]|attraktiv|attractive|bewert|valuation|risik|risk|kaufen|\bbuy\b|invest', value):
        return 'finance_analyze'
    if re.search(r'kurs|quote|price|wie steht|how is|trading at|stock', value):
        return 'finance_quote'
    return None


def market_constraints(prompt):
    value = str(prompt).lower()
    exchange = next((name for name in ('NASDAQ', 'NYSE', 'XETRA', 'STUTTGART') if name.lower() in value), None)
    currency = next((name for name in ('USD', 'EUR', 'GBP', 'JPY', 'CHF') if re.search(r'\b' + name.lower() + r'\b', value)), None)
    return exchange, currency


def context_symbols(conversation):
    """A follow-up can use only one instrument from the most recent user request."""
    if not isinstance(conversation, (list, tuple)):
        return []
    for item in reversed(conversation[-10:]):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            item = {'role': item[0], 'content': item[1]}
        if isinstance(item, dict) and item.get('role') == 'user':
            previous = str(item.get('content') or '')[:10000]
            intent = finance_intent(previous)
            tickers = symbols_from_prompt(previous)
            return tickers if intent in {'finance_quote', 'finance_analyze', 'finance_history'} and len(tickers) == 1 else []
    return []
,
        '', candidate, flags=re.I,
    ).strip(' \\t\\r\\n,;:?!')
    lowered = candidate.lower()
    if not candidate or len(candidate) > 80 or len(candidate.split()) > 8:
        return None
    if re.match(r'^(?:mein(?:e|en|er|es)?|my|dies(?:e|er|es)?|this|that|sie|it)\\b', lowered):
        return None
    generic = {
        'markt', 'market', 'portfolio', 'depot', 'dokument', 'document', 'text', 'log',
        'code', 'projekt', 'project', 'system', 'pc', 'computer', 'mac', 'macbook',
        'laptop', 'website', 'webseite', 'repo', 'repository', 'aktie', 'stock',
        'vertrag', 'contract', 'lage', 'situation', 'bild', 'image', 'foto', 'photo',
        'audio', 'video', 'datei', 'file',
    }
    words = set(re.findall(r'[a-z0-9]+', lowered))
    if not words or words <= generic or words & {
        'dokument', 'document', 'code', 'projekt', 'project', 'website', 'webseite',
        'repo', 'repository', 'vertrag', 'contract', 'lage', 'situation', 'bild',
        'image', 'foto', 'photo', 'audio', 'video', 'datei', 'file',
    }:
        return None
    if any(char in candidate for char in '\\n\\r<>/\\\\'):
        return None
    return candidate


def finance_intent(prompt, conversation_context=None):
    value = str(prompt or '').lower()
    # Programming, creative and workspace instructions retain their own routing.
    if re.search(r'\b(?:implement\w*|code|python|javascript|workspace|repo|erzähle|story|gedicht|poem|bild|image|video)\b', value):
        return None
    if re.search(r'\b(?:gpu|cpu|hardware|memory|speicher|driver|treiber)\b', value) and not re.search(r'kurs|aktie|stock|price|quote|invest|bewert|valuation', value):
        return None
    if re.search(r'\b(?:portfolio|depot)\b', value) and re.search(r'analy[sz]|risk|risik|bewert|review', value):
        return 'finance_portfolio_analysis'
    if re.search(r'empfehlung|recommendation', value) and re.search(r'früher|frueher|previous|entwickelt|performance|rendite', value):
        return 'finance_recommendation_performance'
    tickers = symbols_from_prompt(prompt)
    if not tickers:
        if re.search(r'(?:diese|dieser|this|that)\s+(?:aktie|stock)|\b(?:sie|it)\b', value) and (context_symbols(conversation_context) or re.search(r'aktie|stock', value)):
            if re.search(r'analy[sz]|risik|risk|attraktiv|attractive', value):
                return 'finance_analyze'
            if re.search(r'kurs|price|quote|wie steht|how is', value):
                return 'finance_quote'
        return None
    if re.search(r'\b(?:news|nachrichten|meldungen|earnings|quartalszahlen)\b', value) and not re.search(r'analy[sz]|vergleiche|compare', value):
        return 'web_search'
    if len(tickers) > 1 and re.search(r'vergleich|vergleiche|compare|\bor\b|\boder\b|\bvs\.?\b|versus', value):
        return 'finance_compare'
    if re.search(r'histor|verlauf|history|performance|rendite', value):
        return 'finance_history'
    if re.search(r'analy[sz]|attraktiv|attractive|bewert|valuation|risik|risk|kaufen|\bbuy\b|invest', value):
        return 'finance_analyze'
    if re.search(r'kurs|quote|price|wie steht|how is|trading at|stock', value):
        return 'finance_quote'
    return None


def market_constraints(prompt):
    value = str(prompt).lower()
    exchange = next((name for name in ('NASDAQ', 'NYSE', 'XETRA', 'STUTTGART') if name.lower() in value), None)
    currency = next((name for name in ('USD', 'EUR', 'GBP', 'JPY', 'CHF') if re.search(r'\b' + name.lower() + r'\b', value)), None)
    return exchange, currency


def context_symbols(conversation):
    """A follow-up can use only one instrument from the most recent user request."""
    if not isinstance(conversation, (list, tuple)):
        return []
    for item in reversed(conversation[-10:]):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            item = {'role': item[0], 'content': item[1]}
        if isinstance(item, dict) and item.get('role') == 'user':
            previous = str(item.get('content') or '')[:10000]
            intent = finance_intent(previous)
            tickers = symbols_from_prompt(previous)
            return tickers if intent in {'finance_quote', 'finance_analyze', 'finance_history'} and len(tickers) == 1 else []
    return []
