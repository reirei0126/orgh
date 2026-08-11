// 目視検証用スクリーンショット撮影スクリプト。
// 前提: `VITE_MOCK=1 npm run dev` が http://localhost:1420 で起動していること
// (別ポートで起動した場合は環境変数 SHOT_BASE_URL で上書き可能)。
// 実行: node scripts/shot.mjs
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const BASE = process.env.SHOT_BASE_URL ?? "http://localhost:1420";
const OUT = fileURLToPath(new URL("../docs/screenshots/", import.meta.url));
const OUT_PHASE3 = fileURLToPath(new URL("../docs/screenshots/phase3/", import.meta.url));

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

  // ミッション詳細ページの検収裁定(verdict)/人間依頼(awaiting_human)UI。
  // b1c2d3e4 = done かつ未裁定(裁定フォームが出る状態)
  await page.goto(`${BASE}/#/mission/b1c2d3e4`);
  await page.waitForSelector("#verdict-reason");
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_PHASE3}detail-verdict-form.png`, fullPage: false });

  // c1d2e3f4 = done かつ verdicts に1件記録済み(裁定済み表示)
  await page.goto(`${BASE}/#/mission/c1d2e3f4`);
  await page.waitForSelector(".record-card");
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_PHASE3}detail-verdict-recorded.png`, fullPage: false });

  // d1e2f3a4 = awaiting_human タスクを持つミッション(人間依頼ブロック)
  await page.goto(`${BASE}/#/mission/d1e2f3a4`);
  await page.waitForSelector('textarea[id^="human-note-"]');
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_PHASE3}detail-human-request.png`, fullPage: false });

  await browser.close();
  console.log(
    "saved list.png / detail.png / new.png / " +
      "phase3/detail-verdict-form.png / phase3/detail-verdict-recorded.png / phase3/detail-human-request.png",
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
