// orgh 仕様理解度クイズ 設問バンク(SSOTはソースコード。出典 sources[] は必ず実在パスにすること)
// 形式検証は tests/test_quiz_bank.py が行う(id重複・選択肢範囲・出典の実在・カテゴリ妥当性)。
window.ORGH_QUIZ = {
  "version": 1,
  "updated": "2026-08-17",
  "categories": [
    { "id": "architecture", "label": "アーキテクチャ全体", "reading": "README.md / docs/deep-dive.md 1章" },
    { "id": "state", "label": "状態遷移とattempt", "reading": "orgh/state.py / orgh/orchestrator/task_executor.py" },
    { "id": "governance", "label": "統治線(ガード・裁定・基準台帳)", "reading": "orgh/guard.py / orgh/criteria.py / docs/threat-model.md" },
    { "id": "budget", "label": "予算プール", "reading": "orgh/state.py Budget / orgh/orchestrator/budget_policy.py" },
    { "id": "isolation", "label": "worktree分離とcopyback", "reading": "orgh/worktree.py / orgh/copyback.py" },
    { "id": "knowledge", "label": "組織知(playbooks/Retro/gc)", "reading": "orgh/planner.py / orgh/gc.py" },
    { "id": "runtime", "label": "実行基盤(queue/executor/slots/lease/cancel)", "reading": "orgh/queue.py / orgh/executor.py / orgh/slots.py / orgh/lease.py" },
    { "id": "source", "label": "入力ソース(Obsidian)", "reading": "orgh/sources/obsidian.py" },
    { "id": "cli", "label": "CLIと運用", "reading": "orgh/cli.py" },
    { "id": "config", "label": "設定", "reading": "config.example.yaml" },
    { "id": "desktop", "label": "orgh Desktop", "reading": "desktop/API.md / desktop/src/types.ts" }
  ],
  "questions": [
    {
      "id": "arch-001",
      "category": "architecture",
      "difficulty": "basic",
      "type": "single",
      "question": "orghのミッション1本の基本ループとして正しい並びはどれか。",
      "choices": [
        "plan(Planner) → 並列execute(Worker) → review(Reviewer) → 差し戻し改善 → retro(playbooks蒸留)",
        "ingest → build → deploy → monitor",
        "review → plan → execute → retro",
        "plan → review → execute → 人間承認"
      ],
      "answer": [0],
      "explanation": "PlannerがタスクDAGを設計し、OrchestratorがWorkerを並列起動、Reviewerが受け入れ条件で検収し、落ちたタスクはフィードバック付きで差し戻し、終端後にRetroが教訓をplaybooksへ蒸留する。",
      "sources": ["README.md", "orgh/orchestrator/scheduler.py"]
    },
    {
      "id": "arch-002",
      "category": "architecture",
      "difficulty": "basic",
      "type": "single",
      "question": "Planner / Reviewer / Retro の3ロールの実装上の共通点は何か。",
      "choices": [
        "いずれも headless の worker CLI を1発叩いてJSONを返させる薄いラッパ(_ask_json)である",
        "いずれも常駐プロセスとして動く",
        "いずれもRust側(desktop/src-tauri)で実装されている",
        "いずれもテンプレートを使わずコード内に文字列でプロンプトを持つ"
      ],
      "answer": [0],
      "explanation": "3ロールとも orgh/planner.py の共通ヘルパー _ask_json() を経由し、プロンプト本文は prompts/*.md に外出しされている(ユーザーが育てる部分)。",
      "sources": ["orgh/planner.py", "prompts/planner.md"]
    },
    {
      "id": "arch-003",
      "category": "architecture",
      "difficulty": "applied",
      "type": "single",
      "question": "_ask_json() がLLM出力から結果を取り出す方法として正しいものはどれか。",
      "choices": [
        "出力から最初のJSONブロックを正規表現(DOTALL)で抜き出して json.loads する",
        "出力全体を必ず json.loads する(前置きがあれば失敗させる)",
        "YAMLとしてパースする",
        "stdoutの1行目だけを使う"
      ],
      "answer": [0],
      "explanation": "コードフェンスや前置き説明が混ざっても拾えるよう、`\\{.*\\}`(DOTALL)で最初のJSONブロックを抽出してからパースする設計。",
      "sources": ["orgh/planner.py"]
    },
    {
      "id": "arch-004",
      "category": "architecture",
      "difficulty": "internals",
      "type": "multi",
      "question": "orgh/orchestrator パッケージの分割後、次のうち実在するサブモジュールはどれか(複数選択)。",
      "choices": [
        "scheduler(DAG解決・並列dispatch・ライフサイクル)",
        "task_executor(1タスクのattemptループ)",
        "review_pipeline(reviewer+persona検収とロールリトライ)",
        "planner_pipeline(タスク分解の再帰実行)"
      ],
      "answer": [0, 1, 2],
      "explanation": "orchestratorは scheduler / task_executor / review_pipeline / cancellation / budget_policy / copyback_gate / transitions に分割されている。planner_pipeline は存在しない(サブミッション再帰は未実装)。",
      "sources": ["orgh/orchestrator/__init__.py"]
    },
    {
      "id": "arch-005",
      "category": "architecture",
      "difficulty": "internals",
      "type": "single",
      "question": "orgh/orchestrator/__init__.py に残っているアンダースコア付きalias(_run_task等)の扱いとして正しいものはどれか。",
      "choices": [
        "既存テストの直接import互換のためだけに残しており、monkeypatchの標的にはならない(patchは定義元モジュールに当てる)",
        "推奨API。新規コードもここからimportする",
        "実行時にfacade経由で解決されるため、差し替えると挙動が変わる",
        "非推奨なので次のリリースで削除予定であり、テストからも参照されていない"
      ],
      "answer": [0],
      "explanation": "実行は各サブモジュールのグローバル解決を通るため、facadeのaliasを差し替えても実挙動は変わらない。patchは orgh.orchestrator.task_executor 等の定義元に当てる。",
      "sources": ["orgh/orchestrator/__init__.py"]
    },
    {
      "id": "state-001",
      "category": "state",
      "difficulty": "basic",
      "type": "single",
      "question": "orgh/state.py の TERMINAL タプルに含まれる状態はどれか。",
      "choices": [
        "done / failed / cancelled / skipped",
        "done / failed のみ",
        "done / failed / awaiting_human / awaiting_approval",
        "done / failed / cancelled / review"
      ],
      "answer": [0],
      "explanation": "TERMINAL = (\"done\", \"failed\", \"cancelled\", \"skipped\")。awaiting_human / awaiting_approval は終端ではなく人間の操作を待つ一時停止状態。",
      "sources": ["orgh/state.py"]
    },
    {
      "id": "state-002",
      "category": "state",
      "difficulty": "applied",
      "type": "single",
      "question": "実行中(queued/running/review)のままプロセスがクラッシュしたミッションを resume するとどうなるか。",
      "choices": [
        "RunStore.load() が _INFLIGHT_STATUSES のタスクを pending へ巻き戻す(デッドロック解消)",
        "そのまま running として扱われ、二重に走る",
        "failed に確定し、--retry-failed が必須になる",
        "mission.json が壊れているとみなしてエラー終了する"
      ],
      "answer": [0],
      "explanation": "_INFLIGHT_STATUSES = (\"queued\", \"running\", \"review\") はロード時に pending へロールバックされる。生死の判定材料としては別途 lease.json がある。",
      "sources": ["orgh/state.py", "orgh/lease.py"]
    },
    {
      "id": "state-003",
      "category": "state",
      "difficulty": "applied",
      "type": "single",
      "question": "worker出力が \"Request timed out\" や \"ECONNRESET\" にマッチした場合の扱いは。",
      "choices": [
        "インフラ起因とみなし attempts を消費せずに待機して再試行する(infra_max_retriesで上限あり)",
        "即 failed にする",
        "attemptsを1消費して通常の差し戻しに回す",
        "Reviewerに判定を委ねる"
      ],
      "answer": [0],
      "explanation": "INFRA_ERROR_RE にマッチする出力はworkerの失敗ではなくネットワーク断等とみなし、attempt非消費でリトライする(実運用でネットワーク断が3attemptを浪費した事例への対処)。",
      "sources": ["orgh/orchestrator/task_executor.py"]
    },
    {
      "id": "state-004",
      "category": "state",
      "difficulty": "internals",
      "type": "single",
      "question": "BaseAdapter が付ける task_timeout マーカー(\"timeout\")がインフラエラー扱いされないのはなぜか。",
      "choices": [
        "詰まったworkerの可能性があり、attempt非消費で粘ると無限に待つため通常failure扱いにする",
        "タイムアウトは常にネットワーク起因ではないと証明されているため",
        "adapterがすでにリトライ済みだから",
        "Reviewerがタイムアウトを検知して再実行するため"
      ],
      "answer": [0],
      "explanation": "\"timeout\" は INFRA_ERROR_RE の対象外で、attemptを消費する通常の失敗として扱う。",
      "sources": ["orgh/orchestrator/task_executor.py", "orgh/adapters/base.py"]
    },
    {
      "id": "state-005",
      "category": "state",
      "difficulty": "applied",
      "type": "single",
      "question": "Reviewerのfeedbackが \"REPLAN:\" で始まったときの挙動として正しいものは。",
      "choices": [
        "Plannerへエスカレーションしてタスクの指示と受け入れ条件を再設計し、attemptを消費せず再実行する(1タスク1回まで)",
        "同じセッションへ差し戻し、attemptを1消費する",
        "ミッション全体を作り直す",
        "awaiting_human に遷移し人間の再設計を待つ"
      ],
      "answer": [0],
      "explanation": "replan_task() が prompts/replan.md で prompt/acceptance を再設計する。t.attempts -= 1(非消費)・t.replans += 1 とし、replans >= 1 なら以後は失敗として打ち切る。",
      "sources": ["orgh/planner.py", "orgh/orchestrator/task_executor.py"]
    },
    {
      "id": "state-006",
      "category": "state",
      "difficulty": "applied",
      "type": "single",
      "question": "Reviewerのfeedbackが \"HUMAN:\" で始まったときの挙動は。",
      "choices": [
        "awaiting_human に遷移し依頼書artifactを生成、attemptは消費しない(試行回数の上限も設けない)",
        "failedに確定して人間の再実行を待つ",
        "REPLANと同じくPlannerに戻る",
        "承認待ち(awaiting_approval)になり orgh approve を待つ"
      ],
      "answer": [0],
      "explanation": "enter_awaiting_human() が依頼書 runs/<mission_id>/artifacts/human_request_<task_id>.md を生成し、refund_attempt=TrueでattemptsをREPLANと同型に戻す。復帰は orgh humandone。",
      "sources": ["orgh/orchestrator/transitions.py", "orgh/cli.py"]
    },
    {
      "id": "state-007",
      "category": "state",
      "difficulty": "applied",
      "type": "single",
      "question": "orgh humandone で提出した --note の内容はどう扱われるか。",
      "choices": [
        "通常のworker成果と同様にReviewerへ渡され、合格ならdone・不合格なら再びawaiting_humanに戻る",
        "無検査でdoneに確定する",
        "ledgerに記録されるだけでReviewerには渡らない",
        "Plannerに渡されて計画が再設計される"
      ],
      "answer": [0],
      "explanation": "人間の完了報告も検収を通す設計。不合格ならfeedbackを踏まえて再度awaiting_humanに戻り、この経路には試行回数の上限がない。",
      "sources": ["orgh/cli.py", "README.md"]
    },
    {
      "id": "state-008",
      "category": "state",
      "difficulty": "internals",
      "type": "single",
      "question": "Reviewer呼び出し自体が失敗(max_turns超過・接続断など)した場合、何を再試行するか。",
      "choices": [
        "ロール呼び出しのみを再試行し、worker実行はやり直さない(成果とコストを捨てない)",
        "workerから丸ごとやり直す",
        "何も再試行せずタスクをfailedにする",
        "Plannerに戻して計画から作り直す"
      ],
      "answer": [0],
      "explanation": "role_call_with_retry() がロールだけをリトライする。ただし FileNotFoundError のような決定論的な設定ミス(personas.enabledのタイポ等)は即座に再送出し、無駄な待機を発生させない。",
      "sources": ["orgh/orchestrator/review_pipeline.py"]
    },
    {
      "id": "state-009",
      "category": "state",
      "difficulty": "internals",
      "type": "single",
      "question": "scheduler.ready() が返すタスクの条件は。",
      "choices": [
        "status が pending で、deps がすべて done のタスク",
        "status が pending のタスクすべて",
        "deps が空のタスクすべて",
        "status が queued のタスク"
      ],
      "answer": [0],
      "explanation": "ready() は毎ループこの条件で抽出され、POLL_INTERVAL=0.5秒粒度で ThreadPoolExecutor に submit される。",
      "sources": ["orgh/orchestrator/scheduler.py"]
    },
    {
      "id": "state-010",
      "category": "state",
      "difficulty": "internals",
      "type": "single",
      "question": "transitions.transition() が「保存(store.save)を行わない」のはなぜか。",
      "choices": [
        "保存はスケジューラのタスク完了時に一括で行われるため",
        "mission.jsonを持たない設計だから",
        "保存はGUI側の責務だから",
        "保存すると自己改変ガードに抵触するため"
      ],
      "answer": [0],
      "explanation": "transition() はlock下でstatus(と任意でreview_notes)を更新しledgerへ記録するだけの共通経路で、遷移の意味づけや永続化タイミングは持たない。",
      "sources": ["orgh/orchestrator/transitions.py"]
    },
    {
      "id": "gov-001",
      "category": "governance",
      "difficulty": "basic",
      "type": "single",
      "question": "自己改変ガードが発動した(awaiting_approval)タスクを続行させる唯一の手段は。",
      "choices": [
        "orgh approve <mission_id>",
        "config で guard.enabled: false を設定する",
        "orgh resume <mission_id> --retry-failed",
        "watch から再着火させる"
      ],
      "answer": [0],
      "explanation": "orgh approve が APPROVED マーカーを作成し該当タスクを pending に戻す。configでの無効化手段は意図的に設けておらず、watcher自動着火でも同じ run_mission() を通るためスキップできない。",
      "sources": ["orgh/guard.py", "orgh/cli.py"]
    },
    {
      "id": "gov-002",
      "category": "governance",
      "difficulty": "applied",
      "type": "multi",
      "question": "needs_approval() が真になる workdir の条件はどれか(複数選択)。",
      "choices": [
        "workdir が orghパッケージディレクトリと一致する、またはその内側にある",
        "workdir が orghパッケージディレクトリを含む(親である)",
        "workdir が prompts_dir / playbooks_dir と一致する、またはその内側にある",
        "prompts_dir / playbooks_dir が workdir の内側にある(逆方向)"
      ],
      "answer": [0, 1, 2],
      "explanation": "パッケージについては「一致・内側・親」の3方向すべてで発動するが、prompts_dir/playbooks_dir は逆方向(運用ディレクトリにprompts/を置く正規構成)まで巻き込まないよう対象外にしている。",
      "sources": ["orgh/guard.py"]
    },
    {
      "id": "gov-003",
      "category": "governance",
      "difficulty": "applied",
      "type": "single",
      "question": "自己改変ガードが1タスクに発動したとき、同ミッションの他タスクはどうなるか。",
      "choices": [
        "タスク単位の判定なので、他の準備完了タスクはブロックされず実行される",
        "ミッション全体が停止する",
        "他タスクもすべて awaiting_approval になる",
        "他タスクは skipped になる"
      ],
      "answer": [0],
      "explanation": "ガードはディスパッチループで t.workdir ごとに判定され、該当タスクだけを承認待ちにする。",
      "sources": ["orgh/orchestrator/scheduler.py", "orgh/guard.py"]
    },
    {
      "id": "gov-004",
      "category": "governance",
      "difficulty": "basic",
      "type": "single",
      "question": "判断基準台帳(criteria)の本台帳へエントリが載る唯一の経路は。",
      "choices": [
        "orgh criteria approve(オーナー操作)",
        "orgh verdict --fail の実行時に自動反映",
        "Retroによる自動追記",
        "Reviewerが合格判定時に自動追記"
      ],
      "answer": [0],
      "explanation": "自動生成は criteria/_drafts/ 止まりで、本台帳への反映は必ず orgh criteria approve を通る(下書き+ワンタップ承認)。下書きの元ネタは orgh verdict の裁定から蒸留される。",
      "sources": ["orgh/criteria.py", "orgh/cli.py"]
    },
    {
      "id": "gov-005",
      "category": "governance",
      "difficulty": "applied",
      "type": "single",
      "question": "criteria台帳のエントリ行が持つ「強度」の値として定義されているのはどれか。",
      "choices": [
        "norm / pref",
        "must / should / may",
        "hard / soft",
        "P0 / P1 / P2"
      ],
      "answer": [0],
      "explanation": "エントリ行は `- ARCH-001 [norm]: ...` の形式で、_VALID_STRENGTHS = {\"norm\", \"pref\"}。失効は別コメント `<!-- superseded_by:ARCH-003 -->` で表す。",
      "sources": ["orgh/criteria.py"]
    },
    {
      "id": "gov-006",
      "category": "governance",
      "difficulty": "internals",
      "type": "single",
      "question": "orgh verdict --fail に付けられる --category の選択肢は。",
      "choices": [
        "visual / factual / premise / other",
        "bug / feature / doc / other",
        "P0 / P1 / P2 / P3",
        "security / performance / ux / other"
      ],
      "answer": [0],
      "explanation": "欠陥カテゴリを件数の元データとして記録するためのもので、率の算出はしない。",
      "sources": ["orgh/cli.py"]
    },
    {
      "id": "gov-007",
      "category": "governance",
      "difficulty": "applied",
      "type": "single",
      "question": "personas.enabled を空に戻したあと、実行開始済みミッションを resume するとペルソナ検収ゲートは。",
      "choices": [
        "走り続ける(タスクに割り当てが保存済み。無効化は次に新規着火するミッションから効く)",
        "即座に無効になる",
        "エラーになりresumeできない",
        "ペルソナの割り当てが自動で削除される"
      ],
      "answer": [0],
      "explanation": "ミッション単位の一貫性を保つ設計。ペルソナは「誰のdepsにも現れない最終タスク」に割り当てられる(apply: final_task)。",
      "sources": ["config.example.yaml", "orgh/orchestrator/scheduler.py"]
    },
    {
      "id": "gov-008",
      "category": "governance",
      "difficulty": "internals",
      "type": "single",
      "question": "Workerのデフォルト allowed_tools について正しいものは。",
      "choices": [
        "Bashは含まれず、必要なタスクにはPlannerがタスク単位の tools で明示付与する",
        "Bashを含むフルアクセスが既定",
        "Readのみが既定で、Write/Editもタスク単位付与",
        "allowed_toolsは廃止され、capability_allowlistに一本化された"
      ],
      "answer": [0],
      "explanation": "既定は \"Read,Write,Edit,Glob,Grep\"。capability_allowlist は固定Bashパターンの能力宣言で、設定時のみ --allowedTools に追記注入され ledger に task.capability_allowlist として記録される。",
      "sources": ["config.example.yaml", "orgh/orchestrator/task_executor.py"]
    },
    {
      "id": "gov-009",
      "category": "governance",
      "difficulty": "internals",
      "type": "single",
      "question": "capability_allowlist の位置づけとして正しいものは。",
      "choices": [
        "セキュリティ境界ではなく、能力不足を誤って人間依頼へ変換しないための能力宣言(UX改善)",
        "workerをsandbox化する強制機構",
        "外部通信を遮断するegress制御",
        "Reviewerの判定基準を宣言するもの"
      ],
      "answer": [0],
      "explanation": "同じargvでもPATH差し替え・cwd・git hook・環境変数で実際の書き込みや外部通信は変わりうるため、sandbox/egress制御が無い現状では保証にならないと明記されている。",
      "sources": ["config.example.yaml", "docs/threat-model.md"]
    },
    {
      "id": "gov-010",
      "category": "governance",
      "difficulty": "internals",
      "type": "single",
      "question": "Retroが返す playbook_name にファイル名の正規表現制約(_PLAYBOOK_NAME_RE)がある理由は。",
      "choices": [
        "LLM由来の名前が playbooks/<name>.md に直挿しされるため、../prompts/reviewer 等でplaybooks外を汚染する経路を塞ぐ",
        "ファイル名を短くしてGUIの表示崩れを防ぐため",
        "playbookのアルファベット順ソートを安定させるため",
        "Windowsのファイル名制約に合わせるため"
      ],
      "answer": [0],
      "explanation": "将来のプロンプトを永続汚染する経路を塞ぐための入力検証で、criteria.py の _SAFE_CATEGORY_RE と同方針。",
      "sources": ["orgh/planner.py", "orgh/criteria.py"]
    },
    {
      "id": "budget-001",
      "category": "budget",
      "difficulty": "basic",
      "type": "single",
      "question": "ミッション予算(loop.budget_usd)を超過したときの挙動は。",
      "choices": [
        "実行中タスクの完了は待つが、未着手タスクは skipped になりミッションが停止する",
        "実行中タスクも即座にterminateされる",
        "全タスクが failed になる",
        "警告のみで実行は続行する"
      ],
      "answer": [0],
      "explanation": "initiate_budget_stop() が pending を skipped にする。予算を上げて orgh resume すれば skipped は pending に戻って続行できる。",
      "sources": ["orgh/orchestrator/budget_policy.py", "orgh/cli.py"]
    },
    {
      "id": "budget-002",
      "category": "budget",
      "difficulty": "applied",
      "type": "single",
      "question": "1タスク上限(loop.task_budget_usd)を超えたタスクはどうなるか。",
      "choices": [
        "その時点で failed とし、次のattemptにもレビューにも進まない",
        "skipped になる",
        "awaiting_human になる",
        "警告のみで最後までattemptを続ける"
      ],
      "answer": [0],
      "explanation": "毎attempt後に t.cost_usd と task_budget_usd を比較し、超過なら即 failed とする。",
      "sources": ["orgh/orchestrator/task_executor.py"]
    },
    {
      "id": "budget-003",
      "category": "budget",
      "difficulty": "internals",
      "type": "single",
      "question": "Budgetが「ミッション単位の固定上限」ではなく共有プールを split() で分配する設計になっている理由は。",
      "choices": [
        "サブミッション再帰を見据え、固定値だと子ミッションごとに上限が掛け算になって破綻するため",
        "並列タスク数に比例して上限を増やしたいため",
        "worker別にコストを按分して請求するため",
        "resume時に消費額をリセットするため"
      ],
      "answer": [0],
      "explanation": "ルートで確保したプールを親から子へ参照渡しし、子の charge() は親へ伝播、親の枯渇は子の exceeded() にも波及する。",
      "sources": ["orgh/state.py"]
    },
    {
      "id": "budget-004",
      "category": "budget",
      "difficulty": "internals",
      "type": "single",
      "question": "resume 時の setup_budget() の挙動として正しいものは。",
      "choices": [
        "ルートミッション(_parentがNone)は消費額を引き継ぎつつ上限だけconfigから再読込し、split()で割当を受けた子は上限を上書きしない",
        "常に上限も消費額もconfigから作り直す",
        "常に保存済みのBudgetをそのまま使う",
        "resume時は予算チェックを無効化する"
      ],
      "answer": [0],
      "explanation": "「予算を上げて続行できるように」ルートの上限のみ再読込する。子プールを上書きすると分配設計が壊れるため対象外。",
      "sources": ["orgh/orchestrator/budget_policy.py", "orgh/state.py"]
    },
    {
      "id": "budget-005",
      "category": "budget",
      "difficulty": "applied",
      "type": "single",
      "question": "累計コストに含まれるものはどれか。",
      "choices": [
        "Worker実行に加えてPlanner/Reviewer/Retroの呼び出しコストも含む",
        "Workerの実行コストのみ",
        "Planner/Reviewerのみ(Workerは別枠)",
        "APIコストは含まず所要時間のみ計上する"
      ],
      "answer": [0],
      "explanation": "ロール呼び出しも同じBudgetへ charge される。orgh status で累計コストと予算消化率(%)を確認できる。",
      "sources": ["README.md", "orgh/planner.py"]
    },
    {
      "id": "iso-001",
      "category": "isolation",
      "difficulty": "basic",
      "type": "single",
      "question": "worktree.enabled: true のとき、タスクごとに作られるworktreeパスとブランチ名の規則は。",
      "choices": [
        "<root>/<mission_id>-<task_id> と orgh/<mission_id>/<task_id>",
        "<root>/<task_id> と orgh-<task_id>",
        "<mission_id>/<task_id> と feature/<task_id>",
        "runs/<mission_id>/worktree と orgh/main"
      ],
      "answer": [0],
      "explanation": "root は worktree.root(既定 .orgh-worktrees、taskのworkdir相対)。worktreeはミッション終了後も残り、orgh cleanup <mission_id> で明示削除する。",
      "sources": ["orgh/worktree.py", "config.example.yaml"]
    },
    {
      "id": "iso-002",
      "category": "isolation",
      "difficulty": "applied",
      "type": "single",
      "question": "依存タスクのブランチのマージはどのタイミングで行われるか。",
      "choices": [
        "新規worktree作成時のみ。再利用worktree(差し戻し・resume)ではマージしない",
        "attemptのたびに毎回",
        "検収合格の直前に毎回",
        "ミッション終了時に一括で"
      ],
      "answer": [0],
      "explanation": "作業途中の状態に後からマージを重ねると衝突リスクの方が大きいため。マージ衝突時は git merge --abort してスキップし、タスク自体は止めない(成果は劣化するが検収で気づける)。",
      "sources": ["orgh/worktree.py"]
    },
    {
      "id": "iso-003",
      "category": "isolation",
      "difficulty": "internals",
      "type": "single",
      "question": "同一リポへの並列 git worktree add を threading.Lock で直列化している理由は。",
      "choices": [
        "git側の索引(index)破損を避けるため",
        "ブランチ名の衝突を避けるため",
        "ディスクI/Oを平準化するため",
        "worktree数の上限を守るため"
      ],
      "answer": [0],
      "explanation": "worktree作成は _LOCK で直列化される。合格タスクのコミットは identity を user.name=orgh / user.email=orgh@local と明示指定する(ホスト名変化で自動検出が壊れた実例があるため)。",
      "sources": ["orgh/worktree.py"]
    },
    {
      "id": "iso-004",
      "category": "isolation",
      "difficulty": "applied",
      "type": "single",
      "question": "copyback契約が必要になるのはどんな場合か。",
      "choices": [
        "宛先がgit管理外の領域で、worktree→branch→diff の受け渡しが空振りする場合",
        "worktreeを無効にしている場合すべて",
        "workerがcodexの場合",
        "成果物が1MBを超える場合"
      ],
      "answer": [0],
      "explanation": "workerが worktree直下の _orgh_staging/ に出力した成果物を、orgh-manifest.json(相対パス・サイズ・SHA-256)と照合しながら宛先ルートへ原子的にコピーバックする。",
      "sources": ["orgh/copyback.py"]
    },
    {
      "id": "iso-005",
      "category": "isolation",
      "difficulty": "internals",
      "type": "multi",
      "question": "copyback の検証で「拒否」されるものはどれか(複数選択)。",
      "choices": [
        "manifestに未列挙のstaging配下ファイル",
        "絶対パスや `..` を含むエントリ",
        "symlink",
        "staging配下のUTF-8以外のバイナリファイル"
      ],
      "answer": [0, 1, 2],
      "explanation": "パスは正規化のうえ worktree/staging/宛先の各ルートに閉包され、絶対パス・`..`・symlink・未列挙ファイルは拒否される。ファイル形式(バイナリか否か)は拒否条件ではない。",
      "sources": ["orgh/copyback.py"]
    },
    {
      "id": "iso-006",
      "category": "isolation",
      "difficulty": "internals",
      "type": "single",
      "question": "copyback の実行順序として正しいものは。",
      "choices": [
        "検収開始時(review遷移直後)にmanifest照合しstagingを凍結、合格後に再検証してから一時ディレクトリ→renameでコピー",
        "worker終了直後に即コピーし、検収はコピー後の実物に対して行う",
        "検収合格後に1度だけ照合してコピーする",
        "コピーは常に宛先へ直接1ファイルずつ書き込む"
      ],
      "answer": [0],
      "explanation": "両時点の照合結果は copyback.manifest として ledger に二重記録され、監査の正本だけで追える。コピーは「一時ディレクトリへ全量配置→再検証→rename」で途中失敗時の宛先汚染(copyback_partial)を防ぐ。",
      "sources": ["orgh/orchestrator/copyback_gate.py", "orgh/copyback.py"]
    },
    {
      "id": "iso-007",
      "category": "isolation",
      "difficulty": "applied",
      "type": "single",
      "question": "worktree直下に orgh-manifest.json が無いタスクではどうなるか。",
      "choices": [
        "start_review_gate() が None を返し、従来経路を一切変えない(後方互換が最優先)",
        "copybackエラーとしてタスクをfailedにする",
        "空のmanifestを自動生成する",
        "awaiting_human に遷移する"
      ],
      "answer": [0],
      "explanation": "copybackはmanifestが出力された場合にのみ発動するopt-in機構。copyback.allowed_roots も既定は空リスト(=無効)。",
      "sources": ["orgh/orchestrator/copyback_gate.py", "config.example.yaml"]
    },
    {
      "id": "iso-008",
      "category": "isolation",
      "difficulty": "internals",
      "type": "single",
      "question": "copyback の宛先事前hash突合による競合検知(copyback_conflict)の位置づけは。",
      "choices": [
        "暫定運用でありセキュリティ保証ではない(同時書き込みや悪意ある置き換えは検知できない)",
        "宛先の改ざんを検知できる完全な保証",
        "sandboxによる強制と同等の防御",
        "gitのpre-commit hookと同等の強制"
      ],
      "answer": [0],
      "explanation": "強制可能な土台(sandbox等)が入るまでの「忘れないための検知」でしかないと明記されている。",
      "sources": ["orgh/copyback.py"]
    },
    {
      "id": "know-001",
      "category": "knowledge",
      "difficulty": "applied",
      "type": "single",
      "question": "playbooksをプロンプトへ注入する際、上限字数(既定8000字)を超えた分はどう扱われるか。",
      "choices": [
        "全playbookの全行をメタデータ日付で降順ソートしてから詰めるため、古い教訓から溢れる",
        "ファイル先頭から順に詰めるため、後半のファイルが溢れる",
        "ランダムサンプリングされる",
        "要約モデルで圧縮される"
      ],
      "answer": [0],
      "explanation": "この「日付降順で詰める」方式により、playbookがどれだけ育っても最新の教訓が必ず注入される(=増幅の実体)。worker側の注入は max_chars=4000。",
      "sources": ["orgh/planner.py"]
    },
    {
      "id": "know-002",
      "category": "knowledge",
      "difficulty": "internals",
      "type": "single",
      "question": "Retroがplaybookへ追記するとき、メタデータコメント <!-- m:<mission_id> d:<date> --> が付くのはどの行か。",
      "choices": [
        "本文が `-` で始まる行のみ",
        "すべての行",
        "見出し行のみ",
        "ファイル末尾に1つだけ"
      ],
      "answer": [0],
      "explanation": "このメタデータを _playbook_context() が日付ソートに使う。人手で書いた(メタ無しの)行は \"0000-00-00\" 扱いで最古として扱われる。",
      "sources": ["orgh/planner.py"]
    },
    {
      "id": "know-003",
      "category": "knowledge",
      "difficulty": "applied",
      "type": "single",
      "question": "orgh resume で完走したミッションのRetroはどう扱われるか。",
      "choices": [
        "全タスクdoneかつ RETRO_DONE マーカーが無い場合のみ実行する",
        "resumeでは常にRetroを行わない",
        "resumeのたびに毎回Retroする",
        "resume時はRetroの代わりにgcを行う"
      ],
      "answer": [0],
      "explanation": "resumeで完走したミッションの教訓がplaybookに残らなかった実運用事例への対処。RETRO_DONE マーカーは3経路共通で二重追記を防ぐ。",
      "sources": ["orgh/cli.py"]
    },
    {
      "id": "know-004",
      "category": "knowledge",
      "difficulty": "internals",
      "type": "single",
      "question": "orgh gc が行う4段階の正しい順序は。",
      "choices": [
        "全量backup → 180日超の教訓をarchive → 統合Retroで重複解消 → retention_days超のrunsをruns/_archiveへ退避",
        "統合Retro → backup → archive → runs退避",
        "archive → 統合Retro → runs退避 → backup",
        "backup → runs退避 → 統合Retro → archive"
      ],
      "answer": [0],
      "explanation": "backupに失敗したらOSErrorで即中断し、playbooksには一切触れない。runsは削除ではなく runs/_archive/ への移動。",
      "sources": ["orgh/gc.py"]
    },
    {
      "id": "know-005",
      "category": "knowledge",
      "difficulty": "applied",
      "type": "single",
      "question": "watcherによるgcの自動起動について正しいものは。",
      "choices": [
        "watch.gc_interval_days ごとに1回実行し、stateファイルが無い初回パスはベースライン記録のみでgcを走らせない",
        "watch起動のたびに必ず1回gcする",
        "ミッション完了ごとにgcする",
        "自動起動は無く、必ず手動の orgh gc が必要"
      ],
      "answer": [0],
      "explanation": "初回パスでいきなり実playbooksを書き換えないための設計。既定は14日、null で無効。",
      "sources": ["orgh/watcher.py", "config.example.yaml"]
    },
    {
      "id": "know-006",
      "category": "knowledge",
      "difficulty": "basic",
      "type": "single",
      "question": "playbooks(教訓)と criteria(判断基準台帳)の役割分担として正しいものは。",
      "choices": [
        "playbooksは作業のやり方の教訓、criteriaは判断の一般原則(オーナー裁定由来)",
        "playbooksは仕様書、criteriaはテストケース",
        "playbooksはPlanner専用、criteriaはWorker専用",
        "両者は同じ内容の別形式のコピー"
      ],
      "answer": [0],
      "explanation": "criteriaはplaybooksと対をなす置き場で、Reviewer/ペルソナ検収に注入され、更新は下書き+承認のガバナンスを通る。",
      "sources": ["orgh/criteria.py", "playbooks/README.md"]
    },
    {
      "id": "rt-001",
      "category": "runtime",
      "difficulty": "applied",
      "type": "single",
      "question": "orgh cancel <mission_id> が別プロセスから実行中ミッションを止められる仕組みは。",
      "choices": [
        "runs/<mission_id>/CANCEL フラグファイルを置き、実行中プロセス自身がループごとに検知して停止する",
        "procregのプロセスレジストリを直接参照してSIGTERMを送る",
        "実行中プロセスへソケット経由でコマンドを送る",
        "mission.jsonのstatusを直接cancelledに書き換える"
      ],
      "answer": [0],
      "explanation": "procregはプロセス内メモリのdictで別プロセスからは触れないため、ファイルシステム経由のCANCELフラグが唯一の停止信号になっている。検知したプロセスが procreg.terminate() で subprocess を落とす。",
      "sources": ["orgh/orchestrator/cancellation.py", "orgh/procreg.py"]
    },
    {
      "id": "rt-002",
      "category": "runtime",
      "difficulty": "internals",
      "type": "single",
      "question": "cancellable_sleep() が素の time.sleep の代わりに使われる理由は。",
      "choices": [
        "リトライ待機中はterminate対象のsubprocessが無く、素のsleepだとキャンセルが最大 infra_wait 秒止まらないため",
        "sleepがGILを占有するため",
        "待機時間をledgerに記録するため",
        "待機中にheartbeatを打つため"
      ],
      "answer": [0],
      "explanation": "CANCELフラグを検知したら早期復帰してTrueを返す。",
      "sources": ["orgh/orchestrator/cancellation.py"]
    },
    {
      "id": "rt-003",
      "category": "runtime",
      "difficulty": "applied",
      "type": "single",
      "question": "orgh watch と orgh executor の分離(R-1)の狙いとして正しいものは。",
      "choices": [
        "watchが長時間ミッションにブロックされず新規ノートを数秒で検知でき、executor再起動でもキュー内容が失われない",
        "watchを複数台に分散して負荷分散するため",
        "executorがLLM呼び出しを行わずコストを下げるため",
        "watchだけでミッションを完結させるため"
      ],
      "answer": [0],
      "explanation": "既定の orgh watch は同プロセスにexecutorスレッドを併走させる互換運用で、完全分離は orgh watch --watch-only + 別プロセスの orgh executor。",
      "sources": ["orgh/executor.py", "orgh/cli.py"]
    },
    {
      "id": "rt-004",
      "category": "runtime",
      "difficulty": "internals",
      "type": "single",
      "question": "永続キュー(runs/_queue/)のclaimがコンシューマのkill -9でも固着しないのはなぜか。",
      "choices": [
        "claimはエントリファイルへのflockで行われ、プロセス死亡時にOSがflockを解放するため",
        "claim時刻をJSONに書き、一定時間で期限切れにするため",
        "watcherが定期的にclaimを掃除するため",
        "claimはメモリ上のみで管理されるため"
      ],
      "answer": [0],
      "explanation": "エントリ作成はtmp書き→renameの原子的作成、上限超は投入拒否、既存IDへの二重投入は冪等にTrue、完了で削除・失敗はclaim解除のみ。",
      "sources": ["orgh/queue.py"]
    },
    {
      "id": "rt-005",
      "category": "runtime",
      "difficulty": "applied",
      "type": "single",
      "question": "loop.parallel と loop.global_parallel の違いは。",
      "choices": [
        "parallelは1ミッション内の同時タスク枠、global_parallelはwatch/CLI/GUIを横断する全プロセスの総枠(runs/_slots/のflockセマフォ)",
        "parallelはタスク、global_parallelはミッションの同時数",
        "parallelはCPU数、global_parallelはメモリ上限",
        "どちらも同義で、後者は旧名"
      ],
      "answer": [0],
      "explanation": "global_parallel は既定 null(無効)で、明示しない限り従来挙動と完全に同一。ロール用の別枠は global_role_parallel。",
      "sources": ["config.example.yaml", "orgh/slots.py"]
    },
    {
      "id": "rt-006",
      "category": "runtime",
      "difficulty": "internals",
      "type": "single",
      "question": "スロット(orgh/slots.py)の待機について正しいものは。",
      "choices": [
        "FIFOは保証されない。待機時間は task.slot_wait イベントとしてledgerに記録する",
        "FIFOキューで公平に割り当てられる",
        "待機は最大30秒でタイムアウトしfailedになる",
        "スロットはプロセス終了後も明示解放が必要"
      ],
      "answer": [0],
      "explanation": "各waiterが独立に slot_0..N-1 を再走査するためFIFOは保証されない。スロットはfd保持中のみ占有され、kill -9を含むプロセス終了でOSが自動解放する。",
      "sources": ["orgh/slots.py", "orgh/orchestrator/task_executor.py"]
    },
    {
      "id": "rt-007",
      "category": "runtime",
      "difficulty": "internals",
      "type": "single",
      "question": "lease(runs/<mission_id>/lease.json)が導入された背景は。",
      "choices": [
        "procreg・ledgerのstart・mission.jsonのいずれも「再起動をまたいだ生存証拠」にならないため",
        "ミッションの実行順序を決めるため",
        "コストの上限を跨プロセスで共有するため",
        "GUIがミッション一覧をキャッシュするため"
      ],
      "answer": [0],
      "explanation": "HEARTBEAT_INTERVAL_SEC=30 で heartbeat を書き、LEASE_EXPIRY_SEC=120 を超えて更新が無ければプロセスは死んだとみなす。書き込みはtmp+os.replaceで原子的、読み取り側は欠損・破損を「leaseなし」として扱う。",
      "sources": ["orgh/lease.py"]
    },
    {
      "id": "rt-008",
      "category": "runtime",
      "difficulty": "internals",
      "type": "single",
      "question": "notify(人間接点イベント通知)の保証レベルとして正しいものは。",
      "choices": [
        "ledgerへの記録が必須の正本で、webhook送信はbest-effort(再送・順序・署名・dead-letterは持たない)",
        "webhook送信は再送付きで確実に配送される",
        "ledgerへの記録は任意で、webhookが正本",
        "通知はGUI起動時のみ発行される"
      ],
      "answer": [0],
      "explanation": "配送保証は外部基盤へ委譲する方針(ARCH-003: 制御意味論=orgh所有 / 実行メカニズム=委譲可)。event_id は (event_type, mission_id, task_id) から決定的に導出され、resume等での再発行でも同じ値になる。",
      "sources": ["orgh/notify.py"]
    },
    {
      "id": "rt-009",
      "category": "runtime",
      "difficulty": "internals",
      "type": "single",
      "question": "同一ミッションの二重実行はどう防がれているか。",
      "choices": [
        "run_mission がミッション単位のflock(プロセス間ロック)を非ブロッキングで取得する",
        "mission.jsonのstatusをrunningにして排他する",
        "キューのclaimのみで防ぐ",
        "防いでいない(利用者の運用責任)"
      ],
      "answer": [0],
      "explanation": "acquire_mission_lock() が flock(LOCK_EX|LOCK_NB) を取り、取得できなければ実行しない。executor側は run_mission のSystemExitを透過させる(別プロセスが完遂・finalizeする)。",
      "sources": ["orgh/orchestrator/scheduler.py", "orgh/executor.py"]
    },
    {
      "id": "rt-010",
      "category": "runtime",
      "difficulty": "internals",
      "type": "single",
      "question": "ミッション実行時のpromptsスナップショット(runs/<id>/prompts)を、prompts_dir自体の差し替えではなく _prompts_read_dir という別キーで行っている理由は。",
      "choices": [
        "prompts_dirを差し替えると自己改変ガードの保護対象判定まで変わってしまうため",
        "スナップショットの容量を節約するため",
        "GUIがprompts_dirを参照するため",
        "gcがprompts_dirを掃除対象にしているため"
      ],
      "answer": [0],
      "explanation": "読み取り先だけを別キーで上書きすることで、ガードの判定基準(prompts_dir/playbooks_dir)は元の設定のまま保たれる。criteriaにも同型の _criteria_read_dir がある。",
      "sources": ["orgh/planner.py", "orgh/orchestrator/scheduler.py"]
    },
    {
      "id": "src-001",
      "category": "source",
      "difficulty": "basic",
      "type": "single",
      "question": "orgh watch がノートを着火させる条件は。",
      "choices": [
        "本文に #go インラインタグがある、またはfrontmatterに orgh: go がある",
        "inboxフォルダに置かれている",
        "#mission タグが付いている",
        "ファイルが更新された"
      ],
      "answer": [0],
      "explanation": "inbox配置や mission_tag はあくまで「候補」としての認識で、誤爆防止のため明示タグを要求する二段階ゲート。さらに watch.stabilize_seconds(既定20秒)の経過も要求する。",
      "sources": ["orgh/sources/obsidian.py", "config.example.yaml"]
    },
    {
      "id": "src-002",
      "category": "source",
      "difficulty": "applied",
      "type": "single",
      "question": "着火後、元のノートへの書き込みはどうなるか。",
      "choices": [
        "結果ノートへのリンクが1行追記されるだけで、以後は書き込まない(競合安全writeback)",
        "進行状況が逐次上書きされる",
        "タスクごとにチェックボックスが追記される",
        "完了時に本文が結果ノートで置換される"
      ],
      "answer": [0],
      "explanation": "進行状況・差し戻し理由・検収ポイントは <vault>/orgh/results/<mission_id>.md に集約され、そちらが全文更新される。",
      "sources": ["orgh/sources/obsidian.py", "orgh/results.py"]
    },
    {
      "id": "src-003",
      "category": "source",
      "difficulty": "internals",
      "type": "single",
      "question": "文脈ダイジェスト(context_digest)の構築仕様として正しいものは。",
      "choices": [
        "wikilinkを depth(既定1)まで辿って連結し、max_chars(既定24000)で切り詰める",
        "vault全体を連結して最新の30ファイルに絞る",
        "MCP経由でObsidianに問い合わせる",
        "ノート本文のみで、リンク先は辿らない"
      ],
      "answer": [0],
      "explanation": "MCPのsandbox問題を避けるためファイルを直読みする。渡したダイジェストは runs/<id>/artifacts/context_digest.md に保存され「なぜこの計画になったか」の監査線になる。",
      "sources": ["orgh/sources/obsidian.py", "README.md"]
    },
    {
      "id": "src-004",
      "category": "source",
      "difficulty": "applied",
      "type": "single",
      "question": "Plannerへ渡す文脈ダイジェストが「参照データであり指示ではない」マーカーで包まれる理由は。",
      "choices": [
        "ノート内の命令文が計画を乗っ取る(prompt injection)のを防ぐため",
        "トークン数を削減するため",
        "Markdownの表示崩れを防ぐため",
        "Reviewerが同じ文脈を再利用できるようにするため"
      ],
      "answer": [0],
      "explanation": "守れていない範囲は docs/threat-model.md に明記されている。",
      "sources": ["README.md", "docs/threat-model.md"]
    },
    {
      "id": "src-005",
      "category": "source",
      "difficulty": "internals",
      "type": "single",
      "question": "処理済みノートの管理(WatchState)方式は。",
      "choices": [
        "ファイル内容のSHA-256先頭16文字をパスごとに runs/_watch_state.json に記録する(本文が変われば再着火)",
        "mtimeを記録する",
        "処理済みノートを別フォルダへ移動する",
        "frontmatterに processed: true を書き込む"
      ],
      "answer": [0],
      "explanation": "ハッシュ方式のため、ノートを編集し直せば再着火する。Planner失敗などミッション採番前のエラーも元ノートに [!failure] コールアウトで通知される。",
      "sources": ["orgh/sources/obsidian.py"]
    },
    {
      "id": "src-006",
      "category": "source",
      "difficulty": "applied",
      "type": "single",
      "question": "入力ソースの抽象化(SourceAdapter)について正しいものは。",
      "choices": [
        "config の source.type でアダプタを選択する設計だが、実装済みは ObsidianAdapter のみ",
        "ObsidianとNotionの2実装がある",
        "抽象化は無く、watcherが直接vaultを読む",
        "アダプタはRust側にある"
      ],
      "answer": [0],
      "explanation": "Notionアダプタは「SourceAdapter実装を足すだけ」の拡張候補として挙げられているが、コード上には存在しない。",
      "sources": ["orgh/sources/base.py", "README.md"]
    },
    {
      "id": "cli-001",
      "category": "cli",
      "difficulty": "basic",
      "type": "single",
      "question": "外部CLI疎通・config・書き込み権限を実行前に確認するコマンドは。",
      "choices": ["orgh doctor", "orgh status", "orgh report", "orgh scan"],
      "answer": [0],
      "explanation": "configが壊れているときこそ原因を報告できるよう、load_configの失敗時もdoctorだけはNGのDoctorReportを返す(GUIのSettings画面もこれに依存)。",
      "sources": ["orgh/cli.py", "orgh/doctor.py"]
    },
    {
      "id": "cli-002",
      "category": "cli",
      "difficulty": "applied",
      "type": "single",
      "question": "orgh resume の既定挙動として正しいものは。",
      "choices": [
        "cancelled/skipped 相当のタスクを attempts=0 の pending に戻す。failed も戻すには --retry-failed が必要",
        "failedタスクも含めてすべて pending に戻す",
        "pendingタスクのみ再実行し、他は触らない",
        "計画からやり直す"
      ],
      "answer": [0],
      "explanation": "予算を上げてからのresumeでskippedが復帰する運用もこの経路。",
      "sources": ["orgh/cli.py"]
    },
    {
      "id": "cli-003",
      "category": "cli",
      "difficulty": "applied",
      "type": "single",
      "question": "初回attempt合格率と差し戻し率の週次推移を出すコマンドは。",
      "choices": ["orgh report", "orgh list", "orgh events", "orgh playbooks"],
      "answer": [0],
      "explanation": "改善ループが効いているか(=増幅が実在するか)を測る最重要メトリクス。ミッション別コスト/所要時間・worker別失敗率も出す。--vault で vault にも書き出す。",
      "sources": ["orgh/report.py", "README.md"]
    },
    {
      "id": "cli-004",
      "category": "cli",
      "difficulty": "applied",
      "type": "multi",
      "question": "--json による機械可読出力(GUI連携用)に対応しているサブコマンドはどれか(複数選択)。",
      "choices": ["status", "list", "criteria list", "approve"],
      "answer": [0, 1, 2],
      "explanation": "--json 対応は list / doctor / events / status / report / playbooks / criteria list。approve は状態を変更する操作で --json を持たない(--yes のみ)。",
      "sources": ["orgh/cli.py"]
    },
    {
      "id": "cli-005",
      "category": "cli",
      "difficulty": "internals",
      "type": "single",
      "question": "orgh status --json のトップレベル verdicts フィールドの内容は。",
      "choices": [
        "runs/<mission_id>/verdicts.jsonl を古い順に配列化したもの",
        "未承認の基準下書き一覧",
        "Reviewerの合否履歴",
        "ペルソナ検収の結果のみ"
      ],
      "answer": [0],
      "explanation": "tasks[] には依頼一文 human_request と(awaiting_humanタスクのみ)依頼書全文 human_request_body が乗る。",
      "sources": ["orgh/status_json.py", "README.md"]
    },
    {
      "id": "cli-006",
      "category": "cli",
      "difficulty": "applied",
      "type": "single",
      "question": "done だが検収裁定(verdict)がまだのミッションを一覧するコマンドは。",
      "choices": [
        "orgh verdict --pending",
        "orgh list --json",
        "orgh criteria list",
        "orgh status --pending"
      ],
      "answer": [0],
      "explanation": "起票/完了/tasks/costをlistと同じ密度で出しつつ、角括弧内だけ状況に差し替えて優先順位付けに使う。",
      "sources": ["orgh/cli.py"]
    },
    {
      "id": "cfg-001",
      "category": "config",
      "difficulty": "basic",
      "type": "single",
      "question": "roles の既定モデル割り当てとして正しいものは。",
      "choices": [
        "planner=opus、reviewer=sonnet、retro=sonnet、workers=sonnet",
        "すべて opus",
        "planner=sonnet、reviewer=opus",
        "planner=fable 固定"
      ],
      "answer": [0],
      "explanation": "設計判断はOpus、実働・ゲートはSonnetの三層。長時間自律スプリントは model: fable に切替できる。",
      "sources": ["config.example.yaml", "README.md"]
    },
    {
      "id": "cfg-002",
      "category": "config",
      "difficulty": "applied",
      "type": "single",
      "question": "reviewer の max_turns を既定30と余裕を持たせているのはなぜか。",
      "choices": [
        "ビルド・テストの再実行を伴うレビューがあり、少ないと上限死するため",
        "Reviewerが複数タスクをまとめて見るため",
        "コストを平準化するため",
        "OpusよりSonnetのほうが1ターンあたりの出力が短いため"
      ],
      "answer": [0],
      "explanation": "Reviewerには Read/Bash を許可し、報告文ではなく実ファイル・テスト実行で判定させる方針。plannerの max_turns=40 も計画前の探索(Read/Glob)分を含む。",
      "sources": ["config.example.yaml"]
    },
    {
      "id": "cfg-003",
      "category": "config",
      "difficulty": "internals",
      "type": "single",
      "question": "worker へ渡す環境変数の既定ポリシーは。",
      "choices": [
        "KEY/TOKEN/SECRET/PASSWORD等の秘密パターンは継承させず、必要なものだけ env_secret_allow で通す",
        "親プロセスの環境変数をすべて継承する",
        "環境変数は一切渡さない",
        "worker種別ごとに固定のホワイトリストがあり変更できない"
      ],
      "answer": [0],
      "explanation": "prompt注入されたworkerによる漏洩防止。ANTHROPIC_API_KEY等の代表的な認証変数は既定で通す。",
      "sources": ["config.example.yaml"]
    },
    {
      "id": "cfg-004",
      "category": "config",
      "difficulty": "applied",
      "type": "single",
      "question": "projects_map を設定する目的は。",
      "choices": [
        "対象プロジェクトの絶対パスと説明の対応表をPlannerへ注入し、パス未記載のノートでも正しいリポでworkdirを解決させるため",
        "GUIのプロジェクト切替メニューを作るため",
        "worktreeのrootを決めるため",
        "gcの対象リポを列挙するため"
      ],
      "answer": [0],
      "explanation": "注入が無いとPlannerが workdir \".\" を出力してorgh自身のリポで実行されてしまう実運用の不具合が背景にある。",
      "sources": ["config.example.yaml", "orgh/planner.py"]
    },
    {
      "id": "cfg-005",
      "category": "config",
      "difficulty": "applied",
      "type": "single",
      "question": "worktree と copyback の既定値の組み合わせとして正しいものは。",
      "choices": [
        "worktree.enabled: false、copyback.allowed_roots: [](いずれも既定は無効)",
        "worktree.enabled: true、copyback.allowed_roots: [\"~\"]",
        "worktree.enabled: true、copyback は常時有効",
        "worktree.enabled: false、copyback は allowed_roots 無指定でも全パス許可"
      ],
      "answer": [0],
      "explanation": "どちらも後方互換を優先したopt-in。copybackのallowed_rootsは絶対パスのみ許可。",
      "sources": ["config.example.yaml"]
    },
    {
      "id": "adp-001",
      "category": "architecture",
      "difficulty": "applied",
      "type": "single",
      "question": "WorkerResult が正規化する5フィールドは。",
      "choices": [
        "ok / output / session_id / cost_usd / raw",
        "status / stdout / stderr / exit_code / duration",
        "ok / output / attempts / model / tokens",
        "pass / feedback / cost_usd / session_id / raw"
      ],
      "answer": [0],
      "explanation": "BaseAdapterはテンプレートメソッドで、サブクラスは _command() と _parse() だけ実装すればよい(「どのCLIエージェントも prompt in -> WorkerResult out に正規化する」)。",
      "sources": ["orgh/adapters/base.py"]
    },
    {
      "id": "adp-002",
      "category": "architecture",
      "difficulty": "applied",
      "type": "single",
      "question": "supports_resume が False のworker(codex等)への差し戻しはどう行われるか。",
      "choices": [
        "worker_prompt() で組み立てた元タスク一式を再度連結した自己完結プロンプトを渡す",
        "フィードバックのみを渡す",
        "セッションIDを再利用して continue する",
        "差し戻さずに即failedにする"
      ],
      "answer": [0],
      "explanation": "断片だけ受けたcodexが実装せず確認質問を返して失敗した実運用事例(7307189e t3)への対処。claude_code は supports_resume=True でフィードバックのみで足りる。",
      "sources": ["orgh/orchestrator/task_executor.py", "orgh/adapters/base.py"]
    },
    {
      "id": "adp-003",
      "category": "architecture",
      "difficulty": "internals",
      "type": "single",
      "question": "任意のCLI LLM(gemini等)をworkerとして使う枠は。",
      "choices": [
        "ShellAdapter(config.workers.shell.argv の {prompt} トークンを置換)",
        "ClaudeCodeAdapter に bin だけ差し替える",
        "CodexAdapter の extra_args を使う",
        "プラグインDLLを追加する"
      ],
      "answer": [0],
      "explanation": "アダプタは REGISTRY への登録で増やせる設計(get_adapter がタスクの worker フィールドから解決、既定は claude_code)。",
      "sources": ["orgh/adapters/base.py", "config.example.yaml"]
    },
    {
      "id": "desk-001",
      "category": "desktop",
      "difficulty": "basic",
      "type": "single",
      "question": "orgh Desktop の位置づけとして正しいものは。",
      "choices": [
        "同じ orgh CLI をサブプロセスとして呼び出す Tauri v2 製GUIラッパー(CLIの置き換えではなく派生)",
        "CLIを置き換える新しい実装",
        "Python製のWebアプリ",
        "orghサーバへ接続するリモートクライアント"
      ],
      "answer": [0],
      "explanation": "CLI(orgh/)⇔Rustブリッジ(desktop/src-tauri/)⇔React UI(desktop/src/)の連携契約は desktop/API.md と desktop/src/types.ts がSSOT。",
      "sources": ["README.md", "desktop/API.md"]
    },
    {
      "id": "desk-002",
      "category": "desktop",
      "difficulty": "applied",
      "type": "multi",
      "question": "orgh Desktop がGUIから行えるオーナー運用機能はどれか(複数選択)。",
      "choices": [
        "検収裁定(orgh verdict)",
        "人間依頼の完了報告(orgh humandone)",
        "基準台帳の下書き承認/棄却(orgh criteria approve/reject)",
        "playbooksのLLM統合(orgh gc)の手動実行"
      ],
      "answer": [0, 1, 2],
      "explanation": "第3期で検収裁定・人間依頼・基準台帳の3画面/機能が入った。GUIからのgc実行はREADMEに挙げられていない。",
      "sources": ["README.md"]
    },
    {
      "id": "meta-001",
      "category": "architecture",
      "difficulty": "basic",
      "type": "single",
      "question": "orghが「既知の割り切り」として明示しているものはどれか。",
      "choices": [
        "単一マシン・個人運用スケールであり、マルチテナントや分散実行は扱わない",
        "テストは存在せず手動検証のみ",
        "LLMを使わずルールベースで計画する",
        "Obsidianが必須である"
      ],
      "answer": [0],
      "explanation": "テストはモックCLI方式のSTを含む346件。Obsidianは任意で、中核ループ(計画→並列実行→レビュー→差し戻し→学習)はObsidianなしでも動く。",
      "sources": ["README.md"]
    }
  ]
};
