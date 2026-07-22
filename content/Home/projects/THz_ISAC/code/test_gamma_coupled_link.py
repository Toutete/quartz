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


class GammaCoupledLinkTest(unittest.TestCase):
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

    def test_third_tab_theory_uses_same_gamma(self):
        keys = (
            "bandwidth_ghz", "symbol_rate_gbaud", "pilot_symbols", "system_nf_db",
            "cspr_db", "theory_tx_ref_dbm", "effective_rcs_dbsm", "target_gamma_mag",
            "comm_accepted_fraction", "target_rcs_sqm", "target_ant_gain_dbi",
            "target_rcs_mode", "ac2", "ref_range_m", "sqrt_k", "gc_db",
            "sweep_tx_power_dbm", "si_on_iso_db", "rho_ref", "comm_req_snr_db",
            "sens_req_snr_db", "radar_proc_gain_db",
        )
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        panel.params = {key: _Var() for key in keys}
        panel.params.update({
            "ref_range_m": _Var(1.0),
            "sweep_tx_power_dbm": _Var(-10.0),
            "si_on_iso_db": _Var(24.0),
            "rho_ref": _Var(0.2),
            "comm_req_snr_db": _Var(15.75),
            "sens_req_snr_db": _Var(13.2),
        })

        ranges = []
        for gamma in (0.0, 0.5):
            cfg = sim.SimConfig(
                rf_carrier_ghz=280.0,
                utcpd_target_dbm=-10.0,
                tx_ant_gain_dbi=32.0,
                rx_ant_gain_dbi=32.0,
                omt_il_db=2.2,
                target_dist_m=1.0,
                target_rcs_sqm=0.01,
                target_ant_gain_dbi=32.0,
                target_gamma_mag=gamma,
                target_pol_eff=1.0,
                target_rcs_mode="coupled_antenna",
                target_effective_rcs_dbsm=None,
                baud_gbaud=15.0,
                syms_per_chirp=1024,
                cspr_db=13.0,
            )
            panel._sync_theory_params_from_cfg(cfg)
            r_comm, r_sens, _ = panel._rmax(np.asarray([0.2]))
            ranges.append((float(r_comm[0]), float(r_sens[0])))

        self.assertAlmostEqual(ranges[1][0] / ranges[0][0], np.sqrt(0.75), places=7)
        self.assertGreater(ranges[1][1], ranges[0][1])

        rcs_axis = np.linspace(-30.0, 0.0, 31)
        r_comm, r_sens_si, r_sens_no_si, _r_isac = panel._rmax_vs_effective_rcs(
            rcs_axis, 0.2
        )
        self.assertTrue(np.allclose(r_comm, r_comm[0]))
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
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        panel.params = {
            "bandwidth_ghz": _Var(15.0),
            "symbol_rate_gbaud": _Var(15.0),
            "pilot_symbols": _Var(1024),
            "radar_proc_gain_db": _Var(30.1029996),
            "system_nf_db": _Var(8.0),
            "cspr_db": _Var(13.0),
            "theory_tx_ref_dbm": _Var(-10.0),
            "sweep_tx_power_dbm": _Var(0.0),
            "si_on_iso_db": _Var(24.0),
            "ac2": _Var(1.0),
            "sqrt_k": _Var(1e-4),
            "gc_db": _Var(0.0),
            "comm_req_snr_db": _Var(15.75),
            "sens_req_snr_db": _Var(13.2),
        }
        rho = np.asarray([0.2])
        comm_ideal, sens_ideal, _ = panel._rmax(rho)
        panel.params["radar_proc_gain_db"].set(21.9)
        comm_eff, sens_eff, _ = panel._rmax(rho)

        self.assertAlmostEqual(float(comm_eff[0] / comm_ideal[0]), 1.0, places=12)
        self.assertAlmostEqual(
            float(sens_eff[0] / sens_ideal[0]),
            10.0 ** ((21.9 - 30.1029996) / 40.0),
            places=7,
        )

        panel.params["radar_proc_gain_db"].set(30.1029996)
        rcs = np.asarray([-10.0])
        rc_i, rs_i, rs_off_i, _ = panel._rmax_vs_effective_rcs(rcs, 0.2)
        panel.params["radar_proc_gain_db"].set(21.9)
        rc_e, rs_e, rs_off_e, _ = panel._rmax_vs_effective_rcs(rcs, 0.2)
        self.assertAlmostEqual(float(rc_e[0] / rc_i[0]), 1.0, places=12)
        self.assertAlmostEqual(
            float(rs_e[0] / rs_i[0]),
            10.0 ** ((21.9 - 30.1029996) / 40.0),
            places=7,
        )
        self.assertAlmostEqual(
            float(rs_off_e[0] / rs_off_i[0]),
            10.0 ** ((21.9 - 30.1029996) / 80.0),
            places=7,
        )

        panel.params["radar_proc_gain_db"].set(21.9)
        comm_rho, sens_rho, _ = panel._rmax(np.asarray([0.2, 0.4]))
        off_rho = panel._rmax_sensing_without_si(np.asarray([0.2, 0.4]))
        self.assertAlmostEqual(float(comm_rho[1] / comm_rho[0]), np.sqrt(0.6 / 0.8), places=7)
        self.assertAlmostEqual(float(sens_rho[1] / sens_rho[0]), 2.0 ** 0.25, places=7)
        self.assertAlmostEqual(float(off_rho[1] / off_rho[0]), 2.0 ** 0.125, places=7)

        panel.params["sweep_tx_power_dbm"].set(0.0)
        comm_p0, sens_p0, _ = panel._rmax(rho)
        off_p0 = panel._rmax_sensing_without_si(rho)
        panel.params["sweep_tx_power_dbm"].set(10.0)
        comm_p10, sens_p10, _ = panel._rmax(rho)
        off_p10 = panel._rmax_sensing_without_si(rho)
        self.assertAlmostEqual(float(comm_p10[0] / comm_p0[0]), 10.0 ** 0.5, places=7)
        self.assertAlmostEqual(float(sens_p10[0] / sens_p0[0]), 10.0 ** 0.5, places=7)
        self.assertAlmostEqual(float(off_p10[0] / off_p0[0]), 10.0 ** 0.25, places=7)

    def test_sensing_model_uses_power_product_and_r_minus_four(self):
        panel = sim.SystemModelValidationPanel.__new__(sim.SystemModelValidationPanel)
        panel.params = {
            "rho": _Var(0.2),
            "cspr_db": _Var(13.0),
            "si_on_iso_db": _Var(24.0),
            "ac2": _Var(0.1),
            "sqrt_k": _Var(2e-4),
            "radar_proc_gain_db": _Var(21.9),
            "gc_db": _Var(-80.0),
            "system_nf_db": _Var(8.0),
            "bandwidth_ghz": _Var(15.0),
            "noise_temperature_k": _Var(290.0),
        }
        model = panel._model(np.asarray([1.0, 2.0]))
        sensing = np.asarray(model["snr_sens"], dtype=np.float64)
        self.assertAlmostEqual(float(sensing[1] / sensing[0]), 1.0 / 16.0, places=12)

        ac2 = 0.1
        alpha = 10.0 ** (-24.0 / 20.0)
        p_si = ac2 * alpha ** 2
        p_echo = ac2 * (2e-4) ** 2
        expected = (
            10.0 ** (21.9 / 10.0)
            * 2.0
            * 0.2
            * p_si
            * p_echo
            / (10.0 ** (13.0 / 10.0) * panel._noise_power_mw())
        )
        self.assertAlmostEqual(float(sensing[0]), expected, places=12)


if __name__ == "__main__":
    unittest.main()
