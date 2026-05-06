"""P1-21b: Hypothesis property tests for MF-K05 Gompertz_Microbial."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_k05
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    float_in_bounds,
    output_bounds_for,
)


class TestMFK05PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        A=float_in_bounds("MF-K05", "A"),
        mu_max=float_in_bounds("MF-K05", "mu_max"),
        lambda_h=float_in_bounds("MF-K05", "lambda"),
        t=float_in_bounds("MF-K05", "t"),
    )
    def test_in_bounds_inputs_return_finite_bounded_log_growth(
        self, A: float, mu_max: float, lambda_h: float, t: float
    ) -> None:
        out = mf_k05.solve({"A": A, "mu_max": mu_max, "lambda": lambda_h, "t": t})

        assert_solver_contract(self, out)
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        value = out["result"]["value"]
        bounds = output_bounds_for("MF-K05")
        self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, A + 1.0e-9 * max(1.0, abs(A)))


class TestMFK05PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        A=st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
        mu_max=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
        lambda_h=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    def test_lag_time_value_and_late_time_asymptote(
        self, A: float, mu_max: float, lambda_h: float
    ) -> None:
        at_lag = mf_k05.solve({"A": A, "mu_max": mu_max, "lambda": lambda_h, "t": lambda_h})
        late = mf_k05.solve({"A": A, "mu_max": mu_max, "lambda": 0.0, "t": 100_000.0})

        self.assertTrue(at_lag["validity"]["passed"], msg=at_lag["validity"]["issues"])
        self.assertTrue(late["validity"]["passed"], msg=late["validity"]["issues"])
        self.assertTrue(
            math.isclose(at_lag["result"]["value"], A * math.exp(-math.e), rel_tol=1.0e-12, abs_tol=1.0e-12),
            msg=at_lag["result"]["value"],
        )
        self.assertTrue(
            math.isclose(late["result"]["value"], A, rel_tol=1.0e-12, abs_tol=1.0e-12),
            msg=late["result"]["value"],
        )


class TestMFK05PropertyGompertzLaw(unittest.TestCase):

    @settings(max_examples=200, deadline=2000)
    @given(
        A=st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
        mu_max=st.floats(min_value=0.001, max_value=20.0, allow_nan=False, allow_infinity=False),
        lambda_h=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        lag_gap=st.floats(min_value=1.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        t_offset=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    )
    def test_growth_increases_with_time_and_is_delayed_by_larger_lag(
        self, A: float, mu_max: float, lambda_h: float, lag_gap: float, t_offset: float
    ) -> None:
        values = []
        for t in (0.0, lambda_h, lambda_h + 10.0, lambda_h + 100.0):
            out = mf_k05.solve({"A": A, "mu_max": mu_max, "lambda": lambda_h, "t": t})
            self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
            values.append(out["result"]["value"])

        for earlier, later in zip(values, values[1:]):
            self.assertGreaterEqual(later, earlier - 1.0e-12, msg=values)

        t_same = lambda_h + t_offset
        lower_lag = mf_k05.solve({"A": A, "mu_max": mu_max, "lambda": lambda_h, "t": t_same})
        higher_lag = mf_k05.solve({"A": A, "mu_max": mu_max, "lambda": lambda_h + lag_gap, "t": t_same})
        self.assertTrue(lower_lag["validity"]["passed"], msg=lower_lag["validity"]["issues"])
        self.assertTrue(higher_lag["validity"]["passed"], msg=higher_lag["validity"]["issues"])
        self.assertLessEqual(
            higher_lag["result"]["value"],
            lower_lag["result"]["value"] + 1.0e-12,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
