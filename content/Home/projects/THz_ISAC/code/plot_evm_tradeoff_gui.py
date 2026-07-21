"""Plot the symbol-rate EVM / SSBI trade-off figure.

Default data source is the hardcoded measured EVM table (photocurrent 7 mA,
16QAM / 32QAM, fsym=2..20 GBaud) transcribed from the lab spreadsheet.
By default, this produces the paper-facing single-panel figure used to argue
that low-symbol-rate operation is AWGN-limited while high-symbol-rate operation
shows an SINR degradation:

  1. measured 32QAM EVM,
  2. an AWGN theoretical reference line fitted only to the 2-4 GBaud regime,
  3. an SINR trace from the electronic-noise-free/MZM-only nonlinear bound.

--mode photocurrent produces a separate paper figure: measured EVM vs UTC-PD
photocurrent (4.5-7 mA, fixed symbol rate) with a log10(Iph)-linear fit per
series (theoretically -20 dB/decade for a purely AWGN-limited, quadratic
UTC-PD photomixing law) and the same isac_gui physics simulation swept over
photocurrent instead of symbol rate. See
05_symbol_rate_evm_ssbi_tradeoff.md section 4.5 -- the Iph labels are
nominal/unsynchronized, so treat this as a trend check, not an absolute
calibration.

The legacy two-panel EVM + range-resolution figure remains available with
--mode legacy.

Two other data sources remain available for cross-checking against raw
captures: --source npz (data/captures/bandwidth/Data_fIF*_fsym*.npz, which
also carries a Welch-PSD spectral SNR) and --source excel (the exp_data.xlsx
back-to-back "direct cable" sweep). The physics-sim curve is only computed
for labels isac_gui recognizes as a modulation (e.g. "16QAM", "32QAM").

The simulated curve is expensive (full time-domain isac_gui.run_isac_sim per
symbol rate, averaged over several random seeds) so it is cached to
data/sim_evm_series_<modulation>.json (--mode paper/legacy) or
data/sim_evm_photocurrent_<label>.json (--mode photocurrent), keyed by a hash
of the source parameter JSON; pass --force-resim to bypass the cache.

Examples
--------
python plot_evm_tradeoff_gui.py --out data/fig3_evm_ssbi_tradeoff.png
python plot_evm_tradeoff_gui.py --mode photocurrent --no-show
python plot_evm_tradeoff_gui.py --mode legacy --out data/fig3_evm_tradeoff.png
python plot_evm_tradeoff_gui.py --source npz --out data/fig3_from_npz.png
python plot_evm_tradeoff_gui.py --no-show  # save without opening the GUI
python plot_evm_tradeoff_gui.py --no-sim   # skip the physics simulation curve
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from read_range_data import metric_map, to_float, unpack

C = 3e8
PAPER_BOX_ASPECT = 0.8  # height / width, i.e. 5:4 landscape plot box


def load_measured_table() -> dict[str, dict[str, np.ndarray]]:
    """EVM (dB) vs symbol rate (GBaud), photocurrent 7 mA, transcribed as-is
    from the lab spreadsheet (DFT-s-OFDM, rho known per FEC-threshold note).

    Cross-checked against the re-demodulated captures in
    data/captures/bandwidth/cpe_evm_remeasurement*.csv (see
    05_symbol_rate_evm_ssbi_tradeoff.md section 3.3)."""
    data = {
        "16QAM": {2: -25.22, 4: -23.22, 8: -20.68, 10: -19.66, 12: -18.49, 15: -17.42, 17: -16.9, 20: -15.94},
        "32QAM": {2: -25.56, 4: -23.77, 8: -20.76, 10: -19.5, 12: -18.61, 15: -17.49, 17: -16.5, 20: -15.8},
    }
    series: dict[str, dict[str, np.ndarray]] = {}
    for label, rows in data.items():
        sr = np.asarray(sorted(rows.keys()), dtype=float)
        evm = np.asarray([rows[k] for k in sorted(rows.keys())], dtype=float)
        series[label] = {"symbol_rate_gbaud": sr, "evm_db": evm}
    return series


def default_npz_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "captures" / "bandwidth"


def default_excel_path() -> Path:
    return Path(__file__).resolve().parent.parent / "exp_data.xlsx"


def get_npz_scalar(loaded: np.lib.npyio.NpzFile, key: str, default: Any = "") -> Any:
    if key not in loaded.files:
        return default
    try:
        return unpack(loaded[key])
    except Exception:
        return default


def load_capture_folder(npz_dir: Path) -> dict[str, dict[str, np.ndarray]]:
    """Read all Data_fIF*_fsym*.npz captures in npz_dir, grouped by modulation.

    Each capture stores one EVM value (communication demod result) plus the
    TX symbol rate, modulation, waveform type and launch power as scalars.
    """
    paths = sorted(npz_dir.glob("Data_fIF*_fsym*.npz"))
    if not paths:
        raise ValueError(f"No Data_fIF*_fsym*.npz files found in {npz_dir}")

    by_mod: dict[str, list[tuple[float, float, float, float]]] = {}
    for path in paths:
        with np.load(path, allow_pickle=True) as loaded:
            metrics = metric_map(loaded)
            evm_db = to_float(metrics.get("evm_db", {}).get("value", float("nan")))
            comm_snr_db = to_float(metrics.get("snr_com_db", {}).get("value", float("nan")))
            baud_hz = to_float(get_npz_scalar(loaded, "tx__symbol_rate_actual", float("nan")))
            mod = str(get_npz_scalar(loaded, "tx__modulation", "?"))
            power_dbm = to_float(get_npz_scalar(loaded, "tx__awg_ch1_power_dbm", float("nan")))
        if not (math.isfinite(evm_db) and math.isfinite(baud_hz) and baud_hz > 0):
            continue
        by_mod.setdefault(mod, []).append((baud_hz * 1e-9, evm_db, power_dbm, comm_snr_db))

    series: dict[str, dict[str, np.ndarray]] = {}
    for mod, rows in by_mod.items():
        rows.sort(key=lambda r: r[0])
        arr = np.asarray(rows, dtype=float)
        series[mod] = {
            "symbol_rate_gbaud": arr[:, 0],
            "evm_db": arr[:, 1],
            "power_dbm": arr[:, 2],
            "comm_snr_db": arr[:, 3],
        }
    return series


def load_symbol_rate_table_excel(excel_path: Path, sheet: str) -> dict[str, dict[str, np.ndarray]]:
    """Parse the "Symbol rate (GB)" sub-table from the "direct cable" sheet.

    The sheet mixes multiple small tables; this locates the header row
    whose cells contain "Symbol rate" and "DFT-s-OFDM"/"LFM-QAM", then reads
    numeric rows below it until the symbol-rate column goes blank.
    """
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))

    header_row_idx = None
    sr_col = dfts_col = lfm_col = None
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if isinstance(cell, str) and "symbol rate" in cell.lower():
                header_row_idx = i
                sr_col = j
        if header_row_idx == i:
            for j, cell in enumerate(row):
                if not isinstance(cell, str):
                    continue
                low = cell.lower()
                if "dft-s-ofdm" in low or "dfts-ofdm" in low or "dft-s ofdm" in low:
                    dfts_col = j
                elif "lfm" in low:
                    lfm_col = j
            break

    if header_row_idx is None or sr_col is None:
        raise ValueError(f'No "Symbol rate" header found on sheet "{sheet}" of {excel_path}')

    symbol_rate: list[float] = []
    evm_dfts: list[float] = []
    evm_lfm: list[float] = []
    for row in rows[header_row_idx + 1:]:
        sr_val = row[sr_col] if sr_col < len(row) else None
        if sr_val is None or not isinstance(sr_val, (int, float)):
            break
        symbol_rate.append(float(sr_val))
        evm_dfts.append(_to_float(row[dfts_col]) if dfts_col is not None and dfts_col < len(row) else float("nan"))
        evm_lfm.append(_to_float(row[lfm_col]) if lfm_col is not None and lfm_col < len(row) else float("nan"))

    sr = np.asarray(symbol_rate, dtype=float)
    series: dict[str, dict[str, np.ndarray]] = {}
    for label, evm in (("DFT-s-OFDM ($\\rho$=0.2)", evm_dfts), ("LFM-QAM", evm_lfm)):
        evm_arr = np.asarray(evm, dtype=float)
        valid = np.isfinite(sr) & np.isfinite(evm_arr)
        if np.any(valid):
            series[label] = {"symbol_rate_gbaud": sr[valid], "evm_db": evm_arr[valid]}
    return series


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def resolution_mm(baud_gbaud: np.ndarray) -> np.ndarray:
    b_hz = np.asarray(baud_gbaud, dtype=float) * 1e9
    return C / (2.0 * b_hz) * 1e3


# ---------------------------------------------------------------------------
# Physics-based simulation curve (isac_gui.run_isac_sim), cached to disk.
# ---------------------------------------------------------------------------

DEFAULT_SIM_PARAMS_JSON = Path(__file__).resolve().parent / "data" / "isac_sim_params_20260715_145824.json"
SIM_BAUD_LIST = [2.0, 4.0, 8.0, 10.0, 12.0, 15.0, 20.0]
SIM_MODULATIONS = {"16QAM", "32QAM"}
PREFEC_REQUIRED_SNR_DB = 15.75
PAPER_MODULATION = "32QAM"

# Measured Iph label (mA, nominal/unsynchronized -- see
# 05_symbol_rate_evm_ssbi_tradeoff.md section 4.5) vs EVM at fixed symbol rate.
PAPER_PHOTOCURRENT_DATA = {
    "16QAM @ 15 GBaud": {
        "baud_gbaud": 15.0,
        "iph_ma": [4.5, 5.0, 5.5, 6.0, 6.5, 7.0],
        "evm_db": [-13.78, -14.45, -15.55, -16.22, -16.9, -17.59],
    },
    "32QAM @ 16 GBaud": {
        "baud_gbaud": 16.0,
        "iph_ma": [4.5, 5.0, 5.5, 6.0, 6.5, 7.0],
        "evm_db": [-13.48, -13.68, -14.53, -15.39, -16.57, -17.49],
    },
}

# All electronic noise/quantization sources suppressed, leaving only the
# MZM's 3rd-order Taylor-model optical nonlinearity: an "as-good-as-this-
# waveform-and-modulator-allow" bound, not a literal AWGN-only line.
_ELECTRONIC_NOISE_FREE_OVERRIDES = dict(
    linewidth_mhz=1e-6, carrier_wander_enable=False, carrier_wander_mhz=0.0,
    zbd_nep_pw_sqrt_hz=1e-6, lna_nf_db=0.01, if_amp_nf_db=0.01, awg_dac_bits=16.0,
)


def _sim_cache_path(modulation: str) -> Path:
    return DEFAULT_SIM_PARAMS_JSON.parent / f"sim_evm_series_{modulation}.json"


def _params_fingerprint(params_json: Path) -> str:
    return hashlib.sha256(params_json.read_bytes()).hexdigest()[:16]


def build_sim_cfg(data: dict, modulation: str | None = None):
    """Build a SimConfig from a saved GUI parameter JSON ("Save Params").

    Mirrors isac_gui.ISACPanel._cfg_from_ui's field mapping so this recreates
    exactly the SimConfig the GUI would build for the same preset.
    """
    import isac_gui as sim

    p, c, a = data["params"], data["controls"], data["awg"]

    def pf(key: str, default: float) -> float:
        return float(p.get(key, default))

    cfg = sim.SimConfig(
        fs_gsps=float(a.get("fs_var", 100.0)),
        linewidth_mhz=pf("linewidth_mhz", 0.015),
        if_ghz=float(a.get("if_var", 12.0)),
        rf_carrier_ghz=float(a.get("rf_var", 280.0)),
        waveform=str(a.get("waveform_var", "16QAM")),
        modulation=modulation or str(a.get("modulation_var", "16QAM")),
        coherence_mode=str(c.get("coherence_mode", "Free-running")),
        rx_mode=str(c.get("rx_mode", "Mixer")),
        optical_sideband_mode="SSB" if bool(c.get("ssb_enable", True)) else "DSB",
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
        awg_dac_bits=pf("awg_dac_bits", 8.0),
        utcpd_photocurrent_ma=pf("utcpd_photocurrent_ma", 7.0),
        utcpd_target_dbm=sim.calc_utcpd_output_dbm(pf("utcpd_photocurrent_ma", 7.0)),
        utcpd_responsivity_a_per_w=pf("utcpd_resp_aw", 0.24),
        cspr_db=pf("cspr_db", 13.0),
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
        syms_per_chirp=max(8, int(float(a.get("chirp_len_var", 1024)))),
        pilot_rho=float(np.clip(float(a.get("pilot_rho_var", 0.20)), 0.0, 0.95)),
        rrc_beta=float(np.clip(float(a.get("rrc_beta_var", 0.20)), 0.01, 1.0)),
    )
    return cfg


def _mean_evm_db(evm_db_list: list[float]) -> float:
    lin = [10.0 ** (e / 10.0) for e in evm_db_list if math.isfinite(e)]
    return float(10.0 * np.log10(np.mean(lin))) if lin else float("nan")


def _run_sim_series(base_cfg, baud_list: list[float], seeds: list[int], overrides: dict | None = None) -> np.ndarray:
    import isac_gui as sim

    evm_db = []
    for baud in baud_list:
        trial = []
        for seed in seeds:
            cfg = copy.deepcopy(base_cfg)
            cfg.baud_gbaud = float(baud)
            cfg.sim_seed = int(seed)
            for key, value in (overrides or {}).items():
                setattr(cfg, key, value)
            trial.append(float(sim.run_isac_sim(cfg)["evm_db"]))
        evm_db.append(_mean_evm_db(trial))
    return np.asarray(evm_db, dtype=float)


def compute_sim_series(
    params_json: Path,
    modulation: str,
    baud_list: list[float] = SIM_BAUD_LIST,
    seeds: int = 4,
    use_cache: bool = True,
    force: bool = False,
) -> dict[str, np.ndarray]:
    """Physics-based EVM-vs-symbol-rate curve from isac_gui.run_isac_sim.

    Returns the full-model curve and an "electronic-noise-free" bound curve
    (see _ELECTRONIC_NOISE_FREE_OVERRIDES), cached to
    data/sim_evm_series_<modulation>.json keyed by a hash of params_json so
    a changed preset auto-invalidates the cache.
    """
    seed_list = list(range(int(seeds)))
    fingerprint = _params_fingerprint(params_json)
    cache_path = _sim_cache_path(modulation)
    if use_cache and not force and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
        if (cached.get("fingerprint") == fingerprint
                and cached.get("seeds") == seed_list
                and cached.get("baud_gbaud") == list(baud_list)):
            return {
                "symbol_rate_gbaud": np.asarray(cached["baud_gbaud"], dtype=float),
                "evm_db": np.asarray(cached["evm_db"], dtype=float),
                "bound_evm_db": np.asarray(cached["bound_evm_db"], dtype=float),
            }

    data = json.loads(params_json.read_text(encoding="utf-8"))
    base_cfg = build_sim_cfg(data, modulation=modulation)
    evm_db = _run_sim_series(base_cfg, baud_list, seed_list)
    bound_evm_db = _run_sim_series(base_cfg, baud_list, seed_list, overrides=_ELECTRONIC_NOISE_FREE_OVERRIDES)

    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "fingerprint": fingerprint, "seeds": seed_list, "baud_gbaud": list(baud_list),
            "evm_db": evm_db.tolist(), "bound_evm_db": bound_evm_db.tolist(),
        }, indent=2), encoding="utf-8")
    return {
        "symbol_rate_gbaud": np.asarray(baud_list, dtype=float),
        "evm_db": evm_db,
        "bound_evm_db": bound_evm_db,
    }


def fit_log_iph(iph_ma: np.ndarray, evm_db: np.ndarray) -> tuple[float, float, float]:
    """Least-squares fit of EVM(dB) = a*log10(Iph) + b; returns (a, b, R^2).

    UTC-PD photomixing follows P_THz ~ Iph^2 (calc_utcpd_output_dbm), so a
    purely AWGN-limited system gives a = -20 dB/decade exactly.
    """
    x = np.log10(np.asarray(iph_ma, dtype=float))
    y = np.asarray(evm_db, dtype=float)
    a, b = np.polyfit(x, y, 1)
    pred = a * x + b
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(a), float(b), r2


def _photocurrent_cache_path(label: str) -> Path:
    safe = label.replace(" ", "_").replace("@", "at")
    return DEFAULT_SIM_PARAMS_JSON.parent / f"sim_evm_photocurrent_{safe}.json"


def _run_sim_photocurrent_series(base_cfg, iph_list: list[float], seeds: list[int]) -> np.ndarray:
    import isac_gui as sim

    evm_db = []
    for iph in iph_list:
        trial = []
        for seed in seeds:
            cfg = copy.deepcopy(base_cfg)
            cfg.utcpd_photocurrent_ma = float(iph)
            cfg.utcpd_target_dbm = sim.calc_utcpd_output_dbm(float(iph))
            cfg.sim_seed = int(seed)
            trial.append(float(sim.run_isac_sim(cfg)["evm_db"]))
        evm_db.append(_mean_evm_db(trial))
    return np.asarray(evm_db, dtype=float)


def compute_sim_photocurrent_series(
    params_json: Path,
    label: str,
    modulation: str,
    baud_gbaud: float,
    iph_list: list[float],
    seeds: int = 4,
    use_cache: bool = True,
    force: bool = False,
) -> dict[str, np.ndarray]:
    """Physics-based EVM-vs-photocurrent curve from isac_gui.run_isac_sim at a
    fixed symbol rate, cached to data/sim_evm_photocurrent_<label>.json."""
    seed_list = list(range(int(seeds)))
    fingerprint = _params_fingerprint(params_json)
    cache_path = _photocurrent_cache_path(label)
    if use_cache and not force and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
        if (cached.get("fingerprint") == fingerprint
                and cached.get("seeds") == seed_list
                and cached.get("baud_gbaud") == float(baud_gbaud)
                and cached.get("iph_ma") == list(iph_list)):
            return {
                "iph_ma": np.asarray(cached["iph_ma"], dtype=float),
                "evm_db": np.asarray(cached["evm_db"], dtype=float),
            }

    data = json.loads(params_json.read_text(encoding="utf-8"))
    base_cfg = build_sim_cfg(data, modulation=modulation)
    base_cfg.baud_gbaud = float(baud_gbaud)
    evm_db = _run_sim_photocurrent_series(base_cfg, iph_list, seed_list)

    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "fingerprint": fingerprint, "seeds": seed_list, "baud_gbaud": float(baud_gbaud),
            "iph_ma": list(iph_list), "evm_db": evm_db.tolist(),
        }, indent=2), encoding="utf-8")
    return {"iph_ma": np.asarray(iph_list, dtype=float), "evm_db": evm_db}


def _evm_db_to_power(evm_db: np.ndarray | float) -> np.ndarray:
    return 10.0 ** (np.asarray(evm_db, dtype=float) / 10.0)


def _evm_power_to_db(evm_power: np.ndarray | float) -> np.ndarray:
    evm_power_arr = np.maximum(np.asarray(evm_power, dtype=float), np.finfo(float).tiny)
    return 10.0 * np.log10(evm_power_arr)


def _pick_modulation_series(series: dict[str, dict[str, np.ndarray]], modulation: str) -> tuple[str, dict[str, np.ndarray]]:
    wanted = modulation.strip().upper()
    for label, values in series.items():
        if label.strip().upper() == wanted:
            return label, values
    available = ", ".join(sorted(series.keys()))
    raise ValueError(f"{modulation} data is required for the paper SSBI figure. Available: {available}")


def _awgn_reference_from_low_rates(sr_gbaud: np.ndarray, evm_db: np.ndarray, low_rates: tuple[float, ...] = (2.0, 4.0)) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit EVM_AWGN(B) = offset + 10log10(B/2GBd) using low-rate points only."""
    sr = np.asarray(sr_gbaud, dtype=float)
    evm = np.asarray(evm_db, dtype=float)
    low_mask = np.zeros_like(sr, dtype=bool)
    for rate in low_rates:
        low_mask |= np.isclose(sr, rate, rtol=0.0, atol=1e-6)
    low_mask &= np.isfinite(evm)
    if np.count_nonzero(low_mask) == 0:
        finite = np.isfinite(sr) & np.isfinite(evm)
        if not np.any(finite):
            raise ValueError("No finite measured EVM values are available for AWGN reference fitting.")
        ref_idx = int(np.argmin(sr[finite]))
        finite_indices = np.flatnonzero(finite)
        low_mask[finite_indices[ref_idx]] = True

    fit_offset_db = float(np.mean(evm[low_mask] - 10.0 * np.log10(sr[low_mask] / 2.0)))
    awgn_db = fit_offset_db + 10.0 * np.log10(sr / 2.0)
    return sr[low_mask], fit_offset_db + 10.0 * np.log10(sr[low_mask] / 2.0), fit_offset_db


