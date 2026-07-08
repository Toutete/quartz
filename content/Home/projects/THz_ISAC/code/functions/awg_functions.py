import socket
import time
import numpy as np


def parse_channels(ch_str: str) -> list[int]:
    try:
        return [int(c.strip()) for c in ch_str.split(',') if c.strip()]
    except (ValueError, AttributeError):
        print(f"Warning: Could not parse channel string '{ch_str}'. Defaulting to [1].")
        return [1]


def _parse_visa_socket_addr(visa_addr: str) -> tuple[str, int]:
    """Parse 'TCPIP0::host::port::SOCKET' into (host, port)."""
    parts = [p.strip() for p in visa_addr.split('::')]
    if len(parts) >= 3:
        return parts[1], int(parts[2])
    raise ValueError(f"Cannot parse VISA socket address: {visa_addr}")


class AwgSocketController:
    """
    Raw TCP/SCPI controller for socket-connected AWGs.
    Protocol: send ASCII SCPI commands terminated by newline.
    Binary block data follows IEEE 488.2 definite-length arbitrary-block format.
    """

    RECV_BUF = 65536

    def __init__(self, host: str, port: int, timeout_s: float = 30.0):
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self._sock: socket.socket | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout_s)
        self._sock.connect((self.host, self.port))
        self._sock.settimeout(0.3)
        try:
            self._sock.recv(self.RECV_BUF)
        except Exception:
            pass
        self._sock.settimeout(self.timeout_s)

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def write(self, cmd: str, delay_s: float = 0.02):
        self._sock.sendall((cmd + '\n').encode('ascii'))
        if delay_s > 0:
            time.sleep(delay_s)

    def query(self, cmd: str, timeout_s: float = 5.0) -> str:
        self._sock.settimeout(timeout_s)
        self._sock.sendall((cmd + '\n').encode('ascii'))
        buf = bytearray()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                chunk = self._sock.recv(self.RECV_BUF)
            except socket.timeout:
                break
            if chunk:
                buf.extend(chunk)
                if buf.endswith(b'\n'):
                    break
        self._sock.settimeout(self.timeout_s)
        return buf.decode('ascii', errors='replace').strip()

    def write_binary_block(self, header_cmd: str, data: bytes, delay_s: float = 0.1):
        """Send SCPI command followed by IEEE 488.2 definite-length block data."""
        n = len(data)
        digits = str(n)
        block_header = f'#{len(digits)}{digits}'.encode('ascii')
        sep = '' if header_cmd.endswith((',', ' ')) else ' '
        msg = (header_cmd + sep).encode('ascii') + block_header + data + b'\n'
        total_sent = 0
        while total_sent < len(msg):
            sent = self._sock.send(msg[total_sent:])
            if sent == 0:
                raise RuntimeError("AWG socket connection broken during binary transfer")
            total_sent += sent
        if delay_s > 0:
            time.sleep(delay_s)

    def wait_opc(self, timeout_s: float = 60.0) -> bool:
        """Wait for operation complete (*OPC? returns 1 when done)."""
        result = self.query('*OPC?', timeout_s=timeout_s)
        return result.strip() == '1'

    def check_error(self, context: str = "SCPI") -> None:
        """Raise when the instrument reports a SCPI error."""
        try:
            err = self.query(':SYST:ERR?', timeout_s=5.0)
        except Exception:
            return
        if err and not err.startswith(('0', '+0')):
            raise RuntimeError(f"{context}: AWG error {err}")

    def drain_errors(self, limit: int = 16) -> list[str]:
        """Drain the SCPI error queue and return non-zero entries."""
        errors: list[str] = []
        for _ in range(max(1, int(limit))):
            try:
                err = self.query(':SYST:ERR?', timeout_s=2.0)
            except Exception:
                break
            if not err:
                break
            parts = [p.strip() for p in err.split(';') if p.strip()]
            if not parts:
                parts = [err.strip()]
            stop = False
            for part in parts:
                if part.startswith(('0', '+0')):
                    stop = True
                else:
                    errors.append(part)
            if stop:
                break
        return errors


def _normalize_to_int16(sig: np.ndarray) -> np.ndarray:
    """Normalize float signal [-1,1] to int16. Clips to +/-1 before scaling."""
    s = np.asarray(sig, dtype=np.float64).flatten()
    peak = np.max(np.abs(s))
    if peak > 0:
        s = s / peak
    s = np.clip(s, -1.0, 1.0)
    return (s * 32767).astype(np.int16)


def _normalize_to_int8(sig: np.ndarray) -> np.ndarray:
    """Normalize float signal [-1,1] to signed 8-bit DAC samples."""
    s = np.asarray(sig, dtype=np.float64).flatten()
    peak = np.max(np.abs(s))
    if peak > 0:
        s = s / peak
    s = np.clip(s, -1.0, 1.0)
    return np.round(s * 127).astype(np.int8)


def _vpp_for_channel(vpp, ch: int) -> float:
    """Return a channel-specific Vpp from a scalar, dict, list, or tuple."""
    if isinstance(vpp, dict):
        if ch in vpp:
            return float(vpp[ch])
        if str(ch) in vpp:
            return float(vpp[str(ch)])
        if vpp:
            return float(next(iter(vpp.values())))
    if isinstance(vpp, (list, tuple, np.ndarray)):
        idx = max(0, int(ch) - 1)
        if idx < len(vpp):
            return float(vpp[idx])
        if len(vpp):
            return float(vpp[0])
    return float(vpp)


