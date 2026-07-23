import unittest
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isac_gui import SimConfig, SystemModelValidationPanel, calc_isac_link_budget


class _Var:
    def __init__(self, value):
        self.value = str(value)

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)


def _validation_model():
    model = object.__new__(SystemModelValidationPanel)
    values = {
        "detector_reference_source": "simulation",
        "rho": 0.20,
        "rho_ref": 0.20,
        "comm_req_snr_db": 15.75,
        "sens_req_snr_db": 13.2,
        "sim_comm_ref_snr_db": 19.0,
        "comm_ref_snr_db": 19.0,
        "comm_noise_snr_ref_db": 20.5,
        "comm_sir_ref_db": 25.0,
        "comm_detector_ref_range_m": 1.0,
        "comm_detector_ref_tx_dbm": -10.0,
        "comm_detector_ref_rho": 0.20,
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
        "si_sweep_min_dbm": -70.0,
        "si_sweep_max_dbm": -15.0,
        "si_sweep_points": 301,
        "si_ssbi_leakage_db": 0.0,
        "lna_ip1db_dbm": -20.0,
        "si_sinr_ylim_min": -10.0,
        "si_sinr_ylim_max": 50.0,
    }
    model.params = {key: _Var(value) for key, value in values.items()}
    model.meas_points = []
    return model


