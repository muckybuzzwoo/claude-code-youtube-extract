# Install-dependency helper

Shared install flow used by SKILL.md Steps 0.3.b (yt-dlp missing) and 0.5 (ffmpeg missing). The main skill file references this helper and only loads it when a dependency actually needs to be installed — on the happy path (all deps already present) this file is never read.

## Inputs

- `dep_name` — display name (e.g. `"yt-dlp"` or `"ffmpeg"`)
- `options` — ordered list of `{label, command}` pairs from the SKILL.md Step 0.2 matrix for the detected OS. `label` is the short user-facing string (e.g. `"winget"`). `command` is the full non-interactive Bash line to execute.
- `doc_url` — official-docs link for manual install instructions
- `on_decline` — `"abort"` (yt-dlp) or `"skip_screenshots"` (ffmpeg)
- `verify_cmd` — command that must exit 0 after a successful install

## Step A0 — Pre-flight checks (package manager availability)

Before asking the user anything, verify that the install command in `options` can actually run. If it cannot, asking the user to confirm an install that will fail 127 with "command not found" is worse than useless — it wastes a prompt and then produces a Step F error message that tells the user to run the same failing command manually.

**macOS Homebrew availability.** When running on macOS AND every entry in `options` uses `brew`: probe `command -v brew`. If brew is NOT installed, skip Step A entirely and emit this message:

```
[dep_name] requires Homebrew to install on macOS, but Homebrew is not present on this system.

Install Homebrew first by following the instructions at https://brew.sh (a single curl command), then re-run /yt-extract.
```

In practice this triggers only for ffmpeg — yt-dlp on macOS has both `brew` and `pip3` options in the Step 0.2 matrix, so the probe short-circuits to Step A (which offers pip3 as a valid alternative).

If `on_decline == "abort"`: abort the skill. If `on_decline == "skip_screenshots"` (ffmpeg): set `skip_screenshots = true` and return to the caller (no abort).

**Linux ffmpeg sudo availability.** When running on Linux AND the dep is ffmpeg AND the detected command uses `sudo`: probe `sudo -n true 2>/dev/null`. If that fails (no active sudo session, no `NOPASSWD`), skip Step A entirely and emit this message:

```
ffmpeg is not installed, and installing it on Linux requires sudo.

I cannot run `sudo` from here without blocking on the password prompt. Please install ffmpeg manually in your own terminal:

  - sudo apt install -y ffmpeg    (Debian/Ubuntu)
  - sudo dnf install -y ffmpeg    (Fedora/RHEL)

Then re-run /yt-extract.

Docs: https://ffmpeg.org/download.html
```

Set `skip_screenshots = true` and return to the caller. The user is already informed; no second prompt needed.

For all other cases, continue to Step A below.

## Step A — Ask the user

If `options.length == 1`:
```
AskUserQuestion
  question: "[dep_name] is not installed. Install with `[options[0].label]` (`[options[0].command]`)?"
  options:
    - "Yes, install it"
    - "No"
```

If `options.length > 1`:
```
AskUserQuestion
  question: "[dep_name] is not installed. Which install method should I use?"
  options:
    - one option per entry in `options` — label = `options[i].label`; description = `"Runs: [options[i].command]"`
    - "No, do not install"
```

## Step B — On decline

- If `on_decline == "abort"`:
  ```
  [dep_name] is required but was not installed.

  Install it manually with one of:
    - [options[0].command]
    - [options[1].command]   (if present)

  Then re-run /yt-extract.

  Docs: [doc_url]
  ```
  **Abort the skill.**

- If `on_decline == "skip_screenshots"`: set `skip_screenshots = true` and return to the caller (no abort).

## Step C — On accept: run the chosen install command

Execute `options[chosen_index].command` via Bash exactly as written (the command already contains all non-interactive flags). Capture exit code and stderr.

**Winget "already installed" special case:** If the command is a `winget` command and the exit code is `43` (package already installed, no upgrade available), treat this as exit code `0` — the package is present on the system. Proceed to Step D to verify PATH availability.

## Step D — Verify

Run `verify_cmd`. If it succeeds (exit 0), the install worked — return success to the caller.

**Windows post-install PATH-recovery fallback.** If `verify_cmd` fails AND `<OS> == Windows`: invoke **Step W (Windows PATH Recovery)** below with the same `dep_name` and `verify_cmd`. Dispatch on Step W's return state:

- `recovered` → return success to the caller (the user already consented to recovery in W.3 — no second prompt).
- `staged_for_restart` → emit Step W's restart message and **abort the skill** regardless of `on_decline` (matches Step E semantics — a half-installed dep is broken). Step E is not reached because Step W has replaced it.
- `not_found` or `copy_failed` → fall through to Step E.

Otherwise (non-Windows, or Step W declined recovery) → proceed to Step E.

## Step E — On verification failure

(Install command returned exit 0, or winget exit 43, but binary still not on PATH.)

```
Installation completed but [dep_name] is still not on PATH.

This usually means the shell hasn't picked up the new PATH entry yet.
Please restart your terminal and re-run /yt-extract.

If the problem persists, install [dep_name] manually:
  - [options[0].command]
  - [options[1].command]   (if present)

Docs: [doc_url]
```

