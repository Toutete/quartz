"""
Real DSO SCPI controllers.
  - KeysightUxrDso  : raw SCPI socket on port 5025 (Keysight UXR / MSOX)
  - LecroyVicpDso   : VICP protocol on port 1861  (LeCroy / Teledyne-LeCroy MAUI)
  - DummyDsoController : offline testing only, NOT returned for real DSO types
"""
from __future__ import annotations

import socket
import struct
import time

import numpy as np
from scipy.signal import resample as _sp_resample

# ── Constants ────────────────────────────────────────────────────────────────
KEYSIGHT_SCPI_PORT = 5025
LECROY_VICP_PORT   = 1861
_RECV_BUF          = 131072        # 128 kB per recv()


# ── Low-level helpers ────────────────────────────────────────────────────────
def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), _RECV_BUF))
        if not chunk:
            raise RuntimeError(
                f"Socket closed: expected {n} B, received {len(buf)} B"
            )
        buf.extend(chunk)
    return bytes(buf)


def _parse_ieee488_block(raw: bytes) -> bytes:
    """Strip '#<d><len>' header and return payload bytes only."""
    idx = raw.find(b"#")
    if idx < 0:
        return raw
    d = raw[idx + 1] - ord("0")
    if d <= 0 or idx + 2 + d > len(raw):
        return raw[idx + 2:]
    n = int(raw[idx + 2 : idx + 2 + d])
    start = idx + 2 + d
    return raw[start : start + n]


def _extract_wavedesc(raw: bytes) -> bytes:
    """Locate the WAVEDESC binary structure inside a LeCroy response."""
    idx = raw.find(b"WAVEDESC")
    if idx >= 0:
        return raw[idx:]
    block = _parse_ieee488_block(raw)
    idx2 = block.find(b"WAVEDESC")
    return block[idx2:] if idx2 >= 0 else block


def _norm_keysight_ch(ch: str) -> str:
    ch = ch.upper().strip()
    if ch.startswith("C") and ch[1:].isdigit():
        return f"CHAN{ch[1:]}"
    if ch.isdigit():
        return f"CHAN{ch}"
    if ch.startswith("CHAN"):
        return ch
    return "CHAN1"


def _norm_lecroy_ch(ch: str) -> str:
    ch = ch.upper().strip()
    if ch.startswith("CHAN") and ch[4:].isdigit():
        return f"C{ch[4:]}"
    if ch.isdigit():
        return f"C{ch}"
    if ch.startswith("C") and ch[1:].isdigit():
        return ch
    return "C1"


# ── Keysight UXR / MSOX (SCPI socket, port 5025) ────────────────────────────
class KeysightUxrDso:
    """Keysight UXR-series oscilloscope via raw SCPI on port 5025."""

    def __init__(self, host: str, timeout_ms: int = 30_000) -> None:
        self.host      = host
        self.timeout_s = timeout_ms / 1000.0
        self._sock: socket.socket | None = None

    # context manager ─────────────────────────────────────────────────────────
    def __enter__(self) -> "KeysightUxrDso":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout_s)
        self._sock.connect((self.host, KEYSIGHT_SCPI_PORT))
        # drain any unsolicited banner
        self._sock.settimeout(0.4)
        try:
            self._sock.recv(_RECV_BUF)
        except Exception:
            pass
        self._sock.settimeout(self.timeout_s)
        return self

    def __exit__(self, *_) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # SCPI primitives ─────────────────────────────────────────────────────────
    def write(self, cmd: str, delay: float = 0.05) -> None:
        assert self._sock
        self._sock.sendall((cmd + "\n").encode("ascii"))
        if delay > 0:
            time.sleep(delay)

    def query(self, cmd: str, timeout_s: float = 10.0) -> str:
        assert self._sock
        self._sock.settimeout(timeout_s)
        self._sock.sendall((cmd + "\n").encode("ascii"))
        buf = bytearray()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                chunk = self._sock.recv(_RECV_BUF)
            except socket.timeout:
                break
            if chunk:
                buf.extend(chunk)
                if buf.endswith(b"\n"):
                    break
        self._sock.settimeout(self.timeout_s)
        return buf.decode("ascii", errors="replace").strip()

    def _read_binary_block(self, timeout_s: float = 60.0) -> bytes:
        """Accumulate bytes until a complete IEEE 488.2 binary block is received."""
        assert self._sock
        self._sock.settimeout(timeout_s)
        buf = bytearray()
        deadline = time.time() + timeout_s
        expected: int | None = None
        hdr_end:  int | None = None

        while time.time() < deadline:
            try:
                chunk = self._sock.recv(_RECV_BUF)
            except socket.timeout:
                break
            if not chunk:
                break
            buf.extend(chunk)

            if hdr_end is None:
                idx = bytes(buf).find(b"#")
                if idx >= 0 and len(buf) >= idx + 2:
                    d = buf[idx + 1] - ord("0")
                    if d > 0 and len(buf) >= idx + 2 + d:
                        n = int(bytes(buf[idx + 2 : idx + 2 + d]))
                        hdr_end  = idx + 2 + d
                        expected = hdr_end + n

            if expected is not None and len(buf) >= expected:
                break

        self._sock.settimeout(self.timeout_s)
        return bytes(buf)

    # capture ─────────────────────────────────────────────────────────────────
    def capture(
        self, channel: str = "CHAN1", fallback_fs: float = 256e9
    ) -> tuple[np.ndarray, np.ndarray, float]:
        ch = _norm_keysight_ch(channel)

        self.write(f":WAVeform:SOURce {ch}")
        self.write(":WAVeform:FORmat WORD")
        self.write(":WAVeform:BYTeorder LSBFirst")
        self.write(":WAVeform:UNSigned OFF")

        pre = self.query(":WAVeform:PREamble?", timeout_s=10.0)
        parts = pre.split(",")
        x_inc, x_orig, y_inc, y_orig, y_ref, fs = (
            1.0 / fallback_fs, 0.0, 1.0, 0.0, 0.0, fallback_fs
        )
        if len(parts) >= 10:
            try:
                xi = float(parts[4])
                x_inc  = xi if xi > 0 else x_inc
                x_orig = float(parts[5])
                y_inc  = float(parts[7])
                y_orig = float(parts[8])
                y_ref  = float(parts[9])
                fs     = 1.0 / x_inc
            except (ValueError, ZeroDivisionError):
                pass

        self.write(":WAVeform:DATA?", delay=0)
        raw     = self._read_binary_block(timeout_s=60.0)
        payload = _parse_ieee488_block(raw)

        raw_i16 = np.frombuffer(payload, dtype="<i2")
        voltage = (raw_i16.astype(np.float64) - y_ref) * y_inc + y_orig
        t       = x_orig + np.arange(len(voltage), dtype=np.float64) * x_inc
        return t, voltage, fs


