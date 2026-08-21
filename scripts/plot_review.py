"""Draw the figures a planning checkpoint is read from.

A review render answers "did this stage do what I meant" and the answer is easier
to see than to describe. This writes two views of one rendered directory:

* ``side-<x>.png``  — every track of one recording stacked, for questions about
  the whole side: are the cuts where they should be, do the sides sit at the same
  level, does one track stand out.
* ``track-<nn>.png`` — one track per image, at five times the vertical resolution,
  for questions about one boundary or one tail. Both views were tried on the same
  album and the stacked one hid two findings the per-track one made obvious: a
  2.2 s run-out tail that read as a hairline, and whether a long fade descended
  smoothly or stepped.

Each image is a linear waveform (full scale, so clipping and squashing show) over
a dB panel (0 to -80 dBFS, peak and RMS as lines, so the noise floor and the fades
show). Neither panel says whether anything is *audible*: see the skills.

This is a review artifact, disposable in exactly the way ``review/split-loud/`` is.
It measures nothing that reaches ``analysis.json`` and decides nothing that reaches
a plan; it lives here rather than in the job directory because a job directory
holds no scripts, and outside the package because it is not a pipeline stage.

    python scripts/plot_review.py review/level

Groups come from the manifests the render wrote — one per recording, so a
two-sided album gets one side figure each. A directory with no manifest (the flat
``review/split-loud/`` copy) is drawn as a single group.
"""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
import soundfile as sf

RGB = npt.NDArray[np.uint8]
F64 = npt.NDArray[np.float64]

WIDTH = 1800
MARGIN = 40
GAP = 26
SIDE_PANEL = 150
WAVE_PANEL = 300
DB_PANEL = 260
DB_TOP = 0.0
DB_BOTTOM = -80.0

BACKGROUND = (22, 22, 24)
GRID_FAINT = (52, 56, 64)
GRID_STRONG = (118, 124, 138)
ZERO_LINE = (95, 100, 112)
WAVE_COLOURS = ((120, 190, 255), (255, 165, 120), (150, 220, 160), (220, 160, 230))
PEAK_LINE = (105, 115, 135)
RMS_LINE = (255, 215, 110)

AUDIO_SUFFIXES = (".flac", ".wav", ".aiff", ".aif")


class Group(NamedTuple):
    """One recording's worth of rendered tracks, in album order."""

    name: str
    files: list[Path]


class Envelope(NamedTuple):
    """Per-column summary of a signal, one column per pixel."""

    low: F64
    high: F64
    peak: F64
    rms: F64