def _ssbi_bound_from_sim(args: argparse.Namespace, modulation: str, sr_gbaud: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    if args.no_sim:
        return None
    try:
        sim_series = compute_sim_series(
            args.sim_params, modulation.strip().upper(),
            baud_list=[float(v) for v in sr_gbaud],
            seeds=args.sim_seeds,
            force=args.force_resim,
        )
    except Exception as exc:
        print(f"WARNING: SSBI/MZM-only sim failed for {modulation}: {exc}")
        return None
    return sim_series["symbol_rate_gbaud"], sim_series["bound_evm_db"]


def _interpolate_evm_at(sr_gbaud: np.ndarray, evm_db: np.ndarray, anchor_gbaud: float) -> float:
    order = np.argsort(sr_gbaud)
    x = np.asarray(sr_gbaud, dtype=float)[order]
    y = np.asarray(evm_db, dtype=float)[order]
    return float(np.interp(float(anchor_gbaud), x, y))


def _snr_evm_curve(x_gbaud: np.ndarray, anchor_gbaud: float, anchor_snr_db: float) -> np.ndarray:
    return -float(anchor_snr_db) + 10.0 * np.log10(np.asarray(x_gbaud, dtype=float) / float(anchor_gbaud))


def _ssbi_excess_evm_power(sir_x_gbaud: np.ndarray, sir_evm_db: np.ndarray, zero_gbaud: float) -> np.ndarray:
    """Return the rate-dependent excess distortion power above a low-rate reference.

    The raw MZM-only/nonlinear simulation contains a small residual distortion
    even at low symbol rates.  For a figure claiming high-rate SSBI degradation,
    that low-rate residual should not be counted as an additional impairment;
    otherwise SINR is worse than SNR even where the AWGN-limited approximation
    is supposed to hold.
    """
    sir_power = _evm_db_to_power(sir_evm_db)
    ref_power = float(10.0 ** (_interpolate_evm_at(sir_x_gbaud, sir_evm_db, zero_gbaud) / 10.0))
    return np.maximum(sir_power - ref_power, 0.0)


def make_paper_ssbi_figure(series: dict[str, dict[str, np.ndarray]], args: argparse.Namespace) -> None:
    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import AutoMinorLocator, NullFormatter, ScalarFormatter

    plt.rcParams.update({
        "font.family": "Times New Roman",
        "mathtext.fontset": "stix",
        "axes.labelsize": 13,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 11,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "axes.linewidth": 0.9,
    })

    label, values = _pick_modulation_series(series, PAPER_MODULATION)
    order = np.argsort(values["symbol_rate_gbaud"])
    sr = np.asarray(values["symbol_rate_gbaud"], dtype=float)[order]
    evm = np.asarray(values["evm_db"], dtype=float)[order]
    valid = np.isfinite(sr) & np.isfinite(evm)
    sr = sr[valid]
    evm = evm[valid]
    if sr.size == 0:
        raise ValueError("No finite 32QAM EVM values are available.")

    awgn_low_x, awgn_low_y, awgn_offset_db = _awgn_reference_from_low_rates(sr, evm)
    snr_anchor_gbaud = float(args.snr_anchor_gbaud)
    default_anchor_snr_db = -_interpolate_evm_at(sr, evm, snr_anchor_gbaud)
    snr_anchor_db = float(args.snr_anchor_db) if args.snr_anchor_db is not None else default_anchor_snr_db
    snr_smooth = np.geomspace(max(1.0, float(np.min(sr)) * 0.9), min(float(args.xmax_gbaud), float(np.max(sr)) * 1.02), 240)
    snr_smooth_y = _snr_evm_curve(snr_smooth, snr_anchor_gbaud, snr_anchor_db)

    ssbi_bound = _ssbi_bound_from_sim(args, label, sr)

    figure_dpi = 120 if args.show else args.dpi
    fig, ax = plt.subplots(figsize=(4.8, 3.85), dpi=figure_dpi)
    meas_line, = ax.plot(
        sr, evm, "o-", color="black", lw=1.45, ms=5.8, mew=0.9,
        label="_nolegend_", picker=6,
    )
    meas_line._cursor_label = "Measured EVM"  # type: ignore[attr-defined]

    awgn_line, = ax.plot(
        snr_smooth, snr_smooth_y, "--", color="#0000bd", lw=1.45,
        label="-SNR", picker=5,
    )
    awgn_line._cursor_label = "Theoretical SNR"  # type: ignore[attr-defined]

    if ssbi_bound is not None:
        sir_x, sir_evm_db = ssbi_bound
        snr_evm_at_sir_x = _snr_evm_curve(sir_x, snr_anchor_gbaud, snr_anchor_db)
        ssbi_excess_power = _ssbi_excess_evm_power(sir_x, sir_evm_db, float(args.ssbi_zero_gbaud))
        # EVM^2 is the inverse-SNR/SIR quantity. The low-rate nonlinear
        # residual is subtracted so the AWGN-limited region satisfies
        # SINR = SNR; only the symbol-rate-dependent excess is added.
        #
        # 1/SINR = 1/SNR + 1/SIR maps to
        # EVM_SINR^2 = EVM_SNR^2 + EVM_SIR^2 on this plot.
        sinr_evm_db = _evm_power_to_db(_evm_db_to_power(snr_evm_at_sir_x) + ssbi_excess_power)
        sinr_line, = ax.plot(
            sir_x, sinr_evm_db, "--", color="#ff0000",  lw=1.45,
            label="-SINR", picker=5,
        )
        sinr_line._cursor_label = "SINR"  # type: ignore[attr-defined]
    else:
        sinr_evm_db = None

    threshold_db = -float(args.required_snr_db)
    thr_line = ax.axhline(
        threshold_db, color="0.35", ls=":", lw=1.2,
        label="_nolegend_",
    )
    thr_line._cursor_label = "Pre-FEC threshold"  # type: ignore[attr-defined]

    ax.set_xscale("log")
    ax.set_xlim(2, 20)
    ax.set_ylim(-30, -10)
    ax.set_yticks([-30, -25, -20, -15, -10])
    ax.set_box_aspect(PAPER_BOX_ASPECT)
    ax.set_xlabel("Symbol rate (GBaud)")
    ax.set_ylabel("EVM (dB)")
    tick_candidates = [2, 4, 8, 10, 15, 20]
    tick_candidates = [t for t in tick_candidates if ax.get_xlim()[0] <= t <= ax.get_xlim()[1]]
    ax.set_xticks(tick_candidates)
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.grid(True, which="major", alpha=0.32)
    ax.grid(True, which="minor", alpha=0.12)
    ax.legend(handles=[awgn_line, sinr_line] if ssbi_bound is not None else [awgn_line], loc="lower right", frameon=False)
    for spine in ax.spines.values():
        spine.set_visible(True)

    cursor_annotations: dict[Any, Any] = {}

    def on_pick(event: Any) -> None:
        line = event.artist
        if not hasattr(line, "get_xdata") or not len(event.ind):
            return
        indices = np.asarray(event.ind, dtype=int)
        xdata = np.asarray(line.get_xdata(), dtype=float)
        ydata = np.asarray(line.get_ydata(), dtype=float)
        mouse_x = event.mouseevent.xdata
        idx = int(indices[0] if mouse_x is None else indices[np.argmin(np.abs(xdata[indices] - mouse_x))])
        old = cursor_annotations.pop(ax, None)
        if old is not None:
            old.remove()
        annotation = ax.annotate(
            f"{getattr(line, '_cursor_label', line.get_label())}\n{xdata[idx]:.3g} GBd, {ydata[idx]:.2f} dB",
            xy=(xdata[idx], ydata[idx]), xytext=(8, 11), textcoords="offset points",
            fontsize=10, bbox={"boxstyle": "round,pad=0.25", "fc": "white", "alpha": 0.92},
            arrowprops={"arrowstyle": "->", "lw": 0.8},
        )
        cursor_annotations[ax] = annotation
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("pick_event", on_pick)

    if args.show:
        from matplotlib.widgets import Button, Slider

        fig.subplots_adjust(bottom=0.31, left=0.16, right=0.98, top=0.96)
        slider_ax = fig.add_axes((0.24, 0.15, 0.47, 0.04))
        save_ax = fig.add_axes((0.76, 0.065, 0.15, 0.075))
        snr_slider = Slider(
            slider_ax,
            f"SNR@{snr_anchor_gbaud:g}GBd [dB]",
            valmin=max(0.0, snr_anchor_db - 8.0),
            valmax=snr_anchor_db + 8.0,
            valinit=snr_anchor_db,
            valstep=0.1,
        )
        save_button = Button(save_ax, "Save")

        def update_snr(new_snr_db: float) -> None:
            awgn_line.set_ydata(_snr_evm_curve(snr_smooth, snr_anchor_gbaud, float(new_snr_db)))
            if ssbi_bound is not None:
                updated_snr_at_sir_x = _snr_evm_curve(sir_x, snr_anchor_gbaud, float(new_snr_db))
                updated_sinr = _evm_power_to_db(_evm_db_to_power(updated_snr_at_sir_x) + ssbi_excess_power)
                sinr_line.set_ydata(updated_sinr)
            fig.canvas.draw_idle()

        helper_text = fig.text(0.16, 0.075, "Click a trace to read values", fontsize=9, color="0.25")

        def save_current(_event: Any) -> None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            hidden_artists = [slider_ax, save_ax, helper_text]
            previous_visibility = [artist.get_visible() for artist in hidden_artists]
            active_annotation = cursor_annotations.get(ax)
            annotation_visibility = None
            if active_annotation is not None:
                annotation_visibility = active_annotation.get_visible()
                active_annotation.set_visible(False)
            try:
                for artist in hidden_artists:
                    artist.set_visible(False)
                fig.canvas.draw()
                fig.savefig(args.out, dpi=args.dpi, bbox_inches="tight", pad_inches=0.04)
            finally:
                for artist, was_visible in zip(hidden_artists, previous_visibility):
                    artist.set_visible(was_visible)
                if active_annotation is not None and annotation_visibility is not None:
                    active_annotation.set_visible(annotation_visibility)
                fig.canvas.draw_idle()
            print(f"Saved visible graph only: {args.out}")

        snr_slider.on_changed(update_snr)
        save_button.on_clicked(save_current)
    else:
        fig.tight_layout()

    if not args.show:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.out, dpi=args.dpi, bbox_inches="tight", pad_inches=0.04)
        print(f"Saved: {args.out}")
    print(
        "Paper-mode model: theoretical SNR line is anchored at "
        f"{snr_anchor_db:.2f} dB for {snr_anchor_gbaud:g} GBaud and plotted over the full range; "
        f"SSBI excess is zeroed at {float(args.ssbi_zero_gbaud):g} GBaud; threshold = {threshold_db:.2f} dB EVM."
    )
    if ssbi_bound is not None:
        ratio = _evm_db_to_power(sinr_evm_db[-1]) / _evm_db_to_power(sinr_evm_db[0])
        print(
            "SINR trace uses 1/SINR = 1/SNR + 1/SIR; "
            f"EVM^2 growth from {ssbi_bound[0][0]:g} to {ssbi_bound[0][-1]:g} GBaud: {float(ratio):.2f}x"
        )
    if args.show:
        plt.show()
    else:
        plt.close(fig)


