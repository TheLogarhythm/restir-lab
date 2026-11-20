// Verify source-derived Marp slides and the exact clips pinned by current-media.json.
const fs = require('fs');
const os = require('os');
const path = require('path');
const {execFileSync} = require('child_process');
const {pathToFileURL} = require('url');
const {createRequire} = require('module');
const root = path.resolve(__dirname, '..');
const repo = path.resolve(root, '../..');
const staticOnly = process.argv.includes('--static');

function marpPackage() {
  const candidates = [];
  if (process.env.MARP_CLI_PATH) {
    let dir = path.resolve(process.env.MARP_CLI_PATH);
    if (fs.existsSync(dir) && fs.statSync(dir).isFile()) dir = path.dirname(dir);
    candidates.push(path.join(dir, 'package.json'));
  }
  for (const dir of [repo, root]) candidates.push(path.join(dir, 'node_modules/@marp-team/marp-cli/package.json'));
  const caches = [process.env.npm_config_cache,
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'npm-cache'), path.join(os.homedir(), '.npm')].filter(Boolean);
  for (const cache of caches) {
    const npx = path.join(cache, '_npx');
    if (!fs.existsSync(npx)) continue;
    for (const dir of fs.readdirSync(npx).sort()) candidates.push(path.join(npx, dir, 'node_modules/@marp-team/marp-cli/package.json'));
  }
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && JSON.parse(fs.readFileSync(candidate, 'utf8')).version === '4.5.1') return candidate;
  }
  throw Error('Install @marp-team/marp-cli@4.5.1 locally or set MARP_CLI_PATH to its installed CLI; no download is performed.');
}