# --------------------------------------------------------------------------- #
# PNG output. Hand-rolled so the tool adds no plotting dependency to a project
# whose runtime needs none; the format's uncompressed-filter form is four chunks.
def write_png(path: Path, image: RGB) -> None:
    height, width, _ = image.shape
    raw = b"".join(b"\x00" + image[y].tobytes() for y in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------- #
def read_mono(path: Path) -> tuple[F64, int]:
    samples, sample_rate = sf.read(str(path), dtype="float64", always_2d=True)
    mono: F64 = np.asarray(samples, dtype=np.float64).mean(axis=1)
    return mono, int(sample_rate)


def envelope_of(signal: F64, columns: int) -> Envelope:
    edges = np.linspace(0, signal.size, columns + 1).astype(int)
    low = np.empty(columns, dtype=np.float64)
    high = np.empty(columns, dtype=np.float64)
    peak = np.empty(columns, dtype=np.float64)
    rms = np.empty(columns, dtype=np.float64)
    for index in range(columns):
        window = signal[edges[index] : max(edges[index] + 1, edges[index + 1])]
        low[index] = window.min()
        high[index] = window.max()
        peak[index] = np.abs(window).max()
        rms[index] = np.sqrt((window**2).mean())
    return Envelope(low=low, high=high, peak=peak, rms=rms)


def to_db(values: F64) -> F64:
    return np.asarray(20.0 * np.log10(np.maximum(values, 1e-9)), dtype=np.float64)


def db_row(value: float, top: int, height: int) -> int:
    position = (DB_TOP - value) / (DB_TOP - DB_BOTTOM)
    return top + int(np.clip(position, 0.0, 1.0) * (height - 1))


# --------------------------------------------------------------------------- #
def draw_time_grid(image: RGB, top: int, height: int, duration: float, columns: int) -> None:
    """A line every 30 s, brighter on the minute, so positions can be read off."""
    if duration <= 0:
        return
    for second in range(30, int(duration), 30):
        column = MARGIN + int(second / duration * columns)
        if MARGIN <= column < MARGIN + columns:
            image[top : top + height, column] = GRID_STRONG if second % 60 == 0 else GRID_FAINT


def draw_waveform(
    image: RGB, top: int, height: int, env: Envelope, columns: int, colour: tuple[int, int, int]
) -> None:
    middle = top + height // 2
    half = height // 2 - 2
    image[middle, MARGIN : MARGIN + columns] = ZERO_LINE
    for fraction in (0.25, 0.5, 0.75, 1.0):
        for sign in (-1, 1):
            row = int(middle + sign * fraction * half)
            row = max(top, min(top + height - 1, row))
            image[row, MARGIN : MARGIN + columns] = GRID_STRONG if fraction == 1.0 else GRID_FAINT
    for index in range(columns):
        upper = int(middle - np.clip(env.high[index], -1.0, 1.0) * half)
        lower = int(middle - np.clip(env.low[index], -1.0, 1.0) * half)
        image[min(upper, lower) : max(upper, lower) + 1, MARGIN + index] = colour


def draw_db(image: RGB, top: int, height: int, env: Envelope, columns: int) -> None:
    """Peak and RMS as *lines*. Filling to the baseline saturates the panel: on a
    dense track everything above -40 dB becomes one block and the floor vanishes,
    which is the failure this drawing replaced."""
    for level in range(0, int(DB_BOTTOM) - 1, -10):
        row = db_row(float(level), top, height)
        image[row, MARGIN : MARGIN + columns] = (
            GRID_STRONG if level in (-20, -40, -60) else GRID_FAINT
        )
    peak_db = to_db(env.peak)
    rms_db = to_db(env.rms)
    previous: dict[str, int] = {}
    for index in range(columns):
        for key, values, colour in (("peak", peak_db, PEAK_LINE), ("rms", rms_db, RMS_LINE)):
            row = db_row(float(values[index]), top, height)
            before = previous.get(key, row)
            image[min(before, row) : max(before, row) + 1, MARGIN + index] = colour
            previous[key] = row


# --------------------------------------------------------------------------- #
def side_figure(group: Group, out: Path, colour: tuple[int, int, int]) -> Path:
    """One panel per track, stacked in album order: the whole side at a glance."""
    columns = WIDTH - 2 * MARGIN
    count = len(group.files)
    height = MARGIN + count * SIDE_PANEL + (count - 1) * GAP + MARGIN
    image: RGB = np.full((height, WIDTH, 3), BACKGROUND, dtype=np.uint8)
    for position, path in enumerate(group.files):
        signal, sample_rate = read_mono(path)
        top = MARGIN + position * (SIDE_PANEL + GAP)
        draw_time_grid(image, top, SIDE_PANEL, signal.size / sample_rate, columns)
        draw_waveform(image, top, SIDE_PANEL, envelope_of(signal, columns), columns, colour)
    target = out / f"side-{group.name}.png"
    write_png(target, image)
    return target


def track_figure(path: Path, out: Path, colour: tuple[int, int, int]) -> Path:
    """One track: linear waveform over a dB panel, at full vertical resolution."""
    signal, sample_rate = read_mono(path)
    duration = signal.size / sample_rate
    columns = WIDTH - 2 * MARGIN
    height = MARGIN + WAVE_PANEL + GAP + DB_PANEL + MARGIN
    image: RGB = np.full((height, WIDTH, 3), BACKGROUND, dtype=np.uint8)
    env = envelope_of(signal, columns)
    wave_top = MARGIN
    db_top = MARGIN + WAVE_PANEL + GAP
    draw_time_grid(image, wave_top, WAVE_PANEL, duration, columns)
    draw_time_grid(image, db_top, DB_PANEL, duration, columns)
    draw_waveform(image, wave_top, WAVE_PANEL, env, columns, colour)
    draw_db(image, db_top, DB_PANEL, env, columns)
    target = out / f"{path.stem}.png"
    write_png(target, image)
    return target


# --------------------------------------------------------------------------- #
def groups_in(render: Path) -> list[Group]:
    """One group per manifest, because a manifest is one recording's receipt.

    Without manifests — the flat loud copy has none by design — everything in the
    directory is one group, which is what that copy is.
    """
    groups: list[Group] = []
    for manifest_path in sorted(render.glob("manifest*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # A receipt is written beside a copy of the plan that produced it
        # (adr/0018), and that copy matches the glob too. Identify by
        # document_type rather than by name, which is what it is for.
        if manifest.get("document_type") != "manifest":
            continue
        outputs = sorted(manifest["outputs"], key=lambda entry: int(entry["track_index"]))
        files = [render / Path(str(entry["path"])).name for entry in outputs]
        present = [path for path in files if path.exists()]
        if present:
            name = manifest_path.stem.replace("manifest", "").strip("-_") or manifest_path.stem
            groups.append(Group(name=name.replace("side-", "") or name, files=present))
    if groups:
        return groups
    loose = sorted(p for p in render.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)
    return [Group(name="all", files=loose)] if loose else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("render", type=Path, help="a rendered directory, e.g. review/level")
    parser.add_argument(
        "-o", "--out", type=Path, default=None, help="where to write (default: <render>/plots)"
    )
    parser.add_argument(
        "--view",
        choices=("both", "side", "track"),
        default="both",
        help="which figures to draw (default: both)",
    )
    arguments = parser.parse_args()

    render: Path = arguments.render
    if not render.is_dir():
        parser.error(f"{render} is not a directory")
    groups = groups_in(render)
    if not groups:
        parser.error(f"no audio found in {render}")

    out: Path = arguments.out if arguments.out is not None else render / "plots"
    out.mkdir(parents=True, exist_ok=True)

    for index, group in enumerate(groups):
        colour = WAVE_COLOURS[index % len(WAVE_COLOURS)]
        if arguments.view in ("both", "side"):
            print(side_figure(group, out, colour))
        if arguments.view in ("both", "track"):
            for path in group.files:
                print(track_figure(path, out, colour))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
