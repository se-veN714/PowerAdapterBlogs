# PAdif MCP — local implementation

Remote Streamable HTTP at `/padif/mcp/`, JSON-response mode on Django's existing
WSGI stack. Supported protocol revisions: 2025-03-26, 2025-06-18, 2025-11-25.
No SSE notifications, transport sessions, file uploads or main-publication tool.
Validated against the official Python MCP SDK 1.30.0, including its OAuth provider.

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
| `padif:read` | `list_documents`, `get_workspace`, `get_version`, `compare_versions`, `list_annotations` |
| `padif:version` | `create_branch`, `commit_version` |
| `padif:annotate` | `add_annotation`, `reply_annotation`, `resolve_annotation` |

Only granted tools are listed; the same scopes are enforced on calls. IDs are
positive integers, never booleans; schemas reject unknown arguments. Source lines
are 1-based original Markdown lines, counting empty lines, not visual wraps.
Read lists use offset/limit. Workspace bounds version/comment summaries at 50;
the complete selected head content is returned. Read history by version ID.

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

The portal manages only the signed-in user's article AI+ applications, their
withdrawal/relinquishment, and connections. Its article links open the article
itself. Owner collaboration controls and AI+ approval/direct grants remain at
`/padif/documents/<id>/collaboration/`, in separate human-members and AI+ sections.
Dashboard review grants module eligibility; article owners independently review
each article request. Neither decision creates an OAuth token or enlarges scope.
Request outcomes are terminal; current eligibility/AI+ and historical approval
are displayed separately. Role or eligibility cycles cannot revive old requests.

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
