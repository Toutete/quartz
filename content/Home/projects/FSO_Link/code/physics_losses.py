"""Optional physics-informed losses for AI-PD training."""

from __future__ import annotations

import torch


def energy_consistency_loss(
    predicted_power_linear: torch.Tensor,
    reference_power_linear: torch.Tensor,
    relative_tolerance: float = 0.25,
) -> torch.Tensor:
    """Penalize nonphysical total-power changes beyond a soft tolerance."""
    pred_total = predicted_power_linear.sum(dim=(-2, -1))
    ref_total = reference_power_linear.sum(dim=(-2, -1))
    rel_error = (pred_total - ref_total).abs() / (ref_total.abs() + 1e-8)
    return torch.relu(rel_error - relative_tolerance).pow(2).mean()


def temporal_weight_smoothness_loss(weight_sequence: torch.Tensor) -> torch.Tensor:
    """Encourage slowly varying combiner coefficients.

    Expected shape: [batch, time, rows, cols].
    """
    if weight_sequence.shape[1] < 2:
        return torch.zeros((), device=weight_sequence.device, dtype=weight_sequence.dtype)
    return (weight_sequence[:, 1:] - weight_sequence[:, :-1]).pow(2).mean()


def zernike_spectrum_prior_loss(
    coeffs: torch.Tensor,
    mode_order: torch.Tensor,
    slope: float = 11.0 / 6.0,
) -> torch.Tensor:
    """Weak Kolmogorov-like decay prior for auxiliary Zernike coefficients."""
    scale = torch.pow(mode_order.to(coeffs.device).float().clamp_min(1.0), slope)
    return (coeffs.pow(2) * scale).mean()
