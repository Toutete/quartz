"""Zernike fitting helpers for aperture-phase labels.

Use this module when the split-step simulator exposes the received aperture
phase. The fitted low-order coefficients can be added as auxiliary labels for
CNN training.
"""

from __future__ import annotations

from math import factorial
from typing import Iterable

import numpy as np


LOW_ORDER_MODES: list[tuple[int, int]] = [
    (1, -1),  # tilt y
    (1, 1),   # tilt x
    (2, 0),   # defocus
    (2, -2),  # astigmatism
    (2, 2),   # astigmatism
    (3, -1),  # coma
    (3, 1),   # coma
]


def zernike_radial(n: int, m_abs: int, rho: np.ndarray) -> np.ndarray:
    if (n - m_abs) % 2 != 0:
        return np.zeros_like(rho)
    radial = np.zeros_like(rho, dtype=np.float64)
    for k in range((n - m_abs) // 2 + 1):
        coeff = (
            (-1) ** k
            * factorial(n - k)
            / (
                factorial(k)
                * factorial((n + m_abs) // 2 - k)
                * factorial((n - m_abs) // 2 - k)
            )
        )
        radial += coeff * rho ** (n - 2 * k)
    return radial


def zernike(n: int, m: int, rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    radial = zernike_radial(n, abs(m), rho)
    if m < 0:
        return radial * np.sin(abs(m) * theta)
    if m > 0:
        return radial * np.cos(m * theta)
    return radial


def aperture_coordinates(grid_n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    axis = np.linspace(-1.0, 1.0, grid_n, dtype=np.float64)
    xx, yy = np.meshgrid(axis, axis)
    rho = np.sqrt(xx * xx + yy * yy)
    theta = np.arctan2(yy, xx)
    mask = rho <= 1.0
    return rho, theta, mask


def zernike_design_matrix(
    grid_n: int,
    modes: Iterable[tuple[int, int]] = LOW_ORDER_MODES,
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    rho, theta, default_mask = aperture_coordinates(grid_n)
    use_mask = default_mask if mask is None else (default_mask & mask.astype(bool))
    basis = [zernike(n, m, rho, theta)[use_mask] for n, m in modes]
    return np.stack(basis, axis=1), use_mask


def fit_zernike_coefficients(
    phase: np.ndarray,
    modes: Iterable[tuple[int, int]] = LOW_ORDER_MODES,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Least-squares fit of aperture phase to selected Zernike modes."""
    if phase.ndim != 2 or phase.shape[0] != phase.shape[1]:
        raise ValueError("phase must be a square 2-D array")
    design, use_mask = zernike_design_matrix(phase.shape[0], modes=modes, mask=mask)
    target = np.unwrap(np.unwrap(phase, axis=0), axis=1)[use_mask]
    coeffs, *_ = np.linalg.lstsq(design, target, rcond=None)
    return coeffs.astype(np.float32)
