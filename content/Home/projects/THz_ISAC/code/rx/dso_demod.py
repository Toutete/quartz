"""
dso_demod_lfm_qam.py  -  Teledyne LeCroy LabMaster 10-59Zi-A + LFM-QAM
=========================================================================

단계:
  [1] DSO 연결 (VISA/VICP) -> 파형 캡처  또는  .trc 파일 로드
  [2] 시간 도메인 + 주파수 스펙트럼 관찰
  [3] 리샘플링 (DSO fs -> 시뮬레이션 fs)
  [4] 동기화 (Cross-correlation)
  [5] LFM-QAM 복조 (De-chirping + QAM 결정)
  [6] 거리 프로파일 / 성상도 시각화 및 결과 저장

사용법:
  # 라이브 캡처
  python dso_demod_lfm_qam.py --mode live --host 192.168.0.10 --ch C1
  # 오프라인 .trc 파일
  python dso_demod_lfm_qam.py --mode trc  --trc waveform.trc
  # 시뮬레이션 데이터만 (기본)
  python dso_demod_lfm_qam.py --mode sim  --sim data/sim_isac_lfm_qam.npz
  # 관찰만 (복조 생략)
  python dso_demod_lfm_qam.py --mode live --host 192.168.0.10 --no-demod
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Tuple

import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# 1. DSO 연결 및 파형 캡처  (Teledyne LeCroy LabMaster)
# ============================================================

class LabMasterDSO:
    """
    Teledyne LeCroy LabMaster 10-59Zi-A VISA 인터페이스.

    연결 순서:
      1) pyvisa @ivi  (Keysight/NI IO Libraries 설치된 경우)
      2) pyvisa @py   (pyvisa-py 순수 Python 백엔드)

    VISA 리소스:
      TCPIP::<host>::inst0::INSTR  (VXI-11  - pyvisa-py 권장)
      TCPIP::<host>::1861::SOCKET  (VICP    - LeCroy 고유 프로토콜)
    """

    VICP_PORT = 1861

    def __init__(self, host: str, timeout_ms: int = 10_000):
        self.host       = host
        self.timeout_ms = timeout_ms
        self.inst       = None
        self._rm        = None
        self._resource_name = ""
        self._using_tcpip_fallback = False
        self._vicp_last_error = ""

    # ---- 연결 / 해제 ---------------------------------------------------

    def connect(self) -> None:
        """DSO에 VISA로 연결합니다."""
        import pyvisa

        backends = ("", "@ivi", "@py")
        addr_candidates = [
            f"VICP::{self.host}::INSTR",
            f"VICP::{self.host}::inst0::INSTR",
            f"TCPIP0::{self.host}::inst0::INSTR",
            f"TCPIP::{self.host}::inst0::INSTR",
            f"TCPIP::{self.host}::{self.VICP_PORT}::SOCKET",
        ]

        last_err = None
        for backend in backends:
            try:
                rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
            except Exception as e:
                last_err = e
                continue

            for addr in addr_candidates:
                try:
                    inst = rm.open_resource(addr)
                    # 파형 질의는 전송량이 커서 타임아웃을 넉넉히 둔다.
                    inst.timeout = max(self.timeout_ms, 15_000)
                    try:
                        inst.clear()
                    except Exception:
                        pass
                    if "SOCKET" in addr:
                        inst.read_termination  = "\n"
                        inst.write_termination = "\n"
                    idn = inst.query("*IDN?").strip()
                    print(f"[DSO] 연결 성공 ({backend or 'default'} / {addr}): {idn}")
                    self.inst = inst
                    self._rm = rm
                    self._resource_name = addr
                    self._using_tcpip_fallback = addr.upper().startswith("TCPIP")
                    return
                except Exception as e:
                    print(f"[DSO] {backend or 'default'} / {addr} 실패: {e}")
                    if addr.upper().startswith("VICP"):
                        self._vicp_last_error = str(e)
                    last_err = e

            try:
                rm.close()
            except Exception:
                pass

        raise ConnectionError(
            f"DSO({self.host}) 연결 실패. 마지막 오류: {last_err}"
        )

    def disconnect(self) -> None:
        if self.inst:
            try:
                self.inst.close()
            except Exception:
                pass
            self.inst = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    # ---- 파형 캡처 -------------------------------------------------------

    def capture(self, channel: str = "C1", fallback_fs: float | None = None) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        지정 채널의 파형을 캡처합니다.

        Parameters
        ----------
        channel : str  - 채널 이름 (예: "C1", "C2", "C3", "C4")

        Returns
        -------
        t  : ndarray [s]   - 시간 축
        y  : ndarray [V]   - 전압 파형 (실수)
        fs : float [Sa/s]  - 샘플링 레이트
        """
        if self.inst is None:
            raise RuntimeError(
                "DSO에 연결되어 있지 않습니다. connect()를 먼저 호출하세요."
            )

        inst = self.inst
        ch   = channel.upper()

        # 통신 설정
        inst.write("COMM_HEADER OFF")            # 응답 헤더 생략
        inst.write("COMM_ORDER LO")              # 리틀엔디안
        inst.write("COMM_FORMAT DEF9,WORD,BIN")  # 16-bit signed int, binary block

        # INSPECT/VBS 질의가 막히는 장비가 있어, 실패 시 fallback_fs로 계속 진행.
        try:
            fs = self._query_sample_rate(ch)
        except Exception:
            if fallback_fs is None or fallback_fs <= 0:
                raise
            fs = float(fallback_fs)
            print(f"[DSO] {ch}: sample-rate query failed; using fallback fs={fs/1e9:.3f} GSa/s")
        h_int = 1.0 / fs

        try:
            # 1) 기본 경로: 기존 WF? + IEEE block 파싱
            raw = self._fetch_waveform_raw(ch)

            y_int, n_parsed = self._parse_ieee_block(raw, dtype=np.int16)
            n = n_parsed

            y = y_int[:n].astype(np.float64)
            v_gain, v_offset = self._try_query_vertical_scale(ch)
            if v_gain is not None and v_offset is not None:
                y = y * v_gain - v_offset
                print(f"[DSO] {ch}: N={n:,}, fs={fs/1e9:.3f} GSa/s, scaled")
            else:
                print(f"[DSO] {ch}: N={n:,}, fs={fs/1e9:.3f} GSa/s, unscaled(raw ADC code)")

            t = np.arange(n) * h_int
            return t, y, fs
        except Exception as primary_exc:
            # 2) 요청된 GitHub 라이브러리 백엔드 재시도
            print(f"[DSO] Primary capture path failed: {primary_exc}")
            print("[DSO] Trying TeledyneLeCroyPy backend...")
            try:
                return self._capture_with_teledynelecroypy(ch, fallback_fs=fallback_fs)
            except Exception as secondary_exc:
                raise RuntimeError(
                    "Failed to capture live waveform with both backends. "
                    f"Primary error: {primary_exc}; "
                    f"TeledyneLeCroyPy error: {secondary_exc}"
                ) from secondary_exc

    def _capture_with_teledynelecroypy(self, channel: str, fallback_fs: float | None = None) -> Tuple[np.ndarray, np.ndarray, float]:
        """Secondary backend based on https://github.com/SengerM/TeledyneLeCroyPy."""
        try:
            import TeledyneLeCroyPy
        except Exception as e:
            raise RuntimeError(
                "TeledyneLeCroyPy is not installed. Install with: "
                "pip install git+https://github.com/SengerM/TeledyneLeCroyPy"
            ) from e

        if not (len(channel) == 2 and channel[0].upper() == 'C' and channel[1].isdigit()):
            raise ValueError(f"Unsupported channel format: {channel}")
        n_channel = int(channel[1])
        if n_channel not in {1, 2, 3, 4}:
            raise ValueError(f"Channel out of range: {channel}")

        resource_name = self._resource_name or f"TCPIP0::{self.host}::inst0::INSTR"
        scope = TeledyneLeCroyPy.LeCroyWaveRunner(resource_name)
        try:
            data = scope.get_waveform(n_channel=n_channel)
        finally:
            try:
                scope.resource.close()
            except Exception:
                pass

        waveforms = data.get("waveforms", [])
        if len(waveforms) == 0:
            raise RuntimeError("TeledyneLeCroyPy returned no waveform segments.")

        wf0 = waveforms[0]
        time_key = next((k for k in wf0.keys() if "Time" in k), None)
        amp_key = next((k for k in wf0.keys() if "Amplitude" in k), None)
        if time_key is None or amp_key is None:
            raise RuntimeError(f"Unexpected waveform dict keys: {list(wf0.keys())}")

        t = np.asarray(wf0[time_key], dtype=np.float64)
        y = np.asarray(wf0[amp_key], dtype=np.float64)
        if len(t) != len(y) or len(t) < 2:
            if fallback_fs is None or fallback_fs <= 0:
                raise RuntimeError("Invalid time axis from TeledyneLeCroyPy and no fallback fs provided.")
            fs = float(fallback_fs)
            t = np.arange(len(y), dtype=np.float64) / fs
            return t, y, fs

        dt = np.median(np.diff(t))
        if not np.isfinite(dt) or dt <= 0:
            if fallback_fs is None or fallback_fs <= 0:
                raise RuntimeError("Could not infer sample rate from TeledyneLeCroyPy time axis.")
            fs = float(fallback_fs)
            t = np.arange(len(y), dtype=np.float64) / fs
            return t, y, fs

        fs = float(1.0 / dt)
        print(f"[DSO] TeledyneLeCroyPy capture OK: N={len(y):,}, fs={fs/1e9:.3f} GSa/s")
        return t, y, fs

    def _fetch_waveform_raw(self, channel: str) -> bytes:
        inst = self.inst
        if inst is None:
            raise RuntimeError("DSO not connected.")

        commands = [
            f"{channel}:WF? DAT1",
            f"{channel}:WAVEFORM? DAT1",
            f"{channel}:WF?",
            f"{channel}:WAVEFORM?",
        ]

        last_resp_preview = ""
        saw_tcpip_warning = False
        for cmd in commands:
            try:
                inst.write(cmd)
                raw = inst.read_raw()
                if b"#" in raw:
                    return raw

                preview = raw[:200].decode(errors="ignore").strip()
                if preview:
                    last_resp_preview = preview

                # TCPIP 경고 응답이면 다음 명령으로 재시도
                up = preview.upper()
                if "WARNING" in up and "TCPIP" in up:
                    saw_tcpip_warning = True
                    continue
            except Exception as e:
                last_resp_preview = str(e)
                continue

        if saw_tcpip_warning:
            vicp_hint = ""
            if self._vicp_last_error:
                vicp_hint = (
                    " VICP connect failed in this PC environment. "
                    f"Last VICP error: {self._vicp_last_error}. "
                    "Install Teledyne LeCroy VICP Passport (or WaveStudio package) and retry."
                )
            raise RuntimeError(
                "Scope is blocking waveform transfer on current TCPIP control interface. "
                "Received warning: 'CURRENT REMOTE CONTROL INTERFACE IS TCPIP'. "
                f"Current VISA resource: {self._resource_name or 'unknown'}. "
                "For MCM-Zi-A, use a VICP-capable VISA resource if available, "
                "or enable waveform transfer for TCPIP control interface on scope. "
                "Use TRC mode as immediate workaround."
                f"{vicp_hint}"
            )

        raise ValueError(
            "IEEE binary block header '#' not found in waveform response. "
            f"Last response preview: {last_resp_preview}"
        )

    @staticmethod
    def _extract_first_float(text: str) -> float | None:
        m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(text))
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    def _query_float_candidates(self, commands: list[str]) -> float | None:
        for cmd in commands:
            try:
                resp = self.query(cmd)
                if "WARNING" in resp.upper() and "TCPIP" in resp.upper():
                    continue
                val = self._extract_first_float(resp)
                if val is not None:
                    return val
            except Exception:
                continue
        return None

    def _query_sample_rate(self, channel: str) -> float:
        fs = self._query_float_candidates([
            "VBS? 'return=app.Acquisition.Horizontal.SampleRate'",
            "VBS? \"return=app.Acquisition.Horizontal.SampleRate\"",
            f"VBS? 'return=app.Acquisition.{channel}.Out.Result.SampleRate'",
        ])
        if fs is not None and fs > 0:
            return fs

        h_int = self._query_float_candidates([
            f"{channel}:INSPECT? 'HORIZ_INTERVAL'",
            f"{channel}:INSPECT? \"HORIZ_INTERVAL\"",
        ])
        if h_int is not None and h_int > 0:
            return 1.0 / h_int

        raise ValueError("Failed to get sample rate from scope (SampleRate/HORIZ_INTERVAL unavailable).")

    def _try_query_vertical_scale(self, channel: str) -> tuple[float | None, float | None]:
        v_gain = self._query_float_candidates([
            f"{channel}:INSPECT? 'VERTICAL_GAIN'",
            f"{channel}:INSPECT? \"VERTICAL_GAIN\"",
            f"VBS? 'return=app.Acquisition.{channel}.Out.Result.VerticalPerStep'",
        ])
        v_offset = self._query_float_candidates([
            f"{channel}:INSPECT? 'VERTICAL_OFFSET'",
            f"{channel}:INSPECT? \"VERTICAL_OFFSET\"",
            f"VBS? 'return=app.Acquisition.{channel}.Out.Result.VerticalOffset'",
        ])
        return v_gain, v_offset

    def _inspect(self, channel: str, param: str) -> str:
        """
        INSPECT? 명령으로 파형 파라미터를 조회합니다.
        'PARAM : value' 형태 응답에서 값 부분만 추출합니다.
        """
        resp = self.inst.query(f"{channel}:INSPECT? '{param}'").strip()

        # LeCroy 응답은 펌웨어/접속 방식에 따라 헤더 텍스트가 섞일 수 있으므로
        # 뒤쪽 토큰부터 숫자 토큰을 찾아 사용한다.
        candidates = [resp]
        if ":" in resp:
            candidates.insert(0, resp.split(":")[-1])
        if "=" in resp:
            candidates.insert(0, resp.split("=")[-1])

        for chunk in candidates:
            tokens = re.split(r"[\s,]+", chunk.strip())
            for tok in reversed(tokens):
                t = tok.strip("\"'[](){};")
                try:
                    float(t)
                    return t
                except Exception:
                    continue

        raise ValueError(f"Failed to parse INSPECT value: channel={channel}, param={param}, resp='{resp}'")

    @staticmethod
    def _parse_ieee_block(raw: bytes, dtype=np.int16) -> Tuple[np.ndarray, int]:
        """
        IEEE 488.2 definite-length binary block을 파싱합니다.

        형식: [optional_text] # <d> <len_digits> <payload>
        LeCroy 응답 앞에 'C1:WF DAT1,' 텍스트가 붙을 수 있습니다.
        """
        idx = raw.find(b"#")
        if idx < 0:
            raise ValueError("IEEE binary block 헤더('#')를 찾을 수 없습니다.")
        idx     += 1
        n_digits = int(chr(raw[idx]))
        idx     += 1
        n_bytes  = int(raw[idx: idx + n_digits])
        idx     += n_digits
        payload  = raw[idx: idx + n_bytes]
        arr      = np.frombuffer(payload, dtype=dtype)
        return arr, len(arr)

    # ---- 유틸리티 --------------------------------------------------------

    def query(self, cmd: str) -> str:
        if self.inst is None:
            raise RuntimeError("DSO not connected.")
        return self.inst.query(cmd).strip()

    def write(self, cmd: str) -> None:
        if self.inst is None:
            raise RuntimeError("DSO not connected.")
        self.inst.write(cmd)


