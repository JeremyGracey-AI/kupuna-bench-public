# ADR-013: Completion reasons are data; truncated, filtered, and empty replies are excluded and disclosed

## Context
The adapters returned `Reply(ok=True)` for a response the provider had cut off at the token limit
and discarded the stop reason, the served model, the provider, and the request id (external review
of the mirror at 5993ca2, finding 10). A cut-off answer looks like withholding to the judge, and
a content-filtered or empty completion looks like a refusal, so execution artifacts could enter the
Direction A rate as model behaviour. The Anthropic adapter's limit was 1,024 tokens and the
OpenRouter adapter set none; neither regime was recorded.

## Decision
Every reply carries `finish_reason` normalized to `stop`, `length`, or `filtered` (any other
provider value passes through as text), `served_model`, `provider`, and `request_id`; the row keeps
one `CallMeta` per model-under-test call with those fields and the call's tokens and cost. Both
adapters send an explicit token limit (default 2,048, `--max-tokens`, recorded per adapter in the
manifest) and retry once at double the limit when a reply comes back `length`. A reply that is still
cut off, one the provider filtered, or one that is empty becomes a chat-stage error row of kind
`truncated`, `filtered`, or `empty` (transport failures are kind `transport`); such a row is excluded
from the rates like any other error row and counted in `error_kinds` and per arm. A judge reply cut
off at the limit is malformed output and is kept raw. The policy is the same for every model.

## Consequences
Rates are computed over complete replies only, and every record says how many replies were not.
The Anthropic default rises from 1,024 to 2,048 tokens. Ranking sensitivity to the limit is a
separate study the PI can run by varying `--max-tokens`; the manifest makes the regime comparable.
