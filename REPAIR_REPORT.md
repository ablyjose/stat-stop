Review and repair notes, October 27, 2026
=======================================

Monaco follow-up: the cached 2026 race has car telemetry for Norris (285 samples), but his position table is empty with no columns. FastF1 3.9.0 fails inside `pos_data.merge_channels` when `get_telemetry()` attempts to index that table by `Date`. The shared lap reader now falls back to car data with interpolated lap boundaries and calculated distance if the position merge fails or produces invalid distance samples. It validates the fallback before accepting it. Both the importer and API use this reader. The scheduler also prints its retry delay explicitly; the default 900-second wait previously appeared to hang. Stationary fallback samples retain the last timestamp at each repeated distance. All 22 Monaco race drivers passed validation against the existing local FastF1 cache, and regression coverage now totals 58 passing tests.

The review covered the backend, scripts, frontend pages and components, launch and deployment configuration, dependency manifests, existing tests, Git history, and the population log. The tracked application files initially matched HEAD. The surviving population script and tests were ignored by Git and depended on helpers absent from that tracked revision. This explains the inconsistent working copy; the available history does not establish who made each change.

Confirmed failures and repairs
-----------------------------

| Area | Evidence and effect | Repair |
| --- | --- | --- |
| Importer and R2 contract | `auto_prepopulate.log:16607` records the traceback for the missing `telemetry_completion_key`. Three other imported helpers were also absent. | Restored completion-key, timing-validation, and corner-cache helpers. |
| Invalid timing caches | A live read of the 2026 United States GP timing index found zero drivers. The API accepted any truthy dictionary, including this empty index. | Validate stored timing indexes; rebuild invalid entries; reject empty or partially failed source processing before uploading. |
| Telemetry completion | Older logs repeatedly reported successful population while the next check still found missing data. | Validate telemetry before uploading and publish the versioned completion marker only after every required driver upload succeeds. Preserve nonzero exit status on failure. |
| Deleted scheduler | Existing tests referenced `auto_prepopulate.py`, which was absent. | Recreated the scheduler with UTC race-end checks, retries, streamed child output, CSV status, one-shot and explicit watch modes. It checks race, qualifying, and applicable sprint sessions. |
| Circuit annotations | The API expected a list, while the script also used an expiring unavailable-map dictionary. Passing that dictionary to the frontend would break `.map()`. | Read both formats and always return a list to the frontend. Unavailable optional maps have an expiry; source failures stay retryable. |
| Telemetry API | Missing fastest laps and missing numbered laps became generic 500 errors. A partial cache miss reloaded both drivers. | Return clear 404 errors, retain the cached driver's data, and validate generated telemetry before saving. The API and importer share the delta validator. |
| Runtime and entrypoints | At the start, `.venv` contained FastF1 3.9.0 while plain `python` used 3.8.3. Package-style backend imports also failed. | The user updated their regular Python environment. The launcher resolves `python` from PATH, and scheduler children use that same interpreter. FastF1 3.9 dependency bounds and compatible package/direct imports keep these paths consistent. Optional F1 credentials load from `backend/.env` without overriding environment variables. |
| Frontend | Lint failed on an unused multiselect variable. Request failures were console-only; telemetry driver selections could remain invalid after changing events. | Fix lint, show request errors, reconcile event and driver selections, ignore outdated option responses, and correct race-pace empty-data and lap-domain handling. |
| Regression coverage | The entire tests directory and the manual population script were ignored. `test_drivers.py` ran network requests during collection. | Keep scripts and tests visible to Git, ignore generated logs/status files, replace the network-on-import test, and isolate R2 in unit tests. |

Authentication and stored data
------------------------------

Both Python environments initially reported no stored authentication, including a check outside the execution sandbox. After the user's browser login, the project interpreter reported an active F1TV token. A live FastF1 race load then returned 1,164 laps for 22 drivers, including 1,163 timed laps. R2 access also succeeded. Existing Australian GP qualifying telemetry passed the shared delta calculation, producing 567 comparison samples.

The original log and CSV were retained. R2 checks during diagnosis were read-only. Generated live-validation payloads are saved under `cache/repair-preview/`, which is ignored by Git.

The complete United States GP population flow subsequently succeeded with uploads redirected to those local files. It generated 48 objects: 22 race telemetry entries, 22 qualifying telemetry entries, two completion markers, one timing index covering 22 drivers, and one circuit-corner list. The API served the generated race telemetry successfully with 746 delta samples and 20 corner markers. The console's normal upload messages came from the production code; the validation upload adapter wrote only local files. The live R2 timing index still needs the normal population command below to replace its empty data.

Validation
----------

- 54 backend tests passed in both the original project virtual environment and the user's updated regular Python environment, covering imports, failed uploads, empty timing indexes, corner-cache expiry, missing laps, delta calculations, scheduler retries, and future/unknown schedule dates. Regular `python` now reports FastF1 3.9.0 and the active F1TV login. The HTTP test dependency (`httpx`) was installed in that environment for the API smoke test.
- Both population command-line help entrypoints run successfully.
- Frontend ESLint and the production build passed. Vite retains its existing large-chunk advisory.
- Python compilation, dependency consistency, and Git whitespace checks passed.
- Full live US GP prepopulation passed with local output capture, followed by an API check against the generated payloads. No R2 uploads were performed during verification.
- The HTTP smoke test requires local asyncio sockets. In the restricted Windows execution sandbox these were blocked, so the full test suite was run outside that sandbox with R2 mocked.

Run from the repository root
----------------------------

Use your regular Python interpreter consistently. A virtual environment is optional:

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q
python backend/scripts/prepopulate.py --year 2026 --gp "United States Grand Prix"
```

The scheduler runs one season check by default. Add `--watch` for continuous polling:

```powershell
python backend/scripts/auto_prepopulate.py --year 2026
python backend/scripts/auto_prepopulate.py --year 2026 --watch
```

The scheduler appends to `backend/scripts/auto_prepopulate.log` and updates `backend/scripts/f1_race_ends.csv`. It estimates race completion at 2.5 hours after the scheduled UTC start. Events with unknown start times remain unprocessed. `--attempts`, `--retry-delay`, and `--interval` control retries and polling; `--force` rebuilds existing products. The scheduler has been restored as source code and has not been installed as an operating-system scheduled job.

For future browser login renewal, use the same interpreter and OS user:

```powershell
python -m fastf1 auth f1tv --method browser --authenticate
python -m fastf1 auth f1tv --status
```

The previously documented `TOKEN_VALUE` variable was unused by the application. The example configuration now documents FastF1's supported login and optional credential inputs. The user's actual `.env` was preserved.
