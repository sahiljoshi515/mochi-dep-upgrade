// How this plugin's page draws the upgrade-dependency task's output, an UpgradeReportOutput: the
// upgrade as submitted, every check the verifier made (verdict.details.constraints) with its
// outcome in words, the agent's migration notes, the changed files with their diffs, and where the
// answer key came from. Everything shown comes from the output and the verdict.
import { disclosure, h, icon, statusPill } from "./kit/components.js";

const MAX_DIFF_LINES = 400;

/** A check's state as a word and a tone: held, failed, or not checked. */
function checkState(ok) {
  if (ok === true) return ["Held", "ok"];
  if (ok === false) return ["Failed", "bad"];
  return ["Not checked", "neutral"];
}

function checkList(constraints) {
  return h(
    "ol",
    { class: "checks", "aria-label": "Checks" },
    constraints.map((item) => {
      const [word, tone] = checkState(item.ok);
      return h(
        "li",
        { class: `check check-${tone}` },
        statusPill(word, tone, { icon: true }),
        h("span", { class: "check-label", text: item.constraint }),
        item.ok !== true && item.message ? h("span", { class: "check-message muted small-text", text: item.message }) : null,
      );
    }),
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

function upgradeCard(output, { verdict }) {
  const details = verdict?.details ?? {};
  const constraints = Array.isArray(details.constraints) ? details.constraints : [];
  const held = constraints.filter((item) => item.ok === true).length;
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
    constraints.length
      ? h("div", { class: "upgrade-section" }, h("h4", { text: `Checks: ${held} of ${constraints.length} held` }), checkList(constraints))
      : null,
    output.migration.length ? h("div", { class: "upgrade-section" }, h("h4", { text: "What the agent changed" }), h("ul", { class: "notes" }, output.migration.map((note) => h("li", { text: note })))) : null,
    h("div", { class: "upgrade-section" }, h("h4", { text: `Changed files (${output.changed_files.length})` }), changedFiles(output.changed_files, details.diff)),
    failedPublic.length ? disclosure({ summary: `Failing tests (${failedPublic.length})` }, h("ul", { class: "notes mono" }, failedPublic.map((test) => h("li", { text: test })))) : null,
    provenance(details),
  );
}

export default { UpgradeReportOutput: upgradeCard };
