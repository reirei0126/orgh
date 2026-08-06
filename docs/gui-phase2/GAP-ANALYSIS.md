# orgh GUI第2期 ギャップ分析

## 分析の前提(参照ブランチ、参照した資料、走査方法)

- 参照ブランチ: `orgh/8e096d63/t4`(デスクトップGUI第1期、未マージ)。作業ディレクトリ `/Users/uesugirei/projects/org-harness` のHEADは分析全体を通じて常に `main` のまま維持し、checkout・merge・pull・push・ブランチ作成は一切行っていない。
- 一次資料: 先行タスクが作成した `docs/gui-phase2/INVENTORY.md`(実装インベントリ)。本ドキュメントの1〜6章すべてを読了した上で、ギャップの裏取りが必要な箇所を追加で実コードから確認した。
- 追加で直接確認した読み取り専用コマンドと対象ファイル:
  - `git show orgh/8e096d63/t4:config.example.yaml` — セットアップ時にユーザーが編集すべき全設定項目の把握
  - `git show orgh/8e096d63/t4:desktop/src/pages/{NewMissionPage,MissionListPage,MissionDetailPage,SettingsPage}.tsx` — 画面文言・エラーハンドリング・ヒントテキストの逐語確認
  - `git show orgh/8e096d63/t4:desktop/src-tauri/src/commands.rs` — `settings.runs_dir` が実際にCLI呼び出し引数へ渡されているかの確認(`build_run_args`・`run_json`・`run_sync` の全呼び出し箇所)
  - `git show orgh/8e096d63/t4:orgh/sources/obsidian.py` — `#go`(trigger_tag)判定ロジック(`is_triggered`/`should_trigger`)の実装箇所の特定
  - `git show orgh/8e096d63/t4:orgh/cli.py` — `run --note` 経路が上記の判定関数を呼び出しているかの確認(呼び出しなしを確認)
  - `git show orgh/8e096d63/t4:orgh/doctor.py` — `worker:*` チェックの実装(`--version` 実行のみで認証状態は見ていないことの確認)
  - `git show orgh/8e096d63/t4:orgh/{gc,report}.py` — `gc`/`report` の集計内容とGUI非公開の裏取り
  - `git show orgh/8e096d63/t4:desktop/src/components/StatusBadge.tsx` — ステータスラベルの言語(英語のまま)の確認
  - `git show orgh/8e096d63/t4:README.md`, `docs/orgh-first-guide.md` — GUI外に存在する導入・非エンジニア向け説明の範囲確認(GUI内から到達できないことの確認)
  - `git grep -n "projects_map" orgh/8e096d63/t4` — `projects_map` がconfig/Planner側の概念のみで、GUIコード(`desktop/`)には一切出現しないことの確認
- 走査方法: タスク仕様で固定されたライフサイクル3段(セットアップ/利用開始/利用熟練)×品質特性2種(機能の有無/user friendliness)の6セルそれぞれについて、INVENTORY.mdの該当章(1章CLI能力・2章構造化データ・3章画面インベントリ・4章CLI×GUI対応マップ・5章設定/接続・6章VERIFY.md)を突き合わせ、CLIにある能力・情報のうちGUIに存在しないもの(機能の有無)と、GUIに存在するが表示や導線が実装と食い違う・分かりにくいもの(user friendliness)を分けて列挙した。

### 深刻度の判定基準

- **高**: この機能・分かりやすさの欠如により、ユーザーが初めての成功体験に到達できない、または日常運用の中で必ず詰まる(GUIだけでは完結できず都度CLIやテキストエディタに頼らざるを得ない)。
- **中**: 回避策(CLIに戻る、テキストエディタで直接編集する等)は存在するが、その都度の摩擦が大きい。
- **低**: 現状でも運用は成立するが、あれば体験が良くなる。

## ギャップ一覧(6セル)

### A-1 セットアップ × 機能の有無

