# Dependency Upgrade

A `nanoagent.plugin/v1` plugin, created by `nanoagent plugin new` with the
structure of NanoAgent's reference plugin, `plugins/arxiv-source`. Its task,
`upgrade-dependency`, gives an agent a small, realistic Python project pinned
to an old major of a real library and asks it to raise that one dependency to
a target version and change the code so the project builds and passes its
public and hidden tests, without touching anything unrelated.

## Tools

| Tool | Does | Code |
|---|---|---|
| `pin_project` | The task's reference: the pristine project's tree hashes, its `[project]` dependencies and `requires-python`, every other direct dependency's locked version, the allowed additions and collateral, the forbidden patterns, the hidden tests' hash and ids, and the change limits | `src/plugin/project.py` |
| `start_project` | Copies the project into `dep-upgrade/<project>/`, commits it (`git init`), creates the project's venv on the plugin's own Python outside the workspace (see Limitations) and runs `uv sync --frozen`; resumable (`complete: false` means call again, progress in `.judge/progress.json`) and idempotent; returns the dependency facts, the source files that import the dependency (`uses_dependency`) and a compact layout (at most 40 entries) | `src/plugin/project.py` |
| `list_files` | A recursive, sorted, paginated listing under a workspace path, skipping `.git`, `.venv`, `.judge` and caches | `src/plugin/files.py` |
| `read_file` | Up to 200 lines and 8 KB of a UTF-8 file (`truncated` says to continue from the next line) | `src/plugin/files.py` |
| `search` | A regular expression over the files matching a glob under a folder, up to 50 hits | `src/plugin/files.py` |
| `write_file` | Writes 1 to 5 files in one call (60 KB in all), all or none: `pyproject.toml` (only its `[project]` dependencies array may differ from the pristine file) or `.py` files under `src/<package>/`; refuses `tests/`, `README.md`, `uv.lock`, `.judge/` and anything else; returns only each file's path and size | `src/plugin/files.py` |
| `sync` | `uv lock` then `uv sync` into the project's venv, resumable across calls (`complete: false` means call again); a resolution or install failure comes back as `ok: false` with the log's tail | `src/plugin/build.py` |
| `run_build` | `uv build --wheel` into the scratch folder outside the workspace | `src/plugin/build.py` |
| `run_tests` | The project's public tests in its venv, with the project's warning flags (deprecations as errors) and a JSON recorder; counts, failed ids and a 60-line tail | `src/plugin/build.py` |
| `judge` | The trusted final look, in stages that resume across calls (`complete: false` means call again; stage results in `.judge/progress.json` under the hash of the tree they judged): `git status` against the pristine commit, `uv lock --check`, the installed version, the wheel, the pristine public tests restored from the plugin's copy, the hidden tests, a forbidden-pattern scan; when every stage is done it writes `.judge/judgement.json` (`complete: true`) and `.judge/diff.patch`; returns counts and the changed files, nothing about the hidden tests | `src/plugin/judge.py` |

### The projects

