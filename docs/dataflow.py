"""Render the high-level data-flow diagram to docs/dataflow.png.

    python docs/dataflow.py     # requires matplotlib

Kept in source so the architecture diagram stays reproducible and editable
rather than being a hand-drawn one-off.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# palette
EXT = "#e5e7eb"      # external actors (racks, browser)
SVC = "#dbeafe"      # services (FastAPI, queue, writer)
STORE = "#fef3c7"    # datastores
EDGE = "#374151"     # node borders
WRITE = "#1d4ed8"    # write path (solid)
READ = "#0f766e"     # read path (dashed)
TXT = "#111827"

fig, ax = plt.subplots(figsize=(12, 6.2))
ax.set_xlim(0, 13)
ax.set_ylim(0, 6.4)
ax.axis("off")

def box(x, y, w, h, label, fill, sub=None):
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.4, edgecolor=EDGE, facecolor=fill, zorder=3))
    ax.text(x, y + (0.16 if sub else 0), label, ha="center", va="center",
            fontsize=10.5, fontweight="bold", color=TXT, zorder=4)
    if sub:
        ax.text(x, y - 0.24, sub, ha="center", va="center",
                fontsize=8.2, color="#4b5563", zorder=4)
    return (x, y, w, h)

def arrow(a, b, color, style="-", rad=0.0, label=None, lx=0, ly=0, lfs=8.3):
    p = FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=15,
                        linewidth=1.6, color=color, linestyle=style,
                        connectionstyle=f"arc3,rad={rad}", zorder=2,
                        shrinkA=2, shrinkB=2)
    ax.add_patch(p)
    if label:
        mx, my = (a[0] + b[0]) / 2 + lx, (a[1] + b[1]) / 2 + ly
        ax.text(mx, my, label, ha="center", va="center", fontsize=lfs,
                color=color, zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))

LANE = 4.35
racks  = box(1.35, LANE, 2.0, 1.0, "racks", EXT, "{deviceId, power,\ntemperature, ts}")
api    = box(4.35, LANE, 1.9, 0.9, "FastAPI", SVC, "POST /api/metrics")
queue  = box(7.05, LANE, 1.9, 0.9, "asyncio.Queue", SVC, "bounded buffer")
writer = box(9.75, LANE, 1.9, 0.9, "batch writer", SVC, "flush ≤500 / 250ms")
tsdb   = box(12.0, 5.35, 2.0, 0.95, "TimescaleDB", STORE, "hypertable")
dfly   = box(12.0, 3.35, 2.0, 0.95, "Dragonfly", STORE, "latest / device")
browser = box(4.35, 1.15, 2.0, 0.95, "browser", EXT, "polls every 5s / 15s")

# --- write path (solid) ---
arrow((racks[0]+1.0, LANE), (api[0]-0.95, LANE), WRITE, label="POST → 202", ly=0.28)
arrow((api[0]+0.95, LANE), (queue[0]-0.95, LANE), WRITE, label="put_nowait()", ly=0.28)
arrow((queue[0]+0.95, LANE), (writer[0]-0.95, LANE), WRITE, label="drain\nbatch", ly=0.34, lfs=7.6)
arrow((writer[0]+0.95, LANE+0.15), (tsdb[0]-1.0, 5.35), WRITE, rad=0.15, label="COPY", lx=0.1, ly=0.28)
arrow((writer[0]+0.95, LANE-0.15), (dfly[0]-1.0, 3.35), WRITE, rad=-0.12, label="write-through\n(CAS)", lx=0.15, ly=-0.3, lfs=7.6)

# --- read path (dashed): both stores arc high over the write lane into FastAPI,
#     then a single response arrow down to the browser. Keeps reads clear of boxes.
arrow((tsdb[0]-1.05, 5.35), (api[0]+0.55, api[1]+0.46), READ, style="--", rad=0.30,
      label="/devices, /:id/metrics", lx=1.4, ly=0.62)
arrow((dfly[0]-0.7, dfly[1]+0.5), (api[0]-0.15, api[1]+0.46), READ, style="--", rad=0.58,
      label="/live, /summary", lx=-1.1, ly=0.55)
arrow((api[0], api[1]-0.48), (browser[0], browser[1]+0.5), READ, style="--",
      label="responses", lx=0.95, ly=0.0)

ax.text(1.35, 6.2, "high-level data flow", fontsize=13, fontweight="bold", color=TXT)

# legend
ax.plot([0.5, 1.1], [0.45, 0.45], color=WRITE, lw=1.8)
ax.text(1.25, 0.45, "write / ingest path", fontsize=8.5, va="center", color=WRITE)
ax.plot([4.3, 4.9], [0.45, 0.45], color=READ, lw=1.8, linestyle="--")
ax.text(5.05, 0.45, "read path (browser polls)", fontsize=8.5, va="center", color=READ)

plt.tight_layout()
out = os.path.join(os.path.dirname(__file__), "dataflow.png")
plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
print("wrote", out)
