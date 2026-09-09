"""Small cancellation bridge for native Z3 solver calls.

Z3's Python ``check`` call is synchronous.  When a campaign cancellation is
available, running it on a daemon thread and using Z3's interrupt API lets the
orchestrator stop the native solver instead of waiting for the configured
solver timeout.  The caller still owns status mapping and completeness rules.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

import z3
import z3.z3core as z3core


@dataclass(frozen=True, slots=True)
class SolverCheck:
    """Raw solver outcome plus cancellation diagnostics."""

    result: object
    interrupted: bool = False
    callback_error: Exception | None = None


def check_solver(
    solver: z3.Solver,
    cancelled: Callable[[], bool] | None,
) -> SolverCheck:
    """Run ``solver.check`` and propagate cooperative cancellation to Z3."""

    if cancelled is None:
        return SolverCheck(solver.check())
    if not callable(cancelled):
        return SolverCheck(solver.check(), callback_error=TypeError("cancelled must be callable"))

    result: list[object] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            result.append(solver.check())
        except Exception as error:  # native bindings may raise non-Z3 exceptions
            errors.append(error)

    worker = threading.Thread(target=run, name="crossllm-z3", daemon=True)
    worker.start()
    interrupted = False
    callback_error: Exception | None = None
    while worker.is_alive():
        worker.join(0.01)
        try:
            if cancelled():
                interrupted = True
                z3core.Z3_solver_interrupt(solver.ctx.ref(), solver.solver)
                break
        except Exception as error:
            callback_error = error
            z3core.Z3_solver_interrupt(solver.ctx.ref(), solver.solver)
            break
    worker.join()
    if errors:
        raise errors[0]
    if not result:
        raise z3.Z3Exception("solver returned no result")
    return SolverCheck(result[0], interrupted, callback_error)


__all__ = ["SolverCheck", "check_solver"]
