# ADR-005: Coders are not graders; at least one coder family is outside the roster

## Context
The grounded-theory discovery track uses language models as open coders. A reviewer will ask
whether a coder from a family under test can code its own transcripts.

## Decision
Coders are not graders, so overlap with models under test is allowed, but at least one coder
family must be outside the roster under test, results are reported per family, and every coder
is named in the coding result (exact dated ids and the served model id are planned).

## Consequences
Per-family disagreement is itself a measurement (a family's prior). A silent model update
changes the analyst, so coding results cite the model ids used; exact dated ids and the served
model id are planned.
