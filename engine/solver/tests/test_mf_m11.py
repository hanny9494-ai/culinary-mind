"""Tests for MF-M11 SCFE_Solubility (Chrastil)."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_m11

class TestMFM11(unittest.TestCase):
    # Realistic caffeine in SC-CO2 Chrastil params (k=4.85, a=-7000, b=-23)
    KW = {"k": 4.85, "a": -7000.0, "b": -23.0}

    def test_chrastil_caffeine_typical(self):
        out = mf_m11.solve({"rho_CO2": 800.0, "T_K": 313.0, **self.KW})
        self.assertTrue(out["validity"]["passed"], msg=out["validity"]["issues"])
        # Expected y ~ exp(-12.94) ~ 2.4e-6
        ln_y = self.KW["k"] * math.log(800.0) + self.KW["a"]/313.0 + self.KW["b"]
        self.assertAlmostEqual(out["result"]["value"], math.exp(ln_y), delta=1e-10)

    def test_T_C_conversion(self):
        out_k = mf_m11.solve({"rho_CO2": 800.0, "T_K": 313.0, **self.KW})
        out_c = mf_m11.solve({"rho_CO2": 800.0, "T_C": 313.0 - 273.15, **self.KW})
        self.assertAlmostEqual(out_k["result"]["value"], out_c["result"]["value"], delta=1e-12)

    def test_higher_rho_higher_solubility(self):
        out_low = mf_m11.solve({"rho_CO2": 400.0, "T_K": 313.0, **self.KW})
        out_high = mf_m11.solve({"rho_CO2": 900.0, "T_K": 313.0, **self.KW})
        self.assertGreater(out_high["result"]["value"], out_low["result"]["value"])

    def test_negative_rho_rejected(self):
        out = mf_m11.solve({"rho_CO2": -100.0, "T_K": 313.0, **self.KW})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