# ── LeCroy / Teledyne-LeCroy (VICP, port 1861) ──────────────────────────────
class LecroyVicpDso:
    """
    LeCroy MAUI oscilloscope via VICP (Virtual Instrument Control Protocol).
    VICP wraps IEEE 488.2 SCPI over TCP on port 1861.

    VICP frame layout (controller→instrument):
      byte 0-1: 0x01 0x01  (version)
      byte 2  : operation  (0x09 = DATA + EOI)
      byte 3  : sequence number (1-255, wraps)
      bytes 4-7: payload length, big-endian uint32

    Instrument→controller response has the same 8-byte header, followed by
    the response payload (ASCII or IEEE 488.2 binary block).
    """

    def __init__(self, host: str, timeout_ms: int = 30_000) -> None:
        self.host      = host
        self.timeout_s = timeout_ms / 1000.0
        self._sock: socket.socket | None = None
        self._seq: int = 1

    # context manager ─────────────────────────────────────────────────────────
    def __enter__(self) -> "LecroyVicpDso":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout_s)
        self._sock.connect((self.host, LECROY_VICP_PORT))
        # drain any unsolicited banner from the scope
        self._sock.settimeout(0.4)
        try:
            self._sock.recv(_RECV_BUF)
        except Exception:
            pass
        self._sock.settimeout(self.timeout_s)
        # One-time configuration
        self._vicp_write("CHDR OFF")          # no channel-header prefix in responses
        time.sleep(0.1)
        self._vicp_write("COMM_FORMAT DEF9,WORD,BIN")   # 16-bit signed, binary
        self._vicp_write("COMM_ORDER LO")               # little-endian
        time.sleep(0.1)
        return self

    def __exit__(self, *_) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # VICP primitives ─────────────────────────────────────────────────────────
    def _next_seq(self) -> int:
        s = self._seq
        self._seq = (self._seq % 255) + 1
        return s

    def _vicp_hdr(self, op: int, n: int) -> bytes:
        return bytes([0x01, 0x01, op, self._next_seq()]) + struct.pack(">I", n)

    def _vicp_write(self, cmd: str) -> None:
        assert self._sock
        payload = (cmd + "\n").encode("ascii")
        self._sock.sendall(self._vicp_hdr(0x09, len(payload)) + payload)

    def _vicp_read(self, timeout_s: float = 10.0) -> bytes:
        assert self._sock
        self._sock.settimeout(timeout_s)
        hdr = _recv_exact(self._sock, 8)
        n   = struct.unpack(">I", hdr[4:8])[0]
        if n == 0:
            return b""
        data = _recv_exact(self._sock, n)
        self._sock.settimeout(self.timeout_s)
        return data

    # public SCPI interface ───────────────────────────────────────────────────
    def write(self, cmd: str, delay: float = 0.05) -> None:
        self._vicp_write(cmd)
        if delay > 0:
            time.sleep(delay)

    def query(self, cmd: str, timeout_s: float = 10.0) -> str:
        self._vicp_write(cmd)
        try:
            resp = self._vicp_read(timeout_s=timeout_s)
        except Exception:
            return ""
        return resp.decode("ascii", errors="replace").strip()

    def query_binary(self, cmd: str, timeout_s: float = 60.0) -> bytes:
        self._vicp_write(cmd)
        try:
            return self._vicp_read(timeout_s=timeout_s)
        except Exception:
            return b""

    # capture ─────────────────────────────────────────────────────────────────
    def capture(
        self, channel: str = "C1", fallback_fs: float = 40e9
    ) -> tuple[np.ndarray, np.ndarray, float]:
        ch  = _norm_lecroy_ch(channel)
        fs  = fallback_fs

        # ── Sample rate ───────────────────────────────────────────────────────
        sara = self.query("SARA?", timeout_s=5.0)
        try:
            # LeCroy returns e.g. "2.5000000E+010 Sa/s"
            fs = float(sara.strip().split()[0])
        except Exception:
            pass

        # ── Transfer all samples ──────────────────────────────────────────────
        self.write("WAVEFORM_SETUP SP,0,NP,0,FP,0,SN,0", delay=0.15)

        # ── Scaling from WAVEDESC ─────────────────────────────────────────────
        vert_gain   = 1.0
        vert_offset = 0.0
        try:
            desc_raw = self.query_binary(f"{ch}:WF DESC", timeout_s=15.0)
            desc     = _extract_wavedesc(desc_raw)
            if len(desc) >= 180:
                vert_gain   = struct.unpack_from("<f", desc, 156)[0]
                vert_offset = struct.unpack_from("<f", desc, 160)[0]
                horiz_int   = struct.unpack_from("<f", desc, 176)[0]
                if horiz_int > 0:
                    fs = 1.0 / horiz_int
        except Exception as exc:
            print(f"[LeCroy] WAVEDESC parse warning: {exc}")

        # ── Waveform data ─────────────────────────────────────────────────────
        dat1_raw = self.query_binary(f"{ch}:WF DAT1", timeout_s=60.0)
        dat1     = _parse_ieee488_block(dat1_raw)

        if len(dat1) < 2:
            raise RuntimeError(
                f"LeCroy: no waveform data received for {ch} "
                f"(raw payload {len(dat1_raw)} B). "
                "Check channel selection, trigger status, and waveform_setup."
            )

        # LeCroy: voltage = VERTICAL_GAIN * raw_int16 - VERTICAL_OFFSET
        raw_i16 = np.frombuffer(dat1, dtype="<i2")
        voltage = raw_i16.astype(np.float64) * vert_gain - vert_offset
        t       = np.arange(len(voltage), dtype=np.float64) / fs
        return t, voltage, fs


