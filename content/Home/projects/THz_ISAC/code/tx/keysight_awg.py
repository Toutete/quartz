from __future__ import annotations

import numpy as np
import pyvisa
from pyvisa import VisaIOError


def open_socket(addr: str, timeout_ms: int = 5000):
    """Open VISA socket using available backend (@ivi -> @py)."""
    rm = None
    for backend in ("@ivi", "@py"):
        try:
            rm = pyvisa.ResourceManager(backend)
            break
        except Exception:
            continue
    if rm is None:
        raise RuntimeError("No VISA backend available. Install pyvisa-py.")

    try:
        inst = rm.open_resource(addr, open_timeout=timeout_ms)
    except TypeError:
        inst = rm.open_resource(addr)

    inst.timeout = timeout_ms
    inst.chunk_size = 1024 * 64
    inst.write_termination = "\n"
    inst.read_termination = "\n"
    return rm, inst


def open_inst(visa_addr: str, timeout_ms: int = 2000, verify_identity: bool = False):
    """Open AWG connection and optionally verify IDN."""
    rm = None
    inst = None
    try:
        rm, inst = open_socket(visa_addr, timeout_ms=timeout_ms)
        print(f"Connection established: {visa_addr}")
        if verify_identity:
            try:
                idn = inst.query("*IDN?")
                print(f"Device ID: {idn.strip()}")
            except VisaIOError as e:
                print(f"Warning: *IDN? failed: {e}")
        return inst, rm
    except Exception as e:
        print(f"Connection failed: {repr(e)}")
        try:
            if inst is not None:
                inst.close()
        except Exception:
            pass
        try:
            if rm is not None:
                rm.close()
        except Exception:
            pass
        return None, None


def check_err(inst, max_reads: int = 20) -> None:
    for _ in range(max_reads):
        err = inst.query(":SYST:ERR?").strip()
        if err.startswith("+0") or "No error" in err:
            return
        print("SCPI Error:", err)


def stop_run(inst) -> bool:
    try:
        inst.write(":ABOR")
    except VisaIOError as e:
        print("ABORt failed:", e)
        return False
    return True


def float_to_int8(x_float: np.ndarray) -> np.ndarray:
    x = np.clip(x_float, -1.0, 1.0)
    x_i8 = np.round(x * 127.0).astype(np.int16)
    x_i8 = np.clip(x_i8, -127, 127).astype(np.int8)
    return x_i8


def write_awg(inst_awg, ch_list: list[int], wave_i8: np.ndarray) -> None:
    num_ch = len(ch_list)
    rows, cols = wave_i8.shape
    if num_ch != cols:
        raise ValueError(f"Channel mismatch: len(ch_list)={num_ch}, wave_i8 columns={cols}")

    prev_timeout = inst_awg.timeout
    inst_awg.timeout = 60000

    for ch in ch_list:
        inst_awg.write(f":TRAC{ch}:DEL:ALL")
        inst_awg.write(f":TRAC{ch}:DEF {1},{rows},0")
    check_err(inst_awg)

    for col_idx, ch in enumerate(ch_list):
        data_1d = wave_i8[:, col_idx]
        inst_awg.write_binary_values(
            f":TRAC{ch}:DATA {1},0,",
            data_1d,
            datatype="b",
            is_big_endian=False,
        )

    check_err(inst_awg)
    inst_awg.timeout = prev_timeout


