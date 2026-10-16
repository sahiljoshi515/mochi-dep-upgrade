# Dependency Upgrade

A `nanoagent.plugin/v1` plugin, created by `nanoagent plugin new` with the template's checks kept.

Redo a real open-source project's upgrade of one dependency to its new major version. Each instance is
a commit in which upstream itself upgraded the dependency and changed its code. The agent gets the
repository at the commit before, with the old version installed, and must raise the requirement and
migrate the code so that:
- the project locks and installs exactly the target release, with the files PyPI serves for it;
- its wheel builds;
- the repository's own tests pass;
- upstream's post-upgrade tests (hidden) pass;
- nothing unrelated changes.

A deterministic verifier (no model) checks 19 constraints and says which failed and why.

## Tools

- `pin_upgrade`: the task's reference. It reads the instance's catalog entry and, from PyPI, the files
  of the target release, which must still be the ones the instance was validated with. It also notes
  any judgement already in the workspace, so a run must judge afresh.
- `start_upgrade`: checks the repository out under `dep-upgrade/<instance>/` at the commit before
  upstream's upgrade. The tree comes from GitHub's codeload and must match the validated tree hash.
  It records the pristine tree and installs the pre-upgrade lock in a venv outside the workspace. It
  returns:
  - the dependency, its current and target versions, the spec file and its requirement;
  - the editable globs and where the source imports the dependency;
  - the public tests that break on the new version, with their first error;
  - the tests that are not judged;
  - whether the instance fits a hosted run;
  - the rules.
- `list_files`, `read_file`, `search`: bounded reads of the workspace, never inside `.judge/`.
- `edit_file`: exact replacements (each `old` must occur once), all or none, only in the spec file's
  requirements and in source files under the editable globs. With `then: sync_and_test` it re-locks,
  installs and runs the public tests in the same call.
- `write_file`: whole files (new modules), with the same rules and the same `then`.
- `sync`: re-locks the spec as it stands, as of the instance's resolution date, with every other
  package held at its pre-upgrade version by constraints. It then installs exactly that lock (hashes
  required, wheels only).
- `run_tests`: the repository's tests on the agent's code, in a scratch copy. Failures among tests that
  are not judged are only counted.
