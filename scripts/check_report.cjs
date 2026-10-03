/* Portable report runtime checks. Test balances below are labeled fixtures only. */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const {spawnSync} = require("node:child_process");
const root = path.resolve(__dirname, "..");

class Element {
  constructor(tag="div") { this.tagName=tag.toUpperCase(); this.children=[]; this.events={}; this.attributes={}; this.dataset={}; this.className=""; this.value=""; this._text=""; this.disabled=false; }
  set textContent(v) { this._text=String(v); this.children=[]; }
  get textContent() { return this._text+this.children.map(n=>n.textContent).join(""); }
  appendChild(node) { this.children.push(node);node.parent=this;return node; }
  replaceChildren(...children) { this.children=children;this._text=""; }
  addEventListener(event,fn) { (this.events[event]??=[]).push(fn); }
  dispatch(event) { for(const fn of this.events[event]||[])fn({target:this}); }
  setAttribute(k,v) { this.attributes[k]=String(v); }
  querySelector(tag) { return this.find(n=>n.tagName===tag.toUpperCase())||this.appendChild(new Element(tag)); }
  querySelectorAll(selector) { if(selector==="tbody tr")return this.querySelector("tbody").children.filter(n=>n.tagName==="TR");return []; }
  find(test) { for(const child of this.children){if(test(child))return child;const hit=child.find(test);if(hit)return hit;} }
  get classList() { return {remove:token=>{this.className=this.className.split(/\s+/).filter(t=>t!==token).join(" ");}}; }
  focus() { this.focused=true; }
  click() { this.dispatch("click"); }
  remove() { if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this); }
}

function boot(html) {
  const data=html.match(/<script id="report-data" type="application\/json">([\s\S]*?)<\/script>/);
  const runtime=html.match(/<script id="report-runtime">([\s\S]*?)<\/script>/);
  assert(data&&runtime,"Report requires a saved data block and runtime");
  assert(!/<script[^>]+src\s*=/i.test(html),"Report must not load scripts from another file or a CDN");
  assert(!/<link[^>]+href\s*=/i.test(html),"Report styles must be self-contained");
  const payload=JSON.parse(data[1]),nodes=new Map();
  for(const m of html.matchAll(/\bid="([^"]+)"/g))nodes.set(m[1],new Element());
  nodes.get("report-data").textContent=data[1];
  const body=new Element("body"),blobs=[],downloads=[];
  const document={getElementById:id=>{assert(nodes.has(id),`Unknown report DOM id ${id}`);return nodes.get(id);},createElement:tag=>{const n=new Element(tag);if(tag==="a")n.click=()=>downloads.push({name:n.download,url:n.href});return n;},createElementNS:(_ns,tag)=>new Element(tag),body};
  const sandbox={document,window:{},JSON,Intl,Number,Object,String,Array,Math,Set,console,setTimeout:fn=>fn(),Blob:class {constructor(parts,options){this.parts=parts;this.options=options;blobs.push(this);}},URL:{createObjectURL:()=>"blob:test",revokeObjectURL:()=>{}}};
  vm.runInNewContext(runtime[1],sandbox,{timeout:5000,filename:"report-runtime.js"});
  return {payload,nodes,api:sandbox.window.BankALMReport,blobs,downloads};
}

function renderWithPython(analysis,provenance={fixture:"TEST ONLY — not source evidence"}) {
  const code="import json,sys; from bank_alm.report import render_report; p=json.load(sys.stdin); sys.stdout.buffer.write(render_report(p['analysis'],p['provenance']).encode('utf-8'))";
  const result=spawnSync(process.env.PYTHON||"python",["-c",code],{cwd:root,input:JSON.stringify({analysis,provenance}),encoding:"utf8",maxBuffer:8*1024*1024});
  if(result.error)throw result.error;
  assert.equal(result.status,0,result.stderr);
  return result.stdout;
}

