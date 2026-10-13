// The dep-upgrade page's own pieces: what each project is, how a run's tool calls map to the
// steps, the four check rows, the changed-file diffs read from the workspace, the verdict and the
// error wording. Pure functions where feasible; views at the end.

import { banner, disclosure, h, icon, statusPill } from "./kit/components.js";

/** The shipped projects, as the picker and the result card describe them (mirrors instance.json). */
export const PROJECTS = {
  "invoicer-pydantic-2": { name: "invoicer", library: "pydantic", from: "1.10.13", to: "2.14.1", breaks: "validators, class Config, BaseSettings, .dict() and .json()" },
  "ledger-sqlalchemy-2": { name: "ledger", library: "SQLAlchemy", from: "1.4.54", to: "2.1.4", breaks: "engine.execute, select([...]), Query.get, row[\"column\"]" },
  "notes-flask-3": { name: "notes", library: "Flask", from: "2.2.5", to: "3.1.3", breaks: "json_encoder, before_first_request, flask.escape, werkzeug.urls" },
  "salesreport-pandas-3": { name: "salesreport", library: "pandas", from: "2.1.4", to: "3.0.6", breaks: "applymap, fillna(method=), the \"M\" alias, copy-on-write" },
  "arrays-numpy-2": { name: "arrays", library: "NumPy", from: "1.26.4", to: "2.5.4", breaks: "np.float_, np.NaN, np.product, np.trapz, np.in1d" },
};

const CHECK_LABELS = {
  version: "Target version locked and installed",
  build: "Wheel builds",
  public_tests: "Public tests pass",
  hidden_tests: "Hidden tests pass",
};
const MAX_DIFF_LINES = 400;

/** "1.10.13" -> "1.10" for a picker label. */
const minor = (version) => version.split(".").slice(0, 2).join(".");

/** What the page says about a project id, with a fallback for an id this page does not know. */
export function describeProject(id) {
  const known = PROJECTS[id];
  if (!known) {
    const [name, ...rest] = id.split("-");
    return { id, name, library: rest.join(" ") || id, from: "", to: "", breaks: "", label: id, caption: `Upgrade the project ${id}.` };
  }
  return {
    id,
    ...known,
    label: `${known.name} · ${known.library} ${minor(known.from)} → ${minor(known.to)}`,
    caption: `Raises ${known.library} from ${known.from} to ${known.to} in the ${known.name} project and migrates the code that breaks: ${known.breaks}.`,
  };
}

// ----- Progress -----

/**
 * What a `task.tool` event means for the progress card. `progress` is the run's running tally
 * (mutated): files read, files written, the last test counts.
 * @returns {{step: string, state?: string, detail?: string, note?: string}}
 */
export function progressFromTool(tool, data, progress) {
  switch (tool.name) {
    case "start_project":
      progress.dependency = data?.dependency ?? progress.dependency;
      progress.current = data?.current_version ?? progress.current;
      progress.target = data?.target_version ?? progress.target;
      if (data && data.complete === false) return { step: "setup", detail: "Still installing the project; the agent calls again" };
      return { step: "setup", state: "done", detail: data ? `${data.dependency} ${data.current_version} installed; target ${data.target_version}` : undefined };
    case "list_files":
    case "read_file":
    case "search":
      progress.reads += 1;
      return { step: "read", detail: `${progress.reads} ${progress.reads === 1 ? "look" : "looks"} at the code` };
    case "write_file":
      for (const item of data?.written ?? []) progress.written.add(item.path.split("/").slice(2).join("/"));
      return { step: "work", detail: `${progress.written.size} ${progress.written.size === 1 ? "file" : "files"} changed` };
    case "sync": {
      const version = data?.installed?.[progress.dependency];
      if (data && data.complete === false) return { step: "work", detail: "Still locking and installing; the agent calls again" };
      return { step: "work", detail: data?.ok ? `Locked and installed ${progress.dependency} ${version ?? ""}`.trim() : "The new requirement did not resolve; the agent is adjusting it" };
    }
    case "run_build":
      return { step: "work", detail: data?.ok ? "Wheel built" : "The build failed; the agent is fixing it" };
    case "run_tests": {
      if (data) progress.tests = { passed: data.passed, collected: data.collected };
      const detail = data ? `${data.passed} of ${data.collected} public tests pass` : undefined;
      return { step: "work", detail };
    }
    case "judge":
      if (data && data.complete === false) return { step: "check", detail: "Judging in stages; the agent calls again", progress: "indeterminate" };
      return { step: "check", detail: data ? `${data.changed_files.length} changed ${data.changed_files.length === 1 ? "file" : "files"}, ${data.public_passed} public tests passed` : undefined };
    default:
      return { step: "work" };
  }
}

