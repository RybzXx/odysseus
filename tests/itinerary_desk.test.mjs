import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import test from "node:test";

function desk() {
  const elements = new Map();
  const document = { getElementById(id) {
    if (!elements.has(id)) elements.set(id, { innerHTML: "" });
    return elements.get(id);
  }};
  const context = vm.createContext({ document, window: {} });
  const source = readFileSync(new URL("../static/js/itineraryDesk.js", import.meta.url), "utf8");
  // Load the production functions without starting the page's network bootstrap.
  vm.runInContext(source.slice(0, source.indexOf('$("new-request").addEventListener')), context);
  return { context, elements };
}

test("incomplete results disable generation and display their requirements", () => {
  const { context } = desk();
  context.draft = { day_count: 7, normalized: {}, sequences: [{ source: "rules",
    day_codes: ["BG"], check: { is_clean: false, faults: [{ statement: "Missing south" }],
      untested: ["Date unknown"], fault_count: 1, flag_count: 0 } }] };
  const output = vm.runInContext("stripHtml(draft) + runResultHtml(draft)", context);
  assert.match(output, /disabled/);
  assert.match(output, /Incomplete itinerary/);
  assert.match(output, /Missing south/);
  assert.match(output, /Date unknown/);
  assert.match(output, /Recalculate itinerary/);
});

test("a new rules result takes precedence over model history", () => {
  const { context } = desk();
  context.draft = { normalized: {}, sequences: [
    { source: "model", day_codes: ["OLD"], check: { is_clean: false } },
    { source: "rules", day_codes: ["A", "B", "C"], check: { is_clean: true }, generation: { ready: true } },
  ] };
  const output = vm.runInContext("stripHtml(draft)", context);
  assert.match(output, /3 day\(s\)/);
  assert.match(output, /data-source="rules"/);
  assert.doesNotMatch(output, /disabled/);
  assert.match(output, /Rules recalculated/);
  assert.match(output, /No model used for this result/);
});

test("rule books read the API wrapper and identify retired guidance", async () => {
  const { context, elements } = desk();
  context.reply = { counted: { rules: [{ family: "move", statement: "Counted road" }] },
    judged: { rules: [{ rule_id: "old", statement: "Preserved exception", status: "retired" },
      { rule_id: "new", statement: "Visit the south", enforced_by: "sequence_check.region_coverage" }] } };
  vm.runInContext("api = async () => reply", context);
  await vm.runInContext("loadRuleBooks()", context);
  const output = elements.get("rule-books").innerHTML;
  assert.match(output, /Counted road/);
  assert.match(output, /retired/);
  assert.match(output, /Enforced by itinerary checks/);
});


test("a pricing failure blocks a route that passes the itinerary checks", () => {
  const { context } = desk();
  context.draft = { normalized: {}, sequences: [{ source: "rules", day_codes: ["A"],
    check: { is_clean: true }, generation: { ready: false, errors: ["Vehicle VAN is not in the catalogue"] } }] };
  const output = vm.runInContext("stripHtml(draft) + runResultHtml(draft)", context);
  assert.match(output, /disabled/);
  assert.match(output, /Vehicle VAN is not in the catalogue/);
});
