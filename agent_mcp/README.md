# PAdif MCP — local implementation

Remote Streamable HTTP at `/padif/mcp/`, JSON-response mode on Django's existing
WSGI stack. Supported protocol revisions: 2025-03-26, 2025-06-18, 2025-11-25.
No SSE notifications, transport sessions or main-publication tool. Private Markdown
staging is available through authenticated website selection and controlled chunks.
Validated against the official Python MCP SDK 1.30.0, including its OAuth provider.

## Tool safety and long-document contract

[Tool safety Spec v1.0](TOOL_SAFETY_SPEC.md) and its
[acceptance matrix](TOOL_SAFETY_ACCEPTANCE_MATRIX.md) define the proposed shared
contract for the original ten tools, bounded reads, exact patches and private
Markdown staging uploads. Phase 1 is implemented locally: common live-permission
checks, response budgets, bounded reads and exact patches (originally 13 tools).
[Phase 1 validation](TOOL_SAFETY_PHASE1_VALIDATION.md) separates actual evidence
from pending work. Phase 2 adds isolated diff budgets and complete reply-thread
pagination; see [Phase 2 validation](TOOL_SAFETY_PHASE2_VALIDATION.md).
Phase 3 implements private staging and website selection (19 tools total), with
[upload validation evidence](TOOL_SAFETY_PHASE3_VALIDATION.md). A native WorkBuddy
file adapter remains unsupported; no client credential extraction is permitted.
No deployment is included.

## Connect

1. WorkBuddy and other clients supporting RFC 7591 DCR discover the registration
   endpoint and register automatically. This creates an application identifier,
   not a user authorization or token. No manual client ID setup is needed.
   Clients that require a pre-registered ID remain supported; an administrator
   can register the client's actual callback URI:

   ```powershell
   .\.venv\Scripts\python.exe manage.py register_padif_mcp_client --client-id writing-agent --name "Writing Agent" --redirect-uri "http://127.0.0.1:9919/callback"
   ```

2. Add the configured site's `/padif/mcp/` URL to a client supporting remote MCP,
   OAuth Authorization Code + S256 PKCE, and either dynamic registration or
   pre-registered public client IDs. For pre-registration, configure the same
   client ID and callback URI there. No client secret.
3. Connect from that client. The site's browser login/TOTP policy and explicit
   consent page apply; read is selected by default, writes are opt-in.
4. Manage/revoke connections at `/accounts/security/agents/`.

Dynamic registration accepts public Authorization Code clients only, with S256
enforced at authorization time. Registration accepts 1–4 exact HTTPS callbacks
(loopback HTTP is allowed for desktop clients), at most 16 KB of JSON and 10
requests per client IP per minute. No user token, secret, registration-management
token or RFC 7592 management endpoint is issued. Unrecognized metadata cannot
assign a user, skip consent, or change the client type. Requested scopes must be
within the existing three PAdif scopes; consent remains explicit and defaults to
read-only. Names are self-declared, not proof of publisher identity.
CIMD remains unsupported. Each client must be tested with its real
callback/configuration before claiming compatibility. Never put access or refresh
tokens into a browser URL, manuscript, screenshot, log or repository file.

## OAuth

- Canonical issuer is `PUBLIC_SITE_URL`, validated by `manage.py check`.
- Production requires HTTPS; HTTP only with DEBUG and a localhost/loopback origin.
- Discovery: `/.well-known/oauth-authorization-server` and
  `/.well-known/oauth-protected-resource/padif/mcp/`.
- Authorization, token, revocation: `/accounts/agent/oauth/{authorize,token,revoke}/`.
- Registration discovery and POST: `/accounts/agent/oauth/register/`.
- Only public Authorization Code clients; exact registered redirect matching;
  S256, state, and the canonical MCP `resource` are required on authorization.
- Consent is signed and expires after 10 minutes; the authorization code expires
  after 120 seconds. A client cannot request automatic approval.
- Access tokens expire after 15 minutes. Connections expire 7 days after the
  original grant, including when refreshes continue. Refresh tokens rotate with
  zero grace and family replay detection. Concurrent refresh/code exchanges are
  serialized. Credentials are stored as SHA-256 checksums, not recoverable tokens.
- OAuth MCP tokens and legacy device API tokens are deliberately separate
  audiences. They cannot be interchanged. Existing device routes remain intact.
- Account deactivation, lost PAdif capability, expired connection and revocation
  are checked on calls/refreshes. User disconnect invalidates the entire family.
