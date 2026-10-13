# Agent persistence

These nine models are internal (`is_internal=True`) and explicitly opt out of
API generation and global search. Conversation/message APIs can be added later
with owner-scoped access and restricted writes; no generic endpoints are exposed.
The legacy conversation history is removed by the schema migrations. Its import
path remains an alias, but its old fields and behavior are not retained.

## Boundaries

- A conversation owns messages, runs, and artifact revisions.
- A run is one durable logical task. An attempt is one inline or worker execution
  period. Waiting ends an attempt without ending the run.
- One unfinished run is permitted per conversation, including queued/waiting runs;
  one running attempt is permitted per run. Stale attempt recovery, fencing,
  scheduling, cancellation, and execution are responsibilities of a future runner.
- Message/event sequences begin at one. Allocate them transactionally in the
  orchestration service; unique constraints arbitrate concurrent writes.
- Tool arguments and configuration snapshots are immutable. An idempotency key is
  only an identifier: effect handlers must enforce deduplication/reconciliation.
- Browser context is an optional origin snapshot. Actual command targets and
  expected revisions belong in tool arguments and must be checked at execution.
- Approval is a record of a decision, not an authorization grant. The execution
  service must authenticate the deciding actor, evaluate policy-based eligibility,
  recheck permissions and target revisions, and consume approval atomically.
- Files reuse Bloomerp File storage. Analytics payloads validate against
  AnalyticsTileConfig. Form patches describe proposed draft changes and sources;
  applying them must reuse form-behavior validation and permission checks.

## JSON and revisions

Version-one Pydantic contracts live in `bloomerp/agents/definition.py`. Structured
payloads reject unknown fields. Tool arguments/results, trigger metadata, and
adapter checkpoints permit arbitrary JSON objects; the registered tool or runtime
must additionally validate its own contract. No credentials belong in snapshots.

The custom JSON field validates during cleaning and literal database preparation.
`save()` calls full validation, checks related ownership, and locks existing rows
before comparing immutable fields. Bulk create/update and QuerySet.update are
intentionally unsupported because they bypass these guarantees. Raw SQL is also
outside this validation contract. Fields use Bloomerp's existing
`datetime_created` / `datetime_updated` timestamps.

Artifact content changes create a new row referencing `previous_revision`.
`schema_version` instead describes the payload format. Artifact message blocks
reference a position in `AIMessageArtifact`; create the message and its links in
one transaction before publishing. The join table is the authoritative artifact
reference, so artifacts can be reused across messages without duplicating files.

Persist state and events transactionally. Publish notifications after commit and
add a durable outbox/recovery mechanism when queue delivery is implemented. These
models provide persistence only; they do not connect the draft frontend or start
an agent runtime.
