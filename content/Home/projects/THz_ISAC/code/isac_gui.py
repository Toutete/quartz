#!/usr/bin/env python3
from __future__ import annotations
import csv
import copy
import io
import json
from dataclasses import dataclass
import sys
import threading
import math
import time
import warnings

# Suppress tight_layout warnings that spam the console
warnings.filterwarnings("ignore", message="This figure includes Axes that are not compatible with tight_layout")

from scipy.signal import welch, hilbert, fftconvolve
from scipy.special import erfcinv
from scipy.stats import ncx2

import queue
import threading
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from datetime import datetime

import numpy as np
import matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# IEEE Transactions-style figure defaults: serif (Times New Roman) fonts,
# modest sizes, and math text that matches the body font.
matplotlib.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman"],
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 8,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "mathtext.fontset": "stix",
})

from functions.awg_functions import download_to_awg, parse_channels, run_awg, stop_awg, test_awg_connection
from functions.dso_functions import (
    create_dso_controller,
    fft_resample_complex,
    normalize_dso_type,
)
from functions.dsp_functions import (
    apply_cross_polarization_sic,
    apply_linear_rls_sic,
    align_symbols_for_ber as _align_symbols_for_ber,
    bits_per_symbol as _bits_per_symbol,
    bits_to_qam_symbols as _bits_to_qam_symbols,
    hard_bits_from_symbols as _hard_bits_from_symbols,
    generate_zadoff_chu,
    normalize_iq_for_awg,
    normalize_real_for_awg,
    prbs_bits_lfsr as _prbs_bits_lfsr,
    sc_fde_equalizer,
    lfm_qam_rx_dsp_chain,
)

APP_DIR = Path(__file__).resolve().parent

def apply_unified_style(root: tk.Tk) -> None:
        style = ttk.Style(root)
        try: style.theme_use("clam")
        except Exception: pass

        bg = "#f4f6f9"
        card = "#ffffff"
        text = "#1e293b"
        sub = "#64748b"
        primary = "#2563eb"
        primary_hover = "#1d4ed8"

        root.configure(bg=bg)
        base_font = tkfont.nametofont("TkDefaultFont")
        base_font.configure(family="Segoe UI", size=10)
        heading_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        table_head_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")

        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=card)
        style.configure("TLabel", background=bg, foreground=text, font=base_font)
        style.configure("Muted.TLabel", background=bg, foreground=sub, font=base_font)
        style.configure("Title.TLabel", background=bg, foreground=primary, font=heading_font)
        style.configure("TLabelframe", background=bg, foreground=text, font=table_head_font)
        style.configure("TLabelframe.Label", background=bg, foreground=text, font=table_head_font)
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 6), font=base_font)
        style.map("TNotebook.Tab", background=[("selected", card), ("!selected", "#cbd5e1")], foreground=[("selected", primary), ("!selected", text)], padding=[("selected", (14, 8)), ("!selected", (12, 6))])
        style.configure("TButton", padding=(10, 6), font=base_font)
        style.configure("Primary.TButton", padding=(12, 6), font=base_font, foreground="white", background=primary)
        style.map("Primary.TButton", background=[("active", primary_hover), ("disabled", "#94a3b8")], foreground=[("disabled", "#f1f5f9")])
        style.configure("TEntry", padding=(5, 4), fieldbackground=card)
        style.configure("TCombobox", padding=(5, 4), fieldbackground=card)
        style.configure("Treeview", background=card, fieldbackground=card, font=base_font, rowheight=28)
        style.configure("Treeview.Heading", font=table_head_font, background="#e2e8f0", foreground=text)

def _parse_float_input(raw: str, field_name: str) -> float:
        try:
                return float(str(raw).strip())
        except Exception:
                raise ValueError(f"Invalid input for {field_name}: '{raw}'")
def _parse_ghz_input(raw: str, field_name: str) -> float: return _parse_float_input(raw, field_name) * 1e9

# ==============================================================================
# UNIFIED TX & SIMULATION PANEL (Restructured UI)
# ==============================================================================
class IsacTxSimPanel:
        def __init__(self, parent: ttk.Frame, runtime: dict, on_tx_generated=None) -> None:
                self.parent = parent
                self.runtime = runtime
                self.on_tx_generated = on_tx_generated
                self._build_ui()

        def _build_ui(self) -> None:
                frm = ttk.Frame(self.parent, padding=6)
                frm.pack(fill=tk.BOTH, expand=True)

                self._updating_power = False
                self._updating_vpp = False

                # Group 1: Connection
                conn_grp = ttk.LabelFrame(frm, text="Connection", padding=6)
                conn_grp.pack(fill=tk.X, pady=(0, 4))

                self.ip_var = tk.StringVar(value="192.168.1.2")
                ttk.Label(conn_grp, text="AWG IP").grid(row=0, column=0, sticky="w")
                ttk.Entry(conn_grp, textvariable=self.ip_var, width=14).grid(row=0, column=1, sticky="w", padx=(4, 0))

                self.port_var = tk.StringVar(value="60007")
                ttk.Label(conn_grp, text="Port").grid(row=0, column=2, sticky="w", padx=(10, 0))
                ttk.Entry(conn_grp, textvariable=self.port_var, width=8).grid(row=0, column=3, sticky="w", padx=(4, 0))

                ttk.Button(conn_grp, text="Test Connection", command=self._on_test_connection).grid(row=0, column=4, sticky="w", padx=(10, 0))

                self.mode_var = tk.StringVar(value="Real IF")
                ttk.Label(conn_grp, text="Signal Type").grid(row=1, column=0, sticky="w", pady=(5, 0))
                mode_box = ttk.Combobox(conn_grp, textvariable=self.mode_var, values=["IQ", "Real IF"], state="readonly", width=10)
                mode_box.grid(row=1, column=1, sticky="w", pady=(5, 0), padx=(4, 0))
                mode_box.bind("<<ComboboxSelected>>", lambda _: self._on_mode_changed())

                self.ch_var = tk.StringVar(value="1,2")
                self.ch_combo = ttk.Combobox(conn_grp, textvariable=self.ch_var, state="readonly", width=8)
                ttk.Label(conn_grp, text="AWG Ch").grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(5, 0))
                self.ch_combo.grid(row=1, column=3, sticky="w", pady=(5, 0), padx=(4, 0))

                self.fs_var = tk.StringVar(value="120")
                ttk.Label(conn_grp, text="Sample Rate (GHz)").grid(row=2, column=0, sticky="w", pady=(5, 0))
                ttk.Entry(conn_grp, textvariable=self.fs_var, width=10).grid(row=2, column=1, sticky="w", pady=(5, 0), padx=(4, 0))

                # Group 2: Signal Design & Download
                sig_grp = ttk.LabelFrame(frm, text="Signal Design & Download", padding=6)
                sig_grp.pack(fill=tk.X, pady=(0, 4))
                sig_grp.columnconfigure(1, weight=1)
                sig_grp.columnconfigure(3, weight=1)
                sig_grp.columnconfigure(5, weight=1)

                self.modulation_var = tk.StringVar(value="16QAM")
                ttk.Label(sig_grp, text="Modulation").grid(row=0, column=0, sticky="w")
                ttk.Combobox(
                    sig_grp,
                    textvariable=self.modulation_var,
                    values=["QPSK", "8PSK", "16QAM", "32QAM"],
                    state="readonly",
                    width=10,
                ).grid(row=0, column=1, sticky="w")

                self.symbol_rate_var = tk.StringVar(value="15")
                ttk.Label(sig_grp, text="Symbol Rate (GHz)").grid(row=0, column=2, sticky="w", padx=(10, 0))
                ttk.Entry(sig_grp, textvariable=self.symbol_rate_var, width=10).grid(row=0, column=3, sticky="w")

                self.if_var = tk.StringVar(value="11")
                ttk.Label(sig_grp, text="IF Freq (GHz)").grid(row=0, column=4, sticky="w", padx=(10, 0))
                self.if_entry = ttk.Entry(sig_grp, textvariable=self.if_var, width=10)
                self.if_entry.grid(row=0, column=5, sticky="w")

                self.prbs_n_var = tk.StringVar(value="15")
                ttk.Label(sig_grp, text="PRBS N").grid(row=1, column=0, sticky="w", pady=(5, 0))
                ttk.Entry(sig_grp, textvariable=self.prbs_n_var, width=10).grid(row=1, column=1, sticky="w", pady=(5, 0))

                self.chirp_len_var = tk.StringVar(value="1024")
                ttk.Label(sig_grp, text="Syms/Chirp").grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(5, 0))
                ttk.Entry(sig_grp, textvariable=self.chirp_len_var, width=10).grid(row=1, column=3, sticky="w", pady=(5, 0))

                self.rf_var = tk.StringVar(value="280")
                ttk.Label(sig_grp, text="RF Freq (GHz)").grid(row=1, column=4, sticky="w", padx=(10, 0), pady=(5, 0))
                ttk.Entry(sig_grp, textvariable=self.rf_var, width=10).grid(row=1, column=5, sticky="w", pady=(5, 0))

                self.waveform_var = tk.StringVar(value="DFT-s-OFDM")
                ttk.Label(sig_grp, text="Waveform").grid(row=2, column=0, sticky="w", pady=(5, 0))
                ttk.Combobox(sig_grp, textvariable=self.waveform_var,
                             values=["Tone", "SC", "OFDM", "DFT-s-OFDM", "FMCW"],
                             state="readonly", width=10).grid(row=2, column=1, sticky="w", pady=(5, 0))

                self.pilot_rho_var = tk.StringVar(value="0.20")
                ttk.Label(sig_grp, text="Pilot rho").grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(5, 0))
                ttk.Entry(sig_grp, textvariable=self.pilot_rho_var, width=10).grid(row=2, column=3, sticky="w", pady=(5, 0))

                self.rrc_beta_var = tk.StringVar(value="0.20")
                ttk.Label(sig_grp, text="RRC roll-off").grid(row=3, column=0, sticky="w", pady=(5, 0))
                ttk.Entry(sig_grp, textvariable=self.rrc_beta_var, width=10).grid(row=3, column=1, sticky="w", pady=(5, 0))

                self.max_awg_ksa_var = tk.StringVar(value="2048")
                ttk.Label(sig_grp, text="Max AWG (kSa)").grid(row=3, column=2, sticky="w", padx=(10, 0), pady=(5, 0))
                ttk.Entry(sig_grp, textvariable=self.max_awg_ksa_var, width=10).grid(row=3, column=3, sticky="w", pady=(5, 0))

                self.mem_warn_var = tk.StringVar(value="Memory: -- kSa")
                ttk.Label(sig_grp, textvariable=self.mem_warn_var, style="Muted.TLabel").grid(row=4, column=0, columnspan=4, sticky="w", pady=(5, 0))

                self.osr_var = tk.StringVar(value="OSR: --")
                ttk.Button(sig_grp, text="Download to AWG", command=self._on_download, style="Primary.TButton").grid(row=2, column=4, columnspan=2, sticky="w", padx=(10, 0), pady=(5, 0))

                # Group 3: Output Power & Control
                pwr_grp = ttk.LabelFrame(frm, text="Output Power & Control", padding=6)
                pwr_grp.pack(fill=tk.X, pady=(0, 4))

                self.power_dbm_var = tk.StringVar(value="-6")
                ttk.Label(pwr_grp, text="CH1 Power (dBm)").grid(row=0, column=0, sticky="w")
                ttk.Entry(pwr_grp, textvariable=self.power_dbm_var, width=10).grid(row=0, column=1, sticky="w", padx=(4, 0))

                self.vpp_ch1_var = tk.StringVar(value="0.3170")
                self.vpp_ch2_var = tk.StringVar(value="0.3170")
                self.vpp_var = self.vpp_ch1_var  # compatibility for simulation panels
                ttk.Label(pwr_grp, text="CH1 Vpp").grid(row=0, column=2, sticky="w", padx=(10, 0))
                ttk.Entry(pwr_grp, textvariable=self.vpp_ch1_var, width=10).grid(row=0, column=3, sticky="w", padx=(4, 0))
                ttk.Label(pwr_grp, text="CH2 Vpp").grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(5, 0))
                ttk.Entry(pwr_grp, textvariable=self.vpp_ch2_var, width=10).grid(row=1, column=3, sticky="w", padx=(4, 0), pady=(5, 0))

                btn_f = ttk.Frame(pwr_grp)
                btn_f.grid(row=0, column=4, sticky="w", padx=(10, 0))
                ttk.Button(btn_f, text="AWG ON", command=self._on_awg_run, style="Primary.TButton").pack(side=tk.LEFT)
                ttk.Button(btn_f, text="AWG OFF", command=self._on_awg_off).pack(side=tk.LEFT, padx=(4, 0))

                for var in [self.prbs_n_var, self.fs_var, self.symbol_rate_var, self.chirp_len_var,
                             self.modulation_var, self.waveform_var, self.if_var,
                             self.pilot_rho_var, self.rrc_beta_var, self.max_awg_ksa_var]:
                    var.trace_add("write", self._on_tx_param_changed)

                self.power_dbm_var.trace_add("write", self._on_power_changed)
                self.vpp_ch1_var.trace_add("write", self._on_vpp_changed)

                self._on_mode_changed()
                self._check_memory_limit()
                self._on_power_changed()

        def _on_tx_param_changed(self, *_) -> None:
            # Keep the GUI responsive: changing a field should only refresh
            # derived labels.  The heavy TX reference file is regenerated by
            # Download/Simulation, not on every keystroke or internal Fs snap.
            self._check_memory_limit()

        def _max_awg_samples_setting(self) -> int:
            try:
                max_ksa = float(self.max_awg_ksa_var.get())
            except Exception:
                max_ksa = 2048.0
            if not np.isfinite(max_ksa) or max_ksa <= 0:
                max_ksa = 2048.0
            return max(1024, int(round(max_ksa * 1000.0)))

        @staticmethod
        def _snap_awg_segment_len(n_samples: int, *, multiple: int = 128, min_len: int = 1024) -> int:
            n = int(max(min_len, n_samples))
            n = (n // multiple) * multiple
            return max(min_len, n)

        def _choose_tone_segment_len(self, fs_awg: float, if_hz: float, max_samples: int) -> tuple[int, float]:
            """Pick a M8194A-safe tone length with minimal record-boundary phase jump."""
            max_len = self._snap_awg_segment_len(max_samples)
            min_len = self._snap_awg_segment_len(1024)
            if fs_awg <= 0 or if_hz <= 0:
                return max_len, 0.0

            best_len = max_len
            best_err = float("inf")
            for n in range(max_len, min_len - 1, -128):
                cycles = float(n) * float(if_hz) / float(fs_awg)
                err = abs(cycles - round(cycles))
                if err < best_err - 1e-12:
                    best_len = n
                    best_err = err
                    if err < 1e-12:
                        break
            return int(best_len), float(best_err)

        @staticmethod
        def _select_awg_grid_for_symbol_rate(fs_hint: float, sym_rate: float) -> tuple[float, int]:
            """Choose M8194A raster rate and integer samples/symbol."""
            if sym_rate <= 0:
                raise ValueError("Symbol Rate must be positive and non-zero.")
            fs_min = 95.6e9
            fs_max = 120.0e9
            nps_min = int(np.ceil(fs_min / sym_rate - 1e-12))
            nps_max = int(np.floor(fs_max / sym_rate + 1e-12))
            if nps_min > nps_max:
                raise ValueError(
                    f"No integer AWG samples/symbol for {sym_rate/1e9:.6f} Gsym/s "
                    f"in the M8194A {fs_min/1e9:.1f}-{fs_max/1e9:.1f} GSa/s range."
                )
            nps_candidates = np.arange(nps_min, nps_max + 1, dtype=np.int64)
            fs_candidates = nps_candidates.astype(np.float64) * sym_rate
            preferred = float(np.clip(float(fs_hint), fs_min, fs_max))
            best_idx = int(np.argmin(np.abs(fs_candidates - preferred)))
            return float(fs_candidates[best_idx]), int(nps_candidates[best_idx])

        @staticmethod
        def _estimate_frame_symbols_for_memory(
            waveform_type: str,
            prbs_n: int,
            bps: int,
            n_sym_per_chirp: int,
        ) -> tuple[int, int, int]:
            min_chirps = 4
            min_syms_required = min_chirps * n_sym_per_chirp
            prbs_syms_required = int(np.ceil(((2 ** int(prbs_n)) - 1) / max(1, int(bps))))
            wave = str(waveform_type).strip()

            if wave == "Tone":
                return min_syms_required, min_chirps, 0

            if wave == "QAM":
                pre_len = min(64, max(16, n_sym_per_chirp // 8))
                pre_len = max(8, min(pre_len, n_sym_per_chirp - 1))
                data_len = max(1, n_sym_per_chirp - pre_len)
                n_chirps = max(min_chirps, int(np.ceil(prbs_syms_required / data_len)))
                return n_chirps * n_sym_per_chirp, n_chirps, pre_len

            if wave == "FMCW":
                return min_syms_required, min_chirps, 0

            if wave == "DFT-s-OFDM":
                n_chirps = max(min_chirps, int(np.ceil(prbs_syms_required / n_sym_per_chirp)))
                return n_chirps * n_sym_per_chirp, n_chirps, 0

            n_total_syms = max(min_syms_required, prbs_syms_required + 8)
            pre_len = 8
            for _ in range(4):
                pre_len = max(8, min(64, n_total_syms // 8))
                needed = max(min_syms_required, prbs_syms_required + pre_len)
                if n_total_syms >= needed:
                    break
                n_total_syms = needed
            return n_total_syms, 1, pre_len

        def _check_memory_limit(self) -> bool:
            try:
                n = int(_parse_float_input(self.prbs_n_var.get(), "PRBS N"))
                fs = _parse_ghz_input(self.fs_var.get(), "AWG Fs")
                sym_rate = _parse_ghz_input(self.symbol_rate_var.get(), "Symbol Rate")
                bps = _bits_per_symbol(self.modulation_var.get())
                n_sym_per_chirp = max(8, int(_parse_float_input(self.chirp_len_var.get(), "Symbols per Chirp")))
                if self.waveform_var.get().strip() == "Tone":
                    fs_eff = float(np.clip(fs, 95.6e9, 120.0e9))
                    total_pts, tone_err = self._choose_tone_segment_len(
                        fs_eff,
                        _parse_ghz_input(self.if_var.get(), "IF Freq"),
                        min(self._max_awg_samples_setting(), 262144),
                    )
                    total_ksa = total_pts / 1e3
                    self.osr_var.set(f"Tone @ {fs_eff/1e9:.3f} GSa/s")
                    if tone_err < 1e-9:
                        self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa OK (128-aligned, periodic)")
                    else:
                        self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa OK (128-aligned)")
                    return True
                num_symbols, _, _ = self._estimate_frame_symbols_for_memory(
                    self.waveform_var.get(), n, bps, n_sym_per_chirp
                )
                fs_eff, n_per_sym = self._select_awg_grid_for_symbol_rate(fs, sym_rate)
                total_pts = int(num_symbols * n_per_sym)
                total_ksa = total_pts / 1e3
                osr = n_per_sym
                max_samples = self._max_awg_samples_setting()
                max_ksa = max_samples / 1e3
                self.osr_var.set(f"OSR: {osr:d} Sa/sym @ {fs_eff/1e9:.3f} GSa/s")

                if total_pts > max_samples:
                    self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa OVER LIMIT (> {max_ksa:.0f} kSa)")
                    return False
                elif total_pts > 0.90 * max_samples:
                    self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa near limit")
                    return True
                else:
                    self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa OK")
                    return True
            except:
                self.mem_warn_var.set("Memory: -- kSa")
                self.osr_var.set("OSR: --")
                return False

        def _on_mode_changed(self) -> None:
            if self.mode_var.get() == "IQ":
                choices = ["1,3", "1,2", "2,4", "3,4"]
                self.ch_combo.configure(values=choices)
                if self.ch_var.get() not in choices: self.ch_var.set(choices[0])
                self.if_entry.configure(state="disabled")
            else:
                choices = ["1,2", "1", "2", "3", "4"]
                self.ch_combo.configure(values=choices)
                if self.ch_var.get() not in choices: self.ch_var.set("1,2")
                self.if_entry.configure(state="normal")

        def _vpp_by_channel(self, channels: list[int]) -> dict[int, float]:
            try:
                v1 = float(self.vpp_ch1_var.get())
            except Exception:
                v1 = 0.1
            try:
                v2 = float(self.vpp_ch2_var.get())
            except Exception:
                v2 = v1
            out: dict[int, float] = {}
            for ch in channels:
                ch_i = int(ch)
                out[ch_i] = v2 if ch_i == 2 else v1
            return out

        def _vpp_status_text(self, channels: list[int]) -> str:
            vals = self._vpp_by_channel(channels)
            return ", ".join(f"CH{ch}={vals[ch]:.4f} Vpp" for ch in sorted(vals))

        def _on_test_connection(self) -> None:
            def worker() -> None:
                try:
                    addr = f"TCPIP0::{self.ip_var.get().strip()}::{int(self.port_var.get())}::SOCKET"
                    test_awg_connection(addr, timeout_ms=10000)
                    self.parent.after(0, lambda: messagebox.showinfo("Success", "AWG Connection OK!"))
                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("Error", f"Connection Failed:\n{m}"))
            threading.Thread(target=worker, daemon=True).start()

        def _generate_tx_signal(self) -> dict:
            if not self._check_memory_limit():
                raise MemoryError(
                    f"Signal size exceeds Max AWG memory setting "
                    f"({self._max_awg_samples_setting() / 1e3:.0f} kSa)."
                )

            mod = self.modulation_var.get().strip().upper()
            waveform_type = self.waveform_var.get().strip()
            prbs = int(_parse_float_input(self.prbs_n_var.get(), "PRBS N"))
            fs_awg_user_hint = _parse_ghz_input(self.fs_var.get(), "AWG Fs")
            sym_rate = _parse_ghz_input(self.symbol_rate_var.get(), "Symbol Rate")
            if waveform_type == "Tone":
                if sym_rate <= 0:
                    sym_rate = 1e9
                fs_awg = float(np.clip(fs_awg_user_hint, 95.6e9, 120.0e9))
                n_per_sym = 1
                self.fs_var.set(f"{fs_awg/1e9:.6f}")
            elif sym_rate <= 0:
                raise ValueError("Symbol Rate must be positive and non-zero.")
            else:
                # M8194A can use 95.6-120 GSa/s.  The GUI AWG Fs is treated as a
                # preferred raster rate; the selected rate is constrained so
                # fs_awg = symbol_rate * integer_sps exactly.
                fs_awg, n_per_sym = self._select_awg_grid_for_symbol_rate(fs_awg_user_hint, sym_rate)
                self.fs_var.set(f"{fs_awg/1e9:.6f}")

            if_hz = _parse_ghz_input(self.if_var.get(), "IF Freq") if self.mode_var.get() == "Real IF" else 0.0
            try:
                pilot_rho = float(np.clip(float(self.pilot_rho_var.get()), 0.0, 0.95))
            except Exception:
                pilot_rho = 0.20
            try:
                tx_rrc_beta = float(np.clip(float(self.rrc_beta_var.get()), 0.01, 0.95))
            except Exception:
                tx_rrc_beta = 0.20
            n_sym_per_chirp = max(8, int(_parse_float_input(self.chirp_len_var.get(), "Symbols per Chirp")))
            requested_n_sym_per_chirp = int(n_sym_per_chirp)

            # n_per_sym and fs_awg were already chosen exactly above (fs_awg is
            # an exact integer multiple of sym_rate) -- re-deriving n_per_sym
            # here with a `max(8, ...)` floor silently overrode that for any
            # symbol rate whose only achievable nps is below 8 (e.g. 17.5 GHz
            # -> nps=6 exactly, but this used to force nps=8 while fs_awg
            # stayed at 105 GHz, so symbol_rate_actual came out as 105/8 =
            # 13.125 GHz instead of the requested 17.5 GHz).
            ts_actual = n_per_sym / fs_awg

            bps = _bits_per_symbol(mod)

            def make_prbs_qam_symbols(n_symbols: int) -> np.ndarray:
                n_symbols_i = max(1, int(n_symbols))
                bits_i = _prbs_bits_lfsr(prbs, n_symbols_i * bps)
                return _bits_to_qam_symbols(bits_i, modulation=mod)[:n_symbols_i]

            min_chirps = 4
            min_syms_required = min_chirps * n_sym_per_chirp
            prbs_syms_required = int(np.ceil(((2 ** prbs) - 1) / max(1, bps)))

            def _snap_chirps_to_if_grid(min_rows: int, syms_per_row: int) -> int:
                rows_min = max(1, int(min_rows))
                syms_per_row = max(1, int(syms_per_row))
                if if_hz <= 0 or sym_rate <= 0:
                    return rows_min
                max_rows = self._max_awg_samples_setting() // max(1, syms_per_row * n_per_sym)
                max_rows = max(rows_min, int(max_rows))
                search_stop = min(max_rows, rows_min + 2048)
                ratio = if_hz / sym_rate
                best_rows = rows_min
                best_err = float("inf")
                for rows in range(rows_min, search_stop + 1):
                    cycles = ratio * rows * syms_per_row
                    err = abs(cycles - round(cycles))
                    if err < best_err - 1e-12:
                        best_rows = rows
                        best_err = err
                        if err < 1e-12:
                            break
                return int(best_rows)

            n_chirps = max(min_chirps, int(np.ceil(prbs_syms_required / n_sym_per_chirp)))
            n_chirps = _snap_chirps_to_if_grid(n_chirps, n_sym_per_chirp)
            qam_symbols = make_prbs_qam_symbols(n_chirps * n_sym_per_chirp)
            tx_sym_matrix = qam_symbols.reshape(n_chirps, n_sym_per_chirp)

            Tc = n_sym_per_chirp * ts_actual
            t_fast = np.arange(n_sym_per_chirp * n_per_sym, dtype=np.float64) / fs_awg - Tc / 2.0
            lfm_chirp = np.exp(1j * np.pi * (sym_rate / Tc) * t_fast ** 2)

            qam_preamble_len = 0
            qam_preamble_symbols = np.zeros(0, dtype=np.complex128)
            qam_rrc_beta = tx_rrc_beta
            qam_rrc_span = 8
            qam_rrc_taps = np.array([1.0], dtype=np.float64)
            n_overhead_chirps = 0
            ce_lfm_chirp_slope_hz_per_s = 0.0
            dft_n_fft = 0
            dft_n_data = 0
            dft_active_bins = np.zeros(0, dtype=np.int64)
            dft_data_scale = np.zeros(0, dtype=np.float64)
            dft_zc_symbols = np.zeros(0, dtype=np.complex128)
            dft_zc_pilot = np.zeros(0, dtype=np.complex128)
            dft_pilot_scale = 1.0
            payload_data_symbols = 0
            tone_cycle_err = float("nan")

            if waveform_type == "Tone":
                max_tone_samples = min(self._max_awg_samples_setting(), 262144)
                tone_samples, tone_cycle_err = self._choose_tone_segment_len(
                    fs_awg, if_hz, max_tone_samples
                )
                n_chirps = 1
                n_sym_per_chirp = int(tone_samples)
                requested_n_sym_per_chirp = int(tone_samples)
                qam_symbols = np.ones(tone_samples, dtype=np.complex128)
                tx_sym_matrix = qam_symbols.reshape(1, -1)
                tx_bb_matrix = np.ones((1, tone_samples), dtype=np.complex128)
                base_chirp = np.ones(tone_samples, dtype=np.complex128)
                payload_data_symbols = 0
                if tone_cycle_err >= 1e-9:
                    self.mem_warn_var.set(
                        f"Tone length {tone_samples:,} Sa is 128-aligned; "
                        f"IF cycle err={tone_cycle_err:.2e}"
                    )
            elif waveform_type == "QAM":
                qam_preamble_len = min(64, max(16, n_sym_per_chirp // 8))
                data_len = n_sym_per_chirp - qam_preamble_len
                if data_len <= 0:
                    raise ValueError("Symbols per Chirp must be larger than preamble length for QAM mode")
                n_chirps = max(min_chirps, int(np.ceil(prbs_syms_required / data_len)))
                n_chirps = _snap_chirps_to_if_grid(n_chirps, n_sym_per_chirp)

                # Use Zadoff-Chu sequence for QAM preamble for better CFO resilience
                zc_raw = generate_zadoff_chu(qam_preamble_len, u=1)
                qam_preamble_symbols = np.asarray(zc_raw, dtype=np.complex128)

                data_needed = n_chirps * data_len
                payload_data_symbols = data_needed
                qam_data = make_prbs_qam_symbols(data_needed).reshape(n_chirps, data_len)
                tx_sym_matrix = np.concatenate([np.tile(qam_preamble_symbols, (n_chirps, 1)), qam_data], axis=1)
                qam_symbols = tx_sym_matrix.reshape(-1)

                base_chirp = np.ones_like(lfm_chirp, dtype=np.complex128)
                qam_rrc_taps = self._rrc_taps(n_per_sym, beta=qam_rrc_beta, span=qam_rrc_span)

                # Apply RRC filter to the entire sequence at once to avoid boundary discontinuities
                up_all = np.zeros(len(qam_symbols) * n_per_sym, dtype=np.complex128)
                up_all[::n_per_sym] = qam_symbols
                tx_bb_all = self._apply_fir_same(up_all, qam_rrc_taps)
                tx_bb_matrix = tx_bb_all.reshape(n_chirps, n_sym_per_chirp * n_per_sym)
            elif waveform_type == "FMCW":
                base_chirp = lfm_chirp
                tx_sym_matrix = np.ones((n_chirps, n_sym_per_chirp), dtype=np.complex128)
                qam_symbols = tx_sym_matrix.reshape(-1)
                tx_bb_matrix = np.repeat(tx_sym_matrix, n_per_sym, axis=1) * base_chirp[np.newaxis, :]
            elif waveform_type == "DFT-s-OFDM":
                # Band-limited DFT-s-OFDM with a superimposed ZC sensing pilot.
                # One block spans n_sym_per_chirp data symbols and
                # n_sym_per_chirp*sps AWG samples, so the occupied bandwidth
                # remains approximately the configured symbol rate.
                dft_n_data = int(n_sym_per_chirp)
                dft_n_fft = int(n_sym_per_chirp * n_per_sym)
                if dft_n_fft <= dft_n_data or dft_n_data < 8:
                    raise ValueError("DFT-s-OFDM requires Syms/Chirp >= 8 and samples/symbol > 1.")

                # --- BUG FIX for PRBS length ---
                # 1. Generate the true PRBS sequence of length 2^n - 1.
                prbs_len_bits = (2 ** prbs) - 1
                if prbs_len_bits > 0:
                    prbs_bits_base = _prbs_bits_lfsr(prbs, prbs_len_bits)
                else:
                    prbs_bits_base = np.array([], dtype=np.uint8)

                # 2. Calculate total bits needed and generate them by tiling the base PRBS sequence.
                #    This ensures the payload is a valid, cyclic PRBS sequence.
                needed_bits = (n_chirps * dft_n_data) * bps
                if needed_bits <= prbs_len_bits or prbs_len_bits == 0:
                    qam_bits = prbs_bits_base[:needed_bits]
                else:
                    reps = int(np.ceil(needed_bits / prbs_len_bits))
                    qam_bits = np.tile(prbs_bits_base, reps)[:needed_bits]

                qam_symbols = _bits_to_qam_symbols(qam_bits, modulation=mod)
                # --- END BUG FIX ---

                payload_data_symbols = len(qam_symbols)
                tx_sym_matrix = qam_symbols.reshape(n_chirps, dft_n_data)

                offsets = np.arange(-(dft_n_data // 2), dft_n_data - dft_n_data // 2, dtype=np.int64)
                dft_active_bins = np.mod(offsets, dft_n_fft).astype(np.int64)

                def _scfdma_time_from_symbols(symbols: np.ndarray) -> tuple[np.ndarray, float]:
                    sy = np.asarray(symbols, dtype=np.complex128).reshape(-1)
                    spread = np.fft.fft(sy) / np.sqrt(max(len(sy), 1))
                    X = np.zeros(dft_n_fft, dtype=np.complex128)
                    X[dft_active_bins] = spread
                    raw = np.fft.ifft(X)
                    scale = float(np.sqrt(np.mean(np.abs(raw) ** 2)))
                    if scale <= 1e-15:
                        scale = 1.0
                    return (raw / scale).astype(np.complex128), scale

                dft_zc_symbols = np.asarray(generate_zadoff_chu(dft_n_data, u=1), dtype=np.complex128)
                dft_zc_pilot, dft_pilot_scale = _scfdma_time_from_symbols(dft_zc_symbols)

                tx_bb_matrix = np.zeros((n_chirps, dft_n_fft), dtype=np.complex128)
                dft_data_scale = np.zeros(n_chirps, dtype=np.float64)
                sr = np.sqrt(max(0.0, pilot_rho))
                sd = np.sqrt(max(0.0, 1.0 - pilot_rho))
                for row in range(n_chirps):
                    data_time, scale_i = _scfdma_time_from_symbols(tx_sym_matrix[row])
                    dft_data_scale[row] = scale_i
                    tx_bb_matrix[row] = sr * dft_zc_pilot + sd * data_time

                base_chirp = np.ones(dft_n_fft, dtype=np.complex128)
                n_overhead_chirps = 0
            else:
                # LFM-QAM shared waveform: one continuous chirp carries the
                # selected communication constellation directly. There is no
                # TDM sensing-only chirp and no separate PSK-order override; the
                # payload modulation is exactly the GUI modulation
                # (QPSK/8PSK/16QAM/32QAM).
                shared_bps = _bits_per_symbol(mod)
                n_total_syms = max(min_syms_required, prbs_syms_required + 8)
                for _ in range(4):
                    qam_preamble_len = max(8, min(64, n_total_syms // 8))
                    needed_syms = max(min_syms_required, prbs_syms_required + qam_preamble_len)
                    if n_total_syms >= needed_syms:
                        break
                    n_total_syms = needed_syms

                qam_preamble_len = max(8, min(64, n_total_syms // 8))
                pre_bits = _prbs_bits_lfsr(7, qam_preamble_len * shared_bps)
                qam_preamble_symbols = _bits_to_qam_symbols(
                    pre_bits, modulation=mod
                )[:qam_preamble_len]

                n_data_syms = max(1, n_total_syms - qam_preamble_len)
                payload_data_symbols = n_data_syms
                data_bits = _prbs_bits_lfsr(prbs, n_data_syms * shared_bps)
                qam_data = _bits_to_qam_symbols(data_bits, modulation=mod)[:n_data_syms]

                qam_symbols = np.concatenate([qam_preamble_symbols, qam_data])
                n_total_syms = len(qam_symbols)
                symbol_wave = np.repeat(qam_symbols, n_per_sym)

                Tc_full = n_total_syms * ts_actual
                t_full = np.arange(n_total_syms * n_per_sym, dtype=np.float64) / fs_awg - Tc_full / 2.0
                chirp_slope_hz_per_s = sym_rate / Tc_full
                base_chirp = np.exp(1j * np.pi * chirp_slope_hz_per_s * t_full ** 2)
                ce_lfm_chirp_slope_hz_per_s = float(chirp_slope_hz_per_s)

                tx_baseband_shared = base_chirp * symbol_wave
                tx_bb_matrix = tx_baseband_shared.reshape(1, -1)
                tx_sym_matrix = qam_symbols.reshape(1, -1)

                n_chirps = 1
                n_sym_per_chirp = n_total_syms
                n_overhead_chirps = 0

            tx_baseband = tx_bb_matrix.reshape(-1)
            iqtools_carrier_cycles = 0
            iqtools_if_freq = 0.0
            if if_hz > 0 and fs_awg > 0 and len(tx_baseband) > 0:
                # Keysight IQTools quantizes carrierOffset to an integer number
                # of cycles over the waveform record.  Generate and demodulate
                # with this grid-snapped IF to keep the AWG segment periodic.
                iqtools_carrier_cycles = int(round(len(tx_baseband) * if_hz / fs_awg))
                iqtools_if_freq = iqtools_carrier_cycles * fs_awg / len(tx_baseband)
            if_hz_awg = iqtools_if_freq if if_hz > 0 and iqtools_if_freq > 0 else if_hz

            if self.mode_var.get() == "IQ":
                awg_sig = normalize_iq_for_awg(tx_baseband)
            else:
                t = np.arange(len(tx_baseband), dtype=np.float64) / fs_awg
                real_if = np.real(tx_baseband * np.exp(1j * 2.0 * np.pi * if_hz_awg * t))
                awg_sig = normalize_real_for_awg(real_if)

            try:
                awg_ch1_power_dbm = float(self.power_dbm_var.get())
            except Exception:
                awg_ch1_power_dbm = float("nan")
            try:
                awg_ch1_vpp = float(self.vpp_ch1_var.get())
            except Exception:
                awg_ch1_vpp = float("nan")
            try:
                awg_ch2_vpp = float(self.vpp_ch2_var.get())
            except Exception:
                awg_ch2_vpp = float("nan")

            payload = {
                "tx_signal": tx_baseband,
                "awg_sig": awg_sig,
                "fs": fs_awg,
                "qam_symbols": qam_symbols,
                "tx_sym_matrix": tx_sym_matrix,
                "tx_bb_matrix": tx_bb_matrix,
                "base_chirp": base_chirp,
                "symbol_rate": sym_rate,
                "symbol_rate_actual": sym_rate if waveform_type == "Tone" else fs_awg / n_per_sym,
                "if_freq": if_hz_awg,
                "if_freq_requested": if_hz,
                "iqtools_if_freq": iqtools_if_freq,
                "iqtools_carrier_cycles": iqtools_carrier_cycles,
                "modulation": mod,
                "waveform_type": waveform_type,
                "awg_ch1_power_dbm": awg_ch1_power_dbm,
                "awg_ch1_vpp": awg_ch1_vpp,
                "awg_ch2_vpp": awg_ch2_vpp,
                "prbs_n": prbs,
                "qam_preamble_len": qam_preamble_len,
                "qam_preamble_symbols": qam_preamble_symbols,
                "qam_rrc_beta": qam_rrc_beta,
                "qam_rrc_span": qam_rrc_span,
                "qam_rrc_taps": qam_rrc_taps,
                "mode": self.mode_var.get(),
                "fc": _parse_ghz_input(self.rf_var.get(), "RF Freq"),
                "c0": 3e8,
                "B": sym_rate,
                "Ts": ts_actual,
                "sps": n_per_sym,
                "awg_segment_len_samples": int(len(awg_sig)),
                "awg_segment_granularity": 128,
                "tone_cycle_error": tone_cycle_err,
                "n_chirps": n_chirps,
                "n_sym_per_chirp": n_sym_per_chirp,
                "requested_n_sym_per_chirp": requested_n_sym_per_chirp,
                "n_overhead_chirps": n_overhead_chirps,
                "ce_lfm_chirp_slope_hz_per_s": ce_lfm_chirp_slope_hz_per_s,
                "dft_n_fft": dft_n_fft,
                "dft_n_data": dft_n_data,
                "dft_active_bins": dft_active_bins,
                "dft_data_scale": dft_data_scale,
                "dft_zc_symbols": dft_zc_symbols,
                "dft_zc_pilot": dft_zc_pilot,
                "dft_pilot_scale": dft_pilot_scale,
                "prbs_bits_target": int((2 ** prbs) - 1),
                "payload_data_symbols": int(payload_data_symbols),
                "payload_data_bits": int(payload_data_symbols * bps),
                "amplitude_ratio_rho": pilot_rho if waveform_type == "DFT-s-OFDM" else np.nan,
            }

            # Save implicit reference for live processing if needed
            out_path = APP_DIR / "data" / "current_tx_ref.npz"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(out_path, **{k: np.asarray(v) if isinstance(v, (list, np.ndarray)) else np.array([v]) for k,v in payload.items()})
            return payload

        def _is_tx_payload_stale(self, ctx: dict) -> bool:
            try:
                cur_wave = self.waveform_var.get().strip()
                cur_mod = self.modulation_var.get().strip().upper()
                cur_mode = self.mode_var.get().strip()
                cur_prbs = int(_parse_float_input(self.prbs_n_var.get(), "PRBS N"))
                cur_nsym = max(8, int(_parse_float_input(self.chirp_len_var.get(), "Symbols per Chirp")))
                cur_fs = _parse_ghz_input(self.fs_var.get(), "AWG Fs")
                cur_sr = _parse_ghz_input(self.symbol_rate_var.get(), "Symbol Rate")
                cur_if = _parse_ghz_input(self.if_var.get(), "IF Freq") if cur_mode == "Real IF" else 0.0
                cur_rho = float(np.clip(float(self.pilot_rho_var.get()), 0.0, 0.95))
                cur_beta = float(np.clip(float(self.rrc_beta_var.get()), 0.01, 0.95))
            except Exception:
                return True

            if str(ctx.get("waveform_type", "LFM-QAM")).strip() != cur_wave:
                return True
            if str(ctx.get("modulation", "16QAM")).strip().upper() != cur_mod:
                return True
            if str(ctx.get("mode", "Real IF")).strip() != cur_mode:
                return True
            if int(ctx.get("prbs_n", -1)) != cur_prbs:
                return True
            try:
                target_bits = int((2 ** cur_prbs) - 1)
                payload_bits = int(ctx.get("payload_data_bits", 0))
                if payload_bits < target_bits and cur_wave != "FMCW":
                    return True
            except Exception:
                return True
            ctx_requested_nsym = int(ctx.get("requested_n_sym_per_chirp", ctx.get("n_sym_per_chirp", -1)))
            if ctx_requested_nsym != cur_nsym:
                return True
            if int(ctx.get("sps", -1)) <= 0:
                return True

            fs_old = float(ctx.get("fs", -1.0))
            sr_old = float(ctx.get("symbol_rate", -1.0))
            if_old = float(ctx.get("if_freq_requested", ctx.get("if_freq", 0.0)))
            if abs(fs_old - cur_fs) > 1e-6 * max(cur_fs, 1.0):
                return True
            if abs(sr_old - cur_sr) > 1e-6 * max(cur_sr, 1.0):
                return True
            if abs(if_old - cur_if) > 1e-6 * max(abs(cur_if), 1.0):
                return True
            beta_old = float(ctx.get("qam_rrc_beta", np.nan))
            if not np.isfinite(beta_old) or abs(beta_old - cur_beta) > 1e-6:
                return True
            if cur_wave == "DFT-s-OFDM":
                rho_old = float(ctx.get("amplitude_ratio_rho", np.nan))
                if not np.isfinite(rho_old) or abs(rho_old - cur_rho) > 1e-6:
                    return True

            return False

        def _on_generate(self) -> None:
            def worker():
                try:
                    payload = self._generate_tx_signal()
                    self.runtime["tx_payload"] = payload
                    if callable(self.on_tx_generated):
                        self.parent.after(0, lambda: self.on_tx_generated(str(APP_DIR / "data" / "current_tx_ref.npz")))
                    n_samples = len(payload['awg_sig'])
                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("Generate Error", m))
            threading.Thread(target=worker, daemon=True).start()

        def _on_download(self) -> None:
            def worker():
                try:
                    # Always generate anew when "To AWG" is clicked
                    payload = self._generate_tx_signal()
                    self.runtime["tx_payload"] = payload
                    if callable(self.on_tx_generated):
                        self.parent.after(0, lambda: self.on_tx_generated(str(APP_DIR / "data" / "current_tx_ref.npz")))

                    pl = self.runtime["tx_payload"]
                    addr = f"TCPIP0::{self.ip_var.get().strip()}::{int(self.port_var.get())}::SOCKET"

                    channels_list = parse_channels(self.ch_var.get())
                    if not channels_list:
                        channels_list = [1, 2]
                    download_to_awg(
                        awg_sig=np.asarray(pl["awg_sig"]),
                        channels=channels_list,
                        awg_addr=addr,
                        fs=float(pl["fs"]),
                        vpp=self._vpp_by_channel(channels_list),
                    )
                    self.parent.after(0, lambda: messagebox.showinfo("Success", "Download to AWG Complete!"))
                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("Download Error", m))
            threading.Thread(target=worker, daemon=True).start()

        def _on_power_changed(self, *_) -> None:
            if self._updating_vpp:
                return
            self._updating_power = True
            try:
                p_dbm = float(self.power_dbm_var.get())
                p_w = 10.0 ** (p_dbm / 10.0) * 1e-3
                vpp = 20.0 * np.sqrt(max(p_w, 0.0))
                self.vpp_var.set(f"{vpp:.4f}")
            except Exception:
                pass
            finally:
                self._updating_power = False

        def _on_vpp_changed(self, *_) -> None:
            if self._updating_power:
                return
            self._updating_vpp = True
            try:
                vpp = float(self.vpp_var.get())
                if vpp > 0:
                    p_w = (vpp ** 2) / 400.0
                    p_dbm = 10.0 * np.log10(p_w / 1e-3)
                    self.power_dbm_var.set(f"{p_dbm:.2f}")
                else:
                    self.power_dbm_var.set("")
            except Exception:
                pass
            finally:
                self._updating_vpp = False

        def _on_awg_run(self) -> None:
            def worker():
                try:
                    addr = f"TCPIP0::{self.ip_var.get().strip()}::{int(self.port_var.get())}::SOCKET"
                    channels_list = parse_channels(self.ch_var.get())
                    if not channels_list:
                        channels_list = [1, 2]
                    vpp_map = self._vpp_by_channel(channels_list)
                    run_awg(awg_addr=addr, channels=channels_list, vpp=vpp_map)
                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("AWG Run Error", m))
            threading.Thread(target=worker, daemon=True).start()

        def _on_awg_off(self) -> None:
            def worker():
                try:
                    addr = f"TCPIP0::{self.ip_var.get().strip()}::{int(self.port_var.get())}::SOCKET"
                    stop_awg(awg_addr=addr, channels=[1, 2, 3, 4])
                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("AWG Stop Error", m))
            threading.Thread(target=worker, daemon=True).start()

        # --- Simulation Logic ---

        @staticmethod
        def _dbm_to_w(p_dbm: float) -> float: return 1e-3 * (10 ** (p_dbm / 10.0))

        @staticmethod
        def _fspl_db(distance_m: float, rf_hz: float) -> float:
            return 20.0 * np.log10(4.0 * np.pi * max(distance_m, 1e-6) * rf_hz / 3e8)

        def _noise_dbm(self, symbol_rate: float) -> tuple[float, str]:
            nf_db = _parse_float_input(self.nf_var.get(), "Noise Figure")
            bw_hz = max(symbol_rate * 1.2, 1.0)
            return -174.0 + 10.0 * np.log10(bw_hz) + nf_db, f"from_nf (B={bw_hz:.3e} Hz, NF={nf_db:.2f} dB)"

        def _scope_profile(self, scope_model: str) -> tuple[float, float]:
            if "UXR" in scope_model: return 40e9, 256e9
            if "LeCroy" in scope_model: return 59e9, 160e9
            return 59e9, 160e9

        def _calculate_total_noise(self, pr_comm_dbm: float, symbol_rate: float, scope_model: str, rx_gain_db: float) -> tuple[float, dict]:
            gain_lin = 10.0 ** (rx_gain_db / 10.0)
            p_w = self._dbm_to_w(pr_comm_dbm + rx_gain_db)
            v_rms_sig = np.sqrt(max(p_w, 1e-30) * 50.0)
            ideal = max((2.0 * np.sqrt(2.0) * v_rms_sig) / 8.0 * 1.3, 1e-6)
            decade = 10.0 ** np.floor(np.log10(ideal))
            choices = np.array([1.0, 2.0, 5.0, 10.0])
            idx = int(np.argmin(np.abs(choices - (ideal / decade))))
            recommended_vdiv = float(choices[idx] * decade)
            fs_v = recommended_vdiv * 8.0

            if "UXR" in scope_model:
                scope_bw_hz = 40e9
                fs_v_array = np.array([0.060, 0.100, 0.160, 0.400, 0.800, 1.6, 4.0])
                vrms_v_array = np.array([0.34e-3, 0.49e-3, 0.72e-3, 1.6e-3, 3.4e-3, 6.7e-3, 16e-3])
            else:
                scope_bw_hz = 59e9
                scale_factor = 3.1e-3 / 1.6e-3
                fs_v_array = np.array([0.060, 0.100, 0.160, 0.400, 0.800, 1.6, 4.0])
                vrms_v_array = np.array([0.34e-3, 0.49e-3, 0.72e-3, 1.6e-3, 3.4e-3, 6.7e-3, 16e-3]) * scale_factor

            scope_vrms = float(np.interp(fs_v, fs_v_array, vrms_v_array))
            bw_sig_hz = max(symbol_rate * 1.2, 1.0)
            dso_total_noise_w = (scope_vrms**2) / 50.0
            dso_noise_in_band_w = dso_total_noise_w * (bw_sig_hz / scope_bw_hz)

            thermal_noise_dbm, _ = self._noise_dbm(symbol_rate)
            thermal_noise_w = self._dbm_to_w(thermal_noise_dbm) * gain_lin

            total_noise_w = thermal_noise_w + dso_noise_in_band_w
            total_noise_dbm = 10.0 * np.log10(total_noise_w / 1e-3)
            dso_noise_floor_dbm_hz = 10.0 * np.log10(max(dso_total_noise_w / max(scope_bw_hz, 1.0), 1e-30) / 1e-3)
            dso_noise_40g_dbm = dso_noise_floor_dbm_hz + 10.0 * np.log10(40e9)
            _, scope_fs_hz = self._scope_profile(scope_model)

            info = {
                "recommended_vdiv": recommended_vdiv,
                "scope_vrms": scope_vrms,
                "dso_noise_dbm": 10.0 * np.log10(max(dso_noise_in_band_w, 1e-30) / 1e-3),
                "thermal_noise_dbm": thermal_noise_dbm,
                "thermal_noise_dbm_at_dso": 10.0 * np.log10(max(thermal_noise_w, 1e-30) / 1e-3),
                "total_noise_dbm": total_noise_dbm,
                "scope_bw_hz": scope_bw_hz,
                "scope_fs_hz": scope_fs_hz,
                "dso_noise_floor_dbm_hz": dso_noise_floor_dbm_hz,
                "dso_noise_40g_dbm": dso_noise_40g_dbm,
                "rx_gain_db": rx_gain_db,
            }
            return total_noise_dbm, info

        @staticmethod
        def _lowpass_complex_fft(sig: np.ndarray, fs: float, cutoff_hz: float) -> np.ndarray:
            x = np.asarray(sig, dtype=np.complex128)
            if len(x) == 0: return x
            freq = np.fft.fftfreq(len(x), d=1.0 / fs)
            X = np.fft.fft(x)
            X[np.abs(freq) > cutoff_hz] = 0.0
            return np.fft.ifft(X)

        @staticmethod
        def _single_sided_spectrum(sig: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
            x = np.asarray(sig, dtype=np.float64)
            if len(x) == 0: return np.array([0.0]), np.array([-300.0])
            w = np.hanning(len(x))
            return np.fft.rfftfreq(len(x), d=1.0/fs), 20.0 * np.log10(np.abs(np.fft.rfft(x * w)) / (np.sum(w) + 1e-15) + 1e-15)

        @staticmethod
        def _two_sided_spectrum(sig: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
            x = np.asarray(sig, dtype=np.complex128)
            if len(x) == 0: return np.array([0.0]), np.array([-300.0])
            w = np.hanning(len(x))
            return np.fft.fftshift(np.fft.fftfreq(len(x), d=1.0/fs)), 20.0 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(x * w))) / (np.sum(w) + 1e-15) + 1e-15)

        def _set_kpi_rows(self, left_rows: list, right_rows: list) -> None:
            for item in self.kpi_table.get_children(): self.kpi_table.delete(item)
            for i in range(max(len(left_rows), len(right_rows))):
                lm, lv, lu = left_rows[i] if i < len(left_rows) else ("", "", "")
                rm, rv, ru = right_rows[i] if i < len(right_rows) else ("", "", "")
                fmt = lambda v: "nan" if isinstance(v, float) and not np.isfinite(v) else (f"{v:.3e}" if isinstance(v, float) and (abs(v)>=1e4 or 0<abs(v)<1e-3) else (f"{v:.6g}" if isinstance(v, float) else str(v)))
                self.kpi_table.insert("", tk.END, values=(lm, fmt(lv) if lv != "--" else "--", lu, rm, fmt(rv) if rv != "--" else "--", ru), tags=("even" if i % 2 == 0 else "odd",))

        def _draw_placeholder(self) -> None:
            self.fig.clear(); ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, "Press 'Time/Spectrum' or 'Demod.'", ha="center", va="center", fontsize=10)
            ax.set_axis_off(); self.canvas.draw_idle()

        @staticmethod
        def _time_unit_scale(t_max: float) -> tuple[float, str]: return (1e9, "ns") if t_max < 1e-6 else ((1e6, "us") if t_max < 1e-3 else (1e3, "ms"))

        @staticmethod
        def _freq_unit_scale(f_max: float) -> tuple[float, str]: return (1e-9, "GHz") if f_max >= 1e9 else ((1e-6, "MHz") if f_max >= 1e6 else ((1e-3, "kHz") if f_max >= 1e3 else (1.0, "Hz")))

        @staticmethod
        def _sinr_target_ber_1e3(modulation: str, impl_margin_db: float = 0.0) -> float:
            m = str(modulation).strip().upper()
            # Uncoded AWGN rule-of-thumb targets for BER ~= 1e-3.
            if m == "QPSK":
                base = 10.0
            elif m == "8PSK":
                base = 14.0
            elif m == "16QAM":
                base = 17.0
            elif m == "32QAM":
                base = 21.0
            else:
                base = 17.0
            return float(base + max(0.0, impl_margin_db))

        @staticmethod
        def _rrc_taps(sps: int, beta: float = 0.20, span: int = 8) -> np.ndarray:
            sps_i = max(2, int(sps))
            b = float(np.clip(beta, 1e-3, 0.99))
            sp = max(4, int(span))
            n = np.arange(-sp * sps_i, sp * sps_i + 1, dtype=np.float64)
            t = n / sps_i

            h = np.zeros_like(t)
            for i, tt in enumerate(t):
                if abs(tt) < 1e-12:
                    h[i] = 1.0 + b * (4.0 / np.pi - 1.0)
                    continue
                if abs(abs(tt) - 1.0 / (4.0 * b)) < 1e-10:
                    h[i] = (b / np.sqrt(2.0)) * (
                        (1.0 + 2.0 / np.pi) * np.sin(np.pi / (4.0 * b))
                        + (1.0 - 2.0 / np.pi) * np.cos(np.pi / (4.0 * b))
                    )
                    continue
                num = np.sin(np.pi * tt * (1.0 - b)) + 4.0 * b * tt * np.cos(np.pi * tt * (1.0 + b))
                den = np.pi * tt * (1.0 - (4.0 * b * tt) ** 2)
                h[i] = num / (den + 1e-15)

            h = h / np.sqrt(np.sum(h ** 2) + 1e-15)
            return h.astype(np.float64)

        @staticmethod
        def _apply_fir_same(x: np.ndarray, h: np.ndarray) -> np.ndarray:
            xr = np.asarray(x, dtype=np.complex128)
            hr = np.asarray(h, dtype=np.float64)
            return np.convolve(xr, hr, mode="same")

        @staticmethod
        def _interp_complex(x: np.ndarray, idx: float) -> complex:
            i0 = int(np.floor(idx))
            if i0 < 0:
                return complex(x[0])
            if i0 >= len(x) - 1:
                return complex(x[-1])
            frac = idx - i0
            return complex((1.0 - frac) * x[i0] + frac * x[i0 + 1])

        @staticmethod
        def _cfo_compensate(signal: np.ndarray, cfo_hz: float, fs: float) -> np.ndarray:
            """Applies CFO correction to a signal."""
            t = np.arange(len(signal)) / fs
            cfo_corr = np.exp(-1j * 2 * np.pi * cfo_hz * t)
            return signal * cfo_corr

        @classmethod
        def _cfo_grid_search(
            cls,
            signal: np.ndarray,
            template: np.ndarray,
            fs: float,
            search_range_hz: float,
            num_steps: int = 41,
        ) -> tuple[float, float]:
            """
            Estimates CFO by finding the frequency offset that maximizes correlation.
            Returns the estimated CFO in Hz and the max correlation value.
            """
            if not np.any(signal) or not np.any(template):
                return 0.0, 0.0

            freq_offsets = np.linspace(-search_range_hz, search_range_hz, num_steps)
            max_corr_val = -1.0
            best_cfo = 0.0

            search_len = min(len(signal), len(template) * 3)
            sig_segment = signal[:search_len]

            from scipy.signal import correlate

            for cfo_hz in freq_offsets:
                sig_corrected = cls._cfo_compensate(sig_segment, cfo_hz, fs)
                corr = correlate(sig_corrected, template, mode="valid", method="fft")
                current_max = np.max(np.abs(corr))
                if current_max > max_corr_val:
                    max_corr_val = current_max
                    best_cfo = cfo_hz

            return best_cfo, max_corr_val

        @classmethod
        def _gardner_timing_recovery(
            cls,
            samples: np.ndarray,
            sps: int,
            n_symbols: int,
            gain: float = 0.01,
            start_offset: float | None = None,
        ) -> np.ndarray:
            x = np.asarray(samples, dtype=np.complex128).reshape(-1)
            if len(x) < 4 * max(2, sps):
                return np.zeros(0, dtype=np.complex128)

            sps_f = float(max(2, sps))
            omega = sps_f
            mu = 0.0
            t = 2.0 * sps_f if start_offset is None else float(start_offset)
            t = max(t, sps_f + 1.0)
            out = []

            while t + sps_f < len(x) - 2 and len(out) < n_symbols:
                x_now = cls._interp_complex(x, t + mu)
                x_mid = cls._interp_complex(x, t + mu - 0.5 * sps_f)
                x_prev = cls._interp_complex(x, t + mu - sps_f)
                err = np.real((x_prev - x_now) * np.conj(x_mid))

                out.append(x_now)

                omega = np.clip(omega + gain * err, 0.8 * sps_f, 1.2 * sps_f)
                mu += omega
                t += np.floor(mu)
                mu -= np.floor(mu)

            return np.asarray(out, dtype=np.complex128)

        def _build_simulated_rx(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, dict]:
            if "tx_payload" not in self.runtime:
                self.runtime["tx_payload"] = self._generate_tx_signal()
            elif self._is_tx_payload_stale(self.runtime["tx_payload"]):
                self.runtime["tx_payload"] = self._generate_tx_signal()

            ctx = self.runtime["tx_payload"]
            tx_bb_sim = ctx["tx_signal"]
            fs_sim = ctx["fs"]
            rs = float(ctx["symbol_rate"])
            f_if = _parse_ghz_input(self.if_var.get(), "IF Freq")
            tx_mode = ctx["mode"]

            scope_model = str(self.scope_model_var.get()).strip()
            _, fs_scope = self._scope_profile(scope_model)

            d = _parse_float_input(self.dist_var.get(), "Distance")
            rf_hz = _parse_ghz_input(self.rf_var.get(), "RF Frequency")
            vel_mps = _parse_float_input(self.vel_var.get(), "Target Velocity")
            txp_dbm = _parse_float_input(self.txp_var.get(), "TX Power")
            sigma = _parse_float_input(self.rcs_var.get(), "Sensing RCS sigma")
            ant_gain = _parse_float_input(self.ant_gain_var.get(), "Antenna Gain")
            rx_gain_db = _parse_float_input(self.rx_gain_var.get(), "RX IF Gain")
            antenna_sic_db = _parse_float_input(self.antenna_sic_var.get(), "OMT Isolation")
            sic_dsp_enabled = bool(self.sic_dsp_var.get())
            sic_mode = str(self.sic_mode_var.get()).strip()
            si_enabled = bool(self.si_enable_var.get())
            sic_taps = max(3, int(_parse_float_input(self.sic_taps_var.get(), "SIC taps")))
            sic_mu = max(1e-4, _parse_float_input(self.sic_mu_var.get(), "SIC mu"))
            sic_lambda = float(np.clip(_parse_float_input(self.sic_lambda_var.get(), "RLS lambda"), 0.90, 0.99999))

            c0 = 3e8
            tau = 2.0 * d / c0
            lam = c0 / rf_hz
            fd_hz = 2.0 * vel_mps / max(lam, 1e-15)
            delay_samples = int(round(tau * fs_sim))
            path_loss_db = self._fspl_db(d, rf_hz)

            pr_comm_dbm = txp_dbm + 2.0 * ant_gain - path_loss_db
            pr_radar_dbm = txp_dbm + 2.0 * ant_gain + 20.0 * np.log10(lam) + 10.0 * np.log10(sigma) - 30.0 * np.log10(4.0 * np.pi) - 40.0 * np.log10(max(d, 1e-6))
            pr_comm_dbm_dso = pr_comm_dbm + rx_gain_db

            pr_comm_w = self._dbm_to_w(pr_comm_dbm)
            gain_lin = 10.0 ** (rx_gain_db / 10.0)
            p_current_w = float(np.mean(np.abs(tx_bb_sim) ** 2) / 50.0) + 1e-30
            scale_rx = np.sqrt((pr_comm_w * gain_lin) / p_current_w)
            rx_vrms_expected = np.sqrt(max(pr_comm_w * gain_lin, 1e-30) * 50.0)

            # Fractional-delay channel model avoids coarse integer-sample range quantization.
            n = len(tx_bb_sim)
            nfft = 1
            while nfft < 2 * n:
                nfft *= 2
            freq = np.fft.fftfreq(nfft, d=1.0 / fs_sim)
            delayed = np.fft.ifft(np.fft.fft(tx_bb_sim, nfft) * np.exp(-1j * 2.0 * np.pi * freq * tau))[:n]
            t_sim = np.arange(n, dtype=np.float64) / fs_sim
            rx_bb_sim = delayed * scale_rx
            rx_bb_sim *= np.exp(1j * 2.0 * np.pi * fd_hz * t_sim)
            rx_bb_sim *= np.exp(-1j * 2.0 * np.pi * (rf_hz + f_if) * tau)

            si_info = {
                "enabled": si_enabled,
                "antenna_sic_db": antenna_sic_db,
                "si_power_dbm_antenna": txp_dbm - antenna_sic_db if si_enabled else -300.0,
                "si_power_dbm_at_dso": -300.0,
                "comm_power_dbm_at_dso": pr_comm_dbm_dso,
                "comm_power_dbm_omt": pr_comm_dbm,
                "lna_input_dbm": float("nan"),
                "si_to_comm_db": -300.0,
                "sinr_pre_db": float("nan"),
                "sinr_post_db": float("nan"),
                "sinr_gain_db": float("nan"),
                "si_power_pre_dbm": float("nan"),
                "si_power_post_dbm": float("nan"),
                "si_reduction_db": float("nan"),
                "impair_pre_dbm": float("nan"),
                "impair_post_dbm": float("nan"),
                "dsp_sic_enabled": sic_dsp_enabled,
                "dsp_mode": sic_mode,
                "dsp_sic_db": 0.0,
                "dsp_sic_total_db": 0.0,
                "dsp_sic_db_si_only": 0.0,
                "dsp_lag_samples": 0,
                "dsp_alpha_mag": 0.0,
                "dsp_input_dbm": float("nan"),
                "dsp_output_dbm": float("nan"),
            }
            if si_enabled:
                # OMT leakage model: a fraction of TX leaks into OMT RX port before LNA/mixer.
                p_si_target_dbm = txp_dbm - max(0.0, antenna_sic_db) + rx_gain_db
                p_si_target_w = self._dbm_to_w(p_si_target_dbm)
                p_si_raw_w = float(np.mean(np.abs(tx_bb_sim) ** 2) / 50.0) + 1e-30
                si_leak = np.asarray(tx_bb_sim, dtype=np.complex128) * np.sqrt(p_si_target_w / p_si_raw_w)

                si_info["si_power_dbm_at_dso"] = 10.0 * np.log10(max(np.mean(np.abs(si_leak) ** 2) / 50.0, 1e-30) / 1e-3)
                si_info["si_to_comm_db"] = si_info["si_power_dbm_at_dso"] - pr_comm_dbm_dso
            else:
                si_leak = np.zeros_like(rx_bb_sim)

            p_comm_omt_w = self._dbm_to_w(pr_comm_dbm)
            p_si_omt_w = self._dbm_to_w(txp_dbm - max(0.0, antenna_sic_db)) if si_enabled else 0.0
            si_info["lna_input_dbm"] = float(10.0 * np.log10(max((p_comm_omt_w + p_si_omt_w) / 1e-3, 1e-30)))

            # Front-end input is the sum of received signal and leaked SI (before digital RX stages).
            rx_bb_combined = rx_bb_sim + si_leak

            total_noise_dbm, noise_info = self._calculate_total_noise(pr_comm_dbm, rs, scope_model, rx_gain_db)

            total_noise_w = self._dbm_to_w(total_noise_dbm) * (fs_sim / max(rs, 1.0))
            sigma_v = np.sqrt(total_noise_w * 50.0)
            rng = np.random.default_rng()
            noise_vec = (sigma_v / np.sqrt(2.0)) * (rng.standard_normal(len(rx_bb_combined)) + 1j * rng.standard_normal(len(rx_bb_combined)))
            rx_bb_noisy = rx_bb_combined + noise_vec

            p_sig = float(np.mean(np.abs(rx_bb_sim) ** 2) / 50.0 + 1e-30)
            p_si_pre = float(np.mean(np.abs(si_leak) ** 2) / 50.0 + 1e-30)
            p_noise = float(np.mean(np.abs(noise_vec) ** 2) / 50.0 + 1e-30)
            p_imp_pre = float(np.mean(np.abs((rx_bb_combined + noise_vec) - rx_bb_sim) ** 2) / 50.0 + 1e-30)
            sinr_pre_db = float(10.0 * np.log10(p_sig / p_imp_pre))
            si_info["sinr_pre_db"] = sinr_pre_db
            si_info["si_power_pre_dbm"] = float(10.0 * np.log10(max(p_si_pre / 1e-3, 1e-30)))
            si_info["impair_pre_dbm"] = float(10.0 * np.log10(max(p_imp_pre / 1e-3, 1e-30)))

            if si_enabled and sic_dsp_enabled:
                n_per_sym = int(ctx.get("sps", max(1, int(round(fs_sim / max(rs, 1.0))))))
                lag_search = max(32, min(4096, 4 * n_per_sym))
                tx_ref = np.asarray(tx_bb_sim, dtype=np.complex128)
                if sic_mode == "Linear RLS":
                    adapt_len = max(sic_taps + 8, int(delay_samples) - 2 * sic_taps)
                    if adapt_len >= len(rx_bb_noisy):
                        adapt_len = None
                    rx_bb_noisy, sic_metrics = apply_linear_rls_sic(
                        rx_signal=rx_bb_noisy,
                        tx_ref=tx_ref,
                        num_taps=sic_taps,
                        lam=sic_lambda,
                        max_lag=lag_search,
                        adapt_len=adapt_len,
                    )
                    si_after, sic_metrics_si_only = apply_linear_rls_sic(
                        rx_signal=si_leak,
                        tx_ref=tx_ref,
                        num_taps=sic_taps,
                        lam=sic_lambda,
                        max_lag=lag_search,
                        adapt_len=adapt_len,
                    )
                else:
                    adapt_len_nl = max(sic_taps + 8, int(delay_samples) - 2 * sic_taps)
                    if adapt_len_nl >= len(rx_bb_noisy):
                        adapt_len_nl = None
                    rx_bb_noisy, sic_metrics = apply_cross_polarization_sic(
                        rx_signal=rx_bb_noisy,
                        tx_ref=tx_ref,
                        num_taps=sic_taps,
                        mu=sic_mu,
                        lam=sic_lambda,
                        max_lag=lag_search,
                        adapt_len=adapt_len_nl,
                    )
                    si_after, sic_metrics_si_only = apply_cross_polarization_sic(
                        rx_signal=si_leak,
                        tx_ref=tx_ref,
                        num_taps=sic_taps,
                        mu=sic_mu,
                        lam=sic_lambda,
                        max_lag=lag_search,
                        adapt_len=adapt_len_nl,
                    )
                sic_db = float(sic_metrics.get("sic_db", 0.0))
                sic_total_db = float(sic_metrics.get("sic_db_total", 0.0))
                sic_si_only_db = float(sic_metrics_si_only.get("sic_db", 0.0))
                if not np.isfinite(sic_db):
                    sic_db = 0.0
                if not np.isfinite(sic_total_db):
                    sic_total_db = 0.0
                if not np.isfinite(sic_si_only_db):
                    sic_si_only_db = 0.0
                si_info["dsp_sic_db"] = sic_db
                si_info["dsp_sic_total_db"] = sic_total_db
                si_info["dsp_sic_db_si_only"] = sic_si_only_db
                si_info["dsp_lag_samples"] = int(sic_metrics.get("lag_samples", 0))
                si_info["dsp_alpha_mag"] = float(sic_metrics.get("alpha_mag", 0.0))
                si_info["dsp_input_dbm"] = 10.0 * np.log10(max(float(sic_metrics.get("input_power", 0.0)) / 1e-3, 1e-30))
                si_info["dsp_output_dbm"] = 10.0 * np.log10(max(float(sic_metrics.get("output_power", 0.0)) / 1e-3, 1e-30))

                p_si_post = float(np.mean(np.abs(si_after) ** 2) / 50.0 + 1e-30)
                si_info["si_power_post_dbm"] = float(10.0 * np.log10(max(p_si_post / 1e-3, 1e-30)))
                si_info["si_reduction_db"] = float(10.0 * np.log10(max(p_si_pre / p_si_post, 1e-30)))

            p_imp_post = float(np.mean(np.abs(rx_bb_noisy - rx_bb_sim) ** 2) / 50.0 + 1e-30)
            sinr_post_db = float(10.0 * np.log10(p_sig / p_imp_post))
            si_info["sinr_post_db"] = sinr_post_db
            si_info["sinr_gain_db"] = float(sinr_post_db - si_info["sinr_pre_db"])
            si_info["impair_post_dbm"] = float(10.0 * np.log10(max(p_imp_post / 1e-3, 1e-30)))

            if tx_mode == "Real IF":
                rx_raw_sim = np.real(rx_bb_noisy * np.exp(1j * 2.0 * np.pi * f_if * t_sim))
            else:
                rx_raw_sim = rx_bb_noisy

            if not np.isclose(fs_sim, fs_scope):
                if tx_mode == "Real IF":
                    rx_raw_scope = np.real(fft_resample_complex(rx_raw_sim, fs_in=fs_sim, fs_out=fs_scope))
                else:
                    rx_raw_scope = fft_resample_complex(rx_raw_sim, fs_in=fs_sim, fs_out=fs_scope)
            else:
                rx_raw_scope = rx_raw_sim

            fs = fs_scope
            t = np.arange(len(rx_raw_scope), dtype=np.float64) / fs
            if tx_mode == "Real IF":
                #
                rx_mixed = rx_raw_scope * np.exp(-1j * 2.0 * np.pi * f_if * t) * 2.0
                #
                rx_bb_view = self._lowpass_complex_fft(rx_mixed, fs=fs, cutoff_hz=1.2 * rs)
            else:
                rx_bb_view = rx_raw_scope

            meta = {
                **ctx,
                "delay_samples_sim": delay_samples, "fs_sim": fs_sim, "fs_scope": fs,
                "noise_info": noise_info, "pr_comm_dbm": pr_comm_dbm, "pr_radar_dbm": pr_radar_dbm,
                "tx_power_dbm": txp_dbm, "f_if_demod": f_if if tx_mode == "Real IF" else 0.0,
                "rx_for_demod": rx_raw_scope, "scope_model": scope_model,
                "fd_hz": fd_hz,
                "path_loss_db": path_loss_db,
                "rx_vrms_expected": rx_vrms_expected,
                "pr_comm_dbm_dso": pr_comm_dbm_dso,
                "rx_gain_db": rx_gain_db,
                "si_info": si_info,
                "tx_raw_scope": np.real(tx_bb_sim * np.exp(1j * 2.0 * np.pi * f_if * t_sim)) if tx_mode == "Real IF" else np.asarray(tx_bb_sim),
                "tx_bb_scope": np.asarray(tx_bb_sim),
            }
            return t, np.asarray(rx_raw_scope), np.asarray(rx_bb_view), fs, meta

        def _render_quadrant(
            self,
            t: np.ndarray,
            y_raw: np.ndarray,
            y_bb: np.ndarray,
            fs_dso: float,
            fs_awg: float,
            symbol_rate: float,
            onset_idx: int,
            tx_raw: np.ndarray,
            tx_bb: np.ndarray,
        ) -> None:
            n_plot_rx = min(len(t), max(200, int(10 * (fs_dso / symbol_rate))))
            start_idx = max(0, min(onset_idx, len(t) - n_plot_rx))
            end_idx = min(len(t), start_idx + n_plot_rx)
            t_win, y_raw_win, y_bb_win = t[start_idx:end_idx], np.real(y_raw[start_idx:end_idx]), y_bb[start_idx:end_idx]
            t_rel = (t_win - t_win[0]) if len(t_win) > 0 else np.array([0.0])

            f_tx, p_tx = self._single_sided_spectrum(np.real(tx_raw), fs_awg)
            f_raw, p_raw = self._single_sided_spectrum(np.real(y_raw), fs_dso)
            f_bb, p_bb = self._two_sided_spectrum(np.asarray(y_bb, dtype=np.complex128), fs_dso)
            bb_pos = f_bb >= 0.0
            f_bb_pos = f_bb[bb_pos]
            p_bb_pos = p_bb[bb_pos]
            ts, tu = self._time_unit_scale(float(t_rel[-1] if len(t_rel) > 0 else 0.0))
            fsf_raw, fu_raw = self._freq_unit_scale(float(max(np.max(np.abs(f_raw)), 1.0)))
            fsf_bb, fu_bb = self._freq_unit_scale(float(max(np.max(np.abs(f_bb)), 1.0)))

            self.fig.clear()
            ax1 = self.fig.add_subplot(321)
            ax2 = self.fig.add_subplot(322)
            ax3 = self.fig.add_subplot(323)
            ax4 = self.fig.add_subplot(324)
            ax5 = self.fig.add_subplot(325)
            ax6 = self.fig.add_subplot(326)

            n_plot_tx = min(len(tx_raw), max(200, int(10 * (fs_awg / symbol_rate))))
            tx_win = np.real(tx_raw[:n_plot_tx])
            t_tx_win = np.arange(len(tx_win)) / fs_awg

            ax1.plot(t_tx_win * ts, tx_win, linewidth=0.7)
            ax1.set_title("TX Time")
            ax1.set_xlabel(f"Time [{tu}]")
            ax1.grid(True)
            if len(tx_win) > 8:
                ypk = np.percentile(np.abs(tx_win), 99.5)
                ax1.set_ylim(-1.25 * max(ypk, 1e-6), 1.25 * max(ypk, 1e-6))

            ax2.plot(f_tx * 1e-9, p_tx, linewidth=0.7)
            ax2.set_xlim(0.0, 40.0)
            ax2.set_title("TX Spectrum (AWG fs)")
            ax2.set_xlabel("Freq [GHz]")
            ax2.grid(True)
            if len(p_tx) > 0:
                pmax = float(np.max(p_tx))
                ax2.set_ylim(pmax - 80.0, pmax + 3.0)

            ax3.plot(t_rel * ts, y_raw_win, linewidth=0.6)
            ax3.set_title("Raw IF Time")
            ax3.set_xlabel(f"Time [{tu}]")
            ax3.grid(True)
            if len(y_raw_win) > 8:
                ypk = np.percentile(np.abs(y_raw_win), 99.5)
                ax3.set_ylim(-1.25 * max(ypk, 1e-6), 1.25 * max(ypk, 1e-6))

            ax4.plot(f_raw * 1e-9, p_raw, linewidth=0.6)
            ax4.set_xlim(0.0, 40.0)
            ax4.set_title("Raw IF Spectrum (DSO fs)")
            ax4.set_xlabel("Freq [GHz]")
            ax4.grid(True)
            if len(p_raw) > 0:
                pmax = float(np.max(p_raw))
                ax4.set_ylim(pmax - 80.0, pmax + 3.0)

            ax5.plot(t_rel * ts, np.real(y_bb_win), linewidth=0.8, label="I")
            ax5.plot(t_rel * ts, np.imag(y_bb_win), linewidth=0.8, alpha=0.7, label="Q")
            ax5.set_title("Baseband Time")
            ax5.set_xlabel(f"Time [{tu}]")
            ax5.grid(True)
            ax5.legend(loc="upper right", fontsize=7)
            if len(y_bb_win) > 8:
                ypk = np.percentile(np.abs(y_bb_win), 99.5)
                ax5.set_ylim(-1.25 * max(ypk, 1e-6), 1.25 * max(ypk, 1e-6))

            ax6.plot(f_bb_pos * 1e-9, p_bb_pos, linewidth=0.6)
            bb_span_ghz = max(0.5, min(40.0, 2.0 * symbol_rate * 1e-9))
            ax6.set_xlim(0.0, bb_span_ghz)
            ax6.set_title("Baseband Spectrum (DSO fs)")
            ax6.set_xlabel("Freq [GHz]")
            ax6.grid(True)
            if len(p_bb_pos) > 0:
                pmax = float(np.max(p_bb_pos))
                ax6.set_ylim(pmax - 80.0, pmax + 3.0)
            self.fig.tight_layout(); self.canvas.draw_idle()

        def _render_demod_dashboard(self, res: dict, target_dist: float) -> None:
            self.fig.clear()
            ax1 = self.fig.add_subplot(221)
            ax2 = self.fig.add_subplot(222)
            ax3 = self.fig.add_subplot(223)
            ax4 = self.fig.add_subplot(224)

            qref = np.asarray(res.get("qam_ref", []), dtype=np.complex128)
            qest = np.asarray(res.get("qam_est_eq", res.get("qam_est", [])), dtype=np.complex128)
            range_axis_1d = np.asarray(res.get("range_axis_1d", []), dtype=np.float64)
            range_profile_db_1d = np.asarray(res.get("range_profile_db_1d", []), dtype=np.float64)
            est = float(res.get("estimated_dist", float("nan")))

            if len(range_axis_1d) > 0 and len(range_profile_db_1d) > 0:
                ax1.plot(range_axis_1d, range_profile_db_1d, color="blue", linewidth=1.0)
                ax1.axvline(target_dist, color="red", linestyle="--", label="Target")
                max_x = max(20.0, 2.5 * target_dist)
                ax1.set_xlim(0.0, max_x)
                ax1.set_ylim(-60.0, 5.0)
                ax1.set_title(f"Range Profile (Est: {est:.2f}m)")
                ax1.set_xlabel("Range (m)")
                ax1.grid(True)
                ax1.legend(fontsize=8)
            else:
                ax1.text(0.5, 0.5, "No range profile", ha="center", va="center")
                ax1.set_axis_off()

            rd_power = np.asarray(res.get("rd_power", []), dtype=np.float64)
            rd_range_axis = np.asarray(res.get("rd_range_axis", []), dtype=np.float64)
            vel_axis = np.asarray(res.get("vel_axis", []), dtype=np.float64)
            if rd_power.ndim == 2 and len(rd_range_axis) > 1 and len(vel_axis) > 0:
                max_r_m = 50.0
                max_r_bin = int(np.searchsorted(rd_range_axis, max_r_m, side="right"))
                max_r_bin = max(2, min(max_r_bin, rd_power.shape[1]))
                im = ax2.imshow(
                    rd_power[:, :max_r_bin],
                    aspect="auto",
                    origin="lower",
                    extent=[rd_range_axis[0], rd_range_axis[max_r_bin - 1], vel_axis[0], vel_axis[-1]],
                    cmap="jet",
                )
                ax2.set_title("Range-Doppler Map")
                ax2.set_xlabel("Range (m)")
                ax2.set_ylabel("Velocity (m/s)")
                self.fig.colorbar(im, ax=ax2)
            else:
                ax2.text(0.5, 0.5, "No RD map", ha="center", va="center")
                ax2.set_axis_off()

            if "rx_sync" in res and "dechirped" in res:
                fs_sim = res["fs_sim"]
                nps = res["nps"]
                plot_samples = min(len(res["rx_sync"]), 10 * nps)

                t_plot = np.arange(plot_samples) / fs_sim * 1e9  # in ns

                ax3.plot(t_plot, np.real(res["rx_sync"][:plot_samples]), label="I (Chirped)", linewidth=1.0, alpha=0.5)
                ax3.plot(t_plot, np.real(res["dechirped"][:plot_samples]), label="I (De-chirped)", linewidth=1.0, color="red")
                ax3.set_title("Baseband Time (First 20 Syms)")
                ax3.set_xlabel("Time (ns)")
                ax3.grid(True)
                ax3.legend(loc="upper right", fontsize=7)

            if len(qest) > 0:
                ax4.scatter(qest.real, qest.imag, s=12, color="red", label="RX Eq", alpha=0.85)
            if len(qref) > 0:
                ax4.scatter(qref.real, qref.imag, s=26, marker="x", color="black", label="TX")
            ax4.set_title(f"Constellation (EVM: {res.get('evm_db', float('nan')):.2f} dB)")
            ax4.set_xlim(-1.5, 1.5)
            ax4.set_ylim(-1.5, 1.5)
            ax4.set_aspect("equal", adjustable="box")
            ax4.grid(True)
            if len(qref) > 0 or len(qest) > 0:
                ax4.legend(fontsize=8)

            self.fig.tight_layout(); self.canvas.draw_idle()

        def _on_observe(self) -> None:
            def worker():
                try:
                    t, y_raw, y_bb, fs, meta = self._build_simulated_rx()
                    onset_idx = int(meta["delay_samples_sim"] * (fs / meta["fs_sim"]))
                    self.parent.after(
                        0,
                        lambda: self._render_quadrant(
                            t,
                            y_raw,
                            y_bb,
                            fs_dso=fs,
                            fs_awg=meta["fs_sim"],
                            symbol_rate=meta.get("symbol_rate"),
                            onset_idx=onset_idx,
                            tx_raw=np.asarray(meta.get("tx_raw_scope", y_raw)),
                            tx_bb=np.asarray(meta.get("tx_bb_scope", y_bb)),
                        ),
                    )
                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("Simulation", m))
            threading.Thread(target=worker, daemon=True).start()

        def _on_run_demod(self) -> None:
            def worker():
                try:
                    _, _, _, _, meta = self._build_simulated_rx()
                    rx_signal_scope = np.asarray(meta["rx_for_demod"])
                    fs_scope = float(meta["fs_scope"])
                    fs_sim = float(meta["fs_sim"])
                    waveform_type = str(meta.get("waveform_type", "LFM-QAM")).strip()

                    # 1) Bring to simulation rate to keep symbol slicing exact.
                    if not np.isclose(fs_scope, fs_sim):
                        if meta["f_if_demod"] > 0:
                            rx_signal_sim = np.real(fft_resample_complex(rx_signal_scope, fs_in=fs_scope, fs_out=fs_sim))
                        else:
                            rx_signal_sim = fft_resample_complex(rx_signal_scope, fs_in=fs_scope, fs_out=fs_sim)
                    else:
                        rx_signal_sim = rx_signal_scope

                    # 2) Down-convert to complex baseband.
                    if meta["f_if_demod"] > 0:
                        t_sim = np.arange(len(rx_signal_sim)) / fs_sim
                        rx_bb_sync = rx_signal_sim * np.exp(-1j * 2.0 * np.pi * meta["f_if_demod"] * t_sim) * 2.0
                        lpf_cutoff = min(1.2 * meta["B"], fs_sim * 0.45)
                        rx_bb_sync = self._lowpass_complex_fft(rx_bb_sync, fs=fs_sim, cutoff_hz=lpf_cutoff)
                    else:
                        rx_bb_sync = np.asarray(rx_signal_sim, dtype=np.complex128)

                    # +++ NEW: Coarse CFO Estimation & Correction +++
                    # This step is critical for real hardware where LOs are not perfectly synced.
                    try:
                        cfo_search_range_khz = 5000  # Search +/- 5 MHz, reasonable for THz systems
                        cfo_search_range_hz = cfo_search_range_khz * 1e3

                        # Use the first chirp's baseband signal as the template for correlation.
                        tx_bb_matrix_cfo = np.asarray(meta.get("tx_bb_matrix", []), dtype=np.complex128)
                        if tx_bb_matrix_cfo.size > 0:
                            # --- PERFORMANCE FIX: Cap template length for faster CFO search ---
                            cfo_template_len = min(len(tx_bb_matrix_cfo[0]), 4096)
                            template_for_cfo = tx_bb_matrix_cfo[0, :cfo_template_len]

                            # Grid search for the frequency offset that maximizes correlation.
                            coarse_cfo_hz, _ = self._cfo_grid_search(
                                rx_bb_sync, template_for_cfo, fs_sim, cfo_search_range_hz, num_steps=51
                            )

                            # Apply coarse CFO correction to the entire baseband signal
                            if abs(coarse_cfo_hz) > 1e-3:
                                rx_bb_sync = self._cfo_compensate(rx_bb_sync, coarse_cfo_hz, fs_sim)
                    except Exception as e:
                        # If CFO estimation fails, log the error and proceed without correction
                        import traceback
                        print("=" * 50)
                        print("WARNING: Coarse CFO estimation failed. The demodulator will likely fail.")
                        print(f"Error: {e}")
                        print(traceback.format_exc())
                        print("=" * 50)
                        pass
                    # --- END NEW ---

                    # 3) Frame sync using the waveform template, then matched-filter ranging.
                    nps = int(meta.get("sps", 1))
                    n_chirps = int(meta.get("n_chirps", 1))
                    n_sym_per_chirp = int(meta.get("n_sym_per_chirp", max(1, len(meta["qam_symbols"]) // max(n_chirps, 1))))
                    pts_per_chirp = n_sym_per_chirp * nps
                    qam_preamble_len = int(meta.get("qam_preamble_len", 0))
                    qam_preamble_symbols = np.asarray(meta.get("qam_preamble_symbols", []), dtype=np.complex128).reshape(-1)
                    qam_rrc_taps = np.asarray(meta.get("qam_rrc_taps", [1.0]), dtype=np.float64).reshape(-1)
                    tx_bb_matrix = np.asarray(meta.get("tx_bb_matrix", []), dtype=np.complex128)
                    tx_sym_matrix = np.asarray(meta.get("tx_sym_matrix", []), dtype=np.complex128)

                    if tx_bb_matrix.size == 0:
                        base_ch = np.asarray(meta["base_chirp"], dtype=np.complex128)
                        tx_syms = np.asarray(meta["qam_symbols"], dtype=np.complex128)[: n_chirps * n_sym_per_chirp]
                        tx_sym_matrix = tx_syms.reshape(n_chirps, n_sym_per_chirp)
                        if waveform_type == "QAM":
                            tx_bb_matrix = np.repeat(tx_sym_matrix, nps, axis=1)
                        elif waveform_type == "FMCW":
                            tx_sym_matrix = np.ones((n_chirps, n_sym_per_chirp), dtype=np.complex128)
                            tx_bb_matrix = np.repeat(tx_sym_matrix, nps, axis=1) * base_ch[np.newaxis, :]
                        else:
                            tx_bb_matrix = np.repeat(tx_sym_matrix, nps, axis=1) * base_ch[np.newaxis, :]

                    from scipy.signal import correlate
                    if waveform_type == "QAM":
                        # QAM has no chirp signature; use delay hint and short local correlation refinement.
                        qam_tmpl_syms = min(max(qam_preamble_len, 24), n_sym_per_chirp)
                        qam_template = tx_bb_matrix[0, : qam_tmpl_syms * nps]
                        coarse = int(max(0, meta.get("delay_samples_sim", 0)))
                        win = max(nps * 2, 32)
                        start = max(0, coarse - win)
                        stop = min(len(rx_bb_sync), coarse + win + len(qam_template) + 1)
                        if stop - start <= len(qam_template):
                            frame_start = coarse
                            corr = np.array([1.0], dtype=np.float64)
                        else:
                            local = rx_bb_sync[start:stop]
                            corr = np.abs(correlate(local, qam_template, mode="valid", method="fft"))
                            frame_start = int(start + np.argmax(corr))
                    else:
                        template = tx_bb_matrix[0]
                        search_len = min(len(rx_bb_sync), len(template) + int(meta["delay_samples_sim"] * 2) + len(template) * 4)
                        if len(rx_bb_sync) <= len(template):
                            frame_start = int(max(0, meta["delay_samples_sim"]))
                            corr = np.array([1.0], dtype=np.float64)
                        else:
                            corr = np.abs(correlate(rx_bb_sync[:search_len], template, mode="valid", method="fft"))
                            frame_start = int(np.argmax(corr))

                    total_pts = n_chirps * pts_per_chirp

                    # Sensing path: keep raw timing (no frame shift) to preserve absolute delay information.
                    if total_pts > len(rx_bb_sync):
                        rx_radar_frame = np.pad(rx_bb_sync, (0, total_pts - len(rx_bb_sync)))
                    else:
                        rx_radar_frame = rx_bb_sync[:total_pts]
                    rx_radar_mat = rx_radar_frame.reshape(n_chirps, pts_per_chirp)

                    mf_out = np.fft.ifft(
                        np.fft.fft(rx_radar_mat, axis=1) * np.conj(np.fft.fft(tx_bb_matrix, axis=1)),
                        axis=1,
                    )
                    rd_map = np.fft.fftshift(np.fft.fft(mf_out, axis=0), axes=0)
                    rd_power = 20.0 * np.log10(np.abs(rd_map) + 1e-12)

                    # 1D range profile: average linear matched-filter outputs across chirps.
                    corr_acc = None
                    lags = None
                    for i in range(n_chirps):
                        c_i = correlate(rx_radar_mat[i], tx_bb_matrix[i], mode="full", method="fft")
                        if corr_acc is None:
                            corr_acc = np.zeros_like(np.abs(c_i), dtype=np.float64)
                            lags = np.arange(-(len(tx_bb_matrix[i]) - 1), len(rx_radar_mat[i]), dtype=np.int64)
                        corr_acc += np.abs(c_i)
                    range_prof_lin = corr_acc / max(n_chirps, 1)
                    if lags is not None and len(lags) == len(range_prof_lin):
                        valid = lags >= 0
                        lags_v = lags[valid]
                        prof_v = range_prof_lin[valid]
                    else:
                        lags_v = np.arange(len(range_prof_lin), dtype=np.int64)
                        prof_v = range_prof_lin

                    est_idx = int(np.argmax(prof_v)) if len(prof_v) > 0 else 0
                    est_delay = int(lags_v[est_idx]) if len(lags_v) > est_idx else frame_start
                    est_dist = est_delay * meta["c0"] / (2.0 * fs_sim)
                    range_axis_1d = lags_v.astype(np.float64) * meta["c0"] / (2.0 * fs_sim)
                    range_profile_db_1d = 20.0 * np.log10(prof_v / (np.max(prof_v) + 1e-15) + 1e-15)

                    # Communication path: align frame for stable symbol slicing/equalization.
                    available_pts = max(0, len(rx_bb_sync) - frame_start)
                    valid_chirps = max(1, min(n_chirps, available_pts // max(pts_per_chirp, 1)))
                    if valid_chirps < n_chirps:
                        tx_sym_matrix = tx_sym_matrix[:valid_chirps]
                        tx_bb_matrix = tx_bb_matrix[:valid_chirps]
                        n_chirps = valid_chirps
                        total_pts = n_chirps * pts_per_chirp

                    if frame_start + total_pts > len(rx_bb_sync):
                        rx_frame = np.pad(rx_bb_sync[frame_start:], (0, frame_start + total_pts - len(rx_bb_sync)))
                    else:
                        rx_frame = rx_bb_sync[frame_start: frame_start + total_pts]
                    rx_mat = rx_frame.reshape(n_chirps, pts_per_chirp)

                    rx_sync_mat = rx_mat
                    if waveform_type == "FMCW":
                        dechirped_mat = rx_sync_mat * np.conj(np.asarray(meta["base_chirp"], dtype=np.complex128))[np.newaxis, :]
                        qam_ref_aligned = np.array([], dtype=np.complex128)
                        qam_est = np.array([], dtype=np.complex128)
                        qam_est_aligned = np.array([], dtype=np.complex128)
                        timing_gain_used = float("nan")
                        evm_db = float("nan")
                        evm_pct = float("nan")
                        ber = float("nan")
                        sym_err = float("nan")
                    else:
                        if waveform_type == "QAM":
                            dechirped_mat = rx_sync_mat
                            rx_mf_mat = np.zeros_like(dechirped_mat)
                            for i in range(n_chirps):
                                rx_mf_mat[i] = self._apply_fir_same(dechirped_mat[i], qam_rrc_taps)

                            qam_est_rows = []
                            qam_ref_rows = []
                            timing_gain_candidates = (0.002, 0.005, 0.01, 0.02)
                            selected_gains = []
                            for i in range(n_chirps):
                                best_sym = None
                                best_gain = None
                                best_nmse = np.inf
                                for tg in timing_gain_candidates:
                                    sym_try = self._gardner_timing_recovery(rx_mf_mat[i], sps=nps, n_symbols=n_sym_per_chirp, gain=tg)
                                    if len(sym_try) < n_sym_per_chirp:
                                        continue
                                    sym_try = sym_try[:n_sym_per_chirp]
                                    ref_eval = tx_sym_matrix[i, : max(8, min(qam_preamble_len, n_sym_per_chirp))] if qam_preamble_len > 0 else tx_sym_matrix[i]
                                    est_eval = sym_try[: len(ref_eval)]
                                    den_e = np.sum(np.abs(est_eval) ** 2) + 1e-15
                                    h_e = np.sum(ref_eval * np.conj(est_eval)) / den_e
                                    nmse = np.mean(np.abs(h_e * est_eval - ref_eval) ** 2) / (np.mean(np.abs(ref_eval) ** 2) + 1e-15)
                                    if nmse < best_nmse:
                                        best_nmse = float(nmse)
                                        best_sym = sym_try
                                        best_gain = float(tg)

                                sym_rec = best_sym
                                if sym_rec is None:
                                    # Fallback: phase-search symbol slicing if Gardner under-runs.
                                    best_nmse = np.inf
                                    best_cand = None
                                    for phase in range(max(1, nps)):
                                        cand = rx_mf_mat[i, phase::nps][:n_sym_per_chirp]
                                        if len(cand) < n_sym_per_chirp:
                                            continue
                                        den_c = np.sum(np.abs(tx_sym_matrix[i]) ** 2) + 1e-15
                                        h_c = np.sum(cand * np.conj(tx_sym_matrix[i])) / den_c
                                        cand_eq = cand / (h_c + 1e-15)
                                        nmse = np.mean(np.abs(cand_eq - tx_sym_matrix[i]) ** 2)
                                        if nmse < best_nmse:
                                            best_nmse = float(nmse)
                                            best_cand = cand
                                    if best_cand is None:
                                        continue
                                    sym_rec = best_cand
                                    best_gain = float("nan")
                                else:
                                    sym_rec = sym_rec[:n_sym_per_chirp]
                                qam_est_rows.append(sym_rec)
                                qam_ref_rows.append(tx_sym_matrix[i])
                                selected_gains.append(best_gain)

                            if len(qam_est_rows) == 0:
                                qam_est_mat = np.zeros((0, n_sym_per_chirp), dtype=np.complex128)
                                tx_sym_matrix = np.zeros((0, n_sym_per_chirp), dtype=np.complex128)
                                timing_gain_used = float("nan")
                            else:
                                qam_est_mat = np.asarray(qam_est_rows, dtype=np.complex128)
                                tx_sym_matrix = np.asarray(qam_ref_rows, dtype=np.complex128)
                                valid_tg = np.asarray([g for g in selected_gains if np.isfinite(g)], dtype=np.float64)
                                timing_gain_used = float(np.mean(valid_tg)) if len(valid_tg) > 0 else float("nan")

                            # Per-chirp linear phase correction (residual CFO/phase drift) before equalization.
                            if qam_est_mat.size > 0 and tx_sym_matrix.size > 0:
                                k_all = np.arange(n_sym_per_chirp, dtype=np.float64)
                                for i in range(len(qam_est_mat)):
                                    if qam_preamble_len > 4:
                                        k_fit = np.arange(qam_preamble_len, dtype=np.float64)
                                        est_fit = qam_est_mat[i, :qam_preamble_len]
                                        ref_fit = tx_sym_matrix[i, :qam_preamble_len]
                                    else:
                                        k_fit = k_all
                                        est_fit = qam_est_mat[i]
                                        ref_fit = tx_sym_matrix[i]

                                    ph = np.unwrap(np.angle(est_fit * np.conj(ref_fit) + 1e-15))
                                    if len(ph) >= 2:
                                        slope_i, intercept_i = np.polyfit(k_fit, ph, deg=1)
                                        qam_est_mat[i] = qam_est_mat[i] * np.exp(-1j * (slope_i * k_all + intercept_i))

                            if qam_preamble_len > 0 and qam_preamble_len < n_sym_per_chirp:
                                pre_ref = tx_sym_matrix[:, :qam_preamble_len]
                                pre_est = qam_est_mat[:, :qam_preamble_len]
                                den_pre = np.sum(pre_est * np.conj(pre_est), axis=1) + 1e-15
                                h_pre = np.sum(pre_ref * np.conj(pre_est), axis=1) / den_pre
                                qam_est_mat = qam_est_mat * h_pre[:, np.newaxis]
                                qam_ref = tx_sym_matrix[:, qam_preamble_len:].reshape(-1)
                                qam_est = qam_est_mat[:, qam_preamble_len:].reshape(-1)
                            else:
                                qam_ref = tx_sym_matrix.reshape(-1)
                                qam_est = qam_est_mat.reshape(-1)
                        else:  # LFM-QAM: shared waveform (single continuous
                               # chirp carrying the selected modulation)
                            # n_chirps==1 here (the whole frame is one
                            # "chirp"), so there is one row to dechirp -- no
                            # per-chirp pilot/Gardner machinery.
                            base_ch = np.asarray(meta["base_chirp"], dtype=np.complex128)
                            dechirped_mat = rx_sync_mat * np.conj(base_ch)[np.newaxis, :]
                            shared_preamble_len = int(meta.get(
                                "qam_preamble_len",
                                meta.get("psk_preamble_len", 0),
                            ))
                            shared_preamble_ref = np.asarray(
                                meta.get(
                                    "qam_preamble_symbols",
                                    meta.get("psk_preamble_symbols", []),
                                ),
                                dtype=np.complex128,
                            ).reshape(-1)
                            qam_est, _lfm_diag = DsoPanel._recover_lfm_qam_symbols_integrate_and_dump(
                                dechirped_mat[0],
                                n_per_sym=nps,
                                n_symbols=n_sym_per_chirp,
                                preamble_len=shared_preamble_len,
                                preamble_ref=shared_preamble_ref,
                            )
                            qam_ref = tx_sym_matrix[0][:len(qam_est)]
                            timing_gain_used = float("nan")

                        # Remove linear phase drift across symbols (beat/CFO residue after de-chirp).
                        if len(qam_est) > 4 and len(qam_ref) == len(qam_est):
                            ph = np.unwrap(np.angle(qam_est * np.conj(qam_ref) + 1e-15))
                            k = np.arange(len(ph), dtype=np.float64)
                            slope, intercept = np.polyfit(k, ph, deg=1)
                            qam_est = qam_est * np.exp(-1j * (slope * k + intercept))

                        try:
                            sc_fde_taps = max(1, int(float(self.sc_fde_taps_var.get())))
                            sc_fde_enable = bool(self.sc_fde_enable_var.get())
                        except Exception:
                            sc_fde_taps = 21
                            sc_fde_enable = True
                        qam_est_eq = sc_fde_equalizer(qam_est, qam_ref, num_taps=sc_fde_taps, enable=sc_fde_enable)

                        # Remove clearly invalid near-origin symbols typically caused by frame padding/underrun.
                        if waveform_type == "QAM" and len(qam_est_eq) > 0 and len(qam_ref) == len(qam_est_eq):
                            ref_scale = float(np.sqrt(np.mean(np.abs(qam_ref) ** 2) + 1e-15))
                            amp_gate = max(1e-3, 0.10 * ref_scale)
                            valid = np.abs(qam_est_eq) >= amp_gate
                            if np.any(valid):
                                qam_ref = qam_ref[valid]
                                qam_est_eq = qam_est_eq[valid]

                        # Align small symbol-lag mismatch before quality metrics.
                        qam_ref_aligned, qam_est_aligned = _align_symbols_for_ber(qam_ref, qam_est_eq, max_lag=16)

                        err = qam_est_aligned - qam_ref_aligned
                        evm_rms = np.sqrt(np.mean(np.abs(err) ** 2) / (np.mean(np.abs(qam_ref_aligned) ** 2) + 1e-15))
                        evm_db = 20.0 * np.log10(evm_rms + 1e-15)
                        evm_pct = 100.0 * evm_rms

                        br = _hard_bits_from_symbols(qam_ref_aligned, meta.get("modulation", "16QAM"))
                        be = _hard_bits_from_symbols(qam_est_aligned, meta.get("modulation", "16QAM"))
                        ber = float(np.mean(br != be)) if len(br) == len(be) and len(br) > 0 else float("nan")

                        # SER from hard decision symbol mismatch.
                        if len(qam_ref_aligned) > 0:
                            bps = _bits_per_symbol(meta.get("modulation", "16QAM"))
                            sym_err = np.mean(np.any(br.reshape(-1, bps) != be.reshape(-1, bps), axis=1)) if np.isfinite(ber) else float("nan")
                        else:
                            sym_err = float("nan")

                    tc = n_sym_per_chirp * (1.0 / max(meta["B"], 1.0))
                    vel_axis = np.fft.fftshift(np.fft.fftfreq(n_chirps, d=tc)) * (meta["c0"] / max(meta["fc"], 1.0)) / 2.0
                    rd_range_axis = np.arange(pts_per_chirp, dtype=np.float64) * meta["c0"] / (2.0 * fs_sim)

                    res = {
                        "qam_ref": qam_ref_aligned,
                        "qam_est": qam_est,
                        "qam_est_eq": qam_est_aligned,
                        "evm_db": float(evm_db),
                        "evm_pct": float(evm_pct),
                        "ber": float(ber),
                        "ser": float(sym_err),
                        "estimated_dist": float(est_dist),
                        "rx_sync": rx_sync_mat.reshape(-1),
                        "dechirped": dechirped_mat.reshape(-1),
                        "fs_sim": fs_sim,
                        "nps": int(nps),
                        "range_axis_1d": range_axis_1d,
                        "range_profile_db_1d": range_profile_db_1d,
                        "rd_range_axis": rd_range_axis,
                        "rd_power": rd_power,
                        "vel_axis": vel_axis,
                        "timing_gain_used": float(timing_gain_used),
                    }

                    target_dist = float(_parse_float_input(self.dist_var.get(), "Distance"))
                    self.parent.after(0, lambda: self._render_demod_dashboard(res, target_dist))

                    ninfo = meta["noise_info"]
                    si_info = meta.get("si_info", {})
                    sinr_post_db = float(si_info.get("sinr_post_db", float("nan")))
                    sinr_req_nom = self._sinr_target_ber_1e3(meta.get("modulation", "16QAM"), impl_margin_db=0.0)
                    sinr_req_m3 = self._sinr_target_ber_1e3(meta.get("modulation", "16QAM"), impl_margin_db=3.0)

                    def _dmax_from_sinr(req_db: float) -> float:
                        if (not np.isfinite(sinr_post_db)) or target_dist <= 0.0:
                            return float("nan")
                        return float(target_dist * (10.0 ** ((sinr_post_db - req_db) / 20.0)))

                    dmax_nom = _dmax_from_sinr(sinr_req_nom)
                    dmax_m3 = _dmax_from_sinr(sinr_req_m3)

                    left_rows = [
                        ("Path Loss", float(meta.get("path_loss_db", float("nan"))), "dB"),
                        ("Received Power", float(si_info.get("comm_power_dbm_omt", meta.get("pr_comm_dbm", float("nan")))), "dBm"),
                        ("LNA Input Power", float(si_info.get("lna_input_dbm", float("nan"))), "dBm"),
                        ("OMT Isolation", float(si_info.get("antenna_sic_db", 0.0)), "dB"),
                        ("SINR post", float(si_info.get("sinr_post_db", float("nan"))), "dB"),
                        ("SINR req (BER1e-3)", sinr_req_nom, "dB"),
                        ("d_max @ BER1e-3", dmax_nom, "m"),
                        ("d_max @ BER1e-3 +3dB", dmax_m3, "m"),
                    ]
                    right_rows = [
                        ("Waveform", waveform_type, ""),
                        ("DSP Mode", si_info.get("dsp_mode", "--"), ""),
                        ("SI Red. (time pwr)", float(si_info.get("si_reduction_db", float("nan"))), "dB"),
                        ("DSP SIC Supp.", float(si_info.get("dsp_sic_db", 0.0)), "dB"),
                        ("Estimated Distance", est_dist, "m"),
                        ("Timing gain (auto)", float(res.get("timing_gain_used", float("nan"))), ""),
                        ("EVM", float(res.get("evm_db", float("nan"))), "dB"),
                        ("EVM", float(res.get("evm_pct", float("nan"))), "%"),
                        ("BER", float(res.get("ber", float("nan"))), ""),
                        ("SER", float(res.get("ser", float("nan"))), ""),
                    ]
                    self.parent.after(0, lambda: self._set_kpi_rows(left_rows, right_rows))

                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("Simulation Error", m))
            threading.Thread(target=worker, daemon=True).start()

        def _on_calculate(self) -> None:
            try:
                d = _parse_float_input(self.dist_var.get(), "Distance")
                f = _parse_ghz_input(self.rf_var.get(), "RF Frequency")
                ptx_dbm = _parse_float_input(self.txp_var.get(), "TX Power")
                sym_rate = _parse_ghz_input(self.symbol_rate_var.get(), "Symbol Rate")
                ant_gain = _parse_float_input(self.ant_gain_var.get(), "Antenna Gain")
                rx_gain_db = _parse_float_input(self.rx_gain_var.get(), "RX IF Gain")
                si_enabled = bool(self.si_enable_var.get())
                antenna_sic_db = _parse_float_input(self.antenna_sic_var.get(), "OMT Isolation")

                path_loss_db = self._fspl_db(d, f)
                pr_comm_dbm = ptx_dbm + 2.0 * ant_gain - path_loss_db
                scope_model = str(self.scope_model_var.get()).strip()
                _, noise_info = self._calculate_total_noise(pr_comm_dbm, sym_rate, scope_model, rx_gain_db)
                pr_comm_dbm_dso = pr_comm_dbm + rx_gain_db
                si_power_dbm_ant = ptx_dbm - max(0.0, antenna_sic_db) if si_enabled else -300.0
                si_power_dbm_dso = si_power_dbm_ant + rx_gain_db if si_enabled else -300.0
                si_to_comm_db = si_power_dbm_dso - pr_comm_dbm_dso if si_enabled else -300.0

                p_comm_omt_w = self._dbm_to_w(pr_comm_dbm)
                p_si_omt_w = self._dbm_to_w(si_power_dbm_ant) if si_enabled else 0.0
                lna_input_dbm = 10.0 * np.log10(max((p_comm_omt_w + p_si_omt_w) / 1e-3, 1e-30))

                left_rows = [
                    ("Path Loss", path_loss_db, "dB"),
                    ("Received Power", pr_comm_dbm, "dBm"),
                    ("LNA Input Power", lna_input_dbm, "dBm"),
                    ("OMT Isolation", antenna_sic_db, "dB"),
                    ("SINR post", "--", "dB"),
                    ("SINR req (BER1e-3)", self._sinr_target_ber_1e3(self.modulation_var.get(), impl_margin_db=0.0), "dB"),
                    ("d_max @ BER1e-3", "--", "m"),
                    ("d_max @ BER1e-3 +3dB", "--", "m"),
                ]
                right_rows = [
                    ("Waveform", self.waveform_var.get(), ""),
                    ("DSP Mode", self.sic_mode_var.get(), ""),
                    ("SI Red. (time pwr)", "--", "dB"),
                    ("DSP SIC Supp.", "--", "dB"),
                    ("Estimated Distance", "--", "m"),
                    ("Timing gain (auto)", "--", ""),
                    ("EVM", "--", "dB"),
                    ("EVM", "--", "%"),
                    ("BER", "--", ""),
                    ("SER", "--", ""),
                ]
                self._set_kpi_rows(left_rows, right_rows)
            except Exception as e:
                messagebox.showerror("Calculation Error", str(e))

# ==============================================================================
# DSO PANEL
# ==============================================================================

# === PHOTONIC ISAC SIM ===
@dataclass
class SimConfig:
    fs_gsps: float = 100.0
    frame_len: int = 4096
    num_frames: int = 100
    step_ns: float = 20.0

    linewidth_mhz: float = 0.015
    baud_gbaud: float = 10.0
    if_ghz: float = 12.0
    rf_carrier_ghz: float = 270.0
    waveform: str = "16QAM"
    modulation: str = "16QAM"
    chirp_bw_ghz: float = 2.0

    coherence_mode: str = "Free-running"
    rx_mode: str = "Mixer"
    optical_sideband_mode: str = "DSB"
    si_enable: bool = True
    carrier_wander_enable: bool = False
    carrier_wander_mhz: float = 0.0
    sc_fde_enable: bool = True
    sc_fde_taps: int = 21

    # Optical front-end / MZM settings. UTC-PD photocurrent sets absolute
    # optical power; AWG RF power moves the signal-to-carrier ratio.
    awg_rf_power_dbm: float = -10.0
    awg_ref_power_dbm: float = -10.0
    mzm_drive_gain_db: float = 8.0
    mzm_vpi_v: float = 3.0
    mzm_phi_bias_deg: float = 45.0
    mzm_input_ohm: float = 50.0
    mzm_eo_bw_ghz: float = 30.0
    mzm_insertion_loss_db: float = 3.5
    awg_dac_bits: float = 8.0
    optical_center_freq_thz: float = 193.41
    utcpd_photocurrent_ma: float = 7.0
    utcpd_target_dbm: float = -10.0
    utcpd_responsivity_a_per_w: float = 0.24
    cspr_db: float = 13.0
    lna_gain_db: float = 13.0
    lna_nf_db: float = 8.0
    zbd_responsivity_vpw: float = 1500.0
    zbd_nep_pw_sqrt_hz: float = 5.0
    c1_drive_gain_db: float = 27.0
    c2_drive_gain_db: float = 20.0
    c1_cable_loss_db: float = 10.0
    c2_cable_loss_db: float = 22.0
    if_amp_nf_db: float = 5.0
    dso_vscale_mv: float = 100.0
    dso_bandwidth_ghz: float = 40.0
    omt_iso_db: float = 24.0
    omt_il_db: float = 2.0
    ant_gain_dbi: float = 33.0
    tx_ant_gain_dbi: float = 33.0
    rx_ant_gain_dbi: float = 33.0
    target_rcs_sqm: float = 0.01
    target_ant_gain_dbi: float = 33.0
    target_gamma_mag: float = 0.5
    target_pol_eff: float = 1.0
    target_dist_m: float = 1.0  # Default 1m
    sim_seed: int | None = None
    syms_per_chirp: int = 1024
    pilot_rho: float = 0.20
    rrc_beta: float = 0.20
    # Derived link parameters.
    tx_power_dbm: float = 0.0
    path_loss_db: float = 0.0
    delay_ns: float = 0.0

def rrc_filter(span_sym, alpha, ts, fs):
    t = np.arange(-span_sym, span_sym + 1) / fs
    h = np.zeros(len(t))
    for i, tc in enumerate(t):
        if tc == 0: h[i] = 1.0 + alpha * (4 / np.pi - 1)
        elif abs(tc) == ts / (4 * alpha): h[i] = (alpha / np.sqrt(2)) * (((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))) + ((1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha))))
        else: h[i] = (np.sin(np.pi * tc / ts * (1 - alpha)) + 4 * alpha * tc / ts * np.cos(np.pi * tc / ts * (1 + alpha))) / (np.pi * tc / ts * (1 - (4 * alpha * tc / ts) ** 2))
    return h / np.sum(h)

def generate_phase_noise(n, lw, fs):
    return np.cumsum(np.random.normal(0, np.sqrt(2 * np.pi * lw / fs), n))

def calc_psd(sig, fs):
    """DSO-tab compatible single-sided PSD in dBm/Hz."""
    x = np.real(np.asarray(sig)).astype(np.float64, copy=False).reshape(-1)
    if len(x) == 0 or fs <= 0:
        return np.array([0.0]), np.array([-300.0])
    f, pxx = welch(np.real(x), fs=fs, nperseg=min(4096, len(x)), scaling="density")
    p_dbm_hz = 10.0 * np.log10(np.maximum(pxx / 50.0 / 1e-3, 1e-30))
    return f, p_dbm_hz

def calc_fft_psd(sig, fs):
    """Single-frame periodogram PSD for comparing against Welch averaging."""
    x = np.real(np.asarray(sig)).astype(np.float64, copy=False).reshape(-1)
    if len(x) == 0 or fs <= 0:
        return np.array([0.0]), np.array([-300.0])
    x = x - float(np.mean(x))
    win = np.hanning(len(x))
    scale = fs * np.sum(win ** 2)
    X = np.fft.rfft(x * win)
    pxx = (np.abs(X) ** 2) / max(scale, 1e-30)
    if len(pxx) > 2:
        pxx[1:-1] *= 2.0
    f = np.fft.rfftfreq(len(x), 1.0 / fs)
    p_dbm_hz = 10.0 * np.log10(np.maximum(pxx / 50.0 / 1e-3, 1e-30))
    return f, p_dbm_hz

def calc_power_dbm(sig, R=50.0):
    """Time-domain RMS power calculation into 50 ohms."""
    p_w = np.mean(np.abs(sig)**2) / R
    return 10 * np.log10(p_w + 1e-20) + 30.0

def calc_utcpd_output_dbm(photocurrent_ma: float) -> float:
    # Quadratic photomixing law (P_THz ~ I_photo^2, below saturation), calibrated
    # to the NICT IOD-PMJ-13001 operating point in HANDOFF.md (~-7 mA -> ~-10 dBm @ 270 GHz).
    i_ref_ma, p_ref_dbm = 7.0, -10.0
    return p_ref_dbm + 20.0 * np.log10(max(photocurrent_ma, 1e-6) / i_ref_ma)

def dbm_to_w(p_dbm: float) -> float:
    return 1e-3 * (10.0 ** (float(p_dbm) / 10.0))

def w_to_dbm(p_w: float) -> float:
    return 10.0 * np.log10(max(float(p_w), 1e-30) * 1e3)

def effective_cspr_db(cfg: SimConfig) -> float:
    metrics = calc_mzm_drive_metrics(
        cfg.awg_rf_power_dbm,
        cfg.mzm_drive_gain_db,
        cfg.cspr_db,
        cfg.awg_ref_power_dbm,
        cfg.mzm_vpi_v,
        cfg.mzm_phi_bias_deg,
        cfg.mzm_input_ohm,
    )
    return float(metrics["effective_cspr_db"])

def optical_sideband_mode(cfg: SimConfig) -> str:
    mode = str(getattr(cfg, "optical_sideband_mode", "DSB") or "DSB").strip().upper()
    return "SSB" if mode == "SSB" else "DSB"

def calc_mzm_drive_metrics(
    awg_rf_dbm: float,
    drive_gain_db: float,
    cspr_ref_db: float,
    awg_ref_dbm: float,
    vpi_v: float = 7.0,
    phi_bias_deg: float = 45.0,
    input_ohm: float = 50.0,
) -> dict[str, float]:
    rf_in_dbm = float(awg_rf_dbm) + float(drive_gain_db)
    p_rf_w = dbm_to_w(rf_in_dbm)
    v_rms = np.sqrt(max(p_rf_w, 0.0) * max(float(input_ohm), 1e-12))
    phi_b = np.deg2rad(float(np.clip(phi_bias_deg, 1e-3, 89.999)))
    u_rms = np.pi * v_rms / (2.0 * max(float(vpi_v), 1e-12))
    m_eff = abs(u_rms * np.tan(phi_b))
    cspr_from_drive = -20.0 * np.log10(max(m_eff, 1e-12))
    # The entered/measured CSPR is kept as a reference value only. Simulation
    # uses the drive-derived CSPR so IF input power changes modulation index,
    # MZM distortion, UTC-PD sideband power, and ZBD output band power together.
    eff_cspr = cspr_from_drive
    return {
        "rf_in_dbm": rf_in_dbm,
        "rf_power_w": p_rf_w,
        "v_rms": float(v_rms),
        "u_rms": float(u_rms),
        "m_eff": float(m_eff),
        "phi_bias_deg": float(phi_bias_deg),
        "vpi_v": float(vpi_v),
        "input_ohm": float(input_ohm),
        "entered_cspr_db": float(cspr_ref_db),
        "effective_cspr_db": float(eff_cspr),
    }

def calc_utcpd_optical_line_powers(cfg: SimConfig) -> dict[str, float]:
    """Infer UTC-PD input optical line powers from photocurrent and CSPR."""
    p_total_w = max(
        (float(cfg.utcpd_photocurrent_ma) * 1e-3)
        / max(float(cfg.utcpd_responsivity_a_per_w), 1e-12),
        1e-15,
    )
    cspr_eff_db = effective_cspr_db(cfg)
    cspr_lin = max(10.0 ** (abs(cspr_eff_db) / 10.0), 1e-12)
    mode = optical_sideband_mode(cfg)
    n_sidebands = 1.0 if mode == "SSB" else 2.0
    # CSPR is carrier power divided by total modulated signal power. For DSB,
    # that signal power is shared by the two sidebands; for SSB it is all in
    # the retained sideband.
    p_mzm_carrier_w = p_total_w / max(2.0 + 1.0 / cspr_lin, 1e-30)
    p_tone1_w = p_mzm_carrier_w
    p_signal_total_w = p_mzm_carrier_w / cspr_lin
    p_sideband_each_w = p_signal_total_w / n_sidebands
    return {
        "total_w": p_total_w,
        "tone1_w": p_tone1_w,
        "mzm_carrier_w": p_mzm_carrier_w,
        "sideband_each_w": p_sideband_each_w,
        "signal_total_w": p_signal_total_w,
        "dsb_total_w": p_signal_total_w,
        "mzm_branch_w": p_mzm_carrier_w + p_signal_total_w,
        "tone_ratio": 1.0,
        "effective_cspr_db": float(cspr_eff_db),
        "sideband_mode": mode,
        "total_dbm": w_to_dbm(p_total_w),
        "tone1_dbm": w_to_dbm(p_tone1_w),
        "mzm_carrier_dbm": w_to_dbm(p_mzm_carrier_w),
        "sideband_each_dbm": w_to_dbm(p_sideband_each_w),
        "signal_total_dbm": w_to_dbm(p_signal_total_w),
        "dsb_total_dbm": w_to_dbm(p_signal_total_w),
    }

def calc_utcpd_rf_line_powers(cfg: SimConfig) -> dict[str, float]:
    """Expected UTC-PD RF line powers after photomixing, normalized to TX power."""
    total_rf_w = dbm_to_w(cfg.utcpd_target_dbm)
    cspr_lin = max(10.0 ** (abs(effective_cspr_db(cfg)) / 10.0), 1e-12)
    mode = optical_sideband_mode(cfg)
    n_sidebands = 1.0 if mode == "SSB" else 2.0
    carrier_w = total_rf_w / max(1.0 + 1.0 / cspr_lin, 1e-30)
    signal_total_w = carrier_w / cspr_lin
    sideband_each_w = signal_total_w / n_sidebands
    return {
        "total_w": total_rf_w,
        "carrier_w": carrier_w,
        "sideband_each_w": sideband_each_w,
        "signal_total_w": signal_total_w,
        "dsb_total_w": signal_total_w,
        "sideband_mode": mode,
        "total_dbm": w_to_dbm(total_rf_w),
        "carrier_dbm": w_to_dbm(carrier_w),
        "sideband_each_dbm": w_to_dbm(sideband_each_w),
        "signal_total_dbm": w_to_dbm(signal_total_w),
        "dsb_total_dbm": w_to_dbm(signal_total_w),
    }

def add_display_line_mw(
    freq_axis: np.ndarray,
    accum_mw: np.ndarray,
    center: float,
    power_dbm: float,
    fwhm: float,
) -> None:
    sigma = max(float(fwhm) / 2.354820045, np.finfo(float).eps)
    accum_mw += dbm_to_w(power_dbm) * 1e3 * np.exp(-0.5 * ((freq_axis - center) / sigma) ** 2)

def classify_isac_waveform(waveform: str) -> str:
    w = str(waveform or "").strip().upper().replace("_", "-")
    if w in {"TONE", "CW"}:
        return "Tone"
    if w in {"OFDM", "OFDM-16QAM"}:
        return "OFDM"
    if w in {"DFT-S-OFDM", "DFTS-OFDM", "SC-FDMA"}:
        return "DFT-s-OFDM"
    if "FMCW" in w:
        return "FMCW"
    if "LFM" in w:
        return "LFM-QAM"
    return "SC"

def next_pow2(n: int) -> int:
    return 1 << int(np.ceil(np.log2(max(int(n), 1))))

def estimate_waveform_bandwidth_hz(cfg: SimConfig, waveform_kind: str | None = None) -> float:
    kind = classify_isac_waveform(cfg.waveform) if waveform_kind is None else waveform_kind
    baud = max(float(cfg.baud_gbaud) * 1e9, 1.0)
    rrc = max(float(cfg.rrc_beta), 0.0)
    if kind == "Tone":
        return max(0.05e9, min(0.5e9, 0.25 * baud))
    if kind == "FMCW":
        return max(float(cfg.chirp_bw_ghz) * 1e9, 0.05e9)
    if kind == "LFM-QAM":
        return max(float(cfg.chirp_bw_ghz) * 1e9 + baud * (1.0 + rrc), baud)
    if kind in {"OFDM", "DFT-s-OFDM"}:
        return baud
    return baud * (1.0 + rrc)

def make_bandpass_mask(f_axis: np.ndarray, f_if_hz: float, bandwidth_hz: float) -> np.ndarray:
    half_bw = 0.5 * max(float(bandwidth_hz), 1.0)
    low = max(30e3, float(f_if_hz) - half_bw)
    high = min(30e9, float(f_if_hz) + half_bw)
    if high <= low:
        high = min(30e9, max(low * 1.01, float(f_if_hz) + 1e6))
    af = np.abs(f_axis)
    return (af >= low) & (af <= high)

def apply_mzm_eo_response(sig: np.ndarray, fs: float, eo_bw_hz: float) -> np.ndarray:
    """Apply the MXAN-LN-40 electro-optic bandwidth as a mild low-pass response."""
    x = np.asarray(sig, dtype=np.float64)
    if len(x) < 8 or fs <= 0 or eo_bw_hz <= 0:
        return x
    f = np.fft.fftfreq(len(x), d=1.0 / fs)
    # Spec gives S21 EO bandwidth typ. 30 GHz.  A first-order magnitude model
    # keeps the response near-flat inside the passband while still making
    # 20-GBaud waveforms see more edge loss than 15-GBaud waveforms.
    h = 1.0 / np.sqrt(1.0 + (np.abs(f) / max(float(eo_bw_hz), 1.0)) ** 2)
    y = np.real(np.fft.ifft(np.fft.fft(x) * h))
    return y

def apply_awg_dac_quantization(sig: np.ndarray, bits: float, headroom_db: float = 1.0) -> np.ndarray:
    """Emulate the AWG's finite-ENOB DAC by quantizing to its own peak.

    The step size is set from this waveform's own peak (with a small headroom
    so the peak doesn't sit exactly at full scale), so a higher-PAPR waveform
    -- e.g. the more up-sampled low-symbol-rate DFT-s-OFDM blocks -- uses less
    of the DAC's RMS range and sees proportionally more quantization noise,
    the same way a real 8-bit AWG would.
    """
    x = np.asarray(sig, dtype=np.float64)
    if bits <= 0 or bits >= 16 or len(x) < 2:
        return x
    peak = float(np.max(np.abs(x))) + 1e-30
    full_scale = peak * 10.0 ** (max(headroom_db, 0.0) / 20.0)
    step = 2.0 * full_scale / (2.0 ** bits)
    return np.clip(np.round(x / step) * step, -full_scale, full_scale)

def si_normalized_cfr_delay_profile(
    freqs_hz: np.ndarray,
    h: np.ndarray,
    weight: np.ndarray | None,
    range_axis_m: np.ndarray,
    range_scale_m_per_s: float,
) -> dict[str, np.ndarray | float]:
    """Single-capture SI-referenced CFR delay profile.

    The zero-delay SI is modeled as the weighted constant component of H(f).
    The plotted profile is the delay matched sum of H/H_SI - 1, so a target
    echo appears as exp(-j 2*pi*f*tau) while the common SI phase is removed.
    """
    f = np.asarray(freqs_hz, dtype=np.float64).reshape(-1)
    hc = np.asarray(h, dtype=np.complex128).reshape(-1)
    r = np.asarray(range_axis_m, dtype=np.float64).reshape(-1)
    n = min(len(f), len(hc))
    if n < 16 or len(r) < 4 or not np.isfinite(range_scale_m_per_s) or range_scale_m_per_s <= 0:
        return {
            "range_m": np.zeros(0, dtype=np.float64),
            "profile_db": np.zeros(0, dtype=np.float64),
            "peak_m": float("nan"),
            "coherence": float("nan"),
            "si_ref_abs": float("nan"),
        }
    f = f[:n]
    hc = hc[:n]
    if weight is None:
        w = np.ones(n, dtype=np.float64)
    else:
        w = np.asarray(weight, dtype=np.float64).reshape(-1)[:n]
        if len(w) < n:
            w = np.pad(w, (0, n - len(w)), constant_values=0.0)
    valid = (
        np.isfinite(f)
        & np.isfinite(hc.real)
        & np.isfinite(hc.imag)
        & np.isfinite(w)
        & (w > 0.0)
        & (np.abs(hc) > 1e-15)
    )
    if np.count_nonzero(valid) < 16:
        return {
            "range_m": np.zeros(0, dtype=np.float64),
            "profile_db": np.zeros(0, dtype=np.float64),
            "peak_m": float("nan"),
            "coherence": float("nan"),
            "si_ref_abs": float("nan"),
        }
    f = f[valid]
    hc = hc[valid]
    w = w[valid]
    w = w / (np.nanmax(w) + 1e-15)
    good = w >= 0.03
    if np.count_nonzero(good) >= 16:
        f = f[good]
        hc = hc[good]
        w = w[good]
    si_ref = np.sum(w * hc) / (np.sum(w) + 1e-15)
    if (not np.isfinite(si_ref.real)) or abs(si_ref) <= 1e-15:
        si_ref = np.median(hc)
    if (not np.isfinite(si_ref.real)) or abs(si_ref) <= 1e-15:
        return {
            "range_m": np.zeros(0, dtype=np.float64),
            "profile_db": np.zeros(0, dtype=np.float64),
            "peak_m": float("nan"),
            "coherence": float("nan"),
            "si_ref_abs": float("nan"),
        }
    residual = hc / (si_ref + 1e-15) - 1.0
    residual = residual - (np.sum(w * residual) / (np.sum(w) + 1e-15))
    tau = r / float(range_scale_m_per_s)
    amp = np.zeros(len(tau), dtype=np.complex128)
    # Chunk over range bins to avoid creating very large frequency x range matrices.
    chunk = 512
    for i0 in range(0, len(tau), chunk):
        tt = tau[i0:i0 + chunk]
        phase = np.exp(1j * 2.0 * np.pi * f[:, np.newaxis] * tt[np.newaxis, :])
        amp[i0:i0 + chunk] = np.sum((w * residual)[:, np.newaxis] * phase, axis=0)
    mag = np.abs(amp) / (np.sum(w) + 1e-15)
    prof_db = 20.0 * np.log10(mag / (np.nanmax(mag) + 1e-30) + 1e-30)
    peak_idx = int(np.nanargmax(mag)) if len(mag) else 0
    peak_m = float(r[peak_idx]) if len(r) > peak_idx else float("nan")
    phase_unit = residual / (np.abs(residual) + 1e-15)
    coherence = float(np.abs(np.sum(w * phase_unit)) / (np.sum(w) + 1e-15))
    return {
        "range_m": r,
        "profile_db": prof_db,
        "peak_m": peak_m,
        "coherence": coherence,
        "si_ref_abs": float(abs(si_ref)),
    }

def make_osa_display_spectrum(cfg: SimConfig) -> dict[str, np.ndarray]:
    """UTC-PD input optical line display inferred from photocurrent and CSPR."""
    f2 = float(cfg.optical_center_freq_thz)
    f1 = f2 - float(cfg.rf_carrier_ghz) / 1000.0
    f_if_thz = float(cfg.if_ghz) / 1000.0
    lo = min(f1, f2 - f_if_thz) - 0.03
    hi = max(f1, f2 + f_if_thz) + 0.03
    f = np.linspace(lo, hi, 8000)
    optical_lines = calc_utcpd_optical_line_powers(cfg)
    floor_dbm = float(optical_lines["sideband_each_dbm"]) - 45.0
    p_mw = np.full_like(f, dbm_to_w(floor_dbm) * 1e3)

    # This is a display-only OSA trace width. The physical laser linewidth is
    # much narrower than the plotted span, so using it directly makes the
    # carrier miss FFT/display bins and falsely appear below the DSB.
    display_fwhm_thz = 0.0015

    tone1_dbm = float(optical_lines["tone1_dbm"])
    carrier_dbm = float(optical_lines["mzm_carrier_dbm"])
    sideband_dbm = float(optical_lines["sideband_each_dbm"])
    mode = optical_sideband_mode(cfg)
    add_display_line_mw(f, p_mw, f2, carrier_dbm, display_fwhm_thz)
    if mode == "DSB":
        add_display_line_mw(f, p_mw, f2 - f_if_thz, sideband_dbm, display_fwhm_thz)
    add_display_line_mw(f, p_mw, f2 + f_if_thz, sideband_dbm, display_fwhm_thz)

    sig_mw = p_mw.copy()
    lo_mw = np.full_like(f, dbm_to_w(floor_dbm) * 1e3)
    add_display_line_mw(f, lo_mw, f1, tone1_dbm, display_fwhm_thz)
    return {
        "freq_thz": f,
        "signal_dbm": 10.0 * np.log10(np.maximum(sig_mw, 1e-30)),
        "lo_dbm": 10.0 * np.log10(np.maximum(lo_mw, 1e-30)),
        "tone1_freq_thz": np.asarray(f1),
        "tone2_freq_thz": np.asarray(f2),
        "tone1_power_dbm": np.asarray(tone1_dbm),
        "carrier_power_dbm": np.asarray(carrier_dbm),
        "sideband_power_dbm": np.asarray(sideband_dbm),
        "total_optical_power_dbm": np.asarray(float(optical_lines["total_dbm"])),
        "sideband_mode": np.asarray(mode),
    }

def make_utcpd_rf_display_spectrum(cfg: SimConfig) -> dict[str, np.ndarray]:
    """Display UTC-PD output as carrier + signal sideband RF line powers in dBm."""
    rf = float(cfg.rf_carrier_ghz)
    f_if = float(cfg.if_ghz)
    bw = max(float(cfg.baud_gbaud), 0.2)
    span = f_if + 0.5 * bw + 5.0
    f = np.linspace(rf - span, rf + span, 6000)
    rf_lines = calc_utcpd_rf_line_powers(cfg)
    floor_dbm = float(rf_lines["sideband_each_dbm"]) - 55.0
    p_mw = np.full_like(f, dbm_to_w(floor_dbm) * 1e3)
    line_fwhm_ghz = 0.12 if classify_isac_waveform(cfg.waveform) == "Tone" else max(0.35, bw / 3.0)
    mode = optical_sideband_mode(cfg)
    add_display_line_mw(f, p_mw, rf, float(rf_lines["carrier_dbm"]), line_fwhm_ghz)
    if mode == "DSB":
        add_display_line_mw(f, p_mw, rf - f_if, float(rf_lines["sideband_each_dbm"]), line_fwhm_ghz)
    add_display_line_mw(f, p_mw, rf + f_if, float(rf_lines["sideband_each_dbm"]), line_fwhm_ghz)
    return {
        "freq_ghz": f,
        "power_dbm": 10.0 * np.log10(np.maximum(p_mw, 1e-30)),
        "carrier_freq_ghz": np.asarray(rf),
        "sideband_lo_ghz": np.asarray(rf - f_if),
        "sideband_hi_ghz": np.asarray(rf + f_if),
        "carrier_power_dbm": np.asarray(float(rf_lines["carrier_dbm"])),
        "sideband_each_dbm": np.asarray(float(rf_lines["sideband_each_dbm"])),
        "total_power_dbm": np.asarray(float(rf_lines["total_dbm"])),
        "sideband_mode": np.asarray(mode),
    }

def calc_isac_link_budget(
    distance_m: float,
    rf_ghz: float,
    tx_dbm: float,
    tx_gain_dbi: float,
    rx_gain_dbi: float,
    rcs_sqm: float,
    lna_gain_db: float,
    c1_drive_gain_db: float,
    c2_drive_gain_db: float,
    c1_cable_loss_db: float,
    c2_cable_loss_db: float,
    omt_il_db: float = 0.0,
    target_ant_gain_dbi: float = 0.0,
    target_gamma_mag: float = 0.0,
    target_pol_eff: float = 1.0,
) -> dict[str, float]:
    # One-way RX (C1): UTC-PD -> OMT -> TX ant -- FSPL -- RX ant -> OMT -> LNA
    #   P_rx_received = P_tx - L_OMT + G_tx - FSPL + G_rx - L_OMT
    # Monostatic sensing RX (C2): UTC-PD -> OMT -> TX ant -- FSPL -- RX ant
    #   (antenna-mode + structural RCS) -- FSPL -- TX ant -> OMT -> LNA
    #   P_radar_echo = P_tx - L_OMT + G_tx - L_radar + G_tx - L_OMT
    #   L_radar = 2*FSPL - G_RCS, with G_RCS = 10*log10(4*pi*sigma_eff/lambda^2)
    #   the RCS expressed as an equivalent antenna gain.
    d = max(float(distance_m), 1e-9)
    rf_hz = max(float(rf_ghz), 1e-9) * 1e9
    lam = 3e8 / rf_hz
    sigma_struct = max(float(rcs_sqm), 0.0)
    g_target = 10.0 ** (float(target_ant_gain_dbi) / 10.0)
    gamma_mag = float(np.clip(abs(float(target_gamma_mag)), 0.0, 1.0))
    pol_eff = float(np.clip(float(target_pol_eff), 0.0, 1.0))
    # Structural RCS is already an area in m^2; antenna gain and load
    # reflection must not multiply it again.  Those factors belong only to
    # the antenna-mode reradiation term.
    sigma_struct_eff = sigma_struct * pol_eff
    sigma_ant = (lam ** 2 * g_target ** 2 * gamma_mag ** 2 * pol_eff) / (4.0 * np.pi)
    sigma = max(sigma_struct_eff + sigma_ant, 1e-12)
    omt_il_db = float(omt_il_db)
    fspl_one_way_db = 20.0 * np.log10(4.0 * np.pi * d * rf_hz / 3e8)
    rcs_gain_db = 10.0 * np.log10(4.0 * np.pi * sigma / (lam ** 2) + 1e-30)
    radar_loss_db = 2.0 * fspl_one_way_db - rcs_gain_db
    c1_total_loss_db = fspl_one_way_db - tx_gain_dbi - rx_gain_dbi + 2.0 * omt_il_db
    c2_total_loss_db = radar_loss_db - tx_gain_dbi - rx_gain_dbi + 2.0 * omt_il_db
    c1_rf_dbm = float(tx_dbm - c1_total_loss_db)
    c2_rf_dbm = float(tx_dbm - c2_total_loss_db)
    c1_if_chain_db = float(c1_drive_gain_db - c1_cable_loss_db)
    c2_if_chain_db = float(c2_drive_gain_db - c2_cable_loss_db)
    return {
        "delay_ns": 2.0 * d / 3e8 * 1e9,
        "fspl_one_way_db": fspl_one_way_db,
        "rcs_gain_db": rcs_gain_db,
        "radar_loss_db": radar_loss_db,
        "omt_il_db": omt_il_db,
        "radar_path_loss_db": c2_total_loss_db,
        "c1_total_loss_db": c1_total_loss_db,
        "structural_rcs_sqm": sigma_struct,
        "reradiated_structural_rcs_sqm": sigma_struct_eff,
        "antenna_mode_rcs_sqm": sigma_ant,
        "effective_rcs_sqm": sigma,
        "c1_rf_dbm": c1_rf_dbm,
        "c2_rf_dbm": c2_rf_dbm,
        "c1_if_chain_db": c1_if_chain_db,
        "c2_if_chain_db": c2_if_chain_db,
        "c1_if_dbm": c1_rf_dbm + lna_gain_db + c1_if_chain_db,
        "c2_if_dbm": c2_rf_dbm + lna_gain_db + c2_if_chain_db,
    }

def calc_uxr0404a_noise_vrms(vscale_mv: float, bandwidth_hz: float) -> float:
    """Approximate UXR0404A input-referred noise for the selected V/div scale."""
    fs_v_array = np.array([0.060, 0.100, 0.160, 0.400, 0.800, 1.6, 4.0])
    vrms_v_array = np.array([0.34e-3, 0.49e-3, 0.72e-3, 1.6e-3, 3.4e-3, 6.7e-3, 16e-3])
    full_scale_v = max(float(vscale_mv), 1e-6) * 1e-3 * 8.0
    noise_40g = float(np.interp(full_scale_v, fs_v_array, vrms_v_array))
    return noise_40g * np.sqrt(max(float(bandwidth_hz), 1.0) / 40e9)

def calc_if_band_metrics(sig: np.ndarray, fs: float, f_if_hz: float, bandwidth_hz: float,
                         noise_vrms: float = 0.0) -> dict[str, float]:
    x = np.asarray(sig, dtype=np.float64).reshape(-1)
    if len(x) < 8 or fs <= 0:
        return {
            "band_power_dbm": float("nan"),
            "snr_db": float("nan"),
            "noise_dbm": float("nan"),
            "noise_power_dbm": float("nan"),
            "noise_floor_dbm_hz": float("nan"),
            "noise_density_dbm_hz": float("nan"),
        }
    f, psd_dbm_hz = calc_psd(x, fs)
    psd_mw_hz = 10.0 ** (np.asarray(psd_dbm_hz, dtype=np.float64) / 10.0)
    lo = max(0.0, f_if_hz - 0.5 * bandwidth_hz)
    hi = min(0.5 * fs, f_if_hz + 0.5 * bandwidth_hz)
    band = (f >= lo) & (f <= hi)
    if np.count_nonzero(band) < 2:
        return {
            "band_power_dbm": float("nan"),
            "snr_db": float("nan"),
            "noise_dbm": float("nan"),
            "noise_power_dbm": float("nan"),
            "noise_floor_dbm_hz": float("nan"),
            "noise_density_dbm_hz": float("nan"),
        }
    df = float(np.nanmedian(np.diff(f))) if len(f) > 1 else 1.0
    analysis_bw = max(hi - lo, 1.0)
    p_mw = float(np.sum(psd_mw_hz[band]) * df)
    guard_hz = max(0.1 * bandwidth_hz, 5.0 * df)
    finite_floor = np.isfinite(psd_mw_hz) & (psd_mw_hz > 0.0)
    noise_band = (
        (f > max(30e3, 5.0 * df))
        & (f < 0.95 * 0.5 * fs)
        & ((f < lo - guard_hz) | (f > hi + guard_hz))
        & finite_floor
    )
    if np.count_nonzero(noise_band) < 8:
        noise_band = (
            (f > max(30e3, 5.0 * df))
            & (f < 0.95 * 0.5 * fs)
            & (~band)
            & finite_floor
        )
    if np.count_nonzero(noise_band) < 8:
        noise_band = (
            (f > max(30e3, 5.0 * df))
            & (f < 0.95 * 0.5 * fs)
            & finite_floor
        )
    floor_pool = (
        (f > max(30e3, 5.0 * df))
        & (f < 0.95 * 0.5 * fs)
        & finite_floor
    )
    noise_density_mw_hz = float("nan")
    if np.count_nonzero(floor_pool) >= 8:
        # Use a robust displayed-spectrum floor, not only an out-of-band slice.
        # Wide symbol rates can occupy most of the IF span; an out-of-band-only
        # estimate then samples a different analog region and makes noise power
        # non-physical.  The lower-quartile floor tracks the visible PSD floor
        # while rejecting in-band payload peaks and SSBI/spurious lines.
        noise_density_mw_hz = float(np.quantile(psd_mw_hz[floor_pool], 0.25))
    elif np.count_nonzero(noise_band) >= 8:
        noise_density_mw_hz = float(np.median(psd_mw_hz[noise_band]))
    noise_mw_dso = ((float(noise_vrms) ** 2) / 50.0) * 1e3 * (max(hi - lo, 1.0) / max(40e9, hi - lo))
    # The table's noise density must match the plotted spectrum floor.  Use
    # the measured PSD median first; the UXR V/div model is only a last-resort
    # fallback when a spectrum floor cannot be estimated at all.
    if np.isfinite(noise_density_mw_hz) and noise_density_mw_hz > 0.0:
        noise_mw = noise_density_mw_hz * analysis_bw
        noise_source = "spectrum_floor"
    else:
        noise_mw = noise_mw_dso
        noise_density_mw_hz = noise_mw / analysis_bw
        noise_source = "uxr_model"
    noise_mw = max(noise_mw, 1e-30)
    sig_mw = max(p_mw - noise_mw, 1e-30)
    noise_power_dbm = 10.0 * np.log10(noise_mw)
    noise_density_dbm_hz = 10.0 * np.log10(max(noise_density_mw_hz, 1e-30))
    return {
        "band_power_dbm": 10.0 * np.log10(sig_mw),
        "raw_band_power_dbm": 10.0 * np.log10(max(p_mw, 1e-30)),
        "noise_dbm": noise_power_dbm,
        "noise_power_dbm": noise_power_dbm,
        "noise_floor_dbm_hz": noise_density_dbm_hz,
        "noise_density_dbm_hz": noise_density_dbm_hz,
        "analysis_bw_hz": analysis_bw,
        "noise_source": noise_source,
        "snr_db": 10.0 * np.log10(sig_mw / noise_mw),
    }

def calc_if_signal_band_power_mw(sig: np.ndarray, fs: float, f_if_hz: float,
                                 bandwidth_hz: float) -> float:
    """Integrate deterministic IF signal power without estimating a noise floor."""
    x = np.asarray(sig, dtype=np.float64).reshape(-1)
    if len(x) < 8 or fs <= 0:
        return float("nan")
    f, psd_dbm_hz = calc_psd(x, fs)
    psd_mw_hz = 10.0 ** (np.asarray(psd_dbm_hz, dtype=np.float64) / 10.0)
    lo = max(0.0, float(f_if_hz) - 0.5 * float(bandwidth_hz))
    hi = min(0.5 * float(fs), float(f_if_hz) + 0.5 * float(bandwidth_hz))
    band = (f >= lo) & (f <= hi) & np.isfinite(psd_mw_hz)
    if np.count_nonzero(band) < 2:
        return float("nan")
    df = float(np.nanmedian(np.diff(f))) if len(f) > 1 else 1.0
    return float(np.sum(np.maximum(psd_mw_hz[band], 0.0)) * df)

def qam_hard_demod(symbols: np.ndarray, mod: str) -> np.ndarray:
    """Generic hard-decision demodulator for QAM."""
    bps = _bits_per_symbol(mod)
    num_syms = 1 << bps
    all_bits = np.arange(num_syms, dtype=np.uint8).reshape(-1, 1)
    bit_patterns = list(((all_bits >> i) & 1) for i in range(bps - 1, -1, -1))
    flat_bits = np.hstack(bit_patterns).flatten()
    const = _bits_to_qam_symbols(flat_bits, mod)
    return np.argmin(np.abs(np.asarray(symbols)[:, None] - const[None, :]), axis=1)


def estimate_measured_evm_percent(evm_db):
    if np.isfinite(evm_db):
        return 100.0 * (10.0 ** (evm_db / 20.0))
    return np.nan

def run_isac_sim(cfg: SimConfig):
    if cfg.sim_seed is not None:
        np.random.seed(int(cfg.sim_seed))
    fs = cfg.fs_gsps * 1e9
    frame_len, num_frames = int(cfg.frame_len), int(cfg.num_frames)
    step = max(int(fs * cfg.step_ns * 1e-9), 1)
    total_samples = frame_len + step * num_frames
    t = np.arange(total_samples) / fs

    baud_rate, f_if = cfg.baud_gbaud * 1e9, cfg.if_ghz * 1e9
    samples_per_sym = max(int(round(fs / baud_rate)), 1)
    d_link = max(float(cfg.target_dist_m), 1e-6)
    link = calc_isac_link_budget(
        distance_m=d_link,
        rf_ghz=cfg.rf_carrier_ghz,
        tx_dbm=cfg.utcpd_target_dbm,
        tx_gain_dbi=cfg.tx_ant_gain_dbi,
        rx_gain_dbi=cfg.rx_ant_gain_dbi,
        rcs_sqm=cfg.target_rcs_sqm,
        lna_gain_db=cfg.lna_gain_db,
        c1_drive_gain_db=cfg.c1_drive_gain_db,
        c2_drive_gain_db=cfg.c2_drive_gain_db,
        c1_cable_loss_db=cfg.c1_cable_loss_db,
        c2_cable_loss_db=cfg.c2_cable_loss_db,
        omt_il_db=cfg.omt_il_db,
        target_ant_gain_dbi=cfg.target_ant_gain_dbi,
        target_gamma_mag=cfg.target_gamma_mag,
        target_pol_eff=cfg.target_pol_eff,
    )
    radar_path_loss_db = float(link["radar_path_loss_db"])
    one_way_path_loss_db = float(link["fspl_one_way_db"])
    c1_total_loss_db = float(link["c1_total_loss_db"])
    delay_ns = float(link["delay_ns"])
    cfg.path_loss_db = radar_path_loss_db
    cfg.delay_ns = delay_ns

    # 1. Baseband & IF Upconversion (Real)
    bps = _bits_per_symbol(cfg.modulation)
    num_unique_syms = 1 << bps

    # Create a reference constellation based on the modulation
    all_bits = np.arange(num_unique_syms, dtype=np.uint8).reshape(-1, 1)
    bit_patterns = list(((all_bits >> i) & 1) for i in range(bps - 1, -1, -1))
    flat_bits = np.hstack(bit_patterns).flatten()
    qam_syms = _bits_to_qam_symbols(flat_bits, cfg.modulation)
    waveform_kind = classify_isac_waveform(cfg.waveform)
    occupied_bw_hz = estimate_waveform_bandwidth_hz(cfg, waveform_kind)
    h_rrc = rrc_filter(200, max(float(cfg.rrc_beta), 0.01), 1/baud_rate, fs)
    dft_active_bins = None
    dft_n_data = 0
    dft_n_fft = 0
    dft_pilot_active = None
    dft_tx_blocks = []
    dft_tx_symbol_blocks = []
    dft_data_scales = []
    dft_sr = 0.0
    dft_sd = 1.0

    if waveform_kind == "Tone":
        bb_sig = np.ones(total_samples, dtype=np.complex128)
        symbols = np.ones(max(total_samples // samples_per_sym, 1), dtype=np.complex128)
        sym_idx = np.zeros(len(symbols), dtype=np.int64)
        chirp = np.ones_like(t)
    elif waveform_kind == "OFDM":
        N_fft_ofdm = 2048
        N_cp = 256
        N_sym_total = N_fft_ofdm + N_cp
        num_ofdm_syms = total_samples // N_sym_total + 2
        active_sc = int(np.clip((cfg.baud_gbaud * 1e9) / (fs / N_fft_ofdm), 8, N_fft_ofdm // 2))

        ofdm_bb = np.zeros(num_ofdm_syms * N_sym_total, dtype=complex)
        tx_ofdm_syms = []
        sym_idx_list = []

        for i in range(num_ofdm_syms):
            idx = np.random.randint(0, num_unique_syms, active_sc)
            syms = qam_syms[idx]
            tx_ofdm_syms.append(syms)
            sym_idx_list.append(idx)

            X = np.zeros(N_fft_ofdm, dtype=complex)
            start_idx = N_fft_ofdm//2 - active_sc//2
            X[start_idx : start_idx + active_sc] = syms

            X_shifted = np.fft.ifftshift(X)
            x_t = np.fft.ifft(X_shifted) * np.sqrt(N_fft_ofdm)

            x_sym = np.concatenate([x_t[-N_cp:], x_t])
            ofdm_bb[i*N_sym_total : (i+1)*N_sym_total] = x_sym

        bb_sig = ofdm_bb[:total_samples]
        symbols = np.concatenate(tx_ofdm_syms)
        sym_idx = np.concatenate(sym_idx_list)
        chirp = np.ones_like(t)
    elif waveform_kind == "DFT-s-OFDM":
        n_data = max(8, int(cfg.syms_per_chirp))
        dft_oversample = max(fs / max(baud_rate, 1.0), 2.0)
        # Keep the active DFT-s-OFDM bandwidth equal to the requested symbol
        # rate: BW_active = n_data * fs / n_fft.  The earlier next_pow2()
        # rounding made 15 and 20 GBaud both land on n_fft=8192 at fs=120 GS/s,
        # so both waveforms were effectively ~15 GHz wide and EVM did not move.
        n_fft_dft = max(n_data + 8, int(round(n_data * dft_oversample)))
        num_blocks = total_samples // n_fft_dft + 2
        offsets = np.arange(-(n_data // 2), n_data - n_data // 2, dtype=np.int64)
        active_bins = np.mod(offsets, n_fft_dft).astype(np.int64)
        dft_active_bins = active_bins
        dft_n_data = n_data
        dft_n_fft = n_fft_dft
        occupied_bw_hz = min(0.95 * fs, float(n_data) * fs / max(float(n_fft_dft), 1.0))

        def scfdma_block(syms: np.ndarray) -> tuple[np.ndarray, float]:
            spread = np.fft.fft(syms) / np.sqrt(max(len(syms), 1))
            X = np.zeros(n_fft_dft, dtype=np.complex128)
            X[active_bins] = spread
            x = np.fft.ifft(X)
            scale = np.sqrt(np.mean(np.abs(x) ** 2)) + 1e-15
            return x / scale, float(scale)

        sym_idx = np.random.randint(0, num_unique_syms, num_blocks * n_data)
        symbols = qam_syms[sym_idx]
        zc = np.asarray(generate_zadoff_chu(n_data, u=1), dtype=np.complex128)
        pilot_block, _ = scfdma_block(zc)
        dft_pilot_active = np.fft.fft(pilot_block)[active_bins]
        rho = float(np.clip(cfg.pilot_rho, 0.0, 0.95))
        sr = np.sqrt(rho)
        sd = np.sqrt(max(0.0, 1.0 - rho))
        dft_sr = float(sr)
        dft_sd = float(sd)
        blocks = []
        for i in range(num_blocks):
            sym_block = symbols[i * n_data:(i + 1) * n_data]
            data_block, scale_i = scfdma_block(sym_block)
            tx_block = sr * pilot_block + sd * data_block
            blocks.append(tx_block)
            dft_tx_blocks.append(tx_block)
            dft_tx_symbol_blocks.append(sym_block)
            dft_data_scales.append(scale_i)
        bb_sig = np.concatenate(blocks)[:total_samples]
        chirp = np.ones_like(t)
    elif waveform_kind == "FMCW":
        sweep_bw = max(cfg.chirp_bw_ghz, 0.01) * 1e9
        t0 = t - np.mean(t)
        k = sweep_bw / max(t[-1] - t[0], 1.0 / fs)
        chirp = np.exp(1j * np.pi * k * (t0 ** 2))
        bb_sig = chirp
        symbols = np.ones(max(total_samples // samples_per_sym, 1), dtype=np.complex128)
        sym_idx = np.zeros(len(symbols), dtype=np.int64)
    else:
        sym_idx = np.random.randint(0, num_unique_syms, int(total_samples / samples_per_sym) + 1)
        symbols = qam_syms[sym_idx]
        upsampled = np.zeros(len(symbols) * samples_per_sym, dtype=complex)
        upsampled[::samples_per_sym] = symbols

        bb_sig = np.convolve(upsampled, h_rrc, mode="same")[:total_samples]

        if waveform_kind == "LFM-QAM":
            sweep_bw = max(cfg.chirp_bw_ghz, 0.01) * 1e9
            t0 = t - np.mean(t)
            k = sweep_bw / max(t[-1] - t[0], 1.0 / fs)
            chirp = np.exp(1j * np.pi * k * (t0 ** 2))
            bb_sig = bb_sig * chirp
        else:
            chirp = np.ones_like(t)

    x_if_cplx = bb_sig * np.exp(1j * 2 * np.pi * f_if * t)
    x_if_real = np.real(x_if_cplx)
    x_if_real = apply_awg_dac_quantization(x_if_real, cfg.awg_dac_bits)

    # Optical field model: one MZM/data tone and one second optical tone.  The
    # MZM branch uses a third-order Taylor expansion of cos(phi_b + u*s(t)), so
    # AWG IF power changes modulation index, CSPR, and IMD terms together.
    s_drive = x_if_real / (np.sqrt(np.mean(x_if_real ** 2)) + 1e-12)
    s_mzm = apply_mzm_eo_response(s_drive, fs, max(float(cfg.mzm_eo_bw_ghz), 0.01) * 1e9)
    optical_lines = calc_utcpd_optical_line_powers(cfg)
    p_opt_total_w = optical_lines["total_w"]
    p_lo_laser_w = optical_lines["tone1_w"]
    p_carrier_w = optical_lines["mzm_carrier_w"]
    p_signal_w = optical_lines["signal_total_w"]
    p_data_laser_w = optical_lines["mzm_branch_w"]
    mzm_metrics = calc_mzm_drive_metrics(
        cfg.awg_rf_power_dbm,
        cfg.mzm_drive_gain_db,
        cfg.cspr_db,
        cfg.awg_ref_power_dbm,
        cfg.mzm_vpi_v,
        cfg.mzm_phi_bias_deg,
        cfg.mzm_input_ohm,
    )
    phi_b = np.deg2rad(float(np.clip(cfg.mzm_phi_bias_deg, 1e-3, 89.999)))
    u_rms = float(mzm_metrics.get("u_rms", 0.0))
    if optical_sideband_mode(cfg) == "SSB":
        # A single-drive Taylor model is a DSB MZM model.  For the optional SSB
        # display mode, keep the complex single-sideband envelope but scale it
        # from the drive-derived CSPR so power sweeps remain physical.
        m_ssb = x_if_cplx / (np.sqrt(np.mean(np.abs(x_if_cplx) ** 2)) + 1e-12)
        e_mod = np.sqrt(max(p_carrier_w, 0.0)) + np.sqrt(max(p_signal_w, 0.0)) * m_ssb
    else:
        tan_phi = np.tan(phi_b)
        e_shape = np.cos(phi_b) * (
            1.0
            - u_rms * tan_phi * s_mzm
            - 0.5 * (u_rms ** 2) * (s_mzm ** 2)
            + (u_rms ** 3) * tan_phi * (s_mzm ** 3) / 6.0
        )
        e_mod = np.sqrt(max(p_data_laser_w, 0.0)) * e_shape / (np.sqrt(np.mean(np.abs(e_shape) ** 2)) + 1e-15)

    #
    lw = cfg.linewidth_mhz * 1e6
    phi_1 = generate_phase_noise(total_samples, lw, fs)
    phi_2 = generate_phase_noise(total_samples, lw, fs)
    if cfg.coherence_mode == "Self-coherent": phi_2 = phi_1

    if cfg.carrier_wander_enable and cfg.carrier_wander_mhz > 0:
        wander = np.cumsum(np.random.randn(total_samples))
        wander = (wander - np.mean(wander)) / (np.std(wander) + 1e-12) * (cfg.carrier_wander_mhz * 1e6)
        phi_wander = 2 * np.pi * np.cumsum(wander) / fs
    else:
        phi_wander = np.zeros(total_samples)

    e_data = e_mod * np.exp(1j * phi_1)
    e_lo = np.sqrt(p_lo_laser_w) * np.exp(1j * (phi_2 + phi_wander))

    # UTC-PD photomixes the two optical tones and drives the antenna directly (no THz PA).
    beat_raw = e_data * np.conj(e_lo)
    beat_pwr_w = np.mean(np.abs(beat_raw)**2) / 50.0
    target_w = 10**((cfg.utcpd_target_dbm - 30) / 10)
    v_tx_out = beat_raw * np.sqrt(target_w / max(float(beat_pwr_w), 1e-30))

    #
    alpha_si = 10**(-cfg.omt_iso_db / 20.0)
    beta_echo = 10**(-radar_path_loss_db / 20.0)
    delay_samp = int(delay_ns * 1e-9 * fs)

    v_si = v_tx_out * alpha_si if cfg.si_enable else np.zeros_like(v_tx_out)
    v_echo = np.zeros_like(v_tx_out)
    #
    omega_c_tau = 2.0 * np.pi * (cfg.rf_carrier_ghz * 1e9) * (delay_ns * 1e-9)
    if delay_samp > 0:
        v_echo[delay_samp:] = v_tx_out[:-delay_samp] * beta_echo * np.exp(-1j * omega_c_tau)
    else:
        v_echo = v_tx_out * beta_echo * np.exp(-1j * omega_c_tau)

    # LNA model: gain + noise figure.
    v_lna_in = v_si + v_echo
    lna_gain_lin = 10 ** (cfg.lna_gain_db / 20.0)
    v_lna_sig = v_lna_in * lna_gain_lin
    dso_analog_bw_hz = min(max(float(cfg.dso_bandwidth_ghz) * 1e9, 1.0), 0.5 * fs)
    if_chain_bw_hz = min(30e9, dso_analog_bw_hz, 0.5 * fs)
    rf_noise_bw_hz = dso_analog_bw_hz
    if_noise_bw_hz = if_chain_bw_hz
    n_in_dbm = -174.0 + 10 * np.log10(rf_noise_bw_hz) + cfg.lna_nf_db
    n_out_w = 10 ** ((n_in_dbm + cfg.lna_gain_db - 30.0) / 10.0)
    n_out_vrms2 = n_out_w * 50.0
    awgn_lna = np.sqrt(n_out_vrms2 / 2.0) * (np.random.randn(total_samples) + 1j * np.random.randn(total_samples))
    v_rx_in = v_lna_sig + awgn_lna

    # 6. Receiver detection.
    if cfg.rx_mode == "ZBD":
        p_inst_w = (np.abs(v_rx_in) ** 2) / 50.0
        v_det = cfg.zbd_responsivity_vpw * p_inst_w
        nep_w_sqrt_hz = cfg.zbd_nep_pw_sqrt_hz * 1e-12
        v_nep_rms = cfg.zbd_responsivity_vpw * nep_w_sqrt_hz * np.sqrt(if_noise_bw_hz)
        v_det += np.random.normal(0.0, v_nep_rms, total_samples)
        v_rec = v_det - np.mean(v_det)
    else:
        v_mix_in = v_rx_in - v_si * lna_gain_lin
        v_rec = np.real(v_mix_in)

    # 6-2. IF Amp (Broadband: ~30kHz to 30GHz)
    N_f = len(v_rec)
    f_axis = np.fft.fftfreq(N_f, 1/fs)

    #
    amp_mask = (np.abs(f_axis) > 30e3) & (np.abs(f_axis) < if_chain_bw_hz)
    v_rec_filt = np.real(np.fft.ifft(np.fft.fft(v_rec) * amp_mask))

    #
    c2_if_gain_lin = 10**((cfg.c2_drive_gain_db - cfg.c2_cable_loss_db) / 20.0)
    dso_noise_vrms = calc_uxr0404a_noise_vrms(cfg.dso_vscale_mv, dso_analog_bw_hz)
    v_rec_amp = v_rec_filt * c2_if_gain_lin
    n_if_w_c2 = 10**((-174.0 + 10*np.log10(if_noise_bw_hz) + cfg.if_amp_nf_db + cfg.c2_drive_gain_db - 30.0) / 10.0)
    v_dso_in = (
        v_rec_amp
        + np.sqrt(n_if_w_c2 * 50.0 / 2.0) * np.random.randn(N_f)
        + dso_noise_vrms * np.random.randn(N_f)
    )

    c2_target_phase_components = None
    if cfg.rx_mode == "ZBD":
        # Separate the deterministic target terms of |SI + echo|^2.  A single
        # real square-law output contains a cos(carrier phase) null, so its
        # power can ripple strongly with distance even while echo RF power
        # decreases as R^-4.  Averaging the two orthogonal cross-term phases
        # gives the carrier-phase-independent target-power envelope used by
        # the link budget and distance-sweep metrics.
        v_si_lna = v_si * lna_gain_lin
        v_echo_lna = v_echo * lna_gain_lin
        v_echo_self_raw = cfg.zbd_responsivity_vpw * (np.abs(v_echo_lna) ** 2) / 50.0
        v_cross_complex_raw = (
            2.0
            * cfg.zbd_responsivity_vpw
            * v_si_lna
            * np.conj(v_echo_lna)
            / 50.0
        )

        def _c2_if_component(x: np.ndarray) -> np.ndarray:
            x_real = np.asarray(np.real(x), dtype=np.float64)
            x_real = x_real - float(np.mean(x_real))
            return np.real(np.fft.ifft(np.fft.fft(x_real) * amp_mask)) * c2_if_gain_lin

        c2_target_phase_components = (
            _c2_if_component(v_echo_self_raw),
            _c2_if_component(np.real(v_cross_complex_raw)),
            _c2_if_component(np.imag(v_cross_complex_raw)),
        )

    v_rec = v_dso_in  # note
    v_demod = hilbert(v_dso_in) if cfg.rx_mode == 'Mixer' else v_dso_in.astype(np.complex128)

    # 7. Range Profile & Delay Estimation
    c2_sic_for_metrics = v_dso_in
    if cfg.rx_mode == 'ZBD':
        # ZBD produces an IF term through carrier/sideband beating. Use the
        # same real-IF TX reference that the DSO DSP uses, not |TX|^2, which
        # mainly emphasizes DC/2IF envelope terms and gives unstable range
        # sidelobes for communication-bearing waveforms.
        ref_sig = x_if_real - np.mean(x_if_real)
        ref_sig_filt = np.real(np.fft.ifft(np.fft.fft(ref_sig) * amp_mask)) * c2_if_gain_lin

        # Apply Digital Self-Interference Cancellation (SIC) for ZBD
        if cfg.si_enable:
            v_si_zbd_raw = cfg.zbd_responsivity_vpw * (np.abs(v_si * lna_gain_lin)**2) / 50.0
            v_si_zbd = v_si_zbd_raw - np.mean(v_si_zbd_raw)
            v_si_zbd = np.real(np.fft.ifft(np.fft.fft(v_si_zbd_raw) * amp_mask)) * c2_if_gain_lin
            c2_sic_for_metrics = v_dso_in - v_si_zbd
            radar_input = v_dso_in
        else:
            radar_input = v_dso_in

        ref_sig = ref_sig_filt
    else:
        # Mixer is coherent. Correlate complex RF envelopes.
        ref_sig = np.real(x_if_real)
        radar_input = v_dso_in

    radar_input = np.asarray(radar_input, dtype=np.float64).reshape(-1)
    ref_sig = np.asarray(ref_sig, dtype=np.float64).reshape(-1)
    radar_input = radar_input - float(np.mean(radar_input)) if len(radar_input) else radar_input
    ref_sig = ref_sig - float(np.mean(ref_sig)) if len(ref_sig) else ref_sig
    sync_corr_full = np.abs(fftconvolve(radar_input, ref_sig[::-1], mode="full"))
    lags_full = np.arange(-(len(ref_sig) - 1), len(radar_input), dtype=np.int64)
    si_norm_range_axis = np.zeros(0, dtype=np.float64)
    si_norm_profile_db = np.zeros(0, dtype=np.float64)
    si_norm_target_over_si_db = float("nan")
    si_norm_phase_coherence = float("nan")
    try:
        frame_n = min(int(frame_len), len(radar_input), len(ref_sig))
        n_frames_norm = max(1, min(int(num_frames), 64))
        if frame_n >= 32 and n_frames_norm >= 1:
            ref_frame = np.asarray(ref_sig[:frame_n], dtype=np.float64)
            ref_frame = ref_frame - float(np.mean(ref_frame))
            ref_frame_c = hilbert(ref_frame)
            lags_norm = np.arange(-(frame_n - 1), frame_n, dtype=np.int64)
            near_zero = np.abs(lags_norm) <= max(2, int(0.02 * frame_n))
            corr_sum = None
            phase_unit: list[complex] = []
            for k in range(n_frames_norm):
                start = min(k * step, max(0, len(radar_input) - frame_n))
                seg = np.asarray(radar_input[start:start + frame_n], dtype=np.float64)
                if len(seg) < frame_n:
                    break
                seg = seg - float(np.mean(seg))
                corr_c = fftconvolve(hilbert(seg), np.conj(ref_frame_c[::-1]), mode="full")
                if corr_sum is None:
                    corr_sum = np.zeros_like(corr_c, dtype=np.complex128)
                if np.any(near_zero):
                    z_idx_local = np.flatnonzero(near_zero)
                    z_idx = int(z_idx_local[int(np.argmax(np.abs(corr_c[near_zero])))])
                else:
                    z_idx = int(np.argmin(np.abs(lags_norm)))
                si_phase = float(np.angle(corr_c[z_idx] + 1e-30))
                phase_unit.append(np.exp(1j * si_phase))
                corr_sum += corr_c * np.exp(-1j * si_phase)
            if corr_sum is not None:
                mag = np.abs(corr_sum / max(1, len(phase_unit)))
                rng_norm_full = lags_norm.astype(np.float64) * (3e8 / 2.0 / fs)
                valid_norm = (rng_norm_full >= 0.0) & (rng_norm_full <= 4.0)
                si_norm_range_axis = rng_norm_full[valid_norm]
                si_mag = mag[valid_norm]
                si_norm_profile_db = 20.0 * np.log10(si_mag / (np.max(si_mag) + 1e-30) + 1e-30)
                if np.any(near_zero):
                    z_idx_local = np.flatnonzero(near_zero)
                    z_idx = int(z_idx_local[int(np.argmax(mag[near_zero]))])
                else:
                    z_idx = int(np.argmin(np.abs(lags_norm)))
                target_mask_full = (
                    np.isfinite(rng_norm_full)
                    & (np.abs(rng_norm_full - float(cfg.target_dist_m)) <= max(0.05, 3e8 / (2.0 * max(occupied_bw_hz, 1.0))))
                    & (rng_norm_full >= 0.0)
                )
                if np.any(target_mask_full):
                    t_idx_all = np.flatnonzero(target_mask_full)
                    t_idx = int(t_idx_all[int(np.argmax(mag[target_mask_full]))])
                    si_norm_target_over_si_db = 20.0 * np.log10((mag[t_idx] + 1e-30) / (mag[z_idx] + 1e-30))
                if phase_unit:
                    si_norm_phase_coherence = float(np.abs(np.mean(np.asarray(phase_unit))))
    except Exception:
        pass

    best_delay = int(lags_full[int(np.argmax(sync_corr_full))]) if len(sync_corr_full) else 0

    if cfg.si_enable:
        demod_delay = 0  # Dominant signal is SI
    else:
        demod_delay = best_delay  # Dominant signal is Echo

    corr_db = 20.0 * np.log10(sync_corr_full + 1e-20)
    corr_db = corr_db - np.max(corr_db)

    range_axis_full = lags_full.astype(np.float64) * (3e8 / 2.0 / fs)
    valid_range = (range_axis_full >= 0.0) & (range_axis_full <= 5.0)
    range_axis = range_axis_full[valid_range]
    range_profile_db = corr_db[valid_range]
    si_cfr_range_axis = np.zeros(0, dtype=np.float64)
    si_cfr_profile_db = np.zeros(0, dtype=np.float64)
    si_cfr_peak_m = float("nan")
    si_cfr_coherence = float("nan")
    try:
        n_cfr = min(len(radar_input), len(ref_sig))
        if n_cfr >= 64 and len(range_axis) >= 8:
            x_ref = np.asarray(ref_sig[:n_cfr], dtype=np.float64)
            y_rx = np.asarray(radar_input[:n_cfr], dtype=np.float64)
            win_cfr = np.hanning(n_cfr)
            X = np.fft.fft((x_ref - float(np.mean(x_ref))) * win_cfr)
            Y = np.fft.fft((y_rx - float(np.mean(y_rx))) * win_cfr)
            f_cfr = np.fft.fftfreq(n_cfr, d=1.0 / fs)
            band_cfr = make_bandpass_mask(f_cfr, f_if, occupied_bw_hz)
            band_cfr &= f_cfr > 0.0
            sxx = np.abs(X) ** 2
            band_cfr &= sxx > (np.nanmax(sxx) + 1e-30) * 1e-5
            if np.count_nonzero(band_cfr) >= 16:
                idx_cfr = np.argsort(f_cfr[band_cfr])
                h_cfr = (Y[band_cfr] * np.conj(X[band_cfr])) / (sxx[band_cfr] + 1e-30)
                w_cfr = sxx[band_cfr] / (np.nanmax(sxx[band_cfr]) + 1e-30)
                si_cfr = si_normalized_cfr_delay_profile(
                    f_cfr[band_cfr][idx_cfr],
                    h_cfr[idx_cfr],
                    w_cfr[idx_cfr],
                    range_axis,
                    3e8 / 2.0,
                )
                si_cfr_range_axis = np.asarray(si_cfr["range_m"], dtype=np.float64)
                si_cfr_profile_db = np.asarray(si_cfr["profile_db"], dtype=np.float64)
                si_cfr_peak_m = float(si_cfr["peak_m"])
                si_cfr_coherence = float(si_cfr["coherence"])
    except Exception:
        pass
    proc_gain_db = 10.0 * np.log10(max(len(ref_sig), 1))
    radar_snr_db = float("nan")
    pslr_db = float("nan")
    selected_range_m = float("nan")
    self_interference_range_m = float("nan")
    zero_guard_m = float("nan")
    if len(range_profile_db) > 8:
        prof_lin = sync_corr_full[valid_range]
        si_idx = int(np.argmax(prof_lin))
        self_interference_range_m = float(range_axis[si_idx])
        if len(range_axis) > 1:
            dr_m = float(np.median(np.diff(range_axis)))
        else:
            dr_m = 3e8 / 2.0 / fs
        range_res_m = 3e8 / (2.0 * max(float(occupied_bw_hz), 1.0))
        zero_guard_m = max(0.05, 2.0 * range_res_m)
        target_window_m = max(0.05, 2.0 * range_res_m)

        target_mask = (
            np.isfinite(range_axis)
            & (np.abs(range_axis - float(cfg.target_dist_m)) <= target_window_m)
            & (range_axis > zero_guard_m)
        )
        if np.any(target_mask):
            target_indices = np.flatnonzero(target_mask)
            pk = int(target_indices[int(np.argmax(prof_lin[target_mask]))])
        else:
            link_mask = np.isfinite(range_axis) & (range_axis > zero_guard_m)
            if np.any(link_mask):
                link_indices = np.flatnonzero(link_mask)
                pk = int(link_indices[int(np.argmax(prof_lin[link_mask]))])
            else:
                pk = si_idx
        selected_range_m = float(range_axis[pk])
        guard = max(3, int(np.ceil(max(zero_guard_m, 2.0 * dr_m) / max(dr_m, 1e-12))))
        side = np.ones(len(range_profile_db), dtype=bool)
        side[max(0, pk - guard):min(len(side), pk + guard + 1)] = False
        side &= ~(np.isfinite(range_axis) & (np.abs(range_axis) <= zero_guard_m))
        if np.any(side):
            side_max = float(np.max(range_profile_db[side]))
            noise_med = float(np.median(range_profile_db[side]))
            pslr_db = float(range_profile_db[pk] - side_max)
            radar_snr_db = float(range_profile_db[pk] - noise_med)

    # 8. Remote Comm Receiver (1-way Comm Path + DSP)
    #
    d = d_link
    path_loss_com_db = one_way_path_loss_db
    effective_one_way_loss_db = c1_total_loss_db
    beta_com = 10**(-effective_one_way_loss_db / 20.0)
    delay_samp_com = int((d / 3e8 * 1e9) * 1e-9 * fs)

    v_com = np.zeros_like(v_tx_out)
    omega_c_tau_com = 2.0 * np.pi * (cfg.rf_carrier_ghz * 1e9) * (d / 3e8)
    if delay_samp_com > 0:
        v_com[delay_samp_com:] = v_tx_out[:-delay_samp_com] * beta_com * np.exp(-1j * omega_c_tau_com)
    else:
        v_com = v_tx_out * beta_com * np.exp(-1j * omega_c_tau_com)

    v_lna_sig_com = v_com * lna_gain_lin
    awgn_lna_com = np.sqrt(n_out_vrms2 / 2.0) * (np.random.randn(total_samples) + 1j * np.random.randn(total_samples))
    v_rx_in_com = v_lna_sig_com + awgn_lna_com

    if cfg.rx_mode == "ZBD":
        p_inst_w_com = (np.abs(v_rx_in_com) ** 2) / 50.0
        v_det_com = cfg.zbd_responsivity_vpw * p_inst_w_com
        v_det_com += np.random.normal(0.0, v_nep_rms, total_samples)
        v_rec_com = v_det_com - np.mean(v_det_com)
    else:
        #
        if cfg.coherence_mode == "Self-coherent":
            phi_remote_total = np.zeros(total_samples)
        else:
            lw_remote = cfg.linewidth_mhz * 1e6
            phi_remote = generate_phase_noise(total_samples, lw_remote, fs)
            if cfg.carrier_wander_enable and cfg.carrier_wander_mhz > 0:
                wander_remote = np.cumsum(np.random.randn(total_samples))
                wander_remote = (wander_remote - np.mean(wander_remote)) / (np.std(wander_remote) + 1e-12) * (cfg.carrier_wander_mhz * 1e6)
                phi_remote_total = phi_remote + 2 * np.pi * np.cumsum(wander_remote) / fs
            else:
                phi_remote_total = phi_remote
        v_mix_in_com = v_rx_in_com * np.exp(-1j * phi_remote_total)
        v_rec_com = np.real(v_mix_in_com)

    N_f_com = len(v_rec_com)
    f_axis_com = np.fft.fftfreq(N_f_com, 1/fs)
    amp_mask_com = (np.abs(f_axis_com) > 30e3) & (np.abs(f_axis_com) < if_chain_bw_hz)
    v_rec_filt_com = np.real(np.fft.ifft(np.fft.fft(v_rec_com) * amp_mask_com))
    c1_if_gain_lin = 10**((cfg.c1_drive_gain_db - cfg.c1_cable_loss_db) / 20.0)
    n_if_w_c1 = 10**((-174.0 + 10*np.log10(if_noise_bw_hz) + cfg.if_amp_nf_db + cfg.c1_drive_gain_db - 30.0) / 10.0)
    v_dso_in_com = (
        v_rec_filt_com * c1_if_gain_lin
        + np.sqrt(n_if_w_c1 * 50.0 / 2.0) * np.random.randn(N_f_com)
        + dso_noise_vrms * np.random.randn(N_f_com)
    )
    v_demod_com = hilbert(v_dso_in_com) if cfg.rx_mode == "Mixer" else v_dso_in_com.astype(np.complex128)
    analysis_bw_hz = max(occupied_bw_hz, 1.0)
    c1_band_metrics = calc_if_band_metrics(v_dso_in_com, fs, f_if, analysis_bw_hz, dso_noise_vrms)
    c2_raw_band_metrics = calc_if_band_metrics(v_dso_in, fs, f_if, analysis_bw_hz, dso_noise_vrms)
    c2_coherent_band_metrics = calc_if_band_metrics(
        c2_sic_for_metrics, fs, f_if, analysis_bw_hz, dso_noise_vrms
    )
    c2_band_metrics = dict(c2_coherent_band_metrics)
    if c2_target_phase_components is not None:
        echo_self_if, cross_i_if, cross_q_if = c2_target_phase_components
        p_echo_self_mw = calc_if_signal_band_power_mw(
            echo_self_if, fs, f_if, analysis_bw_hz
        )
        p_cross_i_mw = calc_if_signal_band_power_mw(
            cross_i_if, fs, f_if, analysis_bw_hz
        )
        p_cross_q_mw = calc_if_signal_band_power_mw(
            cross_q_if, fs, f_if, analysis_bw_hz
        )
        if all(np.isfinite(v) for v in (p_echo_self_mw, p_cross_i_mw, p_cross_q_mw)):
            # E_phi[(A cos(phi) + B sin(phi))^2] = (A^2 + B^2)/2.
            # Echo self-beat is phase independent and is added as positive power.
            target_mw = max(
                p_echo_self_mw + 0.5 * (p_cross_i_mw + p_cross_q_mw),
                1e-30,
            )
            noise_dbm = float(c2_coherent_band_metrics.get("noise_power_dbm", float("nan")))
            noise_mw = 10.0 ** (noise_dbm / 10.0) if np.isfinite(noise_dbm) else float("nan")
            c2_band_metrics["band_power_dbm"] = 10.0 * np.log10(target_mw)
            c2_band_metrics["raw_band_power_dbm"] = (
                10.0 * np.log10(target_mw + noise_mw)
                if np.isfinite(noise_mw)
                else 10.0 * np.log10(target_mw)
            )
            c2_band_metrics["snr_db"] = (
                10.0 * np.log10(target_mw / max(noise_mw, 1e-30))
                if np.isfinite(noise_mw)
                else float("nan")
            )
            c2_band_metrics["metric_mode"] = "phase_averaged_target"
            c2_band_metrics["echo_self_power_dbm"] = 10.0 * np.log10(max(p_echo_self_mw, 1e-30))
            c2_band_metrics["si_echo_cross_power_dbm"] = 10.0 * np.log10(
                max(0.5 * (p_cross_i_mw + p_cross_q_mw), 1e-30)
            )

    # 9. Demodulation (Remote Comm)
    lo_if = np.exp(-1j * 2 * np.pi * f_if * t)
    rx_bb_raw = v_demod_com * lo_if
    bb_cutoff_hz = min(0.45 * fs, max(0.5 * occupied_bw_hz * 1.35, 0.2e9))
    bb_freq = np.fft.fftfreq(len(rx_bb_raw), 1 / fs)
    rx_bb_raw = np.fft.ifft(np.fft.fft(rx_bb_raw) * (np.abs(bb_freq) <= bb_cutoff_hz))
    demod_delay = delay_samp_com

    evm_db, ser = float('nan'), float('nan')
    best_eq, best_tx, best_idx = None, None, None
    sym_eq = np.zeros(0, dtype=np.complex128)
    sym_tx = np.zeros(0, dtype=np.complex128)
    best_metric = np.inf

    if waveform_kind == "OFDM":
        lag_candidates = range(max(0, demod_delay - 5), demod_delay + 5)
        for lag in lag_candidates:
            temp_eq, temp_tx, temp_idx = [], [], []
            H_chan = None

            for i in range(num_ofdm_syms):
                start_idx = i * N_sym_total + lag
                if start_idx + N_sym_total > len(rx_bb_raw): break

                y_t = rx_bb_raw[start_idx + N_cp : start_idx + N_sym_total]
                if len(y_t) < N_fft_ofdm: break

                Y = np.fft.fftshift(np.fft.fft(y_t) / np.sqrt(N_fft_ofdm))
                start_sc = N_fft_ofdm//2 - active_sc//2
                rx_syms = Y[start_sc : start_sc + active_sc]
                tx_ref = tx_ofdm_syms[i]

                if H_chan is None:
                    # Symbol 0 as Preamble for Zero-Forcing Equalization
                    H_chan = rx_syms / (tx_ref + 1e-15)
                    H_chan = np.convolve(H_chan, np.ones(5)/5, mode='same') # Smooth
                else:
                    eq_syms = rx_syms / (H_chan + 1e-15)
                    #
                    cpe = np.mean(eq_syms * np.conj(tx_ref))
                    eq_syms = eq_syms * np.exp(-1j * np.angle(cpe))
                    temp_eq.append(eq_syms)
                    temp_tx.append(tx_ref)
                    temp_idx.append(sym_idx_list[i])

            if temp_eq:
                teq = np.concatenate(temp_eq)
                ttx = np.concatenate(temp_tx)
                tidx = np.concatenate(temp_idx)
                nmse = np.mean(np.abs(teq - ttx)**2) / (np.mean(np.abs(ttx)**2) + 1e-15)
                if nmse < best_metric:
                    best_metric = nmse
                    best_eq, best_tx, best_idx = teq, ttx, tidx

    elif waveform_kind == "DFT-s-OFDM" and dft_active_bins is not None and dft_pilot_active is not None:
        lag_candidates = range(max(0, demod_delay - 8), demod_delay + 9)
        for lag in lag_candidates:
            rec_syms = []
            ref_syms = []
            ref_idx = []
            for i, tx_block in enumerate(dft_tx_blocks):
                start_idx = i * dft_n_fft + lag
                if start_idx + dft_n_fft > len(rx_bb_raw):
                    break
                y = rx_bb_raw[start_idx:start_idx + dft_n_fft]
                h_blk = np.vdot(tx_block, y) / (np.vdot(tx_block, tx_block) + 1e-15)
                y_eq = y / (h_blk + 1e-15)
                active = np.fft.fft(y_eq)[dft_active_bins]
                data_active = (active - dft_sr * dft_pilot_active) / max(dft_sd, 1e-12)
                scale_i = dft_data_scales[i] if i < len(dft_data_scales) else 1.0
                sy_est = np.fft.ifft(data_active * scale_i * np.sqrt(max(dft_n_data, 1)))
                sy_ref = dft_tx_symbol_blocks[i]
                if len(sy_est) == len(sy_ref):
                    rec_syms.append(sy_est)
                    ref_syms.append(sy_ref)
                    ref_idx.append(sym_idx[i * dft_n_data:(i + 1) * dft_n_data])
            if rec_syms:
                teq = np.concatenate(rec_syms)
                ttx = np.concatenate(ref_syms)
                tidx = np.concatenate(ref_idx)
                scale = np.sqrt(np.mean(np.abs(ttx) ** 2) / (np.mean(np.abs(teq) ** 2) + 1e-15))
                teq = teq * scale
                ph = np.vdot(teq, ttx)
                teq = teq * np.exp(-1j * np.angle(ph + 1e-15))
                nmse = np.mean(np.abs(teq - ttx) ** 2) / (np.mean(np.abs(ttx) ** 2) + 1e-15)
                if nmse < best_metric:
                    best_metric = nmse
                    best_eq, best_tx, best_idx = teq, ttx, tidx

    elif waveform_kind not in {"Tone", "FMCW"}:
        # QAM / LFM-QAM processing
        if waveform_kind == "LFM-QAM":
            local_chirp = np.zeros_like(chirp)
            if demod_delay > 0:
                local_chirp[demod_delay:] = chirp[:-demod_delay]
            else:
                local_chirp = chirp
            rx_bb_raw = rx_bb_raw * np.conj(local_chirp)

        rx_bb = np.convolve(rx_bb_raw, h_rrc, mode="same")

        delay_sym = int(round(demod_delay / max(samples_per_sym, 1)))
        lag_candidates = {max(delay_sym + d, 0) for d in range(-2, 3)}
        train_len = 2048

        best_corr = -1.0
        best_off = 0
        best_lag = 0

        search_len = min(2000, len(symbols))
        for off in range(samples_per_sym):
            sym_stream = rx_bb[off::samples_per_sym]
            for lag in sorted(lag_candidates):
                if lag >= len(sym_stream): continue
                m_search = min(len(sym_stream) - lag, search_len)
                if m_search < 200: continue

                sym_rx = sym_stream[lag:lag + m_search]
                tx_ref = symbols[:m_search]

                #
                #
                chunk_size = 10
                num_chunks = m_search // chunk_size
                if num_chunks == 0: continue

                rx_c = sym_rx[:num_chunks*chunk_size].reshape(num_chunks, chunk_size)
                tx_c = tx_ref[:num_chunks*chunk_size].reshape(num_chunks, chunk_size)
                corr = np.sum(np.abs(np.sum(rx_c * np.conj(tx_c), axis=1)))

                if corr > best_corr:
                    best_corr = float(corr)
                    best_off = off
                    best_lag = lag

        sym_stream = rx_bb[best_off::samples_per_sym]
        m = min(len(sym_stream) - best_lag, len(symbols))
        if m >= 200:
            sym_rx = sym_stream[best_lag:best_lag + m]
            tx_ref = symbols[:m]

            # AGC: normalize RX symbols to the reference average power.
            scale = np.sqrt(np.mean(np.abs(tx_ref)**2) / (np.mean(np.abs(sym_rx)**2) + 1e-15))
            sym_rx = sym_rx * scale

            #
            preamble_len = min(200, len(sym_rx))
            h_ph = np.sum(sym_rx[:preamble_len] * np.conj(tx_ref[:preamble_len]))
            sym_rx = sym_rx * np.exp(-1j * np.angle(h_ph + 1e-15))

            g0 = 50
            g1 = min(m - 50, g0 + train_len)
            if g1 > g0:
                if cfg.rx_mode == "Mixer":
                    #
                    ph = np.unwrap(np.angle(sym_rx * np.conj(tx_ref) + 1e-15))
                    ph_s = np.convolve(ph, np.ones(21)/21, mode="same")
                    sym_rx = sym_rx * np.exp(-1j * ph_s)

                    #
                    eq_all = sc_fde_equalizer(sym_rx, tx_ref, num_taps=cfg.sc_fde_taps, enable=cfg.sc_fde_enable)
                else:
                    eq_all = sc_fde_equalizer(sym_rx, tx_ref, num_taps=cfg.sc_fde_taps, enable=cfg.sc_fde_enable)
                    t_fit = tx_ref[g0:g1]

                err = eq_all - tx_ref
                skip = min(1000, len(err) // 2)
                if len(err) > skip and skip > 0:
                    nmse = np.mean(np.abs(err[skip:]) ** 2) / (np.mean(np.abs(tx_ref[skip:]) ** 2) + 1e-15)
                else:
                    nmse = np.mean(np.abs(err) ** 2) / (np.mean(np.abs(tx_ref) ** 2) + 1e-15)
                best_metric = nmse
                best_eq, best_tx, best_idx = eq_all, tx_ref, sym_idx[:m]

    if best_eq is not None:
        sym_eq, sym_tx = best_eq, best_tx
        evm = np.sqrt(best_metric)
        evm_db = 20 * np.log10(evm + 1e-15)
        rx_idx = qam_hard_demod(sym_eq, cfg.modulation)
        ser = float(np.mean(best_idx != rx_idx))
    elif waveform_kind in {"Tone", "FMCW"}:
        sym_eq = np.zeros(0, dtype=np.complex128)
        sym_tx = np.zeros(0, dtype=np.complex128)

    osa_display = make_osa_display_spectrum(cfg)
    rf_display = make_utcpd_rf_display_spectrum(cfg)
    rf_line_powers = calc_utcpd_rf_line_powers(cfg)
    return {
        "bb_sig": bb_sig, "fs": fs, "rf_c": cfg.rf_carrier_ghz * 1e9, "step": step, "frame_len": frame_len, "num_frames": num_frames,
        "waveform_kind": waveform_kind,
        "occupied_bw_hz": occupied_bw_hz,
        "if_center_hz": f_if,
        "radar_path_loss_db": radar_path_loss_db,
        "one_way_fspl_db": one_way_path_loss_db,
        "round_trip_fspl_db": 2.0 * one_way_path_loss_db,
        "rcs_gain_db": link["rcs_gain_db"],
        "radar_loss_db": link["radar_loss_db"],
        "structural_rcs_sqm": link["structural_rcs_sqm"],
        "reradiated_structural_rcs_sqm": link["reradiated_structural_rcs_sqm"],
        "antenna_mode_rcs_sqm": link["antenna_mode_rcs_sqm"],
        "effective_rcs_sqm": link["effective_rcs_sqm"],
        "rf_noise_bw_hz": rf_noise_bw_hz,
        "if_noise_bw_hz": if_noise_bw_hz,
        "optical_center_freq_thz": cfg.optical_center_freq_thz,
        "e_data": e_data, "e_lo": e_lo, "v_tx_out": v_tx_out,
        "v_rx_in_rad": v_rx_in, "v_si": v_si, "v_echo": v_echo,
        "v_rec_com": v_dso_in_com, "v_rec_c1": v_dso_in_com, "v_rec_c2": c2_sic_for_metrics,
        "v_rec_c2_raw": v_dso_in,
        "sym_tx": sym_tx, "sym_eq": sym_eq, "evm_db": evm_db, "ser": ser,
        "range_axis_m": range_axis, "range_profile_db": range_profile_db,
        "si_norm_range_axis_m": si_norm_range_axis,
        "si_norm_range_profile_db": si_norm_profile_db,
        "si_norm_target_over_si_db": si_norm_target_over_si_db,
        "si_norm_phase_coherence": si_norm_phase_coherence,
        "si_cfr_range_axis_m": si_cfr_range_axis,
        "si_cfr_range_profile_db": si_cfr_profile_db,
        "si_cfr_peak_m": si_cfr_peak_m,
        "si_cfr_coherence": si_cfr_coherence,
        "c1_band_metrics": c1_band_metrics, "c2_band_metrics": c2_band_metrics,
        "c2_coherent_band_metrics": c2_coherent_band_metrics,
        "c2_raw_band_metrics": c2_raw_band_metrics,
        "radar_snr_db": radar_snr_db, "pslr_db": pslr_db, "processing_gain_db": proc_gain_db,
        "radar_pre_snr_db_c2": c2_band_metrics.get("snr_db", float("nan")),
        "snr_rad_post_db_c2": radar_snr_db,
        "radar_processing_gain_db_c2": proc_gain_db,
        "snr_rad_pg_corrected_db_c2": radar_snr_db - proc_gain_db if np.isfinite(radar_snr_db) and np.isfinite(proc_gain_db) else float("nan"),
        "selected_range_m": selected_range_m,
        "self_interference_range_m": self_interference_range_m,
        "zero_guard_m": zero_guard_m,
        "dso_noise_vrms": dso_noise_vrms,
        "optical_power_w": p_opt_total_w,
        "optical_data_laser_w": p_data_laser_w,
        "optical_lo_laser_w": p_lo_laser_w,
        "optical_carrier_w": p_carrier_w,
        "optical_dsb_w": p_signal_w,
        "optical_signal_w": p_signal_w,
        "optical_sideband_each_w": optical_lines["sideband_each_w"],
        "optical_line_powers": optical_lines,
        "utcpd_rf_line_powers": rf_line_powers,
        "mzm_metrics": mzm_metrics,
        "observed_cspr_db": mzm_metrics.get("effective_cspr_db", cfg.cspr_db),
        "osa_display": osa_display,
        "utcpd_rf_display": rf_display,
    }

class PhotonicIsacSimPanel:
    def __init__(self, parent: ttk.Frame, plot_parent: ttk.Frame = None, awg_source=None, show_awg_params: bool = True):
        self.parent = parent
        self.plot_parent = plot_parent if plot_parent else parent
        self.awg_source = awg_source
        self.show_awg_params = show_awg_params
        self.after_id, self.frame_idx, self.data = None, 0, None
        self.params = {}

        self.status_var = tk.StringVar(value="Ready")
        self.demod_var = tk.StringVar()
        self.anim_ms = tk.IntVar(value=100)
        self.carrier_wander_enable_var = tk.BooleanVar(value=True)
        self.si_enable_var = tk.BooleanVar(value=True)
        self.ssb_enable_var = tk.BooleanVar(value=False)
        self.sim_welch_psd_var = tk.BooleanVar(value=True)
        self.show_si_norm_range_var = tk.BooleanVar(value=False)
        self.rx_mode_var = tk.StringVar(value="ZBD")
        self.coherence_var = tk.StringVar(value="Free-running")
        if self.awg_source is not None:
            self.awg_fs_var = self.awg_source.fs_var
            self.awg_ip_var = self.awg_source.ip_var
            self.awg_port_var = self.awg_source.port_var
            self.awg_ch_var = self.awg_source.ch_var
            self.awg_vpp_var = self.awg_source.vpp_var

        self._build_ui()
        self._apply_default_sim_preset()
        self._init_plot()
        self._update_table()

    def _apply_default_sim_preset(self) -> None:
        """Apply the project default preset to the UI without running a simulation."""
        preset_path = APP_DIR / "data" / "isac_sim_params_20260720.json"
        if not preset_path.exists():
            return
        try:
            with open(preset_path, "r", encoding="utf-8") as f:
                preset = json.load(f)
            self._apply_sim_preset(preset)
            if "omt_iso_db" in self.params:
                self.params["omt_iso_db"].set("24")
            self.status_var.set(f"Default preset: {preset_path.name}")
        except Exception as exc:
            self.status_var.set(f"Default preset error: {exc}")

    def _param_float(self, key: str, default: float) -> float:
        try:
            raw = self.params[key].get().strip()
            if raw == "":
                return float(default)
            return float(raw)
        except Exception:
            return float(default)

    @staticmethod
    def _var_float(var, default: float) -> float:
        try:
            raw = var.get().strip()
            if raw == "":
                return float(default)
            return float(raw)
        except Exception:
            return float(default)

    def _collect_sim_preset(self) -> dict:
        awg_keys = [
            "fs_var", "ip_var", "port_var", "ch_var", "vpp_var", "power_dbm_var",
            "rf_var", "if_var", "symbol_rate_var", "waveform_var", "modulation_var",
            "chirp_len_var", "pilot_rho_var", "rrc_beta_var",
        ]
        awg_values = {}
        awg = getattr(self, "awg_source", None)
        if awg is not None:
            for key in awg_keys:
                var = getattr(awg, key, None)
                if var is not None and hasattr(var, "get"):
                    try:
                        awg_values[key] = var.get()
                    except Exception:
                        pass
        return {
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "params": {key: var.get() for key, var in self.params.items()},
            "controls": {
                "carrier_wander_enable": bool(self.carrier_wander_enable_var.get()),
                "si_enable": bool(self.si_enable_var.get()),
                "ssb_enable": bool(self.ssb_enable_var.get()),
                "sim_welch_psd": bool(self.sim_welch_psd_var.get()),
                "show_si_norm_range": bool(self.show_si_norm_range_var.get()),
                "rx_mode": self.rx_mode_var.get(),
                "coherence_mode": self.coherence_var.get(),
                "sc_fde_enable": bool(getattr(self, "sc_fde_enable_var", tk.BooleanVar(value=True)).get()),
                "sc_fde_taps": getattr(self, "sc_fde_taps_var", tk.StringVar(value="1")).get(),
            },
            "awg": awg_values,
        }

    def _apply_sim_preset(self, preset: dict) -> None:
        for key, value in dict(preset.get("params", {})).items():
            if key in self.params:
                self.params[key].set(str(value))
        controls = dict(preset.get("controls", {}))
        bool_map = {
            "carrier_wander_enable": self.carrier_wander_enable_var,
            "si_enable": self.si_enable_var,
            "ssb_enable": self.ssb_enable_var,
            "sim_welch_psd": self.sim_welch_psd_var,
            "show_si_norm_range": self.show_si_norm_range_var,
            "sc_fde_enable": getattr(self, "sc_fde_enable_var", None),
        }
        for key, var in bool_map.items():
            if key in controls and var is not None:
                var.set(bool(controls[key]))
        if "rx_mode" in controls:
            self.rx_mode_var.set(str(controls["rx_mode"]))
        if "coherence_mode" in controls:
            self.coherence_var.set(str(controls["coherence_mode"]))
        if "sc_fde_taps" in controls and hasattr(self, "sc_fde_taps_var"):
            self.sc_fde_taps_var.set(str(controls["sc_fde_taps"]))
        awg = getattr(self, "awg_source", None)
        if awg is not None:
            for key, value in dict(preset.get("awg", {})).items():
                var = getattr(awg, key, None)
                if var is not None and hasattr(var, "set"):
                    try:
                        var.set(str(value))
                    except Exception:
                        pass
        self._update_table()
        if self.data is not None:
            self._update_range_profile()

    def _save_sim_params(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.parent,
            title="Save Simulation Parameters",
            defaultextension=".json",
            filetypes=[("JSON preset", "*.json"), ("All files", "*.*")],
            initialfile=f"isac_sim_params_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._collect_sim_preset(), f, indent=2)
            self.status_var.set(f"Saved parameters: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Save Parameters", str(exc), parent=self.parent)

    def _load_sim_params(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.parent,
            title="Load Simulation Parameters",
            filetypes=[("JSON preset", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                preset = json.load(f)
            if not isinstance(preset, dict):
                raise ValueError("Preset file must contain a JSON object.")
            self._apply_sim_preset(preset)
            self.status_var.set(f"Loaded parameters: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Load Parameters", str(exc), parent=self.parent)

    def _build_ui(self):
        # LEFT PANEL (parameters)
        left = ttk.Frame(self.parent)
        left.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # RIGHT PANEL (plots)
        self.right_frame = ttk.Frame(self.plot_parent)
        right = self.right_frame
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # Top control buttons
        ctrl = ttk.LabelFrame(left, text="Controls", padding=4)
        ctrl.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        ttk.Button(ctrl, text="Run Simulation", style="Primary.TButton", command=self.run_simulation).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(ctrl, text="Save Params", command=self._save_sim_params).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(ctrl, text="Load Params", command=self._load_sim_params).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self._anim_btn = ttk.Button(ctrl, text="Anim Start", command=self._cmd_toggle_anim)
        self._anim_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Checkbutton(ctrl, text="Welch PSD", variable=self.sim_welch_psd_var,
                        command=self._update_frame).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Checkbutton(ctrl, text="SI phase-align", variable=self.show_si_norm_range_var,
                        command=self._update_range_profile).pack(side=tk.LEFT, padx=2)

        # Split left panel into simulation parameters and physics table
        split_pane = ttk.PanedWindow(left, orient=tk.HORIZONTAL)
        split_pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_params = ttk.Frame(split_pane)
        right_table = ttk.Frame(split_pane)

        split_pane.add(left_params, weight=3)
        split_pane.add(right_table, weight=2)

        # Right table: calculated physics parameters
        tf = ttk.LabelFrame(right_table, text="Calculated Physics Parameters", padding=4)
        tf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=(4, 0))
        tbl_frame = ttk.Frame(tf)
        tbl_frame.pack(fill=tk.BOTH, expand=True)
        self.table = ttk.Treeview(tbl_frame, columns=("Value", "Unit"), show="tree headings", height=15)
        self.table.heading("#0", text="Parameter")
        self.table.heading("Value", text="Value")
        self.table.heading("Unit", text="Unit")
        self.table.column("#0", width=120)
        self.table.column("Value", width=70, anchor="center")
        self.table.column("Unit", width=40, anchor="center")
        tbl_scroll = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=tbl_scroll.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tbl_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.rows = {
            "tx":        self.table.insert("", "end", text="UTC-PD Output (TX)", values=("0.00", "dBm")),
            "opt_pwr":   self.table.insert("", "end", text="UTC-PD Optical In", values=("0.00", "mW")),
            "mzm_rf":    self.table.insert("", "end", text="MZM RF Input",        values=("-2.0", "dBm")),
            "target_gain": self.table.insert("", "end", text="Common/Re-rad Ant Gain", values=("0.00", "dBi")),
            "rcs_struct": self.table.insert("", "end", text="Structural RCS",     values=("0.00", "m^2")),
            "rcs_struct_eff": self.table.insert("", "end", text="Pol.-adjusted Structural RCS", values=("0.00", "m^2")),
            "rcs_ant":   self.table.insert("", "end", text="Antenna-mode RCS",   values=("0.00", "m^2")),
            "rcs_eff":    self.table.insert("", "end", text="Effective RCS",     values=("0.00", "m^2")),
            "delay":     self.table.insert("", "end", text="Sensing Echo Delay", values=("0.00", "ns")),
            "omt_il":    self.table.insert("", "end", text="OMT Insertion Loss (x2)", values=("0.00", "dB")),
            "comm_loss": self.table.insert("", "end", text="C1 FSPL (one-way)", values=("0.00", "dB")),
            "comm_rx":   self.table.insert("", "end", text="C1 P_rx_received",  values=("0.00", "dBm")),
            "radar_fspl2": self.table.insert("", "end", text="C2 Round-trip FSPL", values=("0.00", "dB")),
            "rcs_gain":  self.table.insert("", "end", text="C2 RCS Gain",       values=("0.00", "dB")),
            "loss":      self.table.insert("", "end", text="C2 sensing loss (2xFSPL - RCS gain)", values=("0.00", "dB")),
            "echo":      self.table.insert("", "end", text="C2 echo power", values=("0.00", "dBm")),
            "if_chain":  self.table.insert("", "end", text="C1/C2 IF Gain",     values=("0/0", "dB")),
            "c1_band":   self.table.insert("", "end", text="C1 Band Power",     values=("N/A", "dBm")),
            "c2_band":   self.table.insert("", "end", text="C2 Target Band Power (phase avg.)", values=("N/A", "dBm")),
            "c1_noise":  self.table.insert("", "end", text="C1 Noise Power",    values=("N/A", "dBm")),
            "c2_noise":  self.table.insert("", "end", text="C2 Noise Power",    values=("N/A", "dBm")),
            "c1_noise_density": self.table.insert("", "end", text="C1 Spectrum Noise Density", values=("N/A", "dBm/Hz")),
            "c2_noise_density": self.table.insert("", "end", text="C2 Spectrum Noise Density", values=("N/A", "dBm/Hz")),
            "noise_source": self.table.insert("", "end", text="Noise Source", values=("N/A", "")),
            "comm_snr":  self.table.insert("", "end", text="Comm SNR (EVM)",    values=("N/A", "dB")),
            "radar_snr": self.table.insert("", "end", text="C2 Sensing SINR", values=("N/A", "dB")),
            "range_detect": self.table.insert("", "end", text="Range Detection", values=("normalized CFR", "")),
            "range_sel": self.table.insert("", "end", text="Selected Target Range", values=("N/A", "m")),
            "si_cfr_peak": self.table.insert("", "end", text="SI-CFR Peak", values=("N/A", "m")),
            "si_cfr_coh": self.table.insert("", "end", text="SI-CFR Coherence", values=("N/A", "")),
            "si_norm_ratio": self.table.insert("", "end", text="SI-align Target/SI", values=("N/A", "dB")),
            "si_norm_coh": self.table.insert("", "end", text="SI Phase Coherence", values=("N/A", "")),
            "pslr":      self.table.insert("", "end", text="C2 PSLR",           values=("N/A", "dB")),
            "proc_gain": self.table.insert("", "end", text="Processing Gain",   values=("N/A", "dB")),
            "evm_pct":   self.table.insert("", "end", text="Comm EVM",          values=("N/A",  "%")),
            "evm_snr":   self.table.insert("", "end", text="EVM-implied SNR",    values=("N/A", "dB")),
        }

        # Left parameters
        param_outer = ttk.Frame(left_params)
        param_outer.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        param_canvas = tk.Canvas(param_outer, highlightthickness=0, bg="#f4f6f9")
        param_vbar = ttk.Scrollbar(param_outer, orient="vertical", command=param_canvas.yview)
        param_canvas.configure(yscrollcommand=param_vbar.set)
        param_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        param_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        params_frame = ttk.Frame(param_canvas)
        _cw = param_canvas.create_window((0, 0), window=params_frame, anchor="nw")
        params_frame.bind("<Configure>", lambda _: param_canvas.configure(scrollregion=param_canvas.bbox("all")))
        param_canvas.bind("<Configure>", lambda e: param_canvas.itemconfig(_cw, width=e.width))
        param_canvas.bind("<MouseWheel>", lambda e: param_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # AWG Parameters
        if self.show_awg_params:
            awg_grp = ttk.LabelFrame(params_frame, text="AWG Parameters", padding=8)
            awg_grp.pack(fill=tk.X, pady=(0, 5))

            ttk.Label(awg_grp, text="AWG Fs [GS/s]").grid(row=0, column=0, sticky="w", pady=2)
            self.awg_fs_var = tk.StringVar(value="120")
            ttk.Entry(awg_grp, textvariable=self.awg_fs_var, width=10).grid(row=0, column=1, sticky="w")

            ttk.Label(awg_grp, text="AWG IP").grid(row=1, column=0, sticky="w", pady=2)
            self.awg_ip_var = tk.StringVar(value="192.168.1.2")
            ttk.Entry(awg_grp, textvariable=self.awg_ip_var, width=12).grid(row=1, column=1, sticky="w")

            ttk.Label(awg_grp, text="AWG Port").grid(row=2, column=0, sticky="w", pady=2)
            self.awg_port_var = tk.StringVar(value="60007")
            ttk.Entry(awg_grp, textvariable=self.awg_port_var, width=10).grid(row=2, column=1, sticky="w")

            ttk.Label(awg_grp, text="Channel").grid(row=3, column=0, sticky="w", pady=2)
            self.awg_ch_var = tk.StringVar(value="4")
            ttk.Combobox(awg_grp, textvariable=self.awg_ch_var, values=["1", "2", "3", "4", "1,2", "1,3"], width=8).grid(row=3, column=1, sticky="w")

            ttk.Label(awg_grp, text="Amplitude (Vpp)").grid(row=4, column=0, sticky="w", pady=2)
            self.awg_vpp_var = tk.StringVar(value="0.1")
            ttk.Entry(awg_grp, textvariable=self.awg_vpp_var, width=10).grid(row=4, column=1, sticky="w")

        # Simulation Parameters
        grp = ttk.LabelFrame(params_frame, text="Simulation Parameters", padding=8)
        grp.pack(fill=tk.X)

        def add_p(row, key, label, val):
            ttk.Label(grp, text=label).grid(row=row, column=0, sticky="w", pady=2)
            self.params[key] = tk.StringVar(value=val)
            self.params[key].trace_add("write", self._update_table)
            e = ttk.Entry(grp, textvariable=self.params[key], width=10)
            e.grid(row=row, column=1, sticky="w")
            return e

        # removed fs_gsps
        add_p(1, "linewidth_mhz", "Laser Linewidth [MHz]", "0.015")
        add_p(2, "cspr_db", "Measured CSPR Ref [dB]", "13")
        add_p(3, "opt_center_thz", "Opt Tone Center [THz]", "193.41")
        add_p(4, "mzm_drive_gain_db", "MZM Drive Amp [dB]", "8.0")
        add_p(5, "utcpd_resp_aw", "UTC-PD Resp. [A/W]", "0.24")
        # removed baud_gbaud
        # removed if_ghz
        self.waveform_var = tk.StringVar(value="16QAM") # Hidden, managed by awg
        # removed chirp_bw_ghz

        ttk.Checkbutton(grp, text="Enable Carrier Wander", variable=self.carrier_wander_enable_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(grp, text="Enable SI Leakage", variable=self.si_enable_var).grid(row=8, column=0, columnspan=1, sticky="w", pady=2)
        ttk.Checkbutton(grp, text="SSB Optical Modulation", variable=self.ssb_enable_var, command=self._update_table).grid(row=8, column=1, columnspan=1, sticky="w", pady=2)
        ttk.Label(grp, text="Coherence Mode").grid(row=9, column=0, sticky="w", pady=2)
        ttk.Combobox(grp, textvariable=self.coherence_var, values=["Free-running", "Self-coherent"], width=12).grid(row=9, column=1)
        ttk.Label(grp, text="RX Front-end").grid(row=10, column=0, sticky="w", pady=2)
        ttk.Combobox(grp, textvariable=self.rx_mode_var, values=["Mixer", "ZBD"], width=12).grid(row=10, column=1)

        ttk.Separator(grp, orient="horizontal").grid(row=11, column=0, columnspan=2, sticky="ew", pady=5)
        add_p(12, "utcpd_photocurrent_ma", "UTC-PD Photocurrent [mA]", "7.0")
        add_p(13, "lna_gain_db",  "THz LNA Gain [dB]",      "13.0")
        add_p(14, "lna_nf_db",    "LNA NF [dB]",            "8.0")
        add_p(15, "zbd_resp_vpw", "VDI ZBD Resp. [V/W]",    "1500")
        add_p(16, "zbd_nep_pw",   "VDI ZBD NEP [pW/sqrtHz]","5")
        add_p(17, "c1_drive_gain_db","C1 Drive Amp [dB]",   "27")
        add_p(18, "if_amp_nf_db", "IF Amp NF [dB]",         "5.0")
        add_p(19, "c2_drive_gain_db","C2 Drive Amp [dB]",   "20")
        add_p(20, "tx_ant_gain_dbi", "Common Ant Gain [dBi]", "33")
        add_p(21, "mzm_vpi_v", "MZM Vpi @20GHz [V]", "3")
        add_p(22, "c1_cable_loss_db", "C1 Cable/Adaptor Loss [dB]", "10")
        add_p(23, "c2_cable_loss_db", "C2 Cable Loss [dB]", "22")
        add_p(24, "dso_vscale_mv", "UXR V/div [mV]",        "100.0")
        add_p(25, "dso_bw_ghz",    "UXR BW [GHz]",          "40.0")
        add_p(26, "omt_iso_db",   "OMT Isolation [dB]",     "24")
        add_p(27, "omt_il_db",    "OMT Insertion Loss [dB]", "2")
        add_p(28, "rcs_sqm",      "Struct. RCS [m^2]",      "0.01")
        add_p(29, "mzm_phi_bias_deg", "MZM Bias phi [deg]", "45.0")
        add_p(30, "target_gamma_mag", "Target |Gamma|",     "0.5")
        add_p(31, "target_pol_eff", "Target Pol Eff",       "1.0")
        add_p(35, "mzm_eo_bw_ghz", "MZM EO BW [GHz]", "30.0")
        add_p(36, "awg_dac_bits", "AWG DAC ENOB [bits]", "8.0")

        ttk.Label(grp, text="Target Dist [m]").grid(row=32, column=0, sticky="w", pady=2)
        self.params["target_dist_m"] = tk.StringVar(value="1.0")
        self.params["target_dist_m"].trace_add("write", self._update_table)
        ttk.Entry(grp, textvariable=self.params["target_dist_m"], width=10).grid(row=32, column=1, sticky="w")

        self.sc_fde_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp, text="Enable Post-EQ (LS)", variable=self.sc_fde_enable_var).grid(row=33, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(grp, text="Post-EQ Taps").grid(row=34, column=0, sticky="w", pady=2)
        self.sc_fde_taps_var = tk.StringVar(value="1")
        ttk.Entry(grp, textvariable=self.sc_fde_taps_var, width=10).grid(row=34, column=1, sticky="w")

        # Plot on right
        self.fig = Figure(figsize=(8, 8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        ttk.Label(right, textvariable=self.demod_var, foreground="#114488", font=("Arial", 12, "bold")).pack(pady=5)

    def _update_table(self, *args):
        try:
            d = self._param_float("target_dist_m", 1.0)
            photocurrent_ma = self._param_float("utcpd_photocurrent_ma", 7.0)
            utcpd_resp = self._param_float("utcpd_resp_aw", 0.24)
            tx_dbm = calc_utcpd_output_dbm(photocurrent_ma)
            opt_mw = (
                photocurrent_ma
                / max(utcpd_resp, 1e-12)
            )
            cspr_db = self._param_float("cspr_db", 20.0)
            opt_center = self._param_float("opt_center_thz", 193.41)
            try:
                rf_ghz = self._var_float(self.awg_source.rf_var, 280.0) if getattr(self, "awg_source", None) else 280.0
            except Exception:
                rf_ghz = 280.0
            opt_tone2 = opt_center
            opt_tone1 = opt_center - rf_ghz / 1000.0
            try:
                awg_rf_power_dbm = self._var_float(self.awg_source.power_dbm_var, -10.0) if getattr(self, "awg_source", None) else -10.0
            except Exception:
                awg_rf_power_dbm = -10.0
            optical_cfg = SimConfig(
                optical_center_freq_thz=opt_center,
                rf_carrier_ghz=rf_ghz,
                optical_sideband_mode="SSB" if bool(self.ssb_enable_var.get()) else "DSB",
                cspr_db=cspr_db,
                awg_rf_power_dbm=awg_rf_power_dbm,
                awg_ref_power_dbm=-10.0,
                mzm_drive_gain_db=self._param_float("mzm_drive_gain_db", 8.0),
                mzm_vpi_v=self._param_float("mzm_vpi_v", 7.0),
                mzm_phi_bias_deg=self._param_float("mzm_phi_bias_deg", 45.0),
                mzm_eo_bw_ghz=self._param_float("mzm_eo_bw_ghz", 30.0),
                utcpd_photocurrent_ma=photocurrent_ma,
                utcpd_responsivity_a_per_w=utcpd_resp,
                utcpd_target_dbm=tx_dbm,
            )
            optical_lines = calc_utcpd_optical_line_powers(optical_cfg)
            rf_lines = calc_utcpd_rf_line_powers(optical_cfg)
            mzm_metrics = calc_mzm_drive_metrics(
                awg_rf_power_dbm,
                self._param_float("mzm_drive_gain_db", 8.0),
                cspr_db,
                -10.0,
                self._param_float("mzm_vpi_v", 7.0),
                self._param_float("mzm_phi_bias_deg", 45.0),
            )
            uxr_noise_mv = calc_uxr0404a_noise_vrms(
                self._param_float("dso_vscale_mv", 100.0),
                self._param_float("dso_bw_ghz", 40.0) * 1e9,
            ) * 1e3
            tx_gain = self._param_float("tx_ant_gain_dbi", 33.0)
            rx_gain = tx_gain
            rcs = self._param_float("rcs_sqm", 0.01)
            target_ant_gain = tx_gain
            target_gamma = self._param_float("target_gamma_mag", 0.5)
            target_pol = self._param_float("target_pol_eff", 1.0)
            link = calc_isac_link_budget(
                distance_m=d,
                rf_ghz=rf_ghz,
                tx_dbm=tx_dbm,
                tx_gain_dbi=tx_gain,
                rx_gain_dbi=rx_gain,
                rcs_sqm=rcs,
                lna_gain_db=self._param_float("lna_gain_db", 13.0),
                c1_drive_gain_db=self._param_float("c1_drive_gain_db", 27.0),
                c2_drive_gain_db=self._param_float("c2_drive_gain_db", 20.0),
                c1_cable_loss_db=self._param_float("c1_cable_loss_db", 10.0),
                c2_cable_loss_db=self._param_float("c2_cable_loss_db", 22.0),
                omt_il_db=self._param_float("omt_il_db", 2.0),
                target_ant_gain_dbi=target_ant_gain,
                target_gamma_mag=target_gamma,
                target_pol_eff=target_pol,
            )
            delay_ns = link["delay_ns"]
            loss_db = link["radar_loss_db"]
            echo_dbm = link["c2_rf_dbm"]
            si_enable = bool(self.si_enable_var.get())
            si_dbm = tx_dbm - self._param_float("omt_iso_db", 24.0) if si_enable else -300.0
            lna_gain_db = self._param_float("lna_gain_db", 13.0)
            lna_nf_db = self._param_float("lna_nf_db", 8.0)
            lna_out_dbm = max(echo_dbm, si_dbm) + lna_gain_db
            try:
                waveform_kind = classify_isac_waveform(self.awg_source.waveform_var.get()) if getattr(self, "awg_source", None) else "LFM-QAM"
                baud_for_bw = self._var_float(self.awg_source.symbol_rate_var, 10.0) if getattr(self, "awg_source", None) else 10.0
                chirp_for_bw = baud_for_bw
                rrc_for_bw = self._var_float(self.awg_source.rrc_beta_var, 0.20) if getattr(self, "awg_source", None) else 0.20
            except Exception:
                waveform_kind, baud_for_bw, chirp_for_bw, rrc_for_bw = "LFM-QAM", 10.0, 10.0, 0.20
            bw_cfg = SimConfig(
                waveform=waveform_kind,
                baud_gbaud=baud_for_bw,
                chirp_bw_ghz=chirp_for_bw,
                rrc_beta=rrc_for_bw,
            )
            occupied_bw_hz = estimate_waveform_bandwidth_hz(bw_cfg, waveform_kind)
            dso_bw_hz = self._param_float("dso_bw_ghz", 40.0) * 1e9
            rx_bw_hz = max(dso_bw_hz, 1.0)
            if_noise_bw_hz = min(30e9, rx_bw_hz)

            lna_noise_dbm = -174.0 + 10 * np.log10(rx_bw_hz) + lna_nf_db + lna_gain_db
            zbd_noise_v = self._param_float("zbd_resp_vpw", 1700.0) * self._param_float("zbd_nep_pw", 4.8) * 1e-12 * np.sqrt(if_noise_bw_hz)

            # Link-budget SINR approximation
            #
            data_pwr_ratio_db = -abs(cspr_db)
            p_echo_lin = 10 ** ((echo_dbm + data_pwr_ratio_db) / 10.0)
            p_si_lin = 10 ** ((si_dbm + data_pwr_ratio_db) / 10.0)

            #
            try:
                if getattr(self, "awg_source", None):
                    baud_rate_hz = self._var_float(self.awg_source.symbol_rate_var, 10.0) * 1e9
                else:
                    baud_rate_hz = 10e9
            except:
                baud_rate_hz = 10e9
            p_noise_in_dbm = -174.0 + 10 * np.log10(baud_rate_hz) + lna_nf_db
            p_noise_lin = 10 ** (p_noise_in_dbm / 10.0)

            sinr_lin = p_echo_lin / (p_si_lin + p_noise_lin + 1e-30)
            sinr_db = 10 * np.log10(sinr_lin + 1e-30)

            p_echo_out_lin = 10 ** (echo_dbm / 10.0) * 10 ** (lna_gain_db / 10.0)
            p_si_out_lin = 10 ** (si_dbm / 10.0) * 10 ** (lna_gain_db / 10.0)
            p_noise_out_lin = 10 ** (lna_noise_dbm / 10.0)
            lna_total_dbm = 10 * np.log10(p_echo_out_lin + p_si_out_lin + p_noise_out_lin + 1e-30)

            loss_com_db = link["fspl_one_way_db"]
            comm_dbm = link["c1_rf_dbm"]

            p_comm_data_lin = 10 ** ((comm_dbm + data_pwr_ratio_db) / 10.0)
            com_snr_db = 10 * np.log10(p_comm_data_lin / (p_noise_lin + 1e-30) + 1e-30)

            # Measured EVM is updated after simulation run.

            self.table.item(self.rows["tx"], values=(f"{tx_dbm:.1f}", "dBm"))
            if "opt_pwr" in self.rows:
                self.table.item(self.rows["opt_pwr"], values=(f"{opt_mw:.2f}", "mW"))
            if "mzm_rf" in self.rows:
                self.table.item(
                    self.rows["mzm_rf"],
                    values=(f"{mzm_metrics['rf_in_dbm']:.1f} dBm, m={mzm_metrics['m_eff']:.3f}", f"CSPR {mzm_metrics['effective_cspr_db']:.1f} dB"),
                )
            if "target_gain" in self.rows:
                self.table.item(self.rows["target_gain"], values=(f"{target_ant_gain:.1f}", "dBi"))
            if "rcs_struct" in self.rows:
                self.table.item(self.rows["rcs_struct"], values=(f"{link['structural_rcs_sqm']:.4g}", "m^2"))
            if "rcs_struct_eff" in self.rows:
                self.table.item(self.rows["rcs_struct_eff"], values=(f"{link['reradiated_structural_rcs_sqm']:.4g}", "m^2"))
            if "rcs_ant" in self.rows:
                self.table.item(self.rows["rcs_ant"], values=(f"{link['antenna_mode_rcs_sqm']:.4g}", "m^2"))
            if "rcs_eff" in self.rows:
                self.table.item(self.rows["rcs_eff"], values=(f"{link['effective_rcs_sqm']:.4g}", "m^2"))
            self.table.item(self.rows["delay"], values=(f"{delay_ns:.2f}", "ns"))
            if "omt_il" in self.rows:
                self.table.item(self.rows["omt_il"], values=(f"{2.0 * link['omt_il_db']:.2f}", "dB"))
            self.table.item(self.rows["loss"], values=(f"{loss_db:.1f}", "dB"))
            self.table.item(self.rows["echo"], values=(f"{echo_dbm:.1f}", "dBm"))
            if "comm_loss" in self.rows:
                self.table.item(self.rows["comm_loss"], values=(f"{loss_com_db:.1f}", "dB"))
            if "comm_rx" in self.rows:
                self.table.item(self.rows["comm_rx"], values=(f"{comm_dbm:.1f}", "dBm"))
            if "radar_fspl2" in self.rows:
                self.table.item(self.rows["radar_fspl2"], values=(f"{2.0 * loss_com_db:.1f}", "dB"))
            if "rcs_gain" in self.rows:
                self.table.item(self.rows["rcs_gain"], values=(f"{link['rcs_gain_db']:.1f}", "dB"))
            if "if_chain" in self.rows:
                self.table.item(self.rows["if_chain"], values=(f"{link['c1_if_chain_db']:.1f}/{link['c2_if_chain_db']:.1f}", "dB"))
            if "comm_snr" in self.rows:
                self.table.item(self.rows["comm_snr"], values=("N/A", "dB"))
        except Exception as e:
            print(f"Update table error: {e}")

    def _cfg_from_ui(self) -> SimConfig:
        awg = self.awg_source
        def _awg_float(attr: str, fallback: float) -> float:
            try:
                var = getattr(awg, attr)
                raw = var.get().strip()
                if raw == "":
                    return float(fallback)
                return float(raw)
            except Exception:
                return float(fallback)
        awg_rf_dbm = _awg_float("power_dbm_var", -6.0) if awg else -6.0
        rf_ghz = _awg_float("rf_var", 280.0) if awg else 280.0
        cfg = SimConfig(
            fs_gsps=_awg_float("fs_var", 120.0) if awg else 120.0,
            linewidth_mhz=self._param_float("linewidth_mhz", 0.015),
            baud_gbaud=_awg_float("symbol_rate_var", 15.0) if awg else 15.0,
            if_ghz=_awg_float("if_var", 11.0) if awg else 11.0,
            rf_carrier_ghz=rf_ghz,
            waveform=awg.waveform_var.get().strip() if awg else "LFM-QAM",
            modulation=awg.modulation_var.get().strip() if awg else "16QAM",
            chirp_bw_ghz=_awg_float("symbol_rate_var", 2.0) if awg else 2.0,
            coherence_mode=self.coherence_var.get().strip(),
            rx_mode=self.rx_mode_var.get().strip(),
            optical_sideband_mode="SSB" if bool(self.ssb_enable_var.get()) else "DSB",
            si_enable=bool(self.si_enable_var.get()),
            carrier_wander_enable=bool(self.carrier_wander_enable_var.get()),
            carrier_wander_mhz=10.0 if self.carrier_wander_enable_var.get() else 0.0,
            optical_center_freq_thz=self._param_float("opt_center_thz", 193.41),
            awg_rf_power_dbm=awg_rf_dbm,
            mzm_drive_gain_db=self._param_float("mzm_drive_gain_db", 8.0),
            mzm_vpi_v=self._param_float("mzm_vpi_v", 3.0),
            mzm_phi_bias_deg=self._param_float("mzm_phi_bias_deg", 45.0),
            mzm_eo_bw_ghz=self._param_float("mzm_eo_bw_ghz", 30.0),
            awg_dac_bits=self._param_float("awg_dac_bits", 8.0),
            utcpd_photocurrent_ma=self._param_float("utcpd_photocurrent_ma", 7.0),
            utcpd_target_dbm=calc_utcpd_output_dbm(self._param_float("utcpd_photocurrent_ma", 7.0)),
            utcpd_responsivity_a_per_w=self._param_float("utcpd_resp_aw", 0.24),
            cspr_db=self._param_float("cspr_db", 13.0),
            lna_gain_db=self._param_float("lna_gain_db", 13.0),
            lna_nf_db=self._param_float("lna_nf_db", 8.0),
            zbd_responsivity_vpw=self._param_float("zbd_resp_vpw", 1500.0),
            zbd_nep_pw_sqrt_hz=self._param_float("zbd_nep_pw", 5.0),
            c1_drive_gain_db=self._param_float("c1_drive_gain_db", 27.0),
            c2_drive_gain_db=self._param_float("c2_drive_gain_db", 20.0),
            if_amp_nf_db=self._param_float("if_amp_nf_db", 5.0),
            dso_vscale_mv=self._param_float("dso_vscale_mv", 100.0),
            dso_bandwidth_ghz=self._param_float("dso_bw_ghz", 40.0),
            omt_iso_db=self._param_float("omt_iso_db", 24.0),
            omt_il_db=self._param_float("omt_il_db", 2.0),
            ant_gain_dbi=self._param_float("tx_ant_gain_dbi", 33.0),
            tx_ant_gain_dbi=self._param_float("tx_ant_gain_dbi", 33.0),
            rx_ant_gain_dbi=self._param_float("tx_ant_gain_dbi", 33.0),
            c1_cable_loss_db=self._param_float("c1_cable_loss_db", 10.0),
            c2_cable_loss_db=self._param_float("c2_cable_loss_db", 22.0),
            target_rcs_sqm=self._param_float("rcs_sqm", 0.01),
            target_ant_gain_dbi=self._param_float("tx_ant_gain_dbi", 33.0),
            target_gamma_mag=self._param_float("target_gamma_mag", 0.5),
            target_pol_eff=self._param_float("target_pol_eff", 1.0),
            target_dist_m=max(self._param_float("target_dist_m", 1.0), 0.1),
            syms_per_chirp=max(8, int(_awg_float("chirp_len_var", 1024))),
            pilot_rho=float(np.clip(_awg_float("pilot_rho_var", 0.20), 0.0, 0.95)),
            rrc_beta=float(np.clip(_awg_float("rrc_beta_var", 0.20), 0.01, 1.0)),
        )

        cfg.delay_ns = (2.0 * cfg.target_dist_m) / 3e8 * 1e9
        cfg.path_loss_db = calc_isac_link_budget(
            distance_m=cfg.target_dist_m,
            rf_ghz=cfg.rf_carrier_ghz,
            tx_dbm=cfg.utcpd_target_dbm,
            tx_gain_dbi=cfg.tx_ant_gain_dbi,
            rx_gain_dbi=cfg.rx_ant_gain_dbi,
            rcs_sqm=cfg.target_rcs_sqm,
            lna_gain_db=cfg.lna_gain_db,
            c1_drive_gain_db=cfg.c1_drive_gain_db,
            c2_drive_gain_db=cfg.c2_drive_gain_db,
            c1_cable_loss_db=cfg.c1_cable_loss_db,
            c2_cable_loss_db=cfg.c2_cable_loss_db,
            omt_il_db=cfg.omt_il_db,
            target_ant_gain_dbi=cfg.target_ant_gain_dbi,
            target_gamma_mag=cfg.target_gamma_mag,
            target_pol_eff=cfg.target_pol_eff,
        )["radar_path_loss_db"]
        cfg.tx_power_dbm = cfg.utcpd_target_dbm
        return cfg

    def _init_plot(self):
        self.fig.clear()
        gs = self.fig.add_gridspec(2, 3)
        self.axes = [self.fig.add_subplot(gs[0,0]), self.fig.add_subplot(gs[0,1]), self.fig.add_subplot(gs[1,0]), self.fig.add_subplot(gs[1,1])]
        self.ax_range = self.fig.add_subplot(gs[0,2])
        self.ax_const = self.fig.add_subplot(gs[1,2])
        self.lines = []
        self._spectrum_band_artists = []
        titles = ["1) Optical Tones", "2) UTC-PD Output (TX Antenna)", "3) C2 Spectrum (Monostatic)", "4) C1 Spectrum (One-way)"]
        colors = ["purple", "red", "#2563eb", "#2563eb"]

        for i, ax in enumerate(self.axes):
            line_label = "Raw" if i >= 2 else "Signal"
            line, = ax.plot([], [], lw=1.1 if i >= 2 else 1.5, color=colors[i], label=line_label)
            if i == 2:
                self.l_c2_band, = ax.plot([], [], lw=1.0, color="#dc2626", alpha=0.90, label="In-band raw")
            if i == 3:
                self.l_c1_band, = ax.plot([], [], lw=1.0, color="#dc2626", alpha=0.90, label="In-band raw")
            ax.legend(loc="upper right", fontsize=8)
            self.lines.append(line)
            ax.set_title(titles[i])
            ax.grid(True, alpha=0.45)
            ax.set_ylabel("Power [dBm]" if i < 2 else "dBm/Hz")
            if i >= 2:
                ax.set_xlabel("Frequency (GHz)")

        self.l_lo, = self.axes[0].plot([], [], lw=1.2, color="black", label="Opt. LO")
        self.axes[0].legend(loc="upper right", fontsize=8)
        self.ax_range.set_title("5) C2 Range Profile")
        self.ax_range.set_xlabel("Range [m]")
        self.ax_range.set_ylabel("Magnitude [dB]")
        self.ax_range.grid(True, alpha=0.45)
        self.ax_range.set_xlim(0, 5)

        self.ax_const.set_title("6) Constellation")
        self.ax_const.set_xlim(-1.8, 1.8); self.ax_const.set_ylim(-1.8, 1.8)
        self.ax_const.grid(True, alpha=0.45)
        self.fig.tight_layout()

    def run_simulation(self) -> None:
        try:
            self.stop_animation()
            self._update_table()  # note
            cfg = self._cfg_from_ui()

            #
            self.data = run_isac_sim(cfg)
            sideband_mode = optical_sideband_mode(cfg)

            #
            #
            #
            c = cfg.rf_carrier_ghz
            fs = self.data["fs"]
            #
            span = cfg.if_ghz + (cfg.baud_gbaud / 2.0) + 5.0
            zbd_span = min(
                30.0,
                max(span, 2.0 * cfg.if_ghz + cfg.baud_gbaud + 3.0),
            )

            #
            opt_center = cfg.optical_center_freq_thz
            self.axes[0].set_xlim(opt_center - cfg.rf_carrier_ghz / 1000.0 - 0.03, opt_center + cfg.if_ghz / 1000.0 + 0.03)
            self.axes[0].set_title(f"1) Optical Tones + {sideband_mode}")
            self.axes[1].set_title(f"2) UTC-PD Output ({sideband_mode})")
            self.axes[1].set_xlim(c - span, c + span)
            spec_fmax_ghz = min(25.0, cfg.dso_bandwidth_ghz, 0.5 * fs / 1e9)
            self.axes[2].set_xlim(0.0, spec_fmax_ghz)
            self.axes[3].set_xlim(0.0, spec_fmax_ghz)
            self.axes[2].set_title(f"C2 Spectrum [0-{spec_fmax_ghz:.0f} GHz]")
            self.axes[3].set_title(f"C1 Spectrum [0-{spec_fmax_ghz:.0f} GHz]")

            #
            #
            #
            bw_db = 10 * np.log10(fs)
            p_tx_dbm = cfg.utcpd_target_dbm
            p_si_dbm = p_tx_dbm - cfg.omt_iso_db
            p_echo_dbm = p_tx_dbm - cfg.path_loss_db
            p_lna_sig_dbm = max(p_si_dbm, p_echo_dbm) + cfg.lna_gain_db
            p_lna_noise_dbm = -174.0 + bw_db + cfg.lna_nf_db + cfg.lna_gain_db

            #
            tx_psd_dbmhz = p_tx_dbm - bw_db
            lna_sig_psd_dbmhz = p_lna_sig_dbm - bw_db
            lna_noise_psd_dbmhz = p_lna_noise_dbm - bw_db

            optical_lines = self.data.get("optical_line_powers", {})
            opt_hi = max(
                float(optical_lines.get("tone1_dbm", -10.0)),
                float(optical_lines.get("mzm_carrier_dbm", -10.0)),
            )
            opt_lo = float(optical_lines.get("sideband_each_dbm", opt_hi - 20.0))
            self.axes[0].set_ylim(opt_lo - 45.0, opt_hi + 8.0)
            rf_lines = self.data.get("utcpd_rf_line_powers", {})
            rf_hi = float(rf_lines.get("carrier_dbm", cfg.utcpd_target_dbm))
            rf_lo = float(rf_lines.get("sideband_each_dbm", rf_hi - 20.0))
            self.axes[1].set_ylim(rf_lo - 45.0, rf_hi + 8.0)
            _, p_c2_probe = calc_psd(self.data["v_rec_c2"], fs)
            self.axes[2].set_ylim(-150.0, -90.0)

            # Plot 4 shows the detector's (ZBD/Mixer) output, which lives on a
            # different power scale than the RF chain above (e.g. ZBD's V/W
            # responsivity gain) — derive its y-range from the actual detected
            # data instead of the RF link-budget formula, or the curve clips.
            _, p_com_probe = calc_psd(self.data["v_rec_com"], fs)
            self.axes[3].set_ylim(-150.0, -90.0)

            analysis_bw_hz = max(float(self.data.get("occupied_bw_hz", cfg.baud_gbaud * 1e9)), 1.0)
            f1_ghz = max(0.0, cfg.if_ghz - 0.5 * analysis_bw_hz / 1e9)
            f2_ghz = min(spec_fmax_ghz, cfg.if_ghz + 0.5 * analysis_bw_hz / 1e9)
            for artist in getattr(self, "_spectrum_band_artists", []):
                try:
                    artist.remove()
                except Exception:
                    pass
            self._spectrum_band_artists = []
            for ax in (self.axes[2], self.axes[3]):
                self._spectrum_band_artists.extend([
                    ax.axvspan(f1_ghz, f2_ghz, alpha=0.13, color="#f59e0b"),
                    ax.axvline(f1_ghz, color="#f59e0b", lw=1.0, linestyle="--"),
                    ax.axvline(f2_ghz, color="#f59e0b", lw=1.0, linestyle="--"),
                    ax.axvline(cfg.if_ghz, color="#dc2626", lw=1.0, linestyle=":"),
                ])

            c1m = self.data.get("c1_band_metrics", {})
            c2m = self.data.get("c2_band_metrics", {})
            if "c1_band" in self.rows:
                self.table.item(self.rows["c1_band"], values=(f"{float(c1m.get('band_power_dbm', np.nan)):.2f}", "dBm"))
            if "c2_band" in self.rows:
                self.table.item(self.rows["c2_band"], values=(f"{float(c2m.get('band_power_dbm', np.nan)):.2f}", "dBm"))
            if "c1_noise" in self.rows:
                self.table.item(self.rows["c1_noise"], values=(f"{float(c1m.get('noise_power_dbm', c1m.get('noise_dbm', np.nan))):.2f}", "dBm"))
            if "c2_noise" in self.rows:
                self.table.item(self.rows["c2_noise"], values=(f"{float(c2m.get('noise_power_dbm', c2m.get('noise_dbm', np.nan))):.2f}", "dBm"))
            if "c1_noise_density" in self.rows:
                self.table.item(self.rows["c1_noise_density"], values=(f"{float(c1m.get('noise_density_dbm_hz', c1m.get('noise_floor_dbm_hz', np.nan))):.2f}", "dBm/Hz"))
            if "c2_noise_density" in self.rows:
                self.table.item(self.rows["c2_noise_density"], values=(f"{float(c2m.get('noise_density_dbm_hz', c2m.get('noise_floor_dbm_hz', np.nan))):.2f}", "dBm/Hz"))
            if "noise_source" in self.rows:
                self.table.item(
                    self.rows["noise_source"],
                    values=(f"C1:{c1m.get('noise_source', 'N/A')} / C2:{c2m.get('noise_source', 'N/A')}", ""),
                )
            if "comm_snr" in self.rows:
                self.table.item(self.rows["comm_snr"], values=("N/A", "dB"))
            if "radar_snr" in self.rows:
                self.table.item(self.rows["radar_snr"], values=(f"{float(self.data.get('radar_snr_db', np.nan)):.2f}", "dB"))
            if "range_detect" in self.rows:
                self.table.item(self.rows["range_detect"], values=("normalized CFR", ""))
            if "range_sel" in self.rows:
                self.table.item(self.rows["range_sel"], values=(f"{float(self.data.get('selected_range_m', np.nan)):.3f}", "m"))
            if "si_cfr_peak" in self.rows:
                self.table.item(self.rows["si_cfr_peak"], values=(f"{float(self.data.get('si_cfr_peak_m', np.nan)):.3f}", "m"))
            if "si_cfr_coh" in self.rows:
                self.table.item(self.rows["si_cfr_coh"], values=(f"{float(self.data.get('si_cfr_coherence', np.nan)):.3f}", ""))
            if "si_norm_ratio" in self.rows:
                self.table.item(self.rows["si_norm_ratio"], values=(f"{float(self.data.get('si_norm_target_over_si_db', np.nan)):.2f}", "dB"))
            if "si_norm_coh" in self.rows:
                self.table.item(self.rows["si_norm_coh"], values=(f"{float(self.data.get('si_norm_phase_coherence', np.nan)):.3f}", ""))
            if "pslr" in self.rows:
                self.table.item(self.rows["pslr"], values=(f"{float(self.data.get('pslr_db', np.nan)):.2f}", "dB"))
            if "proc_gain" in self.rows:
                self.table.item(self.rows["proc_gain"], values=(f"{float(self.data.get('processing_gain_db', np.nan)):.2f}", "dB"))

            #
            #
            #
            self.ax_const.cla()
            self.ax_const.set_title(f"6) Constellation ({cfg.modulation})")
            self.ax_const.grid(True, alpha=0.45)

            sym_eq = np.asarray(self.data.get("sym_eq", []))
            sym_tx = np.asarray(self.data.get("sym_tx", []))

            if len(sym_eq) > 0:
                self.ax_const.scatter(np.real(sym_eq[:2000]), np.imag(sym_eq[:2000]), s=8, alpha=0.6)
            if len(sym_tx) > 0:
                self.ax_const.scatter(np.real(sym_tx[:2000]), np.imag(sym_tx[:2000]), s=22, marker="x", color="red")

            #
            self.ax_const.set_xlim(-1.5, 1.5)
            self.ax_const.set_ylim(-1.5, 1.5)
            self.ax_const.set_aspect("equal", adjustable="box")

            #
            evm_db = float(self.data.get("evm_db", float('nan')))
            ser = float(self.data.get("ser", float('nan')))

            if np.isfinite(evm_db):
                evm_snr_db = -evm_db
                self.demod_var.set(f"{cfg.modulation} Demod: EVM={evm_db:.1f} dB | EVM-SNR={evm_snr_db:.1f} dB | SER={ser:.4f}")
                evm_pct = estimate_measured_evm_percent(evm_db)
                self.table.item(self.rows["evm_pct"], values=(f"{evm_pct:.2f}", "%"))
                if "comm_snr" in self.rows:
                    self.table.item(self.rows["comm_snr"], values=(f"{evm_snr_db:.2f}", "dB"))
                if "evm_snr" in self.rows:
                    self.table.item(self.rows["evm_snr"], values=(f"{evm_snr_db:.2f}", "dB"))
            else:
                self.demod_var.set(f"Comm Demod: N/A ({cfg.rx_mode})")
                if "comm_snr" in self.rows:
                    self.table.item(self.rows["comm_snr"], values=("N/A", "dB"))

            self._update_range_profile()

            self.frame_idx = 0
            self._update_frame()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _update_range_profile(self):
        if not self.data:
            return
        self.ax_range.cla()
        self.ax_range.set_title("5) Normalized CFR Range Profile")
        self.ax_range.set_xlabel("Range [m]")
        self.ax_range.set_ylabel("Magnitude [dB]")
        self.ax_range.grid(True, alpha=0.45)

        rng_cfr = np.asarray(self.data.get("si_cfr_range_axis_m", []), dtype=np.float64)
        prof_cfr = np.asarray(self.data.get("si_cfr_range_profile_db", []), dtype=np.float64)
        if len(rng_cfr) > 0 and len(rng_cfr) == len(prof_cfr):
            x_m = rng_cfr
            show = np.isfinite(x_m) & np.isfinite(prof_cfr) & (x_m >= 0.0) & (x_m <= 5.0)
            if np.count_nonzero(show) >= 2:
                self.ax_range.plot(x_m[show], prof_cfr[show], color="#dc2626", lw=1.2, label="Normalized CFR")
                peak_m = float(self.data.get("si_cfr_peak_m", float("nan")))
                if np.isfinite(peak_m):
                    self.ax_range.axvline(peak_m, color="#111827", linestyle=":", linewidth=0.9)
                self.ax_range.legend(loc="upper right", fontsize=8)
        else:
            self.ax_range.text(0.5, 0.5, "No normalized CFR profile", ha="center", va="center",
                               transform=self.ax_range.transAxes, color="gray")
        self.ax_range.set_xlim(0.0, 5.0)
        self.ax_range.set_ylim(-45.0, 10.0)

    def _update_frame(self):
        if not self.data: return
        fs, rf_c, step, flen = self.data["fs"], self.data["rf_c"], self.data["step"], self.data["frame_len"]
        s, e = self.frame_idx * step, self.frame_idx * step + flen

        # Plot 1: OSA-like optical power trace. CSPR is a line/band-power
        # relation, so plotting optical Welch PSD can make narrow carriers look
        # artificially lower than spread DSB content.
        osa = self.data.get("osa_display", {})
        self.lines[0].set_data(osa.get("freq_thz", []), osa.get("signal_dbm", []))
        sideband_mode = str(np.asarray(osa.get("sideband_mode", "DSB")).item()) if "sideband_mode" in osa else "DSB"
        self.lines[0].set_label(f"MZM carrier + {sideband_mode}")
        self.l_lo.set_data(osa.get("freq_thz", []), osa.get("lo_dbm", []))
        self.l_lo.set_label("Optical tone")
        self.axes[0].legend(loc="upper right", fontsize=8)

        # Plot 2: RF spectrum analyzer-like UTC-PD output power trace.
        rf_disp = self.data.get("utcpd_rf_display", {})
        pwr_tx = calc_power_dbm(self.data["v_tx_out"][s:e])
        self.lines[1].set_data(rf_disp.get("freq_ghz", []), rf_disp.get("power_dbm", []))
        self.lines[1].set_label(f"UTC-PD Out ({pwr_tx:.1f} dBm)")

        # Plot 3: C2 raw DSO IF spectrum. The C2 table noise density/power use
        # this same trace so the metric follows the visible spectrum floor.
        c2_plot = np.asarray(self.data.get("v_rec_c2_raw", self.data["v_rec_c2"]))
        if bool(self.sim_welch_psd_var.get()):
            f, p_c2 = calc_psd(c2_plot, fs)
        else:
            f, p_c2 = calc_fft_psd(c2_plot[s:e], fs)
        f_ghz = f / 1e9
        fmax_ghz = float(self.axes[2].get_xlim()[1])
        mask = f_ghz <= fmax_ghz
        self.lines[2].set_data(f_ghz[mask], p_c2[mask])
        f1_ghz = float(self.data.get("if_center_hz", 0.0)) / 1e9 - 0.5 * float(self.data.get("occupied_bw_hz", 1.0)) / 1e9
        f2_ghz = float(self.data.get("if_center_hz", 0.0)) / 1e9 + 0.5 * float(self.data.get("occupied_bw_hz", 1.0)) / 1e9
        band = mask & (f_ghz >= f1_ghz) & (f_ghz <= f2_ghz)
        self.l_c2_band.set_data(f_ghz[band], p_c2[band])
        self.lines[2].set_label("Raw")
        self.axes[1].legend(loc="upper right", fontsize=8)
        self.axes[2].legend(loc="upper right", fontsize=8)

        # Plot 4: C1 DSO IF spectrum
        c1_plot = np.asarray(self.data["v_rec_c1"])
        if bool(self.sim_welch_psd_var.get()):
            f, p_bb = calc_psd(c1_plot, fs)
        else:
            f, p_bb = calc_fft_psd(c1_plot[s:e], fs)
        f_ghz = f / 1e9
        fmax_ghz = float(self.axes[3].get_xlim()[1])
        mask = f_ghz <= fmax_ghz
        self.lines[3].set_data(f_ghz[mask], p_bb[mask])
        band = mask & (f_ghz >= f1_ghz) & (f_ghz <= f2_ghz)
        self.l_c1_band.set_data(f_ghz[band], p_bb[band])
        self.lines[3].set_label("Raw")
        self.axes[3].legend(loc="upper right", fontsize=8)

        self.canvas.draw_idle()
        self.frame_idx = (self.frame_idx + 1) % self.data["num_frames"]


    def _on_download_awg(self):
        def worker():
            from functions.awg_functions import download_to_awg, parse_channels, stop_awg
            from functions.dsp_functions import normalize_real_for_awg
            from tkinter import messagebox

            try:
                addr = f"TCPIP0::{self.awg_ip_var.get().strip()}::{int(self.awg_port_var.get())}::SOCKET"
                stop_awg(awg_addr=addr, channels=[1, 2, 3, 4])

                if not self.data:
                    self.parent.after(0, lambda: messagebox.showinfo("Info", "Running simulation first to generate signal..."))
                    cfg = self._cfg_from_ui()
                    self.data = run_isac_sim(cfg)

                cfg = self._cfg_from_ui()
                bb_sig = self.data.get("bb_sig")
                if bb_sig is None:
                    raise ValueError("Simulation did not return bb_sig")

                sim_fs = self.data["fs"]
                awg_fs_ghz = float(self.awg_fs_var.get())
                awg_fs = awg_fs_ghz * 1e9

                if abs(sim_fs - awg_fs) > 1e3:
                    num_samples = int(len(bb_sig) * awg_fs / sim_fs)
                    bb_awg = fft_resample_complex(bb_sig, fs_in=sim_fs, fs_out=awg_fs)
                else:
                    bb_awg = bb_sig

                max_awg_samples = 512000
                if len(bb_awg) > max_awg_samples:
                    bb_awg = bb_awg[:max_awg_samples]

                valid_len = (len(bb_awg) // 256) * 256
                if valid_len == 0: valid_len = len(bb_awg)
                bb_awg = bb_awg[:valid_len]

                f_if = cfg.if_ghz * 1e9
                t_awg = np.arange(len(bb_awg)) / awg_fs
                x_if_cplx = bb_awg * np.exp(1j * 2 * np.pi * f_if * t_awg)
                x_if_real = np.real(x_if_cplx)

                awg_sig = normalize_real_for_awg(x_if_real)
                addr = f"TCPIP0::{self.awg_ip_var.get().strip()}::{int(self.awg_port_var.get())}::SOCKET"

                channels_list = parse_channels(self.awg_ch_var.get())
                download_to_awg(
                    awg_sig=awg_sig,
                    channels=channels_list if channels_list else [1],
                    awg_addr=addr,
                    fs=awg_fs,
                    vpp=float(self.awg_vpp_var.get()),
                )
                n_samp = len(awg_sig)
                self.parent.after(0, lambda n=n_samp: messagebox.showinfo("Success", f"Download to AWG Complete!\nLength: {n} samples"))
            except Exception as e:
                self.parent.after(0, lambda m=str(e): messagebox.showerror("AWG Download Error", m))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def start_animation(self):
        if not self.data: return
        if not self.after_id: self._schedule_next_frame()

    def _schedule_next_frame(self):
        self._update_frame()
        self.after_id = self.parent.after(self.anim_ms.get(), self._schedule_next_frame)

    def stop_animation(self):
        if self.after_id:
            self.parent.after_cancel(self.after_id)
            self.after_id = None

    def _cmd_to_awg(self):
        if self.awg_source is not None:
            self.awg_source._on_download()
        else:
            self._on_download_awg()

    def _cmd_run_awg(self):
        if self.awg_source is not None:
            self.awg_source._on_awg_run()

    def _cmd_toggle_anim(self):
        if self.after_id:
            self.stop_animation()
            self._anim_btn.configure(text="Anim Start")
        else:
            self.start_animation()
            if self.after_id:
                self._anim_btn.configure(text="Anim Stop")

class DsoPanel:
    """DSO Capture + Spectrum Analysis + Demodulation panel."""

    # Keysight UXR0404A analog bandwidth (GHz)
    _UXR0404A_BW_GHZ: float = 40.0

    def __init__(self, parent: ttk.Frame, runtime: dict) -> None:
        self.parent = parent
        self.runtime = runtime
        self.log_q: queue.Queue[str] = queue.Queue()
        self.conn_status_var = tk.StringVar(value="Not checked")
        self._rx_sig: np.ndarray | None = None
        self._rx_fs: float = 1.0
        self._rx_t: np.ndarray | None = None
        self._rx_multi: dict[str, dict[str, np.ndarray | float]] = {}
        self._noise_floor_ref_dbmhz: float | None = None   # stored DSO noise density in dBm/Hz
        self._metrics: dict[str, dict[str, object]] = {}
        self._loaded_capture_without_metrics = False
        self._last_range_summaries: list[dict[str, object]] = []
        self._last_range_results: list[dict[str, object]] = []
        self._last_power_fading_rows: list[dict] = []
        self._last_power_fading_summary: dict[str, dict[str, float | str]] = {}
        self._last_power_fading_paths: tuple[Path, Path] | None = None
        self._last_loaded_capture_path: str | None = None
        self._build_ui()
        self._start_log_pump()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main = ttk.Frame(self.parent, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Left panel
        left = ttk.Frame(main, width=460)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        # Right plot panel
        self.right_frame = ttk.Frame(main)
        right = self.right_frame
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))

        # Section 1: DSO Connection
        grp1 = ttk.LabelFrame(left, text="DSO Connection", padding=8)
        grp1.pack(fill=tk.X, pady=(0, 6))
        grp1.columnconfigure(1, weight=1)
        grp1.columnconfigure(3, weight=1)

        self.live_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp1, text="Live DSO (uncheck = use last capture)",
                        variable=self.live_var,
                        command=self._on_mode_changed).grid(row=0, column=0, columnspan=4, sticky="w")

        #
        ttk.Label(grp1, text="DSO Channel", font=("Segoe UI", 10, "bold")).grid(
            row=1, column=0, sticky="w", pady=(8, 4))
        self.ch_var = tk.StringVar(value="C1")
        self.channel_select_vars: dict[str, tk.BooleanVar] = {}
        _ch_frame = ttk.Frame(grp1)
        _ch_frame.grid(row=1, column=1, columnspan=3, sticky="w", pady=(8, 4))
        for _ch in ["C1", "C2", "C3", "C4"]:
            _var = tk.BooleanVar(value=(_ch in {"C1", "C2"}))
            self.channel_select_vars[_ch] = _var
            ttk.Checkbutton(
                _ch_frame,
                text=_ch,
                variable=_var,
                command=self._on_channel_selection_changed,
            ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(_ch_frame, text="Trig").pack(side=tk.LEFT, padx=(2, 4))
        self.trig_ch_var = tk.StringVar(value="C3")
        ttk.Combobox(
            _ch_frame,
            textvariable=self.trig_ch_var,
            values=["Off", "C1", "C2", "C3", "C4"],
            state="readonly",
            width=5,
        ).pack(side=tk.LEFT)
        self.ch_combo = None  # ch_var is the authoritative source

        ttk.Label(grp1, text="DSO Type").grid(row=2, column=0, sticky="w", pady=3)
        self.dso_type_var = tk.StringVar(value="keysight_uxr")
        self.dso_type_combo = ttk.Combobox(
            grp1, textvariable=self.dso_type_var,
            values=["keysight_uxr", "lecroy"], state="readonly", width=14)
        self.dso_type_combo.grid(row=2, column=1, sticky="w")
        ttk.Label(grp1, text="DSO SR (GS/s)").grid(row=2, column=2, sticky="w", padx=(10, 0))
        self.dso_sr_var = tk.StringVar(value="Auto")
        ttk.Combobox(grp1, textvariable=self.dso_sr_var,
                     values=["Auto", "64", "70", "84", "105", "119", "128", "140", "210", "256"],
                     state="normal", width=8).grid(
            row=2, column=3, sticky="w")

        ttk.Label(grp1, text="DSO Host").grid(row=3, column=0, sticky="w", pady=3)
        self.host_var = tk.StringVar(value="192.168.1.4")
        self.host_entry = ttk.Entry(grp1, textvariable=self.host_var, width=16)
        self.host_entry.grid(row=3, column=1, sticky="we")
        ttk.Label(grp1, text="Timeout (ms)").grid(row=3, column=2, sticky="w", padx=(10, 0))
        self.timeout_var = tk.StringVar(value="10000")
        self.timeout_entry = ttk.Entry(grp1, textvariable=self.timeout_var, width=8)
        self.timeout_entry.grid(row=3, column=3, sticky="w")

        ttk.Label(grp1, text="Scope BW (GHz)").grid(row=4, column=0, sticky="w", pady=3)
        self.scope_bw_var = tk.StringVar(value=str(self._UXR0404A_BW_GHZ))
        ttk.Entry(grp1, textvariable=self.scope_bw_var, width=8).grid(row=4, column=1, sticky="w")
        self.ch1_scale_mv_var = tk.StringVar(value="100")
        self.ch2_scale_mv_var = tk.StringVar(value="20")
        self.ch_scale_mv_var = self.ch1_scale_mv_var  # backwards-compatible alias
        ttk.Label(grp1, text="CH1 Scale (mV/div)").grid(row=4, column=2, sticky="w", padx=(10, 0), pady=3)
        ttk.Entry(grp1, textvariable=self.ch1_scale_mv_var, width=8).grid(row=4, column=3, sticky="w")
        ttk.Label(grp1, text="CH2 Scale (mV/div)").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Entry(grp1, textvariable=self.ch2_scale_mv_var, width=8).grid(row=5, column=1, sticky="w")

        ttk.Label(grp1, text="Process Fs (GS/s)").grid(row=5, column=2, sticky="w", padx=(10, 0), pady=3)
        self.capture_fs_var = tk.StringVar(value="Auto")
        ttk.Entry(grp1, textvariable=self.capture_fs_var, width=8).grid(row=5, column=3, sticky="w")
        ttk.Label(grp1, text="Capture Margin (xT)").grid(row=6, column=0, sticky="w", pady=3)
        self.max_samples_var = tk.StringVar(value="2.2")
        ttk.Entry(grp1, textvariable=self.max_samples_var, width=8).grid(row=6, column=1, sticky="w")

        ttk.Label(grp1, text="Data Length (kSa)").grid(row=6, column=2, sticky="w", padx=(10, 0), pady=3)
        self.data_len_ksa_var = tk.StringVar(value="")
        ttk.Entry(grp1, textvariable=self.data_len_ksa_var, width=8).grid(row=6, column=3, sticky="w")
        ttk.Label(grp1, text="Trig Level (mV)").grid(row=7, column=0, sticky="w", pady=3)
        self.trig_level_mv_var = tk.StringVar(value="0")
        ttk.Entry(grp1, textvariable=self.trig_level_mv_var, width=8).grid(row=7, column=1, sticky="w")

        ttk.Separator(grp1, orient="horizontal").grid(
            row=8, column=0, columnspan=4, sticky="ew", pady=(6, 2))
        ttk.Label(grp1, text="FFT Offset (dBm)").grid(row=9, column=0, sticky="w", pady=3)
        self.fft_offset_var = tk.StringVar(value="-40")
        ttk.Entry(grp1, textvariable=self.fft_offset_var, width=8).grid(row=9, column=1, sticky="w")
        ttk.Label(grp1, text="FFT Scale (dBm/div)").grid(row=9, column=2, sticky="w", padx=(10, 0))
        self.fft_scale_div_var = tk.StringVar(value="10")
        ttk.Entry(grp1, textvariable=self.fft_scale_div_var, width=8).grid(row=9, column=3, sticky="w")
        self.fft_offset_var.trace_add("write", self._on_fft_axis_var_changed)
        self.fft_scale_div_var.trace_add("write", self._on_fft_axis_var_changed)

        conn_btn_f = ttk.Frame(grp1)
        conn_btn_f.grid(row=9, column=0, columnspan=4, sticky="w", pady=(8, 0))
        conn_btn_top = ttk.Frame(conn_btn_f)
        conn_btn_top.pack(fill=tk.X)
        conn_btn_bottom = ttk.Frame(conn_btn_f)
        conn_btn_bottom.pack(fill=tk.X, pady=(5, 0))
        self.test_btn = ttk.Button(conn_btn_top, text="Connection",
                                   command=self._on_test_connection)
        self.test_btn.pack(side=tk.LEFT)
        ttk.Button(conn_btn_top, text="Single",
                   command=self._on_dso_single).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(conn_btn_bottom, text="Acquire", style="Primary.TButton",
                   command=self._on_capture_live).pack(side=tk.LEFT)
        ttk.Button(conn_btn_bottom, text="Best EVM x10",
                   command=self._on_best_evm_acquire).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(conn_btn_bottom, text="Max Power x10",
                   command=self._on_best_power_acquire).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(conn_btn_bottom, text="Power Fade x30",
                   command=self._on_power_fading_probe).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(conn_btn_bottom, text="Save Fade",
                   command=self._on_save_power_fading_result).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(conn_btn_bottom, text="Apply",
                   command=self._on_apply_dso_settings).pack(side=tk.LEFT, padx=(6, 0))

        self.conn_status_var = tk.StringVar(value="Not checked")
        tk.Label(grp1, textvariable=self.conn_status_var,
                 fg="gray", bg="#f4f6f9").grid(row=10, column=0, columnspan=4, sticky="w", pady=(2, 0))

        cap_file_f = ttk.Frame(grp1)
        cap_file_f.grid(row=11, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(cap_file_f, text="Save",
                   command=self._on_save_capture).pack(side=tk.LEFT)
        ttk.Button(cap_file_f, text="Load",
                   command=self._on_load_capture).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(cap_file_f, text="Paper Spectrum",
                   command=self._on_plot_saved_spectrum_figure).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(cap_file_f, text="Screenshot",
                   command=self._on_save_screenshot_png).pack(side=tk.LEFT, padx=(6, 0))
        self.capture_file_var = tk.StringVar(value="Capture: live/memory")
        ttk.Label(grp1, textvariable=self.capture_file_var,
                  style="Muted.TLabel").grid(row=12, column=0, columnspan=4, sticky="w", pady=(2, 0))

        #
        _scroll_holder = ttk.Frame(left)
        _scroll_holder.pack(fill=tk.BOTH, expand=True)
        lc = tk.Canvas(_scroll_holder, highlightthickness=0, bg="#f4f6f9")
        lsb = ttk.Scrollbar(_scroll_holder, orient="vertical", command=lc.yview)
        lc.configure(yscrollcommand=lsb.set)
        lsb.pack(side=tk.RIGHT, fill=tk.Y)
        lc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lf = ttk.Frame(lc)
        _lw = lc.create_window((0, 0), window=lf, anchor="nw")
        lf.bind("<Configure>", lambda _: lc.configure(scrollregion=lc.bbox("all")))
        lc.bind("<Configure>", lambda e: lc.itemconfig(_lw, width=e.width))
        lc.bind("<MouseWheel>", lambda e: lc.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Section 2: Signal Parameters
        grp2 = ttk.LabelFrame(lf, text="Signal Parameters", padding=8)
        grp2.pack(fill=tk.X, pady=(0, 6))
        grp2.columnconfigure(1, weight=1)
        grp2.columnconfigure(3, weight=1)

        ttk.Label(grp2, text="Carrier/IF Freq (GHz)").grid(row=0, column=0, sticky="w", pady=3)
        self.fc_var = tk.StringVar(value="10.0")
        ttk.Entry(grp2, textvariable=self.fc_var, width=13).grid(row=0, column=1, sticky="w")

        ttk.Label(grp2, text="Symbol Rate (GHz)").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.sr_var = tk.StringVar(value="10.0")
        ttk.Entry(grp2, textvariable=self.sr_var, width=13).grid(row=0, column=3, sticky="w")

        ttk.Label(grp2, text="Modulation").grid(row=1, column=0, sticky="w", pady=3)
        self.demod_mod_var = tk.StringVar(value="16QAM")
        ttk.Combobox(grp2, textvariable=self.demod_mod_var,
                     values=["QPSK", "8PSK", "16QAM", "32QAM"],
                     state="readonly", width=13).grid(row=1, column=1, sticky="w")

        ttk.Label(grp2, text="RRC Roll-off").grid(row=1, column=2, sticky="w", padx=(10, 0))
        self.demod_beta_var = tk.StringVar(value="0.20")
        ttk.Entry(grp2, textvariable=self.demod_beta_var, width=13).grid(row=1, column=3, sticky="w")

        ttk.Label(grp2, text="RRC Span (sym)").grid(row=2, column=0, sticky="w", pady=3)
        self.demod_span_var = tk.StringVar(value="8")
        ttk.Entry(grp2, textvariable=self.demod_span_var, width=13).grid(row=2, column=1, sticky="w")

        self.band_info_var = tk.StringVar(value="Band: ---")
        ttk.Label(grp2, textvariable=self.band_info_var,
                  style="Muted.TLabel").grid(row=2, column=2, columnspan=2, sticky="w", padx=(10, 0))

        for v in (self.fc_var, self.sr_var, self.demod_beta_var):
            v.trace_add("write", lambda *_: self._update_band_label())
        self._update_band_label()

        btn_f = ttk.Frame(grp2)
        btn_f.grid(row=3, column=0, columnspan=4, sticky="we", pady=(10, 0))
        btn_f_top = ttk.Frame(btn_f)
        btn_f_top.pack(fill=tk.X)
        btn_f_ref = ttk.Frame(btn_f)
        btn_f_ref.pack(fill=tk.X, pady=(5, 0))
        btn_f_misc = ttk.Frame(btn_f)
        btn_f_misc.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(btn_f_top, text="Demodulate", style="Primary.TButton",
                   command=self._on_demod_button).pack(side=tk.LEFT)
        ttk.Button(btn_f_top, text="Detect Range", style="Primary.TButton",
                   command=self._on_detect_range_button).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_f_top, text="Best Range x10",
                   command=self._on_best_range_acquire).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(btn_f_ref, text="Store Zero Ref",
                   command=self._on_set_range_zero).pack(side=tk.LEFT)
        ttk.Button(btn_f_ref, text="Clear Ref",
                   command=self._on_clear_range_zero).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_f_ref, text="Save Range",
                   command=self._on_save_range_data).pack(side=tk.LEFT, padx=(6, 0))
        self.range_zero_enable_var = tk.BooleanVar(value=False)

        ttk.Button(btn_f_misc, text="Measure SNR",
                   command=self._on_measure_band).pack(side=tk.LEFT)
        ttk.Button(btn_f_misc, text="Show H(f)",
                   command=self._on_show_channel_response).pack(side=tk.LEFT, padx=(6, 0))

        self.filter_overlay_var = tk.BooleanVar(value=True)
        self.filter_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp2, text="Show in-band PSD", variable=self.filter_overlay_var,
                        command=self._plot_spectrum_and_time).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(grp2, text="Apply demod LPF", variable=self.filter_enable_var).grid(
            row=4, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.show_sync_corr_var = tk.BooleanVar(value=False)

        self.sc_fde_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp2, text="Enable Post-EQ (LS)", variable=self.sc_fde_enable_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(grp2, text="Post-EQ Taps").grid(row=5, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.sc_fde_taps_var = tk.StringVar(value="1")
        taps_frame = ttk.Frame(grp2)
        taps_frame.grid(row=5, column=3, sticky="w", pady=(6, 0))
        ttk.Entry(taps_frame, textvariable=self.sc_fde_taps_var, width=7).pack(side=tk.LEFT)
        ttk.Button(taps_frame, text="Sweep",
                   command=self._on_sweep_sc_fde_taps).pack(side=tk.LEFT, padx=(5, 0))

        self.auto_sync_tx_params_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            grp2,
            text="Sync symbol/mod from AWG",
            variable=self.auto_sync_tx_params_var,
        ).grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))

        ttk.Label(grp2, text="Range Modes").grid(row=7, column=0, sticky="w", pady=(6, 0))
        self.range_mode_var = tk.StringVar(value="Row1 one-way, Row2 monostatic")
        self.range_modes_info_var = tk.StringVar(value="Row1: one-way LOS (c), Row2: monostatic sensing (c/2)")
        ttk.Label(grp2, textvariable=self.range_modes_info_var,
                  style="Muted.TLabel").grid(row=7, column=1, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(grp2, text="Range Diff (mm)").grid(row=9, column=0, sticky="w", pady=(6, 0))
        self.range_target_m_var = tk.StringVar(value="0")
        ttk.Entry(grp2, textvariable=self.range_target_m_var, width=10).grid(row=9, column=1, sticky="w", pady=(6, 0))
        ttk.Label(grp2, text="Diff Tol (mm)").grid(row=9, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.range_tolerance_m_var = tk.StringVar(value="5")
        ttk.Entry(grp2, textvariable=self.range_tolerance_m_var, width=10).grid(row=9, column=3, sticky="w", pady=(6, 0))

        ttk.Label(grp2, text="UTC-PD Photocurrent (mA)").grid(row=8, column=0, sticky="w", pady=(6, 0))
        self.photocurrent_ma_var = tk.StringVar(value="")
        ttk.Entry(grp2, textvariable=self.photocurrent_ma_var, width=10).grid(
            row=8, column=1, sticky="w", pady=(6, 0))
        ttk.Label(grp2, text="PD Responsivity (A/W)").grid(row=8, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.pd_responsivity_var = tk.StringVar(value="0.24")
        ttk.Entry(grp2, textvariable=self.pd_responsivity_var, width=10).grid(
            row=8, column=3, sticky="w", pady=(6, 0))
        for v in (self.photocurrent_ma_var, self.pd_responsivity_var):
            v.trace_add("write", lambda *_: self._refresh_metrics_table())

        # Section 3: Results
        # These StringVars are still used by DSP callbacks and saved captures.
        self.band_pwr_var    = tk.StringVar(value="Band Power:  ---")
        self.noise_floor_var = tk.StringVar(value="Noise Density: ---")
        self.snr_var         = tk.StringVar(value="Band SNR:    ---")
        self.evm_var         = tk.StringVar(value="EVM:         ---")
        self.ber_var         = tk.StringVar(value="BER:         ---")
        self.sym_count_var   = tk.StringVar(value="Symbols:     ---")

        grp_summary = ttk.LabelFrame(lf, text="Key Results", padding=6)
        grp_summary.pack(fill=tk.X, pady=(0, 6))
        self.summary_vars: dict[str, tk.StringVar] = {}
        summary_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        summary_items = [
            ("band_power_dbm", "Band Power"),
            ("noise_power_dbm", "Noise Power"),
            ("snr_com_db", "SNR"),
            ("evm_db", "EVM"),
            ("ber", "BER"),
            ("range_peak_mm", "Range"),
            ("range_resolution_mm", "Range Res."),
            ("diff_range_mm", "Delta Range"),
        ]
        for idx, (key, label) in enumerate(summary_items):
            row, col = divmod(idx, 2)
            cell = ttk.Frame(grp_summary)
            cell.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0), pady=3)
            grp_summary.columnconfigure(col, weight=1)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            var = tk.StringVar(value="---")
            self.summary_vars[key] = var
            ttk.Label(cell, textvariable=var, font=summary_font).pack(anchor="w")

        grp_metrics = ttk.LabelFrame(lf, text="Metrics", padding=6)
        grp_metrics.pack(fill=tk.X, pady=(0, 6))
        self.metrics_tree = ttk.Treeview(
            grp_metrics,
            columns=("metric", "value", "unit"),
            show="headings",
            height=12,
        )
        self.metrics_tree.heading("metric", text="Metric")
        self.metrics_tree.heading("value", text="Value")
        self.metrics_tree.heading("unit", text="Unit")
        self.metrics_tree.column("metric", width=190, anchor="w")
        self.metrics_tree.column("value", width=115, anchor="e")
        self.metrics_tree.column("unit", width=55, anchor="w")
        metrics_scroll = ttk.Scrollbar(
            grp_metrics, orient="vertical", command=self.metrics_tree.yview
        )
        self.metrics_tree.configure(yscrollcommand=metrics_scroll.set)
        metrics_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.metrics_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.parent.after(0, self._refresh_metrics_table)

        # Section 4: Log
        grp4 = ttk.LabelFrame(lf, text="Log", padding=4)
        grp4.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.log_text = tk.Text(grp4, height=8, bg="#ffffff",
                                font=("Consolas", 8), wrap="none")
        log_sb = ttk.Scrollbar(grp4, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Plot area
        # Physical grid is 4 rows (Time/Spectrum/Demod/Range) x 2 columns
        # Plot area: 2 rows (channels) x 4 columns (Time/Spectrum/Demod/Range).
        # Keeping one channel per row makes full-duplex measurements easier to compare.
        self.fig = Figure(figsize=(15.5, 8.5), dpi=100)
        gs = self.fig.add_gridspec(
            2, 4, left=0.055, right=0.985, bottom=0.075, top=0.94,
            hspace=0.34, wspace=0.31,
        )
        self.fd_axes = [
            [self.fig.add_subplot(gs[row, col]) for col in range(4)]
            for row in range(2)
        ]
        self.ax_time = self.fd_axes[0][0]
        self.ax_spec = self.fd_axes[0][1]
        self.ax_const = self.fd_axes[0][2]
        self.ax_range = self.fd_axes[0][3]
        self._init_plots()

        self.canvas_plot = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas_plot.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self._on_mode_changed()

    def _init_plots(self) -> None:
        titles = ("Time", "Spectrum", "Demod", "Range")
        for row in range(2):
            for col, title in enumerate(titles):
                ax = self.fd_axes[row][col]
                ax.set_title(title)
                ax.text(0.5, 0.5, "No data", ha="center", va="center",
                        transform=ax.transAxes, color="gray")
                ax.set_axis_off()
        self._apply_dashboard_layout()

    def _apply_dashboard_layout(self) -> None:
        self.fig.subplots_adjust(
            left=0.055, right=0.985, bottom=0.075, top=0.94,
            hspace=0.34, wspace=0.31,
        )

    @staticmethod
    def _apply_range_xlim(ax, est_range: float, default_max_m: float = 10.0,
                          zero_active: bool = False,
                          range_resolution_m: float = float("nan"),
                          x_scale: float = 1.0) -> None:
        """Set range-axis limits.

        est_range is always in meters. x_scale converts the plotted axis
        (normally 1e3 for mm). Keep this contract strict; passing an already
        scaled value here makes the axis 1000x too wide.
        """
        if zero_active:
            half_span_m = 0.015
            if np.isfinite(range_resolution_m) and range_resolution_m > 0:
                half_span_m = max(0.015, min(0.050, 3.0 * float(range_resolution_m)))
            ax.set_xlim(-half_span_m * x_scale, half_span_m * x_scale)
            return
        if x_scale >= 100.0 and np.isfinite(est_range) and est_range > 0:
            # In mm view, 0-10 m becomes 0-10000 mm and compresses the trace.
            # Show a practical absolute-range view unless the detected peak is
            # genuinely beyond the default span.
            if est_range <= default_max_m:
                range_max = min(default_max_m, max(2.0, est_range + 0.5, 1.25 * est_range))
            else:
                range_max = est_range * 1.15
        else:
            range_max = default_max_m
            if np.isfinite(est_range) and est_range > range_max:
                range_max = est_range * 1.15
        ax.set_xlim(0.0, range_max * x_scale)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        self.log_q.put(msg)

    def _start_log_pump(self) -> None:
        def pump() -> None:
            while not self.log_q.empty():
                self.log_text.insert(tk.END, self.log_q.get_nowait() + "\n")
                self.log_text.see(tk.END)
            self.parent.after(120, pump)
        pump()

    def _on_mode_changed(self) -> None:
        live = bool(self.live_var.get())
        state_live = "readonly" if live else "disabled"
        state_live_n = "normal" if live else "disabled"
        self.dso_type_combo.configure(state=state_live)
        self.host_entry.configure(state=state_live_n)
        self.timeout_entry.configure(state=state_live_n)
        self.test_btn.configure(state=state_live_n)

    def _selected_dso_channels(self) -> list[str]:
        selected = [
            ch for ch in ("C1", "C2", "C3", "C4")
            if bool(self.channel_select_vars.get(ch, tk.BooleanVar(value=False)).get())
        ]
        if not selected:
            cur = self.ch_var.get().strip().upper()
            selected = [cur if cur in {"C1", "C2", "C3", "C4"} else "C1"]
        return selected

    def _display_dso_channels(self) -> list[str]:
        selected = self._selected_dso_channels()
        return selected[:2]

    def _channel_scale_mv(self, ch_num: int) -> float:
        try:
            if int(ch_num) == 2:
                return float(self.ch2_scale_mv_var.get())
            return float(self.ch1_scale_mv_var.get())
        except Exception:
            return 100.0 if int(ch_num) != 2 else 20.0

    def _set_primary_rx_channel(self, ch: str) -> None:
        key = ch.strip().upper()
        item = self._rx_multi.get(key)
        if not item:
            return
        self.ch_var.set(key)
        self._rx_sig = np.asarray(item["sig"], dtype=np.float64)
        self._rx_t = np.asarray(item["t"], dtype=np.float64)
        self._rx_fs = float(item["fs"])

    def _on_channel_selection_changed(self) -> None:
        selected = self._selected_dso_channels()
        if len(selected) > 2:
            self._log("[UI] More than two DSO channels selected; dashboard shows the first two only.")
        primary = selected[0]
        self.ch_var.set(primary)
        if primary in self._rx_multi:
            self._set_primary_rx_channel(primary)
            self._plot_spectrum_and_time()

    def _on_range_zero_toggle(self) -> None:
        state = "ON" if bool(self.range_zero_enable_var.get()) else "OFF"
        self._log(
            f"[ISAC] Relative zero-axis display {state}. "
            "Normal mode keeps the absolute range axis and overlays the stored zero reference."
        )
        if self._rx_sig is not None:
            self._on_isac_dechirp_range()

    def _on_clear_range_zero(self) -> None:
        for key in (
            "lfm_range_zero_by_ch",
            "lfm_range_zero_info",
            "lfm_range_zero_delay_s",
            "lfm_range_zero_channel",
            "lfm_range_zero_cfr",
        ):
            self.runtime.pop(key, None)
        self.range_zero_enable_var.set(False)
        self._last_range_results = []
        self._last_range_summaries = []
        self._clear_range_metrics()
        self._log("[ISAC] Cleared stored zero/reference range data. Absolute range detection is now unreferenced.")
        if self._rx_sig is not None:
            self._plot_spectrum_and_time()
            self._refresh_metrics_table()

    def _on_fft_axis_var_changed(self, *_) -> None:
        """Trace callback: update spectrum y-axis only (no PSD recompute)."""
        if self._rx_sig is None:
            return
        try:
            # -60 offset to compensate for DSO calculation difference
            fft_offset = float(self.fft_offset_var.get()) - 60.0
            fft_scale  = float(self.fft_scale_div_var.get())
            if fft_scale > 0:
                for row_axes in getattr(self, "fd_axes", [[None, self.ax_spec]]):
                    ax = row_axes[1] if row_axes and len(row_axes) > 1 else self.ax_spec
                    if ax is not None:
                        ax.set_ylim(fft_offset - 8.0 * fft_scale, fft_offset)
                self.canvas_plot.draw_idle()
        except (ValueError, AttributeError):
            pass

    def _lfm_qam_extra_half_bw_ghz(self, sr: float) -> float:
        """Extra one-sided bandwidth the LFM sweep adds on top of the RRC band.

        The TX side multiplies each chirp by exp(j*pi*(symbol_rate/Tc)*t^2),
        which sweeps exactly one symbol-rate's worth of bandwidth (see
        _rx_to_baseband's occupied_one_sided calc).  QAM/FMCW don't chirp the
        data, so they get no extra width here.
        """
        try:
            pl = self._load_tx_payload_for_isac()
        except Exception:
            pl = None
        if pl is not None and str(pl.get("waveform_type", "")).strip() == "LFM-QAM":
            return 0.5 * sr
        return 0.0

    def _measurement_bandwidth_ghz(self, sr: float, beta: float) -> float:
        try:
            pl = self._load_tx_payload_for_isac()
            waveform_type = str(pl.get("waveform_type", "")).strip() if pl else ""
        except Exception:
            waveform_type = ""
        if waveform_type == "Tone":
            return max(0.02, min(1.0, float(sr)))
        if waveform_type == "DFT-s-OFDM":
            # The occupied DFT-s-OFDM band is set by the active IFFT bins, not
            # by a hard-coded RRC roll-off or display guard.  Fall back to Rs
            # when older TX refs do not carry the DFT metadata.
            try:
                sr_ref_hz = self._payload_symbol_rate_hz(pl) if pl else 0.0
                sr_ui_hz = float(sr) * 1e9
                if sr_ref_hz > 0 and sr_ui_hz > 0:
                    tol = max(5.0e6, 5.0e-4 * max(sr_ref_hz, sr_ui_hz))
                    if abs(sr_ref_hz - sr_ui_hz) > tol:
                        return float(sr)
                n_fft = int(pl.get("dft_n_fft", 0)) if pl else 0
                active = np.asarray(pl.get("dft_active_bins", []), dtype=np.int64).reshape(-1) if pl else np.zeros(0)
                fs_ref = float(pl.get("fs", 0.0)) if pl else 0.0
                if n_fft > 0 and len(active) > 0 and fs_ref > 0:
                    return (fs_ref * len(active) / n_fft) / 1e9
            except Exception:
                pass
            return float(sr)
        return float(sr) * (1.0 + float(np.clip(beta, 0.0, 1.0))) + 2.0 * self._lfm_qam_extra_half_bw_ghz(sr)

    def _update_band_label(self) -> None:
        try:
            fc   = float(self.fc_var.get())
            sr   = float(self.sr_var.get())
            beta = float(self.demod_beta_var.get())
            bw   = self._measurement_bandwidth_ghz(sr, beta)
            f_lo = fc - bw / 2.0
            f_hi = fc + bw / 2.0
            self.band_info_var.set(f"Band: {f_lo:.3f} - {f_hi:.3f} GHz")
        except Exception:
            self.band_info_var.set("Band: ---")

    def _get_signal_band_ghz(self) -> tuple[float, float]:
        """Compute (f_low, f_high) in GHz from carrier freq, symbol rate and RRC beta."""
        fc   = float(self.fc_var.get())
        sr   = float(self.sr_var.get())
        beta = float(np.clip(float(self.demod_beta_var.get()), 0.0, 1.0))
        bw   = self._measurement_bandwidth_ghz(sr, beta)
        return fc - bw / 2.0, fc + bw / 2.0

    @staticmethod
    def _metric_is_finite(value) -> bool:
        try:
            return bool(np.isfinite(float(value)))
        except Exception:
            return False

    @staticmethod
    def _metric_fmt(value, force_sci: bool = False) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, str):
            return value
        try:
            v = float(value)
            if not np.isfinite(v):
                return "N/A"
            if force_sci:
                return f"{v:.3e}"
            av = abs(v)
            if av != 0.0 and (av >= 1e4 or av < 1e-3):
                return f"{v:.3e}"
            if av >= 100:
                return f"{v:.2f}"
            if av >= 10:
                return f"{v:.3f}"
            return f"{v:.4f}"
        except Exception:
            return str(value)

    @staticmethod
    def _papr_db(x: np.ndarray) -> float:
        arr = np.asarray(x)
        if arr.size == 0:
            return float("nan")
        p = np.abs(arr.astype(np.complex128)) ** 2
        avg = float(np.mean(p))
        peak = float(np.max(p))
        if avg <= 0.0 or peak <= 0.0:
            return float("nan")
        return 10.0 * np.log10(peak / avg)

    def _rx_envelope_papr_db(self, sig: np.ndarray, fs: float) -> float:
        """PAPR of the received IF signal's band-limited analytic envelope."""
        x = np.asarray(sig, dtype=np.float64).reshape(-1)
        if len(x) < 8 or fs <= 0:
            return float("nan")
        try:
            f1_ghz, f2_ghz = self._get_signal_band_ghz()
            x_bp = self._fft_bandpass_real(x - float(np.mean(x)), fs, f1_ghz * 1e9, f2_ghz * 1e9)
            analytic = hilbert(x_bp)
            return self._papr_db(analytic)
        except Exception:
            return float("nan")

    def _set_metric(self, key: str, label: str, value, unit: str = "",
                    note: str = "", category: str = "") -> None:
        self._loaded_capture_without_metrics = False
        self._metrics[key] = {
            "label": label,
            "value": value,
            "unit": unit,
            "note": note,
            "category": category,
        }

    def _metric_float(self, key: str) -> float:
        item = self._metrics.get(key, {})
        try:
            return float(item.get("value", float("nan")))
        except Exception:
            return float("nan")

    def _metric_order(self) -> list[tuple[str, str, str, str, str]]:
        return [
            ("waveform_type", "Waveform", "", "System", "TX waveform type used by the reference."),
            ("modulation", "Modulation", "", "System", "TX/demod modulation format."),
            ("carrier_if_ghz", "Carrier/IF", "GHz", "System", "Configured real-IF carrier."),
            ("symbol_rate_ghz", "Symbol Rate", "GHz", "System", "Configured or restored symbol rate."),
            ("bandwidth_hz", "Bandwidth Bw", "GHz", "System", "Occupied measurement band used for SNR/DIR."),
            ("band_power_dbm", "Band Power", "dBm", "Comm", "Noise-subtracted in-band signal power."),
            ("noise_floor_dbmhz", "Noise Density", "dBm/Hz", "Comm", "Stored or capture-derived DSO PSD noise density."),
            ("noise_power_dbm", "Noise Power", "dBm", "Comm", "Noise density integrated over the analysis bandwidth."),
            ("snr_com_db", "Band SNR", "dB", "Comm", "Band Power divided by Noise Power; use EVM-implied SNR for demod quality."),
            ("sinr_com_db", "SINR_com", "dB", "Comm", "Equals SNR if interference is not separately estimated."),
            ("dir_gbps", "DIR", "Gb/s", "Comm", "Bw*log2(1+EVM-implied SNR) when available."),
            ("evm_db", "EVM", "dB", "Comm", "Measured demodulation EVM."),
            ("evm_snr", "EVM-implied SNR", "dB", "Comm", "-EVM[dB]; demodulation-quality communication SNR."),
            ("evm_pct", "EVM", "%", "Comm", "Measured demodulation EVM."),
            ("ber", "BER", "", "Comm", "Measured pre-FEC BER when PRBS/reference lock is valid."),
            ("symbols", "Symbols", "", "Comm", "Symbols used for BER/EVM."),
            ("radar_pre_snr_db_c2", "C2 Sensing pre-DSP SNR", "dB", "Sensing", "C2 in-band SNR before matched-filter/CFR range processing."),
            ("snr_rad_db", "Sensing SINR", "dB", "Sensing", "C2 post-processing range-profile SINR: target peak minus profile-floor median."),
            ("snr_rad_post_db_c2", "C2 Sensing post-proc SINR", "dB", "Sensing", "C2 range-profile SINR after matched-filter/CFR processing."),
            ("radar_processing_gain_db_c2", "C2 Sensing proc. gain", "dB", "Sensing", "Approx. 10log10(Nchirps*Nref) range-processing gain."),
            ("snr_rad_pg_corrected_db_c2", "C2 Sensing PG-corrected SINR", "dB", "Sensing", "Post-processing C2 sensing SINR minus the estimated processing gain."),
            ("mi_rad_mbps", "MI_sens", "Mbit/s", "Sensing", "0.5/Tsig*log2(1+SINR_sens)."),
            ("crlb_range_std_mm", "Range CRLB std", "mm", "Sensing", "AWGN delay CRLB using occupied bandwidth RMS proxy."),
            ("pslr_db", "PSLR", "dB", "Sensing", "Peak-to-sidelobe ratio from latest range profile."),
            ("range_peak_m", "Range Peak", "m", "Sensing", "Latest estimated range peak."),
            ("range_peak_mm", "Range Peak", "mm", "Sensing", "Latest estimated range peak in millimeters."),
            ("diff_range_mm", "Range Difference", "mm", "Sensing", "Current peak/CFR displacement relative to stored zero reference."),
            ("diff_cfr_coherence", "Differential CFR Coh.", "", "Sensing", "Coherence of differential CFR ratio."),
            ("range_mse_m2", "Range Est. MSE", "m^2", "Sensing", "Requires a known ground-truth range."),
            ("range_resolution_mm", "Range Resolution (Monostatic)", "mm", "Sensing", "Theoretical c/(2*Bw) range resolution."),
            ("duty_cycle_pct", "Sensing Duty Cycle", "%", "Sensing", "Fraction of the frame usable for matched-filter sensing processing."),
            ("awg_papr_db", "MZM Input IF Crest PAPR", "dB", "System", "Voltage-squared crest factor of the real-IF AWG waveform that drives the MZM."),
            ("rx_papr_db", "ADC Input IF Crest PAPR", "dB", "System", "Voltage-squared crest factor of the captured DSO IF waveform; use this to check ADC/headroom stress."),
            ("amplitude_ratio_rho", "Amplitude Ratio rho", "", "System", "Dual-chirp up/down amplitude ratio, if available."),
            ("photocurrent_ma", "Photocurrent", "mA", "System", "Enter the measured UTC-PD DC photocurrent above."),
            ("optical_power_dbm", "Optical Power", "dBm", "System", "Derived from Photocurrent / PD Responsivity."),
        ]

    def _update_derived_metrics(self) -> None:
        try:
            self._set_metric("carrier_if_ghz", "Carrier/IF", float(self.fc_var.get()), "GHz")
        except Exception:
            pass
        try:
            self._set_metric("symbol_rate_ghz", "Symbol Rate", float(self.sr_var.get()), "GHz")
        except Exception:
            pass
        self._set_metric("modulation", "Modulation", self.demod_mod_var.get().strip(), "")
        try:
            pl0 = self.runtime.get("tx_payload")
            if pl0:
                waveform_type0 = str(pl0.get("waveform_type", "unknown"))
                self._set_metric("waveform_type", "Waveform", waveform_type0, "")
                self._set_metric("modulation", "Modulation", str(pl0.get("modulation", self.demod_mod_var.get())), "")
                if "symbol_rate" in pl0:
                    self._set_metric("symbol_rate_ghz", "Symbol Rate", float(pl0.get("symbol_rate")) / 1e9, "GHz")
                if "symbol_rate_actual" in pl0:
                    self._set_metric(
                        "symbol_rate_actual_ghz",
                        "Actual Symbol Rate",
                        float(pl0.get("symbol_rate_actual")) / 1e9,
                        "GHz",
                    )

                # Sensing duty cycle: fraction of the frame that is a genuine
                # matched-filter sensing pulse. Shared LFM-QAM and DFT-s-OFDM
                # use the whole frame for sensing.
                if waveform_type0 in {"LFM-QAM", "DFT-s-OFDM"}:
                    self._set_metric("duty_cycle_pct", "Sensing Duty Cycle", 100.0, "%")
        except Exception:
            pass

        try:
            f1_ghz, f2_ghz = self._get_signal_band_ghz()
            bw_hz = max(0.0, (f2_ghz - f1_ghz) * 1e9)
            self._set_metric("bandwidth_hz", "Bandwidth Bw", bw_hz / 1e9, "GHz")
            if bw_hz > 0:
                range_res_m = self._range_delay_scale_m_per_s(row=1) / bw_hz
                self._set_metric(
                    "range_resolution_mm", "Range Resolution (Monostatic)",
                    range_res_m * 1e3, "mm",
                )
        except Exception:
            bw_hz = float("nan")

        evm_snr_db = self._metric_float("evm_snr")
        snr_db = evm_snr_db if np.isfinite(evm_snr_db) else self._metric_float("snr_com_db")
        if np.isfinite(snr_db) and not self._metric_is_finite(self._metric_float("sinr_com_db")):
            self._set_metric(
                "sinr_com_db", "SINR_com", snr_db, "dB",
                "No separate clutter/interference estimate; using EVM-implied SNR when available."
            )
        sinr_db = self._metric_float("sinr_com_db")
        if np.isfinite(snr_db) and np.isfinite(bw_hz) and bw_hz > 0:
            snr_lin = 10.0 ** (snr_db / 10.0)
            self._set_metric("dir_gbps", "DIR", bw_hz * np.log2(1.0 + snr_lin) / 1e9, "Gb/s")

        rad_snr_db = self._metric_float("snr_rad_db")
        if not np.isfinite(rad_snr_db):
            c2_pre_snr_db = self._metric_float("radar_pre_snr_db_c2")
            if not np.isfinite(c2_pre_snr_db):
                c2_pre_snr_db = self._metric_float("snr_com_db_c2")
            if np.isfinite(c2_pre_snr_db):
                rad_snr_db = c2_pre_snr_db
                self._set_metric(
                    "snr_rad_db",
                    "Sensing SINR",
                    rad_snr_db,
                    "dB",
                    "Fallback only: C2 pre-DSP band SNR. Run Detect Range for post-processing sensing SINR.",
                )
        if np.isfinite(rad_snr_db):
            rad_snr_lin = 10.0 ** (rad_snr_db / 10.0)
            try:
                pl = self.runtime.get("tx_payload") or self._load_tx_payload_for_isac()
            except Exception:
                pl = None
            t_sig = float("nan")
            if pl is not None:
                try:
                    tx = np.asarray(pl.get("tx_signal", []))
                    fs_tx = float(pl.get("fs", 0.0))
                    if len(tx) > 0 and fs_tx > 0:
                        t_sig = len(tx) / fs_tx
                except Exception:
                    t_sig = float("nan")
            if not np.isfinite(t_sig) and self._rx_sig is not None and self._rx_fs > 0:
                t_sig = len(self._rx_sig) / float(self._rx_fs)
            if np.isfinite(t_sig) and t_sig > 0:
                self._set_metric("mi_rad_mbps", "MI_rad", 0.5 / t_sig * np.log2(1.0 + rad_snr_lin) / 1e6, "Mbit/s")
            if np.isfinite(bw_hz) and bw_hz > 0:
                beta_rms = bw_hz / np.sqrt(12.0)
                tau_std = np.sqrt(1.0 / (8.0 * np.pi ** 2 * beta_rms ** 2 * rad_snr_lin))
                self._set_metric("crlb_range_std_mm", "Range CRLB std",
                                 self._range_delay_scale_m_per_s() * tau_std * 1e3, "mm")

        try:
            pl = self.runtime.get("tx_payload")
            if pl:
                if "awg_sig" in pl:
                    self._set_metric("awg_papr_db", "MZM Input IF Crest PAPR", self._papr_db(np.asarray(pl["awg_sig"])), "dB")
                if "amplitude_ratio_rho" in pl:
                    self._set_metric("amplitude_ratio_rho", "Amplitude Ratio rho", pl.get("amplitude_ratio_rho"), "")
        except Exception:
            pass
        if self._rx_sig is not None:
            self._set_metric("rx_papr_db", "ADC Input IF Crest PAPR", self._papr_db(np.asarray(self._rx_sig)), "dB")

        try:
            photocurrent_ma = float(self.photocurrent_ma_var.get())
            responsivity_a_per_w = float(self.pd_responsivity_var.get())
            if photocurrent_ma > 0 and responsivity_a_per_w > 0:
                p_opt_w = (photocurrent_ma * 1e-3) / responsivity_a_per_w
                p_opt_dbm = 10.0 * np.log10(p_opt_w * 1e3)
                self._set_metric("photocurrent_ma", "Photocurrent", photocurrent_ma, "mA")
                self._set_metric(
                    "optical_power_dbm", "Optical Power", p_opt_dbm, "dBm",
                    f"P_opt = I_pd / R, R={responsivity_a_per_w:.3f} A/W (vendor-measured UTC-PD responsivity).",
                )
        except Exception:
            pass

    def _metric_rows(self) -> list[dict[str, str]]:
        if self._loaded_capture_without_metrics:
            return []
        self._update_derived_metrics()
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        hidden_keys = {
            "awg_fs_gsa", "tx_sps", "hd_fec_7pct", "kp4_fec_5pct",
            "range_resolution_row1_mm", "range_resolution_row2_mm",
            "psk_order", "tx_papr_db", "rx_env_papr_db",
        }
        for key, label, unit_default, category, note_default in self._metric_order():
            item = self._metrics.get(key, {})
            value = item.get("value", "N/A")
            unit = str(item.get("unit") or unit_default)
            note = str(item.get("note") or note_default)
            rows.append({
                "key": key,
                "label": str(item.get("label", label)),
                "value": self._metric_fmt(value, force_sci=(key == "ber")),
                "unit": unit,
                "note": note,
                "category": str(item.get("category") or category),
            })
            seen.add(key)
        for key, item in self._metrics.items():
            if key in seen or key in hidden_keys:
                continue
            rows.append({
                "key": key,
                "label": str(item.get("label", key)),
                "value": self._metric_fmt(item.get("value", "N/A")),
                "unit": str(item.get("unit", "")),
                "note": str(item.get("note", "")),
                "category": str(item.get("category", "")),
            })
        return rows

    def _refresh_metrics_table(self) -> None:
        if not hasattr(self, "metrics_tree"):
            return
        rows = self._metric_rows()
        self.metrics_tree.delete(*self.metrics_tree.get_children())
        for row in rows:
            self.metrics_tree.insert(
                "",
                tk.END,
                iid=row["key"] if row["key"] not in self.metrics_tree.get_children() else "",
                values=(row["label"], row["value"], row["unit"]),
            )
        self._refresh_summary_panel(rows)

    def _refresh_summary_panel(self, rows: list[dict[str, str]] | None = None) -> None:
        if not hasattr(self, "summary_vars"):
            return
        if rows is None:
            rows = self._metric_rows()
        by_key = {row.get("key", ""): row for row in rows}
        for key, var in self.summary_vars.items():
            row = by_key.get(key)
            if row is None:
                var.set("---")
                continue
            value = row.get("value", "N/A")
            unit = row.get("unit", "")
            if not value or value == "N/A":
                var.set("N/A")
            elif unit:
                var.set(f"{value} {unit}")
            else:
                var.set(value)

    def _on_save_metrics_csv(self) -> None:
        rows = self._metric_rows()
        out_dir = APP_DIR / "data" / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        default_path = out_dir / f"isac_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path_str = filedialog.asksaveasfilename(
            title="Save Metrics CSV",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            with open(path_str, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["key", "category", "metric", "value", "unit", "note"])
                for row in rows:
                    writer.writerow([row["key"], row["category"], row["label"], row["value"], row["unit"], row["note"]])
            self._log(f"[Metrics] Saved CSV: {path_str}")
        except Exception as e:
            messagebox.showerror("Save Metrics Error", str(e))

    def _on_save_screenshot_png(self) -> None:
        out_dir = APP_DIR / "data" / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        default_path = out_dir / f"{self._artifact_default_stem('SS')}.png"
        path_str = filedialog.asksaveasfilename(
            title="Save GUI Screenshot",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            from PIL import Image

            rows = self._metric_rows()
            graph_buf = io.BytesIO()
            self.fig.savefig(
                graph_buf, format="png", dpi=160,
                facecolor="white", bbox_inches="tight",
            )
            graph_buf.seek(0)
            graph_img = Image.open(graph_buf).convert("RGB")

            table_width = 6.2
            table_height = max(2.4, 0.30 * (len(rows) + 2))
            table_fig = Figure(figsize=(table_width, table_height), dpi=160)
            table_ax = table_fig.add_subplot(111)
            table_ax.set_axis_off()
            table_ax.set_title("Metrics", fontsize=12, fontweight="bold", pad=10)
            cells = [[r["label"], r["value"], r["unit"]] for r in rows]
            if not cells:
                cells = [["No saved metrics", "", ""]]
            table = table_ax.table(
                cellText=cells,
                colLabels=["Metric", "Value", "Unit"],
                colWidths=[0.55, 0.28, 0.17],
                cellLoc="left",
                loc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1.0, 1.25)
            for (row, col), cell in table.get_celld().items():
                cell.set_edgecolor("#cbd5e1")
                if row == 0:
                    cell.set_facecolor("#e2e8f0")
                    cell.set_text_props(weight="bold")
                elif row % 2 == 0:
                    cell.set_facecolor("#f8fafc")
                if col == 1 and row > 0:
                    cell.set_text_props(ha="right")
            table_buf = io.BytesIO()
            table_fig.savefig(
                table_buf, format="png", dpi=160,
                facecolor="white", bbox_inches="tight", pad_inches=0.15,
            )
            table_buf.seek(0)
            table_img = Image.open(table_buf).convert("RGB")

            gap = 24
            width = graph_img.width + gap + table_img.width
            height = max(graph_img.height, table_img.height)
            combined = Image.new(
                "RGB", (width, height), "white"
            )
            combined.paste(graph_img, (0, 0))
            combined.paste(table_img, (graph_img.width + gap, 0))
            combined.save(path_str)
            self._log(f"[Screenshot] Saved PNG: {path_str}")
        except Exception as e:
            messagebox.showerror(
                "Screenshot Error",
                f"Could not save plots and metrics PNG.\n\n{e}\n\nInstall Pillow if it is unavailable."
            )

    def _on_run_isac_analysis(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire or load a capture first.")
            return
        try:
            pl_pre = self._load_tx_payload_for_isac()
            if pl_pre is not None:
                self._sync_dsp_params_from_payload(pl_pre, source="Run ISAC", force=False)
                self._assert_dsp_payload_consistent(pl_pre, context="Run ISAC")
        except Exception as e:
            self._log(f"[ISAC] Setup error: {e}")
            messagebox.showerror("Run ISAC Error", str(e))
            return
        self._log("[ISAC] Running combined analysis: SNR + demod + range.")
        display_channels = self._display_dso_channels()
        if self._rx_multi and display_channels:
            comm_ch = display_channels[0]
            self._set_primary_rx_channel(comm_ch)
            self._log(f"[ISAC] Communication demodulation uses row-1 one-way LOS channel {comm_ch}.")
        try:
            self._on_measure_band()
        except Exception as e:
            self._log(f"[ISAC] SNR measurement skipped: {e}")
        self._on_demodulate()
        try:
            pl = self._load_tx_payload_for_isac()
            waveform = str(pl.get("waveform_type", "") if pl else "").strip().upper()
        except Exception:
            waveform = ""
        if "LFM" in waveform or "FMCW" in waveform or "OFDM" in waveform:
            self.parent.after(250, self._on_isac_dechirp_range)
        else:
            self._log("[ISAC] Range step skipped because the TX reference is not an ISAC ranging waveform.")

    def _on_demod_button(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire or load a capture first.")
            return
        display_channels = self._display_dso_channels()
        if self._rx_multi and display_channels and display_channels[0] in self._rx_multi:
            self._set_primary_rx_channel(display_channels[0])
            self._log(f"[Demod] Using communication channel {display_channels[0]}.")
        try:
            self._on_measure_band()
        except Exception as e:
            self._log(f"[Demod] SNR measurement skipped: {e}")
        self._on_demodulate()

    def _on_detect_range_button(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire or load a capture first.")
            return
        try:
            pl = self._load_tx_payload_for_isac()
            if pl is not None:
                self._sync_dsp_params_from_payload(pl, source="Detect Range", force=False)
                self._assert_dsp_payload_consistent(pl, context="Detect Range")
        except Exception as e:
            self._log(f"[ISAC] Range setup error: {e}")
            messagebox.showerror("Detect Range Error", str(e))
            return
        self._on_isac_dechirp_range()

    def _scope_bw_ghz(self) -> float:
        try:
            return float(self.scope_bw_var.get())
        except Exception:
            return self._UXR0404A_BW_GHZ

    def _tx_occupied_bw_hz(self, pl: dict | None = None) -> float:
        if pl is None:
            try:
                pl = self._load_tx_payload_for_isac()
            except Exception:
                pl = None
        try:
            if pl and str(pl.get("waveform_type", "")).strip() == "DFT-s-OFDM":
                n_fft = int(pl.get("dft_n_fft", 0))
                n_active = len(np.asarray(pl.get("dft_active_bins", []), dtype=np.int64).reshape(-1))
                fs_ref = float(pl.get("fs", 0.0))
                if n_fft > 0 and n_active > 0 and fs_ref > 0:
                    return float(fs_ref * n_active / n_fft)
        except Exception:
            pass
        try:
            sr = self._payload_symbol_rate_hz(pl) if pl else float(self.sr_var.get()) * 1e9
        except Exception:
            sr = 1e9
        try:
            beta = float(np.clip(float(self.demod_beta_var.get()), 0.0, 1.0))
        except Exception:
            beta = 0.20
        try:
            wf = str(pl.get("waveform_type", "")).strip() if pl else ""
        except Exception:
            wf = ""
        if wf == "Tone":
            return max(20e6, min(1e9, sr))
        if wf == "LFM-QAM":
            return max(sr * (1.0 + beta), 2.0 * sr)
        return sr * (1.0 + beta)

    def _max_dso_sample_rate_hz(self) -> float:
        n_ch = len(self._selected_dso_channels())
        dso_type_val = self.dso_type_var.get().lower()
        if "uxr" in dso_type_val or "keysight" in dso_type_val:
            if n_ch <= 1:
                return 256e9
            if n_ch == 2:
                return 128e9
            return 64e9
        return 160e9

    def _recommended_dso_sample_rate_hz(self, pl: dict | None = None) -> float | None:
        if pl is None:
            try:
                pl = self._load_tx_payload_for_isac()
            except Exception:
                pl = None
        try:
            sr_hz = self._payload_symbol_rate_hz(pl) if pl else float(self.sr_var.get()) * 1e9
            if_hz = self._payload_if_hz(pl) if pl else float(self.fc_var.get()) * 1e9
        except Exception:
            return None
        if not np.isfinite(sr_hz) or sr_hz <= 0 or not np.isfinite(if_hz) or if_hz < 0:
            return None

        occupied = max(self._tx_occupied_bw_hz(pl), sr_hz)
        f_hi = if_hz + 0.5 * occupied * 1.12
        max_fs = self._max_dso_sample_rate_hz()
        if max_fs <= 0:
            return None

        min_for_nyquist = 2.25 * f_hi
        min_sps = 4 if str((pl or {}).get("waveform_type", "")).strip() == "DFT-s-OFDM" else 3
        k_min = max(min_sps, int(np.ceil(min_for_nyquist / sr_hz)))
        k_max = int(np.floor(max_fs / sr_hz))
        if k_max < k_min:
            return float(max_fs)

        fs_awg = float((pl or {}).get("fs", 0.0))
        awg_sps = int(round(fs_awg / sr_hz)) if fs_awg > 0 else 0
        best: tuple[float, int] | None = None
        for k in range(k_min, k_max + 1):
            fs = sr_hz * k
            if fs > max_fs * (1.0 + 1e-9):
                continue
            # Prefer the smallest integer samples/symbol that clears Nyquist,
            # then a simple AWG/DSO ratio when there is a tie.
            ratio_penalty = 0.0
            if awg_sps > 0:
                from math import gcd
                g = gcd(max(k, 1), max(awg_sps, 1))
                ratio_penalty = (k // g) + (awg_sps // g)
            score = 1000.0 * (k - k_min) + ratio_penalty
            if best is None or score < best[0]:
                best = (score, k)
        if best is None:
            return None
        return float(sr_hz * best[1])

    def _requested_process_fs(self) -> float | None:
        raw = self.capture_fs_var.get().strip()
        if not raw or raw.lower() == "auto":
            return None
        fs = float(raw) * 1e9
        if fs <= 0:
            raise ValueError("Process Fs must be positive.")
        return fs

    def _capture_fs_for_length_estimate_hz(self) -> float:
        process_fs = self._requested_process_fs()
        if process_fs is not None:
            return float(process_fs)
        raw_sr = str(self.dso_sr_var.get()).strip()
        requested = self._requested_dso_sample_rate_hz(resolve_auto=True)
        if raw_sr.lower() == "auto":
            # UXR often snaps arbitrary requested rates to the highest legal
            # rate for the active channel count (for example 72 -> 128 GSa/s
            # with two channels).  Size the record for that snapped rate so
            # the full TX frame still fits after resampling.
            return float(max(requested or 0.0, self._max_dso_sample_rate_hz(), 64e9))
        return float(requested or 64e9)

    def _minimum_capture_margin(self, pl: dict | None = None) -> float:
        try:
            waveform = str((pl or {}).get("waveform_type", "")).strip()
            if waveform == "DFT-s-OFDM":
                return 3.0
            if waveform in {"LFM-QAM", "FMCW"}:
                return 2.5
        except Exception:
            pass
        return 1.5

    def _log_capture_sample_plan(self, fallback_fs: float, max_samples: int | None) -> None:
        try:
            pl = self._load_tx_payload_for_isac()
        except Exception:
            pl = None
        try:
            fs_ref = float((pl or {}).get("fs", 0.0))
            sr_hz = self._payload_symbol_rate_hz(pl) if pl else float(self.sr_var.get()) * 1e9
            nps = int((pl or {}).get("sps", round(fs_ref / sr_hz) if sr_hz > 0 and fs_ref > 0 else 0))
            tx_len = len(np.asarray((pl or {}).get("awg_sig", [])))
            tx_dur_us = (tx_len / fs_ref * 1e6) if fs_ref > 0 and tx_len > 0 else float("nan")
            cap_us = (float(max_samples) / float(fallback_fs) * 1e6) if max_samples and fallback_fs > 0 else float("nan")
            ratio = float(fallback_fs) / fs_ref if fs_ref > 0 else float("nan")
            self._log(
                "[Acq] Sample plan: "
                f"AWG_fs={fs_ref/1e9:.6f} GSa/s, "
                f"DSO_req/fallback={fallback_fs/1e9:.6f} GSa/s, "
                f"ratio={ratio:.6f}, sym_rate={sr_hz/1e9:.6f} GBd, "
                f"AWG_sps={nps}, max_samples={max_samples or 'auto'}, "
                f"TX={tx_dur_us:.3f} us, capture~{cap_us:.3f} us."
            )
        except Exception as e:
            self._log(f"[Acq] Sample plan unavailable: {e}")

    def _max_capture_samples(self) -> int | None:
        # Manual data length override has highest priority
        raw_ksa = self.data_len_ksa_var.get().strip()
        if raw_ksa:
            try:
                return int(float(raw_ksa) * 1000)
            except Exception:
                pass

        raw = self.max_samples_var.get().strip()
        # If field is empty, auto-compute from TX signal duration with 1.5x margin
        if not raw:
            pl = self._load_tx_payload_for_isac()
            if pl and "awg_sig" in pl and "fs" in pl:
                sig_len = len(pl["awg_sig"])
                fs_awg = float(pl["fs"])
                fs_dso_auto = self._capture_fs_for_length_estimate_hz()
                duration = sig_len / fs_awg
                margin = self._minimum_capture_margin(pl)
                return max(int(duration * fs_dso_auto * margin), 100000)
            return None
        val = float(raw)
        if val <= 0:
            raise ValueError("Margin/Samples must be positive.")

        # If the user typed a huge number, treat it as literal Max Samples (legacy)
        if val >= 1000:
            return int(val)

        # Otherwise, compute required samples dynamically based on actual TX duration
        pl = self._load_tx_payload_for_isac()
        if pl and "awg_sig" in pl and "fs" in pl:
            sig_len = len(pl["awg_sig"])
            fs_awg = pl["fs"]

            fs_dso_target = self._capture_fs_for_length_estimate_hz()

            duration = sig_len / fs_awg
            margin = max(float(val), self._minimum_capture_margin(pl))
            needed_samples = int(duration * fs_dso_target * margin)
            return max(needed_samples, 100000)

        # Fallback if no TX payload is generated yet
        return 10000000

    @staticmethod
    def _resample_real(sig: np.ndarray, fs_in: float, fs_out: float) -> np.ndarray:
        if np.isclose(fs_in, fs_out):
            return np.asarray(sig, dtype=np.float64)
        y = fft_resample_complex(np.asarray(sig, dtype=np.float64), fs_in=fs_in, fs_out=fs_out)
        return np.real(y).astype(np.float64)

    @staticmethod
    def _fft_bandpass_real(sig: np.ndarray, fs: float, f_lo: float, f_hi: float) -> np.ndarray:
        x = np.asarray(sig, dtype=np.float64)
        if len(x) == 0:
            return x
        lo = max(0.0, float(f_lo))
        hi = min(fs / 2.0, float(f_hi))
        if hi <= lo:
            return np.zeros_like(x)
        freq = np.fft.fftfreq(len(x), d=1.0 / fs)
        X = np.fft.fft(x)
        af = np.abs(freq)
        mask = np.zeros(len(x), dtype=np.float64)
        pass_mask = (af >= lo) & (af <= hi)
        mask[pass_mask] = 1.0
        trans = min(max(0.02 * (hi - lo), 0.05e9), 0.50e9)
        if trans > 0:
            lo_tr = (af > max(0.0, lo - trans)) & (af < lo)
            if np.any(lo_tr):
                u = (af[lo_tr] - max(0.0, lo - trans)) / max(lo - max(0.0, lo - trans), 1.0)
                mask[lo_tr] = 0.5 * (1.0 - np.cos(np.pi * u))
            hi_tr = (af > hi) & (af < min(fs / 2.0, hi + trans))
            if np.any(hi_tr):
                u = (af[hi_tr] - hi) / max(min(fs / 2.0, hi + trans) - hi, 1.0)
                mask[hi_tr] = 0.5 * (1.0 + np.cos(np.pi * u))
        X *= mask
        return np.real(np.fft.ifft(X))

    @staticmethod
    def _compute_psd_db(sig: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
        """Single-sided PSD in dBm/Hz with a 50 ohm reference via Welch."""
        from scipy.signal import welch as _welch
        n = len(sig)
        nperseg = min(n, 4096)
        f, pxx = _welch(np.real(sig), fs=fs, nperseg=nperseg, scaling="density")
        psd_dbm_hz = 10.0 * np.log10(np.maximum(pxx / 50.0 / 1e-3, 1e-30))
        return f, psd_dbm_hz

    @staticmethod
    def _rrc_filter(sps: int, beta: float, span: int) -> np.ndarray:
        n = np.arange(-span * sps, span * sps + 1, dtype=np.float64)
        t = n / sps
        h = np.zeros_like(t)
        for i, tt in enumerate(t):
            if abs(tt) < 1e-10:
                h[i] = 1.0 + beta * (4.0 / np.pi - 1.0)
            elif abs(abs(tt) - 1.0 / (4.0 * beta)) < 1e-8:
                h[i] = (beta / np.sqrt(2.0)) * (
                    (1 + 2/np.pi) * np.sin(np.pi / (4 * beta))
                    + (1 - 2/np.pi) * np.cos(np.pi / (4 * beta)))
            else:
                num = np.sin(np.pi * tt * (1 - beta)) + 4 * beta * tt * np.cos(np.pi * tt * (1 + beta))
                den = np.pi * tt * (1 - (4 * beta * tt) ** 2)
                h[i] = num / (den + 1e-15)
        return h / (np.sqrt(np.sum(h**2)) + 1e-15)

    @staticmethod
    def _qam_hard_decision(syms: np.ndarray, M: int) -> np.ndarray:
        """Hard decision for square QAM. Returns ideal constellation point indices."""
        if M == 2:      # BPSK
            levels = np.array([-1.0, 1.0])
            re_idx = np.argmin(np.abs(np.real(syms)[:, None] - levels[None, :]), axis=1)
            return (levels[re_idx] + 0j).astype(np.complex128)
        if M == 4:      # QPSK
            c = np.array([-1-1j,-1+1j,1-1j,1+1j]) / np.sqrt(2)
        elif M == 8:    # 8PSK
            c = np.exp(1j * np.pi * np.arange(8) / 4)
        elif M == 32:
            bits = np.array(
                [[int(b) for b in format(i, "05b")] for i in range(32)],
                dtype=np.uint8,
            )
            c = _bits_to_qam_symbols(bits.reshape(-1), "32QAM")
        elif M == 64:
            bits = np.array(
                [[int(b) for b in format(i, "06b")] for i in range(64)],
                dtype=np.uint8,
            )
            c = _bits_to_qam_symbols(bits.reshape(-1), "64QAM")
        else:           # Square QAM fallback, e.g. 16QAM
            sq = int(np.sqrt(M))
            lvl = np.arange(-(sq-1), sq, 2, dtype=float)
            c = np.array([a + 1j*b for b in lvl for a in lvl])
        c = c / np.sqrt(np.mean(np.abs(c)**2))
        dist = np.abs(syms[:, None] - c[None, :])
        return c[np.argmin(dist, axis=1)]

    @staticmethod
    def _estimate_qam_cfo_mth_power(
        samples: np.ndarray,
        fs: float,
        sps: int,
        modulation: str,
        max_cfo_hz: float = 20e6,
    ) -> tuple[float, int, float]:
        """Blind QAM CFO estimate using the modulation's rotational symmetry.

        Sampling each possible symbol phase before taking the M-th power avoids
        doing a costly CFO/correlation grid search over the full DSO record.
        """
        x = np.asarray(samples, dtype=np.complex128).reshape(-1)
        sps_i = max(2, int(sps))
        if len(x) < 64 * sps_i or fs <= 0:
            return 0.0, 0, 0.0

        energies = np.asarray([
            np.mean(np.abs(x[phase::sps_i]) ** 2)
            for phase in range(sps_i)
        ])
        timing_phase = int(np.argmax(energies))
        symbols = x[timing_phase::sps_i]

        mod_u = str(modulation).strip().upper()
        if mod_u == "BPSK":
            order = 2
        elif mod_u == "8PSK":
            order = 8
        else:
            order = 4

        powered = symbols ** order
        n_fft = 1 << int(np.ceil(np.log2(max(64, len(powered)))))
        spectrum = np.abs(np.fft.fftshift(
            np.fft.fft(powered * np.hanning(len(powered)), n=n_fft)
        ))
        symbol_fs = fs / sps_i
        freqs = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / symbol_fs))
        search_limit = min(order * abs(float(max_cfo_hz)), 0.49 * symbol_fs)
        search = np.abs(freqs) <= search_limit
        if not np.any(search):
            return 0.0, timing_phase, 0.0

        searched = spectrum[search]
        peak_i = int(np.argmax(searched))
        peak_freq = float(freqs[search][peak_i])
        quality = float(searched[peak_i] / (np.median(searched) + 1e-15))
        return peak_freq / order, timing_phase, quality

    @staticmethod
    def _align_symbols_normalized(
        ref_symbols: np.ndarray,
        est_symbols: np.ndarray,
        max_lag: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, int]:
        """Align symbols with a normalized complex-correlation score."""
        ref = np.asarray(ref_symbols, dtype=np.complex128).reshape(-1)
        est = np.asarray(est_symbols, dtype=np.complex128).reshape(-1)
        best: tuple[float, int, int] | None = None

        for lag in range(-max(0, int(max_lag)), max(0, int(max_lag)) + 1):
            ref_start = max(0, lag)
            est_start = max(0, -lag)
            n = min(len(ref) - ref_start, len(est) - est_start)
            if n < 8:
                continue
            r = ref[ref_start:ref_start + n]
            e = est[est_start:est_start + n]
            score = float(np.abs(np.vdot(e, r)) / np.sqrt(
                (np.vdot(e, e).real + 1e-15) *
                (np.vdot(r, r).real + 1e-15)
            ))
            if best is None or score > best[0]:
                best = (score, lag, n)

        if best is None:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, np.zeros(0, dtype=np.int64), 0.0, 0

        score, lag, n = best
        ref_start = max(0, lag)
        est_start = max(0, -lag)
        ref_idx = np.arange(ref_start, ref_start + n, dtype=np.int64)
        return (
            ref[ref_start:ref_start + n].copy(),
            est[est_start:est_start + n].copy(),
            ref_idx,
            score,
            lag,
        )

    @staticmethod
    def _correct_symbols_to_reference(
        est_symbols: np.ndarray,
        ref_symbols: np.ndarray,
        train_mask: np.ndarray | None = None,
        linear_phase: bool = True,
        track_phase: bool = True,
        widely_linear: bool = True,
    ) -> np.ndarray:
        est = np.asarray(est_symbols, dtype=np.complex128).reshape(-1)
        ref = np.asarray(ref_symbols, dtype=np.complex128).reshape(-1)
        n = min(len(est), len(ref))
        if n == 0:
            return np.zeros(0, dtype=np.complex128)

        est = est[:n].copy()
        ref = ref[:n]
        if train_mask is None:
            train = np.ones(n, dtype=bool)
        else:
            train = np.asarray(train_mask, dtype=bool).reshape(-1)[:n].copy()
            if len(train) < n:
                train = np.pad(train, (0, n - len(train)), constant_values=False)
        if np.count_nonzero(train) < 2:
            train[:] = True

        idx = np.flatnonzero(train)
        k_all = np.arange(n, dtype=np.float64)
        pair = est[idx] * np.conj(ref[idx])
        valid = np.abs(pair) > 1e-12
        if linear_phase and np.count_nonzero(valid) >= 2:
            k_fit = idx[valid].astype(np.float64)
            ph_fit = np.unwrap(np.angle(pair[valid]))
            try:
                slope, intercept = np.polyfit(k_fit, ph_fit, deg=1)
                est *= np.exp(-1j * (slope * k_all + intercept))
            except Exception:
                pass
        elif linear_phase and np.count_nonzero(valid) == 1:
            est *= np.exp(-1j * float(np.angle(pair[valid][0])))

        # Decision-directed or reference-aided phase-noise cleanup.  Use it only
        # when training covers most symbols; sparse repeated preambles are better
        # handled by the linear fit above.
        if track_phase and np.count_nonzero(train) >= 32 and np.mean(train) > 0.5:
            block = max(32, min(256, int(np.count_nonzero(train) // 8)))
            centers: list[float] = []
            phases: list[float] = []
            for start in range(0, n, block):
                stop = min(n, start + block)
                local = train[start:stop]
                if np.count_nonzero(local) < max(8, block // 8):
                    continue
                z = np.sum(est[start:stop][local] * np.conj(ref[start:stop][local]))
                if np.abs(z) > 1e-12:
                    centers.append(0.5 * (start + stop - 1))
                    phases.append(float(np.angle(z)))
            if len(phases) >= 2:
                ph = np.unwrap(np.asarray(phases, dtype=np.float64))
                ctr = np.asarray(centers, dtype=np.float64)
                ph_track = np.interp(k_all, ctr, ph, left=ph[0], right=ph[-1])
                est *= np.exp(-1j * ph_track)
            elif len(phases) == 1:
                est *= np.exp(-1j * phases[0])

        train_idx = np.flatnonzero(train)
        if widely_linear and len(train_idx) >= 8:
            a_train = np.column_stack((
                est[train_idx],
                np.conj(est[train_idx]),
                np.ones(len(train_idx), dtype=np.complex128),
            ))
            try:
                coef, _, _, _ = np.linalg.lstsq(a_train, ref[train_idx], rcond=None)
                a_all = np.column_stack((
                    est,
                    np.conj(est),
                    np.ones(n, dtype=np.complex128),
                ))
                est = a_all @ coef
            except Exception:
                pass

        den = np.vdot(est[train_idx], est[train_idx]).real + 1e-15
        gain = np.vdot(est[train_idx], ref[train_idx]) / den
        return est * gain

    @classmethod
    def _reference_lock_score(
        cls,
        est_symbols: np.ndarray,
        ref_symbols: np.ndarray,
        train_mask: np.ndarray | None = None,
        track_phase: bool = False,
        widely_linear: bool = True,
    ) -> tuple[float, np.ndarray]:
        est_corr = cls._correct_symbols_to_reference(
            est_symbols,
            ref_symbols,
            train_mask=train_mask,
            linear_phase=True,
            track_phase=track_phase,
            widely_linear=widely_linear,
        )
        ref = np.asarray(ref_symbols, dtype=np.complex128).reshape(-1)[:len(est_corr)]
        if len(est_corr) == 0:
            return 0.0, est_corr
        if train_mask is None:
            train = np.ones(len(est_corr), dtype=bool)
        else:
            train = np.asarray(train_mask, dtype=bool).reshape(-1)[:len(est_corr)]
            if len(train) < len(est_corr):
                train = np.pad(train, (0, len(est_corr) - len(train)), constant_values=False)
        if np.count_nonzero(train) < 2:
            train[:] = True
        e = est_corr[train]
        r = ref[train]
        score = float(np.abs(np.vdot(e, r)) / np.sqrt(
            (np.vdot(e, e).real + 1e-15) *
            (np.vdot(r, r).real + 1e-15)
        ))
        return score, est_corr

    @classmethod
    def _decision_directed_symbol_cleanup(
        cls,
        symbols: np.ndarray,
        modulation: str,
        iterations: int = 3,
    ) -> tuple[np.ndarray, np.ndarray]:
        est = np.asarray(symbols, dtype=np.complex128).reshape(-1).copy()
        if len(est) == 0:
            return est, est.copy()
        rms = float(np.sqrt(np.mean(np.abs(est) ** 2)))
        if rms > 1e-15:
            est /= rms
        constellation_size = 1 << _bits_per_symbol(modulation)
        mod_u = str(modulation).strip().upper()
        allow_widely_linear = mod_u not in {"BPSK", "QPSK", "8PSK"}
        decisions = cls._qam_hard_decision(est, constellation_size)
        for _ in range(max(1, int(iterations))):
            est = cls._correct_symbols_to_reference(
                est,
                decisions,
                train_mask=None,
                linear_phase=True,
                track_phase=True,
                widely_linear=allow_widely_linear,
            )
            decisions = cls._qam_hard_decision(est, constellation_size)
        return est, decisions

    @staticmethod
    def _blind_psk_block_phase_track(symbols: np.ndarray, order: int, block: int = 128) -> np.ndarray:
        x = np.asarray(symbols, dtype=np.complex128).reshape(-1).copy()
        if len(x) < 2 * max(8, int(block)) or order <= 1:
            return x

        centers: list[float] = []
        phases: list[float] = []
        block_i = max(32, int(block))
        for start in range(0, len(x), block_i):
            stop = min(len(x), start + block_i)
            seg = x[start:stop]
            if len(seg) < 16:
                continue
            mag = np.abs(seg)
            valid = mag > max(1e-12, 0.25 * float(np.median(mag) + 1e-15))
            if np.count_nonzero(valid) < 8:
                continue
            z = np.mean((seg[valid] / (mag[valid] + 1e-15)) ** int(order))
            if np.abs(z) <= 1e-12:
                continue
            centers.append(0.5 * (start + stop - 1))
            phases.append(float(np.angle(z)))

        if len(phases) < 2:
            return x

        ph = np.unwrap(np.asarray(phases, dtype=np.float64)) / float(order)
        ctr = np.asarray(centers, dtype=np.float64)
        k = np.arange(len(x), dtype=np.float64)
        ph_track = np.interp(k, ctr, ph, left=ph[0], right=ph[-1])
        return x * np.exp(-1j * ph_track)

    @classmethod
    def _blind_qam_symbol_stream_from_mf(
        cls,
        rx_mf: np.ndarray,
        sps: int,
        modulation: str,
        n_symbols: int,
        preferred_phase: int = 0,
    ) -> tuple[np.ndarray, np.ndarray, float, int, int, float, float, str]:
        x = np.asarray(rx_mf, dtype=np.complex128).reshape(-1)
        sps_i = max(1, int(sps))
        n_req = max(64, int(n_symbols))
        if len(x) < 8 * sps_i:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, float("inf"), 0, 0, 0.0, 0.0, "none"

        mod_u = str(modulation).strip().upper()
        if mod_u == "BPSK":
            order = 2
        elif mod_u == "8PSK":
            order = 8
        elif mod_u == "QPSK":
            order = 4
        else:
            order = 0

        phase_energy = []
        for ph in range(sps_i):
            ss = x[ph::sps_i]
            if len(ss) >= 64:
                phase_energy.append((float(np.mean(np.abs(ss[:min(2048, len(ss))]) ** 2)), ph))
        phase_candidates = [int(preferred_phase) % sps_i]
        phase_candidates += [ph for _, ph in sorted(phase_energy, reverse=True)[:10]]
        phase_candidates = list(dict.fromkeys(phase_candidates))
        ppm_candidates = (0.0, -5000.0, 5000.0, -2500.0, 2500.0, -1000.0, 1000.0)
        gardner_gains = (0.0015, 0.004, 0.008)

        constellation_size = 1 << _bits_per_symbol(modulation)
        best: tuple[float, float, np.ndarray, np.ndarray, int, int, float, float, str] | None = None

        def score_candidate(
            cand_in: np.ndarray,
            ph_in: int,
            start_in: int,
            ppm_in: float,
            method_in: str,
        ) -> None:
            nonlocal best
            cand = np.asarray(cand_in, dtype=np.complex128).reshape(-1).copy()
            if len(cand) < 64:
                return
            cand -= np.mean(cand)
            rms = float(np.sqrt(np.mean(np.abs(cand) ** 2)))
            if rms <= 1e-15:
                return
            cand /= rms

            if order > 0 and len(cand) >= 32:
                powered = cand ** order
                mag = np.abs(powered)
                valid = mag > max(1e-12, 0.25 * float(np.median(mag) + 1e-15))
                if np.count_nonzero(valid) >= 16:
                    k_fit = np.flatnonzero(valid).astype(np.float64)
                    ph_fit = np.unwrap(np.angle(powered[valid]))
                    try:
                        slope, intercept = np.polyfit(k_fit, ph_fit, deg=1)
                        k_all = np.arange(len(cand), dtype=np.float64)
                        cand *= np.exp(-1j * (slope * k_all + intercept) / float(order))
                    except Exception:
                        pass
                cand = cls._blind_psk_block_phase_track(cand, order=order, block=96)

            est, decisions = cls._decision_directed_symbol_cleanup(
                cand,
                modulation=modulation,
                iterations=4,
            )
            if len(est) < 64:
                return
            evm = float(np.sqrt(
                np.mean(np.abs(est - decisions) ** 2) /
                (np.mean(np.abs(decisions) ** 2) + 1e-15)
            ))
            labels = cls._qam_hard_decision(est, constellation_size)
            _, counts = np.unique(np.round(labels, 12), return_counts=True)
            probs = counts.astype(np.float64) / max(1, int(np.sum(counts)))
            entropy = float(-np.sum(probs * np.log(probs + 1e-15)) / np.log(max(2, constellation_size)))
            metric = evm + 0.40 * max(0.0, 0.55 - entropy)
            if best is None or metric < best[0]:
                best = (
                    metric, evm, est.copy(), decisions.copy(), int(ph_in), int(start_in),
                    entropy, float(ppm_in), str(method_in),
                )

        for ph in phase_candidates:
            ss0 = x[ph::sps_i]
            if len(ss0) < 64:
                continue
            m = min(n_req, len(ss0), 4096)
            if m < 64:
                continue

            start_candidates = {0}
            if len(ss0) > m:
                power = np.abs(ss0) ** 2
                energy = np.convolve(power, np.ones(m, dtype=np.float64), mode="valid")
                for idx in np.argsort(energy)[-4:]:
                    start_candidates.add(int(idx))

            for start in sorted(s for s in start_candidates if 0 <= s <= len(ss0) - m):
                frame_start_sample = int(ph) + int(start) * sps_i
                for ppm in ppm_candidates:
                    step = float(sps_i) * (1.0 + float(ppm) * 1e-6)
                    if step <= 0.5 or frame_start_sample + (m - 1) * step >= len(x) - 1:
                        continue
                    if abs(ppm) <= 1e-12:
                        cand = np.asarray(ss0[start:start + m], dtype=np.complex128).copy()
                    else:
                        cand = cls._sample_fractional_symbol_indices(
                            x,
                            frame_start_sample=float(frame_start_sample),
                            step_samples=step,
                            symbol_indices=np.arange(m, dtype=np.int64),
                        )
                    score_candidate(cand, ph, start, ppm, f"fixed/sro={ppm:.0f}ppm")

                for gain in gardner_gains:
                    cand_g = cls._recover_qam_symbols_from_mf(
                        x,
                        frame_start_sample=frame_start_sample,
                        sps=sps_i,
                        n_symbols=m,
                        gain=float(gain),
                    )
                    score_candidate(cand_g, ph, start, 0.0, f"gardner/gain={gain:.4f}")

        if best is None:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, float("inf"), 0, 0, 0.0, 0.0, "none"
        _, evm, est_best, ref_best, ph_best, start_best, entropy_best, ppm_best, method_best = best
        return (
            est_best, ref_best, float(evm), int(ph_best), int(start_best),
            float(entropy_best), float(ppm_best), str(method_best),
        )

    @classmethod
    def _blind_qam_filter_symbol_search(
        cls,
        rx_bb: np.ndarray,
        rx_mf_primary: np.ndarray,
        sps: int,
        modulation: str,
        n_symbols: int,
        preferred_phase: int,
        primary_beta: float,
        span: int,
        extra_betas: tuple[float, ...] = (),
    ) -> tuple[np.ndarray, np.ndarray, float, int, int, float, float, str, str]:
        candidates: list[tuple[str, np.ndarray]] = []
        beta_seen: set[float] = set()

        def add_beta_candidate(label: str, beta_value: float, samples: np.ndarray | None = None) -> None:
            beta_clipped = float(np.clip(beta_value, 0.0, 1.0))
            key = round(beta_clipped, 4)
            if key in beta_seen:
                return
            beta_seen.add(key)
            if samples is None:
                taps = IsacTxSimPanel._rrc_taps(max(1, int(sps)), beta=beta_clipped, span=max(1, int(span)))
                mf = fftconvolve(np.asarray(rx_bb, dtype=np.complex128), taps, mode="same")
            else:
                mf = np.asarray(samples, dtype=np.complex128)
            candidates.append((f"{label}-rrc{beta_clipped:.2f}", mf))

        add_beta_candidate("payload", primary_beta, rx_mf_primary)
        for beta in extra_betas:
            add_beta_candidate("try", float(beta))
        candidates.append(("raw-bb", np.asarray(rx_bb, dtype=np.complex128)))

        best: tuple[float, np.ndarray, np.ndarray, float, int, int, float, float, str, str] | None = None
        for filter_name, mf_try in candidates:
            est, ref, evm, ph, start, entropy, ppm, method = cls._blind_qam_symbol_stream_from_mf(
                mf_try,
                sps=sps,
                modulation=modulation,
                n_symbols=n_symbols,
                preferred_phase=preferred_phase,
            )
            if len(est) < 64 or not np.isfinite(evm):
                continue
            metric = float(evm) + 0.40 * max(0.0, 0.55 - float(entropy))
            if best is None or metric < best[0]:
                best = (
                    metric, est.copy(), ref.copy(), float(evm), int(ph), int(start),
                    float(entropy), float(ppm), str(method), str(filter_name),
                )

        if best is None:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, float("inf"), 0, 0, 0.0, 0.0, "none", "none"
        _, est_best, ref_best, evm_best, ph_best, start_best, entropy_best, ppm_best, method_best, filter_best = best
        return (
            est_best, ref_best, evm_best, ph_best, start_best,
            entropy_best, ppm_best, method_best, filter_best,
        )

    @classmethod
    def _recover_qam_symbols_from_mf(
        cls,
        rx_mf: np.ndarray,
        frame_start_sample: int,
        sps: int,
        n_symbols: int,
        gain: float,
    ) -> np.ndarray:
        x = np.asarray(rx_mf, dtype=np.complex128).reshape(-1)
        if len(x) == 0 or n_symbols <= 0:
            return np.zeros(0, dtype=np.complex128)
        sps_i = max(2, int(sps))
        pre_guard = 2 * sps_i
        start = max(0, int(frame_start_sample) - pre_guard)
        offset = float(int(frame_start_sample) - start)
        need = int(np.ceil(offset + (int(n_symbols) + 1) * sps_i + 4))
        stop = min(len(x), start + need)
        seg = x[start:stop]
        if len(seg) < need:
            seg = np.pad(seg, (0, need - len(seg)))
        return IsacTxSimPanel._gardner_timing_recovery(
            seg,
            sps=sps_i,
            n_symbols=int(n_symbols),
            gain=float(gain),
            start_offset=offset,
        )

    @staticmethod
    def _sample_fractional_symbol_indices(
        samples: np.ndarray,
        frame_start_sample: float,
        step_samples: float,
        symbol_indices: np.ndarray,
        cfo_hz: float = 0.0,
        fs: float = 1.0,
        conjugate: bool = False,
    ) -> np.ndarray:
        x = np.asarray(samples, dtype=np.complex128).reshape(-1)
        sym_idx = np.asarray(symbol_indices, dtype=np.float64).reshape(-1)
        if len(x) < 2 or len(sym_idx) == 0 or step_samples <= 0:
            return np.zeros(0, dtype=np.complex128)
        pos = float(frame_start_sample) + sym_idx * float(step_samples)
        if np.any(pos < 0.0) or np.any(pos >= len(x) - 1):
            return np.zeros(0, dtype=np.complex128)
        i0 = np.floor(pos).astype(np.int64)
        frac = pos - i0.astype(np.float64)
        out = ((1.0 - frac) * x[i0] + frac * x[i0 + 1]).astype(np.complex128)
        if conjugate:
            out = np.conj(out)
        if fs > 0 and abs(cfo_hz) > 1e-9:
            out *= np.exp(-1j * 2.0 * np.pi * float(cfo_hz) * pos / float(fs))
        return out

    @staticmethod
    def _common_gain_corr_score(est_symbols: np.ndarray, ref_symbols: np.ndarray) -> float:
        est = np.asarray(est_symbols, dtype=np.complex128).reshape(-1)
        ref = np.asarray(ref_symbols, dtype=np.complex128).reshape(-1)
        n = min(len(est), len(ref))
        if n < 4:
            return 0.0
        est = est[:n]
        ref = ref[:n]
        est = est - np.mean(est)
        ref = ref - np.mean(ref)
        den_e = np.vdot(est, est).real
        den_r = np.vdot(ref, ref).real
        if den_e <= 1e-15 or den_r <= 1e-15:
            return 0.0
        return float(np.abs(np.vdot(est, ref)) / np.sqrt(den_e * den_r + 1e-15))

    @classmethod
    def _refine_qam_frame_cfo_sro(
        cls,
        rx_mf: np.ndarray,
        fs: float,
        qam_ref_full: np.ndarray,
        preamble_mask: np.ndarray,
        data_mask: np.ndarray,
        rough_frame_starts: list[tuple[int, int]],
        sps: int,
        modulation: str,
    ) -> dict | None:
        """Jointly refine QAM frame start, residual CFO, and samples/symbol.

        Keysight IQTools can quantize carrierOffset and can slightly alter the
        effective sample/symbol ratio when it must satisfy AWG segment
        granularity.  Integer-nps slicing is brittle in that case; this routine
        scores the known preamble symbols on a fractional timing grid.
        """
        x = np.asarray(rx_mf, dtype=np.complex128).reshape(-1)
        ref = np.asarray(qam_ref_full, dtype=np.complex128).reshape(-1)
        if len(x) < 16 or len(ref) < 16 or sps <= 0 or fs <= 0:
            return None
        starts = [
            (int(sym), int(samp))
            for sym, samp in rough_frame_starts
            if 0 <= int(samp) < len(x) - 2
        ]
        if not starts:
            return None

        pre = np.asarray(preamble_mask, dtype=bool).reshape(-1)[:len(ref)]
        data = np.asarray(data_mask, dtype=bool).reshape(-1)[:len(ref)]
        if len(pre) < len(ref):
            pre = np.pad(pre, (0, len(ref) - len(pre)), constant_values=False)
        if len(data) < len(ref):
            data = np.pad(data, (0, len(ref) - len(data)), constant_values=False)

        pre_idx = np.flatnonzero(pre)
        data_idx = np.flatnonzero(data)
        eval_parts: list[np.ndarray] = []
        if len(pre_idx) > 0:
            if len(pre_idx) > 256:
                take_pre = np.linspace(0, len(pre_idx) - 1, 256).round().astype(np.int64)
                eval_parts.append(pre_idx[take_pre])
            else:
                eval_parts.append(pre_idx)
        if len(data_idx) > 0:
            n_data_eval = 512 - sum(len(p) for p in eval_parts)
            n_data_eval = max(0, min(n_data_eval, len(data_idx)))
            if n_data_eval > 0:
                take_data = np.linspace(0, len(data_idx) - 1, n_data_eval).round().astype(np.int64)
                eval_parts.append(data_idx[take_data])
        if eval_parts:
            eval_idx = np.unique(np.concatenate(eval_parts)).astype(np.int64)
        else:
            eval_idx = np.arange(min(len(ref), 512), dtype=np.int64)
        if len(eval_idx) < 8:
            eval_idx = np.arange(min(len(ref), 512), dtype=np.int64)
        if len(eval_idx) > 512:
            take = np.linspace(0, len(eval_idx) - 1, 512).round().astype(np.int64)
            eval_idx = eval_idx[take]
        ref_eval = ref[eval_idx]

        if len(pre_idx) >= 8:
            split_at = np.flatnonzero(np.diff(pre_idx) > 1) + 1
            runs = np.split(pre_idx, split_at)
            cfo_idx = max(runs, key=len)
            if len(cfo_idx) > 256:
                cfo_idx = cfo_idx[:256]
        else:
            cfo_idx = eval_idx[:min(len(eval_idx), 256)]
        ref_cfo = ref[cfo_idx]

        mod_u = str(modulation).strip().upper()
        modes = ((False, "direct"), (True, "conj"))
        if mod_u not in {"BPSK", "QPSK", "8PSK"}:
            modes = ((False, "direct"),)

        best: dict | None = None
        coarse_records: list[dict] = []

        def estimate_cfo_from_ref(est_raw: np.ndarray, ref_raw: np.ndarray, positions: np.ndarray) -> float:
            n = min(len(est_raw), len(ref_raw), len(positions))
            if n < 8:
                return 0.0
            pair = est_raw[:n] * np.conj(ref_raw[:n])
            mag = np.abs(pair)
            good = mag > max(1e-12, 0.20 * float(np.median(mag) + 1e-15))
            if np.count_nonzero(good) < 8:
                good = mag > 1e-12
            if np.count_nonzero(good) < 8:
                return 0.0
            p = np.asarray(positions[:n], dtype=np.float64)[good]
            ph = np.unwrap(np.angle(pair[good]))
            try:
                slope, _ = np.polyfit(p, ph, deg=1)
            except Exception:
                return 0.0
            cfo = float(slope * float(fs) / (2.0 * np.pi))
            return float(np.clip(cfo, -250e6, 250e6))

        def visit_grid(ppm_values: np.ndarray, start_offsets: np.ndarray, collect: bool = False) -> None:
            nonlocal best
            for ppm in ppm_values:
                step = float(sps) * (1.0 + float(ppm) * 1e-6)
                if step <= 0.5:
                    continue
                for frame_start_sym, frame_start_sample in starts:
                    for start_off in start_offsets:
                        start = float(frame_start_sample) + float(start_off)
                        positions = start + eval_idx.astype(np.float64) * step
                        positions_cfo = start + cfo_idx.astype(np.float64) * step
                        if (
                            np.any(positions < 0.0) or np.any(positions >= len(x) - 1) or
                            np.any(positions_cfo < 0.0) or np.any(positions_cfo >= len(x) - 1)
                        ):
                            continue
                        for conj_flag, mode_name in modes:
                            est_cfo = cls._sample_fractional_symbol_indices(
                                x,
                                frame_start_sample=start,
                                step_samples=step,
                                symbol_indices=cfo_idx,
                                cfo_hz=0.0,
                                fs=float(fs),
                                conjugate=conj_flag,
                            )
                            est_raw = cls._sample_fractional_symbol_indices(
                                x,
                                frame_start_sample=start,
                                step_samples=step,
                                symbol_indices=eval_idx,
                                cfo_hz=0.0,
                                fs=float(fs),
                                conjugate=conj_flag,
                            )
                            if len(est_raw) != len(ref_eval) or len(est_cfo) != len(ref_cfo):
                                continue
                            cfo = estimate_cfo_from_ref(est_cfo, ref_cfo, positions_cfo)
                            est_eval = est_raw * np.exp(
                                -1j * 2.0 * np.pi * cfo * positions / float(fs)
                            )
                            score = cls._common_gain_corr_score(est_eval, ref_eval)
                            if best is None or score > best["sync_score"]:
                                record = {
                                    "sync_score": float(score),
                                    "cfo_hz": float(cfo),
                                    "sro_ppm": float(ppm),
                                    "step": float(step),
                                    "start_sample": float(start),
                                    "frame_start_sym": int(frame_start_sym),
                                    "mode": mode_name,
                                    "conjugate": bool(conj_flag),
                                }
                                best = record
                            elif collect:
                                record = {
                                    "sync_score": float(score),
                                    "cfo_hz": float(cfo),
                                    "sro_ppm": float(ppm),
                                    "step": float(step),
                                    "start_sample": float(start),
                                    "frame_start_sym": int(frame_start_sym),
                                    "mode": mode_name,
                                    "conjugate": bool(conj_flag),
                                }
                            else:
                                record = None
                            if collect and record is not None:
                                coarse_records.append(record)

        coarse_ppm = np.unique(np.concatenate((
            np.arange(-5000, 5001, 500, dtype=np.float64),
            np.asarray([-20000, -10000, 10000, 20000], dtype=np.float64),
        )))
        coarse_start = np.linspace(-1.0 * float(sps), 1.0 * float(sps), 33, dtype=np.float64)
        visit_grid(coarse_ppm, coarse_start, collect=True)
        if best is None:
            return None

        fine_ppm_offsets = np.asarray(
            [-750, -500, -300, -200, -100, -30, 0, 30, 100, 200, 300, 500, 750],
            dtype=np.float64,
        )
        fine_start = np.linspace(-0.08 * float(sps), 0.08 * float(sps), 17, dtype=np.float64)
        top_coarse = sorted(
            coarse_records,
            key=lambda r: float(r.get("sync_score", 0.0)),
            reverse=True,
        )[:8]
        if not top_coarse and best is not None:
            top_coarse = [best]
        old_starts = starts.copy()
        try:
            for rec in top_coarse:
                starts[:] = [(int(rec["frame_start_sym"]), int(round(rec["start_sample"])))]
                fine_ppm = float(rec["sro_ppm"]) + fine_ppm_offsets
                visit_grid(fine_ppm, fine_start, collect=False)
        finally:
            starts[:] = old_starts

        if best is None:
            return None

        all_idx = np.arange(len(ref), dtype=np.int64)
        est_full = cls._sample_fractional_symbol_indices(
            x,
            frame_start_sample=best["start_sample"],
            step_samples=best["step"],
            symbol_indices=all_idx,
            cfo_hz=best["cfo_hz"],
            fs=float(fs),
            conjugate=bool(best["conjugate"]),
        )
        if len(est_full) < min(64, len(ref)):
            return None
        est_full = est_full[:len(ref)]
        pre_score, _ = cls._reference_lock_score(
            est_full,
            ref,
            train_mask=pre,
            track_phase=False,
            widely_linear=False,
        )
        data_score, _ = cls._reference_lock_score(
            est_full,
            ref,
            train_mask=data,
            track_phase=False,
            widely_linear=(mod_u not in {"BPSK", "QPSK", "8PSK"}),
        )
        best["symbols"] = est_full.copy()
        best["pre_score"] = float(pre_score)
        best["data_score"] = float(data_score)
        best["rank_score"] = float(pre_score + 0.35 * data_score)
        best["sro_ppm"] = float((best["step"] / float(sps) - 1.0) * 1e6)
        return best

    @classmethod
    def _refine_lfm_frame_sro(
        cls,
        rx_bb: np.ndarray,
        frame_start: int,
        tx_ref: np.ndarray,
        fs: float,
        max_ppm: float = 150.0,
        max_cfo_hz: float = 5e6,
    ) -> tuple[float, float, float, float]:
        """Jointly refine the LFM-QAM frame start, sample-rate offset and CFO.

        Dechirping multiplies the received signal by a deterministic chirp
        reference sample-for-sample, so even a few-ppm clock mismatch between
        the AWG and the scope (they are not phase-locked here) leaves a
        residual sweep on later chirps that a single integer-sample
        correlation peak cannot remove -- that residual is what turns a good
        SNR into a near-0 dB EVM.  Every transmitted LFM-QAM sample is known
        (deterministic PRBS payload), so this scores a coarse-to-fine
        (ppm, start-offset) grid directly against the full TX baseband
        reference and returns the affine fit that best explains the whole
        capture.

        The upstream coarse CFO grid search (against a single chirp) is not
        always exact; any residual carrier offset rotates phase across the
        long evaluation span and gets misread as a timing/rate error if left
        uncompensated here, which silently corrupts the (ppm, start) fit and
        caps the achievable score.  So CFO is estimated jointly per
        candidate (linear phase-vs-position regression), exactly like
        `_refine_qam_frame_cfo_sro` already does for plain QAM.
        """
        x = np.asarray(rx_bb, dtype=np.complex128).reshape(-1)
        ref = np.asarray(tx_ref, dtype=np.complex128).reshape(-1)
        n_ref = len(ref)
        if n_ref < 64 or len(x) < 64 or fs <= 0:
            return float(frame_start), 0.0, 0.0, 0.0

        n_eval = min(n_ref, 800)
        eval_idx = np.linspace(0, n_ref - 1, n_eval)
        ref_eval = ref[eval_idx.round().astype(np.int64)]

        def fit_cfo(est: np.ndarray, positions: np.ndarray) -> float:
            pair = est * np.conj(ref_eval)
            mag = np.abs(pair)
            good = mag > max(1e-12, 0.20 * float(np.median(mag) + 1e-15))
            if np.count_nonzero(good) < 8:
                return 0.0
            ph = np.unwrap(np.angle(pair[good]))
            try:
                slope, _ = np.polyfit(positions[good], ph, deg=1)
            except Exception:
                return 0.0
            cfo = float(slope * float(fs) / (2.0 * np.pi))
            return float(np.clip(cfo, -max_cfo_hz, max_cfo_hz))

        def score(ppm: float, start_off: float) -> tuple[float, float]:
            step = 1.0 + ppm * 1e-6
            start = float(frame_start) + start_off
            est = cls._sample_fractional_symbol_indices(
                x, frame_start_sample=start, step_samples=step, symbol_indices=eval_idx,
            )
            if len(est) != len(ref_eval):
                return -1.0, 0.0
            positions = start + eval_idx * step
            cfo = fit_cfo(est, positions)
            est_c = est * np.exp(-1j * 2.0 * np.pi * cfo * positions / float(fs))
            return cls._common_gain_corr_score(est_c, ref_eval), cfo

        best_score, best_cfo = score(0.0, 0.0)
        best_ppm, best_off = 0.0, 0.0
        ppm_span, off_span = float(max_ppm), 4.0
        for _ in range(4):
            ppm_grid = np.linspace(best_ppm - ppm_span, best_ppm + ppm_span, 13)
            off_grid = np.linspace(best_off - off_span, best_off + off_span, 9)
            for ppm in ppm_grid:
                for off in off_grid:
                    s, cfo = score(float(ppm), float(off))
                    if s > best_score:
                        best_score, best_ppm, best_off, best_cfo = s, float(ppm), float(off), cfo
            ppm_span *= 0.35
            off_span *= 0.35

        return float(frame_start) + best_off, best_ppm, best_cfo, best_score

    @staticmethod
    def _build_prbs_period_symbols(prbs_n: int, modulation: str) -> np.ndarray:
        bps = _bits_per_symbol(modulation)
        bits = _prbs_bits_lfsr(int(prbs_n), (2 ** int(prbs_n)) - 1)
        bits = bits[:max(bps, (len(bits) // bps) * bps)]
        return _bits_to_qam_symbols(bits, modulation=modulation)

    @staticmethod
    def _lfsr_bits_variant(
        prbs_n: int,
        length: int,
        taps: tuple[int, int],
        seed_mode: str,
        output_tail: bool,
    ) -> np.ndarray:
        n = int(prbs_n)
        if seed_mode == "last-one":
            state = np.zeros(n, dtype=np.uint8)
            state[-1] = 1
        else:
            state = np.ones(n, dtype=np.uint8)
        out = np.zeros(int(length), dtype=np.uint8)
        tap_idx = [max(0, min(n - 1, int(t) - 1)) for t in taps]
        for i in range(int(length)):
            out[i] = state[-1] if output_tail else state[0]
            fb = np.bitwise_xor.reduce(state[tap_idx])
            state[1:] = state[:-1]
            state[0] = fb
        return out

    @classmethod
    def _build_prbs_period_symbol_candidates(
        cls,
        prbs_n: int,
        modulation: str,
    ) -> list[tuple[str, np.ndarray]]:
        bps = _bits_per_symbol(modulation)
        n = int(prbs_n)
        bit_len = max(bps, (2 ** n) - 1)
        bit_len = (bit_len // bps) * bps
        std_taps = {
            7: (7, 6),
            9: (9, 5),
            10: (10, 7),
            11: (11, 9),
            15: (15, 14),
            20: (20, 3),
            23: (23, 18),
        }

        bit_variants: list[tuple[str, np.ndarray]] = [
            ("gui-lfsr", _prbs_bits_lfsr(n, bit_len)),
        ]
        if n in std_taps:
            taps = std_taps[n]
            for seed_mode in ("ones", "last-one"):
                for output_tail in (True, False):
                    bits = cls._lfsr_bits_variant(n, bit_len, taps, seed_mode, output_tail)
                    bit_variants.append((
                        f"std-{seed_mode}-{'tail' if output_tail else 'head'}",
                        bits,
                    ))
            # Legacy IQTools code used 1 - flipud(PNSequence.step()).  Keep the
            # most likely PNSequence state/output variants without exploding the
            # live search space.
            for output_tail in (True, False):
                bits = cls._lfsr_bits_variant(n, bit_len, taps, "last-one", output_tail)
                bit_variants.append((
                    f"iqtools-last-one-{'tail' if output_tail else 'head'}",
                    1 - bits[::-1],
                ))

        candidates: list[tuple[str, np.ndarray]] = []
        seen: set[bytes] = set()
        for name, bits0 in bit_variants:
            bits_t = np.asarray(bits0[:bit_len], dtype=np.uint8)
            key = bits_t.tobytes()
            if key in seen:
                continue
            seen.add(key)
            syms = _bits_to_qam_symbols(bits_t, modulation=modulation)
            if len(syms) >= 8:
                candidates.append((name, syms))
        return candidates

    @classmethod
    def _prbs_symbol_stream_fallback(
        cls,
        rx_mf: np.ndarray,
        sps: int,
        modulation: str,
        prbs_n: int,
        n_symbols: int,
        preferred_phase: int = 0,
        preferred_start: int = 0,
    ) -> tuple[np.ndarray, np.ndarray, float, int, int, int, str]:
        x = np.asarray(rx_mf, dtype=np.complex128).reshape(-1)
        sps_i = max(1, int(sps))
        ref_candidates = cls._build_prbs_period_symbol_candidates(prbs_n, modulation)
        if len(x) < 8 * sps_i or not ref_candidates:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, 0.0, 0, 0, 0, "none"

        energies = []
        for ph in range(sps_i):
            ss = x[ph::sps_i]
            if len(ss) >= 16:
                energies.append((float(np.mean(np.abs(ss[:min(len(ss), 2048)]) ** 2)), ph))
        phase_candidates = [int(preferred_phase) % sps_i]
        phase_candidates += [ph for _, ph in sorted(energies, reverse=True)[:3]]
        phase_candidates = list(dict.fromkeys(phase_candidates))

        best: dict | None = None
        ref_period_max = max(len(r) for _, r in ref_candidates)
        ppm_candidates = np.asarray(
            [0, -1000, 1000, -5000, 5000],
            dtype=np.float64,
        )
        window_cache: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}

        def ref_windows(ref_name: str, ref_period: np.ndarray, m_eval_i: int) -> tuple[np.ndarray, np.ndarray]:
            key = (ref_name, int(m_eval_i))
            cached = window_cache.get(key)
            if cached is not None:
                return cached
            reps_i = int(np.ceil((m_eval_i + len(ref_period)) / len(ref_period))) + 1
            ref_long_i = np.tile(ref_period, reps_i)
            try:
                win = np.lib.stride_tricks.sliding_window_view(
                    ref_long_i[:m_eval_i + len(ref_period) - 1],
                    m_eval_i,
                )[:len(ref_period)]
            except Exception:
                win = np.asarray(
                    [ref_long_i[off:off + m_eval_i] for off in range(len(ref_period))],
                    dtype=np.complex128,
                )
            dwin_i = win[:, 1:] * np.conj(win[:, :-1]) if m_eval_i >= 4 else win
            window_cache[key] = (win, dwin_i)
            return win, dwin_i
        for ph in phase_candidates:
            ss0 = x[ph::sps_i]
            if len(ss0) < 32:
                continue
            for mode, conj_flag in (("direct", False), ("conj", True)):
                ss_raw = np.conj(ss0) if conj_flag else ss0
                target_eval = min(
                    int(n_symbols),
                    max(768, min(1280, ref_period_max + 128)),
                )
                m_eval = min(len(ss_raw), max(256, target_eval))
                if len(ss_raw) < m_eval:
                    continue
                start_candidates = {0, max(0, int(preferred_start))}

                power = np.abs(ss_raw) ** 2
                if len(power) >= m_eval:
                    win = np.ones(m_eval, dtype=np.float64)
                    energy = np.convolve(power, win, mode="valid")
                    for idx in np.argsort(energy)[-2:]:
                        start_candidates.add(int(idx))

                max_start = len(ss_raw) - m_eval
                if len(ss_raw) >= int(n_symbols):
                    max_start = min(max_start, len(ss_raw) - int(n_symbols))
                start_candidates = [
                    s for s in sorted(start_candidates)
                    if 0 <= s <= max_start
                ]
                for start_sym in start_candidates:
                    for ppm in ppm_candidates:
                        step = float(sps_i) * (1.0 + float(ppm) * 1e-6)
                        frame_start_sample = int(ph) + int(start_sym) * sps_i
                        if step <= 0.5:
                            continue
                        if ppm == 0:
                            ss = np.asarray(ss_raw[start_sym:start_sym + m_eval], dtype=np.complex128).copy()
                        else:
                            ss = cls._sample_fractional_symbol_indices(
                                x,
                                frame_start_sample=float(frame_start_sample),
                                step_samples=step,
                                symbol_indices=np.arange(m_eval, dtype=np.int64),
                                cfo_hz=0.0,
                                fs=1.0,
                                conjugate=conj_flag,
                            )
                        if len(ss) < m_eval:
                            continue
                        ss -= np.mean(ss)
                        rms = float(np.sqrt(np.mean(np.abs(ss) ** 2)))
                        if rms <= 1e-15:
                            continue
                        ss /= rms

                        for ref_name, ref_period in ref_candidates:
                            windows, dwin = ref_windows(ref_name, ref_period, m_eval)
                            if m_eval >= 4:
                                dss = ss[1:] * np.conj(ss[:-1])
                                num = np.abs(dwin @ np.conj(dss))
                                den = np.sqrt(
                                    (np.sum(np.abs(dwin) ** 2, axis=1) + 1e-15) *
                                    (np.vdot(dss, dss).real + 1e-15)
                                )
                                scores = num / den
                            else:
                                num = np.abs(windows @ np.conj(ss))
                                den = np.sqrt(
                                    (np.sum(np.abs(windows) ** 2, axis=1) + 1e-15) *
                                    (np.vdot(ss, ss).real + 1e-15)
                                )
                                scores = num / den
                            top_offsets = np.argsort(scores)[-12:]
                            for off_i in top_offsets:
                                off = int(off_i)
                                ref_try = windows[off].copy()
                                cand = cls._correct_symbols_to_reference(
                                    ss,
                                    ref_try,
                                    linear_phase=True,
                                    track_phase=False,
                                    widely_linear=False,
                                )
                                br = _hard_bits_from_symbols(ref_try, modulation)
                                be = _hard_bits_from_symbols(cand, modulation)
                                ber = float(np.mean(br != be)) if len(br) == len(be) > 0 else 1.0
                                corr_score = float(np.abs(np.vdot(cand, ref_try)) / np.sqrt(
                                    (np.vdot(cand, cand).real + 1e-15) *
                                    (np.vdot(ref_try, ref_try).real + 1e-15)
                                ))
                                metric = ber - 0.03 * corr_score
                                if best is None or metric < best["metric"]:
                                    best = {
                                        "metric": float(metric),
                                        "score": float(corr_score),
                                        "phase": int(ph),
                                        "start": int(start_sym),
                                        "offset": int(off),
                                        "mode": mode,
                                        "conjugate": bool(conj_flag),
                                        "ppm": float(ppm),
                                        "ref_name": ref_name,
                                        "ref_period": ref_period,
                                    }

        if best is None:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, 0.0, 0, 0, 0, "none"

        ph_best = int(best["phase"])
        start_best = int(best["start"])
        off_best = int(best["offset"])
        mode_best = str(best["mode"])
        ppm_best = float(best["ppm"])
        ref_period_best = np.asarray(best["ref_period"], dtype=np.complex128)
        step_best = float(sps_i) * (1.0 + ppm_best * 1e-6)
        frame_start_sample = ph_best + start_best * sps_i
        n_fit = int(np.floor((len(x) - 1 - frame_start_sample) / max(step_best, 1e-9))) + 1
        n = min(int(n_symbols), max(0, n_fit))
        reps = int(np.ceil((off_best + n) / len(ref_period_best))) + 1
        ref_full = np.tile(ref_period_best, reps)[off_best:off_best + n]
        best_est = None
        best_score = -1.0
        gain_options = (0.0,) if abs(ppm_best) > 1e-9 else (0.0, 0.0015, 0.004, 0.008)
        for gain in gain_options:
            if gain == 0.0 and abs(ppm_best) <= 1e-9:
                ss_full = x[ph_best::sps_i]
                if bool(best["conjugate"]):
                    ss_full = np.conj(ss_full)
                cand = np.asarray(ss_full[start_best:start_best + n], dtype=np.complex128).copy()
            elif gain == 0.0:
                cand = cls._sample_fractional_symbol_indices(
                    x,
                    frame_start_sample=float(frame_start_sample),
                    step_samples=step_best,
                    symbol_indices=np.arange(n, dtype=np.int64),
                    cfo_hz=0.0,
                    fs=1.0,
                    conjugate=bool(best["conjugate"]),
                )
            else:
                cand = cls._recover_qam_symbols_from_mf(
                    x,
                    frame_start_sample=frame_start_sample,
                    sps=sps_i,
                    n_symbols=n,
                    gain=gain,
                )
                if bool(best["conjugate"]):
                    cand = np.conj(cand)
                cand = cand[:n]
            if len(cand) < min(64, n):
                continue
            ref_c = ref_full[:len(cand)]
            rms_full = float(np.sqrt(np.mean(np.abs(cand) ** 2)))
            if rms_full > 1e-15:
                cand = cand / rms_full
            cand = cls._correct_symbols_to_reference(
                cand,
                ref_c,
                linear_phase=True,
                track_phase=False,
                widely_linear=False,
            )
            cand_score = float(np.abs(np.vdot(cand, ref_c)) / np.sqrt(
                (np.vdot(cand, cand).real + 1e-15) *
                (np.vdot(ref_c, ref_c).real + 1e-15)
            ))
            if cand_score > best_score:
                best_score = cand_score
                best_est = cand
        if best_est is None:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, 0.0, int(ph_best), int(start_best), int(off_best), mode_best
        mode_label = (
            f"{mode_best}/{best['ref_name']}/sro={ppm_best:.0f}ppm"
        )
        return best_est, ref_full[:len(best_est)], float(max(float(best["score"]), best_score)), int(ph_best), int(start_best), int(off_best), mode_label

    @classmethod
    def _equalize_reference_candidates(
        cls,
        est_symbols: np.ndarray,
        ref_symbols: np.ndarray,
        modulation: str,
        sc_fde_taps: int,
        sc_fde_enable: bool,
        max_lag: int,
    ) -> tuple[np.ndarray, np.ndarray, str, float]:
        ref = np.asarray(ref_symbols, dtype=np.complex128).reshape(-1)
        est = np.asarray(est_symbols, dtype=np.complex128).reshape(-1)
        n = min(len(ref), len(est))
        if n == 0:
            empty = np.zeros(0, dtype=np.complex128)
            return empty, empty, "empty", float("inf")
        ref = ref[:n]
        est = est[:n]
        mod_u = str(modulation).strip().upper()
        allow_widely_linear = mod_u not in {"BPSK", "QPSK", "8PSK"}

        base_candidates: list[tuple[str, np.ndarray]] = [
            ("phase", est),
        ]
        if allow_widely_linear:
            base_candidates.extend([
                ("iq", est),
                ("raw-iq", est),
                ("conj-iq", np.conj(est)),
            ])
        else:
            base_candidates.append(("conj-phase", np.conj(est)))
        if mod_u in {"QPSK", "16QAM"}:
            base_candidates.extend([
                ("rot90-iq", 1j * est),
                ("rot180-iq", -est),
                ("rot270-iq", -1j * est),
            ])

        best: tuple[float, np.ndarray, np.ndarray, str] | None = None
        ref_raw, est_raw, _, _, _ = cls._align_symbols_normalized(
            ref, est, max_lag=max(0, int(max_lag))
        )
        if len(ref_raw) >= 8:
            est_raw = cls._correct_symbols_to_reference(
                est_raw,
                ref_raw,
                linear_phase=False,
                track_phase=False,
                widely_linear=False,
            )
            evm_raw = float(np.sqrt(
                np.mean(np.abs(est_raw - ref_raw) ** 2) /
                (np.mean(np.abs(ref_raw) ** 2) + 1e-15)
            ))
            best = (evm_raw, ref_raw, est_raw, "raw+noeq")

        for name, x0 in base_candidates:
            try:
                if name == "phase":
                    x = cls._correct_symbols_to_reference(
                        x0, ref, linear_phase=True, track_phase=allow_widely_linear, widely_linear=False
                    )
                elif name == "conj-phase":
                    x = cls._correct_symbols_to_reference(
                        x0, ref, linear_phase=True, track_phase=False, widely_linear=False
                    )
                elif name == "raw-iq":
                    x = cls._correct_symbols_to_reference(
                        x0, ref, linear_phase=False, track_phase=False, widely_linear=True
                    )
                else:
                    x = cls._correct_symbols_to_reference(
                        x0, ref, linear_phase=True, track_phase=False, widely_linear=allow_widely_linear
                    )

                eq_enable_options = [False, True] if bool(sc_fde_enable) else [False]
                for eq_enable in eq_enable_options:
                    eq = sc_fde_equalizer(
                        x, ref,
                        num_taps=max(1, int(sc_fde_taps)),
                        enable=eq_enable,
                    )
                    ref_al, est_al, _, _, _ = cls._align_symbols_normalized(
                        ref, eq, max_lag=max(0, int(max_lag))
                    )
                    if len(ref_al) < 8:
                        continue
                    est_al = cls._correct_symbols_to_reference(
                        est_al,
                        ref_al,
                        linear_phase=True,
                        track_phase=allow_widely_linear,
                        widely_linear=allow_widely_linear,
                    )
                    corr_after = float(np.abs(np.vdot(est_al, ref_al)) / np.sqrt(
                        (np.vdot(est_al, est_al).real + 1e-15) *
                        (np.vdot(ref_al, ref_al).real + 1e-15)
                    ))
                    power_ratio = float(
                        (np.mean(np.abs(est_al) ** 2) + 1e-15) /
                        (np.mean(np.abs(ref_al) ** 2) + 1e-15)
                    )
                    if corr_after < 0.15 or power_ratio < 0.05:
                        continue
                    evm = float(np.sqrt(
                        np.mean(np.abs(est_al - ref_al) ** 2) /
                        (np.mean(np.abs(ref_al) ** 2) + 1e-15)
                    ))
                    cand_name = f"{name}+eq" if eq_enable else f"{name}+noeq"
                    if best is None or evm < best[0]:
                        best = (evm, ref_al, est_al, cand_name)
            except Exception:
                continue

        if best is None:
            ref_al, est_al, _, _, _ = cls._align_symbols_normalized(
                ref, est, max_lag=max(0, int(max_lag))
            )
            if len(ref_al) == 0:
                return np.zeros(0, dtype=np.complex128), np.zeros(0, dtype=np.complex128), "failed", float("inf")
            evm = float(np.sqrt(
                np.mean(np.abs(est_al - ref_al) ** 2) /
                (np.mean(np.abs(ref_al) ** 2) + 1e-15)
            ))
            return ref_al, est_al, "fallback", evm

        evm, ref_best, est_best, name_best = best
        return ref_best, est_best, name_best, evm

    @staticmethod
    def _bits_per_sym(mod: str) -> int:
        return {"BPSK":1,"QPSK":2,"8PSK":3,"16QAM":4,"32QAM":5,"64QAM":6}.get(mod.upper(), 4)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @staticmethod
    def _channel_number_from_text(ch_text: str) -> str:
        return str(ch_text).strip().upper().replace("C", "").replace("HAN", "").replace("NEL", "")

    def _dso_channel_number(self) -> str:
        return self._channel_number_from_text(self.ch_var.get())

    @staticmethod
    def _dso_write_ok(dso, cmd: str) -> bool:
        try:
            dso.write(cmd)
            return True
        except Exception:
            return False

    @staticmethod
    def _dso_query_text(dso, cmd: str, timeout_s: float = 2.0) -> str:
        try:
            return str(dso.query(cmd, timeout_s=timeout_s)).strip()
        except TypeError:
            try:
                return str(dso.query(cmd)).strip()
            except Exception:
                return ""
        except Exception:
            return ""

    def _drain_dso_errors(self, dso, limit: int = 8) -> list[str]:
        errors: list[str] = []
        for _ in range(max(1, int(limit))):
            msg = self._dso_query_text(dso, ":SYSTem:ERRor?", timeout_s=2.0)
            if not msg:
                break
            upper = msg.upper()
            if upper.startswith("+0") or upper.startswith("0,") or "NO ERROR" in upper:
                break
            errors.append(msg)
        return errors

    def _apply_keysight_time_fft_layout(self, dso, selected_nums: list[str]) -> dict:
        """Create a Time/FFT display layout for one or two Keysight channels."""
        nums = [str(n).strip() for n in selected_nums if str(n).strip()]
        nums = nums[:2]
        applied: dict[str, object] = {}
        if not nums:
            return applied

        for idx in range(1, 5):
            self._dso_write_ok(dso, f":FUNCtion{idx}:DISPlay OFF")

        for idx, ch_num in enumerate(nums, start=1):
            self._dso_write_ok(dso, f":CHANnel{ch_num}:DISPlay ON")
            self._dso_write_ok(dso, f":FUNCtion{idx}:FFTMagnitude CHANnel{ch_num}")
            self._dso_write_ok(dso, f":FUNCtion{idx}:FFT:VUNits DB")
            self._dso_write_ok(dso, f":FUNCtion{idx}:FFT:STARt 0")
            self._dso_write_ok(dso, f":FUNCtion{idx}:FFT:STOP 25000000000")
            self._dso_write_ok(dso, f":FUNCtion{idx}:DISPlay ON")

        for area in range(2, 9):
            self._dso_write_ok(dso, f":DISPlay:GRATicule:AREA{area}:STATe OFF")

        if len(nums) >= 2:
            # UXR 2-by-2 in waveform area 1:
            # grid 1/2 = time traces, grid 3/4 = FFT/PSD traces.
            self._dso_write_ok(dso, ":DISPlay:GRATicule:NUMBer 4,1")
            self._dso_write_ok(dso, ":DISPlay:GRATicule:GLAYout THORizontal,1")
            assignments = (
                (f"CHN{nums[0]}", 1),
                (f"CHN{nums[1]}", 2),
                ("FN1", 3),
                ("FN2", 4),
            )
            applied["dso_layout"] = f"[C{nums[0]} time, C{nums[1]} time; C{nums[0]} PSD, C{nums[1]} PSD]"
        else:
            # One channel: keep time and FFT stacked.
            self._dso_write_ok(dso, ":DISPlay:GRATicule:NUMBer 2,1")
            self._dso_write_ok(dso, ":DISPlay:GRATicule:GLAYout SVERtical,1")
            assignments = (
                (f"CHN{nums[0]}", 1),
                ("FN1", 2),
            )
            applied["dso_layout"] = f"C{nums[0]} time/FFT"

        for source, grid in assignments:
            self._dso_write_ok(dso, f":DISPlay:GRATicule:SETGrat {source},{grid},1")
        return applied

    def _apply_dso_trigger_settings_to_controller(self, dso) -> dict:
        applied: dict[str, object] = {}
        trig_txt = self.trig_ch_var.get().strip()
        if trig_txt.lower() == "off":
            return applied

        trig_num = self._channel_number_from_text(trig_txt)
        if not trig_num:
            return applied

        level_v = 0.0
        try:
            level_v = float(self.trig_level_mv_var.get()) / 1000.0
        except Exception:
            level_v = 0.0

        if self._dso_write_ok(dso, ":TRIGger:MODE EDGE"):
            applied["trigger_mode"] = "EDGE"

        source_ok = False
        for cmd in (f":TRIGger:EDGE:SOURce CHANnel{trig_num}",):
            source_ok = self._dso_write_ok(dso, cmd) or source_ok
        if source_ok:
            applied["trigger_source"] = f"C{trig_num}"

        level_ok = False
        for cmd in (
            f":TRIGger:LEVel CHANnel{trig_num},{level_v:.12g}",
        ):
            level_ok = self._dso_write_ok(dso, cmd) or level_ok
        if level_ok:
            applied["trigger_level_v"] = level_v
        return applied

    def _requested_dso_sample_rate_hz(self, resolve_auto: bool = True) -> float | None:
        sr_val = str(self.dso_sr_var.get()).strip()
        if not sr_val or sr_val.lower() == "auto":
            if resolve_auto:
                return self._recommended_dso_sample_rate_hz()
            return None
        try:
            fs_target = float(sr_val) * 1e9
        except Exception:
            return None
        if not np.isfinite(fs_target) or fs_target <= 0:
            return None
        return float(fs_target)

    def _apply_dso_sample_rate_to_controller(self, dso, dso_type_val: str = "") -> dict:
        applied: dict[str, object] = {}
        sr_text = str(self.dso_sr_var.get()).strip()
        auto_selected = (not sr_text) or sr_text.lower() == "auto"
        fs_target = self._requested_dso_sample_rate_hz(resolve_auto=not auto_selected)
        is_keysight = "uxr" in dso_type_val or "keysight" in dso_type_val

        if auto_selected:
            recommended = self._recommended_dso_sample_rate_hz()
            applied["sample_rate_target"] = "Auto"
            if recommended is not None and np.isfinite(recommended):
                applied["sample_rate_recommended_for_record"] = float(recommended)
                try:
                    pl = self._load_tx_payload_for_isac()
                    sr_hz = self._payload_symbol_rate_hz(pl) if pl else float(self.sr_var.get()) * 1e9
                    fs_awg = float((pl or {}).get("fs", 0.0))
                    dso_sps = recommended / sr_hz if sr_hz > 0 else float("nan")
                    awg_sps = fs_awg / sr_hz if sr_hz > 0 and fs_awg > 0 else float("nan")
                    self._log(
                        "[Acq] DSO SR Auto: scope chooses the legal rate; "
                        f"record sizing uses >= {recommended/1e9:.6f} GSa/s "
                        f"({dso_sps:.3f} Sa/sym, AWG={fs_awg/1e9:.6f} GSa/s, "
                        f"AWG_SPS={awg_sps:.3f})."
                    )
                except Exception:
                    pass
            if is_keysight:
                auto_ok = self._dso_write_ok(dso, ":ACQuire:SRATe:ANALog:AUTO ON")
                if auto_ok:
                    applied["sample_rate_auto"] = True
                actual_txt = self._dso_query_text(dso, ":ACQuire:SRATe:ANALog?")
                try:
                    actual = float(actual_txt)
                    if np.isfinite(actual) and actual > 0:
                        applied["sample_rate_actual"] = actual
                except Exception:
                    if actual_txt:
                        applied["sample_rate_actual"] = actual_txt
            return applied

        if fs_target is None:
            applied["sample_rate_target"] = "Auto"
            if is_keysight and self._dso_write_ok(dso, ":ACQuire:SRATe:ANALog:AUTO ON"):
                applied["sample_rate_auto"] = True
            return applied

        applied["sample_rate_target"] = fs_target
        if not is_keysight:
            return applied

        auto_ok = self._dso_write_ok(dso, ":ACQuire:SRATe:ANALog:AUTO OFF")
        rate_ok = self._dso_write_ok(dso, f":ACQuire:SRATe:ANALog {fs_target:.12g}")
        if auto_ok or rate_ok:
            actual_txt = self._dso_query_text(dso, ":ACQuire:SRATe:ANALog?")
            try:
                actual = float(actual_txt)
                if np.isfinite(actual) and actual > 0:
                    applied["sample_rate_actual"] = actual
            except Exception:
                if actual_txt:
                    applied["sample_rate_actual"] = actual_txt
        return applied

    def _warn_dso_sample_rate_mismatch(self, ch: str, fs_native: float) -> None:
        if str(self.dso_sr_var.get()).strip().lower() == "auto":
            return
        fs_target = self._requested_dso_sample_rate_hz()
        if fs_target is None:
            return
        try:
            fs_native = float(fs_native)
        except Exception:
            return
        if not np.isfinite(fs_native) or fs_native <= 0:
            return
        if abs(fs_native - fs_target) > 0.05 * fs_target:
            self._log(
                f"[Acq] WARNING: {ch} DSO returned fs={fs_native/1e9:.3f} GSa/s "
                f"while GUI requests {fs_target/1e9:.3f} GSa/s. "
                "Check UXR memory/timebase limits or sample-rate command support."
            )

    def _apply_dso_gui_settings_to_controller(
        self,
        dso,
        include_layout: bool = True,
        touch_display: bool = True,
        touch_scale: bool = True,
        touch_timebase: bool = True,
        touch_trigger: bool = True,
        touch_fft_axis: bool = True,
        touch_sample_rate: bool = True,
    ) -> dict:
        """Apply GUI DSO settings to an already-open controller."""
        applied: dict[str, object] = {}
        dso_type_val = self.dso_type_var.get().lower()
        ch_num = self._dso_channel_number()
        selected_nums = [self._channel_number_from_text(ch) for ch in self._selected_dso_channels()]
        selected_nums = [n for n in selected_nums if n]

        if touch_display:
            for display_num in (1, 2, 3, 4):
                state = "ON" if display_num in selected_nums else "OFF"
                self._dso_write_ok(dso, f":CHANnel{display_num}:DISPlay {state}")
        if touch_scale:
            for display_num in selected_nums:
                try:
                    scale_vdiv = self._channel_scale_mv(display_num) / 1000.0
                    if self._dso_write_ok(dso, f":CHANnel{display_num}:SCALe {scale_vdiv:.6g}"):
                        applied[f"ch{display_num}_scale_vdiv"] = scale_vdiv
                except Exception:
                    pass
        if selected_nums:
            applied["channels"] = [f"C{n}" for n in selected_nums]

        sr_val = self.dso_sr_var.get()
        sr_auto = str(sr_val).strip().lower() == "auto"
        fs_target = self._requested_dso_sample_rate_hz(resolve_auto=True)
        if fs_target is not None:
            applied["sample_rate_target"] = fs_target
        elif str(sr_val).strip().lower() != "auto":
            try:
                fs_target = float(sr_val) * 1e9
                applied["sample_rate_target"] = fs_target
            except Exception:
                fs_target = None

        if touch_sample_rate:
            applied.update(self._apply_dso_sample_rate_to_controller(dso, dso_type_val))

        n_pts = None
        raw_ksa = self.data_len_ksa_var.get().strip()
        if raw_ksa:
            try:
                n_pts = int(float(raw_ksa) * 1000)
            except Exception:
                n_pts = None
        if n_pts is None:
            n_pts = self._max_capture_samples()
        if n_pts:
            n_pts = int(n_pts)
            applied["points_target"] = n_pts
            fs_for_timebase = self._capture_fs_for_length_estimate_hz() if sr_auto else fs_target
            if touch_timebase and fs_for_timebase and fs_for_timebase > 0:
                time_range = n_pts / fs_for_timebase
                if self._dso_write_ok(dso, f":TIMebase:RANGe {time_range:.12g}"):
                    applied["time_range"] = time_range

        if ch_num:
            if "uxr" in dso_type_val or "keysight" in dso_type_val:
                if include_layout:
                    applied.update(self._apply_keysight_time_fft_layout(dso, selected_nums or [ch_num]))
            else:
                if include_layout:
                    self._dso_write_ok(dso, f":FUNCtion1:FFT:MAGNitude CHANnel{ch_num}")
                    self._dso_write_ok(dso, ":FUNCtion1:DISPlay ON")

        if touch_trigger:
            applied.update(self._apply_dso_trigger_settings_to_controller(dso))

        if touch_fft_axis:
            try:
                fft_offset = float(self.fft_offset_var.get())
                fft_range = float(self.fft_scale_div_var.get()) * 8.0
                if "uxr" in dso_type_val or "keysight" in dso_type_val:
                    applied["fft_axis"] = "gui-only"
                else:
                    ok1 = self._dso_write_ok(dso, f":FUNCtion1:VERTical:OFFSet {fft_offset:.12g}")
                    ok2 = self._dso_write_ok(dso, f":FUNCtion1:VERTical:RANGe {fft_range:.12g}")
                    if ok1 or ok2:
                        applied["fft_offset"] = fft_offset
                        applied["fft_range"] = fft_range
            except Exception:
                pass

        if include_layout and ch_num and not ("uxr" in dso_type_val or "keysight" in dso_type_val):
            self._dso_write_ok(dso, ":DISPlay:WINDow2:STATE ON")
            self._dso_write_ok(dso, ":DISPlay:WINDow2:SOURce FUNCtion1")

        return applied

    def _on_apply_dso_settings(self) -> None:
        """Apply Ch Scale, FFT Offset/Scale, Data Length to the DSO without full reset."""
        def worker():
            try:
                self.parent.after(0, lambda: self.conn_status_var.set("Applying..."))
                host = self.host_var.get().strip()
                timeout_ms = int(_parse_float_input(self.timeout_var.get(), "Timeout"))
                with create_dso_controller(
                    dso_type=normalize_dso_type(self.dso_type_var.get()),
                    host=host, timeout_ms=timeout_ms
                ) as dso:
                    self._drain_dso_errors(dso)
                    applied = self._apply_dso_gui_settings_to_controller(
                        dso,
                        include_layout=False,
                        touch_display=False,
                        touch_scale=True,
                        touch_timebase=False,
                        touch_trigger=False,
                        touch_fft_axis=False,
                    )
                    self._log(f"[Apply] GUI DSO settings applied: {applied}")
                    scpi_errors = self._drain_dso_errors(dso)
                    if scpi_errors:
                        self._log(f"[Apply] DSO SCPI errors: {' | '.join(scpi_errors)}")
                self._log("[Apply] DSO settings applied.")
                self.parent.after(0, lambda: self.conn_status_var.set("Settings Applied"))
            except Exception as e:
                self._log(f"[Apply] Failed: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Apply Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _on_test_connection(self) -> None:
        def worker():
            try:
                self.parent.after(0, lambda: self.conn_status_var.set("Checking..."))
                host = self.host_var.get().strip()
                timeout_ms = int(_parse_float_input(self.timeout_var.get(), "Timeout"))
                with create_dso_controller(
                    dso_type=normalize_dso_type(self.dso_type_var.get()),
                    host=host, timeout_ms=timeout_ms
                ) as dso:
                    idn = dso.query("*IDN?")

                    try:
                        dso.write("*RST")
                        import time; time.sleep(1.0)

                        applied = self._apply_dso_gui_settings_to_controller(
                            dso,
                            include_layout=True,
                            touch_display=True,
                            touch_scale=True,
                            touch_timebase=True,
                            touch_trigger=True,
                            touch_fft_axis=True,
                        )
                        self._log(f"[Conn] GUI settings applied: {applied}")
                        scpi_errors = self._drain_dso_errors(dso)
                        if scpi_errors:
                            self._log(f"[Conn] DSO SCPI errors: {' | '.join(scpi_errors)}")
                        self._log("[Conn] DSO hardware initialized and synced.")
                    except Exception as ex:
                        self._log(f"[Conn] Warning: could not set all DSO params ({ex})")

                self._log(f"[Conn] OK: {idn}")
                self.parent.after(0, lambda: self.conn_status_var.set("Connected"))
            except Exception as e:
                self._log(f"[Conn] Failed: {e}")
                self.parent.after(0, lambda: self.conn_status_var.set("Failed"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_dso_single(self) -> None:
        def worker():
            try:
                self.parent.after(0, lambda: self.conn_status_var.set("Sending Single..."))
                host = self.host_var.get().strip()
                timeout_ms = int(_parse_float_input(self.timeout_var.get(), "Timeout"))
                dso_type_val = self.dso_type_var.get().lower()
                with create_dso_controller(
                    dso_type=normalize_dso_type(dso_type_val),
                    host=host, timeout_ms=timeout_ms
                ) as dso:
                    if "uxr" in dso_type_val or "keysight" in dso_type_val:
                        dso.write(":SINGle")
                    else:
                        dso.write("TRMD SINGLE")
                self._log("[Single] Sent Single Trigger command.")
                self.parent.after(0, lambda: self.conn_status_var.set("Single Triggered"))
            except Exception as e:
                self._log(f"[Single] Failed: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Single Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _on_capture_live(self) -> None:
        def worker():
            try:
                live = bool(self.live_var.get())
                if live:
                    host = self.host_var.get().strip()
                    timeout_ms = int(_parse_float_input(self.timeout_var.get(), "Timeout"))
                    channels = self._selected_dso_channels()
                    capture_channels = list(channels)
                    if len(channels) > 2:
                        self._log("[Acq] More than two channels selected; capturing all, dashboard shows first two.")
                    primary_ch = channels[0]
                    self.ch_var.set(primary_ch)
                    process_fs = self._requested_process_fs()
                    dso_fs_req = self._requested_dso_sample_rate_hz(resolve_auto=True)
                    if process_fs is not None:
                        fallback_fs = process_fs
                    elif dso_fs_req is not None:
                        fallback_fs = dso_fs_req
                    else:
                        fallback_fs = 64e9 if "keysight" in normalize_dso_type(self.dso_type_var.get()) else 40e9
                    max_samples = self._max_capture_samples()
                    self._log_capture_sample_plan(fallback_fs, max_samples)
                    self._log(f"[Acq] Connecting {host} channels={','.join(capture_channels)}...")
                    captured: dict[str, dict[str, np.ndarray | float]] = {}
                    with create_dso_controller(
                        dso_type=normalize_dso_type(self.dso_type_var.get()),
                        host=host, timeout_ms=timeout_ms
                    ) as dso:
                        self._drain_dso_errors(dso)
                        applied = self._apply_dso_gui_settings_to_controller(
                            dso,
                            include_layout=False,
                            touch_display=False,
                            touch_scale=False,
                            touch_timebase=False,
                            touch_trigger=False,
                            touch_fft_axis=False,
                        )
                        self._log(f"[Acq] GUI DSO settings applied: {applied}")

                        scpi_errors = self._drain_dso_errors(dso)
                        if scpi_errors:
                            self._log(f"[Acq] DSO SCPI errors: {' | '.join(scpi_errors)}")

                        for ch in capture_channels:
                            t_rx, rx_sig, fs_dso = dso.capture(
                                channel=ch,
                                fallback_fs=fallback_fs,
                                max_samples=max_samples,
                            )
                            fs_native = float(fs_dso)
                            self._warn_dso_sample_rate_mismatch(ch, fs_native)
                            rx_sig = np.asarray(rx_sig, dtype=np.float64)
                            if process_fs is not None and not np.isclose(fs_native, process_fs):
                                rx_sig = self._resample_real(rx_sig, fs_native, process_fs)
                                fs_dso = process_fs
                                t_rx = np.arange(len(rx_sig), dtype=np.float64) / fs_dso
                                self._log(
                                    f"[Acq] {ch} resampled: "
                                    f"{fs_native/1e9:.3f} -> {fs_dso/1e9:.3f} GSa/s"
                                )
                            if max_samples is not None and len(rx_sig) > max_samples:
                                rx_sig = rx_sig[:max_samples]
                                t_rx = (
                                    np.asarray(t_rx)[:max_samples]
                                    if len(t_rx) >= max_samples
                                    else np.arange(max_samples, dtype=np.float64) / float(fs_dso)
                                )
                                self._log(f"[Acq] {ch} truncated to {max_samples:,} samples")
                            captured[ch] = {
                                "sig": np.asarray(rx_sig, dtype=np.float64),
                                "t": np.asarray(t_rx, dtype=np.float64),
                                "fs": float(fs_dso),
                            }
                            try:
                                pl_rate = self._load_tx_payload_for_isac()
                                fs_ref_rate = float((pl_rate or {}).get("fs", 0.0))
                                rate_note = f", fs_rx/fs_ref={float(fs_dso)/fs_ref_rate:.6f}" if fs_ref_rate > 0 else ""
                            except Exception:
                                rate_note = ""
                            self._log(f"[Acq] {ch}: N={len(rx_sig):,}, fs={float(fs_dso)/1e9:.3f} GSa/s{rate_note}")

                    self._rx_multi = captured
                    self._set_primary_rx_channel(primary_ch)
                    self.runtime["latest_rx_signal"] = self._rx_sig
                    self.runtime["latest_t"]         = self._rx_t
                    self.runtime["latest_fs"]        = self._rx_fs
                    self.runtime["latest_rx_by_channel"] = self._rx_multi
                    self.runtime.pop("latest_capture_file", None)
                    self.runtime.pop("loaded_capture_dsp_state", None)
                    self._last_loaded_capture_path = None
                    self._const_drawn = False
                    self._log(f"[Acq] Done: channels={','.join(captured.keys())}")
                    self.parent.after(
                        0,
                        lambda: self.capture_file_var.set(
                            f"Capture: live acquire {datetime.now().strftime('%H:%M:%S')} (unsaved)"
                        ),
                    )
                else:
                    multi = self.runtime.get("latest_rx_by_channel")
                    sig = self.runtime.get("latest_rx_signal")
                    if multi:
                        self._rx_multi = dict(multi)
                        primary_ch = self._selected_dso_channels()[0]
                        if primary_ch not in self._rx_multi:
                            primary_ch = next(iter(self._rx_multi.keys()))
                        self._set_primary_rx_channel(primary_ch)
                    elif sig is not None:
                        self._rx_sig = np.asarray(sig, dtype=np.float64)
                        self._rx_t   = self.runtime.get("latest_t")
                        self._rx_fs  = float(self.runtime.get("latest_fs", 40e9))
                        self._rx_multi = {
                            self.ch_var.get().strip().upper(): {
                                "sig": self._rx_sig,
                                "t": self._rx_t if self._rx_t is not None else np.arange(len(self._rx_sig), dtype=np.float64) / self._rx_fs,
                                "fs": self._rx_fs,
                            }
                        }
                    else:
                        self.parent.after(0, lambda: messagebox.showwarning("No data", "No capture in memory. Enable Live DSO."))
                        return
                    process_fs = self._requested_process_fs()
                    max_samples = self._max_capture_samples()
                    for ch, item in list(self._rx_multi.items()):
                        sig_i = np.asarray(item["sig"], dtype=np.float64)
                        fs_i = float(item["fs"])
                        t_i = np.asarray(item["t"], dtype=np.float64)
                        if process_fs is not None and not np.isclose(fs_i, process_fs):
                            sig_i = self._resample_real(sig_i, fs_i, process_fs)
                            fs_i = process_fs
                            t_i = np.arange(len(sig_i), dtype=np.float64) / fs_i
                        if max_samples is not None and len(sig_i) > max_samples:
                            sig_i = sig_i[:max_samples]
                            t_i = t_i[:max_samples] if len(t_i) >= max_samples else np.arange(max_samples, dtype=np.float64) / fs_i
                        self._rx_multi[ch] = {"sig": sig_i, "t": t_i, "fs": fs_i}
                    primary_mem = self._selected_dso_channels()[0]
                    if primary_mem not in self._rx_multi:
                        primary_mem = next(iter(self._rx_multi.keys()))
                    self._set_primary_rx_channel(primary_mem)
                    self._const_drawn = False
                    self._log(f"[Acq] Loaded from memory: channels={','.join(self._rx_multi.keys())}")
                    self.parent.after(0, lambda: self.capture_file_var.set("Capture: memory (unsaved)"))
                self.parent.after(0, self._plot_spectrum_and_time)
                self.parent.after(0, self._refresh_metrics_table)
            except Exception as e:
                self._log(f"[Acq] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Acquire Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _capture_live_once_sync(self) -> dict[str, dict[str, np.ndarray | float]]:
        """Capture selected DSO channels once without changing the DSO layout."""
        host = self.host_var.get().strip()
        timeout_ms = int(_parse_float_input(self.timeout_var.get(), "Timeout"))
        channels = self._selected_dso_channels()
        capture_channels = list(channels)
        primary_ch = channels[0]
        self.ch_var.set(primary_ch)

        process_fs = self._requested_process_fs()
        dso_fs_req = self._requested_dso_sample_rate_hz(resolve_auto=True)
        if process_fs is not None:
            fallback_fs = process_fs
        elif dso_fs_req is not None:
            fallback_fs = dso_fs_req
        else:
            fallback_fs = 64e9 if "keysight" in normalize_dso_type(self.dso_type_var.get()) else 40e9
        max_samples = self._max_capture_samples()
        self._log_capture_sample_plan(fallback_fs, max_samples)
        captured: dict[str, dict[str, np.ndarray | float]] = {}

        with create_dso_controller(
            dso_type=normalize_dso_type(self.dso_type_var.get()),
            host=host,
            timeout_ms=timeout_ms,
        ) as dso:
            self._drain_dso_errors(dso)
            applied = self._apply_dso_gui_settings_to_controller(
                dso,
                include_layout=False,
                touch_display=False,
                touch_scale=False,
                touch_timebase=False,
                touch_trigger=False,
                touch_fft_axis=False,
            )
            self._log(f"[Acq] GUI DSO settings applied: {applied}")
            scpi_errors = self._drain_dso_errors(dso)
            if scpi_errors:
                self._log(f"[Acq] DSO SCPI errors: {' | '.join(scpi_errors)}")

            for ch in capture_channels:
                t_rx, rx_sig, fs_dso = dso.capture(
                    channel=ch,
                    fallback_fs=fallback_fs,
                    max_samples=max_samples,
                )
                fs_native = float(fs_dso)
                self._warn_dso_sample_rate_mismatch(ch, fs_native)
                rx_sig = np.asarray(rx_sig, dtype=np.float64)
                if process_fs is not None and not np.isclose(fs_native, process_fs):
                    rx_sig = self._resample_real(rx_sig, fs_native, process_fs)
                    fs_dso = process_fs
                    t_rx = np.arange(len(rx_sig), dtype=np.float64) / fs_dso
                if max_samples is not None and len(rx_sig) > max_samples:
                    rx_sig = rx_sig[:max_samples]
                    t_rx = (
                        np.asarray(t_rx)[:max_samples]
                        if len(t_rx) >= max_samples
                        else np.arange(max_samples, dtype=np.float64) / float(fs_dso)
                    )
                captured[ch] = {
                    "sig": np.asarray(rx_sig, dtype=np.float64),
                    "t": np.asarray(t_rx, dtype=np.float64),
                    "fs": float(fs_dso),
                }
                try:
                    pl_rate = self._load_tx_payload_for_isac()
                    fs_ref_rate = float((pl_rate or {}).get("fs", 0.0))
                    rate_note = (
                        f", fs_rx/fs_ref={float(fs_dso)/fs_ref_rate:.6f}"
                        if fs_ref_rate > 0 else ""
                    )
                except Exception:
                    rate_note = ""
                self._log(
                    f"[Acq] {ch}: N={len(rx_sig):,}, "
                    f"fs={float(fs_dso)/1e9:.3f} GSa/s{rate_note}"
                )

        self._rx_multi = captured
        self._set_primary_rx_channel(primary_ch)
        self.runtime["latest_rx_signal"] = self._rx_sig
        self.runtime["latest_t"] = self._rx_t
        self.runtime["latest_fs"] = self._rx_fs
        self.runtime["latest_rx_by_channel"] = self._rx_multi
        self.runtime.pop("latest_capture_file", None)
        self.runtime.pop("loaded_capture_dsp_state", None)
        self._last_loaded_capture_path = None
        self._const_drawn = False
        return captured

    def _snapshot_capture_state(self) -> dict:
        rx_multi = {}
        for ch, item in (self._rx_multi or {}).items():
            rx_multi[ch] = {
                "sig": np.asarray(item["sig"], dtype=np.float64).copy(),
                "t": np.asarray(item["t"], dtype=np.float64).copy(),
                "fs": float(item["fs"]),
            }
        return {
            "rx_multi": rx_multi,
            "primary_ch": self.ch_var.get().strip().upper(),
            "metrics": copy.deepcopy(self._metrics),
            "rx_sig": None if self._rx_sig is None else np.asarray(self._rx_sig, dtype=np.float64).copy(),
            "rx_t": None if self._rx_t is None else np.asarray(self._rx_t, dtype=np.float64).copy(),
            "rx_fs": float(self._rx_fs) if self._rx_fs is not None else float("nan"),
        }

    def _restore_capture_state(self, snap: dict) -> None:
        self._rx_multi = copy.deepcopy(snap.get("rx_multi", {}))
        primary = str(snap.get("primary_ch", "")).strip().upper()
        if primary in self._rx_multi:
            self._set_primary_rx_channel(primary)
        else:
            self._rx_sig = snap.get("rx_sig")
            self._rx_t = snap.get("rx_t")
            self._rx_fs = float(snap.get("rx_fs", float("nan")))
        self._metrics = copy.deepcopy(snap.get("metrics", {}))
        self.runtime["latest_rx_signal"] = self._rx_sig
        self.runtime["latest_t"] = self._rx_t
        self.runtime["latest_fs"] = self._rx_fs
        self.runtime["latest_rx_by_channel"] = self._rx_multi
        self._const_drawn = False

    def _compose_best_comm_range_state(
        self,
        comm_snap: dict,
        comm_ch: str,
        range_snap: dict,
        range_ch: str,
    ) -> None:
        """Build a final GUI capture from independently selected channels.

        Power fading means the best communication capture and the best
        monostatic range capture often do not occur on the same trigger.  The
        GUI/save path can still represent the intended experiment by keeping
        CH1 from the best-EVM run and CH2 from the best-range run.
        """
        comm_ch = str(comm_ch).strip().upper()
        range_ch = str(range_ch).strip().upper()
        comm_multi = copy.deepcopy(comm_snap.get("rx_multi", {}))
        range_multi = copy.deepcopy(range_snap.get("rx_multi", {}))
        merged: dict[str, dict[str, np.ndarray | float]] = {}

        if comm_ch in comm_multi:
            merged[comm_ch] = comm_multi[comm_ch]
        elif comm_snap.get("rx_sig") is not None:
            fs = float(comm_snap.get("rx_fs", float("nan")))
            sig = np.asarray(comm_snap["rx_sig"], dtype=np.float64)
            t = comm_snap.get("rx_t")
            merged[comm_ch] = {
                "sig": sig,
                "t": np.asarray(t, dtype=np.float64) if t is not None else np.arange(len(sig), dtype=np.float64) / fs,
                "fs": fs,
            }

        if range_ch in range_multi:
            merged[range_ch] = range_multi[range_ch]
        elif range_snap.get("rx_sig") is not None:
            fs = float(range_snap.get("rx_fs", float("nan")))
            sig = np.asarray(range_snap["rx_sig"], dtype=np.float64)
            t = range_snap.get("rx_t")
            merged[range_ch] = {
                "sig": sig,
                "t": np.asarray(t, dtype=np.float64) if t is not None else np.arange(len(sig), dtype=np.float64) / fs,
                "fs": fs,
            }

        if not merged:
            raise ValueError("Could not compose best communication/range capture.")

        self._rx_multi = merged
        if comm_ch in self._rx_multi:
            self._set_primary_rx_channel(comm_ch)
        else:
            self._set_primary_rx_channel(next(iter(self._rx_multi.keys())))
        self._metrics = copy.deepcopy(comm_snap.get("metrics", {}))
        self.runtime["latest_rx_signal"] = self._rx_sig
        self.runtime["latest_t"] = self._rx_t
        self.runtime["latest_fs"] = self._rx_fs
        self.runtime["latest_rx_by_channel"] = self._rx_multi
        self.runtime.pop("latest_capture_file", None)
        self.runtime.pop("loaded_capture_dsp_state", None)
        self._last_loaded_capture_path = None
        self._const_drawn = False

    def _measure_band_for_signal(self, sig: np.ndarray, fs: float) -> dict[str, float]:
        f1_ghz, f2_ghz = self._get_signal_band_ghz()
        if f1_ghz >= f2_ghz:
            raise ValueError("Invalid band: check Carrier Freq and Symbol Rate.")
        f_hz, psd_db = self._compute_psd_db(np.asarray(sig, dtype=np.float64), float(fs))
        f_ghz = f_hz / 1e9
        psd_lin = 10.0 ** (psd_db / 10.0)
        mask_sig = (f_ghz >= f1_ghz) & (f_ghz <= f2_ghz)
        if not np.any(mask_sig):
            raise ValueError(f"Band [{f1_ghz:.2f}-{f2_ghz:.2f} GHz] outside signal bandwidth.")
        df = float(f_hz[1] - f_hz[0]) if len(f_hz) > 1 else 1.0
        p_sig_mw = float(np.sum(psd_lin[mask_sig])) * df
        mask_noise = (~mask_sig) & (f_ghz > 0.5) & (f_ghz <= self._scope_bw_ghz())
        if self._noise_floor_ref_dbmhz is not None:
            nf_mwhz = 10.0 ** (self._noise_floor_ref_dbmhz / 10.0)
        elif np.any(mask_noise):
            nf_mwhz = float(np.median(psd_lin[mask_noise]))
        else:
            nf_mwhz = 1e-30
        bw_sig_hz = max(1.0, (f2_ghz - f1_ghz) * 1e9)
        p_noise_mw = nf_mwhz * bw_sig_hz
        p_true_mw = max(p_sig_mw - p_noise_mw, 1e-30)
        return {
            "band_power_dbm": 10.0 * np.log10(p_true_mw),
            "raw_power_dbm": 10.0 * np.log10(max(p_sig_mw, 1e-30)),
            "noise_floor_dbmhz": 10.0 * np.log10(max(nf_mwhz, 1e-30)),
            "noise_density_dbmhz": 10.0 * np.log10(max(nf_mwhz, 1e-30)),
            "noise_power_dbm": 10.0 * np.log10(max(p_noise_mw, 1e-30)),
            "snr_db": 10.0 * np.log10(max(p_true_mw / max(p_noise_mw, 1e-30), 1e-30)),
            "band_power_mw": p_true_mw,
            "noise_power_mw": p_noise_mw,
            "analysis_bw_hz": bw_sig_hz,
        }

    def _update_band_metrics_for_channels(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for row, ch in enumerate(self._display_dso_channels()):
            item = self._rx_multi.get(ch)
            if not item:
                continue
            vals = self._measure_band_for_signal(np.asarray(item["sig"]), float(item["fs"]))
            out[ch] = vals
            suffix = "" if row == 0 else f" {ch}"
            key_suffix = "" if row == 0 else f"_{ch.lower()}"
            self._set_metric(f"band_power_dbm{key_suffix}", f"Band Power{suffix}", vals["band_power_dbm"], "dBm")
            self._set_metric(f"noise_power_dbm{key_suffix}", f"Noise Power{suffix}", vals["noise_power_dbm"], "dBm")
            self._set_metric(f"snr_com_db{key_suffix}", f"Band SNR{suffix}", vals["snr_db"], "dB")
            self._set_metric(f"noise_floor_dbmhz{key_suffix}", f"Noise Density{suffix}", vals["noise_floor_dbmhz"], "dBm/Hz")
            if row == 0:
                self.band_pwr_var.set(f"Band Power:  {vals['band_power_dbm']:.2f} dBm")
                self.noise_floor_var.set(
                    f"Noise Density: {vals['noise_floor_dbmhz']:.1f} dBm/Hz; "
                    f"Noise Power: {vals['noise_power_dbm']:.2f} dBm"
                )
                self.snr_var.set(f"Band SNR:    {vals['snr_db']:.2f} dB")
            if row == 1:
                self._set_metric(
                    "radar_pre_snr_db_c2",
                    "C2 Sensing pre-DSP SNR",
                    vals["snr_db"],
                    "dB",
                    f"C2 in-band SNR before range processing, from monostatic channel {ch}.",
                )
        return out

    def _clear_demod_metrics(self) -> None:
        for key in ("evm_db", "evm_pct", "ber", "symbols"):
            self._metrics.pop(key, None)

    def _clear_range_metrics(self) -> None:
        for key in list(self._metrics.keys()):
            if key.startswith("range_peak_m") or key.startswith("range_peak_mm") or key.startswith("pslr_db") or key.startswith("diff_range_mm") or key.startswith("range_difference_mm") or key.startswith("cfr_"):
                self._metrics.pop(key, None)
            elif key.startswith("self_interference_peak_m") or key.startswith("zero_guard_m") or key.startswith("diff_cfr_coherence"):
                self._metrics.pop(key, None)
            elif key == "snr_rad_db" or key.startswith("snr_rad_post_db") or key.startswith("radar_processing_gain_db") or key.startswith("snr_rad_pg_corrected_db"):
                self._metrics.pop(key, None)

    def _wait_for_metric(self, key: str, timeout_s: float = 30.0) -> float:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            val = self._metric_float(key)
            if np.isfinite(val):
                return val
            time.sleep(0.2)
        return float("nan")

    def _compute_range_items_for_current_capture(self, pl: dict) -> list[dict]:
        """Compute range profiles for the currently displayed capture channels."""
        range_items: list[dict] = []
        display_channels = self._display_dso_channels()
        if self._rx_multi:
            for row, ch in enumerate(display_channels[:2]):
                item = self._rx_multi.get(ch)
                if not item:
                    continue
                range_row = self._range_row_for_channel(ch, row)
                range_items.append(self._compute_isac_range_profile_for_signal(
                    np.asarray(item["sig"], dtype=np.float64),
                    float(item["fs"]),
                    pl,
                    ch_label=ch,
                    row=range_row,
                ))
        if not range_items and self._rx_sig is not None:
            ch_label = self.ch_var.get().strip().upper() or "C1"
            range_row = self._range_row_for_channel(ch_label, 0)
            range_items.append(self._compute_isac_range_profile_for_signal(
                np.asarray(self._rx_sig, dtype=np.float64),
                float(self._rx_fs),
                pl,
                ch_label=ch_label,
                row=range_row,
            ))
        return range_items

    def _compute_channel_response_for_signal(self, sig: np.ndarray, fs: float,
                                             pl: dict, ch_label: str = "",
                                             row: int = 0) -> dict:
        """Estimate the complex channel response used by the ISAC DSP path.

        The x-axis is reported as the original IF/RF-analysis frequency
        (fc + baseband offset) so the plotted CFR lines up with the spectrum
        panel and with the GUI's shaded measurement bandwidth.
        """
        self._assert_dsp_payload_consistent(pl, context="CFR")
        sig = np.asarray(sig, dtype=np.float64)
        rx_bb, fs_ref = self._rx_to_baseband(sig, float(fs), pl)
        rx_mat, tx_bb_mat, _, _, n_chirps, _, _, _, frame_start = \
            self._frame_sync_and_reshape(rx_bb, fs_ref, pl)
        ref_mat = self._dfts_ofdm_pilot_matrix(pl, n_chirps)
        if ref_mat is None:
            ref_mat = tx_bb_mat

        freqs, h, w = self._estimate_lfm_cfr(rx_mat, ref_mat, fs_ref)
        fc_ghz = float(self.fc_var.get())
        f1_ghz, f2_ghz = self._get_signal_band_ghz()
        rf_ghz = fc_ghz + freqs / 1e9
        finite = (
            np.isfinite(rf_ghz) &
            np.isfinite(h.real) &
            np.isfinite(h.imag) &
            (np.abs(h) > 1e-15)
        )
        in_band = finite & (rf_ghz >= f1_ghz) & (rf_ghz <= f2_ghz)
        if np.count_nonzero(in_band) < 16:
            in_band = finite

        mag = np.abs(h)
        mag_ref = float(np.nanmedian(mag[in_band])) if np.any(in_band) else float(np.nanmax(mag) if len(mag) else 1.0)
        if not np.isfinite(mag_ref) or mag_ref <= 0:
            mag_ref = 1.0
        mag_db = 20.0 * np.log10(np.maximum(mag, 1e-15) / mag_ref)

        phase_resid = np.full_like(rf_ghz, np.nan, dtype=np.float64)
        group_delay_s = float("nan")
        group_range_m = float("nan")
        phase_fit_ok = False
        if np.count_nonzero(in_band) >= 16:
            f_fit = freqs[in_band].astype(np.float64)
            ph = np.unwrap(np.angle(h[in_band]))
            ww = np.asarray(w, dtype=np.float64).reshape(-1)
            if len(ww) == len(freqs):
                ww = ww[in_band]
                ww = np.maximum(ww, 0.0)
            else:
                ww = np.ones_like(f_fit)
            if not np.any(ww > 0):
                ww = np.ones_like(f_fit)
            ww = ww / (np.max(ww) + 1e-15)
            ww = np.where(ww >= 0.03, ww, 0.0)
            if np.count_nonzero(ww > 0) >= 16:
                f_mean = float(np.sum(ww * f_fit) / (np.sum(ww) + 1e-15))
                p_mean = float(np.sum(ww * ph) / (np.sum(ww) + 1e-15))
                f0 = f_fit - f_mean
                p0 = ph - p_mean
                slope = float(np.sum(ww * f0 * p0) / (np.sum(ww * f0 * f0) + 1e-15))
                group_delay_s = -slope / (2.0 * np.pi)
                group_range_m = group_delay_s * self._range_delay_scale_m_per_s(row=row)
                phase_fit = slope * (f_fit - f_mean) + p_mean
                phase_resid[in_band] = ph - phase_fit
                phase_fit_ok = True

        usable_bw_ghz = float("nan")
        ripple_db = float("nan")
        band_coverage = float("nan")
        if np.count_nonzero(in_band) >= 2:
            rf_band = rf_ghz[in_band]
            usable_bw_ghz = float(np.nanmax(rf_band) - np.nanmin(rf_band))
            requested_bw_ghz = max(1e-12, float(f2_ghz - f1_ghz))
            band_coverage = float(np.clip(usable_bw_ghz / requested_bw_ghz, 0.0, 1.5))
            vals = mag_db[in_band]
            ripple_db = float(np.nanpercentile(vals, 95) - np.nanpercentile(vals, 5))

        ch_key = str(ch_label or "").strip().upper()
        zero_info = self._range_zero_info_for_channel(ch_key)
        ref_cfr = (
            zero_info.get("cfr")
            if isinstance(zero_info, dict) and zero_info.get("cfr") is not None
            else self.runtime.get("lfm_range_zero_cfr")
        )
        diff_tau_s = float("nan")
        diff_range_m = float("nan")
        diff_coherence = float("nan")
        if ref_cfr and len(freqs) >= 16:
            try:
                freqs_ref = np.asarray(ref_cfr.get("freqs", []), dtype=np.float64)
                h_ref = np.asarray(ref_cfr.get("h", []), dtype=np.complex128)
                if len(freqs_ref) >= 16 and len(h_ref) == len(freqs_ref):
                    h_ref_i = (
                        np.interp(freqs, freqs_ref, h_ref.real)
                        + 1j * np.interp(freqs, freqs_ref, h_ref.imag)
                    )
                    diff_tau_s, diff_coherence = self._differential_delay_from_cfr(
                        freqs, h, h_ref_i, weight=w
                    )
                    if np.isfinite(diff_tau_s):
                        diff_range_m = diff_tau_s * self._range_delay_scale_m_per_s(row=row)
            except Exception as exc:
                self._log(f"[CFR {ch_label}] differential CFR skipped: {exc}")

        return {
            "ch": ch_label,
            "row": int(row),
            "rf_ghz": rf_ghz,
            "freqs_hz": freqs,
            "h": h,
            "weight": w,
            "mag_db": mag_db,
            "phase_resid_rad": phase_resid,
            "in_band": in_band,
            "f1_ghz": float(f1_ghz),
            "f2_ghz": float(f2_ghz),
            "usable_bw_ghz": usable_bw_ghz,
            "band_coverage": band_coverage,
            "ripple_db": ripple_db,
            "group_delay_s": group_delay_s,
            "group_range_m": group_range_m,
            "phase_fit_ok": bool(phase_fit_ok),
            "diff_tau_s": diff_tau_s,
            "diff_range_m": diff_range_m,
            "diff_coherence": diff_coherence,
            "frame_start": int(frame_start),
            "fs_ref": float(fs_ref),
        }

    def _compute_channel_response_items_for_current_capture(self, pl: dict) -> list[dict]:
        items: list[dict] = []
        display_channels = self._display_dso_channels()
        if self._rx_multi:
            for row, ch in enumerate(display_channels[:2]):
                item = self._rx_multi.get(ch)
                if not item:
                    continue
                items.append(self._compute_channel_response_for_signal(
                    np.asarray(item["sig"], dtype=np.float64),
                    float(item["fs"]),
                    pl,
                    ch_label=ch,
                    row=row,
                ))
        if not items and self._rx_sig is not None:
            ch_label = self.ch_var.get().strip().upper() or "C1"
            items.append(self._compute_channel_response_for_signal(
                np.asarray(self._rx_sig, dtype=np.float64),
                float(self._rx_fs),
                pl,
                ch_label=ch_label,
                row=0,
            ))
        return items

    def _on_show_channel_response(self) -> None:
        if self._rx_sig is None and not self._rx_multi:
            messagebox.showwarning("No data", "Acquire or load a capture first.")
            return

        def worker():
            try:
                pl = self._load_tx_payload_for_isac()
                if pl is None:
                    raise ValueError("No TX reference found. Generate or download the TX signal first.")
                self._sync_dsp_params_from_payload(pl, source="Show H(f)", force=False)
                self._assert_dsp_payload_consistent(pl, context="Show H(f)")
                items = self._compute_channel_response_items_for_current_capture(pl)
                if not items:
                    raise ValueError("No selected channels have capture data for H(f).")
                self.parent.after(0, lambda it=items: self._show_channel_response_results(it))
            except Exception as e:
                self._log(f"[CFR] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Show H(f) Error", m))

        threading.Thread(target=worker, daemon=True).start()

    def _range_quality_summary(
        self,
        result: dict,
        target_m: float,
        target_window_m: float,
        min_quality_db: float = 20.0,
    ) -> dict[str, float | bool | str]:
        """Score whether a range profile finds the requested target cleanly."""
        rng = np.asarray(result.get("rng", []), dtype=np.float64).reshape(-1)
        prof_db = np.asarray(result.get("prof_db", []), dtype=np.float64).reshape(-1)
        out: dict[str, float | bool | str] = {
            "score": float("inf"),
            "range_m": float("nan"),
            "matched_filter_range_m": float("nan"),
            "range_err_m": float("nan"),
            "peak_sep_db": float("nan"),
            "peak_noise_db": float("nan"),
            "competitor_peak_db": float("nan"),
            "target_peak_db": float("nan"),
            "diff_coherence": float(result.get("diff_coherence", float("nan"))),
            "method": str(result.get("range_est_method", "matched-filter")),
            "ok": False,
            "ch": str(result.get("ch", "")).strip().upper(),
        }
        if len(rng) == 0 or len(prof_db) == 0:
            return out
        valid = np.isfinite(rng) & np.isfinite(prof_db)
        if np.count_nonzero(valid) < 8:
            return out

        rng_v = rng[valid]
        prof_v = prof_db[valid]
        main_idx = int(np.argmax(prof_v))
        main_range = float(rng_v[main_idx])
        main_peak_db = float(prof_v[main_idx])
        reported_range = float(result.get("display_range_m", main_range))
        if not np.isfinite(reported_range):
            reported_range = main_range
        if len(rng_v) > 2:
            dr_m = float(np.nanmedian(np.abs(np.diff(np.sort(rng_v)))))
        else:
            dr_m = float("nan")
        span_m = float(np.nanmax(rng_v) - np.nanmin(rng_v)) if len(rng_v) else float("nan")

        target_window_m = max(1e-6, float(target_window_m))
        target_mask = np.abs(rng_v - float(target_m)) <= target_window_m
        target_peak_db = float(np.max(prof_v[target_mask])) if np.any(target_mask) else float("-inf")

        comp_mask = np.ones(len(prof_v), dtype=bool)
        guard_bins = 4
        if np.isfinite(dr_m) and dr_m > 0:
            guard_bins = max(4, int(np.ceil(0.5 * target_window_m / dr_m)))
        comp_mask[max(0, main_idx - guard_bins):min(len(prof_v), main_idx + guard_bins + 1)] = False
        competitor_peak_db = float(np.max(prof_v[comp_mask])) if np.any(comp_mask) else float("-inf")

        noise_guard_m = max(2.0 * target_window_m, (8.0 * dr_m if np.isfinite(dr_m) else 0.0))
        if np.isfinite(span_m) and span_m > 0:
            noise_guard_m = min(max(noise_guard_m, 0.03 * span_m), 0.35 * span_m)
        noise_mask = np.abs(rng_v - main_range) > noise_guard_m
        if np.count_nonzero(noise_mask) < 8:
            noise_mask = comp_mask
        noise_floor_db = float(np.median(prof_v[noise_mask])) if np.any(noise_mask) else float(np.min(prof_v))

        peak_sep_db = main_peak_db - competitor_peak_db
        peak_noise_db = main_peak_db - noise_floor_db
        range_err_m = abs(reported_range - float(target_m))
        quality_weight_m = max(0.001, min(0.03, 0.10 * target_window_m))
        penalty_db = (
            max(0.0, float(min_quality_db) - peak_sep_db)
            + max(0.0, float(min_quality_db) - peak_noise_db)
        )
        score = range_err_m + quality_weight_m * penalty_db
        diff_coh = float(result.get("diff_coherence", float("nan")))
        if str(result.get("range_est_method", "")).lower().startswith("cfr"):
            score += quality_weight_m * max(0.0, 0.35 - (diff_coh if np.isfinite(diff_coh) else 0.0))
        if np.isfinite(target_peak_db):
            score += 0.01 * max(0.0, abs(target_peak_db - main_peak_db) - 1.0)

        out.update({
            "score": float(score),
            "range_m": reported_range,
            "matched_filter_range_m": main_range,
            "range_err_m": range_err_m,
            "peak_sep_db": float(peak_sep_db),
            "peak_noise_db": float(peak_noise_db),
            "competitor_peak_db": float(competitor_peak_db),
            "target_peak_db": float(target_peak_db),
            "diff_coherence": diff_coh,
            "method": str(result.get("range_est_method", "matched-filter")),
            "ok": bool(
                np.isfinite(range_err_m)
                and range_err_m <= target_window_m
                and peak_sep_db >= min_quality_db
                and peak_noise_db >= min_quality_db
            ),
        })
        return out

    def _best_range_summary(
        self,
        results: list[dict],
        target_m: float,
        target_window_m: float,
        min_quality_db: float = 20.0,
    ) -> dict[str, float | bool | str]:
        best: dict[str, float | bool | str] | None = None
        for item in results:
            summary = self._range_quality_summary(
                item,
                target_m=target_m,
                target_window_m=target_window_m,
                min_quality_db=min_quality_db,
            )
            score = float(summary.get("score", float("inf")))
            if best is None or score < float(best.get("score", float("inf"))):
                best = summary
        if best is None:
            return self._range_quality_summary({}, target_m, target_window_m, min_quality_db)
        return best

    def _range_difference_quality_summary(
        self,
        result: dict,
        target_diff_mm: float,
        target_tol_mm: float,
        min_quality_db: float = 12.0,
    ) -> dict[str, float | bool | str]:
        """Score range detection by reference-relative displacement in mm."""
        target_abs_m = float(result.get("target_range_m", float("nan")))
        window_m = max(abs(float(target_tol_mm)) * 1e-3, 1e-6)
        if not np.isfinite(target_abs_m):
            target_abs_m = float(result.get("display_range_m", result.get("est_range", float("nan"))))
        summary = self._range_quality_summary(
            result,
            target_m=target_abs_m,
            target_window_m=window_m,
            min_quality_db=min_quality_db,
        )
        measured_diff_mm = float(result.get("range_diff_mm", float("nan")))
        if not np.isfinite(measured_diff_mm):
            ref_center_m = float(result.get("zero_ref_center_m", float("nan")))
            range_m = float(summary.get("range_m", float("nan")))
            if np.isfinite(ref_center_m) and np.isfinite(range_m):
                measured_diff_mm = (range_m - ref_center_m) * 1e3
        diff_err_mm = abs(measured_diff_mm - float(target_diff_mm)) if np.isfinite(measured_diff_mm) else float("inf")
        pnr_db = float(summary.get("peak_noise_db", float("nan")))
        sep_db = float(summary.get("peak_sep_db", float("nan")))
        quality_penalty_mm = 0.05 * (
            max(0.0, float(min_quality_db) - (pnr_db if np.isfinite(pnr_db) else -120.0))
            + max(0.0, float(min_quality_db) - (sep_db if np.isfinite(sep_db) else -120.0))
        )
        score = diff_err_mm + quality_penalty_mm
        summary.update({
            "score": float(score),
            "range_diff_mm": measured_diff_mm,
            "range_diff_err_mm": diff_err_mm,
            "target_diff_mm": float(target_diff_mm),
            "target_tol_mm": float(target_tol_mm),
            "ok": bool(
                np.isfinite(diff_err_mm)
                and diff_err_mm <= max(abs(float(target_tol_mm)), 1e-6)
                and np.isfinite(pnr_db)
                and pnr_db >= min_quality_db
            ),
        })
        return summary

    def _best_range_target_window_m(self, row: int, tol_m: float) -> float:
        tol_m = abs(float(tol_m)) if np.isfinite(float(tol_m)) else 0.005
        try:
            f1_ghz, f2_ghz = self._get_signal_band_ghz()
            bw_hz = max(1.0, (f2_ghz - f1_ghz) * 1e9)
            res_m = self._range_delay_scale_m_per_s(row=row) / bw_hz
            if np.isfinite(res_m) and res_m > 0:
                return max(tol_m, 2.0 * res_m, 0.005)
        except Exception:
            pass
        return max(tol_m, 0.005)

    def _on_best_power_acquire(self) -> None:
        def worker():
            best_snap = None
            best_score = -np.inf
            best_desc = ""
            try:
                for idx in range(10):
                    self._log(f"[Best Power] Acquire {idx + 1}/10")
                    self._capture_live_once_sync()
                    vals = self._update_band_metrics_for_channels()
                    score = float(sum(v.get("band_power_mw", 0.0) for v in vals.values()))
                    desc = ", ".join(
                        f"{ch}={v['band_power_dbm']:.2f} dBm"
                        for ch, v in vals.items()
                        if np.isfinite(v.get("band_power_dbm", float("nan")))
                    )
                    self._log(f"[Best Power] {idx + 1}/10 score={10*np.log10(max(score,1e-30)):.2f} dBm  {desc}")
                    if score > best_score:
                        best_score = score
                        best_snap = self._snapshot_capture_state()
                        best_desc = desc
                if best_snap is None:
                    raise ValueError("No valid capture was acquired.")
                self._restore_capture_state(best_snap)
                self._update_band_metrics_for_channels()
                self._log(f"[Best Power] Selected best capture: {best_desc}")
                self.parent.after(0, lambda: self.capture_file_var.set("Capture: max-power best (unsaved)"))
                self.parent.after(0, self._plot_spectrum_and_time)
                self.parent.after(0, self._refresh_metrics_table)
            except Exception as e:
                self._log(f"[Best Power] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Best Power Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _power_fading_metrics_for_signal(self, sig: np.ndarray, fs: float) -> dict[str, float]:
        f1_ghz, f2_ghz = self._get_signal_band_ghz()
        if f1_ghz >= f2_ghz:
            raise ValueError("Invalid analysis band. Check IF/symbol-rate/roll-off.")
        f_hz, psd_db = self._compute_psd_db(np.asarray(sig, dtype=np.float64), float(fs))
        f_ghz = f_hz / 1e9
        psd_mw_hz = 10.0 ** (psd_db / 10.0)
        band = (f_ghz >= f1_ghz) & (f_ghz <= f2_ghz)
        if np.count_nonzero(band) < 3:
            raise ValueError(f"Band [{f1_ghz:.3f}, {f2_ghz:.3f}] GHz is outside captured spectrum.")
        fc_ghz = 0.5 * (f1_ghz + f2_ghz)
        lower = band & (f_ghz < fc_ghz)
        upper = band & (f_ghz >= fc_ghz)
        noise = (~band) & (f_ghz > 0.5) & (f_ghz <= self._scope_bw_ghz())
        df_hz = float(np.nanmedian(np.diff(f_hz))) if len(f_hz) > 1 else 1.0

        def integ(mask: np.ndarray) -> float:
            if not np.any(mask):
                return 1e-30
            return max(float(np.sum(psd_mw_hz[mask]) * df_hz), 1e-30)

        band_mw = integ(band)
        lower_mw = integ(lower)
        upper_mw = integ(upper)
        psd_band = psd_mw_hz[band]
        f_band = f_ghz[band]
        centroid_ghz = float(np.sum(f_band * psd_band) / (np.sum(psd_band) + 1e-30))
        peak_freq_ghz = float(f_band[int(np.argmax(psd_band))])
        noise_floor = float(np.median(psd_mw_hz[noise])) if np.any(noise) else float("nan")
        rms_v = float(np.sqrt(np.mean(np.asarray(sig, dtype=np.float64) ** 2)))
        return {
            "band_power_dbm": 10.0 * np.log10(band_mw),
            "lower_power_dbm": 10.0 * np.log10(lower_mw),
            "upper_power_dbm": 10.0 * np.log10(upper_mw),
            "centroid_ghz": centroid_ghz,
            "peak_freq_ghz": peak_freq_ghz,
            "noise_floor_dbmhz": 10.0 * np.log10(max(noise_floor, 1e-30)),
            "rms_dbv": 20.0 * np.log10(max(rms_v, 1e-15)),
        }

    def _summarize_power_fading_rows(self, rows: list[dict]) -> dict[str, dict[str, float | str]]:
        summary: dict[str, dict[str, float | str]] = {}
        channels = sorted({str(r.get("channel", "")) for r in rows if r.get("channel")})
        for ch in channels:
            cr = [r for r in rows if r.get("channel") == ch]
            p = np.asarray([r.get("band_power_dbm", np.nan) for r in cr], dtype=np.float64)
            c = np.asarray([r.get("centroid_ghz", np.nan) for r in cr], dtype=np.float64) * 1e3
            lower = np.asarray([r.get("lower_power_dbm", np.nan) for r in cr], dtype=np.float64)
            upper = np.asarray([r.get("upper_power_dbm", np.nan) for r in cr], dtype=np.float64)
            level_p2p = float(np.nanmax(p) - np.nanmin(p)) if len(p) else float("nan")
            centroid_p2p = float(np.nanmax(c) - np.nanmin(c)) if len(c) else float("nan")
            if np.count_nonzero(np.isfinite(p) & np.isfinite(c)) >= 3:
                corr_pc = float(np.corrcoef(p[np.isfinite(p) & np.isfinite(c)], c[np.isfinite(p) & np.isfinite(c)])[0, 1])
            else:
                corr_pc = float("nan")
            if np.count_nonzero(np.isfinite(lower) & np.isfinite(upper)) >= 3:
                m = np.isfinite(lower) & np.isfinite(upper)
                corr_lu = float(np.corrcoef(lower[m], upper[m])[0, 1])
            else:
                corr_lu = float("nan")
            verdict = "inconclusive"
            try:
                bw_mhz = max(1.0, (self._get_signal_band_ghz()[1] - self._get_signal_band_ghz()[0]) * 1e3)
                if level_p2p >= 3.0 and centroid_p2p <= max(50.0, 0.05 * bw_mhz):
                    verdict = "supports power fading"
                elif centroid_p2p > 0.15 * bw_mhz and abs(corr_pc) > 0.5:
                    verdict = "frequency wandering likely contributes"
            except Exception:
                pass
            summary[ch] = {
                "level_p2p_db": level_p2p,
                "centroid_p2p_mhz": centroid_p2p,
                "power_centroid_corr": corr_pc,
                "lower_upper_corr": corr_lu,
                "verdict": verdict,
            }
        return summary

    def _save_power_fading_probe_artifacts(
        self,
        rows: list[dict],
        summary: dict[str, dict[str, float | str]],
        png_path: Path | None = None,
    ) -> tuple[Path, Path]:
        out_dir = APP_DIR / "data" / "power_fading"
        out_dir.mkdir(parents=True, exist_ok=True)
        if png_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = out_dir / f"power_fading_gui_{stamp}.csv"
            png_path = out_dir / f"power_fading_gui_{stamp}.png"
        else:
            png_path = Path(png_path)
            if png_path.suffix.lower() != ".png":
                png_path = png_path.with_suffix(".png")
            png_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path = png_path.with_suffix(".csv")

        fieldnames = [
            "run", "channel", "time_iso", "fs_gs", "n_samples",
            "band_power_dbm", "lower_power_dbm", "upper_power_dbm",
            "centroid_ghz", "peak_freq_ghz", "noise_floor_dbmhz", "rms_dbv",
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=fieldnames)
            wr.writeheader()
            for row in rows:
                wr.writerow({k: row.get(k, "") for k in fieldnames})
            wr.writerow({})
            wr.writerow({
                "run": "summary",
                "channel": "channel",
                "time_iso": "verdict",
                "fs_gs": "level_p2p_db",
                "n_samples": "centroid_p2p_mhz",
                "band_power_dbm": "power_centroid_corr",
                "lower_power_dbm": "lower_upper_corr",
            })
            for ch, s in summary.items():
                wr.writerow({
                    "run": "summary",
                    "channel": ch,
                    "time_iso": s.get("verdict", ""),
                    "fs_gs": s.get("level_p2p_db", ""),
                    "n_samples": s.get("centroid_p2p_mhz", ""),
                    "band_power_dbm": s.get("power_centroid_corr", ""),
                    "lower_power_dbm": s.get("lower_upper_corr", ""),
                })

        fig = Figure(figsize=(11.0, 7.0), dpi=150)
        axs = fig.subplots(2, 2)
        channels = sorted(summary.keys())
        for ch in channels:
            cr = [r for r in rows if r.get("channel") == ch]
            x = np.asarray([r.get("run", 0) for r in cr], dtype=np.float64)
            p = np.asarray([r.get("band_power_dbm", np.nan) for r in cr], dtype=np.float64)
            c = np.asarray([r.get("centroid_ghz", np.nan) for r in cr], dtype=np.float64)
            lower = np.asarray([r.get("lower_power_dbm", np.nan) for r in cr], dtype=np.float64)
            upper = np.asarray([r.get("upper_power_dbm", np.nan) for r in cr], dtype=np.float64)
            c_off_mhz = (c - np.nanmedian(c)) * 1e3
            axs[0][0].plot(x, p, "o-", label=ch)
            axs[0][1].plot(x, c_off_mhz, "o-", label=ch)
            axs[1][0].plot(x, lower, "o--", label=f"{ch} lower")
            axs[1][0].plot(x, upper, "s-", label=f"{ch} upper")
            axs[1][1].scatter(c_off_mhz, p, s=22, label=ch)
        axs[0][0].set_title("Band Power vs Capture")
        axs[0][0].set_xlabel("Capture")
        axs[0][0].set_ylabel("dBm")
        axs[0][1].set_title("Spectral Centroid Motion")
        axs[0][1].set_xlabel("Capture")
        axs[0][1].set_ylabel("MHz from median")
        axs[1][0].set_title("Lower/Upper Half-band Power")
        axs[1][0].set_xlabel("Capture")
        axs[1][0].set_ylabel("dBm")
        axs[1][1].set_title("Power vs Centroid")
        axs[1][1].set_xlabel("Centroid offset (MHz)")
        axs[1][1].set_ylabel("Band power (dBm)")
        for ax in axs.reshape(-1):
            ax.grid(True, alpha=0.35)
            ax.legend(fontsize=7)
        verdict_txt = " | ".join(
            f"{ch}: {s['verdict']}, swing={float(s['level_p2p_db']):.2f} dB, "
            f"centroid={float(s['centroid_p2p_mhz']):.1f} MHz"
            for ch, s in summary.items()
        )
        fig.suptitle(verdict_txt[:180])
        fig.tight_layout()
        fig.savefig(png_path)
        return csv_path, png_path

    def _on_save_power_fading_result(self) -> None:
        rows = list(getattr(self, "_last_power_fading_rows", []))
        summary = dict(getattr(self, "_last_power_fading_summary", {}))
        if not rows or not summary:
            messagebox.showwarning(
                "No Power Fading Result",
                "Run 'Power Fade x30' first, then save the result."
            )
            return
        out_dir = APP_DIR / "data" / "power_fading"
        out_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"{self._artifact_default_stem('PF')}.png"
        path_str = filedialog.asksaveasfilename(
            title="Save Power Fading Result",
            initialdir=str(out_dir),
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG image + CSV data", "*.png"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            csv_path, png_path = self._save_power_fading_probe_artifacts(
                rows,
                summary,
                png_path=Path(path_str),
            )
            self._last_power_fading_paths = (csv_path, png_path)
            self.capture_file_var.set(f"Capture: power fading saved ({png_path.name})")
            self._log(f"[Power Fade] Saved CSV: {csv_path}")
            self._log(f"[Power Fade] Saved PNG: {png_path}")
        except Exception as e:
            self._log(f"[Power Fade] Save error: {e}")
            messagebox.showerror("Save Power Fading Error", str(e))

    def _show_power_fading_probe_results(self, rows: list[dict], summary: dict[str, dict[str, float | str]]) -> None:
        if not rows:
            return
        axes = getattr(self, "fd_axes", None)
        if axes is None:
            return
        for ax in (axes[0][2], axes[1][2], axes[0][3], axes[1][3]):
            ax.cla()
            ax.grid(True, alpha=0.35)
            ax.set_axis_on()
        channels = sorted(summary.keys())
        for ch in channels:
            cr = [r for r in rows if r.get("channel") == ch]
            x = np.asarray([r.get("run", 0) for r in cr], dtype=np.float64)
            p = np.asarray([r.get("band_power_dbm", np.nan) for r in cr], dtype=np.float64)
            c = np.asarray([r.get("centroid_ghz", np.nan) for r in cr], dtype=np.float64)
            lower = np.asarray([r.get("lower_power_dbm", np.nan) for r in cr], dtype=np.float64)
            upper = np.asarray([r.get("upper_power_dbm", np.nan) for r in cr], dtype=np.float64)
            c_off_mhz = (c - np.nanmedian(c)) * 1e3
            axes[0][2].plot(x, p, "o-", label=ch)
            axes[1][2].plot(x, c_off_mhz, "o-", label=ch)
            axes[0][3].plot(x, lower, "o--", label=f"{ch} lower")
            axes[0][3].plot(x, upper, "s-", label=f"{ch} upper")
            axes[1][3].scatter(c_off_mhz, p, s=24, label=ch)
        axes[0][2].set_title("Power Fading: Band Power")
        axes[0][2].set_xlabel("Capture")
        axes[0][2].set_ylabel("dBm")
        axes[1][2].set_title("Centroid Motion")
        axes[1][2].set_xlabel("Capture")
        axes[1][2].set_ylabel("MHz from median")
        axes[0][3].set_title("Lower/Upper Band Power")
        axes[0][3].set_xlabel("Capture")
        axes[0][3].set_ylabel("dBm")
        axes[1][3].set_title("Power vs Centroid")
        axes[1][3].set_xlabel("Centroid offset (MHz)")
        axes[1][3].set_ylabel("Band power (dBm)")
        for ax in (axes[0][2], axes[1][2], axes[0][3], axes[1][3]):
            ax.legend(fontsize=7)
        self._apply_dashboard_layout()
        self.canvas_plot.draw_idle()

    def _on_power_fading_probe(self) -> None:
        def worker():
            rows: list[dict] = []
            try:
                n_runs = 30
                channels = self._display_dso_channels()
                self._log(
                    f"[Power Fade] Starting {n_runs} live captures using GUI DSO settings "
                    f"on {','.join(channels)}."
                )
                for idx in range(n_runs):
                    run_no = idx + 1
                    self.parent.after(
                        0,
                        lambda n=run_no: self.capture_file_var.set(
                            f"Capture: Power Fade {n}/{n_runs} acquiring..."
                        ),
                    )
                    self._capture_live_once_sync()
                    self._update_band_metrics_for_channels()
                    self.parent.after(0, self._plot_spectrum_and_time)
                    now_iso = datetime.now().isoformat(timespec="seconds")
                    log_parts = []
                    for ch in channels:
                        item = self._rx_multi.get(ch)
                        if not item:
                            continue
                        vals = self._power_fading_metrics_for_signal(
                            np.asarray(item["sig"], dtype=np.float64),
                            float(item["fs"]),
                        )
                        row = {
                            "run": run_no,
                            "channel": ch,
                            "time_iso": now_iso,
                            "fs_gs": float(item["fs"]) / 1e9,
                            "n_samples": len(np.asarray(item["sig"])),
                            **vals,
                        }
                        rows.append(row)
                        log_parts.append(
                            f"{ch}: P={vals['band_power_dbm']:.2f} dBm, "
                            f"centroid={vals['centroid_ghz']:.6f} GHz"
                        )
                    self._log(f"[Power Fade] {run_no}/{n_runs}  " + " | ".join(log_parts))
                    self.parent.after(
                        0,
                        lambda n=run_no, txt=" | ".join(log_parts): self.capture_file_var.set(
                            f"Capture: Power Fade {n}/{n_runs}  {txt}"
                        ),
                    )
                if not rows:
                    raise ValueError("No valid power-fading rows were produced.")
                summary = self._summarize_power_fading_rows(rows)
                self._last_power_fading_rows = [dict(r) for r in rows]
                self._last_power_fading_summary = {ch: dict(s) for ch, s in summary.items()}
                csv_path, png_path = self._save_power_fading_probe_artifacts(rows, summary)
                self._last_power_fading_paths = (csv_path, png_path)
                for ch, s in summary.items():
                    self._log(
                        f"[Power Fade] {ch}: level_p2p={float(s['level_p2p_db']):.2f} dB, "
                        f"centroid_p2p={float(s['centroid_p2p_mhz']):.1f} MHz, "
                        f"P-centroid corr={float(s['power_centroid_corr']):.3f}, "
                        f"lower/upper corr={float(s['lower_upper_corr']):.3f}, "
                        f"verdict={s['verdict']}"
                    )
                self._log(f"[Power Fade] Saved CSV: {csv_path}")
                self._log(f"[Power Fade] Saved PNG: {png_path}")
                self.parent.after(0, lambda: self._show_power_fading_probe_results(rows, summary))
                self.parent.after(
                    0,
                    lambda p=png_path: self.capture_file_var.set(
                        f"Capture: power-fading done ({p.name})"
                    ),
                )
            except Exception as e:
                self._log(f"[Power Fade] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Power Fading Probe Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _on_best_evm_acquire(self) -> None:
        self._run_best_comm_range_acquire("Best EVM")

    def _on_best_range_acquire(self) -> None:
        self._run_best_range_only_acquire()

    def _run_best_range_only_acquire(self) -> None:
        def worker():
            best_snap = None
            best_result = None
            best_score = float("inf")
            best_desc = ""
            try:
                pl = self._load_tx_payload_for_isac()
                if pl is None:
                    raise ValueError("No TX reference found. Generate or download the TX signal first.")

                display_channels = self._display_dso_channels()
                range_ch = display_channels[1] if len(display_channels) > 1 else display_channels[0]
                range_row = 1 if len(display_channels) > 1 else 0
                target_diff_mm = self._range_diff_target_mm()
                tol_mm = self._range_diff_tolerance_mm()
                tol_m = tol_mm * 1e-3
                target_window_m = self._best_range_target_window_m(range_row, tol_m)
                min_quality_db = 12.0
                self._log(
                    f"[Best Range] Range-only search: channel={range_ch}, "
                    f"target dR={target_diff_mm:.2f} mm, window={target_window_m * 1e3:.2f} mm, "
                    f"min PNR={min_quality_db:.1f} dB."
                )

                for idx in range(10):
                    run_no = idx + 1
                    self._log(f"[Best Range] Acquire {run_no}/10")
                    self.parent.after(
                        0,
                        lambda n=run_no: self.capture_file_var.set(
                            f"Capture: Best Range {n}/10 acquiring..."
                        ),
                    )
                    self._capture_live_once_sync()
                    self._update_band_metrics_for_channels()
                    self._clear_range_metrics()
                    item = self._rx_multi.get(range_ch) if self._rx_multi else None
                    if item is None:
                        item = {"sig": self._rx_sig, "fs": self._rx_fs}
                    result = self._compute_isac_range_profile_for_signal(
                        np.asarray(item["sig"], dtype=np.float64),
                        float(item["fs"]),
                        pl,
                        ch_label=range_ch,
                        row=range_row,
                    )
                    summary = self._range_difference_quality_summary(
                        result,
                        target_diff_mm=target_diff_mm,
                        target_tol_mm=max(tol_mm, target_window_m * 1e3),
                        min_quality_db=min_quality_db,
                    )
                    score = float(summary.get("score", float("inf")))
                    est_range = float(summary.get("range_m", float("nan")))
                    mf_range = float(summary.get("matched_filter_range_m", float("nan")))
                    diff_mm = float(summary.get("range_diff_mm", float("nan")))
                    diff_err_mm = float(summary.get("range_diff_err_mm", float("nan")))
                    sep_db = float(summary.get("peak_sep_db", float("nan")))
                    pnr_db = float(summary.get("peak_noise_db", float("nan")))
                    method = str(summary.get("method", "N/A"))
                    self._log(
                        f"[Best Range] {run_no}/10 range={est_range:.4g} m "
                        f"(MF={mf_range:.4g} m) dR={diff_mm:.2f} mm "
                        f"target={target_diff_mm:.2f} mm err={diff_err_mm:.2f} mm "
                        f"PNR={pnr_db:.2f} dB sep={sep_db:.2f} dB "
                        f"method={method} score={score:.4g}"
                    )
                    self.parent.after(
                        0,
                        lambda n=run_no, r=est_range, d=diff_mm, p=pnr_db, s=sep_db: self.capture_file_var.set(
                            f"Capture: Best Range {n}/10  range={r:.4g} m  dR={d:.2f} mm  PNR={p:.2f} dB  sep={s:.2f} dB"
                        ),
                    )
                    self.parent.after(0, lambda item=result: self._show_isac_range_results([item]))

                    if np.isfinite(score) and score < best_score:
                        best_score = score
                        best_snap = self._snapshot_capture_state()
                        best_result = result
                        best_desc = (
                            f"{range_ch} range={est_range:.4g} m, "
                            f"dR={diff_mm:.2f} mm, err={diff_err_mm:.2f} mm, "
                            f"PNR={pnr_db:.2f} dB, sep={sep_db:.2f} dB, method={method}"
                        )
                        self._log(f"[Best Range] New best: {best_desc}")

                if best_snap is None or best_result is None:
                    raise ValueError("No valid range result was produced.")

                self._restore_capture_state(best_snap)
                self._update_band_metrics_for_channels()
                self._log(f"[Best Range] Selected best range capture: {best_desc}")
                self.parent.after(
                    0,
                    lambda d=best_desc: self.capture_file_var.set(
                        f"Capture: best-range selected  {d} (unsaved)"
                    ),
                )
                self.parent.after(0, self._plot_spectrum_and_time)
                display_channels = self._display_dso_channels()
                if display_channels and display_channels[0] in self._rx_multi:
                    self._set_primary_rx_channel(display_channels[0])
                self._clear_demod_metrics()
                self._on_demodulate(show_errors=False, run_async=False)
                self._wait_for_metric("evm_db", timeout_s=0.6)
                self.parent.after(0, lambda item=best_result: self._show_isac_range_results([item]))
                self.parent.after(0, self._refresh_metrics_table)
            except Exception as e:
                self._log(f"[Best Range] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Best Range Error", m))

        threading.Thread(target=worker, daemon=True).start()

    def _run_best_comm_range_acquire(self, label: str) -> None:
        def worker():
            best_comm_snap = None
            best_comm_evm_db = float("inf")
            best_comm_desc = ""
            best_range_snap = None
            best_range_score = float("inf")
            best_range_desc = ""
            try:
                pl = self._load_tx_payload_for_isac()
                if pl is None:
                    raise ValueError("No TX reference found. Generate or download the TX signal first.")

                display_channels = self._display_dso_channels()
                comm_ch = display_channels[0] if len(display_channels) > 0 else "C1"
                range_ch = display_channels[1] if len(display_channels) > 1 else comm_ch
                range_row = 1 if len(display_channels) > 1 else 0
                target_diff_mm = self._range_diff_target_mm()
                tol_mm = self._range_diff_tolerance_mm()
                tol_m = tol_mm * 1e-3
                target_window_m = self._best_range_target_window_m(range_row, tol_m)
                min_quality_db = 12.0
                self._log(
                    f"[{label}] Composite search: comm={comm_ch} by EVM, "
                    f"range={range_ch} by target dR={target_diff_mm:.2f} mm "
                    f"(window={target_window_m * 1e3:.2f} mm, min PNR={min_quality_db:.1f} dB)."
                )

                for idx in range(10):
                    run_no = idx + 1
                    self._log(f"[{label}] Acquire {run_no}/10")
                    self.parent.after(
                        0,
                        lambda n=run_no, lab=label: self.capture_file_var.set(
                            f"Capture: {lab} {n}/10 acquiring..."
                        ),
                    )
                    self._capture_live_once_sync()
                    self._update_band_metrics_for_channels()
                    if comm_ch in self._rx_multi:
                        self._set_primary_rx_channel(comm_ch)
                    self.parent.after(0, self._plot_spectrum_and_time)
                    self.parent.after(0, self._refresh_metrics_table)

                    self._clear_demod_metrics()
                    self._on_demodulate(show_errors=False, run_async=False)
                    # worker() runs inline now, but _show_demod_result (which
                    # actually writes the "evm_db" metric) is still queued via
                    # parent.after(0, ...) since it touches Tk/matplotlib --
                    # give it one mainloop tick to land. On a real failure
                    # nothing gets scheduled at all, so this returns quickly
                    # instead of the old 30s stall per failed run.
                    evm_db = self._wait_for_metric("evm_db", timeout_s=0.6)
                    ber_val = self._metric_float("ber")
                    ber_desc = f"{ber_val:.2e}" if np.isfinite(ber_val) else "N/A"

                    range_result = None
                    range_summary: dict[str, float | bool | str] = {}
                    try:
                        item = self._rx_multi.get(range_ch) if self._rx_multi else None
                        if item is None:
                            item = {"sig": self._rx_sig, "fs": self._rx_fs}
                        range_result = self._compute_isac_range_profile_for_signal(
                            np.asarray(item["sig"], dtype=np.float64),
                            float(item["fs"]),
                            pl,
                            ch_label=range_ch,
                            row=range_row,
                        )
                        range_summary = self._range_difference_quality_summary(
                            range_result,
                            target_diff_mm=target_diff_mm,
                            target_tol_mm=max(tol_mm, target_window_m * 1e3),
                            min_quality_db=min_quality_db,
                        )
                        if range_result:
                            self.parent.after(
                                0,
                                lambda item=range_result: self._show_isac_range_results([item]),
                            )
                    except Exception as range_e:
                        self._log(f"[{label}] {run_no}/10 range check skipped: {range_e}")
                    range_m = float(range_summary.get("range_m", float("nan"))) if range_summary else float("nan")
                    range_score = float(range_summary.get("score", float("inf"))) if range_summary else float("inf")
                    range_diff_mm = float(range_summary.get("range_diff_mm", float("nan"))) if range_summary else float("nan")
                    range_err_mm = float(range_summary.get("range_diff_err_mm", float("nan"))) if range_summary else float("nan")
                    pnr_db = float(range_summary.get("peak_noise_db", float("nan"))) if range_summary else float("nan")
                    sep_db = float(range_summary.get("peak_sep_db", float("nan"))) if range_summary else float("nan")
                    range_method = str(range_summary.get("method", "N/A")) if range_summary else "N/A"
                    range_desc = (
                        f"{range_ch} range={range_m:.4g} m dR={range_diff_mm:.2f} mm "
                        f"err={range_err_mm:.2f} mm "
                        f"PNR={pnr_db:.2f} dB sep={sep_db:.2f} dB method={range_method}"
                        if np.isfinite(range_m)
                        else f"{range_ch} range=N/A"
                    )

                    self._log(
                        f"[{label}] {run_no}/10 {comm_ch} EVM={evm_db:.2f} dB  "
                        f"BER={ber_desc}  {range_desc}  score={range_score:.4g}"
                    )
                    self.parent.after(
                        0,
                        lambda n=run_no, e=evm_db, b=ber_desc, r=range_desc, lab=label: self.capture_file_var.set(
                            f"Capture: {lab} {n}/10  EVM={e:.2f} dB  BER={b}  {r}"
                        ),
                    )

                    if np.isfinite(evm_db) and evm_db < best_comm_evm_db:
                        best_comm_evm_db = evm_db
                        best_comm_snap = self._snapshot_capture_state()
                        best_comm_desc = f"{comm_ch} EVM={evm_db:.2f} dB, BER={ber_desc}"
                        self._log(f"[{label}] New best communication capture: {best_comm_desc}")

                    if np.isfinite(range_score) and range_score < best_range_score:
                        best_range_score = range_score
                        best_range_snap = self._snapshot_capture_state()
                        best_range_desc = range_desc
                        self._log(f"[{label}] New best range capture: {best_range_desc}")

                if best_comm_snap is None:
                    raise ValueError("No valid EVM result was produced.")
                if best_range_snap is None:
                    self._log(f"[{label}] No valid range result; reusing best-EVM capture for {range_ch}.")
                    best_range_snap = best_comm_snap
                    best_range_desc = "range=N/A; reused best-EVM capture"

                self._compose_best_comm_range_state(best_comm_snap, comm_ch, best_range_snap, range_ch)
                self._update_band_metrics_for_channels()
                self._log(
                    f"[{label}] Selected composite capture: "
                    f"comm=({best_comm_desc}); range=({best_range_desc})."
                )
                self.parent.after(
                    0,
                    lambda e=best_comm_evm_db, lab=label, c=comm_ch, r=range_ch: self.capture_file_var.set(
                        f"Capture: {lab} composite  {c} EVM={e:.2f} dB + {r} best range (unsaved)"
                    ),
                )
                self.parent.after(0, self._plot_spectrum_and_time)
                self.parent.after(0, self._refresh_metrics_table)

                if comm_ch in self._rx_multi:
                    self._set_primary_rx_channel(comm_ch)
                self._on_demodulate(show_errors=False, run_async=False)
                self._wait_for_metric("evm_db", timeout_s=0.6)
                try:
                    final_range_items = self._compute_range_items_for_current_capture(pl)
                    if final_range_items:
                        self.parent.after(
                            0,
                            lambda items=final_range_items: self._show_isac_range_results(items),
                        )
                except Exception as range_e:
                    self._log(f"[{label}] Final range update skipped: {range_e}")
            except Exception as e:
                self._log(f"[{label}] Error: {e}")
                self.parent.after(0, lambda m=str(e), lab=label: messagebox.showerror(f"{lab} Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _on_sweep_sc_fde_taps(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire or load a capture first.")
            return

        def worker():
            tap_candidates = [1, 3, 5, 9, 13, 21, 31, 41, 51, 71]
            best_taps = None
            best_evm_db = float("inf")
            old_taps = self.sc_fde_taps_var.get()
            try:
                for taps in tap_candidates:
                    self.sc_fde_taps_var.set(str(taps))
                    self._clear_demod_metrics()
                    self._on_demodulate(show_errors=False, run_async=False)
                    evm_db = self._wait_for_metric("evm_db", timeout_s=0.6)
                    self._log(f"[Post-EQ Sweep] taps={taps}  EVM={evm_db:.2f} dB")
                    if np.isfinite(evm_db) and evm_db < best_evm_db:
                        best_evm_db = evm_db
                        best_taps = taps
                if best_taps is None:
                    self.sc_fde_taps_var.set(old_taps)
                    raise ValueError("No valid EVM result was produced during tap sweep.")
                self.sc_fde_taps_var.set(str(best_taps))
                self._log(f"[Post-EQ Sweep] Selected taps={best_taps}  EVM={best_evm_db:.2f} dB")
                self._on_demodulate(show_errors=False, run_async=False)
            except Exception as e:
                self._log(f"[Post-EQ Sweep] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Post-EQ Sweep Error", m))
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _npz_pack_value(value):
        if isinstance(value, np.ndarray):
            return value
        if isinstance(value, (list, tuple)):
            return np.asarray(value)
        return np.asarray([value])

    @staticmethod
    def _npz_unpack_value(value):
        arr = np.asarray(value)
        if arr.shape == (1,):
            v = arr[0]
            return v.item() if hasattr(v, "item") else v
        return arr

    def _tx_payload_to_npz_items(self, payload: dict | None) -> dict:
        out: dict[str, np.ndarray] = {}
        if not payload:
            return out
        for key, value in payload.items():
            try:
                out[f"tx__{key}"] = self._npz_pack_value(value)
            except Exception:
                pass
        return out

    def _tx_payload_from_npz(self, loaded) -> dict:
        payload: dict = {}
        for key in loaded.files:
            if not key.startswith("tx__"):
                continue
            payload[key[4:]] = self._npz_unpack_value(loaded[key])
        return payload

    def _metrics_to_npz_items(self) -> dict:
        if self._loaded_capture_without_metrics:
            return {}
        rows = self._metric_rows()
        return {
            "metric_keys": np.asarray([r["key"] for r in rows]),
            "metric_categories": np.asarray([r["category"] for r in rows]),
            "metric_labels": np.asarray([r["label"] for r in rows]),
            "metric_values": np.asarray([r["value"] for r in rows]),
            "metric_units": np.asarray([r["unit"] for r in rows]),
            "metric_notes": np.asarray([r["note"] for r in rows]),
        }

    def _metrics_from_npz(self, loaded) -> None:
        if "metric_keys" not in loaded.files or "metric_values" not in loaded.files:
            self._metrics = {}
            self._loaded_capture_without_metrics = True
            return
        keys = np.asarray(loaded["metric_keys"]).reshape(-1)
        vals = np.asarray(loaded["metric_values"]).reshape(-1)
        if len(keys) == 0:
            self._metrics = {}
            self._loaded_capture_without_metrics = True
            return
        labels = np.asarray(loaded["metric_labels"]).reshape(-1) if "metric_labels" in loaded.files else keys
        units = np.asarray(loaded["metric_units"]).reshape(-1) if "metric_units" in loaded.files else np.asarray([""] * len(keys))
        notes = np.asarray(loaded["metric_notes"]).reshape(-1) if "metric_notes" in loaded.files else np.asarray([""] * len(keys))
        cats = np.asarray(loaded["metric_categories"]).reshape(-1) if "metric_categories" in loaded.files else np.asarray([""] * len(keys))
        self._metrics = {}
        self._loaded_capture_without_metrics = False
        for i, raw_key in enumerate(keys):
            key = str(raw_key.item() if hasattr(raw_key, "item") else raw_key)
            val = vals[i].item() if i < len(vals) and hasattr(vals[i], "item") else (vals[i] if i < len(vals) else "N/A")
            label = labels[i].item() if i < len(labels) and hasattr(labels[i], "item") else key
            unit = units[i].item() if i < len(units) and hasattr(units[i], "item") else ""
            note = notes[i].item() if i < len(notes) and hasattr(notes[i], "item") else ""
            cat = cats[i].item() if i < len(cats) and hasattr(cats[i], "item") else ""
            self._metrics[key] = {
                "label": str(label),
                "value": val,
                "unit": str(unit),
                "note": str(note),
                "category": str(cat),
            }

    def _dsp_state_to_npz_items(self) -> dict:
        return {
            "dsp__fc_ghz": np.asarray([self.fc_var.get().strip()]),
            "dsp__sr_ghz": np.asarray([self.sr_var.get().strip()]),
            "dsp__modulation": np.asarray([self.demod_mod_var.get().strip()]),
            "dsp__rrc_beta": np.asarray([self.demod_beta_var.get().strip()]),
            "dsp__rrc_span": np.asarray([self.demod_span_var.get().strip()]),
            "dsp__demod_lpf": np.asarray([int(bool(self.filter_enable_var.get()))], dtype=np.int8),
            "dsp__sc_fde": np.asarray([int(bool(self.sc_fde_enable_var.get()))], dtype=np.int8),
            "dsp__sc_fde_taps": np.asarray([self.sc_fde_taps_var.get().strip()]),
            "dsp__ch1_scale_mv": np.asarray([self.ch1_scale_mv_var.get().strip()]),
            "dsp__ch2_scale_mv": np.asarray([self.ch2_scale_mv_var.get().strip()]),
            "dsp__range_target_m": np.asarray([self.range_target_m_var.get().strip()]),
            "dsp__range_tolerance_m": np.asarray([self.range_tolerance_m_var.get().strip()]),
            "dsp__range_diff_mm": np.asarray([self.range_target_m_var.get().strip()]),
            "dsp__range_diff_tolerance_mm": np.asarray([self.range_tolerance_m_var.get().strip()]),
            "dsp__range_mode": np.asarray([self.range_mode_var.get().strip()]),
            "dsp__pilot_rho": np.asarray([
                str((self.runtime.get("tx_payload") or {}).get("amplitude_ratio_rho", ""))
            ]),
            "dsp__range_mode_row1": np.asarray([self._range_mode_for_row(0)]),
            "dsp__range_mode_row2": np.asarray([self._range_mode_for_row(1)]),
            "dsp__auto_sync_tx_params": np.asarray([int(bool(self.auto_sync_tx_params_var.get()))], dtype=np.int8),
            "dsp__trigger_channel": np.asarray([self.trig_ch_var.get().strip()]),
            "dsp__trigger_level_mv": np.asarray([self.trig_level_mv_var.get().strip()]),
            "dsp__dso_sr_gsa": np.asarray([self.dso_sr_var.get().strip()]),
            "dsp__process_fs_gsa": np.asarray([self.capture_fs_var.get().strip()]),
            "dsp__data_length_ksa": np.asarray([self.data_len_ksa_var.get().strip()]),
        }

    def _range_zero_to_npz_items(self) -> dict:
        out: dict[str, np.ndarray] = {}
        zero_by_ch = self.runtime.get("lfm_range_zero_by_ch")
        if isinstance(zero_by_ch, dict) and zero_by_ch:
            channels = [str(ch).strip().upper() for ch in zero_by_ch.keys()]
            out["range_zero_channels"] = np.asarray(channels)
            for ch in channels:
                info = zero_by_ch.get(ch, {})
                if not isinstance(info, dict):
                    continue
                prefix = f"range_zero__{ch}__"
                for key in (
                    "delay_s", "frame_start", "peak_lag", "frame_period_s", "fs",
                    "profile_center_m", "abs_range_m", "range_mode",
                    "range_scale_m_per_s", "range_resolution_m",
                ):
                    if key in info and info[key] is not None:
                        try:
                            out[prefix + key] = self._npz_pack_value(info[key])
                        except Exception:
                            pass
                cfr_i = info.get("cfr")
                if isinstance(cfr_i, dict):
                    for key in ("freqs", "h", "weight", "fs"):
                        if key in cfr_i:
                            try:
                                out[prefix + f"cfr_{key}"] = self._npz_pack_value(cfr_i[key])
                            except Exception:
                                pass
                prof_i = info.get("profile")
                if isinstance(prof_i, dict):
                    for key in ("lags", "prof_db", "peak_lag", "fs", "center_m", "abs_range_m"):
                        if key in prof_i:
                            try:
                                out[prefix + f"profile_{key}"] = self._npz_pack_value(prof_i[key])
                            except Exception:
                                pass
        if "lfm_range_zero_delay_s" in self.runtime:
            out["range_zero__delay_s"] = np.asarray([float(self.runtime["lfm_range_zero_delay_s"])], dtype=np.float64)
        if "lfm_range_zero_channel" in self.runtime:
            out["range_zero__channel"] = np.asarray([str(self.runtime["lfm_range_zero_channel"])])
        cfr = self.runtime.get("lfm_range_zero_cfr")
        if isinstance(cfr, dict):
            for key in ("freqs", "h", "weight", "fs"):
                if key in cfr:
                    try:
                        out[f"range_zero__cfr_{key}"] = self._npz_pack_value(cfr[key])
                    except Exception:
                        pass
        if self._last_range_summaries:
            out["range_summary_channels"] = np.asarray([str(x.get("channel", "")) for x in self._last_range_summaries])
            out["range_summary_modes"] = np.asarray([str(x.get("range_mode", "")) for x in self._last_range_summaries])
            out["range_summary_methods"] = np.asarray([str(x.get("range_est_method", "")) for x in self._last_range_summaries])
            out["range_summary_peak_m"] = np.asarray([float(x.get("range_peak_m", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_display_m"] = np.asarray([float(x.get("display_range_m", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_matched_filter_peak_m"] = np.asarray([float(x.get("matched_filter_peak_m", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_self_interference_m"] = np.asarray([float(x.get("self_interference_range_m", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_zero_guard_m"] = np.asarray([float(x.get("zero_exclude_m", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_pslr_db"] = np.asarray([float(x.get("pslr_db", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_snr_rad_post_db"] = np.asarray([float(x.get("range_profile_snr_db", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_processing_gain_db"] = np.asarray([float(x.get("processing_gain_db", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_snr_rad_pg_corrected_db"] = np.asarray([float(x.get("pg_corrected_snr_db", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_diff_range_mm"] = np.asarray([float(x.get("diff_range_mm", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_cfr_diff_range_mm"] = np.asarray([float(x.get("cfr_diff_range_mm", float("nan"))) for x in self._last_range_summaries])
            out["range_summary_diff_methods"] = np.asarray([str(x.get("range_diff_method", "")) for x in self._last_range_summaries])
            out["range_summary_diff_cfr_coherence"] = np.asarray([float(x.get("diff_cfr_coherence", float("nan"))) for x in self._last_range_summaries])
        return out

    def _range_zero_from_npz(self, loaded) -> None:
        zero_by_ch: dict[str, dict[str, object]] = {}
        if "range_zero_channels" in loaded.files:
            try:
                channels = [str(x) for x in np.asarray(loaded["range_zero_channels"]).reshape(-1)]
                for ch in channels:
                    prefix = f"range_zero__{ch}__"
                    info: dict[str, object] = {}
                    for key in (
                        "delay_s", "frame_start", "peak_lag", "frame_period_s", "fs",
                        "profile_center_m", "abs_range_m", "range_mode",
                        "range_scale_m_per_s", "range_resolution_m",
                    ):
                        fkey = prefix + key
                        if fkey in loaded.files:
                            val = self._npz_unpack_value(loaded[fkey])
                            try:
                                if key in {"frame_start", "peak_lag"}:
                                    info[key] = int(val)
                                elif key == "range_mode":
                                    info[key] = str(val)
                                else:
                                    info[key] = float(val)
                            except Exception:
                                info[key] = val
                    if prefix + "cfr_freqs" in loaded.files and prefix + "cfr_h" in loaded.files:
                        info["cfr"] = {
                            "freqs": np.asarray(loaded[prefix + "cfr_freqs"], dtype=np.float64).reshape(-1),
                            "h": np.asarray(loaded[prefix + "cfr_h"], dtype=np.complex128).reshape(-1),
                            "weight": (
                                np.asarray(loaded[prefix + "cfr_weight"], dtype=np.float64).reshape(-1)
                                if prefix + "cfr_weight" in loaded.files
                                else np.ones(len(np.asarray(loaded[prefix + "cfr_freqs"]).reshape(-1)))
                            ),
                            "fs": (
                                float(np.asarray(loaded[prefix + "cfr_fs"]).reshape(-1)[0])
                                if prefix + "cfr_fs" in loaded.files
                                else float(info.get("fs", float("nan")))
                            ),
                        }
                    if prefix + "profile_lags" in loaded.files and prefix + "profile_prof_db" in loaded.files:
                        info["profile"] = {
                            "lags": np.asarray(loaded[prefix + "profile_lags"], dtype=np.float64).reshape(-1),
                            "prof_db": np.asarray(loaded[prefix + "profile_prof_db"], dtype=np.float64).reshape(-1),
                            "peak_lag": (
                                float(np.asarray(loaded[prefix + "profile_peak_lag"]).reshape(-1)[0])
                                if prefix + "profile_peak_lag" in loaded.files
                                else float(info.get("peak_lag", 0.0))
                            ),
                            "fs": (
                                float(np.asarray(loaded[prefix + "profile_fs"]).reshape(-1)[0])
                                if prefix + "profile_fs" in loaded.files
                                else float(info.get("fs", float("nan")))
                            ),
                            "center_m": (
                                float(np.asarray(loaded[prefix + "profile_center_m"]).reshape(-1)[0])
                                if prefix + "profile_center_m" in loaded.files
                                else float(info.get("profile_center_m", 0.0))
                            ),
                        }
                        if prefix + "profile_abs_range_m" in loaded.files:
                            try:
                                info["profile"]["abs_range_m"] = float(
                                    np.asarray(loaded[prefix + "profile_abs_range_m"]).reshape(-1)[0]
                                )
                            except Exception:
                                pass
                    if info:
                        zero_by_ch[ch] = info
                if zero_by_ch:
                    self.runtime["lfm_range_zero_by_ch"] = zero_by_ch
                    first_ch = next(iter(zero_by_ch))
                    self.runtime["lfm_range_zero_info"] = zero_by_ch[first_ch]
            except Exception:
                pass
        if "range_zero__delay_s" in loaded.files:
            try:
                self.runtime["lfm_range_zero_delay_s"] = float(np.asarray(loaded["range_zero__delay_s"]).reshape(-1)[0])
            except Exception:
                pass
        if "range_zero__channel" in loaded.files:
            try:
                self.runtime["lfm_range_zero_channel"] = str(self._npz_unpack_value(loaded["range_zero__channel"]))
            except Exception:
                pass
        if "range_zero__cfr_freqs" in loaded.files and "range_zero__cfr_h" in loaded.files:
            try:
                self.runtime["lfm_range_zero_cfr"] = {
                    "freqs": np.asarray(loaded["range_zero__cfr_freqs"], dtype=np.float64).reshape(-1),
                    "h": np.asarray(loaded["range_zero__cfr_h"], dtype=np.complex128).reshape(-1),
                    "weight": (
                        np.asarray(loaded["range_zero__cfr_weight"], dtype=np.float64).reshape(-1)
                        if "range_zero__cfr_weight" in loaded.files
                        else np.ones(len(np.asarray(loaded["range_zero__cfr_freqs"]).reshape(-1)))
                    ),
                    "fs": (
                        float(np.asarray(loaded["range_zero__cfr_fs"]).reshape(-1)[0])
                        if "range_zero__cfr_fs" in loaded.files
                        else float("nan")
                    ),
                }
            except Exception:
                pass

    @staticmethod
    def _filename_num(value, decimals: int = 3) -> str:
        try:
            v = float(value)
            if not np.isfinite(v):
                return "NA"
            text = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
            return text if text not in {"", "-0"} else "0"
        except Exception:
            return "NA"

    @staticmethod
    def _filename_safe_token(value) -> str:
        text = str(value).strip() if value is not None else "NA"
        if not text:
            text = "NA"
        for ch in '<>:"/\\|?* ':
            text = text.replace(ch, "_")
        while "__" in text:
            text = text.replace("__", "_")
        return text.strip("._") or "NA"

    def _artifact_default_stem(self, prefix: str) -> str:
        pl = self.runtime.get("tx_payload")
        if pl is None:
            try:
                pl = self._load_tx_payload_for_isac()
            except Exception:
                pl = None
        pl = pl if isinstance(pl, dict) else {}

        def _hz_to_ghz(value, fallback_text: str = "") -> float:
            try:
                v = float(value)
                if np.isfinite(v):
                    return v / 1e9
            except Exception:
                pass
            try:
                return float(fallback_text)
            except Exception:
                return float("nan")

        if_ghz = _hz_to_ghz(pl.get("if_freq"), self.fc_var.get())
        sr_ghz = _hz_to_ghz(pl.get("symbol_rate"), self.sr_var.get())
        rf_ghz = _hz_to_ghz(pl.get("fc"), "")
        if not np.isfinite(rf_ghz):
            rf_ghz = _hz_to_ghz(pl.get("rf_freq"), "")
        p_dbm = pl.get("awg_ch1_power_dbm", float("nan"))
        waveform = pl.get("waveform_type", "")
        if not str(waveform).strip():
            waveform = self._metrics.get("waveform_type", {}).get("value", "Waveform")
        modulation = pl.get("modulation", "")
        if not str(modulation).strip():
            modulation = self._metrics.get("modulation", {}).get("value", "")
        if not str(modulation).strip():
            modulation = self.demod_mod_var.get().strip()
        iph_ma = self.photocurrent_ma_var.get().strip()
        if not iph_ma:
            iph_ma = self._metrics.get("photocurrent_ma", {}).get("value", "NA")

        return (
            f"{prefix}"
            f"_fIF{self._filename_num(if_ghz, 3)}"
            f"_fsym{self._filename_num(sr_ghz, 3)}"
            f"_P{self._filename_num(p_dbm, 2)}"
            f"_fRF{self._filename_num(rf_ghz, 3)}"
            f"_{self._filename_safe_token(waveform)}"
            f"_{self._filename_safe_token(modulation)}"
            f"_Iph{self._filename_safe_token(self._filename_num(iph_ma, 3))}"
        )

    def _capture_default_path(self) -> Path:
        cap_dir = APP_DIR / "data" / "captures"
        cap_dir.mkdir(parents=True, exist_ok=True)
        return cap_dir / f"{self._artifact_default_stem('Data')}.npz"

    def _range_default_path(self) -> Path:
        range_dir = APP_DIR / "data" / "range"
        range_dir.mkdir(parents=True, exist_ok=True)
        role = str(self.runtime.get("latest_range_save_role", "")).strip().lower()
        if self._last_range_results:
            prefix = "Range"
        elif role == "reference" or self.runtime.get("lfm_range_zero_by_ch"):
            prefix = "RangeRef"
        else:
            prefix = "Range"
        return range_dir / f"{self._artifact_default_stem(prefix)}.npz"

    def _range_results_to_npz_items(self, results: list[dict[str, object]] | None = None) -> dict:
        out: dict[str, np.ndarray] = {}
        items = list(results if results is not None else self._last_range_results)
        if not items:
            out["range_result_count"] = np.asarray([0], dtype=np.int64)
            return out
        out["range_result_count"] = np.asarray([len(items)], dtype=np.int64)
        out["range_result_channels"] = np.asarray([
            str(item.get("ch", f"R{idx + 1}")).strip().upper()
            for idx, item in enumerate(items)
        ])
        array_keys = {
            "dechirped", "rng", "prof_db", "ref_rng", "ref_prof_db",
            "lags", "corr_acc", "cfr_freqs_hz", "cfr_h", "cfr_weight",
            "si_cfr_rng", "si_cfr_prof_db",
        }
        scalar_keys = {
            "ch", "row", "fs_ref", "frame_start", "n_chirps", "pts_per_chirp",
            "ref_len", "range_scale_m_per_s", "est_range", "est_range_raw",
            "display_range_m", "range_est_method", "pslr_db", "range_mode",
            "range_profile_snr_db", "processing_gain_db", "pg_corrected_snr_db",
            "self_interference_range_m", "zero_exclude_m", "diff_tau_s",
            "diff_range_m", "diff_coherence", "zero_active", "zero_ref_center_m",
            "range_diff_mm", "peak_range_diff_mm", "range_diff_method",
            "matched_filter_range_diff_mm", "target_diff_mm", "range_resolution_m",
            "target_range_m", "target_window_m",
            "si_cfr_peak_m", "si_cfr_coherence", "si_cfr_target_db",
        }
        for idx, item in enumerate(items):
            ch = str(item.get("ch", f"R{idx + 1}")).strip().upper() or f"R{idx + 1}"
            prefix = f"range__{idx:02d}__{self._filename_safe_token(ch)}__"
            for key in sorted(array_keys):
                if key not in item:
                    continue
                try:
                    out[prefix + key] = self._npz_pack_value(item[key])
                except Exception:
                    pass
            for key in sorted(scalar_keys):
                if key not in item:
                    continue
                try:
                    out[prefix + key] = self._npz_pack_value(item[key])
                except Exception:
                    pass
        return out

    def _augment_range_item_with_si_cfr(self, item: dict) -> dict:
        out = dict(item)
        if len(np.asarray(out.get("si_cfr_rng", []), dtype=np.float64).reshape(-1)) >= 4:
            return out
        freqs = np.asarray(out.get("cfr_freqs_hz", []), dtype=np.float64).reshape(-1)
        h = np.asarray(out.get("cfr_h", []), dtype=np.complex128).reshape(-1)
        w = np.asarray(out.get("cfr_weight", []), dtype=np.float64).reshape(-1)
        rng = np.asarray(out.get("rng", []), dtype=np.float64).reshape(-1)
        if len(freqs) < 16 or len(h) < 16 or len(rng) < 8:
            return out
        try:
            range_scale = float(out.get("range_scale_m_per_s", self._range_delay_scale_m_per_s(row=int(out.get("row", 0)))))
        except Exception:
            range_scale = 3e8 / 2.0
        cfr_rng = rng[np.isfinite(rng)]
        cfr_rng = cfr_rng[cfr_rng >= 0.0]
        if len(cfr_rng) > 4096:
            cfr_rng = np.linspace(float(np.nanmin(cfr_rng)), float(np.nanmax(cfr_rng)), 4096)
        if len(cfr_rng) < 8:
            return out
        try:
            si_cfr = si_normalized_cfr_delay_profile(freqs, h, w if len(w) else None, cfr_rng, range_scale)
            si_rng = np.asarray(si_cfr["range_m"], dtype=np.float64)
            si_prof = np.asarray(si_cfr["profile_db"], dtype=np.float64)
            si_peak = float(si_cfr["peak_m"])
            target_m = float(out.get("target_range_m", float("nan")))
            target_window_m = float(out.get("target_window_m", float("nan")))
            zero_exclude_m = float(out.get("zero_exclude_m", float("nan")))
            if len(si_rng) == len(si_prof) and len(si_rng):
                pick_mask = np.isfinite(si_rng)
                if np.isfinite(target_m) and target_m > 0 and np.isfinite(target_window_m) and target_window_m > 0:
                    pick_mask &= np.abs(si_rng - target_m) <= target_window_m
                elif np.isfinite(zero_exclude_m) and zero_exclude_m > 0:
                    pick_mask &= si_rng > zero_exclude_m
                if np.any(pick_mask):
                    pick_indices = np.flatnonzero(pick_mask)
                    peak_idx = int(pick_indices[int(np.nanargmax(si_prof[pick_mask]))])
                    si_peak = float(si_rng[peak_idx])
                    out["si_cfr_target_db"] = float(si_prof[peak_idx])
            out["si_cfr_rng"] = si_rng
            out["si_cfr_prof_db"] = si_prof
            out["si_cfr_peak_m"] = si_peak
            out["si_cfr_coherence"] = float(si_cfr["coherence"])
        except Exception:
            pass
        return out

    def _range_results_from_npz(self, loaded) -> list[dict]:
        try:
            count = int(np.asarray(loaded["range_result_count"]).reshape(-1)[0]) if "range_result_count" in loaded.files else 0
        except Exception:
            count = 0
        if count <= 0:
            return []
        channels = []
        if "range_result_channels" in loaded.files:
            try:
                channels = [str(x.item() if hasattr(x, "item") else x).strip().upper() for x in np.asarray(loaded["range_result_channels"]).reshape(-1)]
            except Exception:
                channels = []
        array_keys = {
            "dechirped", "rng", "prof_db", "ref_rng", "ref_prof_db",
            "lags", "corr_acc", "cfr_freqs_hz", "cfr_h", "cfr_weight",
            "si_cfr_rng", "si_cfr_prof_db",
        }
        scalar_keys = {
            "ch", "row", "fs_ref", "frame_start", "n_chirps", "pts_per_chirp",
            "ref_len", "range_scale_m_per_s", "est_range", "est_range_raw",
            "display_range_m", "range_est_method", "pslr_db", "range_mode",
            "range_profile_snr_db", "processing_gain_db", "pg_corrected_snr_db",
            "self_interference_range_m", "zero_exclude_m", "diff_tau_s",
            "diff_range_m", "diff_coherence", "zero_active", "zero_ref_center_m",
            "range_diff_mm", "peak_range_diff_mm", "range_diff_method",
            "matched_filter_range_diff_mm", "target_diff_mm", "range_resolution_m",
            "target_range_m", "target_window_m",
            "si_cfr_peak_m", "si_cfr_coherence", "si_cfr_target_db",
        }
        items: list[dict] = []
        for idx in range(count):
            ch = channels[idx] if idx < len(channels) and channels[idx] else f"R{idx + 1}"
            prefix = f"range__{idx:02d}__{self._filename_safe_token(ch)}__"
            item: dict[str, object] = {"ch": ch}
            for key in array_keys:
                fkey = prefix + key
                if fkey in loaded.files:
                    item[key] = np.asarray(loaded[fkey])
            for key in scalar_keys:
                fkey = prefix + key
                if fkey not in loaded.files:
                    continue
                val = self._npz_unpack_value(loaded[fkey])
                if key in {"ch", "range_est_method", "range_mode", "range_diff_method"}:
                    item[key] = str(val)
                elif key in {"row", "frame_start", "n_chirps", "pts_per_chirp", "ref_len"}:
                    try:
                        item[key] = int(val)
                    except Exception:
                        item[key] = val
                elif key == "zero_active":
                    try:
                        item[key] = bool(int(val))
                    except Exception:
                        item[key] = bool(val)
                else:
                    try:
                        item[key] = float(val)
                    except Exception:
                        item[key] = val
            items.append(self._augment_range_item_with_si_cfr(item))
        return items

    def _on_save_range_data(self) -> None:
        has_ref = bool(self.runtime.get("lfm_range_zero_by_ch") or self.runtime.get("lfm_range_zero_info"))
        has_result = bool(self._last_range_results)
        if not has_ref and not has_result:
            messagebox.showwarning(
                "No range data",
                "Run Detect Range or Store Zero Ref before saving range data.",
            )
            return

        default_path = self._range_default_path()
        path_str = filedialog.asksaveasfilename(
            title="Save Range Data",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            defaultextension=".npz",
            filetypes=[("NumPy range data", "*.npz"), ("All files", "*.*")],
        )
        if not path_str:
            return

        def worker():
            try:
                path = Path(path_str)
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = self._load_tx_payload_for_isac()
                role = "measurement" if self._last_range_results else "reference"
                saved_channels = list(self._rx_multi.keys()) if self._rx_multi else []
                meta = {
                    "created": np.asarray([datetime.now().isoformat(timespec="seconds")]),
                    "artifact_name_stem": np.asarray([self._artifact_default_stem("Range")]),
                    "range_save_role": np.asarray([role]),
                    "range_display_unit": np.asarray(["mm"]),
                    "rx_primary_channel": np.asarray([self.ch_var.get().strip()]),
                    "rx_display_channels": np.asarray(self._selected_dso_channels()),
                    "rx_channels": np.asarray(saved_channels),
                    "fc_ghz": np.asarray([self.fc_var.get().strip()]),
                    "sr_ghz": np.asarray([self.sr_var.get().strip()]),
                    "modulation": np.asarray([self.demod_mod_var.get().strip()]),
                    "range_diff_target_mm": np.asarray([self.range_target_m_var.get().strip()]),
                    "range_diff_tolerance_mm": np.asarray([self.range_tolerance_m_var.get().strip()]),
                    "notes": np.asarray([
                        "Absolute range uses matched-filter lag relative to frame sync; "
                        "stored zero reference provides comparison profile and dR."
                    ]),
                }
                for ch, item in (self._rx_multi or {}).items():
                    key = ch.strip().upper()
                    try:
                        sig_i = np.asarray(item["sig"], dtype=np.float64)
                        fs_i = float(item["fs"])
                        t_i = (
                            np.asarray(item["t"], dtype=np.float64)
                            if item.get("t") is not None and len(item["t"]) == len(sig_i)
                            else np.arange(len(sig_i), dtype=np.float64) / fs_i
                        )
                        meta[f"rx__{key}__sig"] = sig_i
                        meta[f"rx__{key}__t"] = t_i
                        meta[f"rx__{key}__fs"] = np.asarray([fs_i], dtype=np.float64)
                    except Exception:
                        pass
                if not self._rx_multi and self._rx_sig is not None:
                    sig = np.asarray(self._rx_sig, dtype=np.float64)
                    fs = float(self._rx_fs)
                    t = (
                        np.asarray(self._rx_t, dtype=np.float64)
                        if self._rx_t is not None and len(self._rx_t) == len(sig)
                        else np.arange(len(sig), dtype=np.float64) / fs
                    )
                    meta["rx_sig"] = sig
                    meta["rx_t"] = t
                    meta["rx_fs"] = np.asarray([fs], dtype=np.float64)
                meta.update(self._tx_payload_to_npz_items(payload))
                meta.update(self._dsp_state_to_npz_items())
                meta.update(self._metrics_to_npz_items())
                meta.update(self._range_zero_to_npz_items())
                meta.update(self._range_results_to_npz_items())
                np.savez_compressed(path, **meta)
                self.runtime["latest_range_file"] = str(path)
                self._log(f"[Range] Saved {role} range data: {path}")
                self.parent.after(
                    0,
                    lambda p=str(path): self.capture_file_var.set(f"Range: {Path(p).name}"),
                )
            except Exception as e:
                self._log(f"[Range] Save error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Save Range Error", m))

        threading.Thread(target=worker, daemon=True).start()

    def _on_save_capture(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire or load a capture first.")
            return

        default_path = self._capture_default_path()
        path_str = filedialog.asksaveasfilename(
            title="Save DSO Capture",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            defaultextension=".npz",
            filetypes=[("NumPy capture", "*.npz"), ("All files", "*.*")],
        )
        if not path_str:
            return

        def worker():
            try:
                path = Path(path_str)
                path.parent.mkdir(parents=True, exist_ok=True)
                sig = np.asarray(self._rx_sig, dtype=np.float64)
                fs = float(self._rx_fs)
                t = (
                    np.asarray(self._rx_t, dtype=np.float64)
                    if self._rx_t is not None and len(self._rx_t) == len(sig)
                    else np.arange(len(sig), dtype=np.float64) / fs
                )
                payload = self._load_tx_payload_for_isac()
                saved_channels = list(self._rx_multi.keys()) if self._rx_multi else [self.ch_var.get().strip()]
                meta = {
                    "rx_sig": sig,
                    "rx_t": t,
                    "rx_fs": np.asarray([fs], dtype=np.float64),
                    "rx_primary_channel": np.asarray([self.ch_var.get().strip()]),
                    "rx_channels": np.asarray(saved_channels),
                    "rx_channel_count": np.asarray([len(saved_channels)], dtype=np.int64),
                    "rx_display_channels": np.asarray(self._selected_dso_channels()),
                    "created": np.asarray([datetime.now().isoformat(timespec="seconds")]),
                    "artifact_name_stem": np.asarray([self._artifact_default_stem("Data")]),
                    "capture_channel": np.asarray([self.ch_var.get().strip()]),
                    "trigger_channel": np.asarray([self.trig_ch_var.get().strip()]),
                    "trigger_level_mv": np.asarray([self.trig_level_mv_var.get().strip()]),
                    "fc_ghz": np.asarray([self.fc_var.get().strip()]),
                    "sr_ghz": np.asarray([self.sr_var.get().strip()]),
                    "modulation": np.asarray([self.demod_mod_var.get().strip()]),
                    "rrc_beta": np.asarray([self.demod_beta_var.get().strip()]),
                    "rrc_span": np.asarray([self.demod_span_var.get().strip()]),
                    "range_mode": np.asarray([self.range_mode_var.get().strip()]),
                    "demod_lpf": np.asarray([int(bool(self.filter_enable_var.get()))], dtype=np.int8),
                    "sc_fde": np.asarray([int(bool(self.sc_fde_enable_var.get()))], dtype=np.int8),
                    "sc_fde_taps": np.asarray([self.sc_fde_taps_var.get().strip()]),
                    "photocurrent_ma": np.asarray([self.photocurrent_ma_var.get().strip()]),
                    "reference_included": np.asarray([int(payload is not None)], dtype=np.int8),
                    "noise_floor_ref_dbmhz": np.asarray([
                        self._noise_floor_ref_dbmhz if self._noise_floor_ref_dbmhz is not None else np.nan
                    ], dtype=np.float64),
                }
                for ch, item in (self._rx_multi or {}).items():
                    key = ch.strip().upper()
                    try:
                        sig_i = np.asarray(item["sig"], dtype=np.float64)
                        fs_i = float(item["fs"])
                        t_i = (
                            np.asarray(item["t"], dtype=np.float64)
                            if item.get("t") is not None and len(item["t"]) == len(sig_i)
                            else np.arange(len(sig_i), dtype=np.float64) / fs_i
                        )
                        meta[f"rx__{key}__sig"] = sig_i
                        meta[f"rx__{key}__t"] = t_i
                        meta[f"rx__{key}__fs"] = np.asarray([fs_i], dtype=np.float64)
                    except Exception:
                        pass
                meta.update(self._tx_payload_to_npz_items(payload))
                meta.update(self._dsp_state_to_npz_items())
                meta.update(self._metrics_to_npz_items())
                meta.update(self._range_zero_to_npz_items())
                np.savez_compressed(path, **meta)
                self.runtime["latest_capture_file"] = str(path)
                self.parent.after(0, lambda p=str(path): self.capture_file_var.set(f"Capture: {Path(p).name}"))
                self._log(
                    f"[Acq] Saved capture+reference+metrics: {path}  "
                    f"channels={','.join(saved_channels)}  "
                    f"N={len(sig):,}, fs={fs/1e9:.3f} GSa/s"
                )
            except Exception as e:
                self._log(f"[Acq] Save error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Save Capture Error", m))

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_capture(self) -> None:
        cap_dir = APP_DIR / "data" / "captures"
        cap_dir.mkdir(parents=True, exist_ok=True)
        path_str = filedialog.askopenfilename(
            title="Load DSO Capture",
            initialdir=str(cap_dir),
            filetypes=[("NumPy capture", "*.npz"), ("All files", "*.*")],
        )
        if not path_str:
            return

        def worker():
            try:
                path = Path(path_str)
                with np.load(path, allow_pickle=True) as loaded:
                    if "rx_sig" not in loaded.files or "rx_fs" not in loaded.files:
                        range_items = self._range_results_from_npz(loaded)
                        if range_items:
                            payload = self._tx_payload_from_npz(loaded)
                            self._metrics_from_npz(loaded)
                            self._range_zero_from_npz(loaded)
                            if payload:
                                self.runtime["tx_payload"] = payload
                            self.runtime["latest_range_file"] = str(path)

                            def update_range_only():
                                self._last_loaded_capture_path = str(path)
                                self.capture_file_var.set(f"Range: {path.name}")
                                self._show_isac_range_results(range_items)

                            self.parent.after(0, update_range_only)
                            self._log(f"[Range] Loaded saved range data: {path}  results={len(range_items)}")
                            return
                        raise ValueError("This file does not contain rx_sig/rx_fs capture data or saved range results.")
                    sig = np.asarray(loaded["rx_sig"], dtype=np.float64).reshape(-1)
                    fs = float(np.asarray(loaded["rx_fs"]).reshape(-1)[0])
                    t = (
                        np.asarray(loaded["rx_t"], dtype=np.float64).reshape(-1)
                        if "rx_t" in loaded.files
                        else np.arange(len(sig), dtype=np.float64) / fs
                    )
                    if len(t) != len(sig):
                        t = np.arange(len(sig), dtype=np.float64) / fs

                    rx_multi: dict[str, dict[str, np.ndarray | float]] = {}
                    if "rx_channels" in loaded.files:
                        for ch_raw in np.asarray(loaded["rx_channels"]).reshape(-1):
                            ch = str(ch_raw.item() if hasattr(ch_raw, "item") else ch_raw).strip().upper()
                            sig_key = f"rx__{ch}__sig"
                            t_key = f"rx__{ch}__t"
                            fs_key = f"rx__{ch}__fs"
                            if sig_key not in loaded.files or fs_key not in loaded.files:
                                continue
                            sig_i = np.asarray(loaded[sig_key], dtype=np.float64).reshape(-1)
                            fs_i = float(np.asarray(loaded[fs_key]).reshape(-1)[0])
                            t_i = (
                                np.asarray(loaded[t_key], dtype=np.float64).reshape(-1)
                                if t_key in loaded.files
                                else np.arange(len(sig_i), dtype=np.float64) / fs_i
                            )
                            if len(t_i) != len(sig_i):
                                t_i = np.arange(len(sig_i), dtype=np.float64) / fs_i
                            rx_multi[ch] = {"sig": sig_i, "t": t_i, "fs": fs_i}
                    if not rx_multi:
                        primary_file_ch = (
                            self._npz_unpack_value(loaded["rx_primary_channel"])
                            if "rx_primary_channel" in loaded.files
                            else self.ch_var.get().strip().upper()
                        )
                        ch = str(primary_file_ch).strip().upper() or "C1"
                        rx_multi[ch] = {"sig": sig, "t": t, "fs": fs}
                    primary_loaded = (
                        self._npz_unpack_value(loaded["rx_primary_channel"])
                        if "rx_primary_channel" in loaded.files
                        else next(iter(rx_multi.keys()))
                    )
                    primary_loaded = str(primary_loaded).strip().upper()
                    display_loaded: list[str] | None = None
                    if "rx_display_channels" in loaded.files:
                        display_loaded = []
                        for ch_raw in np.asarray(loaded["rx_display_channels"]).reshape(-1):
                            ch_disp = str(ch_raw.item() if hasattr(ch_raw, "item") else ch_raw).strip().upper()
                            if ch_disp in {"C1", "C2", "C3", "C4"}:
                                display_loaded.append(ch_disp)

                    payload = self._tx_payload_from_npz(loaded)
                    self._metrics_from_npz(loaded)
                    self._range_zero_from_npz(loaded)
                    if "noise_floor_ref_dbmhz" in loaded.files:
                        try:
                            nf_ref = float(np.asarray(loaded["noise_floor_ref_dbmhz"]).reshape(-1)[0])
                            self._noise_floor_ref_dbmhz = nf_ref if np.isfinite(nf_ref) else None
                        except Exception:
                            self._noise_floor_ref_dbmhz = None
                    gui_vals = {
                        "fc": self._npz_unpack_value(loaded["dsp__fc_ghz"]) if "dsp__fc_ghz" in loaded.files else (self._npz_unpack_value(loaded["fc_ghz"]) if "fc_ghz" in loaded.files else None),
                        "sr": self._npz_unpack_value(loaded["dsp__sr_ghz"]) if "dsp__sr_ghz" in loaded.files else (self._npz_unpack_value(loaded["sr_ghz"]) if "sr_ghz" in loaded.files else None),
                        "mod": self._npz_unpack_value(loaded["dsp__modulation"]) if "dsp__modulation" in loaded.files else (self._npz_unpack_value(loaded["modulation"]) if "modulation" in loaded.files else None),
                        "beta": self._npz_unpack_value(loaded["dsp__rrc_beta"]) if "dsp__rrc_beta" in loaded.files else (self._npz_unpack_value(loaded["rrc_beta"]) if "rrc_beta" in loaded.files else None),
                        "span": self._npz_unpack_value(loaded["dsp__rrc_span"]) if "dsp__rrc_span" in loaded.files else (self._npz_unpack_value(loaded["rrc_span"]) if "rrc_span" in loaded.files else None),
                        "range_mode": self._npz_unpack_value(loaded["dsp__range_mode"]) if "dsp__range_mode" in loaded.files else (self._npz_unpack_value(loaded["range_mode"]) if "range_mode" in loaded.files else None),
                        "demod_lpf": self._npz_unpack_value(loaded["dsp__demod_lpf"]) if "dsp__demod_lpf" in loaded.files else None,
                        "sc_fde": self._npz_unpack_value(loaded["dsp__sc_fde"]) if "dsp__sc_fde" in loaded.files else None,
                        "sc_fde_taps": self._npz_unpack_value(loaded["dsp__sc_fde_taps"]) if "dsp__sc_fde_taps" in loaded.files else None,
                        "ch1_scale_mv": self._npz_unpack_value(loaded["dsp__ch1_scale_mv"]) if "dsp__ch1_scale_mv" in loaded.files else None,
                        "ch2_scale_mv": self._npz_unpack_value(loaded["dsp__ch2_scale_mv"]) if "dsp__ch2_scale_mv" in loaded.files else None,
                        "range_target_m": (
                            self._npz_unpack_value(loaded["dsp__range_diff_mm"])
                            if "dsp__range_diff_mm" in loaded.files
                            else (self._npz_unpack_value(loaded["dsp__range_target_m"]) if "dsp__range_target_m" in loaded.files else None)
                        ),
                        "range_tolerance_m": (
                            self._npz_unpack_value(loaded["dsp__range_diff_tolerance_mm"])
                            if "dsp__range_diff_tolerance_mm" in loaded.files
                            else (self._npz_unpack_value(loaded["dsp__range_tolerance_m"]) if "dsp__range_tolerance_m" in loaded.files else None)
                        ),
                        "auto_sync": self._npz_unpack_value(loaded["dsp__auto_sync_tx_params"]) if "dsp__auto_sync_tx_params" in loaded.files else None,
                        "trig_ch": self._npz_unpack_value(loaded["dsp__trigger_channel"]) if "dsp__trigger_channel" in loaded.files else (self._npz_unpack_value(loaded["trigger_channel"]) if "trigger_channel" in loaded.files else None),
                        "trig_level": self._npz_unpack_value(loaded["dsp__trigger_level_mv"]) if "dsp__trigger_level_mv" in loaded.files else (self._npz_unpack_value(loaded["trigger_level_mv"]) if "trigger_level_mv" in loaded.files else None),
                        "dso_sr": self._npz_unpack_value(loaded["dsp__dso_sr_gsa"]) if "dsp__dso_sr_gsa" in loaded.files else None,
                        "process_fs": self._npz_unpack_value(loaded["dsp__process_fs_gsa"]) if "dsp__process_fs_gsa" in loaded.files else None,
                        "data_len": self._npz_unpack_value(loaded["dsp__data_length_ksa"]) if "dsp__data_length_ksa" in loaded.files else None,
                        "photocurrent_ma": self._npz_unpack_value(loaded["photocurrent_ma"]) if "photocurrent_ma" in loaded.files else None,
                    }

                self._rx_multi = rx_multi
                if primary_loaded in self._rx_multi:
                    self._set_primary_rx_channel(primary_loaded)
                else:
                    self._set_primary_rx_channel(next(iter(self._rx_multi.keys())))
                self.runtime["latest_rx_signal"] = self._rx_sig
                self.runtime["latest_t"] = self._rx_t
                self.runtime["latest_fs"] = self._rx_fs
                self.runtime["latest_rx_by_channel"] = self._rx_multi
                self.runtime["latest_capture_file"] = str(path)
                self._const_drawn = False
                if payload:
                    self.runtime["tx_payload"] = payload
                    if payload.get("modulation") is not None:
                        gui_vals["mod"] = str(payload.get("modulation"))
                    sr_ref = self._payload_symbol_rate_hz(payload)
                    if_ref = self._payload_if_hz(payload)
                    if sr_ref > 0:
                        gui_vals["sr"] = self._entry_ghz_from_hz(sr_ref, gui_vals.get("sr") or "")
                    if if_ref > 0:
                        gui_vals["fc"] = self._entry_ghz_from_hz(if_ref, gui_vals.get("fc") or "")
                    if payload.get("qam_rrc_beta") is not None:
                        gui_vals["beta"] = str(payload.get("qam_rrc_beta"))
                    if payload.get("qam_rrc_span") is not None:
                        gui_vals["span"] = str(payload.get("qam_rrc_span"))
                    self._log(
                        f"[Acq] Restored TX reference from capture: "
                        f"type={payload.get('waveform_type', 'unknown')} "
                        f"mod={payload.get('modulation', 'unknown')} "
                        f"sr={sr_ref/1e9:.6f} GHz "
                        f"if={if_ref/1e9:.6f} GHz"
                    )

                def update_ui():
                    if gui_vals["fc"] is not None:
                        self.fc_var.set(str(gui_vals["fc"]))
                    if gui_vals["sr"] is not None:
                        self.sr_var.set(str(gui_vals["sr"]))
                    if gui_vals["mod"] is not None:
                        self.demod_mod_var.set(str(gui_vals["mod"]))
                    if gui_vals["beta"] is not None:
                        self.demod_beta_var.set(str(gui_vals["beta"]))
                    if gui_vals["span"] is not None:
                        self.demod_span_var.set(str(gui_vals["span"]))
                    if gui_vals["range_mode"] is not None:
                        self.range_mode_var.set(str(gui_vals["range_mode"]))
                    if gui_vals["demod_lpf"] is not None:
                        self.filter_enable_var.set(bool(int(gui_vals["demod_lpf"])))
                    if gui_vals["sc_fde"] is not None:
                        self.sc_fde_enable_var.set(bool(int(gui_vals["sc_fde"])))
                    if gui_vals["sc_fde_taps"] is not None:
                        self.sc_fde_taps_var.set(str(gui_vals["sc_fde_taps"]))
                    if gui_vals["ch1_scale_mv"] is not None:
                        self.ch1_scale_mv_var.set(str(gui_vals["ch1_scale_mv"]))
                    if gui_vals["ch2_scale_mv"] is not None:
                        self.ch2_scale_mv_var.set(str(gui_vals["ch2_scale_mv"]))
                    if gui_vals["range_target_m"] is not None:
                        self.range_target_m_var.set(str(gui_vals["range_target_m"]))
                    if gui_vals["range_tolerance_m"] is not None:
                        self.range_tolerance_m_var.set(str(gui_vals["range_tolerance_m"]))
                    if gui_vals["auto_sync"] is not None:
                        self.auto_sync_tx_params_var.set(bool(int(gui_vals["auto_sync"])))
                    if gui_vals["trig_ch"] is not None:
                        self.trig_ch_var.set(str(gui_vals["trig_ch"]))
                    if gui_vals["trig_level"] is not None:
                        self.trig_level_mv_var.set(str(gui_vals["trig_level"]))
                    if gui_vals["dso_sr"] is not None and str(gui_vals["dso_sr"]):
                        self.dso_sr_var.set(str(gui_vals["dso_sr"]))
                    if gui_vals["process_fs"] is not None:
                        self.capture_fs_var.set(str(gui_vals["process_fs"]))
                    if gui_vals["data_len"] is not None:
                        self.data_len_ksa_var.set(str(gui_vals["data_len"]))
                    if gui_vals["photocurrent_ma"] is not None:
                        self.photocurrent_ma_var.set(str(gui_vals["photocurrent_ma"]))
                    display_set = set(display_loaded) if display_loaded else set(self._rx_multi.keys())
                    for ch, var in self.channel_select_vars.items():
                        var.set(ch in display_set)
                    if self.ch_var.get().strip().upper() not in self._rx_multi:
                        self.ch_var.set(next(iter(self._rx_multi.keys())))
                    self.live_var.set(False)
                    self._last_loaded_capture_path = str(path)
                    self.runtime["loaded_capture_dsp_state"] = dict(gui_vals)
                    self.capture_file_var.set(f"Capture: {path.name}")
                    self._plot_spectrum_and_time()
                    self._refresh_metrics_table()

                self.parent.after(0, update_ui)
                self._log(f"[Acq] Loaded capture: {path}  N={len(sig):,}, fs={fs/1e9:.3f} GSa/s")
            except Exception as e:
                self._log(f"[Acq] Load error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Load Capture Error", m))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _saved_channel_from_npz(loaded, ch: str) -> tuple[np.ndarray, float]:
        key = ch.strip().upper()
        sig_key = f"rx__{key}__sig"
        fs_key = f"rx__{key}__fs"
        if sig_key in loaded.files and fs_key in loaded.files:
            sig = np.asarray(loaded[sig_key], dtype=np.float64).reshape(-1)
            fs = float(np.asarray(loaded[fs_key]).reshape(-1)[0])
            return sig, fs
        if key == "C1" and "rx_sig" in loaded.files and "rx_fs" in loaded.files:
            sig = np.asarray(loaded["rx_sig"], dtype=np.float64).reshape(-1)
            fs = float(np.asarray(loaded["rx_fs"]).reshape(-1)[0])
            return sig, fs
        raise KeyError(f"{key} waveform was not found in the saved file.")

    def _on_plot_saved_spectrum_figure(self) -> None:
        cap_dir = APP_DIR / "data" / "captures"
        cap_dir.mkdir(parents=True, exist_ok=True)
        path_str = filedialog.askopenfilename(
            title="Load Saved Capture for Paper Spectrum",
            initialdir=str(cap_dir),
            filetypes=[("NumPy capture/range", "*.npz"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            path = Path(path_str)
            with np.load(path, allow_pickle=True) as loaded:
                c1_sig, c1_fs = self._saved_channel_from_npz(loaded, "C1")
                c2_sig, c2_fs = self._saved_channel_from_npz(loaded, "C2")

            fig = Figure(figsize=(6.4, 4.8), dpi=120)
            fig.patch.set_facecolor("white")
            axes = fig.subplots(2, 1, sharex=True)
            fig.subplots_adjust(left=0.28, right=0.98, bottom=0.24, top=0.98, hspace=0.08)

            plot_specs = [
                (axes[0], "C1", c1_sig, c1_fs, (-140.0, -100.0), np.arange(-140.0, -99.0, 10.0)),
                (axes[1], "C2", c2_sig, c2_fs, (-160.0, -120.0), np.arange(-160.0, -120.0, 10.0)),
            ]

            with matplotlib.rc_context({
                "font.family": "Times New Roman",
                "font.size": 26,
                "axes.labelsize": 27,
                "xtick.labelsize": 18,
                "ytick.labelsize": 18,
                "mathtext.fontset": "stix",
            }):
                colors = ["#0400ff", "#ff0000"]
                for idx, (ax, label, sig, fs, ylim, yticks) in enumerate(plot_specs):
                    f_hz, psd_db = self._compute_psd_db(sig, fs)
                    f_ghz = f_hz / 1e9
                    show = np.isfinite(f_ghz) & np.isfinite(psd_db) & (f_ghz >= 0.0) & (f_ghz <= 25.0)
                    ax.plot(f_ghz[show], psd_db[show], color=colors[idx % len(colors)], linewidth=4)
                    ax.set_xlim(0.0, 25.0)
                    ax.set_ylim(*ylim)
                    ax.set_yticks(yticks)
                    ax.set_ylabel("PSD (dBm/Hz)", fontsize= 26, fontname="Times New Roman")
                    ax.grid(True, which="major", color="#b0b7c3", alpha=0.55, linewidth=0.65)
                    ax.grid(True, which="minor", color="#d3d8e0", alpha=0.25, linewidth=0.4)
                    ax.minorticks_on()
                    ax.tick_params(direction="in", top=True, right=True, length=4.5, width=0.85, labelsize=35)
                    ax.tick_params(which="minor", direction="in", top=True, right=True, length=2.5, width=0.65)
                    for tick_label in ax.get_xticklabels() + ax.get_yticklabels():
                        tick_label.set_fontname("Times New Roman")
                        tick_label.set_fontsize(20)
                    for side in ("top", "right", "bottom", "left"):
                        ax.spines[side].set_visible(True)
                        ax.spines[side].set_linewidth(0.95)
                axes[0].tick_params(labelbottom=False)
                axes[1].set_xlabel("Frequency (GHz)", fontsize=37, fontname="Times New Roman")
                axes[1].set_xticks(np.arange(0.0, 25.1, 5.0))

            win = tk.Toplevel(self.parent)
            win.title(f"Paper Spectrum Figure - {path.name}")
            win.geometry("850x700")
            canvas = FigureCanvasTkAgg(fig, master=win)
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

            btn_frame = ttk.Frame(win, padding=8)
            btn_frame.pack(fill=tk.X)
            font_size_var = tk.StringVar(value="35")

            def apply_font_size() -> None:
                try:
                    base = float(font_size_var.get())
                except Exception:
                    base = 35.0
                base = float(np.clip(base, 8.0, 60.0))
                label_size = base + 2.0
                for ax in axes:
                    ax.xaxis.label.set_fontname("Times New Roman")
                    ax.xaxis.label.set_fontsize(label_size)
                    ax.yaxis.label.set_fontname("Times New Roman")
                    ax.yaxis.label.set_fontsize(label_size)
                    ax.tick_params(axis="both", which="major", labelsize=base)
                    for tick_label in ax.get_xticklabels() + ax.get_yticklabels():
                        tick_label.set_fontname("Times New Roman")
                        tick_label.set_fontsize(base)
                left = min(0.38, max(0.16, 0.09 + 0.0052 * label_size))
                bottom = min(0.34, max(0.14, 0.08 + 0.0045 * label_size))
                fig.subplots_adjust(left=left, right=0.98, bottom=bottom, top=0.98, hspace=0.08)
                canvas.draw_idle()

            def save_figure() -> None:
                out = filedialog.asksaveasfilename(
                    parent=win,
                    title="Save Paper Spectrum Figure",
                    initialdir=str(path.parent),
                    initialfile=f"{path.stem}_C1_C2_spectrum.png",
                    defaultextension=".png",
                    filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg"), ("All files", "*.*")],
                )
                if not out:
                    return
                fig.savefig(out, dpi=600, bbox_inches="tight")
                self._log(f"[Paper Spectrum] Saved figure: {out}")

            ttk.Label(btn_frame, text="Font pt").pack(side=tk.LEFT)
            tk.Spinbox(btn_frame, from_=8, to=60, increment=1, textvariable=font_size_var, width=5).pack(side=tk.LEFT, padx=(4, 6))
            ttk.Button(btn_frame, text="Apply", command=apply_font_size).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(btn_frame, text="Save Figure", command=save_figure).pack(side=tk.LEFT)
            ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side=tk.LEFT, padx=(6, 0))
            apply_font_size()
            canvas.draw_idle()
            self._log(f"[Paper Spectrum] Loaded {path.name} and plotted C1/C2 spectra.")
        except Exception as exc:
            messagebox.showerror("Paper Spectrum", str(exc), parent=self.parent)

    def _plot_full_duplex_dashboard(self) -> None:
        if self._rx_sig is None and not self._rx_multi:
            return

        if not self._rx_multi and self._rx_sig is not None:
            ch = self.ch_var.get().strip().upper() or "C1"
            self._rx_multi = {
                ch: {
                    "sig": np.asarray(self._rx_sig, dtype=np.float64),
                    "t": self._rx_t if self._rx_t is not None else np.arange(len(self._rx_sig), dtype=np.float64) / self._rx_fs,
                    "fs": float(self._rx_fs),
                }
            }

        display_channels = self._display_dso_channels()
        if display_channels and display_channels[0] in self._rx_multi:
            self._set_primary_rx_channel(display_channels[0])

        self.ax_time = self.fd_axes[0][0]
        self.ax_spec = self.fd_axes[0][1]
        self.ax_const = self.fd_axes[0][2]
        self.ax_range = self.fd_axes[0][3]

        titles = ("Time", "Spectrum", "Demod", "Range")
        for row in range(2):
            if row >= len(display_channels):
                for col, title in enumerate(titles):
                    ax = self.fd_axes[row][col]
                    ax.cla()
                    ax.set_title(title)
                    ax.text(0.5, 0.5, "No channel selected", ha="center", va="center",
                            transform=ax.transAxes, color="gray")
                    ax.set_axis_off()
                continue

            ch = display_channels[row]
            item = self._rx_multi.get(ch)
            if not item:
                for col, title in enumerate((f"{ch} Time", f"{ch} Spectrum", f"{ch} Demod", f"{ch} Range")):
                    ax = self.fd_axes[row][col]
                    ax.cla()
                    ax.set_title(title)
                    ax.text(0.5, 0.5, "No data", ha="center", va="center",
                            transform=ax.transAxes, color="gray")
                    ax.set_axis_off()
                continue

            sig = np.asarray(item["sig"], dtype=np.float64)
            fs = float(item["fs"])
            if len(sig) == 0 or fs <= 0:
                continue

            ax_time, ax_spec, ax_demod, ax_range = self.fd_axes[row]

            ax_time.cla()
            n_plot = min(len(sig), 4000)
            t_plot = np.arange(n_plot, dtype=np.float64) / fs * 1e9
            sig_plot = sig[:n_plot]
            ax_time.plot(t_plot, sig_plot, linewidth=0.7, color="#16a34a")
            ax_time.set_title(f"{ch} Time")
            ax_time.set_xlabel("Time (ns)")
            ax_time.set_ylabel("Voltage (V)")
            ax_time.set_axis_on()
            ax_time.grid(True, alpha=0.35)
            if n_plot > 0:
                ax_time.set_xlim(t_plot[0], t_plot[-1])
                y_abs_max = float(np.max(np.abs(sig_plot))) * 1.1 or 1.0
                ax_time.set_ylim(-y_abs_max, y_abs_max)

            bw_ghz = self._scope_bw_ghz()
            fmax_ghz = min(25.0, bw_ghz, fs / 2e9)
            f_hz, psd_db = self._compute_psd_db(sig, fs)
            f_ghz = f_hz / 1e9
            mask_disp = f_ghz <= fmax_ghz

            ax_spec.cla()
            ax_spec.plot(f_ghz[mask_disp], psd_db[mask_disp], linewidth=0.8,
                         color="#2563eb", label="Raw")
            ax_spec.set_title(f"{ch} Spectrum [0-25 GHz]")
            ax_spec.set_xlabel("Frequency (GHz)")
            ax_spec.set_ylabel("dBm/Hz")
            ax_spec.set_xlim(0.0, fmax_ghz)
            try:
                fft_offset = float(self.fft_offset_var.get()) - 60.0
                fft_scale = float(self.fft_scale_div_var.get())
                if fft_scale > 0:
                    ax_spec.set_ylim(fft_offset - 8.0 * fft_scale, fft_offset)
            except Exception:
                if np.any(mask_disp):
                    pmax_disp = float(np.max(psd_db[mask_disp]))
                    ax_spec.set_ylim(pmax_disp - 80.0, pmax_disp + 10.0)
            ax_spec.set_axis_on()
            ax_spec.grid(True, alpha=0.35)

            try:
                f1_ghz, f2_ghz = self._get_signal_band_ghz()
                fc_ghz = float(self.fc_var.get())
                band_mask = (f_ghz >= f1_ghz) & (f_ghz <= f2_ghz) & mask_disp
                if bool(self.filter_overlay_var.get()) and np.any(band_mask):
                    # Plot the measured raw PSD inside the analysis band.  Do
                    # not plot a re-filtered waveform here: its hard FFT-mask
                    # edge looks like an artificial spectrum cutoff.
                    ax_spec.plot(f_ghz[band_mask], psd_db[band_mask], linewidth=0.8,
                                 color="#475569", alpha=0.45, label="Band segment")
                ax_spec.axvspan(f1_ghz, f2_ghz, alpha=0.055, color="#f59e0b")
                ax_spec.axvline(f1_ghz, color="#92400e", lw=0.6, alpha=0.55, linestyle=":")
                ax_spec.axvline(f2_ghz, color="#92400e", lw=0.6, alpha=0.55, linestyle=":")
                ax_spec.axvline(fc_ghz, color="#334155", lw=0.7, alpha=0.65, linestyle=":")
                if self._noise_floor_ref_dbmhz is not None:
                    ax_spec.axhline(self._noise_floor_ref_dbmhz, color="#b0280a",
                                    lw=1.0, linestyle="-.")
                ax_spec.legend(fontsize=7)
            except Exception:
                pass

            if row != 0 or not getattr(self, "_const_drawn", False):
                ax_demod.cla()
                ax_demod.text(0.5, 0.5, "Press\n'Demodulate'",
                              ha="center", va="center",
                              transform=ax_demod.transAxes, color="gray")
                ax_demod.set_title(f"{ch} Demod")
                ax_demod.set_axis_on()
                ax_demod.grid(True, alpha=0.25)

            ax_range.cla()
            ax_range.text(0.5, 0.5, "Press\n'Detect Range'",
                          ha="center", va="center",
                          transform=ax_range.transAxes, color="gray")
            ax_range.set_title(f"{ch} Range")
            ax_range.set_axis_on()
            ax_range.grid(True, alpha=0.25)

        self._apply_dashboard_layout()
        self.canvas_plot.draw_idle()

    def _plot_spectrum_and_time(self) -> None:
        self._plot_full_duplex_dashboard()
        return
        if self._rx_sig is None:
            return
        sig = self._rx_sig
        fs  = self._rx_fs

        # Limit display to DSO analog BW
        bw_ghz  = self._scope_bw_ghz()
        fmax_ghz = min(bw_ghz, fs / 2e9)

        f_hz, psd_db = self._compute_psd_db(sig, fs)
        f_ghz = f_hz / 1e9
        mask_disp = f_ghz <= fmax_ghz

        # --- Spectrum ---
        self.ax_spec.cla()
        self.ax_spec.plot(f_ghz[mask_disp], psd_db[mask_disp], linewidth=0.8, color="#2563eb", label="Raw")
        self.ax_spec.set_xlabel("Frequency (GHz)")
        self.ax_spec.set_ylabel("PSD (dBm/Hz)")
        self.ax_spec.set_title(f"Spectrum  [0 - {fmax_ghz:.0f} GHz]")
        self.ax_spec.set_xlim(0.0, fmax_ghz)

        # Apply FFT offset and scale
        try:
            # -60 offset to compensate for DSO calculation difference
            fft_offset = float(self.fft_offset_var.get()) - 60.0
            fft_scale = float(self.fft_scale_div_var.get())
            # For 8 vertical divisions (common in oscilloscopes):
            # The offset now defines the TOP of the Y-axis (Reference Level).
            self.ax_spec.set_ylim(fft_offset - 8.0 * fft_scale, fft_offset)
        except Exception:
            if np.any(mask_disp):
                pmax_disp = float(np.max(psd_db[mask_disp]))
                self.ax_spec.set_ylim(pmax_disp - 80.0, pmax_disp + 10.0)

        self.ax_spec.set_axis_on()
        self.ax_spec.grid(True, alpha=0.4)

        # Band markers derived from signal parameters
        try:
            f1_ghz, f2_ghz = self._get_signal_band_ghz()
            fc_ghz = float(self.fc_var.get())
            band_mask = (f_ghz >= f1_ghz) & (f_ghz <= f2_ghz) & mask_disp
            if bool(self.filter_overlay_var.get()) and np.any(band_mask):
                self.ax_spec.plot(f_ghz[band_mask], psd_db[band_mask], linewidth=0.8,
                                  color="#475569", alpha=0.45, label="Band segment")
            self.ax_spec.axvspan(f1_ghz, f2_ghz, alpha=0.055, color="#f59e0b",
                                 label=f"Signal [{f1_ghz:.2f}-{f2_ghz:.2f} GHz]")
            self.ax_spec.axvline(f1_ghz, color="#92400e", lw=0.7, alpha=0.55, linestyle=":")
            self.ax_spec.axvline(f2_ghz, color="#92400e", lw=0.7, alpha=0.55, linestyle=":")
            self.ax_spec.axvline(fc_ghz, color="#334155", lw=0.8, alpha=0.65, linestyle=":",
                                 label=f"fc={fc_ghz:.2f} GHz")
            idx_fc = np.argmin(np.abs(f_ghz - fc_ghz))
            if mask_disp[idx_fc]:
                psd_fc = psd_db[idx_fc]
                self.ax_spec.plot(fc_ghz, psd_fc, 'ro', markersize=4)
                self.ax_spec.annotate(f"{psd_fc:.1f} dBm/Hz", (fc_ghz, psd_fc),
                                      textcoords="offset points", xytext=(0, 6),
                                      ha='center', color='red', fontsize=8, fontweight='bold')
            # Stored noise floor reference line
            if self._noise_floor_ref_dbmhz is not None:
                self.ax_spec.axhline(self._noise_floor_ref_dbmhz, color="#b0280a",
                                     lw=1.2, linestyle="-.",
                                     label=f"NF ref={self._noise_floor_ref_dbmhz:.1f} dBm/Hz")
            self.ax_spec.legend(fontsize=8)
        except Exception:
            pass

        # --- Time waveform ---
        self.ax_time.cla()
        n_plot = min(len(sig), 4000)
        t_plot = (np.arange(n_plot) / fs) * 1e9
        self.ax_time.plot(t_plot, sig[:n_plot], linewidth=0.7, color="#16a34a")
        self.ax_time.set_xlabel("Time (ns)")
        self.ax_time.set_ylabel("Amplitude (V)")
        self.ax_time.set_title("Time Waveform")
        self.ax_time.set_axis_on()
        self.ax_time.grid(True, alpha=0.4)

        # --- Constellation (keep existing or show placeholder) ---
        if not hasattr(self, "_const_drawn") or not self._const_drawn:
            self.ax_const.cla()
            self.ax_const.text(0.5, 0.5, "Press\n'Demodulate'",
                               ha="center", va="center",
                               transform=self.ax_const.transAxes, color="gray")
            self.ax_const.set_title("Constellation")
            self.ax_const.set_axis_on()
            self.ax_const.grid(True, alpha=0.3)

        self._apply_dashboard_layout()
        self.canvas_plot.draw_idle()

    def _on_measure_noise_floor(self) -> None:
        """Store real DSO noise density from the out-of-band region of the current capture."""
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire a signal first (ideally with no signal connected).")
            return
        try:
            sig = self._rx_sig
            fs  = self._rx_fs
            bw_ghz = self._scope_bw_ghz()

            f_hz, psd_db = self._compute_psd_db(sig, fs)
            f_ghz  = f_hz / 1e9
            psd_lin = 10.0 ** (psd_db / 10.0)

            try:
                f1_ghz, f2_ghz = self._get_signal_band_ghz()
                mask_noise = (~((f_ghz >= f1_ghz) & (f_ghz <= f2_ghz))) & (f_ghz > 0.5) & (f_ghz <= bw_ghz)
            except Exception:
                mask_noise = (f_ghz > 0.5) & (f_ghz <= bw_ghz)

            if not np.any(mask_noise):
                messagebox.showwarning("Error", "Could not find out-of-band noise region.")
                return

            nf_mwhz = float(np.median(psd_lin[mask_noise]))
            self._noise_floor_ref_dbmhz = 10.0 * np.log10(max(nf_mwhz, 1e-30))
            self._const_drawn = False

            self.noise_floor_var.set(f"Noise Density: {self._noise_floor_ref_dbmhz:.1f} dBm/Hz  [stored]")
            self._set_metric("noise_floor_dbmhz", "Noise Density", self._noise_floor_ref_dbmhz, "dBm/Hz")
            self._refresh_metrics_table()
            self._log(f"[NF] DSO noise density stored: {self._noise_floor_ref_dbmhz:.1f} dBm/Hz")
            self._plot_spectrum_and_time()   # redraw with NF reference line
            messagebox.showinfo("Noise Floor Stored",
                f"DSO Noise Density: {self._noise_floor_ref_dbmhz:.1f} dBm/Hz\n"
                "(out-of-band median from current capture)\n\n"
                "This PSD density is integrated over the analysis band for Noise Power and SNR.")
        except Exception as e:
            messagebox.showerror("Noise Floor Error", str(e))

    def _on_measure_band(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire a signal first.")
            return
        try:
            f1_ghz, f2_ghz = self._get_signal_band_ghz()
            if f1_ghz >= f2_ghz:
                raise ValueError("Invalid band: check Carrier Freq and Symbol Rate.")

            sig    = self._rx_sig
            fs     = self._rx_fs
            bw_ghz = self._scope_bw_ghz()

            f_hz, psd_db = self._compute_psd_db(sig, fs)
            f_ghz   = f_hz / 1e9
            psd_lin = 10.0 ** (psd_db / 10.0)   # mW/Hz

            # Signal band power
            mask_sig = (f_ghz >= f1_ghz) & (f_ghz <= f2_ghz)
            if not np.any(mask_sig):
                raise ValueError(f"Band [{f1_ghz:.2f}-{f2_ghz:.2f} GHz] outside signal bandwidth.")
            df       = float(f_hz[1] - f_hz[0])
            p_sig_mw  = float(np.sum(psd_lin[mask_sig])) * df
            p_sig_dbm = 10.0 * np.log10(max(p_sig_mw, 1e-30))

            # Noise: prefer stored reference, otherwise measure out-of-band
            mask_noise = (~mask_sig) & (f_ghz > 0.5) & (f_ghz <= bw_ghz)
            if not np.any(mask_noise):
                mask_noise = ~mask_sig & (f_ghz > 0)

            if self._noise_floor_ref_dbmhz is not None:
                # Use stored DSO noise floor reference
                nf_mwhz    = 10.0 ** (self._noise_floor_ref_dbmhz / 10.0)
                nf_label   = f"{self._noise_floor_ref_dbmhz:.1f} dBm/Hz  [stored ref]"
            elif np.any(mask_noise):
                # Measure from out-of-band region of current signal
                nf_mwhz  = float(np.median(psd_lin[mask_noise]))
                nf_label = f"{10.0*np.log10(max(nf_mwhz,1e-30)):.1f} dBm/Hz  [from capture]"
            else:
                nf_mwhz  = 1e-30
                nf_label = "N/A"

            bw_sig_hz    = (f2_ghz - f1_ghz) * 1e9
            p_noise_mw   = nf_mwhz * bw_sig_hz
            p_noise_dbm  = 10.0 * np.log10(max(p_noise_mw, 1e-30))

            p_sig_true_mw = max(p_sig_mw - p_noise_mw, 1e-30)
            p_sig_true_dbm = 10.0 * np.log10(p_sig_true_mw)

            snr_db       = 10.0 * np.log10(max(p_sig_true_mw / max(p_noise_mw, 1e-30), 1e-30))

            self.band_pwr_var.set(f"Band Power:  {p_sig_true_dbm:.2f} dBm")
            self.noise_floor_var.set(f"Noise Density: {nf_label}; Noise Power: {p_noise_dbm:.2f} dBm")
            self.snr_var.set(f"Band SNR:    {snr_db:.2f} dB")
            nf_dbmhz = 10.0 * np.log10(max(nf_mwhz, 1e-30))
            self._set_metric("band_power_dbm", "Band Power", p_sig_true_dbm, "dBm")
            self._set_metric("noise_floor_dbmhz", "Noise Density", nf_dbmhz, "dBm/Hz")
            self._set_metric("noise_power_dbm", "Noise Power", p_noise_dbm, "dBm")
            self._set_metric("snr_com_db", "Band SNR", snr_db, "dB")
            self._set_metric(
                "sinr_com_db", "SINR_com", snr_db, "dB",
                "No separate clutter/interference estimate; using band-power diagnostic."
            )
            self._refresh_metrics_table()

            self._log(f"[Meas] fc={float(self.fc_var.get()):.2f} GHz  "
                      f"sr={float(self.sr_var.get()):.3f} GHz -> "
                      f"Praw={p_sig_dbm:.2f} dBm  Psig={p_sig_true_dbm:.2f} dBm  "
                      f"N={p_noise_dbm:.2f} dBm  N0={nf_label}  SNR={snr_db:.2f} dB")

            self._const_drawn = False
            self._plot_spectrum_and_time()
        except Exception as e:
            messagebox.showerror("Measure Error", str(e))

    def _load_tx_payload_for_isac(self) -> dict | None:
        payload = self.runtime.get("tx_payload")
        if payload is not None:
            return payload
        ref_path = APP_DIR / "data" / "current_tx_ref.npz"
        if not ref_path.exists():
            return None
        loaded = np.load(ref_path, allow_pickle=True)
        payload = {}
        for key in loaded.files:
            val = loaded[key]
            if val.shape == (1,):
                payload[key] = val[0].item() if hasattr(val[0], "item") else val[0]
            else:
                payload[key] = val
        self.runtime["tx_payload"] = payload
        return payload

    @staticmethod
    def _entry_ghz_from_hz(value_hz: float, fallback: str = "") -> str:
        try:
            v = float(value_hz)
            if np.isfinite(v) and v > 0:
                return f"{v / 1e9:.9f}".rstrip("0").rstrip(".")
        except Exception:
            pass
        return str(fallback)

    @staticmethod
    def _payload_symbol_rate_hz(pl: dict) -> float:
        try:
            return float(pl.get("symbol_rate_actual", pl.get("symbol_rate", 0.0)))
        except Exception:
            return 0.0

    @staticmethod
    def _payload_if_hz(pl: dict) -> float:
        try:
            return float(pl.get("if_freq", pl.get("if_freq_requested", 0.0)))
        except Exception:
            return 0.0

    def _can_auto_sync_dsp_from_payload(self) -> bool:
        """Only offline/loaded captures should silently adopt stored TX refs."""
        try:
            if not bool(self.auto_sync_tx_params_var.get()):
                return False
            if self._last_loaded_capture_path:
                return True
            return not bool(self.live_var.get())
        except Exception:
            return False

    def _sync_dsp_params_from_payload(self, pl: dict, source: str = "TX reference", force: bool = False) -> None:
        """Make the DSO DSP controls mirror the actual TX reference."""
        if not pl:
            return
        if not force and not self._can_auto_sync_dsp_from_payload():
            return
        sr_hz = self._payload_symbol_rate_hz(pl)
        if_hz = self._payload_if_hz(pl)
        mod = str(pl.get("modulation", "")).strip()
        beta = pl.get("qam_rrc_beta", None)
        span = pl.get("qam_rrc_span", None)
        if if_hz > 0:
            self.fc_var.set(self._entry_ghz_from_hz(if_hz, self.fc_var.get()))
        if sr_hz > 0:
            self.sr_var.set(self._entry_ghz_from_hz(sr_hz, self.sr_var.get()))
        if mod:
            self.demod_mod_var.set(mod)
        try:
            beta_f = float(beta)
            if np.isfinite(beta_f):
                self.demod_beta_var.set(f"{beta_f:.4f}".rstrip("0").rstrip("."))
        except Exception:
            pass
        try:
            span_i = int(span)
            if span_i > 0:
                self.demod_span_var.set(str(span_i))
        except Exception:
            pass
        self._update_band_label()
        self._log(
            f"[DSP] Synced DSO DSP from {source}: "
            f"IF={if_hz/1e9:.6f} GHz, SR={sr_hz/1e9:.6f} GHz, "
            f"mod={mod or 'unknown'}."
        )

    def _dsp_payload_mismatch_details(self, pl: dict) -> list[str]:
        details: list[str] = []
        if not pl:
            return details
        try:
            sr_ref = self._payload_symbol_rate_hz(pl)
            sr_ui = float(self.sr_var.get()) * 1e9
            if sr_ref > 0 and sr_ui > 0:
                tol = max(5.0e6, 5.0e-4 * max(sr_ref, sr_ui))
                if abs(sr_ref - sr_ui) > tol:
                    details.append(f"symbol-rate ref={sr_ref/1e9:.6f} GHz, GUI={sr_ui/1e9:.6f} GHz")
        except Exception:
            pass
        try:
            if_ref = self._payload_if_hz(pl)
            if_ui = float(self.fc_var.get()) * 1e9
            if if_ref > 0 and if_ui > 0:
                tol = max(2.0e6, 5.0e-4 * max(if_ref, if_ui))
                if abs(if_ref - if_ui) > tol:
                    details.append(f"IF ref={if_ref/1e9:.6f} GHz, GUI={if_ui/1e9:.6f} GHz")
        except Exception:
            pass
        try:
            mod_ref = str(pl.get("modulation", "")).strip().upper()
            mod_ui = str(self.demod_mod_var.get()).strip().upper()
            if mod_ref and mod_ui and mod_ref != mod_ui:
                details.append(f"modulation ref={mod_ref}, GUI={mod_ui}")
        except Exception:
            pass
        return details

    def _assert_dsp_payload_consistent(self, pl: dict, context: str = "analysis") -> None:
        details = self._dsp_payload_mismatch_details(pl)
        if not details:
            return
        if self._can_auto_sync_dsp_from_payload():
            self._sync_dsp_params_from_payload(pl, source=f"{context} TX reference", force=True)
            details = self._dsp_payload_mismatch_details(pl)
            if not details:
                return
        capture_hint = ""
        if self._last_loaded_capture_path:
            capture_hint = f"\nLoaded capture: {Path(self._last_loaded_capture_path).name}"
        raise ValueError(
            "DSO DSP settings do not match the TX reference/capture.\n"
            + "\n".join(f"- {d}" for d in details)
            + capture_hint
            + "\n\nIn Live DSO mode this usually means the AWG panel was changed after the "
            "current TX reference was generated. Regenerate/download the AWG waveform and "
            "reacquire, or load the matching capture."
        )

    def _warn_if_tx_reference_stale(self, pl: dict) -> None:
        """The Symbol Rate/Modulation/Carrier-IF fields on this tab are display
        mirrors of the TX Design tab (see UnifiedApp._sync_dso_from_awg_panel)
        -- editing them here does not regenerate or re-download anything, so
        the cached TX reference (`self.runtime["tx_payload"]`, set only when
        Generate/Download runs on the TX tab) can silently go stale relative
        to what this tab now shows or what's actually loaded on the AWG.
        That mismatch surfaces downstream as a mysterious "no lock" demod
        error or a Range Profile with no peak, so warn loudly here instead.
        """
        try:
            sr_act = float(pl.get("symbol_rate_actual", pl.get("symbol_rate", 0.0)))
            sr_expected = float(self.sr_var.get()) * 1e9
            if sr_act > 0 and sr_expected > 0 and abs(sr_act - sr_expected) > 0.02 * max(sr_act, sr_expected):
                self._log(
                    f"[TX-ref] WARNING: loaded TX reference symbol rate ({sr_act/1e9:.3f} GHz) "
                    f"does not match this tab's Symbol Rate field ({sr_expected/1e9:.3f} GHz) -- "
                    "this reference is STALE. Go to 'TX Design & Simulation', set the rate you "
                    "want, click Generate (and Download to AWG + Run if using live hardware), "
                    "then re-acquire before demodulating or running ISAC range analysis."
                )
        except Exception:
            pass
        try:
            mod_act = str(pl.get("modulation", "")).strip().upper()
            mod_expected = str(self.demod_mod_var.get()).strip().upper()
            if mod_act and mod_expected and mod_act != mod_expected:
                self._log(
                    f"[TX-ref] WARNING: loaded TX reference modulation ({mod_act}) differs from "
                    f"this tab's Modulation field ({mod_expected}) -- this reference may be stale."
                )
        except Exception:
            pass
        try:
            if_act = float(pl.get("if_freq_requested", pl.get("if_freq", 0.0)))
            if_expected = float(self.fc_var.get()) * 1e9
            if if_act > 0 and if_expected > 0 and abs(if_act - if_expected) > 0.02 * max(if_act, if_expected):
                self._log(
                    f"[TX-ref] WARNING: loaded TX reference IF ({if_act/1e9:.3f} GHz) differs from "
                    f"this tab's Carrier/IF field ({if_expected/1e9:.3f} GHz) -- this reference may be stale."
                )
        except Exception:
            pass

    def _ensure_qam_reference_modulation(self, pl: dict, requested_mod: str) -> dict:
        """Rebuild deterministic QAM symbol reference when DSO UI modulation differs."""
        if str(pl.get("waveform_type", "")).strip() != "QAM":
            return pl
        mod = str(requested_mod).strip().upper()
        if not mod:
            return pl
        current_mod = str(pl.get("modulation", "")).strip().upper()
        if current_mod == mod and "tx_sym_matrix" in pl:
            return pl

        n_chirps = int(pl.get("n_chirps", 1))
        n_sym_per_chirp = int(pl.get("n_sym_per_chirp", 1024))
        qam_preamble_len = int(pl.get(
            "qam_preamble_len",
            min(64, max(16, n_sym_per_chirp // 8)),
        ))
        qam_preamble_len = max(8, min(qam_preamble_len, n_sym_per_chirp - 1))
        data_len = n_sym_per_chirp - qam_preamble_len
        prbs_n = int(pl.get("prbs_n", 11))

        bps = _bits_per_symbol(mod)
        data_needed = n_chirps * data_len
        bits = _prbs_bits_lfsr(prbs_n, data_needed * bps)
        qam_data_symbols = _bits_to_qam_symbols(bits, modulation=mod)[:data_needed]

        qam_preamble_symbols = np.asarray(
            generate_zadoff_chu(qam_preamble_len, u=1),
            dtype=np.complex128,
        )
        qam_data = qam_data_symbols.reshape(n_chirps, data_len)
        tx_sym_matrix = np.concatenate([
            np.tile(qam_preamble_symbols, (n_chirps, 1)),
            qam_data,
        ], axis=1)

        nps = int(pl.get("sps", 1))
        beta = float(pl.get("qam_rrc_beta", 0.20))
        span = int(pl.get("qam_rrc_span", 8))
        qam_rrc_taps = np.asarray(pl.get("qam_rrc_taps", []), dtype=np.float64).reshape(-1)
        if len(qam_rrc_taps) < 3:
            qam_rrc_taps = IsacTxSimPanel._rrc_taps(nps, beta=beta, span=span)

        rebuilt = dict(pl)
        rebuilt.update({
            "modulation": mod,
            "prbs_n": prbs_n,
            "qam_symbols": tx_sym_matrix.reshape(-1),
            "tx_sym_matrix": tx_sym_matrix,
            "qam_preamble_len": qam_preamble_len,
            "qam_preamble_symbols": qam_preamble_symbols,
            "qam_rrc_taps": qam_rrc_taps,
        })
        self.runtime["tx_payload"] = rebuilt
        self._log(
            f"[Demod] Rebuilt deterministic {mod} PRBS{prbs_n} reference "
            f"from DSO modulation setting (saved ref was {current_mod or 'unknown'})."
        )
        return rebuilt

    @staticmethod
    def _lpf_fft_bb(sig: np.ndarray, fs: float, cutoff_hz: float) -> np.ndarray:
        x = np.asarray(sig, dtype=np.complex128)
        if len(x) == 0:
            return x
        if fs <= 0 or cutoff_hz <= 0:
            return x

        # The previous 101-tap FIR was far too short for 1 GHz-class
        # baseband filtering at 120 GS/s and could distort the RRC eye.  Use a
        # zero-phase FFT mask with a raised-cosine transition instead.
        n = len(x)
        pass_hz = min(float(cutoff_hz), 0.45 * float(fs))
        trans_hz = min(
            max(0.35 * pass_hz, 0.25e9),
            max(1.0, 0.48 * float(fs) - pass_hz),
        )
        stop_hz = min(0.49 * float(fs), pass_hz + trans_hz)
        freqs = np.fft.fftfreq(n, d=1.0 / float(fs))
        af = np.abs(freqs)
        mask = np.ones(n, dtype=np.float64)
        mask[af >= stop_hz] = 0.0
        tr = (af > pass_hz) & (af < stop_hz)
        if np.any(tr):
            u = (af[tr] - pass_hz) / max(stop_hz - pass_hz, 1.0)
            mask[tr] = 0.5 * (1.0 + np.cos(np.pi * u))
        return np.fft.ifft(np.fft.fft(x) * mask).astype(np.complex128)

    def _rx_to_baseband(
        self,
        sig: np.ndarray,
        fs_rx: float,
        pl: dict,
        apply_lpf: bool = True,
        sideband_sign: int = -1,
        conjugate_output: bool = False,
    ) -> tuple[np.ndarray, float]:
        """Down-convert from IF to baseband, then resample and LPF."""
        fs_ref = float(pl.get("fs", fs_rx))
        if_req = float(pl.get("if_freq", 0.0))
        if_grid = float(pl.get("iqtools_if_freq", if_req))
        if_freq = if_grid if if_grid > 0 else if_req
        sym_rate = float(pl.get("symbol_rate_actual", pl.get("symbol_rate", pl.get("B", 1e9))))
        waveform_type = str(pl.get("waveform_type", "")).strip()
        rrc_beta = float(pl.get("qam_rrc_beta", 0.20))

        sig_in = np.asarray(sig, dtype=np.float64)
        sig_in = sig_in - float(np.mean(sig_in)) if len(sig_in) else sig_in
        t_rx = np.arange(len(sig_in), dtype=np.float64) / fs_rx

        # 1. Complex Downconversion at native DSO rate
        mix_sign = -1 if int(sideband_sign) < 0 else 1
        if if_freq > 0:
            rx_bb_high = sig_in * np.exp(1j * mix_sign * 2.0 * np.pi * if_freq * t_rx) * 2.0
        else:
            rx_bb_high = sig_in.astype(np.complex128)

        # 2. Resample / Downsample to reference rate
        if not np.isclose(fs_rx, fs_ref, rtol=1e-4):
            rx_bb = fft_resample_complex(rx_bb_high, fs_in=fs_rx, fs_out=fs_ref)
        else:
            rx_bb = rx_bb_high

        # 3. Optional LPF: removes the negative-frequency image (Real IF mode)
        #    and suppresses wideband noise before AGC normalization.  For QAM,
        #    the receive RRC matched filter is the primary demod filter, so this
        #    pre-filter must be wider than the occupied RRC band.
        if apply_lpf and sym_rate > 0:
            if waveform_type == "QAM":
                one_sided_rrc_bw = 0.5 * sym_rate * (1.0 + np.clip(rrc_beta, 0.0, 1.0))
                cutoff = min(max(1.60 * sym_rate, 2.25 * one_sided_rrc_bw), fs_ref * 0.45)
            elif waveform_type == "LFM-QAM":
                # Shared LFM-QAM uses zero-order-held symbols on top of the
                # chirp, so keep enough bandwidth for both sweep and symbol
                # transitions instead of applying a narrow RRC-derived mask.
                chirp_half_bw = 0.5 * float(pl.get("B", sym_rate))
                occupied_one_sided = chirp_half_bw + sym_rate
                cutoff = min(max(1.5 * sym_rate, 1.15 * occupied_one_sided), fs_ref * 0.45)
            elif waveform_type == "DFT-s-OFDM":
                # DFT-s-OFDM occupies the active IFFT bins.  Use the TX
                # reference metadata when available so high-symbol-rate cases
                # such as 17.5 GBd follow the AWG grid exactly.
                try:
                    n_fft = int(pl.get("dft_n_fft", 0))
                    n_active = len(np.asarray(pl.get("dft_active_bins", []), dtype=np.int64).reshape(-1))
                    occupied_bw = fs_ref * n_active / n_fft if n_fft > 0 and n_active > 0 else sym_rate
                except Exception:
                    occupied_bw = sym_rate
                cutoff = min(0.65 * occupied_bw, fs_ref * 0.45)
            else:
                cutoff = min(1.2 * sym_rate, fs_ref * 0.45)
            rx_bb = self._lpf_fft_bb(rx_bb, fs_ref, cutoff)

        # 4. AGC (Automatic Gain Control)
        # Normalize the baseband signal to RMS = 1.0 so that Gardner and slicer thresholds work reliably
        rms_bb = float(np.sqrt(np.mean(np.abs(rx_bb) ** 2)))
        if rms_bb > 1e-15:
            rx_bb /= rms_bb
        if conjugate_output:
            rx_bb = np.conj(rx_bb)

        return rx_bb, fs_ref

    @staticmethod
    def _raw_awg_waveform_lock_probe(sig: np.ndarray, fs_rx: float, pl: dict) -> tuple[float, int, int]:
        """Normalized raw-IF correlation against the downloaded AWG waveform."""
        rx = np.asarray(sig, dtype=np.float64).reshape(-1)
        awg = np.asarray(pl.get("awg_sig", []), dtype=np.float64).reshape(-1)
        fs_awg = float(pl.get("fs", 0.0))
        if len(rx) < 1024 or len(awg) < 1024 or fs_rx <= 0 or fs_awg <= 0:
            return 0.0, 0, 0
        try:
            if not np.isclose(fs_awg, fs_rx, rtol=1e-5):
                tmpl = np.real(fft_resample_complex(awg, fs_in=fs_awg, fs_out=fs_rx))
            else:
                tmpl = awg.astype(np.float64, copy=True)
        except Exception:
            return 0.0, 0, 0
        if len(tmpl) < 1024:
            return 0.0, 0, 0

        # Use a short enough window to avoid clock-drift decorrelation, while
        # still spanning many QPSK symbols.
        n_tmpl = min(len(tmpl), max(4096, int(round(0.8e-6 * fs_rx))))
        tmpl = tmpl[:n_tmpl]
        # Search the full capture, but decimate if needed so the correlation
        # remains tractable on long records with a large pre-trigger margin.
        stride = max(1, int(np.ceil(max(len(tmpl), len(rx)) / 250000)))
        if stride > 1:
            tmpl = tmpl[::stride]
            rx = rx[::stride]
        if len(rx) < len(tmpl) or len(tmpl) < 256:
            return 0.0, 0, len(tmpl)

        tmpl = tmpl - float(np.mean(tmpl))
        rx = rx - float(np.mean(rx))
        et = float(np.vdot(tmpl, tmpl).real)
        if et <= 1e-20:
            return 0.0, 0, len(tmpl)
        corr = np.abs(fftconvolve(rx, tmpl[::-1], mode="valid"))
        er = np.convolve(rx * rx, np.ones(len(tmpl), dtype=np.float64), mode="valid")
        score = corr / np.sqrt(et * er + 1e-30)
        peak = int(np.argmax(score)) if len(score) else 0
        return float(score[peak]) if len(score) else 0.0, int(peak * stride), int(len(tmpl) * stride)

    def _frame_sync_and_reshape(self, rx_bb: np.ndarray, fs_ref: float, pl: dict):
        """Cross-correlate against the known TX reference and reshape frames."""
        waveform_type = str(pl.get("waveform_type", "unknown")).strip()
        tx_bb_matrix = np.asarray(pl.get("tx_bb_matrix", []), dtype=np.complex128)
        tx_sym_matrix = np.asarray(pl.get("tx_sym_matrix", []), dtype=np.complex128)
        base_chirp = np.asarray(pl.get("base_chirp", []), dtype=np.complex128).reshape(-1)
        n_chirps = int(pl.get("n_chirps", tx_bb_matrix.shape[0] if tx_bb_matrix.ndim == 2 else 1))
        n_sym = int(pl.get("n_sym_per_chirp", 0))
        nps = int(pl.get("sps", 1))
        pts_per_chirp = n_sym * nps
        if pts_per_chirp <= 0 or tx_bb_matrix.ndim != 2:
            raise ValueError("TX reference is incomplete. Regenerate the TX signal.")

        # Use the known TX reference for frame sync.  DFT-s-OFDM has a
        # repeated pilot in every block, so a one-block template can lock to a
        # later block and leave too little record for BER/EVM.  When the
        # capture is long enough, use the full known frame to identify row 0.
        template = tx_bb_matrix[0]
        template_label = "row0"
        if waveform_type == "DFT-s-OFDM":
            try:
                full_template = tx_bb_matrix.reshape(-1)
                if len(full_template) > len(template) and len(rx_bb) > len(full_template) + 16:
                    template = full_template
                    template_label = "full-frame"
            except Exception:
                pass
        if len(rx_bb) > len(template):
            corr = np.abs(fftconvolve(rx_bb, np.conj(template[::-1]), mode="valid"))
            frame_start = int(np.argmax(corr))
            _corr_snr = float(corr[frame_start]) / (float(np.mean(corr)) + 1e-15)
            self._log(
                f"[Sync] {waveform_type} sync: frame_start={frame_start:,}  "
                f"corr_peak/mean={_corr_snr:.1f}x  template={template_label}"
            )
        else:
            frame_start = 0

        valid_chirps = min(n_chirps, max(1, (len(rx_bb) - frame_start) // pts_per_chirp))
        if valid_chirps < n_chirps:
            tx_bb_matrix = tx_bb_matrix[:valid_chirps]
            tx_sym_matrix = tx_sym_matrix[:valid_chirps]
            n_chirps = valid_chirps

        total_pts = n_chirps * pts_per_chirp

        # The AWG and the scope free-run on independent clocks (no shared
        # 10 MHz reference here), so the receiver sample grid drifts away
        # from the assumed integer nps spacing over the length of the
        # capture.  Dechirping multiplies by a deterministic phase ramp, so
        # this drift turns into a residual sweep that silently destroys EVM
        # on later chirps even though the cabled-link SNR is excellent.
        # Refine (start, sample-rate-offset) against the fully known TX
        # baseband reference before slicing into chirp rows.
        tx_ref_full = tx_bb_matrix.reshape(-1)[:total_pts]
        refined_start, sro_ppm, sro_cfo_hz, sro_score = self._refine_lfm_frame_sro(
            rx_bb, frame_start, tx_ref_full, fs=fs_ref
        )
        # A weak score here usually means there is still residual CFO/SRO
        # that the fit couldn't explain (or this capture's preamble lock
        # itself was marginal) -- applying a low-confidence correction can
        # make things worse than the raw integer-sample slice, so require a
        # real majority-of-power lock before trusting it.
        rx_frame = None
        if sro_score > 0.35:
            step = 1.0 + sro_ppm * 1e-6
            idx_full = np.arange(total_pts, dtype=np.float64)
            rx_frame = self._sample_fractional_symbol_indices(
                rx_bb,
                frame_start_sample=refined_start,
                step_samples=step,
                symbol_indices=idx_full,
                cfo_hz=sro_cfo_hz,
                fs=fs_ref,
            )
            if len(rx_frame) != total_pts:
                rx_frame = None
            else:
                self._log(
                    f"[Sync] {waveform_type} SRO refine: start={refined_start:.2f}  "
                    f"sro={sro_ppm:.2f} ppm  cfo={sro_cfo_hz/1e3:.2f} kHz  "
                    f"score={sro_score:.3f}"
                )
        if rx_frame is None:
            self._log(
                f"[Sync] {waveform_type} SRO refine: low confidence "
                f"(score={sro_score:.3f}, sro={sro_ppm:.2f} ppm, "
                f"cfo={sro_cfo_hz/1e3:.2f} kHz); using raw integer-sample frame."
            )
            rx_frame = rx_bb[frame_start: frame_start + total_pts]
            if len(rx_frame) < total_pts:
                rx_frame = np.pad(rx_frame, (0, total_pts - len(rx_frame)))
        rx_mat = rx_frame.reshape(n_chirps, pts_per_chirp)
        return rx_mat, tx_bb_matrix, tx_sym_matrix, base_chirp, n_chirps, n_sym, nps, pts_per_chirp, frame_start

    @staticmethod
    def _range_mode_for_row(row: int) -> str:
        return "One-way LOS (c)" if int(row) == 0 else "Monostatic sensing (c/2)"

    @staticmethod
    def _range_row_for_channel(ch_label: str, row: int) -> int:
        ch = str(ch_label or "").strip().upper()
        if ch == "C2":
            return 1
        if ch == "C1":
            return 0
        return int(row)

    def _range_delay_scale_m_per_s(self, mode: str | None = None, row: int | None = None) -> float:
        if mode is None and row is not None:
            mode = self._range_mode_for_row(row)
        mode = (mode or self.range_mode_var.get()).strip().lower()
        return 3e8 / 2.0 if "monostatic" in mode or "c/2" in mode else 3e8

    @staticmethod
    def _estimate_lfm_cfr(rx_mat: np.ndarray, tx_mat: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rx = np.asarray(rx_mat, dtype=np.complex128)
        tx = np.asarray(tx_mat, dtype=np.complex128)
        n_rows = min(rx.shape[0] if rx.ndim == 2 else 0, tx.shape[0] if tx.ndim == 2 else 0)
        if n_rows <= 0:
            return np.zeros(0), np.zeros(0, dtype=np.complex128), np.zeros(0)
        n = min(rx.shape[1], tx.shape[1])
        if n < 16 or fs <= 0:
            return np.zeros(0), np.zeros(0, dtype=np.complex128), np.zeros(0)
        rx = rx[:n_rows, :n]
        tx = tx[:n_rows, :n]
        win = np.hanning(n).astype(np.float64)
        rx_f = np.fft.fft(rx * win[np.newaxis, :], axis=1)
        tx_f = np.fft.fft(tx * win[np.newaxis, :], axis=1)
        sxx = np.sum(np.abs(tx_f) ** 2, axis=0)
        h = np.sum(rx_f * np.conj(tx_f), axis=0) / (sxx + 1e-15)
        freqs = np.fft.fftfreq(n, d=1.0 / float(fs))
        power = sxx / (float(np.max(sxx)) + 1e-15)
        mask = power > 1e-3
        if np.count_nonzero(mask) < 16:
            mask = power > 1e-4
        idx = np.argsort(freqs[mask])
        return freqs[mask][idx], h[mask][idx], power[mask][idx]

    @staticmethod
    def _dfts_ofdm_pilot_matrix(pl: dict, n_rows: int) -> np.ndarray | None:
        if str(pl.get("waveform_type", "")).strip() != "DFT-s-OFDM":
            return None
        pilot = np.asarray(pl.get("dft_zc_pilot", []), dtype=np.complex128).reshape(-1)
        if len(pilot) < 16:
            return None
        rho = float(np.clip(float(pl.get("amplitude_ratio_rho", 0.20)), 0.0, 0.95))
        modulation = str(pl.get("modulation", "16QAM")).strip()
        pilot = np.sqrt(max(rho, 1e-12)) * pilot
        return np.tile(pilot[np.newaxis, :], (max(1, int(n_rows)), 1))

    @staticmethod
    def _recover_dfts_ofdm_symbols(rx_mat: np.ndarray, pl: dict) -> tuple[np.ndarray, np.ndarray, dict]:
        rx = np.asarray(rx_mat, dtype=np.complex128)
        tx_sym = np.asarray(pl.get("tx_sym_matrix", []), dtype=np.complex128)
        tx_ref = np.asarray(pl.get("tx_bb_matrix", []), dtype=np.complex128)
        active_bins = np.asarray(pl.get("dft_active_bins", []), dtype=np.int64).reshape(-1)
        pilot = np.asarray(pl.get("dft_zc_pilot", []), dtype=np.complex128).reshape(-1)
        scales = np.asarray(pl.get("dft_data_scale", []), dtype=np.float64).reshape(-1)
        n_fft = int(pl.get("dft_n_fft", len(pilot)))
        n_data = int(pl.get("dft_n_data", len(active_bins)))
        rho = float(np.clip(float(pl.get("amplitude_ratio_rho", 0.20)), 0.0, 0.95))
        modulation = str(pl.get("modulation", "16QAM")).strip()

        if rx.ndim != 2 or tx_sym.ndim != 2:
            raise ValueError("DFT-s-OFDM TX/RX reference is incomplete.")
        if n_fft <= 0 or n_data <= 0 or len(active_bins) != n_data or len(pilot) != n_fft:
            raise ValueError("DFT-s-OFDM pilot/subcarrier reference is incomplete.")

        n_rows = min(rx.shape[0], tx_sym.shape[0])
        if tx_ref.ndim == 2:
            n_rows = min(n_rows, tx_ref.shape[0])
        if n_rows <= 0:
            raise ValueError("No complete DFT-s-OFDM blocks are available.")

        sr = np.sqrt(max(rho, 1e-12))
        sd = np.sqrt(max(1.0 - rho, 1e-12))
        pilot_component = sr * pilot
        pilot_energy = float(np.vdot(pilot_component, pilot_component).real) + 1e-15
        pilot_active = sr * np.fft.fft(pilot)[active_bins]
        fs_awg = float(pl.get("fs", 0.0))
        cfo_search_hz = max(1.0e6, min(12.0e6, 0.004 * float(pl.get("symbol_rate_actual", pl.get("symbol_rate", 1e9)))))
        cfo_grid = np.linspace(-cfo_search_hz, cfo_search_hz, 41) if fs_awg > 0 and n_fft >= 64 else np.array([0.0])
        t_block = np.arange(n_fft, dtype=np.float64) / fs_awg if fs_awg > 0 else np.arange(n_fft, dtype=np.float64)

        def _smooth_complex_response(h_raw: np.ndarray, weight: np.ndarray | None = None) -> np.ndarray:
            h = np.asarray(h_raw, dtype=np.complex128).reshape(-1)
            if len(h) == 0:
                return h
            valid = np.isfinite(h.real) & np.isfinite(h.imag) & (np.abs(h) > 1e-12)
            if np.count_nonzero(valid) < max(4, len(h) // 32):
                return np.ones_like(h, dtype=np.complex128)
            idx = np.arange(len(h), dtype=np.float64)
            hr = np.interp(idx, idx[valid], h.real[valid])
            hi = np.interp(idx, idx[valid], h.imag[valid])
            h_fill = hr + 1j * hi
            win = int(np.clip(len(h) // 32, 5, 65))
            if win % 2 == 0:
                win += 1
            if win < 5 or win >= len(h):
                return h_fill
            kernel = np.hanning(win)
            if not np.any(kernel > 0):
                kernel = np.ones(win, dtype=np.float64)
            if weight is not None:
                w = np.asarray(weight, dtype=np.float64).reshape(-1)[:len(h)]
                w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
                w = np.maximum(w, 0.0)
            else:
                w = np.ones(len(h), dtype=np.float64)
            pad = win // 2
            ker = kernel / (np.sum(kernel) + 1e-15)
            num_r = np.convolve(np.pad(h_fill.real * w, pad, mode="edge"), ker, mode="valid")
            num_i = np.convolve(np.pad(h_fill.imag * w, pad, mode="edge"), ker, mode="valid")
            den = np.convolve(np.pad(w, pad, mode="edge"), ker, mode="valid")
            return (num_r + 1j * num_i) / (den + 1e-15)

        est_rows: list[np.ndarray] = []
        pilot_locks: list[float] = []
        h_vals: list[complex] = []
        cfo_hz_vals: list[float] = []
        dd_updates = 0
        fde_updates = 0
        ref_updates = 0
        for row in range(n_rows):
            y = np.asarray(rx[row, :n_fft], dtype=np.complex128).reshape(-1)
            if len(y) < n_fft:
                y = np.pad(y, (0, n_fft - len(y)))

            base_lock = float(np.abs(np.vdot(pilot_component, y)) / np.sqrt(
                pilot_energy * (np.vdot(y, y).real + 1e-15)
            ))
            best_lock = base_lock
            best_cfo = 0.0
            best_y = y
            if len(cfo_grid) > 1:
                for cfo_hz in cfo_grid:
                    if abs(float(cfo_hz)) < 1e-9:
                        continue
                    yc = y * np.exp(-1j * 2.0 * np.pi * float(cfo_hz) * t_block)
                    lock_c = float(np.abs(np.vdot(pilot_component, yc)) / np.sqrt(
                        pilot_energy * (np.vdot(yc, yc).real + 1e-15)
                    ))
                    if lock_c > best_lock:
                        best_lock = lock_c
                        best_cfo = float(cfo_hz)
                        best_y = yc
                if best_lock > base_lock * 1.002:
                    y = best_y
                else:
                    best_cfo = 0.0
                    best_lock = base_lock
            cfo_hz_vals.append(best_cfo)

            scale_i = float(scales[row]) if row < len(scales) and np.isfinite(scales[row]) and scales[row] > 0 else 1.0

            def _active_data_freq_from_symbols(symbols: np.ndarray) -> np.ndarray:
                sy = np.asarray(symbols, dtype=np.complex128).reshape(-1)[:n_data]
                spread = np.fft.fft(sy) / np.sqrt(n_data)
                return spread / scale_i

            def _time_from_symbols(symbols: np.ndarray) -> np.ndarray:
                spread = _active_data_freq_from_symbols(symbols) * scale_i
                X = np.zeros(n_fft, dtype=np.complex128)
                X[active_bins] = spread
                return (np.fft.ifft(X) / scale_i).astype(np.complex128)

            def _symbols_from_channel(h_ch: complex) -> np.ndarray:
                if np.ndim(h_ch) == 0:
                    y_eq = y / (complex(h_ch) + 1e-15)
                    data_time = (y_eq - pilot_component) / sd
                    X_est = np.fft.fft(data_time * scale_i)
                    spread_est = X_est[active_bins]
                else:
                    h_vec = np.asarray(h_ch, dtype=np.complex128).reshape(-1)[:n_data]
                    y_active = np.fft.fft(y)[active_bins]
                    data_active = (y_active / (h_vec + 1e-15) - pilot_active) / sd
                    spread_est = data_active * scale_i
                return np.fft.ifft(spread_est * np.sqrt(n_data))[:n_data]

            def _decision_symbols(symbols: np.ndarray) -> tuple[np.ndarray, float]:
                bits_dec = _hard_bits_from_symbols(symbols, modulation)
                dec_syms = _bits_to_qam_symbols(bits_dec, modulation)[:n_data]
                n_dec = min(len(symbols), len(dec_syms))
                if n_dec <= 0:
                    return dec_syms, float("inf")
                denom = float(np.mean(np.abs(dec_syms[:n_dec]) ** 2)) + 1e-15
                metric = float(np.sqrt(np.mean(np.abs(symbols[:n_dec] - dec_syms[:n_dec]) ** 2) / denom))
                return dec_syms, metric

            def _reference_metric(symbols: np.ndarray) -> float:
                ref_row = tx_sym[row, :n_data] if row < tx_sym.shape[0] else np.zeros(0, dtype=np.complex128)
                n_ref = min(len(symbols), len(ref_row))
                if n_ref <= 0:
                    return float("inf")
                ref_local = np.asarray(ref_row[:n_ref], dtype=np.complex128)
                est_local = np.asarray(symbols[:n_ref], dtype=np.complex128)
                est_fit = DsoPanel._correct_symbols_to_reference(
                    est_local,
                    ref_local,
                    linear_phase=True,
                    track_phase=False,
                    widely_linear=str(modulation).strip().upper() not in {"BPSK", "QPSK", "8PSK"},
                )
                denom = float(np.mean(np.abs(ref_local) ** 2)) + 1e-15
                return float(np.sqrt(np.mean(np.abs(est_fit - ref_local) ** 2) / denom))

            h_p = np.vdot(pilot_component, y) / pilot_energy
            if (not np.isfinite(h_p.real)) or abs(h_p) <= 1e-12:
                if tx_ref.ndim == 2 and row < tx_ref.shape[0]:
                    tref = tx_ref[row, :n_fft]
                    h_p = np.vdot(tref, y) / (np.vdot(tref, tref).real + 1e-15)
                else:
                    h_p = 1.0 + 0.0j

            y_active = np.fft.fft(y)[active_bins]
            pilot_valid = np.abs(pilot_active) > 1e-12
            h_pilot_raw = np.ones(n_data, dtype=np.complex128) * h_p
            h_pilot_raw[pilot_valid] = y_active[pilot_valid] / pilot_active[pilot_valid]
            h_pilot_vec = _smooth_complex_response(h_pilot_raw, np.abs(pilot_active) ** 2)

            sym_scalar = _symbols_from_channel(h_p)
            sym_fde = _symbols_from_channel(h_pilot_vec)
            metric_scalar = _reference_metric(sym_scalar)
            metric_fde = _reference_metric(sym_fde)

            h_ref = None
            sym_ref = None
            metric_ref = float("inf")
            h_ref_vec = None
            sym_ref_vec = None
            metric_ref_vec = float("inf")
            if tx_ref.ndim == 2 and row < tx_ref.shape[0]:
                tref = np.asarray(tx_ref[row, :n_fft], dtype=np.complex128).reshape(-1)
                if len(tref) < n_fft:
                    tref = np.pad(tref, (0, n_fft - len(tref)))
                den_ref = float(np.vdot(tref, tref).real) + 1e-15
                h_ref = np.vdot(tref, y) / den_ref
                if np.isfinite(h_ref.real) and np.isfinite(h_ref.imag) and abs(h_ref) > 1e-12:
                    sym_ref = _symbols_from_channel(h_ref)
                    metric_ref = _reference_metric(sym_ref)
                tref_active = np.fft.fft(tref)[active_bins]
                tref_valid = np.abs(tref_active) > 1e-12
                if np.count_nonzero(tref_valid) >= max(8, n_data // 16):
                    h_ref_raw = np.ones(n_data, dtype=np.complex128) * (
                        h_ref if h_ref is not None and np.isfinite(h_ref.real) else h_p
                    )
                    h_ref_raw[tref_valid] = y_active[tref_valid] / tref_active[tref_valid]
                    h_ref_vec = _smooth_complex_response(h_ref_raw, np.abs(tref_active) ** 2)
                    sym_ref_vec = _symbols_from_channel(h_ref_vec)
                    metric_ref_vec = _reference_metric(sym_ref_vec)

            metric_options = [
                ("scalar", metric_scalar, sym_scalar, h_p),
                ("pilot-fde", metric_fde, sym_fde, h_pilot_vec),
                ("ref-scalar", metric_ref, sym_ref, h_ref),
                ("ref-fde", metric_ref_vec, sym_ref_vec, h_ref_vec),
            ]
            metric_options = [
                opt for opt in metric_options
                if opt[2] is not None and opt[3] is not None and np.isfinite(float(opt[1]))
            ]
            best_mode, _, sym_est, h_sel = min(
                metric_options,
                key=lambda opt: float(opt[1]),
            ) if metric_options else ("scalar", metric_scalar, sym_scalar, h_p)

            if best_mode == "ref-fde":
                ref_updates += 1
                fde_updates += 1
            elif best_mode == "ref-scalar":
                ref_updates += 1
            elif best_mode == "pilot-fde":
                fde_updates += 1

            if len(sym_est) >= 8:
                try:
                    for _ in range(2):
                        dec_syms, decision_metric = _decision_symbols(sym_est)
                        if not np.isfinite(decision_metric) or decision_metric > 0.55:
                            break

                        data_freq_dec = _active_data_freq_from_symbols(dec_syms)
                        tx_active_hat = pilot_active + sd * data_freq_dec
                        active_valid = np.abs(tx_active_hat) > 1e-12
                        h_dd_raw = np.ones(n_data, dtype=np.complex128) * (
                            h_p if np.ndim(h_sel) == 0 else np.median(h_sel)
                        )
                        h_dd_raw[active_valid] = y_active[active_valid] / tx_active_hat[active_valid]
                        h_dd_vec = _smooth_complex_response(h_dd_raw, np.abs(tx_active_hat) ** 2)
                        sym_dd_vec = _symbols_from_channel(h_dd_vec)

                        data_time_dec = _time_from_symbols(dec_syms)
                        tx_hat = pilot_component + sd * data_time_dec
                        h_dd_scalar = np.vdot(tx_hat, y) / (np.vdot(tx_hat, tx_hat).real + 1e-15)
                        sym_dd_scalar = (
                            _symbols_from_channel(h_dd_scalar)
                            if np.isfinite(h_dd_scalar.real) and abs(h_dd_scalar) > 1e-12
                            else sym_dd_vec
                        )

                        _, metric_vec = _decision_symbols(sym_dd_vec)
                        _, metric_dd_scalar = _decision_symbols(sym_dd_scalar)
                        if np.isfinite(metric_vec) and metric_vec <= metric_dd_scalar:
                            sym_new = sym_dd_vec
                            h_new = h_dd_vec
                            fde_updates += 1
                        else:
                            sym_new = sym_dd_scalar
                            h_new = h_dd_scalar
                        _, metric_new = _decision_symbols(sym_new)
                        if np.isfinite(metric_new) and metric_new <= decision_metric + 1e-6:
                            sym_est = sym_new
                            h_sel = h_new
                            h_p = (
                                complex(np.mean(np.asarray(h_new, dtype=np.complex128)))
                                if np.ndim(h_new) != 0
                                else complex(h_new)
                            )
                            dd_updates += 1
                        else:
                            break
                except Exception:
                    pass
            est_rows.append(sym_est[:n_data])

            lock = float(np.abs(np.vdot(pilot_component, y)) / np.sqrt(
                pilot_energy * (np.vdot(y, y).real + 1e-15)
            ))
            pilot_locks.append(lock)
            if np.ndim(h_sel) == 0:
                h_vals.append(complex(h_sel))
            else:
                h_arr = np.asarray(h_sel, dtype=np.complex128).reshape(-1)
                h_vals.extend([complex(np.percentile(np.abs(h_arr), 10)), complex(np.percentile(np.abs(h_arr), 90))])

        qam_est = np.asarray(est_rows, dtype=np.complex128).reshape(-1)
        qam_ref = tx_sym[:n_rows, :n_data].reshape(-1)
        diag = {
            "blocks": int(n_rows),
            "pilot_lock": float(np.mean(pilot_locks)) if pilot_locks else 0.0,
            "pilot_lock_min": float(np.min(pilot_locks)) if pilot_locks else 0.0,
            "channel_ripple_db": (
                20.0 * np.log10(
                    (np.max(np.abs(h_vals)) + 1e-15) /
                    (np.min(np.abs(h_vals)) + 1e-15)
                ) if h_vals else float("nan")
            ),
            "cfo_hz_mean": float(np.mean(cfo_hz_vals)) if cfo_hz_vals else 0.0,
            "cfo_hz_maxabs": float(np.max(np.abs(cfo_hz_vals))) if cfo_hz_vals else 0.0,
            "dd_updates": int(dd_updates),
            "fde_updates": int(fde_updates),
            "ref_updates": int(ref_updates),
        }
        return qam_est, qam_ref[:len(qam_est)], diag

    @staticmethod
    def _differential_delay_from_cfr(
        freqs: np.ndarray,
        h_cur: np.ndarray,
        h_ref: np.ndarray,
        weight: np.ndarray | None = None,
    ) -> tuple[float, float]:
        f = np.asarray(freqs, dtype=np.float64).reshape(-1)
        hc = np.asarray(h_cur, dtype=np.complex128).reshape(-1)
        hr = np.asarray(h_ref, dtype=np.complex128).reshape(-1)
        n = min(len(f), len(hc), len(hr))
        if n < 16:
            return float("nan"), float("nan")
        f = f[:n]
        ratio = hc[:n] / (hr[:n] + 1e-15)
        valid = np.isfinite(f) & np.isfinite(ratio.real) & np.isfinite(ratio.imag) & (np.abs(ratio) > 1e-12)
        if np.count_nonzero(valid) < 16:
            return float("nan"), float("nan")
        f = f[valid]
        hc = hc[:n][valid]
        hr = hr[:n][valid]
        ratio = ratio[valid]
        ph = np.unwrap(np.angle(ratio))
        if weight is None:
            w = np.ones(len(f), dtype=np.float64)
        else:
            w = np.asarray(weight, dtype=np.float64).reshape(-1)[:n][valid]
            w = np.maximum(w, 0.0)
        if not np.any(w > 0):
            w = np.ones(len(f), dtype=np.float64)
        amp_reliability = np.minimum(np.abs(hc), np.abs(hr))
        amp_reliability = amp_reliability / (np.nanmax(amp_reliability) + 1e-15)
        w = w * np.clip(amp_reliability, 0.0, 1.0)
        w = w / (np.max(w) + 1e-15)
        good = w >= 0.03
        if np.count_nonzero(good) >= 16:
            f = f[good]
            ratio = ratio[good]
            ph = ph[good]
            w = w[good]

        def _weighted_line(x: np.ndarray, y: np.ndarray, ww: np.ndarray) -> tuple[float, float]:
            ww = np.maximum(np.asarray(ww, dtype=np.float64), 0.0)
            if not np.any(ww > 0):
                ww = np.ones_like(x, dtype=np.float64)
            x0 = x - np.sum(ww * x) / (np.sum(ww) + 1e-15)
            y0 = y - np.sum(ww * y) / (np.sum(ww) + 1e-15)
            slope_i = float(np.sum(ww * x0 * y0) / (np.sum(ww * x0 * x0) + 1e-15))
            intercept_i = float(np.sum(ww * (y - slope_i * x)) / (np.sum(ww) + 1e-15))
            return slope_i, intercept_i

        slope, intercept = _weighted_line(f, ph, w)
        resid = ph - (slope * f + intercept)
        mad = float(np.nanmedian(np.abs(resid - np.nanmedian(resid)))) if len(resid) else float("nan")
        resid_lim = max(np.pi / 2.0, 4.0 * 1.4826 * mad) if np.isfinite(mad) else np.pi
        robust = np.isfinite(resid) & (np.abs(resid) <= resid_lim)
        if np.count_nonzero(robust) >= 16 and np.count_nonzero(robust) < len(f):
            f = f[robust]
            ratio = ratio[robust]
            ph = ph[robust]
            w = w[robust]
            slope, intercept = _weighted_line(f, ph, w)

        delta_tau = -slope / (2.0 * np.pi)
        derot = ratio / (np.abs(ratio) + 1e-15) * np.exp(-1j * (slope * f + intercept))
        coh = float(np.abs(np.sum(w * derot)) / (np.sum(w) + 1e-15))
        return float(delta_tau), coh

    @staticmethod
    def _recover_lfm_qam_symbols_integrate_and_dump(
        dechirped: np.ndarray,
        n_per_sym: int,
        n_symbols: int,
        preamble_len: int,
        preamble_ref: np.ndarray,
    ) -> tuple[np.ndarray, dict]:
        """Rectangular integrate-and-dump plus residual phase/CFO correction.

        The shared LFM-QAM frame is one continuous chirp multiplied by a
        zero-order-held communication symbol stream. `_frame_sync_and_reshape`
        already resamples the frame onto the TX sample grid, so this stage
        only averages each symbol interval and uses the known preamble for a
        final common phase / slow-CFO correction.
        """
        x = np.asarray(dechirped, dtype=np.complex128).reshape(-1)
        n_per_sym = max(1, int(n_per_sym))
        n_symbols = max(1, int(n_symbols))
        need = n_symbols * n_per_sym
        if len(x) < need:
            x = np.pad(x, (0, need - len(x)))
        else:
            x = x[:need]
        symbols = np.mean(x.reshape(n_symbols, n_per_sym), axis=1)

        diag = {"preamble_lock_score": 0.0, "residual_cfo_rad_per_symbol": 0.0, "residual_phase_rad": 0.0}
        preamble_ref = np.asarray(preamble_ref, dtype=np.complex128).reshape(-1)
        preamble_len = max(0, min(int(preamble_len), n_symbols, len(preamble_ref)))
        if preamble_len >= 8:
            est_pre = symbols[:preamble_len]
            ref_pre = preamble_ref[:preamble_len]
            err = est_pre * np.conj(ref_pre)
            lock_score = float(np.abs(np.mean(err)) / (np.mean(np.abs(err)) + 1e-15))
            diag["preamble_lock_score"] = lock_score
            if lock_score > 0.2:
                ph = np.unwrap(np.angle(err))
                idx = np.arange(preamble_len, dtype=np.float64)
                a_mat = np.column_stack([np.ones(preamble_len), idx])
                coef, *_ = np.linalg.lstsq(a_mat, ph, rcond=None)
                phase0, slope = float(coef[0]), float(coef[1])
                diag["residual_phase_rad"] = phase0
                diag["residual_cfo_rad_per_symbol"] = slope
                full_idx = np.arange(n_symbols, dtype=np.float64)
                symbols = symbols * np.exp(-1j * (phase0 + slope * full_idx))
        return symbols, diag

    def _compute_pslr_db(self, profile_linear: np.ndarray, rng: np.ndarray | None = None,
                         mode: str | None = None) -> float:
        prof = np.asarray(profile_linear, dtype=np.float64).reshape(-1)
        if len(prof) < 8 or not np.any(np.isfinite(prof)):
            return float("nan")
        prof = np.nan_to_num(prof, nan=0.0, posinf=0.0, neginf=0.0)
        peak_idx = int(np.argmax(prof))
        peak = float(prof[peak_idx])
        if peak <= 0.0:
            return float("nan")
        guard_bins = 4
        try:
            if rng is not None:
                r = np.asarray(rng, dtype=np.float64).reshape(-1)
                if len(r) == len(prof):
                    dr = float(np.nanmedian(np.abs(np.diff(r))))
                    f1_ghz, f2_ghz = self._get_signal_band_ghz()
                    bw_hz = max(1.0, (f2_ghz - f1_ghz) * 1e9)
                    res_m = self._range_delay_scale_m_per_s(mode=mode) / bw_hz
                    if np.isfinite(dr) and dr > 0:
                        guard_bins = max(4, int(np.ceil(res_m / dr)))
        except Exception:
            pass
        mask = np.ones(len(prof), dtype=bool)
        mask[max(0, peak_idx - guard_bins):min(len(prof), peak_idx + guard_bins + 1)] = False
        if not np.any(mask):
            return float("nan")
        sidelobe = float(np.max(prof[mask]))
        if sidelobe <= 0.0:
            return float("nan")
        return 20.0 * np.log10(peak / sidelobe)

    def _range_diff_target_mm(self) -> float:
        try:
            return float(self.range_target_m_var.get())
        except Exception:
            return 0.0

    def _range_diff_tolerance_mm(self) -> float:
        try:
            val = abs(float(self.range_tolerance_m_var.get()))
        except Exception:
            val = 5.0
        return val if np.isfinite(val) and val > 0 else 5.0

    @staticmethod
    def _range_zero_reference_center_m(info: dict | None) -> float:
        if not isinstance(info, dict):
            return float("nan")
        for key in ("abs_range_m", "profile_center_m"):
            try:
                val = float(info.get(key, float("nan")))
                if np.isfinite(val):
                    return val
            except Exception:
                pass
        profile = info.get("profile")
        if isinstance(profile, dict):
            for key in ("center_m", "abs_range_m"):
                try:
                    val = float(profile.get(key, float("nan")))
                    if np.isfinite(val):
                        return val
                except Exception:
                    pass
        return float("nan")

    def _range_zero_info_for_channel(self, ch_label: str = "") -> dict | None:
        ch_key = str(ch_label or "").strip().upper()
        zero_by_ch = self.runtime.get("lfm_range_zero_by_ch", {})
        if isinstance(zero_by_ch, dict) and ch_key:
            info = zero_by_ch.get(ch_key)
            if isinstance(info, dict):
                return info
        info = self.runtime.get("lfm_range_zero_info")
        return info if isinstance(info, dict) else None

    @staticmethod
    def _refine_range_peak_centroid(
        rng: np.ndarray,
        profile_linear: np.ndarray,
        peak_idx: int,
        half_span_m: float,
    ) -> float:
        r = np.asarray(rng, dtype=np.float64).reshape(-1)
        p = np.asarray(profile_linear, dtype=np.float64).reshape(-1)
        if len(r) != len(p) or len(r) == 0:
            return float("nan")
        peak_idx = int(np.clip(int(peak_idx), 0, len(r) - 1))
        peak_range = float(r[peak_idx])
        if not np.isfinite(peak_range):
            return peak_range
        if not np.isfinite(half_span_m) or half_span_m <= 0:
            if len(r) > 2:
                dr = float(np.nanmedian(np.abs(np.diff(np.sort(r[np.isfinite(r)])))))
                half_span_m = max(2.0 * dr, 1e-6) if np.isfinite(dr) and dr > 0 else 1e-6
            else:
                half_span_m = 1e-6
        mask = np.isfinite(r) & np.isfinite(p) & (np.abs(r - peak_range) <= half_span_m)
        if np.count_nonzero(mask) < 3:
            return peak_range
        vals = np.maximum(p[mask], 0.0)
        if not np.any(vals > 0):
            return peak_range
        floor = float(np.percentile(vals, 20.0))
        weights = np.maximum(vals - floor, 0.0)
        if not np.any(weights > 0):
            weights = vals
        denom = float(np.sum(weights))
        if denom <= 0:
            return peak_range
        refined = float(np.sum(r[mask] * weights) / denom)
        return refined if np.isfinite(refined) else peak_range

    def _compute_isac_range_profile_for_signal(self, sig: np.ndarray, fs: float,
                                               pl: dict, ch_label: str = "",
                                               row: int = 0) -> dict:
        self._assert_dsp_payload_consistent(pl, context="range")
        sig = np.asarray(sig, dtype=np.float64)
        rx_bb, fs_ref = self._rx_to_baseband(sig, float(fs), pl)
        rx_mat, tx_bb_mat, _, base_chirp, n_chirps, _, _, pts_per_chirp, frame_start = \
            self._frame_sync_and_reshape(rx_bb, fs_ref, pl)
        range_mode = self._range_mode_for_row(row)
        range_scale = self._range_delay_scale_m_per_s(mode=range_mode)
        ref_mat = self._dfts_ofdm_pilot_matrix(pl, n_chirps)
        if ref_mat is None:
            ref_mat = tx_bb_mat
        ref_len = int(ref_mat.shape[1])

        corr_acc = np.zeros(pts_per_chirp + ref_len - 1, dtype=np.float64)
        for i in range(n_chirps):
            ref_i = ref_mat[min(i, ref_mat.shape[0] - 1)]
            ci = np.abs(fftconvolve(rx_mat[i], np.conj(ref_i[::-1]), mode="full"))
            corr_acc += ci
        corr_acc /= max(n_chirps, 1)

        lags = np.arange(-(ref_len - 1), pts_per_chirp, dtype=np.int64)
        est_idx = int(np.argmax(corr_acc)) if len(corr_acc) else 0
        ch_key = str(ch_label or "").strip().upper()
        # Keep range display/detection absolute. Stored zero reference is used
        # only as an overlay and for dR/CFR-delta estimation, never to shift
        # the range axis. The old relative-axis mode was ambiguous with
        # repeated frames and made 1 m absolute checks disappear after
        # Store Zero Ref.
        zero_enabled = False
        zero_ref_info = self._range_zero_info_for_channel(ch_key)
        zero_info = zero_ref_info if zero_enabled else None
        ref_center_m = self._range_zero_reference_center_m(zero_ref_info)
        zero_delay_s = (
            float(zero_info.get("delay_s"))
            if isinstance(zero_info, dict) and zero_info.get("delay_s") is not None
            else (self.runtime.get("lfm_range_zero_delay_s") if zero_enabled else None)
        )
        prefix = f"[ISAC {ch_label}]" if ch_label else "[ISAC]"
        if zero_delay_s is None:
            if zero_ref_info is None:
                self._log(
                    f"{prefix} WARNING: no stored zero reference; range profile is absolute "
                    "within the current frame-sync delay convention only."
                )
            delay_s = lags.astype(np.float64) / fs_ref
        else:
            # Relative displacement should compare the matched-filter peak
            # position inside the synchronized frame.  Using the absolute
            # record index (frame_start + lag) is fragile for repeated frames:
            # frame sync may lock to the neighboring repeat and shift the
            # whole range axis by ~one frame, which appears as persistent
            # false peaks around -1 m.  Store Zero Ref saves peak_lag for this
            # reason; use it as the relative-zero anchor.
            zero_peak_lag = (
                float(zero_info.get("peak_lag"))
                if isinstance(zero_info, dict) and zero_info.get("peak_lag") is not None
                else None
            )
            if zero_peak_lag is not None:
                delay_s = (lags.astype(np.float64) - float(zero_peak_lag)) / fs_ref
            else:
                raw_delay_s = (lags.astype(np.float64) + float(frame_start)) / fs_ref
                raw_delay_s = raw_delay_s - float(zero_delay_s)
                frame_period_s = (
                    float(zero_info.get("frame_period_s"))
                    if isinstance(zero_info, dict) and zero_info.get("frame_period_s")
                    else float(n_chirps * pts_per_chirp) / float(fs_ref)
                )
                fold_offset_s = 0.0
                if frame_period_s > 0 and len(raw_delay_s) > est_idx:
                    peak_delay_s = float(raw_delay_s[est_idx])
                    fold_offset_s = round(peak_delay_s / frame_period_s) * frame_period_s
                delay_s = raw_delay_s - fold_offset_s
                if abs(fold_offset_s) > 0.25 * frame_period_s:
                    self._log(
                        f"{prefix} range-zero frame ambiguity folded by "
                        f"{fold_offset_s * 1e9:.3f} ns "
                        f"({fold_offset_s * range_scale:.3f} m, mode={range_mode})."
                    )

        rng = delay_s * range_scale
        prof_v = corr_acc
        prof_db = 20.0 * np.log10(prof_v / (np.max(prof_v) + 1e-15) + 1e-15)
        target_diff_mm = self._range_diff_target_mm()
        target_tol_mm = self._range_diff_tolerance_mm()
        target_diff_m = target_diff_mm * 1e-3
        target_tol_m = target_tol_mm * 1e-3
        if zero_delay_s is not None:
            target_m = target_diff_m
        elif np.isfinite(ref_center_m):
            target_m = ref_center_m + target_diff_m
        else:
            target_m = float("nan")
        ref_rng = np.zeros(0, dtype=np.float64)
        ref_prof_db = np.zeros(0, dtype=np.float64)
        profile_source_info = zero_info if isinstance(zero_info, dict) else zero_ref_info
        if isinstance(profile_source_info, dict) and profile_source_info.get("profile") is not None:
            try:
                prof_info = profile_source_info.get("profile", {})
                ref_lags = np.asarray(prof_info.get("lags", []), dtype=np.float64).reshape(-1)
                ref_prof = np.asarray(prof_info.get("prof_db", []), dtype=np.float64).reshape(-1)
                ref_peak_lag = float(prof_info.get("peak_lag", profile_source_info.get("peak_lag", 0.0)))
                ref_fs = float(prof_info.get("fs", profile_source_info.get("fs", fs_ref)))
                n_ref = min(len(ref_lags), len(ref_prof))
                if n_ref >= 8 and ref_fs > 0:
                    ref_rng_rel = (ref_lags[:n_ref] - ref_peak_lag) / ref_fs * range_scale
                    try:
                        ref_center_profile_m = float(prof_info.get(
                            "center_m",
                            profile_source_info.get("profile_center_m", ref_center_m),
                        ))
                        if np.isfinite(ref_center_profile_m):
                            ref_center_m = ref_center_profile_m
                    except Exception:
                        pass
                    if zero_delay_s is None:
                        center = ref_center_m if np.isfinite(ref_center_m) else 0.0
                        ref_rng = center + ref_rng_rel
                    else:
                        ref_rng = ref_rng_rel
                    ref_prof_db = ref_prof[:n_ref]
            except Exception:
                ref_rng = np.zeros(0, dtype=np.float64)
                ref_prof_db = np.zeros(0, dtype=np.float64)
        if zero_delay_s is None and (not np.isfinite(target_m)) and np.isfinite(ref_center_m):
            target_m = ref_center_m + target_diff_m
        self_interference_range_m = float("nan")
        zero_exclude_m = float("nan")
        monostatic_row = "monostatic" in str(range_mode).lower()
        try:
            f1_ghz, f2_ghz = self._get_signal_band_ghz()
            bw_hz = max(1.0, (f2_ghz - f1_ghz) * 1e9)
            range_res_m = range_scale / bw_hz
        except Exception:
            range_res_m = float("nan")

        if not np.isfinite(target_tol_m) or target_tol_m <= 0:
            target_tol_m = 0.01 if zero_delay_s is not None else 0.05
        target_window_m = target_tol_m
        if np.isfinite(range_res_m) and range_res_m > 0:
            target_window_m = max(target_window_m, 2.0 * range_res_m)
        if zero_delay_s is None and np.isfinite(target_m) and target_m > 0:
            # Keep the ROI useful even when the GUI still has the old coarse
            # 0.25 m tolerance.  The plot can zoom much tighter than the
            # search window; this window is only for picking the intended
            # second peak near the target instead of the self-interference.
            target_window_m = min(max(target_window_m, 0.02), 0.35)

        if zero_delay_s is not None and len(corr_acc) and len(rng) == len(corr_acc):
            zero_track_span_m = 0.015
            if np.isfinite(range_res_m) and range_res_m > 0:
                zero_track_span_m = max(0.015, min(0.050, 3.0 * float(range_res_m)))
            near_zero = np.isfinite(rng) & (np.abs(rng) <= zero_track_span_m)
            if np.any(near_zero):
                near_idx = np.flatnonzero(near_zero)
                local_idx = int(near_idx[int(np.argmax(corr_acc[near_zero]))])
                if local_idx != est_idx:
                    self._log(
                        f"{prefix} zero-relative tracking ignored global peak "
                        f"{float(rng[est_idx]) * 1e3:.2f} mm and selected "
                        f"{float(rng[local_idx]) * 1e3:.2f} mm "
                        f"within +/-{zero_track_span_m * 1e3:.1f} mm."
                    )
                est_idx = local_idx
            else:
                self._log(
                    f"{prefix} zero-relative tracking found no peak within "
                    f"+/-{zero_track_span_m * 1e3:.1f} mm; using global peak."
                )

        # The "exclude near rng=0, then hunt for the strongest peak farther
        # out" logic below only makes sense in ABSOLUTE mode, where the
        # OMT's leaked self-interference genuinely sits at delay~0 (relative
        # to the frame-sync peak) and a real target is farther away. Once a
        # range-zero calibration is active we're doing fine relative-
        # displacement sensing around that calibrated reference point, where
        # the true target peak can legitimately sit right at/near rng=0 --
        # excluding it there discarded exactly the peak we wanted and
        # reported some unrelated sidelobe/reflection instead (this is what
        # produced spurious jumps like -400 mm right after Set Range Zero).
        if (not monostatic_row) and zero_delay_s is None and len(corr_acc) and len(rng) == len(corr_acc):
            if np.isfinite(rng[est_idx]) and rng[est_idx] < 0:
                pos_mask = np.isfinite(rng) & (rng >= 0.0)
                if np.any(pos_mask):
                    pos_indices = np.flatnonzero(pos_mask)
                    pos_idx = int(pos_indices[int(np.argmax(corr_acc[pos_mask]))])
                    self._log(
                        f"{prefix} absolute one-way peak was negative "
                        f"({float(rng[est_idx]):.4g} m); selected positive peak "
                        f"{float(rng[pos_idx]):.4g} m instead."
                    )
                    est_idx = pos_idx

        if monostatic_row and zero_delay_s is None and len(corr_acc) and len(rng) == len(corr_acc):
            si_idx = int(np.argmax(corr_acc))
            self_interference_range_m = float(rng[si_idx]) if len(rng) > si_idx else float("nan")
            zero_exclude_m = max(
                0.05,
                2.0 * range_res_m if np.isfinite(range_res_m) and range_res_m > 0 else 0.05,
            )
            target_mask = (
                np.isfinite(rng)
                & np.isfinite(target_m)
                & (target_m > 0)
                & (np.abs(rng - target_m) <= target_window_m)
            )
            if np.any(target_mask):
                target_indices = np.flatnonzero(target_mask)
                target_idx = int(target_indices[int(np.argmax(corr_acc[target_mask]))])
                est_idx = target_idx
                self._log(
                    f"{prefix} target-guided monostatic peak: "
                    f"target={target_m:.4g} m, picked={float(rng[est_idx]):.4g} m, "
                    f"window=+/-{target_window_m:.4g} m, SI={self_interference_range_m:.4g} m"
                )
            else:
                link_mask = np.isfinite(rng) & (rng > zero_exclude_m)
                if np.any(link_mask):
                    link_indices = np.flatnonzero(link_mask)
                    link_idx = int(link_indices[int(np.argmax(corr_acc[link_mask]))])
                    est_idx = link_idx
                    self._log(
                        f"{prefix} monostatic peaks: "
                        f"SI={self_interference_range_m:.4g} m, "
                        f"link={float(rng[est_idx]):.4g} m, "
                        f"zero_guard={zero_exclude_m:.4g} m"
                    )
                else:
                    self._log(
                        f"{prefix} monostatic peak search found no link peak beyond "
                        f"{zero_exclude_m:.4g} m; using absolute peak."
                    )

        freqs_cur, h_cur, w_cur = self._estimate_lfm_cfr(rx_mat, ref_mat, fs_ref)
        si_cfr_rng = np.zeros(0, dtype=np.float64)
        si_cfr_prof_db = np.zeros(0, dtype=np.float64)
        si_cfr_peak_m = float("nan")
        si_cfr_coherence = float("nan")
        si_cfr_target_db = float("nan")
        try:
            cfr_rng = rng[np.isfinite(rng)]
            cfr_rng = cfr_rng[cfr_rng >= 0.0]
            if len(cfr_rng) > 4096:
                cfr_rng = np.linspace(float(np.nanmin(cfr_rng)), float(np.nanmax(cfr_rng)), 4096)
            if len(freqs_cur) >= 16 and len(cfr_rng) >= 8:
                si_cfr = si_normalized_cfr_delay_profile(
                    freqs_cur,
                    h_cur,
                    w_cur,
                    cfr_rng,
                    range_scale,
                )
                si_cfr_rng = np.asarray(si_cfr["range_m"], dtype=np.float64)
                si_cfr_prof_db = np.asarray(si_cfr["profile_db"], dtype=np.float64)
                si_cfr_coherence = float(si_cfr["coherence"])
                if len(si_cfr_rng) == len(si_cfr_prof_db) and len(si_cfr_rng):
                    pick_mask = np.isfinite(si_cfr_rng)
                    if np.isfinite(target_m) and target_m > 0:
                        pick_mask &= np.abs(si_cfr_rng - target_m) <= target_window_m
                    elif monostatic_row and np.isfinite(zero_exclude_m):
                        pick_mask &= si_cfr_rng > zero_exclude_m
                    if not np.any(pick_mask):
                        pick_mask = np.isfinite(si_cfr_rng)
                        if monostatic_row and np.isfinite(zero_exclude_m):
                            pick_mask &= si_cfr_rng > zero_exclude_m
                    if np.any(pick_mask):
                        pick_indices = np.flatnonzero(pick_mask)
                        si_pick = int(pick_indices[int(np.nanargmax(si_cfr_prof_db[pick_mask]))])
                        si_cfr_peak_m = float(si_cfr_rng[si_pick])
                        si_cfr_target_db = float(si_cfr_prof_db[si_pick])
                    else:
                        si_cfr_peak_m = float(si_cfr["peak_m"])
                if np.isfinite(si_cfr_peak_m):
                    self._log(
                        f"{prefix} SI-CFR normalized: peak={si_cfr_peak_m:.4g} m  "
                        f"coherence={si_cfr_coherence:.3f}"
                    )
        except Exception as si_cfr_e:
            self._log(f"{prefix} SI-CFR normalized skipped: {si_cfr_e}")
        ref_cfr = (
            zero_ref_info.get("cfr")
            if isinstance(zero_ref_info, dict) and zero_ref_info.get("cfr") is not None
            else self.runtime.get("lfm_range_zero_cfr")
        )
        diff_tau_s = float("nan")
        diff_range_m = float("nan")
        diff_coherence = float("nan")
        display_range_m = float("nan")
        range_est_method = "matched-filter"
        if ref_cfr and len(freqs_cur) >= 16:
            try:
                freqs_ref = np.asarray(ref_cfr.get("freqs", []), dtype=np.float64)
                h_ref = np.asarray(ref_cfr.get("h", []), dtype=np.complex128)
                if len(freqs_ref) >= 16 and len(h_ref) == len(freqs_ref):
                    h_ref_i = (
                        np.interp(freqs_cur, freqs_ref, h_ref.real)
                        + 1j * np.interp(freqs_cur, freqs_ref, h_ref.imag)
                    )
                    dtau, coh = self._differential_delay_from_cfr(
                        freqs_cur, h_cur, h_ref_i, weight=w_cur
                    )
                    if np.isfinite(dtau):
                        delta_r = dtau * range_scale
                        diff_tau_s = float(dtau)
                        diff_range_m = float(delta_r)
                        diff_coherence = float(coh)
                        self._log(
                            f"{prefix} differential CFR: "
                            f"dTau={dtau*1e12:.3f} ps  "
                            f"dR={delta_r*1e3:.3f} mm  "
                            f"coherence={coh:.3f}  "
                            f"mode={range_mode}"
                        )
            except Exception as cfr_e:
                self._log(f"{prefix} differential CFR skipped: {cfr_e}")

        if str(pl.get("waveform_type", "")).strip() == "DFT-s-OFDM":
            dechirped = rx_mat.reshape(-1)
        else:
            dechirped = (rx_mat * np.conj(base_chirp)[np.newaxis, :]).reshape(-1)
        est_range_raw = float(rng[est_idx]) if len(rng) > est_idx else float("nan")
        refine_half_span_m = float("nan")
        if np.isfinite(range_res_m) and range_res_m > 0:
            refine_half_span_m = 0.5 * float(range_res_m)
        elif len(rng) > 2:
            try:
                dr_m = float(np.nanmedian(np.abs(np.diff(np.sort(rng[np.isfinite(rng)])))))
                refine_half_span_m = 3.0 * dr_m if np.isfinite(dr_m) and dr_m > 0 else float("nan")
            except Exception:
                refine_half_span_m = float("nan")
        est_range = self._refine_range_peak_centroid(rng, prof_v, est_idx, refine_half_span_m)
        if not np.isfinite(est_range):
            est_range = est_range_raw
        display_range_m = est_range
        if zero_delay_s is not None and np.isfinite(diff_range_m):
            # In range-zero mode the frame synchronizer can re-center the
            # strongest matched-filter peak on every capture.  That is fine
            # for absolute lock, but it can hide small mechanical
            # displacement.  Use H1/H0 phase slope as the displayed
            # differential range when its coherence is usable.
            if np.isfinite(diff_coherence) and diff_coherence >= 0.20:
                display_range_m = diff_range_m
                range_est_method = "CFR phase-slope"
                self._log(
                    f"{prefix} zero-relative display uses CFR delta "
                    f"{display_range_m * 1e3:.3f} mm "
                    f"(MF peak={est_range * 1e3:.3f} mm, coherence={diff_coherence:.3f})."
                )
            else:
                self._log(
                    f"{prefix} CFR delta low confidence "
                    f"(dR={diff_range_m * 1e3:.3f} mm, coherence={diff_coherence:.3f}); "
                    f"displaying matched-filter peak {est_range * 1e3:.3f} mm."
                )
        prof_metric = prof_v
        if monostatic_row and np.isfinite(zero_exclude_m) and len(rng) == len(prof_v):
            prof_metric = prof_v.copy()
            prof_metric[np.isfinite(rng) & (np.abs(rng) <= zero_exclude_m)] = 0.0
        pslr_db = self._compute_pslr_db(prof_metric, rng, mode=range_mode)
        range_profile_snr_db = float("nan")
        processing_gain_db = float("nan")
        pg_corrected_snr_db = float("nan")
        try:
            if n_chirps > 0 and ref_len > 0:
                processing_gain_db = 10.0 * math.log10(float(n_chirps) * float(ref_len))
            elif ref_len > 0:
                processing_gain_db = 10.0 * math.log10(float(ref_len))
        except Exception:
            processing_gain_db = float("nan")
        try:
            if len(prof_db) == len(rng) and len(prof_db) > 8 and len(prof_db) > est_idx:
                if len(rng) > 1:
                    dr_m = float(np.nanmedian(np.abs(np.diff(np.sort(rng[np.isfinite(rng)])))))
                else:
                    dr_m = float("nan")
                guard_m = 0.025
                if np.isfinite(range_res_m) and range_res_m > 0:
                    guard_m = max(guard_m, 2.0 * float(range_res_m))
                if np.isfinite(dr_m) and dr_m > 0:
                    guard_m = max(guard_m, 2.0 * dr_m)
                side = np.isfinite(rng) & np.isfinite(prof_db)
                if np.isfinite(rng[est_idx]):
                    side &= np.abs(rng - float(rng[est_idx])) > guard_m
                if monostatic_row and np.isfinite(zero_exclude_m):
                    side &= np.abs(rng) > float(zero_exclude_m)
                if np.count_nonzero(side) >= 8:
                    noise_med = float(np.nanmedian(prof_db[side]))
                    range_profile_snr_db = float(prof_db[est_idx] - noise_med)
                    if np.isfinite(processing_gain_db):
                        pg_corrected_snr_db = range_profile_snr_db - processing_gain_db
        except Exception:
            range_profile_snr_db = float("nan")
        peak_range_diff_mm = (
            (display_range_m - ref_center_m) * 1e3
            if np.isfinite(display_range_m) and np.isfinite(ref_center_m)
            else float("nan")
        )
        mf_range_diff_mm = (
            (est_range - ref_center_m) * 1e3
            if np.isfinite(est_range) and np.isfinite(ref_center_m)
            else float("nan")
        )
        cfr_range_diff_mm = diff_range_m * 1e3 if np.isfinite(diff_range_m) else float("nan")
        range_diff_method = "peak-reference"
        range_diff_mm = peak_range_diff_mm
        if (
            np.isfinite(cfr_range_diff_mm)
            and np.isfinite(diff_coherence)
            and diff_coherence >= 0.35
        ):
            range_diff_mm = cfr_range_diff_mm
            range_diff_method = "CFR phase-slope"
        diff_txt = f"  dR={range_diff_mm:.2f} mm" if np.isfinite(range_diff_mm) else ""
        self._log(
            f"{prefix} frame={frame_start:,}  chirps={n_chirps}  peak={est_range:.4g} m"
            f"  display={display_range_m:.4g} m ({range_est_method})"
            f"{diff_txt}"
            f"  PSLR={pslr_db:.2f} dB  mode={range_mode}"
            f"{'  (absolute)' if zero_delay_s is None else '  (relative axis)'}"
        )
        return {
            "ch": ch_label,
            "row": int(row),
            "dechirped": dechirped,
            "fs_ref": float(fs_ref),
            "frame_start": int(frame_start),
            "n_chirps": int(n_chirps),
            "pts_per_chirp": int(pts_per_chirp),
            "ref_len": int(ref_len),
            "lags": lags.astype(np.float64),
            "corr_acc": corr_acc.astype(np.float64),
            "range_scale_m_per_s": float(range_scale),
            "rng": rng,
            "prof_db": prof_db,
            "ref_rng": ref_rng,
            "ref_prof_db": ref_prof_db,
            "cfr_freqs_hz": freqs_cur,
            "cfr_h": h_cur,
            "cfr_weight": w_cur,
            "si_cfr_rng": si_cfr_rng,
            "si_cfr_prof_db": si_cfr_prof_db,
            "si_cfr_peak_m": si_cfr_peak_m,
            "si_cfr_coherence": si_cfr_coherence,
            "si_cfr_target_db": si_cfr_target_db,
            "est_range": est_range,
            "est_range_raw": est_range_raw,
            "display_range_m": display_range_m,
            "range_est_method": range_est_method,
            "pslr_db": pslr_db,
            "range_profile_snr_db": range_profile_snr_db,
            "processing_gain_db": processing_gain_db,
            "pg_corrected_snr_db": pg_corrected_snr_db,
            "range_mode": range_mode,
            "self_interference_range_m": self_interference_range_m,
            "zero_exclude_m": zero_exclude_m,
            "diff_tau_s": diff_tau_s,
            "diff_range_m": diff_range_m,
            "diff_coherence": diff_coherence,
            "zero_active": bool(zero_delay_s is not None),
            "zero_ref_center_m": ref_center_m,
            "range_diff_mm": range_diff_mm,
            "peak_range_diff_mm": peak_range_diff_mm,
            "range_diff_method": range_diff_method,
            "matched_filter_range_diff_mm": mf_range_diff_mm,
            "target_diff_mm": target_diff_mm,
            "range_resolution_m": range_res_m,
            "target_range_m": target_m,
            "target_window_m": target_window_m,
        }

    def _on_isac_dechirp_range(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire a signal first.")
            return

        def worker():
            try:
                pl = self._load_tx_payload_for_isac()
                if pl is None:
                    raise ValueError("No TX reference found. Generate or download the TX signal first.")
                self._warn_if_tx_reference_stale(pl)

                range_items = []
                display_channels = self._display_dso_channels()
                if self._rx_multi:
                    for row, ch in enumerate(display_channels[:2]):
                        item = self._rx_multi.get(ch)
                        if not item:
                            continue
                        try:
                            range_items.append(self._compute_isac_range_profile_for_signal(
                                np.asarray(item["sig"], dtype=np.float64),
                                float(item["fs"]),
                                pl,
                                ch_label=ch,
                                row=row,
                            ))
                        except Exception as ch_e:
                            self._log(f"[ISAC {ch}] range calculation skipped: {ch_e}")
                    if range_items:
                        self.parent.after(0, lambda items=range_items: self._show_isac_range_results(items))
                        return

                ch_label = self.ch_var.get().strip().upper() or "C1"
                range_items.append(self._compute_isac_range_profile_for_signal(
                    np.asarray(self._rx_sig, dtype=np.float64),
                    float(self._rx_fs),
                    pl,
                    ch_label=ch_label,
                    row=0,
                ))
                self.parent.after(0, lambda items=range_items: self._show_isac_range_results(items))
                return

            except Exception as e:
                self._log(f"[ISAC] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("ISAC De-chirp Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _on_set_range_zero(self) -> None:
        """Calibrate the ISAC range axis from the current capture.

        Capture this at the reference position/path. The absolute
        matched-filter peak, reference range profile, and CFR are stored per
        displayed channel so later captures can be plotted against the saved
        reference and scored by range difference in millimeters.
        """
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire a reference signal first.")
            return

        def worker():
            try:
                pl = self._load_tx_payload_for_isac()
                if pl is None:
                    raise ValueError("No TX reference found. Generate or download the TX signal first.")
                self._warn_if_tx_reference_stale(pl)

                display_channels_now = self._display_dso_channels()
                if self._rx_multi:
                    zero_channels = [
                        ch for ch in display_channels_now
                        if ch in self._rx_multi
                    ]
                    if not zero_channels:
                        zero_channels = [next(iter(self._rx_multi))]
                else:
                    zero_channels = [self.ch_var.get().strip().upper() or "C1"]

                zero_by_ch = dict(self.runtime.get("lfm_range_zero_by_ch", {}))
                first_info = None
                log_parts = []
                for zero_ch in zero_channels:
                    item = self._rx_multi.get(zero_ch) if self._rx_multi else None
                    if item is not None:
                        sig = np.asarray(item["sig"], dtype=np.float64)
                        fs_zero = float(item["fs"])
                    else:
                        sig = np.asarray(self._rx_sig, dtype=np.float64)
                        fs_zero = float(self._rx_fs)

                    rx_bb, fs_ref = self._rx_to_baseband(sig, fs_zero, pl)
                    rx_mat, tx_bb_mat, _, _, n_chirps, _, _, pts_per_chirp, frame_start = \
                        self._frame_sync_and_reshape(rx_bb, fs_ref, pl)
                    ref_mat = self._dfts_ofdm_pilot_matrix(pl, n_chirps)
                    if ref_mat is None:
                        ref_mat = tx_bb_mat
                    ref_len = int(ref_mat.shape[1])

                    corr_acc = np.zeros(pts_per_chirp + ref_len - 1, dtype=np.float64)
                    for i in range(n_chirps):
                        ref_i = ref_mat[min(i, ref_mat.shape[0] - 1)]
                        ci = np.abs(fftconvolve(rx_mat[i], np.conj(ref_i[::-1]), mode="full"))
                        corr_acc += ci
                    corr_acc /= max(n_chirps, 1)
                    lags = np.arange(-(ref_len - 1), pts_per_chirp, dtype=np.int64)
                    row = (
                        display_channels_now.index(zero_ch)
                        if zero_ch in display_channels_now
                        else 0
                    )
                    row = self._range_row_for_channel(zero_ch, row)
                    range_mode = self._range_mode_for_row(row)
                    range_scale = self._range_delay_scale_m_per_s(mode=range_mode)
                    try:
                        f1_ghz, f2_ghz = self._get_signal_band_ghz()
                        bw_hz = max(1.0, (f2_ghz - f1_ghz) * 1e9)
                        range_res_m = range_scale / bw_hz
                    except Exception:
                        range_res_m = float("nan")
                    rng_abs = lags.astype(np.float64) / float(fs_ref) * range_scale
                    peak_idx = int(np.argmax(corr_acc)) if len(corr_acc) else 0
                    if len(corr_acc) and len(rng_abs) == len(corr_acc):
                        monostatic_row = "monostatic" in str(range_mode).lower()
                        if monostatic_row:
                            zero_guard_m = max(
                                0.05,
                                2.0 * range_res_m if np.isfinite(range_res_m) and range_res_m > 0 else 0.05,
                            )
                            link_mask = np.isfinite(rng_abs) & (rng_abs > zero_guard_m)
                            if np.any(link_mask):
                                link_idx = np.flatnonzero(link_mask)
                                peak_idx = int(link_idx[int(np.argmax(corr_acc[link_mask]))])
                        elif np.isfinite(rng_abs[peak_idx]) and rng_abs[peak_idx] < 0:
                            pos_mask = np.isfinite(rng_abs) & (rng_abs >= 0.0)
                            if np.any(pos_mask):
                                pos_idx = np.flatnonzero(pos_mask)
                                peak_idx = int(pos_idx[int(np.argmax(corr_acc[pos_mask]))])
                    peak_lag = int(lags[peak_idx]) if len(corr_acc) else 0
                    abs_range_m = float(rng_abs[peak_idx]) if len(rng_abs) > peak_idx else float("nan")
                    abs_range_m = self._refine_range_peak_centroid(
                        rng_abs,
                        corr_acc,
                        peak_idx,
                        0.5 * range_res_m if np.isfinite(range_res_m) and range_res_m > 0 else float("nan"),
                    )

                    zero_delay_s = float(frame_start + peak_lag) / fs_ref
                    frame_period_s = float(n_chirps * pts_per_chirp) / float(fs_ref)
                    prof_db = 20.0 * np.log10(corr_acc / (np.max(corr_acc) + 1e-15) + 1e-15)
                    profile_info = {
                        "lags": lags.astype(np.float64),
                        "prof_db": prof_db.astype(np.float64),
                        "peak_lag": float(peak_lag),
                        "fs": float(fs_ref),
                        "center_m": float(abs_range_m) if np.isfinite(abs_range_m) else 0.0,
                        "abs_range_m": float(abs_range_m) if np.isfinite(abs_range_m) else float("nan"),
                    }
                    freqs_ref, h_ref, w_ref = self._estimate_lfm_cfr(rx_mat, ref_mat, fs_ref)
                    cfr_info = None
                    if len(freqs_ref) >= 16:
                        cfr_info = {
                            "freqs": freqs_ref,
                            "h": h_ref,
                            "weight": w_ref,
                            "fs": float(fs_ref),
                        }
                    info = {
                        "delay_s": zero_delay_s,
                        "frame_start": int(frame_start),
                        "peak_lag": int(peak_lag),
                        "frame_period_s": frame_period_s,
                        "cfr": cfr_info,
                        "profile": profile_info,
                        "profile_center_m": float(profile_info.get("center_m", 0.0)),
                        "abs_range_m": float(abs_range_m) if np.isfinite(abs_range_m) else float("nan"),
                        "range_mode": range_mode,
                        "range_scale_m_per_s": float(range_scale),
                        "range_resolution_m": float(range_res_m),
                        "fs": float(fs_ref),
                    }
                    zero_by_ch[zero_ch] = info
                    if first_info is None:
                        first_info = (zero_ch, info)
                    log_parts.append(
                        f"{zero_ch}: {zero_delay_s * 1e9:.3f} ns "
                        f"(frame={frame_start:,}, lag={peak_lag:,}, "
                        f"range={abs_range_m:.4g} m, CFR={len(freqs_ref):,})"
                    )

                self.runtime["lfm_range_zero_by_ch"] = zero_by_ch
                self._last_range_results = []
                self._last_range_summaries = []
                self.runtime["latest_range_save_role"] = "reference"
                if first_info is not None:
                    first_ch, info = first_info
                    self.runtime["lfm_range_zero_info"] = info
                    self.runtime["lfm_range_zero_delay_s"] = float(info["delay_s"])
                    self.runtime["lfm_range_zero_channel"] = first_ch
                    if info.get("cfr") is not None:
                        self.runtime["lfm_range_zero_cfr"] = info["cfr"]
                self._log("[ISAC] Range zero calibrated: " + " | ".join(log_parts))

                # Keep the user's differential target intact. Store Zero Ref
                # now saves the absolute reference profile/peak; normal
                # detection stays on the absolute range axis and reports
                # current_peak - reference_peak in millimeters.
                try:
                    f1_ghz, f2_ghz = self._get_signal_band_ghz()
                    bw_hz = max(0.0, (f2_ghz - f1_ghz) * 1e9)
                    res_m = (self._range_delay_scale_m_per_s(row=1) / bw_hz) if bw_hz > 0 else float("nan")
                except Exception:
                    res_m = float("nan")
                tol_mm = (max(2.0 * res_m, 0.001) * 1e3) if np.isfinite(res_m) and res_m > 0 else 5.0

                def _apply_zero_range_target(t_mm=tol_mm):
                    self.range_zero_enable_var.set(False)
                    try:
                        cur_tol = abs(float(self.range_tolerance_m_var.get()))
                    except Exception:
                        cur_tol = float("nan")
                    if (not np.isfinite(cur_tol)) or cur_tol > 5.0 * t_mm:
                        self.range_tolerance_m_var.set(f"{t_mm:.3g}")
                self.parent.after(0, _apply_zero_range_target)
                self._log(
                    f"[ISAC] Zero reference stored for overlay/differential range. "
                    f"Enter e.g. -10 in Range Diff (mm) for a -10 mm move. "
                    f"Suggested tolerance={tol_mm:.2f} mm."
                )

                self.parent.after(0, lambda z=", ".join(zero_channels): messagebox.showinfo(
                    "Range Zero Set",
                    f"Range zero set for: {z}\n"
                    "Future range plots stay absolute and overlay each saved reference profile.\n"
                    f"Range Diff was kept unchanged. Suggested tolerance: {tol_mm:.2f} mm."
                ))
            except Exception as e:
                self._log(f"[ISAC] Range zero calibration error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Set Range Zero Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _show_channel_response_results(self, results: list[dict]) -> None:
        self._plot_spectrum_and_time()
        if not results:
            return
        self._last_cfr_summaries = []

        for item in results:
            row = int(item.get("row", 0))
            row = max(0, min(row, len(self.fd_axes) - 1)) if hasattr(self, "fd_axes") else 0
            ax_mag = self.fd_axes[row][2] if hasattr(self, "fd_axes") else self.ax_const
            ax_phase = self.fd_axes[row][3] if hasattr(self, "fd_axes") else getattr(self, "ax_range", self.ax_const)

            ch = str(item.get("ch", "")).strip().upper() or f"Row {row + 1}"
            rf_ghz = np.asarray(item.get("rf_ghz", []), dtype=np.float64)
            mag_db = np.asarray(item.get("mag_db", []), dtype=np.float64)
            phase_resid = np.asarray(item.get("phase_resid_rad", []), dtype=np.float64)
            in_band = np.asarray(item.get("in_band", []), dtype=bool)
            f1_ghz = float(item.get("f1_ghz", float("nan")))
            f2_ghz = float(item.get("f2_ghz", float("nan")))
            ripple_db = float(item.get("ripple_db", float("nan")))
            usable_bw_ghz = float(item.get("usable_bw_ghz", float("nan")))
            band_coverage = float(item.get("band_coverage", float("nan")))
            diff_range_m = float(item.get("diff_range_m", float("nan")))
            diff_coh = float(item.get("diff_coherence", float("nan")))
            group_range_m = float(item.get("group_range_m", float("nan")))

            self._last_cfr_summaries.append({
                "channel": ch,
                "usable_bw_ghz": usable_bw_ghz,
                "band_coverage": band_coverage,
                "ripple_db": ripple_db,
                "diff_range_m": diff_range_m,
                "diff_coherence": diff_coh,
                "group_range_m": group_range_m,
            })

            suffix = "" if len(results) == 1 or row == 0 else f" {ch}"
            key_suffix = "" if len(results) == 1 or row == 0 else f"_{ch.lower()}"
            self._set_metric(f"cfr_usable_bw_ghz{key_suffix}", f"CFR Usable BW{suffix}", usable_bw_ghz, "GHz")
            self._set_metric(f"cfr_band_coverage{key_suffix}", f"CFR Band Coverage{suffix}", band_coverage * 100.0, "%")
            self._set_metric(f"cfr_ripple_db{key_suffix}", f"CFR Ripple{suffix}", ripple_db, "dB")
            self._set_metric(f"cfr_diff_range_mm{key_suffix}", f"CFR Delta Range{suffix}", diff_range_m * 1e3, "mm")
            self._set_metric(f"cfr_diff_coherence{key_suffix}", f"CFR Delta Coherence{suffix}", diff_coh, "")

            ax_mag.cla()
            ax_phase.cla()
            if len(rf_ghz) == 0 or len(mag_db) == 0:
                ax_mag.text(0.5, 0.5, "No CFR data", ha="center", va="center",
                            transform=ax_mag.transAxes, color="gray")
                ax_phase.text(0.5, 0.5, "No CFR data", ha="center", va="center",
                              transform=ax_phase.transAxes, color="gray")
                ax_mag.set_title(f"{ch} |H(f)|")
                ax_phase.set_title(f"{ch} Phase")
                continue

            finite_mag = np.isfinite(rf_ghz) & np.isfinite(mag_db)
            band_span = max(0.1, f2_ghz - f1_ghz) if np.isfinite(f1_ghz) and np.isfinite(f2_ghz) else 1.0
            x_lo = max(0.0, f1_ghz - 0.08 * band_span) if np.isfinite(f1_ghz) else float(np.nanmin(rf_ghz[finite_mag]))
            x_hi = min(25.0, f2_ghz + 0.08 * band_span) if np.isfinite(f2_ghz) else float(np.nanmax(rf_ghz[finite_mag]))
            plot_mask = finite_mag & (rf_ghz >= x_lo) & (rf_ghz <= x_hi)
            if np.count_nonzero(plot_mask) < 8:
                plot_mask = finite_mag

            idx = np.flatnonzero(plot_mask)
            if len(idx) > 2500:
                idx = idx[::max(1, len(idx) // 2500)]

            ax_mag.plot(rf_ghz[idx], mag_db[idx], color="#7c3aed", linewidth=1.0, label="|H|")
            if len(in_band) == len(rf_ghz) and np.any(in_band):
                ib = np.flatnonzero(in_band & np.isfinite(mag_db))
                if len(ib):
                    if len(ib) > 2500:
                        ib = ib[::max(1, len(ib) // 2500)]
                    ax_mag.plot(rf_ghz[ib], mag_db[ib], color="#475569", linewidth=0.8, alpha=0.45, label="Analysis band")
            if np.isfinite(f1_ghz) and np.isfinite(f2_ghz):
                ax_mag.axvspan(f1_ghz, f2_ghz, alpha=0.055, color="#f59e0b")
                ax_mag.axvline(f1_ghz, color="#92400e", lw=0.6, alpha=0.55, linestyle=":")
                ax_mag.axvline(f2_ghz, color="#92400e", lw=0.6, alpha=0.55, linestyle=":")
            ax_mag.axhline(0.0, color="#64748b", linewidth=0.8, linestyle=":")
            if np.any(plot_mask):
                vals = mag_db[plot_mask]
                lo = float(np.nanpercentile(vals, 2)) - 4.0
                hi = float(np.nanpercentile(vals, 98)) + 4.0
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    ax_mag.set_ylim(max(-60.0, lo), min(25.0, hi))
            ax_mag.set_xlim(x_lo, x_hi)
            ax_mag.set_xlabel("Frequency (GHz)")
            ax_mag.set_ylabel("|H(f)| (dB, median-normalized)")
            ax_mag.set_title(f"{ch} |H(f)|  ripple={ripple_db:.2f} dB")
            ax_mag.grid(True, alpha=0.35)
            ax_mag.legend(fontsize=7, loc="best")

            finite_phase = plot_mask & np.isfinite(phase_resid)
            pidx = np.flatnonzero(finite_phase)
            if len(pidx) > 2500:
                pidx = pidx[::max(1, len(pidx) // 2500)]
            if len(pidx) >= 8:
                ax_phase.plot(rf_ghz[pidx], phase_resid[pidx], color="#0f766e", linewidth=1.0)
            else:
                ax_phase.text(0.5, 0.5, "Phase fit unavailable", ha="center", va="center",
                              transform=ax_phase.transAxes, color="gray")
            if np.isfinite(f1_ghz) and np.isfinite(f2_ghz):
                ax_phase.axvspan(f1_ghz, f2_ghz, alpha=0.05, color="#f59e0b")
                ax_phase.axvline(f1_ghz, color="#92400e", lw=0.6, alpha=0.55, linestyle=":")
                ax_phase.axvline(f2_ghz, color="#92400e", lw=0.6, alpha=0.55, linestyle=":")
            ax_phase.set_xlim(x_lo, x_hi)
            ax_phase.set_xlabel("Frequency (GHz)")
            ax_phase.set_ylabel("Phase residual (rad)")
            title = f"{ch} ∠H(f) residual"
            if np.isfinite(diff_range_m):
                title += f"  ΔR={diff_range_m * 1e3:.2f} mm"
            ax_phase.set_title(title)
            ax_phase.grid(True, alpha=0.35)
            note_lines = []
            if np.isfinite(usable_bw_ghz):
                note_lines.append(f"usable BW {usable_bw_ghz:.2f} GHz")
            if np.isfinite(band_coverage):
                note_lines.append(f"coverage {100.0 * band_coverage:.1f}%")
            if np.isfinite(diff_coh):
                note_lines.append(f"CFR coh {diff_coh:.2f}")
            elif np.isfinite(group_range_m):
                note_lines.append(f"uncal. slope {group_range_m:.3g} m")
            if note_lines:
                ax_phase.text(
                    0.03, 0.04, "\n".join(note_lines),
                    transform=ax_phase.transAxes, ha="left", va="bottom",
                    fontsize=8,
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.82, edgecolor="#94a3b8"),
                )

            self._log(
                f"[CFR {ch}] BW={usable_bw_ghz:.3f} GHz "
                f"({100.0 * band_coverage:.1f}% of GUI band), "
                f"ripple={ripple_db:.2f} dB, "
                f"diff={diff_range_m * 1e3:.3f} mm, coh={diff_coh:.3f}"
            )

        self._apply_dashboard_layout()
        self.canvas_plot.draw_idle()
        self._refresh_metrics_table()

    def _show_isac_range_results(self, results: list[dict]) -> None:
        self._plot_spectrum_and_time()
        if not results:
            return
        self._last_range_summaries = []
        results = [self._augment_range_item_with_si_cfr(dict(item)) for item in results]
        self._last_range_results = list(results)
        self.runtime["latest_range_save_role"] = "measurement"

        for item in results:
            row = int(item.get("row", 0))
            row = max(0, min(row, len(self.fd_axes) - 1)) if hasattr(self, "fd_axes") else 0
            ax = self.fd_axes[row][3] if hasattr(self, "fd_axes") else getattr(self, "ax_range", self.ax_const)
            rng = np.asarray(item.get("rng", []), dtype=np.float64)
            prof_db = np.asarray(item.get("prof_db", []), dtype=np.float64)
            si_cfr_rng = np.asarray(item.get("si_cfr_rng", []), dtype=np.float64)
            si_cfr_prof_db = np.asarray(item.get("si_cfr_prof_db", []), dtype=np.float64)
            ref_rng = np.asarray(item.get("ref_rng", []), dtype=np.float64)
            ref_prof_db = np.asarray(item.get("ref_prof_db", []), dtype=np.float64)
            est_range = float(item.get("est_range", float("nan")))
            si_cfr_peak_m = float(item.get("si_cfr_peak_m", float("nan")))
            si_cfr_coh = float(item.get("si_cfr_coherence", float("nan")))
            pslr_db = float(item.get("pslr_db", float("nan")))
            range_profile_snr_db = float(item.get("range_profile_snr_db", float("nan")))
            processing_gain_db = float(item.get("processing_gain_db", float("nan")))
            pg_corrected_snr_db = float(item.get("pg_corrected_snr_db", float("nan")))
            range_mode = str(item.get("range_mode", self._range_mode_for_row(row)))
            si_range_m = float(item.get("self_interference_range_m", float("nan")))
            zero_exclude_m = float(item.get("zero_exclude_m", float("nan")))
            target_range_m = float(item.get("target_range_m", float("nan")))
            target_window_m = float(item.get("target_window_m", float("nan")))
            cfr_diff_range_mm = float(item.get("diff_range_m", float("nan"))) * 1e3
            diff_range_mm = float(item.get("range_diff_mm", cfr_diff_range_mm))
            diff_coh = float(item.get("diff_coherence", float("nan")))
            zero_ref_center_m = float(item.get("zero_ref_center_m", float("nan")))
            target_diff_mm = float(item.get("target_diff_mm", float("nan")))
            range_diff_method = str(item.get("range_diff_method", "peak-reference"))
            display_range_m = float(item.get("display_range_m", est_range))
            range_est_method = str(item.get("range_est_method", "matched-filter"))
            ch = str(item.get("ch", "")).strip().upper() or f"Row {row + 1}"
            zero_active = bool(item.get("zero_active", False))
            x_scale = 1e3
            x_unit = "mm"
            rng_plot = rng * x_scale
            ref_rng_plot = ref_rng * x_scale
            est_plot = est_range * x_scale if np.isfinite(est_range) else est_range
            display_plot = display_range_m * x_scale if np.isfinite(display_range_m) else display_range_m
            reported_range_m = display_range_m if np.isfinite(display_range_m) else est_range
            self._last_range_summaries.append({
                "channel": ch,
                "range_peak_m": reported_range_m,
                "matched_filter_peak_m": est_range,
                "display_range_m": display_range_m,
                "range_est_method": range_est_method,
                "self_interference_range_m": si_range_m,
                "zero_exclude_m": zero_exclude_m,
                "pslr_db": pslr_db,
                "range_profile_snr_db": range_profile_snr_db,
                "processing_gain_db": processing_gain_db,
                "pg_corrected_snr_db": pg_corrected_snr_db,
                "range_mode": range_mode,
                "diff_range_mm": diff_range_mm,
                "cfr_diff_range_mm": cfr_diff_range_mm,
                "range_diff_method": range_diff_method,
                "diff_cfr_coherence": diff_coh,
                "si_cfr_peak_m": si_cfr_peak_m,
                "si_cfr_coherence": si_cfr_coh,
            })
            suffix = "" if len(results) == 1 else f" {ch}"
            self._set_metric(f"range_peak_m{suffix}".strip().replace(" ", "_").lower(),
                             f"Range Peak{suffix}", reported_range_m, "m")
            self._set_metric(f"range_peak_mm{suffix}".strip().replace(" ", "_").lower(),
                             f"Range Peak{suffix}", reported_range_m * 1e3, "mm")
            self._set_metric(f"pslr_db{suffix}".strip().replace(" ", "_").lower(),
                             f"PSLR{suffix}", pslr_db, "dB")
            self._set_metric(f"snr_rad_post_db{suffix}".strip().replace(" ", "_").lower(),
                             f"Sensing post-proc SINR{suffix}", range_profile_snr_db, "dB")
            self._set_metric(f"radar_processing_gain_db{suffix}".strip().replace(" ", "_").lower(),
                             f"Sensing processing gain{suffix}", processing_gain_db, "dB")
            self._set_metric(f"snr_rad_pg_corrected_db{suffix}".strip().replace(" ", "_").lower(),
                             f"Sensing PG-corrected SINR{suffix}", pg_corrected_snr_db, "dB")
            self._set_metric(f"diff_range_mm{suffix}".strip().replace(" ", "_").lower(),
                             f"Range Difference{suffix}", diff_range_mm, "mm")
            self._set_metric(f"diff_cfr_coherence{suffix}".strip().replace(" ", "_").lower(),
                             f"Differential CFR Coh.{suffix}", diff_coh, "")
            self._set_metric(f"si_cfr_peak_m{suffix}".strip().replace(" ", "_").lower(),
                             f"SI-CFR Peak{suffix}", si_cfr_peak_m, "m")
            self._set_metric(f"si_cfr_coherence{suffix}".strip().replace(" ", "_").lower(),
                             f"SI-CFR Coh.{suffix}", si_cfr_coh, "")
            if np.isfinite(si_range_m):
                self._set_metric(f"self_interference_peak_m{suffix}".strip().replace(" ", "_").lower(),
                                 f"Self-Interference Peak{suffix}", si_range_m, "m")
                self._set_metric(f"zero_guard_m{suffix}".strip().replace(" ", "_").lower(),
                                 f"Zero Guard{suffix}", zero_exclude_m, "m")
            if row == 0:
                self._set_metric("range_peak_m", "Range Peak", reported_range_m, "m")
                self._set_metric("range_peak_mm", "Range Peak", reported_range_m * 1e3, "mm")
                self._set_metric("pslr_db", "PSLR", pslr_db, "dB")
                self._set_metric("snr_rad_post_db", "Sensing post-proc SINR", range_profile_snr_db, "dB")
                self._set_metric("radar_processing_gain_db", "Sensing processing gain", processing_gain_db, "dB")
                self._set_metric("snr_rad_pg_corrected_db", "Sensing PG-corrected SINR", pg_corrected_snr_db, "dB")
                self._set_metric("diff_range_mm", "Range Difference", diff_range_mm, "mm")
                self._set_metric("range_difference_mm", "Range Difference", diff_range_mm, "mm")
                self._set_metric("diff_cfr_coherence", "Differential CFR Coh.", diff_coh, "")
                self._set_metric("si_cfr_peak_m", "SI-CFR Peak", si_cfr_peak_m, "m")
                self._set_metric("si_cfr_coherence", "SI-CFR Coh.", si_cfr_coh, "")
            if ch == "C2" and np.isfinite(range_profile_snr_db):
                self._set_metric("snr_rad_post_db_c2", "C2 Sensing post-proc SINR", range_profile_snr_db, "dB")
                self._set_metric("radar_processing_gain_db_c2", "C2 Sensing proc. gain", processing_gain_db, "dB")
                self._set_metric("snr_rad_pg_corrected_db_c2", "C2 Sensing PG-corrected SINR", pg_corrected_snr_db, "dB")
                self._set_metric(
                    "snr_rad_db",
                    "Sensing SINR",
                    range_profile_snr_db,
                    "dB",
                    "C2 post-processing range-profile SNR: target peak minus profile-floor median.",
                )

            ax.cla()
            if len(si_cfr_rng) == 0 or len(si_cfr_rng) != len(si_cfr_prof_db):
                ax.text(0.5, 0.5, "No normalized CFR data", ha="center", va="center",
                        transform=ax.transAxes, color="gray")
            else:
                si_cfr_plot = si_cfr_rng * x_scale
                si_show = (
                    np.isfinite(si_cfr_plot)
                    & np.isfinite(si_cfr_prof_db)
                    & (si_cfr_plot >= 0.0)
                    & (si_cfr_plot <= 2000.0)
                )
                if np.count_nonzero(si_show) >= 4:
                    ax.plot(
                        si_cfr_plot[si_show],
                        si_cfr_prof_db[si_show],
                        color="#dc2626",
                        linewidth=1.2,
                        label="Normalized CFR",
                    )
                    if np.isfinite(si_cfr_peak_m):
                        ax.axvline(
                            si_cfr_peak_m * x_scale,
                            color="#111827",
                            linestyle=":",
                            linewidth=0.9,
                            label=f"Peak {si_cfr_peak_m * x_scale:.1f} {x_unit}",
                        )
                    ax.legend(fontsize=8, loc="upper right")
                else:
                    ax.text(0.5, 0.5, "No normalized CFR data in 0-2000 mm", ha="center", va="center",
                            transform=ax.transAxes, color="gray")
            ax.set_xlabel(f"Range ({x_unit})")
            ax.set_ylabel("Magnitude (dB)")
            ax.set_title(f"{ch} Normalized CFR ({range_mode})")
            ax.set_xlim(0.0, 2000.0)
            ax.set_ylim(-45.0, 10.0)
            ax.grid(True, alpha=0.35)

        self._apply_dashboard_layout()
        self.canvas_plot.draw_idle()
        self._refresh_metrics_table()

    def _show_isac_range_result(self, dechirped: np.ndarray, fs_ref: float,
                                rng: np.ndarray, prof_db: np.ndarray, est_range: float) -> None:
        self._plot_spectrum_and_time()

        ax = getattr(self, "ax_range", self.ax_const)
        ax.cla()
        show = np.ones(len(rng), dtype=bool)
        if len(rng) and np.isfinite(est_range):
            finite_rng = rng[np.isfinite(rng)]
            if len(finite_rng):
                total_span = float(np.nanmax(finite_rng) - np.nanmin(finite_rng))
                half_span = max(10.0, min(200.0, 0.10 * total_span))
                show = (rng >= est_range - half_span) & (rng <= est_range + half_span)
                if np.count_nonzero(show) < 8:
                    show = np.ones(len(rng), dtype=bool)
        ax.plot(rng[show] * 1e3, prof_db[show], color="#0f766e", linewidth=1.2)
        if np.isfinite(est_range):
            ax.axvline(est_range * 1e3, color="#dc2626", linestyle="--", label=f"Peak {est_range*1e3:.2f} mm")
            ax.legend(fontsize=8)
        ax.set_xlabel("Range (mm)")
        ax.set_ylabel("Magnitude (dB)")
        ax.set_title(f"{self.ch_var.get().strip().upper()} Range Profile")
        self._apply_range_xlim(ax, est_range, x_scale=1e3)
        if np.any(show):
            try:
                y_hi = max(5.0, float(np.nanmax(prof_db[show])) + 8.0)
            except Exception:
                y_hi = 10.0
            ax.set_ylim(-45.0, y_hi)
        ax.grid(True, alpha=0.35)
        mode = self._range_mode_for_row(0)
        pslr_db = self._compute_pslr_db(10.0 ** (np.asarray(prof_db, dtype=np.float64) / 20.0), rng, mode=mode)
        self._set_metric("range_peak_m", "Range Peak", est_range, "m")
        self._set_metric("range_peak_mm", "Range Peak", est_range * 1e3, "mm")
        self._set_metric("pslr_db", "PSLR", pslr_db, "dB")
        self._last_range_summaries = [{
            "channel": self.ch_var.get().strip().upper(),
            "range_peak_m": est_range,
            "pslr_db": pslr_db,
            "range_mode": mode,
        }]
        self._refresh_metrics_table()
        self._apply_dashboard_layout()
        self.canvas_plot.draw_idle()

    def _plot_correlation_for_debug(
        self,
        corr_data: np.ndarray,
        title: str = "DIAGNOSTIC: Frame Sync Correlation",
        xlabel: str = "Lag (samples)",
    ) -> None:
        """Plots the raw correlation vector for debugging sync issues."""
        if not bool(getattr(self, "show_sync_corr_var", tk.BooleanVar(value=False)).get()):
            return
        ax = getattr(self, "ax_const", self.fd_axes[0][2])
        ax.cla()
        ax.plot(corr_data, color="purple", linewidth=0.8)
        if len(corr_data) > 0:
            peak_val = np.max(corr_data)
            peak_idx = np.argmax(corr_data)
            mean_val = np.mean(corr_data)
            ax.axhline(mean_val, color='r', linestyle='--', linewidth=1.0, label=f"Mean: {mean_val:.2e}")
            ax.plot(peak_idx, peak_val, 'x', color='red', markersize=8, label=f"Peak: {peak_val:.2e}")
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Correlation Magnitude")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.4)
        self.canvas_plot.draw_idle()

    def _on_demodulate(self, show_errors: bool = True, run_async: bool = True) -> None:
        if self._rx_sig is None:
            if show_errors:
                messagebox.showwarning("No data", "Acquire a signal first.")
            else:
                self._log("[Demod] Skipped: no acquired signal.")
            return

        try:
            pl_pre = self._load_tx_payload_for_isac()
            if pl_pre is not None:
                self._sync_dsp_params_from_payload(pl_pre, source="demod", force=False)
                self._assert_dsp_payload_consistent(pl_pre, context="demod")
        except Exception as e:
            self._log(f"[Demod] Setup error: {e}")
            if show_errors:
                messagebox.showerror("Demodulate Error", str(e))
            return

        # Retrieve tkinter variables in the main thread
        demod_mod_val = self.demod_mod_var.get()
        demod_beta_val = self.demod_beta_var.get()
        demod_span_val = self.demod_span_var.get()
        filter_enable_val = bool(self.filter_enable_var.get())
        sc_fde_taps_val = self.sc_fde_taps_var.get()
        sc_fde_enable_val = bool(self.sc_fde_enable_var.get())

        def worker():
            try:
                pl = self._load_tx_payload_for_isac()
                if pl is None:
                    if show_errors:
                        self.parent.after(0, lambda: messagebox.showwarning(
                            "No TX Reference", "Generate the TX signal first."))
                    else:
                        self._log("[Demod] Skipped: no TX reference.")
                    return

                self._warn_if_tx_reference_stale(pl)
                self._assert_dsp_payload_consistent(pl, context="demod")
                requested_mod = str(demod_mod_val).strip().upper()
                pl = self._ensure_qam_reference_modulation(pl, requested_mod)

                # +++ DIAGNOSTIC: Log loaded payload info +++
                _sr_req = float(pl.get("symbol_rate", 0.0))
                _sr_act = float(pl.get("symbol_rate_actual", _sr_req))
                _if_req = float(pl.get("if_freq_requested", pl.get("if_freq", 0.0)))
                _if_iqtools = float(pl.get("iqtools_if_freq", pl.get("if_freq", _if_req)))
                self._log(
                    "[Demod] DSP rev=2026-07-03-dft-lock-srate. "
                    f"[Demod] Loaded TX ref: type={pl.get('waveform_type')}, mod={pl.get('modulation')}, "
                    f"prbs={pl.get('prbs_n')} data_bits={int(pl.get('payload_data_bits', 0)):,}/"
                    f"{int(pl.get('prbs_bits_target', 0)):,}, "
                    f"sr={_sr_req/1e9:.6f}GHz(actual={_sr_act/1e9:.6f}), "
                    f"if={_if_req/1e9:.6f}GHz(iqtools-grid={_if_iqtools/1e9:.6f}), "
                    f"sps={pl.get('sps')}"
                )

                sig = np.asarray(self._rx_sig, dtype=np.float64)
                try:
                    beta_guard = float(pl.get("qam_rrc_beta", demod_beta_val))
                    wf_guard = str(pl.get("waveform_type", "")).strip()
                    if wf_guard == "DFT-s-OFDM":
                        half_bw_guard = 0.5 * self._tx_occupied_bw_hz(pl)
                    elif wf_guard == "LFM-QAM":
                        half_bw_guard = max(0.5 * _sr_act * (1.0 + beta_guard), _sr_act)
                    else:
                        half_bw_guard = 0.5 * _sr_act * (1.0 + beta_guard)
                    nyq_guard = 0.5 * float(self._rx_fs)
                    if _if_iqtools > 0 and (_if_iqtools + half_bw_guard) > 0.90 * nyq_guard:
                        self._log(
                            "[Demod] WARNING: IF band is close to DSO Nyquist: "
                            f"IF+BW/2={(_if_iqtools + half_bw_guard)/1e9:.2f} GHz, "
                            f"Nyquist={nyq_guard/1e9:.2f} GHz. "
                            "Use a lower IF or a higher DSO SR if aliasing appears."
                        )
                except Exception:
                    pass
                if bool(getattr(self, "show_sync_corr_var", tk.BooleanVar(value=False)).get()):
                    raw_lock, raw_lag, raw_len = self._raw_awg_waveform_lock_probe(
                        sig,
                        float(self._rx_fs),
                        pl,
                    )
                    self._log(
                        f"[Demod] raw AWG waveform lock: corr={raw_lock:.3f}  "
                        f"lag={raw_lag:,} samples  probe_len={raw_len:,}"
                    )
                rx_bb, fs_ref = self._rx_to_baseband(
                    sig,
                    float(self._rx_fs),
                    pl,
                    apply_lpf=filter_enable_val,
                )

                waveform_type = str(pl.get("waveform_type", "LFM-QAM")).strip()
                mod = requested_mod if waveform_type == "QAM" and requested_mod else str(pl.get("modulation", demod_mod_val)).strip()
                sc_fde_taps = max(1, int(_parse_float_input(sc_fde_taps_val, "Post-EQ Taps")))
                sc_fde_enable = sc_fde_enable_val
                nps = int(pl.get("sps", 1))
                ber_reference_valid = True
                blind_metric_mode = False

                # The previous grid search only inspected the start of the DSO
                # record.  If the frame began later, unrelated payload samples
                # produced a false CFO estimate.  QAM rotational symmetry gives
                # a blind estimate without knowing the frame position first.
                if waveform_type == "QAM":
                    coarse_cfo_hz, blind_phase, cfo_quality = self._estimate_qam_cfo_mth_power(
                        rx_bb, fs_ref, nps, mod
                    )
                    if cfo_quality >= 5.0 and abs(coarse_cfo_hz) > 1e-3:
                        rx_bb = IsacTxSimPanel._cfo_compensate(rx_bb, coarse_cfo_hz, fs_ref)
                    elif cfo_quality < 5.0:
                        self._log("[Demod] WARNING: blind CFO peak is weak; leaving CFO uncorrected.")
                    self._log(
                        f"[Demod] blind CFO={coarse_cfo_hz/1e3:.2f} kHz  "
                        f"timing_phase={blind_phase}/{nps}  quality={cfo_quality:.1f}x"
                    )
                elif waveform_type in ("LFM-QAM", "DFT-s-OFDM"):
                    # _cfo_grid_search only inspects signal[:len(template)*3]
                    # (one ZC-preamble chirp's worth), exactly the bug the
                    # comment above describes -- but real DSO captures here
                    # routinely put frame_start hundreds of thousands of
                    # samples into the record (pre-trigger margin), so that
                    # window is pure idle/noise and the "coarse CFO" it
                    # returns is essentially random (observed: -1200 kHz on
                    # one capture, +2400 kHz on the next, same setup).
                    # Applying that blind guess to the whole record before
                    # frame sync corrupts everything downstream. Both
                    # LFM-QAM and DFT-s-OFDM instead locate frame_start first
                    # via a full-record correlation, then
                    # `_frame_sync_and_reshape` -> `_refine_lfm_frame_sro`
                    # jointly fits CFO and SRO against the now-correctly
                    # located reference -- so no blind pre-correction here.
                    pass
                else:
                    try:
                        tx_bb_matrix_cfo = np.asarray(pl.get("tx_bb_matrix", []), dtype=np.complex128)
                        if tx_bb_matrix_cfo.size > 0:
                            coarse_cfo_hz, _ = IsacTxSimPanel._cfo_grid_search(
                                rx_bb, tx_bb_matrix_cfo[0], fs_ref, 15e6, num_steps=51
                            )
                            if abs(coarse_cfo_hz) > 1e-3:
                                rx_bb = IsacTxSimPanel._cfo_compensate(rx_bb, coarse_cfo_hz, fs_ref)
                                self._log(
                                    f"[Demod] Applied coarse CFO correction: "
                                    f"{coarse_cfo_hz/1e3:.2f} kHz"
                                )
                    except Exception as cfo_e:
                        self._log(f"[Demod] CFO estimation failed: {cfo_e}")

                _if_freq_log = float(pl.get("if_freq", 0.0))
                self._log(f"[Demod] waveform={waveform_type}  mod={mod}  "
                          f"if_freq={_if_freq_log/1e9:.3f} GHz  "
                          f"fs_rx={float(self._rx_fs)/1e9:.3f} GHz  "
                          f"fs_ref={fs_ref/1e9:.3f} GHz  nps={nps}  "
                          f"N_bb={len(rx_bb):,}  "
                          f"demod_lpf={'on' if filter_enable_val else 'off'}")
                if waveform_type == "DFT-s-OFDM":
                    occupied_hz = self._tx_occupied_bw_hz(pl)
                    rf_lo = (_if_freq_log - 0.5 * occupied_hz) / 1e9
                    rf_hi = (_if_freq_log + 0.5 * occupied_hz) / 1e9
                    bb_lpf = min(0.65 * occupied_hz, fs_ref * 0.45)
                    self._log(
                        "[Demod] DFT grid: "
                        f"occupied={occupied_hz/1e9:.3f} GHz, "
                        f"display_band={rf_lo:.3f}-{rf_hi:.3f} GHz, "
                        f"bb_lpf={bb_lpf/1e9:.3f} GHz, "
                        f"rx_nyquist={0.5*float(self._rx_fs)/1e9:.3f} GHz. "
                        "The muted spectrum overlay is raw PSD highlighted inside this analysis band."
                    )

                def _recover_dfts_ofdm_once(rx_bb_in: np.ndarray, retry_label: str = "") -> dict:
                    rx_mat_local, tx_bb_mat_local, tx_sym_mat_local, base_chirp_local, n_chirps_local, n_sym_local, _, pts_per_chirp_local, frame_start_local = \
                        self._frame_sync_and_reshape(rx_bb_in, fs_ref, pl)
                    corr_local = np.abs(fftconvolve(rx_bb_in, np.conj(tx_bb_mat_local[0][::-1]), mode="valid"))
                    qam_est_local, qam_ref_local, dft_diag_local = self._recover_dfts_ofdm_symbols(rx_mat_local, pl)
                    dft_widely_linear_local = str(mod).strip().upper() not in {"BPSK", "QPSK", "8PSK"}
                    dft_payload_lock_local, _ = self._reference_lock_score(
                        qam_est_local,
                        qam_ref_local,
                        train_mask=None,
                        track_phase=False,
                        widely_linear=dft_widely_linear_local,
                    )
                    dft_diag_local["payload_lock"] = float(dft_payload_lock_local)
                    self._log(
                        f"[Demod] DFT-s-OFDM recover{retry_label}: blocks={dft_diag_local['blocks']}  "
                        f"pilot_lock={dft_diag_local['pilot_lock']:.3f} "
                        f"(min={dft_diag_local['pilot_lock_min']:.3f})  "
                        f"payload_lock={dft_payload_lock_local:.3f}  "
                        f"channel_ripple={dft_diag_local['channel_ripple_db']:.2f} dB  "
                        f"pilot_cfo={dft_diag_local['cfo_hz_mean']/1e3:.1f} kHz "
                        f"(max={dft_diag_local['cfo_hz_maxabs']/1e3:.1f})  "
                        f"dd_refine={dft_diag_local['dd_updates']}  "
                        f"fde={dft_diag_local.get('fde_updates', 0)}  "
                        f"ref_aided={dft_diag_local.get('ref_updates', 0)}  "
                        f"rho={float(pl.get('amplitude_ratio_rho', 0.20)):.2f}"
                    )
                    return {
                        "rx_bb": rx_bb_in,
                        "rx_mat": rx_mat_local,
                        "tx_bb_mat": tx_bb_mat_local,
                        "tx_sym_mat": tx_sym_mat_local,
                        "base_chirp": base_chirp_local,
                        "n_chirps": int(n_chirps_local),
                        "n_sym": int(n_sym_local),
                        "pts_per_chirp": int(pts_per_chirp_local),
                        "frame_start": int(frame_start_local),
                        "qam_est": qam_est_local,
                        "qam_ref": qam_ref_local,
                        "dft_diag": dft_diag_local,
                        "dft_payload_lock": float(dft_payload_lock_local),
                        "corr_dft": corr_local,
                    }

                if waveform_type == "QAM":
                    # --- QAM Demodulation (Single Carrier, No Chirp) ---
                    qam_preamble_symbols = np.asarray(pl.get("qam_preamble_symbols", []), dtype=np.complex128).reshape(-1)
                    qam_rrc_taps = np.asarray(pl.get("qam_rrc_taps", [1.0]), dtype=np.float64).reshape(-1)
                    qam_rrc_beta = float(pl.get("qam_rrc_beta", 0.20))
                    qam_rrc_span = int(pl.get("qam_rrc_span", 8))
                    try:
                        ui_rrc_beta = float(np.clip(float(demod_beta_val), 0.0, 1.0))
                    except Exception:
                        ui_rrc_beta = qam_rrc_beta
                    try:
                        ui_rrc_span = max(1, int(float(demod_span_val)))
                    except Exception:
                        ui_rrc_span = qam_rrc_span
                    qam_ref_full = np.asarray(
                        pl.get("tx_sym_matrix", []), dtype=np.complex128
                    ).reshape(-1)
                    if len(qam_ref_full) == 0:
                        raise ValueError("QAM symbol reference is empty. Regenerate the TX signal.")
                    if len(qam_preamble_symbols) < 8:
                        raise ValueError("QAM preamble reference is missing. Regenerate the TX signal.")

                    # Match-filter the complete capture, then find the known ZC
                    # preamble at symbol rate.  This remains coherent through
                    # analogue channel distortion that makes sample-for-sample
                    # correlation with the complete TX waveform too brittle.
                    rx_mf_all = fftconvolve(rx_bb, qam_rrc_taps, mode="same")
                    pre_energy = float(np.sum(np.abs(qam_preamble_symbols) ** 2))
                    best_sync = None
                    for sample_phase in range(max(1, nps)):
                        symbol_stream_try = rx_mf_all[sample_phase::nps]
                        if len(symbol_stream_try) < len(qam_preamble_symbols):
                            continue
                        pre_corr = np.abs(fftconvolve(
                            symbol_stream_try,
                            np.conj(qam_preamble_symbols[::-1]),
                            mode="valid",
                        ))
                        window_energy = np.convolve(
                            np.abs(symbol_stream_try) ** 2,
                            np.ones(len(qam_preamble_symbols), dtype=np.float64),
                            mode="valid",
                        )
                        pre_corr_norm = pre_corr / np.sqrt(
                            pre_energy * window_energy + 1e-15
                        )
                        peak_i = int(np.argmax(pre_corr_norm))
                        peak_v = float(pre_corr_norm[peak_i])
                        if best_sync is None or peak_v > best_sync[0]:
                            best_sync = (
                                peak_v, sample_phase, peak_i,
                                symbol_stream_try, pre_corr_norm,
                            )
                    if best_sync is None:
                        raise ValueError("QAM preamble timing search produced no symbols.")

                    timing_score, sample_phase, best_pre_idx, symbol_stream, pre_corr_norm = best_sync
                    self._log(
                        f"[Demod] QAM preamble sync: phase={sample_phase}/{nps}  "
                        f"symbol={best_pre_idx:,}  norm_corr={timing_score:.3f}"
                    )
                    self.parent.after(
                        0,
                        lambda c=pre_corr_norm: self._plot_correlation_for_debug(
                            c,
                            title="DIAGNOSTIC: QAM Preamble Sync",
                            xlabel="Lag (symbols)",
                        ),
                    )

                    from scipy.signal import find_peaks
                    n_sym_per_chirp = int(pl.get("n_sym_per_chirp", len(qam_ref_full)))
                    n_chirps = int(pl.get("n_chirps", 1))
                    peak_height = max(0.20, 0.60 * timing_score)
                    pre_peaks, _ = find_peaks(
                        pre_corr_norm,
                        height=peak_height,
                        distance=max(len(qam_preamble_symbols), n_sym_per_chirp // 2),
                    )
                    if best_pre_idx not in pre_peaks:
                        pre_peaks = np.unique(np.append(pre_peaks, best_pre_idx))
                    if len(pre_peaks) > 12:
                        strongest = np.argsort(pre_corr_norm[pre_peaks])[-12:]
                        pre_peaks = np.sort(pre_peaks[strongest])

                    # Exclude known ZC preambles from constellation and EVM.
                    # This supports both the legacy per-chirp preambles and a
                    # single frame-level preamble.
                    qam_preamble_len = int(pl.get("qam_preamble_len", 0))
                    data_mask = np.ones(len(qam_ref_full), dtype=bool)
                    ref_matrix = np.asarray(pl.get("tx_sym_matrix", []), dtype=np.complex128)
                    if qam_preamble_len > 0 and len(qam_preamble_symbols) == qam_preamble_len:
                        if ref_matrix.ndim == 2:
                            for row in range(ref_matrix.shape[0]):
                                if np.allclose(
                                    ref_matrix[row, :qam_preamble_len],
                                    qam_preamble_symbols,
                                    rtol=1e-7, atol=1e-9,
                                ):
                                    start_i = row * ref_matrix.shape[1]
                                    data_mask[start_i:start_i + qam_preamble_len] = False
                        else:
                            data_mask[:qam_preamble_len] = False
                    preamble_mask = ~data_mask
                    if np.count_nonzero(preamble_mask) < 8:
                        preamble_mask = np.ones(len(qam_ref_full), dtype=bool)

                    # Repeated preambles reveal chirp boundaries but not which
                    # chirp is row zero.  Test possible row identities and run
                    # Gardner timing recovery from each candidate frame start.
                    rough_frame_starts: list[tuple[int, int]] = []
                    for pre_idx in pre_peaks:
                        for row_idx in range(max(1, n_chirps)):
                            frame_start_sym = int(pre_idx) - row_idx * n_sym_per_chirp
                            if frame_start_sym < 0:
                                continue
                            frame_start_sample = sample_phase + frame_start_sym * nps
                            if 0 <= frame_start_sample < len(rx_mf_all):
                                rough_frame_starts.append((frame_start_sym, frame_start_sample))
                    rough_frame_starts = list(dict.fromkeys(rough_frame_starts))

                    best_frame = None
                    refined = None
                    if rough_frame_starts and timing_score < 0.85:
                        refined = self._refine_qam_frame_cfo_sro(
                            rx_mf_all,
                            fs_ref,
                            qam_ref_full,
                            preamble_mask,
                            data_mask,
                            rough_frame_starts,
                            nps,
                            mod,
                        )
                        if refined is not None:
                            best_frame = (
                                refined["rank_score"],
                                refined["pre_score"],
                                refined["data_score"],
                                refined["frame_start_sym"],
                                int(round(refined["start_sample"])),
                                -2.0,
                                np.asarray(refined["symbols"], dtype=np.complex128).copy(),
                            )
                            self._log(
                                f"[Demod] QAM CFO/SRO refined sync: sync={refined['sync_score']:.3f}  "
                                f"pre={refined['pre_score']:.3f}  data={refined['data_score']:.3f}  "
                                f"cfo={refined['cfo_hz']/1e6:.3f} MHz  "
                                f"sro={refined['sro_ppm']:.1f} ppm  mode={refined['mode']}  "
                                f"start={int(round(refined['start_sample'])):,}"
                            )
                        else:
                            self._log(
                                f"[Demod] QAM CFO/SRO refined sync: no usable candidate "
                                f"(rough_starts={len(rough_frame_starts)})"
                            )

                    timing_gains = (0.0, 0.0015, 0.004, 0.008)
                    qam_sync_widely_linear = str(mod).strip().upper() not in {"BPSK", "QPSK", "8PSK"}
                    for frame_start_sym, frame_start_sample in rough_frame_starts:
                        frame_end_sym = frame_start_sym + len(qam_ref_full)
                        for tg in timing_gains:
                            if tg == 0.0 and frame_end_sym <= len(symbol_stream):
                                est_try = symbol_stream[frame_start_sym:frame_end_sym].copy()
                            else:
                                est_try = self._recover_qam_symbols_from_mf(
                                    rx_mf_all,
                                    frame_start_sample=frame_start_sample,
                                    sps=nps,
                                    n_symbols=len(qam_ref_full),
                                    gain=tg,
                                )
                            if len(est_try) < len(qam_ref_full):
                                continue
                            est_try = est_try[:len(qam_ref_full)]
                            pre_score, _ = self._reference_lock_score(
                                est_try,
                                qam_ref_full,
                                train_mask=preamble_mask,
                                track_phase=False,
                                widely_linear=qam_sync_widely_linear,
                            )
                            data_score, _ = self._reference_lock_score(
                                est_try,
                                qam_ref_full,
                                train_mask=data_mask,
                                track_phase=False,
                                widely_linear=qam_sync_widely_linear,
                            )
                            rank_score = pre_score + 0.35 * data_score
                            if best_frame is None or rank_score > best_frame[0]:
                                best_frame = (
                                    rank_score,
                                    pre_score,
                                    data_score,
                                    frame_start_sym,
                                    frame_start_sample,
                                    tg,
                                    est_try.copy(),
                                )

                    if best_frame is None:
                        frame_start_sym = max(
                            0,
                            min(best_pre_idx, max(0, len(symbol_stream) - len(qam_ref_full))),
                        )
                        frame_start = sample_phase + frame_start_sym * nps
                        qam_est_raw = self._recover_qam_symbols_from_mf(
                            rx_mf_all,
                            frame_start_sample=frame_start,
                            sps=nps,
                            n_symbols=len(qam_ref_full),
                            gain=0.0,
                        )
                        if len(qam_est_raw) < 64:
                            raise ValueError("The capture does not contain enough QAM symbols.")
                        best_frame = (0.0, 0.0, 0.0, frame_start_sym, frame_start, 0.0, qam_est_raw)

                    _, preamble_lock_score, ref_lock_score, frame_start_sym, frame_start, timing_gain_used, qam_est_raw = best_frame
                    if ref_lock_score >= 0.30:
                        qam_ref = qam_ref_full.copy()
                        qam_est = qam_est_raw.copy()
                        ref_idx = np.arange(len(qam_ref), dtype=np.int64)
                        self._log(
                            f"[Demod] QAM TX-reference lock: preamble={preamble_lock_score:.3f}  "
                            f"data={ref_lock_score:.3f}  gardner_gain={timing_gain_used:.4f}  "
                            f"frame_start={int(frame_start):,}"
                        )
                    else:
                        # Low data-correlation is common before equalization on
                        # real captures.  Keep the deterministic PRBS/TX
                        # reference for EVM and BER, but log the low confidence.
                        qam_ref = qam_ref_full.copy()
                        qam_est = qam_est_raw[:len(qam_ref_full)].copy()
                        if len(qam_est) < 64:
                            raise ValueError("The capture does not contain enough QAM symbols.")
                        ref_idx = np.arange(len(qam_ref), dtype=np.int64)
                        self._log(
                            f"[Demod] WARNING: TX-reference data lock={ref_lock_score:.3f} "
                            f"(preamble={preamble_lock_score:.3f}); continuing with "
                            f"deterministic PRBS reference for BER/EVM."
                        )

                    used_prbs_fallback = False
                    fb_score = 0.0
                    if timing_score < 0.55 or ref_lock_score < 0.20:
                        fb_est, fb_ref, fb_score, fb_phase, fb_start, fb_off, fb_mode = self._prbs_symbol_stream_fallback(
                            rx_mf_all,
                            sps=nps,
                            modulation=mod,
                            prbs_n=int(pl.get("prbs_n", 11)),
                            n_symbols=int(np.count_nonzero(data_mask)),
                            preferred_phase=sample_phase,
                            preferred_start=best_pre_idx,
                        )
                        self._log(
                            f"[Demod] PRBS fallback probe: score={fb_score:.3f}  "
                            f"phase={fb_phase}/{nps}  start={fb_start}  offset={fb_off}  mode={fb_mode}"
                        )
                        if len(fb_est) >= 64 and fb_score > max(ref_lock_score, 0.25):
                            qam_est = fb_est
                            qam_ref = fb_ref
                            used_prbs_fallback = True
                            frame_start = fb_phase + fb_start * nps
                            self._log("[Demod] PRBS fallback selected; bypassing weak preamble frame sync.")

                    if not used_prbs_fallback and timing_score < 0.55 and ref_lock_score < 0.20:
                        beta_candidates = tuple(
                            b for b in (ui_rrc_beta, 0.35, 0.25, 0.50)
                            if np.isfinite(b)
                        )
                        blind_est, blind_ref, blind_evm, blind_phase, blind_start, blind_entropy, blind_sro_ppm, blind_method, blind_filter = (
                            self._blind_qam_filter_symbol_search(
                                rx_bb,
                                rx_mf_all,
                                sps=nps,
                                modulation=mod,
                                n_symbols=int(np.count_nonzero(data_mask)),
                                preferred_phase=sample_phase,
                                primary_beta=qam_rrc_beta,
                                span=ui_rrc_span,
                                extra_betas=beta_candidates,
                            )
                        )
                        if len(blind_est) < 64:
                            raise ValueError(
                                "No reliable QAM/PRBS lock and too few symbols for blind constellation display. "
                                f"preamble_corr={timing_score:.3f}, data_corr={ref_lock_score:.3f}, "
                                f"prbs_corr={fb_score:.3f}."
                            )
                        qam_est = blind_est
                        qam_ref = blind_ref
                        used_prbs_fallback = True
                        ber_reference_valid = False
                        blind_metric_mode = True
                        frame_start = int(blind_phase + blind_start * nps)
                        self._log(
                            "No reliable QAM/PRBS lock; showing blind decision-directed constellation only. "
                            f"preamble_corr={timing_score:.3f}, data_corr={ref_lock_score:.3f}, "
                            f"prbs_corr={fb_score:.3f}. "
                            f"blind_phase={blind_phase}/{nps}, blind_start={blind_start}, "
                            f"blind_filter={blind_filter}, blind_method={blind_method}, "
                            f"blind_sro={blind_sro_ppm:.0f} ppm, "
                            f"blind_evm={20.0*np.log10(blind_evm + 1e-15):.2f} dB, "
                            f"entropy={blind_entropy:.2f}. BER is unavailable until the TX PRBS/reference matches."
                        )

                    if not used_prbs_fallback:
                        keep = data_mask[ref_idx]
                        qam_ref = qam_ref[keep]
                        qam_est = qam_est[keep]

                elif waveform_type == "DFT-s-OFDM":
                    dft_candidates: list[dict] = []

                    def _dft_candidate_score(result: dict) -> float:
                        diag_i = result.get("dft_diag", {})
                        blocks_i = float(diag_i.get("blocks", 0))
                        payload_i = float(result.get("dft_payload_lock", 0.0))
                        pilot_i = float(diag_i.get("pilot_lock", 0.0))
                        min_pilot_i = float(diag_i.get("pilot_lock_min", 0.0))
                        return 20.0 * payload_i + 2.0 * pilot_i + min_pilot_i + 0.005 * blocks_i

                    def _add_dft_candidate(
                        label: str,
                        rx_bb_candidate: np.ndarray | None = None,
                        *,
                        apply_lpf_i: bool = True,
                        sideband_sign_i: int = -1,
                        conjugate_i: bool = False,
                    ) -> None:
                        try:
                            if rx_bb_candidate is None:
                                rx_bb_candidate, _ = self._rx_to_baseband(
                                    sig,
                                    float(self._rx_fs),
                                    pl,
                                    apply_lpf=apply_lpf_i,
                                    sideband_sign=sideband_sign_i,
                                    conjugate_output=conjugate_i,
                                )
                            res_i = _recover_dfts_ofdm_once(rx_bb_candidate, f" [{label}]")
                            res_i["candidate_label"] = label
                            res_i["candidate_score"] = _dft_candidate_score(res_i)
                            dft_candidates.append(res_i)
                        except Exception as cand_e:
                            self._log(f"[Demod] DFT-s-OFDM candidate {label} failed: {cand_e}")

                    _add_dft_candidate("default", rx_bb)
                    best_so_far = max(dft_candidates, key=lambda r: r.get("candidate_score", -np.inf)) if dft_candidates else None
                    def _dft_good_enough(res: dict | None) -> bool:
                        if not res:
                            return False
                        diag = res.get("dft_diag", {})
                        return (
                            len(res.get("qam_est", [])) >= 64
                            and float(res.get("dft_payload_lock", 0.0)) >= 0.10
                            and float(diag.get("pilot_lock_min", 0.0)) >= 0.04
                        )

                    if not _dft_good_enough(best_so_far):
                        # Fast path first: the usual direct chain plus the
                        # common conjugate ambiguity. Only expand further if
                        # these still do not lock.
                        _add_dft_candidate("default+conj", None, apply_lpf_i=filter_enable_val, sideband_sign_i=-1, conjugate_i=True)
                        best_so_far = max(dft_candidates, key=lambda r: r.get("candidate_score", -np.inf)) if dft_candidates else None
                    if filter_enable_val and not _dft_good_enough(best_so_far):
                        _add_dft_candidate("LPF-off", None, apply_lpf_i=False, sideband_sign_i=-1, conjugate_i=False)
                        best_so_far = max(dft_candidates, key=lambda r: r.get("candidate_score", -np.inf)) if dft_candidates else None
                    if not _dft_good_enough(best_so_far):
                        # Last resort: opposite-sideband hypotheses are
                        # expensive because they re-run sync/recovery. Keep
                        # them out of the normal successful path.
                        _add_dft_candidate("opposite-sideband", None, apply_lpf_i=filter_enable_val, sideband_sign_i=+1, conjugate_i=False)
                        best_so_far = max(dft_candidates, key=lambda r: r.get("candidate_score", -np.inf)) if dft_candidates else None
                    if not _dft_good_enough(best_so_far):
                        _add_dft_candidate("opposite-sideband+conj", None, apply_lpf_i=filter_enable_val, sideband_sign_i=+1, conjugate_i=True)

                    if not dft_candidates:
                        raise ValueError("No DFT-s-OFDM demodulation candidate produced symbols.")
                    dft_result_best = max(dft_candidates, key=lambda r: r.get("candidate_score", -np.inf))
                    self._log(
                        f"[Demod] DFT-s-OFDM selected candidate: {dft_result_best.get('candidate_label', 'unknown')}  "
                        f"score={dft_result_best.get('candidate_score', float('nan')):.3f}  "
                        f"payload_lock={dft_result_best['dft_payload_lock']:.3f}  "
                        f"pilot_lock={dft_result_best['dft_diag']['pilot_lock']:.3f}  "
                        f"min_pilot={dft_result_best['dft_diag']['pilot_lock_min']:.3f}"
                    )

                    rx_bb = dft_result_best["rx_bb"]
                    rx_mat = dft_result_best["rx_mat"]
                    tx_bb_mat = dft_result_best["tx_bb_mat"]
                    tx_sym_mat = dft_result_best["tx_sym_mat"]
                    base_chirp = dft_result_best["base_chirp"]
                    n_chirps = dft_result_best["n_chirps"]
                    n_sym = dft_result_best["n_sym"]
                    pts_per_chirp = dft_result_best["pts_per_chirp"]
                    frame_start = dft_result_best["frame_start"]
                    qam_est = dft_result_best["qam_est"]
                    qam_ref = dft_result_best["qam_ref"]
                    dft_diag = dft_result_best["dft_diag"]
                    dft_payload_lock = dft_result_best["dft_payload_lock"]
                    expected_blocks = max(1, int(pl.get("n_chirps", dft_diag.get("blocks", 1))))
                    blocks_ratio = min(1.0, float(dft_diag.get("blocks", 0)) / float(expected_blocks))
                    payload_lock_floor = 0.03 if blocks_ratio < 0.5 else (0.05 if blocks_ratio < 0.85 else 0.10)
                    pilot_min_floor = 0.015
                    if dft_diag.get("blocks", 0) < expected_blocks:
                        self._log(
                            f"[Demod] DFT-s-OFDM partial-frame capture: blocks={dft_diag.get('blocks', 0)}/{expected_blocks} "
                            f"({100.0 * blocks_ratio:.1f}%). Using relaxed lock floor {payload_lock_floor:.3f}."
                        )
                    self.parent.after(
                        0,
                        lambda c=dft_result_best["corr_dft"]: self._plot_correlation_for_debug(
                            c,
                            title="DIAGNOSTIC: DFT-s-OFDM Frame Sync",
                            xlabel="Lag (samples)",
                        ),
                    )
                    if len(qam_est) < 64 or dft_payload_lock < payload_lock_floor or dft_diag["pilot_lock_min"] < pilot_min_floor:
                        raise ValueError(
                            "No reliable DFT-s-OFDM/PRBS lock. "
                            f"payload_lock={dft_payload_lock:.3f}, "
                            f"pilot_lock={dft_diag['pilot_lock']:.3f}, "
                            f"min_pilot={dft_diag['pilot_lock_min']:.3f}, "
                            f"blocks={dft_diag.get('blocks', 0)}/{expected_blocks}, "
                            f"TX_ref_PRBS={pl.get('prbs_n')}, "
                            f"data_bits={int(pl.get('payload_data_bits', 0)):,}/"
                            f"{int(pl.get('prbs_bits_target', 0)):,}. "
                            "Regenerate/download the AWG waveform after PRBS, modulation, "
                            "waveform, or IF changes; reacquire the DSO capture if the "
                            "capture settings changed."
                        )

                else:
                    # --- LFM-QAM Demodulation (shared waveform: single
                    #     continuous chirp carrying the selected modulation) ---
                    # n_chirps==1 here (the whole frame is one "chirp"), so
                    # _frame_sync_and_reshape's generic n_chirps/pts_per_chirp
                    # reshape and its SRO/CFO refine against the fully-known
                    # reference apply unchanged -- this is what gives this
                    # waveform its 100%-duty-cycle sensing processing gain.
                    rx_mat, tx_bb_mat, tx_sym_mat, base_chirp, n_chirps, n_sym, _, pts_per_chirp, frame_start = \
                        self._frame_sync_and_reshape(rx_bb, fs_ref, pl)

                    corr_lfm = np.abs(fftconvolve(rx_bb, np.conj(tx_bb_mat[0][::-1]), mode="valid"))
                    self.parent.after(0, lambda c=corr_lfm: self._plot_correlation_for_debug(c))

                    dechirped_lfm = (rx_mat[0] * np.conj(base_chirp)).reshape(-1)
                    shared_preamble_len = int(pl.get(
                        "qam_preamble_len",
                        pl.get("psk_preamble_len", 0),
                    ))
                    shared_preamble_ref = np.asarray(
                        pl.get("qam_preamble_symbols", pl.get("psk_preamble_symbols", [])),
                        dtype=np.complex128,
                    ).reshape(-1)
                    qam_est, lfm_diag = self._recover_lfm_qam_symbols_integrate_and_dump(
                        dechirped_lfm,
                        n_per_sym=nps,
                        n_symbols=n_sym,
                        preamble_len=shared_preamble_len,
                        preamble_ref=shared_preamble_ref,
                    )
                    qam_ref = tx_sym_mat[0][:len(qam_est)]
                    lfm_preamble_lock = float(lfm_diag.get("preamble_lock_score", 0.0))
                    lfm_payload_lock = 0.0
                    if len(qam_ref) == len(qam_est) and len(qam_ref) > max(16, shared_preamble_len + 8):
                        lfm_data_mask = np.ones(len(qam_ref), dtype=bool)
                        lfm_data_mask[:max(0, shared_preamble_len)] = False
                        lfm_widely_linear = str(mod).strip().upper() not in {"BPSK", "QPSK", "8PSK"}
                        lfm_payload_lock, _ = self._reference_lock_score(
                            qam_est,
                            qam_ref,
                            train_mask=lfm_data_mask,
                            track_phase=False,
                            widely_linear=lfm_widely_linear,
                        )
                    self._log(
                        f"[Demod] LFM-QAM recover: N={len(qam_est)}  "
                        f"preamble_lock={lfm_preamble_lock:.3f}  "
                        f"payload_lock={lfm_payload_lock:.3f}  "
                        f"residual_cfo={lfm_diag['residual_cfo_rad_per_symbol']:.4f} rad/sym  "
                        f"residual_phase={lfm_diag['residual_phase_rad']:.3f} rad"
                    )
                    if lfm_preamble_lock < 0.25 or lfm_payload_lock < 0.12:
                        raise ValueError(
                            "No reliable LFM-QAM/PRBS lock. "
                            f"preamble_lock={lfm_preamble_lock:.3f}, "
                            f"payload_lock={lfm_payload_lock:.3f}, "
                            f"TX_ref_PRBS={pl.get('prbs_n')}, "
                            f"data_bits={int(pl.get('payload_data_bits', 0)):,}. "
                            "Regenerate/download the AWG waveform after PRBS/modulation changes, then acquire again."
                        )

                # --- Common Post-processing for all waveform types ---
                # Step 1: coarse symbol alignment first; phase correction needs correct pairs.
                if waveform_type == "QAM":
                    qam_ref_al = np.asarray(qam_ref, dtype=np.complex128)
                    qam_est_al = np.asarray(qam_est, dtype=np.complex128)
                else:
                    qam_ref_al, qam_est_al = _align_symbols_for_ber(
                        qam_ref, qam_est, max_lag=max(16, nps * 4))
                self._log(f"[Demod] coarse align: ref={len(qam_ref_al)} est={len(qam_est_al)}")

                if len(qam_ref_al) < 8 or len(qam_est_al) < 8:
                    raise ValueError("Too few aligned symbols for EVM/BER measurement.")

                metric_lag = max(4, sc_fde_taps if waveform_type == "QAM" else nps)
                qam_ref_fin, qam_est_fin, eq_mode, evm_rms = self._equalize_reference_candidates(
                    qam_est_al,
                    qam_ref_al,
                    modulation=mod,
                    sc_fde_taps=sc_fde_taps,
                    sc_fde_enable=(sc_fde_enable and not blind_metric_mode),
                    max_lag=metric_lag,
                )
                if len(qam_ref_fin) < 8 or len(qam_est_fin) < 8:
                    raise ValueError("Equalizer produced too few symbols for EVM/BER measurement.")
                self._log(f"[Demod] selected EQ path: {eq_mode}")

                evm_db  = 20.0 * np.log10(evm_rms + 1e-15)
                evm_pct = 100.0 * evm_rms

                br = _hard_bits_from_symbols(qam_ref_fin, mod)
                be = _hard_bits_from_symbols(qam_est_fin, mod)
                ber = (
                    float(np.mean(br != be))
                    if ber_reference_valid and len(br) == len(be) > 0
                    else float("nan")
                )
                n_sym_out = len(qam_ref_fin)

                self._log(f"[Demod] {waveform_type}/{mod}  frame_start={frame_start:,} "
                          f"N={n_sym_out}  EVM={evm_db:.2f} dB ({evm_pct:.1f}%)  BER~{ber:.2e}")
                self.parent.after(0, lambda: self._show_demod_result(
                    qam_est_fin, evm_db, evm_pct, ber, n_sym_out, mod))
            except Exception as e:
                self._log(f"[Demod] Error: {e}")
                if show_errors:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("Demodulate Error", m))
        # Best-EVM/Post-EQ-sweep loops already run inside their own background
        # worker thread and call this repeatedly in a tight loop -- spawning
        # yet another thread per call meant the caller had no direct signal
        # of completion and had to poll _wait_for_metric for up to 30s on
        # every failed (no-lock) run, which is what made those loops feel
        # like they hung. run_async=False runs `worker` inline so the call
        # blocks until this attempt is actually done, success or failure.
        if run_async:
            threading.Thread(target=worker, daemon=True).start()
        else:
            worker()

    def _show_demod_result(self, syms_eq: np.ndarray,
                           evm_db: float, evm_pct: float, ber: float, n_sym: int,
                           modulation: str | None = None) -> None:
        self.evm_var.set(f"EVM:         {evm_db:.2f} dB  ({evm_pct:.1f} %)")
        self.ber_var.set(
            f"BER:         {ber:.2e}" if np.isfinite(ber)
            else "BER:         ---"
        )
        self.sym_count_var.set(f"Symbols:     {n_sym:,}")
        self._set_metric("evm_db", "EVM", evm_db, "dB")
        evm_snr = -evm_db if np.isfinite(evm_db) else float("nan")
        self._set_metric("evm_snr", "EVM-implied SNR", evm_snr, "dB")
        self._set_metric("sinr_com_db", "SINR_com", evm_snr, "dB", "Using EVM-implied SNR for demodulation quality.")
        self._set_metric("evm_pct", "EVM", evm_pct, "%")
        self._set_metric("ber", "BER", ber if np.isfinite(ber) else float("nan"), "")
        self._set_metric("symbols", "Symbols", int(n_sym), "")
        self._refresh_metrics_table()

        self._const_drawn = True
        self.ax_const.cla()
        n_show = min(len(syms_eq), 3000)
        self.ax_const.scatter(np.real(syms_eq[:n_show]), np.imag(syms_eq[:n_show]),
                              s=6, alpha=0.5, color="#2563eb", label="RX")
        # Build constellation alphabet from modulation type (deterministic, exact grid)
        plot_mod = modulation or self.demod_mod_var.get()
        _bps = _bits_per_symbol(plot_mod)
        _n_pts = 1 << _bps
        _all_bits = np.array(
            [[int(b) for b in format(i, f'0{_bps}b')] for i in range(_n_pts)],
            dtype=np.uint8,
        )
        ideal_pts = _bits_to_qam_symbols(_all_bits.reshape(-1), plot_mod)
        self.ax_const.scatter(np.real(ideal_pts), np.imag(ideal_pts),
                              s=60, marker="x", color="red", linewidths=1.5, label="Ref.")
        ber_text = f"BER $\\approx$ {ber:.2e}" if np.isfinite(ber) else "BER = N/A"
        self.ax_const.set_title("Constellation")
        self.ax_const.text(
            0.03, 0.03, f"EVM = {evm_db:.2f} dB\n{ber_text}",
            transform=self.ax_const.transAxes, ha="left", va="bottom", fontsize=8,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="#94a3b8"),
        )
        self.ax_const.set_xlabel("In-Phase")
        self.ax_const.set_ylabel("Quadrature")
        self.ax_const.set_xlim(-1.5, 1.5)
        self.ax_const.set_ylim(-1.5, 1.5)
        self.ax_const.set_aspect("equal", adjustable="box")
        self.ax_const.grid(True, alpha=0.35)
        self.ax_const.legend(fontsize=7, loc="upper right")
        self._apply_dashboard_layout()
        self.canvas_plot.draw_idle()

class SystemModelValidationPanel:
    """Paper-model SNR/range validation tab."""

    def __init__(self, parent: ttk.Frame, runtime: dict | None = None, tx_source=None, photonic_source=None):
        self.parent = parent
        self.runtime = runtime if runtime is not None else {}
        self.tx_source = tx_source
        self.photonic_source = photonic_source
        self.params: dict[str, tk.StringVar] = {}
        self.meas_points: list[dict[str, float | str]] = []
        self.status_var = tk.StringVar(value="Ready")
        self._build_ui()
        self.status_var.set("Ready. Press Run to sweep distance.")

    def _build_ui(self) -> None:
        outer = ttk.PanedWindow(self.parent, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=1)
        outer.add(right, weight=5)

        ctrl = ttk.LabelFrame(left, text="Paper Model Parameters", padding=8)
        ctrl.pack(fill=tk.BOTH, expand=True)

        def add(row: int, key: str, label: str, value: str) -> None:
            ttk.Label(ctrl, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=value)
            self.params[key] = var
            ttk.Entry(ctrl, textvariable=var, width=12).grid(row=row, column=1, sticky="w", pady=2)

        add(0, "r_min_m", "Distance min [m]", "0.25")
        add(1, "r_max_m", "Distance max [m]", "2")
        add(2, "n_range", "Sweep points", "9")
        add(3, "rho", "rho pilot power", "0.20")
        add(4, "cspr_db", "CSPR [dB]", "20")
        add(5, "iso_db", "OMT ISO [dB]", "25")
        add(6, "ac2", "A_c^2 [mW]", "1.0")
        add(7, "sqrt_k", "sqrt(K) [amp*m^2]", "1e-4")
        add(8, "bandwidth_ghz", "B signal [GHz]", "2.0")
        add(9, "pilot_time_ns", "T_p pilot [ns]", "102.4")
        add(10, "gc_db", "G_c [dB]", "0")
        add(11, "noise_density_dbmhz", "Spectrum noise density [dBm/Hz]", "-130")
        add(12, "modulation_order", "Comm M-QAM", "32")
        add(13, "ber_target", "BER target", "1e-3")
        add(14, "pfa", "Sensing Pfa", "1e-6")
        add(15, "pd", "Sensing Pd", "0.90")
        add(16, "rho_points", "rho sweep points", "101")
        add(17, "mc_trials", "MC trials", "2000")
        add(18, "m_min", "m sweep min", "0.02")
        add(19, "m_max", "m sweep max", "1.0")
        add(20, "m_points", "m sweep points", "300")
        add(21, "phi_bias_deg", "MZM phi_b [deg]", "45")
        add(22, "gamma1_dbm", "gamma1 [dBm]", "0")
        add(23, "gamma2_dbm", "gamma2 [dBm]", "-20")
        add(24, "gamma3_dbm", "gamma3 [dBm]", "-30")
        add(25, "papr_db", "Waveform PAPR [dB]", "8")
        add(26, "backoff_db", "Power backoff [dB]", "3")
        add(27, "m_peak_limit", "m peak limit", "1.0")

        btns = ttk.Frame(ctrl)
        btns.grid(row=28, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Run", style="Primary.TButton", command=self._run).pack(side=tk.LEFT)
        ttk.Button(btns, text="Sync Sim", command=self._sync_from_sim).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Load Save Data", command=self._load_measurement).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Clear Meas.", command=self._clear_measurements).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(ctrl, textvariable=self.status_var, style="Muted.TLabel", wraplength=260).grid(
            row=29, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ctrl.columnconfigure(1, weight=1)

        self.fig = Figure(figsize=(10, 7), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.axes = self.fig.subplots(2, 2)
        self.fig.tight_layout()

    def _float(self, key: str, default: float) -> float:
        try:
            return float(self.params[key].get())
        except Exception:
            return float(default)

    def _int(self, key: str, default: int) -> int:
        try:
            return int(float(self.params[key].get()))
        except Exception:
            return int(default)

    def _processing_gain_lin(self) -> float:
        bandwidth_hz = max(self._float("bandwidth_ghz", 2.0) * 1e9, 1.0)
        pilot_time_s = max(self._float("pilot_time_ns", 1024.0) * 1e-9, 1e-15)
        return max(bandwidth_hz * pilot_time_s, 1.0)

    def _noise_power_mw(self) -> float:
        density_dbmhz = self._float("noise_density_dbmhz", -130.0)
        bandwidth_hz = max(self._float("bandwidth_ghz", 2.0) * 1e9, 1.0)
        return max((10.0 ** (density_dbmhz / 10.0)) * bandwidth_hz, 1e-30)

    def _qam_moment_factors(self) -> tuple[float, float]:
        try:
            m_order = max(2, int(round(self._float("modulation_order", 32.0))))
            if m_order <= 4:
                mod = "QPSK"
            else:
                mod = f"{m_order}QAM"
            bps = max(1, int(np.ceil(np.log2(m_order))))
            bits = np.array(
                [[int(b) for b in format(i, f"0{bps}b")] for i in range(1 << bps)],
                dtype=np.uint8,
            )
            syms = np.asarray(_bits_to_qam_symbols(bits.reshape(-1), mod), dtype=np.complex128).reshape(-1)
            if len(syms) == 0:
                return 1.0, 1.0
            p2 = max(float(np.mean(np.abs(syms) ** 2)), 1e-30)
            mu4 = float(np.mean(np.abs(syms) ** 4) / (p2 ** 2))
            mu6 = float(np.mean(np.abs(syms) ** 6) / (p2 ** 3))
            return max(mu4, 1.0), max(mu6, 1.0)
        except Exception:
            return 1.0, 1.0

    def _sdinr_model(self) -> dict[str, np.ndarray | float]:
        m_min = max(self._float("m_min", 0.02), 1e-5)
        m_max = max(self._float("m_max", 1.0), m_min * 1.01)
        n_pts = max(32, min(self._int("m_points", 300), 5000))
        m_axis = np.geomspace(m_min, m_max, n_pts)
        phi_b = np.deg2rad(float(np.clip(self._float("phi_bias_deg", 45.0), 1e-3, 89.999)))
        cot_phi = 1.0 / max(np.tan(phi_b), 1e-12)
        gamma1_mw = max(10.0 ** (self._float("gamma1_dbm", 0.0) / 10.0), 1e-30)
        gamma2_mw = max(10.0 ** (self._float("gamma2_dbm", -20.0) / 10.0), 0.0)
        gamma3_mw = max(10.0 ** (self._float("gamma3_dbm", -30.0) / 10.0), 0.0)
        noise_mw = self._noise_power_mw()
        mu4, mu6 = self._qam_moment_factors()
        papr_lin = max(10.0 ** (self._float("papr_db", 8.0) / 10.0), 1.0)
        backoff_lin = max(10.0 ** (self._float("backoff_db", 3.0) / 10.0), 1.0)
        m_peak_limit = max(self._float("m_peak_limit", 1.0), 1e-6)
        m_allowed = m_peak_limit / np.sqrt(papr_lin * backoff_lin)

        sig_mw = gamma1_mw * (m_axis ** 2)
        ssbi_mw = gamma2_mw * mu4 * (m_axis ** 4)
        imd3_mw = gamma3_mw * mu6 * (m_axis ** 6) * (cot_phi ** 4)
        den_mw = np.maximum(noise_mw + ssbi_mw + imd3_mw, 1e-30)
        sdinr = sig_mw / den_mw
        feasible = m_axis <= m_allowed
        if np.any(feasible & np.isfinite(sdinr)):
            feasible_idx = np.flatnonzero(feasible)
            opt_idx = int(feasible_idx[int(np.nanargmax(sdinr[feasible]))])
        else:
            opt_idx = int(np.nanargmax(sdinr)) if np.any(np.isfinite(sdinr)) else 0

        cspr_axis = 1.0 / np.maximum(m_axis ** 2, 1e-30)
        cspr_now = 10.0 ** (self._float("cspr_db", 20.0) / 10.0)
        m_now = 1.0 / np.sqrt(max(cspr_now, 1e-30))
        return {
            "m": m_axis,
            "cspr_db": 10.0 * np.log10(cspr_axis),
            "sdinr": sdinr,
            "sdinr_db": self._db(sdinr),
            "signal_mw": sig_mw,
            "noise_mw": noise_mw,
            "ssbi_mw": ssbi_mw,
            "imd3_mw": imd3_mw,
            "feasible": feasible,
            "m_allowed": float(m_allowed),
            "m_opt": float(m_axis[opt_idx]),
            "cspr_opt_db": float(10.0 * np.log10(cspr_axis[opt_idx])),
            "sdinr_opt_db": float(10.0 * np.log10(max(sdinr[opt_idx], 1e-30))),
            "m_now": float(m_now),
            "cspr_now_db": float(self._float("cspr_db", 20.0)),
            "cot_phi": float(cot_phi),
            "mu4": float(mu4),
            "mu6": float(mu6),
            "papr_db": float(10.0 * np.log10(papr_lin)),
            "backoff_db": float(10.0 * np.log10(backoff_lin)),
        }

    def _comm_threshold_db(self) -> float:
        try:
            m = max(2, int(round(self._float("modulation_order", 32.0))))
            ber = float(np.clip(self._float("ber_target", 1e-3), 1e-12, 0.2))
            k = max(np.log2(m), 1.0)
            sqrt_m = np.sqrt(float(m))
            coeff = 4.0 / k * (1.0 - 1.0 / sqrt_m)
            q_arg = float(np.clip(ber / max(coeff, 1e-15), 1e-15, 0.499999))
            q_inv = np.sqrt(2.0) * float(erfcinv(2.0 * q_arg))
            # EVM-implied SNR is Es/N0. The common BER approximation is often
            # written with Eb/N0 via sqrt(3*k/(M-1)*Eb/N0); converting to
            # Es/N0 removes the /k term.
            gamma = (q_inv ** 2) * (m - 1.0) / 3.0
            return float(10.0 * np.log10(max(gamma, 1e-30)))
        except Exception:
            return 18.0

    def _sens_threshold_db(self) -> float:
        pfa = float(np.clip(self._float("pfa", 1e-6), 1e-15, 0.5))
        pd = float(np.clip(self._float("pd", 0.90), 1e-6, 1.0 - 1e-9))
        eta = -np.log(pfa)
        lo, hi = 0.0, 1.0
        # Noncoherent complex detector: 2|y|^2 is noncentral chi-square
        # with df=2 and noncentrality 2*SNR.
        while ncx2.sf(2.0 * eta, 2, 2.0 * hi) < pd and hi < 1e9:
            hi *= 2.0
        for _ in range(70):
            mid = 0.5 * (lo + hi)
            if ncx2.sf(2.0 * eta, 2, 2.0 * mid) >= pd:
                hi = mid
            else:
                lo = mid
        gamma = hi
        return float(10.0 * np.log10(max(gamma, 1e-30)))

    def _sync_from_sim(self) -> None:
        try:
            cfg = None
            if self.photonic_source is not None and hasattr(self.photonic_source, "_cfg_from_ui"):
                cfg = self.photonic_source._cfg_from_ui()
                waveform_kind = classify_isac_waveform(cfg.waveform)
                bw_hz = estimate_waveform_bandwidth_hz(cfg, waveform_kind)
                if bw_hz > 0:
                    self.params["bandwidth_ghz"].set(f"{bw_hz / 1e9:.6g}")
                pilot_time_s = max(float(cfg.syms_per_chirp), 1.0) / max(float(cfg.baud_gbaud) * 1e9, 1.0)
                self.params["pilot_time_ns"].set(f"{pilot_time_s * 1e9:.6g}")
                self.params["rho"].set(f"{float(cfg.pilot_rho):.6g}")
                self.params["cspr_db"].set(f"{float(cfg.cspr_db):.6g}")
                self.params["iso_db"].set(f"{float(cfg.omt_iso_db):.6g}")
                rf_lines = calc_utcpd_rf_line_powers(cfg)
                self.params["ac2"].set(f"{float(rf_lines.get('carrier_w', 1e-6)) * 1e3:.6g}")
                ref_r = max(float(cfg.target_dist_m), 1e-6)
                link = calc_isac_link_budget(
                    distance_m=ref_r,
                    rf_ghz=cfg.rf_carrier_ghz,
                    tx_dbm=cfg.utcpd_target_dbm,
                    tx_gain_dbi=cfg.tx_ant_gain_dbi,
                    rx_gain_dbi=cfg.rx_ant_gain_dbi,
                    rcs_sqm=cfg.target_rcs_sqm,
                    lna_gain_db=cfg.lna_gain_db,
                    c1_drive_gain_db=cfg.c1_drive_gain_db,
                    c2_drive_gain_db=cfg.c2_drive_gain_db,
                    c1_cable_loss_db=cfg.c1_cable_loss_db,
                    c2_cable_loss_db=cfg.c2_cable_loss_db,
                    omt_il_db=cfg.omt_il_db,
                    target_ant_gain_dbi=cfg.target_ant_gain_dbi,
                    target_gamma_mag=cfg.target_gamma_mag,
                    target_pol_eff=cfg.target_pol_eff,
                )
                beta_ref = 10.0 ** (-float(link["radar_path_loss_db"]) / 20.0)
                self.params["sqrt_k"].set(f"{beta_ref * ref_r ** 2:.6g}")
                ac2_mw = max(float(rf_lines.get("carrier_w", 1e-6)) * 1e3, 1e-30)
                c1_total_mw = dbm_to_w(float(link["c1_rf_dbm"])) * 1e3
                gc = max(c1_total_mw * ref_r ** 2 / ac2_mw, 1e-30)
                self.params["gc_db"].set(f"{10.0 * np.log10(gc):.6g}")
                if getattr(self.photonic_source, "data", None):
                    c1m = self.photonic_source.data.get("c1_band_metrics", {})
                    nf = float(c1m.get("noise_density_dbm_hz", c1m.get("noise_floor_dbm_hz", float("nan"))))
                    if np.isfinite(nf):
                        self.params["noise_density_dbmhz"].set(f"{nf:.6g}")
            pl = self.runtime.get("tx_payload")
            if isinstance(pl, dict) and pl:
                bw = float(pl.get("B", pl.get("symbol_rate", pl.get("symbol_rate_actual", 2e9))))
                if np.isfinite(bw) and bw > 0:
                    self.params["bandwidth_ghz"].set(f"{bw / 1e9:.6g}")
                n_chirps = int(pl.get("n_chirps", 1))
                n_sym = int(pl.get("n_sym_per_chirp", 1024))
                sym_rate = float(pl.get("symbol_rate_actual", pl.get("symbol_rate", 1e9)))
                if sym_rate > 0:
                    self.params["pilot_time_ns"].set(f"{(n_chirps * n_sym / sym_rate) * 1e9:.6g}")
                rho = float(pl.get("amplitude_ratio_rho", float("nan")))
                if np.isfinite(rho):
                    self.params["rho"].set(f"{rho:.6g}")
                if "awg_sig" in pl:
                    papr = DsoPanel._papr_db(np.asarray(pl["awg_sig"]))
                    if np.isfinite(papr):
                        self.params["papr_db"].set(f"{papr:.6g}")
                mod = str(pl.get("modulation", "")).upper()
                if "32" in mod:
                    self.params["modulation_order"].set("32")
                elif "16" in mod:
                    self.params["modulation_order"].set("16")
                elif "64" in mod:
                    self.params["modulation_order"].set("64")
            # N_c and N_sensing are not independent knobs here: both are the
            # integrated ZBD/DSO output noise density over B.
            self._run()
        except Exception as exc:
            messagebox.showerror("Sync Sim", str(exc), parent=self.parent)

    def _model(self, ranges_m: np.ndarray, rho: float | None = None) -> dict[str, np.ndarray | float]:
        rho_v = float(np.clip(self._float("rho", 0.2) if rho is None else rho, 1e-9, 1.0 - 1e-9))
        cspr = 10.0 ** (self._float("cspr_db", 20.0) / 10.0)
        alpha = 10.0 ** (-self._float("iso_db", 25.0) / 20.0)
        ac2 = max(self._float("ac2", 1.0), 1e-30)
        sqrt_k = max(self._float("sqrt_k", 1e-4), 1e-30)
        gp = self._processing_gain_lin()
        gc = 10.0 ** (self._float("gc_db", 0.0) / 10.0)
        n_sens = self._noise_power_mw()
        n_comm = self._noise_power_mw()
        r = np.maximum(np.asarray(ranges_m, dtype=np.float64), 1e-12)
        snr_comm = ((1.0 - rho_v) * ac2 * gc) / (cspr * (r ** 2) * n_comm)
        snr_sens = (2.0 * rho_v * alpha * ac2 * sqrt_k * gp) / (n_sens * (r ** 2))
        return {
            "rho": rho_v,
            "snr_comm": snr_comm,
            "snr_sens": snr_sens,
            "alpha": alpha,
            "cspr": cspr,
            "gp": gp,
            "n_mw": n_comm,
        }

    @staticmethod
    def _db(x: np.ndarray | float) -> np.ndarray | float:
        return 10.0 * np.log10(np.maximum(x, 1e-30))

    def _rmax(self, rho: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rho = np.clip(np.asarray(rho, dtype=np.float64), 1e-12, 1.0 - 1e-12)
        cspr = 10.0 ** (self._float("cspr_db", 20.0) / 10.0)
        alpha = 10.0 ** (-self._float("iso_db", 25.0) / 20.0)
        ac2 = max(self._float("ac2", 1.0), 1e-30)
        sqrt_k = max(self._float("sqrt_k", 1e-4), 1e-30)
        gp = self._processing_gain_lin()
        gc = 10.0 ** (self._float("gc_db", 0.0) / 10.0)
        n_sens = self._noise_power_mw()
        n_comm = self._noise_power_mw()
        g_sens = 10.0 ** (self._sens_threshold_db() / 10.0)
        g_comm = 10.0 ** (self._comm_threshold_db() / 10.0)
        r_comm = np.sqrt(((1.0 - rho) * ac2 * gc) / (cspr * n_comm * g_comm))
        r_sens = np.sqrt((2.0 * rho * alpha * ac2 * sqrt_k * gp) / (n_sens * g_sens))
        return r_comm, r_sens, np.minimum(r_comm, r_sens)

    def _monte_carlo_snr_db(self, snr_lin: np.ndarray) -> np.ndarray:
        trials = max(32, min(self._int("mc_trials", 2000), 200000))
        snr = np.asarray(snr_lin, dtype=np.float64)
        out = np.zeros_like(snr)
        rng = np.random.default_rng(12345)
        for idx, val in np.ndenumerate(snr):
            noise = (rng.normal(size=trials) + 1j * rng.normal(size=trials)) / np.sqrt(2.0)
            sig = np.sqrt(max(float(val), 0.0))
            y = sig + noise
            est_sig = np.abs(np.mean(y)) ** 2
            est_noise = max(float(np.mean(np.abs(y - np.mean(y)) ** 2)), 1e-30)
            out[idx] = 10.0 * np.log10(max(est_sig / est_noise, 1e-30))
        return out

    def _run(self) -> None:
        try:
            r_min = max(self._float("r_min_m", 0.2), 1e-6)
            r_max = max(self._float("r_max_m", 20.0), r_min * 1.01)
            n_range = max(16, min(self._int("n_range", 240), 5000))
            ranges = np.geomspace(r_min, r_max, n_range)
            model = self._model(ranges)
            rho = float(model["rho"])
            snr_comm = np.asarray(model["snr_comm"], dtype=np.float64)
            snr_sens = np.asarray(model["snr_sens"], dtype=np.float64)
            comm_thr_db = self._comm_threshold_db()
            sens_thr_db = self._sens_threshold_db()
            gp_db = 10.0 * np.log10(max(float(model.get("gp", 1.0)), 1e-30))
            n_dbm = 10.0 * np.log10(max(float(model.get("n_mw", 1e-30)), 1e-30))
            nf_dbmhz = self._float("noise_density_dbmhz", -130.0)

            sdinr_model = self._sdinr_model()

            ax_snr, ax_sdinr, ax_rho, ax_meas = self.axes.reshape(-1)
            for ax in self.axes.reshape(-1):
                ax.cla()
                ax.grid(True, alpha=0.35)

            ax_snr.semilogx(ranges, self._db(snr_comm), label="SNR_comm calc", color="#2563eb")
            ax_snr.semilogx(ranges, self._db(snr_sens), label="SNR_sens calc", color="#dc2626")
            ax_snr.axhline(comm_thr_db, color="#2563eb", linestyle=":", linewidth=0.9, label=f"BER threshold {comm_thr_db:.1f} dB")
            ax_snr.axhline(sens_thr_db, color="#dc2626", linestyle=":", linewidth=0.9, label=f"Pfa thr {sens_thr_db:.1f} dB")
            ax_snr.set_title("SNR vs Range")
            ax_snr.set_xlabel("Range [m]")
            ax_snr.set_ylabel("SNR [dB]")
            ax_snr.legend(fontsize=8)

            sample_idx = np.unique(np.linspace(0, len(ranges) - 1, min(28, len(ranges))).astype(int))
            mc_comm_db = self._monte_carlo_snr_db(snr_comm[sample_idx])
            mc_sens_db = self._monte_carlo_snr_db(snr_sens[sample_idx])
            ax_snr.scatter(ranges[sample_idx], mc_comm_db, s=14, marker="o", color="#60a5fa", label="comm MC")
            ax_snr.scatter(ranges[sample_idx], mc_sens_db, s=14, marker="x", color="#f87171", label="sens MC")

            m_axis = np.asarray(sdinr_model["m"], dtype=np.float64)
            sdinr_db = np.asarray(sdinr_model["sdinr_db"], dtype=np.float64)
            m_opt = float(sdinr_model["m_opt"])
            m_now = float(sdinr_model["m_now"])
            m_allowed = float(sdinr_model["m_allowed"])
            cspr_opt_db = float(sdinr_model["cspr_opt_db"])
            cspr_now_db = float(sdinr_model["cspr_now_db"])
            sdinr_opt_db = float(sdinr_model["sdinr_opt_db"])
            papr_db = float(sdinr_model["papr_db"])
            backoff_db = float(sdinr_model["backoff_db"])
            ax_sdinr.semilogx(m_axis, sdinr_db, color="#7c3aed", linewidth=1.4, label="SDINR")
            ax_sdinr.axvline(m_opt, color="#111827", linestyle="--", linewidth=1.0, label=f"m_opt={m_opt:.3g}")
            if m_axis[0] < m_allowed < m_axis[-1]:
                ax_sdinr.axvline(m_allowed, color="#dc2626", linestyle="-.", linewidth=1.0, label="PAPR/OBO limit")
                ax_sdinr.axvspan(m_allowed, m_axis[-1], color="#dc2626", alpha=0.08)
            if m_axis[0] <= m_now <= m_axis[-1]:
                ax_sdinr.axvline(m_now, color="#f59e0b", linestyle=":", linewidth=1.2, label=f"current CSPR={cspr_now_db:.1f} dB")
            ax_sdinr.set_title("SDINR vs Modulation Index")
            ax_sdinr.set_xlabel("m  (CSPR = 1/m^2)")
            ax_sdinr.set_ylabel("SDINR [dB]")
            ax_sdinr.legend(fontsize=8)
            ax_sdinr.text(
                0.03, 0.04,
                f"opt CSPR={cspr_opt_db:.2f} dB\n"
                f"opt SDINR={sdinr_opt_db:.2f} dB\n"
                f"PAPR/OBO={papr_db:.1f}/{backoff_db:.1f} dB",
                transform=ax_sdinr.transAxes,
                ha="left",
                va="bottom",
                fontsize=8,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.82, edgecolor="#cbd5e1"),
            )

            n_rho = max(16, min(self._int("rho_points", 101), 2000))
            rho_axis = np.linspace(1e-3, 0.999, n_rho)
            r_comm, r_sens, r_joint = self._rmax(rho_axis)
            ax_rho.plot(rho_axis, r_comm, color="#2563eb", label=r"$R_{\max}^{\mathrm{comm}}$")
            ax_rho.plot(rho_axis, r_sens, color="#dc2626", label=r"$R_{\max}^{\mathrm{sens}}$")
            ax_rho.plot(rho_axis, r_joint, color="#111827", linewidth=1.4, label=r"$R_{\max}$ (ISAC)")
            ax_rho.axvline(rho, color="#64748b", linestyle=":", linewidth=0.9)
            ax_rho.set_title("ISAC Range")
            ax_rho.set_xlabel("rho pilot power ratio")
            ax_rho.set_ylabel("ISAC Range [m]")
            ax_rho.legend(fontsize=8)

            ax_meas.semilogx(ranges, self._db(snr_comm), color="#2563eb", alpha=0.35, label="comm calc")
            ax_meas.semilogx(ranges, self._db(snr_sens), color="#dc2626", alpha=0.35, label="sens calc")
            for p in self.meas_points:
                rr = float(p.get("range_m", float("nan")))
                sc = float(p.get("snr_comm_db", float("nan")))
                ss = float(p.get("snr_sens_db", float("nan")))
                name = str(p.get("name", "meas"))
                if np.isfinite(rr) and np.isfinite(sc):
                    ax_meas.scatter([rr], [sc], color="#1d4ed8", marker="o", s=36)
                    ax_meas.annotate(name, (rr, sc), fontsize=7, xytext=(4, 4), textcoords="offset points")
                if np.isfinite(rr) and np.isfinite(ss):
                    ax_meas.scatter([rr], [ss], color="#b91c1c", marker="D", s=34)
            ax_meas.set_title("Loaded Save Data Overlay")
            ax_meas.set_xlabel("Distance [m]")
            ax_meas.set_ylabel("SNR [dB]")
            ax_meas.legend(fontsize=8)

            self.fig.tight_layout()
            self.canvas.draw_idle()
            rc, rs, rj = self._rmax(np.asarray([rho]))
            self.status_var.set(
                f"rho={rho:.3f}  R_max^comm={rc[0]:.3g} m  "
                f"R_max^sens={rs[0]:.3g} m  R_max(ISAC)={rj[0]:.3g} m  "
                f"Gp=T*B={gp_db:.1f} dB  "
                f"N={n_dbm:.1f} dBm ({nf_dbmhz:.1f} dBm/Hz x B)  "
                f"m_opt={m_opt:.3g} CSPR_opt={cspr_opt_db:.1f} dB  "
                f"m_limit={m_allowed:.3g}  "
                f"thr(comm/sens)={comm_thr_db:.1f}/{sens_thr_db:.1f} dB  "
                f"meas={len(self.meas_points)}"
            )
        except Exception as exc:
            self.status_var.set(f"Error: {exc}")
            messagebox.showerror("System Model Simulation", str(exc), parent=self.parent)

    @staticmethod
    def _as_float(value, default: float = float("nan")) -> float:
        try:
            if isinstance(value, np.ndarray):
                value = value.reshape(-1)[0]
            if hasattr(value, "item"):
                value = value.item()
            return float(value)
        except Exception:
            return default

    def _metric_dict_from_npz(self, loaded) -> dict[str, float]:
        out: dict[str, float] = {}
        if "metric_keys" in loaded.files and "metric_values" in loaded.files:
            keys = np.asarray(loaded["metric_keys"]).reshape(-1)
            vals = np.asarray(loaded["metric_values"]).reshape(-1)
            for i, raw in enumerate(keys):
                key = str(raw.item() if hasattr(raw, "item") else raw)
                if i < len(vals):
                    out[key] = self._as_float(vals[i])
        return out

    def _range_summary_float_for_channel(self, loaded, key: str, channel: str = "C2") -> float:
        if key not in loaded.files:
            return float("nan")
        arr = np.asarray(loaded[key], dtype=np.float64).reshape(-1)
        if not len(arr):
            return float("nan")
        idx = None
        if "range_summary_channels" in loaded.files:
            try:
                channels = [
                    str(x.item() if hasattr(x, "item") else x).strip().upper()
                    for x in np.asarray(loaded["range_summary_channels"]).reshape(-1)
                ]
                target = channel.strip().upper()
                if target in channels:
                    idx = channels.index(target)
            except Exception:
                idx = None
        if idx is not None and idx < len(arr) and np.isfinite(arr[idx]):
            return float(arr[idx])
        finite = arr[np.isfinite(arr)]
        return float(finite[0]) if len(finite) else float("nan")

    def _load_measurement(self) -> None:
        path_str = filedialog.askopenfilename(
            parent=self.parent,
            title="Load Saved Capture/Range Data",
            initialdir=str(APP_DIR / "data"),
            filetypes=[("NumPy save data", "*.npz"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            path = Path(path_str)
            with np.load(path, allow_pickle=True) as loaded:
                metrics = self._metric_dict_from_npz(loaded)
                range_m = float("nan")
                for key in ("range_summary_peak_m", "range_summary_display_m", "range_summary_matched_filter_peak_m"):
                    range_m = self._range_summary_float_for_channel(loaded, key, "C2")
                    if np.isfinite(range_m):
                        break
                if not np.isfinite(range_m):
                    for key in ("range_peak_m", "si_cfr_peak_m"):
                        if key in metrics and np.isfinite(metrics[key]):
                            range_m = metrics[key]
                            break
                snr_comm = metrics.get("evm_snr", float("nan"))
                if not np.isfinite(snr_comm) and np.isfinite(metrics.get("evm_db", float("nan"))):
                    snr_comm = -float(metrics.get("evm_db"))
                if not np.isfinite(snr_comm):
                    snr_comm = metrics.get("snr_com_db", metrics.get("snr_com_db_c1", float("nan")))
                snr_sens = metrics.get(
                    "snr_rad_post_db_c2",
                    metrics.get(
                        "snr_rad_post_db",
                        metrics.get("snr_rad_db", metrics.get("snr_com_db_c2", float("nan"))),
                    ),
                )
                if not np.isfinite(snr_sens):
                    for key in ("range_summary_pslr_db", "range_summary_diff_cfr_coherence"):
                        if key in loaded.files:
                            arr = np.asarray(loaded[key], dtype=np.float64).reshape(-1)
                            finite = arr[np.isfinite(arr)]
                            if len(finite):
                                snr_sens = float(finite[0])
                                break
                rho = metrics.get("amplitude_ratio_rho", float("nan"))
                if not np.isfinite(rho) and "dsp__pilot_rho" in loaded.files:
                    rho = self._as_float(loaded["dsp__pilot_rho"])
                point = {
                    "name": path.stem[:18],
                    "range_m": range_m,
                    "snr_comm_db": snr_comm,
                    "snr_sens_db": snr_sens,
                    "rho": rho,
                }
                self.meas_points.append(point)
            self._run()
        except Exception as exc:
            messagebox.showerror("Load Save Data", str(exc), parent=self.parent)

    def _clear_measurements(self) -> None:
        self.meas_points.clear()
        self._run()

    # Final paper-figure implementation.  These definitions intentionally
    # override the earlier exploratory SDINR/rho methods above.
    def _build_ui(self) -> None:
        outer = ttk.PanedWindow(self.parent, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=1)
        outer.add(right, weight=5)

        ctrl = ttk.LabelFrame(left, text="ISAC Range Validation", padding=8)
        ctrl.pack(fill=tk.BOTH, expand=True)

        def add(row: int, key: str, label: str, value: str) -> None:
            ttk.Label(ctrl, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=value)
            self.params[key] = var
            entry = ttk.Entry(ctrl, textvariable=var, width=12)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            if key in {
                "plot_x_min_m", "plot_x_max_m",
                "sinr_ylim_min", "sinr_ylim_max",
                "radar_ylim_min", "radar_ylim_max",
                "c2_meas_power_min_dbm",
            }:
                entry.bind("<Return>", lambda _event: self._refresh_plot())
                entry.bind("<FocusOut>", lambda _event: self._refresh_plot())

        def hidden(key: str, value: str) -> None:
            self.params[key] = tk.StringVar(value=value)

        add(0, "r_min_m", "Distance min [m]", "0.25")
        add(1, "r_max_m", "Distance max [m]", "2")
        add(2, "plot_x_min_m", "Plot x min [m]", "0")
        add(3, "plot_x_max_m", "Plot x max [m]", "2")
        add(4, "sweep_points", "Sweep points", "9")
        add(5, "ref_range_m", "Metric ref distance [m]", "1.0")
        add(6, "si_on_iso_db", "SI-on isolation [dB]", "24")
        add(7, "si_off_iso_db", "SI-off isolation [dB]", "1000")
        add(8, "sweep_tx_power_dbm", "Sweep TX power [dBm]", "-10")
        add(9, "rho_ref", "rho at ref", "0.20")
        add(10, "rho", "rho for curve", "0.20")
        add(11, "sim_comm_ref_snr_db", "Comm SNR @ref [dB]", "17.49")
        add(12, "c2_power_ref_dbm", "C2 target @ref [dBm]", "-42.52")
        add(13, "c2_noise_power_dbm", "Fixed C2 noise [dBm]", "-46.47")
        add(14, "radar_proc_gain_db", "Sensing proc. gain [dB]", "16.6")
        add(15, "c2_meas_power_min_dbm", "C2 meas min [dBm]", "")
        add(16, "comm_req_snr_db", "Pre-FEC req. SNR [dB]", "15.75")
        add(17, "sens_req_snr_db", "Sensing req. SINR (Pd/Pfa) [dB]", "13.2")
        add(18, "sinr_ylim_min", "Comm. SINR y min [dB]", "0")
        add(19, "sinr_ylim_max", "Comm. SINR y max [dB]", "50")
        add(20, "radar_ylim_min", "Sensing SINR y min [dB]", "-10")
        add(21, "radar_ylim_max", "Sensing SINR y max [dB]", "40")
        add(22, "manual_evm_points", "Manual EVM [mm:dB]", "1000:-17.49, 1100:-16.21, 1200:-15.1")
        add(23, "manual_c2_si_on_points", "Manual C2 SI-on [mm:dBm]", "1000:-38.3, 1100:-40.6, 1200:-42.4")
        add(24, "manual_c2_si_off_points", "Manual C2 SI-off [mm:dBm]", "")
        hidden("c2_no_si_power_ref_dbm", "")
        hidden("si_off_power_penalty_db", "")
        hidden("n_range", "9")
        hidden("comm_ref_snr_db", "17.49")
        hidden("sens_ref_snr_db", "21.6")
        hidden("sim_sens_ref_snr_db", "21.6")
        hidden("bandwidth_ghz", "15.0")
        hidden("raw_noise_dbm", "")
        hidden("target_peak_dbm_ref", "")
        hidden("alpha_ref_db", "0")
        hidden("processing_gain_db", "0")
        hidden("rho_points", "201")

        btns = ttk.Frame(ctrl)
        btns.grid(row=25, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Run Sweep", style="Primary.TButton", command=self._run).pack(side=tk.LEFT)
        ttk.Button(btns, text="Redraw", command=self._refresh_plot).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Sync Sim", command=self._sync_from_sim).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Load Params JSON", command=self._load_params_json).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Load Save Data", command=self._load_measurement).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Clear Meas.", command=self._clear_measurements).pack(side=tk.LEFT, padx=(6, 0))

        save_btns = ttk.Frame(ctrl)
        save_btns.grid(row=26, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(save_btns, text="Save SINR PNG", command=self._save_evm_radar_png).pack(side=tk.LEFT)
        ttk.Button(save_btns, text="Save ISAC Range PNG", command=self._save_rho_tradeoff_png).pack(side=tk.LEFT, padx=(6, 0))

        self.save_legend_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ctrl,
            text="Include legend in saved PNG",
            variable=self.save_legend_var,
        ).grid(row=27, column=0, columnspan=2, sticky="w", pady=(5, 0))

        ttk.Label(ctrl, textvariable=self.status_var, style="Muted.TLabel", wraplength=280).grid(
            row=28, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ctrl.columnconfigure(1, weight=1)

        self.fig = Figure(figsize=(10, 7), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.axes = np.asarray(self.fig.subplots(2, 2), dtype=object)
        self.fig.tight_layout()

        self.meas_points = self._default_measurements()
        self.sim_sweep: dict[str, np.ndarray] | None = None
        self._evm_radar_plot_cache: dict[str, object] | None = None

    def _finite_param(self, key: str) -> float:
        try:
            raw = self.params[key].get().strip()
            if raw == "":
                return float("nan")
            val = float(raw)
            return val if np.isfinite(val) else float("nan")
        except Exception:
            return float("nan")

    def _apply_evm_radar_limits(self, ax_sinr, ax_radar, x_min: float, x_max: float) -> None:
        from matplotlib.ticker import MultipleLocator

        ax_sinr.set_xlim(x_min, x_max)
        ax_sinr.xaxis.set_major_locator(MultipleLocator(0.5))
        for ax, lo_key, hi_key in (
            (ax_sinr, "sinr_ylim_min", "sinr_ylim_max"),
            (ax_radar, "radar_ylim_min", "radar_ylim_max"),
        ):
            lo = self._finite_param(lo_key)
            hi = self._finite_param(hi_key)
            cur_lo, cur_hi = ax.get_ylim()
            if np.isfinite(lo) or np.isfinite(hi):
                ax.set_ylim(lo if np.isfinite(lo) else cur_lo, hi if np.isfinite(hi) else cur_hi)

    def _style_ieee_axis(self, ax) -> None:
        ax.tick_params(
            axis="both",
            which="major",
            direction="in",
            top=True,
            right=True,
            labelsize=14,
            width=0.9,
            length=5,
        )
        ax.title.set_fontname("Times New Roman")
        ax.xaxis.label.set_fontname("Times New Roman")
        ax.yaxis.label.set_fontname("Times New Roman")
        ax.xaxis.label.set_size(15)
        ax.yaxis.label.set_size(15)
        ax.title.set_size(15)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontname("Times New Roman")
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(1.0)

    @staticmethod
    def _style_paper_legend(legend, fontsize: float) -> None:
        frame = legend.get_frame()
        frame.set_facecolor("white")
        frame.set_edgecolor("#cbd5e1")
        frame.set_alpha(0.90)
        frame.set_linewidth(0.8)
        for text_item in legend.get_texts():
            text_item.set_fontname("Times New Roman")
            text_item.set_fontsize(fontsize)
        title = legend.get_title()
        if title.get_text():
            title.set_fontname("Times New Roman")
            title.set_fontsize(fontsize + 0.5)
            title.set_fontweight("normal")
            title.set_color("#111111")

    @staticmethod
    def _threshold_crossing_x(x: np.ndarray, y: np.ndarray, threshold: float) -> float:
        x_arr = np.asarray(x, dtype=np.float64).reshape(-1)
        y_arr = np.asarray(y, dtype=np.float64).reshape(-1)
        valid = np.isfinite(x_arr) & np.isfinite(y_arr)
        if np.count_nonzero(valid) < 2 or not np.isfinite(threshold):
            return float("nan")
        x_arr = x_arr[valid]
        y_arr = y_arr[valid]
        order = np.argsort(x_arr)
        x_arr = x_arr[order]
        y_arr = y_arr[order]
        for idx in range(len(x_arr) - 1):
            y0 = float(y_arr[idx])
            y1 = float(y_arr[idx + 1])
            if y0 >= threshold and y1 <= threshold:
                if y0 == y1:
                    return float(x_arr[idx])
                frac = (threshold - y0) / (y1 - y0)
                return float(x_arr[idx] + frac * (x_arr[idx + 1] - x_arr[idx]))
        return float("nan")

    def _add_sinr_threshold_annotations(
        self,
        ax_sinr,
        ax_radar,
        ranges: np.ndarray,
        comm_sinr: np.ndarray,
        radar_on: np.ndarray,
        comm_threshold_db: float,
        radar_threshold_db: float,
        for_save: bool = False,
    ) -> tuple[float, float]:
        blue = "#0000ff"
        red = "#ff0000"
        black = "#111111"
        text_size = 14
        x_value_offset_m = 0.05  # Adjust this value to move the x-axis numbers left/right.
        ax_sinr.axhline(comm_threshold_db, color=black, linestyle=":", linewidth=1.0, alpha=0.75, zorder=1.5)
        ax_radar.axhline(radar_threshold_db, color=black, linestyle=":", linewidth=1.0, alpha=0.75, zorder=1.5)
        ax_radar.text(
            0.015,
            radar_threshold_db,
            f"{radar_threshold_db:g}",
            transform=ax_radar.get_yaxis_transform(),
            ha="left",
            va="bottom",
            color=red,
            fontsize=text_size,
            fontname="Times New Roman",
        )
        ax_sinr.text(
            0.985,
            comm_threshold_db,
            f"{comm_threshold_db:g}",
            transform=ax_sinr.get_yaxis_transform(),
            ha="right",
            va="bottom",
            color=blue,
            fontsize=text_size,
            fontname="Times New Roman",
        )

        rmax_comm = self._threshold_crossing_x(ranges, comm_sinr, comm_threshold_db)
        rmax_radar = self._threshold_crossing_x(ranges, radar_on, radar_threshold_db)
        x_min, x_max = ax_radar.get_xlim()

        def mark_crossing(ax, xpos: float, threshold: float, color: str) -> None:
            if not np.isfinite(xpos) or not (x_min <= xpos <= x_max):
                return
            y_min, y_max = ax.get_ylim()
            ymax = float(np.clip((threshold - y_min) / max(y_max - y_min, 1e-12), 0.0, 1.0))
            ax.axvline(xpos, ymin=0.0, ymax=ymax, color=black, linestyle="--", linewidth=1.0,
                       alpha=0.85, zorder=1.5)
            x_span = max(x_max - x_min, 1e-12)
            text_x = float(np.clip(xpos + x_value_offset_m, x_min + 0.01 * x_span, x_max - 0.01 * x_span))
            ax.text(
                text_x,
                0.018,
                f"{xpos:.1f}",
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                color=black,
                fontsize=text_size,
                fontname="Times New Roman",
            )

        mark_crossing(ax_radar, rmax_radar, radar_threshold_db, red)
        mark_crossing(ax_sinr, rmax_comm, comm_threshold_db, blue)
        return rmax_comm, rmax_radar

    def _add_grouped_sinr_legends(self, ax_sinr, ax_radar, no_si_valid: bool, linewidth: float, for_save: bool) -> None:
        from matplotlib.lines import Line2D

        if for_save and not bool(self.save_legend_var.get()):
            return

        blue = "#0000ff"
        red = "#ff0000"
        green = "#008000"
        fontsize = 11 if for_save else 10
        radar_handles = [
            Line2D([0], [0], color=red, linestyle="--", linewidth=linewidth, label="Sim. (with SI)"),
        ]
        if no_si_valid:
            radar_handles.append(
                Line2D([0], [0], color=green, linestyle="--", linewidth=linewidth * 0.9, label="Sim. (without SI)")
            )
        radar_handles.append(
            Line2D([0], [0], color=red, marker="s", linestyle="None", markerfacecolor=red,
                   markeredgecolor=red, markersize=6.5, label="Meas.")
        )
        comm_handles = [
            Line2D([0], [0], color=blue, linestyle="--", linewidth=linewidth, label="Sim."),
            Line2D([0], [0], color=blue, marker="o", linestyle="None", markerfacecolor="none",
                   markeredgecolor=blue, markeredgewidth=1.4, markersize=6.5, label="Meas."),
        ]
        radar_legend = ax_radar.legend(
            handles=radar_handles,
            title="Sensing",
            loc="lower left",
            fontsize=fontsize,
            frameon=True,
            fancybox=True,
            handlelength=2.2,
            handletextpad=0.7,
            borderpad=0.45,
            labelspacing=0.35,
        )
        comm_legend = ax_sinr.legend(
            handles=comm_handles,
            title="Comm.",
            loc="upper right",
            fontsize=fontsize,
            frameon=True,
            fancybox=True,
            handlelength=2.2,
            handletextpad=0.7,
            borderpad=0.45,
            labelspacing=0.35,
        )
        self._style_paper_legend(radar_legend, fontsize)
        self._style_paper_legend(comm_legend, fontsize)

    def _draw_evm_radar_figure(self, fig: Figure, cache: dict[str, object], for_save: bool = False):
        ax_radar = fig.add_subplot(111)
        ax_sinr = ax_radar.twinx()
        ranges = np.asarray(cache["ranges"], dtype=np.float64)
        comm_sinr = np.asarray(cache["comm_sinr"], dtype=np.float64)
        radar_on = np.asarray(cache["radar_on"], dtype=np.float64)
        radar_off = np.asarray(cache["radar_off"], dtype=np.float64)
        points = list(cache["points"])
        x_min = float(cache["x_min"])
        x_max = float(cache["x_max"])
        comm_thr = float(cache["comm_thr"])
        radar_thr = float(cache["radar_thr"])
        no_si_valid = bool(cache["no_si_valid"])
        blue = "#0000ff"
        red = "#ff0000"
        green = "#008000"
        joint_color = "#7c3aed"
        lw = 2.2 if for_save else 1.9

        ax_radar.grid(True, which="major", color="#cbd5e1", linewidth=0.55, alpha=0.75)
        ax_sinr.plot(ranges, comm_sinr, color=blue, linestyle="--", linewidth=lw)
        ax_radar.plot(ranges, radar_on, color=red, linestyle="--", linewidth=lw)
        if no_si_valid:
            ax_radar.plot(ranges, radar_off, color=green, linestyle="--", linewidth=lw * 0.9, zorder=3)

        for p in points:
            rr = float(p.get("range_m", float("nan")))
            snr_comm = float(p.get("snr_comm_db", float("nan")))
            if not np.isfinite(snr_comm):
                evm = float(p.get("evm_db", float("nan")))
                snr_comm = -evm if np.isfinite(evm) else float("nan")
            if np.isfinite(rr) and np.isfinite(snr_comm):
                ax_sinr.scatter([rr], [snr_comm], facecolors="none", edgecolors=blue,
                                marker="o", s=62 if for_save else 52, linewidths=1.5, zorder=6)

        for state, color, marker in (("on", red, "s"), ("off", green, "^")):
            pts = cache.get(f"{state}_radar_points", [])
            if pts:
                rr = np.asarray([p[0] for p in pts], dtype=np.float64)
                yy = np.asarray([p[1] for p in pts], dtype=np.float64)
                ax_radar.scatter(rr, yy, facecolors=color if state == "on" else "none", edgecolors=color,
                                 marker=marker, s=62 if for_save else 52, linewidths=1.5, zorder=6)

        ax_radar.set_xlabel("Distance [m]")
        ax_sinr.set_ylabel("Comm. SINR [dB]", color=blue)
        ax_radar.set_ylabel("Sensing SINR [dB]", color=red)
        ax_sinr.tick_params(axis="y", colors=blue)
        ax_radar.tick_params(axis="y", colors=red)
        for ax in (ax_radar, ax_sinr):
            ax.spines["left"].set_color(red)
            ax.spines["right"].set_color(blue)

        vals = comm_sinr[np.isfinite(comm_sinr)]
        meas_vals = np.asarray([
            float(p.get("snr_comm_db", float("nan")))
            if np.isfinite(float(p.get("snr_comm_db", float("nan"))))
            else -float(p.get("evm_db", float("nan")))
            for p in points
            if np.isfinite(float(p.get("snr_comm_db", float("nan")))) or np.isfinite(float(p.get("evm_db", float("nan"))))
        ], dtype=np.float64)
        vals = np.concatenate([vals, meas_vals[np.isfinite(meas_vals)]])
        if len(vals):
            ax_sinr.set_ylim(float(np.nanmin(vals)) - 2.0, float(np.nanmax(vals)) + 2.0)
        rvals = np.concatenate([radar_on.reshape(-1), radar_off.reshape(-1)])
        rpt = [
            y
            for state in ("on", "off")
            for _, y in cache.get(f"{state}_radar_points", [])
        ]
        if rpt:
            rvals = np.concatenate([rvals, np.asarray(rpt, dtype=np.float64)])
        rvals = rvals[np.isfinite(rvals)]
        if len(rvals):
            ax_radar.set_ylim(float(np.nanmin(rvals)) - 4.0, float(np.nanmax(rvals)) + 4.0)
        self._apply_evm_radar_limits(ax_sinr, ax_radar, x_min, x_max)
        self._add_sinr_threshold_annotations(
            ax_sinr,
            ax_radar,
            ranges,
            comm_sinr,
            radar_on,
            comm_thr,
            radar_thr,
            for_save=for_save,
        )
        self._add_grouped_sinr_legends(ax_sinr, ax_radar, no_si_valid, lw, for_save)
        self._style_ieee_axis(ax_sinr)
        self._style_ieee_axis(ax_radar)
        return ax_sinr, ax_radar

    def _save_evm_radar_png(self) -> None:
        cache = getattr(self, "_evm_radar_plot_cache", None)
        if not cache:
            messagebox.showinfo("Save PNG", "Run the distance validation first.", parent=self.parent)
            return
        path_str = filedialog.asksaveasfilename(
            parent=self.parent,
            title="Save Communication / Sensing SINR Figure",
            defaultextension=".png",
            filetypes=[("PNG figure", "*.png")],
            initialfile="communication_sensing_sinr_vs_distance.png",
        )
        if not path_str:
            return
        try:
            fig = Figure(figsize=(5.0, 4.0), dpi=600)
            self._draw_evm_radar_figure(fig, cache, for_save=True)
            fig.tight_layout(pad=0.35)
            fig.savefig(path_str, dpi=600, bbox_inches="tight", facecolor="white")
            self.status_var.set(f"Saved PNG: {Path(path_str).name}")
        except Exception as exc:
            messagebox.showerror("Save PNG", str(exc), parent=self.parent)

    def _draw_rho_tradeoff_axis(self, ax, for_save: bool = False) -> None:
        blue = "#0000ff"
        red = "#ff0000"
        black = "#111111"
        green = "#008000"
        linewidth = 2.0 if for_save else 1.3
        n_rho = max(16, min(self._int("rho_points", 201), 2000))
        rho_axis = np.linspace(1e-3, 0.999, n_rho)
        r_comm, r_sens_on, r_sens_off, r_joint_on, _r_joint_off = self._rmax_from_ref(rho_axis)

        ax.grid(True, which="major", color="#cbd5e1", linewidth=0.55, alpha=0.75)
        ax.plot(rho_axis, r_comm, color=blue, linewidth=linewidth,
                label=r"$R_{\max}^{\mathrm{comm}}$")
        ax.plot(rho_axis, r_sens_on, color=red, linewidth=linewidth,
                label=r"$R_{\max}^{\mathrm{sens}}$ (with SI)")
        if np.any(np.isfinite(r_sens_off)):
            ax.plot(rho_axis, r_sens_off, color=green, linestyle="--", linewidth=linewidth * 0.9,
                    label=r"$R_{\max}^{\mathrm{sens}}$ (without SI)")
        ax.plot(rho_axis, r_joint_on, color=black, linewidth=linewidth,
                label=r"$R_{\max}$ (ISAC, with SI)")
        range_values = np.concatenate([
            np.asarray(r_comm, dtype=np.float64).reshape(-1),
            np.asarray(r_sens_on, dtype=np.float64).reshape(-1),
            np.asarray(r_sens_off, dtype=np.float64).reshape(-1),
            np.asarray(r_joint_on, dtype=np.float64).reshape(-1),
        ])
        range_values = range_values[np.isfinite(range_values) & (range_values >= 0.0)]
        y_upper = 3.0
        if len(range_values):
            y_upper = max(3.0, 0.5 * np.ceil(2.0 * 1.08 * float(np.max(range_values))))
        finite_joint = np.isfinite(r_joint_on)
        if np.any(finite_joint):
            finite_indices = np.flatnonzero(finite_joint)
            joint_idx = int(finite_indices[int(np.nanargmax(r_joint_on[finite_joint]))])
            joint_max = float(r_joint_on[joint_idx])
            rho_opt = float(rho_axis[joint_idx])
            ax.axhline(
                joint_max,
                color=black,
                linestyle="--",
                linewidth=1.0 if for_save else 0.9,
                alpha=0.75,
                label="_nolegend_",
            )
            ax.axvline(
                rho_opt,
                color=black,
                linestyle="--",
                linewidth=1.0 if for_save else 0.9,
                alpha=0.75,
                label="_nolegend_",
            )
            ax.plot(
                [rho_opt],
                [joint_max],
                marker="o",
                markersize=4.8 if for_save else 4.0,
                markerfacecolor="white",
                markeredgecolor=black,
                markeredgewidth=1.0,
                linestyle="None",
                zorder=6,
                label="_nolegend_",
            )
            ax.text(
                0.98,
                joint_max,
                f"{joint_max:.1f} m",
                transform=ax.get_yaxis_transform(),
                ha="right",
                va="bottom",
                fontsize=11 if for_save else 9,
                fontname="Times New Roman",
                color=black,
            )
            ax.text(
                rho_opt,
                0.025,
                rf"$\rho={rho_opt:.2f}$",
                transform=ax.get_xaxis_transform(),
                ha="left",
                va="bottom",
                fontsize=11 if for_save else 9,
                fontname="Times New Roman",
                color=black,
            )
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, y_upper)
        ax.set_xlabel(r"Power-allocation ratio, $\rho$")
        ax.set_ylabel("ISAC Range (m)")
        # if not for_save:
        #     ax.set_title("rho Trade-off")
        if not for_save or bool(self.save_legend_var.get()):
            legend_size = 11 if for_save else 9
            legend = ax.legend(
                loc="best",
                fontsize=legend_size,
                frameon=True,
                handlelength=2.4,
                borderpad=0.45,
                labelspacing=0.35,
            )
            self._style_paper_legend(legend, legend_size)
        self._style_ieee_axis(ax)

    def _save_rho_tradeoff_png(self) -> None:
        path_str = filedialog.asksaveasfilename(
            parent=self.parent,
            # title="Save rho Trade-off Figure",
            defaultextension=".png",
            filetypes=[("PNG figure", "*.png")],
            initialfile="isac_range_vs_rho.png",
        )
        if not path_str:
            return
        try:
            fig = Figure(figsize=(5.0, 4.0), dpi=600)
            ax = fig.add_subplot(111)
            self._draw_rho_tradeoff_axis(ax, for_save=True)
            fig.tight_layout(pad=0.35)
            fig.savefig(path_str, dpi=600, bbox_inches="tight", facecolor="white")
            self.status_var.set(f"Saved rho PNG: {Path(path_str).name}")
        except Exception as exc:
            messagebox.showerror("Save rho PNG", str(exc), parent=self.parent)

    def _default_comm_measurements(self) -> list[dict[str, float | str]]:
        # User-provided measured communication EVM points for 15-GBaud 32QAM.
        return [
            {"name": "Measured EVM 1000 mm", "range_m": 1.0, "evm_db": -17.49, "snr_comm_db": 17.49},
            {"name": "Measured EVM 1100 mm", "range_m": 1.1, "evm_db": -16.21, "snr_comm_db": 16.21},
            {"name": "Measured EVM 1200 mm", "range_m": 1.2, "evm_db": -15.10, "snr_comm_db": 15.10},
        ]

    @staticmethod
    def _normalize_profile_db(profile_db: np.ndarray) -> np.ndarray:
        y = np.asarray(profile_db, dtype=np.float64).reshape(-1)
        finite = np.isfinite(y)
        if np.any(finite):
            y = y - float(np.nanmax(y[finite]))
        return y

    @staticmethod
    def _metric_float_from_loaded(loaded: np.lib.npyio.NpzFile, *keys: str) -> float:
        try:
            from read_range_data import metric_map, to_float
            metrics = metric_map(loaded)
            for key in keys:
                value = to_float(metrics.get(key, {}).get("value", float("nan")))
                if np.isfinite(value):
                    return float(value)
        except Exception:
            pass
        return float("nan")

    def _c2_radar_snr_from_npz(self, path: Path, range_mm: float, use_reference: bool) -> tuple[float, float, str]:
        target_m = float(range_mm) * 1e-3
        try:
            from read_range_data import collect_range_results, infer_processing_gain_db
            with np.load(path, allow_pickle=True) as loaded:
                results = collect_range_results(loaded)
                result = next(
                    (item for item in results if str(item.get("channel", item.get("ch", ""))).strip().upper() == "C2"),
                    results[0] if results else {},
                )
                pg_db = float(infer_processing_gain_db(result, loaded))
                metric_db = self._metric_float_from_loaded(loaded, "snr_com_db_c2", "snr_rad_db")
                if use_reference:
                    x = np.asarray(result.get("ref_rng", []), dtype=np.float64).reshape(-1)
                    y = self._normalize_profile_db(np.asarray(result.get("ref_prof_db", []), dtype=np.float64).reshape(-1))
                    source = "C2 reference profile"
                else:
                    x = np.asarray(result.get("rng", []), dtype=np.float64).reshape(-1)
                    y = self._normalize_profile_db(np.asarray(result.get("prof_db", []), dtype=np.float64).reshape(-1))
                    source = "C2 range profile"
            n = min(len(x), len(y))
            if n >= 8:
                x = x[:n]
                y = y[:n]
                finite = np.isfinite(x) & np.isfinite(y)
                roi = finite & (np.abs(x - target_m) <= 0.04)
                if np.count_nonzero(roi) >= 4:
                    roi_idx = np.flatnonzero(roi)
                    pk = int(roi_idx[int(np.nanargmax(y[roi]))])
                elif np.count_nonzero(finite) >= 4:
                    finite_idx = np.flatnonzero(finite)
                    pk = int(finite_idx[int(np.nanargmax(y[finite]))])
                    source += " global peak"
                else:
                    pk = -1
                if pk >= 0:
                    floor = finite & (np.abs(x - x[pk]) > 0.025)
                    if np.count_nonzero(floor) >= 4:
                        return float(y[pk] - np.nanmedian(y[floor])), pg_db, source
            if np.isfinite(metric_db):
                return float(metric_db), pg_db, "C2 pre-DSP metric fallback"
            return float("nan"), pg_db, "C2 profile unavailable"
        except Exception as exc:
            return float("nan"), float("nan"), f"C2 sensing read error: {exc}"

    def _c2_inband_power_from_npz(self, path: Path) -> float:
        try:
            with np.load(path, allow_pickle=True) as loaded:
                return self._metric_float_from_loaded(loaded, "band_power_dbm_c2")
        except Exception:
            return float("nan")

    def _default_radar_measurements(self) -> list[dict[str, float | str]]:
        """Load built-in C2 post-processing sensing SINR markers from saved range data."""
        base = APP_DIR / "data" / "EVM_range"
        specs = [
            ("C2 sensing 1100 mm", base / "Data_range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph7.npz", 1100.0, False, True),
        ]
        points: list[dict[str, float | str]] = []
        for label, path, range_mm, use_reference, include_radar_snr in specs:
            if not path.exists():
                continue
            try:
                snr_db, pg_db, source = self._c2_radar_snr_from_npz(path, range_mm, use_reference)
                if not include_radar_snr:
                    snr_db = float("nan")
                    source = "C2 spectrum power only"
                c2_power_dbm = self._c2_inband_power_from_npz(path)
                if not (np.isfinite(snr_db) or np.isfinite(c2_power_dbm)):
                    continue
                points.append({
                    "name": label,
                    "range_m": float(range_mm) * 1e-3,
                    "evm_db": float("nan"),
                    "snr_comm_db": float("nan"),
                    "snr_sens_db": float(snr_db),
                    "c2_inband_power_dbm": float(c2_power_dbm),
                    "c2_si_state": "on",
                    "radar_processing_gain_db": float(pg_db),
                    "snr_source": f"{path.name}: {source}",
                })
            except Exception:
                continue
        return points

    def _default_measurements(self) -> list[dict[str, float | str]]:
        return self._default_radar_measurements()

    @staticmethod
    def _range_value_from_token(token: str) -> tuple[float, float]:
        raw = token.strip()
        if not raw:
            return float("nan"), float("nan")
        for sep in (":", ",", "=", " "):
            if sep in raw:
                left, right = raw.split(sep, 1)
                break
        else:
            return float("nan"), float("nan")
        try:
            r_raw = float(left.strip())
            val = float(right.strip())
        except Exception:
            return float("nan"), float("nan")
        # User-facing entry is mm by default.  Values <= 50 are accepted as m.
        r_m = r_raw * 1e-3 if abs(r_raw) > 50.0 else r_raw
        if r_m <= 0.0:
            return float("nan"), float("nan")
        return float(r_m), float(val)

    def _parse_manual_points(self, key: str, value_key: str, name_prefix: str, si_state: str | None = None) -> list[dict[str, float | str]]:
        raw = self.params.get(key, tk.StringVar(value="")).get()
        tokens = [tok.strip() for tok in raw.replace("\n", ";").replace(",", ";").split(";")]
        points: list[dict[str, float | str]] = []
        for idx, token in enumerate(tokens, start=1):
            r_m, value = self._range_value_from_token(token)
            if not (np.isfinite(r_m) and np.isfinite(value)):
                continue
            point: dict[str, float | str] = {
                "name": f"{name_prefix} {r_m * 1e3:.0f} mm",
                "range_m": r_m,
                value_key: value,
                "source": "manual",
            }
            if value_key == "evm_db":
                point["snr_comm_db"] = -value
            if si_state is not None:
                point["c2_si_state"] = si_state
            points.append(point)
        return points

    def _manual_measurements(self) -> list[dict[str, float | str]]:
        points = self._parse_manual_points("manual_evm_points", "evm_db", "Manual EVM")
        points.extend(self._parse_manual_points("manual_c2_si_on_points", "c2_inband_power_dbm", "Manual C2 SI-on", "on"))
        points.extend(self._parse_manual_points("manual_c2_si_off_points", "c2_inband_power_dbm", "Manual C2 SI-off", "off"))
        return points

    def _active_measurements(self) -> list[dict[str, float | str]]:
        manual = self._manual_measurements()
        manual_c2_ranges: dict[str, list[float]] = {"on": [], "off": []}
        for point in manual:
            state = str(point.get("c2_si_state", "")).strip().lower()
            rr = float(point.get("range_m", float("nan")))
            pp = float(point.get("c2_inband_power_dbm", float("nan")))
            if state in manual_c2_ranges and np.isfinite(rr) and np.isfinite(pp):
                manual_c2_ranges[state].append(rr)
        active: list[dict[str, float | str]] = []
        for p in self.meas_points:
            state = str(p.get("c2_si_state", "")).strip().lower()
            rr = float(p.get("range_m", float("nan")))
            has_c2 = np.isfinite(float(p.get("c2_inband_power_dbm", float("nan"))))
            same_range_override = any(
                np.isfinite(rr) and abs(rr - manual_rr) <= 5e-4
                for manual_rr in manual_c2_ranges.get(state, [])
            )
            if has_c2 and same_range_override:
                continue
            active.append(p)
        active.extend(manual)
        return active

    def _fixed_raw_noise_dbm(self) -> float:
        n_dbm = self._finite_param("raw_noise_dbm")
        if np.isfinite(n_dbm):
            return float(n_dbm)
        bw_hz = max(self._float("bandwidth_ghz", 15.0) * 1e9, 1.0)
        # Conservative fallback: displayed spectrum floor integrated over the
        # signal bandwidth.  If raw H-domain calibration is available, enter it
        # in "Fixed raw H noise [dBm]" and this fallback is bypassed.
        return float(-130.0 + 10.0 * np.log10(bw_hz))

    def _sensing_ref_from_fixed_noise(self, fallback_db: float) -> float:
        peak_dbm = self._finite_param("target_peak_dbm_ref")
        if not np.isfinite(peak_dbm):
            return float(fallback_db)
        n_raw_dbm = self._fixed_raw_noise_dbm()
        alpha_db = self._float("alpha_ref_db", 0.0)
        gp_db = self._float("processing_gain_db", 0.0)
        return float(peak_dbm - n_raw_dbm + alpha_db + gp_db)

    def _fit_measured_comm_snr(self, ranges: np.ndarray) -> np.ndarray:
        pts = [
            (float(p["range_m"]), float(p["snr_comm_db"]))
            for p in self._active_measurements()
            if np.isfinite(float(p.get("range_m", np.nan))) and np.isfinite(float(p.get("snr_comm_db", np.nan)))
        ]
        r = np.maximum(np.asarray(ranges, dtype=np.float64), 1e-12)
        if len(pts) >= 2:
            x = np.log10(np.asarray([p[0] for p in pts], dtype=np.float64))
            y = np.asarray([p[1] for p in pts], dtype=np.float64)
            slope, intercept = np.polyfit(x, y, 1)
            return intercept + slope * np.log10(r)
        ref_r = max(self._float("ref_range_m", 1.0), 1e-12)
        ref_snr = self._float("comm_ref_snr_db", 17.49)
        return ref_snr - 20.0 * np.log10(r / ref_r)

    def _c2_power_points(self, si_state: str | None = None) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        state_filter = str(si_state).strip().lower() if si_state is not None else ""
        min_power_dbm = self._finite_param("c2_meas_power_min_dbm")
        for p in self._active_measurements():
            point_state = str(p.get("c2_si_state", "on")).strip().lower()
            if state_filter and point_state != state_filter:
                continue
            rr = float(p.get("range_m", float("nan")))
            pp = float(p.get("c2_inband_power_dbm", float("nan")))
            if point_state == "on" and np.isfinite(min_power_dbm) and np.isfinite(pp) and pp < min_power_dbm:
                continue
            if np.isfinite(rr) and rr > 0.0 and np.isfinite(pp):
                pts.append((rr, pp))
        return pts

    def _fit_c2_power_slope(self, si_state: str | None = None) -> tuple[float, float]:
        pts = self._c2_power_points(si_state)
        if len(pts) < 2:
            return float("nan"), float("nan")
        r_vals = np.asarray([p[0] for p in pts], dtype=np.float64)
        if float(np.nanmax(r_vals) / max(np.nanmin(r_vals), 1e-12)) < 1.5:
            return float("nan"), float("nan")
        x = np.log10(r_vals)
        y = np.asarray([p[1] for p in pts], dtype=np.float64)
        if len(np.unique(np.round(x, 9))) < 2:
            return float("nan"), float("nan")
        slope, intercept = np.polyfit(x, y, 1)
        return float(slope), float(intercept)

    def _c2_power_ref_dbm(self) -> float:
        ref_r = max(self._float("ref_range_m", 1.0), 1e-12)
        entered = self._finite_param("c2_power_ref_dbm")
        if np.isfinite(entered):
            return float(entered)
        pts = self._c2_power_points("on")
        if pts:
            idx = int(np.argmin(np.abs(np.log10(np.maximum([p[0] for p in pts], 1e-12) / ref_r))))
            return float(pts[idx][1])
        return -42.52

    def _c2_noise_power_dbm(self) -> float:
        entered = self._finite_param("c2_noise_power_dbm")
        if np.isfinite(entered):
            return float(entered)
        return -46.47

    def _radar_proc_gain_db(self) -> float:
        entered = self._finite_param("radar_proc_gain_db")
        if np.isfinite(entered):
            return float(entered)
        legacy = self._finite_param("processing_gain_db")
        return float(legacy) if np.isfinite(legacy) else 0.0

    def _c2_power_curve_dbm(self, ranges: np.ndarray, si_state: str) -> np.ndarray:
        r = np.maximum(np.asarray(ranges, dtype=np.float64), 1e-12)
        ref_r = max(self._float("ref_range_m", 1.0), 1e-12)
        rho_ref = float(np.clip(self._float("rho_ref", 0.20), 1e-9, 1.0 - 1e-9))
        rho_v = float(np.clip(self._float("rho", 0.20), 1e-9, 1.0 - 1e-9))
        rho_term = 10.0 * np.log10(rho_v / rho_ref)
        if str(si_state).strip().lower() == "off":
            pts = self._c2_power_points("off")
            if pts:
                r_pts = np.asarray([p[0] for p in pts], dtype=np.float64)
                p_pts = np.asarray([p[1] for p in pts], dtype=np.float64)
                idx = int(np.argmin(np.abs(np.log10(np.maximum(r_pts, 1e-12) / ref_r))))
                ref_r = float(r_pts[idx])
                p_ref = float(p_pts[idx])
            else:
                p_ref = self._finite_param("c2_no_si_power_ref_dbm")
                if not np.isfinite(p_ref):
                    return np.full_like(r, np.nan, dtype=np.float64)
                if p_ref >= self._c2_power_ref_dbm():
                    return np.full_like(r, np.nan, dtype=np.float64)
            # No-SI ZBD output is echo self-beat: echo RF power follows
            # 1/R^4, and the detector output electrical power follows 1/R^8.
            return p_ref + rho_term - 80.0 * np.log10(r / max(ref_r, 1e-12))
        # SI-assisted ZBD homodyne output is proportional to SI amplitude times
        # echo amplitude; the detected IF electrical power follows about 1/R^4.
        return self._c2_power_ref_dbm() + rho_term - 40.0 * np.log10(r / ref_r)

    def _no_si_anchor_status(self) -> str:
        p_no_si = self._finite_param("c2_no_si_power_ref_dbm")
        if not np.isfinite(p_no_si):
            return "not set"
        p_si = self._c2_power_ref_dbm()
        if p_no_si >= p_si:
            return f"invalid ({p_no_si:.1f} >= SI {p_si:.1f} dBm)"
        return f"{p_no_si:.1f} dBm"

    def _radar_snr_from_c2_power_db(self, power_dbm: np.ndarray | float) -> np.ndarray | float:
        return np.asarray(power_dbm, dtype=np.float64) - self._c2_noise_power_dbm() + self._radar_proc_gain_db()

    def _c2_power_radar_snr_points(self, si_state: str | None = None) -> list[tuple[float, float]]:
        """Return measured sensing SINR, falling back to calibrated C2 power only when absent."""
        pts: list[tuple[float, float]] = []
        state_filter = str(si_state).strip().lower() if si_state is not None else ""
        min_power_dbm = self._finite_param("c2_meas_power_min_dbm")
        for point in self._active_measurements():
            point_state = str(point.get("c2_si_state", "on")).strip().lower()
            if state_filter and point_state != state_filter:
                continue
            rr = float(point.get("range_m", float("nan")))
            pp = float(point.get("c2_inband_power_dbm", float("nan")))
            if point_state == "on" and np.isfinite(min_power_dbm) and np.isfinite(pp) and pp < min_power_dbm:
                continue
            snr = float(point.get("snr_sens_db", float("nan")))
            allow_power_conversion = bool(point.get("derive_radar_snr_from_power", False)) or str(
                point.get("source", "")
            ).strip().lower() == "manual"
            if not np.isfinite(snr) and np.isfinite(pp) and allow_power_conversion:
                snr = float(pp - self._c2_noise_power_dbm() + self._radar_proc_gain_db())
            if np.isfinite(rr) and rr > 0.0 and np.isfinite(snr):
                pts.append((rr, snr))
        return pts

    def _derived_radar_ref_snr_db(self) -> float:
        return float(self._c2_power_ref_dbm() - self._c2_noise_power_dbm() + self._radar_proc_gain_db())

    def _snr_curve_from_ref(self, ranges: np.ndarray, ref_snr_db: float, rho: float, kind: str) -> np.ndarray:
        r = np.maximum(np.asarray(ranges, dtype=np.float64), 1e-12)
        ref_r = max(self._float("ref_range_m", 1.0), 1e-12)
        rho_ref = float(np.clip(self._float("rho_ref", 0.20), 1e-9, 1.0 - 1e-9))
        rho_v = float(np.clip(rho, 1e-9, 1.0 - 1e-9))
        if kind == "comm":
            rho_term = 10.0 * np.log10((1.0 - rho_v) / max(1.0 - rho_ref, 1e-12))
            range_term = -20.0 * np.log10(r / ref_r)
        else:
            rho_term = 10.0 * np.log10(rho_v / rho_ref)
            range_term = -40.0 * np.log10(r / ref_r)
        return float(ref_snr_db) + rho_term + range_term

    def _rmax_from_ref(
        self, rho_axis: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        ref_r = max(self._float("ref_range_m", 1.0), 1e-12)
        rho_ref = float(np.clip(self._float("rho_ref", 0.20), 1e-9, 1.0 - 1e-9))
        rho = np.clip(np.asarray(rho_axis, dtype=np.float64), 1e-9, 1.0 - 1e-9)
        comm_ref = self._float("sim_comm_ref_snr_db", self._float("comm_ref_snr_db", 17.49))
        sens_on_ref = self._derived_radar_ref_snr_db()
        sens_off_ref = float("nan")
        sweep = getattr(self, "sim_sweep", None)
        if sweep is not None:
            sweep_r = np.asarray(sweep.get("range_m", []), dtype=np.float64)
            if len(sweep_r):
                ref_idx = int(np.nanargmin(np.abs(sweep_r - ref_r)))
                sweep_rho = np.asarray(sweep.get("sweep_rho", []), dtype=np.float64).reshape(-1)
                if len(sweep_rho) and np.isfinite(sweep_rho[0]):
                    rho_ref = float(np.clip(sweep_rho[0], 1e-9, 1.0 - 1e-9))
                on_vals = np.asarray(sweep.get("on_radar_snr_db", []), dtype=np.float64)
                off_vals = np.asarray(sweep.get("off_radar_snr_db", []), dtype=np.float64)
                if ref_idx < len(on_vals) and np.isfinite(on_vals[ref_idx]):
                    sens_on_ref = float(on_vals[ref_idx])
                if ref_idx < len(off_vals) and np.isfinite(off_vals[ref_idx]):
                    sens_off_ref = float(off_vals[ref_idx])
        if not np.isfinite(sens_off_ref):
            off_power = np.asarray(
                self._c2_power_curve_dbm(np.asarray([ref_r]), "off"),
                dtype=np.float64,
            )
            if len(off_power) and np.isfinite(off_power[0]):
                sens_off_ref = float(self._radar_snr_from_c2_power_db(off_power[0]))
        comm_thr = self._float("comm_req_snr_db", 15.75)
        sens_thr = self._float("sens_req_snr_db", 13.2)
        comm_at_ref = comm_ref + 10.0 * np.log10((1.0 - rho) / max(1.0 - rho_ref, 1e-12))
        r_comm = ref_r * (10.0 ** ((comm_at_ref - comm_thr) / 20.0))
        if np.isfinite(sens_off_ref):
            # Phase-averaged ZBD target SINR:
            # gamma_on = A_hom*(rho/rho0)*(R0/R)^4
            #          + B_self*(rho/rho0)^2*(R0/R)^8.
            gamma_on_ref = 10.0 ** (sens_on_ref / 10.0)
            gamma_off_ref = 10.0 ** (sens_off_ref / 10.0)
            gamma_hom_ref = max(gamma_on_ref - gamma_off_ref, 0.0)
            rho_ratio = rho / rho_ref
            gamma_hom = gamma_hom_ref * rho_ratio
            gamma_self = gamma_off_ref * (rho_ratio ** 2)
            gamma_thr = max(10.0 ** (sens_thr / 10.0), 1e-30)
            disc = np.maximum(gamma_hom ** 2 + 4.0 * gamma_thr * gamma_self, 0.0)
            x_on = (gamma_hom + np.sqrt(disc)) / (2.0 * gamma_thr)
            r_sens_on = ref_r * np.maximum(x_on, 0.0) ** 0.25
            r_sens_off = ref_r * np.maximum(gamma_self / gamma_thr, 0.0) ** 0.125
        else:
            sens_on_at_ref = sens_on_ref + 10.0 * np.log10(rho / rho_ref)
            r_sens_on = ref_r * (10.0 ** ((sens_on_at_ref - sens_thr) / 40.0))
            r_sens_off = np.full_like(rho, np.nan, dtype=np.float64)
        return (
            r_comm,
            r_sens_on,
            r_sens_off,
            np.minimum(r_comm, r_sens_on),
            np.minimum(r_comm, r_sens_off),
        )

    def _sync_from_sim(self) -> None:
        try:
            if self.photonic_source is None or not hasattr(self.photonic_source, "_cfg_from_ui"):
                return
            cfg = self.photonic_source._cfg_from_ui()
            waveform_kind = classify_isac_waveform(cfg.waveform)
            bw_hz = estimate_waveform_bandwidth_hz(cfg, waveform_kind)
            self.params["bandwidth_ghz"].set(f"{bw_hz / 1e9:.6g}")
            self.params["sweep_tx_power_dbm"].set(f"{float(cfg.utcpd_target_dbm):.6g}")
            self.params["si_on_iso_db"].set(f"{float(cfg.omt_iso_db):.6g}")
            self.params["rho"].set(f"{float(cfg.pilot_rho):.6g}")
            self.params["rho_ref"].set(f"{float(cfg.pilot_rho):.6g}")
            self.params["ref_range_m"].set(f"{float(cfg.target_dist_m):.6g}")
            data = getattr(self.photonic_source, "data", None)
            if data:
                evm_db = float(data.get("evm_db", float("nan")))
                if np.isfinite(evm_db):
                    self.params["sim_comm_ref_snr_db"].set(f"{-evm_db:.6g}")
                radar_db = float("nan")
                for key in ("snr_rad_post_db_c2", "radar_snr_db", "radar_pre_snr_db_c2"):
                    radar_db = float(data.get(key, float("nan")))
                    if np.isfinite(radar_db):
                        break
                if np.isfinite(radar_db):
                    self.params["sim_sens_ref_snr_db"].set(f"{radar_db:.6g}")
                pg_db = float(data.get("radar_processing_gain_db_c2", data.get("processing_gain_db", float("nan"))))
                if np.isfinite(pg_db):
                    self.params["processing_gain_db"].set(f"{pg_db:.6g}")
                c2m = data.get("c2_band_metrics", {})
                p_dbm = float(c2m.get("band_power_dbm", float("nan")))
                if np.isfinite(p_dbm):
                    self.params["c2_power_ref_dbm"].set(f"{p_dbm:.6g}")
                    self.params["c2_no_si_power_ref_dbm"].set("")
                n_dbm = float(c2m.get("noise_power_dbm", float("nan")))
                if np.isfinite(n_dbm):
                    self.params["raw_noise_dbm"].set(f"{n_dbm:.6g}")
            self._run()
        except Exception as exc:
            messagebox.showerror("Sync Sim", str(exc), parent=self.parent)

    def _load_params_json(self) -> None:
        path_str = filedialog.askopenfilename(
            parent=self.parent,
            title="Load Save Params JSON",
            initialdir=str(APP_DIR),
            filetypes=[("JSON preset", "*.json"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            with open(path_str, "r", encoding="utf-8") as f:
                preset = json.load(f)
            if self.photonic_source is not None and hasattr(self.photonic_source, "_apply_sim_preset"):
                self.photonic_source._apply_sim_preset(preset)
                cfg = self.photonic_source._cfg_from_ui()
                ref_r = max(self._float("ref_range_m", float(cfg.target_dist_m)), 1e-6)
                cfg.target_dist_m = ref_r
                self.params["ref_range_m"].set(f"{ref_r:.6g}")
                self.params["sweep_tx_power_dbm"].set(f"{float(cfg.utcpd_target_dbm):.6g}")
                self.params["si_on_iso_db"].set(f"{float(cfg.omt_iso_db):.6g}")
                self.params["rho"].set(f"{float(cfg.pilot_rho):.6g}")
                self.params["rho_ref"].set(f"{float(cfg.pilot_rho):.6g}")
                sim = run_isac_sim(cfg)
                evm_db = float(sim.get("evm_db", float("nan")))
                if np.isfinite(evm_db):
                    self.params["sim_comm_ref_snr_db"].set(f"{-evm_db:.6g}")
                radar_db = float("nan")
                for key in ("snr_rad_post_db_c2", "radar_snr_db", "radar_pre_snr_db_c2"):
                    radar_db = float(sim.get(key, float("nan")))
                    if np.isfinite(radar_db):
                        break
                if np.isfinite(radar_db):
                    self.params["sim_sens_ref_snr_db"].set(f"{radar_db:.6g}")
                pg_db = float(sim.get("radar_processing_gain_db_c2", sim.get("processing_gain_db", float("nan"))))
                if np.isfinite(pg_db):
                    self.params["processing_gain_db"].set(f"{pg_db:.6g}")
                c2m = sim.get("c2_band_metrics", {})
                p_dbm = float(c2m.get("band_power_dbm", float("nan")))
                if np.isfinite(p_dbm):
                    self.params["c2_power_ref_dbm"].set(f"{p_dbm:.6g}")
                    self.params["c2_no_si_power_ref_dbm"].set("")
                self.params["bandwidth_ghz"].set(f"{float(sim.get('occupied_bw_hz', 15e9)) / 1e9:.6g}")
            self.status_var.set(f"Loaded params: {Path(path_str).name}")
            self._run()
        except Exception as exc:
            messagebox.showerror("Load Params JSON", str(exc), parent=self.parent)

    def _load_measurement(self) -> None:
        path_str = filedialog.askopenfilename(
            parent=self.parent,
            title="Load Saved Capture/Range Data",
            initialdir=str(APP_DIR / "data"),
            filetypes=[("NumPy save data", "*.npz"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            path = Path(path_str)
            with np.load(path, allow_pickle=True) as loaded:
                metrics = self._metric_dict_from_npz(loaded)
                known_ranges_m = {
                    "Data_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz": 1.014,
                    "Data_range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph7.npz": 1.100,
                    "Data_range1100_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz": 1.100,
                    "Range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz": 1.014,
                }
                range_m = float(known_ranges_m.get(path.name, float("nan")))
                if not np.isfinite(range_m):
                    for key in ("range_summary_display_m", "range_summary_peak_m", "range_summary_matched_filter_peak_m"):
                        range_m = self._range_summary_float_for_channel(loaded, key, "C2")
                        if np.isfinite(range_m):
                            break
                snr_comm = metrics.get("evm_snr", float("nan"))
                evm_db = metrics.get("evm_db", float("nan"))
                if not np.isfinite(snr_comm) and np.isfinite(evm_db):
                    snr_comm = -float(evm_db)
                snr_sens = self._range_summary_float_for_channel(
                    loaded, "range_summary_snr_rad_post_db", "C2"
                )
                if not np.isfinite(snr_sens):
                    snr_sens = metrics.get(
                        "snr_rad_post_db_c2",
                        metrics.get("snr_rad_post_db", float("nan")),
                    )
                if not np.isfinite(snr_sens) and np.isfinite(range_m):
                    snr_sens, _, _ = self._c2_radar_snr_from_npz(
                        path, range_m * 1e3, False
                    )
                if not np.isfinite(snr_sens):
                    snr_sens = metrics.get(
                        "snr_rad_db", metrics.get("snr_com_db_c2", float("nan"))
                    )
                c2_power_dbm = metrics.get("band_power_dbm_c2", float("nan"))
                point = {
                    "name": path.stem[:18],
                    "source_path": str(path.resolve()),
                    "range_m": range_m,
                    "evm_db": -snr_comm if np.isfinite(snr_comm) else evm_db,
                    "snr_comm_db": snr_comm,
                    "snr_sens_db": snr_sens,
                    "c2_inband_power_dbm": c2_power_dbm,
                    "c2_si_state": "on",
                }
                source_path = str(path.resolve())
                self.meas_points = [
                    p for p in self.meas_points
                    if str(p.get("source_path", "")) != source_path
                ]
                self.meas_points.append(point)
            self.status_var.set(
                f"Loaded measurement: {path.name}  "
                f"C2={c2_power_dbm:.2f} dBm  Sensing SINR={snr_sens:.2f} dB"
            )
            self._refresh_plot()
        except Exception as exc:
            messagebox.showerror("Load Save Data", str(exc), parent=self.parent)

    def _clear_measurements(self) -> None:
        self.meas_points = self._default_measurements()
        self._refresh_plot()

    def _refresh_plot(self) -> None:
        """Redraw from the cached sweep without running the physical simulation."""
        self._run(use_cached_sweep=True)

    def _sweep_metric_row(self, data: dict, fixed_noise_dbm: float | None = None, fixed_pg_db: float | None = None) -> dict[str, float]:
        evm_db = float(data.get("evm_db", float("nan")))
        c2m = data.get("c2_band_metrics", {})
        c2_power_dbm = float(c2m.get("band_power_dbm", float("nan")))
        c2_noise_dbm = float(c2m.get("noise_power_dbm", c2m.get("noise_dbm", float("nan"))))
        pre_snr_db = float(data.get("radar_pre_snr_db_c2", float("nan")))
        post_snr_db = float(data.get("snr_rad_post_db_c2", data.get("radar_snr_db", float("nan"))))
        pg_db = float("nan")
        if np.isfinite(post_snr_db) and np.isfinite(pre_snr_db):
            pg_db = post_snr_db - pre_snr_db
        elif np.isfinite(data.get("radar_processing_gain_db_c2", float("nan"))):
            pg_db = float(data.get("radar_processing_gain_db_c2"))
        use_noise = c2_noise_dbm if fixed_noise_dbm is None else fixed_noise_dbm
        use_pg = pg_db if fixed_pg_db is None else fixed_pg_db
        radar_snr_db = c2_power_dbm - use_noise + use_pg if all(np.isfinite(v) for v in (c2_power_dbm, use_noise, use_pg)) else post_snr_db
        return {
            "evm_db": evm_db,
            "comm_snr_db": -evm_db if np.isfinite(evm_db) else float("nan"),
            "c2_power_dbm": c2_power_dbm,
            "c2_noise_dbm": c2_noise_dbm,
            "pre_snr_db": pre_snr_db,
            "post_snr_db": post_snr_db,
            "pg_db": pg_db,
            "radar_snr_db": float(radar_snr_db),
        }

    def _run_distance_sweep(self, ranges: np.ndarray) -> dict[str, np.ndarray] | None:
        if self.photonic_source is None or not hasattr(self.photonic_source, "_cfg_from_ui"):
            return None
        base_cfg = self.photonic_source._cfg_from_ui()
        iso_on = self._float("si_on_iso_db", 24.0)
        iso_off = self._float("si_off_iso_db", 1000.0)
        sweep_tx_dbm = self._finite_param("sweep_tx_power_dbm")
        sweep_rho = float(np.clip(self._float("rho", float(base_cfg.pilot_rho)), 1e-9, 0.95))
        ref_r = max(self._float("ref_range_m", 1.0), 1e-6)
        r = np.asarray(ranges, dtype=np.float64)
        sim_r = np.maximum(r, 0.1)
        ref_idx = int(np.argmin(np.abs(sim_r - ref_r)))

        raw: dict[str, list[dict[str, float]]] = {"on": [], "off": []}
        for state, iso in (("on", iso_on), ("off", iso_off)):
            for i, dist in enumerate(sim_r):
                cfg = copy.deepcopy(base_cfg)
                cfg.target_dist_m = float(dist)
                cfg.delay_ns = (2.0 * cfg.target_dist_m) / 3e8 * 1e9
                if np.isfinite(sweep_tx_dbm):
                    cfg.utcpd_target_dbm = float(sweep_tx_dbm)
                    cfg.tx_power_dbm = float(sweep_tx_dbm)
                cfg.pilot_rho = sweep_rho
                cfg.omt_iso_db = float(iso)
                cfg.si_enable = True
                cfg.rx_mode = "ZBD"
                if cfg.sim_seed is None:
                    cfg.sim_seed = 0
                tx_txt = f", TX={sweep_tx_dbm:.1f} dBm" if np.isfinite(sweep_tx_dbm) else ""
                self.status_var.set(f"Sweeping {state.upper()} isolation={iso:.1f} dB{tx_txt}: {i + 1}/{len(sim_r)}")
                try:
                    self.parent.update_idletasks()
                except Exception:
                    pass
                raw[state].append(self._sweep_metric_row(run_isac_sim(cfg)))

        # Noise power and processing gain are receiver/DSP calibration
        # constants. Re-estimating either one at every transmit power makes
        # the apparent gain collapse as the target grows and incorrectly
        # cancels the sensing-SINR improvement.
        ref_noise = self._finite_param("c2_noise_power_dbm")
        if not np.isfinite(ref_noise):
            ref_noise = raw["on"][ref_idx].get("c2_noise_dbm", float("nan"))
        if not np.isfinite(ref_noise):
            finite_noise = [row["c2_noise_dbm"] for row in raw["on"] if np.isfinite(row.get("c2_noise_dbm", float("nan")))]
            ref_noise = float(np.nanmedian(finite_noise)) if finite_noise else float("nan")
        ref_pg = self._finite_param("radar_proc_gain_db")
        if not np.isfinite(ref_pg):
            ref_pg = raw["on"][ref_idx].get("pg_db", float("nan"))
        if not np.isfinite(ref_pg):
            finite_pg = [row["pg_db"] for row in raw["on"] if np.isfinite(row.get("pg_db", float("nan")))]
            ref_pg = float(np.nanmedian(finite_pg)) if finite_pg else 0.0

        out: dict[str, np.ndarray] = {"range_m": sim_r, "requested_range_m": r}
        for state in ("on", "off"):
            rows = [self._sweep_metric_row({"evm_db": row["evm_db"], "c2_band_metrics": {"band_power_dbm": row["c2_power_dbm"], "noise_power_dbm": row["c2_noise_dbm"]}, "radar_pre_snr_db_c2": row["pre_snr_db"], "snr_rad_post_db_c2": row["post_snr_db"]}, ref_noise, ref_pg) for row in raw[state]]
            for key in ("evm_db", "comm_snr_db", "c2_power_dbm", "c2_noise_dbm", "pre_snr_db", "post_snr_db", "pg_db", "radar_snr_db"):
                out[f"{state}_{key}"] = np.asarray([row[key] for row in rows], dtype=np.float64)
        law_r = np.maximum(sim_r, 1e-12)
        law_ref_r = max(float(sim_r[ref_idx]), 1e-12)
        if np.isfinite(out["off_c2_power_dbm"][ref_idx]):
            off_p_ref = 10.0 ** (float(out["off_c2_power_dbm"][ref_idx]) / 10.0)
            off_p = off_p_ref * (law_r / law_ref_r) ** (-8.0)
            out["off_c2_power_raw_dbm"] = out["off_c2_power_dbm"].copy()
            out["off_c2_power_dbm"] = 10.0 * np.log10(np.maximum(off_p, 1e-30))
        if np.isfinite(out["on_c2_power_dbm"][ref_idx]):
            on_p_ref = 10.0 ** (float(out["on_c2_power_dbm"][ref_idx]) / 10.0)
            off_p_ref = 10.0 ** (float(out["off_c2_power_dbm"][ref_idx]) / 10.0) if np.isfinite(out["off_c2_power_dbm"][ref_idx]) else 0.0
            hom_p_ref = max(on_p_ref - off_p_ref, 0.0)
            off_p = 10.0 ** (out["off_c2_power_dbm"] / 10.0) if np.any(np.isfinite(out["off_c2_power_dbm"])) else np.zeros_like(law_r)
            hom_p = hom_p_ref * (law_r / law_ref_r) ** (-4.0)
            out["on_c2_power_raw_dbm"] = out["on_c2_power_dbm"].copy()
            out["on_c2_power_dbm"] = 10.0 * np.log10(np.maximum(off_p + hom_p, 1e-30))

        if np.isfinite(out["off_radar_snr_db"][ref_idx]):
            off_s_ref = 10.0 ** (float(out["off_radar_snr_db"][ref_idx]) / 10.0)
            off_s = off_s_ref * (law_r / law_ref_r) ** (-8.0)
            out["off_radar_snr_raw_db"] = out["off_radar_snr_db"].copy()
            out["off_radar_snr_db"] = 10.0 * np.log10(np.maximum(off_s, 1e-30))
        if np.isfinite(out["on_radar_snr_db"][ref_idx]):
            on_s_ref = 10.0 ** (float(out["on_radar_snr_db"][ref_idx]) / 10.0)
            off_s_ref = 10.0 ** (float(out["off_radar_snr_db"][ref_idx]) / 10.0) if np.isfinite(out["off_radar_snr_db"][ref_idx]) else 0.0
            hom_s_ref = max(on_s_ref - off_s_ref, 0.0)
            off_s = 10.0 ** (out["off_radar_snr_db"] / 10.0) if np.any(np.isfinite(out["off_radar_snr_db"])) else np.zeros_like(law_r)
            hom_s = hom_s_ref * (law_r / law_ref_r) ** (-4.0)
            out["on_radar_snr_raw_db"] = out["on_radar_snr_db"].copy()
            out["on_radar_snr_db"] = 10.0 * np.log10(np.maximum(off_s + hom_s, 1e-30))
        out["ref_noise_dbm"] = np.asarray([ref_noise], dtype=np.float64)
        out["ref_pg_db"] = np.asarray([ref_pg], dtype=np.float64)
        out["iso_on_db"] = np.asarray([iso_on], dtype=np.float64)
        out["iso_off_db"] = np.asarray([iso_off], dtype=np.float64)
        out["sweep_rho"] = np.asarray([sweep_rho], dtype=np.float64)
        out["sweep_tx_power_dbm"] = np.asarray([sweep_tx_dbm], dtype=np.float64)

        ref_on_power = float(out["on_c2_power_dbm"][ref_idx])
        if np.isfinite(ref_on_power):
            self.params["c2_power_ref_dbm"].set(f"{ref_on_power:.6g}")
        if np.isfinite(ref_noise) and not np.isfinite(self._finite_param("c2_noise_power_dbm")):
            self.params["c2_noise_power_dbm"].set(f"{ref_noise:.6g}")
        if np.isfinite(ref_pg) and not np.isfinite(self._finite_param("radar_proc_gain_db")):
            self.params["radar_proc_gain_db"].set(f"{ref_pg:.6g}")
        ref_comm = float(out["on_comm_snr_db"][ref_idx])
        if np.isfinite(ref_comm):
            self.params["sim_comm_ref_snr_db"].set(f"{ref_comm:.6g}")
        self.params["rho_ref"].set(f"{sweep_rho:.6g}")
        return out

    def _run(self, use_cached_sweep: bool = False) -> None:
        try:
            r_min = max(self._float("r_min_m", 0.0), 0.0)
            r_max = max(self._float("r_max_m", 4.0), max(r_min + 0.1, 0.1))
            plot_x_min = self._finite_param("plot_x_min_m")
            plot_x_max = self._finite_param("plot_x_max_m")
            if not np.isfinite(plot_x_min):
                plot_x_min = 0.0
            if not np.isfinite(plot_x_max):
                plot_x_max = 2.0
            if plot_x_max <= plot_x_min:
                plot_x_max = plot_x_min + max(r_max - r_min, 0.1)
            n_range = max(3, min(self._int("sweep_points", self._int("n_range", 21)), 101))
            ranges = np.linspace(r_min, r_max, n_range)
            ref_r = max(self._float("ref_range_m", 1.0), 1e-12)
            if r_min <= ref_r <= r_max and not np.any(np.isclose(ranges, ref_r, rtol=0.0, atol=1e-12)):
                ranges = np.sort(np.append(ranges, ref_r))
            curve_ranges = ranges.astype(np.float64, copy=True)
            curve_ranges[curve_ranges <= 0.0] = np.nan
            rho = float(np.clip(self._float("rho", 0.20), 1e-9, 1.0 - 1e-9))
            comm_thr = self._float("comm_req_snr_db", 15.75)
            sens_thr = self._float("sens_req_snr_db", 13.2)
            sweep = self.sim_sweep if use_cached_sweep else self._run_distance_sweep(ranges)
            if sweep is not None:
                self.sim_sweep = sweep
                ranges = sweep["range_m"]
                sim_comm_snr = sweep["on_comm_snr_db"]
                sim_eff_sinr = sim_comm_snr
                sim_c2_on_power = sweep["on_c2_power_dbm"]
                sim_c2_off_power = sweep["off_c2_power_dbm"]
                sim_sens_on_snr = sweep["on_radar_snr_db"]
                sim_sens_off_snr = sweep["off_radar_snr_db"]
                no_si_valid = bool(np.any(np.isfinite(sim_sens_off_snr)))
                ref_r = max(self._float("ref_range_m", 1.0), 1e-6)
                ref_idx = int(np.argmin(np.abs(ranges - ref_r)))
                sens_ref = (
                    float(sim_sens_on_snr[ref_idx])
                    if np.isfinite(sim_sens_on_snr[ref_idx])
                    else float("nan")
                )
            else:
                sim_comm_snr = self._snr_curve_from_ref(
                    curve_ranges,
                    self._float("sim_comm_ref_snr_db", self._float("comm_ref_snr_db", 17.49)),
                    rho,
                    "comm",
                )
                sim_eff_sinr = sim_comm_snr
                sim_c2_on_power = self._c2_power_curve_dbm(curve_ranges, "on")
                sim_c2_off_power = self._c2_power_curve_dbm(curve_ranges, "off")
                sim_sens_on_snr = self._radar_snr_from_c2_power_db(sim_c2_on_power)
                sim_sens_off_snr = self._radar_snr_from_c2_power_db(sim_c2_off_power)
                no_si_valid = bool(np.any(np.isfinite(sim_sens_off_snr)))
                sens_ref = self._derived_radar_ref_snr_db()

            self.fig.clf()
            grid_axes = np.asarray(self.fig.subplots(2, 2), dtype=object)
            self.axes = grid_axes
            ax_rad = grid_axes[0, 0]
            ax_snr = grid_axes[0, 1]
            ax_c2pow = grid_axes[1, 0]
            ax_rho = grid_axes[1, 1]
            ax_evm = ax_rad.twinx()

            blue = "#0000ff"
            red = "#ff0000"
            black = "#111111"
            green = "#008000"

            ax_rad.grid(True, which="major", color="#cbd5e1", linewidth=0.55, alpha=0.75)
            ax_evm.plot(ranges, sim_eff_sinr, color=blue, linestyle="--", linewidth=1.9)
            ax_rad.plot(ranges, sim_sens_on_snr, color=red, linestyle="--", linewidth=1.9)
            if no_si_valid:
                ax_rad.plot(ranges, sim_sens_off_snr, color=green, linestyle="--", linewidth=1.7, zorder=3)

            active_points = self._active_measurements()
            self._evm_radar_plot_cache = {
                "ranges": np.asarray(ranges, dtype=np.float64).copy(),
                "comm_sinr": np.asarray(sim_eff_sinr, dtype=np.float64).copy(),
                "radar_on": np.asarray(sim_sens_on_snr, dtype=np.float64).copy(),
                "radar_off": np.asarray(sim_sens_off_snr, dtype=np.float64).copy(),
                "points": list(active_points),
                "x_min": float(plot_x_min),
                "x_max": float(plot_x_max),
                "comm_thr": float(comm_thr),
                "radar_thr": float(sens_thr),
                "no_si_valid": bool(no_si_valid),
                "on_radar_points": self._c2_power_radar_snr_points("on"),
                "off_radar_points": self._c2_power_radar_snr_points("off"),
            }
            for p in active_points:
                rr = float(p.get("range_m", float("nan")))
                sinr = float(p.get("snr_comm_db", float("nan")))
                if not np.isfinite(sinr):
                    evm = float(p.get("evm_db", float("nan")))
                    sinr = -evm if np.isfinite(evm) else float("nan")
                if np.isfinite(rr) and np.isfinite(sinr):
                    ax_evm.scatter(
                        [rr],
                        [sinr],
                        facecolors="none",
                        edgecolors=blue,
                        marker="o",
                        s=52,
                        linewidths=1.5,
                        zorder=6,
                    )

            for state, color, marker in (
                ("on", red, "s"),
                ("off", green, "^"),
            ):
                pts_snr = self._c2_power_radar_snr_points(state)
                if pts_snr:
                    rr = np.asarray([p[0] for p in pts_snr], dtype=np.float64)
                    ss = np.asarray([p[1] for p in pts_snr], dtype=np.float64)
                    ax_rad.scatter(
                        rr,
                        ss,
                        facecolors=color if state == "on" else "none",
                        edgecolors=color,
                        marker=marker,
                        s=52,
                        linewidths=1.5,
                        zorder=6,
                    )
            ax_rad.set_xlabel("Distance (m)")
            ax_evm.set_ylabel("Comm. SINR (dB)", color=blue)
            ax_rad.set_ylabel("Sensing SINR (dB)", color=red)
            ax_evm.tick_params(axis="y", colors=blue)
            ax_rad.tick_params(axis="y", colors=red)
            for ax in (ax_rad, ax_evm):
                ax.spines["left"].set_color(red)
                ax.spines["right"].set_color(blue)
            ax_evm.set_xlim(plot_x_min, plot_x_max)

            evm_vals = [sim_eff_sinr]
            meas_evm = [
                float(p.get("snr_comm_db", float("nan")))
                if np.isfinite(float(p.get("snr_comm_db", float("nan"))))
                else -float(p.get("evm_db", float("nan")))
                for p in active_points
                if np.isfinite(float(p.get("snr_comm_db", float("nan")))) or np.isfinite(float(p.get("evm_db", float("nan"))))
            ]
            if meas_evm:
                evm_vals.append(np.asarray(meas_evm, dtype=np.float64))
            evm_all = np.concatenate([np.asarray(v, dtype=np.float64).reshape(-1) for v in evm_vals])
            evm_all = evm_all[np.isfinite(evm_all)]
            if len(evm_all):
                ax_evm.set_ylim(float(np.nanmin(evm_all)) - 2.0, float(np.nanmax(evm_all)) + 2.0)

            rad_all = np.concatenate([
                np.asarray(sim_sens_on_snr, dtype=np.float64).reshape(-1),
                np.asarray(sim_sens_off_snr, dtype=np.float64).reshape(-1),
            ])
            rad_pts = [
                y
                for state in ("on", "off")
                for _, y in self._c2_power_radar_snr_points(state)
            ]
            if rad_pts:
                rad_all = np.concatenate([rad_all, np.asarray(rad_pts, dtype=np.float64)])
            rad_all = rad_all[np.isfinite(rad_all)]
            if len(rad_all):
                ax_rad.set_ylim(float(np.nanmin(rad_all)) - 3.0, float(np.nanmax(rad_all)) + 3.0)
            self._apply_evm_radar_limits(ax_evm, ax_rad, plot_x_min, plot_x_max)
            self._add_sinr_threshold_annotations(
                ax_evm,
                ax_rad,
                ranges,
                sim_eff_sinr,
                sim_sens_on_snr,
                comm_thr,
                sens_thr,
                for_save=False,
            )
            self._add_grouped_sinr_legends(ax_evm, ax_rad, no_si_valid, 1.9, False)

            ax_snr.grid(True, alpha=0.30)
            ax_snr.plot(ranges, sim_comm_snr, color=blue, linestyle="--", linewidth=1.5, label="Effective SINR")
            ax_snr.plot(ranges, sim_sens_on_snr, color=red, linestyle="--", linewidth=1.5, label="Sensing with SI")
            if no_si_valid:
                ax_snr.plot(ranges, sim_sens_off_snr, color=green, linestyle="--", linewidth=1.4, label="Sensing without SI")
            ax_snr.axhline(comm_thr, color=blue, linestyle=":", linewidth=0.9, alpha=0.55)
            ax_snr.axhline(sens_thr, color=red, linestyle=":", linewidth=0.9, alpha=0.55)
            ax_snr.set_xlim(plot_x_min, plot_x_max)
            ax_snr.set_xlabel("Distance [m]")
            ax_snr.set_ylabel("SINR [dB]")
            ax_snr.set_title("SINR Detail")
            detail_legend = ax_snr.legend(loc="best", fontsize=9, frameon=True)
            self._style_paper_legend(detail_legend, 9)

            c2_on_pts = self._c2_power_points("on")
            c2_off_pts = self._c2_power_points("off")
            ax_c2pow.grid(True, alpha=0.30)
            ax_c2pow.plot(ranges, sim_c2_on_power, color=red, linestyle="--", linewidth=1.5, label="SI on")
            if no_si_valid:
                ax_c2pow.plot(ranges, sim_c2_off_power, color=green, linestyle="--", linewidth=1.4, label="No SI")
            if c2_on_pts:
                ax_c2pow.scatter(
                    [p[0] for p in c2_on_pts],
                    [p[1] for p in c2_on_pts],
                    facecolors="none",
                    edgecolors=red,
                    marker="s",
                    s=42,
                    linewidths=1.2,
                    zorder=5,
                    label="Meas. SI on",
                )
            if c2_off_pts:
                ax_c2pow.scatter(
                    [p[0] for p in c2_off_pts],
                    [p[1] for p in c2_off_pts],
                    facecolors="none",
                    edgecolors=black,
                    marker="^",
                    s=44,
                    linewidths=1.2,
                    zorder=5,
                    label="Meas. no SI",
                )
            ax_c2pow.set_xlim(plot_x_min, plot_x_max)
            ax_c2pow.set_xlabel("Distance (m)")
            ax_c2pow.set_ylabel("C2 band power (dBm)")
            ax_c2pow.set_title("C2 Band Power")
            power_legend = ax_c2pow.legend(loc="best", fontsize=9, frameon=True)
            self._style_paper_legend(power_legend, 9)

            self._draw_rho_tradeoff_axis(ax_rho, for_save=False)

            for ax_i in (ax_evm, ax_rad, ax_snr, ax_c2pow, ax_rho):
                self._style_ieee_axis(ax_i)
            for ax_i in (ax_evm, ax_rad):
                ax_i.spines["left"].set_color(red)
                ax_i.spines["right"].set_color(blue)

            self.fig.tight_layout()
            self.canvas.draw_idle()
            rc, rs_on, rs_off, rj_on, rj_off = self._rmax_from_ref(np.asarray([rho]))
            n_evm_meas = sum(
                1 for p in active_points
                if np.isfinite(float(p.get("range_m", float("nan"))))
                and np.isfinite(float(p.get("evm_db", float("nan"))))
            )
            n_radar_meas = sum(
                1 for p in active_points
                if np.isfinite(float(p.get("range_m", float("nan"))))
                and np.isfinite(float(p.get("snr_sens_db", float("nan"))))
            )
            c2_slope, _ = self._fit_c2_power_slope("on")
            c2_slope_txt = f"{c2_slope:.1f} dB/dec" if np.isfinite(c2_slope) else "N/A"
            self.status_var.set(
                f"rho={rho:.3f}  R_max^comm={rc[0]:.3g} m  "
                f"R_max^sens(on/off)={rs_on[0]:.3g}/{rs_off[0]:.3g} m  "
                f"R_max(ISAC,on/off)={rj_on[0]:.3g}/{rj_off[0]:.3g} m  "
                f"comm_ref={self._float('sim_comm_ref_snr_db', 17.49):.2f} dB  "
                f"sens_ref={sens_ref:.2f} dB = C2P {self._c2_power_ref_dbm():.1f} - N {self._c2_noise_power_dbm():.1f} + PG {self._radar_proc_gain_db():.1f}  "
                f"iso on/off={self._float('si_on_iso_db', 24.0):.0f}/{self._float('si_off_iso_db', 1000.0):.0f} dB  "
                f"TX={self._finite_param('sweep_tx_power_dbm'):.1f} dBm  "
                f"meas EVM/sensing/C2on/off={n_evm_meas}/{n_radar_meas}/{len(self._c2_power_points('on'))}/{len(self._c2_power_points('off'))}  "
                f"C2 SI-on slope={c2_slope_txt}"
            )
        except Exception as exc:
            self.status_var.set(f"Error: {exc}")
            messagebox.showerror("System Model Validation", str(exc), parent=self.parent)

def main() -> None:
    root = tk.Tk()
    UnifiedApp(root)
    root.mainloop()

class UnifiedApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ISAC Unified GUI (TX + DSO + Simulation)")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        window_w = max(1200, min(1900, screen_w - 40))
        window_h = max(760, min(1050, screen_h - 80))
        self.root.geometry(f"{window_w}x{window_h}")
        self.root.minsize(min(1500, window_w), min(850, window_h))
        apply_unified_style(self.root)

        self.runtime: dict = {}
        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        tab_tx_sim = ttk.Frame(notebook)
        tab_dso = ttk.Frame(notebook)
        tab_model = ttk.Frame(notebook)
        notebook.add(tab_tx_sim, text="TX Design & Simulation")
        notebook.add(tab_dso, text="DSO Live Capture")
        notebook.add(tab_model, text="System Model Validation")

        tx_sim_paned = ttk.PanedWindow(tab_tx_sim, orient=tk.HORIZONTAL)
        tx_sim_paned.pack(fill=tk.BOTH, expand=True)

        # Single sidebar on the left for all controls
        controls_left = ttk.Frame(tx_sim_paned)
        # Main area on the right for all plots
        plots_right = ttk.Frame(tx_sim_paned)

        tx_sim_paned.add(controls_left, weight=1)
        tx_sim_paned.add(plots_right, weight=9)

        awg_control_frame = ttk.Frame(controls_left)
        awg_control_frame.pack(fill=tk.X)

        sim_control_frame = ttk.Frame(controls_left)
        sim_control_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.tx_sim_panel = IsacTxSimPanel(awg_control_frame, runtime=self.runtime, on_tx_generated=self._on_reference_npz_ready)
        self.photonic_sim_panel = PhotonicIsacSimPanel(
            parent=sim_control_frame,
            plot_parent=plots_right,
            awg_source=self.tx_sim_panel,
            show_awg_params=False,
        )
        self.dso_panel = DsoPanel(tab_dso, runtime=self.runtime)
        self.system_model_panel = SystemModelValidationPanel(
            tab_model,
            runtime=self.runtime,
            tx_source=self.tx_sim_panel,
            photonic_source=self.photonic_sim_panel,
        )
        self._install_awg_dso_sync_traces()

    def _sync_dso_from_awg_panel(self, source: str = "AWG panel") -> None:
        try:
            if not hasattr(self, "dso_panel"):
                return
            if not bool(self.dso_panel.auto_sync_tx_params_var.get()):
                self.dso_panel._log(f"[App] IF/symbol/mod sync from {source} is OFF.")
                return
            self.dso_panel.fc_var.set(self.tx_sim_panel.if_var.get())
            self.dso_panel.sr_var.set(self.tx_sim_panel.symbol_rate_var.get())
            self.dso_panel.demod_mod_var.set(self.tx_sim_panel.modulation_var.get())
            if hasattr(self.tx_sim_panel, "rrc_beta_var"):
                self.dso_panel.demod_beta_var.set(self.tx_sim_panel.rrc_beta_var.get())
            self.dso_panel._update_band_label()
            if getattr(self.dso_panel, "_rx_sig", None) is not None:
                self.dso_panel._plot_spectrum_and_time()
            self.dso_panel._log(f"[App] IF, symbol rate, modulation, and roll-off synced from {source}.")
        except Exception as e:
            if hasattr(self, "dso_panel"):
                self.dso_panel._log(f"[App] Sync error: {e}")

    def _install_awg_dso_sync_traces(self) -> None:
        try:
            vars_to_sync = [
                self.tx_sim_panel.if_var,
                self.tx_sim_panel.symbol_rate_var,
                self.tx_sim_panel.modulation_var,
            ]
            if hasattr(self.tx_sim_panel, "rrc_beta_var"):
                vars_to_sync.append(self.tx_sim_panel.rrc_beta_var)
            for var in vars_to_sync:
                var.trace_add("write", lambda *_: self._sync_dso_from_awg_panel("AWG panel"))
            self._sync_dso_from_awg_panel("AWG panel")
        except Exception as e:
            self.dso_panel._log(f"[App] Could not install AWG/DSO sync traces: {e}")

    def _on_reference_npz_ready(self, file_path: str) -> None:
        if hasattr(self, "dso_panel"):
            self.dso_panel._log(f"[App] Internal TX Reference Updated: {file_path}")
        try:
            self._sync_dso_from_awg_panel("AWG TX reference")
        except Exception as e:
            if hasattr(self, "dso_panel"):
                self.dso_panel._log(f"[App] Sync error: {e}")

if __name__ == "__main__":
    main()
