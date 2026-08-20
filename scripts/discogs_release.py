"""Fetch a Discogs release, or a master's versions, for plan-metadata to read.

`www.discogs.com` answers a plain fetch with **403**, so scraping the page a
person pastes does not work. `api.discogs.com` answers the same release without
authentication, provided the request carries a User-Agent — the default one is
rejected outright. That pair of facts is the whole reason this script exists;
rediscovering it costs a turn every time.

    python scripts/discogs_release.py https://www.discogs.com/release/28396297
    python scripts/discogs_release.py 28396297 --json > release.json
    python scripts/discogs_release.py 714555 --versions      # a master's pressings

Accepts a bare id, a `release/<id>` or `master/<id>` path, or a full URL. Prints
the fields the metadata checkpoint has to show: label and catalogue number,
country, year, format, the identifiers that pin a pressing (barcode, matrix and
runout), and the tracklist with positions and durations.

`--versions` is for the case plan-metadata calls "several candidates survive": it
lists a master's pressings so the person holding the record can pick theirs by
catalogue number.

Unauthenticated requests are rate-limited to 25 a minute; setting `DISCOGS_TOKEN`
raises that, and the token is read from the environment and never written
anywhere. Release lookups have returned image URLs without one, but Discogs does
not promise that, so treat a missing image list as normal rather than as a fault.

This is a lookup, not a decision and not a measurement. What it prints becomes a
plan only by way of plan-metadata, which is where the choosing happens.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

API = "https://api.discogs.com"
USER_AGENT = "vinyl-process/0.1 +https://github.com/local/vinyl-process"
ID_PATTERN = re.compile(r"(?:^|/)(release|master)s?/(\d+)|^(\d+)$")


class LookupFailed(RuntimeError):
    """The API could not be reached, or answered with something unusable."""


def parse_reference(text: str) -> tuple[str, str]:
    """``(kind, id)`` from a bare id, a ``release/123`` path, or a full URL."""
    match = ID_PATTERN.search(text.strip())
    if match is None:
        raise LookupFailed(f"cannot read a Discogs id out of {text!r}")
    if match.group(3) is not None:
        return "release", match.group(3)
    return match.group(1), match.group(2)


def get(path: str) -> dict[str, Any]:
    request = urllib.request.Request(f"{API}{path}", headers={"User-Agent": USER_AGENT})
    token = os.environ.get("DISCOGS_TOKEN")
    if token:
        request.add_header("Authorization", f"Discogs token={token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        hint = {
            401: "the token in DISCOGS_TOKEN was rejected",
            404: "no such release or master",
            429: "rate limited; unauthenticated callers get 25 requests a minute",
        }.get(error.code, "")
        raise LookupFailed(f"{API}{path} returned {error.code}{': ' + hint if hint else ''}") from (
            error
        )
    except urllib.error.URLError as error:
        raise LookupFailed(f"could not reach {API}: {error.reason}") from error
    return payload


def artist_names(entries: list[dict[str, Any]]) -> str:
    """Discogs' ``anv`` is the name as this release prints it — keep both."""
    rendered = []
    for entry in entries:
        name = str(entry.get("name", ""))
        printed = str(entry.get("anv") or "")
        rendered.append(f"{printed} ({name})" if printed and printed != name else name)
    return ", ".join(rendered)


def show_release(release: dict[str, Any]) -> None:
    labels = release.get("labels") or []
    formats = release.get("formats") or []
    print(f"release      {release.get('id')}  {release.get('uri', '')}")
    print(f"title        {release.get('title')}")
    print(f"artists      {artist_names(release.get('artists') or [])}")
    for label in labels:
        print(f"label        {label.get('name')}  catno {label.get('catno')}")
    print(f"country      {release.get('country')}")
    print(f"year         {release.get('year')}   released {release.get('released_formatted')}")
    for entry in formats:
        descriptions = ", ".join(entry.get("descriptions") or [])
        text = entry.get("text") or ""
        print(
            f"format       {entry.get('name')} x{entry.get('qty')}  {descriptions}  {text}".rstrip()
        )
    print(f"genres       {', '.join(release.get('genres') or [])}")
    print(f"styles       {', '.join(release.get('styles') or [])}")
    print(f"master       {release.get('master_id')}")

    identifiers = release.get("identifiers") or []
    if identifiers:
        print("identifiers")
        for entry in identifiers:
            description = entry.get("description")
            suffix = f"  ({description})" if description else ""
            print(f"  {entry.get('type')}: {entry.get('value')}{suffix}")

    notes = (release.get("notes") or "").strip()
    if notes:
        print("notes")
        for line in notes.splitlines():
            print(f"  {line}")

    images = release.get("images") or []
    print(f"images       {len(images)}" + ("" if images else "  (none returned)"))
    for image in images:
        if image.get("type") == "primary":
            print(f"  primary: {image.get('uri')}")

    print("tracklist")
    for track in release.get("tracklist") or []:
        position = str(track.get("position") or "")
        duration = str(track.get("duration") or "")
        print(f"  {position:<4} {duration:>6}  {track.get('title')}")


def show_versions(master: dict[str, Any], versions: dict[str, Any]) -> None:
    print(f"master       {master.get('id')}  {master.get('title')}")
    print(f"artists      {artist_names(master.get('artists') or [])}")
    print("versions     (pick the one whose catalogue number matches the sleeve)")
    for version in versions.get("versions") or []:
        print(
            f"  release/{version.get('id'):<10} {version.get('catno')!s:<18}"
            f" {version.get('country')!s:<14} {version.get('released')!s:<6}"
            f" {version.get('format')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", help="a Discogs id, release/<id>, master/<id>, or URL")
    parser.add_argument(
        "--versions",
        action="store_true",
        help="treat the reference as a master and list its pressings",
    )
    parser.add_argument("--json", action="store_true", help="print the raw API response instead")
    arguments = parser.parse_args()

    try:
        kind, identifier = parse_reference(arguments.reference)
        if arguments.versions or kind == "master":
            master = get(f"/masters/{identifier}")
            versions = get(f"/masters/{identifier}/versions?per_page=100")
            if arguments.json:
                json.dump({"master": master, "versions": versions}, sys.stdout, ensure_ascii=False)
                print()
            else:
                show_versions(master, versions)
        else:
            release = get(f"/releases/{identifier}")
            if arguments.json:
                json.dump(release, sys.stdout, ensure_ascii=False, indent=2)
                print()
            else:
                show_release(release)
    except LookupFailed as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
