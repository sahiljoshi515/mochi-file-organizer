// The File Organizer page: pick a seed and a size, let the agent tidy the messy folder it makes,
// and see every file where the rules put it, with the check's verdict. The chat with the agent
// lives in a drawer. Mirrors plugins/nasdaq-drawdown/ui/app.js.

import { announce, appShell, banner, card, dataTable, disclosure, errorCard, explainError, h, howItWorks, icon, listFiles, numberStepper, plural, runButton, segmented, skeleton, statusPill, taskRun, verdictBanner } from "./kit/components.js";
import { ERROR_RULES, SEED_MAX, SEED_MIN, SIZES, countsFrom, problemKinds, problemRows, progressFrom, renderTree, rootFor, sizeOf, treeFrom, verdictWords } from "./organizer.js";

const TASK = "organize";
const STEPS = [
  { id: "make", label: "Making the messy folder" },
  { id: "inspect", label: "Agent inspecting files" },
  { id: "sort", label: "Agent moving and deleting" },
  { id: "check", label: "Checking every file" },
];

export default async function page({ plugin }) {
  // These cannot be recovered from on the page; the message reaches a reader.
  const task = plugin.tasks.find((one) => one.id === TASK);
  if (!task) throw new Error("This version of File Organizer no longer offers the tidying task this page is built around.");
  const properties = task.inputSchema?.properties ?? {};
  if (!properties.seed || !properties.size) throw new Error("This version of File Organizer no longer takes a seed and a size, which this page asks for.");

  let progress = null; // what the current run has told the page so far
  let shown = null; // the run the result card shows

  // ----- Chat -----

  const shell = appShell({
    plugin,
    chat: {
      intro: h("div", { class: "chat-intro small" }, h("img", { src: plugin.product.icon, alt: "" }), h("p", { class: "muted", text: "Ask how the rules decide a file's place, or what went wrong in a run." })),
      note: "The agent can look at the folder and explain the rules. Answers here are not checked; the result on the page is.",
      placeholder: "Ask about the rules or a file",
      suggestions: ["How is a duplicate decided?", "Which date wins when a photo has EXIF and a date in its name?", "What does the slug of \"Résumé (1).pdf\" look like?"],
      prepare: (text) => (shown ? `(I'm looking at the folder ${shown.root}, tidied by the last run.)\n\n${text}` : text),
    },
  });

  // ----- Picker -----

  const seed = numberStepper({ label: "Seed", value: 1, min: SEED_MIN, max: SEED_MAX, hint: "The same seed and size always make the same messy folder.", onChange: refreshNote });
  const size = segmented({ label: "Size", showLabel: true, value: SIZES[0].value, options: SIZES.map((one) => ({ value: one.value, label: `${one.label} · ${one.files} files` })), onChange: refreshNote });
  const run = taskRun({ task: TASK, title: "Tidying the folder", steps: STEPS, onEvent: track, onFinish: finished });
  run.element.tabIndex = -1;
  const go = runButton({ label: "Tidy the folder", run, block: true, onClick: () => start(), note: noteFor() });
  run.subscribe((busy) => {
    seed.setDisabled(busy);
    size.setDisabled(busy);
  });
  const pickerCard = card({ title: "Pick a mess", className: "picker-card" }, h("div", { class: "picker-grid" }, seed.element, size.element, go.element));

  function noteFor() {
    const chosen = sizeOf(size?.value?.() ?? SIZES[0].value);
    const budget = chosen.value === "small" ? " Designed to take 4 tool calls and the answer, inside the 6 agent steps Mochi's hosted runner allows: one to make and list the folder, three to tidy 15 files each." : " Medium and large need a runner with a higher step limit, such as your own computer.";
    return `Makes ${chosen.files} files, with duplicates, junk and misnamed files, in ${rootFor(seed?.value?.() ?? 1, chosen.value)}. Takes a few minutes.${budget}`;
  }
  function refreshNote() {
    go.element.querySelector(".muted.small-text").textContent = noteFor();
  }

  // ----- Results -----

  const result = h("div", { class: "result-area" });
  const intro = card({ className: "intro-card" }, h("p", { class: "intro-summary", text: plugin.product.summary }), howItWorks(plugin.product.steps));

  function show(...nodes) {
    intro.hidden = true;
    result.classList.remove("stale");
    result.replaceChildren(...nodes);
  }

  function start() {
    if (run.busy) return;
    const chosen = { seed: seed.value(), size: size.value() };
    progress = { ...chosen, root: rootFor(chosen.seed, chosen.size) };
    if (shown && result.firstChild) result.classList.add("stale");
    else show(h("div", { class: "card large" }, skeleton({ lines: 3, block: true })));
    run.start(chosen);
    run.element.focus({ preventScroll: true });
    run.element.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }

  function track(name, data, controller) {
    switch (name) {
      case "task.started":
      case "task.reference":
        controller.step("make", { detail: "Preparing the answer key: the same folder, tidied by the rules.", progress: "indeterminate" });
        break;
      case "task.tool":
        trackTool(data, controller);
        break;
      case "task.answer":
        controller.step("check", { progress: "indeterminate" });
        break;
    }
  }

  function trackTool(tool, controller) {
    progress.tools = [...(progress.tools ?? []), { ...tool, data: tool.isError ? null : parseToolOutput(tool.output) }];
    const state = progressFrom(progress.tools);
    if (tool.isError) {
      controller.note(failedCallNote(tool));
      return;
    }
    if (tool.name === "unpack_inbox") {
      controller.step("make", { state: "done", detail: `${plural(state.files ?? 0, "file")} in ${plural(state.dirs ?? 0, "folder")}` });
      controller.step("inspect", { detail: state.total ? `${state.listed} of ${state.total} files listed with the rules` : "Read the rules", progress: state.total ? state.listed / state.total : "indeterminate" });
    } else if (tool.name === "read_rules") {
      controller.step("inspect", { detail: "Read the rules", progress: "indeterminate" });
    } else if (tool.name === "inventory") {
      controller.step("inspect", { detail: state.total ? `${state.listed} of ${state.total} files listed` : `${state.listed} files listed`, progress: state.total ? state.listed / state.total : "indeterminate" });
    } else if (tool.name === "apply_plan") {
      const failed = state.failed ? ` · ${plural(state.failed, "item")} refused` : "";
      controller.step("sort", { detail: `${state.moved} moved, ${state.deleted} deleted${failed}`, progress: state.files ? Math.min(1, (state.moved + state.deleted) / state.files) : "indeterminate" });
    } else if (tool.name === "list_tree") {
      controller.step("sort", { detail: `${state.moved} moved, ${state.deleted} deleted · looking over the result` });
    }
  }

  function failedCallNote(tool) {
    if (tool.name === "apply_plan") return "One batch of moves was refused; the agent retried.";
    if (tool.name === "inventory") return "One listing failed; the agent retried.";
    return "One step failed; the agent retried.";
  }

  async function finished(outcome) {
    const { root, seed: usedSeed, size: usedSize } = progress;
    if (outcome.verdict) {
      shown = { root, seed: usedSeed, size: usedSize, verdict: outcome.verdict, answer: outcome.answer, state: progressFrom(progress.tools ?? []) };
      show(await resultCard(shown));
      announce(result.firstChild.getAttribute("aria-label"));
      return;
    }
    shown = null;
    const message = outcome.error ?? "The run ended without checking the folder.";
    const again = h("button", { type: "button", class: "button small", onclick: () => start() }, icon("refresh", { size: 15 }), "Run again");
    show(errorCard({ message, rules: ERROR_RULES, title: outcome.startFailed ? "Couldn't start" : undefined, actions: [again] }));
    announce(explainError(message, ERROR_RULES).text);
  }

  async function resultCard(view) {
    const counts = countsFrom(view.verdict);
    const words = verdictWords(view.verdict);
    const rows = problemRows(view.verdict);
    const headline = view.verdict.valid
      ? `All ${counts.unique ?? ""} files are in place`.replace("  ", " ")
      : counts.placed !== null && counts.unique !== null
        ? `${counts.placed} of ${counts.unique} files are in place`
        : "The folder could not be checked";
    const chosen = sizeOf(view.size);

    const tiles = h(
      "div",
      { class: "tiles" },
      tile(counts.files, "files to start with"),
      tile(counts.unique, "to keep and file"),
      tile(counts.duplicates, "duplicate copies to delete"),
      tile(counts.removed, "junk and empty files to delete"),
    );

    let tree;
    try {
      const prefix = `${view.root}/organized/`;
      const files = await listFiles({ prefix });
      const node = treeFrom(files, prefix);
      tree = files.length
        ? disclosure({ summary: "The organized folder", hint: plural(files.length, "file"), open: true, className: "tree-disclosure" }, renderTree(node))
        : banner({ tone: "neutral", title: "organized/ is empty.", live: false });
    } catch (problem) {
      tree = banner({ tone: "warn", title: "The organized folder couldn't be listed.", body: problem.message, live: false });
    }

    const table = rows.length
      ? disclosure(
          { summary: "What went wrong, file by file", hint: plural(rows.length, "problem"), open: rows.length <= 12, className: "problems" },
          h("p", { class: "muted small-text legend" }, problemKinds().map((kind) => h("span", { class: "legend-item", title: kind.explain }, statusPill(kind.word, kind.tone), " ", kind.explain))),
          dataTable({
            columns: [
              { key: "word", label: "Problem", primary: true, render: (row) => statusPill(row.word, row.tone) },
              { key: "path", label: "Where it is", render: (row) => (row.path ? h("code", { class: "path", text: row.path }) : null) },
              { key: "expected", label: "Where the rules put it", render: (row) => (row.expected ? h("code", { class: "path", text: row.expected }) : null) },
              { key: "note", label: "Note" },
            ],
            rows,
            filterPlaceholder: "Find a file",
            caption: "Every file the check found out of place",
            empty: "No problem matches.",
            limit: 40,
          }).element,
        )
      : null;

    const parts = [
      h(
        "header",
        { class: "result-head" },
        h("div", { class: "result-titles" }, h("h2", { class: "result-headline", text: headline }), h("p", { class: "muted result-sub" }, icon("folder", { size: 16 }), `Seed ${view.seed} · ${chosen.label}, ${chosen.files} files · ${view.root}`)),
        h("div", { class: "card-actions" }, h("button", { type: "button", class: "button small", onclick: () => start() }, icon("refresh", { size: 15 }), "Run again")),
      ),
      tiles,
      verdictBanner(view.verdict, words),
      table,
      tree,
      view.state.batches ? h("p", { class: "muted small-text", text: `The agent moved ${view.state.moved} and deleted ${view.state.deleted} files in ${plural(view.state.batches, "batch", "batches")}${view.state.failed ? `; ${plural(view.state.failed, "item")} were refused by the folder` : ""}.` }) : null,
      view.answer ? disclosure({ summary: "The agent's report" }, h("p", { class: "prose", text: view.answer })) : null,
      disclosure(
        { summary: "About this check" },
        h(
          "ul",
          { class: "about-list" },
          h("li", { text: "The answer key is the same folder tidied by the rules before the agent starts; every kept file's hash and final path is pinned." }),
          h("li", { text: "Afterwards every file in organized/ is hashed and compared with the key: each kept file once, at exactly its path, nothing else anywhere." }),
          h("li", { text: "Duplicates are decided by content hash alone; types by the bytes, never the name; dates by EXIF, PNG, PDF or front-matter metadata first, then the file name, then the modification time." }),
        ),
      ),
    ];
    return h("section", { class: "card large result-card", "aria-label": headline }, parts);
  }

  function tile(value, label) {
    return h("div", { class: "tile" }, h("span", { class: "tile-value numeric", text: value === null ? "–" : String(value) }), h("span", { class: "tile-label", text: label }));
  }

  shell.main.append(pickerCard, run.element, result, intro);
  return shell.element;
}

function parseToolOutput(output) {
  if (output && typeof output === "object") return output;
  try {
    const value = JSON.parse(output);
    return value && typeof value === "object" ? value : null;
  } catch {
    return null;
  }
}
