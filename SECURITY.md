# Security and dual-use reports

KŪPUNA-Bench scores two failure directions, and Direction B (harmful compliance) means some
scenarios touch medication dosing, driving with cognitive impairment, and end-of-life decisions.
Answer keys are written as criteria, never as harmful specifics (`CONTRIBUTING.md`). If you find an
item, answer key, transcript, or document in this repository that reads like a recipe for harm, or a
security problem in the harness (for example a path that could expose an API key), report it
privately rather than in a public issue.

## How to report

Email melissa@thegerontechnologygroup.com with "KUPUNA-Bench" in the subject line.

By post: The Gerontechnology Group, LLC, 6501 Pickens St, Unit B, Houston, TX 77007, United States.

Name the file, item id, and turn it concerns and what a reader could do with it. Do not paste harmful
specifics into the report.

## What happens next

The PI decides whether the item is withdrawn, rewritten, or kept, and the decision is recorded in
`docs/decisions/` without the harmful specifics. Reporters are credited in the release notes if they
want to be.

## Scope

In scope: scenarios, answer keys, rubric, grader prompts, run records, and harness code in this
repository. Out of scope: the behaviour of the models under test; report that to the model's vendor.