- User disconnect, authorization, writes, replay and admin revocation use the
  existing audit outbox; bodies and token values are not logged.
- Admin MCP connections page can revoke selected connections/all connections of
  selected users. Existing account-wide legacy Agent revoke also revokes MCP.

PAdif requires the global capability plus an owner-managed document role.
Viewers can read; collaborators can write branches and annotations; only owners
publish main through web confirmation. Anonymous and unshared accounts cannot
list or read documents, including superusers in normal PAdif/MCP routes.
Agent access additionally requires per-document, per-user AI+ opt-in (default off),
PAdif module qualification and OAuth scopes. Role changes/removal and qualification
revocation disable AI+; reapproval never restores it automatically.

## Tools and write contract

| Scope | Tools |
| --- | --- |
| `padif:read` | `list_documents`, `get_workspace`, `get_version`, `compare_versions`, `list_annotations`, `get_document_outline`, `read_content_chunk` |
| `padif:version` | `create_branch`, `commit_version`, `apply_version_patch`, `begin_markdown_upload`, `append_markdown_chunk`, `get_markdown_upload_status`, `validate_markdown_upload`, `commit_markdown_upload`, `cancel_markdown_upload` |
| `padif:annotate` | `add_annotation`, `reply_annotation`, `resolve_annotation` |

Only granted tools are listed; the same scopes are enforced on calls. IDs are
positive integers, never booleans; schemas reject unknown arguments. Source lines
are 1-based original Markdown lines, counting empty lines, not visual wraps.
Read lists use offset/limit. For long documents first call
`get_workspace(document_id, include_content=false)`: versions/annotation metadata
are capped at 50, branches at 100, with explicit truncation flags and no bodies.
Omitting this optional field retains the legacy full-content request, subject to
the response budget. Read history by version ID.

`get_document_outline` returns paginated ATX/setext headings outside fenced code,
source line numbers and fixed-version metadata/hash. It is a source-navigation
helper, not a complete CommonMark parser. `read_content_chunk` accepts only a
version, annotation, reply or resolution-note ID; never a local path or URL.
Chunks are at most 16 KiB of UTF-8 and may be smaller to fit the wire budget.
Signed cursors expire in one hour and bind the connection, source and SHA-256;
a changed resolution note returns `STALE_CONTENT`. Follow `next_cursor` until null.

`apply_version_patch` requires a non-main branch, current base ID and canonical
SHA-256. Up to 20 edits use 1-based half-open ranges, exact `expected_lines` and
`replacement_lines`; empty arrays support insert/delete. Embedded CR/LF in an
individual line, overlaps, mismatched text/hash or stale heads reject the entire
write. Replacement text is capped at 32 KiB, final content at 2 MiB. Canonical
content removes a leading BOM and converts CRLF/CR to LF, preserving blank lines
and trailing LF. The historical version is never rewritten.

All tool results are bounded to 64 KiB of actual JSON-RPC response bytes,
including text and structuredContent copies. Oversized legacy reads now return
`OUTPUT_TOO_LARGE` with bounded-read guidance; oversized write results roll back
the business write, receipt and audit transaction. New-tool JSON-RPC requests
are capped at 64 KiB; legacy transport retains its 2,300,000-byte ceiling. RPC
string IDs are limited to 128 characters. Invalid Unicode/NUL is rejected without
echoing supplied content. Text containing the literal characters `\\u0000` is valid.

Every call reloads live connection eligibility and intersects stored scopes with
the authenticated token scopes; writes repeat this under the connection lock.
Current article permissions are checked before reading an idempotency receipt.
Neither tool instructions nor these server checks sandbox a client's terminal or
credential files. Client-side isolation requires separate real-client evidence.

### Diff budgets and reply pages

`compare_versions` executes in a private Python subprocess with a 3-second
wall-time target (preflight time is subtracted from the subprocess timeout).
Timeout kills and reaps the child, returning `DIFF_TOO_COMPLEX` with no partial
diff. Process creation/termination can add OS overhead. Preflight caps each source
at 2 MiB, sentence count at 10,000 per side, sentence alignment product at 4 million
and maximum sentence-length product at 4 million. These conservative checks can
reject a large comparison even when its documents are valid. There are at most
two concurrent diff children per web process; a busy process returns retryable
`DIFF_BUSY` without queuing more workers. This is not a cluster-wide quota or an
OS-enforced RSS limit. The website/legacy API comparison and commit-time statistics
keep their existing execution paths; this budget applies to MCP comparisons.

