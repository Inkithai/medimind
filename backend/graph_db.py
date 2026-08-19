"""
Neo4j connection (drug/poisoning reference knowledge graph)
===========================================================
Lazy singleton driver for the optional WHO antidote reference graph (see
poisoning_kg.py). This graph is a shared reference knowledge base — not
per-patient data — so unlike db.py there is no user_id scoping here.

OPTIONAL, BY DESIGN
-------------------
The graph is an enrichment, not core: a missing NEO4J_* variable, an
uninstalled driver, or a down/unreachable instance must never stop the
API from serving documents, timelines, cross-checks or Q&A. Callers use
`is_configured()` to skip the graph entirely when it is not set up, and
wrap the rest in try/except so a configured-but-unreachable graph fails
closed (an upload simply proceeds without reference notes, and findings
grade as model knowledge — the honest default).

OBSERVABILITY
-------------
Every interaction is logged at three points — before the call, at each
step within it, and on completion — because this is the one dependency
in the pipeline that is remote, optional, and allowed to fail silently.
The logs are the only way to tell "the graph returned nothing because
this drug isn't an antidote" apart from "the graph returned nothing
because we never reached it". Completion logs report what the server
actually did (nodes/relationships created, properties set, rows
returned) and how long it took, rather than echoing back what was
requested — on a MERGE-based idempotent load those are very different
numbers.

Credentials are never logged: `_safe_uri()` strips any embedded
userinfo before a URI reaches the log.

Env:
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE (optional,
    defaults to "neo4j")
"""

import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger("graph_db")

try:
    from neo4j import Driver, GraphDatabase

    NEO4J_IMPORT_OK = True
except ImportError:  # pragma: no cover — environment-dependent
    Driver = None  # type: ignore[assignment]
    GraphDatabase = None  # type: ignore[assignment]
    NEO4J_IMPORT_OK = False

_driver: Optional[Any] = None


class GraphUnavailableError(RuntimeError):
    """The reference graph cannot be used right now (not configured, or
    the driver is not installed). Callers treat this as 'no graph'."""


def is_configured() -> bool:
    """True when the graph could be used: driver importable AND the
    required NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD env vars set.
    Callers skip the graph entirely when this is False."""
    if not NEO4J_IMPORT_OK:
        return False
    return bool(
        os.environ.get("NEO4J_URI")
        and os.environ.get("NEO4J_USERNAME")
        and os.environ.get("NEO4J_PASSWORD")
    )


# Connection-freshness settings, all aimed at one observed failure class:
# a pooled connection left idle for hours gets closed by the managed cloud
# instance (or a load balancer in front of it), and the driver discovers
# the dead connection only on use — a ConnectionResetError on the next
# upload. MAX_CONNECTION_LIFETIME retires connections on our schedule;
# LIVENESS_CHECK_TIMEOUT makes the driver ping an idle connection before
# handing it out; managed transactions then retry, so even a connection
# that dies between check and query is recovered.
MAX_CONNECTION_LIFETIME = int(os.environ.get("NEO4J_MAX_CONNECTION_LIFETIME", "300"))
LIVENESS_CHECK_TIMEOUT = int(os.environ.get("NEO4J_LIVENESS_CHECK_TIMEOUT", "30"))
CONNECTION_ACQUISITION_TIMEOUT = int(os.environ.get("NEO4J_CONNECTION_ACQUISITION_TIMEOUT", "30"))
# Bounds the driver's internal retry of a managed transaction. Kept short
# because this graph is an optional enrichment on a request a user is
# waiting on: recovering a dropped connection is worth a few seconds, but
# never worth holding up an upload that succeeds without it.
MAX_TRANSACTION_RETRY_TIME = int(os.environ.get("NEO4J_MAX_TRANSACTION_RETRY_TIME", "15"))

# Matches the "user:password@" portion of a URI. Neo4j URIs normally carry
# credentials out of band (the auth= tuple), but a URI *can* embed them,
# and a logged password is a leak that outlives the process in whatever
# collects these logs.
_USERINFO_RE = re.compile(r"//[^/@]*@")


def _safe_uri(uri: str) -> str:
    """The URI with any embedded credentials replaced, safe to log."""
    return _USERINFO_RE.sub("//<redacted>@", uri or "")


