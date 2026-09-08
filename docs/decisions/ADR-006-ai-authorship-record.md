# ADR-006: AI authorship record for the build

## Context
The build ledger is gitignored, so the repository needs a committed record of which model
produced which commit.

## Decision
| Task | Commit(s) | Implementer model | Reviewer model |
|---|---|---|---|
| 1 | c5fb5c7 | Sonnet 5 | Sonnet 5 |
| 2 | be4c661 | Sonnet 5 | Sonnet 5 |
| 3 | ab0830d, 17bdf8c | Haiku 4.5 | Sonnet 5, Haiku 4.5 |
| 4 | d9a3d21, 7fa93af | Haiku 4.5 | Sonnet 5, Haiku 4.5 |
| 5 | 8643265, 01de50a | Sonnet 5 | Sonnet 5, Haiku 4.5 |
| 6 | 80d1577, d51804a | Sonnet 5 | Opus 5, Sonnet 5 |
| 7 | 6ebefb5 | Haiku 4.5 | Sonnet 5 |
| 8 | fe12fd7, 1247f89 | Sonnet 5 | Sonnet 5, Haiku 4.5 |
| 9 | fe30283 | Haiku 4.5 | Sonnet 5 |
| 10 | 297565f | Sonnet 5 | Haiku 4.5 |
| 11 | 1dbde8c, 16951f3, 2d2646d | Sonnet 5 | Opus 5, Sonnet 5, Haiku 4.5 |
| 12 | 33234bb, 041db1e | Haiku 4.5 | Sonnet 5, Haiku 4.5 |
| 13 | 8814c41, cbc4fda | Haiku 4.5 | Sonnet 5, Haiku 4.5 |
| 14 | 0d6cbb8, d02784e | Sonnet 5 | Sonnet 5, Haiku 4.5 |
| 15 | c20a5a3 | Haiku 4.5 | Haiku 4.5 |
| 16 | f6f939e, 1a73ed8, and the commit that lands this row | Sonnet 5 | Sonnet 5, Haiku 4.5 |

Controller throughout: Claude Fable 5.1.

## Consequences
Every `[worker]` commit is AI-produced; `[human]` commits are Jeremy's. The table above is
extended by each later task.
