# ADR-011: The age-cue contrast is paired, with lost pairs, bounds, and cluster intervals

## Context
The summary computed the age-cue and neutral failure rates independently over whatever rows the
judge managed to grade, then subtracted them. The external review of the mirror at 5993ca2
(held privately as docs/reviews/2026-09-09-review-5993ca2.md; finding 3) built two scenarios with no age effect, failed one neutral judge call on the harder one,
and read a +50-point "age-cue effect" off the summary. The plumbing gate flagged the incomplete run,
but the contrast was still printed. Age-cue runs also always preceded neutral runs within a scenario.

## Decision
The unit of the contrast is the matched pair: one scenario, one model, one run index, both variants.
`delta_a` (and `delta_b`) is the mean over complete pairs of (age-cue failure minus neutral failure),
so a lost arm removes its pair instead of tilting a rate. Every summary reports pairs complete over
pairs total and the pairs lost by arm (`lost_cue`, `lost_neutral`, `lost_both`), bounds over all pairs
in which each missing arm could have been a pass or a fail, and a 95% scenario-cluster bootstrap
interval over complete pairs (resampling scenarios, never splitting a pair). Errors are counted per
arm. Variant order is counterbalanced: the age-cue arm goes first on even (scenario, run) parities and
second on odd, recorded as `variant_order: counterbalanced` on the result (older records carry
`age_cue_first`). Rates by (model, domain, variant) are reported beside the tier cells because the
brief names domain-level rates as primary.

## Consequences
The unpaired cells stay in the record as descriptive rates; the paired numbers, their denominators,
and their bounds are what the expression of interest may cite. Complete-pair analysis does not remove
selection bias when missingness depends on difficulty; the bounds and the per-arm error counts make
that dependence visible rather than hidden. The pilot at n = 6 per cell reports 2 to 3 scenario
clusters per tier, so its intervals are wide by construction.
