"""Deterministic campaign plan generation for M08.01."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import random
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

from ..contracts.canonical import canonical_json, sha256_hex


@dataclass(frozen=True, slots=True)
class PlannedCampaign:
    campaign_id: str
    instance_id: str
    lineage_id: str
    method: str
    backbone: str | None
    model_tag: str | None
    replicate: int
    order_index: int
    config_hash: str
    status: str = "planned"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "campaign_id": self.campaign_id,
            "instance_id": self.instance_id,
            "lineage_id": self.lineage_id,
            "method": self.method,
            "backbone": self.backbone,
            "model_tag": self.model_tag,
            "replicate": self.replicate,
            "order_index": self.order_index,
            "config_hash": self.config_hash,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    plan_id: str
    mode: str
    seed: int
    created_at: str
    campaigns: tuple[PlannedCampaign, ...]
    campaigns_hash: str
    protocol_lock_hash: str | None = None
    model_lock_hash: str | None = None
    benchmark_manifest_hash: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "mode": self.mode,
            "seed": self.seed,
            "created_at": self.created_at,
            "campaign_count": len(self.campaigns),
            "campaigns_hash": self.campaigns_hash,
            "protocol_lock_hash": self.protocol_lock_hash,
            "model_lock_hash": self.model_lock_hash,
            "benchmark_manifest_hash": self.benchmark_manifest_hash,
            "campaigns": [campaign.as_dict() for campaign in self.campaigns],
        }
        return {**payload, "plan_hash": sha256_hex(payload)}

    def write_jsonl(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(campaign.as_dict(), sort_keys=True) + "\n" for campaign in self.campaigns),
            encoding="utf-8",
        )

    def write_json(self, path: Path) -> None:
        """Write plan metadata and campaigns together for lock/readiness checks."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")


class CampaignPlanner:
    """Build an immutable, randomized execution order from frozen inputs."""

    def build(
        self,
        *,
        mode: str,
        instances: list[dict[str, str]],
        methods: list[str],
        backbones: list[dict[str, str | None]],
        replicates: int | None,
        seed: int,
        config: dict[str, object],
        protocol_lock_hash: str | None = None,
        model_lock_hash: str | None = None,
        benchmark_manifest_hash: str | None = None,
        created_at: str | None = None,
    ) -> CampaignPlan:
        if mode not in {"development", "evaluation"}:
            raise ValueError("mode must be development or evaluation")
        if replicates is None or replicates <= 0:
            raise ValueError("replicates must be a positive integer")
        if mode == "evaluation":
            lock_values = {
                "protocol": protocol_lock_hash,
                "model": model_lock_hash,
                "benchmark": benchmark_manifest_hash,
            }
            missing = [name for name, value in lock_values.items() if not value]
            if missing:
                raise ValueError(
                    "evaluation plan requires protocol, model and benchmark lock hashes"
                )
            malformed = [
                name for name, value in lock_values.items()
                if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ]
            if malformed:
                raise ValueError(
                    "evaluation lock hashes must be lowercase SHA-256 digests: "
                    + ", ".join(malformed)
                )
        if not instances or not methods or not backbones:
            raise ValueError("instances, methods and backbones must be non-empty")
        self._validate_instances(instances)
        self._validate_backbones(backbones)
        if len(set(methods)) != len(methods) or any(not method for method in methods):
            raise ValueError("methods must be unique and non-empty")
        config_hash = sha256_hex(config)
        rows: list[PlannedCampaign] = []
        for instance in instances:
            for method in methods:
                for backbone in backbones:
                    for replicate in range(1, replicates + 1):
                        identity = canonical_json({
                            "seed": seed,
                            "instance_id": instance["instance_id"],
                            "lineage_id": instance["lineage_id"],
                            "method": method,
                            "backbone": backbone.get("backbone"),
                            "model_tag": backbone.get("model_tag"),
                            "replicate": replicate,
                            "config_hash": config_hash,
                        }).decode("ascii")
                        rows.append(
                            PlannedCampaign(
                                campaign_id=str(uuid5(NAMESPACE_URL, f"crossllm:{identity}")),
                                instance_id=instance["instance_id"],
                                lineage_id=instance["lineage_id"],
                                method=method,
                                backbone=backbone.get("backbone"),
                                model_tag=backbone.get("model_tag"),
                                replicate=replicate,
                                order_index=-1,
                                config_hash=config_hash,
                            )
                        )
        # Randomize only the scheduled order; stable campaign identity stays tied
        # to frozen inputs and is therefore safe to resume/idempotently export.
        rng = random.Random(seed)
        blocks: dict[str, list[PlannedCampaign]] = {}
        for row in rows:
            blocks.setdefault(row.instance_id, []).append(row)
        ordered: list[PlannedCampaign] = []
        for instance_id in sorted(blocks):
            block = blocks[instance_id]
            rng.shuffle(block)
            ordered.extend(block)
        ordered = [replace(row, order_index=index) for index, row in enumerate(ordered)]
        campaign_rows = [row.as_dict() for row in ordered]
        campaigns_hash = sha256_hex(campaign_rows)
        plan_id = str(uuid5(NAMESPACE_URL, f"crossllm-plan:{mode}:{seed}:{campaigns_hash}"))
        return CampaignPlan(
            plan_id=plan_id,
            mode=mode,
            seed=seed,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
            campaigns=tuple(ordered),
            campaigns_hash=campaigns_hash,
            protocol_lock_hash=protocol_lock_hash,
            model_lock_hash=model_lock_hash,
            benchmark_manifest_hash=benchmark_manifest_hash,
        )

    @staticmethod
    def _validate_instances(instances: list[dict[str, str]]) -> None:
        ids: set[str] = set()
        for row in instances:
            if not isinstance(row, dict) or not isinstance(row.get("instance_id"), str) or not row["instance_id"]:
                raise ValueError("each instance needs a non-empty instance_id")
            if not isinstance(row.get("lineage_id"), str) or not row["lineage_id"]:
                raise ValueError("each instance needs a non-empty lineage_id")
            if row["instance_id"] in ids:
                raise ValueError("instance IDs must be unique")
            ids.add(row["instance_id"])

    @staticmethod
    def _validate_backbones(backbones: list[dict[str, str | None]]) -> None:
        keys = [(row.get("backbone"), row.get("model_tag")) for row in backbones]
        if any(not backbone for backbone, _ in keys) or len(set(keys)) != len(keys):
            raise ValueError("backbones must have unique non-empty backbone values")
