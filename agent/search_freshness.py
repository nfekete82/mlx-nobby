"""Backward-compatible agent import for shared backend date validation."""
from backend.search_freshness import requires_today_news, publication_time, filter_today_news

__all__ = ["requires_today_news", "publication_time", "filter_today_news"]
