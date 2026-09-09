"""Monte Carlo precision simulation for the hierarchical paired design."""

from __future__ import annotations

from dataclasses import dataclass, replace
import random
from math import sqrt
from statistics import mean, pstdev, stdev


@dataclass(frozen=True, slots=True)
class PrecisionSimulationConfig:
    instances_per_lineage: dict[str, int]
    campaigns_per_instance: int
    draws: int = 10_000
    seed: int = 0
    target_recall_mcse: float = 0.025
    target_difference_mcse: float = 0.03

    def __post_init__(self) -> None:
        if not self.instances_per_lineage or any(count <= 0 for count in self.instances_per_lineage.values()):
            raise ValueError("instances_per_lineage must contain positive counts")
        if self.campaigns_per_instance <= 0 or self.draws <= 1:
            raise ValueError("campaigns_per_instance and draws must be greater than zero")


@dataclass(frozen=True, slots=True)
class PrecisionSimulationResult:
    draws: int
    seed: int
    campaigns_per_instance: int
    recall_mean: float
    difference_mean: float
    recall_mcse: float
    difference_mcse: float
    recall_target_met: bool
    difference_target_met: bool
    between_lineage_recall_sd: float
    between_lineage_difference_sd: float
    conditional_recall_mcse: float
    conditional_difference_mcse: float
    conditional_recall_sd: float
    conditional_difference_sd: float

    def as_dict(self) -> dict[str, object]:
        return {
            "draws": self.draws,
            "seed": self.seed,
            "campaigns_per_instance": self.campaigns_per_instance,
            "recall_mean": self.recall_mean,
            "difference_mean": self.difference_mean,
            "recall_mcse": self.recall_mcse,
            "difference_mcse": self.difference_mcse,
            "recall_target_met": self.recall_target_met,
            "difference_target_met": self.difference_target_met,
            "between_lineage_recall_sd": self.between_lineage_recall_sd,
            "between_lineage_difference_sd": self.between_lineage_difference_sd,
            "conditional_recall_mcse": self.conditional_recall_mcse,
            "conditional_difference_mcse": self.conditional_difference_mcse,
            "conditional_recall_sd": self.conditional_recall_sd,
            "conditional_difference_sd": self.conditional_difference_sd,
        }


@dataclass(frozen=True, slots=True)
class ReplicateSelection:
    """Development-only comparison of a prespecified common-R menu."""

    candidate_replicates: tuple[int, ...]
    selected_replicates: int | None
    recall_target: float
    difference_target: float
    candidates: tuple[PrecisionSimulationResult, ...]
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "candidate_replicates": list(self.candidate_replicates),
            "selected_replicates": self.selected_replicates,
            "recall_target": self.recall_target,
            "difference_target": self.difference_target,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "reason": self.reason,
        }


