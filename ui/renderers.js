// How this plugin's page draws the organize-folder task's output, an OrganizeOutput: what the run did,
// then every check the verifier made (verdict.details.constraints), then this run's files
// (verdict.details.rows), each with what happened to it and whether that is where the rules put it.
import { dataTable, disclosure, h, icon, plural, statusPill } from "./kit/components.js";

const ACTION = { move: "Moved", delete: "Deleted", stay: "In place" };
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

function checkList(constraints) {
  if (!Array.isArray(constraints) || !constraints.length) return null;
  const failed = constraints.filter((entry) => entry.ok === false).length;
  const item = (entry) =>
    h(
      "li",
      { class: `fo-check ${entry.ok === true ? "ok" : entry.ok === false ? "bad" : "skip"}` },
      icon(entry.ok === true ? "check" : entry.ok === false ? "error" : "info", { size: 14, label: entry.ok === true ? "Holds" : entry.ok === false ? "Fails" : "Not checked" }),
      h("span", { class: "fo-check-text" }, h("span", { text: entry.constraint }), entry.ok === false && entry.message ? h("span", { class: "fo-check-why", text: entry.message }) : null),
    );
  return disclosure(
    { summary: failed ? `${failed} of ${constraints.length} checks failed` : `All ${constraints.length} checks hold`, open: failed > 0, className: "fo-checks" },
    h("ul", { class: "fo-check-list" }, constraints.map(item)),
  );
}

function rowsTable(rows) {
  if (!Array.isArray(rows) || !rows.length) return null;
  const columns = [
    { key: "path", label: "File", primary: true },
    {
      key: "action",
      label: "What happened",
      value: (row) => `${ACTION[row.action] ?? row.action}: ${REASON[row.reason] ?? row.reason}`,
    },
    { key: "target", label: "Now at", value: (row) => (row.action === "delete" ? "—" : row.target ?? "—") },
    {
      key: "ok",
      label: "As the rules say",
      sortable: false,
      value: (row) => (row.ok ? "yes" : "no"),
      render: (row) => (row.ok ? statusPill("Yes", "ok") : statusPill(row.found ? `No: found at ${row.found}` : "No", "bad")),
    },
  ];
  return dataTable({ caption: "This run's files", columns, rows, limit: 15, filterPlaceholder: "Filter files", empty: "This run had nothing to do." }).element;
}

export default {
  OrganizeOutput: (out, { verdict } = {}) =>
    h(
      "div",
      { class: "fo-result" },
      headline(out, verdict),
      checkList(verdict?.details?.constraints),
      rowsTable(verdict?.details?.rows),
    ),
};
