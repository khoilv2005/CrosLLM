#!/usr/bin/env python3
"""Offline CrossLLM planning and manifest checks; does not run any LLM or EVM."""
from __future__ import annotations
import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any

HEX64 = re.compile(r'^[0-9a-fA-F]{64}$')
COMMIT = re.compile(r'^[0-9a-fA-F]{40,64}$')
REQUIRED = ('instance_id','lineage_id','protocol_name','version_id','split','cohort',
            'status','source_repository','source_commit','source_sha256',
            'artifact_pack_sha256','compiler_settings_hash','chain_pair',
            'architecture','threat_profile_id','attestation_profile_id',
            'property_family','gold_property_id','ground_truth_evidence_hash',
            'trigger_validation_status','native_evm_scope')
FAMILIES = {'input_validation','logic','quorum','replay','finality','message_handling'}
COHORTS = {'historical', 'sealed', 'negative', 'prospective', 'adaptation'}
PLACEHOLDER_VALUES = {
    'replace', 'ACTUAL_HASH', 'replace_with_immutable_commit',
    'ASSIGN_STABLE_ID', 'ACTUAL_PROTOCOL', 'EXACT_VERSION',
}

def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding='utf-8') as stream:
        for lineno, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'{path}:{lineno}: invalid JSON: {exc.msg}') from exc
            if not isinstance(row, dict):
                raise ValueError(f'{path}:{lineno}: each row must be an object')
            rows.append(row)
    if not rows:
        raise ValueError('manifest is empty')
    return rows

def validate(rows: list[dict[str, Any]], mode: str = 'starter') -> tuple[list[str], list[str]]:
    if mode not in {'starter', 'evaluation'}:
        raise ValueError(f'unknown validation mode {mode!r}')
    errors: list[str] = []
    warnings: list[str] = []
    ids: set[str] = set()
    hashes: dict[str, str] = {}
    splits: dict[str, set[str]] = collections.defaultdict(set)
    by_id = {r.get('instance_id'): r for r in rows}
    for num, row in enumerate(rows, 1):
        ident = str(row.get('instance_id', f'row-{num}'))
        missing = [k for k in REQUIRED if k not in row or row[k] is None]
        if missing:
            errors.append(f'{ident}: missing required values {missing}')
        if ident in ids:
            errors.append(f'{ident}: duplicate instance_id')
        ids.add(ident)
        for key in ('source_sha256','artifact_pack_sha256','compiler_settings_hash',
                    'ground_truth_evidence_hash'):
            if not HEX64.fullmatch(str(row.get(key,''))):
                errors.append(f'{ident}: {key} must be an actual 64-hex SHA256')
        if not COMMIT.fullmatch(str(row.get('source_commit',''))):
            errors.append(f'{ident}: source_commit must be a full commit hash')
        split = row.get('split')
        if split not in {'development','evaluation'}:
            errors.append(f'{ident}: invalid split {split!r}')
        lineage = str(row.get('lineage_id',''))
        if lineage:
            splits[lineage].add(str(split))
        if row.get('property_family') not in FAMILIES:
            errors.append(f'{ident}: unrecognized property_family')
        if row.get('cohort') not in COHORTS:
            errors.append(f'{ident}: invalid cohort')
        if row.get('status') not in {'vulnerable','patched','benign'}:
            errors.append(f'{ident}: invalid status')
        if (not isinstance(row.get('chain_pair'),list) or len(row['chain_pair']) != 2
                or any(not isinstance(chain, str) or not chain for chain in row['chain_pair'])):
            errors.append(f'{ident}: chain_pair must have two entries')
        if not isinstance(row.get('native_evm_scope'), bool):
            errors.append(f'{ident}: native_evm_scope must be boolean')
        if row.get('cohort') == 'negative' and row.get('status') == 'vulnerable':
            errors.append(f'{ident}: vulnerable item cannot initially be a negative control')
        if row.get('status') == 'vulnerable' and row.get('trigger_validation_status') != 'pass':
            errors.append(f'{ident}: vulnerable instance lacks a validated trigger')
        if row.get('status') in {'patched','benign'} and not row.get('negative_validation_scope'):
            errors.append(f'{ident}: negative control needs an explicit validation scope')
        if row.get('cohort') == 'sealed' and not row.get('seal_timestamp'):
            errors.append(f'{ident}: sealed cohort needs a commitment timestamp')
        if row.get('cohort') == 'historical' and row.get('native_evm_scope') is not True:
            errors.append(f'{ident}: non-EVM adaptation must not be labeled native historical')
        digest = str(row.get('artifact_pack_sha256',''))
        if digest in hashes:
            warnings.append(f'{ident}: identical artifact pack to {hashes[digest]}; '
                            'deduplicate instances or justify separate properties without inflating negatives')
        hashes[digest] = ident
        paired = row.get('paired_instance_id')
        if paired and paired not in by_id:
            errors.append(f'{ident}: paired instance {paired} is absent')
        elif paired and by_id[paired].get('lineage_id') != row.get('lineage_id'):
            errors.append(f'{ident}: matched pair has different code lineage')
        elif paired and by_id[paired].get('paired_instance_id') != ident:
            errors.append(f'{ident}: matched pair linkage is not reciprocal')
        # Gold identifiers and hashes are allowed; secret property/trigger contents are not.
        for key in ('gold_property','trigger_calldata','exploit_payload','mutation_diff'):
            if key in row:
                errors.append(f'{ident}: secret field {key} is forbidden in the public manifest')
        for key, value in row.items():
            if isinstance(value, str) and value in PLACEHOLDER_VALUES:
                errors.append(f'{ident}: placeholder value in {key}')
        if mode == 'evaluation' and row.get('cohort') not in {'sealed', 'negative'}:
            errors.append(f'{ident}: evaluation mode requires sealed or negative cohort')
        if mode == 'evaluation' and row.get('split') != 'evaluation':
            errors.append(f'{ident}: evaluation mode requires evaluation split')
    for lineage, values in splits.items():
        if len(values) > 1:
            errors.append(f'{lineage}: development/evaluation lineage leakage')
    eval_lineages = {r.get('lineage_id') for r in rows if r.get('split') == 'evaluation'}
    if len(eval_lineages) < 12:
        warnings.append(f'Only {len(eval_lineages)} evaluation lineages; planning target is at least 12')
    if mode == 'evaluation':
        for digest, ident in hashes.items():
            duplicates = [r.get('instance_id') for r in rows
                          if r.get('artifact_pack_sha256') == digest]
            if len(duplicates) > 1:
                errors.append(f'{ident}: duplicate artifact content in evaluation rows {duplicates}')
    return errors, warnings

