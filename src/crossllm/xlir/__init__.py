"""Typed, grounded CrossLLM intermediate representation (XLIR)."""

from .compiler import CompilationResult, Diagnostic, XLIRCompiler
from .evaluator import EvaluationError, StateBindings, TraceBindings, evaluate_invariant, evaluate_trace
from .evaluator import evaluate_expression
from .lowering import LoweringDiagnostic, LoweringResult, SolverIR, SolverNode, XLIRLowerer
from .model import BoundRef, Expression, Invariant, Literal, Quantifier, SymbolRef, Temporal, ValueType
from .legitimacy import LegitimacyResult, LegitimacyStatus, assess_legitimacy
from .vacuity import VacuityResult, VacuityStatus, check_antecedent, check_antecedent_smt, check_antecedent_transition
from .primitives import PrimitiveExpansionError, expand_primitive

__all__ = [
    "CompilationResult",
    "Diagnostic",
    "EvaluationError",
    "Expression",
    "BoundRef",
    "Invariant",
    "Literal",
    "SymbolRef",
    "Quantifier",
    "Temporal",
    "StateBindings",
    "TraceBindings",
    "SolverIR",
    "SolverNode",
    "ValueType",
    "VacuityResult",
    "VacuityStatus",
    "XLIRCompiler",
    "XLIRLowerer",
    "LoweringDiagnostic",
    "LoweringResult",
    "check_antecedent",
    "check_antecedent_smt",
    "check_antecedent_transition",
    "LegitimacyResult",
    "LegitimacyStatus",
    "assess_legitimacy",
    "evaluate_expression",
    "evaluate_invariant",
    "evaluate_trace",
    "PrimitiveExpansionError",
    "expand_primitive",
]
