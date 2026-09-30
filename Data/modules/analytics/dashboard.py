"""Bounded multi-database dashboard aggregates for LLM / Statistieken.

Read-only. CONTROL for jobs/research/agents/events; KNOWLEDGE for
knowledge_documents / datasets. Never writes. Never synthesizes history.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from contextlib import contextmanager

from Data.modules.analytics.contracts import (
    ACTIVITY_EVENT_KINDS,
    DATASET_TYPE_LABELS,
    DEFAULT_ACTIVITY_LIMIT,
    DEFAULT_CHART_RANGE,
    DEFAULT_RANKING_RANGE,
    FAILED_JOB_STATES,
    ITEM_TYPE_LABELS,
    MAX_ACTIVITY_LIMIT,
    METRIC_DEFS,
    PROCESSING_TASK_LABELS,
    RESEARCH_ACTIVITY_LABELS,
    SOURCE_CLASS_LABELS,
    TERMINAL_JOB_STATES,
    classify_dataset_type,
    classify_item_type,
    classify_research_activity,
    classify_source,
    normalize_range,
    processing_task_for_capability,
)
from Data.modules.common.sqlite_policy import open_sqlite_connection


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _window(range_key: str) -> tuple[datetime, datetime, timedelta]:
    end = utc_now()
    mapping = {
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }
    delta = mapping.get(range_key, timedelta(days=30))
    return end - delta, end, delta


def _bucket_key(dt: datetime, range_key: str) -> str:
    if range_key in {"1h", "24h"}:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00:00+00:00")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _empty_metric(*, measured: bool = False) -> dict[str, Any]:
    return {
        "value": None,
        "measured": measured,
        "deltaPercent": None,
        "deltaDirection": None,
        "spark": [],
        "status": "UNMEASURED" if not measured else "OK",
    }


def _delta_percent(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        if current == 0:
            return 0.0
        return None  # insufficient baseline — not "infinite %"
    return round(((current - previous) / abs(previous)) * 100.0, 1)


def _coverage(measured: int, total: int) -> dict[str, Any]:
    unknown = max(0, total - measured)
    pct = round((measured / total) * 100.0, 1) if total > 0 else None
    return {
        "measuredCount": measured,
        "unknownCount": unknown,
        "totalCount": total,
        "coveragePercent": pct,
    }


def _agent_id_from_provenance(prov: dict[str, Any] | None) -> str | None:
    """Extract agent attribution from durable provenance / producer fields.

    Supports explicit agent_id keys and producer forms used by SignalFabric:
    ``signal_fabric:{sender_id}``.
    """
    if not isinstance(prov, dict):
        return None
    agent_id = (
        prov.get("agent_id")
        or prov.get("agentId")
        or prov.get("source_actor")
        or prov.get("sourceActor")
        or (prov.get("actor") if isinstance(prov.get("actor"), str) else None)
    )
    if agent_id:
        return str(agent_id)
    producer = prov.get("producer") or prov.get("source")
    if isinstance(producer, str) and producer.startswith("signal_fabric:"):
        sender = producer.split(":", 1)[1].strip()
        return sender or None
    return None


class AnalyticsDashboard:
    """Composable read aggregates for GET /api/analytics/dashboard."""

    def __init__(
        self,
        control_db_path: Path,
        knowledge_db_path: Path | None = None,
        *,
        telemetry_provider: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self.control_db_path = Path(control_db_path)
        self.knowledge_db_path = Path(knowledge_db_path) if knowledge_db_path else None
        self.telemetry_provider = telemetry_provider

    @contextmanager
    def _connect(self, path: Path) -> Iterator[sqlite3.Connection]:
        conn = open_sqlite_connection(path, set_wal=False)
        try:
            yield conn
        finally:
            conn.close()

    def _knowledge_conn(self) -> Any:
        if self.knowledge_db_path is None:
            return self._connect(self.control_db_path)
        return self._connect(self.knowledge_db_path)

    def _control_conn(self) -> Any:
        return self._connect(self.control_db_path)

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    def dashboard(
        self,
        *,
        chart_range: str | None = None,
        ranking_range: str | None = None,
        activity_limit: int = DEFAULT_ACTIVITY_LIMIT,
    ) -> dict[str, Any]:
        chart_key = normalize_range(chart_range, default=DEFAULT_CHART_RANGE)
        ranking_key = normalize_range(ranking_range, default=DEFAULT_RANKING_RANGE)
        limit = max(1, min(int(activity_limit or DEFAULT_ACTIVITY_LIMIT), MAX_ACTIVITY_LIMIT))
        collected = _iso(utc_now())
        source_status: dict[str, str] = {}

        kpis, kpi_status = self._kpis(chart_key)
        source_status["kpis"] = kpi_status

        try:
            knowledge_growth = self._knowledge_growth(chart_key)
            source_status["knowledgeGrowth"] = "OK"
        except Exception as exc:  # noqa: BLE001
            knowledge_growth = {"range": chart_key, "points": [], "error": str(exc)[:200]}
            source_status["knowledgeGrowth"] = "ERROR"

        try:
            dataset_growth = self._dataset_growth(chart_key)
            source_status["datasetGrowth"] = "OK"
        except Exception as exc:  # noqa: BLE001
            dataset_growth = {"range": chart_key, "points": [], "error": str(exc)[:200]}
            source_status["datasetGrowth"] = "ERROR"

        try:
            research_activity = self._research_activity(chart_key)
            source_status["researchActivity"] = "OK"
        except Exception as exc:  # noqa: BLE001
            research_activity = {"range": chart_key, "series": [], "error": str(exc)[:200]}
            source_status["researchActivity"] = "ERROR"

        try:
            distributions = self._distributions()
            source_status["distributions"] = "OK"
        except Exception as exc:  # noqa: BLE001
            distributions = {"error": str(exc)[:200]}
            source_status["distributions"] = "ERROR"

        try:
            rankings = self._rankings(ranking_key)
            source_status["rankings"] = "OK"
        except Exception as exc:  # noqa: BLE001
            rankings = {"range": ranking_key, "error": str(exc)[:200]}
            source_status["rankings"] = "ERROR"

        try:
            processing = self._processing_times(chart_key)
            source_status["processing"] = "OK"
        except Exception as exc:  # noqa: BLE001
            processing = {"range": chart_key, "tasks": [], "error": str(exc)[:200]}
            source_status["processing"] = "ERROR"

        try:
            activity = self._activity(limit=limit)
            source_status["activity"] = "OK"
        except Exception as exc:  # noqa: BLE001
            activity = {"items": [], "error": str(exc)[:200]}
            source_status["activity"] = "ERROR"

        resources, res_status = self._resources()
        source_status["resources"] = res_status

        partial = any(v in {"ERROR", "DEGRADED", "UNAVAILABLE"} for v in source_status.values())
        return {
            "collectedAt": collected,
            "chartRange": chart_key,
            "rankingRange": ranking_key,
            "activityLimit": limit,
            "kpis": kpis,
            "knowledgeGrowth": knowledge_growth,
            "datasetGrowth": dataset_growth,
            "researchActivity": research_activity,
            "distributions": distributions,
            "rankings": rankings,
            "processing": processing,
            "activity": activity,
            "resources": resources,
            "sourceStatus": source_status,
            "partial": partial,
            "metricDefs": METRIC_DEFS,
            "truth": {
                "server_side_aggregation": True,
                "no_invented_cost": True,
                "no_fake_trends": True,
                "no_synthetic_history": True,
                "unknown_is_not_zero": True,
                "multi_database_reads": True,
                "analytics_is_read_model": True,
            },
        }

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------

    def _kpis(self, range_key: str) -> tuple[dict[str, Any], str]:
        start, end, delta = _window(range_key)
        prev_start, prev_end = start - delta, start
        status = "OK"
        out: dict[str, Any] = {}

        # Knowledge / documents
        try:
            ki_cur, ki_prev, ki_spark = self._knowledge_counts(start, end, prev_start, prev_end, range_key)
            doc_cur, doc_prev, doc_spark = self._document_counts(start, end, prev_start, prev_end, range_key)
            out["knowledgeItems"] = self._kpi_payload(ki_cur, ki_prev, ki_spark, lower_is_better=False)
            out["documents"] = self._kpi_payload(doc_cur, doc_prev, doc_spark, lower_is_better=False)
        except Exception:  # noqa: BLE001
            status = "DEGRADED"
            out["knowledgeItems"] = {**_empty_metric(), "status": "ERROR"}
            out["documents"] = {**_empty_metric(), "status": "ERROR"}

        # Datasets
        try:
            ds_cur, ds_prev, ds_spark = self._dataset_counts(start, end, prev_start, prev_end, range_key)
            out["datasets"] = self._kpi_payload(ds_cur, ds_prev, ds_spark, lower_is_better=False)
        except Exception:  # noqa: BLE001
            status = "DEGRADED"
            out["datasets"] = {**_empty_metric(), "status": "ERROR"}

        # Research
        try:
            r_cur, r_prev, r_spark = self._research_counts(start, end, prev_start, prev_end, range_key)
            out["researchJobs"] = self._kpi_payload(r_cur, r_prev, r_spark, lower_is_better=False)
        except Exception:  # noqa: BLE001
            status = "DEGRADED"
            out["researchJobs"] = {**_empty_metric(), "status": "ERROR"}

        # Processing duration
        try:
            p_cur, p_prev, p_spark = self._processing_avg(start, end, prev_start, prev_end, range_key)
            if p_cur is None:
                out["avgProcessingSeconds"] = {
                    **_empty_metric(measured=False),
                    "spark": p_spark,
                }
            else:
                out["avgProcessingSeconds"] = self._kpi_payload(
                    p_cur, p_prev, p_spark, lower_is_better=True
                )
        except Exception:  # noqa: BLE001
            status = "DEGRADED"
            out["avgProcessingSeconds"] = {**_empty_metric(), "status": "ERROR"}

        # System usage via resource pressure
        try:
            usage, usage_prev = self._system_usage()
            if usage is None:
                out["systemUsagePercent"] = _empty_metric(measured=False)
            else:
                out["systemUsagePercent"] = self._kpi_payload(
                    usage, usage_prev, [], lower_is_better=True
                )
        except Exception:  # noqa: BLE001
            status = "DEGRADED"
            out["systemUsagePercent"] = {**_empty_metric(), "status": "ERROR"}

        return out, status

    def _kpi_payload(
        self,
        current: float | None,
        previous: float | None,
        spark: list[float],
        *,
        lower_is_better: bool,
    ) -> dict[str, Any]:
        delta = _delta_percent(current, previous)
        direction = None
        if delta is not None:
            if delta == 0:
                direction = "flat"
            elif lower_is_better:
                direction = "improved" if delta < 0 else "regressed"
            else:
                direction = "improved" if delta > 0 else "regressed"
        return {
            "value": current,
            "measured": current is not None,
            "deltaPercent": delta,
            "deltaDirection": direction,
            "lowerIsBetter": lower_is_better,
            "previousValue": previous,
            "spark": spark,
            "status": "OK" if current is not None else "UNMEASURED",
        }

    def _knowledge_counts(
        self,
        start: datetime,
        end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        range_key: str,
    ) -> tuple[float, float | None, list[float]]:
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "knowledge_documents"):
                return 0.0, 0.0, []
            total = int(conn.execute("SELECT COUNT(*) AS c FROM knowledge_documents").fetchone()["c"])
            cur = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM knowledge_documents WHERE created_at >= ? AND created_at <= ?",
                    (_iso(start), _iso(end)),
                ).fetchone()["c"]
            )
            # Lifetime total for KPI display; window used for delta/spark.
            # Spec: KPI shows total inventory; delta is period vs previous period additions.
            prev = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM knowledge_documents WHERE created_at >= ? AND created_at < ?",
                    (_iso(prev_start), _iso(prev_end)),
                ).fetchone()["c"]
            )
            spark = self._daily_counts(
                conn,
                "knowledge_documents",
                "created_at",
                start,
                end,
                range_key,
            )
            # Previous period insufficient if no rows older than prev_start and prev==0 and total==cur
            prev_out: float | None = float(prev)
            earliest = conn.execute(
                "SELECT MIN(created_at) AS m FROM knowledge_documents"
            ).fetchone()["m"]
            earliest_dt = _parse_ts(earliest)
            if earliest_dt is not None and earliest_dt > prev_start and prev == 0:
                prev_out = None
            return float(total), prev_out if cur or prev else (0.0 if total == 0 else prev_out), spark

    def _document_counts(
        self,
        start: datetime,
        end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        range_key: str,
    ) -> tuple[float, float | None, list[float]]:
        """Count knowledge documents classified as item_type=document."""
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "knowledge_documents"):
                return 0.0, 0.0, []
            cols = _columns(conn, "knowledge_documents")
            rows = conn.execute(
                "SELECT id, source, created_at"
                + (", trust_metadata_json" if "trust_metadata_json" in cols else "")
                + " FROM knowledge_documents"
            ).fetchall()
            # Prefer majority chunk source_type per document when available.
            chunk_types: dict[str, str] = {}
            if _table_exists(conn, "knowledge_chunks") and "source_type" in _columns(conn, "knowledge_chunks"):
                for r in conn.execute(
                    """
                    SELECT document_id, source_type, COUNT(*) AS c
                    FROM knowledge_chunks
                    GROUP BY document_id, source_type
                    ORDER BY c DESC
                    """
                ).fetchall():
                    did = r["document_id"]
                    if did not in chunk_types:
                        chunk_types[did] = r["source_type"]

            total_docs = 0
            cur = 0
            prev = 0
            bucket_counts: dict[str, int] = {}
            for row in rows:
                src = chunk_types.get(row["id"]) or row["source"]
                itype = classify_item_type(src)
                if itype != "document":
                    continue
                total_docs += 1
                created = _parse_ts(row["created_at"])
                if created is None:
                    continue
                if start <= created <= end:
                    cur += 1
                    bk = _bucket_key(created, range_key)
                    bucket_counts[bk] = bucket_counts.get(bk, 0) + 1
                if prev_start <= created < prev_end:
                    prev += 1

            spark = [float(v) for v in self._spark_from_buckets(bucket_counts, start, end, range_key)]
            prev_out: float | None = float(prev)
            if prev == 0 and cur > 0:
                # Check if any document-type existed before prev_start
                has_older = False
                for row in rows:
                    src = chunk_types.get(row["id"]) or row["source"]
                    if classify_item_type(src) != "document":
                        continue
                    created = _parse_ts(row["created_at"])
                    if created is not None and created < prev_start:
                        has_older = True
                        break
                if not has_older:
                    prev_out = None
            return float(total_docs), prev_out, spark

    def _dataset_counts(
        self,
        start: datetime,
        end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        range_key: str,
    ) -> tuple[float, float | None, list[float]]:
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "datasets"):
                return 0.0, 0.0, []
            total = int(conn.execute("SELECT COUNT(*) AS c FROM datasets").fetchone()["c"])
            cur = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM datasets WHERE created_at >= ? AND created_at <= ?",
                    (_iso(start), _iso(end)),
                ).fetchone()["c"]
            )
            prev = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM datasets WHERE created_at >= ? AND created_at < ?",
                    (_iso(prev_start), _iso(prev_end)),
                ).fetchone()["c"]
            )
            spark = self._daily_counts(conn, "datasets", "created_at", start, end, range_key)
            prev_out: float | None = float(prev)
            earliest = conn.execute("SELECT MIN(created_at) AS m FROM datasets").fetchone()["m"]
            earliest_dt = _parse_ts(earliest)
            if earliest_dt is not None and earliest_dt > prev_start and prev == 0:
                prev_out = None
            return float(total), prev_out, spark

    def _research_counts(
        self,
        start: datetime,
        end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        range_key: str,
    ) -> tuple[float, float | None, list[float]]:
        with self._control_conn() as conn:
            if not _table_exists(conn, "research_runs"):
                return 0.0, 0.0, []
            total = int(conn.execute("SELECT COUNT(*) AS c FROM research_runs").fetchone()["c"])
            cur = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM research_runs WHERE created_at >= ? AND created_at <= ?",
                    (_iso(start), _iso(end)),
                ).fetchone()["c"]
            )
            prev = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM research_runs WHERE created_at >= ? AND created_at < ?",
                    (_iso(prev_start), _iso(prev_end)),
                ).fetchone()["c"]
            )
            spark = self._daily_counts(conn, "research_runs", "created_at", start, end, range_key)
            prev_out: float | None = float(prev)
            earliest = conn.execute("SELECT MIN(created_at) AS m FROM research_runs").fetchone()["m"]
            earliest_dt = _parse_ts(earliest)
            if earliest_dt is not None and earliest_dt > prev_start and prev == 0:
                prev_out = None
            return float(total), prev_out, spark

    def _processing_avg(
        self,
        start: datetime,
        end: datetime,
        prev_start: datetime,
        prev_end: datetime,
        range_key: str,
    ) -> tuple[float | None, float | None, list[float]]:
        with self._control_conn() as conn:
            if not _table_exists(conn, "jobs"):
                return None, None, []
            cols = _columns(conn, "jobs")
            if "started_at" not in cols or "finished_at" not in cols:
                return None, None, []
            rows = conn.execute(
                """
                SELECT capability_id, state, started_at, finished_at
                FROM jobs
                WHERE finished_at IS NOT NULL AND started_at IS NOT NULL
                """
            ).fetchall()
            cur_durs: list[float] = []
            prev_durs: list[float] = []
            bucket_durs: dict[str, list[float]] = {}
            for row in rows:
                task = processing_task_for_capability(row["capability_id"])
                if task is None:
                    continue
                state = str(row["state"] or "")
                if state not in TERMINAL_JOB_STATES:
                    continue
                started = _parse_ts(row["started_at"])
                finished = _parse_ts(row["finished_at"])
                if started is None or finished is None or finished < started:
                    continue
                dur = (finished - started).total_seconds()
                if dur < 0:
                    continue
                if start <= finished <= end:
                    cur_durs.append(dur)
                    bk = _bucket_key(finished, range_key)
                    bucket_durs.setdefault(bk, []).append(dur)
                if prev_start <= finished < prev_end:
                    prev_durs.append(dur)
            if not cur_durs and not prev_durs:
                # Also check if ANY processing durations exist ever
                any_ok = False
                for row in rows:
                    if processing_task_for_capability(row["capability_id"]) and str(row["state"] or "") in TERMINAL_JOB_STATES:
                        any_ok = True
                        break
                if not any_ok:
                    return None, None, []
            cur_avg = sum(cur_durs) / len(cur_durs) if cur_durs else None
            prev_avg = sum(prev_durs) / len(prev_durs) if prev_durs else None
            # Lifetime weighted average for KPI display when window empty but history exists
            if cur_avg is None and cur_durs == []:
                all_durs: list[float] = []
                for row in rows:
                    task = processing_task_for_capability(row["capability_id"])
                    if task is None:
                        continue
                    if str(row["state"] or "") not in TERMINAL_JOB_STATES:
                        continue
                    started = _parse_ts(row["started_at"])
                    finished = _parse_ts(row["finished_at"])
                    if started is None or finished is None or finished < started:
                        continue
                    all_durs.append((finished - started).total_seconds())
                if all_durs:
                    cur_avg = sum(all_durs) / len(all_durs)
            spark = []
            for bk in self._bucket_labels(start, end, range_key):
                vals = bucket_durs.get(bk, [])
                spark.append(round(sum(vals) / len(vals), 2) if vals else 0.0)
            return (
                round(cur_avg, 2) if cur_avg is not None else None,
                round(prev_avg, 2) if prev_avg is not None else None,
                spark,
            )

    def _system_usage(self) -> tuple[float | None, float | None]:
        """Canonical resource-pressure % from measured telemetry components.

        Mirrors ``measure_resource_pressure`` weights for cpu/ram/vram only
        (Data/modules/cognition/resource_pressure.py) without importing the
        cognition package (avoids pulling model-runtime deps into analytics).
        UNMEASURED when no component is measured — never a fake constant.
        """
        if not self.telemetry_provider:
            return None, None
        snap = self.telemetry_provider()
        if not snap:
            return None, None
        dashboard = snap.get("dashboard") if isinstance(snap.get("dashboard"), dict) else {}
        components: dict[str, float] = {}
        weights = {"cpu": 1.0, "ram": 1.2, "vram": 1.3}
        for key, out_name in (
            ("cpuPct", "cpu"),
            ("ramPct", "ram"),
            ("vramPct", "vram"),
        ):
            raw = dashboard.get(key)
            if raw is None and out_name == "vram":
                raw = dashboard.get("gpuPct")
            if raw is None:
                continue
            try:
                components[out_name] = max(0.0, min(1.0, float(raw) / 100.0))
            except (TypeError, ValueError):
                continue
        if not components:
            return None, None
        total_w = sum(weights[k] for k in components)
        acc = sum(components[k] * weights[k] for k in components)
        pressure = acc / total_w if total_w else 0.0
        # No historical pressure store — previous period unavailable.
        return round(pressure * 100.0, 1), None

    # ------------------------------------------------------------------
    # Growth charts
    # ------------------------------------------------------------------

    def _knowledge_growth(self, range_key: str) -> dict[str, Any]:
        start, end, _ = _window(range_key)
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "knowledge_documents"):
                return {
                    "range": range_key,
                    "from": _iso(start),
                    "to": _iso(end),
                    "points": [],
                    "subtitle": "Totale kennis items in de tijd",
                }
            # Baseline: documents created before window (known history only).
            baseline = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM knowledge_documents WHERE created_at < ?",
                    (_iso(start),),
                ).fetchone()["c"]
            )
            rows = conn.execute(
                """
                SELECT created_at FROM knowledge_documents
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at ASC
                """,
                (_iso(start), _iso(end)),
            ).fetchall()
            # Earliest known timestamp — do not invent pre-history.
            earliest = conn.execute(
                "SELECT MIN(created_at) AS m FROM knowledge_documents"
            ).fetchone()["m"]
            earliest_dt = _parse_ts(earliest)

            bucket_adds: dict[str, int] = {}
            for row in rows:
                dt = _parse_ts(row["created_at"])
                if dt is None:
                    continue
                bk = _bucket_key(dt, range_key)
                bucket_adds[bk] = bucket_adds.get(bk, 0) + 1

            points = []
            running = baseline
            for bk in self._bucket_labels(start, end, range_key):
                bk_dt = _parse_ts(bk) or start
                # Skip buckets before earliest known data (unknown, not zero-filled history).
                if earliest_dt is not None and bk_dt.date() < earliest_dt.date() and range_key not in {"1h", "24h"}:
                    points.append({"t": bk, "value": None, "known": False})
                    continue
                if earliest_dt is not None and range_key in {"1h", "24h"} and bk_dt < earliest_dt:
                    points.append({"t": bk, "value": None, "known": False})
                    continue
                running += bucket_adds.get(bk, 0)
                points.append({"t": bk, "value": running, "known": True})
            return {
                "range": range_key,
                "from": _iso(start),
                "to": _iso(end),
                "points": points,
                "subtitle": "Totale kennis items in de tijd",
                "baseline": baseline,
            }

    def _dataset_growth(self, range_key: str) -> dict[str, Any]:
        start, end, _ = _window(range_key)
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "datasets"):
                return {
                    "range": range_key,
                    "from": _iso(start),
                    "to": _iso(end),
                    "points": [],
                    "sizeSemantics": "on_disk_artifact_byte_size",
                    "subtitle": "Aantal datasets en totale grootte",
                }
            cols = _columns(conn, "datasets")
            has_bytes = "byte_size" in cols
            baseline_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM datasets WHERE created_at < ?",
                    (_iso(start),),
                ).fetchone()["c"]
            )
            if has_bytes:
                base_bytes_row = conn.execute(
                    """
                    SELECT COALESCE(SUM(byte_size), 0) AS s,
                           COUNT(byte_size) AS measured
                    FROM datasets
                    WHERE created_at < ? AND byte_size IS NOT NULL
                    """,
                    (_iso(start),),
                ).fetchone()
                baseline_bytes = int(base_bytes_row["s"] or 0)
            else:
                baseline_bytes = 0

            select = "created_at, byte_size" if has_bytes else "created_at"
            rows = conn.execute(
                f"""
                SELECT {select} FROM datasets
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at ASC
                """,
                (_iso(start), _iso(end)),
            ).fetchall()
            earliest = conn.execute("SELECT MIN(created_at) AS m FROM datasets").fetchone()["m"]
            earliest_dt = _parse_ts(earliest)

            bucket_count: dict[str, int] = {}
            bucket_bytes: dict[str, int] = {}
            measured_total = 0
            unknown_total = 0
            for row in rows:
                dt = _parse_ts(row["created_at"])
                if dt is None:
                    continue
                bk = _bucket_key(dt, range_key)
                bucket_count[bk] = bucket_count.get(bk, 0) + 1
                if has_bytes:
                    bs = row["byte_size"]
                    if bs is None:
                        unknown_total += 1
                    else:
                        measured_total += 1
                        bucket_bytes[bk] = bucket_bytes.get(bk, 0) + int(bs)
                else:
                    unknown_total += 1

            # Lifetime coverage
            if has_bytes:
                cov = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN byte_size IS NOT NULL THEN 1 ELSE 0 END) AS measured
                    FROM datasets
                    """
                ).fetchone()
                coverage = _coverage(int(cov["measured"] or 0), int(cov["total"] or 0))
            else:
                coverage = _coverage(0, baseline_count)

            points = []
            running_c = baseline_count
            running_b = baseline_bytes
            for bk in self._bucket_labels(start, end, range_key):
                bk_dt = _parse_ts(bk) or start
                if earliest_dt is not None:
                    if range_key in {"1h", "24h"} and bk_dt < earliest_dt:
                        points.append({"t": bk, "count": None, "sizeGb": None, "known": False})
                        continue
                    if range_key not in {"1h", "24h"} and bk_dt.date() < earliest_dt.date():
                        points.append({"t": bk, "count": None, "sizeGb": None, "known": False})
                        continue
                running_c += bucket_count.get(bk, 0)
                running_b += bucket_bytes.get(bk, 0)
                points.append(
                    {
                        "t": bk,
                        "count": running_c,
                        "sizeGb": round(running_b / (1024**3), 3) if has_bytes else None,
                        "known": True,
                    }
                )
            return {
                "range": range_key,
                "from": _iso(start),
                "to": _iso(end),
                "points": points,
                "sizeSemantics": "on_disk_artifact_byte_size",
                "coverage": coverage,
                "subtitle": "Aantal datasets en totale grootte",
            }

    def _research_activity(self, range_key: str) -> dict[str, Any]:
        start, end, _ = _window(range_key)
        series_keys = list(RESEARCH_ACTIVITY_LABELS.keys())
        empty_series = [
            {"key": k, "label": RESEARCH_ACTIVITY_LABELS[k], "points": []}
            for k in series_keys
            if k != "other"
        ]
        with self._control_conn() as conn:
            if not _table_exists(conn, "research_runs"):
                return {
                    "range": range_key,
                    "from": _iso(start),
                    "to": _iso(end),
                    "series": empty_series,
                }
            # Join projects for typed fields.
            has_projects = _table_exists(conn, "research_projects")
            if has_projects:
                proj_cols = _columns(conn, "research_projects")
                select_proj = "p.allow_web, p.execution_mode, p.topic, p.analysis_mode"
                if "connected_datasets_json" in proj_cols:
                    select_proj += ", p.connected_datasets_json"
                else:
                    select_proj += ", '[]' AS connected_datasets_json"
                rows = conn.execute(
                    f"""
                    SELECT r.run_id, r.created_at, r.execution_mode AS run_mode,
                           r.analysis_mode AS run_analysis,
                           {select_proj}
                    FROM research_runs r
                    LEFT JOIN research_projects p ON p.project_id = r.project_id
                    WHERE r.created_at >= ? AND r.created_at <= ?
                    """,
                    (_iso(start), _iso(end)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT run_id, created_at, execution_mode AS run_mode,
                           analysis_mode AS run_analysis
                    FROM research_runs
                    WHERE created_at >= ? AND created_at <= ?
                    """,
                    (_iso(start), _iso(end)),
                ).fetchall()

            buckets: dict[str, dict[str, int]] = {k: {} for k in series_keys}
            for row in rows:
                dt = _parse_ts(row["created_at"])
                if dt is None:
                    continue
                keys = row.keys() if hasattr(row, "keys") else []
                allow_web = None
                if "allow_web" in keys:
                    aw = row["allow_web"]
                    allow_web = bool(aw) if aw is not None else None
                connected = _loads(
                    row["connected_datasets_json"] if "connected_datasets_json" in keys else "[]",
                    [],
                )
                cat = classify_research_activity(
                    allow_web=allow_web,
                    execution_mode=(
                        row["execution_mode"]
                        if "execution_mode" in keys
                        else row["run_mode"]
                    ),
                    topic=row["topic"] if "topic" in keys else None,
                    analysis_mode=(
                        row["analysis_mode"]
                        if "analysis_mode" in keys
                        else row["run_analysis"]
                    ),
                    connected_datasets=connected if isinstance(connected, list) else [],
                )
                bk = _bucket_key(dt, range_key)
                buckets.setdefault(cat, {})
                buckets[cat][bk] = buckets[cat].get(bk, 0) + 1

            labels = self._bucket_labels(start, end, range_key)
            series = []
            for key in ("web_research", "analyse", "trading", "agent_research"):
                pts = [{"t": bk, "value": buckets.get(key, {}).get(bk, 0)} for bk in labels]
                series.append({"key": key, "label": RESEARCH_ACTIVITY_LABELS[key], "points": pts})
            other_total = sum(sum(v.values()) for k, v in buckets.items() if k == "other")
            return {
                "range": range_key,
                "from": _iso(start),
                "to": _iso(end),
                "series": series,
                "otherCount": other_total,
            }

    # ------------------------------------------------------------------
    # Distributions
    # ------------------------------------------------------------------

    def _distributions(self) -> dict[str, Any]:
        return {
            "itemTypes": self._item_type_distribution(),
            "datasetTypes": self._dataset_type_distribution(),
            "sources": self._source_distribution(),
        }

    def _item_type_distribution(self) -> dict[str, Any]:
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "knowledge_documents"):
                return {"total": 0, "segments": []}
            cols = _columns(conn, "knowledge_documents")
            rows = conn.execute(
                "SELECT id, source FROM knowledge_documents"
            ).fetchall()
            chunk_types: dict[str, str] = {}
            if _table_exists(conn, "knowledge_chunks") and "source_type" in _columns(conn, "knowledge_chunks"):
                for r in conn.execute(
                    """
                    SELECT document_id, source_type, COUNT(*) AS c
                    FROM knowledge_chunks
                    GROUP BY document_id, source_type
                    ORDER BY c DESC
                    """
                ).fetchall():
                    if r["document_id"] not in chunk_types:
                        chunk_types[r["document_id"]] = r["source_type"]
            counts: dict[str, int] = {}
            for row in rows:
                src = chunk_types.get(row["id"]) or row["source"]
                itype = classify_item_type(src)
                counts[itype] = counts.get(itype, 0) + 1
            total = sum(counts.values())
            order = ["document", "note", "web", "code", "dataset", "other", "unknown"]
            segments = []
            for key in order:
                n = counts.get(key, 0)
                if n <= 0 and key in {"unknown"} and "unknown" not in counts:
                    continue
                if n <= 0 and key not in counts:
                    continue
                segments.append(
                    {
                        "key": key,
                        "label": ITEM_TYPE_LABELS.get(key, key),
                        "count": n,
                        "percent": round((n / total) * 100.0, 1) if total else 0.0,
                    }
                )
            # Fix rounding drift on last segment
            if segments and total:
                drift = round(100.0 - sum(s["percent"] for s in segments), 1)
                if abs(drift) >= 0.1:
                    segments[-1]["percent"] = round(segments[-1]["percent"] + drift, 1)
            return {"total": total, "segments": segments}

    def _dataset_type_distribution(self) -> dict[str, Any]:
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "datasets"):
                return {"total": 0, "segments": []}
            cols = _columns(conn, "datasets")
            has_meta = "metadata_json" in cols
            rows = conn.execute(
                "SELECT metadata_json FROM datasets" if has_meta else "SELECT 1 AS metadata_json FROM datasets"
            ).fetchall()
            counts: dict[str, int] = {}
            for row in rows:
                meta = _loads(row["metadata_json"] if has_meta else None, {})
                if not isinstance(meta, dict):
                    meta = {}
                semantic = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else {}
                primary = (
                    semantic.get("primaryCategory")
                    or semantic.get("primary_category")
                    or meta.get("primaryCategory")
                    or meta.get("category")
                )
                bucket = classify_dataset_type(primary_category=primary, metadata={**meta, **semantic})
                counts[bucket] = counts.get(bucket, 0) + 1
            total = sum(counts.values())
            order = ["training", "market", "research", "evaluation", "synthetic", "other", "unknown"]
            segments = []
            for key in order:
                n = counts.get(key, 0)
                if n <= 0:
                    continue
                segments.append(
                    {
                        "key": key,
                        "label": DATASET_TYPE_LABELS.get(key, key),
                        "count": n,
                        "percent": round((n / total) * 100.0, 1) if total else 0.0,
                    }
                )
            if segments and total:
                drift = round(100.0 - sum(s["percent"] for s in segments), 1)
                if abs(drift) >= 0.1:
                    segments[-1]["percent"] = round(segments[-1]["percent"] + drift, 1)
            return {"total": total, "segments": segments}

    def _source_distribution(self) -> dict[str, Any]:
        with self._knowledge_conn() as conn:
            if not _table_exists(conn, "knowledge_documents"):
                return {"total": 0, "segments": []}
            cols = _columns(conn, "knowledge_documents")
            has_prov = False
            # Provenance lives on chunks primarily.
            rows = conn.execute("SELECT id, source FROM knowledge_documents").fetchall()
            chunk_prov: dict[str, dict[str, Any]] = {}
            if _table_exists(conn, "knowledge_chunks"):
                ccols = _columns(conn, "knowledge_chunks")
                if "provenance_json" in ccols:
                    has_prov = True
                    for r in conn.execute(
                        "SELECT document_id, provenance_json, source_type FROM knowledge_chunks"
                    ).fetchall():
                        if r["document_id"] in chunk_prov:
                            continue
                        chunk_prov[r["document_id"]] = {
                            "provenance": _loads(r["provenance_json"], {}),
                            "source_type": r["source_type"] if "source_type" in r.keys() else None,
                        }
            counts: dict[str, int] = {}
            for row in rows:
                prov_info = chunk_prov.get(row["id"], {})
                prov = prov_info.get("provenance") if isinstance(prov_info.get("provenance"), dict) else {}
                raw = (
                    prov.get("kind")
                    or prov.get("source")
                    or prov.get("ingestion")
                    or prov_info.get("source_type")
                    or row["source"]
                )
                # Empty source with no provenance → unknown (not Manual).
                if (not raw or not str(raw).strip()) and not prov:
                    key = "unknown"
                elif not raw or not str(raw).strip():
                    key = "unknown"
                else:
                    key = classify_source(str(raw))
                counts[key] = counts.get(key, 0) + 1
            total = sum(counts.values())
            order = ["web_scraping", "manual", "agent_research", "import", "api", "other", "unknown"]
            segments = []
            for key in order:
                n = counts.get(key, 0)
                if n <= 0:
                    continue
                segments.append(
                    {
                        "key": key,
                        "label": SOURCE_CLASS_LABELS.get(key, key),
                        "count": n,
                        "percent": round((n / total) * 100.0, 1) if total else 0.0,
                    }
                )
            if segments and total:
                drift = round(100.0 - sum(s["percent"] for s in segments), 1)
                if abs(drift) >= 0.1:
                    segments[-1]["percent"] = round(segments[-1]["percent"] + drift, 1)
            return {
                "total": total,
                "segments": segments,
                "truth": {"provenancePreferred": has_prov, "unknownNotForcedManual": True},
            }

    # ------------------------------------------------------------------
    # Rankings
    # ------------------------------------------------------------------

    def _rankings(self, range_key: str) -> dict[str, Any]:
        start, end, delta = _window(range_key)
        prev_start, prev_end = start - delta, start
        return {
            "range": range_key,
            "from": _iso(start),
            "to": _iso(end),
            "topAgents": self._top_agents(start, end),
            "topSources": self._top_sources(),
            "popularTags": self._popular_tags(start, end, prev_start, prev_end),
        }

    def _top_agents(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Agents ranked by knowledge contributions with provenance evidence."""
        attributions: dict[str, dict[str, Any]] = {}
        with self._knowledge_conn() as conn:
            if _table_exists(conn, "knowledge_chunks") and "provenance_json" in _columns(
                conn, "knowledge_chunks"
            ):
                # Join document created_at for period filter.
                has_docs = _table_exists(conn, "knowledge_documents")
                doc_cols = _columns(conn, "knowledge_documents") if has_docs else set()
                if has_docs:
                    trust_sel = (
                        ", d.trust_metadata_json"
                        if "trust_metadata_json" in doc_cols
                        else ", '{}' AS trust_metadata_json"
                    )
                    rows = conn.execute(
                        f"""
                        SELECT c.chunk_id, c.provenance_json, c.document_id,
                               d.created_at, d.size_bytes{trust_sel}
                        FROM knowledge_chunks c
                        JOIN knowledge_documents d ON d.id = c.document_id
                        WHERE d.created_at >= ? AND d.created_at <= ?
                        """,
                        (_iso(start), _iso(end)),
                    ).fetchall()
                else:
                    rows = []
                seen_docs: set[str] = set()
                for row in rows:
                    prov = _loads(row["provenance_json"], {})
                    if not isinstance(prov, dict):
                        prov = {}
                    trust = _loads(row["trust_metadata_json"], {}) if "trust_metadata_json" in row.keys() else {}
                    if isinstance(trust, dict):
                        nested = trust.get("provenance") if isinstance(trust.get("provenance"), dict) else {}
                        merged = {**nested, **prov}
                        if trust.get("producer") and "producer" not in merged:
                            merged["producer"] = trust.get("producer")
                    else:
                        merged = prov
                    agent_id = _agent_id_from_provenance(merged)
                    if not agent_id:
                        continue
                    entry = attributions.setdefault(
                        agent_id,
                        {"items": 0, "bytes": 0, "bytesMeasured": 0, "docs": set()},
                    )
                    doc_id = row["document_id"]
                    if doc_id in seen_docs:
                        continue
                    seen_docs.add(doc_id)
                    entry["items"] += 1
                    entry["docs"].add(doc_id)
                    bs = row["size_bytes"] if "size_bytes" in row.keys() else None
                    if bs is not None:
                        entry["bytes"] += int(bs)
                        entry["bytesMeasured"] += 1

        if not attributions:
            return []

        # Success rate from agent_missions in window for attributed agents only.
        mission_stats: dict[str, dict[str, int]] = {}
        names: dict[str, str] = {}
        with self._control_conn() as conn:
            if _table_exists(conn, "agent_definitions"):
                for r in conn.execute("SELECT agent_id, name FROM agent_definitions").fetchall():
                    names[r["agent_id"]] = r["name"]
            if _table_exists(conn, "agent_missions"):
                for r in conn.execute(
                    """
                    SELECT agent_id, status, COUNT(*) AS c
                    FROM agent_missions
                    WHERE created_at >= ? AND created_at <= ?
                    GROUP BY agent_id, status
                    """,
                    (_iso(start), _iso(end)),
                ).fetchall():
                    st = mission_stats.setdefault(r["agent_id"], {"total": 0, "ok": 0})
                    st["total"] += int(r["c"])
                    if str(r["status"] or "").lower() in {"completed", "succeeded", "ready"}:
                        st["ok"] += int(r["c"])

        ranked = sorted(attributions.items(), key=lambda kv: kv[1]["items"], reverse=True)[:5]
        out = []
        for idx, (agent_id, data) in enumerate(ranked, start=1):
            ms = mission_stats.get(agent_id)
            success = None
            if ms and ms["total"] > 0:
                success = round((ms["ok"] / ms["total"]) * 100.0, 1)
            size_label = None
            if data["bytesMeasured"] > 0:
                size_label = round(data["bytes"] / (1024**3), 3)  # GB
            out.append(
                {
                    "rank": idx,
                    "agentId": agent_id,
                    "name": names.get(agent_id) or agent_id,
                    "items": data["items"],
                    "sizeGb": size_label,
                    "sizeStatus": "MEASURED" if size_label is not None else "UNMEASURED",
                    "successRatePercent": success,
                    "successStatus": "MEASURED" if success is not None else "UNMEASURED",
                }
            )
        return out

    def _top_sources(self) -> list[dict[str, Any]]:
        """Aggregate by classified source label; percentage of all knowledge items."""
        dist = self._source_distribution()
        total = int(dist.get("total") or 0)
        segments = list(dist.get("segments") or [])
        # Also compute size when available.
        size_by_class: dict[str, int] = {}
        measured_by_class: dict[str, int] = {}
        with self._knowledge_conn() as conn:
            if _table_exists(conn, "knowledge_documents"):
                cols = _columns(conn, "knowledge_documents")
                has_size = "size_bytes" in cols
                chunk_types: dict[str, dict[str, Any]] = {}
                if _table_exists(conn, "knowledge_chunks"):
                    ccols = _columns(conn, "knowledge_chunks")
                    for r in conn.execute(
                        "SELECT document_id, source_type"
                        + (", provenance_json" if "provenance_json" in ccols else "")
                        + " FROM knowledge_chunks"
                    ).fetchall():
                        if r["document_id"] in chunk_types:
                            continue
                        prov = _loads(r["provenance_json"], {}) if "provenance_json" in r.keys() else {}
                        chunk_types[r["document_id"]] = {
                            "source_type": r["source_type"] if "source_type" in r.keys() else None,
                            "provenance": prov if isinstance(prov, dict) else {},
                        }
                for row in conn.execute(
                    "SELECT id, source"
                    + (", size_bytes" if has_size else "")
                    + " FROM knowledge_documents"
                ).fetchall():
                    info = chunk_types.get(row["id"], {})
                    prov = info.get("provenance") or {}
                    raw = (
                        prov.get("kind")
                        or prov.get("source")
                        or info.get("source_type")
                        or row["source"]
                    )
                    key = classify_source(str(raw) if raw else None) if raw else "unknown"
                    if has_size and row["size_bytes"] is not None:
                        size_by_class[key] = size_by_class.get(key, 0) + int(row["size_bytes"])
                        measured_by_class[key] = measured_by_class.get(key, 0) + 1

        out = []
        for idx, seg in enumerate(segments[:5], start=1):
            key = seg["key"]
            size_gb = None
            if measured_by_class.get(key):
                size_gb = round(size_by_class.get(key, 0) / (1024**3), 3)
            out.append(
                {
                    "rank": idx,
                    "key": key,
                    "name": seg["label"],
                    "items": seg["count"],
                    "sizeGb": size_gb,
                    "sizeStatus": "MEASURED" if size_gb is not None else "UNMEASURED",
                    "percent": seg["percent"] if total else 0.0,
                }
            )
        return out

    def _popular_tags(
        self,
        start: datetime,
        end: datetime,
        prev_start: datetime,
        prev_end: datetime,
    ) -> list[dict[str, Any]]:
        """Aggregate canonical tags from dataset semantic profiles + knowledge trust_metadata."""
        cur_counts: dict[str, int] = {}
        prev_counts: dict[str, int] = {}

        def _add_tags(tags: list[Any], created: datetime | None) -> None:
            if created is None:
                return
            for raw in tags:
                tag = str(raw or "").strip().lower()
                if not tag or len(tag) > 64:
                    continue
                if start <= created <= end:
                    cur_counts[tag] = cur_counts.get(tag, 0) + 1
                if prev_start <= created < prev_end:
                    prev_counts[tag] = prev_counts.get(tag, 0) + 1

        with self._knowledge_conn() as conn:
            if _table_exists(conn, "datasets") and "metadata_json" in _columns(conn, "datasets"):
                for row in conn.execute(
                    "SELECT metadata_json, created_at FROM datasets"
                ).fetchall():
                    meta = _loads(row["metadata_json"], {})
                    if not isinstance(meta, dict):
                        continue
                    semantic = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else {}
                    tags = semantic.get("tags") or meta.get("tags") or meta.get("semanticTags") or []
                    if isinstance(tags, list):
                        _add_tags(tags, _parse_ts(row["created_at"]))

            if _table_exists(conn, "knowledge_documents") and "trust_metadata_json" in _columns(
                conn, "knowledge_documents"
            ):
                for row in conn.execute(
                    "SELECT trust_metadata_json, created_at FROM knowledge_documents"
                ).fetchall():
                    trust = _loads(row["trust_metadata_json"], {})
                    if not isinstance(trust, dict):
                        continue
                    tags = trust.get("tags") or []
                    if isinstance(tags, list):
                        _add_tags(tags, _parse_ts(row["created_at"]))

            # Chunk provenance tags
            if _table_exists(conn, "knowledge_chunks") and "provenance_json" in _columns(
                conn, "knowledge_chunks"
            ):
                has_docs = _table_exists(conn, "knowledge_documents")
                if has_docs:
                    for row in conn.execute(
                        """
                        SELECT c.provenance_json, d.created_at
                        FROM knowledge_chunks c
                        JOIN knowledge_documents d ON d.id = c.document_id
                        """
                    ).fetchall():
                        prov = _loads(row["provenance_json"], {})
                        if not isinstance(prov, dict):
                            continue
                        tags = prov.get("tags") or []
                        if isinstance(tags, list):
                            _add_tags(tags, _parse_ts(row["created_at"]))

        ranked = sorted(cur_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        out = []
        for idx, (tag, count) in enumerate(ranked, start=1):
            prev = prev_counts.get(tag)
            trend = _delta_percent(float(count), float(prev) if prev is not None else None)
            # If tag never seen in previous window and no prior history signal:
            if prev is None and tag not in prev_counts:
                # Check if we have ANY previous-period tags at all
                trend = _delta_percent(float(count), 0.0) if prev_counts else None
                if prev_counts and tag not in prev_counts:
                    trend = None  # new tag — insufficient previous for this tag
            out.append(
                {
                    "rank": idx,
                    "tag": tag,
                    "count": count,
                    "trendPercent": trend,
                }
            )
        return out

    # ------------------------------------------------------------------
    # Processing times panel
    # ------------------------------------------------------------------

    def _processing_times(self, range_key: str) -> dict[str, Any]:
        start, end, _ = _window(range_key)
        with self._control_conn() as conn:
            tasks: dict[str, list[float]] = {k: [] for k in PROCESSING_TASK_LABELS}
            if not _table_exists(conn, "jobs"):
                return {
                    "range": range_key,
                    "from": _iso(start),
                    "to": _iso(end),
                    "tasks": [
                        {
                            "key": k,
                            "label": PROCESSING_TASK_LABELS[k],
                            "avgSeconds": None,
                            "minSeconds": None,
                            "maxSeconds": None,
                            "count": 0,
                            "status": "UNMEASURED",
                        }
                        for k in PROCESSING_TASK_LABELS
                    ],
                }
            cols = _columns(conn, "jobs")
            if "started_at" not in cols or "finished_at" not in cols:
                return {
                    "range": range_key,
                    "tasks": [
                        {
                            "key": k,
                            "label": PROCESSING_TASK_LABELS[k],
                            "avgSeconds": None,
                            "minSeconds": None,
                            "maxSeconds": None,
                            "count": 0,
                            "status": "UNMEASURED",
                        }
                        for k in PROCESSING_TASK_LABELS
                    ],
                }
            rows = conn.execute(
                """
                SELECT capability_id, state, started_at, finished_at
                FROM jobs
                WHERE finished_at IS NOT NULL AND started_at IS NOT NULL
                  AND finished_at >= ? AND finished_at <= ?
                """,
                (_iso(start), _iso(end)),
            ).fetchall()
            for row in rows:
                task = processing_task_for_capability(row["capability_id"])
                if task is None:
                    continue
                if str(row["state"] or "") not in TERMINAL_JOB_STATES:
                    continue
                started = _parse_ts(row["started_at"])
                finished = _parse_ts(row["finished_at"])
                if started is None or finished is None or finished < started:
                    continue
                tasks[task].append((finished - started).total_seconds())

            out_tasks = []
            for key, label in PROCESSING_TASK_LABELS.items():
                durs = tasks.get(key) or []
                if not durs:
                    out_tasks.append(
                        {
                            "key": key,
                            "label": label,
                            "avgSeconds": None,
                            "minSeconds": None,
                            "maxSeconds": None,
                            "count": 0,
                            "status": "EMPTY",
                        }
                    )
                else:
                    out_tasks.append(
                        {
                            "key": key,
                            "label": label,
                            "avgSeconds": round(sum(durs) / len(durs), 2),
                            "minSeconds": round(min(durs), 2),
                            "maxSeconds": round(max(durs), 2),
                            "count": len(durs),
                            "status": "OK",
                        }
                    )
            return {
                "range": range_key,
                "from": _iso(start),
                "to": _iso(end),
                "tasks": out_tasks,
                "durationRule": "finished_at - started_at",
                "excludesNonTerminal": True,
            }

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------

    def _activity(self, *, limit: int) -> dict[str, Any]:
        events: list[dict[str, Any]] = []

        # Observability events (CONTROL)
        with self._control_conn() as conn:
            if _table_exists(conn, "observability_events"):
                cols = _columns(conn, "observability_events")
                # Schema varies — best-effort.
                time_col = "created_at" if "created_at" in cols else ("ts" if "ts" in cols else None)
                if time_col:
                    name_col = "name" if "name" in cols else ("event_name" if "event_name" in cols else None)
                    cat_col = "category" if "category" in cols else None
                    payload_col = "payload_json" if "payload_json" in cols else (
                        "payload" if "payload" in cols else None
                    )
                    select = [time_col]
                    if name_col:
                        select.append(name_col)
                    if cat_col:
                        select.append(cat_col)
                    if payload_col:
                        select.append(payload_col)
                    try:
                        rows = conn.execute(
                            f"""
                            SELECT {", ".join(select)}
                            FROM observability_events
                            ORDER BY {time_col} DESC
                            LIMIT ?
                            """,
                            (limit * 3,),
                        ).fetchall()
                        for row in rows:
                            name = str(row[name_col] if name_col else "event")
                            cat = str(row[cat_col] if cat_col else "")
                            payload = _loads(row[payload_col], {}) if payload_col else {}
                            kind = self._activity_kind(name, cat)
                            detail = self._activity_detail(name, cat, payload)
                            events.append(
                                {
                                    "t": row[time_col],
                                    "kind": kind,
                                    "event": self._activity_title(name, cat, kind),
                                    "details": detail,
                                }
                            )
                    except sqlite3.Error:
                        pass

            if _table_exists(conn, "research_events"):
                try:
                    for row in conn.execute(
                        """
                        SELECT created_at, event_kind, payload_json
                        FROM research_events
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall():
                        kind = "research_completed" if "complet" in str(row["event_kind"] or "").lower() else "other"
                        payload = _loads(row["payload_json"], {})
                        events.append(
                            {
                                "t": row["created_at"],
                                "kind": kind,
                                "event": f"Research {row['event_kind']}",
                                "details": self._safe_detail(payload),
                            }
                        )
                except sqlite3.Error:
                    pass

            if _table_exists(conn, "research_runs"):
                try:
                    for row in conn.execute(
                        """
                        SELECT run_id, status, finished_at, created_at
                        FROM research_runs
                        WHERE status IN ('completed', 'failed', 'cancelled')
                        ORDER BY COALESCE(finished_at, created_at) DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall():
                        events.append(
                            {
                                "t": row["finished_at"] or row["created_at"],
                                "kind": "research_completed",
                                "event": f"Research run {row['status']}",
                                "details": row["run_id"],
                            }
                        )
                except sqlite3.Error:
                    pass

        # Knowledge commit / recent documents
        with self._knowledge_conn() as conn:
            if _table_exists(conn, "knowledge_documents"):
                try:
                    for row in conn.execute(
                        """
                        SELECT id, title, source, created_at
                        FROM knowledge_documents
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall():
                        events.append(
                            {
                                "t": row["created_at"],
                                "kind": "knowledge_added",
                                "event": "Kennis item toegevoegd",
                                "details": f"{row['title'][:80]} ({row['source']})",
                            }
                        )
                except sqlite3.Error:
                    pass

            if _table_exists(conn, "dataset_jobs"):
                try:
                    for row in conn.execute(
                        """
                        SELECT job_id, job_type, status, finished_at, created_at
                        FROM dataset_jobs
                        WHERE status IN ('completed', 'failed')
                        ORDER BY COALESCE(finished_at, created_at) DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall():
                        events.append(
                            {
                                "t": row["finished_at"] or row["created_at"],
                                "kind": "dataset_processed",
                                "event": f"Dataset {row['job_type']} {row['status']}",
                                "details": row["job_id"],
                            }
                        )
                except sqlite3.Error:
                    pass

        # Sort newest first, bound
        def sort_key(e: dict[str, Any]) -> str:
            return str(e.get("t") or "")

        events.sort(key=sort_key, reverse=True)
        trimmed = events[:limit]
        for e in trimmed:
            if e.get("kind") not in ACTIVITY_EVENT_KINDS:
                e["kind"] = "other"
        return {"limit": limit, "items": trimmed}

    def _activity_kind(self, name: str, category: str) -> str:
        blob = f"{name} {category}".lower()
        if "embed" in blob:
            return "embeddings"
        if "knowledge" in blob or "ingest" in blob:
            return "knowledge_added"
        if "dataset" in blob:
            return "dataset_processed"
        if "research" in blob:
            return "research_completed"
        if "sync" in blob:
            return "sync"
        return "other"

    def _activity_title(self, name: str, category: str, kind: str) -> str:
        titles = {
            "knowledge_added": "Kennis item toegevoegd",
            "dataset_processed": "Dataset verwerkt",
            "research_completed": "Research afgerond",
            "sync": "Automatische sync",
            "embeddings": "Embeddings gegenereerd",
        }
        return titles.get(kind) or name or category or "Event"

    def _activity_detail(self, name: str, category: str, payload: Any) -> str:
        if isinstance(payload, dict):
            return self._safe_detail(payload)
        return f"{category}:{name}"[:120]

    def _safe_detail(self, payload: dict[str, Any]) -> str:
        # Redact obvious secrets.
        redacted = {
            k: v
            for k, v in payload.items()
            if not any(s in str(k).lower() for s in ("secret", "token", "password", "api_key", "apikey"))
        }
        count = redacted.get("count") or redacted.get("items") or redacted.get("n")
        source = redacted.get("source") or redacted.get("kind") or redacted.get("type")
        if count is not None and source is not None:
            return f"{count} items ({source})"
        if count is not None:
            return f"{count} items"
        summary = redacted.get("summary") or redacted.get("message") or redacted.get("title")
        if summary:
            return str(summary)[:120]
        return json.dumps(redacted, ensure_ascii=False)[:120] if redacted else "—"

    # ------------------------------------------------------------------
    # Resources (thin projection; live telemetry remains authoritative)
    # ------------------------------------------------------------------

    def _resources(self) -> tuple[dict[str, Any], str]:
        if not self.telemetry_provider:
            return {
                "cpu": {"pct": None, "status": "UNMEASURED"},
                "ram": {"pct": None, "usedBytes": None, "totalBytes": None, "status": "UNMEASURED"},
                "gpu": {"pct": None, "status": "UNMEASURED", "devices": []},
                "disk": {"pct": None, "usedBytes": None, "totalBytes": None, "status": "UNMEASURED", "metric": None},
            }, "UNAVAILABLE"
        snap = self.telemetry_provider()
        if not snap:
            return {
                "cpu": {"pct": None, "status": "UNMEASURED"},
                "ram": {"pct": None, "usedBytes": None, "totalBytes": None, "status": "UNMEASURED"},
                "gpu": {"pct": None, "status": "UNMEASURED", "devices": []},
                "disk": {"pct": None, "usedBytes": None, "totalBytes": None, "status": "UNMEASURED", "metric": None},
            }, "UNAVAILABLE"
        dash = snap.get("dashboard") if isinstance(snap.get("dashboard"), dict) else {}
        cpu = snap.get("cpu") if isinstance(snap.get("cpu"), dict) else {}
        mem = snap.get("memory") if isinstance(snap.get("memory"), dict) else {}
        gpu = snap.get("gpu") if isinstance(snap.get("gpu"), dict) else {}
        disk = snap.get("disk") if isinstance(snap.get("disk"), dict) else {}
        devices = gpu.get("devices") if isinstance(gpu.get("devices"), list) else []
        # GPU aggregate: prefer dashboard.gpuPct (existing semantics); else max device util.
        gpu_pct = dash.get("gpuPct")
        if gpu_pct is None and devices:
            vals = [d.get("utilizationPct") for d in devices if isinstance(d, dict) and d.get("utilizationPct") is not None]
            gpu_pct = max(vals) if vals else None
        return {
            "collectedAt": snap.get("collectedAt"),
            "cpu": {
                "pct": dash.get("cpuPct") if dash.get("cpuPct") is not None else cpu.get("utilizationPct"),
                "status": "OK" if (dash.get("cpuPct") is not None or cpu.get("available")) else "UNMEASURED",
            },
            "ram": {
                "pct": dash.get("ramPct") if dash.get("ramPct") is not None else mem.get("utilizationPct"),
                "usedBytes": mem.get("usedBytes"),
                "totalBytes": mem.get("totalBytes"),
                "status": "OK" if (dash.get("ramPct") is not None or mem.get("available")) else "UNMEASURED",
            },
            "gpu": {
                "pct": gpu_pct,
                "status": "OK" if gpu_pct is not None else ("UNMEASURED" if not gpu.get("available") else "UNMEASURED"),
                "devices": devices,
                "aggregate": "dashboard_gpuPct_or_max_device",
            },
            "disk": {
                "pct": dash.get("diskPct") if dash.get("diskPct") is not None else disk.get("utilizationPct"),
                "usedBytes": disk.get("usedBytes"),
                "totalBytes": disk.get("totalBytes"),
                "metric": disk.get("metric"),
                "status": "OK" if (dash.get("diskPct") is not None or disk.get("available")) else "UNMEASURED",
            },
            "truth": snap.get("truth") or {},
        }, "OK"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _daily_counts(
        self,
        conn: sqlite3.Connection,
        table: str,
        time_col: str,
        start: datetime,
        end: datetime,
        range_key: str,
    ) -> list[float]:
        rows = conn.execute(
            f"""
            SELECT {time_col} AS ts FROM {table}
            WHERE {time_col} >= ? AND {time_col} <= ?
            """,
            (_iso(start), _iso(end)),
        ).fetchall()
        bucket_counts: dict[str, int] = {}
        for row in rows:
            dt = _parse_ts(row["ts"])
            if dt is None:
                continue
            bk = _bucket_key(dt, range_key)
            bucket_counts[bk] = bucket_counts.get(bk, 0) + 1
        return self._spark_from_buckets(bucket_counts, start, end, range_key)

    def _spark_from_buckets(
        self,
        bucket_counts: dict[str, int],
        start: datetime,
        end: datetime,
        range_key: str,
    ) -> list[float]:
        return [float(bucket_counts.get(bk, 0)) for bk in self._bucket_labels(start, end, range_key)]

    def _bucket_labels(self, start: datetime, end: datetime, range_key: str) -> list[str]:
        labels: list[str] = []
        if range_key in {"1h", "24h"}:
            step = timedelta(hours=1)
            cur = start.replace(minute=0, second=0, microsecond=0)
            if cur < start:
                cur += step
            while cur <= end:
                labels.append(_bucket_key(cur, range_key))
                cur += step
        else:
            step = timedelta(days=1)
            cur = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
            if cur < start:
                cur += step
            while cur <= end:
                labels.append(_bucket_key(cur, range_key))
                cur += step
        return labels
