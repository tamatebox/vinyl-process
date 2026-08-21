---
name: plan-metadata
description: Resolve a recording to a specific Discogs/MusicBrainz release and produce the metadata section of processing_plan.json (album, artist, year, per-track titles and vinyl positions, release IDs, artwork). Use when planning tags for a vinyl rip.
---

# Plan Metadata

Identify the exact release and record its tags in the plan. The executor applies
tags after all audio processing and never touches the network — whatever you
conclude must be *in* the plan.

## Outside references

Where a rule below is a matter of tagging or cataloguing convention rather than of
this codebase, it is cited. Anything here without a citation is an in-house
judgement and should be treated as uncalibrated until someone finds a source for
it.

**What the fields mean.** The tags this section fills are ID3v2.4 frames (and their
Vorbis-comment equivalents), and
[the frame specification](https://id3.org/id3v2.4.0-frames) settles four
questions this skill used to answer from taste:

- `total_tracks` — TRCK "MAY be extended with a '/' character and a numeric string
  containing the total number of tracks/elements on the original recording.
  E.g. **'4/9'**". "The original recording" is the album, which is why a one-side
  plan must set `total_tracks` to the album's count rather than let it default to
  what this plan cuts.
- `disc_number` / `total_discs` — TPOS "is used **if** the source described in the
  'TALB' frame is divided into several mediums, e.g. a double CD". A single record
  is not divided into several mediums, so there is no part to describe and `null`
  is the correct value, not `1/1`. It also confirms the disc/side distinction: the
  medium is the record, and a side is not a medium.
- `genre` and `styles` — TCON: "since the category list would be impossible to
  maintain with accurate and up to date categories, **define your own**". So a
  release's own genre words are legitimate content for the frame; there is no
  controlled vocabulary to conform to.
- `comment` — COMM "is intended for any kind of full text information that does not
  fit in any other frame", and "**newline characters are allowed**". The multi-line
  rip chain in step 5 is within spec rather than a liberty.

**One release, not the album.** MusicBrainz's
[release group](https://musicbrainz.org/doc/Release_Group) documentation draws the
line this procedure's step 1 turns on: "a **release** is something you can buy,
such as a CD or a digital download, while a **release group** embraces the overall
concept of an album." The record in the room is a release. That is also the
mechanism behind `prefer_original_release_year`: the group carries the album's
first date, the release carries this pressing's, and they are different facts
rather than a better and a worse answer.

**Various Artists.** MusicBrainz reserves the special artist for exactly the case
in step 3: "[Used only for compilation-type releases or release groups containing
tracks by multiple different artists](https://musicbrainz.org/doc/Various_Artists)",
and "this artist shouldn't generally be used for recordings, tracks or works" — so
it belongs in `album_artist` and never in a track's own `artist`, which is what the
tagger's fallback chain would otherwise make of a blank.

**Which title, when the release prints two.** MusicBrainz's
[release style guide](https://musicbrainz.org/doc/Style/Release): "If several
versions of a title are provided, such as when release title differs between cover
and spine, or the track titles differ between the back cover and a booklet
tracklist, it's generally better to **follow the more detailed one**." A sleeve
that disagrees with itself is normal; this is the tie-break. The same page rejects
placeholder medium titles — "'CD n' or 'Disc n' should not be entered as a medium
title, since they are not actual titles" — which is the same instinct as leaving
`disc_number` `null` on a single.

**The vinyl position form.** `"A1"`, `"B3"` is what Discogs' own API returns in a
vinyl release's `tracklist[].position`, which is the evidence this skill actually
uses, via `scripts/discogs_release.py`. The database guideline that mandates the
form lives on `support.discogs.com`, which answers a plain fetch with **403** and
is therefore **unread** here — cite the API response, not a guideline nobody in
this repository has seen. ID3v2.4 has no frame for a vinyl position, so the tagger
writes it as a user-defined `TXXX` under the description `VINYL_POSITION`
([tagger.py](../../../src/vinyl_process/metadata/tagger.py)). Nothing standard
reads that, which is why striking the field costs a person less than striking
`catalog_number` — check the filename template first either way.

**Uncalibrated numbers in this skill**: the **±5 s** tolerance for matching a
release by per-track duration. In-house, and generous — a pressing can legitimately
differ from a printed duration by more than that, which is why step 1 treats a
mismatch as a fact to resolve rather than as a rejection.

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
   and/or `musicbrainz_release_id`.

   Apply `preferences.album_suffix` to `album` if it is set — `" [Vinyl Ripping]"`
   and the like, appended verbatim, so a rip stays distinguishable from a digital
   edition of the same album sitting next to it. It goes in the tag only: the
   filenames come from `tracks[].title`. Write the combined string into the plan
   rather than the rule, the same way the comment is composed.

   **A resolved field is not a wanted field.** A Discogs release will fill more of
   this section than most people want written into their library, and the tag set
   is theirs to choose: on one album **four** cleanly resolved fields — genre,
   styles, label and the vinyl position — were struck at the checkpoint, and one of
   them had two candidate values that would have cost a round trip to settle for a
   tag nobody wanted. So resolve everything,
   then **show the tag set and let them prune it**, rather than presenting a filled
   section as settled. A field left `null` is simply not written: no `TPUB`, no
   `TCON`, no `VINYL_POSITION`. Check first whether anything else reads the field —
   `catalog_number` and `position` are available to the filename template, so
   clearing them can change a filename as well as a tag. `genre` is a single string and `styles` a list,
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
     per-track `artist` on every entry — the credit is for the release, and "shouldn't
     generally be used for recordings, tracks or works" (*Outside references*). The
     tagger falls back track → `artist` → `album_artist`, so an album-level `artist`
     would quietly become the performer of any track whose own artist you could not
     fill, and `"Various Artists"` left in the track's own field would be the same
     mistake spelled differently.
4. `disc_number` and `total_discs`: the **disc**, not the side. TPOS describes a
   source "divided into several mediums" (*Outside references*), and the medium is
   the record — both sides of one are the same disc, and the side is already in
   `tracks[].position` — so a double album is discs 1 and 2 across four plans.
   Leave both `null` on a single record: with nothing divided there is no part to
   number, and `1/1` asserts a set that does not exist.
5. `comment`: compose it from the `[rip]` configuration section and write the
   finished string into the plan. That section holds the chain the record was
   played and digitised through — turntable, tonearm, headshell, cartridge,
   stylus, phono stage, ADC, software — because it is the same for every album
   until something is replaced. It has no method that renders itself, on purpose:
   what goes in a comment and in what order is a choice, and choices belong in the
   plan ([adr/0009](../../../docs/adr/0009-the-rip-chain-is-configuration-the-comment-is-a-plan-value.md)).

   Provenance only — which pressing, and what it came through:

   ```
   Vinyl rip. Discogs release 28396297 (UIJY-75237).
   Technics SL-1200MK5 / LP Gear Ultimate Headshell / Audio-Technica ATN-3600L
   / Linn Akurate DSM/2 / Behringer U-Control UCA222 — 48 kHz 16-bit
   ```

   Leave out what the chain does not record; an omitted phono stage is honest and
   a guessed one is not. Do **not** put the processing in here — the mode, the
   gain, whether declick ran. The manifest is where that lives, it is measured
   rather than asserted, and a comment repeating it goes stale the moment the plan
   is re-run with one value changed.

   Nothing checks the chain against the audio. If the ADC in the configuration is
   wrong it is wrong in every tag, silently, so read it back at the checkpoint
   instead of assuming it.
6. Artwork: set `artwork_path` to a local `.jpg`/`.jpeg`/`.png` file if the user has
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
  "disc_number": null,              // the disc, not the side; null on a single
  "total_discs": null,
  "comment": "Vinyl rip. Discogs release 1873013 (SHVL 804). …",
  "tracks": [ { "index": 1, "title": "Speak to Me", "artist": null, "position": "A1" } ],
  "decision": { "skill": "plan-metadata", "rationale": "…", "confidence": 0.9,
                "inputs": ["discogs:release/1873013"] }
}
```

Run `vinyl-process lint` before shipping. The findings that belong to this
section are `missing-title`, `no-album-title` and `orphan-metadata`. The last
means this section names tracks the `split` section does not cut — on a
two-sided album that is normal for `total_tracks`, and a defect for
`metadata.tracks`.

## Checkpoint

A wrong release makes every tag wrong, and it is cheap to check. Present:

- the release you resolved to: artist, album, label, catalogue number, country,
  year, and its Discogs/MusicBrainz id;
- **how** you matched it — catalogue number from the sleeve, track count, per-side
  durations within N seconds;
- the tracklist as it will be tagged, with the vinyl positions;
- the `comment` in full, and the `[rip]` fields it came from. It is the one tag
  no measurement can check, so the person who owns the equipment has to read it;
- anything you could not verify, marked as such.

Never present titles taken from memory as if they were looked up.

## Rules

- This section is the single source of truth for titles: the export filenames are
  rendered from it, so it must cover every `split` index even when
  `"enabled": false` (which means "do not write tags", not "forget the names").
- `year`: `preferences.prefer_original_release_year` decides, and it is `true` by
  default — so the original release year unless the user has asked for the year of
  the pressing they own. These are two different facts rather than a right and a
  wrong one (the release group's date against the release's, *Outside references*),
  so say which you wrote.
- Use the tracklist's original-language titles unless
  `preferences.title_style` is `transliterate`.
- Never fill titles from memory for an obscure release. Verify against a source,
  or ask.
- **Titles that were provisional have already been written to disk.** The review
  renders take their filenames from this section, so a tracklist used before the
  release was settled is sitting in the directory the person has been listening to.
  When the pressing resolves, diff the titles against what `review/` actually
  holds and say what moved: a track has been played and plotted under a title the
  sleeve does not carry. Re-render
  only if `review/` is still being used to decide something; if `album/` is next,
  name the stale files instead, because a plot or a manifest that refers to them
  by the old name is about to be replaced anyway.
- **A discography site is not the pressing.** It gives you the album, and the tags
  follow the record in the room. A non-authoritative tracklist has differed from
  the sleeve by **one character** — a different word, not a typo — with a duration
  6 s out, on a list that was otherwise **nine of ten right**. That ratio is what
  makes the failure quiet: nothing looks wrong until the release id arrives.
  Where you have had to work from one anyway, mark every title provisional in the
  message that shows them, and re-check all of them once the pressing is settled
  rather than only the ones you doubted.
- Write titles as the release prints them, punctuation included. Filename safety is
  the executor's job — `/` and `:` become `_` in the filename only — so
  pre-sanitising here would push that damage into the tags as well.
- Local metadata the user supplied overrides remote sources.
