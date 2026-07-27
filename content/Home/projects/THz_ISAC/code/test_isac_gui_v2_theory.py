"""Regression tests for the closed-form figures in isac_gui_v2.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure


sys.path.insert(0, str(Path(__file__).resolve().parent))
from isac_gui_v2 import (
    SystemModelValidationPanel,
    generate_bandlimited_noise,
)


class _Var:
    def __init__(self, value):
        self.value = str(value)

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)


def _theory_model() -> SystemModelValidationPanel:
    model = object.__new__(SystemModelValidationPanel)
    model.photonic_source = None
    values = {
        "rho": 0.20,
        "bandwidth_ghz": 20.0,
        "pilot_symbols": 1024,
        "symbol_rate_gbaud": 20.0,
        "sweep_tx_power_dbm": -10.0,
        "si_on_iso_db": 25.0,
        "cspr_db": 13.0,
        "effective_rcs_dbsm": -8.0,
        "system_nf_db": 8.0,
        "noise_temperature_k": 290.0,
        "theory_lna_nep": "13.0, 5.0",
        "theory_rf_carrier_ghz": 280.0,
        "theory_tx_gain_dbi": 33.0,
        "theory_rx_gain_dbi": 33.0,
        "theory_noise_noise_overlap": 1.0,
        "theory_post_detector_floor_dbmw2": -300.0,
        "theory_ssbi_fraction": 0.069,
        "required_sinr_db": "15.75, 13.2",
        "si_sweep_limits_dbm": "-60, -20",
        "si_sweep_points": 201,
        "ref_range_m": 1.1,
        "lna_ip1db_dbm": -20.0,
        "radar_proc_gain_db": 30.1029995664,
    }
    model.params = {key: _Var(value) for key, value in values.items()}
    return model


class ClosedFormTheoryTests(unittest.TestCase):
    def test_distance_comm_curve_uses_first_tab_equalizer_evm(self):
        sweep_evm_sinr = np.asarray([21.0, 17.5, 12.25])
        result = SystemModelValidationPanel._comm_sinr_from_distance_sweep(
            {"on_comm_snr_db": sweep_evm_sinr}
        )

        np.testing.assert_array_equal(result, sweep_evm_sinr)
        self.assertIsNot(result, sweep_evm_sinr)

    def test_bandlimited_noise_preserves_integrated_rms(self):
        np.random.seed(7)
        n = 8192
        frequency = np.fft.fftfreq(n, d=1.0 / 100.0)
        mask = np.abs(frequency) <= 10.0
        target_rms = 0.037

        noise = generate_bandlimited_noise(mask, target_rms)
        spectrum = np.fft.fft(noise)

        self.assertAlmostEqual(
            float(np.sqrt(np.mean(noise ** 2))), target_rms, places=14
        )
        self.assertLess(
            float(np.max(np.abs(spectrum[~mask]))),
            1e-10,
        )

    def test_band_power_points_are_independent_and_have_own_offset(self):
        model = object.__new__(SystemModelValidationPanel)
        model.params = {
            "manual_c2_si_on_points": _Var("1000:-38, 1200:-42"),
            "bandpower_est_offset_db": _Var(1.5),
        }
        model.meas_points = []
        model.runtime = {}
        model._c2_power_curve_dbm = lambda ranges, _state: np.full_like(
            np.asarray(ranges, dtype=np.float64), -40.0
        )
        model._model = lambda ranges: {
            "snr_sens": np.full_like(
                np.asarray(ranges, dtype=np.float64), 100.0
            )
        }

        before = model._c2_power_radar_snr_points("on")
        model.params["manual_c2_si_on_points"].set(
            "1000:-30, 1200:-42"
        )
        after = model._c2_power_radar_snr_points("on")

        self.assertAlmostEqual(before[0][1], 23.5)
        self.assertAlmostEqual(before[1][1], 19.5)
        self.assertAlmostEqual(after[0][1], 31.5)
        self.assertAlmostEqual(after[1][1], before[1][1])

    def test_si_figure_has_no_shading_linear_guide_or_operating_point(self):
        model = _theory_model()
        fig = Figure(figsize=(5.0, 4.0))
        ax = fig.add_subplot(111)

        model._draw_si_power_axis(ax, for_save=True)

        self.assertEqual(len(ax.patches), 0)
        self.assertNotIn("#008000", [line.get_color() for line in ax.lines])
        self.assertFalse(any(line.get_marker() == "o" for line in ax.lines))

    def test_rho_tradeoff_ranges_satisfy_the_closed_form_thresholds(self):
        model = _theory_model()
        rcs = np.asarray([-8.0])
        low_rho = model._rmax_vs_effective_rcs(rcs, 0.20)
        high_rho = model._rmax_vs_effective_rcs(rcs, 0.80)
        context = model._closed_form_theory_context()
        comm_threshold = 10.0 ** (15.75 / 10.0)
        sensing_threshold = 10.0 ** (13.2 / 10.0)
        sigma = 10.0 ** (-8.0 / 10.0)

        for rho, curves in ((0.20, low_rho), (0.80, high_rho)):
            r_comm = float(curves[0][0])
            p_rx = context["comm_rx_r2_coefficient_mw_m2"] / r_comm ** 2
            comm_sinr = (
                context["m2"] * (1.0 - rho) * p_rx ** 2
                / (
                    context["detector_noise_floor_mw2"]
                    + 2.0 * p_rx * context["rf_noise_mw"]
                    + context["detector_ssbi_coefficient"] * p_rx ** 2
                )
            )
            self.assertAlmostEqual(comm_sinr, comm_threshold, places=10)

            r_sens = float(curves[1][0])
            p_echo = (
                context["echo_per_pt_unit_rcs"]
                * context["pt_mw"]
                * sigma
                / r_sens ** 4
            )
            sensing_sinr = (
                rho
                * context["gp"]
                * 2.0
                * context["m2"]
                * (context["si_mw"] * p_echo + p_echo ** 2)
                / (
                    context["detector_noise_floor_mw2"]
                    + 2.0
                    * (context["si_mw"] + p_echo)
                    * context["rf_noise_mw"]
                    + context["detector_ssbi_coefficient"]
                    * context["si_mw"] ** 2
                )
            )
            self.assertAlmostEqual(sensing_sinr, sensing_threshold, places=10)

        self.assertLess(float(high_rho[0][0]), float(low_rho[0][0]))
        self.assertGreater(float(high_rho[1][0]), float(low_rho[1][0]))

    def test_detector_coefficients_are_dimensionally_consistent(self):
        model = _theory_model()
        coefficients = model._closed_form_detector_noise_coefficients()
        m2 = 10.0 ** (-13.0 / 10.0)

        expected_noise = (
            1.380649e-23 * 290.0 * 10.0 ** 0.8 * 20.0e9 * 1e3
        )
        expected_nep = (5.0e-9) ** 2 * 20.0e9 / (10.0 ** 1.3) ** 2
        expected_floor = expected_noise ** 2 + expected_nep + 1e-30

        self.assertAlmostEqual(float(coefficients["rf_noise_mw"]), expected_noise)
        self.assertAlmostEqual(
            float(coefficients["noise_noise_mw2"]), expected_noise ** 2
        )
        self.assertAlmostEqual(
            float(coefficients["zbd_nep_noise_mw2"]), expected_nep
        )
        self.assertAlmostEqual(
            float(coefficients["noise_floor_mw2"]), expected_floor
        )
        self.assertAlmostEqual(
            float(coefficients["si_noise_coefficient_mw"]),
            2.0 * expected_noise,
            places=18,
        )
        self.assertAlmostEqual(
            float(coefficients["ssbi_coefficient"]),
            0.069 * m2 ** 2,
            places=18,
        )
        self.assertGreater(
            float(coefficients["zbd_nep_noise_mw2"]),
            float(coefficients["noise_noise_mw2"]),
        )

    def test_si_sweep_has_floor_gain_plateau_and_ssbi_rolloff(self):
        model = _theory_model()
        curves = model._si_power_sweep_curves()
        x = np.asarray(curves["si_power_dbm"], dtype=np.float64)
        y = np.asarray(curves["with_si_db"], dtype=np.float64)
        slope = np.gradient(y, x)

        def nearest(values: np.ndarray, target: float) -> float:
            return float(values[int(np.argmin(np.abs(x - target)))])

        self.assertLess(abs(nearest(slope, -60.0)), 0.15)
        self.assertGreater(nearest(slope, -40.0), 0.65)
        self.assertGreater(nearest(slope, -35.0), 0.55)
        self.assertLess(nearest(slope, -20.0), -0.50)
        self.assertAlmostEqual(float(curves["current_si_dbm"]), -35.0)
        self.assertGreater(float(curves["current_sinr_db"]), 13.2)
        self.assertLess(
            float(curves["linear_region_min_dbm"]),
            float(curves["linear_region_max_dbm"]),
        )

    def test_symbol_rate_scales_integrated_rf_noise(self):
        model = _theory_model()
        reference = model._closed_form_detector_noise_coefficients()
        model.params["symbol_rate_gbaud"].set(10.0)
        half_rate = model._closed_form_detector_noise_coefficients()

        self.assertAlmostEqual(
            float(half_rate["rf_noise_mw"])
            / float(reference["rf_noise_mw"]),
            0.5,
            places=12,
        )
        self.assertAlmostEqual(
            float(half_rate["noise_noise_mw2"])
            / float(reference["noise_noise_mw2"]),
            0.25,
            places=12,
        )
        self.assertAlmostEqual(
            float(half_rate["zbd_nep_noise_mw2"])
            / float(reference["zbd_nep_noise_mw2"]),
            0.5,
            places=12,
        )
        self.assertAlmostEqual(
            float(half_rate["ssbi_coefficient"]),
            float(reference["ssbi_coefficient"]),
            places=18,
        )

    def test_entered_processing_gain_changes_only_sensing_ranges(self):
        model = _theory_model()
        rcs = np.asarray([-8.0])
        ideal = model._rmax_vs_effective_rcs(rcs, 0.20)
        ideal_gain_db = model._radar_proc_gain_db()
        model.params["radar_proc_gain_db"].set(26.0)
        practical = model._rmax_vs_effective_rcs(rcs, 0.20)
        gain_ratio = 10.0 ** ((26.0 - ideal_gain_db) / 10.0)

        self.assertAlmostEqual(float(practical[0][0] / ideal[0][0]), 1.0)
        self.assertGreater(
            float(practical[1][0] / ideal[1][0]),
            gain_ratio ** 0.25,
        )
        self.assertLess(
            float(practical[1][0] / ideal[1][0]),
            gain_ratio ** 0.125,
        )
        off_ratio = float(practical[2][0] / ideal[2][0])
        # Echo--noise beating makes the no-SI exponent slightly steeper than
        # the fixed-floor-only eighth-root limit.
        self.assertGreater(off_ratio, gain_ratio ** 0.25)
        self.assertLess(off_ratio, gain_ratio ** 0.125)

    def test_both_sensing_ranges_scale_as_rcs_fourth_root(self):
        model = _theory_model()
        low = model._rmax_vs_effective_rcs(np.asarray([-20.0]), 0.20)
        high = model._rmax_vs_effective_rcs(np.asarray([-10.0]), 0.20)
        expected = 10.0 ** (0.25)

        self.assertAlmostEqual(float(high[2][0] / low[2][0]), expected)
        # The exact with-SI equation has the same sigma^(1/4) scaling because
        # its coefficients scale as C4~sigma and C8~sigma^2.
        self.assertAlmostEqual(float(high[1][0] / low[1][0]), expected)

    def test_ssbi_coefficient_tracks_the_fourth_power_modulation_law(self):
        model = _theory_model()
        reference = model._closed_form_theory_context()
        model.params["cspr_db"].set(10.0)
        stronger_modulation = model._closed_form_theory_context()
        m2_ratio = 10.0 ** ((13.0 - 10.0) / 10.0)

        self.assertAlmostEqual(
            float(
                stronger_modulation["detector_ssbi_coefficient"]
                / reference["detector_ssbi_coefficient"]
            ),
            m2_ratio ** 2,
            places=12,
        )
        self.assertAlmostEqual(
            float(
                stronger_modulation["detector_ssbi_transition_dbm"]
                - reference["detector_ssbi_transition_dbm"]
            ),
            -3.0,
            places=12,
        )


if __name__ == "__main__":
    unittest.main()
