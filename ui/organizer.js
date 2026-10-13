// The File Organizer page's own pieces: the task root, what the run's tool calls say so far, the
// counts and problems the check reports, the verdict in plain words, and the organized/ tree.

import { h, icon } from "./kit/components.js";

/** The three sizes of messy folder, as the task offers them. */
export const SIZES = [
  { value: "small", label: "Small", files: 60 },
  { value: "medium", label: "Medium", files: 150 },
  { value: "large", label: "Large", files: 300 },
];
export const SEED_MIN = 0;
export const SEED_MAX = 999999;

/** The folder a run works in, relative to the workspace. */
export function rootFor(seed, size) {
  return `file-organizer/${seed}-${size}`;
}

/** The size entry for a value, or the first. */
export function sizeOf(value) {
  return SIZES.find((one) => one.value === value) ?? SIZES[0];
}

/**
 * What the run has told the page so far, from the tool calls that succeeded: how many files the
 * folder holds, how many the agent has listed, moved and deleted, and how many items failed.
 * @param {Array<{name: string, isError: boolean, data: object|null, arguments?: object}>} tools
 */
export function progressFrom(tools) {
  const state = { files: null, dirs: null, rules: false, listed: 0, total: null, moved: 0, deleted: 0, failed: 0, batches: 0, listings: 0 };
  for (const tool of tools) {
    if (tool.isError || !tool.data) continue;
    const data = tool.data;
    if (tool.name === "unpack_inbox") {
      state.files = data.files ?? null;
      state.dirs = data.dirs ?? null;
      if (data.rules) state.rules = true;
    } else if (tool.name === "read_rules") state.rules = true;
    else if (tool.name === "inventory") {
      state.total = data.total ?? state.total;
      state.listed = Math.min(state.total ?? Infinity, state.listed + (data.files?.length ?? 0));
    } else if (tool.name === "apply_plan") {
      state.batches += 1;
      state.moved += data.moved ?? 0;
      state.deleted += data.deleted ?? 0;
      state.failed += data.errors?.length ?? 0;
    } else if (tool.name === "list_tree") state.listings += 1;
  }
  return state;
}

/** The counts the check reports: files made, files to keep, duplicates and junk to delete, files in place. */
export function countsFrom(verdict) {
  const details = verdict?.details ?? {};
  const number = (value) => (typeof value === "number" ? value : null);
  return { files: number(details.files), unique: number(details.unique), duplicates: number(details.duplicates), removed: number(details.removed), placed: number(details.placed) };
}

const KINDS = {
  missing: { word: "Missing", tone: "bad", explain: "Not anywhere in organized/ (deleted, or still in the inbox)." },
  misplaced: { word: "Wrong place", tone: "warn", explain: "In organized/, but not at the path the rules give." },
  duplicates_kept: { word: "Duplicate kept", tone: "warn", explain: "A second copy of a kept file is still there." },
  extra: { word: "Should be gone", tone: "bad", explain: "Junk, an empty file or a copy that the rules delete." },
  leftovers: { word: "Left behind", tone: "bad", explain: "A file outside organized/." },
  bad_names: { word: "Odd name", tone: "warn", explain: "Not a path the rules could give." },
};

/**
 * One row per problem the check reports, for the mismatch table:
 * `{kind, word, tone, path, expected, note}`.
 */
export function problemRows(verdict) {
  const details = verdict?.details ?? {};
  const rows = [];
  for (const item of details.missing ?? []) rows.push({ kind: "missing", path: "", expected: item.expected, note: "" });
  for (const item of details.misplaced ?? []) rows.push({ kind: "misplaced", path: (item.actual ?? []).join(", "), expected: item.expected, note: "" });
  for (const item of details.duplicates_kept ?? []) rows.push({ kind: "duplicates_kept", path: (item.extra ?? []).join(", "), expected: item.expected, note: "" });
  for (const path of details.extra ?? []) rows.push({ kind: "extra", path, expected: "", note: "" });
  for (const path of details.leftovers ?? []) rows.push({ kind: "leftovers", path, expected: "", note: "" });
  for (const item of details.bad_names ?? []) rows.push({ kind: "bad_names", path: item.path, expected: "", note: item.problem ?? "" });
  return rows.map((row) => ({ ...row, word: KINDS[row.kind].word, tone: KINDS[row.kind].tone }));
}

/** The six problem kinds with their words, for a legend. */
export function problemKinds() {
  return Object.entries(KINDS).map(([kind, one]) => ({ kind, ...one }));
}

function count(verdict, key) {
  return (verdict?.details?.[key] ?? []).length;
}

/**
 * The verdict in this page's words: a title, a body and lines for the banner.
 * @param {object} verdict A `task.verdict`.
 */
