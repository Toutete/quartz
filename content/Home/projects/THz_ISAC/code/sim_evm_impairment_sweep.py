"""Ablation sweep: which modeled impairment explains the low-symbol-rate EVM
floor in the one-way comm link (`run_isac_sim`'s `v_rec_com` path)?

Loads a saved GUI parameter JSON (isac_sim_params_*.json), builds the same
SimConfig the GUI would for a sweep of symbol rates, and re-runs the
simulation with one impairment source knocked out at a time:

  - baseline           : all impairments as saved
  - no_phase_noise     : laser linewidth -> ~0, carrier wander disabled
  - no_zbd_nep         : ZBD envelope-detector NEP noise -> ~0
  - min_thermal_nf     : LNA + IF-amp noise figure -> ~0 dB (thermal floor only)
  - no_dso_noise       : UXR0404A ADC noise model monkeypatched to 0

Each (baud, config) cell is averaged over several random seeds because the
DFT-s-OFDM block count is small (5-17 blocks) at low symbol rates, matching
the real captures, so single-seed EVM is noisy.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import numpy as np

import isac_gui as sim

PARAMS_JSON = Path(__file__).resolve().parent / "data" / "isac_sim_params_20260715_145824.json"
BAUD_LIST = [2.0, 4.0, 8.0, 10.0, 12.0, 15.0, 17.0, 20.0]
SEEDS = list(range(4))
MODULATION_OVERRIDE = os.environ.get("SIM_MODULATION", "").strip() or None

MEASURED_16QAM_DB = {2.0: -25.22, 4.0: -23.22, 8.0: -20.68, 10.0: -19.66,
                     12.0: -18.49, 15.0: -17.42, 17.0: -16.90, 20.0: -15.94}
MEASURED_32QAM_DB = {2.0: -25.16, 4.0: -23.37, 8.0: -19.76, 10.0: -19.80,
                     12.0: -18.71, 15.0: -17.49, 17.0: -16.50, 20.0: -15.77}
MEASURED_DB = MEASURED_32QAM_DB if MODULATION_OVERRIDE == "32QAM" else MEASURED_16QAM_DB
# Points the user read off the GUI (isac_sim_params_20260715_145824.json state).
GUI_READ_DB = {2.0: -26.3, 4.0: -23.5, 15.0: -17.5, 20.0: -16.0}


def build_base_cfg(data: dict) -> sim.SimConfig:
    p = data["params"]
    c = data["controls"]
    a = data["awg"]

    def pf(key, default):
        return float(p.get(key, default))

    cfg = sim.SimConfig(
        fs_gsps=float(a.get("fs_var", 100.0)),
        linewidth_mhz=pf("linewidth_mhz", 0.015),
        if_ghz=float(a.get("if_var", 12.0)),
        rf_carrier_ghz=float(a.get("rf_var", 280.0)),
        waveform=str(a.get("waveform_var", "16QAM")),
        modulation=str(a.get("modulation_var", "16QAM")),
        coherence_mode=str(c.get("coherence_mode", "Free-running")),
        rx_mode=str(c.get("rx_mode", "Mixer")),
        optical_sideband_mode="SSB" if bool(c.get("ssb_enable", False)) else "DSB",
        si_enable=bool(c.get("si_enable", True)),
        carrier_wander_enable=bool(c.get("carrier_wander_enable", False)),
        carrier_wander_mhz=10.0 if bool(c.get("carrier_wander_enable", False)) else 0.0,
        sc_fde_enable=bool(c.get("sc_fde_enable", True)),
        sc_fde_taps=int(float(c.get("sc_fde_taps", 21))),
        optical_center_freq_thz=pf("opt_center_thz", 193.41),
        awg_rf_power_dbm=float(a.get("power_dbm_var", -10.0)),
        mzm_drive_gain_db=pf("mzm_drive_gain_db", 8.0),
        mzm_vpi_v=pf("mzm_vpi_v", 7.0),
        mzm_phi_bias_deg=pf("mzm_phi_bias_deg", 45.0),
        mzm_eo_bw_ghz=pf("mzm_eo_bw_ghz", 30.0),
        utcpd_photocurrent_ma=pf("utcpd_photocurrent_ma", 7.0),
        utcpd_target_dbm=sim.calc_utcpd_output_dbm(pf("utcpd_photocurrent_ma", 7.0)),
        utcpd_responsivity_a_per_w=pf("utcpd_resp_aw", 0.24),
        cspr_db=pf("cspr_db", 20.0),
        lna_gain_db=pf("lna_gain_db", 13.0),
        lna_nf_db=pf("lna_nf_db", 8.0),
        zbd_responsivity_vpw=pf("zbd_resp_vpw", 1700.0),
        zbd_nep_pw_sqrt_hz=pf("zbd_nep_pw", 4.8),
        c1_drive_gain_db=pf("c1_drive_gain_db", 30.0),
        c2_drive_gain_db=pf("c2_drive_gain_db", 24.0),
        if_amp_nf_db=pf("if_amp_nf_db", 5.0),
        dso_vscale_mv=pf("dso_vscale_mv", 100.0),
        dso_bandwidth_ghz=pf("dso_bw_ghz", 40.0),
        omt_iso_db=pf("omt_iso_db", 25.0),
        omt_il_db=pf("omt_il_db", 1.5),
        ant_gain_dbi=pf("tx_ant_gain_dbi", 30.0),
        tx_ant_gain_dbi=pf("tx_ant_gain_dbi", 30.0),
        rx_ant_gain_dbi=pf("tx_ant_gain_dbi", 30.0),
        c1_cable_loss_db=pf("c1_cable_loss_db", 0.0),
        c2_cable_loss_db=pf("c2_cable_loss_db", 0.0),
        target_rcs_sqm=pf("rcs_sqm", 1.0),
        target_ant_gain_dbi=pf("tx_ant_gain_dbi", 30.0),
        target_gamma_mag=pf("target_gamma_mag", 1.0),
        target_pol_eff=pf("target_pol_eff", 1.0),
        target_dist_m=max(pf("target_dist_m", 1.0), 0.1),
        awg_dac_bits=pf("awg_dac_bits", 8.0),
        syms_per_chirp=max(8, int(float(a.get("chirp_len_var", 1024)))),
        pilot_rho=float(np.clip(float(a.get("pilot_rho_var", 0.20)), 0.0, 0.95)),
        rrc_beta=float(np.clip(float(a.get("rrc_beta_var", 0.20)), 0.01, 1.0)),
    )
    if MODULATION_OVERRIDE:
        cfg.modulation = MODULATION_OVERRIDE
    return cfg


ABLATIONS = {
    "baseline": lambda cfg: cfg,
    "no_phase_noise": lambda cfg: _set(cfg, linewidth_mhz=1e-6, carrier_wander_enable=False, carrier_wander_mhz=0.0),
    "no_zbd_nep": lambda cfg: _set(cfg, zbd_nep_pw_sqrt_hz=1e-6),
    "min_thermal_nf": lambda cfg: _set(cfg, lna_nf_db=0.01, if_amp_nf_db=0.01),
    "no_dso_noise": lambda cfg: cfg,  # handled via monkeypatch instead
    "no_awg_quant": lambda cfg: _set(cfg, awg_dac_bits=16.0),
}


def _set(cfg: sim.SimConfig, **kwargs) -> sim.SimConfig:
    cfg = copy.deepcopy(cfg)
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def run_one(cfg: sim.SimConfig, baud: float, seed: int, ablation: str) -> float:
    cfg = copy.deepcopy(cfg)
    cfg.baud_gbaud = baud
    cfg.sim_seed = seed
    cfg = ABLATIONS[ablation](cfg)

    original_dso_noise = sim.calc_uxr0404a_noise_vrms
    if ablation == "no_dso_noise":
        sim.calc_uxr0404a_noise_vrms = lambda *a, **k: 0.0
    try:
        data = sim.run_isac_sim(cfg)
    finally:
        sim.calc_uxr0404a_noise_vrms = original_dso_noise
    return float(data["evm_db"])


def mean_evm_db(evm_db_list: list[float]) -> float:
    lin_sq = [10.0 ** (e / 10.0) for e in evm_db_list if np.isfinite(e)]
    if not lin_sq:
        return float("nan")
    return 10.0 * np.log10(float(np.mean(lin_sq)))


def main() -> None:
    import csv

    data = json.loads(PARAMS_JSON.read_text(encoding="utf-8"))
    base_cfg = build_base_cfg(data)
    modulation = MODULATION_OVERRIDE or base_cfg.modulation

    results: dict[str, dict[float, float]] = {name: {} for name in ABLATIONS}
    header = f"{'GBaud':>6} {'measured':>9} " + " ".join(f"{name:>16}" for name in ABLATIONS)
    print(f"# modulation={modulation}")
    print(header)
    for baud in BAUD_LIST:
        row_vals = []
        for name in ABLATIONS:
            evms = [run_one(base_cfg, baud, seed, name) for seed in SEEDS]
            avg = mean_evm_db(evms)
            results[name][baud] = avg
            row_vals.append(avg)
        measured = MEASURED_DB.get(baud, float("nan"))
        print(f"{baud:6.1f} {measured:9.2f} " + " ".join(f"{v:16.2f}" for v in row_vals))

    print("\nDelta vs baseline (positive = ablation improved/lowered EVM, i.e. that term mattered):")
    print(f"{'GBaud':>6} " + " ".join(f"{name:>16}" for name in ABLATIONS if name != "baseline"))
    for baud in BAUD_LIST:
        base = results["baseline"][baud]
        deltas = [base - results[name][baud] for name in ABLATIONS if name != "baseline"]
        print(f"{baud:6.1f} " + " ".join(f"{d:16.2f}" for d in deltas))

    out_csv = PARAMS_JSON.parent / f"sim_impairment_sweep_{modulation}.csv"
    fieldnames = ["modulation", "symbol_rate_gbaud", "measured_evm_db"] + list(ABLATIONS)
    with out_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for baud in BAUD_LIST:
            row = {"modulation": modulation, "symbol_rate_gbaud": baud,
                   "measured_evm_db": MEASURED_DB.get(baud, float("nan"))}
            row.update({name: results[name][baud] for name in ABLATIONS})
            writer.writerow(row)
    print(f"\nSaved: {out_csv}")


if __name__ == "__main__":
    main()