/** A muted progress note for a tool call that failed (the agent usually retries). */
export function failedCallNote(tool) {
  const text = String(tool.output ?? "");
  if (tool.name === "write_file") return "A write was refused (only the dependency and the package's code may change); the agent retried.";
  if (tool.name === "start_project") return `Setting up the project failed: ${text.slice(0, 160)}`;
  return "One step failed; the agent retried.";
}

// ----- Verdict -----

/**
 * The four check rows (and the structure gate) from a verdict's details, in display order; each
 * `{id, label, ok, message}`. A verdict without details gets four unknown rows.
 */
export function checksFromVerdict(verdict) {
  const given = Array.isArray(verdict?.details?.checks) ? verdict.details.checks : [];
  const byId = Object.fromEntries(given.map((check) => [check.id, check]));
  const rows = Object.entries(CHECK_LABELS).map(([id, label]) => ({ id, label, ok: byId[id]?.ok ?? null, message: byId[id]?.message ?? "" }));
  const structure = byId.structure;
  if (structure && structure.ok === false) rows.unshift({ id: "structure", label: "Only allowed changes, nothing touched afterwards", ok: false, message: structure.message });
  return rows;
}

/** The verdict in this page's words. */
export function verdictWords(verdict, project) {
  const details = verdict.details ?? {};
  if (verdict.valid) {
    return { tone: "ok", title: `Checked. ${project.library} is at ${project.to}, the wheel builds and every public and hidden test passes.`, score: "" };
  }
  const violations = Array.isArray(details.violations) ? details.violations : [];
  if (violations.length) {
    return {
      tone: "bad",
      title: "Not accepted: the change broke the rules.",
      body: "The checks below were not scored because the structure gate failed.",
      lines: violations.slice(0, 6),
      score: "",
    };
  }
  const failed = checksFromVerdict(verdict).filter((row) => row.ok === false);
  return {
    tone: "warn",
    title: failed.length ? `Not done: ${failed.map((row) => row.label.toLowerCase()).join("; ")}.` : "The result could not be accepted.",
    body: typeof verdict.score === "number" ? `${Math.round(verdict.score * 100)}% of the checks held.` : undefined,
    lines: failed.map((row) => `${row.label}: ${row.message}`),
    score: "",
  };
}

/** Known task errors in plain words, tried before the kit's common ones. */
export const ERROR_RULES = [
  { id: "cancelled", match: (message) => message === "cancelled", text: "Stopped. Nothing new was saved.", tone: "neutral" },
  { id: "setup", match: /could not (create|install)/i, text: "The project could not be installed: PyPI was not reachable or the install timed out. Try again in a minute." },
  { id: "unknown", match: /unknown project/, text: "This page's list of projects is out of date; pick another project." },
  { id: "input", match: "invalid input", text: "That project isn't one this plugin ships." },
];

// ----- Diffs -----

/**
 * A unified diff as files: `{path, status, added, removed, lines: [{kind, text}]}` with kinds
 * `add`, `del`, `ctx` and `hunk`. Header lines are dropped; a new file reads as `added`.
 */
export function parseDiff(text) {
  const files = [];
  let current = null;
  for (const line of String(text ?? "").split("\n")) {
    if (line.startsWith("diff --git ")) {
      const path = line.split(" b/")[1] ?? line.slice(11);
      current = { path, status: "modified", added: 0, removed: 0, lines: [] };
      files.push(current);
      continue;
    }
    if (!current) continue;
    if (line.startsWith("new file mode")) current.status = "added";
    else if (line.startsWith("deleted file mode")) current.status = "deleted";
    else if (line.startsWith("+++ ") || line.startsWith("--- ") || line.startsWith("index ")) continue;
    else if (line.startsWith("@@")) current.lines.push({ kind: "hunk", text: line });
    else if (line.startsWith("+")) {
      current.added += 1;
      current.lines.push({ kind: "add", text: line.slice(1) });
    } else if (line.startsWith("-")) {
      current.removed += 1;
      current.lines.push({ kind: "del", text: line.slice(1) });
    } else if (line.startsWith(" ")) current.lines.push({ kind: "ctx", text: line.slice(1) });
  }
  return files.filter((file) => file.path !== "/dev/null");
}

