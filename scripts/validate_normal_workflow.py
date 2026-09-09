#!/usr/bin/env python3
"""CrossLLM Normal Workflow Validator.

Executes and verifies deterministic paired-domain normal workflow assertions
across all 16 CrossLLM lineages.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
HARNESS_DIR = DATASET_DIR / "harness"

LINEAGES = [
    "hop", "layerzero_v2", "celer_cbridge", "chainbridge",
    "hyperlane", "axelar_gmp", "synapse", "wormhole_evm_sdk",
    "across", "stargate", "arbitrum_token_bridge", "optimism",
    "zksync_era", "polygon_zkevm", "scroll", "linea"
]

def main() -> int:
    print("=" * 60)
    print("Executing CrossLLM Normal Workflow Validations")
    print("=" * 60)
    
    failures = []
    for lid in LINEAGES:
        test_file = HARNESS_DIR / lid / "normal_workflow_test.py"
        if not test_file.exists():
            failures.append(f"{lid}: normal_workflow_test.py missing")
            continue
            
        spec = importlib.util.spec_from_file_location(f"test_{lid}", test_file)
        if spec is None or spec.loader is None:
            failures.append(f"{lid}: unable to load test module")
            continue
            
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            test_fn_name = f"test_{lid}_normal_workflow"
            test_fn = getattr(module, test_fn_name, None)
            if test_fn:
                test_fn()
            else:
                failures.append(f"{lid}: test function {test_fn_name} not found")
        except Exception as e:
            failures.append(f"{lid}: assertion failed: {e}")
            
    print("-" * 60)
    if failures:
        print(f"[FAIL] {len(failures)} normal workflow tests failed:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
        
    print(f"[PASS] All {len(LINEAGES)} lineage normal workflows validated successfully!")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