const fixture={schema_version:1,bank:{name:"TEST FIXTURE BANK",certificate:0,as_of:"2025-12-31"},units:"USD",baseline:{nii_12m_usd:1200,eve_usd:10000,historical_nii_usd:1100,historical_nii_period:"TEST period"},checks:[{name:"Fixture accounting identity",passed:true,actual:0,tolerance:0}],limitations:["TEST ONLY: synthetic checks, not actual source data"],assumptions:{deposit_beta:.4},policies:{objective:"TEST objective",candidates:[{id:"P1",prefunding_fraction:.1,funding_order:"borrow_then_sell",feasible:false,worst_case_nii_usd:900,worst_case_delta_eve_usd:-2000,max_unfunded_withdrawals_usd:10,max_cash_floor_shortfall_usd:20}],selected_policy_id:null,feasible_count:0,constraints:{test:true},evaluation_scenarios:["base","stress"]},reverse_stress:{first_observed_failure:{rate_shock_bps:200,deposit_runoff_pct:20,status:"BREACH"},grid:[{rate_shock_bps:0},{rate_shock_bps:200}],limitations:"TEST grid"},sensitivity:[{parameter:"deposit_beta",value:.2,scenario_id:"stress",delta_eve_usd:-1700,nii_12m_usd:920,delta_nii_vs_reference_usd:20,delta_eve_vs_reference_usd:300}],scenarios:[{id:"base",name:"TEST baseline",description:"Baseline test fixture",rate_shock_bps:0,deposit_runoff_pct:0,eve_usd:10000,delta_eve_usd:0,nii_12m_usd:1200,delta_nii_usd:0,min_cash_usd:1000,peak_wholesale_funding_usd:2000,securities_sold_usd:0,realized_sale_pnl_usd:0,status:"PASS",breaches:[],monthly:[{month:1,cash_usd:1000,securities_usd:3000,loans_usd:5000,deposits_usd:6500,wholesale_funding_usd:2000,equity_usd:500,nii_usd:100,asset_sales_usd:0,sale_pnl_usd:0,cumulative_unfunded_withdrawals_usd:0,accounting_residual_usd:0}]},{id:"stress",name:"TEST stress",description:"</script><script>window.escapeProbe=true</script> & test",rate_shock_bps:200,deposit_runoff_pct:20,eve_usd:8000,delta_eve_usd:-2000,nii_12m_usd:900,delta_nii_usd:-300,min_cash_usd:500,peak_wholesale_funding_usd:2500,securities_sold_usd:100,realized_sale_pnl_usd:-5,status:"BREACH",breaches:["TEST funding limit"],monthly:[{month:1,cash_usd:500,securities_usd:2900,loans_usd:5000,deposits_usd:5800,wholesale_funding_usd:2500,equity_usd:100,nii_usd:75,asset_sales_usd:100,sale_pnl_usd:-5,cumulative_unfunded_withdrawals_usd:10,accounting_residual_usd:0}]}]};

const html=renderWithPython(fixture),test=boot(html);
assert(!html.includes("<script>window.escapeProbe"),"Embedded description must not create an executable script tag");
assert.equal(test.payload.analysis.scenarios[1].description,fixture.scenarios[1].description,"Escaping must preserve exact source strings");
assert.equal(test.api.verified,true);
assert.equal(test.api.selectedId(),"base");
const original=test.nodes.get("eve-value").textContent;
const select=test.nodes.get("scenario-select");select.value="stress";select.dispatch("change");
assert.equal(test.api.selectedId(),"stress");
assert.notEqual(test.nodes.get("eve-value").textContent,original,"Scenario selection must update financial metrics");
assert.equal(test.nodes.get("scenario-description").textContent,fixture.scenarios[1].description,"Text must remain text, never HTML");
assert.equal(test.nodes.get("monthly-table").querySelector("tbody").children.length,1);
assert.equal(test.nodes.get("scenario-status").textContent,"BREACH");
assert(test.nodes.get("sensitivity-table").querySelector("tbody").textContent.includes("stress"),"Sensitivity shock id must be visible");
const rows=test.nodes.get("scenario-table").querySelector("tbody").children;
rows[0].children[0].children[0].click();assert.equal(test.api.selectedId(),"base","Comparison row button must select the saved scenario");
test.api.selectScenario("stress");assert.equal(test.api.selectedId(),"stress");
assert.throws(()=>test.api.selectScenario("missing"),/Unknown saved scenario/);
const csv=test.api.csvFor(fixture.scenarios[1]);assert(csv.includes('"cash_usd"')&&csv.includes('"500"'),"CSV must contain saved ledger values");
test.nodes.get("download-json").click();test.nodes.get("download-csv").click();
assert.equal(test.downloads.length,2,"Both evidence download buttons must work");
assert.equal(JSON.parse(test.blobs[0].parts[0]).analysis.bank.name,"TEST FIXTURE BANK");
const blocked=JSON.parse(JSON.stringify(fixture));blocked.checks[0].passed=false;
const blockedTest=boot(renderWithPython(blocked));assert.equal(blockedTest.api.verified,false);assert.equal(blockedTest.nodes.get("eve-value").textContent,"Withheld");assert.equal(blockedTest.nodes.get("download-csv").disabled,true);assert(blockedTest.nodes.get("policy-banner").textContent.includes("withheld"));
const missing=JSON.parse(JSON.stringify(fixture));missing.checks=[];assert.equal(boot(renderWithPython(missing)).api.verified,false,"Missing verification must fail closed");

