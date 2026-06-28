#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
from scipy.signal import welch, hilbert, fftconvolve

import queue
import threading
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from functions.awg_functions import download_to_awg, parse_channels, run_awg, test_awg_connection
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
                outer = ttk.Frame(self.parent)
                outer.pack(fill=tk.BOTH, expand=True)

                frm = ttk.Frame(outer, padding=12)
                frm.pack(fill=tk.BOTH, expand=True)

                self._updating_power = False
                self._updating_vpp = False
                current_row = 0

                # ==========================================================
                # SECTION 1: Hardware & Channel Setup
                # ==========================================================
                ttk.Label(frm, text="1. Hardware & Channel Setup", style="Title.TLabel").grid(row=current_row, column=0, columnspan=6, sticky="w", pady=(0, 4))
                current_row += 1

                hw_grp = ttk.LabelFrame(frm, text="AWG & Output Parameters", padding=10)
                hw_grp.grid(row=current_row, column=0, columnspan=6, sticky="we", pady=(0, 12))
                hw_grp.columnconfigure(1, weight=1)
                hw_grp.columnconfigure(3, weight=1)
                hw_grp.columnconfigure(5, weight=1)

                self.mode_var = tk.StringVar(value="Real IF")
                ttk.Label(hw_grp, text="Signal Type").grid(row=0, column=0, sticky="w")
                mode_box = ttk.Combobox(hw_grp, textvariable=self.mode_var, values=["IQ", "Real IF"], state="readonly", width=12)
                mode_box.grid(row=0, column=1, sticky="w")
                mode_box.bind("<<ComboboxSelected>>", lambda _: self._on_mode_changed())

                self.ch_var = tk.StringVar(value="1")
                self.ch_combo = ttk.Combobox(hw_grp, textvariable=self.ch_var, state="readonly", width=10)
                ttk.Label(hw_grp, text="AWG Channel(s)").grid(row=0, column=2, sticky="w", padx=(16, 0))
                self.ch_combo.grid(row=0, column=3, sticky="w")

                self.vpp_var = tk.StringVar(value="0.1")
                ttk.Label(hw_grp, text="Amplitude (Vpp)").grid(row=0, column=4, sticky="w", padx=(16, 0))
                ttk.Entry(hw_grp, textvariable=self.vpp_var, width=10).grid(row=0, column=5, sticky="w")

                self.fs_var = tk.StringVar(value="120")
                ttk.Label(hw_grp, text="AWG Sample Rate (GHz)").grid(row=1, column=0, sticky="w", pady=(8, 0))
                ttk.Entry(hw_grp, textvariable=self.fs_var, width=12).grid(row=1, column=1, sticky="w", pady=(8, 0))

                self.ip_var = tk.StringVar(value="192.168.1.2")
                ttk.Label(hw_grp, text="AWG IP/Host").grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
                ttk.Entry(hw_grp, textvariable=self.ip_var, width=16).grid(row=1, column=3, sticky="w", pady=(8, 0))

                self.port_var = tk.StringVar(value="60007")
                ttk.Label(hw_grp, text="Port").grid(row=1, column=4, sticky="w", padx=(16, 0), pady=(8, 0))
                ttk.Entry(hw_grp, textvariable=self.port_var, width=10).grid(row=1, column=5, sticky="w", pady=(8, 0))

                self.power_dbm_var = tk.StringVar(value="")
                ttk.Label(hw_grp, text="TX Power (dBm)").grid(row=2, column=0, sticky="w", pady=(8, 0))
                ttk.Entry(hw_grp, textvariable=self.power_dbm_var, width=12).grid(row=2, column=1, sticky="w", pady=(8, 0))
                ttk.Label(hw_grp, text="(입력 시 Vpp 자동 계산, 50Ω 기준)", style="Muted.TLabel").grid(row=2, column=2, columnspan=4, sticky="w", padx=(16, 0), pady=(8, 0))

                pass  # Buttons consolidated in PhotonicIsacSimPanel global controls

                current_row += 1

                # ==========================================================
                # SECTION 2: Signal Design
                # ==========================================================
                ttk.Label(frm, text="2. Signal Properties (ISAC)", style="Title.TLabel").grid(row=current_row, column=0, columnspan=6, sticky="w", pady=(0, 4))
                current_row += 1

                sig_grp = ttk.LabelFrame(frm, text="Modulation & Waveform Parameters", padding=10)
                sig_grp.grid(row=current_row, column=0, columnspan=6, sticky="we", pady=(0, 12))
                sig_grp.columnconfigure(1, weight=1); sig_grp.columnconfigure(3, weight=1); sig_grp.columnconfigure(5, weight=1)

                self.modulation_var = tk.StringVar(value="16QAM")
                ttk.Label(sig_grp, text="Modulation").grid(row=0, column=0, sticky="w")
                ttk.Combobox(sig_grp, textvariable=self.modulation_var, values=["QPSK", "16QAM"], state="readonly", width=12).grid(row=0, column=1, sticky="w")

                self.symbol_rate_var = tk.StringVar(value="1.0")
                ttk.Label(sig_grp, text="Symbol Rate (GHz)").grid(row=0, column=2, sticky="w", padx=(16, 0))
                ttk.Entry(sig_grp, textvariable=self.symbol_rate_var, width=12).grid(row=0, column=3, sticky="w")

                self.if_var = tk.StringVar(value="10")
                ttk.Label(sig_grp, text="IF Frequency (GHz)").grid(row=0, column=4, sticky="w", padx=(16, 0))
                self.if_entry = ttk.Entry(sig_grp, textvariable=self.if_var, width=12)
                self.if_entry.grid(row=0, column=5, sticky="w")

                self.prbs_n_var = tk.StringVar(value="11")
                ttk.Label(sig_grp, text="PRBS N (Length)").grid(row=1, column=0, sticky="w", pady=(8, 0))
                ttk.Entry(sig_grp, textvariable=self.prbs_n_var, width=12).grid(row=1, column=1, sticky="w", pady=(8, 0))

                self.chirp_len_var = tk.StringVar(value="256")
                ttk.Label(sig_grp, text="Symbols per Chirp").grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
                ttk.Entry(sig_grp, textvariable=self.chirp_len_var, width=12).grid(row=1, column=3, sticky="w", pady=(8, 0))

                self.rf_var = tk.StringVar(value="270")
                ttk.Label(sig_grp, text="RF Freq (GHz)").grid(row=1, column=4, sticky="w", padx=(16, 0), pady=(8, 0))
                ttk.Entry(sig_grp, textvariable=self.rf_var, width=12).grid(row=1, column=5, sticky="w", pady=(8, 0))

                self.waveform_var = tk.StringVar(value="LFM-QAM")
                ttk.Label(sig_grp, text="Waveform").grid(row=2, column=0, sticky="w", pady=(8, 0))
                ttk.Combobox(sig_grp, textvariable=self.waveform_var, values=["LFM-QAM", "QAM", "FMCW"], state="readonly", width=12).grid(row=2, column=1, sticky="w", pady=(8, 0))

                self.mem_warn_var = tk.StringVar(value="Memory: -- kSa")
                ttk.Label(sig_grp, textvariable=self.mem_warn_var, style="Muted.TLabel").grid(row=2, column=2, columnspan=2, sticky="w", pady=(8, 0), padx=(16, 0))

                self.osr_var = tk.StringVar(value="OSR: --")
                ttk.Label(sig_grp, textvariable=self.osr_var, style="Muted.TLabel").grid(row=2, column=4, columnspan=2, sticky="w", padx=(16, 0), pady=(8, 0))

                current_row += 1

                frm.columnconfigure(1, weight=1); frm.columnconfigure(3, weight=1); frm.columnconfigure(5, weight=1)

                for var in [self.prbs_n_var, self.fs_var, self.symbol_rate_var, self.chirp_len_var, self.modulation_var, self.waveform_var, self.if_var]:
                    var.trace_add("write", lambda *_: [self._check_memory_limit(), self._on_generate()])

                self.power_dbm_var.trace_add("write", self._on_power_changed)
                self.vpp_var.trace_add("write", self._on_vpp_changed)

                self._on_mode_changed()
                self._check_memory_limit()

        def _check_memory_limit(self) -> bool:
            try:
                n = int(_parse_float_input(self.prbs_n_var.get(), "PRBS N"))
                fs = _parse_ghz_input(self.fs_var.get(), "AWG Fs")
                sym_rate = _parse_ghz_input(self.symbol_rate_var.get(), "Symbol Rate")
                bps = _bits_per_symbol(self.modulation_var.get())
                n_sym_per_chirp = max(8, int(_parse_float_input(self.chirp_len_var.get(), "Symbols per Chirp")))
                min_chirps = 4
                raw_symbols = max(1, (2 ** n - 1) // bps)
                num_symbols = max(raw_symbols, min_chirps * n_sym_per_chirp)
            
                pts_per_sym = fs / sym_rate
                total_pts = int(num_symbols * pts_per_sym)
                total_ksa = total_pts / 1e3
                osr = fs / sym_rate
                self.osr_var.set(f"OSR: {osr:.3f} Sa/sym")
            
                if total_pts > 512_000:
                    self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa 🚨 (> 512 kSa)")
                    return False
                elif total_pts > 450_000:
                    self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa ⚠️ (near limit)")
                    return True
                else:
                    self.mem_warn_var.set(f"Memory: {total_ksa:.1f} kSa ✔️")
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
                choices = ["1", "2", "3", "4"]
                self.ch_combo.configure(values=choices)
                if self.ch_var.get() not in choices: self.ch_var.set("2")
                self.if_entry.configure(state="normal")

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
                raise MemoryError("Signal size exceeds 512 kSa limit.")

            mod = self.modulation_var.get().strip().upper()
            waveform_type = self.waveform_var.get().strip()
            prbs = int(_parse_float_input(self.prbs_n_var.get(), "PRBS N"))
            fs_awg = _parse_ghz_input(self.fs_var.get(), "AWG Fs")
            if fs_awg <= 0:
                raise ValueError("AWG Sample Rate must be positive and non-zero.")
            sym_rate = _parse_ghz_input(self.symbol_rate_var.get(), "Symbol Rate")
            if sym_rate <= 0:
                raise ValueError("Symbol Rate must be positive and non-zero.")
            if_hz = _parse_ghz_input(self.if_var.get(), "IF Freq") if self.mode_var.get() == "Real IF" else 0.0
            n_sym_per_chirp = max(8, int(_parse_float_input(self.chirp_len_var.get(), "Symbols per Chirp")))

            ts = 1.0 / sym_rate
            n_per_sym = max(8, int(round(fs_awg * ts)))
            ts_actual = n_per_sym / fs_awg
        
            bits = _prbs_bits_lfsr(prbs, (2 ** prbs) - 1)
            bps = _bits_per_symbol(mod)
            bits = bits[:max(bps, (len(bits) // bps) * bps)]
            qam_all = _bits_to_qam_symbols(bits, modulation=mod)

            min_chirps = 4
            min_syms_required = min_chirps * n_sym_per_chirp
            if len(qam_all) < min_syms_required:
                rep = int(np.ceil(min_syms_required / max(len(qam_all), 1)))
                qam_all = np.tile(qam_all, rep)

            n_chirps = max(1, len(qam_all) // n_sym_per_chirp)
            qam_symbols = qam_all[: n_chirps * n_sym_per_chirp]
            tx_sym_matrix = qam_symbols.reshape(n_chirps, n_sym_per_chirp)

            Tc = n_sym_per_chirp * ts_actual
            t_fast = np.arange(n_sym_per_chirp * n_per_sym, dtype=np.float64) / fs_awg - Tc / 2.0
            lfm_chirp = np.exp(1j * np.pi * (sym_rate / Tc) * t_fast ** 2)

            qam_preamble_len = 0
            qam_preamble_symbols = np.zeros(0, dtype=np.complex128)
            qam_rrc_beta = 0.25
            qam_rrc_span = 8
            qam_rrc_taps = np.array([1.0], dtype=np.float64)

            if waveform_type == "QAM":
                qam_preamble_len = min(64, max(16, n_sym_per_chirp // 8))
                data_len = n_sym_per_chirp - qam_preamble_len
                if data_len <= 0:
                    raise ValueError("Symbols per Chirp must be larger than preamble length for QAM mode")

                pn_bits = _prbs_bits_lfsr(9, qam_preamble_len)
                qam_preamble_symbols = (2.0 * pn_bits.astype(np.float64) - 1.0).astype(np.complex128)
                qam_preamble_symbols *= np.exp(1j * np.pi / 4.0)

                data_needed = n_chirps * data_len
                if len(qam_all) < data_needed:
                    rep = int(np.ceil(data_needed / max(len(qam_all), 1)))
                    qam_all = np.tile(qam_all, rep)
                qam_data = qam_all[:data_needed].reshape(n_chirps, data_len)
                tx_sym_matrix = np.concatenate([np.tile(qam_preamble_symbols, (n_chirps, 1)), qam_data], axis=1)
                qam_symbols = tx_sym_matrix.reshape(-1)

                base_chirp = np.ones_like(lfm_chirp, dtype=np.complex128)
                qam_rrc_taps = self._rrc_taps(n_per_sym, beta=qam_rrc_beta, span=qam_rrc_span)
                tx_bb_matrix = np.zeros((n_chirps, n_sym_per_chirp * n_per_sym), dtype=np.complex128)
                for i in range(n_chirps):
                    up = np.zeros(n_sym_per_chirp * n_per_sym, dtype=np.complex128)
                    up[::n_per_sym] = tx_sym_matrix[i]
                    tx_bb_matrix[i] = self._apply_fir_same(up, qam_rrc_taps)
            elif waveform_type == "FMCW":
                base_chirp = lfm_chirp
                tx_sym_matrix = np.ones((n_chirps, n_sym_per_chirp), dtype=np.complex128)
                qam_symbols = tx_sym_matrix.reshape(-1)
                tx_bb_matrix = np.repeat(tx_sym_matrix, n_per_sym, axis=1) * base_chirp[np.newaxis, :]
            else:
                base_chirp = lfm_chirp
                
                zc_len = 63
                zc_seq = generate_zadoff_chu(zc_len, u=25)
                
                pilot_len = 200
                pn_bits = _prbs_bits_lfsr(9, pilot_len)
                pilot_syms = (2.0 * pn_bits.astype(np.float64) - 1.0).astype(np.complex128)
                pilot_syms *= np.exp(1j * np.pi / 4.0)
                
                header = np.concatenate([zc_seq, pilot_syms])
                header_len = len(header)
                
                data_len = n_sym_per_chirp - header_len
                if data_len <= 0:
                    raise ValueError(f"Symbols per Chirp ({n_sym_per_chirp}) must be > {header_len} for ZC+Pilot header")
                
                data_needed = n_chirps * data_len
                if len(qam_all) < data_needed:
                    rep = int(np.ceil(data_needed / max(len(qam_all), 1)))
                    qam_all = np.tile(qam_all, rep)
                qam_data = qam_all[:data_needed].reshape(n_chirps, data_len)
                
                tx_sym_matrix = np.concatenate([np.tile(header, (n_chirps, 1)), qam_data], axis=1)
                qam_symbols = tx_sym_matrix.reshape(-1)
                
                qam_rrc_beta = 0.25
                qam_rrc_span = 8
                qam_rrc_taps = self._rrc_taps(n_per_sym, beta=qam_rrc_beta, span=qam_rrc_span)
                
                # LFM-QAM bypasses RRC (uses rectangular pulses) as requested
                tx_bb_matrix = np.repeat(tx_sym_matrix, n_per_sym, axis=1) * base_chirp[np.newaxis, :]

            tx_baseband = tx_bb_matrix.reshape(-1)

            if self.mode_var.get() == "IQ":
                awg_sig = normalize_iq_for_awg(tx_baseband)
            else:
                t = np.arange(len(tx_baseband), dtype=np.float64) / fs_awg
                real_if = np.real(tx_baseband * np.exp(1j * 2.0 * np.pi * if_hz * t))
                awg_sig = normalize_real_for_awg(real_if)

            payload = {
                "tx_signal": tx_baseband, 
                "awg_sig": awg_sig,
                "fs": fs_awg,
                "qam_symbols": qam_symbols,
                "tx_sym_matrix": tx_sym_matrix,
                "tx_bb_matrix": tx_bb_matrix,
                "base_chirp": base_chirp,
                "symbol_rate": sym_rate,
                "if_freq": if_hz,
                "modulation": mod,
                "waveform_type": waveform_type,
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
                "n_chirps": n_chirps,
                "n_sym_per_chirp": n_sym_per_chirp,
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
            except Exception:
                return True

            if str(ctx.get("waveform_type", "LFM-QAM")).strip() != cur_wave:
                return True
            if str(ctx.get("modulation", "16QAM")).strip().upper() != cur_mod:
                return True
            if str(ctx.get("mode", "Real IF")).strip() != cur_mode:
                return True
            if int(ctx.get("n_sym_per_chirp", -1)) != cur_nsym:
                return True
            if int(ctx.get("sps", -1)) <= 0:
                return True

            fs_old = float(ctx.get("fs", -1.0))
            sr_old = float(ctx.get("symbol_rate", -1.0))
            if_old = float(ctx.get("if_freq", 0.0))
            if abs(fs_old - cur_fs) > 1e-6 * max(cur_fs, 1.0):
                return True
            if abs(sr_old - cur_sr) > 1e-6 * max(cur_sr, 1.0):
                return True
            if abs(if_old - cur_if) > 1e-6 * max(abs(cur_if), 1.0):
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
                    self.parent.after(0, lambda n=n_samples: messagebox.showinfo("Success", f"Signal Generated in Memory.\nSamples: {n:,}"))
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
                    download_to_awg(
                        awg_sig=np.asarray(pl["awg_sig"]),
                        channels=channels_list if channels_list else [1],
                        awg_addr=addr,
                        fs=float(pl["fs"]),
                        vpp=float(self.vpp_var.get()),
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
                    vpp = float(self.vpp_var.get())
                    addr = f"TCPIP0::{self.ip_var.get().strip()}::{int(self.port_var.get())}::SOCKET"
                    channels_list = parse_channels(self.ch_var.get())
                    run_awg(awg_addr=addr, channels=channels_list if channels_list else [1], vpp=vpp)
                    self.parent.after(0, lambda v=vpp: messagebox.showinfo("AWG Run", f"AWG 출력 시작.\nVpp = {v:.4f} V"))
                except Exception as e:
                    self.parent.after(0, lambda m=str(e): messagebox.showerror("AWG Run Error", m))
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
            elif m == "16QAM":
                base = 17.0
            else:
                base = 17.0
            return float(base + max(0.0, impl_margin_db))

        @staticmethod
        def _rrc_taps(sps: int, beta: float = 0.25, span: int = 8) -> np.ndarray:
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

        @classmethod
        def _gardner_timing_recovery(
            cls,
            samples: np.ndarray,
            sps: int,
            n_symbols: int,
            gain: float = 0.01,
        ) -> np.ndarray:
            x = np.asarray(samples, dtype=np.complex128).reshape(-1)
            if len(x) < 4 * max(2, sps):
                return np.zeros(0, dtype=np.complex128)

            sps_f = float(max(2, sps))
            omega = sps_f
            mu = 0.0
            t = 2.0 * sps_f
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
            sigma = _parse_float_input(self.rcs_var.get(), "Radar RCS sigma")
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
                # 🎯 믹싱 손실 복구를 위해 x2.0 적용 (수학적 보존)
                rx_mixed = rx_raw_scope * np.exp(-1j * 2.0 * np.pi * f_if * t) * 2.0
                # 🎯 LPF 차단주파수를 대역폭(1.2 * rs)에 정확하게 맞춰 하모닉/광대역 노이즈 완전히 제거
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
                        rx_bb_sync = self._lowpass_complex_fft(rx_bb_sync, fs=fs_sim, cutoff_hz=1.2 * meta["B"])
                    else:
                        rx_bb_sync = np.asarray(rx_signal_sim, dtype=np.complex128)

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

                    # Radar path: keep raw timing (no frame shift) to preserve absolute delay information.
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
                        else:
                            dechirped_mat = rx_sync_mat * np.conj(np.asarray(meta["base_chirp"], dtype=np.complex128))[np.newaxis, :]
                            timing_gain_used = float("nan")
                            # Fractional delay leaves a residual symbol phase offset. Search best sampling phase.
                            best_nmse = np.inf
                            qam_est_mat = np.mean(dechirped_mat.reshape(n_chirps, n_sym_per_chirp, nps), axis=2)
                            for phase in range(max(1, nps)):
                                cand = dechirped_mat[:, phase::nps]
                                if cand.shape[1] < n_sym_per_chirp:
                                    continue
                                cand = cand[:, :n_sym_per_chirp]
                                den_c = np.sum(np.abs(tx_sym_matrix) ** 2) + 1e-15
                                h_c = np.sum(cand * np.conj(tx_sym_matrix)) / den_c
                                cand_eq = cand / (h_c + 1e-15)
                                nmse = np.mean(np.abs(cand_eq - tx_sym_matrix) ** 2) / (np.mean(np.abs(tx_sym_matrix) ** 2) + 1e-15)
                                if nmse < best_nmse:
                                    best_nmse = float(nmse)
                                    qam_est_mat = cand

                            qam_est = qam_est_mat.reshape(-1)
                            qam_ref = tx_sym_matrix.reshape(-1)

                        # Remove linear phase drift across symbols (beat/CFO residue after de-chirp).
                        if len(qam_est) > 4 and len(qam_ref) == len(qam_est):
                            ph = np.unwrap(np.angle(qam_est * np.conj(qam_ref) + 1e-15))
                            k = np.arange(len(ph), dtype=np.float64)
                            slope, intercept = np.polyfit(k, ph, deg=1)
                            qam_est = qam_est * np.exp(-1j * (slope * k + intercept))

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

    linewidth_mhz: float = 0.1
    baud_gbaud: float = 10.0
    if_ghz: float = 10.0
    rf_carrier_ghz: float = 270.0
    waveform: str = "16QAM"
    chirp_bw_ghz: float = 2.0
    
    coherence_mode: str = "Free-running"
    rx_mode: str = "Mixer"
    si_enable: bool = True
    carrier_wander_enable: bool = True
    carrier_wander_mhz: float = 300.0
    sc_fde_enable: bool = True
    sc_fde_taps: int = 21
    
    # 💡 하드웨어 및 레이더 물리 파라미터 
    utcpd_target_dbm: float = -25.0
    pa_gain_db: float = 24.0
    pa_p1db_dbm: float = -1.0
    lna_gain_db: float = 14.0
    lna_nf_db: float = 8.0
    zbd_responsivity_vpw: float = 2200.0
    zbd_nep_pw_sqrt_hz: float = 12.0
    if_amp_gain_db: float = 20.0
    if_amp_nf_db: float = 5.0
    omt_iso_db: float = 25.0
    ant_gain_dbi: float = 25.0
    target_rcs_sqm: float = 1.0
    target_dist_m: float = 1.0  # Default 1m

    # 내부 계산 변수
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
    f, p = welch(sig, fs, nperseg=min(2048, len(sig)), return_onesided=False)
    p_v2hz = np.fft.fftshift(p)
    p_w_hz = p_v2hz / 50.0
    p_dbm_hz = 10 * np.log10(p_w_hz * 1e3 + 1e-30)
    return np.fft.fftshift(f), p_dbm_hz

def calc_power_dbm(sig, R=50.0):
    """Time-domain RMS Power 계산 (into 50 ohms)"""
    p_w = np.mean(np.abs(sig)**2) / R
    return 10 * np.log10(p_w + 1e-20) + 30.0

def qam16_hard_demod(symbols):
    const = np.array([-3-3j, -3-1j, -3+1j, -3+3j, -1-3j, -1-1j, -1+1j, -1+3j, 1-3j, 1-1j, 1+1j, 1+3j, 3-3j, 3-1j, 3+1j, 3+3j]) / np.sqrt(10.0)
    return np.argmin(np.abs(symbols[:, None] - const[None, :]), axis=1)


def estimate_measured_evm_percent(evm_db):
    if np.isfinite(evm_db):
        return 100.0 * (10.0 ** (evm_db / 20.0))
    return np.nan

def run_isac_sim(cfg: SimConfig):
    fs = cfg.fs_gsps * 1e9
    frame_len, num_frames = int(cfg.frame_len), int(cfg.num_frames)
    step = max(int(fs * cfg.step_ns * 1e-9), 1)
    total_samples = frame_len + step * num_frames
    t = np.arange(total_samples) / fs

    baud_rate, f_if = cfg.baud_gbaud * 1e9, cfg.if_ghz * 1e9
    samples_per_sym = max(int(fs / baud_rate), 1)

    # 1. Baseband & IF Upconversion (Real)
    qam16_syms = np.array([-3-3j, -3-1j, -3+1j, -3+3j, -1-3j, -1-1j, -1+1j, -1+3j, 1-3j, 1-1j, 1+1j, 1+3j, 3-3j, 3-1j, 3+1j, 3+3j]) / np.sqrt(10.0)
    
    if cfg.waveform == "OFDM-16QAM":
        N_fft_ofdm = 2048
        N_cp = 256
        N_sym_total = N_fft_ofdm + N_cp
        num_ofdm_syms = total_samples // N_sym_total + 2
        active_sc = int((cfg.baud_gbaud * 1e9) / (fs / N_fft_ofdm))
        
        ofdm_bb = np.zeros(num_ofdm_syms * N_sym_total, dtype=complex)
        tx_ofdm_syms = []
        sym_idx_list = []
        
        for i in range(num_ofdm_syms):
            idx = np.random.randint(0, 16, active_sc)
            syms = qam16_syms[idx]
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
    else:
        sym_idx = np.random.randint(0, 16, int(total_samples / samples_per_sym) + 1)
        symbols = qam16_syms[sym_idx]
        upsampled = np.zeros(len(symbols) * samples_per_sym, dtype=complex)
        upsampled[::samples_per_sym] = symbols
        
        h_rrc = rrc_filter(200, 0.1, 1/baud_rate, fs)
        bb_sig = np.convolve(upsampled, h_rrc, mode="same")[:total_samples]
        
        if cfg.waveform == "LFM-16QAM":
            sweep_bw = max(cfg.chirp_bw_ghz, 0.01) * 1e9
            t0 = t - np.mean(t)
            k = sweep_bw / max(t[-1] - t[0], 1.0 / fs)
            chirp = np.exp(1j * np.pi * k * (t0 ** 2))
            bb_sig = bb_sig * chirp
        else:
            chirp = np.ones_like(t)

    x_if_cplx = bb_sig * np.exp(1j * 2 * np.pi * f_if * t)
    x_if_real = np.real(x_if_cplx)

    # MZM intensity modulation uses real IF drive -> optical DSB in both Mixer and ZBD modes.
    m = x_if_real / (np.max(np.abs(x_if_real)) + 1e-12)
    e_mod = 1.0 + 0.5 * m

    # 2. 광학적 결합 및 위상 잡음
    lw = cfg.linewidth_mhz * 1e6
    phi_1 = generate_phase_noise(total_samples, lw, fs)
    phi_2 = generate_phase_noise(total_samples, lw, fs)
    if cfg.coherence_mode == "Self-coherent": phi_2 = phi_1
    
    wander = np.cumsum(np.random.randn(total_samples))
    wander = (wander - np.mean(wander)) / (np.std(wander) + 1e-12) * (cfg.carrier_wander_mhz * 1e6 if cfg.carrier_wander_enable else 0)
    phi_wander = 2 * np.pi * np.cumsum(wander) / fs

    e_data = e_mod * np.exp(1j * phi_1)
    e_lo = 1.0 * np.exp(1j * (phi_2 + phi_wander))
    
    # 3. UTC-PD 비팅 & 전력 스케일링
    beat_raw = e_data * np.conj(e_lo)
    beat_pwr_w = np.mean(np.abs(beat_raw)**2) / 50.0
    target_w = 10**((cfg.utcpd_target_dbm - 30) / 10)
    beat_tx = beat_raw * np.sqrt(target_w / beat_pwr_w)
    
    # 4. THz PA 증폭 + P1dB 제한
    pa_gain_lin = 10**(cfg.pa_gain_db / 20.0)
    v_pa_out = beat_tx * pa_gain_lin
    p_pa_dbm = calc_power_dbm(v_pa_out)
    if p_pa_dbm > cfg.pa_p1db_dbm:
        v_pa_out *= 10 ** ((cfg.pa_p1db_dbm - p_pa_dbm) / 20.0)
    
    # 5. OMT Isolation 및 Radar Path Loss
    alpha_si = 10**(-cfg.omt_iso_db / 20.0)
    beta_echo = 10**(-cfg.path_loss_db / 20.0)
    delay_samp = int(cfg.delay_ns * 1e-9 * fs)
    
    v_si = v_pa_out * alpha_si if cfg.si_enable else np.zeros_like(v_pa_out)
    v_echo = np.zeros_like(v_pa_out)
    # [수정] RF 반송파에 의한 초고주파 위상 지연(Carrier Phase Shift) 현상 물리적 반영
    omega_c_tau = 2.0 * np.pi * (cfg.rf_carrier_ghz * 1e9) * (cfg.delay_ns * 1e-9)
    if delay_samp > 0: 
        v_echo[delay_samp:] = v_pa_out[:-delay_samp] * beta_echo * np.exp(-1j * omega_c_tau)
    else: 
        v_echo = v_pa_out * beta_echo * np.exp(-1j * omega_c_tau)
    
    # LNA 모델: gain + NF 기반 등가 열잡음
    v_lna_in = v_si + v_echo
    lna_gain_lin = 10 ** (cfg.lna_gain_db / 20.0)
    v_lna_sig = v_lna_in * lna_gain_lin
    n_in_dbm = -174.0 + 10 * np.log10(fs) + cfg.lna_nf_db
    n_out_w = 10 ** ((n_in_dbm + cfg.lna_gain_db - 30.0) / 10.0)
    n_out_vrms2 = n_out_w * 50.0
    awgn_lna = np.sqrt(n_out_vrms2 / 2.0) * (np.random.randn(total_samples) + 1j * np.random.randn(total_samples))
    v_rx_in = v_lna_sig + awgn_lna
    
    # 6. 수신 검파
    if cfg.rx_mode == "ZBD":
        p_inst_w = (np.abs(v_rx_in) ** 2) / 50.0
        v_det = cfg.zbd_responsivity_vpw * p_inst_w
        nep_w_sqrt_hz = cfg.zbd_nep_pw_sqrt_hz * 1e-12
        v_nep_rms = cfg.zbd_responsivity_vpw * nep_w_sqrt_hz * np.sqrt(fs / 2.0)
        v_det += np.random.normal(0.0, v_nep_rms, total_samples)
        v_rec = v_det - np.mean(v_det)
    else:
        v_mix_in = v_rx_in - v_si * lna_gain_lin
        v_rec = np.real(v_mix_in)

    # 6-2. IF Amp (Broadband: ~30kHz to 30GHz)
    N_f = len(v_rec)
    f_axis = np.fft.fftfreq(N_f, 1/fs)
    
    # 앰프 대역폭 (30 kHz ~ 30 GHz) 적용
    amp_mask = (np.abs(f_axis) > 30e3) & (np.abs(f_axis) < 30e9)
    v_rec_filt = np.real(np.fft.ifft(np.fft.fft(v_rec) * amp_mask))
    
    # IF Amp 증폭 및 잡음 추가
    if_gain_lin = 10**(cfg.if_amp_gain_db / 20.0)
    v_rec_amp = v_rec_filt * if_gain_lin
    n_if_w = 10**((-174.0 + 10*np.log10(fs) + cfg.if_amp_nf_db + cfg.if_amp_gain_db - 30.0) / 10.0)
    v_dso_in = v_rec_amp + np.sqrt(n_if_w * 50.0 / 2.0) * np.random.randn(N_f)
    
    v_rec = v_dso_in # 플롯 및 상호상관을 위해 교체
    v_demod = hilbert(v_dso_in) if cfg.rx_mode == 'Mixer' else v_dso_in.astype(np.complex128)

    # 7. Range Profile & Delay Estimation
    if cfg.rx_mode == 'ZBD':
        # ZBD destroys RF phase. Must correlate intensity envelopes!
        ref_sig = np.abs(v_pa_out)**2
        ref_sig = ref_sig - np.mean(ref_sig)
        
        # 기준 신호(Reference)도 동일하게 앰프 대역폭 및 Gain 통과
        ref_sig_filt = np.real(np.fft.ifft(np.fft.fft(ref_sig) * amp_mask)) * if_gain_lin
        
        # Apply Digital Self-Interference Cancellation (SIC) for ZBD
        if cfg.si_enable:
            v_si_zbd_raw = cfg.zbd_responsivity_vpw * (np.abs(v_si * lna_gain_lin)**2) / 50.0
            v_si_zbd = v_si_zbd_raw - np.mean(v_si_zbd_raw)
            v_si_zbd = np.real(np.fft.ifft(np.fft.fft(v_si_zbd_raw) * amp_mask)) * if_gain_lin
            radar_input = v_dso_in - v_si_zbd
        else:
            radar_input = v_dso_in
            
        ref_sig = ref_sig_filt
    else:
        # Mixer is coherent. Correlate complex RF envelopes.
        ref_sig = v_pa_out
        radar_input = v_dso_in

    N = len(radar_input)
    N_fft = 1
    while N_fft < 2 * N: N_fft *= 2
        
    tx_fft = np.fft.fft(ref_sig, N_fft)
    rx_fft = np.fft.fft(radar_input, N_fft)
    sync_corr = np.abs(np.fft.ifft(rx_fft * np.conj(tx_fft)))[:N]
    
    best_delay = int(np.argmax(sync_corr))
    
    if cfg.si_enable:
        demod_delay = 0  # Dominant signal is SI
    else:
        demod_delay = best_delay  # Dominant signal is Echo
    
    corr_db = 20.0 * np.log10(sync_corr + 1e-20)
    corr_db = corr_db - np.max(corr_db)
    
    range_axis = np.arange(N) * (3e8 / 2.0 / fs)
    valid_range = range_axis <= max(20.0, float(cfg.target_dist_m) * 2.5)
    range_axis = range_axis[valid_range]
    range_profile_db = corr_db[valid_range]

    # 8. Remote Comm Receiver (1-way Comm Path + DSP)
    # 레이더 Path Loss와 다른 1-way Friis 전송 손실 계산
    d = cfg.target_dist_m
    lam = 3e8 / (cfg.rf_carrier_ghz * 1e9)
    g_lin = 10 ** (cfg.ant_gain_dbi / 10.0)
    loss_com_lin = ((4 * np.pi) ** 2 * d ** 2) / (g_lin ** 2 * lam ** 2)
    path_loss_com_db = 10 * np.log10(loss_com_lin + 1e-30)
    beta_com = 10**(-path_loss_com_db / 20.0)
    delay_samp_com = int((d / 3e8 * 1e9) * 1e-9 * fs)
    
    v_com = np.zeros_like(v_pa_out)
    omega_c_tau_com = 2.0 * np.pi * (cfg.rf_carrier_ghz * 1e9) * (d / 3e8)
    if delay_samp_com > 0: 
        v_com[delay_samp_com:] = v_pa_out[:-delay_samp_com] * beta_com * np.exp(-1j * omega_c_tau_com)
    else: 
        v_com = v_pa_out * beta_com * np.exp(-1j * omega_c_tau_com)
        
    v_lna_sig_com = v_com * lna_gain_lin
    awgn_lna_com = np.sqrt(n_out_vrms2 / 2.0) * (np.random.randn(total_samples) + 1j * np.random.randn(total_samples))
    v_rx_in_com = v_lna_sig_com + awgn_lna_com
    
    if cfg.rx_mode == "ZBD":
        p_inst_w_com = (np.abs(v_rx_in_com) ** 2) / 50.0
        v_det_com = cfg.zbd_responsivity_vpw * p_inst_w_com
        v_det_com += np.random.normal(0.0, v_nep_rms, total_samples)
        v_rec_com = v_det_com - np.mean(v_det_com)
    else:
        # 원격 수신기는 로컬 LO와 무관한 독립적인 위상 잡음(Free-running) 발생
        if cfg.coherence_mode == "Self-coherent":
            phi_remote_total = np.zeros(total_samples)
        else:
            lw_remote = cfg.linewidth_mhz * 1e6
            phi_remote = generate_phase_noise(total_samples, lw_remote, fs)
            wander_remote = np.cumsum(np.random.randn(total_samples))
            wander_remote = (wander_remote - np.mean(wander_remote)) / (np.std(wander_remote) + 1e-12) * (cfg.carrier_wander_mhz * 1e6 if cfg.carrier_wander_enable else 0)
            phi_remote_total = phi_remote + 2 * np.pi * np.cumsum(wander_remote) / fs
        v_mix_in_com = v_rx_in_com * np.exp(-1j * phi_remote_total)
        v_rec_com = np.real(v_mix_in_com)

    N_f_com = len(v_rec_com)
    f_axis_com = np.fft.fftfreq(N_f_com, 1/fs)
    amp_mask_com = (np.abs(f_axis_com) > 30e3) & (np.abs(f_axis_com) < 30e9)
    v_rec_filt_com = np.real(np.fft.ifft(np.fft.fft(v_rec_com) * amp_mask_com))
    v_dso_in_com = v_rec_filt_com * if_gain_lin + np.sqrt(n_if_w * 50.0 / 2.0) * np.random.randn(N_f_com)
    v_demod_com = hilbert(v_dso_in_com) if cfg.rx_mode == "Mixer" else v_dso_in_com.astype(np.complex128)

    # 9. Demodulation (Remote Comm)
    lo_if = np.exp(-1j * 2 * np.pi * f_if * t)
    rx_bb_raw = v_demod_com * lo_if
    demod_delay = delay_samp_com
    
    evm_db, ser = float('nan'), float('nan')
    best_eq, best_tx, best_idx = None, None, None
    sym_eq = np.zeros(0, dtype=np.complex128)
    sym_tx = np.zeros(0, dtype=np.complex128)
    best_metric = np.inf

    if cfg.waveform == "OFDM-16QAM":
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
                    # [DSP] OFDM CPE(Common Phase Error) 추적 및 보상 (위상 잡음 대응)
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

    else:
        # QAM / LFM-QAM processing
        if cfg.waveform == "LFM-16QAM":
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
                
                # [위상 잡음에 강건한 타이밍 동기화] Non-coherent Integration
                # Free-running 모드에서 심한 위상 변동(Carrier Wander)이 있더라도 정확하게 피크를 찾습니다.
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
            
            # [정밀 AGC] 진폭 스케일링을 참조 신호의 진폭과 완벽히 동기화
            scale = np.sqrt(np.mean(np.abs(tx_ref)**2) / (np.mean(np.abs(sym_rx)**2) + 1e-15))
            sym_rx = sym_rx * scale
            
            # [초기 위상 보정] Preamble (처음 200 심볼)을 활용하여 전체 회전 오프셋 제거 (이퀄라이저 부담 최소화)
            preamble_len = min(200, len(sym_rx))
            h_ph = np.sum(sym_rx[:preamble_len] * np.conj(tx_ref[:preamble_len]))
            sym_rx = sym_rx * np.exp(-1j * np.angle(h_ph + 1e-15))
            
            g0 = 50
            g1 = min(m - 50, g0 + train_len)
            if g1 > g0:
                if cfg.rx_mode == "Mixer":
                    # [잔여 위상 추적] Carrier Wander 등 동적 위상 변화 보상
                    ph = np.unwrap(np.angle(sym_rx * np.conj(tx_ref) + 1e-15))
                    ph_s = np.convolve(ph, np.ones(21)/21, mode="same")
                    sym_rx = sym_rx * np.exp(-1j * ph_s)
                    
                    # 향상된 수렴 속도를 위해 mu=0.05 로 증가
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
        rx_idx = qam16_hard_demod(sym_eq)
        ser = float(np.mean(best_idx != rx_idx))

    return {
        "bb_sig": bb_sig, "fs": fs, "rf_c": cfg.rf_carrier_ghz * 1e9, "step": step, "frame_len": frame_len, "num_frames": num_frames,
        "e_data": e_data, "e_lo": e_lo, "v_pa_out": v_pa_out, 
        "v_rx_in_rad": v_rx_in, "v_si": v_si, "v_echo": v_echo, "v_rec_com": v_dso_in_com,
        "sym_tx": sym_tx, "sym_eq": sym_eq, "evm_db": evm_db, "ser": ser,
        "range_axis_m": range_axis, "range_profile_db": range_profile_db
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
        self.rx_mode_var = tk.StringVar(value="ZBD")
        self.coherence_var = tk.StringVar(value="Free-running")
        if self.awg_source is not None:
            self.awg_fs_var = self.awg_source.fs_var
            self.awg_ip_var = self.awg_source.ip_var
            self.awg_port_var = self.awg_source.port_var
            self.awg_ch_var = self.awg_source.ch_var
            self.awg_vpp_var = self.awg_source.vpp_var
        
        self._build_ui()
        self._init_plot()
        self._update_table()

    def _build_ui(self):
        # LEFT PANEL (parameters)
        left = ttk.Frame(self.parent)
        left.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # RIGHT PANEL (plots)
        self.right_frame = ttk.Frame(self.plot_parent)
        right = self.right_frame
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # ── TOP: Control buttons (4 consolidated) ──
        ctrl = ttk.LabelFrame(left, text="Controls", padding=4)
        ctrl.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        ttk.Button(ctrl, text="Run Simulation", style="Primary.TButton", command=self.run_simulation).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(ctrl, text="To AWG", command=self._cmd_to_awg).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(ctrl, text="Run AWG", command=self._cmd_run_awg).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self._anim_btn = ttk.Button(ctrl, text="Anim Start", command=self._cmd_toggle_anim)
        self._anim_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # ── Split left panel horizontally into (Simulation params | Physics Table) ──
        split_pane = ttk.PanedWindow(left, orient=tk.HORIZONTAL)
        split_pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        left_params = ttk.Frame(split_pane)
        right_table = ttk.Frame(split_pane)
        
        split_pane.add(left_params, weight=3)
        split_pane.add(right_table, weight=2)
        
        # ── RIGHT TABLE: Calculated Physics Parameters ──
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
            "tx":        self.table.insert("", "end", text="Antenna TX Power",  values=("0.00", "dBm")),
            "delay":     self.table.insert("", "end", text="Radar Echo Delay",  values=("0.00", "ns")),
            "loss":      self.table.insert("", "end", text="Radar Path Loss",   values=("0.00", "dB")),
            "echo":      self.table.insert("", "end", text="Radar Echo Power",  values=("0.00", "dBm")),
            "si":        self.table.insert("", "end", text="Local SI Power",    values=("0.00", "dBm")),
            "lna":       self.table.insert("", "end", text="LNA Out (Sig)",     values=("0.00", "dBm")),
            "lna_total": self.table.insert("", "end", text="LNA Out (Total)",   values=("0.00", "dBm")),
            "sinr":      self.table.insert("", "end", text="Radar SINR",        values=("0.00", "dB")),
            "comm_loss": self.table.insert("", "end", text="Comm Path Loss",    values=("0.00", "dB")),
            "comm_rx":   self.table.insert("", "end", text="Comm Rx Power",     values=("0.00", "dBm")),
            "comm_snr":  self.table.insert("", "end", text="Comm SNR",          values=("0.00", "dB")),
            "evm_pct":   self.table.insert("", "end", text="Comm EVM",          values=("N/A",  "%")),
        }

        # ── LEFT PARAMS (scrollable): AWG + Simulation Parameters ──
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
            self.awg_ch_var = tk.StringVar(value="2")
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
            e = ttk.Entry(grp, textvariable=self.params[key], width=10)
            e.grid(row=row, column=1, sticky="w")
            return e

        # removed fs_gsps
        add_p(1, "linewidth_mhz", "Laser Linewidth [MHz]", "0.1")
        # removed baud_gbaud
        # removed if_ghz
        self.waveform_var = tk.StringVar(value="16QAM") # Hidden, managed by awg
        # removed chirp_bw_ghz

        ttk.Checkbutton(grp, text="Enable Carrier Wander", variable=self.carrier_wander_enable_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(grp, text="Enable SI Leakage", variable=self.si_enable_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(grp, text="Coherence Mode").grid(row=8, column=0, sticky="w", pady=2)
        ttk.Combobox(grp, textvariable=self.coherence_var, values=["Free-running", "Self-coherent"], width=12).grid(row=8, column=1)
        ttk.Label(grp, text="RX Front-end").grid(row=9, column=0, sticky="w", pady=2)
        ttk.Combobox(grp, textvariable=self.rx_mode_var, values=["Mixer", "ZBD"], width=12).grid(row=9, column=1)

        ttk.Separator(grp, orient="horizontal").grid(row=10, column=0, columnspan=2, sticky="ew", pady=5)
        add_p(11, "utcpd_dbm",    "UTC-PD Output [dBm]",   "-25.0")
        add_p(12, "pa_gain_db",   "THz PA Gain [dB]",       "24.0")
        add_p(13, "pa_p1db_dbm",  "PA P1dB Out [dBm]",      "-1.0")
        add_p(14, "lna_gain_db",  "LNA Gain [dB]",          "14.0")
        add_p(15, "lna_nf_db",    "LNA NF [dB]",            "8.0")
        add_p(16, "zbd_resp_vpw", "ZBD Resp. [V/W]",        "2200")
        add_p(17, "zbd_nep_pw",   "ZBD NEP [pW/sqrtHz]",   "12")
        add_p(18, "if_amp_gain_db","IF Amp Gain [dB]",      "20.0")
        add_p(19, "if_amp_nf_db", "IF Amp NF [dB]",         "5.0")
        add_p(20, "dso_noise_dbm","DSO Noise [dBm]",        "-50.0")
        add_p(21, "ant_gain_dbi", "Antenna Gain [dBi]",     "25.0")
        add_p(22, "omt_iso_db",   "OMT Isolation [dB]",     "25.0")
        add_p(23, "rcs_sqm",      "Target RCS [m²]",        "1.0")

        ttk.Label(grp, text="Target Dist [m]").grid(row=24, column=0, sticky="w", pady=2)
        self.params["target_dist_m"] = tk.StringVar(value="1.0")
        self.params["target_dist_m"].trace_add("write", self._update_table)
        ttk.Entry(grp, textvariable=self.params["target_dist_m"], width=10).grid(row=24, column=1, sticky="w")
        
        self.sc_fde_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp, text="Enable SC-FDE", variable=self.sc_fde_enable_var).grid(row=25, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(grp, text="SC-FDE Taps").grid(row=26, column=0, sticky="w", pady=2)
        self.sc_fde_taps_var = tk.StringVar(value="21")
        ttk.Entry(grp, textvariable=self.sc_fde_taps_var, width=10).grid(row=26, column=1, sticky="w")

        # Plot on right
        self.fig = Figure(figsize=(8, 8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        ttk.Label(right, textvariable=self.demod_var, foreground="#114488", font=("Arial", 12, "bold")).pack(pady=5)

    def _update_table(self, *args):
        try:
            d = float(self.params["target_dist_m"].get())
            tx_raw_dbm = float(self.params['utcpd_dbm'].get()) + float(self.params['pa_gain_db'].get())
            pa_p1db = float(self.params['pa_p1db_dbm'].get())
            tx_dbm = min(tx_raw_dbm, pa_p1db)
            delay_ns = (2.0 * d) / 3e8 * 1e9
            
            lam = 3e8 / 270e9
            g_lin = 10**(float(self.params["ant_gain_dbi"].get()) / 10.0)
            rcs = float(self.params["rcs_sqm"].get())
            loss_lin = ((4*np.pi)**3 * d**4) / (g_lin**2 * lam**2 * rcs)
            loss_db = 10 * np.log10(loss_lin + 1e-30)
            
            echo_dbm = tx_dbm - loss_db
            si_enable = bool(self.si_enable_var.get())
            si_dbm = tx_dbm - float(self.params["omt_iso_db"].get()) if si_enable else -300.0
            lna_out_dbm = max(echo_dbm, si_dbm) + float(self.params["lna_gain_db"].get())
            # Use AWG fs for bandwidth approximation since fs_gsps param was removed
            if getattr(self, "awg_fs_var", None):
                rx_bw_hz = float(self.awg_fs_var.get()) * 1e9
            else:
                rx_bw_hz = 120e9
            
            lna_noise_dbm = -174.0 + 10 * np.log10(rx_bw_hz) + float(self.params["lna_nf_db"].get()) + float(self.params["lna_gain_db"].get())
            zbd_noise_v = float(self.params["zbd_resp_vpw"].get()) * float(self.params["zbd_nep_pw"].get()) * 1e-12 * np.sqrt(rx_bw_hz / 2.0)

            # Link-budget SINR approximation
            # [물리적 신호 전력 교정] 송신 파워(tx_dbm)의 98%는 광 캐리어 성분이며 데이터(IF) 전력은 약 16.6dB 낮음
            data_pwr_ratio_db = -16.6
            p_echo_lin = 10 ** ((echo_dbm + data_pwr_ratio_db) / 10.0)
            p_si_lin = 10 ** ((si_dbm + data_pwr_ratio_db) / 10.0)
            
            # [수신 대역폭 내 잡음] 정합 필터 통과 후 유효 잡음 대역폭은 Symbol Rate와 동일
            try:
                if getattr(self, "awg_source", None):
                    baud_rate_hz = float(self.awg_source.symbol_rate_var.get()) * 1e9
                else:
                    baud_rate_hz = 10e9
            except:
                baud_rate_hz = 10e9
            p_noise_in_dbm = -174.0 + 10 * np.log10(baud_rate_hz) + float(self.params["lna_nf_db"].get())
            p_noise_lin = 10 ** (p_noise_in_dbm / 10.0)
            
            sinr_lin = p_echo_lin / (p_si_lin + p_noise_lin + 1e-30)
            sinr_db = 10 * np.log10(sinr_lin + 1e-30)

            p_echo_out_lin = 10 ** (echo_dbm / 10.0) * 10 ** (float(self.params["lna_gain_db"].get()) / 10.0)
            p_si_out_lin = 10 ** (si_dbm / 10.0) * 10 ** (float(self.params["lna_gain_db"].get()) / 10.0)
            p_noise_out_lin = 10 ** (lna_noise_dbm / 10.0)
            lna_total_dbm = 10 * np.log10(p_echo_out_lin + p_si_out_lin + p_noise_out_lin + 1e-30)

            loss_com_lin = ((4*np.pi)**2 * d**2) / (g_lin**2 * lam**2)
            loss_com_db = 10 * np.log10(loss_com_lin + 1e-30)
            comm_dbm = tx_dbm - loss_com_db
            
            p_comm_data_lin = 10 ** ((comm_dbm + data_pwr_ratio_db) / 10.0)
            com_snr_db = 10 * np.log10(p_comm_data_lin / (p_noise_lin + 1e-30) + 1e-30)

            # Measured EVM is updated after simulation run.
            
            self.table.item(self.rows["tx"], values=(f"{tx_dbm:.1f}", "dBm"))
            self.table.item(self.rows["delay"], values=(f"{delay_ns:.2f}", "ns"))
            self.table.item(self.rows["loss"], values=(f"{loss_db:.1f}", "dB"))
            self.table.item(self.rows["echo"], values=(f"{echo_dbm:.1f}", "dBm"))
            self.table.item(self.rows["si"], values=((f"{si_dbm:.1f}" if si_enable else "OFF"), ("dBm" if si_enable else "-")))
            self.table.item(self.rows["lna"], values=(f"{lna_out_dbm:.1f}", "dBm"))
            self.table.item(self.rows["lna_total"], values=(f"{lna_total_dbm:.1f}", "dBm"))
            self.table.item(self.rows["sinr"], values=(f"{sinr_db:.2f}", "dB"))
            if "comm_loss" in self.rows:
                self.table.item(self.rows["comm_loss"], values=(f"{loss_com_db:.1f}", "dB"))
            if "comm_rx" in self.rows:
                self.table.item(self.rows["comm_rx"], values=(f"{comm_dbm:.1f}", "dBm"))
            if "comm_snr" in self.rows:
                self.table.item(self.rows["comm_snr"], values=(f"{com_snr_db:.2f}", "dB"))
        except Exception as e:
            print(f"Update table error: {e}")

    def _cfg_from_ui(self) -> SimConfig:
        awg = self.awg_source
        cfg = SimConfig(
            fs_gsps=float(awg.fs_var.get()) if awg else 100.0,
            linewidth_mhz=float(self.params["linewidth_mhz"].get()),
            baud_gbaud=float(awg.symbol_rate_var.get()) if awg else 10.0,
            if_ghz=float(awg.if_var.get()) if awg else 10.0,
            rf_carrier_ghz=float(awg.rf_var.get()) if awg else 270.0,
            waveform=awg.waveform_var.get().strip() if awg else "LFM-QAM",
            chirp_bw_ghz=float(awg.symbol_rate_var.get()) if awg else 2.0,
            coherence_mode=self.coherence_var.get().strip(),
            rx_mode=self.rx_mode_var.get().strip(),
            si_enable=bool(self.si_enable_var.get()),
            carrier_wander_enable=bool(self.carrier_wander_enable_var.get()),
            carrier_wander_mhz=300.0,
            utcpd_target_dbm=float(self.params["utcpd_dbm"].get()),
            pa_gain_db=float(self.params["pa_gain_db"].get()),
            pa_p1db_dbm=float(self.params["pa_p1db_dbm"].get()),
            lna_gain_db=float(self.params["lna_gain_db"].get()),
            lna_nf_db=float(self.params["lna_nf_db"].get()),
            zbd_responsivity_vpw=float(self.params["zbd_resp_vpw"].get()),
            zbd_nep_pw_sqrt_hz=float(self.params["zbd_nep_pw"].get()),
            if_amp_gain_db=float(self.params["if_amp_gain_db"].get()),
            if_amp_nf_db=float(self.params["if_amp_nf_db"].get()),
            omt_iso_db=float(self.params["omt_iso_db"].get()),
            ant_gain_dbi=float(self.params["ant_gain_dbi"].get()),
            target_rcs_sqm=float(self.params["rcs_sqm"].get()),
            target_dist_m=max(float(self.params["target_dist_m"].get()), 0.1),
        )

        cfg.delay_ns = (2.0 * cfg.target_dist_m) / 3e8 * 1e9
        cfg.path_loss_db = 10 * np.log10(((4 * np.pi) ** 3 * cfg.target_dist_m ** 4) / ((10 ** (cfg.ant_gain_dbi / 10.0)) ** 2 * (3e8 / (cfg.rf_carrier_ghz * 1e9)) ** 2 * max(cfg.target_rcs_sqm, 1e-6)) + 1e-30)
        cfg.tx_power_dbm = cfg.utcpd_target_dbm + cfg.pa_gain_db
        return cfg

    def _init_plot(self):
        self.fig.clear()
        gs = self.fig.add_gridspec(2, 3)
        self.axes = [self.fig.add_subplot(gs[0,0]), self.fig.add_subplot(gs[0,1]), self.fig.add_subplot(gs[1,0]), self.fig.add_subplot(gs[1,1])]
        self.ax_range = self.fig.add_subplot(gs[0,2])
        self.ax_const = self.fig.add_subplot(gs[1,2])
        self.lines = []
        titles = ["1) Opt. Spectrum (MZM & LO)", "2) THz PA Output (TX Antenna)", "3) Local LNA Out (Radar)", "4) Remote IF Amp Out (Comm)"]
        colors = ["purple", "red", "orange", "blue"]
        
        for i, ax in enumerate(self.axes):
            if i == 2:
                line, = ax.plot([], [], lw=1.5, color=colors[i], label="Total")
                self.l_si, = ax.plot([], [], lw=1.2, color="green", linestyle="--", label="SI")
                self.l_echo, = ax.plot([], [], lw=1.2, color="magenta", linestyle=":", label="Echo")
                ax.legend(loc="upper right", fontsize=8)
            else:
                line, = ax.plot([], [], lw=1.5, color=colors[i], label="Signal")
                ax.legend(loc="upper right", fontsize=8)
            self.lines.append(line)
            ax.set_title(titles[i])
            ax.grid(True, alpha=0.45)
            ax.set_ylabel("PSD [dBm/Hz]")
            
        self.l_lo, = self.axes[0].plot([], [], lw=1.2, color="black", label="Opt. LO")
        self.axes[0].legend(loc="upper right", fontsize=8)
        self.ax_range.set_title("5) Range Profile")
        self.ax_range.set_xlabel("Range [m]")
        self.ax_range.set_ylabel("Magnitude [dB]")
        self.ax_range.grid(True, alpha=0.45)
        self.ax_range.set_xlim(0, 10)

        self.ax_const.set_title("6) 16-QAM Constellation")
        self.ax_const.set_xlim(-1.8, 1.8); self.ax_const.set_ylim(-1.8, 1.8)
        self.ax_const.grid(True, alpha=0.45)
        self.fig.tight_layout()

    def run_simulation(self) -> None:
        try:
            self.stop_animation()
            self._update_table()  # 레이더 파라미터 테이블 갱신
            cfg = self._cfg_from_ui()
            
            # 시뮬레이션 백엔드 실행
            self.data = run_isac_sim(cfg)
            
            # ─────────────────────────────────────────────────────────
            # 1. X축 범위 완벽 자동화 (주파수 대역 기반)
            # ─────────────────────────────────────────────────────────
            c = cfg.rf_carrier_ghz
            # IF 주파수와 데이터 레이트(Baud)를 합쳐 여유있는 Span 계산
            span = cfg.if_ghz + (cfg.baud_gbaud / 2.0) + 5.0
            
            # 광 스펙트럼: Data(193.4 THz)부터 LO 반송파(193.4 + c THz)까지 동적 조절
            self.axes[0].set_xlim(193.35, 193.40 + (c / 1000.0) + 0.05)
            self.axes[1].set_xlim(c - span, c + span)
            self.axes[2].set_xlim(c - span, c + span)
            self.axes[3].set_xlim(0.0, span)

            # ─────────────────────────────────────────────────────────
            # 2. Y축 고정: 링크버짓 기반 절대 전력 레벨로 설정
            # ─────────────────────────────────────────────────────────
            fs = self.data["fs"]
            bw_db = 10 * np.log10(fs)
            p_pa_dbm = min(cfg.utcpd_target_dbm + cfg.pa_gain_db, cfg.pa_p1db_dbm)
            p_si_dbm = p_pa_dbm - cfg.omt_iso_db
            p_echo_dbm = p_pa_dbm - cfg.path_loss_db
            p_lna_sig_dbm = max(p_si_dbm, p_echo_dbm) + cfg.lna_gain_db
            p_lna_noise_dbm = -174.0 + bw_db + cfg.lna_nf_db + cfg.lna_gain_db

            # PSD( dBm/Hz ) 축으로 변환 시 대역폭 항 제거
            pa_psd_dbmhz = p_pa_dbm - bw_db
            lna_sig_psd_dbmhz = p_lna_sig_dbm - bw_db
            lna_noise_psd_dbmhz = p_lna_noise_dbm - bw_db

            self.axes[0].set_ylim(pa_psd_dbmhz - 80, pa_psd_dbmhz + 20)
            self.axes[1].set_ylim(pa_psd_dbmhz - 80, pa_psd_dbmhz + 20)
            self.axes[2].set_ylim(lna_noise_psd_dbmhz - 10, lna_sig_psd_dbmhz + 20)
            self.axes[3].set_ylim(lna_noise_psd_dbmhz - 20, lna_sig_psd_dbmhz + 20)

            # ─────────────────────────────────────────────────────────
            # 3. Constellation 그래프 자동 스케일링 및 업데이트
            # ─────────────────────────────────────────────────────────
            self.ax_const.cla()
            self.ax_const.set_title("6) Constellation (16-QAM)")
            self.ax_const.grid(True, alpha=0.45)
            
            sym_eq = np.asarray(self.data.get("sym_eq", []))
            sym_tx = np.asarray(self.data.get("sym_tx", []))
            
            if len(sym_eq) > 0: 
                self.ax_const.scatter(np.real(sym_eq[:2000]), np.imag(sym_eq[:2000]), s=8, alpha=0.6)
            if len(sym_tx) > 0: 
                self.ax_const.scatter(np.real(sym_tx[:2000]), np.imag(sym_tx[:2000]), s=22, marker="x", color="red")
            
            # 사용자가 요청한 고정 크기 [-1.5, 1.5]
            self.ax_const.set_xlim(-1.5, 1.5)
            self.ax_const.set_ylim(-1.5, 1.5)
            self.ax_const.set_aspect("equal", adjustable="box")

            # 결과 수치 표기
            evm_db = float(self.data.get("evm_db", float('nan')))
            ser = float(self.data.get("ser", float('nan')))
            
            if np.isfinite(evm_db):
                self.demod_var.set(f"16-QAM Demod: EVM={evm_db:.1f} dB | SER={ser:.4f}")
                evm_pct = estimate_measured_evm_percent(evm_db)
                self.table.item(self.rows["evm_pct"], values=(f"{evm_db:.2f}", "dB"))
                self.table.item(self.rows["evm_pct"], values=(f"{evm_pct:.2f}", "%"))
            else:
                self.demod_var.set(f"Comm Demod: N/A ({cfg.rx_mode})")
                                
            self._update_range_profile()

            self.frame_idx = 0
            self._update_frame()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _update_range_profile(self):
        if not self.data:
            return
        self.ax_range.cla()
        self.ax_range.set_title("5) Range Profile")
        self.ax_range.set_xlabel("Range [m]")
        self.ax_range.set_ylabel("Magnitude [dB]")
        self.ax_range.grid(True, alpha=0.45)

        rng = np.asarray(self.data.get("range_axis_m", []))
        prof = np.asarray(self.data.get("range_profile_db", []))
        if len(rng) > 0:
            max_range = max(10.0, float(np.max(rng)))
            m = rng <= max_range
            self.ax_range.plot(rng[m], prof[m], color="teal", lw=1.3)
            self.ax_range.set_xlim(0.0, max_range)
            max_prof = np.max(prof[m]) if np.any(m) else 0.0
            self.ax_range.set_ylim(-40.0, max_prof + 10.0)
            
    def _update_frame(self):
        if not self.data: return
        fs, rf_c, step, flen = self.data["fs"], self.data["rf_c"], self.data["step"], self.data["frame_len"]
        s, e = self.frame_idx * step, self.frame_idx * step + flen

        # Plot 1: Optical
        f, p_mzm = calc_psd(self.data["e_data"][s:e], fs)
        _, p_lo = calc_psd(self.data["e_lo"][s:e], fs)
        self.lines[0].set_data((f + 193.4e12)/1e12, p_mzm)
        self.l_lo.set_data((f + 193.4e12 + rf_c)/1e12, p_lo)
        
        # Plot 2: PA Output
        f, p_pa = calc_psd(self.data["v_pa_out"][s:e], fs)
        pwr_tx = calc_power_dbm(self.data["v_pa_out"][s:e])
        self.lines[1].set_data((f + rf_c)/1e9, p_pa)
        self.lines[1].set_label(f"PA Out ({pwr_tx:.1f} dBm)")
        
        # Plot 3: LNA Output
        f, p_rx = calc_psd(self.data["v_rx_in_rad"][s:e], fs)
        _, p_si = calc_psd(self.data["v_si"][s:e], fs)
        _, p_echo = calc_psd(self.data["v_echo"][s:e], fs)
        self.lines[2].set_data((f + rf_c)/1e9, p_rx)
        self.l_si.set_data((f + rf_c)/1e9, p_si)
        self.l_echo.set_data((f + rf_c)/1e9, p_echo)
        
        pwr_si = calc_power_dbm(self.data["v_si"][s:e])
        pwr_echo = calc_power_dbm(self.data["v_echo"][s:e])
        pwr_total = calc_power_dbm(self.data["v_rx_in_rad"][s:e])
        self.lines[2].set_label(f"Radar Total ({pwr_total:.1f} dBm)")
        self.l_si.set_label(f"SI ({pwr_si:.1f} dBm)")
        self.l_echo.set_label(f"Echo ({pwr_echo:.1f} dBm)")
        self.axes[1].legend(loc="upper right", fontsize=8); self.axes[2].legend(loc="upper right", fontsize=8)

        # Plot 4: Baseband Comm
        f, p_bb = calc_psd(self.data["v_rec_com"][s:e], fs)
        self.lines[3].set_data(f[f>=0]/1e9, p_bb[f>=0])
        self.lines[3].set_label("Remote IF Out")
        self.axes[3].legend(loc="upper right", fontsize=8)

        self.canvas.draw_idle()
        self.frame_idx = (self.frame_idx + 1) % self.data["num_frames"]


    def _on_download_awg(self):
        def worker():
            import threading
            import numpy as np
            from scipy.signal import resample
            from functions.awg_functions import download_to_awg, parse_channels
            from functions.dsp_functions import normalize_real_for_awg
            from tkinter import messagebox
            
            try:
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
                    bb_awg = resample(bb_sig, num_samples)
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
        self._noise_floor_ref_dbmhz: float | None = None   # stored from "Measure Noise Floor"
        self._build_ui()
        self._start_log_pump()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main = ttk.Frame(self.parent, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ── LEFT PANEL (fixed 420px, scrollable) ─────────────────────
        left = ttk.Frame(main, width=420)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        lc = tk.Canvas(left, highlightthickness=0, bg="#f4f6f9")
        lsb = ttk.Scrollbar(left, orient="vertical", command=lc.yview)
        lc.configure(yscrollcommand=lsb.set)
        lsb.pack(side=tk.RIGHT, fill=tk.Y)
        lc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lf = ttk.Frame(lc)
        _lw = lc.create_window((0, 0), window=lf, anchor="nw")
        lf.bind("<Configure>", lambda _: lc.configure(scrollregion=lc.bbox("all")))
        lc.bind("<Configure>", lambda e: lc.itemconfig(_lw, width=e.width))
        lc.bind("<MouseWheel>", lambda e: lc.yview_scroll(int(-1*(e.delta/120)), "units"))

        # ── RIGHT PANEL (plot) ────────────────────────────────────────
        self.right_frame = ttk.Frame(main)
        right = self.right_frame
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))

        # ══ Section 1: DSO Connection ════════════════════════════════
        grp1 = ttk.LabelFrame(lf, text="DSO Connection", padding=8)
        grp1.pack(fill=tk.X, pady=(0, 6))
        grp1.columnconfigure(1, weight=1)
        grp1.columnconfigure(3, weight=1)

        self.live_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp1, text="Live DSO (uncheck = use last capture)",
                        variable=self.live_var,
                        command=self._on_mode_changed).grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Label(grp1, text="DSO Type").grid(row=1, column=0, sticky="w", pady=3)
        self.dso_type_var = tk.StringVar(value="keysight_uxr")
        self.dso_type_combo = ttk.Combobox(
            grp1, textvariable=self.dso_type_var,
            values=["keysight_uxr", "lecroy"], state="readonly", width=14)
        self.dso_type_combo.grid(row=1, column=1, sticky="w")
        ttk.Label(grp1, text="Scope BW (GHz)").grid(row=1, column=2, sticky="w", padx=(10, 0))
        self.scope_bw_var = tk.StringVar(value=str(self._UXR0404A_BW_GHZ))
        ttk.Entry(grp1, textvariable=self.scope_bw_var, width=7).grid(row=1, column=3, sticky="w")
        
        ttk.Label(grp1, text="DSO SR (GS/s)").grid(row=1, column=4, sticky="w", padx=(10, 0))
        self.dso_sr_var = tk.StringVar(value="256")
        ttk.Combobox(grp1, textvariable=self.dso_sr_var, values=["64", "128", "256", "Auto"], state="readonly", width=7).grid(row=1, column=5, sticky="w")

        ttk.Label(grp1, text="DSO Host").grid(row=2, column=0, sticky="w", pady=3)
        self.host_var = tk.StringVar(value="192.168.1.4")
        self.host_entry = ttk.Entry(grp1, textvariable=self.host_var, width=18)
        self.host_entry.grid(row=2, column=1, columnspan=3, sticky="we")

        ttk.Label(grp1, text="Channel").grid(row=3, column=0, sticky="w", pady=3)
        self.ch_var = tk.StringVar(value="C1")
        self.ch_combo = ttk.Combobox(grp1, textvariable=self.ch_var,
                                      values=["C1","C2","C3","C4"], state="readonly", width=7)
        self.ch_combo.grid(row=3, column=1, sticky="w")
        ttk.Label(grp1, text="Timeout (ms)").grid(row=3, column=2, sticky="w", padx=(10, 0))
        self.timeout_var = tk.StringVar(value="10000")
        self.timeout_entry = ttk.Entry(grp1, textvariable=self.timeout_var, width=8)
        self.timeout_entry.grid(row=3, column=3, sticky="w")
        ttk.Label(grp1, text="Ch Scale (mV/div)").grid(row=3, column=4, sticky="w", padx=(10, 0))
        self.ch_scale_mv_var = tk.StringVar(value="50")
        ttk.Entry(grp1, textvariable=self.ch_scale_mv_var, width=7).grid(row=3, column=5, sticky="w")

        ttk.Label(grp1, text="Process Fs (GS/s)").grid(row=4, column=0, sticky="w", pady=3)
        self.capture_fs_var = tk.StringVar(value="")
        ttk.Entry(grp1, textvariable=self.capture_fs_var, width=10).grid(row=4, column=1, sticky="w")
        ttk.Label(grp1, text="Capture Margin (xT)").grid(row=4, column=2, sticky="w", padx=(10, 0))
        self.max_samples_var = tk.StringVar(value="3.0")
        ttk.Entry(grp1, textvariable=self.max_samples_var, width=10).grid(row=4, column=3, sticky="w")

        conn_btn_f = ttk.Frame(grp1)
        conn_btn_f.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.test_btn = ttk.Button(conn_btn_f, text="Test Connection",
                                   command=self._on_test_connection)
        self.test_btn.pack(side=tk.LEFT)
        ttk.Button(conn_btn_f, text="Acquire", style="Primary.TButton",
                   command=self._on_capture_live).pack(side=tk.LEFT, padx=(6, 0))

        self.conn_status_var = tk.StringVar(value="Not checked")
        tk.Label(grp1, textvariable=self.conn_status_var,
                 fg="gray", bg="#f4f6f9").grid(row=6, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # ══ Section 2: Signal Parameters (unified for all measurements) ══
        grp2 = ttk.LabelFrame(lf, text="Signal Parameters", padding=8)
        grp2.pack(fill=tk.X, pady=(0, 6))
        grp2.columnconfigure(1, weight=1)
        grp2.columnconfigure(3, weight=1)

        ttk.Label(grp2, text="Carrier Freq (GHz)").grid(row=0, column=0, sticky="w", pady=3)
        self.fc_var = tk.StringVar(value="10.0")
        ttk.Entry(grp2, textvariable=self.fc_var, state="disabled", width=10).grid(row=0, column=1, sticky="w")

        ttk.Label(grp2, text="Symbol Rate (GHz)").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.sr_var = tk.StringVar(value="1.0")
        ttk.Entry(grp2, textvariable=self.sr_var, state="disabled", width=10).grid(row=0, column=3, sticky="w")

        ttk.Label(grp2, text="Modulation").grid(row=1, column=0, sticky="w", pady=3)
        self.demod_mod_var = tk.StringVar(value="16QAM")
        ttk.Combobox(grp2, textvariable=self.demod_mod_var,
                     values=["BPSK","QPSK","8PSK","16QAM","32QAM","64QAM"],
                     state="readonly", width=10).grid(row=1, column=1, sticky="w")

        ttk.Label(grp2, text="RRC Roll-off β").grid(row=1, column=2, sticky="w", padx=(10, 0))
        self.demod_beta_var = tk.StringVar(value="0.25")
        ttk.Entry(grp2, textvariable=self.demod_beta_var, state="disabled", width=10).grid(row=1, column=3, sticky="w")

        ttk.Label(grp2, text="RRC Span (sym)").grid(row=2, column=0, sticky="w", pady=3)
        self.demod_span_var = tk.StringVar(value="8")
        ttk.Entry(grp2, textvariable=self.demod_span_var, width=10).grid(row=2, column=1, sticky="w")

        self.band_info_var = tk.StringVar(value="Band: ---")
        ttk.Label(grp2, textvariable=self.band_info_var,
                  style="Muted.TLabel").grid(row=2, column=2, columnspan=2, sticky="w", padx=(10, 0))

        for v in (self.fc_var, self.sr_var, self.demod_beta_var):
            v.trace_add("write", lambda *_: self._update_band_label())
        self._update_band_label()

        btn_f = ttk.Frame(grp2)
        btn_f.grid(row=3, column=0, columnspan=4, sticky="we", pady=(10, 0))
        ttk.Button(btn_f, text="Measure (Power + SNR)", style="Primary.TButton",
                   command=self._on_measure_band).pack(side=tk.LEFT)
        ttk.Button(btn_f, text="Demodulate", style="Primary.TButton",
                   command=self._on_demodulate).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_f, text="ISAC De-chirp / Range", style="Primary.TButton",
                   command=self._on_isac_dechirp_range).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_f, text="Measure Noise Floor",
                   command=self._on_measure_noise_floor).pack(side=tk.LEFT, padx=(6, 0))

        self.filter_overlay_var = tk.BooleanVar(value=True)
        self.filter_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp2, text="Show filtered spectrum", variable=self.filter_overlay_var,
                        command=self._plot_spectrum_and_time).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(grp2, text="Apply demod LPF", variable=self.filter_enable_var).grid(
            row=4, column=2, columnspan=2, sticky="w", padx=(10, 0), pady=(6, 0))
            
        self.sc_fde_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp2, text="Enable SC-FDE", variable=self.sc_fde_enable_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(grp2, text="SC-FDE Taps").grid(row=5, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.sc_fde_taps_var = tk.StringVar(value="21")
        ttk.Entry(grp2, textvariable=self.sc_fde_taps_var, width=10).grid(row=5, column=3, sticky="w", pady=(6, 0))

        # ══ Section 3: Results ════════════════════════════════════════
        grp3 = ttk.LabelFrame(lf, text="Results", padding=8)
        grp3.pack(fill=tk.X, pady=(0, 6))

        self.band_pwr_var    = tk.StringVar(value="Band Power:  ---")
        self.noise_floor_var = tk.StringVar(value="Noise Floor: ---")
        self.snr_var         = tk.StringVar(value="SNR:         ---")
        self.evm_var         = tk.StringVar(value="EVM:         ---")
        self.ber_var         = tk.StringVar(value="BER:         ---")
        self.sym_count_var   = tk.StringVar(value="Symbols:     ---")

        for v in (self.band_pwr_var, self.noise_floor_var, self.snr_var,
                  self.evm_var, self.ber_var, self.sym_count_var):
            ttk.Label(grp3, textvariable=v, foreground="#114488",
                      font=("Segoe UI", 10, "bold")).pack(anchor="w")

        # ══ Section 4: Log ═══════════════════════════════════════════
        grp4 = ttk.LabelFrame(lf, text="Log", padding=4)
        grp4.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.log_text = tk.Text(grp4, height=8, bg="#ffffff",
                                font=("Consolas", 8), wrap="none")
        log_sb = ttk.Scrollbar(grp4, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ── Plot area ────────────────────────────────────────────────
        self.fig = Figure(figsize=(9, 7), dpi=100)
        gs = self.fig.add_gridspec(2, 2, hspace=0.38, wspace=0.35)
        self.ax_spec  = self.fig.add_subplot(gs[0, :])
        self.ax_time  = self.fig.add_subplot(gs[1, 0])
        self.ax_const = self.fig.add_subplot(gs[1, 1])
        self._init_plots()

        self.canvas_plot = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas_plot.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self._on_mode_changed()

    def _init_plots(self) -> None:
        for ax, title in [(self.ax_spec, "Spectrum"), (self.ax_time, "Time Waveform"), (self.ax_const, "Constellation")]:
            ax.set_title(title)
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes, color="gray")
            ax.set_axis_off()
        self.fig.tight_layout()

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
        self.ch_combo.configure(state=state_live)
        self.dso_type_combo.configure(state=state_live)
        self.host_entry.configure(state=state_live_n)
        self.timeout_entry.configure(state=state_live_n)
        self.test_btn.configure(state=state_live_n)

    def _update_band_label(self) -> None:
        try:
            fc   = float(self.fc_var.get())
            sr   = float(self.sr_var.get())
            beta = float(self.demod_beta_var.get())
            bw   = sr * (1.0 + float(np.clip(beta, 0.0, 1.0)))
            f_lo = fc - bw / 2.0
            f_hi = fc + bw / 2.0
            self.band_info_var.set(f"Band: {f_lo:.3f} – {f_hi:.3f} GHz")
        except Exception:
            self.band_info_var.set("Band: ---")

    def _get_signal_band_ghz(self) -> tuple[float, float]:
        """Compute (f_low, f_high) in GHz from carrier freq, symbol rate and RRC beta."""
        fc   = float(self.fc_var.get())
        sr   = float(self.sr_var.get())
        beta = float(np.clip(float(self.demod_beta_var.get()), 0.0, 1.0))
        bw   = sr * (1.0 + beta)
        return fc - bw / 2.0, fc + bw / 2.0

    def _scope_bw_ghz(self) -> float:
        try:
            return float(self.scope_bw_var.get())
        except Exception:
            return self._UXR0404A_BW_GHZ

    def _requested_process_fs(self) -> float | None:
        raw = self.capture_fs_var.get().strip()
        if not raw:
            return None
        fs = float(raw) * 1e9
        if fs <= 0:
            raise ValueError("Process Fs must be positive.")
        return fs

    def _max_capture_samples(self) -> int | None:
        raw = self.max_samples_var.get().strip()
        if not raw:
            return None
        val = float(raw)
        if val <= 0:
            raise ValueError("Margin/Samples must be positive.")
        
        # If the user typed a huge number, treat it as literal Max Samples (legacy)
        if val >= 1000:
            return int(val)
            
        # Otherwise, compute required samples dynamically based on actual TX duration!
        pl = self._load_tx_payload_for_isac()
        if pl and "awg_sig" in pl and "fs" in pl:
            sig_len = len(pl["awg_sig"])
            fs_awg = pl["fs"]
            
            sr_val = self.dso_sr_var.get()
            fs_dso_target = float(sr_val) * 1e9 if sr_val != "Auto" else 256e9
            
            duration = sig_len / fs_awg
            needed_samples = int(duration * fs_dso_target * val)
            
            # Add a small overhead or floor to ensure we don't capture too little
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
        mask = ((np.abs(freq) >= lo) & (np.abs(freq) <= hi))
        X[~mask] = 0.0
        return np.real(np.fft.ifft(X))

    @staticmethod
    def _compute_psd_db(sig: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
        """Single-sided PSD in dBm/Hz (50Ω reference) via Welch."""
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
        else:           # Square QAM: 16,32,64,...
            sq = int(np.sqrt(M))
            lvl = np.arange(-(sq-1), sq, 2, dtype=float)
            c = np.array([a + 1j*b for b in lvl for a in lvl])
        c = c / np.sqrt(np.mean(np.abs(c)**2))
        dist = np.abs(syms[:, None] - c[None, :])
        return c[np.argmin(dist, axis=1)]

    @staticmethod
    def _bits_per_sym(mod: str) -> int:
        return {"BPSK":1,"QPSK":2,"8PSK":3,"16QAM":4,"32QAM":5,"64QAM":6}.get(mod.upper(), 4)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
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
                        
                        ch_str = self.ch_var.get().strip().upper()
                        ch_num = ch_str.replace("C", "").replace("HAN", "").replace("NEL", "")
                        if ch_num:
                            dso.write(f":CHANnel{ch_num}:DISPlay ON")
                            try:
                                scale_vdiv = float(self.ch_scale_mv_var.get()) / 1000.0
                                dso.write(f":CHANnel{ch_num}:SCALe {scale_vdiv:.4f}")
                            except Exception:
                                pass

                        # Sync Sample Rate and Points
                        sr_val = self.dso_sr_var.get()
                        if sr_val != "Auto":
                            fs_dso_target = float(sr_val) * 1e9
                            try: dso.write(f":ACQuire:SRATe {fs_dso_target}")
                            except: pass

                        # To prevent broadened spectrum on the DSO screen, explicitly set Acquire Points and Time Range
                        try:
                            max_samples = self._max_capture_samples()
                            if max_samples:
                                dso.write(f":ACQuire:POINts {int(max_samples)}")
                                if sr_val != "Auto":
                                    time_range = int(max_samples) / fs_dso_target
                                    dso.write(f":TIMebase:RANGe {time_range}")
                        except: pass

                        # Split waveform areas: channel waveform in Area 1, FFT in Area 2
                        if ch_num:
                            dso_type_val = self.dso_type_var.get().lower()
                            try:
                                if "uxr" in dso_type_val or "keysight" in dso_type_val:
                                    # UXR: FFTMagnitude syntax, then split via GRATicule commands (PDF p.621-624)
                                    dso.write(f":FUNCtion1:FFTMagnitude CHANnel{ch_num}")
                                    dso.write(":FUNCtion1:DISPlay ON")
                                    try: dso.write(":DISPlay:LAYout SVERtical")
                                    except: pass
                                    try: dso.write(":DISPlay:GRATicule:AREA2:STATe ON")
                                    except: pass
                                    try: dso.write(f":DISPlay:GRATicule:SETGrat CHN{ch_num},1,1")
                                    except: pass
                                    try: dso.write(":DISPlay:GRATicule:SETGrat FN1,1,2")
                                    except: pass
                                else:
                                    dso.write(f":FUNCtion1:FFT:MAGNitude CHANnel{ch_num}")
                                    dso.write(":FUNCtion1:DISPlay ON")
                                    try: dso.write(":DISPlay:WINDow2:STATE ON")
                                    except: pass
                                    try: dso.write(":DISPlay:WINDow2:SOURce FUNCtion1")
                                    except: pass
                            except:
                                pass
                        self._log("[Conn] DSO hardware initialized and synced.")
                    except Exception as ex:
                        self._log(f"[Conn] Warning: could not set all DSO params ({ex})")
                        
                self._log(f"[Conn] OK: {idn}")
                self.parent.after(0, lambda: self.conn_status_var.set("Connected"))
            except Exception as e:
                self._log(f"[Conn] Failed: {e}")
                self.parent.after(0, lambda: self.conn_status_var.set("Failed"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_capture_live(self) -> None:
        def worker():
            try:
                live = bool(self.live_var.get())
                if live:
                    host = self.host_var.get().strip()
                    timeout_ms = int(_parse_float_input(self.timeout_var.get(), "Timeout"))
                    ch = self.ch_var.get().strip().upper()
                    process_fs = self._requested_process_fs()
                    fallback_fs = process_fs or (256e9 if "keysight" in normalize_dso_type(self.dso_type_var.get()) else 40e9)
                    max_samples = self._max_capture_samples()
                    self._log(f"[Acq] Connecting {host} ch={ch}...")
                    with create_dso_controller(
                        dso_type=normalize_dso_type(self.dso_type_var.get()),
                        host=host, timeout_ms=timeout_ms
                    ) as dso:
                        try:
                            sr_val = self.dso_sr_var.get()
                            if sr_val != "Auto":
                                fs_dso_target = float(sr_val) * 1e9
                                dso.write(f":ACQuire:SRATe {fs_dso_target}")
                                import time; time.sleep(0.5)
                        except Exception as e:
                            self._log(f"[Acq] Could not set sample rate: {e}")
                            
                        t_rx, rx_sig, fs_dso = dso.capture(channel=ch, fallback_fs=fallback_fs, max_samples=max_samples)
                    fs_native = float(fs_dso)
                    rx_sig = np.asarray(rx_sig, dtype=np.float64)
                    if process_fs is not None and not np.isclose(fs_native, process_fs):
                        rx_sig = self._resample_real(rx_sig, fs_native, process_fs)
                        fs_dso = process_fs
                        t_rx = np.arange(len(rx_sig), dtype=np.float64) / fs_dso
                        self._log(f"[Acq] Resampled: {fs_native/1e9:.3f} -> {fs_dso/1e9:.3f} GSa/s")
                    if max_samples is not None and len(rx_sig) > max_samples:
                        rx_sig = rx_sig[:max_samples]
                        t_rx = np.asarray(t_rx)[:max_samples] if len(t_rx) >= max_samples else np.arange(max_samples, dtype=np.float64) / float(fs_dso)
                        self._log(f"[Acq] Truncated to {max_samples:,} samples")
                    self._rx_sig = np.asarray(rx_sig, dtype=np.float64)
                    self._rx_t   = np.asarray(t_rx)
                    self._rx_fs  = float(fs_dso)
                    self.runtime["latest_rx_signal"] = self._rx_sig
                    self.runtime["latest_t"]         = self._rx_t
                    self.runtime["latest_fs"]        = self._rx_fs
                    self._log(f"[Acq] Done: N={len(self._rx_sig):,}, fs={fs_dso/1e9:.3f} GSa/s")
                else:
                    sig = self.runtime.get("latest_rx_signal")
                    if sig is None:
                        self.parent.after(0, lambda: messagebox.showwarning("No data", "No capture in memory. Enable Live DSO."))
                        return
                    self._rx_sig = np.asarray(sig, dtype=np.float64)
                    self._rx_t   = self.runtime.get("latest_t")
                    self._rx_fs  = float(self.runtime.get("latest_fs", 40e9))
                    process_fs = self._requested_process_fs()
                    max_samples = self._max_capture_samples()
                    if process_fs is not None and not np.isclose(self._rx_fs, process_fs):
                        self._rx_sig = self._resample_real(self._rx_sig, self._rx_fs, process_fs)
                        self._rx_fs = process_fs
                        self._rx_t = np.arange(len(self._rx_sig), dtype=np.float64) / self._rx_fs
                    if max_samples is not None and len(self._rx_sig) > max_samples:
                        self._rx_sig = self._rx_sig[:max_samples]
                        self._rx_t = np.asarray(self._rx_t)[:max_samples] if self._rx_t is not None and len(self._rx_t) >= max_samples else np.arange(max_samples, dtype=np.float64) / self._rx_fs
                    self._log(f"[Acq] Loaded from memory: N={len(self._rx_sig):,}")
                self.parent.after(0, self._plot_spectrum_and_time)
            except Exception as e:
                self._log(f"[Acq] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Acquire Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _plot_spectrum_and_time(self) -> None:
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
        self.ax_spec.set_title(f"Spectrum  [0 – {fmax_ghz:.0f} GHz]")
        self.ax_spec.set_xlim(0.0, fmax_ghz)
        if np.any(mask_disp):
            pmax_disp = float(np.max(psd_db[mask_disp]))
            self.ax_spec.set_ylim(pmax_disp - 80.0, pmax_disp + 10.0)
        self.ax_spec.set_axis_on()
        self.ax_spec.grid(True, alpha=0.4)

        # Band markers derived from signal parameters
        try:
            f1_ghz, f2_ghz = self._get_signal_band_ghz()
            fc_ghz = float(self.fc_var.get())
            if bool(self.filter_overlay_var.get()):
                filt = self._fft_bandpass_real(sig, fs, f1_ghz * 1e9, f2_ghz * 1e9)
                ff_hz, ff_db = self._compute_psd_db(filt, fs)
                ff_ghz = ff_hz / 1e9
                ff_mask = ff_ghz <= fmax_ghz
                self.ax_spec.plot(ff_ghz[ff_mask], ff_db[ff_mask], linewidth=0.9,
                                  color="#dc2626", alpha=0.85, label="Filtered")
            self.ax_spec.axvspan(f1_ghz, f2_ghz, alpha=0.15, color="orange",
                                 label=f"Signal [{f1_ghz:.2f}–{f2_ghz:.2f} GHz]")
            self.ax_spec.axvline(f1_ghz, color="orange", lw=1.2, linestyle="--")
            self.ax_spec.axvline(f2_ghz, color="orange", lw=1.2, linestyle="--")
            self.ax_spec.axvline(fc_ghz, color="red", lw=1.0, linestyle=":",
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

        self.fig.tight_layout()
        self.canvas_plot.draw_idle()

    def _on_measure_noise_floor(self) -> None:
        """Store real DSO noise floor from the out-of-band region of the current capture."""
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

            self.noise_floor_var.set(f"Noise Floor: {self._noise_floor_ref_dbmhz:.1f} dBm/Hz  [stored]")
            self._log(f"[NF] DSO noise floor stored: {self._noise_floor_ref_dbmhz:.1f} dBm/Hz")
            self._plot_spectrum_and_time()   # redraw with NF reference line
            messagebox.showinfo("Noise Floor Stored",
                f"DSO Noise Floor: {self._noise_floor_ref_dbmhz:.1f} dBm/Hz\n"
                "(out-of-band median from current capture)\n\n"
                "This replaces the -174 dBm/Hz theoretical value for SNR calculations.")
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
                raise ValueError(f"Band [{f1_ghz:.2f}–{f2_ghz:.2f} GHz] outside signal bandwidth.")
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
            
            p_sig_true_mw = max(p_sig_mw - p_noise_mw, 1e-30)
            p_sig_true_dbm = 10.0 * np.log10(p_sig_true_mw)
            
            snr_db       = 10.0 * np.log10(max(p_sig_true_mw / max(p_noise_mw, 1e-30), 1e-30))

            self.band_pwr_var.set(f"Band Power:  {p_sig_true_dbm:.2f} dBm")
            self.noise_floor_var.set(f"Noise Floor: {nf_label}")
            self.snr_var.set(f"SNR:         {snr_db:.2f} dB")
            
            # Send measurement message to DSO screen
            try:
                live = bool(self.live_var.get())
                if live:
                    host = self.host_var.get().strip()
                    timeout_ms = int(float(self.timeout_var.get()))
                    from functions.dso_functions import create_dso_controller
                    with create_dso_controller("keysight_uxr", host=host, timeout_ms=timeout_ms) as dso:
                        dso.write(f":SYSTem:DSP 'Band Power: {p_sig_true_dbm:.2f} dBm, SNR: {snr_db:.2f} dB'")
            except Exception:
                pass
            self._log(f"[Meas] fc={float(self.fc_var.get()):.2f} GHz  "
                      f"sr={float(self.sr_var.get()):.3f} GHz → "
                      f"P={p_sig_dbm:.2f} dBm  NF={nf_label}  SNR={snr_db:.2f} dB")

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

    def _on_isac_dechirp_range(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire a signal first.")
            return

        def worker():
            try:
                meta = self._load_tx_payload_for_isac()
                if meta is None:
                    raise ValueError("No TX reference found. Generate or download the TX signal first.")

                sig = np.asarray(self._rx_sig, dtype=np.float64)
                fs_rx = float(self._rx_fs)
                fs_ref = float(meta.get("fs", fs_rx))
                if_freq = float(meta.get("if_freq", 0.0))
                mode = str(meta.get("mode", "Real IF"))
                tx_ref = np.asarray(meta.get("tx_signal"), dtype=np.complex128).reshape(-1)
                tx_mat = np.asarray(meta.get("tx_bb_matrix", []), dtype=np.complex128)
                base_chirp = np.asarray(meta.get("base_chirp", []), dtype=np.complex128).reshape(-1)
                n_chirps = int(meta.get("n_chirps", tx_mat.shape[0] if tx_mat.ndim == 2 else 1))
                n_sym = int(meta.get("n_sym_per_chirp", 0))
                sps = int(meta.get("sps", 0))
                pts_per_chirp = int(tx_mat.shape[1] if tx_mat.ndim == 2 and tx_mat.shape[1] > 0 else n_sym * sps)
                if len(tx_ref) == 0 or pts_per_chirp <= 0:
                    raise ValueError("TX reference is incomplete. Regenerate the TX signal.")

                t_rx = np.arange(len(sig), dtype=np.float64) / fs_rx
                if mode == "Real IF" and if_freq > 0:
                    rx_bb = sig * np.exp(-1j * 2.0 * np.pi * if_freq * t_rx) * 2.0
                else:
                    rx_bb = sig.astype(np.complex128)
                if not np.isclose(fs_rx, fs_ref):
                    rx_bb = fft_resample_complex(rx_bb, fs_in=fs_rx, fs_out=fs_ref)

                template = tx_ref[:min(len(tx_ref), len(rx_bb))]
                if len(rx_bb) < len(template):
                    raise ValueError("Capture is shorter than TX reference.")
                corr = fftconvolve(rx_bb, np.conj(template[::-1]), mode="valid")
                frame_start = int(np.argmax(np.abs(corr))) if len(corr) else 0

                valid_chirps = min(n_chirps, max(1, (len(rx_bb) - frame_start) // pts_per_chirp))
                total_pts = valid_chirps * pts_per_chirp
                rx_frame = rx_bb[frame_start:frame_start + total_pts]
                if len(rx_frame) < total_pts:
                    rx_frame = np.pad(rx_frame, (0, total_pts - len(rx_frame)))
                rx_mat = rx_frame.reshape(valid_chirps, pts_per_chirp)

                if tx_mat.ndim == 2 and tx_mat.shape[1] == pts_per_chirp:
                    tx_cmp = tx_mat[:valid_chirps]
                else:
                    tx_cmp = tx_ref[:total_pts].reshape(valid_chirps, pts_per_chirp)

                corr_acc = None
                lags = None
                for i in range(valid_chirps):
                    ci = np.abs(fftconvolve(rx_mat[i], np.conj(tx_cmp[i][::-1]), mode="full"))
                    corr_acc = ci if corr_acc is None else corr_acc + ci
                    lags = np.arange(-(len(tx_cmp[i]) - 1), len(rx_mat[i]), dtype=np.int64)
                prof = corr_acc / max(valid_chirps, 1)
                valid = lags >= 0
                rng = lags[valid].astype(np.float64) * 3e8 / (2.0 * fs_ref)
                prof_db = 20.0 * np.log10(prof[valid] / (np.max(prof[valid]) + 1e-15) + 1e-15)

                if len(base_chirp) == pts_per_chirp:
                    dechirped = (rx_mat * np.conj(base_chirp)[np.newaxis, :]).reshape(-1)
                else:
                    dechirped = rx_mat.reshape(-1)

                est_idx = int(np.argmax(prof[valid])) if np.any(valid) else 0
                est_range = float(rng[est_idx]) if len(rng) > est_idx else float("nan")
                self._log(f"[ISAC] frame={frame_start:,}  chirps={valid_chirps}  est_range={est_range:.4g} m")
                self.parent.after(0, lambda: self._show_isac_range_result(dechirped, fs_ref, rng, prof_db, est_range))
            except Exception as e:
                self._log(f"[ISAC] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("ISAC De-chirp Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _show_isac_range_result(self, dechirped: np.ndarray, fs_ref: float,
                                rng: np.ndarray, prof_db: np.ndarray, est_range: float) -> None:
        self._plot_spectrum_and_time()

        n_plot = min(len(dechirped), 4000)
        t_plot = np.arange(n_plot, dtype=np.float64) / fs_ref * 1e9
        self.ax_time.cla()
        self.ax_time.plot(t_plot, np.real(dechirped[:n_plot]), linewidth=0.7, color="#9333ea")
        self.ax_time.set_xlabel("Time (ns)")
        self.ax_time.set_ylabel("I amplitude")
        self.ax_time.set_title("De-chirped ISAC Signal")
        self.ax_time.grid(True, alpha=0.4)

        self.ax_const.cla()
        max_x = max(10.0, float(np.nanmax(rng)) if len(rng) else 10.0)
        show = rng <= max_x
        self.ax_const.plot(rng[show], prof_db[show], color="#0f766e", linewidth=1.2)
        if np.isfinite(est_range):
            self.ax_const.axvline(est_range, color="#dc2626", linestyle="--", label=f"Peak {est_range:.3g} m")
            self.ax_const.legend(fontsize=8)
        self.ax_const.set_xlabel("Range (m)")
        self.ax_const.set_ylabel("Magnitude (dB)")
        self.ax_const.set_title("ISAC Range Profile")
        self.ax_const.grid(True, alpha=0.35)
        self.fig.tight_layout()
        self.canvas_plot.draw_idle()

    def _on_demodulate(self) -> None:
        if self._rx_sig is None:
            messagebox.showwarning("No data", "Acquire a signal first.")
            return
        def worker():
            try:
                sig  = self._rx_sig.copy()
                fs   = self._rx_fs
                mod  = self.demod_mod_var.get().strip()
                fc   = float(self.fc_var.get()) * 1e9
                sr   = float(self.sr_var.get()) * 1e9
                beta = float(self.demod_beta_var.get())
                span = max(4, int(float(self.demod_span_var.get())))
                bps  = self._bits_per_sym(mod)
                M    = 2 ** bps

                pl = self._load_tx_payload_for_isac()
                tx_ref = None
                if pl:
                    tx_ref = pl.get("qam_symbols", pl.get("syms", None))
                if tx_ref is None:
                    self.parent.after(0, lambda: messagebox.showwarning("No TX Reference", "Please generate the TX signal first (Run AWG/Sim) before demodulating."))
                    return
                chirp_sig = pl.get("base_chirp", None) if pl else None
                
                # Use 10-step DSP chain
                syms_eq, syms_ideal, evm_db = lfm_qam_rx_dsp_chain(
                    rx_signal=sig,
                    fs=fs,
                    baud_rate=sr,
                    if_freq=fc,
                    chirp_signal=chirp_sig,
                    tx_ref_symbols=tx_ref,
                    rrc_alpha=beta,
                    rx_mode="Mixer",
                    sc_fde_enable=self.sc_fde_enable_var.get(),
                    sc_fde_taps=max(1, int(_parse_float_input(self.sc_fde_taps_var.get(), "SC-FDE Taps")))
                )
                
                if syms_eq is None or syms_ideal is None:
                    self._log("[Demod] Demodulation failed (no sync or metric too low).")
                    return
                
                evm_rms = 10 ** (evm_db / 20.0)
                evm_pct = evm_rms * 100.0
                
                # BER
                n_sym = len(syms_eq)
                uniq_re = np.unique(np.real(syms_ideal))
                min_sep = float(np.min(np.diff(uniq_re)) if len(uniq_re) > 1 else 1.0)
                n_err   = int(np.sum(np.abs(syms_eq - syms_ideal) > 0.5 * min_sep))
                ber_est = n_err / max(n_sym * bps, 1)

                self._log(f"[Demod] {mod}  fc={fc/1e9:.2f} GHz  sr={sr/1e9:.3f} GHz  "
                          f"N={n_sym}  EVM={evm_db:.2f} dB ({evm_pct:.1f}%)  BER~{ber_est:.2e}")
                self.parent.after(0, lambda: self._show_demod_result(
                    syms_eq, syms_ideal, evm_db, evm_pct, ber_est, n_sym))
            except Exception as e:
                self._log(f"[Demod] Error: {e}")
                self.parent.after(0, lambda m=str(e): messagebox.showerror("Demodulate Error", m))
        threading.Thread(target=worker, daemon=True).start()

    def _show_demod_result(self, syms_eq: np.ndarray, syms_ideal: np.ndarray,
                           evm_db: float, evm_pct: float, ber: float, n_sym: int) -> None:
        self.evm_var.set(f"EVM:         {evm_db:.2f} dB  ({evm_pct:.1f} %)")
        self.ber_var.set(f"BER:         {ber:.2e}")
        self.sym_count_var.set(f"Symbols:     {n_sym:,}")

        self._const_drawn = True
        self.ax_const.cla()
        n_show = min(len(syms_eq), 3000)
        self.ax_const.scatter(np.real(syms_eq[:n_show]), np.imag(syms_eq[:n_show]),
                              s=6, alpha=0.5, color="#2563eb", label="RX")
        ideal_pts = np.unique(syms_ideal)
        self.ax_const.scatter(np.real(ideal_pts), np.imag(ideal_pts),
                              s=60, marker="x", color="red", linewidths=1.5, label="Ideal")
        self.ax_const.set_title(f"Constellation   EVM={evm_db:.2f} dB   BER~{ber:.2e}")
        self.ax_const.set_xlabel("In-phase")
        self.ax_const.set_ylabel("Quadrature")
        self.ax_const.set_aspect("equal", adjustable="box")
        self.ax_const.grid(True, alpha=0.35)
        self.ax_const.legend(fontsize=7)
        self.fig.tight_layout()
        self.canvas_plot.draw_idle()

def main() -> None:
    root = tk.Tk()
    UnifiedApp(root)
    root.mainloop()

class UnifiedApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ISAC Unified GUI (TX + DSO + Simulation)")
        self.root.geometry("1700x1100")
        self.root.minsize(1450, 900)
        apply_unified_style(self.root)

        self.runtime: dict = {}
        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        tab_tx_sim = ttk.Frame(notebook)
        tab_dso = ttk.Frame(notebook)
        notebook.add(tab_tx_sim, text="TX Design & Simulation")
        notebook.add(tab_dso, text="DSO Live Capture")

        tx_sim_paned = ttk.PanedWindow(tab_tx_sim, orient=tk.HORIZONTAL)
        tx_sim_paned.pack(fill=tk.BOTH, expand=True)

        # Single sidebar on the left for all controls
        controls_left = ttk.Frame(tx_sim_paned)
        # Main area on the right for all plots
        plots_right = ttk.Frame(tx_sim_paned)
        
        tx_sim_paned.add(controls_left, weight=1)
        tx_sim_paned.add(plots_right, weight=4)
        
        awg_control_frame = ttk.Frame(controls_left)
        awg_control_frame.pack(fill=tk.X)
        
        sim_control_frame = ttk.Frame(controls_left)
        sim_control_frame.pack(fill=tk.X, pady=(10, 0))

        self.tx_sim_panel = IsacTxSimPanel(awg_control_frame, runtime=self.runtime, on_tx_generated=self._on_reference_npz_ready)
        self.photonic_sim_panel = PhotonicIsacSimPanel(
            parent=sim_control_frame,
            plot_parent=plots_right,
            awg_source=self.tx_sim_panel,
            show_awg_params=False,
        )
        self.dso_panel = DsoPanel(tab_dso, runtime=self.runtime)

    def _on_reference_npz_ready(self, file_path: str) -> None:
        self.dso_panel._log(f"[App] Internal TX Reference Updated: {file_path}")
        
        # Auto-synchronize AWG parameters to DSO
        try:
            self.dso_panel.fc_var.set(self.tx_sim_panel.rf_var.get())
            self.dso_panel.sr_var.set(self.tx_sim_panel.symbol_rate_var.get())
            self.dso_panel.demod_mod_var.set(self.tx_sim_panel.modulation_var.get())
            
            # Sync Channel automatically
            awg_ch = self.tx_sim_panel.ch_var.get().strip()
            if awg_ch:
                first_ch = awg_ch.split(',')[0].strip()
                if first_ch.isdigit():
                    self.dso_panel.ch_var.set(f"C{first_ch}")

            # Auto-apply DSO config to hardware
            self.dso_panel._on_test_connection()
            
            # Auto-measure if connected, or at least log sync success
            self.dso_panel._log("[App] AWG parameters synced to DSO panel automatically.")
        except Exception as e:
            self.dso_panel._log(f"[App] Sync error: {e}")

if __name__ == "__main__":
    main()