class KeysightUXRDSO:
    """
    Keysight UXR0404A (Infiniium 계열) VISA 인터페이스.

    기본 리소스 후보:
      TCPIP0::<host>::inst0::INSTR
      TCPIP::<host>::inst0::INSTR
      TCPIP0::<host>::hislip0::INSTR
      TCPIP::<host>::5025::SOCKET
    """

    def __init__(self, host: str, timeout_ms: int = 10_000):
        self.host = host
        self.timeout_ms = timeout_ms
        self.inst = None
        self._rm = None
        self._resource_name = ""

    def connect(self) -> None:
        import pyvisa

        backends = ("", "@ivi", "@py")
        addr_candidates = [
            f"TCPIP0::{self.host}::inst0::INSTR",
            f"TCPIP::{self.host}::inst0::INSTR",
            f"TCPIP0::{self.host}::hislip0::INSTR",
            f"TCPIP::{self.host}::hislip0::INSTR",
            f"TCPIP::{self.host}::5025::SOCKET",
        ]

        last_err = None
        for backend in backends:
            try:
                rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
            except Exception as e:
                last_err = e
                continue

            for addr in addr_candidates:
                try:
                    inst = rm.open_resource(addr)
                    inst.timeout = max(self.timeout_ms, 12_000)
                    inst.chunk_size = 1024 * 1024
                    try:
                        inst.clear()
                    except Exception:
                        pass
                    if "SOCKET" in addr.upper():
                        inst.read_termination = "\n"
                        inst.write_termination = "\n"
                    idn = inst.query("*IDN?").strip()
                    print(f"[DSO] 연결 성공 ({backend or 'default'} / {addr}): {idn}")
                    self.inst = inst
                    self._rm = rm
                    self._resource_name = addr
                    return
                except Exception as e:
                    print(f"[DSO] {backend or 'default'} / {addr} 실패: {e}")
                    last_err = e

            try:
                rm.close()
            except Exception:
                pass

        raise ConnectionError(f"Keysight UXR({self.host}) 연결 실패. 마지막 오류: {last_err}")

    def disconnect(self) -> None:
        if self.inst:
            try:
                self.inst.close()
            except Exception:
                pass
            self.inst = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    @staticmethod
    def _parse_channel_index(channel: str) -> int:
        ch = str(channel).strip().upper()
        if len(ch) == 2 and ch[0] == "C" and ch[1].isdigit():
            idx = int(ch[1])
            if idx in (1, 2, 3, 4):
                return idx
        raise ValueError(f"Unsupported Keysight channel format: {channel}. Use C1..C4")

    @staticmethod
    def _parse_ieee_block(raw: bytes, dtype=np.int16) -> np.ndarray:
        idx = raw.find(b"#")
        if idx < 0:
            raise ValueError("IEEE binary block header '#' not found in Keysight response.")
        idx += 1
        n_digits = int(chr(raw[idx]))
        idx += 1
        n_bytes = int(raw[idx: idx + n_digits])
        idx += n_digits
        payload = raw[idx: idx + n_bytes]
        return np.frombuffer(payload, dtype=dtype)

    def capture(self, channel: str = "C1", fallback_fs: float | None = None) -> Tuple[np.ndarray, np.ndarray, float]:
        if self.inst is None:
            raise RuntimeError("DSO에 연결되어 있지 않습니다. connect()를 먼저 호출하세요.")

        inst = self.inst
        ch_idx = self._parse_channel_index(channel)

        inst.write(":WAVEFORM:SOURCE CHANNEL{}".format(ch_idx))
        inst.write(":WAVEFORM:FORMAT WORD")
        try:
            inst.write(":WAVEFORM:BYTEORDER LSBFIRST")
        except Exception:
            pass
        try:
            inst.write(":WAVEFORM:STREAMING ON")
        except Exception:
            pass

        x_inc = float(inst.query(":WAVEFORM:XINCREMENT?").strip())
        x_org = float(inst.query(":WAVEFORM:XORIGIN?").strip())

        try:
            y_inc = float(inst.query(":WAVEFORM:YINCREMENT?").strip())
            y_org = float(inst.query(":WAVEFORM:YORIGIN?").strip())
            y_ref = float(inst.query(":WAVEFORM:YREFERENCE?").strip())
        except Exception:
            y_inc = 1.0
            y_org = 0.0
            y_ref = 0.0

        codes = None
        try:
            codes = inst.query_binary_values(
                ":WAVEFORM:DATA?",
                datatype="h",
                is_big_endian=False,
                container=np.array,
            )
        except Exception:
            inst.write(":WAVEFORM:DATA?")
            raw = inst.read_raw()
            codes = self._parse_ieee_block(raw, dtype=np.int16)

        if codes is None or len(codes) == 0:
            raise RuntimeError("Keysight waveform response is empty.")

        y = (np.asarray(codes, dtype=np.float64) - y_ref) * y_inc + y_org
        n = len(y)
        t = x_org + np.arange(n, dtype=np.float64) * x_inc

        if x_inc > 0:
            fs = float(1.0 / x_inc)
        elif fallback_fs is not None and fallback_fs > 0:
            fs = float(fallback_fs)
            t = np.arange(n, dtype=np.float64) / fs
        else:
            fs = float(inst.query(":ACQUIRE:SRATE?").strip())
            if fs <= 0:
                raise RuntimeError("Failed to infer Keysight sample rate.")
            t = np.arange(n, dtype=np.float64) / fs

        print(f"[DSO] Keysight capture OK: N={n:,}, fs={fs/1e9:.3f} GSa/s")
        return t, y, fs

    def query(self, cmd: str) -> str:
        if self.inst is None:
            raise RuntimeError("DSO not connected.")
        return self.inst.query(cmd).strip()

    def write(self, cmd: str) -> None:
        if self.inst is None:
            raise RuntimeError("DSO not connected.")
        self.inst.write(cmd)


