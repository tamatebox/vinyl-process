---
name: plan-speed
description: Record the replay speed a transfer was played at and the speed it should have been, so the executor can correct it. Produces the speed section of processing_plan.json. Use for a turntable running off-speed, or a 78 whose cutting speed was not 78 rpm.
---

# Plan Speed

Record two numbers: the speed the turntable **actually ran at**, and the speed the
record **should have been played at**. The executor derives the ratio and
resamples.

This skill measures nothing. The deviation comes from a strobe disc, a test
record, a reference tone, or a judgement about the music — and **naming which** is
most of the job, because on a 78 the answer is often not knowable and the plan is
where that has to be admitted.

Disabled by default. On a modern turntable playing a modern LP, the right answer
is almost always to leave it off.

## Outside references

Where a claim below is a matter of transfer practice rather than of this codebase,
it is cited. Anything here without a citation is an in-house judgement and should
be treated as uncalibrated until someone finds a source for it.

**Fix it at replay, not here.** IASA-TC04
[5.2.5 Speed](https://www.iasa-web.org/tc04/mechanical-carriers-speed): "it is
imperative that the disc be **replayed for transfer as close to the original
recording speed as is possible**". Where a reduced-speed replay is deliberate — for
tracking a damaged carrier — the guidance pairs it with the capture rather than
with post-processing: "half-speed replay may be the simplest to employ, as it can be
coupled with **a doubled sample rate** to produce corrected-speed transfers with a
minimum of distortion".

So this stage is the **second-best** answer and should say so. It exists because a
transfer that already happened cannot be replayed differently without doing it
again, and because a resample is exact where a re-transfer costs an afternoon. It
does not make an off-speed transfer as good as an on-speed one: every stage ahead
of it, and the analysis the whole plan was written from, saw the wrong spectrum.
`lint` warns above a semitone (`speed-correction-is-gross`) for exactly that
reason.

**Document the chosen speed — that is an instruction, not a nicety.** The same
section: "**the chosen replay speed should be documented in accompanying
metadata.** This is particularly important where any doubt remains as to the actual
recording speed." This is why the section carries `played_rpm` and `intended_rpm`
rather than a bare ratio: the pair *is* the documentation, and it survives in the
plan next to the `rationale` that says how it was arrived at.

**78 was never a single speed.** "Despite being referred to as '78s', it was very
often the case that **coarse groove shellac discs were not recorded at precisely
78rpm**", and different companies set different official speeds which "were varied
by recording engineers, on occasion during recording sessions". So for a shellac
disc `intended_rpm` is a **judgement**, not a lookup — and the reference is explicit
that "subjective decisions often become necessary", informed by "understanding the
recorded content or recording context".

**What is not cited**: any method for measuring the deviation. IASA names none in
this section, and this project measures none — see *What this codebase cannot tell
you*.

## Inputs

**Uncalibrated numbers in this skill**: the **100-cent** line above which `lint`
calls a correction gross. In-house; the argument behind it (that everything
upstream saw the wrong spectrum) is not.

- **The person who made the transfer.** The primary input, and usually the only
  reliable one. What turntable, at what setting, checked how.
- The release: what speed is this pressing cut at? A 7" at 33, a 12" single at 45,
  an LP at 33 1/3. For shellac, what the label or the discography says — and
  whether it says anything.
- `analysis.json#periodicity` — see below for what it can and cannot do.
- `analysis.json#source.duration_seconds` against a printed side duration. A whole
  side running consistently long or short by the same fraction is evidence; a few
  seconds is not, because printed durations are unreliable (`plan-split` has the
  same warning).

## What this codebase cannot tell you

**There is no speed-deviation measurement here, and `periodicity` is not one.**
It correlates the onset envelope at *configured* periods — 1.8 s and 1.3333 s, the
nominal turns of 33 1/3 and 45 — and reports how strongly each matches. That
answers "is this defect once per revolution", which is what `plan-split` needs. It
does **not** search for the period the platter actually ran at, so it cannot see
that a turntable is 0.4 % fast. Do not read a `revolution[].r` as a speed
measurement.

What that leaves, in order of how much they are worth:

1. **A strobe disc or a test record.** The turntable's own speed, measured
   directly, by the person holding it. This is the answer to ask for.
2. **A reference tone captured on the disc** — mains hum at a known frequency, or
   a test tone. Rare on music pressings.
3. **Pitch of the music against a known reference.** Weak for anything historical:
   concert pitch was not fixed, and a performance may simply have been in a
   different key.
4. **Side duration against a printed one.** Weakest, and only as corroboration.

If none of these is available, **say so and leave the stage off**. A guessed ratio
is worse than an uncorrected transfer: it is an uncorrected transfer plus a
resample, plus a plan that claims a fact nobody established.

## Decision guide

1. **Default**: `"enabled": false`.
2. **Enable when a deviation has been measured or decided**, and put *how* in
   `decision.rationale`. Name the method from the list above.
3. **`played_rpm`** is what the turntable ran at, **`intended_rpm`** what the
   record wanted. Ratio = played / intended, and the executor derives it: played
   fast gives a ratio above 1 and the correction stretches the audio back out.
4. **For a 78**, write the speed you concluded and say it is a judgement. The
   reference expects that; a plan that states 78.26 with no rationale is claiming
   more than anybody knows.
5. **A gross correction — more than a semitone — is a signal to stop and re-record
   instead.** The transfer can be done again at the right speed, and that is what
   practice asks for. Where it genuinely cannot be, proceed and say plainly in the
   rationale that the analysis this plan rests on described the uncorrected audio.
6. **Do not combine with `export.sample_rate`** unless the user asked for both.
   The audio is then resampled twice, and `lint` reports `speed-and-resample`.

## Output

```jsonc
"speed": {
  "enabled": true,
  "engine": "native",              // only 'native' implements speed
  "played_rpm": 33.4,              // what the turntable actually ran at
  "intended_rpm": 33.3333,         // what the record wanted
  "decision": { "skill": "plan-speed", "rationale": "…", "confidence": 0.8,
                "inputs": ["strobe disc, measured by the owner"] }
}
```

Optional in the contract at schema 3.7: a plan that omits it is valid and behaves
as disabled.

`lint` findings that belong here: `speed-without-both-rpm` (an error),
`speed-no-op`, `speed-correction-is-gross`, `speed-and-resample`.

## Checkpoint

**Open this only when the stage is enabled.** Otherwise one line: "speed: off, the
transfer was made at 33 1/3 on a turntable checked with a strobe".

Present:

- **the two speeds, and how the deviation was established.** Not the ratio first —
  the method. A number whose provenance is not stated is the failure this whole
  skill is arranged around;
- the correction in **cents**, which is the unit a listener can judge, and the
  manifest reports it: `33.4 -> 33.3333 rpm (x1.002000); … pitch -3.5 cents`. Under
  about 5 cents nobody will hear it and the honest framing is that this is a
  correctness fix rather than an audible one;
- the new side duration against the old, since a speed correction changes both
  pitch and length and the length is the easier one to check against a printed
  duration;
- **that the plan's own boundaries did not move.** The cut positions stay indices
  into the source recording and the executor maps them through the correction, so
  a boundary agreed at the split checkpoint still lands where it was agreed
  ([adr/0016](../../../docs/adr/0016-a-pre-split-stage-may-remap-time.md)). Say
  this, because it is the thing a person will reasonably worry about.

Render into `review/speed/` and ask them to listen for pitch against something they
know. Do not ask "does it sound better": a 3-cent correction does not, and asking
invites a yes.

## Rules

- Never resample yourself; the executor does.
- Runs **last in the pre-split phase**, after every repair stage. That way repair
  works on the transfer's own samples rather than on interpolated ones, and the
  parameters chosen against `analysis.json` still describe what the engine sees.
- **Plan positions are unaffected.** `split.tracks[]` stays in source samples and
  the manifest still reports source samples; only the cut is mapped. Do not
  pre-scale a boundary yourself — that would double the correction.
- A speed error scales time and pitch **together**, so the fix is a resample and
  nothing else. Do not ask for time-stretching or pitch-shifting: each would fix
  one half and break the other.
- The correction is applied as a rational approximation of the ratio, within about
  4e-7 — four orders of magnitude below the smallest deviation anyone corrects.
  The manifest reports the frame counts, so the realised ratio is checkable.
- `analysis.json` describes the **uncorrected** transfer. Every figure quoted from
  it after this stage is enabled — durations above all — is in the old timeline.
  Say which timeline a number is in whenever it could matter.
