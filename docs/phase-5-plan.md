# Phase 5: deploy and monitoring (done)

## 5a Security hardening
- Security headers on every API response (nosniff, no framing, no referrer, strict CSP, `no-store`
  for `/api`), HSTS behind HTTPS, 413 for bodies over `MAX_REQUEST_BYTES`, API docs switchable off.
- Dashboard nginx: CSP allowing only its own scripts and its API (`frontend/nginx.conf.template`).
- Dependencies: `cryptography` 50.0.2 and `pytest` 9.0.3 (pip-audit advisories), npm advisories fixed.
- `.github/workflows/security.yml`: pip-audit, npm audit, CodeQL (security-extended) on every PR,
  push to main and weekly; Dependabot; `SECURITY.md`.

## 5b Monitoring
- Worker heartbeats (`service_heartbeats`, migration 0004).
- `/health/ready`: database, schema at head, a live worker (503 otherwise).
- `/metrics` (Prometheus), off unless `METRICS_TOKEN`, bearer-protected, route-template labels only.
- Admin **System** page: readiness, workers, job queue, jobs needing a person, failed jobs, triggers.
- Slack alerts (Settings > Slack > Alerts): job needs attention, triggered run failed/blocked,
  trigger starts failing (once), optionally runs awaiting approval. No email contents in alerts.

## 5c Production deployment
- `docker-compose.prod.yml` + `deploy/Caddyfile`: Let's Encrypt HTTPS, one origin, only 80/443
  published, `/metrics` and API docs not exposed, required settings enforced, Secure cookies.
- `scripts/backup.sh` / `scripts/restore.sh` (database + encryption key), `docs/deployment.md`
  (setup, monitoring, backups, upgrades, security checklist), `.env.production.example`.
- Checked locally with `DOMAIN=localhost`: HTTP->HTTPS redirect, HSTS/CSP headers, Secure HttpOnly
  cookie, `/metrics` 404 at the edge, readiness ready, metrics inside the network.

## 5d Add to Slack
- The team's Slack app (Client ID/Secret in Settings or `SLACK_CLIENT_ID/SECRET`), OAuth v2 with a
  single-use state that is bound to its provider, HTTPS-only, bot tokens only; reinstalling keeps
  the chosen channel and alert settings.