- `judge`: the trusted final look, in stages that resume across calls: diff, lock, install
  (`uv pip check`), build (the wheel and the requirement it declares), public tests (failures rerun
  once), hidden tests (upstream's post-upgrade test files from GitHub, sha256-checked) and a shim scan
  of the added lines. It writes `.judge/judgement.json`.

### Tasks

- `upgrade-dependency` (agent).
  - Tools: `start_upgrade`, `list_files`, `read_file`, `search`, `edit_file`, `write_file`, `sync`,
    `run_tests` and `judge`. Reference: `pin_upgrade`.
  - It ends with `submit` of an `UpgradeReportOutput`: the instance, dependency, from and to versions,
    the requirement as the spec now states it, the changed files and 1 to 8 migration notes.

### The instances

Every instance is a real commit, validated by the build-time oracle below. The table is generated from
`src/plugin/data/catalog.json` by `python -m plugin.tools_dev.readme`.

<!-- instances -->
| Instance | Repository (licence) | Upgrade | Judged tests: public / hidden | Upstream's change | Fit |
|---|---|---|---|---|---|
| `pydantic-yaml-pydantic-2` | [NowanIlfideme/pydantic-yaml](https://github.com/NowanIlfideme/pydantic-yaml) (MIT) | pydantic 1.10.11 → 2.0.3 (Python 3.11) | 21 (4 excluded) / 11 | [c3ad43ea76](https://github.com/NowanIlfideme/pydantic-yaml/commit/c3ad43ea76294a27da61dc88e418e8785dfdad53): 8 files, +346 lines | local |
| `respx-httpx-0.28` | [lundberg/respx](https://github.com/lundberg/respx) (BSD-3-Clause) | httpx 0.27.2 → 0.28.1 (Python 3.12) | 313 (8 excluded) / 123 | [179c65131b](https://github.com/lundberg/respx/commit/179c65131b16e895e9da0e2d629aab3db6a97694): 2 files, +7 lines | local |
<!-- /instances -->

### The task, step by step

1. `start_upgrade` with the instance (again while `complete` is false).
2. Read what the breaking errors point at.
3. One `edit_file` with `then: sync_and_test`: raise the requirement so it admits the target, and
   migrate the source with exact replacements.
4. A fix-up `edit_file` if the sync failed or judged tests still fail.
5. `judge` and `submit` in the same step.

This fits the hosted runner's 6 steps when the instance is tagged `hosted` (set-up and judging measured
short enough). `local` instances need a runner whose tool calls may take minutes.

### The verdict: 19 constraints

The verifier recomputes everything it can itself: the pristine record against the catalog's tree hash,
every changed file and added line, the spec's requirements (its own reader), the lock's pins and hashes,
and the shim scan. It takes only what needs execution (install, build, tests) from the judge's record,
after showing that record is this run's, for this instance, with nothing changed since.

| # | Id | Holds when |
|---|---|---|
| 1 | `instance_pinned` | PyPI still serves the target release's files with the validated sha256, not yanked |
| 2 | `submitted_facts` | The submission names this instance, the dependency, and both versions |
| 3 | `migration_notes` | 1 to 8 notes of 10 to 200 characters |
| 4 | `judged` | A complete judgement for this instance exists |
| 5 | `judged_this_run` | It was made in this run (not the judgement found when the task started) and after this set-up (its token) |
| 6 | `judgement_consistent` | It used this catalog entry, the validated pristine tree and the validated hidden tests |
| 7 | `files_as_judged` | Nothing changed after (or while) judging |
| 8 | `submission_matches` | The submitted changed files and requirement are the real ones |
| 9 | `allowed_files_only` | Only the spec file and source under the editable globs changed; nothing was deleted |
| 10 | `within_limits` | Changed files, new files and added lines within the instance's limits (from upstream's own change) |
| 11 | `spec_scope` | The spec changed only the dependency's requirement (and what the upgrade moves with it); no URLs; the rest of the file unchanged |
| 12 | `spec_admits_target` | The requirement admits the target (and excludes the old version when upstream's did) |
| 13 | `lock_target` | The judged lock pins exactly the target, with hashes PyPI serves for it, and is unchanged since judging |
| 14 | `lock_scope` | Every other package in the lock is where the validated post-upgrade lock puts it |
| 15 | `installed_target` | The judged environment has the target installed and `uv pip check` is clean |
| 16 | `builds` | The wheel builds, and its requirement on the dependency admits the target |
| 17 | `public_tests_pass` | Every judged test of the repository passes |
| 18 | `hidden_tests_pass` | Every one of upstream's post-upgrade tests passes |
| 19 | `no_shims` | No shim in the added lines (warning filters, `sys.modules`, reloads, test or version sniffing, monkeypatching the library, `pydantic.v1`) |

How the verdict is scored:
- **Valid** only when all 19 hold. The message then says so.
- **Score** is the share that held, at most 0.99 unless valid.
- **Message** names the first failure, e.g. "The requirement httpx==0.27.2 does not admit 0.28.1" or
  "Shim at respx/mocks.py:2: …".
- **Not checked.** A constraint that needs a missing judgement is marked not checked.
- **Details** carry every constraint (`{id, constraint, ok, expected, actual, message}`), the changed
  files, the diff, failing tests and the provenance. The page draws them as a checklist.

### Where the ground truth comes from

- **The repository.** GitHub's codeload, at the commit before the upgrade (base) and at upstream's
  commit (C). Trees are checked against tree hashes recorded when the instance was validated.
- **Versions and files.** PyPI's JSON API gives the target release and its files' sha256. The
  reference reads it live.
- **Locks.** `uv pip compile --universal --generate-hashes --only-binary :all: --exclude-newer <resolution
  date>`. The pre-upgrade lock comes from the base spec (held below the new major when the spec
  already admits it, as upstream's CI ran it). The validated post-upgrade lock comes from upstream's
  spec. Sync reproduces the latter exactly for upstream's change.
- **Tests.** Public tests are the repository's own at the base commit. Hidden tests are upstream's own
  test files at C.

### How an instance is validated (`python -m plugin.tools_dev.onboard`)

Every cell below runs twice:

| Cell | Source | Tests | Environment |
|---|---|---|---|
| R1 | base | base | old |
| R2 | base | base | new |
| R3 | C | base | new |
| R4 | base | C | old |
| R5 | C | C | new |
| R6 | base | C | new |

From those runs:
- **Public tests** pass in R1 and R3, both times. At most 20% of the base tests may be excluded; the
  rest are listed to the agent.
- **Hidden tests** are tests in the files C changed that pass in R4 and R5, both times. Tests coupled
  to upstream's own renames fail R4 and drop out. At least one is required.
- **Breakage.** Some public test must fail in R2, or some hidden test in R6, so a bare version bump
  cannot pass.
- **Limits** come from upstream's own change (its source changes, and its spec's requirements).
- **Shim patterns** that upstream's own added lines match are dropped.
- **The gold case.** Upstream's change, replayed as `edit_file` replacements (`python -m
  plugin.tools_dev.cases`), must be valid at 1.0.

## Layout

```
contract.py               tools' and task's typed inputs and outputs
nanoagent.yaml            the manifest: tools, the task, hosts
src/plugin/
  __main__.py             the MCP server
  project.py              pin_upgrade, start_upgrade (codeload checkout, pristine record)
  files.py                list_files, read_file, search, edit_file, write_file
  sync.py                 sync, run_tests
  judge.py                judge
  envs.py                 locks (uv pip compile), venvs, installed versions
  testing.py              pytest in a scratch copy, with the JSON recorder (runners/pytest_json.py)
  spec.py, fetch.py, pythons.py, common.py
  data/                   catalog.json, locks/<instance>.{base,gold}.txt, pythons.json
  tools_dev/              onboard (the oracle), recipes.json, cases, readme, record_pythons
verifier/                 the deterministic verifier: task.py (19 constraints), one module per tool
                          group, and the readers the tools share (specs, locks, trees, shims, catalog)
tests/                    offline unit tests, replay.py, and the scripted cases (tests/cases)
ui/                       renderers.js and renderers.css: the result card
product/                  product.yaml and icon.svg
```

## Develop and run

```bash
uv sync --extra dev
uv run pytest                                  # offline: specs, locks, trees, tools, the 19 constraints, the server
NANOAGENT_NETWORK=1 uv run pytest              # also replays every case in tests/cases (GitHub and PyPI)
uv run python tests/replay.py tests/cases/gold_respx-httpx-0.28.json
uv run ruff check .
```

The environments run on Python 3.11 or 3.12, depending on the instance. The interpreter comes from, in
order:
1. the plugin's own, when it matches;
2. one `uv python find` knows;
3. a sha256-pinned python-build-standalone build from releases.astral.sh (`data/pythons.json`).

### Reproduce the checks

- **An instance, from its recipe:**
  `uv run python -m plugin.tools_dev.onboard <instance> [--write]`. It runs the oracle, R1–R6, every
  cell twice, and the evidence goes to `~/mochi-dev/runs/dep-upgrade/build/<instance>/oracle.json`.
- **The cases:** `uv run python -m plugin.tools_dev.cases --adversarial respx-httpx-0.28`.
- **Through NanoAgent's real task runner:** with a scripted agent instead of a model,
  `python scripted_task.py <plugin> tests/cases/<case>.json --sandbox seatbelt`.

### Limitations

- **Locks are plugin-owned.** `.judge/requirements.lock` is the plugin's own; the repositories ship no
  lock file. A real project would commit its lock or its updated spec only.
- **Pinned resolution dates.** Each instance's target is the newest release upstream's spec admits as
  of its resolution date, not today's newest.
- **Hosted fit.** Set-up and judging must fit a hosted run (180 s for everything, with the model's
  steps). Instances tagged `local` need a runner whose tool calls may take minutes.
- **Shims.** The shim scan is a regex scan of the added lines. It catches the common shims, not every
  conceivable one; the hidden tests catch most partial migrations.
- **Validated platforms.** Instances are validated on macOS (Apple silicon); a Linux x86-64 sample is
  checked separately. Wheels-only locks may not install on other platforms.
