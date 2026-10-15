# Build, Test, and Publish AI Operator

This guide takes the repository from a fresh Windows folder to a tested local demo, then to a safe portfolio deployment. Read the production limits before publishing: the app is a single-user local-first starter, not a multi-tenant service.

## Stage 0 — Keep your current project safe

The provided ZIP is a standalone starting project. No existing VS Code folder was available to inspect or modify in this chat.

If you already have a project, make a copy before importing files:

```powershell
# Run in the parent folder; choose your actual project path.
Copy-Item -Recurse -Force .\your-current-project .\your-current-project-backup
```

Extract the ZIP into a new folder first and test it independently. Merge working modules into your existing project only after the new copy passes its tests. Do not overwrite an existing `.env`, database, or workbook.

## Stage 1 — Create the Python environment

Open the project folder in VS Code, then open **Terminal → New Terminal** and ensure PowerShell is selected.

```powershell
Get-Location
Get-ChildItem
py -0p
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m playwright install chromium
```

If `py -3.12 --version` fails, install Python 3.12 and reopen the terminal. In VS Code, press **Ctrl+Shift+P → Python: Select Interpreter**, then select `.venv\Scripts\python.exe`.

Do not run bare `pip` or rely on a global Python installation. Prefix commands with `\.venv\Scripts\python.exe -m ...` so all packages are installed into the intended environment.

## Stage 2 — Validate the environment

```powershell
.\.venv\Scripts\python.exe diagnostics.py
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m pytest -q
```

When dependencies are installed successfully, `tests/test_mcp_server.py` should execute an actual local MCP stdio discovery and confirm that the expected tools are registered. It is written to skip only when the MCP SDK is absent; a skip on a fully installed machine is a setup problem to investigate.

If package installation fails, first confirm network/DNS access and check which executable is running:

```powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); print(sys.version)"
.\.venv\Scripts\python.exe -m pip --version
.\.venv\Scripts\python.exe -m pip check
```

## Stage 3 — Configure Gemini (optional)

Open `.env`. Without a Gemini key, the demo still uses the deterministic planner and local sample dataset. To use model-assisted intent classification:

```dotenv
GEMINI_API_KEY=your_actual_key
GEMINI_MODEL=gemini-flash-latest
```

Do not put a key in `app.py`, `requirements.txt`, a screenshot, a prompt shared publicly, or GitHub. If the configured model is unavailable or the response fails validation, planning falls back to the deterministic classifier. The LLM is not allowed to grant permissions or invent unavailable MCP tools.

