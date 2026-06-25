import socket
import time
import numpy as np


def parse_channels(ch_str: str) -> list[int]:
    try:
        return [int(c.strip()) for c in ch_str.split(',')]
    except (ValueError, AttributeError):
        print(f"Warning: Could not parse channel string '{ch_str}'. Defaulting to [1].")
        return [1]


def _parse_visa_socket_addr(visa_addr: str) -> tuple[str, int]:
    """Parse 'TCPIP0::host::port::SOCKET' → (host, port)."""
    parts = [p.strip() for p in visa_addr.split('::')]
    if len(parts) >= 3:
        return parts[1], int(parts[2])
    raise ValueError(f"Cannot parse VISA socket address: {visa_addr}")


class AwgSocketController:
    """
    Raw TCP/SCPI controller for socket-connected AWGs (Keysight M8195A / M8199A etc.).
    Protocol: send ASCII SCPI commands terminated by '\\n', receive responses terminated by '\\n'.
    Binary block data follows IEEE 488.2 definite-length arbitrary-block format: #<d><len><bytes>.
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
        # Drain any welcome banner (some instruments send one)
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
        msg = (header_cmd + ' ').encode('ascii') + block_header + data + b'\n'
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


def _normalize_to_int16(sig: np.ndarray) -> np.ndarray:
    """Normalize float signal [-1,1] to int16. Clips to ±1 before scaling."""
    s = np.asarray(sig, dtype=np.float64).flatten()
    peak = np.max(np.abs(s))
    if peak > 0:
        s = s / peak
    s = np.clip(s, -1.0, 1.0)
    return (s * 32767).astype(np.int16)


def test_awg_connection(awg_addr: str, timeout_ms: int = 5000) -> None:
    """Test TCP connection to AWG and query *IDN?."""
    host, port = _parse_visa_socket_addr(awg_addr)
    print(f"Connecting to AWG {host}:{port} ...")
    with AwgSocketController(host, port, timeout_s=timeout_ms / 1000.0) as awg:
        idn = awg.query('*IDN?', timeout_s=5.0)
    print(f"AWG response: {idn}")


def download_to_awg(awg_sig: np.ndarray, channels: list[int], awg_addr: str, fs: float, vpp: float) -> None:
    """
    Download waveform to AWG via SCPI over raw TCP socket.
    Tested against Keysight M8195A / M8199A syntax.

    Parameters
    ----------
    awg_sig  : 1-D float array, normalised to ±1
    channels : list of channel numbers (uses first channel)
    awg_addr : VISA socket string  'TCPIP0::host::port::SOCKET'
    fs       : AWG sample rate in Hz
    vpp      : peak-to-peak output amplitude in Volts
    """
    host, port = _parse_visa_socket_addr(awg_addr)
    ch = channels[0] if channels else 1

    sig_i16 = _normalize_to_int16(awg_sig)
    n_samples = len(sig_i16)
    raw_bytes = sig_i16.tobytes()

    print(f"Downloading {n_samples} samples to AWG Ch{ch} @ {fs/1e9:.3f} GSa/s, Vpp={vpp:.4f} V ...")
    with AwgSocketController(host, port, timeout_s=120.0) as awg:
        idn = awg.query('*IDN?')
        print(f"  AWG: {idn}")

        awg.write('*RST', delay_s=1.0)
        awg.write(f':FREQ:RAST {fs:.6e}', delay_s=0.1)

        # Disable output before upload
        awg.write(f':OUTP{ch} OFF', delay_s=0.05)

        # Delete all segments and define new one
        awg.write(f':TRAC{ch}:DEL:ALL', delay_s=0.1)
        awg.write(f':TRAC{ch}:DEF 1,{n_samples}', delay_s=0.1)

        # Upload waveform data
        awg.write_binary_block(f':TRAC{ch}:DATA 1,0', raw_bytes, delay_s=0.2)
        awg.wait_opc(timeout_s=60.0)

        # Select uploaded segment on channel
        awg.write(f':TRAC{ch}:SEL 1', delay_s=0.05)

        # Set amplitude
        awg.write(f':VOLT{ch} {vpp:.4f}', delay_s=0.05)

        # Enable output and arm
        awg.write(f':OUTP{ch} ON', delay_s=0.05)
        awg.write(':INIT:IMM', delay_s=0.1)

    print("Download and run complete.")


def run_awg(awg_addr: str, channels: list[int], vpp: float) -> None:
    """
    Apply new Vpp to AWG channels and trigger output run
    (without re-downloading waveform data).
    """
    host, port = _parse_visa_socket_addr(awg_addr)
    ch = channels[0] if channels else 1

    print(f"AWG Run: Ch{ch}, Vpp={vpp:.4f} V ...")
    with AwgSocketController(host, port, timeout_s=15.0) as awg:
        awg.write(f':VOLT{ch} {vpp:.4f}', delay_s=0.05)
        awg.write(f':OUTP{ch} ON', delay_s=0.05)
        awg.write(':INIT:IMM', delay_s=0.1)
    print("AWG output running.")
