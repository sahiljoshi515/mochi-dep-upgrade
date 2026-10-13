// The dep-upgrade page: pick a project, let the agent raise one library to its target version and
// migrate the code, and see the judge's four checks with the changed files. The chat with the
// plugin's agent lives in a drawer. Mirrors plugins/nasdaq-drawdown/ui/app.js.

import { announce, appShell, card, errorCard, explainError, h, howItWorks, icon, parseToolOutput, readText, runButton, segmented, skeleton, taskRun } from "./kit/components.js";
import { ERROR_RULES, PROJECTS, describeProject, failedCallNote, progressFromTool, resultCard } from "./upgrade.js";

const TASK = "upgrade-dependency";

const STEPS = [
  { id: "pin", label: "Preparing the answer key" },
  { id: "setup", label: "Setting up the project" },
  { id: "read", label: "Agent reading the code" },
  { id: "work", label: "Agent changing and testing" },
  { id: "check", label: "Checking version, build and tests" },
];

export default async function page({ plugin }) {
  const task = plugin.tasks.find((one) => one.id === TASK);
  if (!task) throw new Error("This version of Dependency Upgrade no longer offers the upgrade task this page is built around.");
  const ids = task.inputSchema?.properties?.project?.enum ?? Object.keys(PROJECTS);
  if (!ids.length) throw new Error("This version of Dependency Upgrade ships no project to upgrade.");

  let progress = null; // what the current run has told the page so far
  let shown = null; // the project whose result is on the page

  // ----- Chat -----

  const suggestionsFor = (id) => {
    const project = describeProject(id);
    return [
      `What changed between ${project.library} ${project.from} and ${project.to} that would break ${project.name}?`,
      `Which files of ${project.name} use ${project.library} directly?`,
      "What may the upgrade change, and what is protected?",
    ];
  };
  const shell = appShell({
    plugin,
    chat: {
      intro: h("div", { class: "chat-intro small" }, h("img", { src: plugin.product.icon, alt: "" }), h("p", { class: "muted", text: "Ask about a project, a library's breaking changes, or how the check works." })),
      note: "Answers here are not checked; the result on the page is.",
      placeholder: "Ask about the upgrade",
      suggestions: suggestionsFor(ids[0]),
      prepare: (text) => (shown ? `(I'm looking at the ${shown.name} project, ${shown.library} ${shown.from} to ${shown.to}.)\n\n${text}` : text),
    },
  });

  // ----- Project picker -----

  const caption = h("p", { class: "muted small-text picker-caption", text: describeProject(ids[0]).caption });
  const picker = segmented({
    label: "Project",
    options: ids.map((id) => ({ value: id, label: describeProject(id).label })),
    look: "chips",
    showLabel: true,
    onChange: (id) => {
      caption.textContent = describeProject(id).caption;
      shell.drawer.chat.setSuggestions(suggestionsFor(id));
    },
  });

  const run = taskRun({ task: TASK, title: "Upgrading", steps: STEPS, onEvent: track, onFinish: finished });
  run.element.tabIndex = -1;
  const go = runButton({
    label: "Upgrade it",
    run,
    block: true,
    onClick: () => start(picker.value()),
    note: "Takes a few minutes: the project is installed as it is, the agent re-locks and migrates it, then the judge rebuilds and runs every test. Keep this page open.",
  });
  run.subscribe((busy) => picker.setDisabled(busy));

  const pickerCard = card({ title: "Pick a project", className: "picker-card" }, picker.element, caption, go.element);

  // ----- Results -----

  const result = h("div", { class: "result-area" });
  const intro = card({ className: "intro-card" }, h("p", { class: "intro-summary", text: plugin.product.summary }), howItWorks(plugin.product.steps));

  function show(...nodes) {
    intro.hidden = true;
    result.classList.remove("stale");
    result.replaceChildren(...nodes);
  }

  function start(id) {
    if (run.busy) return;
    picker.set(id);
    progress = { id, project: describeProject(id), dependency: "", current: "", target: "", reads: 0, written: new Set(), tests: null };
    if (shown && result.firstChild) result.classList.add("stale");
    else show(h("div", { class: "card large" }, skeleton({ lines: 4, block: true })));
    run.start({ project: id });
    run.element.focus({ preventScroll: true });
    run.element.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }

  function track(name, data, controller) {
    switch (name) {
      case "task.started":
      case "task.reference":
        controller.step("pin", { detail: "Pinning the pristine project, its lock and the hidden tests.", progress: "indeterminate" });
        break;
      case "task.tool":
        trackTool(data, controller);
        break;
      case "task.answer":
        controller.step("check", { detail: "Reading the judge's record" });
        break;
    }
  }

  function trackTool(tool, controller) {
    const parsed = parseToolOutput(tool.output);
    const data = tool.isError || !parsed?.ok ? null : parsed;
    if (data === null) {
      controller.note(failedCallNote(tool));
      return;
    }
    const { step, state, detail } = progressFromTool(tool, data, progress);
    controller.step(step, { state, detail });
  }

  async function finished(outcome) {
    const { id, project } = progress;
    shown = project;
    let diffText = "";
    if (outcome.verdict) {
      try {
        diffText = await readText(`dep-upgrade/${id}/.judge/diff.patch`);
      } catch {
        diffText = "";
      }
      const card = resultCard({ project, verdict: outcome.verdict, answer: outcome.answer, diffText });
      show(card);
      announce(card.getAttribute("aria-label"));
      return;
    }
    const message = outcome.error ?? "The run ended without checking the upgrade.";
    const again = h("button", { type: "button", class: "button small", onclick: () => start(id) }, icon("refresh", { size: 15 }), "Run again");
    show(errorCard({ message, rules: ERROR_RULES, title: outcome.startFailed ? "Couldn't start" : undefined, actions: [again] }));
    announce(explainError(message, ERROR_RULES).text);
  }

  shell.main.append(pickerCard, run.element, result, intro);
  return shell.element;
}
