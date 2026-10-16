// How this plugin's page draws the organize-folder task's output, an OrganizeOutput: what the run did,
// then every check the verifier made (verdict.details.constraints), then this run's files
// (verdict.details.rows), each with whether its action is done, what the rules do with it and where
// they put it.
import { dataTable, disclosure, h, icon, plural, statusPill } from "./kit/components.js";

const ACTION = { move: "Move", delete: "Delete", stay: "Stay" };
const REASON = { copy: "a duplicate copy", junk: "junk", empty: "an empty file", rules: "filed by the rules", "in-place": "already in place" };

const folderName = (folder) => (folder === "." ? "your File Organizer folder" : folder);

/** "38 moved · 15 deleted · 12 already in place" */
function counts(out) {
  return [`${out.moved} moved`, `${out.deleted} deleted`, `${out.stayed} already in place`].join(" · ");
}

function headline(out, verdict) {
  const parts = [
    h("p", { class: "fo-summary" }, icon(verdict?.valid ? "check" : "folder", { size: 16 }), ` ${folderName(out.folder)}: ${plural(out.files, "file")} took part`),
    h("p", { class: "fo-counts", text: counts(out) }),
  ];
  const pills = [];
  if (out.left > 0) pills.push(statusPill(`${plural(out.left, "action")} not done`, "bad", { icon: true }));
  if (out.remaining > 0) pills.push(statusPill(`${out.remaining} more: ask again to continue`, "info", { icon: true }));
  if (pills.length) parts.push(h("div", { class: "fo-pills" }, pills));
  return parts;
}

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

/** Whether a row's action is done, and when it is not, where its file is: "No: found at …". */
function doneText(row) {
  if (row.ok) return "Yes";
  if (row.action === "delete") return "No: still there";
  if (!row.found) return "No: its bytes are gone";
  return row.found === row.path ? "No: still at its old path" : `No: found at ${row.found}`;
}

function rowsTable(rows) {
  if (!Array.isArray(rows) || !rows.length) return null;
  const columns = [
    { key: "path", label: "File", primary: true },
    { key: "ok", label: "Done", sortable: false, value: doneText, render: (row) => statusPill(doneText(row), row.ok ? "ok" : "bad") },
    { key: "action", label: "The rules say", value: (row) => `${ACTION[row.action] ?? row.action}: ${REASON[row.reason] ?? row.reason}` },
    { key: "target", label: "Belongs at", value: (row) => (row.action === "delete" ? "—" : row.target ?? "—") },
  ];
  const undoneFirst = [...rows.filter((row) => !row.ok), ...rows.filter((row) => row.ok)];
  return dataTable({ caption: "This run's files", columns, rows: undoneFirst, limit: 15, filterPlaceholder: "Filter files", empty: "This run had nothing to do." }).element;
}

export default {
  OrganizeOutput: (out, { verdict } = {}) =>
    h(
      "div",
      { class: "fo-result" },
      headline(out, verdict),
      checksList(verdict),
      rowsTable(verdict?.details?.rows),
    ),
};