**Abort the skill** regardless of `on_decline` — a half-installed dep is not a "skip screenshots" situation, it's broken.

**Note:** Step E is the expected behavior after a first-time install in two cases:
- **Windows + winget:** winget updates the user PATH but the current shell's PATH is stale.
- **macOS + brew on Apple Silicon:** brew appends `/opt/homebrew/bin` to the shell rc (`.zprofile` / `.zshrc`), but the current Bash session's PATH was captured before that change.

In both cases the install actually succeeded — the message is designed to guide the user through the one-time terminal restart, not to signal a broken install.

## Step F — On install command itself failing (non-zero exit)

```
Failed to install [dep_name].

Command: [chosen command]
Exit code: [N]
Error: [first line of stderr]

Please install [dep_name] manually:
  - [options[0].command]
  - [options[1].command]   (if present)

Docs: [doc_url]
```

**Abort the skill.**

## Step W — Windows PATH Recovery (Windows only)

Recovers from the case where `winget` (or another Windows installer) placed the binary on disk but the Bash tool's PATH does not see it — typically because `%LOCALAPPDATA%\Microsoft\WinGet\Links` is empty or absent from the inherited PATH. Two recovery stages run as one consented chain.

**Inputs:** `dep_name` (`"yt-dlp"` or `"ffmpeg"`), `verify_cmd`. `<PY>` is resolved per SKILL.md Step 0.1 — callers do not pass it explicitly; substitute it inline wherever this routine references it.

**Skip on non-Windows (defense-in-depth).** If `<OS> != Windows`, return `not_found` immediately (no-op). The primary OS guards live at the three call sites (SKILL.md Step 0.3b, Step 0.5, and install-helper.md Step D — each explicitly checks `<OS> == Windows` before invoking Step W). This internal check is intentionally redundant: it protects against a future refactor that adds a fourth call site without the caller-side guard.

**Returns one of:** `recovered` (Stage 1 succeeded, Bash sees the binary) / `staged_for_restart` (Stage 2 succeeded, user must restart Claude Code) / `not_found` (no recovery possible) / `copy_failed` (mechanical copy/registry failure).

> **PowerShell quoting note.** Three quoting layers (Claude Code Bash → cmd.exe wrapper → powershell.exe) make long `-Command` strings fragile. **Preferred primary path:** write the PowerShell script into a temp `.ps1` file (e.g. via Bash heredoc to `$TEMP\yt-extract-recovery-<rand>.ps1`) and execute with `powershell -NoProfile -ExecutionPolicy Bypass -File <tmp>`. Use single-line `-Command` only for trivial calls.

### W.1 — Locate the binary

Run a single PowerShell script that merges User+Machine PATH from the Registry (bypassing the stale Bash PATH), then tries `Get-Command`, with a recursive `Get-ChildItem` fallback under `%LOCALAPPDATA%\Microsoft\WinGet\Packages`. For ffmpeg, search for **both** `ffmpeg.exe` AND `ffprobe.exe` — yt-dlp invokes ffprobe internally for stream selection; copying only ffmpeg.exe yields silent screenshot failures.

```powershell
$ErrorActionPreference = 'SilentlyContinue'
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
$bins = if ('<dep_name>' -eq 'ffmpeg') { @('ffmpeg.exe','ffprobe.exe') } else { @('yt-dlp.exe') }
foreach ($b in $bins) {
    $c = Get-Command $b -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if (-not $c) {
        $c = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter $b -ErrorAction SilentlyContinue |
             Select-Object -First 1 -ExpandProperty FullName
    }
    if ($c) { Write-Output "FOUND:$b=$c" } else { Write-Output "MISSING:$b" }
}
```

Parse the output. If any required bin returns `MISSING:...`, return `not_found`. Otherwise collect the resolved source paths into `<src_paths>` (a list of full Windows paths). When a later step needs to display the binary filenames to the user (W.3 question, W.6 restart message), derive them inline from `<src_paths>` basenames — do not track a separate filenames list. Examples for the same `<src_paths>`: `yt-dlp.exe` (single binary, yt-dlp) or `ffmpeg.exe + ffprobe.exe` (two binaries, ffmpeg).

### W.2 — Resolve a Stage-1 destination on the current Bash PATH

Resolve both candidates with **one** Python invocation (avoids two process launches):

```bash
<PY> -c "import sysconfig, os, sys; print(sysconfig.get_paths()['scripts']); print(os.path.dirname(sys.executable))"
```

Line 1 = pip user-scripts dir. Line 2 = Python install dir (where `python.exe` lives). Try them in that order.

Verify each against the **current** Bash `$PATH`. Bash on Windows (Git Bash) reports PATH in Unix form (`/c/Users/...`); Python returns Windows form (`C:\Users\...`). Convert with `cygpath -u "<winpath>"` before grep'ing the candidate against `$PATH`.

