# Liberty Office

Liberty Office is a self-hosted web portal with 13 integrated editors, a private file drive, account administration, and mandatory TOTP multi-factor authentication. English is the default interface and documentation language; Brazilian Portuguese is available in the language selector. [Documentação em português](README.pt-BR.md).

Visit [office.securityops.co](https://office.securityops.co) or [try the demo](https://office.securityops.co/demo). The [Brazilian domain](https://office.securityops.com.br) redirects to the primary origin.

![Liberty Office public demo catalog](docs/screenshots/liberty-demo-desktop.png)

## Try it without an account

The public demo processes supported files in your browser without uploading
documents to the server. It runs on an origin separate from private editors
and cannot write to your Drive. Download a copy, then choose **Finish and clear**.
If the browser closes unexpectedly, local demo data may remain until the next
visit or manual removal of the demo site's data. Close older demo tabs before
starting an upgraded session.

Local imports currently support WordCraft TXT, GridCraft CSV/TSV, DeckCraft
TXT/Markdown outlines, and lightweight TXT/Markdown/HTML. These formats have a
**2 MiB input limit** plus decoded-content limits. The global ceilings are
50 MB per file and 10 files/100 MB cumulatively per project; stricter format
limits prevail. Replacing a file does not reset the budget. Other editors
offer their examples or creation tools, but local imports remain blocked until
their parsers have qualified resource limits. See the [acceptance matrix](docs/ACCEPTANCE.md#temporary-demo-candidate).

The lightweight text mode works without WebGL and supports basic writing and formatting. It does not provide full DOCX fidelity. Full graphical editors require working WebGL2 or WebGPU support in the browser. Startup errors are displayed explicitly, with a compatible option when one exists.

In lightweight mode, TXT and Markdown are plain text: visual formatting is not
exported. Use HTML to export basic formatting. Imported HTML is converted to
inert text while preserving line and block boundaries; it is never executed.

<details><summary>Native editing and small-screen layout</summary>

![Native WordCraft editor](docs/screenshots/liberty-word-native.png)

![Liberty lightweight text editor](docs/screenshots/liberty-word-lite.png)

![Public demo with lightweight text editing on a small screen](docs/screenshots/liberty-demo-mobile.png)

</details>

## Run it yourself

Linux with Docker Engine and Compose v2 is required. Copy `.env.example` to `.env`, set three distinct HTTPS origins (`PUBLIC_ORIGIN`, `EDITOR_ORIGIN`, `DEMO_EDITOR_ORIGIN`), then run `docker compose up -d --build`. The first build downloads pinned upstream editor archives and checks their sizes and SHA-256 hashes. The portal, private editors and demo editors use host ports 8097, 8098 and 8099, all bound to loopback by default. Place an HTTPS reverse proxy in front of them. See [operations in English](docs/OPERATIONS.md) or [Portuguese](docs/OPERATIONS.pt-BR.md) for proxy settings, backup, restore, and upgrades.

WordCraft, FigCraft and GridCraft are rebuilt from pinned Rust sources. Their fixes preserve text before immediate saving and after returning from ribbon controls, provide browser file I/O, and retain initial cell input, respectively. The other editors use verified upstream bundles with the documented branding preparation. Source builds require Linux x86-64, additional time and disk space for Rust dependencies, and CPU Vulkan dependencies for WordCraft's headless native UI tests; no server GPU is required. Original file encoders and licenses are preserved; see [the source-build details](docs/LICENSING.md#source-built-editors).

WordCraft light mode avoids native JS/WASM downloads. Full mode downloads a
roughly 17 MiB gzip module, including the upstream font coverage, on its first
use; unchanged public code is cached separately from no-store session HTML.
This does not make every cold native launch faster or certify complex documents.

The first administrator is created with a one-time bootstrap token stored in the persistent volume. Run `./libertyctl token` on the host to retrieve it privately. There is no default password. Complete TOTP enrollment and save the recovery codes before using files or editors.

## Free accounts

Public registration lets anyone create a free account without an invitation.
Choose **Create a free account**, enter your name, username and a password of
14–256 characters, then enroll a TOTP authenticator and save your recovery codes.
MFA is mandatory; an unfinished account cannot open private files or editors.

Each public account starts with **100 MB = 100,000,000 bytes**. Saved files,
revisions, trash and reserved uploads all count toward that quota. Downloads
remain available when it is full; delete unneeded revisions or empty the trash
to make room. Account files persist until deleted and are **not** subject to
demo cleanup. Only unfinished, never-activated public registrations without
files or other protected references may expire after 24 hours; cleanup runs
during later registrations, not at an exact deletion deadline.

For self-hosting, `PUBLIC_SIGNUP_ENABLED` defaults to `false` for upgrade
compatibility. After operator MFA setup and storage/proxy qualification, set it
to `true` to open registration. `PUBLIC_SIGNUP_QUOTA_BYTES=100000000` is separate
from `DEFAULT_QUOTA_BYTES`, which applies to administrator-created accounts.
The default abuse bounds are 5 signup attempts per source and 20 successful
registrations globally per hour, with 400 public-account slots. These are
capacity safeguards, not an invitation or payment requirement. Change the
documented `SIGNUP_*` settings only to fit verified host capacity. Leave
`TRUSTED_PROXY_CIDRS` empty unless exact trusted proxy peers have been verified;
never trust arbitrary forwarding headers. See [.env.example](.env.example) and
the [security model](docs/SECURITY.md).

## Data and limits

Keep the database, file blobs, MFA key, and bootstrap state in one persistent volume. Run one application instance and one worker per volume; the database uses SQLite WAL on local storage. Back up and test a restore before upgrades. The server can read stored files: this is not end-to-end encryption. Editor compatibility depends on each upstream web application and the browser; there is no universal autosave or live collaboration guarantee.

The Liberty source is AGPL-3.0-or-later and is offered at `/source.zip`. Upstream editors retain their own licenses and notices under `licenses/upstream/`; see [licensing and integration conditions](docs/LICENSING.md). The project is not affiliated with Microsoft, Adobe, or Artcraft.

## Development and validation

Source integrity is recorded with SecOps CodeMark. See [verification instructions](docs/INTEGRITY.md); private signing keys are never distributed.

Use Python 3.12+, install `requirements-dev.txt` with `pip install --require-hashes`, and run `python -m pytest -q`. JavaScript tests run with `npm ci` and `npm test`. Browser acceptance uses isolated synthetic data; see [acceptance criteria](docs/ACCEPTANCE.md). The release remains a candidate: verify the formats and editors you depend on before using important files.