Supply `offset`/`limit` (default 20, maximum 100) to page `diff.ops`; retain the exact
from/to IDs. `total_ops`, global stats/summaries and `next_offset` refer to that
fixed pair. Actual wire size can shorten a page. `ops_complete` describes the
operation list; individual large operations have `text_complete=false` and a typed
`text_ref`, with before/after refs for replacements. These refs identify the **whole
version**, not a falsely precise substring; use source-line hints and chunk reads.
The omitted long inline text/inner details are explicit, never silently truncated.
Omitting pagination retains the old small `{diff: ...}` shape; large full diffs
return `OUTPUT_TOO_LARGE` and pagination guidance. Same-version reads are allowed.

Use `list_annotations(version_id, paginate_replies=true)` for bounded previews,
normally three replies per note. `reply_limit` can select 1–100. Each note carries
`replies_total`, `replies_complete`, `snapshot_max_reply_id`, `next_reply_cursor`.
Resume with **only** version_id, reply_annotation_id, reply_cursor and optional
reply_limit/limit; annotation filters/offset are not continuation arguments.
Replies retain ascending ID order and original author/time. The signed one-hour
cursor binds connection, annotation, version and a maximum reply ID, excluding
later appends; a fresh read starts a new snapshot. Every page rechecks permissions.
No snapshot copy is stored: administrative deletion can remove an entry.

### Private Markdown staging

Default flow: begin a task with document_id, non-main branch, base_version_id and
request_id; give its `file_page_url` to the user. The authenticated user selects a
file there. The browser binds name/size/SHA-256 **before** sending bytes, then sends
16-KiB blocks with normal session/CSRF protection. No OAuth token is exposed to the
browser URL or model. The Agent checks status, validates and commits the upload.
Remote MCP never accepts a local path or reads client credential storage.

The website path is `/accounts/agent/oauth/uploads/<uuid>/`. The six upload tools
require `padif:version`; status is a read-only hint without request_id, while
mutations retain the connection's normal idempotency receipt contract. Controlled
adapters can supply a complete file_name/file_size/file_sha256 manifest at begin
and call append with zero-based chunk_index, strict data_base64 and chunk_sha256.
Without such client capability use the website (`CLIENT_UPLOAD_UNAVAILABLE` is
client guidance, not a server claim to detect WorkBuddy capabilities).

Private bytes live in `MarkdownUploadChunk` PostgreSQL rows, never MEDIA_ROOT or
an arbitrary filesystem path. Tasks have opaque UUIDs and are bound to the user,
original connection, article, branch/base and permission revision snapshots.
Normal token refresh preserves a task; new OAuth connections cannot inherit it.
Permissions, scope, expiry, branch archival and head are rechecked. Reopening a
revoked permission cycle does not restore its staged tasks.

States: awaiting_file → receiving → uploaded → validated → committed; cancellation,
expiry or invalidation are terminal. Manifest binding is immutable. Fixed-size
blocks may arrive out of order; identical duplicates are safe, differing bytes
conflict. Validation verifies actual size/hash, strict UTF-8, nonblank text, no NUL
or disallowed C0/DEL controls and known binary headers. Name checks reject paths,
colon/control/traversal syntax, non-md extensions and more than 120 characters.
MIME is not trusted. Valid HTML/script **text** is permitted and is not executed or
rendered by this upload page. No antivirus or universal safety claim is made.

The raw file SHA-256 and canonical content SHA-256 are separate. Normalization
removes one leading UTF-8 BOM and converts CRLF/CR to LF, preserving blank lines
and final LF. Validation exposes summary/hashes and diff_ref. Compare a staged
source with exactly one of `to_upload_id`/`to_version`; staged comparisons/chunks
also require this connection's version scope and article write operation.
`read_content_chunk(source_kind=upload_markdown, source_id=<uuid>)` reads only a
validated task or its committed immutable version, subject to current permissions.

Limits: 2 MiB/file, 3 active tasks and 8 MiB reserved raw bytes/user, 30-minute
absolute expiry; unknown manifests reserve 2 MiB. Admission is serialized across
connections by a DB lock. Defaults for the whole deployment are 1024 active tasks
and 128 MiB reserved raw bytes (`MCP_UPLOAD_MAX_ACTIVE`, `MCP_UPLOAD_MAX_BYTES`).
These count raw staged bytes, not database/WAL/backups/metadata overhead. Creation
is limited to 10/minute/connection, chunks 60/minute/connection using shared cache.
Do not use a process-local cache for production multi-worker rate guarantees.

