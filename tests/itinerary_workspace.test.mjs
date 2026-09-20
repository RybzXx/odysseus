import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
function workspace() {
  const context=vm.createContext({document:{getElementById:()=>({innerHTML:''})},window:{}});
  vm.runInContext(readFileSync(new URL('../static/js/itineraryWorkspace.js',import.meta.url),'utf8'),context);
  const desk=readFileSync(new URL('../static/js/itineraryDesk.js',import.meta.url),'utf8');
  vm.runInContext(desk.slice(0,desk.indexOf('$("new-request").addEventListener')),context);
  return context;
}
test('a stale plan cannot generate even when stored checks pass',()=>{
  const c=workspace();c.draft={stale:{statement:'Changed'},sequences:[{day_codes:['BG'],check:{is_clean:true},generation:{ready:true}}]};
  assert.equal(vm.runInContext('readiness(draft).label',c),'Recalculation required');
  assert.equal(vm.runInContext('readiness(draft).ready',c),false);
});
test('missing generation validation and empty sequences never become ready',()=>{
  const c=workspace();
  for(const sequence of [{day_codes:['BG'],check:{is_clean:true}},{day_codes:[],check:{is_clean:true},generation:{ready:true}}]) {
    c.draft={sequences:[sequence]}; assert.equal(vm.runInContext('readiness(draft).ready',c),false);
  }
  c.draft={sequences:[]};assert.equal(vm.runInContext('readiness(draft).label',c),'Not calculated');
});
test('latest failed result takes precedence over a ready historical result',()=>{
  const c=workspace();c.draft={sequences:[{day_codes:['BG'],check:{is_clean:true},generation:{ready:true}},{day_codes:['BG'],check:{is_clean:false},generation:{ready:false}}]};
  assert.equal(vm.runInContext('readiness(draft).ready',c),false);
});
test('blockers deduplicate without losing pricing or unknown requirements',()=>{
  const c=workspace();c.draft={sequences:[{check:{untested:['Missing date'],faults:[{day:2,statement:'Wrong city'}]},plan:{issues:['Missing date']},generation:{errors:['Missing vehicle price']}}]};
  assert.equal(vm.runInContext('workspaceProblems(draft).length',c),3);
  const html=vm.runInContext('blockerHtml(draft)',c);
  assert.match(html,/data-target="day-2"/);assert.match(html,/Missing vehicle price/);
});
test('day summaries preserve exclusion and never invent absent places',()=>{
  const c=workspace();c.sequence={day_codes:['<script>'],plan:{days:[{number:1,accommodation:'excluded'}]}};
  const html=vm.runInContext('itineraryDays(sequence)',c);
  assert.match(html,/Unknown start/);assert.match(html,/Unknown destination/);assert.match(html,/excluded/);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
