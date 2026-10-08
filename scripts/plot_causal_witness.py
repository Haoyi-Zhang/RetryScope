#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--cells', type=Path, required=True)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--svg', type=Path, required=True)
    args = parser.parse_args()
    rows = list(csv.DictReader(args.cells.open()))
    levels = sorted({int(row['concurrency']) for row in rows})
    token = []
    timestamp = []
    for level in levels:
        selected = [row for row in rows if int(row['concurrency']) == level]
        weights = [int(row['wire_attempts']) for row in selected]
        total = sum(weights)
        token.append(sum(float(row['token_assignment']) * w for row, w in zip(selected, weights)) / total * 100)
        timestamp.append(sum(float(row['timestamp_assignment']) * w for row, w in zip(selected, weights)) / total * 100)
    fig, ax = plt.subplots(figsize=(3.45, 2.25))
    ax.plot(levels, token, marker='o', linewidth=1.5, label='Causal token')
    ax.plot(levels, timestamp, marker='s', linewidth=1.5, label='Time window')
    ax.set_xlabel('Concurrent operations')
    ax.set_ylabel('Exact attempt assignment (%)')
    ax.set_xticks(levels)
    ax.set_ylim(-3, 103)
    ax.grid(True, axis='y', linewidth=0.4, alpha=0.5)
    ax.legend(loc='center right', frameon=True, fontsize=8)
    fig.tight_layout(pad=0.35)
    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.pdf, bbox_inches='tight')
    fig.savefig(args.svg, bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    main()