Commit reuses the existing version service, changes only the original writing
branch and stores exactly one committed version per task. Different request IDs
still return that task's immutable commit result. Audit, version/head, task state,
receipt and byte purge are one transaction. Invalid/cancelled/expired/committed
task bytes are deleted; history/hashes remain. This is logical DB deletion, not
secure erasure of old PostgreSQL pages or backups.

Run `manage.py cleanup_padif_mcp --dry-run`, then the same command without dry-run
to purge expired/revoked/invalid permission-cycle tasks, independently of clients.
`deploy/systemd/poweradapter-mcp-cleanup.{service,timer}` defines a five-minute scan.
It is not activated by local tests. A future approved production release must
install/enable the units and verify their journal. No production scheduler was
changed in this iteration; the old hourly device-token cleanup remains separate.

Long body/resolution-note/reply fields are explicitly incomplete with typed refs
for `read_content_chunk`; a long selected_text points to its version's source-line
range, not an invented exact selection offset. Pagination may shorten a page or
reduce the preview to one referenced reply to meet the actual 64-KiB wire limit.
Legacy small annotations retain their shape; a legacy thread over 100 replies or
an oversized result fails with guidance rather than returning an incomplete thread.

Every write requires a `request_id` unique within the connection. Retain it on
network retries: successful results are saved atomically with business writes;
reusing it with changed arguments returns `REQUEST_ID_CONFLICT`. Retryable errors
are not saved. Commit also requires an explicit non-main branch and its current
`base_version_id`; stale input returns `STALE_BASE_VERSION` and must be reread and
revised. Direct MCP main commits return `MAIN_REQUIRES_WEB_CONFIRMATION`.
Publish the reviewed branch through the existing website confirmation workflow.

The MCP adapter invokes only allowlisted existing PAdif Agent actions, after
its own OAuth/scope checks, without making loopback HTTP calls or granting a
legacy token. Existing version/branch transaction logic and annotation validation
remain the authority. Receipts and connections are additive tables; no manuscript
or annotation fields are migrated by this feature.

## Validation and maintenance

Run with an isolated local PostgreSQL database/settings, never production:

```powershell
.\.venv\Scripts\python.exe manage.py test agent_mcp.tests padif.tests accounts.tests.test_agent_auth --settings=<local_settings> --noinput
$env:PADIF_MCP_QA_BASE = 'http://127.0.0.1:8772'
$env:PADIF_MCP_QA_PASSWORD = '<disposable local QA account password>'
node agent_mcp/tests/browser_oauth.cjs
```

Browser acceptance requires the `mcp_preview` local account and document titled
`MCP 本地验收`, a pre-registered `padif-local-writing-agent` with callback
`http://127.0.0.1:9919/callback`, Playwright and the project's virtual environment.
Only that fixture is modified, on newly created branches. The official SDK keeps
tokens in memory; temporary authorization callback files and screenshots go to
ignored `.local/browser-qa/`. Main stays unchanged. The report distinguishes an
independently reproduced site-wide MathJax startup error from feature errors.
Set `PADIF_MCP_QA_DCR=1` when running browser acceptance to test the official
client's automatic registration path instead of the pre-registered path.

`manage.py cleanup_padif_mcp --dry-run` previews expiry cleanup. Normal mode
revokes expired credential families, removes their write receipts and expired
codes, and retains connection/audit history. DOT `cleartokens` may then clean old
token rows; do not manually delete live rotating token records, as they are needed
for replay detection. No new production timer has been installed in this local
iteration. Before any future release, run the full archive/manifest workflow;
`agent_mcp` is included in the source manifest roots.


## Two-level access portal (Spec v2.1)

At `/accounts/security/agents/`, apply for the fixed PAdif module (the only
supported option, shown disabled). No free-text module purpose is required;
legacy purposes are retained. New web submissions explicitly include
`module_key=padif`; missing or unsupported keys are rejected.

