# Presenting a comparison

Whenever a checkpoint asks **did this help** or **which of these is right**, the
answer comes from listening, and what you hand over decides whether the listening
happens. Every such decision, not one stage: a repair against no repair, two
candidate boundary sets, a level against the level before it.

## The difference must be the thing under review

**One gain, identical windows, identical fades.** Anything else that differs
between the two copies is a confound, and the louder one wins whatever else is
true.

**Take the gain from the lower rung and never recompute it on the upper one.** A
repair removes impulses, so recomputing makes the repaired copy louder by whatever
came off the peak — a dB is plenty — and it is then preferred for that alone.
Compute once, from one side, apply to both.

**Never build a comparison with `normalize` on.** The pair must differ by one
stage, and a level nobody has agreed to is not that stage.

**Verify it rather than trusting it.** Read both copies back and assert they differ
only where the stage acted, that any marker between them is exactly zero, and that
the leading fade is bit-identical. Three lines, and it has caught both silent
failures: a window edge landing on the defect, and a fade applied to one copy from
a stale variable.

## Match the form to the question

| The question is about | Hand over | Never |
|---|---|---|
| a point defect (a click, a tick) | short clips that switch on their own, **plus** one continuous stretch | only the full tracks — nobody scrubs two long files to the same timestamp |
| a boundary, an entrance, a tail | **whole tracks**, and where two candidate boundary sets are in play, both sets rendered whole under one gain | clips stitched from fragments — tail, dropped segment, next entry. Tried, and read as unintelligible ([plan-split](../skills/plan-split/SKILL.md)) |
| level | whole tracks, each at its own level | a flat gain to match them, which erases the question |

The clip form is for a point defect, and a cut is not one — so a boundary question
never gets clips, however tempting the excerpt looks. Everything above still
applies: two candidate boundary sets compared at two levels compares the levels.

For a point defect build **both** forms. Neither substitutes: a correction can be
plainly audible in a clip and make no difference to the four minutes around it.
Clips go one per defect worth naming — the loudest few, plus one where it is most
exposed (an unaccompanied instrument, a quiet passage) — each playing the window
raw, a silent marker, then the same window processed, with the switch time in the
filename. For the continuous stretch, find the densest run rather than a nice one,
say how many corrections it holds against the track's total, and write two files
rather than a concatenation so it can be looped. That is what "something
continuous" means; a run of clips does not become a listen.

## Building it

Window the two renders that already differ by one stage — the review ladder's
rungs — so you are cutting, not processing. Run it inline; **never save a script
into the job directory**, which is the planning layer written in Python and
invisible to every check here
([adr/0011](../../docs/adr/0011-a-job-directory-holds-no-scripts.md)).

```python
gain = 10 ** ((-1.0 - 20 * np.log10(peak_of_the_lower_rung)) / 20)
w = np.ones(n)
w[:FADE], w[-FADE:] = np.linspace(0, 1, FADE), np.linspace(1, 0, FADE)
# same gain, same w, same [t0, t1) for both copies
out = np.concatenate([A, np.zeros((GAP, ch)), B])
assert np.array_equal(A[:k], B[:k])  # the stage did not touch the fade-in
```

Write it wider than the capture and undithered, for the reason the ladder is: the
album's depth belongs to `plan-export` and an audition copy must not pre-empt it.
Keep it disposable — no manifest, never fed to a stage, never compared against —
with a `README.txt` saying so, which copy is canonical for what, and that both
halves share one gain taken from the lower rung.

## The window figures are uncalibrated

A **5 s** half, a **1 s** marker, **30 ms** fades, the defect **2 s** in. All
in-house. Only the half length has any history, and that history is one owner on
one record asking for five seconds after twenty proved too long to A/B — a recorded
preference, not a calibration. Decide from the criterion: **long enough that the
defect has musical context, short enough that the switch comes before the ear has
moved on.** Say in the checkpoint that you picked rather than sourced them.

The fades are the one figure with a reason behind it. A window edge or marker
boundary that steps from music to zero *is a click*, so an A/B about clicks without
them measures your own construction.

## Handing it over

Give the order to play them in and what each settles — three lines, not a directory
listing. Where the stage is per-side or per-track, name the copy that decides *that*
switch: "this one decides whether side A is worth repairing" is a question someone
can answer.

Positions go in `mm:ss.ss` **within the exported track**, taken from the
sample-wise difference between the two renders rather than the analyzer's positions
— the diff is what the engine did, the positions are what the detector guessed on
the whole file, and they disagree by a few events. Give the correction in dB and
the defect's own peak separately: −12 dB off a −13 dBFS click is a different event
from −12 dB off a −45 dBFS one.

**Say when the answer may be "no difference".** Where every correction is small,
the honest framing is that either answer is fine if nothing is audible, and that
the stage goes off for that side alone if something is. `"enabled": false` per plan
is how that is recorded, and a checkpoint that cannot be answered "it did not help"
is not a checkpoint.
