# Privacy fixes and multi-provider settings

Approved direction: the user reviewed the privacy report and authorized changes in `huiyuanaisherry/deepseek-harness-quant`. Work stays on a `codex/` branch; no production secrets or personal files are read. This is an implementation of the report's recommended DSH-backed settings integration, not a separate credential store.

## Access and privacy

Fix `/dl/` and `/v2/` by decoding and resolving file paths, rejecting absolute paths, backslashes, parent traversal and resolved symlink escape. Only files inside the intended directory are served. Protect private dashboard pages, business APIs and all upstream proxy routes with an application session, including loopback callers. A server-generated random management token lives outside served directories, owner-only, in the DSH home directory. The user retrieves it with an explicit local command; never print it at startup or include it in responses. Login POST exchanges it for an HttpOnly SameSite=Strict cookie; use Secure on HTTPS. Sessions expire, logout revokes them, write requests require exact same origin and a custom header, request bodies are bounded. Rate-limit failed logins. Secrets never enter URLs, browser storage or access logs.

## Provider settings

Add `/settings` to the quant UI. Use DSH rc.6 `llm.providers`, `settings.describe/mutate`, and `credentials.describe/set/unset` internally, preserving DSH's existing credential store. Do not expose an arbitrary management RPC tunnel. Return only allowlisted provider metadata and credential configured/source/writable status. Provider catalog is dynamic. Users can select built-in providers, configure a custom OpenAI completions/Responses or Anthropic endpoint and model, save/replace/remove a Key, and select the default provider/model for new conversations. Show that existing conversations retain their selection; do not silently claim they were switched.

Validate custom HTTPS endpoints, rejecting credentials in URL, query/fragment, localhost/private/link-local/metadata destinations, including resolved IP addresses; disable redirects in our transport. Configuration save is distinct from any model request. Do not offer automatic model discovery or a paid test call in this initial integration: users enter/select model IDs from DSH metadata. Clearly show where the selected provider sends prompts. Preserve fields the form does not own and report configuration/key partial failure separately, with retry-safe operations and optimistic revisions.

## Bridge and pages

Restrict `/api/proxy/*` to the quant bridge routes actually needed by the control page, translating legacy `/quantapi` and `/niuapi` routes to the mounted `/quant` routes where compatible. Never make credentials/settings/general agent management reachable through the legacy tunnel. Replace misleading remote localhost GUI links with the same-origin settings entry where appropriate; leave unsupported chat operations explicit rather than fabricating success. Do not attempt a broad rewrite of DSH internals or the quant research algorithms.

## Verification and deliverable

Use Python stdlib unittest and local fake DSH HTTP endpoints. Cover traversal/symlink escape, unauthenticated reads and writes, exact Origin checks, login/logout/expiry/rate limits, body bounds, catalog shape, provider update preservation, conflicts, partial failures, Key non-disclosure and custom endpoint rejection. No real API keys or billable calls. Review Python and JavaScript changes independently, run UI verification in Chrome against a local fake runtime, push a reviewable branch/PR to the user's fork. Production deployment is a separate step after the code is reviewable.
