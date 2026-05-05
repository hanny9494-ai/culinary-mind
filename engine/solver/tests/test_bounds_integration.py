"""P1-21a: integration checks for solver bounds wiring."""
from __future__ import annotations

import unittest

from engine.solver import (
    mf_c01,
    mf_c02,
    mf_c03,
    mf_c04,
    mf_c05,
    mf_k01,
    mf_k02,
    mf_k03,
    mf_k04,
    mf_k05,
    mf_m01,
    mf_m02,
    mf_m03,
    mf_m04,
    mf_m05,
    mf_m06,
    mf_r01,
    mf_r02,
    mf_r03,
    mf_r04,
    mf_r05,
    mf_r06,
    mf_r07,
    mf_t01,
    mf_t02_cp,
    mf_t02_k,
    mf_t02_rho,
    mf_t03,
    mf_t04,
    mf_t05,
)


ALL_30 = [
    mf_t01, mf_t02_k, mf_t02_cp, mf_t02_rho, mf_t03, mf_t04, mf_t05,
    mf_k01, mf_k02, mf_k03, mf_k04, mf_k05,
    mf_m01, mf_m02, mf_m03, mf_m04, mf_m05, mf_m06,
    mf_r01, mf_r02, mf_r03, mf_r04, mf_r05, mf_r06, mf_r07,
    mf_c01, mf_c02, mf_c03, mf_c04, mf_c05,
]


class TestBoundsIntegration(unittest.TestCase):

    def test_all_30_solvers_have_validate_bounds(self):
        for module in ALL_30:
            with self.subTest(module=module.__name__):
                self.assertTrue(
                    hasattr(module.solve, "__wrapped__"),
                    f"{module.__name__}.solve missing @validate_bounds decorator",
                )

    def test_actual_t01_out_of_bounds_input_fails(self):
        out = mf_t01.solve({
            "T_init": -100,
            "T_boundary": 20,
            "time": 60,
            "x_position": 0,
            "alpha": 1.0e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("T_init" in i for i in out["validity"]["issues"]))

    def test_actual_hlb_input_bounds_fail(self):
        out = mf_c02.solve({"M_h": 2.0e9, "M_l": 1.0})
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("M_h" in i and "outside bounds" in i for i in out["validity"]["issues"]))

    def test_actual_wlf_soft_warn_does_not_fail(self):
        out = mf_r05.solve({"T": 200.0, "Tg": 0.0, "C1": 17.44, "C2": 51.6})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        self.assertTrue(any(i.startswith("WARN:") for i in out["validity"]["issues"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
