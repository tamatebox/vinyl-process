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
| Does a click rung transfer between two sides | **4 records**: 2 disagreeing within an album, 2 agreeing (across **4** sides, and across 2) | It does not in general ([adr/0010](adr/0010-the-click-statistic-is-local.md)); it can within one pressing |
| Is `onset_coincidence` "following the music" | 1 | No where detections are mostly in gaps — confounded by construction, now stated in `plan-declick` from the code rather than the count |
| Does `prefilter` buy headroom | **2/2 say no**; the second **lost** 0.31–0.43 dB with peaks rising on 8–9 of 10 tracks | It costs headroom rather than buying it, because the filter is forward-only. Close to a rule |
| Is the album's loudest sample the needle drop | **3/3**, costing 7 dB, 2.0 dB and 3.7 dB of gain | Never take the reference from `peaks.peak_db` — read the split render. Rule |
| Repair rate against the cited 1-in-200..2000 band | **3 records, 8 sides**, all **13–200×** below the floor | Every transfer measured here lands far under the band, and a well-preserved 1971 pressing landed 40× and 200× under it. Lead, but no longer about reissues alone |
| Can a residual click be reached by any plan value | 1, six variants rendered | No — the span comes from the channel **mean**, so the per-channel leading edge lies outside it and no threshold, `detect_ms`, `confirm_k` or interpolator relocates it. Wants per-channel detection |
| Where does a side's last track end | **2 records, 6 sides** | Neither level marker: `lead_out_start_sample` 5.0-9.3 s early, `silence`'s trailing `music_end_sample` up to 27 s late. `run_out` within 0.6 s, and it placed both ends on the second record too. **Lead** — two records, and still no outside citation for the technique |
| Can a discography site's tracklist be trusted for a pressing | 1 record, **two irreconcilable Discogs partitions** of one album, both LP entries "Needs Vote" | No — and the ear settled it: the owner's four cuts matched one list's printed durations to within **1.5 s**, which is also the only evidence that list came from the object |
| Is the level touched at all | **3/3 normalized**, once only after a flat run was withdrawn | Always, unless the headroom is nil: `album/` is a listening master and the archival citations bear on the raw capture instead ([adr/0023](adr/0023-what-this-produces-is-a-listening-master.md)). Acted on — now stated in `CLAUDE.md` and `plan-normalize` |

## Rows

| Record | Capture | declick | normalize | export | Boundaries |
|---|---|---|---|---|---|
| **Brian Jones Presents The Pipes Of Pan At Joujouka** — Master Musicians Of Joujouka · 2026-08-22 · [16832352](https://www.discogs.com/release/16832352) · Rolling Stones Records P-8176S, Japan 1971 | 48 kHz/16-bit, 2 sides, 6 tr | rung **100** both sides; 1 in **407,094** / **79,523** | `album_peak`, **one album-wide gain +2.9900 dB** back-solved into two per-side targets (−1.0206 / −4.1747), ceiling −1.0 dBTP, nothing capped | FLAC **16**/**tpdf** | 1971 LP is two untitled unbroken sides; all 6 tracks **contiguous, 0 ms fades**, so concatenation reproduces the source; side A's 3 interior cuts placed by the owner **by ear**; both side ends by `run_out` |
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
| Joujouka P-8176S | `declick` rung 75 (side B) | `onset_coincidence` **2.68** with `revolution_lock` 0.57 to explain it; rung 100 had **1.9** with **3.39** |
| Joujouka P-8176S | `declick` rungs 10–35 (side B) | programme rate at or above the gap rate — **375 vs 308**/min at rung 10, still 1.33:1 at rung 35 |
| Joujouka P-8176S | `normalize` per-side `album_peak` −1.0 | +6.16 dB side A against +3.01 dB side B: a **3.15 dB step** on a continuous work, and the needledrop position is that per-file normalising is wrong |
| Joujouka P-8176S | `normalize` equalising the two sides (`album_gated_rms`, one shared target) | **No source found supports it** — both the archival and needledrop camps preserve the relationship. Peak says B is +3.15 dB, loudness says B is −1.95 LU: the sign flips with the quantity |
| Joujouka P-8176S | 1995 Point CD tracklist | Its partition agrees with this pressing only on tracks **4, 5, 6**; 3 of 6 would have carried another piece's name |
| Joujouka P-8176S | `export` 24-bit | Capture is 16-bit — 2nd record to reject this for the same reason |
| Joujouka P-8176S | `normalize` **off** (shipped, then withdrawn) | An archival flat-master rule (IASA, Grammy Museum) applied to the **listening** deliverable — the preservation master is the raw capture, which nothing here writes. Cost **2.99 dB**, and the owner heard it ([adr/0023](adr/0023-what-this-produces-is-a-listening-master.md)) |
| Joujouka P-8176S | `album_peak` targets set from **+3.0106 dB** (−1.0 dBFS on side B) | `peak_ceiling_db` −1.0 dBTP **does** bind at a 0.0116 dB true-peak margin: side B capped to +2.9990 dB with a warning, leaving the sides 0.0116 dB apart and defeating the shared gain. Retargeted from +2.99 dB |

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
| Joujouka P-8176S | normalize reference from `peaks.peak_db` | **3.70 dB** on side A — that sample is the stylus drop at 0:10.404, outside the cuts |
| Joujouka P-8176S | either Discogs partition measured from `lead_in_end_sample` | **14 s** out, and it matched neither list. The agreement appears only from the true music start at 0:15.8, found by a **35 dB** step in 1–3 kHz and 3–8 kHz |
| Joujouka P-8176S | `silence`'s 18.5 s "gap" at the B1/B2 division | Only **2.2 s** of it is quiet: 400–1000 Hz then sits **50 dB** above its own floor for 6 min 20 s of unaccompanied solo pipe. A cut placed later would have cut into it |
| Joujouka P-8176S | `silence_rate_per_minute` read as an unmasked-groove diagnostic | **83 % (A) and 95 % (B)** of pooled silence time falls *inside* the cuts — the material is sparse, so most "silence" is quiet music |
| Joujouka P-8176S | the side difference read from peaks | Matching peaks would have widened the audible gap from **1.95 LU to 5.10 LU** |
| Joujouka P-8176S | `channel_correlation` 0.47 / 0.57 and side B's **+4.10 dB** balance read as a transfer fault | Both are the production: Brian Jones's own stereo phasing and speaker-to-speaker panning, added in London. Side A of the same session reads −0.24 dB |
| Joujouka P-8176S | a Discogs LP tracklist marked "Needs Vote" | **Two irreconcilable partitions** of one album, and the US 1971 LP entry carries the 1995 CD's list verbatim |
| Joujouka P-8176S | "no subjective signal alterations" read as applying to `album/` | **2.99 dB**. The citation is about the preservation master, and that is the raw capture — satisfied before any plan exists |
| Joujouka P-8176S | `peak_ceiling_db` −1.0 dBTP predicted not to bind because true peak − peak is only 0.012 dB | It bound by **exactly** that 0.0116 dB. A ceiling equal to the target always binds on a peak mode; the margin is the gap, however small |

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