| ID | ギャップ | 深刻度(高/中/低) | ユーザーに起きること | 根拠(見たコード/画面のパス・画面名) | 非IT層のみの障壁か(はい/いいえ) |
|---|---|---|---|---|---|
| G-01 | orgh本体の導入(`pip install -e .`、venv構築)がGUIの外に完全に丸投げされている。GUIはインストール済みの`orgh`バイナリの存在を前提とする | 高 | GUIを起動しても、orghが未インストールならSettings画面の3フィールドを埋める前段階で詰まる。GUI単体では「導入」の一歩目すら踏み出せない | `orgh/8e096d63/t4:README.md`「セットアップ」節(`pip install -e .` / `cp config.example.yaml config.yaml`)。`orgh/8e096d63/t4:desktop/src-tauri/src/settings.rs` `impl Default for Settings`(既定値`orghBin: "orgh"`はPATH解決前提で、インストール自体は行わない) | いいえ(開発者でも初回は必ず通る) |
| G-02 | `config.yaml`の主要項目(`vault`/`workers`/`roles`/`loop`/`worktree`/`watch`/`gc`など約20項目)を編集するUIが無く、SettingsPageは`orghBin`/`configPath`/`runsDir`の3フィールドのみ | 中 | doctorを「全OK」にするには`vault.path`やワーカーのバイナリ名・モデル指定などをテキストエディタでYAML直接編集する必要があり、GUIだけではセットアップを完了できない | `orgh/8e096d63/t4:config.example.yaml`(全項目)と`orgh/8e096d63/t4:desktop/src/pages/SettingsPage.tsx`(3フィールドのみ)の対比 | いいえ(ただしYAML編集への抵抗感は非IT層でより大きい) |
| G-03 | 配布用インストーラ(`.dmg`)が生成されておらず`.app`のみで、`.dmg`バンドリングはこの検証環境では未検証・未実施 | 低 | ユーザーは`.app`ファイルを直接受け取るか、自分で`npm run tauri build`を実行する必要がある。標準的なインストーラ体験(ダブルクリックでインストール)が無い | INVENTORY.md 6章(VERIFY.md 1章末尾差分表・6章既知の制約4「`.dmg`バンドリングは未検証」) | いいえ |
| G-04 | 外部ワーカーCLI(`claude`/`codex`)自体のインストール・ログイン(認証)を行う導線がGUIに無い | 中 | doctorの`worker:*`チェックはバイナリの`--version`実行のみを見ており、未インストール・未ログインのどちらであっても「NG」としか分からず、GUI側にインストール手順やログイン手順への案内が無い | `orgh/8e096d63/t4:orgh/doctor.py` `_check_binary()`/`_binaries()`(`--version`疎通のみ)。`orgh/8e096d63/t4:desktop/src/pages/SettingsPage.tsx`(診断結果はテーブル表示のみで手順リンク無し) | いいえ |
| G-05 | Obsidian vault自体の用意(Obsidianアプリのインストール、`inbox`フォルダ作成等)を支援する機能がGUIに無い | 低 | `vault`未設定でも「未設定(watch/scanを使わないなら問題なし)」扱いになるため必須ではないが、vault運用を始めたいユーザーはGUI外で全て自力設定する必要がある | INVENTORY.md 2.4節(doctorの`vault`チェック仕様)。`orgh/8e096d63/t4:config.example.yaml` `vault:`セクション | いいえ |

### A-2 セットアップ × user friendliness

