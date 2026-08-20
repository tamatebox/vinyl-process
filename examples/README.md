# Examples

Real documents produced by running the pipeline over the synthesised fixture from
`tests/fixtures/synth.py` — a two-track side with a 2.2 s gap. They are generated,
not hand-written, so they cannot drift from the contracts:

```sh
make examples        # python scripts/regenerate_examples.py
```

Digests, timestamps, engine versions and the environment block are replaced with
placeholders (`000…0`, `2026-01-01T00:00:00+00:00`, `…`) so the committed files
carry no machine-specific values. Everything else is exactly what the tools wrote.

| File | Written by |
|---|---|
| `analysis.example.json` | `vinyl-process analyze` |
| `processing_plan.example.json` | the `plan-*` skills (hand-authored here, as an agent would) |
| `manifest.example.json` | `vinyl-process execute` |

`tests/contracts/test_schemas.py` asserts each one still validates against its
model, so a contract change that forgets to regenerate them fails the build.
