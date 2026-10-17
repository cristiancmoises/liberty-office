# Liberty Office

Liberty Office 0.2.0-rc.1 is a self-hosted web portal for 13 Artcraft editors, a private file drive, account administration, and mandatory TOTP multi-factor authentication. The interface is in Portuguese. [Documentação em português](README.md).

Visit [office.securityops.co](https://office.securityops.co). The [Brazilian domain](https://office.securityops.com.br) redirects to the primary origin. Editor assets use the separate [editoffice.securityops.co](https://editoffice.securityops.co) origin.

## Run it yourself

Linux with Docker Engine and Compose v2 is required. Copy `.env.example` to `.env`, set distinct HTTPS `PUBLIC_ORIGIN` and `EDITOR_ORIGIN` values when publishing, then run `docker compose up -d --build`. The first build downloads pinned upstream editor archives and checks their sizes and SHA-256 hashes. The portal listens on port 8097 and the editor origin on port 8098; both bind to loopback by default. Place an HTTPS reverse proxy in front of them. See [operations in English](docs/OPERATIONS.en.md) or [Portuguese](docs/OPERATIONS.md) for proxy settings, backup, restore, and upgrades.

The first administrator is created with a one-time bootstrap token stored in the persistent volume. Run `./libertyctl token` on the host to retrieve it privately. There is no default password or public registration. Complete TOTP enrollment and save the recovery codes before using files or editors.

## Data and limits

Keep the database, file blobs, MFA key, and bootstrap state in one persistent volume. Run one application instance and one worker per volume; the database uses SQLite WAL on local storage. Back up and test a restore before upgrades. The server can read stored files: this is not end-to-end encryption. Editor compatibility depends on each upstream web application and the browser; there is no universal autosave or live collaboration guarantee.

The Liberty source is AGPL-3.0-or-later. Upstream editors retain their own licenses and notices under `licenses/upstream/`. The project is not affiliated with Microsoft, Adobe, or Artcraft.