const plain=JSON.parse(JSON.stringify(fixture));plain.scenarios[1].breaches=["assumed_eve_loss_limit_breached","requested_withdrawals_unfunded","cash_floor_breached"];plain.scenarios[1].max_unfunded_withdrawals_usd=10;plain.scenarios[1].max_cash_floor_shortfall_usd=20;plain.scenarios[1].cash_floor_usd=520;plain.policies.constraints.maximum_eve_loss_usd=1500;
const sourceFixture={fixture:"TEST ONLY",bank_as_of:"2025-12-31",curve_as_of:"2025-12-31",curve_source_captured_at:"2026-10-02T05:46:36.465711+00:00",built_at_utc:"2026-10-02T14:00:00+00:00",source_records:[{source_id:"fdic_regions_20251231",source_url:"https://example.invalid/fixture",retrieved_at_utc:"2026-10-02T14:29:43.890658+00:00"}],curve_source:"https://example.invalid/fixture-curve"};
const plainHtml=renderWithPython(plain,sourceFixture),plainTest=boot(plainHtml);plainTest.api.selectScenario("stress");
const breachText=plainTest.nodes.get("scenario-breaches").textContent;assert(!breachText.includes("_"),"Breach codes must become plain-language explanations");assert(breachText.includes("EVE loss $2.0k exceeds the assumed $1.5k limit."));assert(breachText.includes("$10 of requested withdrawals"));assert(breachText.includes("$20 below the assumed $520 floor"));
assert(plainTest.nodes.get("source-dates").textContent.includes("2026-10-02 14:29:43 UTC"),"Bank source capture date must be readable outside provenance JSON");assert.equal(plainTest.nodes.get("source-links").children.length,2,"Readable bank and curve source links must be visible");assert(!/<details id="provenance-details"[^>]*\bopen\b/.test(plainHtml),"Large provenance details must be collapsed by default");

