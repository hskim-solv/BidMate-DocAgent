#!/usr/bin/env node
/**
 * Playwright headless UI smoke for the Streamlit demo (issue #1790).
 *
 * Boots `streamlit run demo/streamlit_app.py` on :8501, waits for the
 * Streamlit health endpoint, then asserts the reviewer-facing surface:
 *   - page <title> contains "BidMate-DocAgent"
 *   - the H1 heading renders
 *   - the three headline pipeline presets are listed (naive_baseline,
 *     agentic_full, agentic_full_llm) — see rag_pipeline_presets.pipeline_cli_choices
 *   - the "Run query" primary button is present (proves the main pane rendered,
 *     which only happens if the sidebar's get_index() succeeded first)
 * Saves a full-page screenshot to reports/ui_smoke/demo.png.
 *
 * Exit 0 = all assertions passed; 1 = streamlit failed to boot or an
 * assertion failed (the screenshot + the last streamlit log are still emitted).
 *
 * Requires: `npm install` (playwright) + `npx playwright install chromium`,
 * the chroma backend deps (chromadb, in requirements.txt), and a prebuilt
 * index at data/index/ (run `make index` first).
 * Run via `make ui-smoke`.
 */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { mkdirSync } from 'node:fs';

const PORT = Number(process.env.UI_SMOKE_PORT || 8501);
const BASE = `http://localhost:${PORT}`;
const PY = process.env.PYTHON || 'python3';
const ART_DIR = 'reports/ui_smoke';
const SHOT = `${ART_DIR}/demo.png`;
const BOOT_TIMEOUT_MS = 180_000;

mkdirSync(ART_DIR, { recursive: true });

let slLog = '';
const streamlit = spawn(
  PY,
  ['-m', 'streamlit', 'run', 'demo/streamlit_app.py',
    '--server.headless', 'true',
    '--server.port', String(PORT),
    '--server.fileWatcherType', 'none',
    '--browser.gatherUsageStats', 'false'],
  {
    // Inherit env with NO BIDMATE_INDEX_BACKEND override, so the demo boots its
    // real default index backend — chroma (ADR 0081). The smoke exercises the
    // actual deployed path; chromadb is required (it's in requirements.txt). Set
    // BIDMATE_INDEX_BACKEND in the environment to smoke a different backend.
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: true,
  },
);
streamlit.stdout.on('data', (d) => { slLog += d.toString(); });
streamlit.stderr.on('data', (d) => { slLog += d.toString(); });

function shutdown(code) {
  // detached:true → kill the whole process group (streamlit spawns children).
  try { process.kill(-streamlit.pid, 'SIGKILL'); } catch { /* already gone */ }
  try { streamlit.kill('SIGKILL'); } catch { /* already gone */ }
  process.exit(code);
}
process.on('SIGINT', () => shutdown(130));
process.on('SIGTERM', () => shutdown(143));

async function waitForHealth(deadlineMs) {
  const end = Date.now() + deadlineMs;
  while (Date.now() < end) {
    if (streamlit.exitCode !== null) return false; // process died early
    try {
      const r = await fetch(`${BASE}/_stcore/health`);
      if (r.ok) return true;
    } catch { /* not up yet */ }
    await sleep(1000);
  }
  return false;
}

const checks = [];
async function check(label, locator) {
  try {
    await locator.first().waitFor({ state: 'visible', timeout: 20_000 });
    checks.push([label, true]);
  } catch {
    checks.push([label, false]);
  }
}

(async () => {
  console.log(`[ui-smoke] booting streamlit on ${BASE} …`);
  const ready = await waitForHealth(BOOT_TIMEOUT_MS);
  if (!ready) {
    console.error('[ui-smoke] streamlit did not become healthy in time.');
    console.error('--- last streamlit log ---');
    console.error(slLog.slice(-2000));
    shutdown(1);
  }
  console.log('[ui-smoke] streamlit healthy — launching chromium.');

  const browser = await chromium.launch();
  let exitCode = 0;
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60_000 });

    // Streamlit renders client-side; wait for the H1 before asserting.
    await page.getByRole('heading', { name: /BidMate-DocAgent/ })
      .first().waitFor({ state: 'visible', timeout: 60_000 });

    await check('h1 heading', page.getByRole('heading', { name: /BidMate-DocAgent/ }));
    for (const preset of ['naive_baseline', 'agentic_full', 'agentic_full_llm']) {
      await check(`preset radio: ${preset}`, page.getByText(preset, { exact: true }));
    }
    await check('Run query button', page.getByRole('button', { name: /Run query/ }));

    const title = await page.title();
    checks.push(['page title ~ BidMate-DocAgent', /BidMate-DocAgent/.test(title)]);

    await page.screenshot({ path: SHOT, fullPage: true });
  } catch (err) {
    console.error(`[ui-smoke] unexpected error: ${err?.message || err}`);
    exitCode = 1;
  } finally {
    await browser.close();
  }

  for (const [label, ok] of checks) console.log(`${ok ? '✅' : '❌'} ${label}`);
  console.log(`[ui-smoke] screenshot: ${SHOT}`);
  if (checks.filter(([, ok]) => !ok).length > 0) exitCode = 1;
  if (exitCode === 0) {
    console.log(`[ui-smoke] PASSED — ${checks.length}/${checks.length} assertions.`);
  } else {
    console.error('[ui-smoke] FAILED.');
  }
  shutdown(exitCode);
})();
