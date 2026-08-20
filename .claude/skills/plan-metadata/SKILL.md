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
  URL. Prefer an explicit ID, and ask for one at **checkpoint 1** rather than here:
  the tracklist is needed from the split checkpoint onward, and the titles go
  straight into the review filenames the person is about to listen to.

  Fetch it with the script — do not try to read the page:

  ```sh
  python scripts/discogs_release.py https://www.discogs.com/release/28396297
  python scripts/discogs_release.py 714555 --versions   # no id yet: list the pressings
  ```

  `www.discogs.com` answers a plain fetch with **403**; `api.discogs.com` answers
  the same release unauthenticated, but only if the request carries a User-Agent.
  The script does both and prints exactly what this checkpoint has to show. Its
  `--versions` mode is the tool for "several candidates survive" below: it lists a
  master's pressings with their catalogue numbers, which the person can match
  against the sleeve in seconds.
- The `split` section: track count and per-track durations, which disambiguate
  pressings.
- `analysis.json#source` (duration) and `analysis.json#recording_info` (channel
  balance, correlation) when you need to tell a mono pressing from a stereo one.
- Local metadata files next to the recording, if the user provided any.

## Procedure

1. Resolve to **one specific release**, not a master: match track count, track
   durations (±5 s), and country/label/catalogue number when the user knows the
   pressing. Then:
   - **several candidates survive** — ask the user; pressings differ and the tags
     follow the pressing.
   - **none survives** — say so and ask. Do not tag from the master or from a
     neighbouring pressing as though it were resolved.
   - **the tracklist and `split` disagree on how many tracks there are** — that is a
     fact about one of them, not something to paper over. A bonus or hidden track,
     an index treated as one track by the label and two by the ear, and a mis-cut
     side all look like this. Say which one you believe and why, and get it
     confirmed before writing titles: `index` has to match the `split` indices
     exactly, so a wrong answer here mislabels every track after it.
2. Extract album-level tags: `album`, `album_artist`, `artist`, `year`, `genre`,
   `styles`, `label`, `catalog_number`, and the resolved `discogs_release_id`
   and/or `musicbrainz_release_id`. `genre` is a single string and `styles` a list,
   so where the release names several genres, take the primary one and put the rest
   in `styles`. Set `total_tracks` to the album's count whenever this plan covers
   only one side: without it the executor falls back on the number of tracks *this*
   plan cuts, so side B tags `6/5` rather than `6/10`.
3. Per track: `index` (matching the `split` indices exactly), `title`, optional
   `artist` for compilations and split releases, and `position` as printed on the
   label (`"A1"`, `"B3"`).
   - **An untitled track**: `title` is a required field, so an entry cannot carry a
     `position` without one. Leave the whole entry out and the filename falls back
     to `Track NN`, with `lint` reporting `missing-title` as a warning — the honest
     outcome, at the cost of that track's vinyl position. Invent a title only if the
     label prints one.
   - **A compilation** wants `album_artist: "Various Artists"`, `artist: null`, and a
     per-track `artist` on every entry. The tagger falls back track → `artist` →
     `album_artist`, so an album-level `artist` would quietly become the performer
     of any track whose own artist you could not fill.
4. Artwork: set `artwork_path` to a local `.jpg`/`.jpeg`/`.png` file if the user has
   one, as an **absolute path** — it is resolved at execution time against whatever
   the working directory happens to be. Confirm the file exists and has one of those
   three extensions *before* writing the plan: `lint` does not check artwork at all,
   so a wrong path first surfaces as an error in the tagging step, after every track
   has been cut, repaired, normalized and encoded. Never invent a path.

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

## Checkpoint

A wrong release makes every tag wrong, and it is cheap to check. Present:

- the release you resolved to: artist, album, label, catalogue number, country,
  year, and its Discogs/MusicBrainz id;
- **how** you matched it — catalogue number from the sleeve, track count, per-side
  durations within N seconds;
- the tracklist as it will be tagged, with the vinyl positions;
- anything you could not verify, marked as such.

Never present titles taken from memory as if they were looked up.

## Rules

- This section is the single source of truth for titles: the export filenames are
  rendered from it, so it must cover every `split` index even when
  `"enabled": false` (which means "do not write tags", not "forget the names").
- `year`: `preferences.prefer_original_release_year` decides, and it is `true` by
  default — so the original release year unless the user has asked for the year of
  the pressing they own.
- Use the tracklist's original-language titles unless
  `preferences.title_style` is `transliterate`.
- Never fill titles from memory for an obscure release. Verify against a source,
  or ask.
- **A discography site is not the pressing.** It gives you the album, and the tags
  follow the record in the room. On the release this rule was written from, a
  Wikipedia tracklist had 墮落 where the sleeve prints 墜落 — one character, a
  different word — and a duration 6 s out. Nine of ten titles were right, which is
  what makes this failure quiet: nothing looks wrong until the release id arrives.
  Where you have had to work from one anyway, mark every title provisional in the
  message that shows them, and re-check all of them once the pressing is settled
  rather than only the ones you doubted.
- Write titles as the release prints them, punctuation included. Filename safety is
  the executor's job — `/` and `:` become `_` in the filename only — so
  pre-sanitising here would push that damage into the tags as well.
- Local metadata the user supplied overrides remote sources.