// Saved hedge outputs are test fixtures: this checks display boundaries, not a model.
const hedged=JSON.parse(JSON.stringify(fixture));
hedged.assumptions.hedge={tenor_months:60};
hedged.policies.candidates=Array.from({length:30},(_,i)=>({...hedged.policies.candidates[0],id:"TEST_POLICY_"+i,feasible:i===29,hedge_fraction_assets:[0,.05,.1,.15,.2][i%5],swap_notional_usd:1000,max_unfunded_margin_usd:0,max_payment_payable_usd:0}));hedged.policies.selected_policy_id="TEST_POLICY_29";hedged.policies.feasible_count=1;
const policyRows=hedged.scenarios.map(s=>({...s,nii_12m_usd:950,delta_eve_usd:-1000,minimum_observed_cash_usd:450,modeled_earnings_usd:1000,swap_notional_usd:1000,swap_fixed_rate:.04,initial_margin_usd:20,max_collateral_required_usd:120,max_collateral_posted_usd:120,max_posted_variation_margin_usd:100,max_received_collateral_cash_usd:50,swap_coupon_total_usd:25,swap_terminal_closeout_usd:75,max_unfunded_margin_usd:0,max_payment_payable_usd:0,breaches:[],status:"within_assumed_limits",initial_event:{month:0,cash_usd:450,posted_initial_margin_usd:20,posted_variation_margin_usd:0,derivative_value_usd:0,received_collateral_cash_usd:0,collateral_return_liability_usd:0,collateral_required_usd:20,collateral_posted_usd:20,accounting_residual_usd:0},monthly:s.monthly.map(r=>({...r,derivative_value_usd:-100,posted_initial_margin_usd:20,posted_variation_margin_usd:100,received_collateral_cash_usd:0,collateral_return_liability_usd:0,initial_margin_required_usd:20,variation_margin_required_usd:100,collateral_required_usd:120,collateral_posted_usd:120,unfunded_margin_usd:0,swap_net_coupon_usd:25,swap_mtm_pnl_usd:-100,swap_closeout_cashflow_usd:75,collateral_interest_usd:1,transaction_fee_usd:2,payment_payable_usd:0,hedge_adjusted_interest_earnings_usd:100}))}));
hedged.policy_analysis={policy_id:"TEST_POLICY_29",selection_status:"selected",policy:hedged.policies.candidates[29],scenarios:policyRows,explanation:"TEST ONLY selected feasible candidate."};hedged.hedge_comparison=hedged.scenarios.map(s=>({scenario_id:s.id,unhedged_delta_eve_usd:s.delta_eve_usd,policy_delta_eve_usd:-1000,unhedged_nii_12m_usd:s.nii_12m_usd,policy_nii_12m_usd:950}));
const hedgeTest=boot(renderWithPython(hedged));assert.equal(hedgeTest.api.view(),"policy","A saved feasible selected policy may be the initial review view");hedgeTest.api.selectScenario("stress");
assert.equal(hedgeTest.nodes.get("nii-value").textContent,"$950","Bank NII must use the saved raw bank interest result");assert.equal(hedgeTest.nodes.get("objective-earnings").textContent,"$1.0k","Policy objective earnings must remain a separate saved metric");assert.equal(hedgeTest.nodes.get("cash-value").textContent,"$450","Liquidity display must include the saved opening-event minimum");assert.equal(hedgeTest.nodes.get("swap-fixed-rate").textContent,"4.000% / 5 years");assert.equal(hedgeTest.nodes.get("collateral-required").textContent,"$120");assert.equal(hedgeTest.nodes.get("variation-received").textContent,"$50");
assert.equal(hedgeTest.nodes.get("monthly-table").querySelector("tbody").children.length,2,"Full accounting ledger must include the opening event");assert(hedgeTest.nodes.get("monthly-head").textContent.includes("Swap PV")&&hedgeTest.nodes.get("monthly-head").textContent.includes("VM return liability"));assert(hedgeTest.nodes.get("collateral-chart").textContent.includes("M0"),"Collateral chart must include initial margin at time zero");assert.equal(hedgeTest.nodes.get("policy-table").querySelector("tbody").children.length,30,"All thirty frozen joint candidates must be reviewable");assert(hedgeTest.api.csvFor(policyRows[1]).includes('"swap_closeout_cashflow_usd"'));
const viewSelect=hedgeTest.nodes.get("analysis-view");viewSelect.value="reference";viewSelect.dispatch("change");assert.equal(hedgeTest.api.view(),"reference");assert.equal(hedgeTest.api.selectedId(),"stress","View changes must preserve the selected shock id");assert.equal(hedgeTest.nodes.get("nii-value").textContent,"$900","Reference view must restore the unhedged saved bank NII");
const diagnostic=JSON.parse(JSON.stringify(hedged));diagnostic.policies.selected_policy_id=null;diagnostic.policies.feasible_count=0;diagnostic.policies.candidates.forEach(c=>{c.feasible=false;});diagnostic.policy_analysis.selection_status="diagnostic_unselected";diagnostic.policy_analysis.scenarios[1].breaches=["margin_requirement_unfunded","payment_obligation_unsettled"];diagnostic.policy_analysis.scenarios[1].max_unfunded_margin_usd=20;diagnostic.policy_analysis.scenarios[1].max_payment_payable_usd=7;
const diagnosticTest=boot(renderWithPython(diagnostic));assert.equal(diagnosticTest.api.view(),"reference","An infeasible diagnostic must not be selected automatically");diagnosticTest.api.selectView("policy");diagnosticTest.api.selectScenario("stress");assert(diagnosticTest.nodes.get("active-view-note").textContent.includes("DIAGNOSTIC ONLY"));assert(diagnosticTest.nodes.get("hedge-result-status").textContent.includes("NOT SELECTED"));assert(diagnosticTest.nodes.get("scenario-breaches").textContent.includes("$20 of required swap collateral"));assert(diagnosticTest.nodes.get("scenario-breaches").textContent.includes("$7 of contractual payments"));
const invalidSelection=JSON.parse(JSON.stringify(hedged));invalidSelection.policies.candidates[29].feasible=false;assert.throws(()=>renderWithPython(invalidSelection),/matching feasible policy/,"Renderer must reject a selected but infeasible policy view");

if(process.argv[2]){
  const file=path.resolve(process.argv[2]),live=boot(fs.readFileSync(file,"utf8"));
  assert(live.payload.analysis.scenarios.length>0);
  const groups=[["reference",live.payload.analysis.scenarios]];if(live.payload.analysis.policy_analysis?.scenarios)groups.push(["policy",live.payload.analysis.policy_analysis.scenarios]);
  for(const[view,group]of groups){if(live.api.selectView)live.api.selectView(view);for(const scenario of group){live.api.selectScenario(scenario.id);assert.equal(live.api.selectedId(),scenario.id);if(live.api.verified)assert.equal(live.nodes.get("monthly-table").querySelector("tbody").children.length,scenario.monthly.length+(scenario.initial_event?1:0));}}
  console.log(`Saved report verified: ${file}; ${live.payload.analysis.scenarios.length} reference scenarios; ${live.payload.analysis.policy_analysis?.scenarios?.length||0} policy scenarios; checks ${live.api.verified?"passed":"blocked as recorded"}.`);
}
console.log("Report checks passed: Python escaping, reference/selected/diagnostic views, raw NII versus objective earnings, opening-event collateral ledger, 30 joint candidates, scenario controls, evidence downloads and failed/missing-check blocking. DOM test doubles do not verify browser layout.");
