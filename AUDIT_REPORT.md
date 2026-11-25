# Pre-production audit

Scope note: the run was cut short on request, so this is a focused audit, not a line-by-line read of
every file. Read in full: `server.py`, `server_journey.py`, `server_orgs.py`, the config and deploy
files, the new journey pages, and the shared API client. Everything else was only searched
(prints, CORS, URLs, env variables, dependencies, boolean state).

## 1. Architecture and implicit state machines

**Architecture.** One FastAPI process (`server.py` plus `server_*.py` routers) serves `/api/*` and the
exported Next.js app (`frontend/out`) on port 8000. `npm run dev` runs Next.js on 3000 and proxies
`/api/*` to 8000. Layers: `piq/` (services, accounts, orgs, journey), `agents/` (LangGraph agents),
`core/` (AI, speech and transcription routers, mail, auth), `database/` (telemetry, SQLite with a
PostgreSQL copy). Health check: `GET /api/health`. CORS origins come from `FRONTEND_ORIGINS`.

**State tracked through booleans or nullable values** (the earlier `useProctor` refactor is already
an explicit union):

| Where | States | Problem found |
|---|---|---|
| `app/critic-quiz/page.tsx` (`batch`, `grade`, `generating`, `grading`) | setup, generating, answering, grading, graded | A proctoring breach could call the grade handler during a manual submit or after grading (double record). **Guarded.** A reducer would be cleaner; not done, risk is higher than the gain. |
| `app/roadmap/page.tsx` (`savingTask`) | idle, saving | `savingTask` was set but never read, so two quick ticks sent two overlapping whole-list saves and one tick was lost. **Guarded.** |
| `app/voice-interview/page.tsx` (`isRecording`, `generating`, `assessing`, `transcribing`, `questionData`, `assessment`) | idle, recording, transcribing, answered, assessed | A double click during the permission prompt opened two microphones; leaving the page while recording left the microphone open. **Fixed.** The cluster of booleans still allows impossible mixes (e.g. recording while assessing). Report only. |
| `app/scanner/page.tsx`, `app/results/page.tsx`, `app/org-admin/page.tsx` (1,700 lines) | loading/ready/error as separate booleans | Not converted. Candidate for a reducer later. |
| `app/settings/page.tsx` (17 boolean/null states), `components/contribute/Contribute.tsx` (12), `app/resume-builder/page.tsx` (11) | | Not reviewed in depth. |

## 2. Changes made

1. **Streamlit untracked** (`git rm -r --cached` + `.gitignore`): `.streamlit/`, `app.py`, `views/`,
   `piq/ui.py`, `piq/charts.py`, `core/proctor_guard.py`, `core/proctor_assets/`, `scripts/pages.py`,
   `scripts/perf.py`. These files were already gone from disk before this run started (shown as
   deleted in `git status`); they are still in history up to commit `4d62a59`.
2. **Committed the in-progress migration** that was sitting uncommitted: unified single-port server
   (static export served by FastAPI), new journey/org API routers and frontend pages, Docker and
   Render config, `streamlit`/`altair` removed from `requirements.txt`, README rewrite.
3. `server.py`: the static-file route raised a 500 on a path containing `%00` (`resolve()` raises
   `ValueError`); now 404. Docstring brought up to date.
4. Upload endpoints (`server_journey.py`, `server_orgs.py`): read at most cap + 1 bytes instead of the
   whole body before checking the 5 MB limit. Same responses, bounded memory.
5. Frontend guards: critic-quiz double grade, roadmap lost tick, voice microphone and audio leak.
6. Docs: `.env.example` (`APP_URL` and Drive callback default to port 8000), `.env.production.example`
   and `render.yaml` (no more Vercel or `API_ORIGIN` instructions: production is one service), README
   convention line (views no longer exist), `frontend/lib/api.ts` header comment.

## 3. Unfixed issues

### High
- **Critic-quiz grading trusts the client** (`server_journey.py:256`, `GradeQuizRequest.batch`). The
  browser sends the whole batch including `correct_index`, so a student can post a forged batch and
  record any score, which feeds the faculty and org dashboards. Fix: serve and store the batch server
  side and grade by id, as `piq/quiz_sessions.py` already does for the practice quiz. Changes the API
  contract, so not done. Confidence: high.

### Medium
- **Voice answer upload is mislabelled** (`frontend/app/voice-interview/page.tsx`, `lib/journeyApi.ts:231`):
  `MediaRecorder` produces webm/ogg but the blob is typed `audio/wav` and named `answer.wav`. Some
  transcribers pick the format from the name. Not verified live. The hands-free page may handle it
  correctly; reuse its approach. Confidence: medium.
- **`/api/journey/voice/assess` takes `question: dict` unvalidated** (`server_journey.py:66`). Type
  errors become a generic 500; the answer length is already capped in the service. Use a Pydantic
  model. Confidence: high.
- **`orgs._own_student` called from the router** (`server_orgs.py:691`): a private function used
  across modules; add a public wrapper in `piq/orgs.py`.
- **No frontend lint or test tooling.** There is no ESLint config and no test runner; only the type
  check and build run. Adding them means new dependencies, so not done.
- **CI cannot run pytest** (`tests/` is intentionally git-ignored); CI runs `scripts.ci_check`. The
  1,105 local tests only run on the developer's machine.

### Low
- **Unused frontend dependencies**: `clsx` and `tailwind-merge` are never imported. They are listed in
  the credits text in `frontend/app/terms/page.tsx`, so removal needs that line changed too.
- **Python dependencies not re-checked** after the Streamlit removal (the check was interrupted). Worth
  confirming `pandas` is still imported.
- **Leftover Streamlit setting**: `raise_page_errors` / `PIQ_RAISE_ERRORS` in `piq/config.py` and
  `scripts/ci_check.py` only served the removed app. Local tests may still reference it, so left.
  `core/drive.py` keeps an unused `ui` parameter.
- **Stale local docs**: `docs/CLAUDE.md` (git-ignored) still describes Streamlit.
- **Logging is not configured** (no `basicConfig`): `log.info` calls are dropped under uvicorn, only
  warnings and errors show. Runtime code has no stray `print`; prints are only in CLI scripts.
- **Dockerfile** copies the whole `frontend/` source into the final image (only `out/` is needed).
- **Empty `catch {}`** in `app/scanner/page.tsx` (`loadMeta`, `loadLastScan`) hides load failures.
- **Effect re-runs on `candidate` identity** in several pages (`critic-quiz`, `roadmap`, `scanner`), so
  a refreshed candidate object reloads data and resets selections.
- **`GET /{path}` catch-all** answers 404 JSON for unknown `/api/...` GETs but 405 for other methods.

## 4. Results

| Check | Result |
|---|---|
| `ruff format --check .` | pass (94 files) |
| `ruff check .` | pass |
| `python -m scripts.ci_check` | all checks passed |
| Backend tests, before changes | 1,105 passed (one timing test, `test_load_balancer::test_a_repeated_plan...`, failed once under load and passed alone) |
| Backend tests, after changes | 1,105 passed |
| `npm run typecheck` | pass |
| `npm run build` | pass (static export) |
| Frontend lint / tests | none exist in the project |

## 5. Assumptions

- The uncommitted working tree was the intended Streamlit-to-Next.js migration and belongs in `main`.
- Streamlit files already deleted from disk were not restored; history holds them.
- Anything that changes an API contract or UI behaviour went in this report, not into code.
- No `.env` file was opened or committed. The `.env.example` files hold names only.
- Shutdown: the instructions allow it only after a verified push.