| ID | ギャップ | 深刻度(高/中/低) | ユーザーに起きること | 根拠(見たコード/画面のパス・画面名) | 非IT層のみの障壁か(はい/いいえ) |
|---|---|---|---|---|---|
| G-06 | 設定画面(SettingsPage)の「runsディレクトリ」フィールドは、値を変更・保存してもCLI呼び出しには一切渡されない「表示用のキャッシュ」でしかない。にもかかわらず、実際にCLI起動に使われる`orghBin`/`configPath`の2フィールドと全く同じ見た目・同じフォームで並んでいる | 高 | ユーザーが「runsディレクトリを変えれば参照先が変わる」と信じて編集しても実際の挙動は変わらず、原因不明の「設定したのに反映されない」状態に陥る。フィールドヒントを読まない限り気づけない | `orgh/8e096d63/t4:desktop/src/pages/SettingsPage.tsx`(フィールドヒント「表示用のキャッシュ。実際の参照元はconfig.yamlのruns_dir。」)。`orgh/8e096d63/t4:desktop/src-tauri/src/commands.rs`(`build_run_args`/`run_json`/`run_sync`のいずれも`settings.runs_dir`を引数に含めていないことを確認済み) | いいえ |
| G-07 | doctorの`worker:<name>`チェックはバイナリの`--version`実行が成功するかのみを見ており、実際にAPI呼び出しに必要な認証(ログイン)状態は検証していない | 高 | 「orgh doctor を実行」で全項目OKになっても、実際にミッションを実行した際にワーカー側の未認証エラーで失敗しうる。doctorの「全OK」表示が実態と食い違う(タスク仕様が例示する「嘘をつく」UIの典型例) | `orgh/8e096d63/t4:orgh/doctor.py` `_check_binary()`(実行するのは`--version`のみ) | いいえ |
| G-08 | ミッション一覧画面の取得失敗バナーは、原因(orgh未検出/config構文エラー/vaultパス不正など)を区別せず「orghコマンドのパスとconfig.yamlの場所が正しいか設定から確認してください」という定型文言のみを表示する | 中 | 実際のエラー文字列(`String(e)`)はバナー内に含まれるが、次に何を確認すべきかの構造化ガイドが無く、原因切り分けをユーザー自身が行う必要がある | `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx`(取得失敗時のempty-stateブロック) | いいえ |
| G-09 | doctor実行への導線がSettings画面の中に埋もれており、一覧画面のエラーバナーから「設定」ボタンを押した後、さらに手動で「orgh doctor を実行」ボタンを押す必要がある(ワンクリックで診断結果まで到達できない) | 低 | 初回セットアップでつまずいた際、原因特定までのクリック数が多い | `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx`(設定ボタンのみ)。`orgh/8e096d63/t4:desktop/src/pages/SettingsPage.tsx`(`handleDoctor()`は同画面内の別ボタン) | いいえ |

### B-1 利用開始 × 機能の有無

| ID | ギャップ | 深刻度(高/中/低) | ユーザーに起きること | 根拠(見たコード/画面のパス・画面名) | 非IT層のみの障壁か(はい/いいえ) |
|---|---|---|---|---|---|
| G-10 | 初ミッションまでの導線(ノートの書き方、`#go`インラインタグまたはfrontmatter `orgh: go`、`projects_map`の役割)を説明する機能がGUIに一切無い(既知ギャップ) | 高 | 新規ミッション画面(NewMissionPage)のヒントはプレースホルダ例文のみで、vaultノートをどう書けば着火するか・`projects_map`が無いとPlannerがworkdirを誤解決しうること、をGUI内で知る手段が無い。初めての成功体験に到達できない | `orgh/8e096d63/t4:desktop/src/pages/NewMissionPage.tsx`(プレースホルダのみ)。`orgh/8e096d63/t4:config.example.yaml`(`trigger_tag`/`projects_map`の説明はconfig内コメントのみ)。`git grep -n "projects_map" orgh/8e096d63/t4`でdesktop/配下に一切出現しないことを確認済み | いいえ |
| G-11 | Plannerが計画生成に失敗した場合、vaultノート末尾に`[!failure]`コールアウトが自動追記される仕組みがあるが、GUI(NewMissionPage)側はこの挙動に一切言及せず、ミッション開始失敗時にvaultを見に行くべきことに気づけない | 中 | intentモードでの失敗はGUI内のonErrorバナーで完結するが、noteモードでの失敗時にvault側へのフィードバック追記があることをGUIから知る手段が無い | `orgh/8e096d63/t4:orgh/sources/obsidian.py` `notify_failure()`。`orgh/8e096d63/t4:desktop/src/pages/NewMissionPage.tsx`(該当する説明文言なし) | いいえ |
| G-12 | note指定モードの入力欄には「vault内のノートパス、またはノート名を指定します」とだけ書かれており、実際の検索仕様(タイトル完全一致を優先し、無ければ部分一致でフォールバック)の説明が無い | 低 | 同名・類似名のノートが複数ある場合にどれが選ばれるか予測できない | `orgh/8e096d63/t4:orgh/sources/obsidian.py` `ObsidianAdapter.find()`。`orgh/8e096d63/t4:desktop/src/pages/NewMissionPage.tsx`(field-hint文言) | いいえ |

