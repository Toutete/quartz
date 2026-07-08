from __future__ import annotations

from .osa_control import configure_osa, open_osa, resolve_sweep_config


def init_AQ6317(
    center_wavelength_nm: float = 1550.1,
    span_nm: float = 1.0,
    osa_gpib: str = "GPIB0::1::INSTR",
    *,
    resolution_nm: float | None = None,
    backend: str | None = None,
    wait_s: float = 0.5,
    timeout_ms: int = 20_000,
    resolution_command: str | None = None,
):
    config = resolve_sweep_config(
        center_wavelength_nm=center_wavelength_nm,
        span_nm=span_nm,
        resolution_nm=resolution_nm,
        resource=osa_gpib,
        model="AQ6317",
        wait_s=wait_s,
        timeout_ms=timeout_ms,
        backend=backend,
        resolution_command=resolution_command,
    )
    rm, inst = open_osa(config.resource, backend=config.backend, timeout_ms=config.timeout_ms)
    configure_osa(inst, config)
    return rm, inst