// ----- Views -----

function checkRows(rows) {
  return h(
    "ul",
    { class: "checks", "aria-label": "Checks" },
    rows.map((row) =>
      h(
        "li",
        { class: `check ${row.ok === true ? "check-ok" : row.ok === false ? "check-bad" : "check-unknown"}` },
        statusPill(row.ok === true ? "Passed" : row.ok === false ? "Failed" : "Not run", row.ok === true ? "ok" : row.ok === false ? "bad" : "neutral", { icon: true }),
        h("span", { class: "check-label", text: row.label }),
        row.ok === false && row.message && row.message !== "ok" ? h("span", { class: "check-message muted small-text", text: row.message }) : null,
      ),
    ),
  );
}

function diffView(file) {
  const shown = file.lines.slice(0, MAX_DIFF_LINES);
  const rows = shown.map((line) =>
    h("div", { class: `diff-line diff-${line.kind}` }, h("span", { class: "diff-sign", "aria-hidden": "true", text: line.kind === "add" ? "+" : line.kind === "del" ? "−" : " " }), h("span", { class: "diff-text", text: line.text })),
  );
  const more = file.lines.length > shown.length ? h("p", { class: "muted small-text", text: `${file.lines.length - shown.length} more lines not shown.` }) : null;
  return h("div", { class: "diff", role: "group", "aria-label": `Changes to ${file.path}` }, rows, more);
}

function changedFiles(files, changedPaths) {
  const listed = files.length ? files : changedPaths.map((path) => ({ path, status: "modified", added: 0, removed: 0, lines: [] }));
  if (!listed.length) return h("p", { class: "muted", text: "No file was changed." });
  return h(
    "div",
    { class: "changed-files" },
    listed.map((file) =>
      disclosure(
        {
          summary: h("span", { class: "changed-summary" }, h("code", { class: "changed-path", text: file.path }), h("span", { class: `pill tone-${file.status === "added" ? "info" : file.status === "deleted" ? "bad" : "neutral"}`, text: file.status })),
          hint: file.lines.length ? `+${file.added} −${file.removed}` : "no diff available",
        },
        file.lines.length ? diffView(file) : h("p", { class: "muted small-text", text: "The judge's diff for this file could not be read." }),
      ),
    ),
  );
}

/**
 * The result card of one run.
 * @param {{project: object, verdict: object, answer?: string, diffText?: string, error?: string}} run
 */
export function resultCard({ project, verdict, answer, diffText, error }) {
  const words = verdict ? verdictWords(verdict, project) : null;
  const headline = verdict?.valid ? `${project.name} now runs on ${project.library} ${project.to}` : `${project.name}: the upgrade to ${project.library} ${project.to} is not accepted`;
  const changed = Array.isArray(verdict?.details?.changed_files) ? verdict.details.changed_files.map((entry) => String(entry).replace(/ \(\w+\)$/, "")) : [];
  const parts = [
    h("header", { class: "result-head" }, h("h2", { class: "result-headline", text: headline }), h("p", { class: "muted result-sub" }, icon("package", { size: 16 }), `${project.library} ${project.from} → ${project.to}`)),
    verdict ? banner({ tone: words.tone, title: words.title, body: words.body, lines: words.lines }) : banner({ tone: "bad", title: "The run ended without a verdict.", body: error ?? "" }),
    verdict ? checkRows(checksFromVerdict(verdict)) : null,
    h("h3", { class: "result-section", text: "What changed" }),
    changedFiles(parseDiff(diffText), changed),
    answer ? disclosure({ summary: "The agent's report" }, h("p", { class: "prose", text: answer })) : null,
    disclosure(
      { summary: "How this was checked" },
      h(
        "ul",
        { class: "about-list" },
        h("li", { text: "The judge re-locked nothing itself: it checked that the lock matches pyproject.toml, read the installed version, built the wheel, and ran the public tests from a pristine copy and the hidden tests in the project's own environment." }),
        h("li", { text: "The verifier then recomputed every file hash, parsed pyproject.toml and uv.lock on its own, and refused shims (compatibility layers, warning filters, monkeypatching) and any change outside the dependency and the package's code." }),
        h("li", { text: "Only a run that holds on all four checks counts as done." }),
      ),
    ),
  ];
  return h("section", { class: "card large result-card", "aria-label": headline }, parts);
}
