from __future__ import annotations

import unittest

from crossllm.baselines import (
    CellEligibility,
    EligibilityStatus,
    build_sensitivity_matrix,
)


class SensitivityMatrixTests(unittest.TestCase):
    def test_matrix_contains_all_prespecified_dimensions_and_pending_eligibility(self) -> None:
        matrix = build_sensitivity_matrix(
            methods=("X", "P"),
            tracks=("automatic",),
            attestation_profiles=("honest", "broken"),
            program_size_strata=("small",),
        )
        # 4 * 4 * 3 * 3 * 2 * 2 * 2 * 3 * 2 * 1 * 2 methods/tracks/profile/size.
        self.assertEqual(len(matrix.cells), 13_824)
        self.assertTrue(all(cell.eligibility.status is EligibilityStatus.PENDING for cell in matrix.cells))
        self.assertEqual(len(matrix.matrix_hash), 64)
        self.assertEqual(matrix.as_dict()["cell_count"], 13_824)

    def test_resolver_records_eligible_and_unsupported_without_inference(self) -> None:
        def resolve(**cell):
            if cell["channel_mode"] == "reordering":
                return CellEligibility(EligibilityStatus.UNSUPPORTED, reason="backend_has_no_reordering_support")
            return CellEligibility(EligibilityStatus.ELIGIBLE, denominator=3)

        matrix = build_sensitivity_matrix(
            methods=("X",), tracks=("automatic",), attestation_profiles=("honest",),
            program_size_strata=("small",),
            proposal_prefixes=(1,), transaction_bounds=(2,), channel_bounds=((6, 1),),
            solver_timeouts=(10,), horizons_minutes=(15,), channel_modes=("fifo", "reordering"),
            reorg_modes=("none",), challenge_timings=("at",), eligibility=resolve,
        )
        statuses = {cell.eligibility.status for cell in matrix.cells}
        self.assertEqual(statuses, {EligibilityStatus.ELIGIBLE, EligibilityStatus.UNSUPPORTED})
        unsupported = next(cell for cell in matrix.cells if cell.eligibility.status is EligibilityStatus.UNSUPPORTED)
        self.assertEqual(unsupported.eligibility.reason, "backend_has_no_reordering_support")
        self.assertEqual(next(cell for cell in matrix.cells if cell.eligibility.status is EligibilityStatus.ELIGIBLE).eligibility.denominator, 3)


if __name__ == "__main__":
    unittest.main()
