# Liberty Office operations

[Português brasileiro](OPERATIONS.pt-BR.md)

The hosted portal is [office.securityops.co](https://office.securityops.co), with
an anonymous [demo](https://office.securityops.co/demo).
[office.securityops.com.br](https://office.securityops.com.br) redirects to it.
Private editors use `https://editoffice.securityops.co`; demo editors use
`https://demo-editoffice.securityops.co`. Set `PUBLIC_ORIGIN`, `EDITOR_ORIGIN`
and `DEMO_EDITOR_ORIGIN` to exact, distinct HTTPS origins without trailing
slashes. Preserve the original Host header through every proxy. The application
does not trust `X-Forwarded-*` as proof of identity. Users behind one proxy may
share its IP throttle.

For a self-hosted instance, copy `.env.example` to `.env`, set all three origins,
and run `docker compose up -d --build`. Host ports 8097/8098/8099 bind to
loopback by default. A proxy on another host needs a scoped LAN binding or a
shared Docker network. Set the private upload body limit to match
`MAX_UPLOAD_BYTES` and allow up to 360 seconds for large transfers. Slow uploads
expire after five minutes. Never expose the Docker socket to the application.

With Nginx Proxy Manager on the existing `npm-bridge` Docker network:

```sh
docker compose -f compose.yaml -f deploy/compose.npm.yaml up -d --build
```

Create three TLS Proxy Hosts forwarding to `http://liberty-office:8097`, each
preserving its original Host; restrict the demo editor host to GET/HEAD and a
small body limit. Set `NPM_NETWORK` for another existing network. When using
overrides, retain the same `COMPOSE_FILE` for every launcher command, including
status, backup and recovery.

## Source build and editor integrity

Source builds currently require Linux x86-64. The default Docker build compiles
WordCraft with FIFO-save/focus fixes, FigCraft with browser file-I/O fixes and
GridCraft with initial cell-input fixes from their pinned Rust sources, then
verifies the output against `wordcraft-build.lock.json`, `figcraft-build.lock.json`
and `gridcraft-build.lock.json`. The other editors use
verified upstream bundles and the documented data-only branding preparation.
Rust, wasm-bindgen, source archives and craft-fonts are pinned in
`scripts/build_wordcraft_web.sh`, `scripts/build_figcraft_web.sh` and
`scripts/build_gridcraft_web.sh`; Cargo uses `--locked` and one build
job. Reserve additional build time, memory and disk for dependencies and build
caches. The recipe refuses to start or finish below 5 GiB free; this is a
storage floor, not a claim that 5 GiB is sufficient for the whole build.
The Docker stages serialize these source builds, including under BuildKit.
The recipes do not impose a container memory/CPU limit themselves; configure
those limits on your build host. The deployment was compiled in a separate
bounded builder, not in the running application container.

No server GPU is required. WordCraft's native UI qualification uses pinned CPU
Vulkan packages. Runtime images contain prepared assets, not the Rust toolchain,
and do not fetch editor code on startup. A trusted local bundle image with `/out`
may be supplied through the `WORDCRAFT_BUNDLE_IMAGE`, `FIGCRAFT_BUNDLE_IMAGE` or
`GRIDCRAFT_BUNDLE_IMAGE` build argument to reuse the corresponding already-tested
build. Each image must include a shell for the conditional build stage.
Exact compiled-file and current patch/recipe
hash checks still apply; an arbitrary or stale bundle is rejected. Preserve
original licenses and source-build records when distributing prepared assets.

## Public demonstration

`/demo` is anonymous and explicitly labelled. Set `DEMO_EDITOR_ORIGIN` to a third,
distinct HTTPS origin (the hosted instance uses `https://demo-editoffice.securityops.co`).
Proxy port 8099 to that host, preserve Host, and allow only GET/HEAD with a small
request-body limit. Never point the demo origin at the private editor origin.
Demo editors cannot upload documents or invoke the private Drive bridge. Only
the qualified browser-local formats listed in the README can be imported. Their
storage is isolated from the authenticated editor origin. The lightweight text
editor is a compatibility mode, not a DOCX replacement.

The hosted Liberty service runs in its own Proxmox CT154. Preserve its persistent
volume and private runtime configuration when rebuilding the application.

### Public-only account maintenance

`liberty.public_app:create_public_app` is a separate read-only ASGI factory.
Run it with the same three origin settings and verified read-only application,
public-generation and source-offer paths. Do not mount the private data volume
or provide account credentials. It does not create a database, MFA key, session,
bootstrap token or volume lock. Its health response includes `mode: public-only`
and the validated current public generation; this is not an account health check.

The English-first maintenance home supports Brazilian Portuguese and links to
the working demo. Only explicit public GET/HEAD routes are exposed. Account and
save routes on the portal return 503, with no automatic retry or promised
completion time; private-editor routes remain unavailable. Verified immutable
`/public-assets/` GET/HEAD remains available on all three origins, including
current and retained code generations; this does not grant a private runtime.
Demo documents stay
browser-local: download a copy and use Finish and clear. Public delivery does
not queue saves or retain document backups.

Starting this runtime alone does not perform a safe handoff. Qualify routing,
old proxy-worker retirement, normal backend exit and authoritative data
reconciliation before changing a live writer. Never use the ordinary stop-first
backup/recovery wrapper as a blue/green maintenance controller.

### Identity-pinned handoff controller

`scripts/deploy_liberty.py` is dry-run by default:

```sh
python3 scripts/deploy_liberty.py --config /private/handoff.json --journal /private/handoff.jsonl
```

The operator-owned mode 0600 configuration uses schema 1, `run_id`, exact
CT154/old-container/image `identity`, and `commands`. Each `MaintenanceOps`
boundary requires an explicit local executable `argv` array and `timeout`.
Worker retirement, normal writer exit and recovery wait indefinitely (`null`);
other commands have bounded timeouts. Adapters are trusted operator programs,
not user-supplied commands or a network administration API. Their small JSON
receipts must attest actual identities, completion and authoritative storage.
Never put credentials or document contents in arguments or receipts. Dry-run
checks configuration; it does not execute preflight or qualify deployment.

After image/storage/recovery acceptance, `--apply` creates a private, fsynced
phase journal. Existing journals are never replayed. A reload or one 503 probe
does not prove old clients have retired: capture PID/start-time identities and
wait for the actual old worker generation, then the old backend and released
volume lock. Use `docker container stop --time -1 EXACT_ID` on the qualified
Docker 26 CLI; never impose a forced-kill deadline. Interrupting this client does
not cancel a daemon-side stop. Inspect real state before any recovery. Recovery
keeps accounts in maintenance and uses the current authoritative copy, not a
stale initial backup. It never automatically reopens accounts or retries saves.

`deploy/compose.bluegreen.yaml` separates the no-private-volume public service
from the explicitly enabled `accounts` candidate profile. It requires a
qualified image and existing verified data path; candidate automatic restart
is disabled. It does not migrate data or authorize two writers. Never stop the
private writer through Compose during this handoff. Render
`deploy/nginx.liberty-maintenance.conf` with `scripts.liberty_proxy`, back up
the exact Liberty blocks, run `nginx -t` and gracefully reload. Preserve shared
TLS, aliases, other sites and proxy trust. The template disables upstream retries
and body buffering, while retaining public-code delivery during account 503s.

The opt-in `tests/integration/test_maintenance_handoff.py` needs an explicitly
prepared disposable remote fixture. It exercises the exact previous application
image and matching nginx 1.26.3 libraries, HTTP/1.1 keepalive/HTTP/2 retirement, an
admitted long upload, disconnected-but-running mutation, real process/lock exit
and continuous public/demo responses. Ports are loopback-only; all data is
synthetic. The common unit suite skips this infrastructure test; a skip is not
qualification. Rehearsal does not promise a production maintenance duration.

## Administrator setup

Operator commands use English by default, independently of the host's `LANG`.
For Brazilian Portuguese, use `LIBERTY_CLI_LANGUAGE=pt-BR ./libertyctl token`
or `LIBERTY_CLI_LANGUAGE=pt-BR python -m liberty.cli --help`. Any other value
selects English. `libertyctl` forwards this choice to each Python command with
Compose's per-command `-e`; it does not write it into `.env` or change the
running service. For direct Compose use, pass
`docker compose exec -T -e LIBERTY_CLI_LANGUAGE=pt-BR office python -m liberty.cli --help`.
Only application-owned messages are translated. Tokens, URLs, paths, JSON status
and binary backup stdout are unchanged; diagnostics from Docker, argparse and
other dependencies may use their own language.

Run `./libertyctl token` on the host and use the one-time token in the portal. Store it privately; do not paste it into logs or tickets. There is no default password. Complete TOTP enrollment and save the recovery codes. Accounts created later receive one-time invitations from an administrator.

## Persistent data and backups

The Docker volume `liberty_office_data` contains the SQLite database, file blobs, MFA encryption key, and bootstrap state. Keep one worker and one application instance per volume. Never point two instances at the same database. The SQLite WAL database needs a local filesystem.

For a consistent backup, create a protected directory outside the volume and run `./libertyctl backup /private/path/liberty-backup.tar.gz`. The launcher stops and restarts the service around the snapshot. Copy the resulting archive to independent protected storage. It contains document content, password hashes, and the MFA key; it is not encrypted by the application.

To rehearse a restore, keep the original volume and use a new empty destination:

```sh
docker compose stop office
docker volume create liberty_office_restored
docker run --rm -i --user 10001:10001 --mount source=liberty_office_restored,target=/data liberty-office:0.2.0-rc.1 python -m liberty.cli restore - /data < liberty-office-backup.tar.gz
```

The restore checks hashes, blob references, SQLite and MFA keys, rejects a
nonempty destination and clears old sessions/reservations. The new volume must
be writable by UID/GID 10001; reserve space for temporary extraction. Validate
login, MFA and document downloads before switching `LIBERTY_VOLUME_NAME` to
the restored volume. Keep the original copy. [Portuguese commands and notes](OPERATIONS.pt-BR.md)
are also available.

For a bind mount, prepare an empty directory owned by UID/GID 10001, set
`LIBERTY_DATA_PATH` and include `deploy/compose.storage.yaml`. This override does
not migrate data. Keep the MFA key with the database; losing it prevents
decryption of existing TOTP secrets. Never place the data directory in a webroot.

## Checks and recovery

Run `./libertyctl status` for read-only status and `./libertyctl verify` for installed editor hashes, database, MFA key, and disk checks. A passing check does not replace browser testing. Monitor health at `/healthz` on the portal and editor origins. Test backups regularly, including a restored document.

For a lost authenticator, an operator can run `./libertyctl recover USER` offline; the user still needs the password and must enroll a new authenticator. `./libertyctl password-reset USER` issues a one-time password reset link and still requires MFA. Treat both outputs as secrets. Before upgrading, take a backup and keep the old image and volume. A database migrated by a newer version must not be opened by an older image; restore the old backup to a new volume for rollback.

The launcher restarts the service even if recovery fails. `status` is read-only;
`doctor --deep` checks integrity and does not qualify production compatibility.
Upgrading the original preview creates schema-2 tables idempotently while
preserving users, MFA, blobs, revisions and shares. Configure the additional
editor origins before switching, and reopen editors after an upgrade.

Drive quotas include revisions, trash and upload reservations, but not image,
database, logs or backup overhead. Changing the default quota does not change
existing accounts. Revisions have no automatic expiry. Startup releases
interrupted reservations/temp files; operators should not delete blobs manually
while the service runs. Backup/restore retains referenced blobs, eliminating
unreferenced blobs only in the new restored volume.

`MIN_FREE_BYTES` reserves physical disk space after all pending uploads and the
incoming file. Its ordinary default remains 16 MiB (16,777,216 bytes); the
dedicated blue/green deployment defaults to 1 GiB (1,073,741,824 bytes). Only
positive integers up to 2^60 are accepted. This is separate from user/global
quotas and includes other users' pending reservations. Uploads and revision
restores that would cross the floor fail before reserving content; existing
downloads remain available even at full quota or below the free-space floor.

English is the default interface. Select Brazilian Portuguese when needed;
changing the language must preserve current form and editor contents. Keep the
original documents when checking editor formats, and repeat browser acceptance
after changing pinned upstream releases or prepared editor assets.
