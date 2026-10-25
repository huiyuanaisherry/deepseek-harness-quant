# Privacy and provider settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified file disclosure and add protected, DSH-backed multi-provider Key configuration to the user's fork.

**Architecture:** Python Handler delegates security and DSH management to focused modules. Browser uses a small same-origin form, DSH remains the only provider/key persistence owner. Auth applies to all private pages and APIs; public login is self-contained.

**Tech Stack:** Python 3.10+, stdlib HTTP/unittest, existing PyYAML, vanilla JS/HTML/CSS, DSH 0.1.0-rc.6.

## Global Constraints

- User fork `huiyuanaisherry/deepseek-harness-quant`, branch `codex/privacy-provider-settings`.
- No production secrets, histories or personal files read. No paid API requests.
- Dynamic provider data comes from DSH; no second credential store.
- Preserve current strategy behavior and unrelated user changes.
- No automatic model discovery in this increment; configuration save itself makes no provider requests.
- Management writes require an authenticated session, exact Origin and `X-Quant-Request: 1`.
- Native DSH RPC request/response envelope must be verified against installed public package code.

### Task 1: Protected server and DSH configuration service

**Files:** create `deck/web_security.py`, `deck/model_settings.py`, `tests/test_web_security.py`, `tests/test_model_settings.py`, `tests/test_deck_security.py`; modify `deck/deck_server.py`, `.gitignore`; create config examples if adding variable settings.

**Interfaces:** expose same-origin `POST /api/auth/login` with `{token}`, `POST /api/auth/logout`, and `GET /api/auth/status`; protect every other API and private page. `GET /login` is self-contained. `GET /api/model-settings` returns `{ok:true,providers:[{id,name,settingsNs,settingsPath,models,profile,credential}],revision,defaultRevision,defaultModel,protocols}` with projected, secret-free fields. `POST /api/model-settings/provider` accepts `{provider,displayName,api,baseURL,models,apiKey,expectedRevision}`; omitted/empty key preserves existing; `{partial:true,...}` explicitly reports a committed profile with a failed credential write. `POST /api/model-settings/key/remove` accepts `{provider}` and resolves its reference server-side; `POST /api/model-settings/default` accepts `{provider,model,expectedRevision}`. Errors have `{ok:false,error:<safe message>,code:<stable code>}`.

- [ ] Write stdlib tests with a temporary repo tree and fake upstream HTTP server. First test real Handler rejects `/dl//<fixture absolute path>` and `/v2//<fixture absolute path>` after authentication and cannot disclose fixture content. Add traversal, encoded paths and symlink cases.
- [ ] Run `python3 -m unittest discover -s tests -v` before implementation and record expected failures for missing auth/provider behavior and unsafe paths.
- [ ] Implement resolved path containment, session auth and bounded JSON handling. Public login uses `fetch('/api/auth/login', {method:'POST',headers:{'Content-Type':'application/json','X-Quant-Request':'1'},body:JSON.stringify({token})})`; success sets an opaque session cookie and navigates to `/`.
- [ ] Implement DSH client and provider service, verifying RPC envelope from public rc.6 code. Example fake provider catalog includes `settingsNs:'llm-pi-ai'`, `settingsPath:['providers','mock']`, `models:[{id:'mock-model'}]`; secrets returned by fake settings must be projected away. Use injectable transport for deterministic failure/conflict tests.
- [ ] Bound upstream calls to loopback; disable redirects; only project safe response fields. Custom endpoint validation rejects all non-global DNS answers and enforces HTTPS without userinfo/query/fragment. Persist configuration through native RPCs, preserve unowned profile fields.
- [ ] Limit old proxy to compatible quant routes, update mappings, and make unsupported routes explicit. Any upstream failure returns a safe error without forwarding body/token details.
- [ ] Run all relevant unittest cases, syntax checks, then commit Task 1 files only.

### Task 2: Multi-provider page and usage documentation

**Files:** create `ui_v2/pages/settings.html`, `ui_v2/assets/model-settings.js`; modify `ui_v2/pages/control.html`, `ui_v2/components/sidebar.js`, relevant menu config/backend API and README/docs. Parent Task 1 routes `/settings` to the page.

**Interfaces:** consume the exact JSON contracts above. The UI uses dynamic providers/protocols/models; custom provider is a form option rather than a hardcoded vendor. Key input is `type=password`, `autocomplete=new-password`, never populated from server. Use DOM textContent/value for upstream data; never insert provider names, endpoints or errors through innerHTML.

- [ ] Add browser-independent JS tests for response-to-form behavior where useful, and an HTTP fixture server wiring Task 1 to fake DSH. Run tests to show missing settings behavior.
- [ ] Build page in existing visual language with dynamic provider selector, model selector/input, display name, protocol, endpoint, Key field, configured/source/writable status, save/remove/default actions, logout and unambiguous status messages. Blank key preserves existing. Show clear input-after-save behavior and partial-save retry messaging.
- [ ] Use `fetch` with `credentials:'same-origin'` and write header `X-Quant-Request: 1`. A 401 sends the browser to `/login`. Load errors stay visible and do not imply success.
- [ ] Add configuration entry through dynamic navigation metadata (respect repository AGENTS.md); replace localhost GUI links in control page with working same-origin settings links without claiming a full DSH GUI.
- [ ] Document how the user obtains the generated admin token locally, how to configure native vendors and compatible endpoints, how Key removal differs from provider removal, how defaults affect new sessions, and the precise privacy limitations from the audit.
- [ ] Run unit checks and Chrome UI verification with fake Key/provider: login, save, select default, reload, remove key; screenshot the result without secret values. Commit Task 2 files only.

### Task 3: Independent review and fork delivery

**Files:** all branch changes; update audit with remediation status without deleting historical findings.

- [ ] Run `python3 -m unittest discover -s tests -v`, compile changed Python files, `node --check` changed JS, `git diff --check`.
- [ ] Ask Python/security and JavaScript reviewers to inspect actual diffs and specs, fix Critical/Important findings with regression checks, repeat review until clear.
- [ ] Verify no admin token, Key, machine-specific deployment config or sensitive test artifact is tracked. Compare source against approved spec.
- [ ] Push `codex/privacy-provider-settings` to origin. Create a reviewable PR if authentication permits and attach it to the chat; otherwise report exact push/PR blocker without claiming publication.
- [ ] Report source privacy findings, verified behavior, test results, fork/PR link and production deployment status. Do not modify the live server as part of fork-only editing.
