"""P1-21b: Hypothesis property tests for MF-K01 Michaelis_Menten."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_k01
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    float_in_bounds,
    near_boundary,
    output_bounds_for,
)


class TestMFK01PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        S=float_in_bounds("MF-K01", "S"),
        Vmax=float_in_bounds("MF-K01", "Vmax"),
        Km=float_in_bounds("MF-K01", "Km"),
    )
    def test_in_bounds_inputs_return_finite_rate_not_above_vmax(
        self, S: float, Vmax: float, Km: float
    ) -> None:
        out = mf_k01.solve({"S": S, "Vmax": Vmax, "Km": Km})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-K01")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, Vmax + 1.0e-9 * max(1.0, abs(Vmax)))


class TestMFK01PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Vmax=near_boundary("MF-K01", "Vmax", side="below_min"),
        Km=near_boundary("MF-K01", "Km", side="below_min"),
    )
    def test_zero_substrate_and_parameter_lower_bounds(
        self, Vmax: float, Km: float
    ) -> None:
        zero = mf_k01.solve({"S": 0.0, "Vmax": 1.0, "Km": 0.5})
        self.assertTrue(zero["validity"]["passed"], msg=zero["validity"]["issues"])
        self.assertAlmostEqual(zero["result"]["value"], 0.0, places=12)

        low_vmax = mf_k01.solve({"S": 1.0, "Vmax": Vmax, "Km": 0.5})
        low_km = mf_k01.solve({"S": 1.0, "Vmax": 1.0, "Km": Km})

        self.assertFalse(low_vmax["validity"]["passed"])
        self.assertTrue(
            any("Vmax" in issue and "outside bounds" in issue for issue in low_vmax["validity"]["issues"]),
            msg=low_vmax["validity"]["issues"],
        )
        self.assertFalse(low_km["validity"]["passed"])
        self.assertTrue(
            any("Km" in issue and "outside bounds" in issue for issue in low_km["validity"]["issues"]),
            msg=low_km["validity"]["issues"],
        )


class TestMFK01PropertyMichaelisMentenLaw(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        Vmax=st.floats(min_value=1.0e-6, max_value=1.0e6, allow_nan=False, allow_infinity=False),
        Km=st.floats(min_value=1.0e-6, max_value=1.0e4, allow_nan=False, allow_infinity=False),
    )
    def test_half_saturation_and_monotonic_substrate_response(
        self, Vmax: float, Km: float
    ) -> None:
        half = mf_k01.solve({"S": Km, "Vmax": Vmax, "Km": Km})
        self.assertTrue(half["validity"]["passed"], msg=half["validity"]["issues"])
        self.assertTrue(
            math.isclose(half["result"]["value"], Vmax / 2.0, rel_tol=1.0e-12, abs_tol=1.0e-12),
            msg=half["result"]["value"],
        )

        values = []
        for substrate in (0.0, Km / 10.0, Km, 10.0 * Km, 100.0 * Km):
            out = mf_k01.solve({"S": substrate, "Vmax": Vmax, "Km": Km})
            self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
            values.append(out["result"]["value"])

        for earlier, later in zip(values, values[1:]):
            self.assertGreaterEqual(later, earlier - 1.0e-9, msg=values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