def normalize_dso_type(dso_type: str) -> str:
    key = str(dso_type).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "lecroy": "lecroy",
        "teledyne": "lecroy",
        "teledyne_lecroy": "lecroy",
        "labmaster": "lecroy",
        "keysight": "keysight_uxr",
        "keysight_uxr": "keysight_uxr",
        "uxr": "keysight_uxr",
        "uxr0404a": "keysight_uxr",
    }
    if key in aliases:
        return aliases[key]
    raise ValueError("Unsupported DSO type. Use one of: lecroy, keysight_uxr")


def create_dso_controller(dso_type: str, host: str, timeout_ms: int = 10_000):
    normalized = normalize_dso_type(dso_type)
    if normalized == "lecroy":
        return LabMasterDSO(host=host, timeout_ms=timeout_ms)
    if normalized == "keysight_uxr":
        return KeysightUXRDSO(host=host, timeout_ms=timeout_ms)
    raise ValueError(f"Unsupported DSO type: {dso_type}")


# ============================================================
# 2. 오프라인 .trc 파일 로드  (lecroyparser)
# ============================================================

def load_trc(file_path: str) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Teledyne LeCroy .trc 파일에서 파형을 로드합니다.

    Returns
    -------
    t  : ndarray [s], y : ndarray [V], fs : float [Sa/s]
    """
    try:
        import lecroyparser
    except ImportError:
        raise ImportError(
            "lecroyparser가 필요합니다: pip install lecroyparser"
        )

    data = lecroyparser.ScopeData(file_path)
    t    = np.asarray(data.x, dtype=np.float64)
    y    = np.asarray(data.y, dtype=np.float64)
    fs   = 1.0 / float(t[1] - t[0])
    print(f"[TRC] {Path(file_path).name}: N={len(t):,}, fs={fs/1e9:.3f} GSa/s")
    return t, y, fs


# ============================================================
# 3. 시간 / 주파수 도메인 관찰
# ============================================================

def plot_time_and_spectrum(
    t:            np.ndarray,
    y:            np.ndarray,
    fs:           float,
    title:        str   = "",
    max_plot_pts: int   = 50_000,
    f_if:         float = 0.0,
) -> None:
    """
    시간 도메인 파형과 단측 전력 스펙트럼을 나란히 플롯합니다.

    Parameters
    ----------
    t            : 시간 배열 [s]
    y            : 전압 배열 [V]  (실수 또는 복소수)
    fs           : 샘플링 레이트 [Sa/s]
    title        : 플롯 제목
    max_plot_pts : 시간 도메인 표시 최대 샘플 수
    f_if         : IF 주파수 [Hz] - 스펙트럼에 마커 표시 (0 이면 생략)
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 4))

    # -- 시간 도메인 -------------------------------------------------------
    ax_t = axes[0]
    n_p  = min(len(t), max_plot_pts)
    ax_t.plot(t[:n_p] * 1e9, np.real(y[:n_p]), linewidth=0.4)
    ax_t.set_title(f"Time Domain  {title}")
    ax_t.set_xlabel("Time [ns]")
    ax_t.set_ylabel("Amplitude [V]")
    ax_t.grid(True)

    # -- 단측 전력 스펙트럼 ------------------------------------------------
    ax_f  = axes[1]
    N     = len(y)
    Y     = np.fft.rfft(np.real(y), n=N)
    f_pos = np.fft.rfftfreq(N, d=1.0 / fs)
    P_db  = 20.0 * np.log10(np.abs(Y) / N + 1e-15)
    ax_f.plot(f_pos / 1e9, P_db, linewidth=0.4)
    if f_if > 0.0:
        ax_f.axvline(
            x=f_if / 1e9, color="red", linestyle="--", linewidth=0.9,
            label=f"f_IF = {f_if/1e9:.1f} GHz",
        )
        ax_f.legend(fontsize=8)
    ax_f.set_title(f"Single-sided Spectrum  {title}")
    ax_f.set_xlabel("Frequency [GHz]")
    ax_f.set_ylabel("Power [dBFS]")
    ax_f.grid(True)

    if title:
        fig.suptitle(title, fontsize=11, y=1.01)
    plt.tight_layout()
    plt.show()


