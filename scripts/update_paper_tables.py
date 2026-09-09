"""Update marked table regions in the single canonical paper source.

Only values present in an analysis artifact are rendered. Missing inferential
fields remain the manuscript's explicit ``\\ResultTBD`` marker, so this tool
cannot turn an incomplete run into a completed scientific claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


BEGIN = "% BEGIN GENERATED:tab:main-v2"
END = "% END GENERATED:tab:main-v2"
RESULT = r"\ResultTBD"


def render_main_table_rows(payload: dict[str, object]) -> str:
    analysis = payload.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("analysis artifact has no analysis object")
    recalls = analysis.get("recall")
    witnesses = analysis.get("native_witness_yield")
    methods = analysis.get("methods")
    if not isinstance(recalls, dict) or not isinstance(witnesses, dict) or not isinstance(methods, list):
        raise ValueError("analysis artifact lacks method metrics")
    rows: list[str] = [
        r"\toprule",
        r"Method & Cohort & Eligible & Recall & $\Delta$ vs. comparator & 95\% CI & Native witness yield & RMTTW \\ \midrule",
    ]
    for method in sorted(value for value in methods if isinstance(value, str)):
        recall = recalls.get(method)
        witness = witnesses.get(method)
        recall_value = _metric_value(recall)
        witness_value = _metric_value(witness)
        eligible = _metric_known_total(recall)
        rows.append(
            f"{_latex(method)} & development/evaluation & {eligible} & {recall_value} & {RESULT} & {RESULT} & {witness_value} & {RESULT} \\\\"
        )
    rows.append(r"\bottomrule")
    return "\n".join(rows)


def update_paper(paper_path: Path, analysis_path: Path) -> None:
    paper = paper_path.read_text(encoding="utf-8")
    payload = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("analysis artifact must be a JSON object")
    if paper.count(BEGIN) != 1 or paper.count(END) != 1:
        raise ValueError("paper must contain exactly one marked main-results region")
    body = render_main_table_rows(payload)
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    replacement = BEGIN + "\n" + body + "\n" + END
    updated = pattern.sub(lambda _match: replacement, paper, count=1)
    paper_path.write_text(updated, encoding="utf-8")


def _metric_value(metric: object) -> str:
    if not isinstance(metric, dict):
        return RESULT
    value = metric.get("value")
    if value is None:
        return RESULT
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("metric value must be numeric or null")
    return f"{float(value):.4g}"


def _metric_known_total(metric: object) -> str:
    if not isinstance(metric, dict):
        return RESULT
    known, total = metric.get("known"), metric.get("total")
    if not isinstance(known, int) or isinstance(known, bool) or not isinstance(total, int) or isinstance(total, bool):
        return RESULT
    return f"{known}/{total}"


def _latex(value: str) -> str:
    return value.replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("&", r"\&")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper", type=Path, default=Path("paper/paper.tex"))
    parser.add_argument("--analysis", type=Path, required=True)
    args = parser.parse_args(argv)
    update_paper(args.paper, args.analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
