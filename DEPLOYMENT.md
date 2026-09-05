# Running SecureSign from zero

Everything runs in Docker; nothing is installed on the machine except Docker itself.
Five minutes of setup, then one build that takes a few minutes the first time.

## 1. Prerequisites

- **Docker** with Compose v2 (`docker compose version` answers) - Docker Desktop on
  Mac/Windows, docker-ce on Linux
- **git**
- **openssl** for generating keys (present on Mac/Linux; on Windows use Git Bash)

## 2. Clone

    git clone https://github.com/raz34900/SecureSign.git securesign
    cd securesign

Everything below runs from the repository root - the compose file reads `.env` from the
directory it sits in.

## 3. Create `.env`

The application refuses to start without its keys, on purpose. Copy the template and
fill in the five empty secrets:

    cp .env.example .env

Every secret in it is generated the same way - run this once per empty line and paste:

    openssl rand -hex 32

The seed and bootstrap passwords at the bottom can stay empty: they only matter for
demo fixtures and unattended installs.

What each is:

| Variable | Role |
|---|---|
| `SS_PII_ENC_KEY` | Encrypts national IDs and wraps every customer's image key. **Losing it loses the data - back it up somewhere that is not this machine.** |
| `SS_PII_INDEX_KEY` | Keys the blind index that makes encrypted IDs searchable |
| `POSTGRES_PASSWORD` | The database password; the URL below assembles itself from it |
| `BACKUP_REPO_PASSPHRASE` | Encrypts the backup repository - a third key, same warning |
| `SS_DATABASE_URL` | Where the API finds PostgreSQL (`db` is the container's name) |

`.env` is gitignored and must stay that way.

## 4. Build and start

    docker compose up -d --build

First run downloads base images and installs PyTorch - expect a few minutes. After
containers start, the API spends **30–60 seconds loading the model** before it answers.

Watch for ready:

    curl -sk https://localhost:8443/api/health

Done when it returns `{"status":"ok", ..., "model_loaded":true}`.

## 5. Create the first account

A fresh installation has no accounts, and creating accounts requires an account. The
bootstrap script creates the operator organisation and its first engineer - the one
account that cannot be made through the application:

    docker compose exec api python scripts/bootstrap.py

It prompts for organisation code (default `SS00`), username (default `eng1`) and a
password, typed twice and never echoed. It refuses to run twice: after this, every
account is made in the panel, where changes are scoped and audited.

## 6. Open it

| URL | What | Who can reach it |
|---|---|---|
| `https://localhost:8443` | The application | the network |
| `https://localhost:8081` | Engineering panel + account provisioning | **this machine only** (host loopback) |

The browser will warn about the certificate: the container generated a self-signed pair
on first start, and a warning is the correct response to a certificate nobody vouched
for. Proceed past it. Production drops a real pair into `deploy/tls/` and needs no other
change.

Sign into the panel at `https://localhost:8081` with the bootstrap account
(`SS00` / `eng1` / your password), create the institutions and their users there. Every
new user gets a generated one-time password, shown exactly once; its owner replaces it
at first sign-in.

Demo fixtures instead of manual setup, if wanted:

    docker compose exec \
      -e SS_SEED_ENGINEER_PASSWORD=... -e SS_SEED_CLERK_PASSWORD=... \
      -e SS_SEED_VERIFIER_PASSWORD=... -e SS_SEED_ORG_ADMIN_PASSWORD=... \
      api python scripts/seed_demo.py

## 7. Public server: standard ports and your domain

Development answers on 8443/8080 so nothing collides on a laptop. A public server wants
443/80 and its real hostname - three lines in `.env`, nothing else:

    PUBLIC_TLS_PORT=443
    PUBLIC_HTTP_PORT=80
    PUBLIC_SERVER_NAME=your.domain.example

Then `docker compose up -d`. One variable feeds both the published port and the
HTTP→HTTPS redirect inside nginx, so they cannot drift apart; `PUBLIC_SERVER_NAME` adds
your domain to the redirect's allow-list - without it, requests carrying your domain in
the Host header get the connection closed instead of redirected (any unknown Host still
does, which is the open-redirect protection working). Unset, everything behaves exactly
as in development.

Put the real certificate pair in `deploy/tls/server.crt` + `server.key` before starting
and the self-signed generator no-ops.

## 8. Prove the backups restore (optional, recommended)

    export BACKUP_REPO_PASSPHRASE=<the value from .env>
    ./scripts/backup_drill.sh

Takes a full backup, simulates a destructive write, restores to the second before it in
a scratch container, and proves an encrypted signature still decrypts from the restored
copy. Ends with `DRILL PASSED`. Run it again whenever you want the same proof.

## If something goes wrong

| Symptom | Cause |
|---|---|
| `required variable POSTGRES_PASSWORD is missing` | Compose was not run from the repository root, or `.env` is missing |
| `port is already allocated` | Something else holds 8443/8080/8081/5432 - stop it, or stop an older copy of this stack |
| `/api/health` unreachable for a minute after start | Normal: the model is loading. If it lasts minutes, `docker compose logs api` |
| API restarts in a loop at first boot | It waits for the database and retries by design; if it never settles, `docker compose logs db` |
| Browser blocks the site entirely | Self-signed certificate - use the "advanced / proceed" path |

## Everyday commands

    docker compose up -d              # start (no rebuild)
    docker compose up -d --build      # start after code changes
    docker compose stop               # stop, keeping all data
    docker compose logs -f api       # follow the API log
    docker compose down               # remove containers, KEEPING data volumes

`docker compose down -v` deletes the database volume. There is no undo. The backup
repository is not touched: it lives on the host at `deploy/backups`, bind-mounted into
the db container, and is removed only by deleting that directory yourself.

After a deploy that changes image preparation (anything in
`packages/signature_core/cleanup.py`, most of all `pad_for_rotation`), rebuild every
stored reference embedding, or references are compared under a preparation they were
never embedded with:

    docker compose exec api python scripts/reembed_references.py