# ── Dummy (offline testing only) ─────────────────────────────────────────────
class DummyDsoController:
    """
    Simulated DSO — returns a noisy sine wave.
    NOT returned by create_dso_controller() for real DSO types.
    """

    def __init__(self, dso_type: str, host: str, timeout_ms: int = 5000) -> None:
        self._idn = f"DUMMY,{dso_type.upper()},{host},{timeout_ms}"

    def __enter__(self) -> "DummyDsoController":
        print("[DummyDSO] Using simulated DSO — not real hardware.")
        return self

    def __exit__(self, *_) -> None:
        pass

    def query(self, cmd: str) -> str:
        return self._idn if "*IDN?" in cmd else ""

    def capture(
        self, channel: str = "C1", fallback_fs: float = 40e9
    ) -> tuple[np.ndarray, np.ndarray, float]:
        _ = channel
        fs = fallback_fs
        n  = 20_000
        t  = np.arange(n) / fs
        sig = np.sin(2 * np.pi * 10e9 * t) + 0.1 * np.random.randn(n)
        return t, sig, fs


# ── Public factory ───────────────────────────────────────────────────────────
def create_dso_controller(dso_type: str, host: str, timeout_ms: int):
    """
    Factory function — returns the real DSO controller for the given type.

    dso_type values  →  controller
    "lecroy"          →  LecroyVicpDso   (port 1861, VICP)
    "keysight_uxr"    →  KeysightUxrDso  (port 5025, raw SCPI)
    anything else     →  KeysightUxrDso  (safe default)
    """
    t = dso_type.lower().strip()
    if t in ("lecroy", "teledyne", "teledyne_lecroy"):
        return LecroyVicpDso(host, timeout_ms)
    elif t in ("keysight_uxr", "keysight", "uxr"):
        return KeysightUxrDso(host, timeout_ms)
    else:
        return KeysightUxrDso(host, timeout_ms)


# ── Utility functions used by GUI ────────────────────────────────────────────
def fft_resample_complex(sig: np.ndarray, fs_in: float, fs_out: float) -> np.ndarray:
    num_out = int(round(len(sig) * fs_out / fs_in))
    return _sp_resample(sig, num_out)


def normalize_dso_type(dso_type_str: str) -> str:
    return dso_type_str.lower().strip()