### B-2 利用開始 × user friendliness

| ID | ギャップ | 深刻度(高/中/低) | ユーザーに起きること | 根拠(見たコード/画面のパス・画面名) | 非IT層のみの障壁か(はい/いいえ) |
|---|---|---|---|---|---|
| G-13 | ミッション/タスクのステータスラベル(`pending`/`running`/`awaiting approval`/`done`/`failed`/`cancelled`/`skipped`/`review`)が英語のまま画面表示される | 中 | 初めて使うユーザーは各ステータスの意味を推測する必要があり、特に`awaiting_approval`(承認待ち)の意味が伝わりにくい | `orgh/8e096d63/t4:desktop/src/components/StatusBadge.tsx` `TONES`定義(`label`が英語のまま) | はい(開発者は英語ステータスに慣れているため障壁が小さい) |
| G-14 | note指定モードでノートが見つからない場合、CLI側の生の例外メッセージ(`note 'xxx' not found`)がそのままonErrorバナーに転記される | 中 | 「ミッションの開始に失敗しました: note 'xxx' not found」という英語混じりの技術的メッセージが表示されるのみで、正しいノート名の書き方への案内が無い | `orgh/8e096d63/t4:orgh/cli.py`(`sys.exit(f"note '{args.note}' not found")`)。`orgh/8e096d63/t4:desktop/src/pages/NewMissionPage.tsx`(`onError`でそのまま`String(e)`を表示) | いいえ |
| G-15 | ミッション完了時に成功体験を後押しする要素(完了サマリ、差分の要約、retroが書いた学びの提示)が無く、StatusBadgeが「done」になるだけ | 低 | 初めてミッションを完走しても「終わった」という以上の手応えが画面から得られない | `orgh/8e096d63/t4:desktop/src/pages/MissionDetailPage.tsx`(完了後も表示は既存のタスク表・ログのみ) | いいえ |
| G-16 | note指定モードは実装上`#go`(trigger_tag)判定を一切通らない(`orgh run --note`は`src.find()`で見つかれば即座に計画生成に進み、`is_triggered`/`should_trigger`は呼ばれない)。一方でconfig.example.yamlやREADMEの`#go`説明を読んだユーザーは「タグを付けないと動かない」と誤解しうるが、GUI側はこの点について何も説明していないため誤解を訂正する手段も無い | 中 | ユーザーがノートに`#go`タグを付け忘れて「動かないのでは」と不安になる、または逆に`#go`の意味を`orgh watch`(GUI非対応)専用の概念と知らずに混乱する | `orgh/8e096d63/t4:orgh/cli.py`(`if args.cmd == "run": ... note = src.find(args.note)`に`is_triggered`呼び出しなし)。`orgh/8e096d63/t4:orgh/sources/obsidian.py`(`is_triggered`/`should_trigger`は`ObsidianAdapter.should_trigger`経由でのみ使われ、これは`watcher.py`からしか呼ばれない) | いいえ |

### C-1 利用熟練 × 機能の有無

