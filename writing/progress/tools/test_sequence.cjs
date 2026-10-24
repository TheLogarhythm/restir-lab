/* Deterministic unit checks for the real viewer controller. No browser or
   external UI is controlled here. Decode events are intentionally reordered. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
  constructor(id){this.id=id;this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.style={};this.dataset={};this.listeners={};this.checked=false;this.attrs={};}
  addEventListener(name,fn,options={}){(this.listeners[name]??=[]).push({fn,once:options.once});}
  removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(x=>x.fn!==fn);}
  fire(name,event={}){for(const listener of [...this.listeners[name]||[]]){if(listener.once)this.removeEventListener(name,listener.fn);listener.fn({...event,currentTarget:this});}}
  setAttribute(name,value){this.attrs[name]=value;}
  getBoundingClientRect(){return {left:0,top:0,width:1920,height:1080};}
  setPointerCapture(){}
}
class Canvas extends Element {
  constructor(id){super(id);this.draws=[];this.lines=[];this.c={
    drawImage:(im)=>{this.imageFrame=im.imageFrame??Math.floor((im.currentTime||0)*30)+1;this.imageId=im.imageId||im.id;this.draws.push([this.imageId,this.imageFrame]);},
    moveTo:(...p)=>this.lines.push(p),lineTo:(...p)=>this.lines.push(p),save(){},restore(){},beginPath(){},closePath(){},clip(){},stroke(){},fillRect(){}};}
  getContext(){return this.c;}
}
class Video extends Element {
  constructor(id){super(id);this._time=0;this.readyState=3;this.paused=true;this.seeking=false;this.cb=null;}
  set currentTime(t){this._time=t;setImmediate(()=>this.fire('seeked'));}
  get currentTime(){return this._time;}
  load(){setImmediate(()=>this.fire('loadeddata'));}
  play(){this.paused=false;return Promise.resolve();}
  pause(){this.paused=true;}
  requestVideoFrameCallback(cb){this.cb=cb;return 1;}
  cancelVideoFrameCallback(){this.cb=null;}
  decode(n){this._time=(n-1)/30;const cb=this.cb;this.cb=null;cb?.(0,{mediaTime:this._time});}
}
const ids=['video-canvas','method-off','method-on','video-scene','video-rate','video-loop','video-stage','divider-handle','tag-on','tag-off','video-frame','video-position','png-on','png-off','frame-prev','frame-next','video-play','video-loading','video-error','preview-kind','show-original','download-comparison','video-split','video-fullscreen','video-player'];
const elements=Object.fromEntries(ids.map(id=>[id,id==='video-canvas'?new Canvas(id):id.startsWith('method-')?new Video(id):new Element(id)]));
elements['video-scene'].value='arcade-motion';elements['video-scene'].options=[{value:'arcade-motion'},{value:'bistro-lighting'}];
elements['video-rate'].value='1';elements['video-loop'].checked=false;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const flush=async()=>{for(let i=0;i<8;i++)await tick();};
const document={getElementById:id=>elements[id],createElement:tag=>new Canvas(tag),addEventListener(){},hidden:false};
class Image {set src(value){this.imageId=value.includes('pdf-on')?'original-on':'original-off';this.imageFrame=Number(value.match(/frame-(\d+)/)[1]);setImmediate(()=>this.onload());}}
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../source/sequence.js'),'utf8'),{document,Image,URLSearchParams,location:{search:''},setTimeout,clearTimeout,console});
(async()=>{
  await flush();const c=elements['video-canvas'];
  assert.equal(c.dataset.frame,'1');assert.equal(elements['video-play'].disabled,false);
  await elements['video-play'].onclick();
  elements['method-off'].decode(10);assert.equal(c.dataset.frame,'1','Unpaired off must not be displayed');
  elements['method-on'].decode(10);assert.equal(c.dataset.frame,'10');
  assert.deepEqual(c.draws.slice(-2).map(x=>x[1]),[10,10]);
  elements['method-on'].decode(12);elements['method-off'].decode(11);assert.equal(c.dataset.frame,'10');
  elements['method-off'].decode(12);assert.equal(c.dataset.frame,'12');
  assert.deepEqual(c.draws.slice(-2).map(x=>x[1]),[12,12]);
  elements['video-split'].oninput({target:{value:'50'}});
  assert(c.lines.at(-2)[0]>c.lines.at(-1)[0], 'Top must be right of bottom: /');
  elements['video-split'].oninput({target:{value:'0'}});assert(c.lines.at(-2)[0]<0&&c.lines.at(-1)[0]<0);
  elements['video-split'].oninput({target:{value:'100'}});assert(c.lines.at(-2)[0]>1920&&c.lines.at(-1)[0]>1920);
  await elements['show-original'].onclick();await flush();
  assert.equal(c.dataset.mode,'original-png');assert.equal(c.dataset.frame,'12');
  assert.deepEqual(c.draws.slice(-2).map(x=>x[0]),['original-off','original-on']);
  elements['frame-next'].onclick();elements['frame-next'].onclick();await flush();
  assert.equal(c.dataset.frame,'13','Latest seek must win without mixing frames');
  elements['video-scene'].value='bistro-lighting';elements['video-scene'].onchange();await flush();
  assert.equal(c.dataset.frame,'1');assert.equal(c.dataset.mode,'video');
  assert(elements['png-on'].href.includes('bistro-lighting'));
  elements['video-frame'].oninput({target:{value:'96'}});
  elements['video-scene'].value='arcade-motion';elements['video-scene'].onchange();await flush();
  await new Promise(resolve=>setTimeout(resolve,65));await flush();
  assert.equal(c.dataset.frame,'1','A queued seek from the previous scene must be canceled');
  await elements['video-play'].onclick();elements['video-loop'].checked=true;
  elements['method-off'].fire('ended');
  elements['video-scene'].value='bistro-lighting';elements['video-scene'].onchange();await flush();
  assert.equal(c.dataset.frame,'1');assert.equal(elements['method-off'].paused,true,'Old loop must not restart a newly selected scene');
  elements['divider-handle'].fire('keydown',{key:'Home',preventDefault(){}});assert.equal(elements['divider-handle'].attrs['aria-valuenow'],'0');
  elements['divider-handle'].fire('keydown',{key:'End',preventDefault(){}});assert.equal(elements['divider-handle'].attrs['aria-valuenow'],'100');
  console.log('PASS: matched decode pairs, dropped/reordered callbacks, slash geometry/endpoints, raw PNG inspection, seeking, scene changes, keyboard control.');
})().catch(e=>{console.error(e);process.exitCode=1;});
