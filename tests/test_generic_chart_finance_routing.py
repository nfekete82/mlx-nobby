from backend.finance_intent import finance_intent


def test_monthly_revenue_chart_stays_normal_chat():
    prompt = (
        "Zeige mir die Entwicklung dieser sechs Monatsumsätze als interaktives Diagramm: "
        "Januar 12.000 €, Februar 15.000 €, März 13.500 €, "
        "April 19.000 €, Mai 22.000 €, Juni 26.000 €. Erkläre den Trend."
    )
    assert finance_intent(prompt) is None
    assert finance_intent("Vergleiche die Monatsumsätze 2026: 12.000 € und 18.000 €") is None
    assert finance_intent("Show monthly revenue: January 12000 EUR, February 15000 EUR") is None


def test_stock_queries_still_use_finance():
    assert finance_intent("Wie steht AMD gerade?") == "finance_quote"
    assert finance_intent("Analysiere NVIDIA") == "finance_analyze"
    assert finance_intent("Vergleiche AMD und NVIDIA") == "finance_compare"