def simulate_hierarchical_precision(
    config: PrecisionSimulationConfig,
    *,
    joint_probabilities: dict[str, tuple[float, float, float, float]],
) -> PrecisionSimulationResult:
    """Simulate paired binary outcomes as (both, left-only, right-only, neither)."""
    if set(joint_probabilities) != set(config.instances_per_lineage):
        raise ValueError("joint probabilities must cover exactly the configured lineages")
    for lineage, probabilities in joint_probabilities.items():
        if len(probabilities) != 4 or any(value < 0 for value in probabilities) or abs(sum(probabilities) - 1.0) > 1e-9:
            raise ValueError(f"invalid joint probabilities for {lineage}")
    rng = random.Random(config.seed)
    recalls: list[float] = []
    differences: list[float] = []
    lineage_recall_rates = [
        probabilities[0] + probabilities[1]
        for _lineage, probabilities in sorted(joint_probabilities.items())
    ]
    lineage_difference_rates = [
        probabilities[1] - probabilities[2]
        for _lineage, probabilities in sorted(joint_probabilities.items())
    ]
    labels = ("both", "left_only", "right_only", "neither")
    for _draw in range(config.draws):
        lineage_left: list[float] = []
        lineage_difference: list[float] = []
        for lineage in sorted(config.instances_per_lineage):
            instance_left: list[float] = []
            instance_right: list[float] = []
            for _instance in range(config.instances_per_lineage[lineage]):
                left_campaigns: list[float] = []
                right_campaigns: list[float] = []
                for _campaign in range(config.campaigns_per_instance):
                    outcome = rng.choices(labels, weights=joint_probabilities[lineage], k=1)[0]
                    left_campaigns.append(float(outcome in {"both", "left_only"}))
                    right_campaigns.append(float(outcome in {"both", "right_only"}))
                instance_left.append(mean(left_campaigns))
                instance_right.append(mean(right_campaigns))
            left_value = mean(instance_left)
            right_value = mean(instance_right)
            lineage_left.append(left_value)
            lineage_difference.append(left_value - right_value)
        recalls.append(mean(lineage_left))
        differences.append(mean(lineage_difference))
    # The repeated draws only simulate campaign-level randomness conditional
    # on the configured lineages and probabilities.  The SD across lineage
    # expectations is reported separately so it is not mistaken for another
    # independent campaign draw or pooled prompt-level precision.
    recall_sampling_sd = stdev(recalls)
    difference_sampling_sd = stdev(differences)
    recall_mcse = recall_sampling_sd / (config.draws**0.5)
    difference_mcse = difference_sampling_sd / (config.draws**0.5)
    # This is the conditional design uncertainty for the planned estimator,
    # keeping the lineage hierarchy intact.  It is distinct from ``recall_mcse``:
    # the latter only measures numerical error from using a finite number of
    # Monte Carlo draws.  For recall, each instance mean averages R Bernoulli
    # campaigns.  For a paired difference, the per-campaign value is -1, 0, or
    # +1, so its variance is E[D^2] - E[D]^2.
    lineage_count = len(config.instances_per_lineage)
    if lineage_count == 0:
        conditional_recall_sd = 0.0
        conditional_difference_sd = 0.0
    else:
        recall_variance = 0.0
        difference_variance = 0.0
        for lineage in sorted(config.instances_per_lineage):
            both, left_only, right_only, _neither = joint_probabilities[lineage]
            left_probability = both + left_only
            difference_expectation = left_only - right_only
            difference_second_moment = left_only + right_only
            instance_count = config.instances_per_lineage[lineage]
            recall_variance += left_probability * (1 - left_probability) / (
                config.campaigns_per_instance * instance_count
            )
            difference_variance += (
                difference_second_moment - difference_expectation**2
            ) / (config.campaigns_per_instance * instance_count)
        conditional_recall_sd = sqrt(max(0.0, recall_variance / lineage_count**2))
        conditional_difference_sd = sqrt(max(0.0, difference_variance / lineage_count**2))
    return PrecisionSimulationResult(
        config.draws,
        config.seed,
        config.campaigns_per_instance,
        mean(recalls),
        mean(differences),
        recall_mcse,
        difference_mcse,
        conditional_recall_sd <= config.target_recall_mcse,
        conditional_difference_sd <= config.target_difference_mcse,
        pstdev(lineage_recall_rates) if len(lineage_recall_rates) > 1 else 0.0,
        pstdev(lineage_difference_rates) if len(lineage_difference_rates) > 1 else 0.0,
        recall_mcse,
        difference_mcse,
        conditional_recall_sd,
        conditional_difference_sd,
    )


def select_common_replicates(
    config: PrecisionSimulationConfig,
    *,
    joint_probabilities: dict[str, tuple[float, float, float, float]],
    candidates: tuple[int, ...] = (5, 10, 20),
) -> ReplicateSelection:
    """Choose the smallest prespecified R satisfying both MCSE targets.

    Every candidate uses the same lineage probabilities, seed and draw count;
    only the common campaign replicate count changes. A missing selection is
    explicit so callers must record a redesign/precision limitation rather than
    silently promoting the largest candidate.
    """
    if not candidates or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in candidates):
        raise ValueError("replicate candidates must be positive integers")
    if len(set(candidates)) != len(candidates):
        raise ValueError("replicate candidates must be unique")
    ordered = tuple(sorted(candidates))
    results = tuple(
        simulate_hierarchical_precision(
            replace(config, campaigns_per_instance=replicates),
            joint_probabilities=joint_probabilities,
        )
        for replicates in ordered
    )
    selected = next(
        (result.campaigns_per_instance for result in results
         if result.recall_target_met and result.difference_target_met),
        None,
    )
    reason = (
        "smallest_candidate_meeting_both_mcse_targets"
        if selected is not None else
        "no_candidate_meets_mcse_targets"
    )
    return ReplicateSelection(
        ordered,
        selected,
        config.target_recall_mcse,
        config.target_difference_mcse,
        results,
        reason,
    )