def make_paper_photocurrent_figure(args: argparse.Namespace) -> None:
    """EVM vs UTC-PD photocurrent, paper-styled to match make_paper_ssbi_figure.

    UTC-PD photomixing follows P_THz ~ Iph^2, so a purely AWGN-limited system
    gives EVM(dB) vs log10(Iph) a -20 dB/decade slope. Each measured series is
    shown with its own least-squares fit (slope/R^2 printed and annotated) and
    -- unless --no-sim -- the isac_gui physics simulation swept over the same
    photocurrents at the same fixed symbol rate. See
    05_symbol_rate_evm_ssbi_tradeoff.md section 4.5: the Iph labels are
    nominal/unsynchronized, so this is a trend check, not an absolute
    calibration.
    """
    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter, ScalarFormatter

    plt.rcParams.update({
        "font.family": "Times New Roman",
        "mathtext.fontset": "stix",
        "axes.labelsize": 13,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 9,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "axes.linewidth": 0.9,
    })

    colors = ["red", "blue"]
    label_color = {label: colors[i % len(colors)] for i, label in enumerate(PAPER_PHOTOCURRENT_DATA)}
    label_open = {label: (i % 2 == 1) for i, label in enumerate(PAPER_PHOTOCURRENT_DATA)}

    all_iph = np.concatenate([np.asarray(e["iph_ma"], dtype=float) for e in PAPER_PHOTOCURRENT_DATA.values()])
    iph_theory = np.geomspace(float(all_iph.min()) * 0.96, float(all_iph.max()) * 1.04, 120)

    figure_dpi = 120 if args.show else args.dpi
    fig, ax = plt.subplots(figsize=(4.8, 3.85), dpi=figure_dpi)

    fit_lines: dict[str, Any] = {}
    sim_lines: dict[str, Any] = {}
    fit_results: dict[str, tuple[float, float, float]] = {}
    sim_series_by_label: dict[str, dict[str, np.ndarray]] = {}
    print(f"{'series':<20} {'fit slope':>16} {'R2':>8}")
    for label, entry in PAPER_PHOTOCURRENT_DATA.items():
        iph = np.asarray(entry["iph_ma"], dtype=float)
        evm = np.asarray(entry["evm_db"], dtype=float)
        color = label_color[label]
        marker_kwargs = (
            {"marker": "o", "markerfacecolor": "none", "markeredgecolor": color}
            if label_open[label] else
            {"marker": "o", "markerfacecolor": color, "markeredgecolor": color}
        )
        meas_line, = ax.plot(
            iph, evm, "-", color=color, lw=1.3, ms=6, mew=1.2,
            label=f"Measured ({label})", picker=6, **marker_kwargs,
        )
        meas_line._cursor_label = f"Measured {label}"  # type: ignore[attr-defined]

        slope, intercept, r2 = fit_log_iph(iph, evm)
        fit_results[label] = (slope, intercept, r2)
        print(f"{label:<20} {slope:13.2f} dB/dec {r2:8.4f}")
        fit_y = slope * np.log10(iph_theory) + intercept
        fit_line, = ax.plot(
            iph_theory, fit_y, "--", color=color, lw=1.2,
            label=f"Fit ({label}): {slope:.1f} dB/dec, $R^2$={r2:.3f}", picker=5,
        )
        fit_line._cursor_label = f"Fit {label}"  # type: ignore[attr-defined]
        fit_lines[label] = fit_line

        if not args.no_sim:
            try:
                sim_series = compute_sim_photocurrent_series(
                    args.sim_params, label, label.split(" @ ")[0], entry["baud_gbaud"],
                    list(iph), seeds=args.sim_seeds, force=args.force_resim,
                )
            except Exception as exc:
                print(f"WARNING: physics sim failed for {label}: {exc}")
            else:
                sim_series_by_label[label] = sim_series
                sim_line, = ax.plot(
                    sim_series["iph_ma"], sim_series["evm_db"], "-.", color=color, lw=1.2,
                    marker="x", ms=5, mew=1.0,
                    label=f"Simulated ({label}, physics model)", picker=5,
                )
                sim_line._cursor_label = f"Simulated {label}"  # type: ignore[attr-defined]
                sim_lines[label] = sim_line

    threshold_db = -float(args.required_snr_db)
    thr_line = ax.axhline(threshold_db, color="0.35", ls=":", lw=1.2, label="_nolegend_")
    thr_line._cursor_label = "Pre-FEC threshold"  # type: ignore[attr-defined]

    ax.set_xscale("log")
    ax.set_xlabel("UTC-PD photocurrent (mA)")
    ax.set_ylabel("EVM (dB)")
    ax.set_box_aspect(PAPER_BOX_ASPECT)
    ax.set_xticks(sorted(set(all_iph.tolist())))
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, which="major", alpha=0.32)
    ax.grid(True, which="minor", alpha=0.12)
    ax.legend(loc="best", frameon=False)
    for spine in ax.spines.values():
        spine.set_visible(True)

    cursor_annotations: dict[Any, Any] = {}

    def on_pick(event: Any) -> None:
        line = event.artist
        if not hasattr(line, "get_xdata") or not len(event.ind):
            return
        indices = np.asarray(event.ind, dtype=int)
        xdata = np.asarray(line.get_xdata(), dtype=float)
        ydata = np.asarray(line.get_ydata(), dtype=float)
        mouse_x = event.mouseevent.xdata
        idx = int(indices[0] if mouse_x is None else indices[np.argmin(np.abs(xdata[indices] - mouse_x))])
        old = cursor_annotations.pop(ax, None)
        if old is not None:
            old.remove()
        annotation = ax.annotate(
            f"{getattr(line, '_cursor_label', line.get_label())}\n{xdata[idx]:.3g} mA, {ydata[idx]:.2f} dB",
            xy=(xdata[idx], ydata[idx]), xytext=(8, 11), textcoords="offset points",
            fontsize=10, bbox={"boxstyle": "round,pad=0.25", "fc": "white", "alpha": 0.92},
            arrowprops={"arrowstyle": "->", "lw": 0.8},
        )
        cursor_annotations[ax] = annotation
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("pick_event", on_pick)

    if args.show:
        from matplotlib.widgets import Button

        fig.subplots_adjust(bottom=0.2, left=0.16, right=0.98, top=0.96)
        save_ax = fig.add_axes((0.76, 0.06, 0.15, 0.08))
        save_button = Button(save_ax, "Save")
        helper_text = fig.text(0.16, 0.06, "Click a trace to read values", fontsize=9, color="0.25")

        def save_current(_event: Any) -> None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            hidden_artists = [save_ax, helper_text]
            previous_visibility = [artist.get_visible() for artist in hidden_artists]
            active_annotation = cursor_annotations.get(ax)
            annotation_visibility = None
            if active_annotation is not None:
                annotation_visibility = active_annotation.get_visible()
                active_annotation.set_visible(False)
            try:
                for artist in hidden_artists:
                    artist.set_visible(False)
                fig.canvas.draw()
                fig.savefig(args.out, dpi=args.dpi, bbox_inches="tight", pad_inches=0.04)
            finally:
                for artist, was_visible in zip(hidden_artists, previous_visibility):
                    artist.set_visible(was_visible)
                if active_annotation is not None and annotation_visibility is not None:
                    active_annotation.set_visible(annotation_visibility)
                fig.canvas.draw_idle()
            print(f"Saved visible graph only: {args.out}")

        save_button.on_clicked(save_current)
    else:
        fig.tight_layout()

    if not args.show:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.out, dpi=args.dpi, bbox_inches="tight", pad_inches=0.04)
        print(f"Saved: {args.out}")

    for label, (slope, _intercept, r2) in fit_results.items():
        msg = f"{label}: measured fit {slope:.2f} dB/decade (R^2={r2:.3f}) vs theoretical -20.0 dB/decade (AWGN, quadratic photomixing)"
        if label in sim_series_by_label:
            sim_slope, _, sim_r2 = fit_log_iph(sim_series_by_label[label]["iph_ma"], sim_series_by_label[label]["evm_db"])
            msg += f"; physics sim fit {sim_slope:.2f} dB/decade (R^2={sim_r2:.3f})"
        print(msg)

    if args.show:
        plt.show()
    else:
        plt.close(fig)