# ============================================================
# 4. 신호 처리 유틸리티
# ============================================================

def fft_resample_complex(
    x: np.ndarray, fs_in: float, fs_out: float
) -> np.ndarray:
    """FFT 도메인 영점 패딩/절단으로 복소 파형을 리샘플링합니다."""
    x = np.asarray(x, dtype=np.complex128)
    if fs_in <= 0 or fs_out <= 0:
        raise ValueError("fs_in, fs_out은 양수여야 합니다.")
    if np.isclose(fs_in, fs_out):
        return x

    n_in  = len(x)
    n_out = max(1, int(round(n_in * fs_out / fs_in)))
    X     = np.fft.fftshift(np.fft.fft(x, n=n_in))

    if n_out > n_in:
        pad  = n_out - n_in
        left = pad // 2
        Y    = np.pad(X, (left, pad - left), mode="constant")
    else:
        cut  = n_in - n_out
        left = cut // 2
        Y    = X[left: n_in - (cut - left)]

    y     = np.fft.ifft(np.fft.ifftshift(Y), n=n_out)
    p_in  = np.mean(np.abs(x) ** 2) + 1e-15
    p_out = np.mean(np.abs(y) ** 2) + 1e-15
    return y * np.sqrt(p_in / p_out)


def fft_lowpass_complex(x: np.ndarray, fs: float, cutoff_hz: float) -> np.ndarray:
    """Apply a simple ideal low-pass mask in FFT domain to complex samples."""
    sig = np.asarray(x, dtype=np.complex128)
    if fs <= 0:
        raise ValueError("fs must be positive")
    if cutoff_hz <= 0:
        return np.zeros_like(sig)

    n = len(sig)
    if n == 0:
        return sig

    freq = np.fft.fftfreq(n, d=1.0 / fs)
    mask = np.abs(freq) <= float(cutoff_hz)
    spec = np.fft.fft(sig)
    spec[~mask] = 0.0
    return np.fft.ifft(spec)


