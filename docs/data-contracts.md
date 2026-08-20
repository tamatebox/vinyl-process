# Data Contracts

Three JSON documents connect the layers. Their single source of truth is the
pydantic models in `src/vinyl_process/models/`; the JSON Schemas generated from
them are committed under `schemas/` (regenerate with
`vinyl-process schemas -o schemas/`). Real, validated examples live in
`examples/`.

All documents share:

- **`schema_version`** — `"MAJOR.MINOR"`. Consumers reject a foreign major.
- **`document_type`** — `analysis` / `processing_plan` / `manifest`, so a file can
  be identified without guessing.
- **`extra="forbid"`** — unknown fields are validation errors, so a typo in a
  hand-authored plan fails loudly instead of being silently ignored.
- **Integer sample positions.** Every position is a sample index into the source
  file, never seconds; durations in seconds appear alongside for human readability
  only. See [adr/0002-sample-positions-are-integers.md](adr/0002-sample-positions-are-integers.md).
- **Digests are SHA-256, lowercase hex, no prefix** — for files (`sha256`) and for
  canonical JSON (`params_digest`, `run_key`, `config_digest`).

## analysis.json — Analyzer → Planning Skills

Produced by `vinyl-process analyze`. Pure measurement; nothing in it is a
decision. It contains **no timestamps**, so analysing the same file twice gives
byte-identical output.

One section per analyzer, named after it. **Every section is optional**: a
partial document is valid, because `analyze --analyzers rms_profile,clicks` is a
supported workflow and because a failing analyzer degrades the document instead of
the run. Consumers must handle absent sections — read `analyzers[]` to see what
happened.

