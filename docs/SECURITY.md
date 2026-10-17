# Security and privacy

[Português brasileiro](SECURITY.pt-BR.md)

## Identity

Every account requires an Argon2id password and confirmed TOTP. The random
bootstrap token works only with an empty database. There is no default password,
public registration or setting that disables MFA. Invitations expire after 48
hours and password-reset links after 30 minutes; both are random, single-use
tokens stored as hashes.

Passwords contain 14–256 characters. At most two concurrent Argon operations
bound memory use per process. Persistent throttling checks the source IP before
creating account-name buckets. JSON is limited to 16 KiB before parsing; uploads
have configured size and receive-time limits. Validation errors do not echo
submitted values.

Opaque sessions are stored as hashes. Cookies are HttpOnly, SameSite=Strict and
Secure over HTTPS, and rotate between password, MFA and full access. Pending
sessions cannot access documents or editors. TOTP uses 30-second steps with a
one-step window and transactional replay prevention. The persistent Fernet key
protects TOTP secrets against an isolated database leak, not a complete volume
copy.

Ten random recovery codes are hashed and consumed atomically. Recovery requires
the password and enrollment of a new authenticator. Resetting an established
account's password preserves its authenticator; incomplete enrollment receives a
new secret. Disabling an account, changing its role or recovering access revokes
sessions. Initial MFA confirmation revokes other pending challenges. Mutations
recheck session, role and recent authentication inside the write transaction.

## Portal and editor boundaries

`PUBLIC_ORIGIN`, `EDITOR_ORIGIN` and `DEMO_EDITOR_ORIGIN` must be distinct. The
server checks the complete Host, including the port. The portal origin provides
the interface, account API and Drive; the private editor origin provides only
`/runtime/TICKET/...`. The demo origin provides anonymous demo assets and cannot
call private account or Drive APIs. The middleware does not grant cross-origin
API access.

Public-demo exports use a separate, bounded message protocol for local browser
downloads. The portal accepts bytes only from the active demo frame and exact
demo origin, validates the request shape and size, and creates its own download
URL. It does not accept an API URL or invoke Drive. This avoids iframe Blob
download incompatibilities without relaxing the iframe sandbox or browser
privacy settings. An acknowledgement confirms download initiation, not that a
user has saved the file to disk.

Each private ticket belongs to a full session, one editor and its expiry time.
Revoking the session invalidates the ticket. Served HTML delays upstream modules
until browser-state cleanup and adapter initialization finish. Editor HTML does
not receive a password or CSRF token. Editor asset preparation and its recorded
modifications are described in [licensing](LICENSING.md).

MessageChannel negotiation checks the source window, exact origin and random
nonce. Messages can offer selected content and export bounded bytes, but cannot
choose an API URL or file owner. Cookies, CSRF, ETag and revision/copy decisions
remain in the portal. Reconnecting an open editor requires the same identity.

The iframe uses a sandbox and CSP restricts connections to local resources.
Graphical editors need JavaScript, WebAssembly, inline styles, Blobs and media
features. Upstream editor code remains trusted within the editor origin; this
is not an individual sandbox for arbitrary code or untrusted plugins. CSP is
not a host or browser outbound firewall.

On account changes, the adapter clears Web Storage, IndexedDB, CacheStorage and
OPFS. Browser locks serialize cleanup where supported. Cleanup failure prevents
engine startup; BroadcastChannel closes previous documents in other tabs. Use
separate browser profiles on shared computers.

## Data and operation

Every Drive request checks ownership or sharing. Sharing is internal and
read-only; recipients access the current version, not the owner's private
history. Their exports become their own copies. Downloads use attachment,
octet-stream and nosniff. Blob paths use UUIDs rather than supplied filenames.

Immutable revisions and ETag/If-Match checks protect updates and restores from
concurrent changes. Transactional quotas include revisions, trash and upload
reservations. The current revision cannot be deleted independently. Bounded
audit logs omit document contents, passwords and tokens.

A volume lock is acquired before opening or migrating the database. Backup,
restore and recovery cooperate with it; status and diagnostics do not migrate
the database. Restore checks hashes, references, SQLite integrity, MFA keys and
an empty destination, and clears restored sessions and reservations. The image
runs without root, capabilities or Docker socket access, with a read-only root
filesystem and bounded logs.

The Docker socket, MFA key and data volume grant access to the data. Restrict
them to operators. Backups contain private data and are not encrypted by the
backup format; protect them and test restores in a separate volume.

## Limits

The host operator can read documents: there is no end-to-end encryption. This
release does not provide antivirus, passkeys/WebAuthn, OIDC/LDAP, S3, arbitrary
code isolation per tenant or external security certification. MFA and quotas
cannot prevent an authorized recipient from copying a file. Format fidelity and
universal autosave depend on the upstream editor.

Run browser/Docker acceptance and representative format checks on the actual
host and proxy. Report security issues privately to your deployment maintainer,
preserving documents and secrets.