def test_awg_connection(awg_addr: str, timeout_ms: int = 5000) -> None:
    """Test TCP connection to AWG and query *IDN?."""
    host, port = _parse_visa_socket_addr(awg_addr)
    print(f"Connecting to AWG {host}:{port} ...")
    with AwgSocketController(host, port, timeout_s=timeout_ms / 1000.0) as awg:
        idn = awg.query('*IDN?', timeout_s=5.0)
    print(f"AWG response: {idn}")


def download_to_awg(awg_sig: np.ndarray, channels: list[int], awg_addr: str, fs: float, vpp) -> None:
    """
    Download waveform to AWG via SCPI over raw TCP socket.
    M8194A direct-mode downloads use signed int8 samples, matching Keysight IQTools.

    Leaves output OFF after downloading; call run_awg() to enable output and start.
    vpp can be a scalar or a {channel: Vpp} mapping.
    """
    host, port = _parse_visa_socket_addr(awg_addr)
    if not channels:
        channels = [1]

    channels = [int(ch) for ch in channels]
    with AwgSocketController(host, port, timeout_s=120.0) as awg:
        idn = awg.query('*IDN?')
        print(f"  AWG: {idn}")
        is_m8194a = "M8194" in idn.upper()
        awg.write('*CLS', delay_s=0.05)
        awg.drain_errors()

        if is_m8194a:
            sig_dac = _normalize_to_int8(awg_sig)
            sample_format = "int8"
        else:
            sig_dac = _normalize_to_int16(awg_sig)
            sample_format = "int16"

        n_samples = len(sig_dac)
        if is_m8194a and n_samples % 128:
            raise ValueError(
                f"M8194A segment length must be a multiple of 128 samples; got {n_samples}. "
                "Regenerate the waveform so the TX reference and AWG record length stay aligned."
            )
        raw_bytes = sig_dac.tobytes()
        vpp_desc = ", ".join(f"{ch}:{_vpp_for_channel(vpp, ch):.4f}" for ch in channels)
        print(
            f"Downloading {n_samples} samples ({sample_format}) to AWG Channels {channels} "
            f"@ {fs/1e9:.3f} GSa/s, Vpp={{{vpp_desc}}} V ..."
        )

        if not is_m8194a:
            awg.write('*RST', delay_s=1.0)
        if is_m8194a:
            ch_set = {int(ch) for ch in channels}
            if ch_set.intersection({2, 3, 4}) or len(ch_set) > 1:
                print(f"  M8194A: setting DAC output mode FOUR for channels {sorted(ch_set)}")
                awg.write(':INST:DACM FOUR', delay_s=0.2)
                awg.check_error("configure DAC output mode")
            if fs >= 92e9:
                awg.write(':FREQ:RANG HIGH', delay_s=0.05)
            elif fs >= 65e9:
                awg.write(':FREQ:RANG MED', delay_s=0.05)
            else:
                awg.write(':FREQ:RANG LOW', delay_s=0.05)

        awg.write(f':FREQ:RAST {fs:.6e}', delay_s=0.1)
        awg.check_error("configure sample rate")
        awg.write(':ABORt', delay_s=0.2)
        awg.wait_opc(timeout_s=20.0)
        awg.drain_errors()

        for ch in channels:
            awg.write(f':OUTP{ch} OFF', delay_s=0.05)
            awg.drain_errors()
            awg.write(f':TRACe{ch}:DELete 1', delay_s=0.1)
            # Deleting a segment that does not exist is harmless and common.
            # Drain the whole queue so that the next DEFine is not blamed for
            # this expected "segment not defined" message.
            awg.drain_errors()

            awg.write(f':TRACe{ch}:DEFine 1,{n_samples}', delay_s=0.1)
            awg.check_error(f"define segment ch{ch}")
            awg.write_binary_block(f':TRACe{ch}:DATA 1,0,', raw_bytes, delay_s=0.2)
            if not awg.wait_opc(timeout_s=60.0):
                raise RuntimeError(f"AWG did not complete waveform upload on channel {ch}")
            awg.check_error(f"upload waveform ch{ch}")

            if not is_m8194a:
                awg.write(f':TRAC{ch}:SEL 1', delay_s=0.05)
                awg.check_error(f"select segment ch{ch}")

            awg.write(f':VOLTage{ch}:AMPLitude {_vpp_for_channel(vpp, ch):.4f}', delay_s=0.05)

    print("Download complete (output off; press AWG ON to run).")


def run_awg(awg_addr: str, channels: list[int], vpp) -> None:
    """Apply per-channel Vpp and start the AWG without re-downloading waveform data."""
    host, port = _parse_visa_socket_addr(awg_addr)
    if not channels:
        channels = [1]
    channels = [int(ch) for ch in channels]

    vpp_desc = ", ".join(f"{ch}:{_vpp_for_channel(vpp, ch):.4f}" for ch in channels)
    print(f"Running AWG Channels {channels} with Vpp={{{vpp_desc}}} V ...")
    with AwgSocketController(host, port, timeout_s=10.0) as awg:
        for ch in channels:
            awg.write(f':VOLTage{ch}:AMPLitude {_vpp_for_channel(vpp, ch):.4f}', delay_s=0.05)
            awg.write(f':OUTP{ch} ON', delay_s=0.05)
        awg.write(':INIT:IMM', delay_s=0.1)
    print("AWG output running.")


def stop_awg(awg_addr: str, channels: list[int]) -> None:
    """Abort the AWG run and disable output channels."""
    host, port = _parse_visa_socket_addr(awg_addr)
    if not channels:
        channels = [1]

    channels = [int(ch) for ch in channels]
    print(f"Stopping AWG Channels {channels} ...")
    with AwgSocketController(host, port, timeout_s=15.0) as awg:
        awg.write(':ABORt', delay_s=0.2)
        for ch in channels:
            awg.write(f':OUTP{ch} OFF', delay_s=0.05)
    print("AWG output stopped.")
