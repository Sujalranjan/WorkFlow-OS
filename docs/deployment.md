# Deploying WorkFlowOS (one team, one server)

Production runs the same images as development behind [Caddy](https://caddyserver.com), which
gets HTTPS certificates from Let's Encrypt automatically and serves the dashboard and the API on
one domain. Only ports 80 and 443 are published.

```
Internet ──443──▶ Caddy ──▶ web (dashboard)          https://DOMAIN/
                        └─▶ api ──▶ postgres         https://DOMAIN/api, /health, /health/ready
                             worker ──▶ postgres     (jobs, email checks)
                             crm (Demo CRM, internal only)
```

## 1. Server and DNS

- A Linux server with Docker (Compose v2.24+), 2 GB RAM is enough for one team.
- A DNS `A`/`AAAA` record for your domain pointing at the server; ports 80 and 443 open.

## 2. Configure

```bash
git clone https://github.com/Sujalranjan/WorkFlow-OS.git && cd WorkFlow-OS
cp .env.production.example .env
# fill in DOMAIN, ACME_EMAIL, POSTGRES_PASSWORD, WORKFLOWOS_SECRET_KEY (commands in the file)
chmod 600 .env
```

Keep `WORKFLOWOS_SECRET_KEY` somewhere safe outside the server too: it encrypts the saved
integration credentials.

## 3. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api \
  python -m app.cli create-user --email you@example.com --name "Your Name" --role admin
```

Open `https://DOMAIN`, sign in, then connect integrations in **Settings**:

- **Gmail:** create a Google OAuth client of type *Web application* with the redirect URI
  `https://DOMAIN/api/integrations/gmail/callback`.
- **Slack, HubSpot, shared folder, Google Sheets:** see the README's Integrations section.
  A shared folder must be mounted into the `api` and `worker` containers (add a `volumes:` entry
  in an override file).

The database schema is migrated automatically when the API starts.

## 4. Monitoring

- `https://DOMAIN/health` is liveness; `https://DOMAIN/health/ready` returns 503 until the
  database is reachable, the schema is current and a worker is alive. Point an uptime monitor at it.
- **System** page (admins): workers, job queue, jobs that need a person, email triggers.
- **Alerts:** choose an alert channel in *Settings › Slack › Alerts* (or `ALERT_SLACK_CHANNEL`).
- **Prometheus:** set `METRICS_TOKEN`; scrape `http://api:8000/metrics` from inside the Docker
  network (Caddy never serves `/metrics`):

  ```yaml
  scrape_configs:
    - job_name: workflowos
      static_configs: [{ targets: ["api:8000"] }]
      authorization: { credentials: "<METRICS_TOKEN>" }
  ```

  Useful alerts: `workflowos_ready == 0`, `workflowos_workers_alive == 0`,
  `workflowos_jobs{status="needs_attention"} > 0`.
- Logs are JSON on stdout (`docker compose logs -f api worker`), each request with an id.

## 5. Backups

```bash
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml" scripts/backup.sh /var/backups/workflowos
```

Run it daily (cron) and copy the output off the server. Restore with `scripts/restore.sh <dump>
[<key>]`. Test a restore now and then on a spare machine.

## 6. Upgrades

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Back up first. Migrations run on start; jobs in progress finish before the worker stops
(`stop_grace_period`), and a job interrupted after it may have changed an external system is
never repeated automatically (it appears under *Needs a person*).

## Security checklist

- [ ] `.env` is `chmod 600`, never committed; `WORKFLOWOS_SECRET_KEY` backed up separately.
- [ ] Only ports 80/443 reachable from the internet (`docker compose ps` shows no other ports).
- [ ] Gmail stays read-only unless you need labeling or Sheets (Settings › Gmail).
- [ ] Each person has their own account with the lowest role that works; API keys only for the
      desktop agent and browser extension.
- [ ] An uptime check on `/health/ready` and a Slack alert channel are set up.
- [ ] Daily backups copied off the server.
