"""Generate a provenance-aware, non-admission artifact status report."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "dataset" / "artifacts"
REPORT = ROOT / "dataset" / "reports" / "artifact_status.md"
SOURCE_LOCK = ROOT / "dataset" / "sources" / "source_lock.json"

LINEAGES = (
    "hop", "layerzero_v2", "celer_cbridge", "chainbridge",
    "hyperlane", "axelar_gmp", "synapse", "wormhole_evm_sdk",
    "across", "stargate", "arbitrum_token_bridge", "optimism",
    "zksync_era", "polygon_zkevm", "scroll", "linea",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bytecode_status(lineage_dir: Path) -> str:
    bytecode = sorted((lineage_dir / "bytecode").glob("*.hex"))
    if not bytecode:
        return "Missing"
    invalid = [path for path in bytecode if len(path.read_text(encoding="utf-8").strip()) <= 2]
    if invalid:
        return "Incomplete (empty/placeholder)"
    return "Non-empty (unverified)"


def _lineage_row(lineage: str, locked: dict) -> tuple[str, bool] | None:
    directory = ARTIFACTS / lineage
    symbols_path = directory / "symbols.json"
    manifest_path = directory / "manifest.json"
    if not symbols_path.is_file() or not manifest_path.is_file():
        return None
    symbols = _load(symbols_path)
    manifest = _load(manifest_path)
    receipt = _load(directory / "source_receipt.json") if (directory / "source_receipt.json").is_file() else {}
    harness_path = ROOT / "dataset" / "harness" / lineage / "harness_config.json"
    harness = _load(harness_path) if harness_path.is_file() else {}
    contracts = symbols.get("contracts", {})
    names = ", ".join(f"`{name}`" for name in contracts)
    functions = sum(int(item.get("function_count", 0)) for item in contracts.values())
    events = sum(int(item.get("event_count", 0)) for item in contracts.values())
    storage = sum(int(item.get("storage_slot_count", 0)) for item in contracts.values())
    admission = receipt.get("artifact_admission_status", "missing")
    pinned = receipt.get("pinned_status", "unknown")
    lock_status = locked.get("artifact_status", "missing")
    harness_status = (
        "source-backed harness"
        if harness.get("source_backed") is True
        else "generated harness"
    )
    readiness = "NOT_EXPERIMENT_READY"
    line = (
        f"| `{lineage}` | {symbols.get('protocol', 'unknown')} | {manifest.get('split', 'unknown')} | "
        f"{names} | {functions} | {events} | {storage} | {manifest.get('artifact_count', 0)} files | "
        f"`{readiness}; {harness_status}` | `{_bytecode_status(directory)}` | "
        f"`lock={lock_status}; pack={admission}; checkout={pinned}` |"
    )
    return line, _bytecode_status(directory) == "Non-empty (unverified)"


def build_report() -> str:
    source_lock = _load(SOURCE_LOCK)
    locked = source_lock.get("lineages", [])
    lock_by_lineage = {
        row.get("lineage_id"): row
        for row in locked
        if isinstance(row, dict) and row.get("lineage_id")
    }
    source_pinned = sum(row.get("artifact_status") == "source_pinned" for row in locked)
    acquired = len(locked)
    source_backed = sum(
        _load(ROOT / "dataset" / "harness" / lineage / "harness_config.json").get("source_backed") is True
        for lineage in LINEAGES
        if (ROOT / "dataset" / "harness" / lineage / "harness_config.json").is_file()
    )
    rows: list[str] = []
    nonempty = 0
    for lineage in LINEAGES:
        result = _lineage_row(lineage, lock_by_lineage.get(lineage, {}))
        if result is None:
            continue
        row, has_nonempty = result
        rows.append(row)
        nonempty += int(has_nonempty)

    return "\n".join([
        "# CrossLLM Dataset Artifact Status Report (Audit Assessment)",
        "",
        "## 1. Executive Summary",
        "",
        f"- **Total Locked Lineages**: {acquired} (4 Development, 12 Evaluation)",
        f"- **Source-pinned registry entries**: {source_pinned} / {acquired}; source-pinned is not case admission.",
        f"- **Artifact packs present**: {len(rows)}; {nonempty} contain non-empty bytecode files (unverified).",
        f"- **Paired-domain harnesses**: {source_backed} source-backed development probes and {len(rows) - source_backed} generated fixtures; independent replay and evaluation admission are not proven.",
        "- **Admission status**: NOT EXPERIMENT READY. Build probes and non-empty bytecode do not establish ancestry, mutation, trigger, control or owner-acceptance evidence.",
        "",
        "## 2. Lineage Artifact Status Matrix",
        "",
        "| Lineage ID | Protocol | Split | Target Contracts | Functions | Events | Storage Slots | Artifacts Hashed | Readiness Status | Bytecode Status | Provenance |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        *rows,
        "",
        "## 3. Findings & Required Engineering Steps",
        "",
        "1. **Source admission**: verify locked archive, ancestry, component licenses and clean-tree policy; record owner acceptance and Codex self-check, without claiming a second review.",
        "2. **Build closure**: retain selected contracts, compiler/settings, ABI, bytecode, storage, dependencies, libraries, proxy/initializer and deployment configuration; non-empty bytecode alone is insufficient.",
        "3. **Native paired harness**: deploy exact source-backed contracts in isolated EVM domains, execute normal workflow and independently validate mutations/controls.",
        "4. **Admission**: attach private evidence hashes, matched-control validation and owner acceptance records before using the final manifest; retain the single-operator limitation.",
        "",
    ])


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report() + "\n", encoding="utf-8")
    print(f"Updated {REPORT.relative_to(ROOT)} from current artifact metadata; no admission is asserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