| ID | ギャップ | 深刻度(高/中/低) | ユーザーに起きること | 根拠(見たコード/画面のパス・画面名) | 非IT層のみの障壁か(はい/いいえ) |
|---|---|---|---|---|---|
| G-17 | `report`(週次の初回attempt合格率・差し戻し率、ミッション別コスト・所要時間、worker別失敗率)をGUIから見る手段が一切無い(既知ギャップ) | 高 | 「増幅」(組織が賢くなっているか)を裏付ける唯一の定量指標がGUI利用者には見えず、CLIで`orgh report`を叩かない限り運用の健全性を把握できない | INVENTORY.md 4章(C7 `report`「なし」)。`orgh/8e096d63/t4:orgh/report.py`(`build_report()`の集計内容)。`orgh/8e096d63/t4:desktop/src-tauri/src/commands.rs`(9コマンド中に`report`相当なし) | いいえ |
| G-18 | retro/playbookの中身(蒸留された組織知)をGUIから閲覧する手段が無い(既知ギャップ) | 高 | 各ミッション終了後にRetroが`playbooks/`へ何を書き足したかをGUIで確認できず、「回すほど組織が賢くなる」という中核体験がGUI利用者には不可視 | INVENTORY.md 3章(GUI画面インベントリにplaybook/retro閲覧画面なし)。`git grep -n "playbook" orgh/8e096d63/t4 -- desktop/`が0件であることを確認済み | いいえ |
| G-19 | `cleanup`(ミッションのworktree/ブランチ掃除)がGUIに無い | 中 | `worktree.enabled: true`で運用している場合、掃除にはCLIへ戻る必要がある。ただし既定値は`worktree.enabled: false`のため全ユーザーに影響するわけではない | INVENTORY.md 4章(C11「なし」)。`orgh/8e096d63/t4:config.example.yaml`(`worktree.enabled`既定`false`) | いいえ |
| G-20 | `resume`(中断・キャンセルされたミッションの再開)がGUIに無い | 高 | GUIの「キャンセル」ボタンでミッションを止めた直後、そのミッションを再開する手段がGUI内に存在せず、キャンセル操作をした瞬間にCLIへ依存せざるを得ない。承認・キャンセルと並ぶ日常操作の直後に穴がある | INVENTORY.md 4章(C9「なし」、`git grep -n "resume" orgh/8e096d63/t4 -- desktop/`一致0件) | いいえ |
| G-21 | `gc`(playbookの統合・退避とruns/のアーカイブ)がGUIに無い | 中 | playbookが肥大化・矛盾を溜め込んでも、GUIからは統合・整理を実行できずCLIに戻る必要がある | INVENTORY.md 4章(C4「なし」)。`orgh/8e096d63/t4:orgh/gc.py`(バックアップ→退避→統合→runs保持の一連の処理) | いいえ |
| G-22 | 複数ミッション横断のコスト俯瞰(合計コスト、期間別推移)を見る手段が無く、一覧テーブルは行ごとのコストのみ(既知ギャップ) | 高 | 並行運用でミッション数が増えるほど、総コストや予算消化ペースを把握するには全行を目視で足し算するしかない | `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx`(テーブルに合計行・集計表示なし)。`orgh/8e096d63/t4:orgh/report.py`(集計自体はCLI側に存在するがGUI非公開、G-17と表裏) | いいえ |
| G-23 | `watch`(vault監視デーモン)の起動・停止・稼働状態確認がGUIに無い | 中 | vaultへのノート投稿で自動着火する運用スタイルを使う場合、デーモンが動いているかをGUIから確認できず、外部起動されたミッションの進捗もポーリングでしか追えない(コード注釈で明示されている制約) | INVENTORY.md 4章(C2「なし」)。`orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx`のコメント(「watchデーモン等の外部起動ミッションはポーリングでしか追えない」) | いいえ |

### C-2 利用熟練 × user friendliness

| ID | ギャップ | 深刻度(高/中/低) | ユーザーに起きること | 根拠(見たコード/画面のパス・画面名) | 非IT層のみの障壁か(はい/いいえ) |
|---|---|---|---|---|---|
| G-24 | 「キャンセル」ボタンの「即時停止ではなくCANCELフラグを立てるだけ」という仕様は、ボタンのホバー時ツールチップ(`title`属性)にしか書かれておらず、画面上に常時表示されるヘルプは無い | 中 | 押下直後もStatusBadgeが「running」のままのため、「効いていないのでは」と誤解し連打・再読み込みなどの不要な操作を誘発しうる | `orgh/8e096d63/t4:desktop/src/pages/MissionDetailPage.tsx`(キャンセルボタンの`title="CANCELフラグを置き、実行中プロセスが検知した時点で停止します(即時停止ではありません)"`) | いいえ |
| G-25 | 承認待ち(`awaiting_approval`)のタスクを一目で区別する専用の強調表示が無く、タスク一覧の行の中でStatusBadgeの黄色バッジのみが目印 | 低 | タスク数が多いミッションでは、どのタスクが承認を要求しているかをテーブルをスクロールして探す必要がある | `orgh/8e096d63/t4:desktop/src/pages/MissionDetailPage.tsx`(タスク表の各行に個別の強調行スタイルなし) | いいえ |
| G-26 | ポーリング間隔(一覧10秒/詳細5秒)に起因する表示遅延が画面上に明示されない。特に自プロセス外(watchデーモン等)が起動したミッションは`mission-updated`イベントが飛ばずポーリングでしか更新されないという制約がコード注釈にしかない | 低 | ユーザーは画面をリアルタイム反映と誤認し、実際の状態変化から最大10秒近く遅れて気づく | `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx`/`MissionDetailPage.tsx`の`LIST_POLL_MS`/`DETAIL_POLL_MS`コメント(UI上の表示は無し) | いいえ |
| G-27 | `skipped`(読み込めなかった`mission.json`)が発生した場合の一覧画面の警告は件数とパス・理由の一覧を出すが、そこから詳細調査(該当ディレクトリを開く等)へ進む導線が無い | 低 | 「データ破損の可能性があります」という警告文だけが表示され、次に何をすべきかはユーザー任せになる | `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx`(skipped警告ブロック) | いいえ |
| G-28 | ミッション一覧にソート・フィルタ(状態別・日付別・intent検索)機能が無い | 中 | 並行ミッションの監視・運用が長期化しミッション数が増えるほど、目的のミッションを探すのに全件を目視で走査する必要がある | `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx`(テーブルはポーリング取得結果をそのまま描画するのみで、ソート・フィルタのstate/UIが無い) | いいえ |