export function verdictWords(verdict) {
  const counts = countsFrom(verdict);
  if (verdict.valid) {
    return { tone: "ok", title: "Checked: every file is where the rules put it, and nothing else is left.", body: counts.unique !== null ? `${counts.unique} files were checked hash by hash against the answer key.` : undefined, score: "" };
  }
  const lines = [];
  const missing = count(verdict, "missing");
  const misplaced = count(verdict, "misplaced");
  const duplicates = count(verdict, "duplicates_kept");
  const extra = count(verdict, "extra");
  const leftovers = count(verdict, "leftovers");
  const badNames = count(verdict, "bad_names");
  if (missing) lines.push(`${missing} ${missing === 1 ? "file is" : "files are"} missing from organized/.`);
  if (misplaced) lines.push(`${misplaced} ${misplaced === 1 ? "file is" : "files are"} in the wrong place or under the wrong name.`);
  if (duplicates) lines.push(`${duplicates} duplicate ${duplicates === 1 ? "copy was" : "copies were"} kept.`);
  if (extra) lines.push(`${extra} ${extra === 1 ? "file" : "files"} that should have been deleted ${extra === 1 ? "is" : "are"} in organized/.`);
  if (leftovers) lines.push(`${leftovers} ${leftovers === 1 ? "file was" : "files were"} left outside organized/.`);
  if (badNames) lines.push(`${badNames} ${badNames === 1 ? "path does" : "paths do"} not follow the naming scheme.`);
  const placed = counts.placed !== null && counts.unique !== null ? `${counts.placed} of ${counts.unique} files ended up in the right place.` : undefined;
  if (!lines.length) return { tone: "bad", title: "The agent did not finish, so the folder could not be checked.", body: placed, score: "" };
  const score = typeof verdict.score === "number" ? `Score ${Math.round(verdict.score * 100)}%` : "";
  return { tone: "warn", title: "The folder is not tidy yet.", body: placed, lines, score };
}

// ----- The tree of organized/ -----

/**
 * The paths under `prefix` as a tree: `{name, folders: Map, files: [{name, size}]}`.
 * @param {Array<{path: string, size: number}>} files From listFiles.
 * @param {string} prefix The part of each path to drop, e.g. "file-organizer/1-small/organized/".
 */
export function treeFrom(files, prefix) {
  const root = { name: "organized", folders: new Map(), files: [] };
  for (const file of files) {
    if (!file.path.startsWith(prefix)) continue;
    const parts = file.path.slice(prefix.length).split("/");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      if (!node.folders.has(part)) node.folders.set(part, { name: part, folders: new Map(), files: [] });
      node = node.folders.get(part);
    }
    node.files.push({ name: parts.at(-1), size: file.size });
  }
  return root;
}

/** How many files a tree node holds, with its sub-folders. */
export function countFiles(node) {
  let total = node.files.length;
  for (const child of node.folders.values()) total += countFiles(child);
  return total;
}

/**
 * A tree node as nested lists: folders as open disclosures down to `openDepth`, files as rows.
 * @param {ReturnType<typeof treeFrom>} node
 */
export function renderTree(node, { depth = 0, openDepth = 2 } = {}) {
  const items = [];
  for (const name of [...node.folders.keys()].sort()) {
    const child = node.folders.get(name);
    const files = countFiles(child);
    items.push(
      h(
        "li",
        { class: "tree-folder" },
        h(
          "details",
          { open: depth < openDepth },
          h("summary", {}, icon("folder", { size: 15 }), h("span", { class: "tree-name", text: name }), h("span", { class: "muted small-text tree-count", text: `${files} ${files === 1 ? "file" : "files"}` })),
          renderTree(child, { depth: depth + 1, openDepth }),
        ),
      ),
    );
  }
  for (const file of [...node.files].sort((a, b) => a.name.localeCompare(b.name))) {
    items.push(h("li", { class: "tree-file" }, icon("file", { size: 14 }), h("span", { class: "tree-name", text: file.name })));
  }
  return h("ul", { class: `tree${depth ? "" : " tree-root"}` }, items);
}

/** Known task errors in plain words (tried before the kit's common ones). */
export const ERROR_RULES = [
  { id: "cancelled", match: (message) => message === "cancelled", text: "Stopped. The folder was left as it was.", tone: "neutral" },
  { id: "seed", match: /seed must be between/, text: "That seed is out of range. Pick a smaller number." },
  { id: "input", match: "invalid input", text: "The seed or size is not valid. Pick again." },
  { id: "unpacked", match: /not a folder in the workspace/, text: "The agent asked about a folder that was never made. Run it again." },
];
