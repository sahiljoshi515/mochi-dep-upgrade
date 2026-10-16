# Dependency Upgrade

A `nanoagent.plugin/v1` plugin, created by `nanoagent plugin new` with the template's checks kept.

Redo a real open-source project's upgrade of one dependency to its new major version. Each instance is
a real change (a commit, a short series of commits, or a merged PR) in which upstream itself upgraded
the dependency and changed its code. The agent gets the repository at the commit before, with the old version installed, and must raise the requirement and
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
  once), hidden tests (upstream's post-upgrade test files from GitHub, sha256-checked), an import probe
  (what importing the project does, against a clean interpreter) and a shim scan of the added code. It
  writes `.judge/judgement.json`.

### Tasks

- `upgrade-dependency` (agent).
  - Tools: `start_upgrade`, `list_files`, `read_file`, `search`, `edit_file`, `write_file`, `sync`,
    `run_tests` and `judge`. Reference: `pin_upgrade`.
  - It ends with `submit` of an `UpgradeReportOutput`: the instance, dependency, from and to versions,
    the requirement as the spec now states it, the changed files and 1 to 8 migration notes.

### The instances

Every instance is a real upstream change, validated by the build-time oracle below. The table is generated from
`src/plugin/data/catalog.json` by `python -m plugin.tools_dev.readme`.

<!-- instances -->
| Instance | Repository (licence) | Upgrade | Judged tests: public / hidden | Upstream's change | Fit |
|---|---|---|---|---|---|
| `click-repl-click-8.2` | [click-contrib/click-repl](https://github.com/click-contrib/click-repl) (MIT) | click 8.1.8 → 8.3.1 (Python 3.12) | 59 (9 excluded) / 11 | [b84191aec2](https://github.com/click-contrib/click-repl/commit/b84191aec21b407b3cb3374ff1ab000887d38f29): 3 files, +25 lines | hosted |
| `emcee-numpy-2` | [dfm/emcee](https://github.com/dfm/emcee) (MIT) | numpy 1.26.4 → 2.0.0 (Python 3.12) | 85 (9 excluded) / 8 | [9c5f59b6ca](https://github.com/dfm/emcee/commit/9c5f59b6ca2fce111cc7348bda415253e0e1c1b0): 1 files, +33 lines | local |
| `ffn-pandas-3` | [pmorissette/ffn](https://github.com/pmorissette/ffn) (MIT) | pandas 2.3.3 → 3.0.1 (Python 3.12) | 50 (1 excluded) / 44 | [bc8e904fa3](https://github.com/pmorissette/ffn/commit/bc8e904fa324bcbed573f2b13055713df1a055c7): 1 files, +9 lines | local |
| `flask-marshmallow-marshmallow-4` | [marshmallow-code/flask-marshmallow](https://github.com/marshmallow-code/flask-marshmallow) (MIT) | marshmallow 3.26.1 → 4.0.0 (Python 3.12) | 44 (5 excluded) / 8 | [d4c087e018](https://github.com/marshmallow-code/flask-marshmallow/commit/d4c087e0186e179f38817006bec4b2a8f277302d): 5 files, +34 lines | hosted |
| `flask-restx-werkzeug-3` | [python-restx/flask-restx](https://github.com/python-restx/flask-restx) (BSD-3-Clause) | Werkzeug 2.3.8 → 3.0.1 (Python 3.11) | 1223 (9 excluded) / 47 | [0c441149ee](https://github.com/python-restx/flask-restx/commit/0c441149ee7de5f04710d24bdc252acb46fdbe37): 4 files, +88 lines | hosted |
| `flask-sqlalchemy-sqlalchemy-2` | [pallets-eco/flask-sqlalchemy](https://github.com/pallets-eco/flask-sqlalchemy) (BSD-3-Clause) | SQLAlchemy 1.4.46 → 2.0.0 (Python 3.11) | 118 (3 excluded) / 53 | [7f94bca1b1](https://github.com/pallets-eco/flask-sqlalchemy/commit/7f94bca1b1e7b1bff0ad172b6130bb3e32060f27): 1 files, +4 lines | hosted |
| `geojson-pydantic-pydantic-2` | [developmentseed/geojson-pydantic](https://github.com/developmentseed/geojson-pydantic) (MIT) | pydantic 1.10.11 → 2.0.2 (Python 3.11) | 133 (1 excluded) / 114 | [40dbafb901](https://github.com/developmentseed/geojson-pydantic/commit/40dbafb90172b161f0945d1917dbbcfb003a1f20): 4 files, +27 lines | hosted |
| `pydantic-yaml-pydantic-2` | [NowanIlfideme/pydantic-yaml](https://github.com/NowanIlfideme/pydantic-yaml) (MIT) | pydantic 1.10.11 → 2.0.3 (Python 3.11) | 21 (4 excluded) / 11 | [c3ad43ea76](https://github.com/NowanIlfideme/pydantic-yaml/commit/c3ad43ea76294a27da61dc88e418e8785dfdad53): 8 files, +346 lines | hosted |
| `respx-httpx-0.28` | [lundberg/respx](https://github.com/lundberg/respx) (BSD-3-Clause) | httpx 0.27.2 → 0.28.1 (Python 3.12) | 313 (8 excluded) / 123 | [179c65131b](https://github.com/lundberg/respx/commit/179c65131b16e895e9da0e2d629aab3db6a97694): 2 files, +7 lines | hosted |
<!-- /instances -->

Candidates the oracle turned down, and why (`src/plugin/tools_dev/rejected.json`):

<!-- rejected -->
| Candidate | Upgrade | Why it is not offered |
|---|---|---|
| [absent1706/sqlalchemy-mixins](https://github.com/absent1706/sqlalchemy-mixins/commit/e0aa411c23e906b90731a981288501c95664fdf2) | SQLAlchemy | Strict hidden rule: upstream's post-upgrade tests import SQLAlchemy-2-only API (DeclarativeBase), so none passes on the old version (R4); and 29 of 41 base tests fail even with upstream's code on 2.0. |
| [wtforms/wtforms-sqlalchemy](https://github.com/wtforms/wtforms-sqlalchemy/commit/1845da429005e3e7c21d822207322985e11f814c) | SQLAlchemy | 6 of 21 base tests (28.6%) fail with upstream's own code on SQLAlchemy 2 (upstream rewrote them): over the 20% exclusion cap (the lead's call: borderline counts as rejected while 6+ strict instances remain). |
| [ewels/rich-click](https://github.com/ewels/rich-click/commit/2268fc4e197c988f14076a138f797dc564367a47) | click | No hidden tests: upstream's change touched no test file. |
| [sloria/environs](https://github.com/sloria/environs/commit/b5a32c90a2ec08a7eaf9fe4afd3152683b676448) | marshmallow | Nothing breaks on marshmallow 4.0 final: the only failing tests test marshmallow 3's behaviour and fail with upstream's code too (a bare version bump would pass). |
| [capitalone/datacompy](https://github.com/capitalone/datacompy/commit/6a7d27d1781632a42a922e3da8ea4ef4668e70ca) | pandas | Its spec needs fugue-sql-antlr, which had no wheels at the time; environments are wheels-only (members need no compiler). |
| [Colin-b/pytest_httpx](https://github.com/Colin-b/pytest_httpx/commit/1571050846) | httpx | Upstream's merge changes only the spec, the version and the tests: a bare version bump suffices. |
<!-- /rejected -->

### The task, step by step

1. `start_upgrade` with the instance (again while `complete` is false).
2. Read what the breaking errors point at.
3. One `edit_file` with `then: sync_and_test`: raise the requirement so it admits the target, and
   migrate the source with exact replacements (at most 10 per call; a larger migration takes a second
   call, and only the last one needs to sync and test).
4. A fix-up `edit_file` if the sync failed or judged tests still fail.
5. `judge` and `submit` in the same step.

This fits the hosted runner's 6 steps when the instance is tagged `hosted`: its gold run, under the
sandbox from a cold cache, took at most 60 s of tool time (set-up at most 45 s and judging at most 40 s,
each in one call) and at most six calls, submit included. `local` instances need a runner whose tool
calls may take minutes.

### The verdict: 19 constraints

The verifier recomputes everything it can itself: the pristine record against the catalog's tree hash,
every changed file and added line, the spec's requirements (its own reader), the lock's pins and hashes,
and the shim scan. It takes only what needs execution (install, build, tests, the import probe) from the judge's record,
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
| 14 | `lock_scope` | Every other package in the lock keeps its pre-upgrade version; one the upgrade moves (collateral), brings in or drops may instead be where upstream's lock has it |
| 15 | `installed_target` | The judged environment has the target installed and `uv pip check` is clean |
| 16 | `builds` | The wheel builds, and its requirement on the dependency admits the target |
| 17 | `public_tests_pass` | Every judged test of the repository passes |
| 18 | `hidden_tests_pass` | Every one of upstream's post-upgrade tests passes |
| 19 | `no_shims` | No shim in the added code, however spelled (the warnings module, `sys.modules` and import tricks, reflection on modules, `exec`, patching the library, version or test sniffing, `pydantic.v1`), and nothing unexpected when the project is imported (warning filters, the warnings module, import hooks, the library's modules and classes) |

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

Each instance starts as a recipe in `src/plugin/tools_dev/recipes.json`. A recipe names:
- the repository, upstream's commit, the dependency and the Python version;
- the spec file and its kind;
- the editable source globs, the test folders, the test requirements and pytest arguments.

Real repositories need a few more settings, each documented in the recipe's notes:
- `base_commit`, when upstream's upgrade spans several commits, or `merge`, to take a merged PR
  against its first parent;
- `base_constraints`, when the spec already admits the new version: the pre-upgrade lock is held
  below it, as upstream's CI ran;
- `resolution_date`, when upstream's commit came before the new version's release, or when the old
  version's wheels came later;
- `install_project` and `env`, for suites that need the project installed or a particular terminal;
- `build_env`, e.g. a setuptools-scm version given without git history;
- `post_setup`, files the project's install would generate.

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
- **Shim rules** that upstream's own change breaks are exempt for the instance (`shim_exempt`:
  flask-restx's `warnings.simplefilter` and `importlib.metadata.version`, pydantic-yaml's
  `pydantic.version.VERSION`), and what importing upstream's tree does is expected of it
  (`probe_expected`: ffn attaches its functions to pandas' `PandasObject`, as it always has).
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
  tools_dev/              onboard (the oracle), recipes.json, rejected.json, cases, fit, readme, record_pythons
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
- **The cases:** `uv run python -m plugin.tools_dev.cases --adversarial respx-httpx-0.28 geojson-pydantic-pydantic-2`
  writes a gold case per instance (upstream's change as `edit_file` and `write_file` calls) and 21 wrong
  submissions on each of the two instances named. `review_*` cases come from the independent review
  (alternative correct migrations, its evasions) and `regress_*` cases are hand-made variants of them;
  they are kept as files.
- **Through NanoAgent's real task runner:** with a scripted agent instead of a model,
  `python scripted_task.py <plugin> tests/cases/<case>.json --sandbox seatbelt`, or every case with
  `python ~/mochi-dev/harness/run_cases.py <plugin> tests/cases/*.json --jobs 1 --sandbox seatbelt`.
- **The fit tags:** `uv run python -m plugin.tools_dev.fit <out-root>/timings.json --load <load average>`
  from the gold cases run one at a time, then `uv run python -m plugin.tools_dev.readme` for the tables.

### Limitations

- **Locks are plugin-owned.** `.judge/requirements.lock` is the plugin's own; the repositories ship no
  lock file. A real project would commit its lock or its updated spec only.
- **Pinned resolution dates.** Each instance's target is the newest release upstream's spec admits as
  of its resolution date, not today's newest.
- **Hosted fit.** Set-up and judging must fit a hosted run (180 s for everything, with the model's
  steps). Instances tagged `local` need a runner whose tool calls may take minutes. The tags come from
  one gold run per instance on an Apple-silicon Mac (the load average is in the catalog). emcee and ffn
  are `local`: their gold runs took 72 s and 65 s of tool time (59 s and 63 s on a quieter re-run), most
  of it their own test suites; the import probe adds about 7 s to ffn, which imports pandas and
  matplotlib twice.
- **No sockets in tests.** The oracle runs every test with no network at all, as NanoAgent's macOS
  sandbox does (no DNS, no loopback server, no Unix socket), so a test that needs one is left out of the
  judged sets: flask-restx's e-mail checks that resolve gmail.com, for one.
- **Shims.** The added code is read twice with the same rules: by the judge with `ast`
  (`src/plugin/shims.py`, recorded in the judgement) and by the verifier from the tokens
  (`verifier/shims.py`; NanoAgent's verifiers may not import `ast`). Names resolve through imports and
  aliases, strings fold (`"filter" + "warnings"`, `chr`, `join`, f-strings, escapes, rot13), and
  `getattr`, `vars`, `__dict__` and computed imports are followed. Code can still hide a name from any
  reading (built from bytes, say); the import probe then shows what the project's import did, but only
  at import time: a shim that acts later, inside a function, is left to the hidden tests.
- **Validated platforms.** Instances are validated on macOS (Apple silicon) only. The locks are
  universal and `data/pythons.json` pins Linux x86-64 interpreters, but no instance has been run on
  Linux yet; wheels-only locks may not install on other platforms.
