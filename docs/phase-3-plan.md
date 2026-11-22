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

### 3a: Integration framework (done, no behaviour change)
- `app/integrations/` with `base.py` (`Integration`, `CatalogAction`, `CatalogParameter`,
  `ClassifiedAction`, URL helpers) and one module per tool: `gmail.py`, `demo_crm.py`, `slack.py`.
  Each declares its actions, classifiers, executor and verifier factories, and a status check.
- `action_catalog.py` keeps its public API but assembles the catalog and classification from
  `INTEGRATIONS`; executor and verifier registries and `/api/status` iterate over it.
  `/api/status` also returns the integration list, and the Overview page renders it, so new tools
  appear without frontend changes.
- Behaviour-neutral, verified by a before/after snapshot: the same 5 actions and identical
  classification of 75 sample events, with the existing suite passing unchanged.
- `tests/backend/test_integrations_framework.py` enforces the rules for every integration:
  namespaced action ids, executor provided and declaring the action, registry membership,
  classifiers that only return their own actions and never overlap, and a broken status check
  that doesn't hide the others.

### 3b: Gmail incremental sync (done, fixes the missed-email bug)
- Each trigger stores its sync position (`history_id`, `synced_until`) in its record, so no
  migration was needed. A poll first asks `users.history.list` whether any message was added
  since `history_id`, and stops there if not (no search).
- Otherwise it lists the ids of every match for `(<query>) after:<synced_until - 10 min>` (never
  earlier than the trigger's start) across all pages, skips ids already in the run ledger, and
  queues up to 50 new runs oldest first. The sync position only moves forward once nothing is left
  behind, so a backlog is worked through over the following polls.
- An expired history id falls back to a full search since the last sync, and a note on the trigger
  says so. A Gmail failure mid-poll leaves the position unchanged; the next poll retries.
- New read-only client methods: `current_history_id`, `messages_added_since`, `list_message_ids`.
- Tests: 120 emails arriving at once are all queued exactly once and in order; no search runs
  when nothing changed; expired history; failure mid-poll; paging in the client
  (`test_gmail_sync.py`). The dashboard shows the poll note ("12 more emails will be queued...").

### 3c: HubSpot (done)
- Settings: paste a HubSpot **service key** (legacy private apps can no longer be created since
  2026-10-26; an existing private-app token still works). Saving checks it against the contacts API
  and records the account id; the key is encrypted and never shown again.
- Settings also picks which contact property `hubspot.update_contact` writes, and an optional default
  value (validated against the property's options). Until a property is chosen those steps are
  BLOCKED (`NOT_CONFIGURED`), never guessed.
- Catalog actions: `hubspot.find_contact` (low; exact email match, a record id, or text search;
  none or several matches pause for a person with the same Inbox picker as the Demo CRM),
  `hubspot.update_contact` (high, requires confirmation), `hubspot.add_note` (medium; note
  associated with the contact, type 202).
- Errors: 401 -> BLOCKED `AUTHENTICATION_REQUIRED`, 403 -> BLOCKED `MISSING_SCOPE`, 429 fails the step
  (fail closed, run again later). Dry runs make no HubSpot calls.
- Observation (best effort, HubSpot does not document its UI): contact record pages and
  contacts-list searches (`app.hubspot.com`, `app-eu1.hubspot.com`) in the extension, plus a content
  script that reports "note saved" / "property X saved" without reading note text or values.
- Verification: re-read the property and the note (body and association) through the API. The
  verification engine now accepts any executor declared in the action catalog instead of a
  hard-coded list.
- `tests/backend/test_hubspot.py`: fake HubSpot API (httpx MockTransport); client, executor,
  verifier, classifiers, Settings, and a recorded Gmail -> HubSpot -> Slack routine discovered and
  run end to end.

### 3d: Slack channel picker (done)
- Settings: paste the bot token, **Check token** lists channels (`conversations.list`, bot's
  channels first, archived ones left out) and you pick one. Public channels need `channels:read`;
  private ones need `groups:read` and are skipped with a note without it. A token with neither
  falls back to typing the channel id.
- Saving checks the channel (`conversations.info`): an unknown id is rejected; membership is
  recorded, and Settings warns while the bot is not in the channel (bots can only post where they
  were invited). Without `channels:read` membership is shown as unknown.
- **Change channel** reuses the saved token (it is never sent back to the browser). The channel
  list is a POST so a token being set up never appears in a URL.
- Fix found on the way: `SlackApiClient` closed an injected HTTP client after its first request.
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