```jsonc
{
  "schema_version": "3.0",
  "document_type": "analysis",
  "generated_by": "vinyl-process 0.1.0",
  "source": { "path": "side-a.wav", "sha256": "…", "sample_rate": 44100,
              "channels": 2, "num_samples": 956970, "duration_seconds": 21.7 },
  "config_digest": "…",             // digest of the [analyzer.*] settings used
  "analyzers": [                    // one record per analyzer that ran
    { "name": "silence", "version": "1.0", "status": "ok",
      "message": null, "duration_ms": null }   // status: ok | failed | skipped
  ],

  "recording_info": { "meta": { "analyzer": "recording_info", "version": "1.0",
                                "params": {}, "confidence": 1.0 },
    "subtype": "PCM_24", "bit_depth": 24, "dc_offset": [0.0, 0.0],
    "channel_peak_db": [-3.9, -4.1], "channel_rms_db": [-19.2, -19.3],
    "channel_balance_db": 0.13, "channel_correlation": 0.999 },

  "rms_profile":   { "window_seconds": 0.2, "hop_seconds": 0.1,
                     "values_db": [-68.1, -67.9, …] },
  "surface_noise": { "noise_floor_db": -68.0, "stability_db": 0.4 },
  "silence":       { "threshold_db": -60.0,
                     "regions": [ { "start_sample": 0,
                                    "music_end_sample": 0,   // where the music
                                    // before this region really stopped, which on
                                    // a fading track is well past start_sample
                                    "music_start_sample": 88200,  // and where the music after it
                                    // starts, which on a fading-in track is before end_sample
                                    "end_sample": 88200,
                                    "mean_rms_db": -68.0, "duration_seconds": 2.0,
                                    "confidence": 0.93 } ] },
  "boundaries":    { "candidates": [ { "sample": 489510, "method": "silence",
                                       "confidence": 0.91 } ],
                     "lead_in_end_sample": 88200,
                     "lead_out_start_sample": 846720 },
  "clicks":        { "count": 5, "rate_per_minute": 13.8,
                     "silence_rate_per_minute": 0.0,     // rate in the gaps…
                     "programme_rate_per_minute": 28.0,  // …versus under the music
                     // the same detector across a ladder of thresholds. The
                     // headline count above is only the rung named by
                     // meta.params.threshold_ratio; the plan picks its own.
                     "threshold_sweep": [ { "threshold": 20.0, "count": 41,
                                            "rate_per_minute": 113.2,
                                            "silence_rate_per_minute": 0.0,
                                            "programme_rate_per_minute": 230.1,
                                            "onset_coincidence": 5.4,  // 1 = blind
                                            // to note attacks, large = following them
                                            "revolution_r": 0.11,
                                            "revolution_lock": 0.5 },
                                          { "threshold": 50.0, "count": 5,   // ← promoted
                                            "rate_per_minute": 13.8,
                                            "silence_rate_per_minute": 0.0,
                                            "programme_rate_per_minute": 28.0,
                                            "onset_coincidence": 0.6,
                                            "revolution_r": 0.61,
                                            "revolution_lock": 2.6 },
                                          { "threshold": 400.0, "count": 0,
                                            "rate_per_minute": 0.0,
                                            "silence_rate_per_minute": 0.0,
                                            "programme_rate_per_minute": 0.0,
                                            // null wherever there is nothing to fold
                                            "onset_coincidence": null,
                                            "revolution_r": null,
                                            "revolution_lock": null } ],
                     "amplitude_histogram": { "unit": "dBFS", "bin_edges": [...],
                                              "counts": [...] },
                     "width_histogram": { "unit": "ms", "bin_edges": [...],
                                          "counts": [...] },
                     "density_per_minute": [5.0],
                     "positions_sample": [...], "positions_truncated": false },
  "peaks":         { "peak_db": -3.96, "peak_sample": 123456,
                     "true_peak_db": -3.71,   // where the waveform goes *between*
                                              // samples; never below peak_db
                     "rms_db": -19.2,
                     "gated_rms_db": -9.44,   // programme only, gaps gated out
                     "crest_factor_db": 15.3 },
  "dynamic_range": { "dr_estimate_db": 12.8, "loud_rms_db": -16.7,
                     "percentiles": { "p05_db": -68.0, "p50_db": -21.0,
                                      "p95_db": -16.7 } },
  "clipping":      { "clipped_sample_count": 0, "clipped_region_count": 0,
                     "longest_run_samples": 0, "ratio": 0.0 },
  "spectral":      { "centroid_mean_hz": 2412.0, "centroid_std_hz": 810.0,
                     "rolloff_mean_hz": 9120.0, "rumble_db": -48.2,
                     "hiss_db": -55.0,
                     "bands": [ { "low_hz": 0.0, "high_hz": 40.0,
                                  "energy_db": -48.2 } ] },
  "transients":    { "hop_seconds": 0.01, "density_per_second": [0.0, 1.0, …],
                     "mean_per_second": 0.1, "peak_per_second": 2.0 },
  "periodicity":   { "onset_hop_seconds": 0.005, "window_seconds": 12.0,
                     "window_hop_seconds": 4.0,
                     "min_period_seconds": 0.25, "max_period_seconds": 4.0,
                     "programme_period_seconds": 0.515,  // the beat
                     "programme_peak_prominence": 0.389, // what music looks like
                     "windows": [ { "start_sample": 576000, "end_sample": 1152000,
                                    "peaks": [ { "period_seconds": 1.335, "r": 0.45 } ],
                                    "baseline_r": 0.17,
                                    // one entry per configured speed
                                    "revolution": [ { "rpm": 33.33,
                                                      "period_seconds": 1.8, "r": 0.18 },
                                                    { "rpm": 45.0,
                                                      "period_seconds": 1.3333,
                                                      "r": 0.45 } ] } ] },

  "warnings": ["clipping: 2 region(s), 31 sample(s) at full scale"]
}
```

Every section carries `meta` (omitted above except once for brevity):

```jsonc
"meta": { "analyzer": "clicks", "version": "2.0",
          "params": { "threshold_ratio": 50.0, "max_width_ms": 2.0, … },
          "confidence": 0.75 }
```

`clicks.silence_rate_per_minute` and `clicks.programme_rate_per_minute` are the
pair that decides whether declicking helps: a worn pressing crackles in the
inter-track gaps too, while a detector over-triggering on the material only fires
under the programme. Both are `null` when the recording has no gap long enough to
measure (`silence_min_seconds`, 2 s by default).

They are reported per rung of `clicks.threshold_sweep`, which is the section a
declick decision is actually made from: no threshold suits two pressings, so the
analyzer reports the whole ladder as the fact and `plan-declick` picks the rung.
Each rung also carries `onset_coincidence` (how much more often than chance its
detections sit on a rising edge — large means the detector is following the music)
and `revolution_lock` (Rayleigh's statistic for the same detections folded onto
the platter's period, whose null is exponential with mean 1 whatever the count, so
rungs are comparable; a high value is a defect struck once per turn, which argues
*for* repair). `count`, `rate_per_minute`, the two histograms, `density_per_minute`
and `positions_sample` all describe one rung only — the one named by
`meta.params.threshold_ratio` — so a plan that chooses a different rung must
re-analyze at it rather than read those fields.

