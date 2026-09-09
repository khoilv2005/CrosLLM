"""Deterministic SVG figure artifacts for prespecified analysis outputs.

The renderer is dependency-free so a clean worker can generate reviewable SVGs
from archived JSON. It never fills absent observations; a figure is emitted
only when its corresponding data series is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
from math import isfinite
from pathlib import Path
from typing import Mapping, Sequence

from ..contracts.canonical import sha256_hex

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class AnalysisFigure:
    figure_id: str
    kind: str
    source: object
    source_hash: str
    svg_hash: str
    svg: str

    def as_dict(self) -> dict[str, object]:
        return {
            "figure_id": self.figure_id,
            "kind": self.kind,
            "source_hash": self.source_hash,
            "svg_hash": self.svg_hash,
            "format": "svg",
        }

    def write_svg(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.figure_id}.svg"
        path.write_text(self.svg, encoding="utf-8")
        return path


class AnalysisFigureBuilder:
    """Build requested charts with stable sorting and provenance hashes."""

    def build(
        self,
        *,
        paired_lineage: Mapping[str, float] | None = None,
        recall_at_n: Mapping[str, Mapping[int, float]] | None = None,
        time_curves: Mapping[str, Sequence[Point]] | None = None,
        scaling: Mapping[str, Mapping[int, float]] | None = None,
        failure_flow: Mapping[str, int] | None = None,
    ) -> tuple[AnalysisFigure, ...]:
        figures: list[AnalysisFigure] = []
        if paired_lineage is not None:
            source = {key: _finite(value, f"paired_lineage[{key}]") for key, value in sorted(paired_lineage.items())}
            figures.append(self._bar("paired_lineage", "Paired lineage effect", source))
        if recall_at_n is not None:
            source = {
                method: {str(n): _probability(value, f"recall_at_n[{method}][{n}]") for n, value in sorted(series.items())}
                for method, series in sorted(recall_at_n.items())
            }
            figures.append(self._multi_line("recall_at_n", "Recall at N", source))
        if time_curves is not None:
            source = {
                method: [[_finite(x, "time x"), _probability(y, "time y")] for x, y in points]
                for method, points in sorted(time_curves.items())
            }
            for method, points in source.items():
                if not points:
                    raise ValueError(f"time_curves[{method}] must not be empty")
            figures.append(self._multi_line("time_curves", "Time curve", source))
        if scaling is not None:
            source = {
                method: {str(size): _finite(value, f"scaling[{method}][{size}]") for size, value in sorted(series.items())}
                for method, series in sorted(scaling.items())
            }
            figures.append(self._multi_line("scaling", "Scaling", source))
        if failure_flow is not None:
            source = {key: _nonnegative_int(value, f"failure_flow[{key}]") for key, value in sorted(failure_flow.items())}
            figures.append(self._bar("failure_flow", "Failure flow", source))
        return tuple(figures)

    @staticmethod
    def _bar(figure_id: str, title: str, source: Mapping[str, float | int]) -> AnalysisFigure:
        normalized = dict(source)
        source_hash = sha256_hex(normalized)
        values = [float(value) for value in normalized.values()]
        maximum = max([0.0, *values])
        width, height = 900, 480
        left, bottom, chart_width, chart_height = 90, 390, 760, 300
        count = max(1, len(normalized))
        bar_width = chart_width / count * 0.68
        elements = [_header(title), _axes(left, bottom, chart_width, chart_height)]
        for index, (label, value) in enumerate(normalized.items()):
            x = left + chart_width * (index + 0.16) / count
            bar_height = 0.0 if maximum == 0 else chart_height * float(value) / maximum
            y = bottom - bar_height
            elements.append(f'<rect x="{x:.3f}" y="{y:.3f}" width="{bar_width:.3f}" height="{bar_height:.3f}" fill="#35618f"/>')
            elements.append(f'<text x="{x + bar_width / 2:.3f}" y="{bottom + 24}" text-anchor="middle" class="label">{html.escape(str(label))}</text>')
            elements.append(f'<text x="{x + bar_width / 2:.3f}" y="{max(25, y - 8):.3f}" text-anchor="middle" class="value">{float(value):.4g}</text>')
        svg = _svg(width, height, elements)
        return AnalysisFigure(figure_id, "bar", normalized, source_hash, sha256_hex(svg), svg)

    @staticmethod
    def _multi_line(figure_id: str, title: str, source: Mapping[str, object]) -> AnalysisFigure:
        source_hash = sha256_hex(source)
        series: dict[str, list[Point]] = {}
        for method, values in source.items():
            if isinstance(values, dict):
                series[method] = [(float(key), float(value)) for key, value in values.items()]
            else:
                series[method] = [(float(point[0]), float(point[1])) for point in values]  # type: ignore[index]
        points = [point for values in series.values() for point in values]
        if not points:
            raise ValueError(f"{figure_id} requires at least one point")
        min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
        min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
        if min_x == max_x:
            max_x = min_x + 1.0
        if min_y == max_y:
            max_y = min_y + 1.0
        width, height = 900, 480
        left, top, chart_width, chart_height = 90, 60, 760, 330
        elements = [_header(title), _axes(left, top + chart_height, chart_width, chart_height)]
        palette = ("#35618f", "#b44b3b", "#43845c", "#8d5aa8", "#bc8528")
        for series_index, (method, values) in enumerate(sorted(series.items())):
            color = palette[series_index % len(palette)]
            path_points = []
            for x_value, y_value in values:
                x = left + (x_value - min_x) / (max_x - min_x) * chart_width
                y = top + chart_height - (y_value - min_y) / (max_y - min_y) * chart_height
                path_points.append((x, y))
            if len(path_points) > 1:
                path = " ".join(("M" if index == 0 else "L") + f" {x:.3f},{y:.3f}" for index, (x, y) in enumerate(path_points))
                elements.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3"/>')
            for x, y in path_points:
                elements.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="4" fill="{color}"/>')
            legend_x = left + series_index * 140
            elements.append(f'<rect x="{legend_x}" y="425" width="12" height="12" fill="{color}"/>')
            elements.append(f'<text x="{legend_x + 18}" y="436" class="label">{html.escape(method)}</text>')
        svg = _svg(width, height, elements)
        return AnalysisFigure(figure_id, "line", source, source_hash, sha256_hex(svg), svg)


def write_figure_bundle(figures: Sequence[AnalysisFigure], directory: Path) -> Path:
    """Write SVGs and a manifest whose rows point back to source hashes."""
    directory.mkdir(parents=True, exist_ok=True)
    for figure in figures:
        figure.write_svg(directory)
    manifest = directory / "figures.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "figures": [figure.as_dict() for figure in figures],
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _probability(value: object, field: str) -> float:
    number = _finite(value, field)
    if not 0 <= number <= 1:
        raise ValueError(f"{field} must be in [0, 1]")
    return number


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _header(title: str) -> str:
    return f'<text x="450" y="30" text-anchor="middle" class="title">{html.escape(title)}</text>'


def _axes(left: float, bottom: float, width: float, height: float) -> str:
    return f'<line x1="{left}" y1="{bottom}" x2="{left + width}" y2="{bottom}" stroke="#222"/><line x1="{left}" y1="{bottom}" x2="{left}" y2="{bottom - height}" stroke="#222"/>'


def _svg(width: int, height: int, elements: Sequence[str]) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><style>.title{{font: bold 18px sans-serif}}.label{{font: 12px sans-serif}}.value{{font: 11px sans-serif}}</style>{"".join(elements)}</svg>\n'


__all__ = ["AnalysisFigure", "AnalysisFigureBuilder", "write_figure_bundle"]
