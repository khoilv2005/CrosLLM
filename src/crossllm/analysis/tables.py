"""Deterministic table artifacts for the analysis/report boundary."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

from .estimands import AnalysisReport, Metric
from .reporting import ContrastInference


@dataclass(frozen=True, slots=True)
class AnalysisTable:
    table_id: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "table_id": self.table_id,
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
        }

    def as_csv(self) -> str:
        stream = StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(self.columns), extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: row.get(column) for column in self.columns} for row in self.rows)
        return stream.getvalue()

    def write_csv(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.table_id}.csv"
        path.write_text(self.as_csv(), encoding="utf-8")
        return path


def build_analysis_tables(
    report: AnalysisReport,
    primary_inference: Iterable[ContrastInference] = (),
    secondary_inference: Iterable[ContrastInference] = (),
) -> tuple[AnalysisTable, ...]:
    """Build the ten stable table regions named by the reporting plan."""
    metric_tables = (
        ("recall", report.recall),
        ("useful_proposal_recall", report.useful_proposal_recall),
        ("false_alert_rate", report.false_alert_rate),
        ("false_discovery_proportion", report.false_discovery_proportion),
        ("native_witness_yield", report.native_witness_yield),
        ("independent_replay_rate", report.independent_replay_rate),
        ("witness_time", report.witness_time),
        ("claim_time", report.claim_time),
    )
    tables = [
        AnalysisTable(table_id, ("method", "value", "known", "total", "missing", "note"), tuple(
            _metric_row(method, metric) for method, metric in sorted(metrics.items())
        ))
        for table_id, metrics in metric_tables
    ]
    stage_rows: list[dict[str, object]] = []
    for method, stages in sorted(report.stage_denominators.items()):
        for stage, values in sorted(stages.items()):
            stage_rows.append({"method": method, "stage": stage, **values})
    tables.append(AnalysisTable(
        "stage_denominators",
        ("method", "stage", "total", "known", "missing", "positive"),
        tuple(stage_rows),
    ))
    conditioned_rows: list[dict[str, object]] = []
    for method, details in sorted(report.time_details.items()):
        for endpoint_name, endpoint in sorted(details.items()):
            conditioned_rows.append({
                "method": method,
                "endpoint": endpoint_name,
                "restricted_value": endpoint.restricted.value,
                "conditioned_value": endpoint.availability_conditioned.value,
                "intention_to_run": endpoint.intention_to_run.value,
                "conditioned_known": endpoint.availability_conditioned.known,
                "conditioned_total": endpoint.availability_conditioned.total,
            })
    tables.append(AnalysisTable(
        "time_conditioned",
        ("method", "endpoint", "restricted_value", "conditioned_value", "intention_to_run", "conditioned_known", "conditioned_total"),
        tuple(conditioned_rows),
    ))
    inference_rows: list[dict[str, object]] = []
    for family, items in (("primary", primary_inference), ("secondary", secondary_inference)):
        for item in items:
            row = item.as_dict()
            sign = row.pop("sign_test")
            bootstrap = row.pop("bootstrap")
            inference_rows.append({
                "family": family,
                "contrast": row["contrast"],
                "adjusted_p_value": row["adjusted_p_value"],
                "wins": sign["wins"],
                "losses": sign["losses"],
                "ties": sign["ties"],
                "effective_n": sign["effective_n"],
                "raw_p_value": sign["p_value"],
                "estimate": bootstrap["estimate"],
                "ci_low": bootstrap["ci_low"],
                "ci_high": bootstrap["ci_high"],
            })
    tables.append(AnalysisTable(
        "inference",
        ("family", "contrast", "adjusted_p_value", "wins", "losses", "ties", "effective_n", "raw_p_value", "estimate", "ci_low", "ci_high"),
        tuple(inference_rows),
    ))
    return tuple(tables)


def _metric_row(method: str, metric: Metric) -> dict[str, object]:
    return {"method": method, **metric.as_dict()}