`periodicity` answers what level and spectrum cannot: whether a quiet stretch is
faint music or the record's own surface. A groove defect repeats once per
revolution and never on the beat, so a window whose `revolution` correlation
rivals its own top peak is the pressing rather than the performance. Compare
against `programme_peak_prominence`, which is what a window of this record's
music measures. Do not read `baseline_r` as a mark of surface noise on its own —
on a tested side the crackling lead-in sat at 0.17 while the run-out groove, a
far cleaner tick, sat at -0.03.

`peaks.true_peak_db` is a 4x-oversampled estimate of the reconstructed
waveform's ceiling (ITU-R BS.1770-4's method, a polyphase FIR rather than the
standard's exact filter). It matters because the executor resamples *after*
normalizing and because a lossy encoder reconstructs too: material at
-0.1 dBFS can come back above 0 dBTP. It is the quantity
`normalize.peak_ceiling_db` is held against.

`peaks.gated_rms_db` measures the programme and not the silence, on BS.1770-4's
400 ms / 75 %-overlap blocks with its absolute (-70) and relative (-10) gates.
`rms_db` averages the inter-track gaps, the fades and the lead-in in too, so the
two differ by however much silence the side carries — which is exactly why a
plain RMS target normalizes a gappy side too loud. Channels are averaged rather
than summed as BS.1770 would, so the figure is directly comparable with `rms_db`,
and it is a level in dBFS, never loudness in LUFS.

`meta.params` records the parameters actually used, so a measurement stays
explainable years later. `meta.confidence` is `1.0` for direct measurements
(peaks, channel levels), lower for estimators (0.75 for click statistics, 0.7 for
the dynamic-range approximation) and computed per case for silence and clipping.
`warnings` states facts, never advice — advice would be a decision.

## processing_plan.json — Planning Skills → DSP Executor

Authored by the `plan-*` skills. The complete record of every decision; the
executor adds nothing subjective. Each section carries an optional `decision`
block: which skill decided, why, how confident it was, and what it consulted.

```jsonc
{
  "schema_version": "3.0",
  "document_type": "processing_plan",
  "created_by": "plan-album",
  "source": { …same shape as analysis.source; sha256 is verified before running… },
  "analysis": { "path": "analysis.json", "sha256": "…" },

  "split": {
    "enabled": true,
    "engine": "native",
    "decision": { "skill": "plan-split", "rationale": "…", "confidence": 0.92,
                  "inputs": ["analysis.json#boundaries", "discogs:release/1873013"] },
    "tracks": [ { "index": 1, "start_sample": 88200, "end_sample": 445410,
                  "fade_in_ms": 20.0, "fade_out_ms": 30.0 } ]
    // index is the position on the *album*: side B continues where side A
    // stopped (6, 7, …), so both sides export into one directory. Indices must
    // be contiguous and ascending within a plan; gaps between tracks are legal
    // and normal — the dead middle of a vinyl gap belongs to neither track.
  },

  "declick": {
    "enabled": true, "engine": "native",
    "algorithm": "block_ratio",       // engine-defined id ('adeclick' on ffmpeg)
    "threshold": 50.0,                // engine-defined scale and deliberately
                                      // without a default: for block_ratio a
                                      // ratio of energies, read off
                                      // clicks.threshold_sweep for *this* pressing
    "max_click_width_ms": 2.0,        // native: also the rejection rule for wider
                                      // events; ffmpeg maps it to an analysis window
    "strength": 1.0,                  // 0..1 blend of the repair; ffmpeg refuses < 1.0
    "preset": null,                   // reserved; no engine interprets it yet
    "params": {}                      // engine-specific extras, e.g. interpolator
  },

  "normalize": {
    "enabled": true, "engine": "native",
    "mode": "album_peak",             // album_peak | album_gated_rms | album_rms |
                                      // track_peak | none
    "target_db": -1.0,
    "peak_ceiling_db": -1.0           // dBTP; null leaves the gain uncapped
    // The gain arithmetic is deterministic and runs post-declick in the executor;
    // the strategy, the target and the ceiling are the decision, recorded here.
    // A level target says nothing about where the peaks land, so an RMS mode
    // without a ceiling can drive the export into a clip — see adr/0007.
  },

  "metadata": {
    "enabled": true,                  // false = do not write tags (names still used)
    "total_tracks": 10,               // album-wide; null = as many as this plan cuts
    "album": "The Dark Side of the Moon", "album_artist": "Pink Floyd",
    "artist": "Pink Floyd", "year": 1973, "genre": "Rock",
    "styles": ["Prog Rock"], "label": "Harvest", "catalog_number": "SHVL 804",
    "discogs_release_id": "1873013", "musicbrainz_release_id": null,
    "artwork_path": null,
    "tracks": [ { "index": 1, "title": "Speak to Me", "artist": null,
                  "position": "A1" } ]
  },

  "export": {
    "format": "flac",                 // flac | wav | aiff
    "bit_depth": 24,                  // 16 | 24
    "sample_rate": null,              // null keeps the source rate
    "dither": "none",                 // none | tpdf
    "dither_seed": 0,                 // seeded, so dithered exports reproduce
    "track_filename_template": "{index:02d} - {title}",
    "write_tags": true
  },

  "notes": "why these boundaries and thresholds were chosen (audit trail)"
}
```

