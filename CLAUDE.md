# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

NOVA is a personal AI assistant: a Python agent engine (CLI + local HTTP/WebSocket server) plus a Tauri +
React desktop app. Three interchangeable providers (`claude_code` via the `claude` CLI, `anthropic` API,
local `ollama`). The agent can read/write files, run shell commands (user-approved), search the web, and
inspect the system — all local tools, no cloud backend of NOVA's own.

Full feature description, env vars, and provider setup: see `README.md`.

## Commands

### Python engine (`src/nova/`)

```bash
uv sync                          # install deps (uses uv.lock, Python 3.12 pinned via .python-version)
uv run nova                      # run the CLI
uv run nova serve                # run the local HTTP/WS server (used by the desktop app)
uv run nova setup                # detect location, write it to .env
uv run pytest                    # full test suite
uv run pytest tests/test_files_tool.py::test_creates_a_file   # single test
```

No Python linter/formatter is configured in this repo.

### Desktop app (`desktop/`)

```bash
cd desktop && npm install
npm run tauri dev                # native window (needs Rust + system libs, see README)
npm run engine:dev                # terminal 1: Python engine on 127.0.0.1, browser mode
npm run dev:browser                # terminal 2: Vite dev server, then open http://localhost:1420
npm test                         # vitest, full suite
npx vitest run src/components/AccountScreen.test.tsx   # single test file
npm run lint                     # oxlint
npm run build                    # tsc -b && vite build
npm run engine:build             # freeze the Python engine with PyInstaller -> ../dist/nova-engine/
npm run app:build                # engine:build + tauri build -> src-tauri/target/release/bundle/nsis/*.exe
```

Scripts that set env vars go through `cross-env`: npm runs scripts with cmd.exe on Windows even from Git Bash,
so plain `VAR=value command` fails there.

## Architecture

### Engine (`src/nova/`)

- `core/agent.py` — the agent loop: `Agent.ask()` sends history to the provider, executes any tool calls
  via `ToolExecutor`, loops until the model answers or `max_agent_turns` is hit. Provider- and
  transport-agnostic; the desktop app's confirmation/progress UI hooks in via `AgentObserver`.
- `providers/` — `claude_code.py`, `anthropic_api.py`, `ollama.py`, all implementing `Provider.complete()`.
  `factory.py` picks one from `Settings.provider`. `claude_code.py` shells out to `claude -p` in
  `--output-format stream-json` mode and intercepts NOVA tool calls from the event stream before the CLI's
  own (disabled) tools would reject them; it keeps a Claude Code session per conversation (`--session-id`
  / `--resume`) so only new messages are sent.
- `tools/` — one file per tool family (`files.py`, `shell.py`, `web.py`, `system_info.py`, `disk_usage.py`,
  `documents.py`, `creative.py`). `registry.py` + `catalog.py` expose them to the agent and route
  confirmations (destructive actions ask the user first via `confirmation.py`).
- `security/` — prompt-injection defences. `exposure.py` tracks what the current request read: once outside
  content (web, files, attachments) was read, tools marked `effect="changes"` always need approval (and
  `effect="sends"` too if private data was read), with a warning in the dialog. `injection.py` flags hostile-
  looking content (a warning light, not the protection). When adding a tool, set `effect` / `reads_outside` /
  `reads_private` on its `Tool`. `device/safety.py` checks files before "open" (extension, mark of the web,
  Defender scan).
- `device/machine.py` — describes the user's computer to the model at launch (OS, shell, home, real personal
  folders via Windows known folders, so OneDrive-redirected Desktops work). Never write machine-specific paths
  in `prompts/system.md`: NOVA ships to other people. `run_command` uses PowerShell on native Windows, bash elsewhere.
- `device/` — OS integration: `location.py` (Windows location service → IP geolocation fallback),
  `filesystem.py` / `access.py` / `opener.py` (file explorer, folder-unlock, "open with default app").
  **These have genuine WSL-only code paths** (gated on `is_wsl()` / `platform.system()`) for bridging to
  the Windows host filesystem from inside WSL — e.g. `wslpath`, an `icacls`-via-PowerShell UAC prompt to
  unlock a locked folder, and Windows user-folder detection. On native Windows (no WSL) these paths are
  simply unreachable, which is why `tests/test_folder_access.py`, parts of `tests/test_file_explorer.py`,
  and `tests/test_disk_usage_tool.py`'s cross-mount detection fail when run outside WSL — not bugs, just
  out of scope for that environment.
