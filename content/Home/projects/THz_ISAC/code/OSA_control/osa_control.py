from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import pyvisa
except ImportError as exc:  # pragma: no cover - handled at runtime
    pyvisa = None
    _PYVISA_IMPORT_ERROR = exc
else:
    _PYVISA_IMPORT_ERROR = None


C_LIGHT = 299_792_458.0


@dataclass(slots=True)
class OSASweepConfig:
    center_wavelength_nm: float = 1550.1
    span_nm: float = 1.0
    resolution_nm: float | None = 0.02
    resource: str = "GPIB0::1::INSTR"
    trace: str = "TRA"
    model: str | None = None
    single_sweep: bool = True
    wait_s: float = 5.0
    timeout_ms: int = 20_000
    backend: str | None = None
    resolution_command: str | None = None


def center_wavelength_from_frequency(center_frequency_thz: float) -> float:
    return C_LIGHT / (center_frequency_thz * 1e12) * 1e9


def center_frequency_from_wavelength(center_wavelength_nm: float) -> float:
    return C_LIGHT / (center_wavelength_nm * 1e-9) * 1e-12


def wavelength_to_frequency_thz(wavelength_nm: np.ndarray) -> np.ndarray:
    wl_m = np.asarray(wavelength_nm, dtype=np.float64) * 1e-9
    return (C_LIGHT / wl_m) * 1e-12


def frequency_to_wavelength_nm(frequency_thz: np.ndarray) -> np.ndarray:
    freq_hz = np.asarray(frequency_thz, dtype=np.float64) * 1e12
    return (C_LIGHT / freq_hz) * 1e9


def resolve_sweep_config(
    *,
    center_wavelength_nm: float | None = None,
    center_frequency_thz: float | None = None,
    span_nm: float | None = None,
    span_ghz: float | None = None,
    resolution_nm: float | None = None,
    resolution_ghz: float | None = None,
    resource: str = "GPIB0::1::INSTR",
    trace: str = "TRA",
    model: str | None = None,
    single_sweep: bool = True,
    wait_s: float = 5.0,
    timeout_ms: int = 20_000,
    backend: str | None = None,
    resolution_command: str | None = None,
) -> OSASweepConfig:
    if center_wavelength_nm is None and center_frequency_thz is None:
        center_wavelength_nm = 1550.1

    if center_wavelength_nm is None:
        center_wavelength_nm = center_wavelength_from_frequency(float(center_frequency_thz))

    if span_nm is None and span_ghz is None:
        span_nm = 1.0

    if span_nm is None:
        span_ghz = float(span_ghz)
        center_frequency_thz = center_frequency_from_wavelength(float(center_wavelength_nm))
        freq_span_thz = span_ghz * 1e-3
        f_lo = max(center_frequency_thz - 0.5 * freq_span_thz, 1e-9)
        f_hi = max(center_frequency_thz + 0.5 * freq_span_thz, 1e-9)
        wl_lo = center_wavelength_from_frequency(f_hi)
        wl_hi = center_wavelength_from_frequency(f_lo)
        span_nm = abs(wl_hi - wl_lo)
        
    if resolution_nm is None and resolution_ghz is not None:
        resolution_ghz = float(resolution_ghz)
        center_frequency_thz = center_frequency_from_wavelength(float(center_wavelength_nm))
        # df = (c / lambda^2) * dlambda => dlambda = df * lambda^2 / c
        # res_nm = (res_ghz * 1e9) * (center_wavelength_nm * 1e-9)^2 / C_LIGHT * 1e9
        # Which simplifies to:
        res_nm = (resolution_ghz * 1e9) * ((center_wavelength_nm * 1e-9)**2) / C_LIGHT * 1e9
        resolution_nm = res_nm

    return OSASweepConfig(
        center_wavelength_nm=float(center_wavelength_nm),
        span_nm=float(span_nm),
        resolution_nm=None if resolution_nm is None else float(resolution_nm),
        resource=resource,
        trace=trace,
        model=model,
        single_sweep=single_sweep,
        wait_s=float(wait_s),
        timeout_ms=int(timeout_ms),
        backend=backend,
        resolution_command=resolution_command,
    )


def open_osa(resource: str, backend: str | None = None, timeout_ms: int = 20_000):
    if pyvisa is None:  # pragma: no cover - runtime dependency guard
        raise ImportError(
            "pyvisa is required for OSA control"
        ) from _PYVISA_IMPORT_ERROR

    rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
    inst = rm.open_resource(resource)
    inst.timeout = timeout_ms
    inst.read_termination = "\n"
    inst.write_termination = "\n"
    try:
        inst.chunk_size = 50_000
    except Exception:
        pass
    return rm, inst


