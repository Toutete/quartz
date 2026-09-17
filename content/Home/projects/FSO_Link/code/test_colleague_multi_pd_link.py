import unittest

import numpy as np

from colleague_multi_pd_link import (
    ColleagueMultiPDConfig,
    _pd_power_from_intensity,
    aperture_gain_db,
    run_colleague_multi_pd_link,
    simulate_colleague_multi_pd_sequence,
)


class ColleagueMultiPDLinkTests(unittest.TestCase):
    def test_receiver_aperture_and_reducer_preserve_collected_power(self):
        cfg = ColleagueMultiPDConfig(
            link_distance_m=800.0,
            rx_lens_diameter_m=0.05,
            pd_rows=2,
            pd_cols=4,
            pd_spacing_m=1e-3,
            pd_radius_m=0.25e-3,
            microlens_enabled=False,
            n_time_frames=3,
            n_screens=0,
            n_subharmonics=0,
            cnn_epochs=0,
            grid_mode="small",
        )
        result = simulate_colleague_multi_pd_sequence(cfg)

        self.assertAlmostEqual(
            result["reduced_lens_radius_m"],
            result["rx_lens_radius_m"] / cfg.beam_reducer_ratio,
        )
        receiver = result["receiver_intensity_seq"][0]
        reduced = result["intensity_seq"][0]
        coords = result["coords_receiver"]
        x, y = np.meshgrid(coords, coords, indexing="ij")
        lens = x**2 + y**2 <= result["rx_lens_radius_m"] ** 2
        receiver_power = np.sum(receiver * lens) * result["dx_receiver"] ** 2
        reduced_power = np.sum(reduced) * result["dx_out"] ** 2
        self.assertAlmostEqual(receiver_power, reduced_power, places=6)
        self.assertLess(np.max(result["parseval_error"]), 1e-10)

    def test_frozen_flow_produces_correlated_time_series_and_link_metrics(self):
        cfg = ColleagueMultiPDConfig(
            link_distance_m=800.0,
            rx_lens_diameter_m=0.05,
            pd_rows=2,
            pd_cols=4,
            pd_spacing_m=1e-3,
            pd_radius_m=0.25e-3,
            microlens_enabled=False,
            n_time_frames=6,
            n_screens=1,
            n_subharmonics=0,
            cnn_time_window=3,
            cnn_epochs=1,
            grid_mode="small",
        )
        result = run_colleague_multi_pd_link(cfg)

        self.assertNotEqual(int(result["screen_shift_pixels"][-1, 0, 0]), 0)
        self.assertTrue(np.isfinite(result["temporal_correlation_lag1"]))
        self.assertTrue(np.all((result["strehl_ratio"] >= 0.0) & (result["strehl_ratio"] <= 1.0 + 1e-9)))
        self.assertIn("CNN predictive", result["metrics"])
        self.assertEqual(result["pd_rx_power_w"].shape, (cfg.n_time_frames, cfg.pd_rows * cfg.pd_cols))
        self.assertTrue(all(np.isfinite(metric["mean_evm_pct"]) for metric in result["metrics"].values()))

    def test_link_direction_and_requested_aperture_gains(self):
        downlink = simulate_colleague_multi_pd_sequence(ColleagueMultiPDConfig(
            link_direction="downlink",
            n_time_frames=3,
            n_screens=0,
            n_subharmonics=0,
            cnn_epochs=0,
            grid_mode="small",
        ))
        uplink = simulate_colleague_multi_pd_sequence(ColleagueMultiPDConfig(
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

    def test_microlens_cells_collect_more_area_without_creating_power(self):
        coords = np.linspace(-2e-3, 2e-3, 101)
        dx = coords[1] - coords[0]
        intensity = np.ones((len(coords), len(coords)))
        positions = [(0.0, 0.0)]
        bare_cfg = ColleagueMultiPDConfig(
            pd_rows=1,
            pd_cols=1,
            pd_spacing_m=1e-3,
            pd_radius_m=0.2e-3,
            microlens_enabled=False,
        )
        lens_cfg = ColleagueMultiPDConfig(
            pd_rows=1,
            pd_cols=1,
            pd_spacing_m=1e-3,
            pd_radius_m=0.2e-3,
            microlens_enabled=True,
            microlens_efficiency=0.8,
        )
        bare, _, _ = _pd_power_from_intensity(intensity, coords, dx, positions, bare_cfg)
        focused, _, masks = _pd_power_from_intensity(intensity, coords, dx, positions, lens_cfg)
        collection_power = np.sum(intensity * masks[0]) * dx**2

        self.assertGreater(focused[0], bare[0])
        self.assertLessEqual(focused[0], collection_power + 1e-15)


if __name__ == "__main__":
    unittest.main()
