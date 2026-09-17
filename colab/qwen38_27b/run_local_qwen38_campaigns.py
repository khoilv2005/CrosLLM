#!/usr/bin/env python3
"""Resumable sequential proposal runner for a local Qwen3.8-27B Colab arm.

Input records intentionally contain a fully rendered public prompt.  This
keeps dataset preparation outside the notebook and prevents this script from
reading benchmark-private fields.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _read_campaigns(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        campaign_id, prompt = row.get("campaign_id"), row.get("prompt")
        if not isinstance(campaign_id, str) or not campaign_id or not isinstance(prompt, str) or not prompt:
            raise ValueError(f"{path}:{line_number}: campaign_id and prompt are required strings")
        if campaign_id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate campaign_id {campaign_id!r}")
        seen.add(campaign_id)
        rows.append(row)
    return rows


def _load_model(model_path: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype="bfloat16")
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        device_map="auto",
        quantization_config=quantization,
        trust_remote_code=True,
    )
    return tokenizer, model


def _checkpoint_path(out_dir: Path, campaign_id: str) -> Path:
    """Use a stable filesystem-safe filename while keeping the ID in JSON."""
    digest = hashlib.sha256(campaign_id.encode("utf-8")).hexdigest()
    return out_dir / f"{digest}.json"


def _load_checkpoint(path: Path, campaign_id: str) -> dict[str, Any] | None:
    """Only a fully written, matching successful result is resumable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not (
        payload.get("record_type") == "local_qwen38_proposal"
        and payload.get("campaign_id") == campaign_id
        and isinstance(payload.get("slots"), list)
    ):
        return None
    return payload


def _is_completed_checkpoint(path: Path, campaign_id: str, slots_per_campaign: int) -> bool:
    payload = _load_checkpoint(path, campaign_id)
    slots = payload.get("slots") if payload else None
    return isinstance(slots, list) and len(slots) == slots_per_campaign and all(
        isinstance(slot, dict) and isinstance(slot.get("response"), str) for slot in slots
    )


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _generate(tokenizer: Any, model: Any, prompt: str, *, max_new_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
    import torch

    messages = [{"role": "user", "content": prompt}]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else None,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True), {
        "prompt_tokens": int(inputs["input_ids"].shape[1]),
        "generated_tokens": int(generated.shape[0]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaigns", type=Path, required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-campaigns", type=int, default=2)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--slots-per-campaign", type=int, default=8)
    parser.add_argument("--fail-fast", action="store_true", help="stop after the first generation error")
    args = parser.parse_args()
    if args.max_campaigns <= 0 or args.max_new_tokens <= 0 or args.slots_per_campaign <= 0:
        raise ValueError("max campaign and generation limits must be positive")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_campaigns(args.campaigns)
    pending: list[dict[str, Any]] = []
    skipped = 0
    corrupt = 0
    for row in rows:
        checkpoint = _checkpoint_path(args.out_dir, row["campaign_id"])
        if checkpoint.exists() and _is_completed_checkpoint(checkpoint, row["campaign_id"], args.slots_per_campaign):
            skipped += 1
        else:
            if checkpoint.exists():
                corrupt += 1
            pending.append(row)

    selected = pending[: args.max_campaigns]
    print(json.dumps({
        "campaigns_total": len(rows), "already_completed": skipped,
        "pending": len(pending), "this_run": len(selected),
        "invalid_checkpoints_to_regenerate": corrupt,
    }), flush=True)
    if not selected:
        return 0

    tokenizer, model = _load_model(args.model_path)
    completed = 0
    slots_completed = 0
    failed = 0
    from tqdm.auto import tqdm

    failures_path = args.out_dir / "failures.jsonl"
    for row in tqdm(selected, desc="Qwen3.8 campaigns", unit="campaign", dynamic_ncols=True):
        campaign_id = row["campaign_id"]
        out = _checkpoint_path(args.out_dir, campaign_id)
        payload = _load_checkpoint(out, campaign_id) or {
            "record_type": "local_qwen38_proposal",
            "campaign_id": campaign_id,
            "campaign": row.get("campaign"),
            "arm": row.get("arm"),
            "method": row.get("method"),
            "public_artifact_pack": row.get("public_artifact_pack"),
            "public_artifact_pack_hash": row.get("public_artifact_pack_hash"),
            "model_tag": "Qwen/Qwen3.8-27B-local-4bit",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prompt_sha256": hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest(),
            "slots": [],
        }
        slots = payload["slots"]
        if not isinstance(slots, list):
            raise ValueError(f"{out}: checkpoint slots must be a list")
        try:
            for slot_index in range(len(slots), args.slots_per_campaign):
                response, usage = _generate(tokenizer, model, row["prompt"], max_new_tokens=args.max_new_tokens, temperature=args.temperature)
                slots.append({
                    "slot_index": slot_index,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "response": response,
                    "usage": usage,
                })
                # Persist every successful slot. A stopped Colab session resumes
                # at the next missing slot instead of repeating the campaign.
                _atomic_json_write(out, payload)
                slots_completed += 1
            completed += 1
        except Exception as exc:  # keep the batch resumable after an individual OOM/request failure
            failure = {
                "campaign_id": campaign_id,
                "next_slot_index": len(slots),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            with failures_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(failure, ensure_ascii=False) + "\n")
            failed += 1
            if args.fail_fast:
                raise
    print(json.dumps({
        "new_campaigns": completed, "failed_this_run": failed,
        "new_slots": slots_completed,
        "already_completed": skipped, "remaining_after_run": len(pending) - completed,
        "checkpoint_dir": str(args.out_dir),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
