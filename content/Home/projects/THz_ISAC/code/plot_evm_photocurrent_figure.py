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
        "font.size": 9,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 8,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "axes.linewidth": 0.9,
        "lines.linewidth": 1.2,
        "savefig.dpi": args.dpi,
    })

    styles = {
        "16QAM @ 15 GBaud": dict(color="#d62728", marker="o", markerfacecolor="#d62728"),
        "32QAM @ 16 GBaud": dict(color="#1f77b4", marker="s", markerfacecolor="none"),
    }

    fig, ax = plt.subplots(figsize=(3.5, 2.6), dpi=args.dpi)

    for label, entry in MEASURED.items():
        iph = np.asarray(entry["iph_ma"], dtype=float)
        evm = np.asarray(entry["evm_db"], dtype=float)
        style = styles[label]
        ax.plot(
            iph,
            evm,
            label=label,
            color=style["color"],
            marker=style["marker"],
            markerfacecolor=style["markerfacecolor"],
            markeredgecolor=style["color"],
            markeredgewidth=0.9,
            markersize=4.0,
            linewidth=1.25,
        )

    ax.set_xlabel("UTC-PD photocurrent (mA)")
    ax.set_ylabel("EVM (dB)")
    ax.set_xticks([4.5, 5, 5.5, 6, 6.5, 7])
    ax.set_xlim(4.35, 7.15)
    ax.set_ylim(-18.5, -13.0)
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, color="#cbd5e1", linewidth=0.45, alpha=0.75)
    ax.legend(
        loc="lower left",
        frameon=True,
        facecolor="white",
        edgecolor="#cbd5e1",
        framealpha=0.92,
        handlelength=1.7,
        borderpad=0.35,
        labelspacing=0.3,
    )
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(True)
        ax.spines[side].set_linewidth(0.9)
    fig.tight_layout(pad=0.35)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight", pad_inches=0.02)
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
    parser.add_argument("--dpi", type=int, default=600)
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--show", dest="show", action="store_true")
    display_group.add_argument("--no-show", dest="show", action="store_false")
    parser.set_defaults(show=True)
    args = parser.parse_args()
    make_figure(args)


if __name__ == "__main__":
    main()
