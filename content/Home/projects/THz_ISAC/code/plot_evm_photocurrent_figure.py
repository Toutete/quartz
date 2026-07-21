"""Plot measured EVM points versus manually recorded UTC-PD photocurrent.

This script intentionally shows measured points only.  It does not draw fitted,
simulated, extrapolated, or threshold/reference curves.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


MEASURED = {
    "16QAM @ 15 GBaud": {
        "baud_gbaud": 15.0,
        "iph_ma": [4.5, 5.0, 5.5, 6.0, 6.5, 7.0],
        "evm_db": [-13.78, -14.45, -15.55, -16.22, -16.9, -17.59],
    },
    "32QAM @ 16 GBaud": {
        "baud_gbaud": 16.0,
        "iph_ma": [4.5, 5.0, 5.5, 6.0, 6.5, 7.0],
        "evm_db": [-13.48, -13.68, -14.53, -15.39, -16.57, -17.49],
    },
}


def make_figure(args: argparse.Namespace) -> None:
    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter, ScalarFormatter

    plt.rcParams.update({
        "font.family": "Times New Roman",
        "mathtext.fontset": "stix",
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 7.5,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "axes.linewidth": 0.8,
    })

    markers = {
        "16QAM @ 15 GBaud": dict(marker="o", markerfacecolor="red", markeredgecolor="red"),
        "32QAM @ 16 GBaud": dict(marker="o", markerfacecolor="none", markeredgecolor="blue"),
    }

    fig, ax = plt.subplots(figsize=(3, 2.5), dpi=args.dpi)

    for label, entry in MEASURED.items():
        iph = np.asarray(entry["iph_ma"], dtype=float)
        evm = np.asarray(entry["evm_db"], dtype=float)
        ax.plot(iph, evm, "none", label=label, **markers[label])

    ax.set_xlabel("UTC-PD photocurrent (mA)")
    ax.set_ylabel("EVM (dB)")
    ax.set_xscale("log")
    ax.set_xticks([4.5, 5, 5.5, 6, 6.5, 7])
    ax.set_ylim(-20, -10)
    ax.set_xlim(4.5, 7)
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, alpha=0.3, which="major")
    ax.legend(loc="best", frameon=False, fontsize=7)
    fig.tight_layout()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"Saved: {args.out}")
    if args.show:
        plt.show()
    else:
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "fig_evm_vs_photocurrent.png",
    )
    parser.add_argument("--dpi", type=int, default=300)
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--show", dest="show", action="store_true")
    display_group.add_argument("--no-show", dest="show", action="store_false")
    parser.set_defaults(show=True)
    args = parser.parse_args()
    make_figure(args)


if __name__ == "__main__":
    main()
