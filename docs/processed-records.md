# Processed records

One row per record, newest first, appended at checkpoint 7 by
[plan-album](../.claude/skills/plan-album/SKILL.md).

**What this is for.** The plan copy beside each manifest holds every parameter and
the manifest holds every outcome including the repair rate
([adr/0018](adr/0018-the-receipt-retains-the-plan-that-produced-it.md)). Neither
can hold *which rung was rejected and what rejected it* — that is a checkpoint
answer and exists only in the conversation where the checkpoint happened. This file
is that half, and nothing else.

**Rows, not prose, and the length is the point.** A datapoint fits a cell. If it
does not fit, it is not a datapoint — it is a rule or a decision, and those have
homes: a `plan-*` skill for a rule, `docs/adr/` for a decision. Reasoning does not
go here; the skill that owns the stage already carries it. Keep the argument out
and the observation in, so a column can be counted rather than re-litigated.

**Nothing is calibrated by being here.** These are third-rank measurements on real
transfers, accumulating. A figure moves into a skill only when the count justifies
it, and the skill then states the count. Quoting one row as practice is the failure
this file exists to prevent.

## What the rows have settled

Read the counts, not the figures. Behind one or two records a line is a lead.

| Question | n | Verdict |
|---|---|---|
| Which metadata fields are wanted | 2/2 struck genre, styles, label, position | Acted on — removed from `plan-metadata` ([adr/0020](adr/0020-four-metadata-fields-left-the-skill-not-the-contract.md)) |
| Does a click rung transfer between two sides | 2 records, disagreeing | It does not ([adr/0010](adr/0010-the-click-statistic-is-local.md)) |
| Is `onset_coincidence` "following the music" | 1 | No where detections are mostly in gaps — confounded by construction, now stated in `plan-declick` from the code rather than the count |
| Does `prefilter` buy headroom | 1 | No systematic gain; peaks moved both ways. Lead only |
| Is the album's loudest music sample a click | 1/1 | Check every time — cost 1.1 dB of gain here |
| Repair rate against the cited 1-in-200..2000 band | 1, at 7-8× below the floor | The citation's "unless in really good condition" may be the usual case for reissues. Lead only |

## Rows

| Record | Capture | declick | normalize | export | Boundaries |
|---|---|---|---|---|---|
| **夜のためいき** — 渥美マリ · 2026-08-21 · [26795813](https://www.discogs.com/release/26795813) · Daiei TJJA-10057, 2023 RSD reissue of 1970 | 48 kHz/16-bit, 2 sides, 12 tr | rung **20** both sides; 1 in 15,265 / 13,172 | `album_peak` −1.0 dBFS/−1.0 dBTP; **+9.1711 / +9.5198**, ceiling capped both | FLAC **16**/tpdf | 4 of 12 starts moved by `band_profile`, 1.1–5.0 s; both side ends by `periodicity` |

Stages off unless a row says otherwise. `prefilter`, `decrackle`, `mono_merge`,
`speed` were off on every record so far.

### Tried and rejected

| Record | Tried | Rejected by |
|---|---|---|
| 夜のためいき | `declick` rung 10 | in-cut gap:programme fell to **1.9:1** (parity); in-cut `revolution_lock` 4.16 → **0.09**; no further album-peak drop |
| 夜のためいき | `prefilter` 20 Hz, 30 Hz @24 dB/oct | **6 of 12** track peaks *rose* (forward-only IIR); `rumble_db` fell only 3.1 / 3.4 dB, so the 0-40 Hz band is mostly 30-40 Hz musical bass |
| 夜のためいき | `decrackle` | On its own input (`review/declick/`): ladder top empty, and the 0-0.1 ms width bin empty **before and after**. "A bit remains" was the AR fill's seam |
| 夜のためいき | `export` 24-bit | Capture is 16-bit; raising a depth cannot retrofit one, and the added quantisation noise lands *below* what the capture already carries |

### Near misses — what a default or an obvious reading would have got wrong

| Record | Reading | Error |
|---|---|---|
| 夜のためいき | normalize reference from `peaks.peak_db` | **≈7 dB** — that sample is the stylus drop, which the cuts discard |
| 夜のためいき | normalize reference from the *un-declicked* split render | **1.106 dB on side A, 0.000 on side B** — only A's loudest music sample was a click, so half the evidence looked clean |
| 夜のためいき | track start from `music_start_sample` | **1.1–5.0 s** late on 4 of 12; worst was 時計 / *El Reloj*, whose 1-8 kHz ticking intro repeats at 1.4-1.6 s, not the 1.8 s revolution |
| 夜のためいき | `disc_number` 1 / `total_discs` 1 on a single record | Asserts a set that does not exist |
| 夜のためいき | `preferences.export_bit_depth = 24` taken as an instruction | It is the default for a capture already at 24 |

## How to add a row

At checkpoint 7, once `verify` is green:

1. Prepend a row to **Rows** — key, capture, and only the stages that were not
   default. Link the release.
2. Add rows to **Tried and rejected** for each rung or setting you rendered and did
   not keep, with the figure that rejected it. This is the part nothing else keeps.
3. Add rows to **Near misses** for anything a default or a plausible reading would
   have got wrong, with the size of the error.
4. Check whether the record moved a count in **What the rows have settled**. A line
   that has crossed from lead to rule belongs in the stage skill that owns it, with
   the count stated — not left here.

Write nothing the plan or the manifest already states, and nothing that needs a
paragraph. A paragraph means it belongs in a skill or an ADR.
