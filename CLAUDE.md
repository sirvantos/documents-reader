# documents-reader

Local PoC: reading, field extraction, search and answers over Russian contracts.
Governing documents: `.specify/memory/constitution.md` (highest priority),
`docs/tech-context.md`, `docs/field-catalog.md`. Features are developed with Spec Kit
(`/speckit.*` commands, artifacts in `specs/<NNN-feature>/`).

## Data privacy (constitution, principle I)

- Never read, print, list or copy anything from the data directory
  (`$DOCREADER_DATA_DIR`) or any real contract, gold set or run result.
- Debug and test only on synthetic files that live in the repository.
- Do not run pipeline commands against real data; the analyst does that in their
  own terminal.

## Model routing

- Spec work stays in the main session (Opus): `/speckit.specify`, `/speckit.clarify`,
  `/speckit.plan`, `/speckit.tasks`, `/speckit.analyze`, `/speckit.checklist`,
  `/speckit.constitution`.
- During `/speckit.implement` the main session coordinates and delegates the work.
  It reads `tasks.md`, hands each task (or a small group of tightly related tasks)
  to the `implementer` subagent, reviews the result, runs the tests, then marks the
  task `[X]`.
  - Default: `implementer` on its own model (Sonnet).
  - Mechanical tasks: pass `model: "haiku"`. These are project scaffolding and config,
    CLI argument wiring, output formatting, and synthetic test-file generators.
  - Critical tasks: the main session does these itself on Opus instead of delegating.
    These are database schema and migrations, atomic file intake (copy and
    transaction ordering), classification and other decision rules, anything touching
    the privacy guards, and any task whose first delegated attempt failed review.
- Independent tasks marked `[P]` may be delegated in parallel.
