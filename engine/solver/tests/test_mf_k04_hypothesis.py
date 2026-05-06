"""P1-21b: Hypothesis property tests for MF-K04 F_Value."""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.solver import mf_k04
from engine.solver.tests._hypothesis_helpers import (
    assert_solver_contract,
    output_bounds_for,
)


class TestMFK04PropertyRangeInvariance(unittest.TestCase):

    @settings(max_examples=50, deadline=5000)
    @given(
        T_ref=st.floats(min_value=80.0, max_value=160.0, allow_nan=False, allow_infinity=False),
        z=st.floats(min_value=5.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        delta_below=st.floats(min_value=0.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        time_s=st.floats(min_value=1.0, max_value=600_000.0, allow_nan=False, allow_infinity=False),
    )
    def test_sampled_temperature_profile_returns_finite_nonnegative_f_value(
        self, T_ref: float, z: float, delta_below: float, time_s: float
    ) -> None:
        temp = T_ref - delta_below
        sampled = mf_k04.solve({
            "times_s": [0.0, time_s / 2.0, time_s],
            "temperatures_C": [temp, temp, temp],
            "T_ref": T_ref,
            "z": z,
        })
        constant = mf_k04.solve({"T_C": temp, "time": time_s, "T_ref": T_ref, "z": z})
        callable_profile = mf_k04.solve({
            "T_profile": lambda _: temp,
            "t_start": 0.0,
            "t_end": time_s,
            "T_ref": T_ref,
            "z": z,
        })

        for out in (sampled, constant, callable_profile):
            assert_solver_contract(self, out)
            self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
            value = out["result"]["value"]
            self.assertTrue(math.isfinite(value), msg=f"output {value!r} not finite")
            self.assertGreaterEqual(value, 0.0)

        value = sampled["result"]["value"]
        bounds = output_bounds_for("MF-K04")
        self.assertGreaterEqual(value, bounds["min"])
        self.assertLessEqual(value, bounds["max"])
        self.assertTrue(
            math.isclose(constant["result"]["value"], value, rel_tol=1.0e-9, abs_tol=1.0e-12),
            msg=(constant["result"]["value"], value),
        )
        self.assertTrue(
            math.isclose(callable_profile["result"]["value"], value, rel_tol=1.0e-9, abs_tol=1.0e-12),
            msg=(callable_profile["result"]["value"], value),
        )


class TestMFK04PropertyBoundaryBehavior(unittest.TestCase):

    @settings(max_examples=50, deadline=5000)
    @given(
        T_ref=st.floats(min_value=80.0, max_value=160.0, allow_nan=False, allow_infinity=False),
        z=st.floats(min_value=5.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    )
    def test_cold_profile_is_near_zero_and_zero_z_fails_validity(
        self, T_ref: float, z: float
    ) -> None:
        cold_temp = T_ref - (9.0 * z)
        cold = mf_k04.solve({
            "times_s": [0.0, 30.0, 60.0],
            "temperatures_C": [cold_temp, cold_temp, cold_temp],
            "T_ref": T_ref,
            "z": z,
        })
        zero_z = mf_k04.solve({"T_C": T_ref, "time": 60.0, "T_ref": T_ref, "z": 0.0})

        self.assertTrue(cold["validity"]["passed"], msg=cold["validity"]["issues"])
        self.assertLessEqual(cold["result"]["value"], 1.1e-9)
        self.assertFalse(zero_z["validity"]["passed"])
        self.assertTrue(
            any("z" in issue for issue in zero_z["validity"]["issues"]),
            msg=zero_z["validity"]["issues"],
        )


class TestMFK04PropertyLethalityLaw(unittest.TestCase):

    @settings(max_examples=50, deadline=5000)
    @given(
        T_ref=st.floats(min_value=100.0, max_value=140.0, allow_nan=False, allow_infinity=False),
        z=st.floats(min_value=8.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        delta_T=st.floats(min_value=1.0, max_value=15.0, allow_nan=False, allow_infinity=False),
        time_s=st.floats(min_value=10.0, max_value=600.0, allow_nan=False, allow_infinity=False),
    )
    def test_uniform_temperature_shift_scales_f_value_by_expected_factor(
        self, T_ref: float, z: float, delta_T: float, time_s: float
    ) -> None:
        base_temp = T_ref - 40.0
        base = mf_k04.solve({
            "times_s": [0.0, time_s / 2.0, time_s],
            "temperatures_C": [base_temp, base_temp, base_temp],
            "T_ref": T_ref,
            "z": z,
        })
        shifted = mf_k04.solve({
            "times_s": [0.0, time_s / 2.0, time_s],
            "temperatures_C": [base_temp + delta_T, base_temp + delta_T, base_temp + delta_T],
            "T_ref": T_ref,
            "z": z,
        })

        self.assertTrue(base["validity"]["passed"], msg=base["validity"]["issues"])
        self.assertTrue(shifted["validity"]["passed"], msg=shifted["validity"]["issues"])
        observed = shifted["result"]["value"] / base["result"]["value"]
        expected = 10.0 ** (delta_T / z)
        self.assertTrue(
            math.isclose(observed, expected, rel_tol=1.0e-10, abs_tol=1.0e-12),
            msg=(observed, expected),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
