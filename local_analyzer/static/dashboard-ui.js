/* Presentation-only helpers: no network calls or device controls. */
(function (root) {
  'use strict';
  const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function number(value) {
    if (!['number','string'].includes(typeof value) || (typeof value === 'string' && !value.trim())) return null;
    return Number.isFinite(Number(value)) ? Number(value) : null;
  }
  // A missing sample or long acquisition gap must break the line, not imply zero
  // output or continuous measurements during an outage.
  function seriesSegments(points, key, maxGapMs = 180000) {
    const segments = [];
    let current = [], previous = null;
    for (const point of points) {
      const time = number(point.timestamp_ms), value = number(point[key]);
      if (time === null || value === null || (previous !== null && (time <= previous || time - previous > maxGapMs))) {
        if (current.length) segments.push(current);
        current = [];
      }
      if (time !== null && value !== null) current.push(point);
      previous = time;
    }
    if (current.length) segments.push(current);
    return segments;
  }
  function balanceParts(snapshot, mode) {
    const positive = (key, sign = 1) => {
      const value = number(snapshot?.sensors?.[key]?.value);
      return value === null ? null : Math.max(sign * value, 0);
    };
    const fields = mode === 'source'
      ? [['Solar','pv_power',1,'#59e39f'],['Grid import','grid_power',1,'#71b7ff'],['Battery discharge','battery_power',1,'#d698ff']]
      : [['Backup','backup_power',1,'#ffcc66'],['GEN load','gen_port_power',1,'#ff8a65'],['Normal','load_power',1,'#9aa9a3'],['Battery charge','battery_power',-1,'#d698ff'],['Grid feed-in','grid_power',-1,'#71b7ff']];
    return fields.map(([label,key,sign,color])=>({label,value:positive(key,sign),color}));
  }
  // Register values arrive as decimal power readings. Summing at their displayed
  // precision avoids exposing binary floating-point noise as fake extra digits.
  function precisePowerSum(values) {
    const decimalPlaces=value=>{
      const text=String(value).toLowerCase(),parts=text.split('e');
      const fraction=(parts[0].split('.')[1]||'').length,exponent=Number(parts[1]||0);
      return Math.max(0,fraction-exponent);
    };
    const places=Math.min(9,Math.max(0,...values.map(decimalPlaces))),scale=10**places;
    if(values.every(value=>Number.isSafeInteger(Math.round(value*scale)))) {
      const result=values.reduce((sum,value)=>sum+Math.round(value*scale),0)/scale;
      return Object.is(result,-0)?0:result;
    }
    const result=values.reduce((sum,value)=>sum+value,0);
    return Object.is(result,-0)?0:result;
  }
  function inverterLossEstimate(snapshot) {
    const formula='PV + signed Grid + signed Battery - Backup - GEN - Normal';
    const keys=['pv_power','grid_power','battery_power','backup_power','gen_port_power','load_power'];
    const values=Object.fromEntries(keys.map(key=>[key,number(snapshot?.sensors?.[key]?.value)]));
    const missing=keys.filter(key=>values[key]===null);
    const base={formula,missing,unsupported:[],value:null,residual:null,sourceTotal:null,destinationTotal:null,
      normalBypass:values.load_power,confidence:'unavailable',parts:null};
    if(snapshot?.ok!==true||missing.length) return {...base,state:'unavailable',reason:snapshot?.ok===false?'partial_sample':'missing_measurements'};
    const unsupported=['pv_power','backup_power','gen_port_power','load_power'].filter(key=>values[key]<0);
    if(unsupported.length) return {...base,state:'unsupported',reason:'unexpected_direction',unsupported};
    const parts={pv:values.pv_power,gridImport:Math.max(values.grid_power,0),gridExport:Math.max(-values.grid_power,0),
      batteryDischarge:Math.max(values.battery_power,0),batteryCharge:Math.max(-values.battery_power,0),
      backup:values.backup_power,gen:values.gen_port_power,normal:values.load_power};
    const sourceTotal=precisePowerSum([parts.pv,parts.gridImport,parts.batteryDischarge]);
    const destinationTotal=precisePowerSum([parts.backup,parts.gen,parts.normal,parts.gridExport,parts.batteryCharge]);
    const residual=precisePowerSum([values.pv_power,values.grid_power,values.battery_power,-values.backup_power,-values.gen_port_power,-values.load_power]);
    const confidence=values.load_power>0?'topology_unverified':'sequential_sample';
    return residual<0
      ? {...base,state:'mismatch',reason:'negative_residual',residual,sourceTotal,destinationTotal,confidence,parts}
      : {...base,state:'estimated',reason:'balance_residual',value:residual,residual,sourceTotal,destinationTotal,confidence,parts};
  }
  function telemetryState(snapshot, mode, now = Date.now()) {
    const captured = Date.parse(snapshot?.captured_at);
    if (!snapshot || !Number.isFinite(captured)) return {kind:'empty', label:'No local sample', animate:false, age:null};
    const age = Math.max(0, Math.floor((now-captured)/1000));
    if (mode === 'original') return {kind:'paused', label:'Collection paused · cached data', animate:false, age};
    if (age > 360) return {kind:'stale', label:'Stale local sample', animate:false, age};
    if (!snapshot.ok) return {kind:'partial', label:'Partial local sample', animate:false, age};
    return {kind:'fresh', label:'Fresh local sample', animate:true, age};
  }
  function filterSensors(sensors, query = '', category = 'all', mode = 'all') {
    const search=query.trim().toLowerCase();
    return sensors.filter(s=>{
      const value=number(s.value);
      return (!search||[s.key,s.name,s.category,s.address_hex,s.unit].some(v=>String(v??'').toLowerCase().includes(search)))
        &&(category==='all'||s.category===category)
        &&(mode!=='nonzero'||value!==0)&&(mode!=='unknown'||value===null);
    });
  }
  function pageName(search, hash, allowed) {
    const legacy=String(hash||'').replace(/^#/,'');
    const requested=new URLSearchParams(search||'').get('page');
    return allowed.includes(legacy)?legacy:allowed.includes(requested)?requested:'overview';
  }
  function csvText(rows) {
    // Spreadsheet formulas are never executed when names/metadata are exported.
    const cell=value=>{
      let text=value==null?'':String(value);
      if(typeof value==='string'&&/^[\s]*[=+\-@]/.test(text))text="'"+text;
      return '"'+text.replace(/"/g,'""')+'"';
    };
    return rows.map(row=>row.map(cell).join(',')).join('\r\n');
  }
  function historyCsv(points, series, keys, cutoff = 0) {
    const columns=keys.filter(k=>series[k]);
    return csvText([['Captured at','Timestamp (ms)',...columns.map(k=>`${series[k].label} (${series[k].unit})`)],
      ...points.filter(p=>number(p.timestamp_ms)!==null&&p.timestamp_ms>=cutoff).sort((a,b)=>a.timestamp_ms-b.timestamp_ms)
        .map(p=>[p.captured_at??new Date(p.timestamp_ms).toISOString(),p.timestamp_ms,...columns.map(k=>number(p[k]))])]);
  }
  function flowLayout(snapshot) {
    const val = key => number(snapshot?.sensors?.[key]?.value);
    const grid = val('grid_power'), battery = val('battery_power');
    const fields = [
      ['solar','Solar','pv_power','source','solar','#bb7907'],
      ['grid',grid===null?'Grid · unknown':grid<0?'Grid export':'Grid import','grid_power',grid<0?'destination':'source','grid','#1688d0'],
      ['battery',battery===null?'Battery · unknown':battery>0?'Discharging':'Charging','battery_power',battery>0?'source':'destination','battery','#8951ce'],
      ['backup','Backup load','backup_power','destination','home','#18856a'],
      ['gen','GEN load','gen_port_power','destination','bolt','#c56631'],
      ['normal','Normal load','load_power','destination','plug','#627991'],
    ];
    const inactive = [], nodes = [], positions = {};
    for (const [key,label,sensor,side,icon,color] of fields) {
      const raw = val(sensor);
      // Visibility uses the raw value, never rounded display text or a deadband.
      if (raw === 0) { inactive.push({key,label:key==='grid'?'Grid':key==='battery'?'Battery':label}); continue; }
      nodes.push({key,label,side,icon,color,value:raw===null?null:['grid','battery'].includes(key)?Math.abs(raw):raw});
    }
    for (const side of ['source','destination']) {
      const column = nodes.filter(node=>node.side===side);
      column.forEach((node,i)=>{
        node.x=side==='source'?20:720;
        node.y=210+(i-(column.length-1)/2)*72;
        positions[node.key]={x:node.x,y:node.y,side};
        const portY=210+(i-(column.length-1)/2)*18;
        node.from=side==='source'?[240,node.y]:[570,portY];
        node.to=side==='source'?[370,portY]:[720,node.y];
      });
    }
    return {nodes,inactive,positions};
  }
  function flowSvg(snapshot, options) {
    const {format, icons, lastLayout = {}, animate = false} = options;
    const layout=flowLayout(snapshot),{nodes,inactive,positions}=layout;
    const inputs=['pv_power','grid_power','battery_power'].map(key=>number(snapshot?.sensors?.[key]?.value));
    const total=inputs.some(v=>v===null)?null:inputs.reduce((sum,v)=>sum+Math.max(v,0),0);
    const max=Math.max(1,...nodes.map(n=>n.value||0));
    const definitions=nodes.map(n=>`<marker id="energyArrow-${n.key}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="${n.color}"/></marker>`).join('');
    const paths=nodes.map(n=>{
      const active=animate&&n.value!==null&&n.value>0;
      const width=n.value>0?2+3*Math.sqrt(n.value/max):2;
      const middle=(n.from[0]+n.to[0])/2,d=`M${n.from} C${middle},${n.from[1]} ${middle},${n.to[1]} ${n.to}`;
      const duration=(4.5-1.5*Math.sqrt(Math.max(0,n.value||0)/max)).toFixed(2);
      const packets=active?`<circle r="3.5" fill="${n.color}" class="energy-packet"><animateMotion dur="${duration}s" repeatCount="indefinite" path="${d}"/></circle>`:'';
      return `<g data-link="${n.key}" data-direction="${n.side}" style="--flow-color:${n.color};--flow-width:${width}px"><path d="${d}" class="flow-track"/><path d="${d}" class="energy-link ${active?'':'idle'}" stroke="${n.color}" stroke-width="${width}" style="animation-duration:${duration}s" ${n.value>0?`marker-end="url(#energyArrow-${n.key})"`:''}><title>${escape(n.label)}: ${escape(format(n.value,'W'))}</title></path>${packets}</g>`;
    }).join('');
    const glyph=(name,x,y,color,size=26)=>`<svg x="${x}" y="${y}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.bolt||''}</svg>`;
    const rendered=nodes.map(n=>{
      const previous=lastLayout[n.key],active=animate&&n.value>0;
      const moving=animate&&previous&&(previous.x!==n.x||previous.y!==n.y);
      const value=String(format(n.value,'W'));
      return `<g transform="translate(${n.x},${n.y})" data-flow="${n.key}" data-side="${n.side}"><g class="flow-node flow-circuit ${moving?'flow-relocating':''}" style="--flow-color:${n.color};--shift-x:${moving?previous.x-n.x:0}px;--shift-y:${moving?previous.y-n.y:0}px"><title>${escape(n.label)}: ${escape(value)}${n.value===null?' · direction not confirmed':''}</title><rect x="0" y="-29" width="220" height="58" rx="13" class="flow-tile"/><circle cx="31" cy="0" r="24" class="flow-halo ${active?'active':''}"/><circle cx="31" cy="0" r="20" class="flow-icon-disc"/>${glyph(n.icon,18,-13,n.color)}<text x="64" y="-7" class="flow-node-label">${escape(n.label)}</text><text x="64" y="17" class="flow-node-value" ${value.length>14?'textLength="148" lengthAdjust="spacingAndGlyphs"':''}>${escape(value)}</text></g></g>`;
    }).join('');
    const inverter=`<g class="flow-node flow-hub"><rect x="358" y="144" width="224" height="132" rx="27" class="flow-hub-halo ${animate&&total>0?'active':''}"/><rect x="370" y="156" width="200" height="108" rx="19" class="energy-node inverter"/>${glyph('cpu',387,173,'#1688d0')}<text x="425" y="190" class="flow-node-label">INVERTER</text><text x="470" y="226" text-anchor="middle" class="flow-node-value" ${String(format(total,'W')).length>16?'textLength="176" lengthAdjust="spacingAndGlyphs"':''}>${escape(format(total,'W'))}</text><text x="470" y="296" text-anchor="middle" class="flow-section-label">COMBINED INPUT</text></g>`;
    const empty=['source','destination'].filter(side=>!nodes.some(n=>n.side===side)).map(side=>`<text x="${side==='source'?130:830}" y="215" text-anchor="middle" class="flow-empty">No active ${side==='source'?'sources':'destinations'}</text>`).join('');
    return {...layout,side:positions.battery?.side||'idle',svg:`<defs>${definitions}</defs><text x="20" y="25" class="flow-section-label">SOURCES · POWER IN</text><text x="720" y="25" class="flow-section-label">DESTINATIONS · POWER OUT</text>${paths}${inverter}${rendered}${empty}`};
  }
  function detailedFlowLayout(snapshot) {
    const sensors=snapshot?.sensors||{}, val=key=>number(sensors[key]?.value);
    const grid=val('grid_power'),battery=val('battery_power');
    const split=['pv1_power','pv2_power','pv1_voltage','pv2_voltage'].some(key=>Object.hasOwn(sensors,key));
    const pv=split
      ? [['pv1','PV1 · MPPT 1','pv1','source','solar','#f4cb7c'],['pv2','PV2 · MPPT 2','pv2','source','solar','#f3b968']]
      : [['solar','Solar · combined','pv','source','solar','#f4cb7c']];
    const specs=[...pv,['grid',grid===null?'Grid · unknown':grid<0?'Grid export':'Grid import','grid',grid<0?'destination':'source','grid','#7ac5ff'],
      ['battery',battery===null?'Battery · unknown':battery>0?'Discharging':'Charging','battery',battery>0?'source':'destination','battery','#c4a8ff'],
      ['backup','Backup · essentials','backup','destination','home','#6fe0c5'],['gen','GEN · high-power loads','gen_port','destination','bolt','#ffad87'],
      ['normal','Normal · grid only','load','grid-only','plug','#a2bbd6']];
    const nodes=[],inactive=[],positions={};
    for(const [key,label,prefix,side,icon,color] of specs) {
      const raw=val(prefix+'_power');
      if(raw===0){inactive.push({key,label:key==='grid'?'Grid':key==='battery'?'Battery':label});continue;}
      nodes.push({key,label,prefix,side,icon,color,raw,value:raw===null?null:['grid','battery'].includes(key)?Math.abs(raw):raw,
        voltage:val(prefix+'_voltage'),current:val(prefix+'_current'),soc:key==='battery'?val('battery_soc'):null});
    }
    for(const side of ['source','destination']) {
      const column=nodes.filter(n=>n.side===side);
      column.forEach((n,i)=>{
        n.x=side==='source'?24:900;n.y=300+(i-(column.length-1)/2)*132;
        const port=322+(i-(column.length-1)/2)*32;
        n.from=side==='source'?[300,n.y]:[720,port];n.to=side==='source'?[480,port]:[900,n.y];
        positions[n.key]={x:n.x,y:n.y,side};
      });
    }
    const normal=nodes.find(n=>n.key==='normal');
    if(normal){normal.x=900;normal.y=636;normal.from=[460,636];normal.to=[900,636];positions.normal={x:900,y:636,side:'grid-only'};}
    return {nodes,inactive,positions,split};
  }
  function detailedFlowSvg(snapshot,options) {
    const {format,icons,animate=false,lastLayout={}}=options;
    const layout=detailedFlowLayout(snapshot),{nodes,positions}=layout;
    const lossEstimate=inverterLossEstimate(snapshot);
    const val=key=>number(snapshot?.sensors?.[key]?.value);
    const sourceReadings=['pv_power','grid_power','battery_power'].map(val);
    const total=sourceReadings.some(v=>v===null)?null:sourceReadings.reduce((sum,v)=>sum+Math.max(v,0),0);
    const max=Math.max(1,...nodes.map(n=>n.value||0));
    const glyph=(name,x,y,color,size=28)=>`<svg x="${x}" y="${y}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.bolt||''}</svg>`;
    const defs=nodes.map(n=>`<marker id="detailArrow-${n.key}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="${n.color}"/></marker>`).join('');
    const paths=nodes.map(n=>{
      const active=animate&&n.value!==null&&n.value>0,middle=(n.from[0]+n.to[0])/2;
      const d=`M${n.from} C${middle},${n.from[1]} ${middle},${n.to[1]} ${n.to}`,duration=(5-2*Math.sqrt(Math.max(0,n.value||0)/max)).toFixed(2);
      const packets=active?[0,1,2].map(i=>`<circle r="4" class="detail-packet" fill="${n.color}"><animateMotion dur="${duration}s" begin="-${Number(duration)*i/3}s" repeatCount="indefinite" path="${d}"/></circle>`).join(''):'';
      return `<g data-link="${n.key}" data-direction="${n.side}" style="--flow-color:${n.color}"><path d="${d}" class="detail-track"/><path d="${d}" class="detail-link ${active?'circuit-running':'idle'}" ${n.value>0?`marker-end="url(#detailArrow-${n.key})"`:''}/>${packets}</g>`;
    }).join('');
    const rendered=nodes.map(n=>{
      const previous=lastLayout[n.key],moving=animate&&previous&&(previous.x!==n.x||previous.y!==n.y);
      const power=String(format(n.value,'W')),electrical=`${format(n.voltage,'V')}  ·  ${format(n.current,'A')}`;
      const soc=n.soc===null?'':`<text x="254" y="-28" text-anchor="end" class="detail-soc-label">${escape(format(n.soc,'%'))}</text><rect x="76" y="45" width="178" height="4" rx="2" class="detail-soc-track"/><rect x="76" y="45" width="${178*Math.max(0,Math.min(100,n.soc))/100}" height="4" rx="2" fill="${n.color}"/>`;
      return `<g transform="translate(${n.x},${n.y})" data-flow="${n.key}" data-side="${n.side}"><g class="detail-node ${n.value===null?'unknown':''} ${moving?'flow-relocating':''}" tabindex="0" role="img" aria-label="${escape(n.label+': '+power+'; '+electrical+(n.soc===null?'':'; '+format(n.soc,'%')+' SOC'))}" style="--flow-color:${n.color};--shift-x:${moving?previous.x-n.x:0}px;--shift-y:${moving?previous.y-n.y:0}px"><title>${escape(n.label)}: ${escape(power)} · ${escape(electrical)}${n.value===null?' · direction unknown':''}</title><path d="M14,-56 H248 L276,-28 V42 Q276,56 262,56 H14 Q0,56 0,42 V-42 Q0,-56 14,-56 Z" class="detail-tile"/><path d="M13,-40 H54 M260,40 H230" class="detail-corner"/><rect x="0" y="-28" width="3" height="56" rx="1.5" fill="${n.color}"/><circle cx="36" cy="-10" r="23" class="detail-icon-disc"/>${glyph(n.icon,22,-24,n.color)}<text x="76" y="-28" class="detail-node-label">${escape(n.label)}</text><text x="76" y="5" class="detail-node-power ${animate&&n.value>0?'updated':''}" ${power.length>15?'textLength="178" lengthAdjust="spacingAndGlyphs"':''}>${escape(power)}</text><text x="76" y="31" class="detail-node-electrical" ${electrical.length>26?'textLength="178" lengthAdjust="spacingAndGlyphs"':''}>${escape(electrical)}</text>${soc}</g></g>`;
    }).join('');
    const anyActive=animate&&nodes.some(n=>n.side!=='grid-only'&&n.value>0);
    const lossValue=lossEstimate.state==='estimated'?format(lossEstimate.value,'W'):lossEstimate.state==='mismatch'?format(lossEstimate.residual,'W'):'—';
    const lossCaption=lossEstimate.state==='estimated'?'EST. LOSS + SELF-USE':lossEstimate.state==='mismatch'?'SIGNED BALANCE MISMATCH':lossEstimate.state==='unsupported'?'PORT DIRECTION UNSUPPORTED':'LOSS ESTIMATE UNAVAILABLE';
    const lossHelp=lossEstimate.state==='estimated'
      ? `Estimated inverter conversion and self-use: ${lossValue}. ${lossEstimate.formula}. Includes wiring, meter and sequential-capture residual.`
      : lossEstimate.state==='mismatch'
        ? `Loss is not reported because measured destinations exceed sources by ${format(Math.abs(lossEstimate.residual),'W')}. Signed balance: ${format(lossEstimate.residual,'W')}.`
        : 'Loss requires one complete successful sample with every power boundary measured.';
    const hub=`<g class="detail-hub"><circle cx="600" cy="322" r="156" class="core-orbit outer ${anyActive?'active':''}"/><circle cx="600" cy="322" r="142" class="core-orbit inner ${anyActive?'active':''}"/><circle cx="600" cy="322" r="127" class="detail-hub-outline"/><circle cx="600" cy="322" r="116" class="detail-hub-body"/>${glyph('cpu',586,222,'#9befee',28)}<text x="600" y="276" text-anchor="middle" class="detail-hub-title">PV9000</text><path d="M536 297h20l13-12 20 25 20-25 20 25 13-13h22" class="detail-wave ${anyActive?'active':''}"/><text x="600" y="347" text-anchor="middle" class="detail-hub-total" ${String(format(total,'W')).length>16?'textLength="194" lengthAdjust="spacingAndGlyphs"':''}>${escape(format(total,'W'))}</text><text x="600" y="370" text-anchor="middle" class="detail-hub-caption">SOURCE SUM · CALCULATED</text><g class="detail-hub-loss ${lossEstimate.state}" role="img" aria-label="${escape(lossHelp)}"><title>${escape(lossHelp)}</title><rect x="520" y="384" width="160" height="45" rx="10" class="detail-hub-loss-bg"/><text x="600" y="400" text-anchor="middle" class="detail-hub-loss-label">${escape(lossCaption)}</text><text x="600" y="420" text-anchor="middle" class="detail-hub-loss-value" ${String(lossValue).length>15?'textLength="136" lengthAdjust="spacingAndGlyphs"':''}>${escape(lossValue)}</text></g><text x="600" y="510" text-anchor="middle" class="detail-hub-caption">LOGICAL POWER ROUTING</text></g>`;
    const bypass=nodes.some(n=>n.key==='normal')?`<path d="M24 572H1176" class="detail-separator"/><rect x="230" y="607" width="230" height="58" rx="12" class="detail-grid-terminal"/>${glyph('grid',245,622,'#627991',26)}<text x="286" y="632" class="detail-node-label">Grid-only connection</text><text x="286" y="652" class="detail-hub-caption">NO BATTERY BACKUP</text>`:'';
    const empty=['source','destination'].filter(side=>!nodes.some(n=>n.side===side)).map(side=>`<text x="${side==='source'?162:1038}" y="306" text-anchor="middle" class="flow-empty">No active ${side==='source'?'sources':'destinations'}</text>`).join('');
    return {...layout,lossEstimate,side:positions.battery?.side||'idle',svg:`<defs>${defs}</defs><text x="24" y="26" class="detail-column-title">POWER SOURCES</text><text x="900" y="26" class="detail-column-title">POWER DESTINATIONS</text>${paths}${hub}${rendered}${bypass}${empty}`};
  }
  const api = {number,seriesSegments,balanceParts,inverterLossEstimate,telemetryState,pageName,filterSensors,csvText,historyCsv,flowLayout,flowSvg,detailedFlowLayout,detailedFlowSvg};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DashboardUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
