import numpy as np


def normalize_power_weights(power, floor=1e-15, temperature=1.0):
    """Return nonnegative PD combining weights that sum to one."""
    p = np.asarray(power, dtype=np.float64)
    p = np.maximum(p, floor)
    if temperature != 1.0:
        p = p ** (1.0 / max(float(temperature), 1e-6))
    return p / (np.sum(p) + floor)


def softmax_log_power_weights(log_power, temperature=1.0):
    z = np.asarray(log_power, dtype=np.float64).reshape(-1)
    z = z / max(float(temperature), 1e-6)
    z = z - np.max(z)
    w = np.exp(z)
    return w / (np.sum(w) + 1e-15)


def combine_channels(samples, weights):
    """Weighted DSP combiner for real or complex channel samples.

    samples shape:
        (channels,) or (channels, time)
    weights shape:
        (channels,)
    """
    x = np.asarray(samples)
    w = np.asarray(weights, dtype=np.float64).reshape(-1)
    if x.shape[0] != w.size:
        raise ValueError(f"channel mismatch: samples has {x.shape[0]}, weights has {w.size}")
    return np.tensordot(w, x, axes=(0, 0))


def quantize_q15(weights):
    """Quantize normalized positive weights to unsigned Q1.15 coefficients."""
    w = normalize_power_weights(weights)
    q = np.round(w * 32767.0).astype(np.int32)
    diff = 32767 - int(np.sum(q))
    if q.size:
        q[int(np.argmax(q))] += diff
    return np.clip(q, 0, 32767).astype(np.uint16)


def dequantize_q15(q_weights):
    return np.asarray(q_weights, dtype=np.float64) / 32767.0
