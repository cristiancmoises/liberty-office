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
FigCraft with browser file-I/O fixes and GridCraft with initial cell-input fixes
from their pinned Rust sources, then verifies the output against
`figcraft-build.lock.json` and `gridcraft-build.lock.json`. The other editors use
verified upstream bundles and the documented data-only branding preparation.
Rust, wasm-bindgen, source archives and craft-fonts are pinned in
`scripts/build_figcraft_web.sh` and `scripts/build_gridcraft_web.sh`; Cargo uses `--locked` and one build
job. Reserve additional build time, memory and disk for dependencies and build
caches. The recipe refuses to start or finish below 5 GiB free; this is a
storage floor, not a claim that 5 GiB is sufficient for the whole build.
The Docker stages serialize these source builds, including under BuildKit.
The recipes do not impose a container memory/CPU limit themselves; configure
those limits on your build host. The deployment was compiled in a separate
bounded builder, not in the running application container.

No server GPU is required. Runtime images contain prepared assets, not the Rust
toolchain, and do not fetch editor code on startup. A trusted local bundle image
with `/out` may be supplied through the `FIGCRAFT_BUNDLE_IMAGE` or
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
Demo editors cannot import files or invoke the private Drive bridge. Their
storage is isolated from the authenticated editor origin. The lightweight text
editor is a compatibility mode, not a DOCX replacement.

The hosted Liberty service runs in its own Proxmox CT154. Preserve its persistent
volume and private runtime configuration when rebuilding the application.

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

English is the default interface. Select Brazilian Portuguese when needed;
changing the language must preserve current form and editor contents. Keep the
original documents when checking editor formats, and repeat browser acceptance
after changing pinned upstream releases or prepared editor assets.