Contract rules a schema cannot express are checked by `vinyl-process lint`:
the named engines exist, are available and have the capability; cuts fit inside
the recording; fades fit inside their track; the filename template renders and
does not collide; the source digest still matches; the analysis describes the same
recording. See [cli.md](cli.md#lint).

Titles appear **only** in `metadata.tracks` — export filenames are rendered from
them, so the plan never carries the same string twice
([adr/0004-titles-live-in-metadata-only.md](adr/0004-titles-live-in-metadata-only.md)).

## manifest.json — DSP Executor → archive

Written next to the exported album. This is the receipt.

```jsonc
{
  "schema_version": "3.0",
  "document_type": "manifest",
  "generated_by": "vinyl-process 0.1.0",
  "run_key": "…",                    // digest over (source digest, plan digest)
  "source": { …SourceInfo of the audio actually read… },
  "plan": { "path": "processing_plan.json", "sha256": "…" },
  "stages": [
    { "stage": "split", "status": "applied", "engine": "native",
      "engine_version": "native 0.1.0 (numpy 2.4.6)",
      "params_digest": "…",          // digest of the plan section that ran
      "detail": "" },
    { "stage": "normalize", "status": "applied", "engine": "native",
      "detail": "mode=album_peak gain_db=+2.9618" }
  ],
  "applied_gain_db": 2.9618,          // null for track_peak (one gain per track)
  "applied_track_gains_db": null,     // the per-track gains, when track_peak ran
  "applied_true_peak_db": -0.9944,    // of the audio as written; above 0 = clipped
  "outputs": [
    { "track_index": 1, "path": "album/01 - Speak to Me.flac", "sha256": "…",
      "bytes": 475509, "num_samples": 357210, "sample_rate": 44100,
      "duration_seconds": 8.1, "source_start_sample": 88200,
      "source_end_sample": 445410, "tagged": true }
  ],
  "environment": { "python": "3.11.11", "numpy": "…", "libsndfile": "…", … },
  "started_at": "2026-08-20T01:44:00+00:00",
  "completed_at": "2026-08-20T01:44:03+00:00",
  "warnings": []
}
```

`started_at` / `completed_at` / `environment` are informational and are the only
fields allowed to differ between two runs of the same plan. Everything else —
`run_key`, `applied_gain_db`, every output digest — must match, and
`vinyl-process verify` proves it.

`applied_true_peak_db` is measured on the audio as exported, after gain and after
any resampling, so it is where the album really ended up rather than where the
plan aimed. `warnings` carries the two things a level decision can get wrong: a
gain the ceiling had to cap (the target level was *not* reached) and a track whose
samples had to be clamped on write.

## Metadata sources

Skills may consult Discogs, MusicBrainz and local files. Whatever they conclude is
copied *into the plan*: the executor performs no network access, ever. That is why
`metadata` is a plain data section rather than a set of lookup instructions.
