import unittest
import sys
import json
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isac_gui import (
    DEFAULT_ISAC_SIM_PRESET,
    SimConfig,
    SystemModelValidationPanel,
    calc_isac_link_budget,
)


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
        "detector_ref_rcs_dbsm": -6.0,
        "effective_rcs_dbsm": -6.0,
        "radar_proc_gain_db": 26.0,
        "bandwidth_ghz": 15.0,
        "symbol_rate_gbaud": 15.0,
        "pilot_symbols": 1024,
        "sqrt_k": 1e-4,
        # -10-dBm total THz power with 13-dB DSB CSPR leaves this carrier
        # component at the detector-reference configuration.
        "ac2": 0.0952273278966,
        "gc_db": 0.0,
        "system_nf_db": 8.0,
        "noise_temperature_k": 290.0,
        "si_sweep_min_dbm": -70.0,
        "si_sweep_max_dbm": -15.0,
        "si_sweep_points": 301,
        "lna_ip1db_dbm": -20.0,
        "si_sinr_ylim_min": -10.0,
        "si_sinr_ylim_max": 50.0,
        "photocurrent_target_range_m": 1.014,
    }
    model.params = {key: _Var(value) for key, value in values.items()}
    model.meas_points = []
    return model


class SystemModelValidationMathTest(unittest.TestCase):
    def test_requested_simulation_preset_is_packaged_as_the_default(self):
        self.assertEqual(
            DEFAULT_ISAC_SIM_PRESET.name,
            "isac_sim_params_20260724_015432.json",
        )
        if not DEFAULT_ISAC_SIM_PRESET.exists():
            self.skipTest("legacy default preset was intentionally removed")
        preset = json.loads(DEFAULT_ISAC_SIM_PRESET.read_text(encoding="utf-8"))
        self.assertEqual(preset["params"]["effective_rcs_dbsm"], "-8")
        self.assertEqual(preset["awg"]["modulation_var"], "32QAM")
        self.assertEqual(preset["awg"]["pilot_rho_var"], "0.20")

    def test_default_simulation_uses_measured_direct_effective_rcs(self):
        cfg = SimConfig()
        self.assertEqual(cfg.target_rcs_mode, "direct_effective")
        self.assertAlmostEqual(float(cfg.target_effective_rcs_dbsm), -6.0)

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
            target_effective_rcs_dbsm=-6.0,
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
            effective_rcs_dbsm=-6.0,
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

    def test_si_power_sweep_component_scaling_uses_one_reference_plane(self):
        model = _validation_model()
        curves = model._si_power_sweep_curves()
        x = np.asarray(curves["si_power_dbm"], dtype=np.float64)
        cross = np.asarray(curves["cross_sinr_db"], dtype=np.float64)
        echo_self = np.asarray(curves["self_sinr_db"], dtype=np.float64)
        lo = int(np.argmin(np.abs(x + 60.0)))
        hi = int(np.argmin(np.abs(x + 40.0)))
        delta_x = x[hi] - x[lo]
        # With equal SI-on/off detector noise in this fixture, cross-beat
        # power is linear in P_SI and echo self-beat is SI independent.
        self.assertAlmostEqual(cross[hi] - cross[lo], delta_x, places=10)
        self.assertAlmostEqual(echo_self[hi] - echo_self[lo], 0.0, places=10)

    def test_si_sweep_operating_point_matches_rcs_detector_model(self):
        model = _validation_model()
        model.status_var = _Var("")
        self.assertTrue(
            model._load_packaged_detector_reference(self._packaged_reference_cfg())
        )
        curves = model._si_power_sweep_curves()
        c4, c8 = model._detector_domain_sensing_coefficients(0.20, -6.0)
        expected_db = 10.0 * np.log10(float(c4) + float(c8))
        self.assertAlmostEqual(
            float(curves["current_sinr_db"]), expected_db, places=3
        )
        self.assertGreater(
            float(curves["current_sinr_db"]),
            model._float("sens_req_snr_db", 13.2),
        )
        # The calibrated point must remain above the measured-system
        # detection requirement beyond 1 m.
        at_1p1_db = 10.0 * np.log10(
            float(c4) / 1.1 ** 4 + float(c8) / 1.1 ** 8
        )
        self.assertGreater(at_1p1_db, model._float("sens_req_snr_db", 13.2))

    def test_packaged_reference_can_supply_pre_sweep_redraw_anchor(self):
        model = _validation_model()
        model.status_var = _Var("")
        cfg = self._packaged_reference_cfg()
        cfg.c2_cable_loss_db = 22.0
        self.assertFalse(model._load_packaged_detector_reference(cfg))
        self.assertTrue(
            model._load_packaged_detector_reference(
                cfg, require_config_match=False
            )
        )
        curves = model._si_power_sweep_curves()
        self.assertTrue(np.all(np.isfinite(curves["full_sinr_db"])))

    def test_si_sweep_and_rcs_model_stay_consistent_when_parameters_change(self):
        model = _validation_model()
        model.status_var = _Var("")
        self.assertTrue(
            model._load_packaged_detector_reference(self._packaged_reference_cfg())
        )
        cases = [
            (-20.0, 24.0, -20.0, 0.02),
            (-10.0, 30.0, -4.28, 0.20),
            (0.0, 20.0, 0.0, 0.40),
        ]
        for tx_dbm, iso_db, rcs_dbsm, rho in cases:
            model.params["sweep_tx_power_dbm"] = _Var(tx_dbm)
            model.params["si_on_iso_db"] = _Var(iso_db)
            model.params["effective_rcs_dbsm"] = _Var(rcs_dbsm)
            model.params["rho"] = _Var(rho)
            curves = model._si_power_sweep_curves()
            c4, c8 = model._detector_domain_sensing_coefficients(rho, rcs_dbsm)
            expected_db = 10.0 * np.log10(float(c4) + float(c8))
            self.assertAlmostEqual(
                float(curves["current_sinr_db"]), expected_db, places=3
            )

    def test_si_noise_ablation_is_not_added_twice(self):
        model = _validation_model()
        model.status_var = _Var("")
        self.assertTrue(
            model._load_packaged_detector_reference(self._packaged_reference_cfg())
        )
        noise_off = float(model._detector_output_noise_mw(0.0))
        noise_ref = float(model._detector_output_noise_mw(1.0))
        expected_off = 10.0 ** (
            model._float("c2_noise_power_off_dbm", -300.0) / 10.0
        )
        expected_on = 10.0 ** (
            model._float("c2_noise_power_dbm", -300.0) / 10.0
        )
        self.assertAlmostEqual(noise_off / expected_off, 1.0, places=10)
        self.assertAlmostEqual(noise_ref / expected_on, 1.0, places=10)

    def test_photocurrent_model_uses_joint_tx_scaling(self):
        model = _validation_model()
        model.status_var = _Var("")
        self.assertTrue(
            model._load_packaged_detector_reference(self._packaged_reference_cfg())
        )
        curves = model._photocurrent_model_curves()
        current = np.asarray(curves["photocurrent_ma"], dtype=np.float64)
        tx_power = np.asarray(curves["tx_power_dbm"], dtype=np.float64)
        sensing_on = np.asarray(curves["sensing_on_db"], dtype=np.float64)
        sensing_off = np.asarray(curves["sensing_off_db"], dtype=np.float64)
        self.assertAlmostEqual(float(tx_power[-1]), -10.0, places=10)
        self.assertAlmostEqual(
            float(tx_power[0]),
            -10.0 + 20.0 * np.log10(4.5 / 7.0),
            places=10,
        )
        self.assertTrue(np.all(np.diff(current) > 0.0))
        self.assertTrue(np.all(np.diff(sensing_on) > 0.0))
        self.assertTrue(np.all(sensing_on >= sensing_off))
        self.assertGreater(float(sensing_on[-1]), 13.2)

    def test_photocurrent_figure_places_tx_power_on_bottom_axis(self):
        model = _validation_model()
        model.status_var = _Var("")
        self.assertTrue(
            model._load_packaged_detector_reference(self._packaged_reference_cfg())
        )
        fig = Figure()
        model._draw_photocurrent_sinr_figure(fig, for_save=False)
        primary = fig.axes[0]
        self.assertEqual(primary.get_xlabel(), "Equivalent THz Tx power (dBm)")
        self.assertEqual(
            primary.child_axes[0].get_xlabel(),
            r"UTC-PD photocurrent, $I_{\mathrm{ph}}$ (mA)",
        )

    def test_processing_gain_keeps_rho_as_a_separate_physical_factor(self):
        model = _validation_model()
        self.assertAlmostEqual(
            float(model._pilot_weighted_processing_gain_db(0.20)),
            26.0 + 10.0 * np.log10(0.20),
            places=10,
        )

    def test_packaged_model_matches_detected_photocurrent_scale(self):
        model = _validation_model()
        model.status_var = _Var("")
        self.assertTrue(
            model._load_packaged_detector_reference(self._packaged_reference_cfg())
        )
        modeled = float(model._photocurrent_model_curves()["sensing_on_db"][-1])
        measured = next(
            float(point["sensing_sinr_db"])
            for point in model._load_photocurrent_measurements()
            if point["modulation"] == "16QAM"
            and float(point["photocurrent_ma"]) == 7.0
        )
        self.assertLess(abs(measured - modeled), 2.0)

    def test_missing_reference_returns_tx_sweep_shaped_comm_nan(self):
        model = _validation_model()
        model.params["detector_reference_source"] = _Var("")
        tx_power = np.linspace(-14.0, -10.0, 201)
        comm = model._comm_sinr_from_reference(
            1.0, 0.20, tx_power_dbm=tx_power
        )
        self.assertEqual(comm.shape, tx_power.shape)
        self.assertTrue(np.all(np.isnan(comm)))

    def test_stored_photocurrent_results_load_without_raw_reprocessing(self):
        model = _validation_model()
        measurements = model._load_photocurrent_measurements()
        self.assertEqual(len(measurements), 10)
        point = next(
            p for p in measurements
            if p["modulation"] == "16QAM"
            and float(p["photocurrent_ma"]) == 6.5
        )
        self.assertAlmostEqual(float(point["sensing_sinr_db"]), 19.60335, places=5)

    def test_si_secondary_axis_maps_operating_point_to_total_tx_power(self):
        model = _validation_model()
        curves = model._si_power_sweep_curves()
        mapped_tx = model._si_carrier_dbm_to_total_tx_dbm(
            float(curves["current_si_dbm"])
        )
        self.assertAlmostEqual(float(mapped_tx), -10.0, places=9)

    def test_raw_photocurrent_capture_reprocessing_finds_known_target(self):
        model = _validation_model()
        path = (
            Path(__file__).resolve().parent
            / "data"
            / "captures"
            / "photocurrent"
            / "Data_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_16QAM_Iph6.5.npz"
        )
        result = model._reprocess_photocurrent_capture(path, 1.014, 13.2)
        self.assertAlmostEqual(float(result["target_peak_m"]), 1.014, delta=0.002)
        self.assertAlmostEqual(
            float(result["sensing_sinr_db"]), 19.60335, delta=0.05
        )
        self.assertTrue(bool(result["target_detected"]))

    def test_1100mm_raw_capture_uses_robust_median_profile_floor(self):
        model = _validation_model()
        path = (
            Path(__file__).resolve().parent
            / "data"
            / "captures"
            / "range_1100mm"
            / "Data_range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph7.npz"
        )
        result = model._reprocess_photocurrent_capture(path, 1.1, 13.2)
        self.assertAlmostEqual(float(result["target_peak_m"]), 1.1, delta=0.003)
        self.assertAlmostEqual(
            float(result["sensing_sinr_db"]), 17.75696, delta=0.05
        )
        self.assertTrue(bool(result["target_detected"]))

    def test_low_tx_with_si_range_remains_above_no_si_range(self):
        model = _validation_model()
        model.status_var = _Var("")
        self.assertTrue(
            model._load_packaged_detector_reference(self._packaged_reference_cfg())
        )
        model.params["sweep_tx_power_dbm"] = _Var(-20.0)
        curves = model._rmax_vs_effective_rcs(np.asarray([-6.0]), 0.20)
        self.assertGreaterEqual(float(curves[1][0]), float(curves[2][0]))

    def test_si_operating_point_and_compression_use_lna_input_plane(self):
        model = _validation_model()
        curves = model._si_power_sweep_curves()
        # -10.212384-dBm carrier power and 24-dB isolation gives the actual
        # packaged-reference SI carrier at the common LNA/ZBD input.
        self.assertAlmostEqual(
            float(curves["current_si_dbm"]), -34.2123840191, places=9
        )
        # Sideband, echo, and noise consume some headroom, so the carrier-only
        # SI boundary must lie below the total-input -20-dBm P1dB.
        self.assertLess(float(curves["compression_si_dbm"]), -20.0)


if __name__ == "__main__":
    unittest.main()