def make_qam_constellation(M: int = 16) -> np.ndarray:
    """정규화된 M-QAM 성상도 포인트를 반환합니다."""
    m_side = int(np.sqrt(M))
    if m_side ** 2 != M:
        raise ValueError("M은 완전제곱수여야 합니다 (예: 4, 16, 64).")
    levels = np.arange(-(m_side - 1), m_side, 2)
    const  = np.array(
        [i + 1j * q for i in levels for q in levels], dtype=np.complex128
    )
    return const / np.sqrt(np.mean(np.abs(const) ** 2))


def qam_hard_demod(
    samples: np.ndarray, constellation: np.ndarray
) -> np.ndarray:
    """최소 유클리드 거리 기준 Hard 결정 복조."""
    dist = np.abs(samples[:, None] - constellation[None, :]) ** 2
    return np.argmin(dist, axis=1)


# ============================================================
# 5. LFM-QAM 동기화 및 복조
# ============================================================

def synchronize(
    rx_real:        np.ndarray,
    ref_chirp_if:   np.ndarray,
    search_symbols: int = 5,
) -> int:
    """
    교차 상관(cross-correlation)으로 첫 번째 LFM 심볼 시작 인덱스를 탐색합니다.

    Parameters
    ----------
    rx_real        : 실수 수신 신호
    ref_chirp_if   : IF 대역 레퍼런스 Chirp (1 심볼 길이)
    search_symbols : 탐색 구간 (심볼 수)

    Returns
    -------
    start_idx : int
    """
    rx = np.asarray(rx_real, dtype=np.float64).reshape(-1)
    ref = np.asarray(ref_chirp_if, dtype=np.float64).reshape(-1)
    n_sym  = len(ref)
    if n_sym == 0 or len(rx) < n_sym:
        return 0

    search = rx[: min(len(rx), search_symbols * n_sym)]
    if len(search) < n_sym:
        return 0

    # scipy.signal.correlate(..., mode="valid") replacement to avoid hard dependency.
    corr = np.correlate(search, ref, mode="valid")
    return int(np.argmax(np.abs(corr)))