def inventory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {'instances':len(rows),
        'lineages':len({r['lineage_id'] for r in rows}),
        'protocol_names':len({r['protocol_name'] for r in rows}),
        'versions':len({(r['lineage_id'],r['version_id']) for r in rows}),
        'distinct_artifact_packs':len({r['artifact_pack_sha256'] for r in rows})}
    for key in ('split','cohort','status','property_family'):
        out[key] = dict(collections.Counter(str(r.get(key)) for r in rows))
    # Dependencies may be repeated across packs: do not label this sum unique contracts.
    out['dependency_references_sum_not_unique_contracts'] = sum(
        int(r.get('infrastructure_contract_count',0)) for r in rows)
    return out

def plan(config: dict[str, Any]) -> dict[str, Any]:
    npos = int(config['benchmark_targets']['sealed_positive'])
    nneg = int(config['benchmark_targets']['distinct_negative'])
    nhist = int(config['benchmark_targets'].get('historical_planning_count',0))
    r = int(config['planning_replicates'])
    n = int(config['proposal_slots'])
    families = len(config['model_families'])
    instances = npos+nneg+nhist
    xc = families*instances*r
    pc = xc
    seconds = float(config['budgets']['campaign_wall_seconds'])
    cores = int(config['budgets']['worker_cpu_cores'])
    return {
        'status':'PLANNING_ARITHMETIC_NOT_EXPERIMENTAL_RESULTS',
        'instances_in_this_plan':instances,
        'crossllm_campaigns':xc,'pure_llm_campaigns':pc,
        'base_llm_calls_before_retry':(xc+pc)*n,
        'crossllm_backend_worker_hours_upper_bound':xc*seconds/3600,
        'crossllm_backend_core_hours_upper_bound':xc*seconds/3600*cores,
        'input_tokens_upper_bound_requested':(xc+pc)*n*config['budgets']['input_native_token_cap'],
        'generated_tokens_upper_bound_requested':(xc+pc)*n*config['budgets']['generated_native_token_cap'],
        'excludes':'historical cases unless entered; non-LLM baselines; GPTScan subset; '
                   'ablations; sensitivities; calibration; preflight; adjudication',
        'warning':'Cloud quota, actual parameter enforcement and observed latency are not established.'}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command',required=True)
    p = sub.add_parser('plan');p.add_argument('--config',type=Path,required=True)
    for name in ('validate','inventory'):
        p = sub.add_parser(name);p.add_argument('--manifest',type=Path,required=True)
        p.add_argument('--out',type=Path)
        if name == 'validate':
            p.add_argument('--mode', choices=('starter', 'evaluation'), default='starter')
    args = ap.parse_args()
    try:
        if args.command == 'plan':
            result = plan(json.loads(args.config.read_text(encoding='utf-8')))
            print(json.dumps(result,indent=2));return 0
        rows = load_jsonl(args.manifest)
        errors,warnings = validate(rows, getattr(args, 'mode', 'starter'))
        for item in warnings:print('WARNING: '+item,file=sys.stderr)
        for item in errors:print('ERROR: '+item,file=sys.stderr)
        if errors:return 2
        result = inventory(rows) if args.command == 'inventory' else {
            'basic_manifest_checks':'pass','validation_mode':getattr(args, 'mode', 'starter'),
            'instances':len(rows),'warnings':warnings,
            'not_checked':'semantic ground truth, primary-source authenticity, '
                          'code ancestry, model identity or implementation correctness'}
        text = json.dumps(result,indent=2)
        if getattr(args,'out',None):args.out.write_text(text+'\n',encoding='utf-8')
        else:print(text)
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);return 2

if __name__ == '__main__':
    raise SystemExit(main())
