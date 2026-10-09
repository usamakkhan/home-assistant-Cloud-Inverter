const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const {number, seriesSegments, balanceParts, inverterLossEstimate, telemetryState, flowLayout, flowSvg, detailedFlowLayout, detailedFlowSvg, pageName, filterSensors, csvText, historyCsv} = require('../static/dashboard-ui.js');
const options = {format:(v,u)=>v===null?'—':`${v} ${u}`,icons:{bolt:'<path d="M1 1"/>'},animate:true};
const snapshot = (battery = 300) => ({ok:true,captured_at:'2026-09-02T12:00:00Z',sensors:{pv_power:{value:500},grid_power:{value:100},battery_power:{value:battery},backup_power:{value:900},gen_port_power:{value:0},load_power:{value:0}}});

test('missing, invalid and actual zero measurements remain distinct',()=>{
  for(const v of [null,undefined,'','   ',NaN,Infinity,true,false,[],[0],{}])assert.equal(number(v),null);
  assert.equal(number(0),0);
  assert.equal(number('0'),0);
});
test('chart segments preserve zero and break on missing readings and long gaps',()=>{
  const points=[{timestamp_ms:0,p:10},{timestamp_ms:60000,p:'20'},{timestamp_ms:120000,p:null},{timestamp_ms:180000,p:0},{timestamp_ms:600000,p:30}];
  assert.deepEqual(seriesSegments(points,'p').map(s=>s.map(p=>p.p)),[[10,'20'],[0],[30]]);
  assert.deepEqual(seriesSegments([{timestamp_ms:null,p:5},{timestamp_ms:0,p:0}],'p').map(s=>s.map(p=>p.p)),[[0]]);
  assert.equal(seriesSegments(points,'missing').length,0);
  assert.equal(seriesSegments([{timestamp_ms:0,p:1},{timestamp_ms:900000,p:2}],'p',2250000).length,1);
});
test('power balance preserves incomplete readings and uses correct battery/grid signs',()=>{
  assert(balanceParts({},'source').every(p=>p.value===null));
  const sample=snapshot(-300);sample.sensors.grid_power.value=-50;
  assert.deepEqual(balanceParts(sample,'source').map(p=>p.value),[500,0,0]);
  assert.deepEqual(balanceParts(sample,'destination').map(p=>p.value),[900,0,0,300,50]);
  delete sample.sensors.gen_port_power;
  assert.equal(balanceParts(sample,'destination')[1].value,null);
});
test('inverter overhead uses exact signed boundary balance and preserves a real zero',()=>{
  const sample=snapshot(-300);
  Object.assign(sample.sensors,{pv_power:{value:1000},grid_power:{value:-100},backup_power:{value:500},gen_port_power:{value:50},load_power:{value:0}});
  const result=inverterLossEstimate(sample);
  assert.equal(result.state,'estimated');assert.equal(result.value,50);assert.equal(result.residual,50);
  assert.equal(result.sourceTotal,1000);assert.equal(result.destinationTotal,950);
  assert.deepEqual(result.parts,{pv:1000,gridImport:0,gridExport:100,batteryDischarge:0,batteryCharge:300,backup:500,gen:50,normal:0});
  const exactZero=snapshot(0);
  Object.assign(exactZero.sensors,{pv_power:{value:0.3},grid_power:{value:0},backup_power:{value:0.1},gen_port_power:{value:0.2},load_power:{value:0}});
  const zero=inverterLossEstimate(exactZero);
  assert.equal(zero.value,0);assert.equal(zero.residual,0);assert(!Object.is(zero.value,-0));
});
test('inverter overhead never turns incomplete, partial or negative balance into loss',()=>{
  const mismatch=snapshot(300);
  Object.assign(mismatch.sensors,{pv_power:{value:500},grid_power:{value:0},backup_power:{value:850},gen_port_power:{value:20},load_power:{value:0}});
  const negative=inverterLossEstimate(mismatch);
  assert.equal(negative.state,'mismatch');assert.equal(negative.value,null);assert.equal(negative.residual,-70);
  const incomplete=structuredClone(mismatch);delete incomplete.sensors.gen_port_power;
  assert.equal(inverterLossEstimate(incomplete).state,'unavailable');assert.deepEqual(inverterLossEstimate(incomplete).missing,['gen_port_power']);
  assert.equal(inverterLossEstimate({...mismatch,ok:false}).reason,'partial_sample');
  const unsupported=structuredClone(mismatch);unsupported.sensors.gen_port_power={value:-25};
  assert.equal(inverterLossEstimate(unsupported).state,'unsupported');assert.deepEqual(inverterLossEstimate(unsupported).unsupported,['gen_port_power']);
});
test('Normal remains a grid-only boundary and lowers confidence when active',()=>{
  const sample=snapshot(-300);
  Object.assign(sample.sensors,{pv_power:{value:1200},grid_power:{value:-100},backup_power:{value:500},gen_port_power:{value:50},load_power:{value:100}});
  const result=inverterLossEstimate(sample);
  assert.equal(result.state,'estimated');assert.equal(result.value,150);assert.equal(result.normalBypass,100);assert.equal(result.confidence,'topology_unverified');
  assert.equal(detailedFlowLayout(sample).nodes.find(n=>n.key==='normal').side,'grid-only');
});
test('fresh, empty, paused, partial and stale samples are labelled honestly',()=>{
  const now=Date.parse('2026-09-02T12:00:30Z');
  assert.equal(telemetryState({},'original',now).kind,'empty');
  assert.equal(telemetryState(snapshot(),'cooperative',now).kind,'fresh');
  assert.equal(telemetryState(snapshot(),'original',now).animate,false);
  assert.equal(telemetryState({...snapshot(),ok:false},'maintenance',now).kind,'partial');
  assert.equal(telemetryState(snapshot(),'cooperative',now+400000).kind,'stale');
});
test('empty flow shows dashes, never fake zero readings or animated activity',()=>{
  const {svg}=flowSvg({},options);
  assert(!svg.includes('0 W'));
  assert(!svg.includes('NaN'));
  assert(svg.includes('—'));
  assert.equal((svg.match(/class="energy-link idle"/g)||[]).length,6);
});
test('discharge moves battery to source side and connects battery to inverter',()=>{
  const result=flowSvg(snapshot(),{...options,lastLayout:flowLayout(snapshot(-300)).positions});
  assert.equal(result.side,'source');
  assert(result.svg.includes('flow-relocating'));
  const battery=result.nodes.find(n=>n.key==='battery');
  assert.equal(battery.from[0],240);assert.equal(battery.to[0],370);
  assert(result.svg.includes('900 W'));
});
test('charging flows from inverter to destination battery',()=>{
  const result=flowSvg(snapshot(-300),{...options,lastLayout:flowLayout(snapshot()).positions});
  assert.equal(result.side,'destination');
  assert(result.svg.includes('flow-relocating'));
  const battery=result.nodes.find(n=>n.key==='battery');
  assert.equal(battery.from[0],570);assert.equal(battery.to[0],720);
  assert(result.svg.includes('Charging'));
});
test('unchanged battery state does not replay slide, paused data does not animate',()=>{
  const result=flowSvg(snapshot(),{...options,lastLayout:flowLayout(snapshot()).positions,animate:false});
  assert(!result.svg.includes('flow-relocating'));
  assert(!result.svg.includes('<animateMotion'));
  assert(!result.svg.includes('flow-halo active'));
  assert.equal((result.svg.match(/class="energy-link idle"/g)||[]).length,4);
});
test('grid export moves right alongside charging battery without overlapping loads',()=>{
  const sample=snapshot(-300);sample.sensors.grid_power.value=-123.456;
  sample.sensors.gen_port_power.value=500;sample.sensors.load_power.value=100;
  const result=flowSvg(sample,{...options,lastLayout:flowLayout(snapshot()).positions});
  const grid=result.nodes.find(n=>n.key==='grid');
  assert.equal(grid.side,'destination');assert.equal(grid.value,123.456);
  assert.equal(grid.from[0],570);assert.equal(grid.to[0],720);
  assert(result.svg.includes('Grid export'));assert(result.svg.includes('123.456 W'));
  assert(result.svg.includes('flow-relocating'));
  const destinations=result.nodes.filter(n=>n.side==='destination');
  assert.equal(destinations.length,5);
  destinations.forEach((n,i)=>{assert(n.y-29>25&&n.y+29<420);if(i)assert(n.y-destinations[i-1].y>=58);});
  const unchanged=flowSvg(sample,{...options,lastLayout:result.positions});
  assert(!unchanged.svg.includes('flow-relocating'));
  assert(unchanged.svg.includes('<animateMotion'));
});
test('only exact zeros disappear; unknown and fractional readings remain',()=>{
  const sample=snapshot(0);sample.sensors.grid_power.value=-0;sample.sensors.pv_power.value=0.001;
  const result=flowSvg(sample,{...options,format:()=> '0 W'});
  assert.deepEqual(result.inactive.map(n=>n.key),['grid','battery','gen','normal']);
  assert(result.nodes.some(n=>n.key==='solar'));
  assert(!result.svg.includes('data-flow="grid"'));
  assert(!result.svg.includes('data-link="grid"'));
  assert(result.svg.includes('<animateMotion'));
  sample.sensors.grid_power.value=null;
  const unknown=flowSvg(sample,options);
  assert(unknown.nodes.some(n=>n.key==='grid'&&n.value===null));
  assert(unknown.svg.includes('direction not confirmed'));
});
test('all-zero sample has no active diagram paths and keeps six inactive readings',()=>{
  const sample=snapshot();Object.values(sample.sensors).forEach(s=>s.value=0);
  const result=flowSvg(sample,options);
  assert.equal(result.nodes.length,0);assert.equal(result.inactive.length,6);
  assert(!result.svg.includes('data-link='));assert(!result.svg.includes('<animateMotion'));
  assert(result.svg.includes('No active sources'));assert(result.svg.includes('No active destinations'));
});
test('formatted values are escaped before entering SVG markup',()=>{
  const result=flowSvg(snapshot(),{...options,format:()=>'<bad>'});
  assert(!result.svg.includes('<bad>'));
  assert(result.svg.includes('&lt;bad&gt;'));
});
test('telemetry search and filters preserve unknowns, exact zero and negative power',()=>{
  const sensors=[{key:'grid_power',name:'Grid',category:'AC',address_hex:'0x1234',value:-25.125},{key:'battery',name:'Battery',category:'DC',value:0},{key:'pv',name:'Solar',category:'DC',value:null}];
  assert.equal(filterSensors(sensors,'1234')[0].key,'grid_power');
  assert.deepEqual(filterSensors(sensors,'','all','nonzero').map(s=>s.key),['grid_power','pv']);
  assert.deepEqual(filterSensors(sensors,'','DC','unknown').map(s=>s.key),['pv']);
  assert.equal(filterSensors(sensors,'battery','AC').length,0);
});
test('page URLs resolve explicit pages, legacy bookmarks and invalid routes safely',()=>{
  const pages=['overview','powerflow','analytics','controls'];
  assert.equal(pageName('?page=powerflow','',pages),'powerflow');
  assert.equal(pageName('?page=powerflow','#analytics',pages),'analytics');
  assert.equal(pageName('?page=constructor','',pages),'overview');
  assert.equal(pageName('?page=%3Cscript%3E','#missing',pages),'overview');
});
test('detailed flow splits MPPT readings without substituting missing strings or duplicating solar total',()=>{
  const sample=snapshot();sample.sensors.pv1_power={value:320.125};sample.sensors.pv1_voltage={value:245.7};sample.sensors.pv1_current={value:1.31};
  const result=detailedFlowSvg(sample,options);
  assert(result.nodes.some(n=>n.key==='pv1'&&n.value===320.125));
  assert(result.nodes.some(n=>n.key==='pv2'&&n.value===null));
  assert(!result.nodes.some(n=>n.key==='solar'));
  assert(result.svg.includes('245.7 V'));assert(result.svg.includes('1.31 A'));
  assert(result.svg.includes('SOURCE SUM · CALCULATED'));
  assert(result.svg.includes('EST. LOSS + SELF-USE'));assert.equal(result.lossEstimate.value,0);
});
test('detailed flow labels a negative balance as mismatch without inventing a loss path',()=>{
  const sample=snapshot(300);
  Object.assign(sample.sensors,{pv_power:{value:500},grid_power:{value:0},backup_power:{value:850},gen_port_power:{value:20},load_power:{value:0}});
  const result=detailedFlowSvg(sample,options);
  assert.equal(result.lossEstimate.state,'mismatch');assert.equal(result.lossEstimate.value,null);assert.equal(result.lossEstimate.residual,-70);
  assert(result.svg.includes('SIGNED BALANCE MISMATCH'));assert(result.svg.includes('-70 W'));
  assert(!result.svg.includes('data-link="loss"'));assert(!result.svg.includes('detailArrow-loss'));
  const unavailable=detailedFlowSvg({},options);
  assert(unavailable.svg.includes('LOSS ESTIMATE UNAVAILABLE'));assert(unavailable.svg.includes('>—</text>'));
});
test('detailed flow handles all grid/battery signs and isolates grid-only Normal load',()=>{
  for(const grid of [-200,200])for(const battery of [-300,300]){
    const sample=snapshot(battery);sample.sensors.grid_power.value=grid;sample.sensors.load_power.value=50;
    const result=detailedFlowLayout(sample),g=result.nodes.find(n=>n.key==='grid'),b=result.nodes.find(n=>n.key==='battery'),normal=result.nodes.find(n=>n.key==='normal');
    assert.equal(g.side,grid<0?'destination':'source');assert.equal(b.side,battery>0?'source':'destination');
    assert.equal(g.value,200);assert.equal(b.value,300);
    assert.equal(normal.side,'grid-only');assert.deepEqual(normal.from,[460,636]);assert.deepEqual(normal.to,[900,636]);
    assert(![480,720].includes(normal.from[0]));
  }
});
test('detailed flow keeps zero SOC, signed currents and finite nonoverlapping readouts',()=>{
  const sample=snapshot(-300);sample.sensors.grid_power.value=-200;sample.sensors.gen_port_power.value=20;sample.sensors.load_power.value=0.001;
  Object.assign(sample.sensors,{pv1_power:{value:100},pv2_power:{value:400},battery_soc:{value:0},battery_current:{value:-5.123456789},battery_voltage:{value:50.1}});
  const result=detailedFlowSvg(sample,options);
  assert(result.svg.includes('0 %'));assert(result.svg.includes('-5.123456789 A'));
  assert(!result.svg.includes('NaN'));assert(!result.svg.includes('Infinity'));
  for(const n of result.nodes){assert(n.x>=0&&n.x+276<=1200);assert(n.y-56>=26&&n.y+56<=720);assert(n.from.every(Number.isFinite));assert(n.to.every(Number.isFinite));}
  for(const side of ['source','destination']){const column=result.nodes.filter(n=>n.side===side);column.slice(1).forEach((n,i)=>assert(n.y-column[i].y>=112));}
  assert(result.nodes.some(n=>n.key==='normal'&&n.value===0.001));
});
test('detailed flow does not animate missing or stale readings and escapes formatted text',()=>{
  const empty=detailedFlowSvg({},options);assert(!empty.svg.includes('<animateMotion'));assert(!empty.svg.includes('0 W'));
  const paused=detailedFlowSvg(snapshot(),{...options,animate:false});assert(!paused.svg.includes('<animateMotion'));assert(!paused.svg.includes('circuit-running'));assert(!paused.svg.includes('detail-wave active'));
  const escaped=detailedFlowSvg(snapshot(),{...options,format:()=>'<bad>'});assert(!escaped.svg.includes('<bad>'));assert(escaped.svg.includes('&lt;bad&gt;'));
});
test('orbital animation and readout effects stop with static samples',()=>{
  const moving=detailedFlowSvg(snapshot(),options).svg;
  assert(moving.includes('core-orbit outer active'));assert(moving.includes('core-orbit inner active'));
  assert(moving.includes('detail-node-power updated'));
  const staticSvg=detailedFlowSvg(snapshot(),{...options,animate:false}).svg;
  assert(!staticSvg.includes('core-orbit outer active'));assert(!staticSvg.includes('core-orbit inner active'));
  assert(!staticSvg.includes('detail-node-power updated'));assert(!staticSvg.includes('<animateMotion'));
  const css=fs.readFileSync(require.resolve('../static/portal.css'),'utf8');
  assert(css.includes('[hidden] { display:none!important; }'));
  assert(css.includes('@media(prefers-reduced-motion:reduce)'));
  assert(css.includes('*,*::before,*::after { animation:none!important; transition:none!important;'));
  assert(css.includes('.detail-packet,.energy-packet { display:none!important; }'));
});
test('neon measurement colors retain readable contrast against the dark node surface',()=>{
  const luminance=hex=>{const rgb=hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:Math.pow((x+.055)/1.055,2.4));return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
  const sample=snapshot();sample.sensors.gen_port_power.value=100;sample.sensors.load_power.value=20;
  for(const node of detailedFlowLayout(sample).nodes){const ratio=(luminance(node.color)+.05)/(luminance('#101e32')+.05);assert(ratio>=4.5,`${node.key}: contrast ${ratio}`);}
});
test('CSV preserves precision and blank unknowns while escaping spreadsheet formulas',()=>{
  assert.equal(csvText([['A,"B"',0,null,-1.23456789,'=SUM(A1)',' @formula']]),'"A,""B""","0","","-1.23456789","\'=SUM(A1)","\' @formula"');
  const result=historyCsv([{timestamp_ms:0,p:200},{captured_at:'2026-09-05T01:02:03Z',timestamp_ms:1000,p:-12.3456789,q:null},{timestamp_ms:2000,p:0,q:1}],{p:{label:'Power',unit:'W'},q:{label:'SOC',unit:'%'}},['p'],500);
  assert(!result.includes('SOC'));assert(!result.includes('200"'));assert(result.includes('2026-09-05T01:02:03Z'));assert(result.includes('"-12.3456789"'));assert(result.includes('"0"'));
});
test('active markup has unique IDs and a sidebar destination for every workspace',()=>{
  const html=fs.readFileSync(require.resolve('../static/index.html'),'utf8').replace(/<template\b[\s\S]*?<\/template>/gi,'').replace(/<script\b[\s\S]*?<\/script>/gi,'');
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(ids.length,new Set(ids).size,'duplicate active element ID');
  const sidebar=html.match(/<aside id="sidebar"[\s\S]*?<\/aside>/)[0];
  const destinations=new Set([...sidebar.matchAll(/data-view="([^"]+)"/g)].map(m=>m[1]));
  for(const id of ids.filter(id=>id.startsWith('view-')))assert(destinations.has(id.slice(5)),`no sidebar destination for ${id}`);
  assert(!sidebar.includes('<button'));
  for(const name of destinations)assert(sidebar.includes(`href="/?page=${name}"`));
  const overview=html.match(/<section id="view-overview"[\s\S]*?<section id="view-powerflow"/)[0];
  assert(!overview.includes('id="energyFlowMap"'));assert(overview.includes('href="/?page=powerflow"'));
  assert(html.includes('id="collectionDrawer"'));assert(html.includes('id="collectionControlsMount"'));
  assert(html.includes('id="collectorInterval" type="number" min="10" max="900" value="180"'));
  assert(html.includes('id="controlSessionBtn"'));
});
test('dashboard boots without data, sends only cache GETs, and preserves unsaved settings',async()=>{
  const html=fs.readFileSync(require.resolve('../static/index.html'),'utf8');
  const elements=new Map();
  for(const match of html.matchAll(/\bid="([^"]+)"/g)) {
    elements.set(match[1],{value:'60',innerHTML:'',textContent:'',style:{},dataset:{},listeners:{},attributes:{},offsetWidth:240,offsetHeight:180,focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {left:0,top:0,width:900,height:300};},classList:{toggle(){},remove(){},contains(){return false;}},setAttribute(key,value){this.attributes[key]=value;},removeAttribute(){},querySelectorAll(){return[];},add(){},addEventListener(name,fn){this.listeners[name]=fn;}});
  }
  const state={mode:'original',host:'192.168.50.10',unit_id:1,interval_seconds:60,quiet_window_seconds:45,capture_count:0,quiet_skips:0,consecutive_failures:0};
  const calls=[];
  const windowEvents={},bodyClasses=new Set();
  const context=vm.createContext({DashboardUI:require('../static/dashboard-ui.js'),document:{getElementById:id=>{assert(elements.has(id),`missing element ${id}`);return elements.get(id);},querySelector:()=>null,querySelectorAll:()=>[],body:{insertAdjacentHTML(){},classList:{toggle(key,on){on?bodyClasses.add(key):bodyClasses.delete(key);}}}},window:{addEventListener(name,handler){windowEvents[name]=handler;},scrollTo(){}},location:{hash:'#overview'},history:{replaceState(){}},Option:function(){},setInterval:()=>1,clearInterval(){},setTimeout(){},requestAnimationFrame(){},navigator:{},fetch:async(url,opts)=>{
    calls.push([url,opts?.method||'GET']);
    const payload=url==='/api/config'?{presets:{},cloud_field_schema:[]}:url.startsWith('/api/history')?{points:[],series:{}}:url.startsWith('/api/activity')?{events:[]}:url==='/api/collector'?state:{error:'No local sample'};
    return {ok:url!=='/api/latest'&&url!=='/api/ha',json:async()=>payload};
  }});
  let script=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(m=>m[1]).join('\n');
  script=script.replace(/^configure\(\)\.catch.*$/m,'');
  vm.runInContext(script,context);
  elements.get('telemetrySearch').value='';elements.get('telemetryFilter').value='all';elements.get('telemetryCategory').value='all';
  await vm.runInContext('configure()',context);
  assert(calls.every(([,method])=>method==='GET'));
  assert.equal(elements.get('liveBtn').disabled,true);
  assert.equal(elements.get('telemetryBadge').textContent,'No local sample');
  assert.equal((elements.get('flowCards').innerHTML.match(/<article/g)||[]).length,6);
  const mode=elements.get('collectorMode');
  mode.value='maintenance';mode.listeners.input();
  vm.runInContext(`renderCollectorStatus(${JSON.stringify(state)})`,context);
  assert.equal(mode.value,'maintenance');
  assert.equal(elements.get('collectorFormNote').hidden,false);
  mode.value='local';mode.listeners.input();
  vm.runInContext(`renderCollectorStatus(${JSON.stringify(state)})`,context);
  assert.equal(mode.value,'local');
  assert.equal(elements.get('collectorQuiet').disabled,true);
  assert.equal(elements.get('collectorInterval').disabled,false);
  vm.runInContext(`renderCollectorStatus({...${JSON.stringify(state)},mode:'local',next_capture_seconds:60},true)`,context);
  assert.equal(elements.get('collectorModeBadge').textContent,'Local');
  assert.equal(elements.get('liveBtn').disabled,false);
  assert.equal(elements.get('controlReadBtn').disabled,false);
  assert(elements.get('collectorStatus').textContent.includes('targets a new saved sample'));
  assert(elements.get('portalSummary').innerHTML.includes('—'));
  assert(!elements.get('portalSummary').innerHTML.includes('0 kWh'));
  vm.runInContext(`renderPortalTelemetry({sensors:{grid_l2_power:{value:12,name:'Unexpected L2',unit:'W'},grid_l3_power:{value:0,name:'Unused L3',unit:'W'}}})`,context);
  assert(elements.get('portalInformation').innerHTML.includes('Unexpected L2'));
  assert(!elements.get('portalInformation').innerHTML.includes('Unused L3'));
  vm.runInContext(`controlFields=[{key:'capacity_mode',name:'Capacity Mode',group:'Remote settings',address_hex:'0x2124',evidence:'Portal',options:{0:'SOC',1:'Voltage'},write_implemented:false}];controlEnabled=true;renderControlFields()`,context);
  assert(elements.get('controlFields').innerHTML.includes('<output'));
  assert(!elements.get('controlFields').innerHTML.includes('data-control="capacity_mode"'));
  vm.runInContext('renderBalance({})',context);
  assert(elements.get('sourceBalance').innerHTML.includes('Incomplete readings'));
  assert(!elements.get('sourceBalance').innerHTML.includes('0 W'));
  assert.equal(elements.get('sourceDonut').style.background,'#e3ebf1');
  vm.runInContext(`renderBalance(${JSON.stringify(snapshot())})`,context);
  assert(elements.get('sourceDonut').style.background.startsWith('conic-gradient'));
  assert(elements.get('destinationBalance').innerHTML.includes('0 W'));

  // Populated chart is tested in the JS VM, without contacting a device/browser.
  const now=Date.now();
  vm.runInContext(`liveHistory=${JSON.stringify([10,20,null,0].map((pv,i)=>({timestamp_ms:now-180000+i*60000,pv_power:pv})))};chartSeriesMeta={pv_power:{label:'Solar',unit:'W',color:'#abc'}};renderHistory()`,context);
  const chart=elements.get('historyChart');
  assert.equal((chart.innerHTML.match(/class="chart-line"/g)||[]).length,1);
  assert.equal((chart.innerHTML.match(/class="chart-last"/g)||[]).length,2);
  assert.equal(chart.attributes.tabindex,'0');
  chart.onfocus();assert(elements.get('chartTooltip').textContent.includes('Solar: 0 W'));
  chart.onkeydown({key:'ArrowLeft',preventDefault(){}});
  assert(elements.get('chartFloat').innerHTML.includes('Not measured'));
  assert.equal(elements.get('chartHoverDots').innerHTML,'');
  chart.onkeydown({key:'Home',preventDefault(){}});
  assert(elements.get('chartTooltip').textContent.includes('Solar: 10 W'));
  chart.onkeydown({key:'Escape',preventDefault(){}});
  assert.equal(elements.get('chartFloat').hidden,true);
  elements.get('chartHover').onpointerdown({clientX:845,clientY:100});
  assert(elements.get('chartTooltip').textContent.includes('Solar: 0 W'));
  assert(!chart.innerHTML.includes('NaN'));

  let resolveFetch,refreshCalls=0;
  context.fetch=()=>{refreshCalls++;return new Promise(resolve=>{resolveFetch=resolve;});};
  const pending=vm.runInContext('refreshCachedLive()',context);
  await vm.runInContext('refreshCachedLive()',context);
  assert.equal(refreshCalls,1,'concurrent refresh is skipped');
  resolveFetch({ok:false,json:async()=>({error:'Offline'})});await pending;
  assert.equal(vm.runInContext('cacheRefreshBusy',context),false);
  vm.runInContext(`latestLive={snapshot:${JSON.stringify({...snapshot(),captured_at:new Date().toISOString()})}}`,context);
  context.fetch=async()=>{throw new Error('Offline');};
  await vm.runInContext('refreshCachedLive()',context);
  assert(elements.get('sampleHealth').textContent.includes('Cache refresh failed'));
  assert.equal((elements.get('energyFlowMap').innerHTML.match(/class="detail-link idle"/g)||[]).length,4);
  assert(elements.get('flowInactive').innerHTML.includes('GEN'));

  // Slower previous range responses must not overwrite the current selection.
  const replies=[];
  context.fetch=()=>new Promise(resolve=>replies.push(resolve));
  const older=vm.runInContext('loadHistory()',context),newer=vm.runInContext('loadHistory()',context);
  replies[1]({ok:true,json:async()=>({points:[],series:{newest:{label:'Newest'}}})});await newer;
  replies[0]({ok:true,json:async()=>({points:[],series:{older:{label:'Older'}}})});await older;
  assert.equal(vm.runInContext('Object.keys(chartSeriesMeta)[0]',context),'newest');

  const telemetry={sensors:{soc:{name:'Battery SOC',key:'soc',category:'Battery',value:84.735,unit:'%'},missing:{name:'Unknown',category:'Battery',value:null,unit:'V'},zero:{name:'Idle power',category:'AC',value:0,unit:'W'}}};
  const group={isConnected:true,open:false,dataset:{category:'Battery'}};
  elements.get('liveDataset').querySelectorAll=()=>[group];
  vm.runInContext(`renderVisibleDataset(${JSON.stringify(telemetry)})`,context);
  group.ontoggle();
  vm.runInContext(`renderVisibleDataset(${JSON.stringify(telemetry)})`,context);
  assert(elements.get('liveDataset').innerHTML.includes('data-category="Battery" >'));
  assert(elements.get('liveDataset').innerHTML.includes('84.735'));
  elements.get('telemetrySearch').value='unknown';
  vm.runInContext(`renderVisibleDataset(${JSON.stringify(telemetry)})`,context);
  assert.equal(elements.get('telemetryCount').textContent,'1 of 3 applicable measurements');
  assert(!elements.get('liveDataset').innerHTML.includes('84.735'));
  elements.get('telemetrySearch').value='';
  vm.runInContext('renderZeroReference({})',context);
  assert(elements.get('zeroReference').innerHTML.includes('unavailable'));
  assert(!elements.get('zeroReference').innerHTML.includes('class="ok"'));

  const current={...snapshot(),captured_at:new Date().toISOString()};
  vm.runInContext(`cacheRefreshFailed=false;latestLive={snapshot:${JSON.stringify(current)}};renderEnergyFlow(latestLive.snapshot)`,context);
  assert(elements.get('energyFlowMap').innerHTML.includes('<animateMotion'));
  assert(elements.get('energyFlowMap').innerHTML.includes('EST. LOSS + SELF-USE'));
  assert(elements.get('flowTelemetryStrip').innerHTML.includes('Est. inverter overhead'));
  assert(elements.get('flowTelemetryStrip').innerHTML.includes('0 W'));
  assert(elements.get('flowDetailCards').innerHTML.includes('Signed balance residual'));
  assert(elements.get('flowReadingTable').innerHTML.includes('Inverter conversion + self-use'));
  elements.get('flowMotionBtn').onclick();
  assert(!elements.get('energyFlowMap').innerHTML.includes('<animateMotion'));
  assert.equal(elements.get('flowMotionBtn').attributes['aria-pressed'],'false');
  elements.get('flowTableBtn').onclick();
  assert.equal(elements.get('flowDiagram').hidden,true);
  assert.equal(elements.get('flowReadingTable').hidden,false);
  assert(elements.get('flowReadingTable').innerHTML.includes('300 W'));
  elements.get('flowTableBtn').onclick();
  assert.equal(elements.get('flowDiagram').hidden,false);

  // A failed history cache must not disable all other panels or startup timers.
  const bootCalls=[];
  context.fetch=async url=>{bootCalls.push(url);if(url.startsWith('/api/history'))throw new Error('History unavailable');return {ok:url!=='/api/latest'&&url!=='/api/ha',json:async()=>url==='/api/config'?{presets:{}}:url==='/api/collector'?state:{events:[],error:'No sample'}};};
  await vm.runInContext('configure()',context);
  assert(bootCalls.includes('/api/collector'));assert(bootCalls.includes('/api/latest'));

  // In-progress diagnostic stays locked through a status poll and mode change.
  vm.runInContext(`renderCollectorStatus({...${JSON.stringify(state)},mode:'maintenance'},true)`,context);
  let finishRead,readCalls=0;
  context.fetch=()=>{readCalls++;return new Promise(resolve=>finishRead=resolve);};
  const readPending=elements.get('controlReadBtn').onclick();
  await elements.get('controlReadBtn').onclick();
  assert.equal(readCalls,1);
  vm.runInContext(`renderCollectorStatus({...${JSON.stringify(state)},mode:'maintenance'},true)`,context);
  assert.equal(elements.get('controlReadBtn').disabled,true);
  vm.runInContext(`renderCollectorStatus(${JSON.stringify(state)},true)`,context);
  finishRead({ok:false,json:async()=>({error:'Mock read failure'})});await readPending;
  assert.equal(elements.get('controlReadBtn').disabled,true);

  // One acknowledged editing session replaces separate startup and mode locks.
  vm.runInContext('controlEnabled=false;controlSessionActive=false;controlDraft={};controlPending=null;renderControlFields()',context);
  elements.get('controlSessionConfirm').checked=true;
  const sessionCalls=[];
  context.fetch=async(url,opts)=>{
    const body=JSON.parse(opts.body);sessionCalls.push([url,body]);
    const starting=body.action==='start';
    return {ok:true,json:async()=>starting
      ?{enabled:true,session_active:true,resume_mode:'local',collector:{...state,mode:'maintenance',manual_device_tools:true,background_polling:false}}
      :{enabled:false,session_active:false,resume_mode:null,collector:{...state,mode:'local',manual_device_tools:false,background_polling:true,next_capture_seconds:10}}};
  };
  await elements.get('controlSessionBtn').onclick();
  assert.equal(sessionCalls[0][0],'/api/controls/session');
  assert.equal(sessionCalls[0][1].confirmation,'ENABLE ABCDE123456789');
  assert.equal(elements.get('controlSessionTitle').textContent,'Editing enabled');
  assert.equal(elements.get('collectorModeBadge').textContent,'Maintenance');
  await elements.get('controlSessionBtn').onclick();
  assert.equal(elements.get('controlSessionTitle').textContent,'Viewing only');
  assert.equal(elements.get('collectorModeBadge').textContent,'Local');

  // New visual controls never contact the device or the backend.
  context.fetch=()=>{throw new Error('Unexpected network request from visual control');};
  elements.get('focusModeBtn').onclick();assert(bodyClasses.has('focus-mode'));
  assert.equal(elements.get('focusModeBtn').attributes['aria-pressed'],'true');
  elements.get('quickNavSearch').value='battery';elements.get('quickNavBtn').onclick();
  assert.equal(elements.get('quickNav').open,true);assert(elements.get('quickNavResults').innerHTML.includes('/?page=powerflow'));
  windowEvents.keydown({key:'Escape',target:{tagName:'BUTTON'}});assert(bodyClasses.has('focus-mode'),'dialog Escape should not also exit focus mode');
  elements.get('quickNavCloseBtn').onclick();
  windowEvents.keydown({key:'Escape',target:{tagName:'BUTTON'}});assert(!bodyClasses.has('focus-mode'));
  windowEvents.keydown({key:'k',ctrlKey:true,target:{tagName:'INPUT'}});assert.equal(elements.get('quickNav').open,false);
  windowEvents.keydown({key:'k',ctrlKey:true,repeat:true,target:{tagName:'BODY'}});assert.equal(elements.get('quickNav').open,false);
  windowEvents.keydown({key:'k',ctrlKey:true,target:{tagName:'BODY'},preventDefault(){}});assert.equal(elements.get('quickNav').open,true);
  elements.get('quickNavSearch').value='<not a page>';elements.get('quickNavSearch').oninput();assert(elements.get('quickNavResults').innerHTML.includes('No matching page'));
  elements.get('quickNavCloseBtn').onclick();
  elements.get('traceBatteryBtn').onclick();assert.equal(elements.get('energyFlowMap').attributes['data-trace'],'battery');
  assert.equal(elements.get('traceBatteryBtn').attributes['aria-pressed'],'true');
  vm.runInContext(`renderEnergyFlow(${JSON.stringify(snapshot(-300))})`,context);assert.equal(elements.get('energyFlowMap').attributes['data-trace'],'battery');
  vm.runInContext(`renderEnergyFlow(${JSON.stringify(snapshot(0))})`,context);assert(elements.get('traceStatus').textContent.includes('idle in displayed sample'));
  vm.runInContext('downloadJson=(value)=>{globalThis.exportedSnapshot=value;}',context);elements.get('exportCachedBtn').onclick();
  assert.equal(vm.runInContext('exportedSnapshot.sensors.battery_power.value',context),300);
  assert(elements.get('flowTelemetryStrip').innerHTML.includes('hud-metric'));
});