def detect_model(inst) -> str:
    try:
        return str(inst.query("*IDN?")).strip()
    except Exception:
        return ""


def _write_if_possible(inst, command: str) -> None:
    inst.write(command)


def configure_osa(inst, config: OSASweepConfig) -> None:
    model = (config.model or detect_model(inst)).upper()

    if "AQ6370" in model:
        _write_if_possible(inst, f":sens:wav:cent {config.center_wavelength_nm:.6f}nm")
        _write_if_possible(inst, f":sens:wav:span {config.span_nm:.6f}nm")
        if config.resolution_nm is not None:
            if config.resolution_command:
                _write_if_possible(inst, config.resolution_command.format(value=config.resolution_nm))
            else:
                _write_if_possible(inst, f":sens:bwid {config.resolution_nm:.6f}nm")
    elif "AQ6317" in model:
        _write_if_possible(inst, f"CTRWL{config.center_wavelength_nm:.6f}")
        _write_if_possible(inst, f"SPAN{config.span_nm:.6f}")
        _write_if_possible(inst, "SMPL10001") # Increase points for fine resolution
        if config.resolution_nm is not None:
            if config.resolution_command:
                _write_if_possible(inst, config.resolution_command.format(value=config.resolution_nm))
            else:
                _write_if_possible(inst, f"RESL{config.resolution_nm:.3f}")
                
        if config.single_sweep:
            _write_if_possible(inst, "SGL")
            
    else:
        _write_if_possible(inst, f":sens:wav:cent {config.center_wavelength_nm:.6f}nm")
        _write_if_possible(inst, f":sens:wav:span {config.span_nm:.6f}nm")
        if config.resolution_nm is not None and config.resolution_command:
            _write_if_possible(inst, config.resolution_command.format(value=config.resolution_nm))

        if config.single_sweep:
            _write_if_possible(inst, ":init:smode 1")
            _write_if_possible(inst, "*CLS")
            _write_if_possible(inst, ":init")


def _parse_trace_csv(raw: str) -> np.ndarray:
    data = np.fromstring(raw.replace("\n", ","), sep=",", dtype=np.float64)
    return data[np.isfinite(data)]


def acquire_spectrum(inst, trace: str = "TRA") -> tuple[np.ndarray, np.ndarray]:
    model = detect_model(inst)
    if "AQ6317" in model.upper():
        trace_id = trace[-1].upper() if trace.startswith("TR") else "A"
        _write_if_possible(inst, "FMT1") # Ensure ASCII format
        x_raw = inst.query(f"WDAT {trace_id}").strip()
        y_raw = inst.query(f"LDAT {trace_id}").strip()
        
        def parse_ando(raw):
            parts = raw.replace("\n", ",").split(",")
            if len(parts) > 1:
                return np.array([float(p) for p in parts[1:] if p.strip()], dtype=np.float64)
            return np.array([], dtype=np.float64)
            
        wavelength_nm = parse_ando(x_raw)
        power_dbm = parse_ando(y_raw)
    else:
        x_raw = inst.query(f":TRAC:DATA:X? {trace}")
        y_raw = inst.query(f":TRAC:DATA:Y? {trace}")
        wavelength_nm = _parse_trace_csv(x_raw)
        power_dbm = _parse_trace_csv(y_raw)
        
    n = min(len(wavelength_nm), len(power_dbm))
    return wavelength_nm[:n], power_dbm[:n]


def plot_osa_spectrum(
    wavelength_nm: np.ndarray,
    power_dbm: np.ndarray,
    *,
    center_wavelength_nm: float | None = None,
    title: str = "Optical Spectrum",
    show_wavelength_axis: bool = True,
    show_center_marker: bool = True,
    linewidth: float = 0.8,
    color: str = "#1d4ed8",
):
    import matplotlib.pyplot as plt

    wavelength_nm = np.asarray(wavelength_nm, dtype=np.float64).reshape(-1)
    power_dbm = np.asarray(power_dbm, dtype=np.float64).reshape(-1)
    n = min(len(wavelength_nm), len(power_dbm))
    if n == 0:
        raise ValueError("No OSA trace data available")

    wavelength_nm = wavelength_nm[:n]
    power_dbm = power_dbm[:n]
    freq_thz = wavelength_to_frequency_thz(wavelength_nm)
    order = np.argsort(freq_thz)
    freq_thz = freq_thz[order]
    power_dbm = power_dbm[order]
    wavelength_nm = wavelength_nm[order]

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(freq_thz, power_dbm, linewidth=linewidth, color=color)
    ax.set_title(title)
    ax.set_xlabel("Frequency [THz]")
    ax.set_ylabel("Power [dBm]")
    ax.grid(True, alpha=0.35)

    if show_center_marker and center_wavelength_nm is not None:
        center_freq_thz = center_frequency_from_wavelength(center_wavelength_nm)
        ax.axvline(center_freq_thz, color="#dc2626", linestyle="--", linewidth=1.0, label="Center")
        ax.legend(loc="best", fontsize=8)

    if show_wavelength_axis:
        secax = ax.secondary_xaxis(
            "top",
            functions=(lambda f: frequency_to_wavelength_nm(f), lambda w: wavelength_to_frequency_thz(w)),
        )
        secax.set_xlabel("Wavelength [nm]")

    peak_idx = int(np.argmax(power_dbm))
    ax.annotate(
        f"Peak {freq_thz[peak_idx]:.3f} THz\n{power_dbm[peak_idx]:.1f} dBm",
        xy=(freq_thz[peak_idx], power_dbm[peak_idx]),
        xytext=(10, 10),
        textcoords="offset points",
        fontsize=8,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="#94a3b8"),
    )
    fig.tight_layout()
    return fig, ax