The portal manages the signed-in user's article AI+ applications, their
withdrawal/relinquishment, and connections. It also shows a creator-only pending
AI+ review queue for their own articles, including their own requests. Approval
and rejection call the existing article decision service, require an explanation
and CSRF-protected POST, and retain all role/module/revision checks. A dashboard
role never grants access to another creator's queue. Article rows link to owner
management; human membership controls and direct article grants remain at
`/padif/documents/<id>/collaboration/`, in separate human-members and AI+ sections.
Dashboard review grants module eligibility; article owners independently review
each article request. Neither decision creates an OAuth token or enlarges scope.
Request outcomes are terminal; current eligibility/AI+ and historical approval
are displayed separately. Role or eligibility cycles cannot revive old requests.

Document headers and collaboration pages distinguish module eligibility from
article consent (unapproved, pending, effective, revoked or unavailable). The
owner-only account picker searches active PAdif-capable users by username or
numeric ID, returns only names/IDs (no email), and retains a native select fallback.
The search endpoint is the document's collaboration URL with `accounts=1&q=...`;
anonymous, nonmember and nonowner requests retain the same document authorization
checks. Names are inserted as text and IDs use a muted style.

Regression: `padif.tests.test_collaboration_presentation`, existing collaboration,
operation and request suites, and `agent_mcp.tests.test_access_web`. The local
`padif/tests/browser_collaboration_access.cjs` uses disposable fixture accounts in
ignored `.local/collaboration-qa.json` on port8775. It covers name/ID search, keyboard
selection, focus, human-role isolation, creator self-approval and three viewports.

Local acceptance uses `browser_two_level_access.cjs` with disposable accounts and
`.local/v2-browser-fixture.json`, plus the existing official SDK OAuth harness.
Browser/SDK evidence is not evidence of a new native WorkBuddy run.

## Article operation grants (Spec v2.2)

Article AI+ stores a user's explicit `allowed_operations`: `padif:read`,
`padif:annotate`, `padif:version`. Nonempty sets require read. Each action checks
human document role, module eligibility, article operation, and the current
client's scope. OAuth scopes do not grant articles or elevate roles. Main remains
owner-confirmed on the web; no MCP authorization-management tool is added.

The management page shows per-article operation summaries and a right drawer.
Users may reduce their own grant immediately (explanation required); an increase
creates an owner-reviewed request and retains current rights. Mixed replacements
atomically reduce first and request the additions. Pending requests snapshot the
grant revision/set as well as role and module cycles; a later downgrade invalidates
the request. Approval cannot silently restore removed rights.

Migration 0008 maps existing enabled grants to their old persisted role limits,
retains source/history, labels inferred legacy requests, and fails on orphaned
active grants rather than inventing membership. Missing/empty operation sets never
mean all operations. Existing token scopes remain unchanged.

Workspace `permissions.allowed_operations` describes the article upper bound;
`effective_operations`, `can_annotate`, and `can_commit_version` describe this
client's actual operations. The legacy `can_write` field remains a coarse human-role
upper bound for compatibility; it is not a server authorization decision and new
clients should use the exact fields.

Run transition, gateway, historical migration and PostgreSQL concurrency tests in
`padif.tests.test_agent_operations*`, plus `agent_mcp.tests.test_operation_web`.
`browser_operation_permissions.cjs` uses disposable local accounts from ignored
`.local/v22-browser-fixture.json` and the `PADIF_V22_QA_PASSWORD` environment variable.
It checks the management/OAuth pages and drawer at 1915×930, 1198×715 and 390×844,
focus, validation failures, immediate reduction and owner approval. It is local
Chromium evidence, not native WorkBuddy proof. No deployment is performed.

### Dashboard eligibility management

`/dashboard/agents/` lets an existing Agent reviewer search registered accounts by
username or exact email, directly open PAdif eligibility, edit the management note,
revoke and reopen eligibility. The account must already be active and have human
PAdif access. Self-management and changes to intrinsic superuser eligibility are
rejected. Every mutation requires POST, CSRF and an explanation; state changes use
the qualification revision to reject stale pages. Notes do not change that cycle.

Direct opening approves a pending real module request if one exists; it never
invents an application. Deletion is logical revocation, preserving audit/history.
Revocation closes article AI+ and invalidates credentials; reopening never restores
those grants or credentials. Article roles, per-article AI+, OAuth consent/scopes
and web-only main publication confirmation remain separate.

Migration 0005 adds optional management metadata without rewriting authorizations.
Regression tests: `test_dashboard_grants`, `test_dashboard_grants_migration`, and
`test_access_review`. `browser_dashboard_grants.cjs` uses disposable local accounts
from ignored `.local/dashboard-grants-qa.json` against port 8774; never use production
credentials. It verifies the CRUD workflow and three viewport widths.
