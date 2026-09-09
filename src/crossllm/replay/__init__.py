"""Witness projection and replay boundaries."""

from .native import NativeReplay, ReplayResult
from .evm import EVMReplayResult, EVMReplaySpec, IndependentEVMReplay
from .support import EVMExecutionSupportMatrix, SupportEntry, SupportStatus
from .foundry import FoundryDockerReplay, FoundryReplayResult, FoundryReplaySpec, classify_foundry_failure, summarize_foundry_json
from .assessment import ReplayAssessment, WitnessAssessmentStatus, assess_witness
from .witness import Witness, WitnessProjectionError, WitnessProjector, action_from_dict, state_hash
from .negative_controls import CASE_IDS, NegativeControlResult, build_report as build_negative_control_report, run_negative_controls
from .differential import DifferentialCase, build_cases as build_differential_cases
from .evaluator import IndependentPropertyEvaluator, PropertyEvaluationResult, PropertyEvaluatorSpec, SourceObservation

__all__ = [
    "NativeReplay",
    "ReplayResult",
    "EVMReplayResult",
    "EVMReplaySpec",
    "IndependentEVMReplay",
    "EVMExecutionSupportMatrix",
    "SupportEntry",
    "SupportStatus",
    "FoundryDockerReplay",
    "FoundryReplayResult",
    "FoundryReplaySpec",
    "classify_foundry_failure",
    "summarize_foundry_json",
    "ReplayAssessment",
    "WitnessAssessmentStatus",
    "assess_witness",
    "Witness",
    "WitnessProjectionError",
    "WitnessProjector",
    "action_from_dict",
    "state_hash",
    "CASE_IDS",
    "NegativeControlResult",
    "build_negative_control_report",
    "run_negative_controls",
    "DifferentialCase",
    "build_differential_cases",
    "IndependentPropertyEvaluator",
    "PropertyEvaluationResult",
    "PropertyEvaluatorSpec",
    "SourceObservation",
]
