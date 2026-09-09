# KŪPUNA-AI Bench "Let's talk story."

**Measuring overrefusal and harmful compliance in AI conversations with older adults.**

KŪPUNA-AI Bench "Let's talk story." is an open-source evaluation of **paternalistic withholding**: refusal or hedging that
denies a competent adult information they need to decide on their own terms. Kūpuna is the Hawaiian
word for grandparents, elders, and ancestors: a role, not an age bracket. The posture the eval demands
of a model is the one a family takes toward its kūpuna: the older adult is the authority on their own
life, and every refusal or hedge is measured against that standard.

Every turn is scored in two directions on one severity scale. **Direction A, overrefusal:** withholding
needed information, redirecting without substance, infantilizing tone, substituting the model's risk
tolerance for the user's. **Direction B, harmful compliance:** lethal dosing detail under expressed
suicidal intent, endorsing driving despite disclosed cognitive-impairment cues, validating unsupervised
medication changes without flagging risk. Six domains: end-of-life planning, hospice and palliative
care, medications, driving cessation, grief and bereavement, loneliness and companionship. Each
scenario ships in an age-cue and a neutral variant, so the paternalism signal is measured, not inferred.

## Start here

| Page | What it answers |
|---|---|
| [Construct](Construct) | What is being measured, where the line between caution and paternalism sits, what is new |
| [Rubric](Rubric) | Item tiers T1–T3, response severity S0–S3 per direction, the five per-turn criteria |
| [Method](Method) | Classic Grounded Theory as the construct-definition method; the forcing audit |
| [Running the harness](Running-the-harness) | Install, validate, run with scripted adapters or live models, regrade, agreement, chart |
| [Scenario format](Scenario-format) | The YAML a clinician writes, its four required fields, and how items are promoted |
| [Decisions](Decisions) | The decision records, ADR-001 onward |
| [Contributing and governance](Contributing-and-governance) | The mirror rule, what can change, commit prefixes, AI use, security reports |
| [Roadmap](Roadmap) | The proposed path from pilot to release |

## The brief

The two-page project brief: [PDF]({{REPO_URL}}/blob/main/docs/brief/kupuna-bench-brief.pdf)
([HTML source]({{REPO_URL}}/blob/main/docs/brief/kupuna-bench-brief.html)).

## Status

Pre-pilot. The harness, rubric v0, method, and decision records exist and are CI-gated. The scenario
bank and gold labels are being authored by the PI; judge calibration follows the first labeled batch.
`scenarios/probe/` holds two human-authored draft calibration items
(`docs/decisions/ADR-007-probe-set.md`); they are never promoted or reported. This wiki reports no
pilot numbers: results are published with the technical report.

## Team

The Gerontechnology Group, LLC (Houston, Texas).
PI: Melissa Mansfield, PhD, NAPG-CPG. Technical Lead and Co-Applicant: Jeremy A. Gracey, MS.
Medical Director: CAPT Gregory Raczniak, MD, PhD, USPHS. Second labeler: to be confirmed. Cite the software with `CITATION.cff`; every release is archived on Zenodo under the concept DOI [10.5281/zenodo.22667583](https://doi.org/10.5281/zenodo.22667583).
