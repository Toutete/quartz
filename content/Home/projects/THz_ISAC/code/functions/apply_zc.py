import numpy as np

def generate_zadoff_chu(N: int, u: int) -> np.ndarray:
    """Generate a Zadoff-Chu sequence of length N and root u."""
    n = np.arange(N)
    return np.exp(-1j * np.pi * u * n * (n + 1) / N)
