"""Remove the throwaway parts of a job directory, once the album can replace them.

``review/`` is the bulk of a finished job — around 760 MB on a 35-minute album,
against 217 MB for the album itself — and it exists only to answer checkpoints
that have already been answered. Everything else in the directory is either the
recording, the plans that reproduce the album from it, or the measurements those
plans cite, and none of that is this script's business.

    python scripts/clean_job.py jobs/<record>            # say what would go
    python scripts/clean_job.py jobs/<record> --delete    # actually remove it

**Dry run by default, and removal works from an allow-list.** Anything the script
does not recognise is reported and left where it is, so a file that drifted into
the directory gets noticed rather than swept up with the renders.

**It refuses while the album cannot stand in for what it is deleting.** Every
manifest in ``album/`` must name outputs that exist and whose SHA-256 still
matches what the manifest recorded. That is the cheap half of ``vinyl-process
verify`` — it proves the album on disk is the album the receipt describes, though
not that re-running the plan would reproduce it, which only ``verify`` shows.
``--force`` skips the check for the case where the album was moved away
deliberately; there is no flag that makes it delete a plan or a recording.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from vinyl_process.hashing import digest_file

#: Directory names inside a job that exist only to answer a checkpoint.
DISPOSABLE_DIRECTORIES = ("review",)

#: What a job legitimately holds besides the disposable renders. Reported as
#: "kept" so the listing accounts for the whole directory rather than a slice.
KEPT_PATTERNS = (
    ("the recording", ("*.flac", "*.wav", "*.aiff", "*.aif")),
    ("plans — these reproduce the album", ("plan-*.json", "processing_plan.json")),
    ("measurements the plans cite", ("analysis*.json",)),
    ("analyzer parameters", ("*.toml",)),
)


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{value:,.0f} B"
        value /= 1024
    return f"{value:,.1f} GB"


def album_problems(album: Path) -> list[str]:
    """Why the album cannot yet stand in for the renders. Empty means it can."""
    if not album.is_dir():
        return [f"{album} does not exist"]
    manifests = sorted(album.glob("manifest*.json"))
    if not manifests:
        return [f"{album} holds no manifest, so nothing says what it should contain"]

    problems: list[str] = []
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{manifest_path.name} cannot be read: {error}")
            continue
        outputs = manifest.get("outputs") or []
        if not outputs:
            problems.append(f"{manifest_path.name} lists no outputs")
        for entry in outputs:
            target = album / Path(str(entry.get("path", ""))).name
            if not target.is_file():
                problems.append(f"{manifest_path.name}: {target.name} is missing")
            elif digest_file(target) != entry.get("sha256"):
                problems.append(f"{manifest_path.name}: {target.name} does not match its digest")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("job", type=Path, help="the job directory, e.g. jobs/<record>")
    parser.add_argument(
        "--delete", action="store_true", help="remove the files instead of listing them"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="delete even though the album cannot be checked (it was moved away, say)",
    )
    arguments = parser.parse_args()

    job: Path = arguments.job
    if not job.is_dir():
        parser.error(f"{job} is not a directory")

    disposable = [job / name for name in DISPOSABLE_DIRECTORIES if (job / name).is_dir()]
    reclaimable = sum(directory_size(path) for path in disposable)

    kept: dict[Path, str] = {}
    for reason, patterns in KEPT_PATTERNS:
        for pattern in patterns:
            for path in job.glob(pattern):
                kept.setdefault(path, reason)
    album = job / "album"
    if album.is_dir():
        kept[album] = "the album"

    accounted = set(kept) | set(disposable)
    unrecognised = sorted(path for path in job.iterdir() if path not in accounted)

    print(f"{job}")
    for path, reason in sorted(kept.items()):
        print(f"  keep    {path.name:<44} {reason}")
    for path in unrecognised:
        print(f"  keep    {path.name:<44} not recognised — left alone")
    if not disposable:
        print("  nothing disposable here")
        return 0
    for path in disposable:
        print(f"  REMOVE  {path.name:<44} {human(directory_size(path))}")

    problems = album_problems(album)
    if problems and not arguments.force:
        print("\nrefusing: the album cannot stand in for these yet")
        for problem in problems:
            print(f"  - {problem}")
        print("  run the plans into album/ first, or pass --force if that is deliberate")
        return 1
    if problems:
        print("\n--force: deleting although the album could not be checked")
        for problem in problems:
            print(f"  - {problem}")

    if not arguments.delete:
        print(f"\ndry run — {human(reclaimable)} would be freed; pass --delete to remove")
        return 0

    for path in disposable:
        shutil.rmtree(path)
        print(f"removed {path}")
    print(f"freed {human(reclaimable)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