def get_osa_spectrum(
    *,
    center_wavelength_nm: float | None = None,
    center_frequency_thz: float | None = None,
    span_nm: float | None = None,
    span_ghz: float | None = None,
    resolution_nm: float | None = None,
    resource: str = "GPIB0::1::INSTR",
    trace: str = "TRA",
    model: str | None = None,
    single_sweep: bool = True,
    wait_s: float = 5.0,
    timeout_ms: int = 20_000,
    backend: str | None = None,
    resolution_command: str | None = None,
    save_path: str | Path | None = None,
    show: bool = True,
):
    config = resolve_sweep_config(
        center_wavelength_nm=center_wavelength_nm,
        center_frequency_thz=center_frequency_thz,
        span_nm=span_nm,
        span_ghz=span_ghz,
        resolution_nm=resolution_nm,
        resource=resource,
        trace=trace,
        model=model,
        single_sweep=single_sweep,
        wait_s=wait_s,
        timeout_ms=timeout_ms,
        backend=backend,
        resolution_command=resolution_command,
    )
    rm, inst = open_osa(config.resource, backend=config.backend, timeout_ms=config.timeout_ms)
    try:
        configure_osa(inst, config)
        if config.wait_s > 0:
            import time

            time.sleep(config.wait_s)
        wavelength_nm, power_dbm = acquire_spectrum(inst, trace=config.trace)
    finally:
        try:
            inst.close()
        finally:
            try:
                rm.close()
            except Exception:
                pass

    fig, ax = plot_osa_spectrum(
        wavelength_nm,
        power_dbm,
        center_wavelength_nm=config.center_wavelength_nm,
        title="Optical Spectrum vs Frequency",
    )

    if save_path is not None:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    if show:
        import matplotlib.pyplot as plt

        plt.show()

    freq_thz = wavelength_to_frequency_thz(wavelength_nm)
    return {
        "config": config,
        "wavelength_nm": wavelength_nm,
        "frequency_thz": freq_thz,
        "power_dbm": power_dbm,
        "figure": fig,
        "axes": ax,
    }


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Acquire and plot an OSA trace as frequency vs power.")
    parser.add_argument("--resource", default="GPIB0::1::INSTR", help="VISA resource string")
    parser.add_argument("--model", default=None, help="Instrument model hint, e.g. AQ6370 or AQ6317")
    parser.add_argument("--center-wavelength-nm", type=float, default=None)
    parser.add_argument("--center-frequency-thz", type=float, default=None)
    parser.add_argument("--span-nm", type=float, default=None)
    parser.add_argument("--span-ghz", type=float, default=None)
    parser.add_argument("--resolution-nm", type=float, default=0.02)
    parser.add_argument("--resolution-command", default=None, help="Custom SCPI command, use {value} placeholder")
    parser.add_argument("--trace", default="TRA")
    parser.add_argument("--backend", default=None, help="PyVISA backend, e.g. @py or @ivi")
    parser.add_argument("--wait-s", type=float, default=5.0)
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--save", default=None, help="Optional output image path")
    parser.add_argument("--no-show", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    get_osa_spectrum(
        center_wavelength_nm=args.center_wavelength_nm,
        center_frequency_thz=args.center_frequency_thz,
        span_nm=args.span_nm,
        span_ghz=args.span_ghz,
        resolution_nm=args.resolution_nm,
        resource=args.resource,
        trace=args.trace,
        model=args.model,
        single_sweep=True,
        wait_s=args.wait_s,
        timeout_ms=args.timeout_ms,
        backend=args.backend,
        resolution_command=args.resolution_command,
        save_path=args.save,
        show=not args.no_show,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())