class SystemModelValidationMathTest(unittest.TestCase):
    @staticmethod
    def _packaged_reference_cfg():
        return SimConfig(
            fs_gsps=120.0,
            baud_gbaud=15.0,
            if_ghz=11.0,
            rf_carrier_ghz=280.0,
            waveform="DFT-s-OFDM",
            modulation="16QAM",
            rx_mode="ZBD",
            coherence_mode="Free-running",
            optical_sideband_mode="DSB",
            carrier_wander_enable=True,
            carrier_wander_mhz=10.0,
            awg_rf_power_dbm=-6.0,
            mzm_drive_gain_db=8.0,
            mzm_vpi_v=3.0,
            mzm_phi_bias_deg=45.0,
            mzm_eo_bw_ghz=30.0,
            awg_dac_bits=8.0,
            utcpd_photocurrent_ma=7.0,
            utcpd_target_dbm=-10.0,
            utcpd_responsivity_a_per_w=0.24,
            cspr_db=13.0,
            lna_gain_db=13.0,
            lna_nf_db=8.0,
            zbd_responsivity_vpw=1500.0,
            zbd_nep_pw_sqrt_hz=5.0,
            c1_drive_gain_db=27.0,
            c2_drive_gain_db=22.0,
            c1_cable_loss_db=10.0,
            c2_cable_loss_db=13.0,
            if_amp_nf_db=5.0,
            dso_vscale_mv=100.0,
            dso_bandwidth_ghz=40.0,
            omt_iso_db=24.0,
            omt_il_db=2.2,
            tx_ant_gain_dbi=32.0,
            rx_ant_gain_dbi=32.0,
            target_rcs_mode="direct_effective",
            target_effective_rcs_dbsm=-4.28,
            target_dist_m=1.0,
            syms_per_chirp=1024,
            pilot_rho=0.2,
            rrc_beta=0.2,
            sc_fde_enable=True,
            sc_fde_taps=1,
            sim_seed=0,
        )

    def test_packaged_reference_requires_matching_config(self):
        model = _validation_model()
        model.status_var = _Var("")
        cfg = self._packaged_reference_cfg()
        self.assertTrue(model._load_packaged_detector_reference(cfg))
        self.assertEqual(model.params["detector_reference_source"].get(), "simulation")
        cfg.cspr_db = 12.0
        self.assertFalse(model._load_packaged_detector_reference(cfg))

    @staticmethod
    def _link(distance_m, omt_il_db=2.2):
        return calc_isac_link_budget(
            distance_m=distance_m,
            rf_ghz=280.0,
            tx_dbm=-10.0,
            tx_gain_dbi=32.0,
            rx_gain_dbi=32.0,
            rcs_sqm=0.01,
            lna_gain_db=13.0,
            c1_drive_gain_db=27.0,
            c2_drive_gain_db=22.0,
            c1_cable_loss_db=10.0,
            c2_cable_loss_db=13.0,
            omt_il_db=omt_il_db,
            target_ant_gain_dbi=32.0,
            target_gamma_mag=0.0,
            target_pol_eff=1.0,
            effective_rcs_dbsm=-4.28,
        )

    def test_link_budget_obeys_one_way_and_monostatic_range_laws(self):
        one_m = self._link(1.0)
        two_m = self._link(2.0)
        self.assertAlmostEqual(
            two_m["c1_rf_dbm"] - one_m["c1_rf_dbm"],
            -20.0 * np.log10(2.0),
            places=10,
        )
        self.assertAlmostEqual(
            two_m["c2_rf_dbm"] - one_m["c2_rf_dbm"],
            -40.0 * np.log10(2.0),
            places=10,
        )

    def test_omt_loss_is_applied_once_per_pass(self):
        base = self._link(1.0, omt_il_db=2.2)
        extra = self._link(1.0, omt_il_db=3.2)
        self.assertAlmostEqual(extra["c1_rf_dbm"] - base["c1_rf_dbm"], -2.0)
        self.assertAlmostEqual(extra["c2_rf_dbm"] - base["c2_rf_dbm"], -2.0)

    def test_detection_threshold_matches_pd_pfa(self):
        model = _validation_model()
        self.assertAlmostEqual(model._sens_threshold_db(), 13.18349, places=4)

    def test_with_si_range_is_not_below_without_si_for_equal_noise(self):
        model = _validation_model()
        rho = np.linspace(0.01, 0.99, 99)
        _comm, sensing_on, _joint = model._rmax(rho)
        sensing_off = model._rmax_sensing_without_si(rho)
        self.assertTrue(np.all(np.isfinite(sensing_on)))
        self.assertTrue(np.all(sensing_on >= sensing_off))

    def test_rcs_scaling_is_sigma_to_one_quarter(self):
        model = _validation_model()
        curves = model._rmax_vs_effective_rcs(np.asarray([-4.28, 5.72]), 0.20)
        expected = 10.0 ** (10.0 / 40.0)
        self.assertAlmostEqual(curves[1][1] / curves[1][0], expected, places=10)
        self.assertAlmostEqual(curves[2][1] / curves[2][0], expected, places=10)

    def test_si_off_uses_its_own_detector_output_noise(self):
        model = _validation_model()
        equal_noise = model._rmax_sensing_without_si(np.asarray([0.20]))[0]
        model.params["c2_noise_power_off_dbm"] = _Var(-50.0)
        lower_off_noise = model._rmax_sensing_without_si(np.asarray([0.20]))[0]
        # Echo self-beat SINR follows R^-8, hence a 10-dB noise reduction
        # extends range by 10^(10/80).
        self.assertAlmostEqual(
            lower_off_noise / equal_noise, 10.0 ** (10.0 / 80.0), places=10
        )

    def test_ten_db_tx_increase_has_square_law_scaling(self):
        model = _validation_model()
        # Remove the finite residual-interference ceiling to isolate the
        # fixed-noise square-law transmit-power scaling.
        model.params["comm_sir_ref_db"] = _Var(300.0)
        base = model._rmax_vs_effective_rcs(np.asarray([-4.28]), 0.20)
        model.params["sweep_tx_power_dbm"] = _Var(0.0)
        boosted = model._rmax_vs_effective_rcs(np.asarray([-4.28]), 0.20)
        self.assertAlmostEqual(boosted[0][0] / base[0][0], 100.0 ** 0.25, places=10)
        self.assertGreaterEqual(boosted[1][0], base[1][0])

    def test_reference_sinr_uses_inverse_snr_plus_inverse_sir(self):
        model = _validation_model()
        result = model._comm_sinr_from_reference(1.0, 0.20)
        snr = 10.0 ** (20.5 / 10.0)
        sir = 10.0 ** (25.0 / 10.0)
        expected = 1.0 / (1.0 / snr + 1.0 / sir)
        self.assertAlmostEqual(float(result), expected, places=10)

    def test_uninitialized_reference_is_not_silently_used(self):
        model = _validation_model()
        model.params["detector_reference_source"] = _Var("")
        comm, sensing, joint = model._rmax(np.asarray([0.20]))
        self.assertTrue(np.isnan(comm[0]))
        self.assertTrue(np.isnan(sensing[0]))
        self.assertTrue(np.isnan(joint[0]))

    def test_measured_c2_power_produces_all_relative_sensing_markers(self):
        model = _validation_model()
        model.params["manual_c2_si_on_points"] = _Var(
            "1000:-38.3, 1100:-40.6, 1200:-42.4"
        )
        model.meas_points = [
            {
                "range_m": 1.1,
                "snr_sens_db": 20.0,
                "c2_si_state": "on",
            }
        ]
        points = model._c2_power_radar_snr_points("on")
        self.assertEqual([round(point[0], 3) for point in points], [1.0, 1.1, 1.2])
        self.assertAlmostEqual(points[0][1], 22.3)
        self.assertAlmostEqual(points[1][1], 20.0)
        self.assertAlmostEqual(points[2][1], 18.2)

    def test_si_power_sweep_has_expected_asymptotic_slopes(self):
        model = _validation_model()
        curves = model._si_power_sweep_curves()
        x = np.asarray(curves["si_power_dbm"], dtype=np.float64)
        thermal = np.asarray(curves["thermal_asymptote_db"], dtype=np.float64)
        beating = np.asarray(curves["si_noise_asymptote_db"], dtype=np.float64)
        ssbi = np.asarray(curves["ssbi_asymptote_db"], dtype=np.float64)
        lo = int(np.argmin(np.abs(x + 60.0)))
        hi = int(np.argmin(np.abs(x + 40.0)))
        delta_x = x[hi] - x[lo]
        self.assertAlmostEqual(thermal[hi] - thermal[lo], delta_x, places=10)
        self.assertAlmostEqual(beating[hi] - beating[lo], 0.0, places=10)
        self.assertAlmostEqual(ssbi[hi] - ssbi[lo], -delta_x, places=10)

    def test_si_operating_point_and_compression_use_lna_input_plane(self):
        model = _validation_model()
        curves = model._si_power_sweep_curves()
        # ac2=1 mW and 24-dB isolation gives -24 dBm carrier SI.
        self.assertAlmostEqual(float(curves["current_si_dbm"]), -24.0, places=10)
        # Sideband, echo, and noise consume some headroom, so the carrier-only
        # SI boundary must lie below the total-input -20-dBm P1dB.
        self.assertLess(float(curves["compression_si_dbm"]), -20.0)


if __name__ == "__main__":
    unittest.main()
