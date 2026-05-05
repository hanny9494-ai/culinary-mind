"""P1-22: provenance field consistency across all MF solver entry points."""
from __future__ import annotations

import re
import unittest
from typing import Callable

from engine.solver import (
    mf_c01, mf_c02, mf_c03, mf_c04, mf_c05,
    mf_k01, mf_k02, mf_k03, mf_k04, mf_k05,
    mf_m01, mf_m02, mf_m03, mf_m04, mf_m05, mf_m06,
    mf_r01, mf_r02, mf_r03, mf_r04, mf_r05, mf_r06, mf_r07,
    mf_t01, mf_t02_cp, mf_t02_k, mf_t02_rho, mf_t03, mf_t04, mf_t05,
)


SAMPLE_PARAMS = {
    "MF-T01": {
        "T_init": 20.0, "T_boundary": 100.0, "time": 60.0,
        "x_position": 0.005, "alpha": 1.4e-7,
    },
    "MF-T02-k": {
        "composition": {"water": 0.7, "protein": 0.2, "fat": 0.1},
        "T_C": 25.0,
    },
    "MF-T02-Cp": {
        "composition": {"water": 0.7, "protein": 0.2, "fat": 0.1},
        "T_C": 25.0,
    },
    "MF-T02-rho": {
        "composition": {"water": 0.7, "protein": 0.2, "fat": 0.1},
        "T_C": 25.0,
    },
    "MF-T03": {"A": 1.0e10, "Ea": 50000.0, "T_K": 298.0},
    "MF-T04": {"Re": 10000.0, "Pr": 0.7, "C": 0.023, "m": 0.8, "n": 0.4},
    "MF-T05": {
        "rho": 1050.0, "L": 250000.0, "d": 0.05,
        "T_f": -1.0, "T_inf": -30.0, "h": 20.0, "k": 0.45,
        "P": 0.5, "R": 0.125,
    },
    "MF-K01": {"S": 1.0, "Vmax": 2.0, "Km": 1.0},
    "MF-K02": {"t": 60.0, "N0": 1000.0, "N": 100.0},
    "MF-K03": {"T1": 121.0, "T2": 131.0, "D1": 10.0, "D2": 1.0},
    "MF-K04": {"T_C": 121.1, "time": 60.0},
    "MF-K05": {"t": 10.0, "A": 5.0, "mu_max": 1.0, "lambda": 2.0},
    "MF-M01": {
        "C_init": 0.0, "C_boundary": 1.0,
        "time": 100.0, "x_position": 0.001, "D_eff": 1.0e-10,
    },
    "MF-M02": {"a_w": 0.5, "W_m": 0.08, "C": 10.0, "K": 0.9},
    "MF-M03": {"substance": "Water", "T_C": 25.0},
    "MF-M04": {"pKa": 4.76, "A_minus_conc": 0.1, "HA_conc": 0.1},
    "MF-M05": {"substance": "CO2", "H": 3.35e-4, "p_gas": 101325.0, "T_C": 25.0},
    "MF-M06": {"substance": "Water", "T_C": 100.0},
    "MF-R01": {"gamma_dot": 100.0, "K": 0.001, "n": 1.0},
    "MF-R02": {"tau_0": 5.0, "K": 2.0, "n": 0.5, "gamma_dot": 100.0},
    "MF-R03": {"tau_0": 4.0, "K_C": 0.25, "gamma_dot": 100.0},
    "MF-R04": {"w1": 0.7, "w2": 0.3, "Tg1": 350.0, "Tg2": 150.0, "k": 5.0},
    "MF-R05": {"T": 50.0, "Tg": 50.0},
    "MF-R06": {"k": 2.5, "I": 1.0, "n": 0.67},
    "MF-R07": {"E": 1.0e11, "gamma_s": 1.0, "a": 1.0e-6},
    "MF-C01": {"r": 1.0e-6, "rho_p": 1050.0, "rho_f": 1000.0, "eta": 0.001},
    "MF-C02": {"M_h": 5.0, "M_l": 5.0},
    "MF-C03": {
        "A_H": 1.0e-20, "kappa": 1.0e8, "zeta": 0.05,
        "epsilon": 78.5, "T": 298.15, "D": 1.0e-9,
    },
    "MF-C04": {"sigma": 0.072, "R": 0.001},
    "MF-C05": {"k1": 1.0, "k2": 2.0, "T1": 20.0, "T2": 30.0},
}


ALL_SOLVERS: list[tuple[str, Callable[[dict], dict]]] = [
    ("MF-T01", mf_t01.solve),
    ("MF-T02-k", mf_t02_k.solve),
    ("MF-T02-Cp", mf_t02_cp.solve),
    ("MF-T02-rho", mf_t02_rho.solve),
    ("MF-T03", mf_t03.solve),
    ("MF-T04", mf_t04.solve),
    ("MF-T05", mf_t05.solve),
    ("MF-K01", mf_k01.solve),
    ("MF-K02", mf_k02.solve),
    ("MF-K03", mf_k03.solve),
    ("MF-K04", mf_k04.solve),
    ("MF-K05", mf_k05.solve),
    ("MF-M01", mf_m01.solve),
    ("MF-M02", mf_m02.solve),
    ("MF-M03", mf_m03.solve),
    ("MF-M04", mf_m04.solve),
    ("MF-M05", mf_m05.solve),
    ("MF-M06", mf_m06.solve),
    ("MF-R01", mf_r01.solve),
    ("MF-R02", mf_r02.solve),
    ("MF-R03", mf_r03.solve),
    ("MF-R04", mf_r04.solve),
    ("MF-R05", mf_r05.solve),
    ("MF-R06", mf_r06.solve),
    ("MF-R07", mf_r07.solve),
    ("MF-C01", mf_c01.solve),
    ("MF-C02", mf_c02.solve),
    ("MF-C03", mf_c03.solve),
    ("MF-C04", mf_c04.solve),
    ("MF-C05", mf_c05.solve),
]


