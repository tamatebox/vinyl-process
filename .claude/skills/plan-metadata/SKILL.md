---
name: plan-metadata
description: Resolve a recording to a specific Discogs/MusicBrainz release and produce the metadata section of processing_plan.json (album, artist, year, per-track titles and vinyl positions, release IDs, artwork). Use when planning tags for a vinyl rip.
---

# Plan Metadata

Identify the exact release and record its tags in the plan. The executor applies
tags after all audio processing and never touches the network — whatever you
conclude must be *in* the plan.

## Inputs

- User-provided identity: artist/album, or a Discogs/MusicBrainz release ID or
  URL. Prefer an explicit ID.
- The `split` section: track count and per-track durations, which disambiguate
  pressings.
- `analysis.json#source` (duration) and `analysis.json#recording_info` (channel
  balance, correlation) when you need to tell a mono pressing from a stereo one.
- Local metadata files next to the recording, if the user provided any.

## Procedure

1. Resolve to **one specific release**, not a master: match track count, track
   durations (±5 s), and country/label/catalogue number when the user knows the
   pressing. If several candidates survive, ask the user.
2. Extract album-level tags: `album`, `album_artist`, `artist`, `year`, `genre`,
   `styles`, `label`, `catalog_number`, and the resolved `discogs_release_id`
   and/or `musicbrainz_release_id`. Set `total_tracks` to the album's count
   whenever this plan covers only one side, or side B will tag `1/5`.
3. Per track: `index` (matching the `split` indices exactly), `title`, optional
   `artist` for compilations and split releases, and `position` as printed on the
   label (`"A1"`, `"B3"`).
4. Artwork: set `artwork_path` to a local `.jpg`/`.jpeg`/`.png` file if the user
   has one. Never invent a path.

## Output

```jsonc
"metadata": {
  "enabled": true,
  "album": "The Dark Side of the Moon",
  "album_artist": "Pink Floyd",
  "artist": "Pink Floyd",
  "year": 1973,
  "genre": "Rock",
  "styles": ["Prog Rock"],
  "label": "Harvest",
  "catalog_number": "SHVL 804",
  "discogs_release_id": "1873013",
  "musicbrainz_release_id": null,
  "artwork_path": null,
  "total_tracks": 10,               // album-wide, when this plan is one side
  "tracks": [ { "index": 1, "title": "Speak to Me", "artist": null, "position": "A1" } ],
  "decision": { "skill": "plan-metadata", "rationale": "…", "confidence": 0.9,
                "inputs": ["discogs:release/1873013"] }
}
```

## Rules

- This section is the single source of truth for titles: the export filenames are
  rendered from it, so it must cover every `split` index even when
  `"enabled": false` (which means "do not write tags", not "forget the names").
- `year` is the pressing the user owns unless they prefer the original release
  year — `preferences.prefer_original_release_year` says which.
- Use the tracklist's original-language titles unless
  `preferences.title_style` is `transliterate`.
- Never fill titles from memory for an obscure release. Verify against a source,
  or ask.
- Local metadata the user supplied overrides remote sources.
