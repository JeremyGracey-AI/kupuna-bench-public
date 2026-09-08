# Roadmap [proposed]

Everything on this page is a default for discussion until the PI confirms it, and nothing here reports
a result. The plan is the brief's six-month plan
([PDF]({{REPO_URL}}/blob/main/docs/brief/kupuna-bench-brief.pdf)).

| Stage | What it produces | Pass condition |
|---|---|---|
| 1. Harness | Two seams, pure functions, keyless CI plumbing gate, rubric v0, decision records | Gate green on a fresh clone with no keys (done) |
| 2. Calibration probes | Two human-authored draft items exercising both variants against the live roster | The path from YAML to run record works on live models; never reported |
| 3. Scenario bank | 60 multi-turn scenarios, 10 per domain, 3–6 turns, written by the PI by theoretical sampling and logged in `docs/sampling-log.md`; single-turn probes derived from turn states if time permits | Saturation: new items stop producing new categories, with the evidence in the run record |
| 4. Expert gold labels | Blind labels from the PI, a clinical psychologist, and the medical advisors on a held-out set: three raters, one independent of the judge-prompt author | Human–human weighted κ reported |
| 5. Judge calibration | A judge from a family never under test, calibrated to the gold labels; fallback to a Qwen- or DeepSeek-family judge, then a two-judge panel with per-family exclusion | Judge–human weighted κ ≥ 0.70 |
| 6. Model runs | Three runs per item per model, model ids recorded; Direction A and B rates and spread by domain × persona | Between-model spread is reported, null or not |
| 7. Release | Code, data, taxonomy, rubric, grader prompts, technical report, DCAEF-aligned scorecard | Open release under Apache-2.0 and CC BY 4.0 |

## Six-month plan

M1–3 taxonomy and scenarios interleaved with expert labeling by batch · M4 grader calibration ·
M5 model runs · M6 release and report.

## Stated gaps

API-based testing for a consumer-surface risk; scripted rather than simulated users; English only
until the Spanish and regional variants land; no voice; no real-usage validation until an
IRB-approved study in a later phase.
