// static/js/markdown/tableRow.js
//
// Pure helper for splitting a markdown table row into cells. No DOM —
// safe to import anywhere and to unit-test under node.

// Split a "| a | b | c |" row into trimmed cell strings.
//
// Strip only the optional leading/trailing pipe, then split — filtering out
// every empty cell (the old behaviour) dropped intentionally-empty interior
// cells too, so "| a |  | c |" collapsed to 2 columns and misaligned with the
// header.
// >>> odysseus-table-escaped-pipe
// Walks the row once. The chained replace/split it replaces could not tell an
// escaped pipe from a column break, so `Iraq \| Collaboration` in an email
// subject opened a phantom column and shifted the rest of the row.
//
// Only `\|` is unescaped: a doubled backslash is left alone so cells holding
// Windows paths are not rewritten.
export function splitTableRow(row) {
  const text = typeof row === 'string' ? row : '';
  const cells = [];
  let cell = '';

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === '\\' && text[i + 1] === '|') {
      cell += '|'; // escaped: content, not a delimiter
      i += 1;
      continue;
    }
    if (ch === '|') {
      cells.push(cell);
      cell = '';
      continue;
    }
    cell += ch;
  }
  cells.push(cell);

  // Drop only the empties produced by the OPTIONAL outer pipes. An
  // intentionally-empty interior cell must survive, or the row misaligns with
  // the header -- the defect this file's previous revision fixed.
  if (cells.length && cells[0].trim() === '') cells.shift();
  if (cells.length && cells[cells.length - 1].trim() === '') cells.pop();

  return cells.map((c) => c.trim());
}
// <<< odysseus-table-escaped-pipe