EXPECTED_CANONICAL_NAMES = {
    "MF-T01": "Fourier_1D",
    "MF-T02-k": "Choi_Okos_k",
    "MF-T02-Cp": "Choi_Okos_Cp",
    "MF-T02-rho": "Choi_Okos_rho",
    "MF-T03": "Arrhenius",
    "MF-T04": "Nusselt_Correlation",
    "MF-T05": "Plank_Freezing",
    "MF-K01": "Michaelis_Menten",
    "MF-K02": "D_Value",
    "MF-K03": "z_Value",
    "MF-K04": "F_Value",
    "MF-K05": "Gompertz_Microbial",
    "MF-M01": "Fick_2nd_Law",
    "MF-M02": "GAB_Isotherm",
    "MF-M03": "Antoine_Equation",
    "MF-M04": "Henderson_Hasselbalch",
    "MF-M05": "Henry_Law_Aroma",
    "MF-M06": "Latent_Heat",
    "MF-R01": "Power_Law",
    "MF-R02": "Herschel_Bulkley",
    "MF-R03": "Casson_Model",
    "MF-R04": "Gordon_Taylor",
    "MF-R05": "WLF_Equation",
    "MF-R06": "Stevens_Power_Law",
    "MF-R07": "Griffith_Fracture",
    "MF-C01": "Stokes_Sedimentation",
    "MF-C02": "HLB_Griffin",
    "MF-C03": "DLVO_Theory",
    "MF-C04": "Laplace_Pressure",
    "MF-C05": "Q10_Rule",
}


def _out(tool_key: str, solve: Callable[[dict], dict]) -> dict:
    return solve(SAMPLE_PARAMS[tool_key])


class TestProvenanceConsistency(unittest.TestCase):

    def test_all_30_solver_entry_points_are_registered(self):
        self.assertEqual(len(ALL_SOLVERS), 30)
        self.assertEqual(set(SAMPLE_PARAMS), {tool_key for tool_key, _ in ALL_SOLVERS})

    def test_all_solvers_emit_provenance_dict(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertIn("provenance", out)
                self.assertIsInstance(out["provenance"], dict)

    def test_all_provenance_have_required_fields(self):
        required = {"tool_id", "tool_canonical_name", "tool_version", "citations", "ckg_node_refs"}
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertTrue(required <= set(out["provenance"].keys()))

    def test_provenance_tool_id_format_valid(self):
        pattern = re.compile(r"^MF-[TKMRC]\d{2}$")
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertTrue(pattern.match(out["provenance"]["tool_id"]))

    def test_provenance_tool_ids_and_canonical_names_expected(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                expected_tool_id = "MF-T02" if tool_key.startswith("MF-T02") else tool_key
                self.assertEqual(out["provenance"]["tool_id"], expected_tool_id)
                self.assertEqual(
                    out["provenance"]["tool_canonical_name"],
                    EXPECTED_CANONICAL_NAMES[tool_key],
                )

    def test_provenance_citations_non_empty_strings(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                citations = out["provenance"]["citations"]
                self.assertGreaterEqual(len(citations), 1)
                self.assertTrue(all(isinstance(c, str) and c for c in citations))

    def test_provenance_ckg_node_refs_format(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                refs = out["provenance"]["ckg_node_refs"]
                self.assertIsInstance(refs, list)
                self.assertGreaterEqual(len(refs), 1)
                for ref in refs:
                    self.assertIn("label", ref)
                    self.assertTrue(ref["label"].startswith("CKG_"))
                    self.assertIn("mf_id", ref)

    def test_ckg_mf_id_lowercase_namespaced(self):
        pattern = re.compile(r"^mf_[tkmrc]\d{2}$")
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                ref = out["provenance"]["ckg_node_refs"][0]
                expected_tool_id = "MF-T02" if tool_key.startswith("MF-T02") else tool_key
                self.assertEqual(ref, {"label": "CKG_MF", "mf_id": expected_tool_id.lower().replace("-", "_")})
                self.assertTrue(pattern.match(ref["mf_id"]))

    def test_provenance_tool_version_is_string(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertIsInstance(out["provenance"]["tool_version"], str)
                self.assertRegex(out["provenance"]["tool_version"], r"^\d+\.\d+")

    def test_provenance_doesnt_break_validity_invariant(self):
        for tool_key, solve in ALL_SOLVERS:
            with self.subTest(tool_key=tool_key):
                out = _out(tool_key, solve)
                self.assertIsInstance(out["validity"]["passed"], bool)
                self.assertIsInstance(out["validity"]["issues"], list)

    def test_provenance_is_fresh_per_call(self):
        for tool_key, solve in ALL_SOLVERS[:5]:
            with self.subTest(tool_key=tool_key):
                out1 = _out(tool_key, solve)
                out1["provenance"]["citations"].append("mutated")
                out1["provenance"]["ckg_node_refs"].append({"label": "CKG_BAD", "mf_id": "mutated"})
                out2 = _out(tool_key, solve)
                self.assertNotIn("mutated", out2["provenance"]["citations"])
                self.assertEqual(out2["provenance"]["ckg_node_refs"][0]["label"], "CKG_MF")


if __name__ == "__main__":
    unittest.main(verbosity=2)