def run_demod(
    rx_signal:       np.ndarray,
    base_chirp:      np.ndarray,
    qam_symbols_ref: np.ndarray,
    fs:              float,
    B:               float,
    Ts:              float,
    fc:              float,
    c0:              float,
    fspl_linear:     float,
    tau:             float,
    delay_samples:   int,
    f_if:            float = 0.0,
    modulation:      str = "16QAM",
) -> dict:
    """
    레이더 거리 추정 + LFM-QAM 통신 복조를 수행합니다.

    Parameters
    ----------
    rx_signal      : 수신 신호 (실수 IF 또는 복소 기저대역)
    base_chirp     : 기저대역 Chirp 레퍼런스 (복소수, 1 심볼 N 샘플)
    qam_symbols_ref: 송신 QAM 심볼 참조값
    fs             : 샘플링 레이트 [Sa/s]
    B              : LFM 대역폭 [Hz]
    Ts             : 심볼 주기 [s]
    fc             : 반송파 주파수 [Hz]
    c0             : 빛의 속도 [m/s]
    fspl_linear    : 자유 공간 경로 손실 (선형)
    tau            : 목표물까지의 왕복 지연 [s]
    delay_samples  : tau에 해당하는 샘플 지연 수
    f_if           : IF 주파수 [Hz]  (실수 IF 신호면 설정, 0 = 복소 기저대역)

    Returns
    -------
    dict:
        range_axis, range_profile, estimated_dist,
        qam_est, evm_db, ser
    """
    rx = np.asarray(rx_signal, dtype=np.complex128)
    bc = np.asarray(base_chirp, dtype=np.complex128)

    # 실수 IF 신호 -> 디지털 다운컨버전
    if f_if > 0.0:
        t_full = np.arange(len(rx)) / fs
        rx     = rx * np.exp(-1j * 2.0 * np.pi * f_if * t_full)
        # Remove mixer image around 2*f_if so de-chirp/QAM estimation is stable.
        lp_cutoff = min(0.45 * fs, max(1.5 * B, 1.0 / max(Ts, 1e-15)))
        rx = fft_lowpass_complex(rx, fs=fs, cutoff_hz=lp_cutoff)

    n_sym       = len(bc)
    num_symbols = min(len(qam_symbols_ref), len(rx) // n_sym)

    range_profile_accum = np.zeros(n_sym, dtype=np.float64)
    qam_est_list: list  = []

    for i in range(num_symbols):
        seg = rx[i * n_sym: (i + 1) * n_sym]

        # 레이더: De-chirping FFT
        range_profile_accum += np.abs(np.fft.fft(bc * np.conj(seg)))

        # 통신: QAM 복조
        if delay_samples >= n_sym:
            continue

        seg_delayed = rx[i * n_sym + delay_samples: (i + 1) * n_sym]
        if len(seg_delayed) != n_sym - delay_samples:
            continue

        ref = bc[: n_sym - delay_samples]
        est = np.mean(seg_delayed * np.conj(ref)) * fspl_linear
        est *= np.exp(1j * 2.0 * np.pi * fc * tau)
        qam_est_list.append(est)

    qam_est = np.array(qam_est_list, dtype=np.complex128)
    qam_ref = qam_symbols_ref[: len(qam_est)]

    # 1-tap complex equalization to remove common gain/phase mismatch.
    # In short cable / low-distortion measurements this should make
    # constellation alignment stable and interpretable.
    if len(qam_est) > 0:
        den = np.vdot(qam_est, qam_est) + 1e-15
        h_ls = np.vdot(qam_est, qam_ref) / den
        qam_est_eq = qam_est * h_ls
    else:
        qam_est_eq = qam_est

    # 거리 축
    freq_axis      = np.fft.fftfreq(n_sym, d=1.0 / fs)
    pos            = freq_axis >= 0
    range_axis     = freq_axis[pos] * c0 / (2.0 * B / Ts)
    range_profile  = (range_profile_accum / max(num_symbols, 1))[pos]
    estimated_dist = (
        float(range_axis[np.argmax(range_profile)])
        if len(range_profile) else float("nan")
    )

    # EVM / SER
    if len(qam_est_eq) > 0:
        err      = qam_est_eq - qam_ref
        evm_rms  = np.sqrt(
            np.mean(np.abs(err) ** 2) / np.mean(np.abs(qam_ref) ** 2)
        )
        evm_db   = 20.0 * np.log10(evm_rms + 1e-15)
        m = 4 if str(modulation).strip().upper() == "QPSK" else 16
        const    = make_qam_constellation(m)
        ser      = float(
            np.mean(
                qam_hard_demod(qam_ref, const) != qam_hard_demod(qam_est_eq, const)
            )
        )
    else:
        evm_db = ser = float("nan")

    return {
        "range_axis":     range_axis,
        "range_profile":  range_profile,
        "estimated_dist": estimated_dist,
        "qam_est":        qam_est,
        "qam_est_eq":     qam_est_eq,
        "qam_ref":        qam_ref,
        "evm_db":         float(evm_db),
        "ser":            ser,
    }


def plot_demod_results(
    res:       dict,
    t_rx:      np.ndarray,
    rx_signal: np.ndarray,
    start_idx: int,
    n_sym:     int,
) -> None:
    """거리 프로파일, 수신 파형, QAM 성상도를 시각화합니다."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 4))

    # -- 거리 프로파일 -----------------------------------------------------
    ax = axes[0]
    ax.plot(res["range_axis"], res["range_profile"])
    if not np.isnan(res["estimated_dist"]):
        ax.axvline(
            x=res["estimated_dist"], color="red", linestyle="--",
            label=f"Est. {res['estimated_dist']:.2f} m",
        )
    ax.set_title("Range Profile (De-chirped)")
    ax.set_xlabel("Range [m]")
    ax.set_ylabel("Magnitude")
    ax.legend()
    ax.grid(True)

    # -- 수신 파형 + 동기화 위치 -------------------------------------------
    ax     = axes[1]
    n_show = min(len(t_rx), 3 * n_sym)
    ax.plot(
        t_rx[:n_show] * 1e6, np.real(rx_signal[:n_show]),
        linewidth=0.4, label="RX",
    )
    if start_idx < len(t_rx):
        ax.axvline(
            x=t_rx[start_idx] * 1e6, color="red", linestyle="--",
            linewidth=0.8, label="Sync",
        )
    ax.set_title("Received Signal & Sync Point")
    ax.set_xlabel("Time [us]")
    ax.set_ylabel("Amplitude [V]")
    ax.legend()
    ax.grid(True)

    # -- QAM 성상도 --------------------------------------------------------
    ax = axes[2]
    qe = res["qam_est"]
    if len(qe) > 0:
        const = make_qam_constellation(16)
        ax.scatter(const.real, const.imag, s=120, alpha=0.3, label="Ideal TX")
        ax.scatter(qe.real, qe.imag, marker="x", color="red",
                   s=60, label="Demod RX")
        ax.set_title(
            f"Constellation  EVM={res['evm_db']:.1f} dB  SER={res['ser']:.3f}"
        )
    else:
        ax.set_title("Constellation (no data)")
    ax.set_xlabel("In-Phase")
    ax.set_ylabel("Quadrature")
    ax.legend()
    ax.grid(True)

    plt.tight_layout()
    plt.show()


# ============================================================
# 6. Main Entry Point
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Teledyne LeCroy LabMaster DSO + LFM-QAM 복조",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # -- 소스 모드 ---------------------------------------------------------
    parser.add_argument(
        "--mode", choices=["live", "trc", "sim"], default="sim",
        help="신호 소스: live=DSO 실시간, trc=.trc 파일, sim=시뮬레이션",
    )

    # -- Live DSO 옵션 -----------------------------------------------------
    parser.add_argument("--host",    type=str, default="192.168.0.30",
                        help="DSO IP 주소 (--mode live)")
    parser.add_argument(
        "--dso-type",
        type=str,
        default="lecroy",
        choices=["lecroy", "keysight_uxr"],
        help="DSO 종류 (--mode live): lecroy 또는 keysight_uxr",
    )
    parser.add_argument("--ch",      type=str, default="C1",
                        help="DSO 채널 (C1, C2, C3, C4)")
    parser.add_argument("--timeout", type=int, default=10_000,
                        help="VISA 타임아웃 [ms]")

    # -- TRC 파일 옵션 -----------------------------------------------------
    parser.add_argument("--trc", type=str, default=None,
                        help=".trc 파일 경로 (--mode trc)")

    # -- 시뮬레이션 / 레퍼런스 데이터 --------------------------------------
    parser.add_argument("--sim", type=str, default="data/sim_isac_lfm_qam.npz",
                        help="레퍼런스 파라미터 npz")
    parser.add_argument("--dso-fs", type=float, default=80e9,
                        help="DSO 샘플링 레이트 [Hz] (파일에 포함 안 된 경우)")

    # -- 신호 파라미터 -----------------------------------------------------
    parser.add_argument("--f-if", type=float, default=10e9,
                        help="IF 주파수 [Hz]  (실수 IF 신호인 경우)")

    # -- 출력 --------------------------------------------------------------
    parser.add_argument("--out", type=str, default="data/dso_demod_result.npz",
                        help="복조 결과 저장 경로")
    parser.add_argument("--no-demod", action="store_true",
                        help="복조 생략 -- 시간/주파수 관찰만 수행")

    args = parser.parse_args()

    # -- 시뮬레이션 파라미터 로드 ------------------------------------------
    sim_path = Path(args.sim)
    if not sim_path.exists():
        raise FileNotFoundError(f"시뮬레이션 파일 없음: {sim_path}")

    sim           = np.load(sim_path)
    base_chirp    = sim["base_chirp"]
    qam_symbols   = sim["qam_symbols"]
    fs_sim        = float(sim["fs"][0])
    Ts            = float(sim["Ts"][0])
    B             = float(sim["B"][0])
    fc            = float(sim["fc"][0])
    c0            = float(sim["c0"][0])
    tau           = float(sim["tau"][0])
    fspl_linear   = float(sim["fspl_linear"][0])
    delay_samples = int(  sim["delay_samples"][0])

    # -- 수신 신호 획득 ----------------------------------------------------
    if args.mode == "live":
        print(f"[Mode] Live  -- DSO {args.host} / {args.ch}")
        with create_dso_controller(dso_type=args.dso_type, host=args.host, timeout_ms=args.timeout) as dso:
            t_rx, rx_signal, fs_dso = dso.capture(channel=args.ch, fallback_fs=args.dso_fs)

    elif args.mode == "trc":
        if args.trc is None:
            parser.error("--mode trc 사용 시 --trc <파일경로>를 지정해 주세요.")
        print(f"[Mode] TRC   -- {args.trc}")
        t_rx, rx_signal, fs_dso = load_trc(args.trc)

    else:  # sim
        print("[Mode] Simulation rx_signal")
        rx_signal = np.asarray(sim["rx_signal"], dtype=np.complex128)
        fs_dso    = fs_sim
        t_rx      = np.arange(len(rx_signal)) / fs_dso

    fs_dso = float(fs_dso)
    print(f"[Signal] N={len(rx_signal):,}, fs={fs_dso/1e9:.3f} GSa/s")

    # -- [단계 2] 시간 / 주파수 관찰 --------------------------------------
    plot_time_and_spectrum(
        t_rx, rx_signal, fs_dso,
        title=f"[{args.mode.upper()}] {args.ch}",
        f_if=args.f_if,
    )

    if args.no_demod:
        return

    # -- [단계 3] 샘플링 레이트 정렬 --------------------------------------
    if not np.isclose(fs_dso, fs_sim):
        print(f"[Resample] {fs_dso/1e9:.3f} GHz -> {fs_sim/1e9:.3f} GHz")
        rx_signal = fft_resample_complex(rx_signal, fs_in=fs_dso, fs_out=fs_sim)
        t_rx      = np.arange(len(rx_signal)) / fs_sim
        fs_dso    = fs_sim

    # -- [단계 4] 동기화 --------------------------------------------------
    n_sym = len(base_chirp)
    k     = B / Ts
    t_sym = np.arange(n_sym) / fs_sim
    ref_chirp_if = np.real(
        np.exp(1j * np.pi * k * t_sym ** 2)
        * np.exp(1j * 2.0 * np.pi * args.f_if * t_sym)
    )
    start_idx = synchronize(np.real(rx_signal), ref_chirp_if)
    print(f"[Sync] 첫 번째 심볼 시작 인덱스: {start_idx}")

    # -- [단계 5] LFM-QAM 복조 --------------------------------------------
    res = run_demod(
        rx_signal      = rx_signal[start_idx:],
        base_chirp     = base_chirp,
        qam_symbols_ref= qam_symbols,
        fs             = fs_sim,
        B              = B,
        Ts             = Ts,
        fc             = fc,
        c0             = c0,
        fspl_linear    = fspl_linear,
        tau            = tau,
        delay_samples  = delay_samples,
        f_if           = args.f_if,
    )

    print("=== 복조 결과 ===")
    print(f"  추정 거리: {res['estimated_dist']:.3f} m")
    print(f"  통신 EVM:  {res['evm_db']:.2f} dB")
    print(f"  SER:       {res['ser']:.4f}")

    # -- [단계 6] 시각화 및 저장 ------------------------------------------
    plot_demod_results(res, t_rx, rx_signal, start_idx, n_sym)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_path,
        range_axis    = res["range_axis"].astype(np.float64),
        range_profile = res["range_profile"].astype(np.float64),
        estimated_dist= np.array([res["estimated_dist"]], dtype=np.float64),
        qam_est       = res["qam_est"].astype(np.complex64),
        evm_db        = np.array([res["evm_db"]], dtype=np.float64),
        ser           = np.array([res["ser"]],   dtype=np.float64),
    )
    print(f"[Saved] {out_path}")


if __name__ == "__main__":
    main()



