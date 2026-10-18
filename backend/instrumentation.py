"""Timing and query-count instrumentation for FalkorDB queries and API routes."""
import time
import logging
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Generator, Optional

logger = logging.getLogger("keystone.instrumentation")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Thread-safe and async-safe context variable to count database queries
_query_count_var: ContextVar[Optional[int]] = ContextVar("keystone_query_count", default=None)
_query_records_var: ContextVar[Optional[list[dict]]] = ContextVar("keystone_query_records", default=None)


def record_query(query: str, duration_sec: float, repo: str) -> None:
    """Record a completed graph query in current instrumentation context if active."""
    current = _query_count_var.get()
    if current is not None:
        _query_count_var.set(current + 1)
    records = _query_records_var.get()
    if records is not None:
        # truncate query for safety/conciseness
        clean_q = " ".join(query.strip().split())[:120]
        records.append({
            "query": clean_q,
            "duration_ms": round(duration_sec * 1000.0, 2),
            "repo": repo,
        })


@contextmanager
def track_queries() -> Generator[dict, None, None]:
    """Context manager to measure and verify the number of executed graph queries."""
    token_cnt = _query_count_var.set(0)
    token_rec = _query_records_var.set([])
    start_time = time.perf_counter()
    summary = {"count": 0, "duration_ms": 0.0, "queries": []}
    try:
        yield summary
    finally:
        total_time = (time.perf_counter() - start_time) * 1000.0
        summary["count"] = _query_count_var.get() or 0
        summary["duration_ms"] = round(total_time, 2)
        summary["queries"] = _query_records_var.get() or []
        _query_count_var.reset(token_cnt)
        _query_records_var.reset(token_rec)


def get_current_query_count() -> Optional[int]:
    return _query_count_var.get()