## Stage 4 — Run locally

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`.

### Scenario A: internship workflow

1. Enter: `Find three internships for a third-year computer science student, compare eligibility, save the best matches to a spreadsheet with links, and draft personalised emails for each.`
2. Click **Plan and research**.
3. Inspect the tool list, ranking reasons, source URLs, eligibility confidence, and sample-data/live-search status.
4. Review the exact Excel rows and draft text.
5. Approve the local writes.
6. Confirm that the final report shows read-back verification and download the workbook/drafts.

### Scenario B: spreadsheet failure recovery

1. Start a new task and wait until the proposed output preview appears.
2. Enable the sidebar switch **Simulate spreadsheet failure**.
3. Approve the output. The spreadsheet write fails before modifying the workbook. It is retried and then paused honestly.
4. Disable the failure switch.
5. Click **Resume the failed step**.
6. Confirm the agent reuses the stored research, does not run the search again, saves missing rows/drafts, re-reads the workbook, and verifies the output.
7. Run the scenario again using a fresh task and the demo output workbook to check duplicate skipping.

For a clean demo environment, back up and remove only generated files under `output/` and `state.db` when the app is stopped. Do not delete a real workbook or database containing data you need.

## Stage 5 — Review before source control

The `.gitignore` excludes `.env`, SQLite state, generated Excel files, and draft/report output. Confirm before committing:

```powershell
git status --short
Get-Content .gitignore
if (Test-Path .env) { Write-Output ".env exists locally; confirm it is ignored." }
```

If the folder is not already a Git repository:

```powershell
git init
git branch -M main
git add .
git status --short
```

Inspect the staged files. Make sure `.env`, `state.db`, private resumes, real applications, personal drafts, and generated workbooks are not staged. Then commit:

```powershell
git commit -m "Build local-first AI Operator foundation"
```

Create an empty repository in GitHub. Then connect it (replace the placeholder with your own repository URL):

```powershell
git remote add origin https://github.com/YOUR_USERNAME/ai-operator.git
git push -u origin main
```

If the project already has a remote, inspect `git remote -v` and use the intended repository rather than adding a second `origin`. Do not force-push over existing work.

## Stage 6 — Portfolio deployment (demo only)

For a portfolio demo, Streamlit Community Cloud can deploy a repository-backed Streamlit app. It supports selecting a repository, branch, entrypoint, Python version, and secrets in its app settings. The `requirements.txt` belongs at the repository root.

1. Push the project to GitHub.
2. Sign in to Streamlit Community Cloud and connect GitHub.
3. Create an app and select the repository, `main` branch, and `app.py` entrypoint.
4. Select Python 3.12 in advanced settings if the selector is available.
5. Add a secret only if model-assisted planning is needed, for example:

```toml
GEMINI_API_KEY = "your_actual_key"
GEMINI_MODEL = "gemini-flash-latest"
```

6. Deploy and inspect build logs. Run through the full demo using synthetic data.

**Do not publish this unmodified single-user app for public use with personal data.** Task history, audit records, generated output files, and SQLite persistence are stored in the app's local filesystem. On a shared public deployment, this design does not provide per-user data isolation. The hosting filesystem may also be ephemeral. Use private access and synthetic records for a personal demonstration only.

## Stage 7 — What must change before a real production launch

Do not skip this stage if the app will handle other people's data or perform real external actions.

### Identity and data isolation

- Implement real authentication (not a hard-coded shared password).
- Add user/tenant IDs to every task, step, approval, audit event, and stored artifact.
- Enforce tenant scoping at every database query and tool boundary.
- Prevent users from viewing one another's task history, spreadsheet contents, resumes, email drafts, or audit records.
- Use persistent managed storage for state and generated files. Replace local SQLite with PostgreSQL for concurrent multi-user use.
- Define retention, export, and deletion policies for profile data and generated artifacts.

### Operational reliability

- Add database migrations and rollback tests.
- Add dependency lockfiles, security scanning, and automated CI tests.
- Add bounded timeouts and cancellation for each provider integration.
- Add backups and restore drills.
- Add structured, redacted logs and monitoring without storing secrets or unnecessary personal information.
- Add rate limits and concurrency limits.
- Add error budgets and incident response documentation.
- Test app restart during every workflow state, not only during the spreadsheet-write step.

### Each consequential integration is its own release

- **Email:** add an OAuth-based provider adapter with draft/send permissions separated. Keep sending approval-gated and reconcile ambiguous send outcomes before retrying.
- **Job applications:** add supported employer/ATS adapters, validate each form schema, prevent duplicate submissions, and require explicit final approval. CAPTCHA or identity checks must pause for the user.
- **Interview scheduling:** integrate a calendar provider with OAuth, time-zone correctness, conflict checks, and approval before sending invitations.
- **Travel/tickets:** select a specific authorized provider. Re-check the live offer and full price immediately before purchase, ask for transaction-specific approval, and pause for secure authentication/payment where required. A generic search result is not a booking API.
- **Browser actions:** keep public/private network egress controls at the infrastructure layer as well as in code. Do not treat webpage text as instructions or bypass access controls.

### Release gates

Before tagging a production release:

- `pytest` passes in CI and on a clean machine.
- Scenario A passes three consecutive times.
- Scenario B passes three consecutive times and no duplicates appear.
- Process restart tests cover discovery, research, approval pending, approval accepted, partially written outputs, and verification failures.
- No unapproved local or external write can occur.
- All success claims are tied to verification evidence.
- The README accurately lists integrations that are real, disabled, or incomplete.
- A demo recording exists as a fallback for a live hackathon presentation.