Reject any candidate whose path is below `\WindowsApps\` (MS-Store stub-redirect ACLs reject `Copy-Item`).

Set `<stage1_dest>` to the first verified, non-WindowsApps candidate. If both candidates are rejected, set `<stage1_dest> = null` (Stage 1 unavailable; only Stage 2 is offered in W.3).

### W.3 — Single confirmation gate covering the full recovery chain

Issue **one** `AskUserQuestion`. The `options` are identical in every case; only the recovery-steps clause inside `question` varies based on `<stage1_dest>`. Use this scaffold:

```
question: "[dep_name] is installed but not visible to this shell yet (winget PATH lag).
           Recover by [<RECOVERY_STEPS>]?"
options:
  - "Yes, do the recovery"
  - "No, I'll handle it myself"
```

In every case, `[binaries]` below is the binary filenames extracted as basenames of `<src_paths>` (e.g. `yt-dlp.exe`, or `ffmpeg.exe + ffprobe.exe`).

Substitute `<RECOVERY_STEPS>`:

- **`<stage1_dest> != null` (Stage 1 available):**
  > 1. copying [binaries] to [stage1_dest] (immediate, no restart), and 2. if that doesn't take effect, copying to `%LOCALAPPDATA%\Microsoft\WinGet\Links` AND adding that directory to your user PATH (Registry; Claude Code restart needed). Step 2 also fixes future winget installs.

- **`<stage1_dest> == null` (Stage 1 unavailable, e.g. MS-Store Python):**
  > configuring user PATH directly: copying [binaries] to `%LOCALAPPDATA%\Microsoft\WinGet\Links` AND adding that directory to your user PATH (Registry; Claude Code restart required).

On "No" → return `not_found` (caller falls back to its existing flow). On "Yes" with Stage 1 available → proceed to W.4 (and on Stage-1-verify-fail → automatic fallthrough to W.6, no second prompt). On "Yes" with Stage 1 unavailable → jump directly to W.6.

### W.4 — Stage 1: Copy

Run one PowerShell script that iterates over `<src_paths>` from W.1 (one source for yt-dlp, two for ffmpeg). `<stage1_dest>` is Python's Scripts directory, which exists by definition because Step 0.3a verified Python — no `mkdir` needed.

```powershell
$ErrorActionPreference = 'Stop'
foreach ($src in @(<src_paths>)) {
    Copy-Item -LiteralPath $src -Destination '<stage1_dest>' -Force
}
```

On non-zero exit → return `copy_failed`.

### W.5 — Stage 1: Re-verify

Run `verify_cmd` via Bash. Exit 0 → return `recovered`. Otherwise → fall through to W.6 automatically (the user already consented to the full chain in W.3 — **no second prompt**). Emit a one-line info message: "Stage-1 copy didn't take effect; falling back to persistent PATH recovery as agreed."

### W.6 — Stage 2: WinGet\Links + persistent user-PATH update

Two operations, both via PowerShell:

**(1) Copy bins to `%LOCALAPPDATA%\Microsoft\WinGet\Links\`.** The Links directory may not exist (this is the original bug's root cause); `New-Item -Force` is idempotent and creates it if missing. Iterate over `<src_paths>` from W.1 — substitute the literal array, e.g. `@('C:\Users\...\yt-dlp.exe')` for yt-dlp, or `@('C:\Users\...\ffmpeg.exe','C:\Users\...\ffprobe.exe')` for ffmpeg.

```powershell
$ErrorActionPreference = 'Stop'
$links = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
New-Item -ItemType Directory -Path $links -Force | Out-Null
foreach ($src in @(<src_paths>)) {
    Copy-Item -LiteralPath $src -Destination $links -Force
}
```

**(2) Add `<Links>` to the user PATH (Registry), idempotent via exact-token comparison** (substring match would false-positive on e.g. `WinGet\LinksOld`):

```powershell
$links = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
$userPath = [Environment]::GetEnvironmentVariable('Path','User')
if (($userPath -split ';') -notcontains $links) {
    $newPath = if ($userPath) { $userPath + ';' + $links } else { $links }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Output 'PATH_UPDATED'
} else {
    Write-Output 'PATH_ALREADY_PRESENT'
}
```

On success → return `staged_for_restart`. The caller emits this restart message and aborts (substitute `[binaries]` with the basenames of `<src_paths>`, e.g. `yt-dlp.exe` or `ffmpeg.exe + ffprobe.exe`):

```
Recovery configured your user PATH:
  - Copied [binaries] to %LOCALAPPDATA%\Microsoft\WinGet\Links\
  - Added that directory to your user PATH (Registry)

Please RESTART Claude Code, then re-run /yt-extract.
After restart, future winget installs will also work without this recovery step.
```

On non-zero PowerShell exit → return `copy_failed`.

### Return contract — caller dispatch

| State                 | SKILL.md 0.3b/0.5 pre-check                    | install-helper.md Step D fallback             |
|-----------------------|-------------------------------------------------|------------------------------------------------|
| `recovered`           | continue to Step 0.4 (skip install-helper)     | return success to caller                       |
| `staged_for_restart`  | emit restart message, abort skill              | emit restart message, abort skill              |
| `not_found`           | invoke install-helper (current behavior)       | proceed to Step E (current behavior)           |
| `copy_failed`         | invoke install-helper                           | proceed to Step E                              |