function presentationInputs() {
  const localPython = path.join(repo, 'build/falcor/verify-env', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const python = process.env.PRESENTATION_PYTHON || (fs.existsSync(localPython) ? localPython : 'python');
  return JSON.parse(execFileSync(python, ['-B', path.join(__dirname, 'build_media.py'), '--describe'], {encoding: 'utf8'}));
}

function browserExecutable() {
  const candidates = [process.env.CHROME_PATH, process.env.PUPPETEER_EXECUTABLE_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  return candidates.find(candidate => fs.existsSync(candidate));
}

(async () => {
  const inputs = presentationInputs();
  const puppeteer = createRequire(marpPackage())('puppeteer-core');
  const executablePath = browserExecutable();
  if (!executablePath) throw Error('Set CHROME_PATH to an installed Chrome/Chromium browser.');
  const browser = await puppeteer.launch({executablePath, headless: true, args: ['--allow-file-access-from-files']});
  const results = {renderer: 'Chrome / Puppeteer', current_media_index: inputs.current_media_index,
    screenshots: [], slides: [], videos: [], errors: []};
  fs.mkdirSync(path.join(root, 'build'), {recursive: true});
  try {
    const page = await browser.newPage();
    await page.setViewport({width: 1920, height: 1080, deviceScaleFactor: 1});
    page.on('pageerror', error => results.errors.push(error.message));
    for (const {deck, slides: count} of inputs.decks) {
      if (staticOnly && deck !== 'final') continue;
      await page.goto(pathToFileURL(path.join(root, deck + '.html')).href, {waitUntil: 'load'});
      await page.addStyleTag({content: '.bespoke-marp-osc {display:none!important;}'});
      const actualCount = await page.evaluate(() => document.querySelectorAll('svg.bespoke-marp-slide').length);
      if (actualCount !== count) results.errors.push(`${deck}: HTML has ${actualCount} slides, source has ${count}`);
      for (let i = 1; i <= count; i++) {
        const expectedVideos = inputs.videos.filter(video => video.deck === deck && video.slide === i);
        if (staticOnly && expectedVideos.length) continue;
        await page.evaluate(number => { location.hash = '#' + number; }, i);
        await page.waitForFunction(number => {
          const all = [...document.querySelectorAll('svg.bespoke-marp-slide')];
          return all[number - 1] && all[number - 1].classList.contains('bespoke-marp-active');
        }, {}, i);
        await new Promise(resolve => setTimeout(resolve, 350));
        const layout = await page.evaluate(() => {
          const slide = document.querySelector('.bespoke-marp-active section');
          const bounds = slide.getBoundingClientRect();
          const overflow = [];
          for (const element of slide.querySelectorAll('h1,h2,h3,p,li,figure,img,table,video')) {
            if (getComputedStyle(element).display === 'none') continue;
            const rect = element.getBoundingClientRect();
            if (rect.width && (rect.left < bounds.left - 2 || rect.right > bounds.right + 2 || rect.top < bounds.top - 2 || rect.bottom > bounds.bottom + 2)) {
              overflow.push({tag: element.tagName, text: element.textContent.slice(0, 100), rect: [rect.left, rect.top, rect.right, rect.bottom]});
            }
          }
          const images = [...slide.querySelectorAll('img')].map(element => ({src: element.getAttribute('src'), loaded: element.complete && element.naturalWidth > 0}));
          const videos = [...slide.querySelectorAll('video')].map(element => ({src: element.src, poster: element.poster}));
          return {bounds: [bounds.width, bounds.height], overflow, images, videos};
        });
        if (layout.overflow.length) results.errors.push(`${deck} slide ${i}: out-of-slide elements`);
        if (layout.images.some(image => !image.loaded)) results.errors.push(`${deck} slide ${i}: broken image`);
        const expectedPaths = expectedVideos.map(video => pathToFileURL(video.path).href).sort();
        const actualPaths = layout.videos.map(video => video.src).sort();
        if (JSON.stringify(expectedPaths) !== JSON.stringify(actualPaths)) results.errors.push(`${deck} slide ${i}: video references differ from current source/index`);
        for (const video of expectedVideos) {
          if (!layout.videos.some(actual => actual.src === pathToFileURL(video.path).href && actual.poster === pathToFileURL(video.poster).href)) {
            results.errors.push(`${deck} slide ${i}: video/poster pair differs from current index`);
          }
        }
        results.slides.push({deck, slide: i, ...layout});
        if (expectedVideos.length) {
          await page.waitForFunction(() => {
            const videos = [...document.querySelectorAll('.bespoke-marp-active video')];
            return videos.length && videos.every(video => video.readyState >= 2 && !video.paused && video.currentTime > 0.1);
          }, {timeout: 30000});
          const state = await page.evaluate(() => [...document.querySelectorAll('video')].map(video => ({
            src: video.src, paused: video.paused, time: video.currentTime, rate: video.playbackRate,
            error: video.error?.message || null, width: video.videoWidth, height: video.videoHeight, duration: video.duration, loop: video.loop
          })));
          if (state.filter(video => !video.paused).length !== expectedVideos.length) results.errors.push(`${deck} slide ${i}: hidden video playing`);
          if (state.some(video => video.rate !== 1 || video.error)) results.errors.push(`${deck} slide ${i}: invalid video rate or error`);
          for (const expected of expectedVideos) {
            const active = state.find(video => video.src === pathToFileURL(expected.path).href);
            if (!active || active.width !== 1920 || active.height !== 1080 || active.duration !== expected.duration || active.loop) results.errors.push(`${deck} slide ${i}: unexpected video dimensions/duration`);
          }
          results.videos.push({deck, slide: i, clips: expectedVideos.length, state});
          await page.evaluate(() => { for (const video of document.querySelectorAll('.bespoke-marp-active video')) { video.pause(); video.currentTime = 0; } });
          await new Promise(resolve => setTimeout(resolve, 250));
        }
        const out = path.join(root, 'build', `${deck}.${String(i).padStart(3, '0')}.png`);
        await page.screenshot({path: out});
        results.screenshots.push(path.relative(root, out).replaceAll('\\', '/'));
      }
    }
    const checks = results.videos.reduce((total, video) => total + video.clips, 0);
    if (!staticOnly && checks !== inputs.videos.length) results.errors.push(`Expected ${inputs.videos.length} current video checks, got ${checks}`);
    const out = path.join(root, 'build', staticOnly ? 'browser-static.json' : 'browser-verification.json');
    fs.writeFileSync(out, JSON.stringify(results, null, 2) + '\n');
    console.log(JSON.stringify({slides: results.slides.length, video_checks: checks, errors: results.errors}));
    if (results.errors.length) process.exitCode = 1;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });