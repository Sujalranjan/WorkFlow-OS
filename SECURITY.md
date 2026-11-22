# Security

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** button on
this repository (Security tab), not in a public issue. You will get a reply within a week.

## How WorkFlowOS protects data

- **Least privilege:** Gmail is read-only unless an admin opts in to labeling or Google Sheets;
  each extra Google permission is requested only for the feature that needs it. HubSpot, Slack and
  Google credentials are stored encrypted (Fernet) and never returned by the API.
- **People decide:** a workflow (and every edited version) runs only after a person approves it;
  triggered runs are approved one by one; ambiguous lookups pause for a person.
- **Fail closed:** missing setup, permissions or values block a step before anything changes; a
  failed or blocked step stops the run; work that may have changed an external system is never
  retried automatically.
- **Accounts:** Argon2id password hashes, HttpOnly session cookies (Secure behind HTTPS), CSRF
  header on every state-changing request, role checks on every route (unlisted routes are
  admin-only), sign-in rate limiting.
- **HTTP:** security headers and a Content-Security-Policy on the API and dashboard, HSTS behind
  HTTPS, a request size limit, and API docs that can be switched off in production.
- **Observation:** the browser extension and desktop agent send structured events (URLs, action
  types, file names, label names), never email bodies, attachment contents, typed text or
  screenshots.
- **Supply chain:** dependency audits (pip-audit, npm audit) and CodeQL run on every pull request
  and weekly; Dependabot proposes updates.

See [docs/architecture.md](docs/architecture.md) for the full safety model.
