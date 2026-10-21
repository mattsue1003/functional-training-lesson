// 用 Chrome 逐格擷取 functional_16x9.html（1920×1080）。
//   node render.js cues                 → build/cues.json（音效時間點）
//   node render.js still 3.5 20 41 ...  → build/still_<秒>.png（檢查用）
//   node render.js frames [workers]     → build/seg_<k>.mp4（無聲畫面，分段平行算圖）
const puppeteer = require('puppeteer-core');
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');

const SFX = '';
const ROOT = __dirname, BUILD = path.join(ROOT, 'build'), SEGS = BUILD;
const PAGE = 'file://' + path.join(ROOT, 'functional_16x9.html') + '?render=1';
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const FF = process.env.FFMPEG || execFileSync('python3', ['-c', 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())']).toString().trim();
const FPS = 30;

async function open() {
  const browser = await puppeteer.launch({executablePath: CHROME, headless: 'new',
    args: ['--allow-file-access-from-files', '--hide-scrollbars', '--force-color-profile=srgb']});
  const page = await browser.newPage();
  await page.setViewport({width: 1920, height: 1080, deviceScaleFactor: 1});
  await page.goto(PAGE, {waitUntil: 'networkidle0'});
  await page.evaluate(async () => {
    await document.fonts.ready;
    // 每個場景先畫一次，讓手寫字型的分段字集都先載入
    for (const s of window.TIMING) { window.render((s.start + s.end) / 2); window.render(s.end - .2); await new Promise(r => setTimeout(r, 30)); }
    await document.fonts.ready; window.render(0);
  });
  return {browser, page};
}

async function main() {
  fs.mkdirSync(SEGS, {recursive: true});
  const [mode, ...rest] = process.argv.slice(2);
  if (mode === 'cues') {
    const {browser, page} = await open();
    const cues = await page.evaluate(() => window.cues());
    fs.writeFileSync(path.join(BUILD, `cues${SFX}.json`), JSON.stringify(cues));
    console.log(cues.length, 'cues');
    await browser.close();
  } else if (mode === 'still') {
    const {browser, page} = await open();
    for (const s of rest) {
      await page.evaluate(t => window.render(t), +s);
      await page.screenshot({path: path.join(BUILD, `still${SFX}_${s}.png`)});
    }
    await browser.close();
  } else if (mode === 'frames') {
    const W = +(rest[0] || 4);
    const {browser: b0, page: p0} = await open();
    const total = await p0.evaluate(() => window.TOTAL);
    await b0.close();
    const N = Math.ceil(total * FPS), per = Math.ceil(N / W);
    console.log(`${N} frames, ${W} workers`);
    const t0 = Date.now();
    await Promise.all([...Array(W)].map(async (_, k) => {
      const a = k * per, b = Math.min(N, a + per);
      if (a >= b) return;
      if (process.env.ONLY != null && +process.env.ONLY !== k) return;   // ONLY=k：只重算第 k 段
      const {browser, page} = await open();
      const out = path.join(SEGS, `seg_${String(k).padStart(2, '0')}.mp4`);
      const ff = spawn(FF, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
        '-vf', 'scale=in_range=pc:out_range=tv', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-r', String(FPS), out], {stdio: ['pipe', 'inherit', 'inherit']});
      for (let f = a; f < b; f++) {
        await page.evaluate(t => window.render(t), f / FPS);
        const buf = await page.screenshot({type: 'jpeg', quality: 93, optimizeForSpeed: true});
        if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
        if (k === 0 && (f - a) % 300 === 0) console.log(`worker0 ${f - a}/${b - a}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
      }
      ff.stdin.end();
      await new Promise(r => ff.on('close', r));
      await browser.close();
    }));
    console.log(`frames done in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
}
main().then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });
