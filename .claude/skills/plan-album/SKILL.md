---
name: plan-album
description: Orchestrate planning for a raw vinyl recording — run the analyzer, apply the plan-split/plan-declick/plan-normalize/plan-metadata/plan-export skills, assemble and lint processing_plan.json, then execute it. Use when the user wants to process a raw vinyl recording end to end.
---

# Plan Album

Turn a raw recording into a validated `processing_plan.json`, then execute it.
You are the planning layer: **you decide, Python only measures and executes.**

## Procedure

1. **Measure** (skip if an `analysis.json` for this exact file already exists):
   ```sh
   vinyl-process analyze <recording> -o analysis.json
   ```
   Read `analyzers[]` first: a section is absent when its analyzer failed, and
   every decision below must cope with that instead of assuming a field exists.

2. **Gather context**
   - Release identity: artist/album, or a Discogs/MusicBrainz release ID or URL.
     Prefer an explicit ID — pressings differ.
   - User preferences: `vinyl-process config show`. These are defaults for your
     decisions, not commands to the executor.
   - Tracklist with per-track durations, when a release is known.

3. **Decide each section** with its owning skill, in this order:
   | Section | Skill |
   |---|---|
   | `split` | [plan-split](../plan-split/SKILL.md) |
   | `declick` | [plan-declick](../plan-declick/SKILL.md) |
   | `normalize` | [plan-normalize](../plan-normalize/SKILL.md) |
   | `metadata` | [plan-metadata](../plan-metadata/SKILL.md) |
   | `export` | [plan-export](../plan-export/SKILL.md) |

4. **Assemble** `processing_plan.json`:
   - `source`: copy verbatim from `analysis.json`.
   - `analysis`: `{"path": "analysis.json", "sha256": "<sha256 of that file>"}`.
   - `created_by`: `"plan-album"`.
   - one object per section, each with a `decision` block recording `skill`,
     `rationale`, `confidence` and the `inputs` you consulted.
   - `notes`: a short summary of the decisions that were not obvious.
   - See `examples/processing_plan.example.json` for the exact shape and
     `schemas/processing_plan.schema.json` for the formal contract.

5. **Lint before handing over** — never give the user an unexecutable plan:
   ```sh
   vinyl-process lint processing_plan.json --audio <recording> --analysis analysis.json
   ```
   Fix every `error`. Explain or fix every `warning`.

6. **Confirm with the user**: track list with durations, and the decisions worth
   knowing about (unusual boundaries, skipped stages, aggressive declicking).

7. **Execute** once they approve, then sanity-check the manifest:
   ```sh
   vinyl-process execute processing_plan.json --audio <recording> -o <album-dir>
   ```

## Rules

- Never modify audio yourself and never bypass the executor.
- Only include the stages the workflow needs: set `"enabled": false` on the rest
  (re-tagging an existing rip = disable `split`, `declick` and `normalize`).
- The plan must stand alone: someone with only the recording and the plan must be
  able to reproduce the album exactly.
- One recording per plan. A two-sided album is two recordings, two analyses and
  two plans exported into the same album directory.
