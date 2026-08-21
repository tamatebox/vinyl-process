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
| Does a click rung transfer between two sides | 3 records: 2 disagreeing within an album, 1 agreeing across **4** sides | It does not in general ([adr/0010](adr/0010-the-click-statistic-is-local.md)); it can within one pressing |
| Is `onset_coincidence` "following the music" | 1 | No where detections are mostly in gaps — confounded by construction, now stated in `plan-declick` from the code rather than the count |
| Does `prefilter` buy headroom | **2/2 say no**; the second **lost** 0.31–0.43 dB with peaks rising on 8–9 of 10 tracks | It costs headroom rather than buying it, because the filter is forward-only. Close to a rule |
| Is the album's loudest sample the needle drop | **2/2**, costing 7 dB and 2.0 dB of gain | Never take the reference from `peaks.peak_db` — read the split render. Rule |
| Repair rate against the cited 1-in-200..2000 band | **2 records, 6 sides**, all 13–25× below the floor | Every transfer measured here lands far under the band. Lead, but no longer about reissues alone |
| Can a residual click be reached by any plan value | 1, six variants rendered | No — the span comes from the channel **mean**, so the per-channel leading edge lies outside it and no threshold, `detect_ms`, `confirm_k` or interpolator relocates it. Wants per-channel detection |
| Where does a side's last track end | 1 record, 4 sides | Neither level marker: `lead_out_start_sample` 5.0-9.3 s early, `silence`'s trailing `music_end_sample` up to 27 s late. `run_out` (new analyzer) within 0.6 s. **Lead only** — one record, and no outside citation for the technique |

## Rows

