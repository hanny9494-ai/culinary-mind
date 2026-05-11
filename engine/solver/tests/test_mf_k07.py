"""Tests for MF-K07 Binding_Equilibrium."""
from __future__ import annotations
import math, unittest
from engine.solver import mf_k07

class TestMFK07(unittest.TestCase):
    def test_K_a_L_eq_1_half_bound(self):
        out = mf_k07.solve({"K_a": 1.0e6, "L_total": 1.0e-6})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.5)

    def test_high_K_a_high_binding(self):
        out = mf_k07.solve({"K_a": 1.0e9, "L_total": 1.0e-3})
        self.assertTrue(out["validity"]["passed"])
        self.assertGreater(out["result"]["value"], 0.99)

    def test_low_K_a_low_binding(self):
        out = mf_k07.solve({"K_a": 1.0, "L_total": 1.0e-6})
        self.assertTrue(out["validity"]["passed"])
        self.assertLess(out["result"]["value"], 0.01)

    def test_K_d_to_K_a_conversion(self):
        out_a = mf_k07.solve({"K_a": 1.0e7, "L_total": 1.0e-6})
        out_d = mf_k07.solve({"K_d": 1.0e-7, "L_total": 1.0e-6})
        self.assertAlmostEqual(out_a["result"]["value"], out_d["result"]["value"])

    def test_negative_L_rejected(self):
        out = mf_k07.solve({"K_a": 1.0e6, "L_total": -1e-6})
        self.assertFalse(out["validity"]["passed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMFK07ExactQuadratic(unittest.TestCase):
    def test_equilibrium_when_L_comparable_to_P(self):
        """P1 fix: exact quadratic mass balance when ligand not in excess."""
        import math
        K_a = 1.0e6
        L_total = 2.0e-6  # 2× excess only (not vast)
        P_total = 1.0e-6
        out = mf_k07.solve({"K_a": K_a, "L_total": L_total, "P_total": P_total})
        self.assertTrue(out["validity"]["passed"])
        # Exact: PL = 0.5*((P+L+1/Ka) - sqrt((P+L+1/Ka)^2 - 4PL))
        sum_t = P_total + L_total + 1/K_a
        pl = 0.5 * (sum_t - math.sqrt(sum_t**2 - 4*P_total*L_total))
        expected = pl / P_total
        self.assertAlmostEqual(out["result"]["value"], expected, places=8)
        # Compare to approximate model (should differ when L not in excess)
        out_approx = mf_k07.solve({"K_a": K_a, "L_total": L_total})  # no P_total → approx
        self.assertNotAlmostEqual(out["result"]["value"], out_approx["result"]["value"], places=2)

    def test_excess_ligand_approximation(self):
        """Without P_total, fall back to L_free ≈ L_total."""
        out = mf_k07.solve({"K_a": 1.0e6, "L_total": 1.0e-6})
        self.assertTrue(out["validity"]["passed"])
        self.assertAlmostEqual(out["result"]["value"], 0.5)
        self.assertTrue(any("excess-ligand" in a for a in out["assumptions"]))
