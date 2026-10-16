// How this plugin's page draws the upgrade-dependency task's output, an UpgradeReportOutput: the
// upgrade as submitted, every check the verifier made (verdict.details.constraints), the agent's
// migration notes, the changed files with their diffs, and where the answer key came from.
// Everything shown comes from the output and the verdict.
import { disclosure, h, icon } from "./kit/components.js";

const MAX_DIFF_LINES = 400;

/** A check's expected or actual value as short text: lists joined, mappings as "key value" pairs. */
function valueText(value) {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length ? value.map(valueText).join(", ") : "none";
  if (typeof value === "object") {
    const pairs = Object.entries(value);
    return pairs.length ? pairs.map(([key, item]) => `${key} ${valueText(item)}`).join("; ") : "none";
  }
  return String(value);
}

const clipped = (text, most = 240) => (text.length > most ? `${text.slice(0, most - 1)}…` : text);
const MARK = { ok: ["check", "holds"], bad: ["error", "fails"], skip: ["minus", "not checked"] };

/** The verdict's checks, in order: ✓ holds; ✗ fails, with why and what was expected against what was
 *  found; – not checked, with the earlier check it needed. */
function checksList(verdict) {
  const constraints = Array.isArray(verdict?.details?.constraints) ? verdict.details.constraints : [];
  if (!constraints.length) return null;
  const failed = constraints.filter((entry) => entry.ok === false).length;
  const skipped = constraints.filter((entry) => entry.ok !== true && entry.ok !== false).length;
  const items = constraints.map((entry) => {
    const state = entry.ok === true ? "ok" : entry.ok === false ? "bad" : "skip";
    const [mark, word] = MARK[state];
    const values = entry.ok === false && entry.expected != null && entry.actual != null;
    return h(
      "li",
      { class: `check check-${state}` },
      h("div", { class: "check-head" }, icon(mark, { size: 14, label: word }), h("span", { text: entry.constraint }), h("code", { class: "check-id", text: entry.id })),
      entry.ok !== true && entry.message ? h("p", { class: "check-message small-text", text: entry.message }) : null,
      values
        ? h(
            "p",
            { class: "check-values small-text" },
            h("span", { class: "muted", text: "Expected: " }),
            clipped(valueText(entry.expected)),
            h("span", { class: "muted", text: " · Actual: " }),
            clipped(valueText(entry.actual)),
          )
        : null,
    );
  });
  const hint = [failed ? `${failed} failed` : "", skipped ? `${skipped} not checked` : ""].filter(Boolean).join(", ") || "all hold";
  return disclosure(
    { summary: `Checks: ${constraints.length - failed - skipped} of ${constraints.length} hold`, open: failed > 0, hint },
    h("ol", { class: "checks" }, items),
  );
}

/** Unified diff lines (as difflib writes them) as files: {path, added, removed, lines}. */
export function parseDiff(lines) {
  const files = [];
  let current = null;
  for (const line of lines ?? []) {
    if (line.startsWith("--- ")) continue;
    if (line.startsWith("+++ ")) {
      current = { path: line.slice(4).replace(/^b\//, ""), added: 0, removed: 0, lines: [] };
      files.push(current);
      continue;
    }
    if (!current) continue;
    if (line.startsWith("@@")) current.lines.push({ kind: "hunk", text: line });
    else if (line.startsWith("+")) {
      current.added += 1;
      current.lines.push({ kind: "add", text: line.slice(1) });
    } else if (line.startsWith("-")) {
      current.removed += 1;
      current.lines.push({ kind: "del", text: line.slice(1) });
    } else current.lines.push({ kind: "ctx", text: line.slice(1) });
  }
  return files;
}

function diffView(file) {
  const shown = file.lines.slice(0, MAX_DIFF_LINES);
  return h(
    "div",
    { class: "diff", role: "group", "aria-label": `Changes to ${file.path}` },
    shown.map((line) =>
      h(
        "div",
        { class: `diff-line diff-${line.kind}` },
        h("span", { class: "diff-sign", "aria-hidden": "true", text: line.kind === "add" ? "+" : line.kind === "del" ? "−" : " " }),
        h("span", { class: "diff-text", text: line.text }),
      ),
    ),
  );
}

function changedFiles(paths, diffLines) {
  const parsed = parseDiff(diffLines);
  const byPath = Object.fromEntries(parsed.map((file) => [file.path, file]));
  if (!paths.length) return h("p", { class: "muted", text: "No file was changed." });
  return h(
    "div",
    { class: "changed-files" },
    paths.map((path) => {
      const file = byPath[path];
      return disclosure(
        { summary: h("code", { class: "changed-path", text: path }), hint: file ? `+${file.added} −${file.removed}` : "no diff in the verdict" },
        file ? diffView(file) : h("p", { class: "muted small-text", text: "The verdict holds no diff for this file." }),
      );
    }),
  );
}

function provenance(details) {
  const source = details.provenance ?? {};
  const items = [
    source.upstream_commit ? h("li", {}, "Upstream's own upgrade: ", h("a", { href: source.upstream_commit, target: "_blank", rel: "noopener noreferrer", text: source.upstream_commit })) : null,
    source.base_commit ? h("li", { text: `Checked out at the commit before it: ${source.base_commit}` }) : null,
    source.pypi_files?.length ? h("li", { text: `Target files from PyPI: ${source.pypi_files.join(", ")}` }) : null,
    source.resolution_date ? h("li", { text: `Every lock is resolved as of ${source.resolution_date}` }) : null,
    details.fit ? h("li", { text: details.fit === "hosted" ? "Measured to fit a hosted run." : "Local runner only: set-up and judging take longer than a hosted run allows." }) : null,
  ].filter(Boolean);
  return items.length ? disclosure({ summary: "Where the answer key comes from" }, h("ul", { class: "about-list" }, items)) : null;
}

function upgradeCard(output, { verdict } = {}) {
  const details = verdict?.details ?? {};
  const failedPublic = details.failed_tests?.public ?? [];
  return h(
    "section",
    { class: "upgrade-card" },
    h(
      "header",
      { class: "upgrade-head" },
      h("p", { class: "upgrade-title" }, icon("file", { size: 18 }), h("span", { text: `${output.dependency} ${output.from_version} → ${output.to_version}` })),
      h("p", { class: "muted small-text", text: `${details.repository ?? output.instance} · requirement ${output.requirement}` }),
    ),
    checksList(verdict),
    output.migration.length ? h("div", { class: "upgrade-section" }, h("h4", { text: "What the agent changed" }), h("ul", { class: "notes" }, output.migration.map((note) => h("li", { text: note })))) : null,
    h("div", { class: "upgrade-section" }, h("h4", { text: `Changed files (${output.changed_files.length})` }), changedFiles(output.changed_files, details.diff)),
    failedPublic.length ? disclosure({ summary: `Failing tests (${failedPublic.length})` }, h("ul", { class: "notes mono" }, failedPublic.map((test) => h("li", { text: test })))) : null,
    provenance(details),
  );
}

export default { UpgradeReportOutput: upgradeCard };