| Record | Capture | declick | normalize | export | Boundaries |
|---|---|---|---|---|---|
| **Emergency On Planet Earth** — Jamiroquai · 2026-08-21 · [25379](https://www.discogs.com/release/25379) · Sony Soho Square 474069 1, Europe 1993, 2×LP | 48 kHz/16-bit, **4 sides**, 10 tr | rung **75** all four sides; 1 in 34,929 / 25,575 / 49,421 / 25,372 | `album_peak` −1.0 dBFS/−1.0 dBTP; **+4.2176 / +4.6197 / +5.2570 / +5.1681**, ceiling capped all four | FLAC **16**/tpdf | every side opens band-limited; 1 start moved 1.2 s by `band_profile`; 3 side ends past `lead_out_start_sample` by 5.0–9.3 s; tr 9/10 contiguous (0.2 s apart) |
| **夜のためいき** — 渥美マリ · 2026-08-21 · [26795813](https://www.discogs.com/release/26795813) · Daiei TJJA-10057, 2023 RSD reissue of 1970 | 48 kHz/16-bit, 2 sides, 12 tr | rung **20** both sides; 1 in 15,265 / 13,172 | `album_peak` −1.0 dBFS/−1.0 dBTP; **+9.1711 / +9.5198**, ceiling capped both | FLAC **16**/tpdf | 4 of 12 starts moved by `band_profile`, 1.1–5.0 s; both side ends by `periodicity` |

Stages off unless a row says otherwise. `prefilter`, `decrackle`, `mono_merge`,
`speed` were off on every record so far.

### Tried and rejected

| Record | Tried | Rejected by |
|---|---|---|
| Emergency On Planet Earth | `declick` rung 50 | tr 4 inverted **in-cut**: gap 7.08/min BELOW programme 7.99/min, `onset_coincidence` **18.22**, `revolution_lock` 0.06 |
| Emergency On Planet Earth | `declick` rung 150 | side A `revolution_lock` 4.04 → **0.01**, side C 3.18 → 0.63 — the once-per-turn defect missed |
| Emergency On Planet Earth | `declick` `confirm_k` 3 and 5 | tr 4 onset barely moved (18.2 → 17.3 → 16.9) while tr 3 fell 87 → 95 → **17** spans; at k=5 the two largest repairs reverted to unrepaired |
| Emergency On Planet Earth | `declick` `detect_ms` 0.4 / 0.6 | 0.4: tr 3 87 → **38** spans, two largest reverted. 0.6: **repaired nothing at all** |
| Emergency On Planet Earth | `declick` `interpolator` hermite / linear | residual moved ±13 in the ratio, both directions — not a fix, because the residual is in untouched samples |
| Emergency On Planet Earth | `prefilter` 20 Hz, 30 Hz @24 dB/oct | album peak **worsened** −5.29 → −4.86 / −4.98 dBFS; track peaks ROSE on **8 of 10** at 20 Hz and **9 of 10** at 30 Hz, up to +1.28 dB; `rumble_db` fell only 0.6–1.7 dB and 40–160 Hz did not move (±0.02 dB) |
| Emergency On Planet Earth | `decrackle` | On its own input (`review/declick/`): **13** events in the 0–0.1 ms bin across 64 min, one above −30 dBFS |
| 夜のためいき | `declick` rung 10 | in-cut gap:programme fell to **1.9:1** (parity); in-cut `revolution_lock` 4.16 → **0.09**; no further album-peak drop |
| 夜のためいき | `prefilter` 20 Hz, 30 Hz @24 dB/oct | **6 of 12** track peaks *rose* (forward-only IIR); `rumble_db` fell only 3.1 / 3.4 dB, so the 0-40 Hz band is mostly 30-40 Hz musical bass |
| 夜のためいき | `decrackle` | On its own input (`review/declick/`): ladder top empty, and the 0-0.1 ms width bin empty **before and after**. "A bit remains" was the AR fill's seam |
| 夜のためいき | `export` 24-bit | Capture is 16-bit; raising a depth cannot retrofit one, and the added quantisation noise lands *below* what the capture already carries |

### Near misses — what a default or an obvious reading would have got wrong

| Record | Reading | Error |
|---|---|---|
| Emergency On Planet Earth | normalize reference from `peaks.peak_db` | **2.0 dB** — the loudest sample of all four captures is the needle drop or a lead-in tick at 1.6–4.6 s |
| Emergency On Planet Earth | last track end from `lead_out_start_sample` | **9.3 s** on C3 and **5.0 s** on D2 — both fired inside a fade, not at the run-out |
| Emergency On Planet Earth | six hand-written rules for the run-out, before `run_out` | Three patching `silence._music_end` and three comparing bands to a whole-file reference. All six failed differently; one moved an *inter-track* gap 4.5 s. The anchor was the missing part, not the band test |
| Emergency On Planet Earth | `run_out` parameters tuned on this record | Only `programme_peak_factor` is sensitive, and its plateau is **1.4-10.0** (identical answer on all four sides); the cliff is at 1.2. The other three moved nothing across 3x wide sweeps |
| Emergency On Planet Earth | last track end from `silence.regions[-1].music_end_sample` | Ran to the **end of the file** on 3 of 4 sides: that region merges the run-out with post-lift digital silence, so `_music_end`'s `min()` reference sits near −95 dB |
| Emergency On Planet Earth | tr 10 start from `music_start_sample` | **3.0 s** — the didgeridoo enters at 625.6 s while the marker fires at 628.6 s, and D1 settles at 625.4 s, so the two tracks are 0.2 s apart |
| Emergency On Planet Earth | tr 5 start from `music_start_sample` | **1.2 s** — a 3–8 kHz element enters before the marker's broadband threshold |
| Emergency On Planet Earth | width histogram read as ruling out wide damage | It cannot — it holds only *accepted* detections. Raising `max_width_ms` 2 → 8 ms was the test, and found **0** new events |
| Emergency On Planet Earth | `revolution_lock` 15.9 / 16.7 read as a once-per-turn tick | Spacings are **0.02–1.0 s**, not 1.8 s: a burst confined to ~17 revolutions gives a high Rayleigh value without a periodic defect |
| Emergency On Planet Earth | repair size measured as peak-before ÷ peak-after | Understated it: at 1:37.87 the peak moved **−2.4 dB** while the **difference signal reached −0.0 dBFS** — the waveform was replaced, not attenuated |
| Emergency On Planet Earth | C's three body gaps read as three track breaks | Only **two** are gaps; the third never reaches a gap floor (band floors −57/−67 dB against −86/−91) and is a quiet passage inside C3 |
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