def make_figure(series: dict[str, dict[str, np.ndarray]], args: argparse.Namespace) -> None:
    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter, ScalarFormatter

    plt.rcParams.update({
        "font.family": "Times New Roman",
        "mathtext.fontset": "stix",
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 7.5,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "axes.linewidth": 0.8,
    })

    if not series:
        raise ValueError("No measured (symbol rate, EVM) series to plot.")

    # Pure, unambiguous red/blue per modulation; filled vs. open marker is the
    # second (color-independent) code, so curves are legible in grayscale too.
    color_cycle = ["red", "blue", "#0f766e", "#b45309"]
    labels = sorted(series.keys())
    colors = {label: color_cycle[i % len(color_cycle)] for i, label in enumerate(labels)}
    open_marker = {label: (i % 2 == 1) for i, label in enumerate(labels)}

    all_sr = np.concatenate([series[label]["symbol_rate_gbaud"] for label in labels])

    x_lo = min(0.8, all_sr.min() * 0.8)
    model_max_gbaud = max(args.xmax_gbaud, float(all_sr.max()))
    x_hi = model_max_gbaud * 1.05

    interactive = bool(args.show)
    figure_height = 4.0 if interactive else 3.0
    fig, (ax_main, ax_res) = plt.subplots(1, 2, figsize=(7.16, figure_height), dpi=args.dpi)

    def marker_kwargs(label: str) -> dict[str, Any]:
        color = colors[label]
        if open_marker[label]:
            return {"marker": "o", "markerfacecolor": "none", "markeredgecolor": color}
        return {"marker": "o", "markerfacecolor": color, "markeredgecolor": color}

    measured_lines = []
    for label in labels:
        sr_v = series[label]["symbol_rate_gbaud"]
        evm_v = series[label]["evm_db"]
        measured_line, = ax_main.plot(
            sr_v, evm_v, "-", color=colors[label], lw=1.4, ms=6, mew=1.3,
            label=f"Measured EVM ({label})", picker=6, **marker_kwargs(label)
        )
        measured_line._cursor_label = f"Measured {label}"  # type: ignore[attr-defined]
        measured_lines.append(measured_line)

    sim_lines = []
    bound_series = None
    if not args.no_sim:
        sim_labels = [label for label in labels if label.strip().upper() in SIM_MODULATIONS]
        for label in sim_labels:
            try:
                sim_series = compute_sim_series(
                    args.sim_params, label.strip().upper(),
                    seeds=args.sim_seeds, force=args.force_resim,
                )
            except Exception as exc:
                print(f"WARNING: physics sim failed for {label}: {exc}")
                continue
            sim_line, = ax_main.plot(
                sim_series["symbol_rate_gbaud"], sim_series["evm_db"], "-.",
                color=colors[label], lw=1.3, marker="x", ms=5, mew=1.1,
                label=f"Simulated EVM ({label}, physics model)", picker=5,
            )
            sim_line._cursor_label = f"Simulated {label}"  # type: ignore[attr-defined]
            sim_lines.append(sim_line)
            if bound_series is None:
                bound_series = sim_series
        if bound_series is not None:
            bound_line, = ax_main.plot(
                bound_series["symbol_rate_gbaud"], bound_series["bound_evm_db"], ":",
                color="0.45", lw=1.2,
                label="Electronic-noise-free bound (MZM nonlinearity only)", picker=5,
            )
            bound_line._cursor_label = "Electronic-noise-free bound"  # type: ignore[attr-defined]
            sim_lines.append(bound_line)

    ax_main.set_ylabel("EVM (dB)")

    x_theory = np.geomspace(x_lo, x_hi, 200)
    resolution_line, = ax_res.plot(
        x_theory, resolution_mm(x_theory), "-", color="blue", lw=1.4,
        label="$c/2B$ (theory)", picker=5,
    )
    resolution_line._cursor_label = "Range resolution"  # type: ignore[attr-defined]
    ax_res.set_ylabel("Range resolution (mm)")
    ax_res.set_yscale("log")

    tick_candidates = sorted(set(np.round(all_sr, 6).tolist()) | {1.0, 2.0, 4.0, 8.0, 10.0, 20.0})
    tick_candidates = [t for t in tick_candidates if x_lo * 0.99 <= t <= x_hi * 1.01]
    for ax in (ax_main, ax_res):
        ax.set_xscale("log")
        ax.set_xlim(x_lo, x_hi)
        ax.set_xticks(tick_candidates)
        ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlabel("Symbol rate (GBaud)")
        ax.grid(True, alpha=0.3, which="major")
        ax.legend(loc="best", frameon=False)

    # Native Matplotlib data cursor: click any marker or curve to read its
    # nearest value.  This avoids an extra mplcursors dependency.
    cursor_annotations: dict[Any, Any] = {}

    def on_pick(event: Any) -> None:
        line = event.artist
        if not hasattr(line, "get_xdata") or not len(event.ind):
            return
        mouse_x = event.mouseevent.xdata
        indices = np.asarray(event.ind, dtype=int)
        xdata = np.asarray(line.get_xdata(), dtype=float)
        ydata = np.asarray(line.get_ydata(), dtype=float)
        idx = int(indices[0] if mouse_x is None else indices[np.argmin(np.abs(xdata[indices] - mouse_x))])
        old = cursor_annotations.pop(line.axes, None)
        if old is not None:
            old.remove()
        label = getattr(line, "_cursor_label", line.get_label())
        y_unit = "mm" if line.axes is ax_res else "dB"
        annotation = line.axes.annotate(
            f"{label}\n{xdata[idx]:.3g} GBaud, {ydata[idx]:.3g} {y_unit}",
            xy=(xdata[idx], ydata[idx]), xytext=(9, 12), textcoords="offset points",
            fontsize=8, bbox={"boxstyle": "round,pad=0.3", "fc": "white", "alpha": 0.92},
            arrowprops={"arrowstyle": "->", "lw": 0.8},
        )
        cursor_annotations[line.axes] = annotation
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("pick_event", on_pick)

    if interactive:
        from matplotlib.widgets import Button

        fig.subplots_adjust(bottom=0.22, left=0.09, right=0.98, top=0.96, wspace=0.30)
        resim_ax = fig.add_axes((0.14, 0.05, 0.20, 0.07))
        save_ax = fig.add_axes((0.36, 0.05, 0.14, 0.07))
        resim_button = Button(resim_ax, "Recompute sim\n(force, slow)")
        save_button = Button(save_ax, "Save")

        def recompute(_event: Any) -> None:
            if args.no_sim:
                return
            resim_button.label.set_text("Running...")
            fig.canvas.draw_idle()
            for line in sim_lines:
                line.remove()
            sim_lines.clear()
            sim_labels = [label for label in labels if label.strip().upper() in SIM_MODULATIONS]
            bound_series = None
            for label in sim_labels:
                sim_series = compute_sim_series(
                    args.sim_params, label.strip().upper(),
                    seeds=args.sim_seeds, force=True,
                )
                sim_line, = ax_main.plot(
                    sim_series["symbol_rate_gbaud"], sim_series["evm_db"], "-.",
                    color=colors[label], lw=1.3, marker="x", ms=5, mew=1.1,
                    label=f"Simulated EVM ({label}, physics model)", picker=5,
                )
                sim_line._cursor_label = f"Simulated {label}"  # type: ignore[attr-defined]
                sim_lines.append(sim_line)
                if bound_series is None:
                    bound_series = sim_series
            if bound_series is not None:
                bound_line, = ax_main.plot(
                    bound_series["symbol_rate_gbaud"], bound_series["bound_evm_db"], ":",
                    color="0.45", lw=1.2,
                    label="Electronic-noise-free bound (MZM nonlinearity only)", picker=5,
                )
                bound_line._cursor_label = "Electronic-noise-free bound"  # type: ignore[attr-defined]
                sim_lines.append(bound_line)
            ax_main.relim()
            ax_main.autoscale_view(scalex=False, scaley=True)
            ax_main.legend(loc="best", frameon=False)
            resim_button.label.set_text("Recompute sim\n(force, slow)")
            fig.canvas.draw_idle()

        def save_current(_event: Any) -> None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(args.out, bbox_inches="tight")
            print(f"Saved current GUI figure: {args.out}")

        resim_button.on_clicked(recompute)
        save_button.on_clicked(save_current)
        fig.text(0.53, 0.075, "Click a marker/curve\nto read its value", fontsize=8, color="0.25")
    else:
        fig.tight_layout()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"Saved: {args.out}")
    if args.show:
        plt.show()
    else:
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("paper", "photocurrent", "legacy"), default="paper",
                        help="paper: 32QAM EVM/AWGN/SSBI figure; photocurrent: EVM vs UTC-PD photocurrent "
                             "figure; legacy: old two-panel EVM + resolution figure")
    parser.add_argument("--source", choices=("table", "npz", "excel"), default="table", help="Data source for measured EVM")
    parser.add_argument("--npz-dir", type=Path, default=default_npz_dir(), help="Folder with Data_fIF*_fsym*.npz captures")
    parser.add_argument("--excel", type=Path, default=default_excel_path(), help="Path to exp_data.xlsx")
    parser.add_argument("--sheet", type=str, default="direct cable", help="Sheet name containing the symbol-rate sweep")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output figure path (default depends on --mode)")
    parser.add_argument("--xmax-gbaud", type=float, dest="xmax_gbaud", default=20.0, help="Upper x-limit for the theory curves")
    parser.add_argument("--ymin-db", type=float, dest="ymin_db", default=-35.0, help="Lower y-limit for paper-mode EVM axis")
    parser.add_argument("--ymax-db", type=float, dest="ymax_db", default=-12.0, help="Upper y-limit for paper-mode EVM axis")
    parser.add_argument("--required-snr-db", type=float, dest="required_snr_db", default=PREFEC_REQUIRED_SNR_DB,
                        help="Required SNR for pre-FEC BER; plotted as EVM=-SNR in paper mode")
    parser.add_argument("--snr-anchor-gbaud", type=float, dest="snr_anchor_gbaud", default=4.0,
                        help="Symbol-rate anchor for the theoretical SNR line in paper mode")
    parser.add_argument("--snr-anchor-db", type=float, dest="snr_anchor_db", default=None,
                        help="Positive SNR value at --snr-anchor-gbaud. Default uses measured 32QAM EVM at that rate.")
    parser.add_argument("--ssbi-zero-gbaud", type=float, dest="ssbi_zero_gbaud", default=4.0,
                        help="Low-rate reference where SSBI excess is set to zero in paper mode")
    parser.add_argument("--sim-params", type=Path, dest="sim_params", default=DEFAULT_SIM_PARAMS_JSON,
                        help="isac_gui 'Save Params' JSON used to build the physics simulation curve")
    parser.add_argument("--sim-seeds", type=int, dest="sim_seeds", default=4,
                        help="Random seeds averaged per symbol rate for the physics simulation curve")
    parser.add_argument("--no-sim", dest="no_sim", action="store_true",
                        help="Skip the physics-based isac_gui simulation curve (measured data only)")
    parser.add_argument("--force-resim", dest="force_resim", action="store_true",
                        help="Bypass the simulation cache and recompute from scratch")
    parser.add_argument("--dpi", type=int, default=300)
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--show", dest="show", action="store_true",
                               help="Open the interactive GUI (default)")
    display_group.add_argument("--no-show", "--save-only", dest="show", action="store_false",
                               help="Save the static publication figure without opening a GUI")
    parser.set_defaults(show=True)
    args = parser.parse_args()

    if args.xmax_gbaud <= 0:
        parser.error("--xmax-gbaud must be positive")
    if args.ymin_db >= args.ymax_db:
        parser.error("--ymin-db must be smaller than --ymax-db")
    if args.snr_anchor_gbaud <= 0:
        parser.error("--snr-anchor-gbaud must be positive")
    if args.ssbi_zero_gbaud <= 0:
        parser.error("--ssbi-zero-gbaud must be positive")
    if args.sim_seeds <= 0:
        parser.error("--sim-seeds must be positive")

    if args.out is None:
        default_names = {
            "paper": "fig3_evm_ssbi_tradeoff.png",
            "photocurrent": "fig_evm_vs_photocurrent.png",
            "legacy": "fig3_evm_tradeoff.png",
        }
        args.out = Path(__file__).resolve().parent / "data" / default_names[args.mode]

    if args.mode == "photocurrent":
        make_paper_photocurrent_figure(args)
        return

    if args.source == "table":
        series = load_measured_table()
    elif args.source == "npz":
        series = load_capture_folder(args.npz_dir)
    else:
        series = load_symbol_rate_table_excel(args.excel, args.sheet)
    if args.mode == "paper":
        make_paper_ssbi_figure(series, args)
    else:
        make_figure(series, args)


if __name__ == "__main__":
    main()
