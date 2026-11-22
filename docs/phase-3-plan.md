# Phase 3: More integrations

Goal: WorkFlowOS works with the tools a real team uses, not only the bundled Demo CRM. Every new
integration follows the same rules as the existing ones: exact routing through the Action Catalog,
encrypted credentials connected from Settings, read-only verification after each run, and no
automatic retries after an external change.

Scope stays "production-ready for one team".

## Where things stand

| Area | Today | Gap |
|---|---|---|
| Catalog | 5 actions: Gmail search + attachment download, Demo CRM find + update, Slack message | Only the Demo CRM; no notes, no threads, nothing to write to a spreadsheet |
| Adding an integration | Touches ~8 places by hand: catalog entry, URL rules, executor, verifier, registry, credential store, Settings UI, status check | Slow and easy to get wrong; each new tool repeats it |
| Slack | Admin pastes a bot token + channel id; token checked with `auth.test` | No "Add to Slack" install, no channel picker |
| Gmail triggers | Every poll searches `(<query>) after:<created>` and takes the newest 25 | **Bug:** if more than 25 matches arrive between polls (e.g. after downtime) the older ones are never returned again and are skipped silently. Each poll also re-reads matches it already processed |
| CRM | Demo CRM only (`crm.*` actions, `/ui/customers` URL rules) | No real CRM |
| Browser extension | Watches Gmail, Slack and the Demo CRM | Needs rules for each new web app |

## Decisions (agreed 2026-11-19)

1. **Integration framework first.** One `Integration` definition per tool: its credentials and connect
   flow, health check, catalog actions, URL/observation rules, executor and verifier. Settings,
   `/api/status`, the executor registry and the classifier read from it. New tools then only add a
   module.
2. **Separate catalog actions per system** (`hubspot.find_contact`, not a generic `crm.find_customer`
   that switches backends). It keeps "one action, exactly one executor" and keeps observation rules
   unambiguous; shared CRM logic lives in a helper both executors use.
3. **HubSpot with a private-app access token** (pasted once in Settings, scopes checked on save), not
   a public OAuth app. It fits one team and needs no public redirect URL.
4. **Gmail: incremental sync with the History API** (`users.history.list` from a stored `historyId`)
   instead of re-searching. Nothing is missed, and nothing already seen is fetched again. No new
   infrastructure. Real push (Pub/Sub) stays optional for later because it needs a Google Cloud
   topic, and a public HTTPS endpoint for push delivery.
5. **Slack: channel picker now, "Add to Slack" (OAuth v2) in Phase 5** once the app is served over
   HTTPS (Slack requires an HTTPS redirect URL). The pasted bot token stays the way to connect.
6. **Extra Google permissions are opt-in.** Gmail stays read-only by default. Turning on "label
   processed emails" or "Google Sheets" in Settings reconnects Google with the added scope
   (`gmail.modify`, `spreadsheets`) through incremental authorization; actions that need a scope
   the connection lacks are blocked with a clear reason instead of failing at run time.

## Milestones

Each one is mergeable on its own, with tests on SQLite and Postgres.

### 3a: Integration framework (no behaviour change)
- `app/integrations/` with one module per tool (gmail, slack, demo_crm) that declares credentials,
  status, catalog actions, classifier rules, executor and verifier.
- Catalog, `classify_event`, executor/verifier registries, `/api/status` and the Settings page are
  generated from these definitions. Existing tests must pass unchanged.

### 3b: Gmail incremental sync (fixes the missed-email bug)
- Store a `history_id` per trigger. Each poll reads `users.history.list(startHistoryId)` for added
  messages, checks them against the trigger query, and pages through every result.
- If the stored id expires (Gmail keeps about a week), fall back to a full search since the last
  successful poll and say so on the trigger.
- Migration `0003` (trigger sync state). A regression test with 60 new emails between two polls.

### 3c: HubSpot
- Settings: paste a private-app token; save checks it and its scopes (`crm.objects.contacts.read`,
  `crm.objects.contacts.write`).
- Catalog actions: `hubspot.find_contact` (by email; several matches pause for a person, as the Demo
  CRM already does), `hubspot.update_contact` (one property, high risk, requires confirmation),
  `hubspot.add_note` (a note attached to the contact).
- Observation: HubSpot contact record pages and property edits in the browser extension.
- Verification: re-read the contact and the note through the API.
- A recorded-session test like `test_observed_to_execution` that discovers a Gmail -> HubSpot ->
  Slack workflow and runs it against a fake HubSpot.

### 3d: Slack channel picker
- Channel picker from `conversations.list` (scope `channels:read`) in Settings, replacing the typed
  channel id; warn when the bot is not a member of the channel.
- "Add to Slack" OAuth moves to Phase 5 (needs HTTPS).

### 3e: More catalog actions (all four chosen)
Each with executor, verifier, observation rule and tests:
- `slack.reply_in_thread`: reply to the message a run posted earlier, instead of a new message.
- `sheets.append_row`: add a row to a Google Sheet (needs the Sheets scope on the Google sign-in).
- `gmail.add_label`: label the processed email. Needs the opt-in `gmail.modify` scope; the label is
  the only change it can make (no sending, deleting, archiving or moving).
- `files.save_to_folder`: copy the downloaded attachment to a configured shared folder.

### 3f: CI, docs, live tests
- Live tests (`@pytest.mark.live`) for HubSpot and Slack OAuth against test accounts; mocked
  transports in the normal suite. README integration guide: "Adding an integration".

## Risks

| Risk | Mitigation |
|---|---|
| HubSpot property names differ per account | Settings lists the account's contact properties; the update action stores the chosen internal name |
| Duplicate CRM writes on retry | Unchanged rule: live runs are never retried; side effects -> needs attention |
| History API ids expire | Detected and handled with a bounded fallback search, shown on the trigger |
| Broader Google scopes (Sheets, Gmail modify) | Only requested if those actions are chosen; existing installs keep read-only until reconnected |
| Refactor in 3a breaks something | 3a is behaviour-neutral and must pass the full existing suite before anything else changes |

## Out of scope

Multi-tenant SaaS, a marketplace of integrations, Pub/Sub push for Gmail (optional, later),
Slack "Add to Slack" OAuth (Phase 5, needs HTTPS),
workflow editor (Phase 4), hosting and HTTPS (Phase 5).
