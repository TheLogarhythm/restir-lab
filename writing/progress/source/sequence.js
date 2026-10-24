/* Display only complete pairs of decoded frames. The archive PNGs are the
   authoritative pause/inspection path; videos are presentation derivatives. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const FPS = 30, LAST = 96;
  const canvas = $('video-canvas'), ctx = canvas.getContext('2d', {alpha:false});
  const videos = {off:$('method-off'), on:$('method-on')};
  const queues = {off:new Map(), on:new Map()};
  let pair = null, frame = 1, split = 50, playing = false, raw = false;
  let generation = 0, seeking = false, seekTimer = 0, dragging = false;
  let callbacks = {off:null, on:null};
  const sourceBase = () => '../../runs/pdf-similarity-archive/artifacts/raw/'+$('video-scene').value+'/frames/';
  const framePath = (method, n) => sourceBase()+'pdf-'+method+'/frame-'+String(n).padStart(4,'0')+'.png';
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const boundary = y => (split / 100 * 1.26 - .13 + .12 - .24 * y / 1080) * 1920;

  function render() {
    if (!pair) return;
    ctx.drawImage(pair.off,0,0,1920,1080);
    ctx.save();ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(boundary(0),0);
    ctx.lineTo(boundary(1080),1080);ctx.lineTo(0,1080);ctx.closePath();ctx.clip();
    ctx.drawImage(pair.on,0,0,1920,1080);ctx.restore();
    ctx.beginPath();ctx.moveTo(boundary(0),0);ctx.lineTo(boundary(1080),1080);
    ctx.strokeStyle='#fff';ctx.lineWidth=3.2;ctx.stroke();
    $('divider-handle').style.left=clamp(boundary(540)/1920*100,1.5,98.5)+'%';
    $('divider-handle').setAttribute('aria-valuenow',String(Math.round(split)));
    $('tag-on').hidden=boundary(70)<220;$('tag-off').hidden=boundary(70)>1700;
  }
  function position(n) {
    frame=clamp(n,1,LAST);$('video-frame').value=String(frame);
    const phase=frame<=32?'Hold':frame<=64?($('video-scene').value==='bistro-lighting'?'Lighting change':'Motion'):'Stop/hold';
    $('video-position').textContent=String(frame).padStart(2,'0')+' / 96 · '+phase;
    $('png-on').href=framePath('on',frame);$('png-off').href=framePath('off',frame);
    $('frame-prev').disabled=frame===1;$('frame-next').disabled=frame===LAST;
    canvas.dataset.frame=String(frame);canvas.dataset.mode=raw?'original-png':'video';
  }
  function snapshot(v) {
    const c=document.createElement('canvas');c.width=1920;c.height=1080;
    c.getContext('2d',{alpha:false}).drawImage(v,0,0);return c;
  }
  function stop() {
    clearTimeout(seekTimer);seekTimer=0;
    playing=false;Object.values(videos).forEach(v=>v.pause());$('video-play').textContent='Play';
  }
  function clearQueues() {queues.off.clear();queues.on.clear();}
  function fail(error) {
    stop();seeking=false;$('video-loading').hidden=true;
    $('video-error').textContent=error.message||String(error);
  }
  function watch(id) {
    const video=videos[id];
    if (callbacks[id]!==null && video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(callbacks[id]);
    const capture=(_now,metadata) => {
      if(playing&&!seeking) {
        const n=clamp(Math.round(metadata.mediaTime*FPS)+1,1,LAST);
        queues[id].set(n,snapshot(video));
        while(queues[id].size>6) queues[id].delete(queues[id].keys().next().value);
        const common=[...queues.off.keys()].filter(f=>queues.on.has(f)&&f>=frame);
        if(common.length) {
          const next=Math.max(...common);pair={off:queues.off.get(next),on:queues.on.get(next)};
          position(next);render();
          for(const q of Object.values(queues)) for(const key of q.keys()) if(key<next)q.delete(key);
        }
        if(id==='off'&&Math.abs(videos.on.currentTime-video.currentTime)>1.5/FPS&&!videos.on.seeking) {
          videos.on.currentTime=video.currentTime;
        }
      }
      callbacks[id]=video.requestVideoFrameCallback(capture);
    };
    if(video.requestVideoFrameCallback) callbacks[id]=video.requestVideoFrameCallback(capture);
    else fail(new Error('Use a recent version of Chrome or Edge with synchronized frame callback support. Original PNG inspection remains available.'));
  }
  function event(video, name, action) {
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>done(new Error('Video loading timed out. Check the local media files.')),12000);
      const good=()=>done(),bad=()=>done(new Error('Cannot read the video. Run tools/build.ps1 -Media to build the media.'));
      function done(error){clearTimeout(timer);video.removeEventListener(name,good);video.removeEventListener('error',bad);error?reject(error):resolve();}
      video.addEventListener(name,good,{once:true});video.addEventListener('error',bad,{once:true});
      try{action();}catch(e){done(e);}
    });
  }
  const image = src => new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('Original PNGs are unavailable. Keep runs/pdf-similarity-archive in the repository.'));im.src=src;});
  async function seek(n, useRaw=raw) {
    const token=++generation;stop();seeking=true;raw=useRaw;
    clearQueues();$('video-loading').hidden=false;$('video-error').textContent='';
    try {
      n=clamp(Number(n),1,LAST);
      let loaded;
      if(useRaw) loaded=await Promise.all(['off','on'].map(id=>image(framePath(id,n))));
      else {
        const time=(n-1+.15)/FPS;
        await Promise.all(Object.values(videos).map(v=>Math.abs(v.currentTime-time)<.0001&&v.readyState>=2?Promise.resolve():event(v,'seeked',()=>{v.currentTime=time;})));
        if(token!==generation)return;
        loaded=[snapshot(videos.off),snapshot(videos.on)];
      }
      if(token!==generation)return;
      pair={off:loaded[0],on:loaded[1]};position(n);render();
      $('preview-kind').textContent=useRaw?'Original PNGs · Same frame · seed 1':'Video preview · seed 1';
      $('show-original').textContent=useRaw?'Return to video frame':'Inspect original PNGs';
      $('video-loading').hidden=true;seeking=false;$('video-play').disabled=false;
      $('video-frame').disabled=false;$('show-original').disabled=false;
      return token;
    } catch(e) {if(token===generation)fail(e);}
  }
  async function play() {
    if(seeking)return;
    if(frame===LAST||raw) {const token=await seek(frame===LAST?1:frame,false);if(token!==generation)return;}
    if(seeking||$('video-error').textContent)return;
    raw=false;clearQueues();playing=true;$('video-play').textContent='Pause';
    try{await Promise.all(Object.values(videos).map(v=>v.play()));}catch(e){if(playing)fail(e);}
  }
  async function loadScene(wanted=1) {
    const token=++generation;stop();seeking=true;pair=null;clearQueues();
    ctx.fillStyle='#10191f';ctx.fillRect(0,0,1920,1080);
    $('video-play').disabled=true;$('video-loading').hidden=false;$('video-error').textContent='';
    $('video-frame').disabled=true;$('show-original').disabled=true;$('frame-prev').disabled=true;$('frame-next').disabled=true;
    const base='assets/videos/'+$('video-scene').value+'/';
    $('download-comparison').href=base+'comparison.mp4';
    try {
      await Promise.all(Object.entries(videos).map(([id,v])=>event(v,'loadeddata',()=>{v.src=base+'pdf-'+id+'.mp4';v.load();})));
      if(token!==generation)return;
      Object.values(videos).forEach(v=>{v.playbackRate=Number($('video-rate').value);});
      watch('off');watch('on');await seek(wanted,false);
    } catch(e){if(token===generation)fail(e);}
  }
  function setSplit(value) {split=clamp(Number(value),0,100);$('video-split').value=String(split);render();}
  function drag(event) {
    const box=$('video-stage').getBoundingClientRect();
    const x=(event.clientX-box.left)/box.width,y=(event.clientY-box.top)/box.height;
    setSplit((x+.01+.24*y)/1.26*100);
  }
  $('video-stage').addEventListener('pointerdown',e=>{dragging=true;e.currentTarget.setPointerCapture(e.pointerId);drag(e);});
  $('video-stage').addEventListener('pointermove',e=>{if(dragging)drag(e);});
  $('video-stage').addEventListener('pointerup',()=>{dragging=false;});
  $('video-stage').addEventListener('pointercancel',()=>{dragging=false;});
  $('divider-handle').addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();setSplit(e.key==='Home'?0:e.key==='End'?100:split+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?10:1));}});
  $('video-split').oninput=e=>setSplit(e.target.value);
  $('video-frame').oninput=e=>{const n=e.target.value;stop();clearTimeout(seekTimer);seekTimer=setTimeout(()=>seek(n),50);};
  $('frame-prev').onclick=()=>seek(frame-1);$('frame-next').onclick=()=>seek(frame+1);
  $('video-play').onclick=()=>playing?stop():play();
  $('show-original').onclick=()=>seek(frame,!raw);
  $('video-scene').onchange=()=>loadScene();
  $('video-rate').onchange=()=>Object.values(videos).forEach(v=>{v.playbackRate=Number($('video-rate').value);});
  $('video-fullscreen').onclick=()=>document.fullscreenElement?document.exitFullscreen():$('video-player').requestFullscreen();
  videos.off.addEventListener('ended',async()=>{
    if(!playing)return;stop();
    const end=await seek(LAST,false);if(end!==generation)return;
    if($('video-loop').checked){const start=await seek(1,false);if(start===generation)play();}
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  const query=new URLSearchParams(location.search),scene=query.get('scene');
  if([...$('video-scene').options].some(o=>o.value===scene))$('video-scene').value=scene;
  loadScene(clamp(Number(query.get('frame'))||1,1,LAST));
})();
