import unittest

import numpy as np

from fso_engine import (
    FSOEngineConfig,
    _pd_power_from_intensity,
    _waterfill_power_allocation,
    aperture_gain_db,
    run_fso_receiver,
    simulate_fso_sequence,
)


class FSOEngineTests(unittest.TestCase):
    def test_receiver_aperture_and_reducer_preserve_collected_power(self):
        cfg = FSOEngineConfig(
            link_distance_m=800.0,
            rx_lens_diameter_m=0.05,
            pupil_relay_output_diameter_m=1e-3,
            pd_rows=2,
            pd_cols=4,
            pd_pitch_m=250e-6,
            pd_integrated_lens_diameter_m=100e-6,
            external_mla_enabled=False,
            n_time_frames=3,
            n_screens=0,
            n_subharmonics=0,
            cnn_epochs=0,
            grid_mode="small",
        )
        result = simulate_fso_sequence(cfg)

        self.assertAlmostEqual(
            result["reduced_lens_radius_m"],
            cfg.pupil_relay_output_diameter_m / 2.0,
        )
        receiver = result["receiver_intensity_seq"][0]
        reduced = result["intensity_seq"][0]
        coords = result["coords_receiver"]
        x, y = np.meshgrid(coords, coords, indexing="ij")
        radius = np.sqrt(x**2 + y**2)
        lens = (
            (radius <= result["rx_lens_radius_m"])
            & (radius >= result["rx_obstruction_radius_m"])
        )
        receiver_power = np.sum(receiver * lens) * result["dx_receiver"] ** 2
        reduced_power = np.sum(reduced) * result["dx_out"] ** 2
        self.assertAlmostEqual(receiver_power, reduced_power, places=6)
        self.assertLess(np.max(result["parseval_error"]), 1e-10)

    def test_frozen_flow_produces_correlated_time_series_and_link_metrics(self):
        cfg = FSOEngineConfig(
            link_distance_m=800.0,
            rx_lens_diameter_m=0.05,
            pupil_relay_output_diameter_m=1e-3,
            pd_rows=2,
            pd_cols=4,
            pd_pitch_m=250e-6,
            pd_integrated_lens_diameter_m=100e-6,
            external_mla_enabled=False,
            n_time_frames=6,
            n_screens=1,
            n_subharmonics=0,
            cnn_time_window=3,
            cnn_epochs=1,
            grid_mode="small",
        )
        result = run_fso_receiver(cfg)

        self.assertNotEqual(int(result["screen_shift_pixels"][-1, 0, 0]), 0)
        self.assertTrue(np.isfinite(result["temporal_correlation_lag1"]))
        self.assertTrue(np.all((result["strehl_ratio"] >= 0.0) & (result["strehl_ratio"] <= 1.0 + 1e-9)))
        self.assertIn("CNN predictive", result["metrics"])
        self.assertIn("r0_to_subaperture_ratio", result["spatial_strategy"])
        self.assertGreater(result["receiver_power_density_scale_max_w_m2"], 0.0)
        self.assertEqual(result["pd_rx_power_w"].shape, (cfg.n_time_frames, cfg.pd_rows * cfg.pd_cols))
        self.assertTrue(all(np.isfinite(metric["mean_evm_pct"]) for metric in result["metrics"].values()))

    def test_link_direction_and_requested_aperture_gains(self):
        downlink = simulate_fso_sequence(FSOEngineConfig(
            link_direction="downlink",
            link_distance_m=800.0,
            n_time_frames=3,
            n_screens=0,
            n_subharmonics=0,
            cnn_epochs=0,
            grid_mode="small",
        ))
        uplink = simulate_fso_sequence(FSOEngineConfig(
            link_direction="uplink",
            link_distance_m=800.0,
            n_time_frames=3,
            n_screens=0,
            n_subharmonics=0,
            cnn_epochs=0,
            grid_mode="small",
        ))

        self.assertGreater(downlink["tx_altitude_m"], downlink["rx_altitude_m"])
        self.assertLess(uplink["tx_altitude_m"], uplink["rx_altitude_m"])
        self.assertAlmostEqual(downlink["tx_antenna_gain_db"], 103.1)
        self.assertAlmostEqual(downlink["rx_antenna_gain_db"], 112.3)
        self.assertAlmostEqual(aperture_gain_db(0.070, 1550e-9), 103.0, places=1)
        self.assertAlmostEqual(aperture_gain_db(0.2032, 1550e-9), 112.3, places=1)

    def test_external_mla_collects_more_area_without_creating_power(self):
        coords = np.linspace(-2e-3, 2e-3, 101)
        dx = coords[1] - coords[0]
        intensity = np.ones((len(coords), len(coords)))
        positions = [(0.0, 0.0)]
        bare_cfg = FSOEngineConfig(
            pd_rows=1,
            pd_cols=1,
            pd_pitch_m=1e-3,
            pd_integrated_lens_diameter_m=0.4e-3,
            external_mla_enabled=False,
        )
        lens_cfg = FSOEngineConfig(
            pd_rows=1,
            pd_cols=1,
            pd_pitch_m=1e-3,
            pd_integrated_lens_diameter_m=0.4e-3,
            external_mla_enabled=True,
            external_mla_fill_factor=0.95,
            external_mla_efficiency=0.8,
        )
        bare, _, _ = _pd_power_from_intensity(intensity, coords, dx, positions, bare_cfg)
        focused, _, masks = _pd_power_from_intensity(intensity, coords, dx, positions, lens_cfg)
        collection_power = np.sum(intensity * masks[0]) * dx**2

        self.assertGreater(focused[0], bare[0])
        self.assertLessEqual(focused[0], collection_power + 1e-15)

    def test_poc_defaults_and_waterfill_weights(self):
        cfg = FSOEngineConfig()
        self.assertEqual((cfg.pd_rows, cfg.pd_cols), (4, 4))
        self.assertAlmostEqual(cfg.pd_pitch_m, 250e-6)
        self.assertAlmostEqual(cfg.pupil_relay_output_diameter_m, 1e-3)
        self.assertAlmostEqual(cfg.central_obstruction_ratio, 0.31)

        allocation = _waterfill_power_allocation(np.asarray([10.0, 2.0, 0.5, 0.0]))
        self.assertAlmostEqual(float(np.sum(allocation)), 1.0)
        self.assertTrue(np.all(allocation >= 0.0))
        self.assertGreater(allocation[0], allocation[1])


if __name__ == "__main__":
    unittest.main()
