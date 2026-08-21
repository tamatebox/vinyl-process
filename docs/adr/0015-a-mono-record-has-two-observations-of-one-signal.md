# 0015 — A mono record has two observations of one signal

**Status**: accepted

## Context

A mono groove is cut **laterally**: the signal is purely horizontal motion, so
both walls carry it. The ClickRepair 3.9 manual's chapter on mono records puts it
directly — "if the stylus is moving in response to tracking a mono recording, the
response measured as movement of the two walls will have the same magnitude… the
electrical output which goes to the audio system will be the same in each channel".

The damage is not shared to the same degree: "**one wall of the groove is often
less damaged than the other**". So a stereo capture of a mono record holds two
observations of one signal with substantially independent noise on each — a
redundancy nothing in this pipeline exploited. Every mono LP and every 78 was
handled as though the two channels were two different signals.

The reference is also explicit that this is why to capture in stereo at all:
"better noise reduction may be achieved by capturing and processing mono material
in stereo", and "this method gives much better results for mono recordings, both
vinyl and shellac".

## Decision

`mono_merge` is a stage, **last in the pre-split phase**, after `declick` and
`decrackle`.

The plan asked whether this should be "a `params` option on the existing
algorithms or an algorithm id of its own". It is **neither**, and reading the
chapter is what settled it: the reference repairs the two walls *independently*
and merges *afterwards* — "the left- and right-hand channels are processed
independently, in order to extract the maximum amount of information", then "the
two channels are merged" — and warns "if you intend to process a file more than
once… **do not apply the merge option at any of the intermediate stages**". A
merge that must follow every repair pass cannot be a parameter of one of them.

### The technique is a level-matched merge, not a substitution

This plan's premise was that "damage on one wall can be filled from the other".
That is not what the reference does, and the reason is in the same chapter: "phono
cartridges are mechanical devices subject to mechanical limitations, and this
ensures that **a scratch in one wall will have consequences in both channels**".
A substitution needs a clean donor at the damaged instant, and the citation says
there often is not one.

What it does instead is merge, with the levels tracked: "it is nearly always the
case that the two channels of data, even if they are highly correlated (as they
should be), are at **different recording levels**" — 1.4 dB across one whole
transfer in its worked example — so the merge uses "dynamically adjusted levels
computed via a moving average", and "the average level of the merged output is
exactly the same as the average of the levels of the incoming channels. This means
that the louder channel will be reduced, the softer one amplified."

**What is established, and what is not.** Averaging two observations whose noise
is independent improves SNR by 3 dB; that is arithmetic, and a test on synthesised
walls with the reference's own 1.4 dB offset confirms the implementation reaches it
(+3.02 dB). Purely out-of-phase content cancels outright, which is arithmetic too,
and is the mechanism behind the manual's note that on shellac the merge "will
remove quite a lot of vertical low-frequency noise".

**Neither figure says what this buys on a record**, and the citation is the reason
to expect less: the walls' damage is *not* independent, because "a scratch in one
wall will have consequences in both channels". The synthetic walls were built with
independent noise — by the same hand that wrote the merge — so 3 dB is the ceiling
of an assumption the source denies, not a measured benefit. What a pressing
actually gains is unmeasured here, and `plan-mono-merge`'s checkpoint is therefore
a listening comparison between the two walls and the merge, not a number.

`strategy` also offers `left` and `right`, which are the reference's own first
option: "audition the left and right tracks separately, and choose the one which is
better". Splicing sections of both — its second option — is not offered: it is
per-passage surgery that "can be very time-consuming" and there is nowhere in this
contract to express it.

### The window is long, and that is a safety property

`level_window_seconds` defaults to 1.0. The citation gives "the moving average is
calculated over a **long scale**, so as not to introduce audible effects" and puts
the tracker's artefacts "in the frequency range 0-20 Hz". A moving average of
length *T* band-limits its own gain modulation to roughly 1/*T* Hz, so 0-20 Hz
implies *T* ≥ about 50 ms — that is the floor `lint` warns below, **derived** from
the citation rather than quoted from it. 1.0 s is this project's own choice and is
marked uncalibrated.

The real reason it must be long is not artefacts: "significant level changes will
normally be associated with **major damage** — for example a bad scratch", and the
manual shows a 10 dB instantaneous difference at one. A tracker fast enough to
follow that would duck the *undamaged* wall while the damage passed. A test pins
that a 1 s window's gain span is unmoved by a scratch that swings a 10 ms window
several dB.

## Consequences

- `SCHEMA_VERSION` 3.5 → **3.6**, minor: optional, disabled by default.
- **The output stays stereo**, with the same data in both channels — "the same
  data is written to both channels of the output file". Collapsing the channel
  count here would surprise every later stage, and `export` has no channel control.
- **Enabling it on a stereo record destroys the image, and nothing downstream
  notices.** That is the one catastrophic failure available, so `lint` checks
  `recording_info.channel_correlation` against 0.9 when it can see the analysis
  (`mono-merge-on-stereo-material`). It is the only check in the pipeline that
  needs both documents at once. The 0.9 line is in-house.
- The stage is irreversible from the album: afterwards both channels carry the
  same data, and the capture is the only place the two walls still exist.
- **A gap this made visible, and did not close.** `native.declick` detects on the
  channel *mean* and repairs every channel over the same span, whereas the
  reference makes "decisions on click detection and repair in the two channels…
  independently". On a mono record that throws away exactly the redundancy this
  stage exists to use — a click found on the mean is repaired on the clean wall
  too. Per-channel detection would change output bytes for any plan with declick
  enabled, so it is its own decision and its own record, not a rider on this one.