def get_driver() -> Any:
    """Returns the shared driver, creating and verifying it on first use.

    Connectivity is verified once at creation so a bad URI/credential is
    reported here — as a connection problem — rather than surfacing later
    as a confusing failure inside whichever query happened to run first.
    """
    global _driver
    if _driver is None:
        if not is_configured():
            raise GraphUnavailableError(
                "Neo4j is not configured (NEO4J_URI / NEO4J_USERNAME / "
                "NEO4J_PASSWORD missing or driver not installed)"
            )
        uri = os.environ["NEO4J_URI"]
        logger.info("neo4j: connecting to %s (database=%s)", _safe_uri(uri), database_name())
        started = time.perf_counter()
        try:
            _driver = GraphDatabase.driver(
                uri,
                auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
                max_connection_lifetime=MAX_CONNECTION_LIFETIME,
                liveness_check_timeout=LIVENESS_CHECK_TIMEOUT,
                connection_acquisition_timeout=CONNECTION_ACQUISITION_TIMEOUT,
                keep_alive=True,
            )
            _driver.verify_connectivity()
        except Exception as e:
            # Reset so a later call retries instead of reusing a driver that
            # never verified — otherwise one startup blip disables the graph
            # for the whole process lifetime.
            _driver = None
            logger.error(
                "neo4j: connection FAILED to %s after %.0fms: %s",
                _safe_uri(uri),
                (time.perf_counter() - started) * 1000,
                e,
            )
            raise
        logger.info(
            "neo4j: connected to %s in %.0fms "
            "(max_connection_lifetime=%ds liveness_check=%ds retry_window=%ds)",
            _safe_uri(uri),
            (time.perf_counter() - started) * 1000,
            MAX_CONNECTION_LIFETIME,
            LIVENESS_CHECK_TIMEOUT,
            MAX_TRANSACTION_RETRY_TIME,
        )
    else:
        logger.debug("neo4j: reusing existing connection (singleton driver)")
    return _driver


def close_driver() -> None:
    """Closes the shared driver, if one was ever opened. Safe to call when
    Neo4j was never used — logs nothing in that case."""
    global _driver
    if _driver is None:
        return
    logger.info("neo4j: closing driver")
    try:
        _driver.close()
    finally:
        _driver = None


def database_name() -> str:
    return os.environ.get("NEO4J_DATABASE", "neo4j")


def _format_counters(summary: Any) -> str:
    """Renders the server's own write counters, showing only what actually
    changed. Returns "no changes" for a MERGE that matched existing data —
    the normal and informative result of re-ingesting the same document."""
    counters = getattr(summary, "counters", None)
    if counters is None:
        return "no counters"
    parts = []
    for label, attr in (
        ("nodes+", "nodes_created"),
        ("nodes-", "nodes_deleted"),
        ("rels+", "relationships_created"),
        ("rels-", "relationships_deleted"),
        ("props", "properties_set"),
        ("labels+", "labels_added"),
        ("constraints+", "constraints_added"),
    ):
        value = getattr(counters, attr, 0) or 0
        if value:
            parts.append(f"{label}={value}")
    return " ".join(parts) if parts else "no changes"


@contextmanager
def session_scope(operation: str) -> Iterator[Any]:
    """
    Opens a Neo4j session for one logical operation, logging the step before
    the connection is used, and again on completion with the elapsed time.
    Failures are logged with the operation name before being re-raised, so a
    caller that swallows the exception (as api.py deliberately does) still
    leaves a trace of what was attempted.
    """
    database = database_name()
    logger.info("neo4j: [%s] starting (database=%s)", operation, database)
    started = time.perf_counter()
    try:
        # Inside the try on purpose: connecting is itself a step that can
        # fail. Every started operation must end with either a "completed"
        # or a "FAILED" line, or a reader cannot tell an aborted operation
        # from one still in flight.
        driver = get_driver()
        with driver.session(
            database=database,
            max_transaction_retry_time=MAX_TRANSACTION_RETRY_TIME,
        ) as session:
            yield session
    except Exception as e:
        logger.error(
            "neo4j: [%s] FAILED after %.0fms: %s",
            operation,
            (time.perf_counter() - started) * 1000,
            e,
        )
        raise
    logger.info(
        "neo4j: [%s] completed in %.0fms",
        operation,
        (time.perf_counter() - started) * 1000,
    )


