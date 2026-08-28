"""Prometheus metrics (spec §7.5)."""

from prometheus_client import Counter, Histogram, generate_latest

UPDATE_LATENCY = Histogram("memebot_update_latency_seconds", "Telegram update handling latency")
INLINE_QUERIES = Counter("memebot_inline_queries_total", "Inline queries served")
SUBMISSIONS_OPENED = Counter("memebot_submissions_opened_total", "Public submissions opened")
VOTES_CAST = Counter("memebot_votes_cast_total", "Votes cast on submissions")
REPORTS_FILED = Counter("memebot_reports_filed_total", "Reports filed")
REMOVAL_REVIEWS = Counter("memebot_removal_reviews_total", "Removal reviews opened")
ERRORS = Counter("memebot_errors_total", "Unhandled errors in update handling")


def metrics_middleware(handler, event, data):
    with UPDATE_LATENCY.time():
        try:
            return handler(event, data)
        except Exception:
            ERRORS.inc()
            raise


def render() -> bytes:
    return generate_latest()
