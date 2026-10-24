
'use strict';
const data=JSON.parse(document.getElementById('report-data').textContent);
const assetUrl=(key)=>data.sources[key]||key;
const el=(id)=>document.getElementById(id);
const escapeText=(v)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,n=5)=>v===''||v==null?'—':Number(v).toFixed(n);
const pair=(r,m)=>num(r[m+'_mean'])+' ± '+num(r[m+'_sd']);
const tableHtml=(rows)=>{if(!rows.length)return '<p>此状态无对应条目。</p>';const keys=Object.keys(rows[0]);return '<div class="scroll"><table><thead><tr>'+keys.map(k=>'<th>'+escapeText(k)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>'<td>'+escapeText(r[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';};
data.conditions.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.label;el('condition').append(o);});
el('condition').value='bistro-exterior-static';
function setFrames(wanted){const c=data.conditions.find(c=>c.id===el('condition').value);el('frame').innerHTML='';c.frames.forEach(f=>{const o=document.createElement('option');o.value=f;o.textContent='Frame '+f;el('frame').append(o);});if(c.frames.includes(Number(wanted)))el('frame').value=wanted;update();}
function update(){
 const c=data.conditions.find(c=>c.id===el('condition').value),f=Number(el('frame').value),reg=el('region').value;
 const phase=f===128?'static-final':'frame-'+f; const stem='frame-'+String(f).padStart(4,'0');
 if(f===128&&el('view').value==='trmae')el('view').value='rendered';
 el('view').querySelector('option[value="trmae"]').disabled=f===128;
 const view=el('view').value,base='images/pdf/'+c.id+'/',bistro=c.id.startsWith('bistro');
 const range=f===128?'41–128':f===32?'1–32':f===48?'33–64':'65–96';
 const timing=f===128?'静态画质 frame 128':'空间画质 frame '+f+'；局部 TRMAE '+(f-1)+'→'+f;
 el('selection-note').textContent=c.label+' · '+timing+' · 图片 seed 1 · '+(bistro?'固定 262,144 local samples 单流参考，精度未评估':'独立双流参考，通过原精度验收')+'。';
 let srcs=[];
 if(view==='rendered'){
  const ims=['reference','pdf-off','pdf-on'].map(m=>{const src=base+(reg==='full'?'frames/':'rois/'+reg+'/')+m+'/'+stem+'.png';srcs.push(src);return '<figure><figcaption>'+({reference:'Reference','pdf-off':'PDF off','pdf-on':'PDF on'}[m])+'</figcaption><a href="'+assetUrl(src)+'" target="_blank"><img src="'+assetUrl(src)+'" alt="'+escapeText(c.label+' '+reg+' '+m+' '+stem)+'"></a></figure>';});
  el('images').innerHTML='<div class="triplet">'+ims.join('')+'</div>';
 }else{const src=base+(reg==='full'?'panels/':'rois/'+reg+'/')+stem+'-'+view+'.png';srcs=[src];el('images').innerHTML='<a href="'+assetUrl(src)+'" target="_blank"><img class="panel" src="'+assetUrl(src)+'" alt="'+escapeText(c.label+' '+reg+' '+view+' '+stem)+'"></a>';}
 el('source-note').textContent='原文件：'+srcs.map(s=>data.sources[s]||s).join('  /  ');
 const s=c.summary.filter(r=>r.phase===phase&&r.region===reg),off=s.find(r=>r.method==='pdf-off'),on=s.find(r=>r.method==='pdf-on');
 const paired=c.paired.find(r=>r.phase===phase&&r.region===reg);
 const metrics=[['smape','SMAPE (%)'],['rmae','RGB RMAE'],['nrmse','NRMSE'],['trmae','局部 TRMAE'],['gpu_ms','GPU total (ms)'],['initial_ms','GPU initial (ms)'],['spatial_ms','GPU spatial (ms)']];
 el('metrics').innerHTML=off&&on?'<div class="scroll"><table><thead><tr><th>指标</th><th>PDF off · 均值 ± SD</th><th>PDF on · 均值 ± SD</th><th>配对差值 on − off · 均值 ± SD</th><th>配对相对变化 (%)</th></tr></thead><tbody>'+metrics.filter(([m])=>off[m+'_mean']!=='').map(([m,label])=>'<tr><td>'+label+'</td><td title="'+escapeText(off[m+'_mean'])+'">'+pair(off,m)+'</td><td title="'+escapeText(on[m+'_mean'])+'">'+pair(on,m)+'</td><td class="'+(Number(paired?.[m+'_mean'])<0?'delta-neg':'delta-pos')+'">'+(paired?pair(paired,m):'—')+'</td><td>'+(paired?num(paired[m+'_relative_percent_mean'],3):'—')+'</td></tr>').join('')+'</tbody></table></div>':'<p>无对应统计。</p>';
 el('table-note').textContent='n=3 独立方法种子。GPU 均值来自完整 '+range+' 帧段；GPU 值不是 ROI 的局部耗时。负差值表示误差或耗时更低。百分比先逐 seed 配对计算，再求均值。'+(view==='smape'?' SMAPE 图固定0–100%色标。':view==='signed_relative'?' 残差图固定−50%至+50%显示范围；单帧残差不能证明偏差。':view==='trmae'?' TRMAE 只涵盖标出的相邻帧对。':'');
 el('csv-link').innerHTML='<a href="'+c.csv.summary+'">当前条件均值与 SD</a> · <a href="'+c.csv.paired+'">配对差值</a> · <a href="'+c.csv.seeds+'">种子级指标</a>';
 el('seed-table').innerHTML=tableHtml(c.seeds.filter(r=>r.phase===phase&&r.region===reg));
}
el('condition').addEventListener('change',()=>setFrames());['frame','region','view'].forEach(k=>el(k).addEventListener('change',update));
const overviewHead=['条件 / 帧','SMAPE off / on (%)','配对 SMAPE 变化 (%)','RMAE off / on','局部 TRMAE off / on','GPU off / on (ms)','配对 GPU 变化 (%)',''];
el('overview-table').innerHTML='<div class="scroll"><table><thead><tr>'+overviewHead.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+data.overview.map(r=>'<tr><td>'+escapeText(data.conditions.find(c=>c.id===r.condition)?.label||r.condition)+' / '+r.representative_frame+'</td><td>'+num(r.smape_off_mean,3)+' / '+num(r.smape_on_mean,3)+'</td><td>'+num(r.smape_paired_relative_percent_mean,2)+'</td><td>'+num(r.rmae_off_mean,5)+' / '+num(r.rmae_on_mean,5)+'</td><td>'+num(r.trmae_off_mean,5)+' / '+num(r.trmae_on_mean,5)+'</td><td>'+num(r.gpu_ms_off_mean,3)+' / '+num(r.gpu_ms_on_mean,3)+'</td><td>'+num(r.gpu_ms_paired_relative_percent_mean,2)+'</td><td><button class="jump" data-condition="'+r.condition+'" data-frame="'+r.representative_frame+'">对照</button></td></tr>').join('')+'</tbody></table></div>';
document.querySelectorAll('.jump').forEach(b=>b.addEventListener('click',()=>{el('condition').value=b.dataset.condition;el('region').value='full';el('view').value='rendered';setFrames(b.dataset.frame);el('compare').scrollIntoView({behavior:'smooth'});}));
setFrames();
