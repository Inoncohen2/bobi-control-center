/**
 * Render `public/icon.svg` to the PNG sizes an installed app needs.
 *
 * There is no image library in this project and there does not need to be:
 * the repository already depends on a browser for its screenshot checks, and a
 * browser is an excellent SVG renderer. Run it when the mark changes:
 *
 *     node scripts/make-icons.mjs
 *
 * The outputs are committed, so a normal build needs neither this script nor a
 * browser.
 */

// `playwright-core` is not a dependency of this project — the outputs are
// committed, so a build never needs it. Point PLAYWRIGHT_CORE at an install
// when you do want to regenerate.
const { chromium } = await import(process.env.PLAYWRIGHT_CORE ?? 'playwright-core');
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const publicDir = resolve(here, '..', 'public');
const svg = readFileSync(resolve(publicDir, 'icon.svg'), 'utf8');

/**
 * `padding` is the maskable safe zone: Android may crop a maskable icon to a
 * circle, so the mark is drawn at 80% and centred on its own background rather
 * than filling the square.
 */
const TARGETS = [
  { file: 'icon-192.png', size: 192, padding: 0 },
  { file: 'icon-512.png', size: 512, padding: 0 },
  { file: 'icon-maskable-512.png', size: 512, padding: 0.1 },
  // iOS does not read the manifest for its home-screen icon, and it does not
  // round corners it was not given, so this one is drawn square and opaque.
  { file: 'apple-touch-icon.png', size: 180, padding: 0 },
];

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium',
});

for (const { file, size, padding } of TARGETS) {
  const inset = Math.round(size * padding);
  const page = await browser.newPage({
    viewport: { width: size, height: size },
    deviceScaleFactor: 1,
  });
  await page.setContent(
    `<!doctype html><style>
       html,body{margin:0;padding:0;background:#4f46e5;}
       svg{display:block;position:absolute;inset:${inset}px;width:${size - inset * 2}px;height:${size - inset * 2}px;}
     </style>${svg}`,
  );
  writeFileSync(resolve(publicDir, file), await page.screenshot({ omitBackground: false }));
  await page.close();
  console.log(`${file.padEnd(24)} ${size}×${size}${padding ? ` (safe zone ${padding * 100}%)` : ''}`);
}

await browser.close();