## 深刻度別サマリ

| ID | ギャップ名 | セル | 深刻度 |
|---|---|---|---|
| G-01 | orgh本体の導入がGUI外に丸投げ | A-1 | 高 |
| G-06 | 「runsディレクトリ」設定が実際には無効なのに機能フィールドと同列に見える | A-2 | 高 |
| G-07 | doctorのworkerチェックが認証状態を検証せず「全OK」が実態と食い違う | A-2 | 高 |
| G-10 | 初ミッションまでの導線(ノートの書き方・#go・projects_map)の説明が無い | B-1 | 高 |
| G-17 | report(週次合格率・差し戻し率・worker別失敗率)を見る手段が無い | C-1 | 高 |
| G-18 | retro/playbookの中身を見る手段が無い | C-1 | 高 |
| G-20 | resume(中断・キャンセル後の再開)がGUIに無い | C-1 | 高 |
| G-22 | 複数ミッション横断のコスト俯瞰が無い | C-1 | 高 |
| G-02 | config.yamlの主要項目を編集するUIが無い | A-1 | 中 |
| G-04 | 外部ワーカーCLI自体の導入・認証導線が無い | A-1 | 中 |
| G-08 | 一覧画面の取得失敗バナーが原因を区別しない | A-2 | 中 |
| G-11 | plan失敗時のvaultコールアウト追記がGUIから見えない | B-1 | 中 |
| G-13 | ステータスラベルが英語のまま | B-2 | 中 |
| G-14 | note not foundの生CLIエラーがそのままバナー表示 | B-2 | 中 |
| G-16 | noteモードは実は#go判定を通らないという実装とREADME説明との整合不足 | B-2 | 中 |
| G-19 | cleanupがGUIに無い | C-1 | 中 |
| G-21 | gcがGUIに無い | C-1 | 中 |
| G-23 | watchの起動・停止・稼働確認がGUIに無い | C-1 | 中 |
| G-24 | キャンセルの非即時性がツールチップのみでの案内 | C-2 | 中 |
| G-28 | ミッション一覧にソート・フィルタが無い | C-2 | 中 |
| G-03 | 配布用インストーラ(.dmg)が無く.appのみ | A-1 | 低 |
| G-05 | vault(Obsidian)自体の用意を支援する機能が無い | A-1 | 低 |
| G-09 | doctor実行への導線がSettings画面内に埋もれている | A-2 | 低 |
| G-12 | note検索仕様(完全一致優先/部分一致フォールバック)の説明が無い | B-1 | 低 |
| G-15 | ミッション完了時に成功体験を後押しする要素が無い | B-2 | 低 |
| G-25 | 承認待ちタスクを一目で区別する強調表示が無い | C-2 | 低 |
| G-26 | ポーリング遅延がUI上に明示されない | C-2 | 低 |
| G-27 | skipped警告から詳細調査への導線が無い | C-2 | 低 |
