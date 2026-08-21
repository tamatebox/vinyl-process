---
name: plan-mono-merge
description: Decide whether a stereo capture of a mono record should be folded onto one signal, and by which strategy. Produces the mono_merge section of processing_plan.json. Use when planning a mono LP or a 78, or when a record's two channels are two observations of one groove.
---

# Plan Mono Merge

A mono record's two groove walls carry **the same signal**, so a stereo capture of
one holds two observations of it. This stage folds them onto one. It is the only
place in the pipeline that exploits that redundancy.

Disabled by default, and it must stay off for every stereo record: folding a
stereo pressing to mono destroys its image, and **nothing downstream will notice**.
That is the one catastrophic failure available here, so the first question is not
"how" but "is this actually a mono record".

## Outside references

Where a claim below is a matter of LP-transfer practice rather than of this
codebase, it is cited. Anything here without a citation is an in-house judgement
and should be treated as uncalibrated until someone finds a source for it.

**Why there is redundancy at all.** The
[ClickRepair 3.9 manual](https://archive.org/stream/manualzilla-id-5804727/5804727_djvu.txt)
(Brian Davies), chapter *Processing Mono Records*: mono settled on "'lateral'
recording, meaning that the signal is recorded as purely horizontal motion", so
"if the stylus is moving in response to tracking a mono recording, the response
measured as movement of the two walls will have the same magnitude… the electrical
output which goes to the audio system will be the same in each channel". The
damage, though, is not shared: "**one wall of the groove is often less damaged than
the other**".

**Capture a mono record in stereo, and expect this stage to be the reason.** "For
mono records, I strongly recommend that the capture is done in stereo, to a stereo
file… This method gives much better results for mono recordings, both vinyl and
shellac", because "**better noise reduction may be achieved** by capturing and
processing mono material in stereo". If a capture arrived already mixed to one
channel, that decision was taken upstream and this stage has nothing to work with —
say so rather than pretending otherwise.

**The redundancy is real but not perfect.** The same chapter: "phono cartridges are
mechanical devices subject to mechanical limitations, and this ensures that **a
scratch in one wall will have consequences in both channels**." So the improvement
is bounded, and a scratch is reduced rather than removed.

That sentence is also the reason **not to quote a figure for the improvement**.
Averaging two observations gains 3 dB only where their noise is independent, and
the citation says a real pair's is not — a scratch reaches both walls. So the
arithmetic gives a ceiling, never a prediction, and how far under it a given
pressing lands depends on that pressing. Present the improvement as something to
listen for.

**Three strategies, and the reference names all three.** "Audition the left and
right tracks separately, and choose the one which is better"; splice sections of
both together; or "merge the two channels to produce a single mono track, which is
written to both channels of the stereo format file". This stage implements the
first and the third. Splicing is not offered: it is per-passage surgery, "can be
very time-consuming", and there is nowhere in this contract to express it.

**Levels have to be matched, and the reference says why.** "It is nearly always the
case that the two channels of data, even if they are highly correlated (as they
should be), are at **different recording levels**… Each of the processes involved in
capturing the record to a sound file can contribute to this lack of equalization."
Its worked example measured **1.4 dB** across an entire transfer. So the merge
"automatically, and dynamically, adjusts the channel contributions to the mix",
using "dynamically adjusted levels computed via a moving average", and "the average
level of the merged output is exactly the same as the average of the levels of the
incoming channels. This means that **the louder channel will be reduced, the softer
one amplified**."

**The window must be long, and that is a safety property.** "The moving average is
calculated over a **long scale**, so as not to introduce audible effects", and the
resulting artefacts are "at a very low level and **in the frequency range 0-20 Hz**".
The reason it matters beyond artefacts: "**significant level changes will normally
be associated with major damage** — for example a bad scratch", and the manual's
own screenshot shows the two channels' peaks differing by **10 dB** at one. A short
window would track that and quietly duck the undamaged wall.

**Merge last.** "If you intend to process a file more than once — perhaps for a
subsequent de-crackling — **do not apply the merge option at any of the intermediate
stages**. This way each channel will be processed independently each time." The
executor already enforces the spirit of this: `mono_merge` is the last pre-split
stage, after `declick` and `decrackle`.

**On shellac it also removes vertical noise.** For 78s the merge "will remove quite
a lot of vertical low-frequency noise" — anything out of phase between the walls
cancels outright, being vertical motion the lateral cut never carried.

## Inputs

**Uncalibrated numbers in this skill**: the **1.0 s** default window, the
**0.05 s** floor `lint` warns below, and the **0.9** channel-correlation line. The
first two are bounded by the citation rather than given by it — a moving average of
length *T* band-limits its own modulation to about 1/*T* Hz, so the cited "0-20 Hz"
implies *T* ≥ ~50 ms, and "long scale" implies considerably more. The correlation
line is entirely in-house.

From `analysis.json`:

- `recording_info.channel_correlation` — **the deciding measurement**, and one of
  the few this stage may take from the capture even though four stages run ahead of
  it. The invariance is worth naming rather than assuming
  ([adr/0019](../../../docs/adr/0019-a-stage-is-parameterised-on-its-own-input.md)):
  `prefilter`, `declick` and `decrackle` repair sparse defects and leave the two
  walls' shared programme alone, so none of them can turn a stereo pressing into a
  mono one or the reverse. Two walls of
  one mono groove are two observations of the same signal, so a mono capture reads
  very high; a stereo record reads well below. `lint` warns below 0.9
  (`mono-merge-on-stereo-material`) when it can see the analysis. It is `null` on a
  single-channel capture.
- `recording_info.channel_balance_db` — how far apart the two walls sit. The
  reference measured 1.4 dB on one transfer; this is the same quantity, and it is
  what the level match will be undoing.
- `source.channels` — fewer than two and there is nothing to fold.
- The release: **is this pressing mono?** A discography entry says so, and it is
  cheaper and more reliable than inferring it. Ask if it is not settled.

## Decision guide

1. **Default**: `"enabled": false`. Every stereo record, and any record whose
   mono-ness you have not established.
2. **Enable only when the pressing is mono**, confirmed from the release and
   corroborated by a high `channel_correlation`. Two weak signals do not make a
   strong one: if the release is unknown *and* the correlation is ambiguous, ask.
3. **`strategy: "level_matched"`** is the default and the right answer when both
   walls are comparably damaged. It is the one that buys the noise reduction: the
   signal adds coherently and the wall-specific damage does not.
4. **`strategy: "left"` or `"right"`** when one wall is plainly better — the
   reference's own first option. This is a **listening** decision, so make it at
   the checkpoint rather than from a number, and say in the rationale what you
   heard. Taking the good wall beats averaging it with the bad one.
5. **`level_window_seconds`**: leave it at 1.0. Shorter is the failure mode the
   citation warns about; there is no argument here for longer, and no source for
   either direction beyond "long".
6. **Do not enable it to fix a channel imbalance on a stereo record.** That is not
   what this is, and there is no gain-balance stage — say so instead.

## Output

```jsonc
"mono_merge": {
  "enabled": true,
  "engine": "native",              // only 'native' implements mono_merge
  "strategy": "level_matched",     // level_matched | left | right
  "level_window_seconds": 1.0,
  "decision": { "skill": "plan-mono-merge", "rationale": "…", "confidence": 0.9,
                "inputs": ["analysis.json#recording_info", "discogs:release/…"] }
}
```

Optional in the contract at schema 3.6: a plan that omits it is valid and behaves
as disabled. The file stays stereo either way — the merged signal is written to
both channels, as the reference does.

`lint` findings that belong here: `mono-merge-on-stereo-material`,
`mono-merge-without-two-walls`, `mono-merge-window-short`.

## Checkpoint

**Open this checkpoint only if the record is mono.** On everything else it is one
line — "mono_merge: off, this is a stereo pressing" — and the flow moves on.

Render it into `review/mono/` with `normalize` still off, so it differs from
`review/decrackle/` (or `review/declick/`) by the fold alone:

```sh
vinyl-process execute plan-side-a.json --audio <recording> \
  -o review/mono --manifest manifest-side-a.json
```

Present:

- **the evidence that it is mono**: the release, and `channel_correlation`. Say
  which of the two you are leaning on;
- `channel_balance_db` before, and the **gain span the tracker actually used**,
  which the manifest's `mono_merge` stage detail reports as
  `gain=-0.67..+0.73 dB`. A span far wider than the balance figure means the
  tracker moved with the material rather than with the transfer, and is worth
  investigating before shipping;
- **the choice between merging and taking one wall**, as a listening question, not
  a measurement — and it has to be, because no number here predicts the outcome. Ask them to play the same passage three ways — left only, right
  only, merged — and say which they prefer. The reference offers all three because
  the answer is genuinely per record;
- for a 78, that the merge also cancels vertical low-frequency noise, so the
  improvement may be larger than on an LP;
- that this is **not reversible from the album**: both channels carry the same
  data afterwards, and the capture is the only place the two walls still exist.

Do not lead with a spectrum or a waveform. What changed is the *difference*
between the channels, which neither figure shows.

## Rules

- Never merge audio yourself; the executor does.
- Runs **last in the pre-split phase**, after `declick` and `decrackle`, because
  the walls must be repaired independently first — that is the reference's
  instruction and
  [adr/0015](../../../docs/adr/0015-a-mono-record-has-two-observations-of-one-signal.md)
  records it.
- The output stays stereo, with the same data in both channels. Do not ask for a
  single-channel file here; `export` has no channel control and the contract has
  no field for one.
- A capture that is already one channel cannot be folded. The stage skips, the
  manifest says so, and the honest note is that the redundancy was discarded at
  capture time — upstream, in `vinyl-archive`.
- `channel_correlation` is a whole-file figure and the merge is applied to the
  whole side, so there is no per-track version of this decision. A record with a
  mono side and a stereo side is two plans anyway.
