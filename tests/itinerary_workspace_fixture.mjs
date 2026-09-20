// Synthetic browser fixture. No connection to the phone or external services.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const names = ['ready', 'blocked', 'stale', 'empty', 'failed', 'document', 'long'];
const drafts = Object.fromEntries(names.map(name => {
  const count = name === 'long' ? 17 : 5;
  const sequence = { source: 'rules', proposed_at: '2026-09-20T10:00:00Z', day_codes: Array(count).fill('BG1CT'),
    check: { is_clean: name !== 'blocked', faults: [], untested: name === 'blocked' ? ['Day 2: the catalogue has no established start city.'] : [], flags: [], fault_count: 0, flag_count: 0 },
    generation: { ready: name !== 'blocked', errors: [] }, plan: { version: 2, days: Array.from({length:count}, (_,i) => ({number:i+1, code:'BG1CT',role:'city_day',start_city:'Baghdad',end_city:'Baghdad',overnight_status:'present',overnight_city:'Baghdad', accommodation:i===2?'excluded':'included',evidence:{place_source:'catalogue'}})), references: [{attachment_name:'Synthetic reference',sent_at:'2025-01-01'}] } };
  return [name, { draft_id:name, request_id:`request-${name}`, origin:'typed', day_count:count,
    normalized:{customer_name:`Example ${name}`,day_count:count,pax:2,requested_regions:[],start_date:'2026-11-01'},
    request_row:{name:`Example ${name}`,tripDays:count,comments:'Keep all submitted details',dietaryNeeds:'Vegetarian'},
    sequences:['empty','failed'].includes(name)?[]:[{...structuredClone(sequence),proposed_at:'2026-09-19T10:00:00Z'},sequence],
    comments:[], notes:[], runs:name==='failed'?[{run_id:'r-fail',statement:'Proposal failed',failures:['Synthetic failure'],untested:[]}]:[],
    doc_url:name==='document'?'https://example.com/existing-document':null,
    stale:name==='stale'?{statement:'Pricing changed. Recalculate.'}:null,
    reference_pool:{route_count:1,counts:{usable:1,needs_review:1,rejected:0},records:[{status:'needs_review',reference:{attachment_name:'Synthetic ambiguous reference'},reasons:['Optional departure']}]}}];
}));
http.createServer(async(req,res)=>{
  const url = new URL(req.url,'http://localhost');
  const send = (data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
  if (url.pathname === '/api/itinerary/requests') return send({requests:names.map(name=>({key:`request-${name}`,name:`Example ${name}`,source:'queue',status:'New'}))});
  if (url.pathname === '/api/itinerary/drafts') return send({drafts:Object.values(drafts)});
  if (url.pathname === '/api/itinerary/templates') return send({count:1,codes:[{code:'BG1CT',title:'Baghdad city tour'}]});
  if (url.pathname === '/api/itinerary/rules') return send({counted:{rules:[]},judged:{rules:[{statement:'Synthetic retired rule',status:'retired'}]}});
  if (url.pathname === '/api/operations/staged') return send({staged:[{id:'s1',conflict:true,key:'request-ready',changes:{status:'Replied'}}]});
  if (url.pathname.startsWith('/api/itinerary/runs/')) return send({run_id:'r-fail',steps:[]});
  const match = url.pathname.match(/^\/api\/itinerary\/drafts\/([^/]+)(?:\/(.+))?$/);
  if (match && drafts[match[1]]) {
    const draft = drafts[match[1]];
    if (match[2] === 'generate') return send({error:'Document generation is forbidden in the fixture'},403);
    if (match[1] === 'blocked' && ['propose-again','comment'].includes(match[2])) return send({error:'Synthetic recoverable failure'},503);
    if (match[2] === 'comment') {
      let body='';for await(const part of req) body+=part;
      draft.comments.push({text:JSON.parse(body).text,at:'2026-09-20T11:00:00Z'});
    }
    if (match[2] === 'propose-again' && draft.sequences.length) { draft.sequences.push(structuredClone(draft.sequences.at(-1))); draft.stale=null; }
    return send(draft);
  }
  try {
    const relative = url.pathname === '/itinerary' ? 'static/itinerary_desk.html' : url.pathname.slice(1);
    const file = path.resolve(root,relative);
    if (!file.startsWith(path.join(root,'static')+path.sep)) return send({},404);
    const body = await readFile(file);
    res.writeHead(200,{'Content-Type':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});res.end(body);
  } catch { send({},404); }
}).listen(7011,'127.0.0.1',()=>console.log('Synthetic itinerary fixture: http://127.0.0.1:7011/itinerary?draft=ready'));
