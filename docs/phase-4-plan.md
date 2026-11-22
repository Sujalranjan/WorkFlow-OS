# Phase 4: workflow editor (done)

Goal: change a discovered workflow without re-recording it, with the same guarantees as discovery:
only catalog actions run, nothing is guessed, and a person approves exactly what will run.

## What can be edited

- Title and description.
- Steps: remove, reorder, or add any action from the catalog (also one that was never recorded,
  e.g. "label the processed email").
- Each step's inputs: **from an earlier step** (a value the same run produced, such as the new
  email's sender), **a fixed value**, or **ask when the run starts**. Optional inputs can stay on
  their default (e.g. the HubSpot property chosen in Settings).

## Rules (server-side, `services/workflow_editor.py`)

- Only catalog actions and their declared parameters; every required input has a source.
- A step must come after the steps that produce what it needs. Each catalog action declares
  `produces` and `requires` (e.g. `slack.reply_in_thread` requires `slack_ts`, `hubspot.update_contact`
  requires `contact_id`), so the editor rejects "reply in thread" before "post to Slack".
- A value that changed between recorded runs (a customer email, a message id) cannot be fixed to
  one of those recorded values: it would act on that record in every later run.
- A fixed value is what the approver approved: run-time inputs never override it.

## Versions and approval

- Saving creates the next version (1.0.0 -> 1.1.0) in `workflow_versions` (migration 0003), with
  author, time, note and a step-level list of changes; earlier versions are kept unchanged.
- The workflow goes back to *requires review*. Planning, manual runs and email triggers are
  blocked until someone approves the new version.
- Approve and reject carry the version the reviewer looked at; a different current version is
  refused (409), so nobody approves changes they have not seen.
- Writes are conditional on the record being unchanged since it was read, so a concurrent edit or
  decision is refused instead of silently overwriting the other (409).
- An execution plan is tied to the version it was made from: a plan (or a paused run) of an older
  version cannot run after an edit (execution policy check).

## API

| Route | Role |
|---|---|
| `GET /api/catalog` | viewer |
| `GET /api/workflows/specifications/{id}/definition` | viewer |
| `POST /api/workflows/specifications/{id}/definition/validate` | approver |
| `PUT /api/workflows/specifications/{id}/definition` | approver |
| `GET /api/workflows/specifications/{id}/versions` and `/versions/{version}` | viewer |

## UI

Workflow page: **Edit** (approvers), live validation against the server's rules, version history,
and a run panel that asks for "ask when the run starts" inputs and shows fixed searches read-only.

## Tests

`tests/backend/test_workflow_editor.py`: catalog rules, ordering by `requires`, recorded-value
pinning, version + re-approval, stale approval refused, concurrent saves, old plan blocked, an edited
routine (added Slack thread reply) run live against fakes, and the API end to end.
