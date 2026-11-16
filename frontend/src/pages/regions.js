import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {table} from '../components/common/table.js';import {badge} from '../components/common/status.js';import {field} from '../components/common/fields.js';import {BRANCHES,MODELS,REGION_STATES} from '../constants/enums.js';
const fmt=x=>x===null||x===undefined?'未定义':Number(x).toFixed(2);
const st=x=>REGION_STATES[x]||x;
const runOf=()=>state.regionRun&&state.regionRun.id?state.regionRun:null;
function memberRows(r){return (r.members||[]).map(m=>[m.branch,MODELS[m.selected_model]||m.selected_model||'—',st(m.state),m.metrics?fmt(m.metrics[m.selected_model]?.mae):'—',m.error||'—'])}
function basisTables(r){
 let rec=r.result?.reconciliation;if(!rec)return '';
 let branches=Object.keys(rec.branches);
 let dayRows=rec.days.map(d=>[d.day,d.region,d.branch_raw_sum,d.gap,...branches.flatMap(b=>[d.branches[b].before,d.branches[b].after,d.branches[b].delta])]);
 let dayHead=['日期','区域总量','网点原始合计','差额',...branches.flatMap(b=>[b+' 前',b+' 后',b+' Δ'])];
 let gaps=rec.days.filter(d=>d.gap!==0).length;
 let gapNote=gaps?`7日中有 ${gaps} 日区域与网点原始合计存在差额，已按权重分摊并取整。`:'7日区域与网点原始合计完全一致（零差额），无需分摊。';
 let credRows=branches.map(b=>{let c=rec.branches[b];return [b,MODELS[c.model]||c.model,fmt(c.mae),c.mape===null?'未定义':fmt(c.mape)+'%',fmt(c.credibility),fmt(c.adjust_weight)]});
 return `<h3>各层回测与可信度</h3><p class="eyebrow">区域 ${MODELS[rec.region_model]||rec.region_model} · MAE ${fmt(rec.region_mae)} · 可信度 ${fmt(rec.region_credibility)}（按 1/(1+MAE) 计）</p>${table(['网点','入选模型','回测MAE','MAPE','可信度','校正分担权重'],credRows)}<h3>调整前后 / 每日网点合计=区域</h3><p class="eyebrow">${gapNote}</p>${table(dayHead,dayRows)}<p class="notice">${esc(rec.rule)}</p>`;
}
export function render(){
 let list=state.regions.map(r=>`<button class="study" data-region-select="${r.id}">#${r.id} ${esc(r.name)} · ${r.members.length}网点 · ${r.runs.length}版本</button>`).join('')||'<p>暂无区域。先在右侧选择网点建组。</p>';
 let region=state.regions.find(r=>r.id===state.regionSelected)||state.regions[0];
 let runs=region?region.runs.map(v=>`<button class="study" data-region-run="${v.id}">#${v.id} v${v.version} ${esc(v.week)} · ${esc(st(v.state))}${v.published_at?' · 已发布':''}${v.superseded_by?' · 已被替换':''}</button>`).join('')||'<p>该区域还没有版本，提交计算后由后台冻结成员日量。</p>':'';
 let selected=runOf();
 let detail=selected?`<div class="result-head"><h2>区域版本 #${selected.id} v${selected.version} ${badge(st(selected.state))}</h2><button id="region-refresh">刷新状态</button></div>
 <p class="eyebrow">${esc(selected.region_name)} / ${esc(selected.week)} / 冻结窗口 ${selected.result?.frozen?esc(selected.result.frozen.window[0])+'~'+esc(selected.result.frozen.window[1])+' · '+selected.result.frozen.days+'天':'—'} / 回测${selected.backtest_days}日</p>
 ${selected.error?`<p class="notice">${esc(selected.error)}</p>`:''}
 <h3>成员计算状态</h3>${table(['网点','入选模型','状态','回测MAE','错误'],memberRows(selected))}
 ${selected.state==='done'?basisTables(selected):'<p class="notice">待算或失败状态不能发布。失败时整组保留为同一版本，补录后点重试，不会新建组。</p>'}
 <div class="actions">${state.user.role!=='viewer'&&selected.state==='done'&&!selected.published_at?`<button class="primary" data-region-publish="${selected.id}">发布本周区域版本</button>`:''}${state.user.role!=='viewer'&&selected.state==='failed'?`<button data-region-retry="${selected.id}">重试同一组</button>`:''}<button data-nav="4">查看排班建议</button></div>`:'<p>选择一个版本查看冻结、回测、调整前后和分担依据。</p>';
 return `<div class="split"><section class="panel"><h2>区域协调版本</h2><p class="notice">冻结区域成员同日期日量后聚合回测；区域和网点分别按各自回测误差形成可信度，再把未来7日非负整数需求协调到每日网点之和等于区域。任一网点失败整组不发布；重试沿用同一组。</p><h3>区域</h3>${list}<h3>版本</h3>${runs}</section><aside class="side"><h2>新建区域</h2><form id="region">${field('区域名称','name','text','required minlength=2 maxlength=60 value="川东片区"')}<label>区域说明<textarea name="note" rows="3"></textarea></label><div class="checks">${BRANCHES.map(b=>`<label class="check"><input type="checkbox" name="members" value="${esc(b)}" ${['川北','川南','东河','西浦'].includes(b)?'checked':''}>${esc(b)}</label>`).join('')}</div><button class="primary">建立区域</button></form>${region?`<h2>调整成员</h2><form id="region-members"><input type="hidden" name="region_id" value="${region.id}"><div class="checks">${BRANCHES.map(b=>`<label class="check"><input type="checkbox" name="members" value="${esc(b)}" ${region.members.includes(b)?'checked':''}>${esc(b)}</label>`).join('')}</div><button>保存成员</button></form>`:''}<h2>提交计算</h2><form id="region-run">${region?`<input type="hidden" name="region_id" value="${region.id}"><p class="eyebrow">当前区域：${esc(region.name)}</p>`:''}${field('回测天数（7–21）','backtest_days','number','required min=7 max=21 value=14')}${field('Holt α','alpha','number','required min=0.01 max=0.99 step=0.01 value=0.6')}${field('Holt β','beta','number','required min=0.01 max=0.99 step=0.01 value=0.2')}${field('单人日容量（排班换算）','capacity','number','required min=1 max=1000 value=12')}<button class="primary" ${region?'':'disabled'}>冻结并计算</button></form></aside></div><section class="panel">${detail}</section>`}
