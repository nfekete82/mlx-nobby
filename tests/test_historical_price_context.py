"""Regression: a 2023 launch price is not asserted as a current price."""
from datetime import date
from types import SimpleNamespace

from agent.semantic_evidence import _historical_price_context


def claim(statement):
    return SimpleNamespace(statement=statement)


def source(url, published=None):
    return SimpleNamespace(final_url=url, publication_date=published)


def test_undated_launch_article_does_not_establish_current_price():
    announcement = source("https://www.raspberrypi.com/news/introducing-raspberry-pi-5/")
    notice = _historical_price_context(
        claim("Die 4-GB-Variante ist für 60 US-Dollar erhältlich."),
        [SimpleNamespace(source_id="s1")], {"s1": announcement},
        today=date(2026, 10, 11))
    assert "kein Nachweis des heutigen Preises" in notice


def test_old_publication_date_labels_historical_price():
    article = source("https://www.example.com/articles/prices", "2023-09-28")
    notice = _historical_price_context(
        claim("Das Modell kostet 80 USD."),
        [SimpleNamespace(source_id="s1")], {"s1": article},
        today=date(2026, 10, 11))
    assert "2023-09-28" in notice
    assert "Historische Preisangabe" in notice


def test_recent_price_source_does_not_get_old_announcement_label():
    recent = source("https://www.example.com/prices", "2026-10-01")
    assert not _historical_price_context(
        claim("Das Modell kostet 77,50 €."),
        [SimpleNamespace(source_id="s1")], {"s1": recent},
        today=date(2026, 10, 11))


def test_price_from_older_and_recent_source_is_not_forced_historical():
    old = source("https://www.example.com/launch", "2023-09-28")
    new = source("https://www.example.com/prices", "2026-10-01")
    assert not _historical_price_context(
        claim("Das Modell kostet 80 US-Dollar."),
        [SimpleNamespace(source_id="s1"), SimpleNamespace(source_id="s2")],
        {"s1": old, "s2": new}, today=date(2026, 10, 11))


def test_nonmonetary_claim_not_affected():
    old = source("https://www.example.com/introducing-new-model/")
    assert not _historical_price_context(
        claim("Das Modell verfügt über vier Prozessorkerne."),
        [SimpleNamespace(source_id="s1")], {"s1": old},
        today=date(2026, 10, 11))


def test_euro_price_from_old_release_is_identified():
    old = source("https://www.example.com/pricing", "2024-01-09")
    assert "Historische Preisangabe" in _historical_price_context(
        claim("Die Variante kostet 90 €."),
        [SimpleNamespace(source_id="s1")], {"s1": old},
        today=date(2026, 10, 11))
