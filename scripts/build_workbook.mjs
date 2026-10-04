/** Editable research case, with fixed audited Python reference imports.
 * Authoring uses the bundled Artifact Tool runtime; no repository dependencies.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';

const ROOT=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const arg=(n,d)=>{const i=process.argv.indexOf(n);return i<0?d:process.argv[i+1];};
const THREAD='01a0fce5-927e-7883-9b51-671e6a527eaa';
const OUT=arg('--output',path.join(ROOT,'outputs',THREAD,'Bank_ALM_Case.xlsx'));
const PREVIEW=arg('--preview-dir',path.join(path.dirname(OUT),'workbook_previews'));
const deps=process.env.CODEX_WORKSPACE_NODE_MODULES||path.join(os.homedir(),'.cache','codex-runtimes','codex-primary-runtime','dependencies','node','node_modules');
const runtime=path.join(os.tmpdir(),`bank-alm-workbook-${THREAD}`);
await fs.mkdir(runtime,{recursive:true});
try{await fs.symlink(deps,path.join(runtime,'node_modules'),'junction');}catch(e){if(e.code!=='EEXIST')throw e;}
const require=createRequire(path.join(runtime,'loader.cjs'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const load=async p=>{const b=await fs.readFile(path.join(ROOT,p));return{data:JSON.parse(b),hash:createHash('sha256').update(b).digest('hex')};};
const [{data:bank,hash:bankHash},{data:curve,hash:curveHash},{data:analysis,hash:analysisHash},{data:provenance},{data:manifest,hash:manifestHash},{data:runStatus}]=await Promise.all([
  load('data/processed/bank_snapshot.json'),load('data/processed/curve.json'),load('output/analysis.json'),load('output/provenance.json'),load('output/manifest.json'),load('output/run_status.json')]);
if(runStatus.status!=='verified_build'||runStatus.manifest_sha256!==manifestHash)throw new Error('The latest engine build is incomplete, failed, or refers to a different manifest.');
if(manifest.status!=='verified_build'||manifest.artifact_hashes['analysis.json']!==analysisHash)throw new Error('Only a verified, hash-matched analysis may be imported.');
if(!Object.keys(manifest.input_hashes||{}).length)throw new Error('The verified release has no input fingerprints.');
for(const [relative,expected] of Object.entries(manifest.input_hashes)){
  const actual=createHash('sha256').update(await fs.readFile(path.join(ROOT,relative))).digest('hex');
  if(actual!==expected)throw new Error(`Source or implementation changed after the engine build: ${relative}`);
}
if(!analysis.checks?.length||analysis.checks.some(x=>x.passed!==true))throw new Error('Engine controls are missing or failed.');
if(curve.as_of>bank.as_of)throw new Error('Curve date is later than the bank date.');
const cfg=analysis.assumptions;
if(curve.tenors_years.length!==14||curve.zero_rates.length!==14)throw new Error('This case expects the disclosed 14-node saved curve; update the visible interpolation layout for a different input.');
if(cfg.horizon_months!==12||cfg.hedge.tenor_months!==60)throw new Error('The editable case is explicitly 12 months with a 60-month swap.');
const tradeDate=new Date(bank.as_of+'T00:00:00Z');
if(tradeDate.getUTCDate()!==new Date(Date.UTC(tradeDate.getUTCFullYear(),tradeDate.getUTCMonth()+1,0)).getUTCDate())throw new Error('This visible formula case requires an end-of-month trade date.');
const {data:profile,hash:profileHash}=await load('data/processed/maturity_profile.json');
const historicalCredit=profile.reported_annual_context_usd.net_chargeoffs/bank.balance_sheet_usd.loans;
const historicalOperating=profile.reported_annual_context_usd.noninterest_expense/bank.totals_usd.assets;
const wb=Workbook.create();
const names=['Summary','Assumptions','Earnings','Swap','Sources','Engine reference','Engine ledgers'];
const ss=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const NAVY='#142D43',INK='#203C50',TAN='#F4F0E6',LINE='#D7DFE3',GREEN='#267348',BLUE='#2457B4',MUTED='#647788',RED='#B33636';
const money='#,##0.00;(#,##0.00);"—"';
const pct='0.0%;(0.0%);"—"';
const integer='#,##0;(#,##0);"—"';
const col=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const val=(s,a,v)=>s.getRange(a).values=[[v]];
// Shared blue settings E61:E74 have one locally validated model-input column G.
// Resolve every cross-sheet shared-setting link to that column (including ranges).
const formula=(s,a,v)=>{const f=v.replace(/Assumptions!\$?E\$?(?:6[1-9]|7[0-4])(?:\:\$?E\$?(?:6[1-9]|7[0-4]))?/g,x=>x.replaceAll('E','G'));s.getRange(a).formulas=[[f]];s.getRange(a).format.font.color=f.includes('!')?GREEN:'#111111';};
const data=(s,a,v)=>s.getRange(a).values=v;
const note=(s,row,text,last='R')=>{s.mergeCells(`C${row}:${last}${row}`);val(s,`C${row}`,text);s.getRange(`C${row}:${last}${row}`).format={font:{name:'Arial',size:10,color:MUTED},wrapText:true,rowHeight:32};};
const section=(s,row,text,last='R')=>{s.mergeCells(`C${row}:${last}${row}`);val(s,`C${row}`,text);s.getRange(`C${row}:${last}${row}`).format={fill:NAVY,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:24};};
const header=(s,a,v)=>{data(s,a,[v]);s.getRange(a).format={fill:NAVY,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:40,horizontalAlignment:'center'};};
for(const [name,s] of Object.entries(ss)){
  s.showGridLines=false;s.tabColor=name==='Summary'?NAVY:name==='Assumptions'?'#7C9BBA':name.startsWith('Engine')?'#B8C2CA':name==='Sources'?'#CFBE98':'#557B8F';
  s.getRange('A1:AA100').format={font:{name:'Arial',size:10,color:INK},rowHeight:20,verticalAlignment:'center'};
  s.getRange('A:B').format.columnWidth=2.5;s.getRange('C:C').format.columnWidth=34;s.getRange('D:D').format.columnWidth=12;s.getRange('E:E').format.columnWidth=18;s.getRange('F:R').format.columnWidth=14;
  val(s,'C2',name==='Summary'?'Bank ALM | editable research case':name==='Engine ledgers'?'Fixed engine ledgers | complete saved events':name==='Engine reference'?'Fixed engine reference | audited build':name);
  s.getRange('C2:R2').format.borders={bottom:{style:'thin',color:LINE}};s.getRange('C2').format.font={name:'Arial',size:14,bold:true,color:NAVY};s.getRange('C2:R2').format.rowHeight=28;
  val(s,'C4','Active case');formula(s,'E4',"='Assumptions'!$E$7");s.getRange('E4:H4').format.font.color=GREEN;s.getRange('E4').format.font.bold=true;
}

// Source values are immutable historical facts, physically separate from research inputs.
const src=ss.Sources;section(src,7,'Public balance sheet | USD, source values');
header(src,'C9:F9',['Reported / mapped item','Units','Public value','FDIC mapping']);
const balanceKeys=['cash','securities','loans','other_assets','noninterest_deposits','interest_deposits','wholesale_funding','other_liabilities','equity'];
const balanceLabels=['Cash and bank balances','Securities, aggregate book','Net loans','Other assets, residual','Noninterest deposits','Interest-bearing deposits','Wholesale funding','Other liabilities, residual','Total consolidated equity'];
balanceKeys.forEach((k,i)=>data(src,`C${10+i}:F${10+i}`,[[balanceLabels[i],'USD',bank.balance_sheet_usd[k],bank.field_mapping[k]]]));
data(src,'C19:F21',[
  ['Total reported assets','USD',bank.totals_usd.assets,'ASSET × 1,000'],['Total deposits','USD',bank.totals_usd.deposits,'DEP × 1,000'],['Reported 2025 NII','USD',bank.earnings.annual_nii_usd,'NIM × 1,000; full year']]);
src.getRange('C10:F21').format.fill=TAN;src.getRange('E10:E21').setNumberFormat('#,##0;(#,##0);"—"');src.getRange('F10:F21').format.wrapText=true;src.getRange('F:F').format.columnWidth=49;
data(src,'C24:E29',[
  ['Bank / swap trade date',null,new Date(bank.as_of+'T00:00:00Z')],['Curve observation date',null,new Date(curve.as_of+'T00:00:00Z')],['Audited engine build UTC',null,provenance.built_at_utc],['Analysis SHA-256',null,analysisHash],['Bank snapshot SHA-256',null,bankHash],['Curve JSON SHA-256',null,curveHash]]);
src.getRange('E24:E25').setNumberFormat('mmm d, yyyy');src.getRange('E26').setNumberFormat('yyyy-mm-dd hh:mm:ss');src.getRange('E27:R29').format.font.size=9;
section(src,30,'Treasury proxy curve | annual continuous zero rates');header(src,'C31:E31',['Tenor, years','Units','Base zero rate']);
data(src,'C32:E45',curve.tenors_years.map((t,i)=>[t,'decimal',curve.zero_rates[i]]));src.getRange('C32:C45').setNumberFormat('0.0000');src.getRange('E32:E45').setNumberFormat('0.0000%');src.getRange('C32:E45').format.fill=TAN;
section(src,48,'Source and build record');
const sourceLines=[`Bank: ${bank.bank_name}, certificate ${bank.certificate}; ${bank.legal_entity}.`,
  `Bank balances as of ${bank.as_of}; downloaded ${bank.source_records.find(x=>x.source_id.includes('20251231'))?.retrieved_at_utc||bank.source_records[0].retrieved_at_utc}.`,
  `FDIC balance source: ${bank.source_records.find(x=>x.source_id.includes('20251231'))?.source_url||bank.source_records[0].source_url}`,
  `Curve as of ${curve.as_of}; captured ${curve.source_captured_at}. ${curve.source}`,
  `Curve source hash: ${curve.source_sha256}; observation hash: ${curve.selected_observation_sha256}.`,
  ...curve.limitations,
  'Original reported dollars above do not change when a case or blue research assumption changes.',
  'The selected FDIC vintage was captured later than the observation date. This is not a point-in-time backtest.',
  'Refresh full engine: python -S scripts/build_report.py; verify: python -S scripts/verify_release.py; then rerun scripts/build_workbook.mjs with the bundled Node runtime.',
  'Fixed engine imports are not recalculated by Excel. Case formulas use the source snapshot and base curve; preserve those historical sources when editing assumptions.'];
sourceLines.forEach((x,i)=>note(src,49+i,x));src.getRange('C51:R51').format.rowHeight=56;src.freezePanes.freezeRows(9);

// One authoritative selector, active driver above the three editable case inputs.
const a=ss.Assumptions;val(a,'C6','Case number');val(a,'E6',3);val(a,'C7','Selected case');formula(a,'E7','=IF(ISNUMBER(E6),IF(AND(E6>=1,E6<=3,E6=INT(E6)),CHOOSE(E6,"Base","Rising rates / runoff","Falling rates"),"n.a."),"n.a.")');
a.getRange('E6').format={fill:'#EAF1F8',font:{name:'Arial',size:11,bold:true,color:BLUE},horizontalAlignment:'center'};a.getRange('E6').dataValidation={rule:{type:'whole',operator:'between',formula1:1,formula2:3}};
note(a,8,'Change the case number or a blue numeric input. One active build updates; fixed engine reference remains unchanged.');
const selected=analysis.policy_analysis?.selection_status==='selected'?analysis.policy_analysis.policy:null;
const prefund=selected?.prefunding_fraction??0.06,hedge=selected?.hedge_fraction_assets??0.05;
const driverRows={shock:12,beta:18,runoff:24,prefund:30,hedge:36,credit:42,depositLag:48,floatingLag:54};
const drivers=[
  ['shock','Parallel rate shock','bp',[0,200,-200],'Immediate and persistent parallel zero-rate shift; first floating fixing stays locked.'],
  ['beta','Deposit repricing beta','fraction',[cfg.deposits.beta,cfg.deposits.beta,cfg.deposits.beta],'Fraction of the short-rate shock passed to interest-bearing deposits after the lag.'],
  ['runoff','Requested deposit runoff','fraction',[0,0.45,0],'Both deposit buckets run off pro rata using the disclosed monthly weights.'],
  ['prefund','Initial term prefunding','% assets',[prefund,prefund,prefund],'Adds cash and fixed-rate debt before the shock; no additional reactive financing in this case.'],
  ['hedge','Payer-swap notional','% assets',[hedge,hedge,hedge],'Pays base-curve par fixed, receives frozen shocked forwards; Treasury research proxy.'],
  ['credit','Noncash credit-loss proxy','% net loans',[historicalCredit,Math.max(0.01,historicalCredit*2),historicalCredit],'Default = reported 2025 net chargeoffs / year-end net loans. Research proxy reduces modeled loan book and earnings; no cash payment.'],
  ['depositLag','Deposit repricing lag','months',[cfg.deposits.repricing_lag_months,cfg.deposits.repricing_lag_months,cfg.deposits.repricing_lag_months],'Whole months; reprices in month lag + 1.'],
  ['floatingLag','Floating-loan reset lag','months',[cfg.loans.floating_reset_lag_months,cfg.loans.floating_reset_lag_months,cfg.loans.floating_reset_lag_months],'Whole months; reprices in month lag + 1.']];
for(const [id,label,units,cases,explanation]of drivers){const r=driverRows[id];section(a,r-1,label);data(a,`C${r}:E${r+3}`,[[`Active ${label.toLowerCase()}`,units,null],['Base',units,cases[0]],['Rising rates / runoff',units,cases[1]],['Falling rates',units,cases[2]]]);
  const input=`CHOOSE($E$6,E${r+1},E${r+2},E${r+3})`;
  const available=`CHOOSE($E$6,ISNUMBER(E${r+1}),ISNUMBER(E${r+2}),ISNUMBER(E${r+3}))`;
  const valid=id.endsWith('Lag')?`AND(${input}>=0,${input}<=12,${input}=INT(${input}))`:id==='shock'?'TRUE':`AND(${input}>=0,${input}<=1)`;
  formula(a,`E${r}`,`=IF(ISNUMBER($E$6),IF(AND($E$6>=1,$E$6<=3,$E$6=INT($E$6)),IF(${available},IF(${valid},${input},"n.a."),"n.a."),"n.a."),"n.a.")`);
  a.mergeCells(`F${r}:R${r+3}`);val(a,`F${r}`,explanation);a.getRange(`F${r}:R${r+3}`).format={wrapText:true,font:{name:'Arial',size:10,color:MUTED}};
  a.getRange(`E${r}`).format={fill:'#E5F0E8',font:{name:'Arial',size:10,bold:true,color:GREEN}};a.getRange(`E${r+1}:E${r+3}`).format={fill:'#EDF3F9',font:{name:'Arial',size:10,color:BLUE}};
  const fmt=id==='shock'||id.endsWith('Lag')?integer:pct;a.getRange(`E${r}:E${r+3}`).setNumberFormat(fmt);
}
section(a,59,'Shared research conventions | editable blue rates');
const settings=[
 [61,'Cash operating expense / assets',historicalOperating,pct],
 [62,'Fixed-rate share of loans',cfg.loans.fixed_fraction,pct], [63,'Fixed-loan coupon',cfg.loans.fixed_coupon,pct], [64,'Floating-loan opening coupon',cfg.loans.floating_coupon,pct], [65,'Securities coupon',cfg.securities.coupon,pct], [66,'Deposit opening rate',cfg.deposits.interest_rate,pct], [67,'Deposit rate floor',cfg.deposits.minimum_interest_rate,pct], [68,'Existing funding opening coupon',cfg.funding.initial_coupon,pct], [69,'Existing funding shock beta',cfg.funding.initial_repricing_beta,pct], [70,'Prefunding spread',cfg.funding.incremental_spread,pct], [71,'Cash yield spread',cfg.cash.yield_spread,pct], [72,'Swap initial margin',cfg.hedge.initial_margin_fraction,pct], [73,'Swap upfront fee',cfg.hedge.transaction_fee_bps,integer], [74,'Free-cash floor',cfg.cash.floor_fraction_assets,pct], [75,'Contractual swap term, fixed',60,integer], [76,'Cash-case closeout month, fixed',12,integer]];
settings.forEach(([r,l,v,f])=>{data(a,`C${r}:E${r}`,[[l,r===73?'bp':r>=75?'months':'decimal',v]]);a.getRange(`E${r}`).setNumberFormat(f);if(r<75)a.getRange(`E${r}`).format={fill:'#EDF3F9',font:{name:'Arial',size:10,color:BLUE}};});
val(a,'E60','Edit input');val(a,'G60','Model input');a.getRange('E60:G60').format.font.bold=true;
for(const[r,,,fmt]of settings){if(r>=75)continue;const input=`E${r}`;const condition=[62,69,72,74].includes(r)?`AND(${input}>=0,${input}<=1)`:[61,67,73].includes(r)?`${input}>=0`:'TRUE';formula(a,`G${r}`,`=IF(ISNUMBER(${input}),IF(${condition},${input},"n.a."),"n.a.")`);a.getRange(`G${r}`).setNumberFormat(fmt);a.getRange(`G${r}`).format.horizontalAlignment='right';}
note(a,78,'Interest uses static opening loan/securities balances. Credit losses reduce loan book without cash use. Operating expense is paid in cash; noninterest income, taxes, sales, amortization and prepayments are excluded.');
note(a,79,'Collateral is assumed posted in full and obligations settled. A negative free-cash balance or gap to the floor shows required outside funding; this case does not make an optimized feasible-policy decision.');
section(a,81,'Input review | terminal diagnostics');
data(a,'C82:E84',[['Active numeric driver count','expected 8',null],['Active case selector','expected 1–3',null],['Blue inputs / public actuals','separate','Public actuals are on Sources']]);
formula(a,'E82','=COUNT(E12,E18,E24,E30,E36,E42,E48,E54)');formula(a,'E83','=IF(ISNUMBER(E6),IF(AND(E6>=1,E6<=3,E6=INT(E6)),"Valid","Invalid"),"Missing")');a.freezePanes.freezeRows(8);

// Dated monthly swap schedule; base par fixing and shocked conditional values.
const swap=ss.Swap;note(swap,5,'USD millions. 60 monthly ACT/365F coupons, end-of-month dates, no business-day adjustment. Single Treasury proxy curve; no principal exchange.');
data(swap,'C6:E15',[
 ['Swap notional','USDm',null],['Base par fixed rate','decimal',null],['First floating fixing, locked','decimal',null],['Active parallel rate shock','decimal',null],['Opening shocked swap value','USDm',null],['Month-12 closeout value','USDm',null],['First-12-month net coupons','USDm',null],['Base inception value','USDm',null],['Base fixed-leg annuity','years',null],['Fee at inception','USDm',null]]);
formula(swap,'E6','=IF(ISNUMBER(Assumptions!E36),Sources!E19/1000000*Assumptions!E36,"n.a.")');
formula(swap,'E7','=(1-L81)/SUM(O22:O81)');formula(swap,'E8','=(1/L22-1)/G22');formula(swap,'E9','=IF(ISNUMBER(Assumptions!E12),Assumptions!E12/10000,"n.a.")');
formula(swap,'E10','=IF(COUNT(U22:U81)=60,SUM(U22:U81),"n.a.")');formula(swap,'E11','=V33');formula(swap,'E12','=IF(COUNT(T22:T33)=12,SUM(T22:T33),"n.a.")');formula(swap,'E13','=IF(COUNT(Y22:Y81)=60,SUM(Y22:Y81),"n.a.")');formula(swap,'E14','=SUM(O22:O81)');formula(swap,'E15','=IF(AND(ISNUMBER(E6),ISNUMBER(Assumptions!E73)),E6*Assumptions!E73/10000,"n.a.")');swap.getRange('E6:E15').setNumberFormat(money);swap.getRange('E7:E9').setNumberFormat('0.0000%');
section(swap,18,'Contractual cash flows and conditional values','Z');
note(swap,19,'Base columns calibrate par once. Scenario columns use a parallel shift. Remaining value discounts the original future coupons by D(t) / D(u); month-12 closeout is the ex-coupon value.','Z');
const sh=['Month','Accrual start','Payment date','Days','ACT/365F','Start time, years','End time, years','Curve bracket','Base zero','Base DF','Shock DF','Start shock DF','Base annuity','Curve forward','Floating fixing','Fixed payment','Float receipt','Net coupon','Net PV at open','Ex-coupon value','Base float coupon','Base net coupon','Base net PV','PV roll residual'];
header(swap,'C21:Z21',sh);swap.getRange('C:C').format.columnWidth=34;swap.getRange('D:D').format.columnWidth=15;swap.getRange('E:E').format.columnWidth=18;swap.getRange('F:Z').format.columnWidth=14;
for(let m=1;m<=60;m++){const r=21+m;val(swap,`C${r}`,m);formula(swap,`D${r}`,m===1?'=Sources!$E$24':`=E${r-1}`);formula(swap,`E${r}`,`=EOMONTH(Sources!$E$24,C${r})`);formula(swap,`F${r}`,`=E${r}-D${r}`);formula(swap,`G${r}`,`=F${r}/365`);formula(swap,`H${r}`,`=(D${r}-Sources!$E$24)/365`);formula(swap,`I${r}`,`=(E${r}-Sources!$E$24)/365`);formula(swap,`J${r}`,`=MIN(13,MAX(1,MATCH(MAX(I${r},Sources!$C$32),Sources!$C$32:$C$45,1)))`);
  formula(swap,`K${r}`,`=IF(I${r}<=Sources!$C$32,Sources!$E$32,IF(I${r}>=Sources!$C$45,Sources!$E$45,INDEX(Sources!$E$32:$E$45,J${r})+(I${r}-INDEX(Sources!$C$32:$C$45,J${r}))/(INDEX(Sources!$C$32:$C$45,J${r}+1)-INDEX(Sources!$C$32:$C$45,J${r}))*(INDEX(Sources!$E$32:$E$45,J${r}+1)-INDEX(Sources!$E$32:$E$45,J${r}))))`);
  formula(swap,`L${r}`,`=EXP(-K${r}*I${r})`);formula(swap,`M${r}`,`=IF(ISNUMBER($E$9),EXP(-(K${r}+$E$9)*I${r}),"n.a.")`);formula(swap,`N${r}`,m===1?'=1':`=M${r-1}`);formula(swap,`O${r}`,`=G${r}*L${r}`);
  formula(swap,`P${r}`,`=IF(AND(ISNUMBER(N${r}),ISNUMBER(M${r})),(N${r}/M${r}-1)/G${r},"n.a.")`);formula(swap,`Q${r}`,m===1?'=$E$8':`=P${r}`);formula(swap,`R${r}`,`=IF(ISNUMBER($E$6),$E$6*$E$7*G${r},"n.a.")`);formula(swap,`S${r}`,`=IF(AND(ISNUMBER($E$6),ISNUMBER(Q${r})),$E$6*Q${r}*G${r},"n.a.")`);formula(swap,`T${r}`,`=IF(AND(ISNUMBER(R${r}),ISNUMBER(S${r})),S${r}-R${r},"n.a.")`);formula(swap,`U${r}`,`=IF(AND(ISNUMBER(T${r}),ISNUMBER(M${r})),T${r}*M${r},"n.a.")`);
  formula(swap,`V${r}`,m===60?'=0':`=IF(AND(ISNUMBER(M${r}),COUNT(U${r+1}:U81)=${60-m}),SUM(U${r+1}:U81)/M${r},"n.a.")`);
  formula(swap,`W${r}`,`=IF(ISNUMBER($E$6),$E$6*(${m===1?'1':`L${r-1}`}/L${r}-1),"n.a.")`);formula(swap,`X${r}`,`=IF(AND(ISNUMBER(W${r}),ISNUMBER(R${r})),W${r}-R${r},"n.a.")`);formula(swap,`Y${r}`,`=IF(ISNUMBER(X${r}),X${r}*L${r},"n.a.")`);formula(swap,`Z${r}`,`=IF(AND(ISNUMBER(${m===1?'$E$10':`V${r-1}`}),ISNUMBER(M${r}),ISNUMBER(T${r}),ISNUMBER(V${r})),${m===1?'$E$10':`V${r-1}`}*N${r}/M${r}-T${r}-V${r},"n.a.")`);
}
swap.getRange('D22:E81').setNumberFormat('mmm d, yyyy');swap.getRange('G22:Q81').setNumberFormat('0.0000');swap.getRange('K22:K81').setNumberFormat('0.0000%');swap.getRange('P22:Q81').setNumberFormat('0.0000%');swap.getRange('R22:Z81').setNumberFormat(money);swap.getRange('Z22:Z81').conditionalFormats.addCustom('ABS(Z22)>0.000001',{font:{color:RED},fill:'#FCE8E6'});swap.freezePanes.freezeRows(21);swap.freezePanes.freezeColumns(5);

// A transparent simplified free-cash/earnings case, not a duplicate Python engine.
const e=ss.Earnings;note(e,5,'USD millions. Static asset balances; deposit runoff; full collateral settlement; no reactive borrowing or sales. The outside-funding gap is a diagnostic, not a solved funding policy.');
val(e,'C7','Free-cash / collateral case');header(e,'F8:R8',['Opening',...Array.from({length:12},(_,i)=>`Month ${i+1}`)]);
const labels={9:'Payment date',10:'Accrual fraction, ACT/365F',12:'Public cash at opening',13:'Public securities, static',14:'Public net loans, interest basis',15:'Opening interest deposits',16:'Opening noninterest deposits',17:'Public existing wholesale funding',18:'Initial term prefunding',19:'Payer-swap notional',20:'Free-cash floor',22:'Interest-bearing deposit withdrawals',23:'Noninterest deposit withdrawals',24:'Ending interest-bearing deposits',25:'Ending noninterest deposits',27:'Cash opening / previous close',28:'Cash simple annual index + spread',29:'Fixed-loan interest',30:'Floating-loan interest',31:'Securities interest',32:'Cash interest',33:'Total modeled interest income',35:'Interest-bearing deposit rate',36:'Deposit interest expense',37:'Existing wholesale interest',38:'Term-prefunding interest',39:'Total modeled interest expense',40:'Raw bank NII',42:'Assumed noncash credit loss',43:'Net swap coupon, cash settled',44:'Posted-collateral interest',45:'Terminal closeout cash',46:'Case earnings after costs / hedge',47:'Cash operating-expense proxy',48:'Swap ex-coupon value before closeout',49:'Required initial margin',50:'Required posted variation margin',51:'Total required posted collateral',52:'Received VM, segregated / unavailable',53:'Change in posted collateral',54:'Upfront swap fee',55:'Net deposit withdrawals',56:'Ending free cash',57:'Outside funding needed to cash floor',58:'Running case earnings',60:'Cash rollforward residual',61:'Swap PV rollforward residual',67:'Opening modeled net loan book',68:'Noncash credit-loss deduction',69:'Ending modeled net loan book'};
for(const[r,l]of Object.entries(labels))val(e,`C${r}`,l);
e.getRange('C:C').format.columnWidth=41;e.getRange('D:E').format.columnWidth=3;e.getRange('F:R').format.columnWidth=15;e.getRange('F10:R61').setNumberFormat(money);e.getRange('F10:R10').setNumberFormat('0.0000');
const publicMap={12:10,13:11,14:12,15:15,16:14,17:16};
for(const[r,sourceRow]of Object.entries(publicMap)){formula(e,`F${r}`,`=Sources!E${sourceRow}/1000000`);for(let m=1;m<=12;m++)formula(e,`${col(5+m)}${r}`,`=$F$${r}`);}
formula(e,'F9','=Sources!E24');formula(e,'F10','=0');formula(e,'F18','=IF(ISNUMBER(Assumptions!E30),Sources!E19/1000000*Assumptions!E30,"n.a.")');formula(e,'F19','=Swap!E6');formula(e,'F20','=IF(ISNUMBER(Assumptions!E74),Sources!E19/1000000*Assumptions!E74,"n.a.")');
formula(e,'F27','=IF(COUNT(F12,F18)=2,F12+F18,"n.a.")');formula(e,'F48','=Swap!E10');formula(e,'F49','=IF(AND(ISNUMBER(F19),ISNUMBER(Assumptions!E72)),F19*Assumptions!E72,"n.a.")');formula(e,'F50','=IF(ISNUMBER(F48),MAX(-F48,0),"n.a.")');formula(e,'F51','=IF(COUNT(F49:F50)=2,SUM(F49:F50),"n.a.")');formula(e,'F52','=IF(ISNUMBER(F48),MAX(F48,0),"n.a.")');formula(e,'F53','=F51');formula(e,'F54','=Swap!E15');formula(e,'F56','=IF(COUNT(F27,F53,F54)=3,F27-F53-F54,"n.a.")');formula(e,'F57','=IF(COUNT(F20,F56)=2,MAX(F20-F56,0),"n.a.")');formula(e,'F58','=IF(ISNUMBER(F54),-F54,"n.a.")');
for(let m=1;m<=12;m++){const c=col(5+m),p=col(4+m),r=21+m;
  formula(e,`${c}9`,`=Swap!E${r}`);formula(e,`${c}10`,`=Swap!G${r}`);for(const row of[18,19,20])formula(e,`${c}${row}`,`=$F$${row}`);
  formula(e,`${c}22`,`=IF(ISNUMBER(Assumptions!$E$24),$F$15*Assumptions!$E$24*Sources!${col(5+m)}67,"n.a.")`);formula(e,`${c}23`,`=IF(ISNUMBER(Assumptions!$E$24),$F$16*Assumptions!$E$24*Sources!${col(5+m)}67,"n.a.")`);
  formula(e,`${c}24`,`=IF(ISNUMBER(${c}22),${m===1?'$F$15':`${p}24`}-${c}22,"n.a.")`);formula(e,`${c}25`,`=IF(ISNUMBER(${c}23),${m===1?'$F$16':`${p}25`}-${c}23,"n.a.")`);formula(e,`${c}27`,`=${p}56`);
  formula(e,`${c}28`,`=IF(AND(ISNUMBER(Assumptions!$E$12),ISNUMBER(Assumptions!$E$71)),(EXP((Sources!$E$33+Assumptions!$E$12/10000)*Sources!$C$33)-1)/Sources!$C$33+Assumptions!$E$71,"n.a.")`);
  formula(e,`${c}29`,`=IF(COUNT(Assumptions!$E$62:$E$63)=2,$F$14*Assumptions!$E$62*Assumptions!$E$63*${c}10,"n.a.")`);
  formula(e,`${c}30`,`=IF(COUNT(Assumptions!$E$12,Assumptions!$E$54,Assumptions!$E$62,Assumptions!$E$64)=4,$F$14*(1-Assumptions!$E$62)*(Assumptions!$E$64+IF(${m}>Assumptions!$E$54,Assumptions!$E$12/10000,0))*${c}10,"n.a.")`);
  formula(e,`${c}31`,`=IF(ISNUMBER(Assumptions!$E$65),$F$13*Assumptions!$E$65*${c}10,"n.a.")`);formula(e,`${c}32`,`=IF(COUNT(${c}27:${c}28)=2,MAX(${c}27,0)*${c}28*${c}10,"n.a.")`);formula(e,`${c}33`,`=IF(COUNT(${c}29:${c}32)=4,SUM(${c}29:${c}32),"n.a.")`);
  formula(e,`${c}35`,`=IF(COUNT(Assumptions!$E$12,Assumptions!$E$18,Assumptions!$E$48,Assumptions!$E$66:$E$67)=5,MAX(Assumptions!$E$67,Assumptions!$E$66+IF(${m}>Assumptions!$E$48,Assumptions!$E$18*Assumptions!$E$12/10000,0)),"n.a.")`);
  const openingDeposits=m===1?'$F$15':`${p}24`;
  formula(e,`${c}36`,`=IF(COUNT(${openingDeposits},${c}35)=2,${openingDeposits}*${c}35*${c}10,"n.a.")`);formula(e,`${c}37`,`=IF(COUNT(Assumptions!$E$12,Assumptions!$E$68:$E$69)=3,$F$17*(Assumptions!$E$68+Assumptions!$E$69*Assumptions!$E$12/10000)*${c}10,"n.a.")`);
  formula(e,`${c}38`,`=IF(COUNT($F$18,Assumptions!$E$70)=2,$F$18*((EXP(Sources!$E$33*Sources!$C$33)-1)/Sources!$C$33+Assumptions!$E$70)*${c}10,"n.a.")`);formula(e,`${c}39`,`=IF(COUNT(${c}36:${c}38)=3,SUM(${c}36:${c}38),"n.a.")`);formula(e,`${c}40`,`=IF(COUNT(${c}33,${c}39)=2,${c}33-${c}39,"n.a.")`);
  formula(e,`${c}42`,`=IF(ISNUMBER(Assumptions!$E$42),$F$14*Assumptions!$E$42*${c}10,"n.a.")`);formula(e,`${c}43`,`=Swap!T${r}`);formula(e,`${c}44`,`=IF(COUNT(${p}51,Swap!P${r})=2,${p}51*Swap!P${r}*${c}10,"n.a.")`);formula(e,`${c}45`,m===12?'=Swap!E11':'=0');formula(e,`${c}47`,`=IF(ISNUMBER(Assumptions!$E$61),Sources!$E$19/1000000*Assumptions!$E$61*${c}10,"n.a.")`);formula(e,`${c}46`,`=IF(COUNT(${c}40,${c}42:${c}45,${c}47)=6,${c}40-${c}42+SUM(${c}43:${c}45)-${c}47,"n.a.")`);
  formula(e,`${c}48`,`=Swap!V${r}`);formula(e,`${c}49`,m===12?'=0':'=$F$49');formula(e,`${c}50`,m===12?'=0':`=IF(ISNUMBER(${c}48),MAX(-${c}48,0),"n.a.")`);formula(e,`${c}51`,`=IF(COUNT(${c}49:${c}50)=2,SUM(${c}49:${c}50),"n.a.")`);formula(e,`${c}52`,m===12?'=0':`=IF(ISNUMBER(${c}48),MAX(${c}48,0),"n.a.")`);formula(e,`${c}53`,`=IF(COUNT(${c}51,${p}51)=2,${c}51-${p}51,"n.a.")`);formula(e,`${c}54`,'=0');formula(e,`${c}55`,`=IF(COUNT(${c}22:${c}23)=2,SUM(${c}22:${c}23),"n.a.")`);formula(e,`${c}56`,`=IF(COUNT(${c}27,${c}42,${c}46,${c}53:${c}55)=6,${c}27+${c}46+${c}42-${c}53-${c}54-${c}55,"n.a.")`);formula(e,`${c}57`,`=IF(COUNT(${c}20,${c}56)=2,MAX(${c}20-${c}56,0),"n.a.")`);formula(e,`${c}58`,`=IF(COUNT(${p}58,${c}46)=2,${p}58+${c}46,"n.a.")`);
  formula(e,`${c}60`,`=IF(COUNT(${c}56,${c}27,${c}42,${c}46,${c}53:${c}55)=7,${c}56-(${c}27+${c}46+${c}42-${c}53-${c}54-${c}55),"n.a.")`);formula(e,`${c}61`,`=Swap!Z${r}`);
  formula(e,`${c}67`,m===1?'=$F$14':`=${p}69`);formula(e,`${c}68`,`=${c}42`);formula(e,`${c}69`,`=IF(COUNT(${c}67:${c}68)=2,${c}67-${c}68,"n.a.")`);
}
e.getRange('F9:R9').setNumberFormat('mmm d, yyyy');for(const row of[28,35]){e.getRange(`F${row}:R${row}`).setNumberFormat(pct);e.getRange(`C${row}:R${row}`).format.font.italic=true;}
for(const row of[33,39,40,46,51,56,57,58])e.getRange(`C${row}:R${row}`).format={fill:row===57?'#FAEEE8':TAN,borders:{top:{style:'thin',color:LINE}},font:{name:'Arial',size:10,bold:true,color:INK}};
e.getRange('F57:R57').conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0.000001,format:{font:{color:RED},fill:'#FCE8E6'}});e.getRange('F56:R56').conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{font:{color:RED},fill:'#FCE8E6'}});
e.getRange('G60:R61').conditionalFormats.addCustom('ABS(G60)>0.000001',{font:{color:RED},fill:'#FCE8E6'});section(e,64,'Scope and formula review');note(e,65,'No business or summary formula reads the review rows above. NII is a cash-flow approximation, not reported profit. Negative cash explicitly represents a funding need; it is not repaired by a balancing plug.');note(e,66,'Credit losses reduce earnings and modeled net loan book, but do not use cash. Interest still uses opening net loans as a simplifying assumption. Cash operating expense uses the historical NONIX/assets proxy.');e.getRange('G67:R69').setNumberFormat(money);e.freezePanes.freezeRows(10);e.freezePanes.freezeColumns(5);
section(src,65,'Fixed monthly runoff allocation');header(src,'G66:R66',Array.from({length:12},(_,i)=>`Month ${i+1}`));data(src,'G67:R67',[cfg.runoff_monthly_weights]);src.getRange('G67:R67').setNumberFormat(pct);note(src,69,'Allocation sums to 100% of the requested runoff. These are model assumptions imported from the engine configuration, not observed bank withdrawals.');
section(src,73,'Reported 2025 cost context | USD, fixed facts');
data(src,'C75:E77',[
 ['Noninterest expense, full year','USD',profile.reported_annual_context_usd.noninterest_expense],
 ['Net chargeoffs, full year','USD',profile.reported_annual_context_usd.net_chargeoffs],
 ['Credit-loss provision, full year','USD',profile.reported_annual_context_usd.provision_for_credit_losses]]);
src.getRange('C75:E77').format.fill=TAN;src.getRange('E75:E77').setNumberFormat('#,##0;(#,##0);"—"');
section(e,73,'Historical ratios | actuals only, assumption context');data(e,'C74:E79',[
 ['Reported annual noninterest expense','USDm',null],['Reported annual net chargeoffs','USDm',null],['Reported year-end total assets','USDm',null],['Reported year-end net loans','USDm',null],['NONIX / year-end total assets','ratio',null],['Net chargeoffs / year-end net loans','ratio',null]]);
formula(e,'E74','=Sources!E75/1000000');formula(e,'E75','=Sources!E76/1000000');formula(e,'E76','=Sources!E19/1000000');formula(e,'E77','=Sources!E12/1000000');formula(e,'E78','=E74/E76');formula(e,'E79','=E75/E77');e.getRange('E74:E77').setNumberFormat(money);e.getRange('E78:E79').setNumberFormat('0.0000%');e.getRange('D:E').format.columnWidth=12;
val(a,'H61','Historical ratio');formula(a,'J61','=Earnings!E78');a.getRange('J61').setNumberFormat('0.0000%');val(a,'K61','Default seeds blue input');
note(src,81,`Cost context: ${profile.source_records[0].source_url}`);src.getRange('C81:R81').format.rowHeight=70;note(src,82,`Maturity / context profile SHA-256 ${profileHash}; captured ${profile.source_records[0].retrieved_at_utc}.`);note(src,83,'The two ratios seed editable research assumptions. Net chargeoffs and provision are different reported measures; the modeled credit-loss proxy is not an accounting provision forecast.');

// Fixed imported reference paths, with no Excel formulas or implied automatic refresh.
const ref=ss['Engine reference'];note(ref,5,`FIXED IMPORT — audited Python build ${provenance.built_at_utc}. Analysis SHA-256 ${analysisHash}.`, 'Q');note(ref,6,'Changing Excel inputs does not update these policy outcomes, nonlinear bank EVE, shaped scenarios or full ledgers. Rerun and verify Python, then rebuild this workbook.','Q');
section(ref,8,'Saved joint funding / hedge policy grid','Q');
header(ref,'C9:Q9',['Policy ID','Prefund % assets','Funding order','Hedge % assets','Swap notional USDm','Feasible','Worst earnings USDm','Worst NII USDm','Worst ΔEVE USDm','Peak unpaid runoff USDm','Peak cash-floor gap USDm','Peak unpaid margin USDm','Peak unpaid payment USDm','Selected in engine','Risk result']);
data(ref,`C10:Q${9+analysis.policies.candidates.length}`,analysis.policies.candidates.map(p=>[p.id,p.prefunding_fraction,p.funding_order==='borrow_first'?'Borrow first':'Sell first',p.hedge_fraction_assets,p.swap_notional_usd/1e6,p.feasible?'Yes':'No',p.worst_case_earnings_usd/1e6,p.worst_case_nii_usd/1e6,p.worst_case_delta_eve_usd/1e6,p.max_unfunded_withdrawals_usd/1e6,p.max_cash_floor_shortfall_usd/1e6,p.max_unfunded_margin_usd/1e6,p.max_payment_payable_usd/1e6,p.id===analysis.policies.selected_policy_id?'Yes':'No',p.feasible?'Within assumed limits':'One or more assumed breaches']));
ref.getRange('C:C').format.columnWidth=48;ref.getRange('D:Q').format.columnWidth=17;ref.getRange('D10:D39').setNumberFormat(pct);ref.getRange('F10:F39').setNumberFormat(pct);ref.getRange('G10:G39').setNumberFormat(money);ref.getRange('I10:O39').setNumberFormat(money);ref.getRange('Q:Q').format.columnWidth=29;
section(ref,42,'Objective and unchanged engine constraints','Q');
note(ref,43,analysis.policies.objective,'Q');note(ref,44,`Feasible ${analysis.policies.feasible_count}/${analysis.policies.candidates.length}; selected ${analysis.policies.selected_policy_id||'none'}. Selection is an in-sample research result, not a bank recommendation.`,'Q');note(ref,45,JSON.stringify(analysis.policies.constraints),'Q');note(ref,46,analysis.policies.caveat,'Q');
const paths=[...analysis.scenarios.map(s=>({group:'Unhedged reference',policy:'reference',s})),...analysis.policies.candidates.flatMap(p=>p.scenarios.map(s=>({group:'Joint candidate',policy:p.id,s})))];
const scenarioFirst=['id','name','status','rate_shock_bps','deposit_runoff_pct','nii_12m_usd','modeled_earnings_usd','delta_eve_usd','minimum_observed_cash_usd','max_collateral_required_usd'];
const scalarKeys=[...new Set([...scenarioFirst,...paths.flatMap(x=>Object.keys(x.s).filter(k=>!['monthly','initial_event'].includes(k))).sort()])];
const sr=50,endCol=col(3+scalarKeys.length);section(ref,48,`All ${paths.length} saved scenario summaries | fixed USD / decimals`,'Q');
header(ref,`C${sr}:${endCol}${sr}`,['Import group','Policy ID',...scalarKeys.map(k=>k.replaceAll('_',' '))]);
data(ref,`C${sr+1}:${endCol}${sr+paths.length}`,paths.map(x=>[x.group,x.policy,...scalarKeys.map(k=>x.s[k]==null?null:typeof x.s[k]==='object'?JSON.stringify(x.s[k]):x.s[k])]));ref.getRange(`C${sr}:${endCol}${sr+paths.length}`).format.font={name:'Arial',size:10,color:INK};ref.getRange(`E:${endCol}`).format.columnWidth=20;ref.getRange('D:D').format.columnWidth=48;ref.getRange(`C${sr}:${endCol}${sr}`).format.fill=NAVY;ref.getRange(`C${sr}:${endCol}${sr}`).format.font.color='#FFFFFF';ref.getRange(`C${sr}:${endCol}${sr}`).format.rowHeight=48;ref.getRange(`C${sr}:${endCol}${sr}`).format.wrapText=true;
scalarKeys.forEach((k,i)=>{if(k.endsWith('_usd'))ref.getRange(`${col(i+4)}${sr+1}:${col(i+4)}${sr+paths.length}`).setNumberFormat('#,##0.00;(#,##0.00);"—"');});ref.freezePanes.freezeRows(9);ref.freezePanes.freezeColumns(4);
const led=ss['Engine ledgers'];note(led,5,'FIXED IMPORT — every saved opening event and monthly event from the reference and every joint candidate. USD and decimal rates exactly as engine output; JSON array/object metadata is retained as text.','S');note(led,6,`Engine build ${provenance.built_at_utc}; analysis SHA-256 ${analysisHash}. Excel inputs do not modify these rows.`,'S');
const events=paths.flatMap(x=>[x.s.initial_event,...x.s.monthly].filter(Boolean).map(ev=>({group:x.group,policy:x.policy,scenario:x.s.id,ev})));
const eventFirst=['month','swap_payment_date','cash_usd','loans_usd','securities_usd','deposits_usd','wholesale_funding_usd','equity_usd','nii_usd','derivative_value_usd','collateral_required_usd','collateral_posted_usd','received_collateral_cash_usd'];
const evKeys=[...new Set([...eventFirst,...events.flatMap(x=>Object.keys(x.ev)).sort()])];const ledEnd=col(4+evKeys.length);
header(led,`C9:${ledEnd}9`,['Import group','Policy ID','Scenario ID',...evKeys.map(k=>k.replaceAll('_',' '))]);
data(led,`C10:${ledEnd}${9+events.length}`,events.map(x=>[x.group,x.policy,x.scenario,...evKeys.map(k=>x.ev[k]==null?null:typeof x.ev[k]==='object'?JSON.stringify(x.ev[k]):x.ev[k])]));led.getRange(`C10:${ledEnd}${9+events.length}`).format.font={name:'Arial',size:10,color:INK};led.getRange(`C9:${ledEnd}9`).format.rowHeight=48;led.getRange(`C:${ledEnd}`).format.columnWidth=20;led.getRange('D:D').format.columnWidth=48;led.getRange('E:E').format.columnWidth=24;evKeys.forEach((k,i)=>{if(k.endsWith('_usd'))led.getRange(`${col(i+5)}10:${col(i+5)}${9+events.length}`).setNumberFormat('#,##0.00;(#,##0.00);"—"');if(k.endsWith('_date'))led.getRange(`${col(i+5)}10:${col(i+5)}${9+events.length}`).setNumberFormat('mmm d, yyyy');});led.freezePanes.freezeRows(9);led.freezePanes.freezeColumns(5);

// Output reads only completed builds, never review diagnostics.
const sum=ss.Summary;note(sum,5,`${bank.bank_name} | ${bank.as_of} balance sheet and ${curve.as_of} Treasury proxy. Editable research case; aggregate public balances plus assumed behavior.`);
section(sum,7,'Active Excel case | USD millions');data(sum,'C9:E19',[
 ['Raw bank NII, 12 months',null,null],['Noncash credit-loss deduction',null,null],['Net swap coupons, 12 months',null,null],['Posted collateral interest',null,null],['Terminal swap closeout value',null,null],['Case earnings after costs / hedge / fee',null,null],['Peak required posted collateral',null,null],['Minimum free cash, opening + month ends',null,null],['Peak outside funding needed to floor',null,null],['Swap notional',null,null],['Base par fixed rate',null,null]]);
const totals={9:'=IF(COUNT(Earnings!G40:R40)=12,SUM(Earnings!G40:R40),"n.a.")',10:'=IF(COUNT(Earnings!G42:R42)=12,SUM(Earnings!G42:R42),"n.a.")',11:'=Swap!E12',12:'=IF(COUNT(Earnings!G44:R44)=12,SUM(Earnings!G44:R44),"n.a.")',13:'=Swap!E11',14:'=Earnings!R58',15:'=IF(COUNT(Earnings!F51:R51)=13,MAX(Earnings!F51:R51),"n.a.")',16:'=IF(COUNT(Earnings!F56:R56)=13,MIN(Earnings!F56:R56),"n.a.")',17:'=IF(COUNT(Earnings!F57:R57)=13,MAX(Earnings!F57:R57),"n.a.")',18:'=Swap!E6',19:'=Swap!E7'};
Object.entries(totals).forEach(([r,f])=>formula(sum,`E${r}`,f));sum.getRange('E9:E18').setNumberFormat(money);sum.getRange('E19').setNumberFormat('0.0000%');sum.getRange('C14:E14').format={fill:TAN,font:{name:'Arial',size:11,bold:true,color:NAVY},borders:{top:{style:'thin',color:LINE}}};sum.getRange('E9:E19').format.font.color=NAVY;
val(sum,'C20','Cash operating expense, 12 months');formula(sum,'E20','=IF(COUNT(Earnings!G47:R47)=12,SUM(Earnings!G47:R47),"n.a.")');sum.getRange('E20').setNumberFormat(money);
sum.mergeCells('G9:R13');val(sum,'G9','A payer swap gains value when rates rise, but may require posted variation margin when rates fall. Compare the margin need and free-cash gap here; the full bank EVE/policy decision remains the fixed Python reference.');sum.getRange('G9:R13').format={fill:TAN,wrapText:true,font:{name:'Arial',size:11,color:INK}};
sum.mergeCells('G15:R19');val(sum,'G15','Start on Assumptions: select 1–3, then edit the blue driver values. Fixed public facts use tan rows. Green links show cross-sheet flow; calculations are black. Excel recalculates this case; changing inputs does not rerun the engine optimizer.');sum.getRange('G15:R19').format={wrapText:true,font:{name:'Arial',size:10,color:MUTED}};
section(sum,22,'Free cash and collateral | active case');
header(sum,'C43:F43',['Event','Free cash USDm','Posted collateral USDm','Funding gap USDm']);
for(let m=0;m<=12;m++){const r=44+m,c=col(5+m);val(sum,`C${r}`,m===0?'Opening':`Month ${m}`);formula(sum,`D${r}`,`=Earnings!${c}56`);formula(sum,`E${r}`,`=Earnings!${c}51`);formula(sum,`F${r}`,`=Earnings!${c}57`);}sum.getRange('D44:F56').setNumberFormat(money);
const chart=sum.charts.add('line',sum.getRange('C43:E56'));chart.title='Free cash and posted collateral (USDm)';chart.titleTextStyle.typeface='Arial';chart.titleTextStyle.fontSize=11;chart.legend={position:'top',textStyle:{typeface:'Arial',fontSize:10}};chart.xAxis={axisType:'textAxis',textStyle:{typeface:'Arial',fontSize:10}};chart.yAxis={numberFormatCode:'#,##0',numberFormatSourceLinked:false,textStyle:{typeface:'Arial',fontSize:10}};chart.setPosition('C24','R41');chart.series.items[0].line={fill:NAVY,style:'solid',width:2};chart.series.items[0].fill=NAVY;chart.series.items[1].line={fill:'#B48035',style:'solid',width:2};chart.series.items[1].fill='#B48035';
section(sum,59,'Interpretation and fixed reference');note(sum,60,'This Excel case isolates repricing, prefunding, hedge cash flows and collateral. It excludes noninterest income and taxes, so case earnings are not reported net income. Full EVE and constrained optimal policy remain fixed imports.');note(sum,61,'Engine reference and Engine ledgers contain the fixed verified Python result. The spreadsheet is editable within its stated scope; source/build refresh instructions and hashes are on Sources.');
val(sum,'C63','Fixed engine baseline NII, USDm');val(sum,'E63',analysis.baseline.nii_12m_usd/1e6);val(sum,'C64','Public historical 2025 NII, USDm');formula(sum,'E64','=Sources!E21/1000000');val(sum,'C65','Fixed engine feasible policies');val(sum,'E65',`${analysis.policies.feasible_count}/${analysis.policies.candidates.length}`);sum.getRange('E63:E64').setNumberFormat(money);note(sum,67,'Reported historical NII and research case NII differ in period and methodology. Do not force either approximation to reconcile to historical earnings.');

// Necessary computational validation and change/recalculate/restore evidence.
await fs.mkdir(path.dirname(OUT),{recursive:true});await fs.mkdir(PREVIEW,{recursive:true});
const numberAt=(s,c)=>{const v=s.getRange(c).values[0][0];if(typeof v!=='number'||!Number.isFinite(v))throw new Error(`${s.name||'sheet'}!${c} is not finite: ${v}`);return v;};
const assert=(ok,msg)=>{if(!ok)throw new Error(msg);};
const formulaErrorPattern=/^#(?:REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!|SPILL!|CALC!)$/;
const formulaErrors=()=>Object.entries(ss).flatMap(([sheet,s])=>{
  const errors=[];
  s.getUsedRange(true).values.forEach((row,r)=>row.forEach((value,c)=>{
    if(typeof value==='string'&&formulaErrorPattern.test(value))errors.push({sheet,used_range_row:r+1,used_range_column:c+1,error:value});
  }));
  return errors;
});
const assertNoFormulaErrors=label=>{const errors=formulaErrors();assert(errors.length===0,`${label}: ${JSON.stringify(errors.slice(0,10))}`);return{sheet_count:names.length,error_count:errors.length};};
wb.recalculate();
const observations=[];
const inputValidityRegressions=[];
const initialNII=numberAt(sum,'E9'),initialMargin=numberAt(sum,'E15'),initialCash=numberAt(sum,'E16'),initialEarnings=numberAt(sum,'E14'),initialOpeningCash=numberAt(e,'F27');
const assertDefaultRestored=label=>assert(numberAt(sum,'E9')===initialNII&&numberAt(sum,'E15')===initialMargin&&numberAt(sum,'E16')===initialCash&&numberAt(sum,'E14')===initialEarnings&&numberAt(e,'F27')===initialOpeningCash,`${label}: restored default changed`);
const publicBefore=JSON.stringify(src.getRange('E10:E21').values);
const costFactsBefore=JSON.stringify(src.getRange('E75:E79').values);
const editRestore=(address,value,metric,expectedChange,label)=>{const old=a.getRange(address).values[0][0],before=numberAt(sum,metric);val(a,address,value);wb.recalculate();const after=numberAt(sum,metric);assert(expectedChange(before,after),label);observations.push({test:label,input:address,before,after});val(a,address,old);wb.recalculate();assert(Math.abs(numberAt(sum,metric)-before)<1e-6,`${label}: restore failed`);};
editRestore('E21',0.75,'E9',(b,x)=>x>b,'Higher deposit beta reduces deposit expense in falling rates');
editRestore('E39',a.getRange('E39').values[0][0]*2,'E15',(b,x)=>Math.abs(x-2*b)<1e-6,'Double hedge notional doubles required collateral');
editRestore('E45',0.01,'E14',(b,x)=>x<b,'Higher noncash credit loss reduces case earnings');
editRestore('E61',historicalOperating*1.2,'E16',(b,x)=>x<b,'Higher cash operating expense lowers free cash');
editRestore('E6',1,'E15',(b,x)=>x<b,'Base case lowers posted variation margin');
// Rising-rate runoff uses opening deposits for interest, then settles withdrawals at month end.
val(a,'E6',2);wb.recalculate();assert(numberAt(e,'G24')<numberAt(e,'F15'),'Runoff case must reduce ending deposits');assert(Math.abs(numberAt(e,'G36')-numberAt(e,'F15')*numberAt(e,'G35')*numberAt(e,'G10'))<1e-6,'Deposit expense must use opening balance');assert(Math.abs(numberAt(e,'H36')-numberAt(e,'G24')*numberAt(e,'H35')*numberAt(e,'H10'))<1e-6,'Subsequent deposit expense must use prior closing balance');val(a,'E6',3);wb.recalculate();
for(const[address,invalid]of[['E72',-0.02],['E62',1.2],['E61',-0.01]]){const old=a.getRange(address).values[0][0];val(a,address,invalid);wb.recalculate();assert(sum.getRange('E9').values[0][0]==='n.a.'||sum.getRange('E14').values[0][0]==='n.a.',`Invalid shared ${address} must propagate unavailable`);val(a,address,old);wb.recalculate();}
const creditBefore=a.getRange('E45').values[0][0],cashBefore=numberAt(e,'R56'),bookBefore=numberAt(e,'R69');val(a,'E45',0.01);wb.recalculate();assert(Math.abs(numberAt(e,'R56')-cashBefore)<1e-6,'Noncash credit-loss change must not use free cash');assert(numberAt(e,'R69')<bookBefore,'Noncash loss must reduce modeled net loan book');val(a,'E45',creditBefore);wb.recalculate();
const oldShock=a.getRange('E15').values[0][0];val(a,'E15',null);wb.recalculate();assert(sum.getRange('E9').values[0][0]==='n.a.','Blank active shock must remain unavailable');val(a,'E15',0);wb.recalculate();assert(typeof sum.getRange('E9').values[0][0]==='number','Zero shock must be numeric');val(a,'E15',oldShock);wb.recalculate();
const oldPrefunding=a.getRange('E33').values[0][0];
for(const[label,value]of[['Blank selected prefunding',null],['Negative selected prefunding',-0.1],['Zero selected prefunding',0]]){
  val(a,'E33',value);wb.recalculate();
  const state={active_prefunding:a.getRange('E30').values[0][0],prefunding:e.getRange('F18').values[0][0],opening_cash:e.getRange('F27').values[0][0],free_cash:e.getRange('F56').values[0][0],nii:sum.getRange('E9').values[0][0]};
  if(value===0){assert(state.active_prefunding===0&&state.prefunding===0&&state.opening_cash===numberAt(e,'F12')&&typeof state.nii==='number','Zero prefunding must remain numeric');}
  else assert(Object.values(state).every(x=>x==='n.a.'),`${label} must propagate unavailable without formula errors`);
  const scan=assertNoFormulaErrors(label);
  val(a,'E33',oldPrefunding);wb.recalculate();assertDefaultRestored(label);
  inputValidityRegressions.push({test:label,input:'E33',value,observed:state,formula_error_scan:scan,default_restored_exactly:true});
}
val(a,'E6','missing');wb.recalculate();
const invalidSelectorState={active_prefunding:a.getRange('E30').values[0][0],prefunding:e.getRange('F18').values[0][0],opening_cash:e.getRange('F27').values[0][0],nii:sum.getRange('E9').values[0][0]};
assert(Object.values(invalidSelectorState).every(x=>x==='n.a.'),'Nonnumeric selector must propagate unavailable');
const invalidSelectorScan=assertNoFormulaErrors('Invalid case selector');
val(a,'E6',3);wb.recalculate();assertDefaultRestored('Invalid case selector');
inputValidityRegressions.push({test:'Invalid case selector',input:'E6',value:'missing',observed:invalidSelectorState,formula_error_scan:invalidSelectorScan,default_restored_exactly:true});
const oldHedge=a.getRange('E39').values[0][0];val(a,'E39',0);wb.recalculate();assert(Math.abs(numberAt(sum,'E15'))<1e-8,'Zero hedge must have zero collateral');assert(Math.abs(numberAt(sum,'E11'))<1e-8,'Zero hedge must have zero coupons');val(a,'E39',oldHedge);wb.recalculate();
assert(JSON.stringify(src.getRange('E10:E21').values)===publicBefore,'Public historical actuals changed');
assert(JSON.stringify(src.getRange('E75:E79').values)===costFactsBefore,'Reported cost context changed');
assert(Math.abs(numberAt(swap,'E13'))<1e-6,'Par inception value is not zero');
for(const row of swap.getRange('Z22:Z81').values)assert(Math.abs(row[0])<1e-6,'Swap conditional PV identity failed');
for(const row of e.getRange('G60:R60').values)for(const v of row)assert(Math.abs(v)<1e-6,'Cash rollforward identity failed');
assert(Math.abs(numberAt(sum,'E9')-initialNII)<1e-6&&Math.abs(numberAt(sum,'E15')-initialMargin)<1e-6&&Math.abs(numberAt(sum,'E16')-initialCash)<1e-6,'Final case does not match restored original');
const finalFormulaErrorScan=assertNoFormulaErrors('Restored final workbook');
await fs.writeFile(path.join(PREVIEW,'formula_errors.ndjson'),formulaErrors().map(x=>JSON.stringify(x)).join('\n'));
for(const [name,range]of [['Summary','C1:R41'],['Assumptions','C1:R34'],['Assumptions','C35:R84'],['Earnings','C1:R40'],['Earnings','C40:R79'],['Swap','C1:Z34'],['Swap','C70:Z81'],['Sources','C1:R45'],['Sources','C48:R83'],['Engine reference','C1:Q39'],['Engine reference','C42:Q62'],['Engine ledgers','C1:S21']]){
  const img=await wb.render({sheetName:name,range,scale:1.4,format:'png'});await fs.writeFile(path.join(PREVIEW,`${name.replaceAll(' ','_')}_${range.replaceAll(':','_')}.png`),new Uint8Array(await img.arrayBuffer()));
}
const metrics={case:a.getRange('E7').values[0][0],nii_usdm:numberAt(sum,'E9'),noncash_credit_loss_usdm:numberAt(sum,'E10'),operating_expense_usdm:numberAt(sum,'E20'),case_earnings_usdm:numberAt(sum,'E14'),peak_collateral_usdm:numberAt(sum,'E15'),minimum_cash_usdm:numberAt(sum,'E16'),funding_gap_usdm:numberAt(sum,'E17'),ending_net_loan_book_usdm:numberAt(e,'R69'),par_fixed_rate:numberAt(swap,'E7'),first_fixing:numberAt(swap,'E8'),opening_swap_value_usdm:numberAt(swap,'E10'),terminal_closeout_usdm:numberAt(swap,'E11'),engine_paths:paths.length,engine_events:events.length,analysis_sha256:analysisHash,built_at_utc:provenance.built_at_utc};
await fs.writeFile(path.join(PREVIEW,'validation.json'),JSON.stringify({passed:true,metrics,observations,input_validity_regressions:inputValidityRegressions,final_formula_error_scan:finalFormulaErrorScan,blank_and_zero_inputs_checked:true,source_actuals_unchanged:true},null,2));
await fs.writeFile(path.join(PREVIEW,'key_ranges.ndjson'),[wb.inspect({kind:'table',range:'Summary!C9:E19',include:'values,formulas',tableMaxRows:11,tableMaxCols:3,maxChars:10000}).ndjson,wb.inspect({kind:'table',range:'Swap!C22:Z23',include:'values,formulas',tableMaxRows:2,tableMaxCols:24,maxChars:12000}).ndjson].join('\n'));
// No edits after this final recalc; exported cells retain cached results.
wb.recalculate();const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(OUT);
// The exporter emits a very large internal cell inspection beside the XLSX.
// Compact key ranges, formula-error scan and validation evidence are retained.
await fs.rm(`${OUT}.inspect.ndjson`,{force:true});
console.log(JSON.stringify({output:OUT,preview:PREVIEW,metrics,tests:observations.length+7}));
