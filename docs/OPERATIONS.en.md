# Liberty Office operations

The hosted portal is [office.securityops.co](https://office.securityops.co). [office.securityops.com.br](https://office.securityops.com.br) redirects to it. Editor assets run at [editoffice.securityops.co](https://editoffice.securityops.co), a separate origin. Keep `PUBLIC_ORIGIN` and `EDITOR_ORIGIN` exact, distinct, HTTPS, and without trailing slashes. Preserve the original Host header through every reverse proxy. The application does not trust `X-Forwarded-*` as proof of identity.

For a self-hosted instance, copy `.env.example` to `.env`, set the two origins, and run `docker compose up -d --build`. The default host ports bind to loopback. A proxy on another host needs an explicitly scoped LAN binding or a shared Docker network. Set the proxy body limit above `MAX_UPLOAD_BYTES` and allow up to 360 seconds for large transfers. Never expose the Docker socket to the application.

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

Run `./libertyctl token` on the host and use the one-time token in the portal. Store it privately; do not paste it into logs or tickets. There is no default password. Complete TOTP enrollment and save the recovery codes. Accounts created later receive one-time invitations from an administrator.

## Persistent data and backups

The Docker volume `liberty_office_data` contains the SQLite database, file blobs, MFA encryption key, and bootstrap state. Keep one worker and one application instance per volume. Never point two instances at the same database. The SQLite WAL database needs a local filesystem.

For a consistent backup, create a protected directory outside the volume and run `./libertyctl backup /private/path/liberty-backup.tar.gz`. The launcher stops and restarts the service around the snapshot. Copy the resulting archive to independent protected storage. It contains document content, password hashes, and the MFA key; it is not encrypted by the application.

To rehearse a restore, keep the original volume, create a new empty Docker volume, stop the original service, and run `python -m liberty.cli restore - /data` in the release image with the backup on standard input and the new volume mounted at `/data`. The restore checks checksums and database integrity. Point the service at the restored volume only after validating login, MFA, and a document download. Do not start two copies against one volume. [The Portuguese operations guide](OPERATIONS.md) contains the exact Docker commands.

## Checks and recovery

Run `./libertyctl status` for read-only status and `./libertyctl verify` for installed editor hashes, database, MFA key, and disk checks. A passing check does not replace browser testing. Monitor health at `/healthz` on the portal and editor origins. Test backups regularly, including a restored document.

For a lost authenticator, an operator can run `./libertyctl recover USER` offline; the user still needs the password and must enroll a new authenticator. `./libertyctl password-reset USER` issues a one-time password reset link and still requires MFA. Treat both outputs as secrets. Before upgrading, take a backup and keep the old image and volume. A database migrated by a newer version must not be opened by an older image; restore the old backup to a new volume for rollback.