- `interfaces/` — `cli.py` (terminal), `server.py` (FastAPI: REST for status/accounts/location/files/
  conversations, one WebSocket for chat; token-protected, bound to `127.0.0.1` only — this is what the
  desktop app talks to), `account.py` (`AccountManager`: picks between "everyday Claude Code login"
  (`~/.claude`, `config_dir=None`) and NOVA's own added accounts under `~/.nova/claude-accounts/<email>/`,
  each with an isolated `CLAUDE_CONFIG_DIR`), `history.py` (`ConversationStore`: one JSON file per
  conversation under `~/.nova/conversations/`, no database).

**Windows subprocess encoding**: every `subprocess.run`/`Popen` call with `text=True` must also pass
`encoding="utf-8"`. Without it, Windows decodes CLI/PowerShell output with the system codepage instead of
UTF-8, corrupting accented characters (manifests as `cafÃ©` for `café`). This bit the `claude_code`
provider, `shell.py`, `account.py`, and the `device/` modules once already — keep it in mind in any new
subprocess call.

### Desktop app (`desktop/`)

Tauri 2 + React 19 + Vite. `src-tauri/src/engine.rs` spawns the Python engine on a free local port
with a random token — in debug builds via `uv run nova serve` from the repo; in release builds via the
frozen `resources/engine/nova-engine.exe` (PyInstaller one-folder build from `packaging/build_engine.py`,
added as a resource only by `tauri.bundle.conf.json` so `tauri dev` doesn't need it), with `~/.nova` as
working directory so its `.env` lives there. The frontend talks to it over `http://127.0.0.1:<port>` + WebSocket
(`desktop/src/lib/api.ts`). Top-level views are wired in `App.tsx`: `HomeScreen`, `AccountScreen` (shown
whenever `needs_account` is true), the chat (`ChatScreen` + `useChat.ts`), and the file explorer
(`components/files/`). Conversation list grouping/titles, path helpers, and tool-call labels each have
their own small `lib/*.ts` module with a matching `*.test.ts`.

## Packaging and release status

Done:
- Standalone engine (PyInstaller), bundled into an NSIS installer by `npm run app:build`. If a frozen-engine
  feature breaks at runtime with `ModuleNotFoundError` or a missing data file, add the package to `COLLECT_ALL`
  in `packaging/build_engine.py`. Tested on a Windows 10 PC without Python/uv/Rust: installs and starts.
- Releases (`.github/workflows/release.yml`): pushing a tag `vX.Y.Z` that matches the version in
  `desktop/src-tauri/tauri.conf.json` (keep `desktop/package.json` and `desktop/src-tauri/Cargo.toml` in sync) builds
  the installer on GitHub Actions and creates a **draft** release with `NOVA_X.Y.Z_x64-setup.exe`, its `.sha256`, and
  the same installer as `NOVA-setup.exe`. Publish the draft by hand. v0.1.0 is published (unsigned).
- Website (`site/`, static, French + `en/`): https://nova.sauv-web.fr, hosted on o2switch. `.github/workflows/site.yml`
  uploads it over FTPS on every push to `site/` (secrets `SITE_FTP_SERVER` / `SITE_FTP_USERNAME` /
  `SITE_FTP_PASSWORD`, FTP account restricted to the subdomain folder). The download button points at
  `releases/latest/download/NOVA-setup.exe`, so never drop that stable-name asset from releases. The site makes no
  third-party requests (self-hosted fonts, strict CSP in `site/.htaccess`): keep it that way, the privacy section says so.
  `site/google728c38d6d785ad63.html` is the Google Search Console ownership proof: never delete it.
- Public identity: copyright holder and site signature are "Sauv'Web"; commits use `sauv.web@gmail.com`. The old
  private history (with personal data) lives only in the local branch `sauvegarde/historique-prive` and the private
  repo `l-sauvinet/nova` (remote `ancien-prive`): never push or publish them. Keep tests free of personal data.

Remaining:
1. Code signing: SignPath Foundation application sent on 2026-10-08 (project "NOVA Assistant"), waiting for their
   answer by email. Once accepted: link the repo in SignPath, add their signing step to `release.yml` (API token as a
   GitHub secret), add "Free code signing provided by SignPath.io, certificate by SignPath Foundation" to the site's
   "Code signing policy" section, then ship v0.1.1 signed. Until then, installers trigger Windows SmartScreen.
2. Auto-update (Tauri updater with its own signing key, independent of SignPath), so v0.1.0 users get new versions.
3. 13 Python tests fail on native Windows (WSL-only code paths + 2 others); mark them `skipif` before running
   `pytest` in CI.

Product constraint that stays true regardless of packaging: NOVA's default provider (`claude_code`) needs
each user to have the Claude Code CLI installed and signed in themselves — there's no way around this for
that provider, it's now explained on the account screen (`AccountScreen.tsx`) with a link.
