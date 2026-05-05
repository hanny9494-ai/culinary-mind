"""P1-21a: @validate_bounds decorator unit tests."""
from __future__ import annotations

import math
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.solver import _common
from engine.solver._common import (
    Validator,
    build_result,
    llm_summary_for,
    provenance_for,
    validate_bounds,
)


class TestValidateBoundsDecorator(unittest.TestCase):

    def setUp(self):
        _common._BOUNDS_CACHE = {}
        _common._MISSING_BOUNDS_WARNED.clear()

    def tearDown(self):
        _common._BOUNDS_CACHE = {}
        _common._MISSING_BOUNDS_WARNED.clear()

    def test_input_in_range_passes(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=50.0, unit="°C", symbol="T",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "T_init": 20,
            "T_boundary": 100,
            "time": 60,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])

    def test_input_below_min_fails(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=50.0, unit="°C", symbol="T",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "T_init": -100,
            "T_boundary": 100,
            "time": 60,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any(
            "T_init" in issue and "outside bounds" in issue
            for issue in out["validity"]["issues"]
        ))

    def test_input_above_max_fails(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=50.0, unit="°C", symbol="T",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "T_init": 500,
            "T_boundary": 100,
            "time": 60,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any(
            "T_init" in issue and "outside bounds" in issue
            for issue in out["validity"]["issues"]
        ))

    def test_output_above_max_fails(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=10000.0, unit="°C", symbol="T(x,t)",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "T_init": 50,
            "T_boundary": 100,
            "time": 60,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any(
            "T(x,t)" in issue and "outside bounds" in issue
            for issue in out["validity"]["issues"]
        ))

    def test_output_nan_fails_finite_check(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=math.nan, unit="°C", symbol="T(x,t)",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "T_init": 50,
            "T_boundary": 100,
            "time": 60,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("T(x,t) must be finite" in i for i in out["validity"]["issues"]))

    def test_missing_mf_id_no_op_warns(self):
        @validate_bounds("MF-XX99")
        def solve(p):
            v = Validator()
            return build_result(
                value=42.0, unit="x", symbol="y",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        with self.assertWarns(RuntimeWarning):
            out = solve({"any": "value"})
        self.assertTrue(out["validity"]["passed"])

    def test_missing_yaml_no_op_warns(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=50.0, unit="°C", symbol="T",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        missing_path = Path("/tmp/codex-definitely-missing-solver-bounds.yaml")
        with patch.object(_common, "_BOUNDS_PATH", missing_path):
            with self.assertWarns(RuntimeWarning):
                out = solve({"T_init": -100})
        self.assertTrue(out["validity"]["passed"])

    def test_yaml_import_missing_no_op_warns(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=50.0, unit="°C", symbol="T",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        with patch.object(_common, "_yaml", None):
            with self.assertWarns(RuntimeWarning):
                out = solve({"T_init": -100})
        self.assertTrue(out["validity"]["passed"])

    def test_dotted_param_resolution(self):
        @validate_bounds("MF-T02")
        def solve(p):
            v = Validator()
            return build_result(
                value=0.6, unit="W/(m·K)", symbol="k",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "composition": {
                "water": 0.7,
                "fat": 0.1,
                "protein": 0.1,
                "carb": 0.1,
            },
            "T_C": 25,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])

        out = solve({
            "composition": {
                "water": 1.5,
                "fat": 0.1,
                "protein": 0.1,
                "carb": 0.1,
            },
            "T_C": 25,
        })
        self.assertFalse(out["validity"]["passed"])

    def test_percent_composition_is_normalized_for_bounds(self):
        @validate_bounds("MF-T02")
        def solve(p):
            v = Validator()
            return build_result(
                value=0.6, unit="W/(m·K)", symbol="k",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "composition": {
                "water": 70,
                "protein": 10,
                "fat": 10,
                "carb": 8,
                "ash": 2,
            },
            "T_C": 25,
        })
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])

    def test_soft_bound_emits_warn_prefix(self):
        @validate_bounds("MF-R05")
        def solve(p):
            v = Validator()
            return build_result(
                value=1.5, unit="dimensionless", symbol="aT",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({"T": 200, "Tg": 0, "C1": 17.44, "C2": 51.6})
        self.assertTrue(any("WARN:" in i for i in out["validity"]["issues"]))
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])

    def test_output_variant_routing_t02_k(self):
        @validate_bounds("MF-T02", output_variant="mf_t02_k")
        def solve(p):
            v = Validator()
            return build_result(
                value=10.0, unit="W/(m·K)", symbol="k",
                assumptions=[], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "composition": {
                "water": 0.7,
                "fat": 0.1,
                "protein": 0.1,
                "carb": 0.1,
            },
            "T_C": 25,
        })
        self.assertFalse(out["validity"]["passed"])
        self.assertTrue(any("k" in i and "outside bounds" in i for i in out["validity"]["issues"]))

    def test_decorator_preserves_provenance_llm_summary(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=50.0, unit="°C", symbol="T(x,t)",
                assumptions=[], validity=v.result(), inputs_used=p,
                provenance=provenance_for(
                    tool_id="MF-T01",
                    tool_canonical_name="Fourier_1D",
                ),
                llm_summary=llm_summary_for(
                    value=50.0,
                    unit="°C",
                    symbol="T(x,t)",
                    tool_canonical_name="Fourier_1D",
                    tool_id="MF-T01",
                ),
            )

        out = solve({
            "T_init": 20,
            "T_boundary": 100,
            "time": 60,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        self.assertIn("provenance", out)
        self.assertIn("llm_summary", out)

    def test_decorator_preserves_legacy_keys(self):
        @validate_bounds("MF-T01")
        def solve(p):
            v = Validator()
            return build_result(
                value=50.0, unit="°C", symbol="T",
                assumptions=["a"], validity=v.result(), inputs_used=p,
            )

        out = solve({
            "T_init": 20,
            "T_boundary": 100,
            "time": 60,
            "x_position": 0.005,
            "alpha": 1.4e-7,
        })
        for key in ["result", "assumptions", "validity", "inputs_used"]:
            self.assertIn(key, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
