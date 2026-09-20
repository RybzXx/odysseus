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

test('group pricing shows both vehicles, FOC, markups and full operating details',()=>{
  const c=workspace();
  c.quote={num_days:10,num_nights:9,basis_label:'Owner variant <test>',basis_is_operations_variant:true,
    options:{office_markup_percent:10,margin_markup_percent:20,single_supplement_override:400},multiplier:1.32,
    rows:[{paying_min:8,paying_max:9,foc:1,TOYOTA_COASTER:1500,VIP_BUS:1900}],hotel_tier:'3star',
    single_supplement:400,guide_days:9,transport_days:9,vehicle_daily_rates:{TOYOTA_COASTER:200,VIP_BUS:450},
    nights_by_city:{Erbil:1},warnings:['Confirm flight <time>'],
    days:[{number:10,date:'2027-04-04',title:'EBSORA',text:'Visit and transfer',overnight_city:''}]};
  const html=vm.runInContext('groupQuoteHtml(quote)',c);
  for(const expected of ['10 days / 9 nights','VIP coach','$1,900','$1,500','8–9 + 1 FOC','cost × 1.32','$400','Visit and transfer','None · departure','Overview proposal']) assert.ok(html.includes(expected),expected);
  assert.ok(html.includes('&lt;test&gt;'));assert.ok(html.includes('&lt;time&gt;'));
});

test('a delayed quote response cannot replace another draft panel',async()=>{
  const c=workspace();let resolve;
  const form={dataset:{},querySelectorAll:()=>[]};
  const nodes={'group-quote-form':form,'group-quote-status':{textContent:''}};
  c.document.getElementById=id=>nodes[id];
  c.fetch=()=>new Promise(r=>{resolve=r;});
  vm.runInContext("current={draft_id:'first'}",c);
  const pending=vm.runInContext('loadGroupQuote()',c);
  vm.runInContext("current={draft_id:'second'}",c);
  nodes['group-quote-form']={dataset:{},querySelectorAll:()=>[]};
  nodes['group-quote-status']={textContent:'Second draft'};
  resolve({ok:true,json:async()=>({})});
  await pending;
  assert.equal(nodes['group-quote-status'].textContent,'Second draft');
});

test('revenue confirmation shows the 450 floor and adjusted predecessor totals',()=>{
  const c=workspace();
  const check={minimum_revenue:17500,maximum_revenue:19250,previous_maximum_revenue:16875,revenue_increase:625,increase_per_person:75};
  c.quote={revenue_confirmation:{passed:true,minimum_increase_usd:450},
    rows:[{paying_min:10,paying_max:11,revenue_checks:{VIP_BUS:check,TOYOTA_COASTER:{...check,minimum_revenue:14000,maximum_revenue:15400,previous_maximum_revenue:13500,revenue_increase:500}}}]};
  const html=vm.runInContext('groupRevenueHtml(quote, amount => "$"+amount.toLocaleString("en-US"))',c);
  for(const expected of ['Revenue check passed','at least $450','FOC travellers do not count','$17,500–$19,250','$16,875','$625','$500']) assert.ok(html.includes(expected),expected);
  c.quote.revenue_confirmation.passed=false;
  assert.doesNotMatch(vm.runInContext('groupRevenueHtml(quote, String)',c),/Revenue check passed/);
});