def _attempt_logger(operation: str, step: str):
    """Counts transaction-function invocations so a driver-internal retry is
    visible in the log. The driver retries silently, which is exactly what
    you want operationally and exactly what you don't want when reading a
    trace — a query that "took 4 seconds" reads very differently once you
    can see it was the third attempt after two dropped connections."""
    state = {"attempt": 0}

    def note_attempt() -> None:
        state["attempt"] += 1
        if state["attempt"] > 1:
            logger.warning(
                "neo4j: [%s] retrying %s (attempt %d) — the previous attempt failed, "
                "most likely a connection dropped while idle",
                operation,
                step,
                state["attempt"],
            )

    return state, note_attempt


def run_write(session: Any, operation: str, step: str, cypher: str, **params: Any) -> Any:
    """
    Runs a writing Cypher statement in a MANAGED transaction, logging the
    step before it is sent and the server's own counters when it returns.
    Returns the ResultSummary.

    Managed (`execute_write`) rather than `session.run()` specifically so
    the driver retries transient failures. The counters are also what
    distinguish "the load worked and changed nothing because the data was
    already there" from "the load silently matched nothing".
    """
    logger.info("neo4j: [%s] -> %s", operation, step)
    started = time.perf_counter()
    state, note_attempt = _attempt_logger(operation, step)

    def _work(tx: Any) -> Any:
        note_attempt()
        return tx.run(cypher, **params).consume()

    summary = session.execute_write(_work)
    logger.info(
        "neo4j: [%s] <- %s ok in %.0fms%s (%s)",
        operation,
        step,
        (time.perf_counter() - started) * 1000,
        f" after {state['attempt']} attempts" if state["attempt"] > 1 else "",
        _format_counters(summary),
    )
    return summary


def run_read(session: Any, operation: str, step: str, cypher: str, **params: Any) -> Any:
    """
    Runs a reading Cypher statement in a MANAGED transaction (see run_write
    for why), logging the step before it is sent and the row count when it
    returns. Returns the records as a list of dicts (the same shape
    session.run(...).data() gives).
    """
    logger.info("neo4j: [%s] -> %s", operation, step)
    started = time.perf_counter()
    state, note_attempt = _attempt_logger(operation, step)

    def _work(tx: Any) -> Any:
        note_attempt()
        # .data() must be called INSIDE the transaction function: the result
        # is consumed when the transaction closes, so returning the Result
        # itself would hand back something already spent.
        return tx.run(cypher, **params).data()

    records = session.execute_read(_work)
    logger.info(
        "neo4j: [%s] <- %s ok in %.0fms%s (%d row(s) returned)",
        operation,
        step,
        (time.perf_counter() - started) * 1000,
        f" after {state['attempt']} attempts" if state["attempt"] > 1 else "",
        len(records),
    )
    return records


def ensure_constraints() -> None:
    """Called once at API startup, next to db.ensure_indexes()."""
    constraints = {
        "Medicine.name unique": (
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Medicine) REQUIRE m.name IS UNIQUE"
        ),
        "SourceDocument.filename unique": (
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:SourceDocument) REQUIRE s.filename IS UNIQUE"
        ),
        "GuidanceSource.id unique": "CREATE CONSTRAINT IF NOT EXISTS FOR (s:GuidanceSource) REQUIRE s.id IS UNIQUE",  # noqa: E501
        "Guidance.id unique": "CREATE CONSTRAINT IF NOT EXISTS FOR (g:Guidance) REQUIRE g.id IS UNIQUE",  # noqa: E501
        "DrugClass.name unique": "CREATE CONSTRAINT IF NOT EXISTS FOR (c:DrugClass) REQUIRE c.name IS UNIQUE",  # noqa: E501
        "Section.id unique": "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE",  # noqa: E501
        "Indication.name unique": "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Indication) REQUIRE i.name IS UNIQUE",  # noqa: E501
        "AWaReGroup.name unique": "CREATE CONSTRAINT IF NOT EXISTS FOR (g:AWaReGroup) REQUIRE g.name IS UNIQUE",  # noqa: E501
        "AgeRestriction.id unique": "CREATE CONSTRAINT IF NOT EXISTS FOR (r:AgeRestriction) REQUIRE r.id IS UNIQUE",  # noqa: E501
    }
    with session_scope("ensure_constraints") as session:
        for step, cypher in constraints.items():
            run_write(session, "ensure_constraints", step, cypher)
