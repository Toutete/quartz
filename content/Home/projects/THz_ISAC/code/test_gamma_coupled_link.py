"""Regression checks for the coupled communication/antenna-RCS model."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isac_gui as sim


def _link(gamma: float, direct_rcs_dbsm: float | None = None) -> dict[str, float]:
    return sim.calc_isac_link_budget(
        distance_m=1.0,
        rf_ghz=280.0,
        tx_dbm=-10.0,
        tx_gain_dbi=32.0,
        rx_gain_dbi=32.0,
        rcs_sqm=0.01,
        lna_gain_db=13.0,
        c1_drive_gain_db=27.0,
        c2_drive_gain_db=20.0,
        c1_cable_loss_db=10.0,
        c2_cable_loss_db=13.0,
        omt_il_db=2.2,
        target_ant_gain_dbi=32.0,
        target_gamma_mag=gamma,
        target_pol_eff=1.0,
        effective_rcs_dbsm=direct_rcs_dbsm,
    )


class _Var:
    def __init__(self, value=""):
        self.value = str(value)

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)


def _detector_panel() -> sim.SystemModelValidationPanel:
    """Return a third-tab model with an explicit detector-domain reference."""
    panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
    values = {
        "detector_reference_source": "simulation",
        "rho": 0.2,
        "rho_ref": 0.2,
        "comm_req_snr_db": 15.75,
        "sens_req_snr_db": 13.2,
        "sim_comm_ref_snr_db": 19.0,
        "comm_noise_snr_ref_db": 20.5,
        "comm_sir_ref_db": 25.0,
        "comm_detector_ref_range_m": 1.0,
        "comm_detector_ref_tx_dbm": -10.0,
        "comm_detector_ref_rho": 0.2,
        "comm_detector_ref_cspr_db": 13.0,
        "sweep_tx_power_dbm": -10.0,
        "theory_tx_ref_dbm": -10.0,
        "cspr_db": 13.0,
        "si_on_iso_db": 24.0,
        "c2_target_power_ref_dbm": -37.23,
        "c2_cross_power_ref_dbm": -37.43,
        "c2_echo_self_power_ref_dbm": -50.78,
        "c2_noise_power_dbm": -40.0,
        "c2_noise_power_off_dbm": -40.0,
        "detector_ref_range_m": 1.0,
        "detector_ref_tx_dbm": -10.0,
        "detector_ref_iso_db": 24.0,
        "detector_ref_cspr_db": 13.0,
        "detector_ref_rcs_dbsm": -4.28,
        "effective_rcs_dbsm": -4.28,
        "radar_proc_gain_db": 26.0,
        "bandwidth_ghz": 15.0,
        "symbol_rate_gbaud": 15.0,
        "pilot_symbols": 1024,
        "sqrt_k": 1e-4,
        "ac2": 1.0,
        "gc_db": 0.0,
        "system_nf_db": 8.0,
        "noise_temperature_k": 290.0,
    }
    panel.params = {key: _Var(value) for key, value in values.items()}
    panel.meas_points = []
    return panel


class GammaCoupledLinkTest(unittest.TestCase):
    def test_c2_power_slope_fit_used_by_redraw_validation(self):
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        panel.meas_points = []
        panel.params = {
            "manual_c2_si_on_points": _Var("500:-20, 1000:-26.0206, 2000:-32.0412"),
            "c2_meas_power_min_dbm": _Var(""),
        }

        slope, intercept = panel._fit_c2_power_slope("on")

        self.assertTrue(np.isfinite(intercept))
        self.assertAlmostEqual(slope, -20.0, places=4)

    def test_default_sensing_measurement_survives_manual_power_override(self):
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        radar_points = panel._default_radar_measurements()
        self.assertEqual(len(radar_points), 1)
        self.assertTrue(np.isfinite(float(radar_points[0]["snr_sens_db"])))

        panel.meas_points = radar_points
        panel.params = {
            "manual_c2_si_on_points": _Var("1100:-40.6"),
            "c2_meas_power_min_dbm": _Var(""),
        }
        active = panel._active_measurements()
        snr_points = panel._c2_power_radar_snr_points("on")
        power_points = panel._c2_power_points("on")
        self.assertEqual(len(active), 2)
        self.assertEqual(len(snr_points), 1)
        self.assertAlmostEqual(snr_points[0][0], 1.1)
        self.assertAlmostEqual(power_points[0][1], -40.6)

    def test_three_c2_band_power_points_produce_three_anchored_sinr_markers(self):
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        panel.meas_points = [{
            "name": "C2 range-profile anchor",
            "range_m": 1.1,
            "snr_sens_db": 20.5,
            "c2_inband_power_dbm": float("nan"),
            "c2_si_state": "on",
        }]
        panel.params = {
            "manual_c2_si_on_points": _Var("1000:-38.3, 1100:-40.6, 1200:-42.4"),
            "c2_noise_power_dbm": _Var(-46.47),
        }

        points = panel._c2_power_radar_snr_points("on")

        self.assertEqual(len(points), 3)
        self.assertAlmostEqual(points[1][0], 1.1)
        self.assertAlmostEqual(points[1][1], 20.5)
        self.assertGreater(points[0][1], points[1][1])
        self.assertGreater(points[1][1], points[2][1])

    def test_third_tab_separates_raw_c2_power_from_target_sinr_power(self):
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        row = panel._sweep_metric_row(
            {
                "evm_db": -18.0,
                "c2_raw_band_metrics": {"raw_band_power_dbm": -30.0},
                "c2_band_metrics": {
                    "band_power_dbm": -50.0,
                    "noise_power_dbm": -70.0,
                },
                "radar_pre_snr_db_c2": 20.0,
                "snr_rad_post_db_c2": 41.0,
            },
            fixed_noise_dbm=-70.0,
            fixed_pg_db=21.0,
        )

        self.assertAlmostEqual(row["c2_power_dbm"], -30.0)
        self.assertAlmostEqual(row["c2_target_power_dbm"], -50.0)
        self.assertAlmostEqual(row["radar_snr_db"], 41.0)

    def test_no_si_raw_power_flattens_only_at_noise_floor_while_echo_decays(self):
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        panel.meas_points = []
        panel.params = {
            "manual_c2_si_on_points": _Var(""),
            "ref_range_m": _Var(1.0),
            "rho_ref": _Var(0.2),
            "rho": _Var(0.2),
            "c2_no_si_power_ref_dbm": _Var(-60.0),
            "c2_noise_power_dbm": _Var(-70.0),
        }
        ranges = np.asarray([1.0, 2.0, 10.0])

        target = panel._c2_target_power_curve_dbm(ranges, "off")
        raw = panel._c2_power_curve_dbm(ranges, "off")

        self.assertAlmostEqual(float(target[1] - target[0]), -80.0 * np.log10(2.0), places=10)
        self.assertGreater(float(raw[1]), float(target[1]))
        self.assertAlmostEqual(float(raw[-1]), -70.0, places=5)

    def test_link_budget_limits_and_structural_floor(self):
        matched = _link(0.0)
        half = _link(0.5)
        reflected = _link(1.0)

        self.assertAlmostEqual(matched["comm_accepted_fraction"], 1.0)
        self.assertAlmostEqual(half["comm_accepted_fraction"], 0.75)
        self.assertAlmostEqual(reflected["comm_accepted_fraction"], 0.0)
        self.assertAlmostEqual(matched["effective_rcs_sqm"], 0.01)
        self.assertAlmostEqual(
            half["antenna_mode_rcs_sqm"] / reflected["antenna_mode_rcs_sqm"],
            0.25,
        )
        self.assertGreaterEqual(reflected["comm_mismatch_loss_db"], 299.0)

    def test_direct_effective_rcs_is_not_inverted_to_gamma(self):
        matched = _link(0.0, -10.0)
        mismatched = _link(0.5, -10.0)

        self.assertAlmostEqual(matched["effective_rcs_sqm"], mismatched["effective_rcs_sqm"])
        self.assertAlmostEqual(
            mismatched["c1_rf_dbm"] - matched["c1_rf_dbm"],
            10.0 * np.log10(0.75),
        )

    def test_time_domain_comm_power_follows_accepted_fraction(self):
        powers = []
        for gamma in (0.0, 0.5, 1.0):
            cfg = sim.SimConfig(
                fs_gsps=40.0,
                frame_len=512,
                num_frames=2,
                step_ns=5.0,
                baud_gbaud=2.0,
                if_ghz=5.0,
                rf_carrier_ghz=280.0,
                waveform="Tone",
                modulation="QPSK",
                coherence_mode="Self-coherent",
                rx_mode="Mixer",
                additive_noise_enable=False,
                sim_seed=7,
                target_dist_m=0.2,
                target_rcs_sqm=0.01,
                target_ant_gain_dbi=32.0,
                target_gamma_mag=gamma,
                target_pol_eff=1.0,
                target_rcs_mode="coupled_antenna",
                target_effective_rcs_dbsm=None,
            )
            result = sim.run_isac_sim(cfg)
            powers.append(float(np.mean(np.abs(result["v_rec_com"]) ** 2)))

        self.assertGreater(powers[0], 0.0)
        self.assertAlmostEqual(powers[1] / powers[0], 0.75, places=3)
        self.assertLess(powers[2] / powers[0], 1e-20)

    def test_third_tab_effective_rcs_sweep_keeps_comm_gamma_fixed(self):
        panel = _detector_panel()
        rcs_axis = np.linspace(-30.0, 0.0, 31)
        r_comm, r_sens_si, r_sens_no_si, _r_isac = panel._rmax_vs_effective_rcs(
            rcs_axis, 0.2
        )
        self.assertTrue(np.allclose(r_comm, r_comm[0]))
        self.assertTrue(np.all(r_sens_si >= r_sens_no_si))
        self.assertAlmostEqual(
            r_sens_si[-1] / r_sens_si[0],
            10.0 ** (30.0 / 40.0),
            places=7,
        )
        self.assertAlmostEqual(
            r_sens_no_si[-1] / r_sens_no_si[0],
            10.0 ** (30.0 / 40.0),
            places=7,
        )

    def test_effective_processing_gain_controls_sensing_not_communication_range(self):
        panel = _detector_panel()
        panel.params["radar_proc_gain_db"].set(30.1029996)
        rho = np.asarray([0.2])
        comm_ideal, sens_ideal, _ = panel._rmax(rho)
        panel.params["radar_proc_gain_db"].set(26.0)
        comm_eff, sens_eff, _ = panel._rmax(rho)

        self.assertAlmostEqual(float(comm_eff[0] / comm_ideal[0]), 1.0, places=12)
        gain_ratio = 10.0 ** ((26.0 - 30.1029996) / 10.0)
        sensing_gain_ratio = float(sens_eff[0] / sens_ideal[0])
        self.assertGreaterEqual(sensing_gain_ratio, gain_ratio ** 0.25)
        self.assertLessEqual(sensing_gain_ratio, gain_ratio ** 0.125)

        panel.params["radar_proc_gain_db"].set(30.1029996)
        rcs = np.asarray([-10.0])
        rc_i, rs_i, rs_off_i, _ = panel._rmax_vs_effective_rcs(rcs, 0.2)
        panel.params["radar_proc_gain_db"].set(26.0)
        rc_e, rs_e, rs_off_e, _ = panel._rmax_vs_effective_rcs(rcs, 0.2)
        self.assertAlmostEqual(float(rc_e[0] / rc_i[0]), 1.0, places=12)
        rcs_gain_ratio = float(rs_e[0] / rs_i[0])
        self.assertGreaterEqual(rcs_gain_ratio, gain_ratio ** 0.25)
        self.assertLessEqual(rcs_gain_ratio, gain_ratio ** 0.125)
        self.assertAlmostEqual(
            float(rs_off_e[0] / rs_off_i[0]),
            10.0 ** ((26.0 - 30.1029996) / 80.0),
            places=7,
        )

        panel.params["radar_proc_gain_db"].set(26.0)
        # Isolate the data-power law from the separately modelled residual
        # communication-interference ceiling.
        panel.params["comm_sir_ref_db"].set(300.0)
        comm_rho, sens_rho, _ = panel._rmax(np.asarray([0.2, 0.4]))
        off_rho = panel._rmax_sensing_without_si(np.asarray([0.2, 0.4]))
        self.assertAlmostEqual(
            float(comm_rho[1] / comm_rho[0]), (0.6 / 0.8) ** 0.25, places=7
        )
        self.assertGreaterEqual(float(sens_rho[1] / sens_rho[0]), 2.0 ** 0.125)
        self.assertLessEqual(float(sens_rho[1] / sens_rho[0]), 2.0 ** 0.25)
        self.assertAlmostEqual(float(off_rho[1] / off_rho[0]), 2.0 ** 0.125, places=7)

        panel.params["sweep_tx_power_dbm"].set(0.0)
        comm_p0, sens_p0, _ = panel._rmax(rho)
        off_p0 = panel._rmax_sensing_without_si(rho)
        panel.params["sweep_tx_power_dbm"].set(10.0)
        comm_p10, sens_p10, _ = panel._rmax(rho)
        off_p10 = panel._rmax_sensing_without_si(rho)
        self.assertAlmostEqual(float(comm_p10[0] / comm_p0[0]), 10.0 ** 0.5, places=7)
        self.assertGreaterEqual(float(sens_p10[0] / sens_p0[0]), 10.0 ** 0.25)
        self.assertLessEqual(float(sens_p10[0] / sens_p0[0]), 10.0 ** 0.5)
        self.assertAlmostEqual(float(off_p10[0] / off_p0[0]), 10.0 ** 0.25, places=7)

        panel.params["radar_proc_gain_db"].set(40.0)
        self.assertAlmostEqual(
            panel._radar_proc_gain_db(),
            10.0 * np.log10(panel._ideal_processing_gain_lin()),
            places=12,
        )

    def test_sensing_model_adds_cross_and_self_beat_powers(self):
        panel = _detector_panel()
        model = panel._model(np.asarray([1.0, 2.0]))
        sensing = np.asarray(model["snr_sens"], dtype=np.float64)
        cross = np.asarray(model["snr_sens_cross"], dtype=np.float64)
        self_beat = np.asarray(model["snr_sens_self"], dtype=np.float64)
        self.assertTrue(np.allclose(sensing, cross + self_beat))
        self.assertAlmostEqual(float(cross[1] / cross[0]), 1.0 / 16.0, places=12)
        self.assertAlmostEqual(float(self_beat[1] / self_beat[0]), 1.0 / 256.0, places=12)

        cross_mw = 10.0 ** (
            panel._float("c2_cross_power_ref_dbm", -300.0) / 10.0
        )
        self_mw = 10.0 ** (
            panel._float("c2_echo_self_power_ref_dbm", -300.0) / 10.0
        )
        noise_mw = 10.0 ** (
            panel._float("c2_noise_power_dbm", -300.0) / 10.0
        )
        expected = (
            10.0 ** (26.0 / 10.0) * 0.2 * (cross_mw + self_mw) / noise_mw
        )
        self.assertAlmostEqual(float(sensing[0]), expected, places=12)

        with_si = panel._rmax(np.asarray([0.2]))[1]
        without_si = panel._rmax_sensing_without_si(np.asarray([0.2]))
        self.assertGreaterEqual(float(with_si[0]), float(without_si[0]))
        at_limit = panel._model(np.asarray([with_si[0]]), rho=0.2)["snr_sens"]
        self.assertAlmostEqual(float(at_limit[0]), 10.0 ** (13.2 / 10.0), places=9)

        panel.params["theory_tx_ref_dbm"] = _Var(-10.0)
        panel.params["sweep_tx_power_dbm"] = _Var(-10.0)
        for tx_dbm in (-30.0, -20.0, -10.0, 0.0, 10.0):
            panel.params["sweep_tx_power_dbm"].set(tx_dbm)
            with_si = panel._rmax(np.asarray([0.2]))[1]
            without_si = panel._rmax_sensing_without_si(np.asarray([0.2]))
            self.assertGreaterEqual(float(with_si[0]), float(without_si[0]))


if __name__ == "__main__":
    unittest.main()
