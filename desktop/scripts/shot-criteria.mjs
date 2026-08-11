// 基準台帳ページの目視検証用スクリーンショット撮影スクリプト。
// 前提: `VITE_MOCK=1 npm run dev` が http://localhost:1420 で起動していること。
// 実行: npx playwright ...を使い node scripts/shot-criteria.mjs
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const BASE = "http://localhost:1420";
const OUT = fileURLToPath(new URL("../docs/screenshots/phase3/", import.meta.url));

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 1400 } });

  await page.goto(`${BASE}/#/criteria`);
  await page.waitForSelector(".page-title");
  await page.waitForTimeout(400);

  // 下書きセクション(モックデータに2件の下書きあり)を撮る
  await page.screenshot({ path: `${OUT}criteria-drafts.png`, fullPage: false });

  // 本台帳セクションまでスクロールして撮る
  const ledgerPanel = page.locator(".panel-title", { hasText: "本台帳" });
  await ledgerPanel.scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT}criteria-ledger.png`, fullPage: false });

  await browser.close();
  console.log("saved criteria-drafts.png / criteria-ledger.png");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
