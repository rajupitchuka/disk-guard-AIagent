"""Database connection helpers — connection pools for TimescaleDB and pgvector,
plus a small set of typed query helpers used by the ingestion + ML services.

Uses psycopg3 (sync). Async would be cleaner for high-throughput production,
but for a POC with batched 15-minute writes the sync path is simpler.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

log = logging.getLogger(__name__)

_timescale_pool: ConnectionPool | None = None
_pgvector_pool: ConnectionPool | None = None


def timescale_pool() -> ConnectionPool:
    global _timescale_pool
    if _timescale_pool is None:
        _timescale_pool = ConnectionPool(
            settings.timescale_dsn,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
        )
        log.info("opened TimescaleDB connection pool")
    return _timescale_pool


def pgvector_pool() -> ConnectionPool:
    global _pgvector_pool
    if _pgvector_pool is None:
        _pgvector_pool = ConnectionPool(
            settings.pgvector_dsn,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row},
        )
        log.info("opened pgvector connection pool")
    return _pgvector_pool


@contextmanager
def timescale_conn() -> Iterator[psycopg.Connection]:
    with timescale_pool().connection() as conn:
        yield conn


@contextmanager
def pgvector_conn() -> Iterator[psycopg.Connection]:
    with pgvector_pool().connection() as conn:
        yield conn


def close_all_pools() -> None:
    global _timescale_pool, _pgvector_pool
    if _timescale_pool is not None:
        _timescale_pool.close()
        _timescale_pool = None
    if _pgvector_pool is not None:
        _pgvector_pool.close()
        _pgvector_pool = None
