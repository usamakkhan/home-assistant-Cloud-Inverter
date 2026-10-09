(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  if (!byId('view-systems')) return;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const finite = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
  const exact = (value, unit = '') => {
    value = finite(value);
    return value === null ? '—' : `${String(value)}${unit ? ` ${unit}` : ''}`;
  };
  const timeLabel = value => {
    if (!value) return 'Not captured';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Invalid timestamp' : date.toLocaleString();
  };
  const ageLabel = seconds => {
    seconds = finite(seconds);
    if (seconds === null) return 'No sample';
    if (seconds < 60) return `${String(seconds)} s ago`;
    if (seconds < 3600) return `${String(Math.floor(seconds / 60))} min ago`;
    return `${String(Math.floor(seconds / 3600))} h ago`;
  };
  const icon = kind => ({
    solarmax:'<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="3"/><path d="M8 7h8v5H8zM9 16h6m-3-4v4"/></svg>',
    knox:'<svg viewBox="0 0 24 24"><path d="M12 2 4 6v12l8 4 8-4V6l-8-4Z"/><path d="m8 14 4-7v5h4l-4 6v-4H8Z"/></svg>',
  }[kind] || '');

  let apiBase = '';
  let state = {config:null, status:null, systems:null, primary:null, neighbor:null, comparison:null, alerts:null};
  let requestSequence = 0;
  let chartCursor = null;
  let adminAvailable = true;

  async function readJson(path) {
    const response = await fetch(apiBase + path, {cache:'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
    return data;
  }
  async function postJson(path, data) {
    const response = await fetch(apiBase + path, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data), cache:'no-store',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
    return payload;
  }

  function systemCard(target, latest, system, type, config) {
    const metric = latest?.metrics || {};
    const telemetry = latest?.telemetry || {};
    const available = !!latest?.available;
    const age = finite(latest?.age_seconds);
    const thresholdKey=type==='mine'?'primary_stale_after_seconds':'neighbor_stale_after_seconds';
    const staleAfter=finite(state.status?.freshness?.[thresholdKey])??45;
    const fresh = available && age !== null && age <= staleAfter;
    const configured = type === 'mine' || !!config?.configured;
    const statusClass = !configured ? 'setup' : !available ? 'offline' : fresh ? 'fresh' : 'stale';
    const statusText = !configured ? 'Setup required' : !available ? 'No decoded data' : age === null ? 'Freshness unknown' : fresh ? 'Fresh' : 'Stale';
    const array = system?.array || {};
    const confidence = type === 'mine' ? 'Verified Senergy map' : config?.protocol_status?.replaceAll('_',' ') || 'Unverified';
    const liveDetails = type === 'neighbor' && available ? `<div class="peer-live-ribbon">
      <div><span>AC output</span><strong>${esc(exact(telemetry.output_active_power_w,'W'))}</strong></div>
      <div><span>Battery</span><strong>${esc(exact(telemetry.battery_soc_percent,'%'))}</strong></div>
      <div><span>Grid</span><strong>${esc(exact(telemetry.grid_voltage_v,'V'))}</strong></div>
      <div><span>Temperature</span><strong>${esc(exact(telemetry.inverter_temperature_c,'°C'))}</strong></div>
    </div>` : '';
    target.innerHTML = `
      <div class="peer-card-head"><div class="peer-device-mark"><span class="peer-device-icon">${icon(type === 'mine' ? 'solarmax' : 'knox')}</span><div><h2>${esc(system?.name || (type === 'mine' ? 'My SolarMax' : 'Neighbor Knox'))}</h2><p>${esc(system?.model || 'Model pending')}</p></div></div><span class="peer-status-chip ${statusClass}">${esc(statusText)}</span></div>
      <div class="peer-power-readout"><span>PV DC INPUT</span><strong>${esc(exact(metric.pv_power_w))}</strong><em>W</em></div>
      <div class="peer-card-stats"><div><span>Installed DC</span><strong>${esc(exact(array.dc_nameplate_kwp, 'kWp'))}</strong></div><div><span>Specific output</span><strong>${esc(exact(metric.specific_power_w_kwp, 'W/kWp'))}</strong></div><div><span>Per panel</span><strong>${esc(exact(metric.power_per_panel_w, 'W'))}</strong></div></div>
      ${liveDetails}
      <div class="peer-card-foot"><span>${esc(`${array.panel_count ?? '—'} × ${array.panel_watts ?? '—'} W panels`)}</span><strong title="${esc(latest?.captured_at || '')}">${esc(ageLabel(age))}</strong></div>
      <div class="peer-card-foot"><span>Profile confidence</span><strong>${esc(confidence)}</strong></div>`;
  }

  function renderSystems() {
    const systems = state.systems?.systems || [];
    const primarySystem = systems.find(system => system.id === 'primary') || state.primary?.device;
    const neighborSystem = systems.find(system => system.id === 'neighbor') || state.neighbor?.device;
    systemCard(byId('primarySystemCard'), state.primary, primarySystem, 'mine', {configured:true});
    systemCard(byId('neighborSystemCard'), state.neighbor, neighborSystem, 'neighbor', state.config);
  }

  const metricMeta = () => ({
    specific_power_w_kwp:{label:'Normalized PV power', unit:'W/kWp'},
    pv_power_w:{label:'Raw PV power', unit:'W'},
    power_per_panel_w:{label:'PV power per panel', unit:'W/panel'},
    capacity_utilization_percent:{label:'DC nameplate utilization', unit:'%'},
  }[byId('peerMetric').value]);
  const sideTimestamp = (point, side) => {
    const parsed=Date.parse(point?.[`${side}_captured_at`]);
    return Number.isFinite(parsed)?parsed:finite(point?.timestamp_ms);
  };

  function segments(points, side, key, x, y, maxGapMs) {
    const result = [];
    let current = [];
    let previousTime = null;
    for (const point of points) {
      const value = finite(point?.[side]?.[key]);
      const time = sideTimestamp(point,side);
      if (value === null || time === null || (previousTime !== null && time - previousTime > maxGapMs)) {
        if (current.length) result.push(current);
        current = [];
      }
      if (value !== null && time !== null) current.push([x(time), y(value)]);
      previousTime = time;
    }
    if (current.length) result.push(current);
    return result;
  }
  function linePath(segment) {
    return segment.map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  }
  function areaPath(segment, bottom) {
    if (!segment.length) return '';
    return `${linePath(segment)} L${segment.at(-1)[0].toFixed(2)},${bottom} L${segment[0][0].toFixed(2)},${bottom} Z`;
  }

  function renderChart() {
    const svg = byId('peerChart');
    if (!svg || !state.comparison) return;
    const points = state.comparison.points || [];
    const key = byId('peerMetric').value;
    const meta = metricMeta();
    const values = points.flatMap(point => [finite(point.primary?.[key]), finite(point.neighbor?.[key])]).filter(value => value !== null);
    if (!points.length || !values.length) {
      svg.innerHTML = `<g><circle cx="500" cy="172" r="62" fill="none" stroke="#294057" stroke-dasharray="3 7"/><path d="M470 178h60M480 158l20-18 20 18" fill="none" stroke="#6f879b" stroke-width="2"/><text x="500" y="267" class="peer-empty-chart peer-empty-chart-title">Waiting for two comparable telemetry streams</text><text x="500" y="291" class="peer-empty-chart">${esc(state.comparison.reason?.replaceAll('_',' ') || 'No aligned samples')}</text></g>`;
      byId('peerChartTooltip').textContent = state.config?.configured
        ? 'The network identity is saved, but a Knox register decoder has not been verified. No SolarMax register addresses are being guessed.'
        : 'Enter the exact neighbor logger IP below. The current message did not contain an address, so the API remains safely unconfigured.';
      byId('peerChartFloat').hidden = true;
      renderInsights();
      return;
    }
    const width = 1000, height = 390, left = 72, right = 24, top = 25, bottom = 48;
    const innerWidth = width - left - right, innerHeight = height - top - bottom;
    const times = points.flatMap(point => [sideTimestamp(point,'primary'),sideTimestamp(point,'neighbor')]).filter(Number.isFinite);
    let minTime = Math.min(...times), maxTime = Math.max(...times);
    if (minTime === maxTime) { minTime -= 5000; maxTime += 5000; }
    const maxValue = Math.max(1, ...values);
    const yMax = maxValue * 1.08;
    const x = value => left + (value - minTime) * innerWidth / (maxTime - minTime);
    const y = value => top + innerHeight - value * innerHeight / yMax;
    const maxGap = Math.max(35000, Number(state.config?.expected_interval_seconds || 10) * 3500);
    const mineSegments = segments(points, 'primary', key, x, y, maxGap);
    const neighborSegments = segments(points, 'neighbor', key, x, y, maxGap);
    const yGrid = Array.from({length:6}, (_, index) => {
      const value = yMax * index / 5, yy = y(value);
      return `<line x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}" class="peer-grid-line"/><text x="${left-10}" y="${yy+4}" text-anchor="end" class="peer-axis-label">${esc(value.toLocaleString(undefined,{maximumFractionDigits:2}))}</text>`;
    }).join('');
    const xGrid = Array.from({length:5}, (_, index) => {
      const timestamp = minTime + (maxTime-minTime)*index/4, xx=x(timestamp);
      return `<line x1="${xx}" x2="${xx}" y1="${top}" y2="${height-bottom}" class="peer-grid-line"/><text x="${xx}" y="${height-19}" text-anchor="middle" class="peer-axis-label">${esc(new Date(timestamp).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}))}</text>`;
    }).join('');
    const connectors = points.map(point => {
      const mine=finite(point.primary?.[key]),neighbor=finite(point.neighbor?.[key]);
      if(mine===null||neighbor===null)return '';
      const mineX=x(sideTimestamp(point,'primary')),neighborX=x(sideTimestamp(point,'neighbor'));
      return `<line x1="${mineX}" x2="${neighborX}" y1="${y(mine)}" y2="${y(neighbor)}" class="peer-pair-link"/><circle cx="${mineX}" cy="${y(mine)}" r="3.5" fill="#62f0bb"/><circle cx="${neighborX}" cy="${y(neighbor)}" r="3.5" fill="#7db7ff"/>`;
    }).join('');
    svg.innerHTML = `<defs><linearGradient id="peerMineArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#62f0bb" stop-opacity=".23"/><stop offset="1" stop-color="#62f0bb" stop-opacity="0"/></linearGradient><linearGradient id="peerNeighborArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7db7ff" stop-opacity=".2"/><stop offset="1" stop-color="#7db7ff" stop-opacity="0"/></linearGradient></defs>${yGrid}${xGrid}<text x="${left}" y="14" class="peer-axis-label">${esc(meta.unit)}</text>${mineSegments.map(segment=>`<path d="${areaPath(segment,height-bottom)}" class="peer-area mine"/><path d="${linePath(segment)}" class="peer-line mine"/>`).join('')}${neighborSegments.map(segment=>`<path d="${areaPath(segment,height-bottom)}" class="peer-area neighbor"/><path d="${linePath(segment)}" class="peer-line neighbor"/>`).join('')}${connectors}<g id="peerHoverLayer"></g><rect id="peerHoverTarget" x="${left}" y="${top}" width="${innerWidth}" height="${innerHeight}" fill="transparent"/>`;
    const target = svg.querySelector('#peerHoverTarget');
    const hover = svg.querySelector('#peerHoverLayer');
    const float = byId('peerChartFloat');
    const showPoint = (point, pointerX = null, pointerY = null) => {
      chartCursor=point.timestamp_ms;
      const mineX=x(sideTimestamp(point,'primary')),neighborX=x(sideTimestamp(point,'neighbor')),xx=(mineX+neighborX)/2,mine=finite(point.primary?.[key]),neighbor=finite(point.neighbor?.[key]);
      hover.innerHTML=`<line x1="${xx}" x2="${xx}" y1="${top}" y2="${height-bottom}" class="peer-hover-line"/>${mine===null?'':`<circle cx="${mineX}" cy="${y(mine)}" r="6" fill="#62f0bb" class="peer-hover-dot"/>`}${neighbor===null?'':`<circle cx="${neighborX}" cy="${y(neighbor)}" r="6" fill="#7db7ff" class="peer-hover-dot"/>`}`;
      float.innerHTML=`<strong>${esc(meta.label)}</strong><span><b class="mine">My SolarMax</b><b>${esc(exact(mine,meta.unit))}</b></span><span><b class="neighbor">Neighbor Knox</b><b>${esc(exact(neighbor,meta.unit))}</b></span><small>Mine: ${esc(timeLabel(point.primary_captured_at))}<br>Neighbor: ${esc(timeLabel(point.neighbor_captured_at))}<br>Capture skew: ${esc(exact(point.skew_ms,'ms'))}</small>`;
      float.hidden=false;
      const plot=byId('peerChartPlot'),plotBox=plot.getBoundingClientRect(),svgBox=svg.getBoundingClientRect();
      const displayX=pointerX===null?svgBox.left+xx*svgBox.width/width-plotBox.left:pointerX-plotBox.left;
      const displayY=pointerY===null?height/2:pointerY-plotBox.top;
      float.style.left=`${Math.max(8,Math.min(plot.clientWidth-float.offsetWidth-8,displayX+14))}px`;
      float.style.top=`${Math.max(8,displayY-float.offsetHeight-12)}px`;
      svg.setAttribute('aria-label',`${meta.label}. My SolarMax ${exact(mine,meta.unit)}. Neighbor Knox ${exact(neighbor,meta.unit)}. Capture skew ${exact(point.skew_ms,'ms')}. Use arrow keys to inspect samples.`);
    };
    const move = event => {
      const box=svg.getBoundingClientRect();
      const cursor=(event.clientX-box.left)*width/box.width;
      const cursorTime=minTime+(cursor-left)*(maxTime-minTime)/innerWidth;
      const point=points.reduce((best,item)=>!best||Math.abs(item.timestamp_ms-cursorTime)<Math.abs(best.timestamp_ms-cursorTime)?item:best,null);
      if(point)showPoint(point,event.clientX,event.clientY);
    };
    target.addEventListener('pointermove',move);
    target.addEventListener('pointerdown',move);
    const dismiss=()=>{hover.innerHTML='';float.hidden=true;chartCursor=null};
    target.addEventListener('pointerleave',dismiss);
    svg.onkeydown=event=>{
      if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;
      event.preventDefault();
      if(event.key==='Escape'){dismiss();return;}
      let index=chartCursor===null?points.length-1:points.findIndex(point=>point.timestamp_ms===chartCursor);
      if(event.key==='Home')index=0;else if(event.key==='End')index=points.length-1;else index=Math.max(0,Math.min(points.length-1,index+(event.key==='ArrowLeft'?-1:1)));
      showPoint(points[index]);
    };
    svg.onfocus=()=>{if(chartCursor===null)showPoint(points.at(-1))};
    const comparableCount=state.comparison.alignment?.comparable_pair_count??points.filter(point=>point.comparable).length;
    byId('peerChartTooltip').textContent=`${String(points.length)} aligned pair${points.length===1?'':'s'} · ${String(comparableCount)} comparable · maximum-cardinality, minimum-skew pairing within ${String(state.comparison.alignment?.max_skew_seconds)} s · no interpolation · exact zero retained`;
    renderInsights();
  }

  function renderInsights() {
    const latest=state.comparison?.latest_comparable??state.comparison?.latest;
    const mineSpecific=finite(latest?.primary?.specific_power_w_kwp),neighborSpecific=finite(latest?.neighbor?.specific_power_w_kwp);
    const floor=finite(state.alerts?.rules?.peer_underperformance?.activation_w_per_kwp)??100;
    const lowLight=mineSpecific!==null&&neighborSpecific!==null&&Math.max(mineSpecific,neighborSpecific)<floor;
    const items = [
      ['Aligned / comparable', `${state.comparison?.alignment?.pair_count ?? 0} / ${state.comparison?.alignment?.comparable_pair_count ?? 0}`],
      ['Latest sample skew', exact(latest?.skew_ms,'ms')],
      ['Neighbor / mine', lowLight?'Low light':exact(latest?.delta?.neighbor_to_primary_percent,'%')],
      ['Specific delta', lowLight?'Suppressed':exact(latest?.delta?.specific_power_w_kwp,'W/kWp')],
    ];
    byId('peerInsightStrip').innerHTML=items.map(([label,value])=>`<div class="peer-insight"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
  }

  const setupStates = new Set(['setup_required','calibration_required','calibrating','monitoring_disabled','unknown','suppressed_low_light','disabled']);
  function alertMatches(alert) {
    const stateFilter=byId('peerAlertSeverity').value,device=byId('peerAlertDevice').value;
    const stateMatch=stateFilter==='all'||alert.state===stateFilter||(stateFilter==='setup'&&setupStates.has(alert.state));
    return stateMatch&&(device==='all'||alert.device_id===device);
  }
  function alertsMarkup(alerts, filtered=true) {
    const visible=filtered?(alerts||[]).filter(alertMatches):(alerts||[]);
    if(!visible.length)return '<div class="empty-panel"><h3>No alerts match this filter</h3><p>Unknown and suppressed states are distinct from healthy.</p></div>';
    return `<div class="peer-alert-list">${visible.map(alert=>`<article class="peer-alert-item" data-state="${esc(alert.state)}"><div class="peer-alert-item-head"><h3>${esc(alert.id.replaceAll('_',' '))}</h3><span class="peer-alert-state">${esc(alert.state.replaceAll('_',' '))}</span></div><p>${esc(alert.message)}</p><div class="peer-alert-meta"><span>${esc(alert.device_id==='primary'?'My SolarMax':'Neighbor Knox')}</span><span>Updated ${esc(timeLabel(alert.updated_at))}</span>${alert.opened_at?`<span>Opened ${esc(timeLabel(alert.opened_at))}</span>`:''}</div></article>`).join('')}</div>`;
  }
  function renderAlerts() {
    const data=state.alerts||{alerts:[],rules:{}};
    const firing=finite(data.firing_count)??0,active=finite(data.active_count)??0;
    byId('peerAlertSummary').textContent=`${String(firing)} firing · ${String(active)} active`;
    byId('peerAlertList').innerHTML=alertsMarkup(data.alerts);
    const mirror=byId('peerAlertsMirror');
    if(mirror)mirror.innerHTML=`<div class="surface-head"><div><h2>Comparison alert engine</h2><p>All persistent states from the independent Knox API. Filters on the comparison page do not apply here.</p></div><span class="peer-alert-count">${esc(String(firing))} firing</span></div>${alertsMarkup(data.alerts,false)}`;
    const rule=data.rules?.peer_underperformance;
    if(rule){byId('peerRuleEnabled').checked=!!rule.enabled;byId('peerRuleDeficit').value=String(rule.deficit_percent);byId('peerRuleDuration').value=String(rule.trigger_for_seconds);byId('peerRuleFloor').value=String(rule.activation_w_per_kwp)}
    byId('peerRuleSaveBtn').disabled=!adminAvailable;
  }

  function renderConfig() {
    const config=state.config;if(!config)return;
    byId('peerLabel').value=config.name||'';
    byId('peerInverterModel').value=config.model||'';
    byId('peerHost').value=config.host||'';
    byId('peerUdpPort').value=String(config.udp_port||58899);
    byId('peerCallbackPort').value=String(config.callback_port||8899);
    byId('peerCallbackHost').value=config.callback_host||'';
    byId('peerCollectionMode').value=config.collection_mode||'local';
    byId('peerPanels').value=String(config.panel_count||10);
    byId('peerPanelWatts').value=String(config.panel_watts||585);
    byId('peerProbeBtn').disabled=!config.configured||!adminAvailable;
    byId('savePeerConfigBtn').disabled=!adminAvailable;
    const local=config.collection_mode!=='original';
    const verified=config.protocol_status==='verified';
    byId('peerConfigStatus').className=`status ${verified&&local?'ok':config.configured?'warn':''}`;
    byId('peerConfigStatus').textContent=config.configured
      ? local
        ? `${config.host} · PI18 ${verified?'verified':'identification pending'} · ${config.automatic_collection?'10-second collection active':'collector starting'}.`
        : `${config.host} · Original/cloud mode · this app sends no local callback requests.`
      : 'Enter the neighbor logger IP to start read-only identification and local collection.';
    if(!adminAvailable)byId('peerConfigStatus').textContent='Viewing through a LAN URL. Open the dashboard on this computer at 127.0.0.1 to change device identity or alert rules.';
    renderProbe(config.last_probe);
  }
  function renderProbe(probe) {
    const target=byId('peerProbeEvidence');
    if(!probe){target.innerHTML='';return;}
    const callback=probe.callback;
    if(!callback){
      target.innerHTML=`<div class="peer-legacy-evidence"><strong>Earlier Modbus check</strong><span>No port-502 response. This result is obsolete because the logger is now confirmed as an outbound EyeBond callback client.</span></div>`;
      return;
    }
    const identity=probe.device_identification||{};
    const metadata=callback.metadata||{};
    const inverter=callback.inverter||{};
    const outcome=callback.ok?'CALLBACK RECEIVED':'NO CALLBACK';
    target.innerHTML=`<div class="peer-evidence-grid callback"><div><span>Reverse callback</span><strong>${outcome}</strong></div><div><span>Inverter protocol</span><strong>${esc(identity.protocol||inverter.protocol_id||'Pending')}</strong></div><div><span>Read commands</span><strong>${esc(String(callback.inverter_reads||0))}</strong></div><div><span>Writes</span><strong>${esc(String((callback.collector_setting_writes||0)+(callback.inverter_writes||0)))}</strong></div></div>
      <div class="peer-identity-sheet"><div><span>Collector PN</span><strong>${esc(callback.collector_pn||'Not read')}</strong></div><div><span>Logger firmware</span><strong>${esc(metadata.firmware_version||'Not read')}</strong></div><div><span>Logger hardware</span><strong>${esc(metadata.hardware_version||'Not read')}</strong></div><div><span>Saved cloud host</span><strong>${esc(metadata.cloud_endpoint||'Not read')}</strong></div></div>
      <p class="subtle">${esc(timeLabel(probe.captured_at))} · transient callback · PI18 reads only · saved logger settings unchanged${callback.error?` · ${esc(callback.error)}`:''}.</p>`;
  }

  function renderNeighborTelemetry() {
    const target=byId('peerTelemetryEvidence');
    const telemetry=state.neighbor?.telemetry||{};
    const sensors=state.neighbor?.sensors||{};
    const collector=state.status?.collector||{};
    if(!Object.keys(telemetry).length){
      const paused=state.config?.collection_mode==='original';
      target.innerHTML=`<div class="peer-telemetry-empty"><strong>${paused?'Local capture paused':'Waiting for live PI18 data'}</strong><span>${esc(paused?'Original/cloud mode makes no callback requests.':collector.last_error||'The collector will retry automatically.')}</span></div>`;
      return;
    }
    const featured=[
      ['PV input',telemetry.pv_power_w,'W'],['AC output',telemetry.output_active_power_w,'W'],
      ['Battery',telemetry.battery_soc_percent,'%'],['Battery flow',telemetry.battery_power_w,'W'],
      ['Grid',telemetry.grid_voltage_v,'V'],['Grid frequency',telemetry.grid_frequency_hz,'Hz'],
      ['Inverter',telemetry.inverter_temperature_c,'°C'],['Mode',sensors.inverter_mode?.value,''],
    ];
    const all=Object.values(sensors).filter(sensor=>sensor&&Object.hasOwn(sensor,'value'));
    target.innerHTML=`<div class="peer-telemetry-head"><div><span>LIVE PI18 TELEMETRY</span><strong>${esc(timeLabel(state.neighbor?.captured_at))}</strong></div><em>${esc(String(all.length))} decoded fields</em></div>
      <div class="peer-telemetry-grid">${featured.map(([label,value,unit])=>`<div><span>${esc(label)}</span><strong>${esc(typeof value==='number'?exact(value,unit):value||'—')}</strong></div>`).join('')}</div>
      <details class="peer-all-fields"><summary>Show every decoded field</summary><div>${all.map(sensor=>`<article><span>${esc(sensor.name)}</span><strong>${esc(typeof sensor.value==='number'?exact(sensor.value,sensor.unit):sensor.value)}</strong><small>${esc(sensor.category||'Telemetry')}</small></article>`).join('')}</div></details>`;
  }

  function renderStatus() {
    const page=byId('peerPageState');
    const pulse=document.querySelector('.peer-api-pulse');
    if(!state.status){page.dataset.state='offline';page.querySelector('span').textContent='Separate API unavailable';if(pulse)pulse.dataset.state='offline';return;}
    if(pulse)pulse.dataset.state='online';
    const primaryAge=finite(state.primary?.age_seconds),neighborAge=finite(state.neighbor?.age_seconds);
    const primaryLimit=finite(state.status.freshness?.primary_stale_after_seconds)??45;
    const neighborLimit=finite(state.status.freshness?.neighbor_stale_after_seconds)??45;
    const primaryFresh=!!state.primary?.available&&primaryAge!==null&&primaryAge<=primaryLimit;
    const neighborFresh=!!state.neighbor?.available&&neighborAge!==null&&neighborAge<=neighborLimit;
    const collector=state.status.collector||{};
    const localMode=state.config?.collection_mode!=='original';
    const attention=!state.status.configured||!primaryFresh||!neighborFresh||state.apiErrors?.length;
    page.dataset.state=attention?'attention':'online';
    page.querySelector('span').textContent=!state.status.configured?'Neighbor setup required':!localMode?'Neighbor local capture paused':!primaryFresh?'Primary sample unavailable':!neighborFresh?'Neighbor capture retrying or stale':state.apiErrors?.length?'Partial API response':'Both streams fresh';
    byId('peerCollectorState').textContent=!state.status.configured?'Setup required':!localMode?'Original/cloud mode':collector.running?(collector.last_error?'Retrying':'Capturing'):'Starting';
    byId('peerCollectorState').dataset.state=!localMode?'paused':collector.last_error?'error':collector.running?'online':'pending';
    byId('peerCollectorCadence').textContent=localMode?`${String(collector.expected_interval_seconds||10)} seconds`:'No local polling';
    byId('peerCollectorIdentity').textContent=collector.collector_pn||state.config?.collector_pn||'Pending';
    byId('peerCloudState').textContent=collector.saved_cloud_endpoint||state.config?.cloud_endpoint||'Not read';
    byId('peerRouteLogger').textContent=`${state.config?.host||'Logger IP pending'} · UDP ${String(collector.discovery_port||state.config?.udp_port||58899)}`;
    byId('peerRouteCallback').textContent=`${state.config?.callback_host||'Auto LAN IP'} · TCP ${String(collector.listener_port||state.config?.callback_port||8899)}`;
    byId('peerApiStatus').className=`status ${state.apiErrors?.length?'warn':'ok'}`;
    byId('peerApiStatus').textContent=state.apiErrors?.length
      ? `API partially available · ${state.apiErrors.join('; ')}`
      : `API online · ${state.status.storage?.saved_samples||0} neighbor samples · ${collector.successes||0}/${collector.attempts||0} callback captures · inverter writes disabled`;
  }

  function render() {renderSystems();renderChart();renderAlerts();renderConfig();renderStatus();renderNeighborTelemetry()}
  async function loadAll() {
    const request=++requestSequence;
    const range=Number(byId('peerRange').value||60);
    const requests=[
      ['config',readJson('/config')],['status',readJson('/status')],['systems',readJson('/systems')],
      ['primary',readJson('/systems/primary/latest')],['neighbor',readJson('/systems/neighbor/latest')],
      ['comparison',readJson(`/comparison?minutes=${range}`)],['alerts',readJson('/alerts')],
    ];
    const settled=await Promise.allSettled(requests.map(([,promise])=>promise));
    if(request!==requestSequence)return;
    const next={...state,apiErrors:[]};
    settled.forEach((result,index)=>{const key=requests[index][0];if(result.status==='fulfilled')next[key]=result.value;else next.apiErrors.push(`${key}: ${result.reason?.message||'unavailable'}`)});
    state=next;
    if(!state.status&&!settled.some(result=>result.status==='fulfilled')){
      const page=byId('peerPageState');page.dataset.state='offline';page.querySelector('span').textContent='Separate API offline';
      byId('peerApiStatus').className='status bad';byId('peerApiStatus').textContent=state.apiErrors.join('; ');
      byId('peerChartTooltip').textContent='The SolarMax dashboard remains available; only the independent comparison API failed.';
      return;
    }
    render();
  }

  byId('peerConfigForm').addEventListener('submit',async event=>{
    event.preventDefault();byId('savePeerConfigBtn').disabled=true;
    try{
      const config=await postJson('/admin/config',{name:byId('peerLabel').value,model:byId('peerInverterModel').value,host:byId('peerHost').value,udp_port:Number(byId('peerUdpPort').value),callback_port:Number(byId('peerCallbackPort').value),callback_host:byId('peerCallbackHost').value||null,collection_mode:byId('peerCollectionMode').value,panel_count:Number(byId('peerPanels').value),panel_watts:Number(byId('peerPanelWatts').value),expected_interval_seconds:10});
      state.config=config;renderConfig();await loadAll();byId('peerConfigStatus').className=config.collection_mode==='local'?'status ok':'status warn';byId('peerConfigStatus').textContent=config.collection_mode==='local'?'Local 10-second collection selected. No logger setting or inverter write was sent.':'Original/cloud mode selected. Local callback requests are stopped.';
    }catch(error){byId('peerConfigStatus').className='status bad';byId('peerConfigStatus').textContent=error.message}finally{byId('savePeerConfigBtn').disabled=!adminAvailable}
  });
  byId('peerProbeBtn').addEventListener('click',async()=>{
    byId('peerProbeBtn').disabled=true;byId('peerConfigStatus').className='status warn';byId('peerConfigStatus').textContent='Listening on the local callback port, sending one unicast EyeBond trigger, then reading logger identity and PI18 telemetry…';
    try{const evidence=await postJson('/admin/probe',{});renderProbe(evidence);await loadAll();const ok=!!evidence.callback?.ok;byId('peerConfigStatus').className=ok?'status ok':'status warn';byId('peerConfigStatus').textContent=ok?'EyeBond callback received and PI18 data captured. No write command was sent.':`The logger did not call back: ${evidence.callback?.error||'no response'}`;}catch(error){byId('peerConfigStatus').className='status bad';byId('peerConfigStatus').textContent=error.message}finally{byId('peerProbeBtn').disabled=!state.config?.configured||!adminAvailable}
  });
  byId('peerRuleSaveBtn').addEventListener('click',async()=>{
    byId('peerRuleSaveBtn').disabled=true;
    try{await postJson('/admin/rules',{rules:{peer_underperformance:{enabled:byId('peerRuleEnabled').checked,deficit_percent:Number(byId('peerRuleDeficit').value),trigger_for_seconds:Number(byId('peerRuleDuration').value),activation_w_per_kwp:Number(byId('peerRuleFloor').value)}}});await loadAll();byId('peerRuleStatus').className='status ok';byId('peerRuleStatus').textContent='Alert rule saved. It still requires fresh aligned daylight samples.'}catch(error){byId('peerRuleStatus').className='status bad';byId('peerRuleStatus').textContent=error.message}finally{byId('peerRuleSaveBtn').disabled=!adminAvailable}
  });
  byId('peerRefreshBtn').addEventListener('click',loadAll);
  byId('peerRange').addEventListener('change',loadAll);
  byId('peerMetric').addEventListener('change',renderChart);
  byId('peerAlertSeverity').addEventListener('change',renderAlerts);
  byId('peerAlertDevice').addEventListener('change',renderAlerts);
  byId('copyPeerApiUrlBtn').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(byId('peerApiEndpoint').textContent);byId('peerApiStatus').textContent='API root copied.'}catch{byId('peerApiStatus').textContent='Copy failed; select the URL manually.'}});

  async function initialize() {
    try {
      const main=await fetch('/api/config',{cache:'no-store'}).then(response=>response.json());
      const port=Number(main.peer_api?.port||8767);
      const plainHost=location.hostname.replaceAll('[','').replaceAll(']','');
      adminAvailable=['127.0.0.1','localhost','::1'].includes(plainHost);
      const hostname=location.hostname.includes(':')?`[${location.hostname.replaceAll('[','').replaceAll(']','')}]`:location.hostname;
      apiBase=`${location.protocol}//${hostname}:${port}/v1`;
      byId('peerApiEndpoint').textContent=apiBase;
      await loadAll();
      setInterval(()=>{if(!document.hidden)loadAll()},10000);
    } catch(error) {
      byId('peerApiStatus').className='status bad';byId('peerApiStatus').textContent=error.message;
    }
  }
  window.PeerDashboard={render:renderChart,refresh:loadAll,get cursorTime(){return chartCursor}};
  initialize();
})();
