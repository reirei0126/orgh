# outcome-log(2026-08-19〜09-17 の30日運用プロトコル正本)

規約: docs/strategy/outcome-2026-08.md §3。1行1レコード追記型(同一missionの再判定は新しい行を追加、最新行が有効)。
自由文セルに `|` を書かない(／で代替)。空欄は `-`。判定enum: used|unused|unknown|unknown-expired|pending。
routeenum: orgh|manual|ai-session|dropped。observe_byは種別固定表(配達=+3日/公開物=+14日/UI・アプリ=+30日/業務=+90日)。
自由文セルに機微情報を書かない(固有名詞・金額・人名は抽象化。詳細はvault側メモに置き `vault参照` と記す)。週次確認: 最大3件・高額順。対象0件の週も `CHECKED W<ISO週番号> 対象0件` 行を追記(実施記録の正本)。E1対象は2026-08-19以降の新規doneのみ(遡及なし)。2週連続で週次が開けない場合は `PAUSED` 行を追記しプロトコル時計を停止(不在をunknown-expiredに変換しない)。

判定(usage) enum: used|unused|unknown|unknown-expired|pending / outcome_result enum: achieved|not-achieved|unknown|pending|-(宣言なし)

| date | mission | 分類 | usd | route | usage | outcome宣言 | observe_by | 判定 | outcome_result | evidence | owner_min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-21 | 8b435cc4 | A | 11.20 | orgh | deployed | 8/27までにREADME公開・応募書類にMCP実績記載(E3宣言) | 2026-09-05 | pending | pending | Notion実疎通成功(pull/writeback各1回)・README節あり | 15 |

## E5補助表(正解先行の非劣性判定用。対象発生時に開始前登録)

| mission | 比較対照mission(同分類・費用±50%の直近) | 手戻り回数 | オーナー確認min | 費用usd | 判定メモ |
|---|---|---|---|---|---|

CHECKED W34 対象0件(プロトコル初日8/19。E1対象=8/19以降の新規doneのため登録なし)

E2初データ(2026-08-19): 620402d6でノートに「予算上限: 15 USD」宣言→mission.json limit_usd=None(Plannerが宣言を予算機構へ未接続)→実費16.04で1USD超過。「宣言が強制に繋がらない」経路欠陥を確認。違反カウント対象(30USD超)ではないが、E2の設計前提に関わるためPlannerの宣言取り込みを要検討事項として記録。

E2データ#2(2026-08-19): 8b435cc4で承認時にmission.budget.limit_usd=40を手動接続したが、実行開始時のsetup_budget(orgh/orchestrator/budget_policy.py)がconfig loop.budget_usd(=None)で上書きし無制限化。宣言経路は「Planner未接続」+「config上書き」の二重断線と確定。実費11.2で実害なし。修正判断は9/17(または費用超過失敗の再発=outcome §5-2トリガー)。

CHECKED W34-2(2026-08-21): E1登録1件(8b435cc4=outcome宣言付きのため任意登録。A分類20USD未満なので必須対象外)。E2対象なし。E3宣言あり1件(8b435cc4)。E4新規メモなし。