def adjust_waveform_length(wave: np.ndarray, method: str = "fft") -> np.ndarray:
    """Adjust waveform length for AWG memory constraints and granularity."""
    min_len = 1024
    max_len = 2**19
    gran = 128

    wave = np.asarray(wave)
    if wave.ndim == 1:
        n = wave.shape[0]
    elif wave.ndim == 2:
        n = wave.shape[0]
    else:
        raise ValueError("wave must be 1D or 2D")

    if n < min_len:
        repeat_factor = int(np.ceil(min_len / n))
        if wave.ndim == 1:
            wave = np.tile(wave, repeat_factor)
        else:
            wave = np.tile(wave, (repeat_factor, 1))
        n = wave.shape[0]

    target = ((n + gran - 1) // gran) * gran
    if target > max_len:
        target = max_len
        wave = wave[:target] if wave.ndim == 1 else wave[:target, :]
        n = target

    if method.lower() == "pad":
        if target > n:
            pad_len = target - n
            if wave.ndim == 1:
                wave = np.concatenate([wave, np.zeros(pad_len, dtype=wave.dtype)])
            else:
                pad = np.zeros((pad_len, wave.shape[1]), dtype=wave.dtype)
                wave = np.vstack([wave, pad])
        return wave

    if method.lower() == "fft":
        def fft_resize_1d(x: np.ndarray, target_len: int) -> np.ndarray:
            x = np.asarray(x)
            cur = len(x)
            if target_len == cur:
                return x.astype(np.complex128) if np.iscomplexobj(x) else x.astype(np.float64)

            x_freq = np.fft.fftshift(np.fft.fft(x))
            if target_len > cur:
                pad = target_len - cur
                left = pad // 2
                right = pad - left
                x_freq = np.pad(x_freq, (left, right), mode="constant")
            else:
                cut = cur - target_len
                left = cut // 2
                right = cut - left
                x_freq = x_freq[left : cur - right]

            y = np.fft.ifft(np.fft.ifftshift(x_freq))
            if not np.iscomplexobj(x):
                y = np.real(y)

            p_in = np.mean(np.abs(x) ** 2) if cur > 0 else 0.0
            p_out = np.mean(np.abs(y) ** 2) if target_len > 0 else 0.0
            if p_in > 0 and p_out > 0:
                y = y * np.sqrt(p_in / p_out)
            return y

        if wave.ndim == 1:
            return fft_resize_1d(wave, target)

        cols = [fft_resize_1d(wave[:, k], target).reshape(-1, 1) for k in range(wave.shape[1])]
        return np.hstack(cols)

    raise ValueError("method must be 'pad' or 'fft'")


def Keysight_AWG_Write(
    AWG_sig,
    CH_list,
    AWG_ADDR: str = "TCPIP0::K-M9537A-40228::60007::SOCKET",
    SEG: int = 1,
    FS: float = 120e9,
    VPP: float = 0.1,
    length_method: str = "fft",
    turn_off_unused: bool = False,
):
    """Download waveform to Keysight M8194A and start output."""
    _ = SEG  # kept for API compatibility

    awg_sig = np.asarray(AWG_sig)
    if awg_sig.ndim == 1:
        awg_sig = awg_sig.reshape(-1, 1)
    if awg_sig.ndim != 2:
        raise ValueError(f"AWG_sig must be 1D or 2D, got ndim={awg_sig.ndim}")

    if not isinstance(CH_list, (list, tuple)) or len(CH_list) == 0:
        raise ValueError("CH_list must be a non-empty list/tuple of channel numbers.")

    n, n_ch = awg_sig.shape
    _ = n
    if len(CH_list) != n_ch:
        raise ValueError(f"Channel mismatch: len(CH_list)={len(CH_list)}, AWG_sig columns={n_ch}")

    inst_awg, rm_awg = open_inst(AWG_ADDR, timeout_ms=60000)
    if inst_awg is None:
        raise RuntimeError("AWG connection failed")

    try:
        stop_run(inst_awg)
        check_err(inst_awg)

        awg_sig2 = adjust_waveform_length(awg_sig, method=length_method)
        wave_i8 = float_to_int8(awg_sig2)

        inst_awg.write(f":FREQ:RAST {FS}")
        check_err(inst_awg)

        write_awg(inst_awg, list(CH_list), wave_i8)
        check_err(inst_awg)

        for ch in [1, 2, 3, 4]:
            if ch in CH_list:
                inst_awg.write(f":VOLT{ch} {VPP}")
                inst_awg.write(f":OUTP{ch} ON")
            elif turn_off_unused:
                inst_awg.write(f":OUTP{ch} OFF")

        check_err(inst_awg)
        inst_awg.write(":INIT:IMM")
        check_err(inst_awg)
    finally:
        try:
            inst_awg.close()
        except Exception:
            pass
        try:
            if rm_awg is not None:
                rm_awg.close()
        except Exception:
            pass
