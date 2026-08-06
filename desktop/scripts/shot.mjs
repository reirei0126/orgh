// 目視検証用スクリーンショット撮影スクリプト。
// 前提: `VITE_MOCK=1 npm run dev` が http://localhost:1420 で起動していること。
// 実行: node scripts/shot.mjs
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const BASE = "http://localhost:1420";
const OUT = fileURLToPath(new URL("../docs/screenshots/", import.meta.url));

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  await page.goto(`${BASE}/#/`);
  await page.waitForSelector("table.data-table");
  await page.screenshot({ path: `${OUT}list.png`, fullPage: false });

  // awaiting_approval を含むミッション(f9e8d7c6)を明示的に開く
  // (承認バッジ・強調ボタン・複数依存のDAGが見える最も代表的な状態のため)。
  await page.goto(`${BASE}/#/mission/f9e8d7c6`);
  await page.waitForSelector(".live-log");
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}detail.png`, fullPage: false });

  await page.goto(`${BASE}/#/new`);
  await page.waitForSelector("textarea.textarea");
  await page.screenshot({ path: `${OUT}new.png`, fullPage: false });

  await browser.close();
  console.log("saved list.png / detail.png / new.png");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