Each project under `src/plugin/instances/<project>/` is a src-layout package of
5 to 8 modules with a README, a `pyproject.toml` whose `[project]`
dependencies pin the old major, a `pytest` dev group, a committed `uv.lock`
resolved for Python 3.12, and public `tests/`. The pristine code uses the
APIs that the target version removed or deprecated, so it fails there until it
is migrated; `hidden_tests/` exercise the new version's behaviour on code
paths the public tests leave alone, and `solution.patch` is one migration that
passes everything (used only by this plugin's own tests).

| Project | Dependency | From | To | What breaks |
|---|---|---|---|---|
| `invoicer-pydantic-2` | pydantic (+ `pydantic-settings` allowed) | `>=1.10.13,<2` | 2.14.1 | `regex=`, `const=`, `min_items=`, class `Config`, `@validator`/`@root_validator`, `BaseSettings`, `.dict/.json/.copy/parse_obj/parse_raw/schema`, `__fields__`, implicit `Optional` defaults, int-to-str coercion |
| `ledger-sqlalchemy-2` | SQLAlchemy | `>=1.4.50,<1.5` | 2.1.4 | `MetaData(bind=)`, `engine.execute`, string SQL, `select([...])`, `case([...])`, `Query.get`, `Row["x"]`, `autoload=True`, `ext.declarative.declarative_base`, implicit commits |
| `notes-flask-3` | Flask (+ Werkzeug and the other Pallets packages as collateral) | `>=2.2,<2.3` | 3.1.3 | `flask.json.JSONEncoder`, `app.json_encoder`, `JSON_SORT_KEYS`, `JSON_AS_ASCII`, `before_first_request`, `flask.escape`/`Markup`, `werkzeug.urls.url_quote`, `werkzeug.security.safe_join` |
| `salesreport-pandas-3` | pandas (numpy may move) | `>=2.1,<2.2` | 3.0.6 | `delim_whitespace`, `infer_datetime_format`, `fillna(method=)`, `applymap`, `pd.value_counts`, `"M"` alias, `DataFrame.first`, grouping columns in `groupby.apply`, chained assignment and `inplace` under copy-on-write, `object` dtype checks under the `str` dtype |
| `arrays-numpy-2` | NumPy | `>=1.26,<2` | 2.5.4 | `np.float_`, `np.NaN`, `np.product`, `np.alltrue`, `np.round_`, `np.cumproduct`, `np.asfarray`, `np.string_`/`np.unicode_`, `np.AxisError`, `np.array(copy=False)`, `np.in1d`, `np.trapz`, `np.row_stack`, 2-D `np.cross`, scalar `repr` |

`instance.json` names the dependency, its import name, the package, the old
requirement and locked version, the target, the allowed new dependencies and
collateral, the forbidden patterns (compatibility shims such as
`pydantic.v1`, warning filters, monkeypatching, test sniffing), the warning
flags the tests run with (`-W error::DeprecationWarning`, plus
`FutureWarning` for pandas) and the hidden test ids.
`src/plugin/tools_dev/check_instances.py` is the build-time oracle: the
pristine project passes its public tests on the old version, pristine plus
hidden tests fail, and the project with `solution.patch` passes public and
hidden tests under the warning flags with exactly the target locked.
`src/plugin/tools_dev/make_cases.py` turns each solution into a harness gold
case under `tests/cases/`.

### How the task is judged

The reference, `pin_project`, runs first in a scratch workspace and is pinned.
Every tool call is checked by the verifier's `verify_input`/`verify_output`,
and `verify_task` reads the finished workspace:

1. `.judge/judgement.json` exists, is the project's, says `complete: true`,
   and was judged against the pinned pristine project and hidden tests;
   nothing changed while the judge ran or after it (whole-tree hash). A run
   that ends without it gets "no judgement: call judge last".
2. `tests/**` and `README.md` hash to the pin; `pyproject.toml` and `uv.lock`
   hash to the judgement.
3. Every changed file is `pyproject.toml`, `uv.lock` or a `.py` file under
   `src/<package>/`, hashes to the judgement, and the new files and added
   lines are within the limits (5 files, 600 lines).
4. `pyproject.toml` differs from the pristine file only inside its `[project]`
   dependencies array; `requires-python` is unchanged; the dependency is
   required exactly once, unconditionally, with a specifier that admits the
   target and rejects the old version; every other requirement is as written
   (collateral excepted); additions come from the allowed list; no URL
   requirements.
5. `uv.lock` holds the dependency at exactly the target from PyPI, every other
   direct dependency at its pinned version (collateral excepted), and no
   package from outside PyPI.
6. No forbidden pattern under `src/` (the judgement's scan and the verifier's
   own).
7. Then four outcomes score 0.25 each: `uv lock --check` passed and the
   installed version is the target; the wheel built; the pristine public tests
   passed; the hidden tests collected exactly the pinned ids and passed. The
   verdict is valid only at 1.0.

The verifier parses `pyproject.toml` and `uv.lock` with regular expressions
(`verifier/pyproject.py`) and compares versions with a small PEP 440 reader
(`verifier/versions.py`); the tools use the same modules, so the pin and the
verdict read the files the same way.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs (none here)
├── run.sh           # exits 0 when this environment can run the plugin
├── src/plugin/      # the MCP server (__main__.py), common.py, the tools, runners/, instances/, tools_dev/
├── tests/           # unit tests, verifier tests, an end-to-end stdio test, harness cases under tests/cases/
├── ui/              # the page: app.js, upgrade.js, app.css
├── product/         # product.yaml and icon.svg
└── verifier/        # deterministic verifier package, one module per tool, task.py for the task
```

`contract.py` types every value: the server builds each call's input into its
class and checks its output against its own, and NanoAgent and the verifier
get the same classes. `verifier/` imports only the standard library and
`contract`. Tool outputs never name the plugin's folder; a project's paths are
reported relative to the workspace.

## Develop and run

```bash
uv sync --extra dev
uv run pytest                       # offline; NANOAGENT_NETWORK=1 adds the PyPI-backed tests
uv run python -m plugin.tools_dev.check_instances   # the oracle, needs PyPI
```

From the NanoAgent repository root:

```bash
.venv/bin/nanoagent plugin inspect plugins/dep-upgrade
.venv/bin/python ~/mochi-dev/harness/scripted_task.py plugins/dep-upgrade tests/cases/gold_invoicer-pydantic-2.json
```

## Limitations

- **No OS sandbox on Mochi's hosted runner.** There the plugin runs without a
  sandbox around it: the code the agent writes and the tests that execute it
  run with the plugin's own privileges. The hash-bound judgement and the
  pinned protected-tree digest cover tampering with the project (tests,
  README, lock, files changed during or after judging), but a test that
  rewrote the plugin's own files (its instances, hidden tests or verifier)
  could not be detected by the plugin itself. Sandboxed hosts (NanoAgent's
  bubblewrap or seatbelt sandbox) make the plugin folder read-only and close
  that gap.
- **The hosted runner allows 6 steps, 2048 output tokens per completion and
  $0.10 per run, and members cannot raise them.** A real upgrade needs more:
  the shortest path is `start_project` → `read_file` → `write_file` → `sync`
  → `judge`, with reads and fixes on top, and `start_project`, `sync` and
  `judge` may each need a second call when they run out of their 150-second
  budget on a cold cache. The task is meant for a runner with a higher step
  limit: the member's own computer running Mochi Lab, or NanoAgent locally. A
  run that stops before a complete `judge` gets the verdict "no judgement:
  call judge last".
- **Hidden tests are hidden from the tools, not from code the agent gets
  executed.** The forbidden patterns (pytest and `_pytest` imports,
  `sys.argv`, `atexit`, `os._exit`, `subprocess`, `ctypes`, the word `judge`,
  warning filters, monkeypatching, `sys.modules`) raise the bar, the hidden
  test files are deleted from the run folder after each run, and no output
  names the plugin's folder; the residual risk is the one the plan accepts.
- **Targets are fixed releases** (the latest when the plugin was built): the
  agent must lock exactly the pinned target, so a newer release on PyPI does
  not change the task.
- **Nothing heavy in the workspace.** The host syncs the whole workspace back into the
  member's agent folder and refuses files over 10 MB, so the project's venv (NumPy alone
  carries a 25 MB OpenBLAS), its wheels, the test run folders and the subprocess HOME live
  outside the workspace, under `<tmp>/nanoagent-dep-upgrade-<sha256 of the workspace path>/`
  (the sandbox home under the macOS sandbox, `/tmp` on the hosted runner). The workspace holds
  only the project tree, its `.git` and `.judge/` (the record files). A later process that finds
  the scratch folder gone rebuilds the venv from `uv.lock` inside the next tool call's budget
  (the call returns `complete: false` and asks to be called again when the rebuild does not
  fit); scratch folders of other workspaces untouched for 12 hours are removed. No tool leaves a
  file over 8 MB in the workspace: every writing tool checks and refuses with a clear error.
- **Budgets.** Every tool call stays under 150 s and every output under about
  1 500 tokens (reads of 200 lines or 8 KB, 50 search hits, 60-line tails of
  200 characters); the projects' modules are at most ~110 lines so a rewritten
  module fits in one completion.
