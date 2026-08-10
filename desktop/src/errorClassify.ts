// P0-5(エラーメッセージのわかりやすい言い換え)のための純粋関数群。
// desktop/API.md/desktop/src-tauri/src/cli.rs のエラー整形規則(の起動に失敗/
// stderrそのまま転送/非0終了コード時のフォールバック文言)と、orgh CLI本体
// (orgh/state.py load_config, orgh/cli.py `note '<name>' not found` 等)が
// 実際に出す文字列を踏まえてパターンマッチする。ここはReactに依存しない
// 純粋関数のみを置き、UI側(MissionListPage/NewMissionPage/ErrorBanner)から
// 呼び出す。判別できないパターンは "unknown" にフォールバックし、生の
// エラーメッセージを失わせない。

export type ListErrorCategory =
  | "orgh_bin_not_found"
  | "config_missing"
  | "vault_invalid"
  | "config_syntax"
  | "unknown";

export interface ListErrorInfo {
  category: ListErrorCategory;
  /** バナーの主見出し。 */
  title: string;
  /** 原因別の次のアクション案内(日本語)。 */
  guidance: string;
}

/**
 * 一覧取得失敗(list_missions)の生エラーメッセージから、可能な範囲で原因を
 * 判別する。judge順は「より具体的なパターン」を先に見る
 * (例: config自体が無い場合のFileNotFoundErrorメッセージにも"config"という
 * 語は出るため、config_missingをconfig_syntaxより先に判定する)。
 */
export function classifyListError(raw: string): ListErrorInfo {
  // Rust側 cli::run_json / run_sync / spawn_and_bridge が子プロセスの
  // spawn自体に失敗したときに必ずこの文言を使う(desktop/src-tauri/src/cli.rs)。
  if (/の起動に失敗/.test(raw)) {
    return {
      category: "orgh_bin_not_found",
      title: "orghコマンドが見つかりません",
      guidance:
        "設定画面の「orghバイナリ」のパスが正しいか確認してください。ターミナルで実際に実行できるパス(例: `which orgh`の結果)を設定してください。",
    };
  }

  // orgh/state.py load_config() が config.yaml 自体が存在しないときに
  // 出す固定文言(未捕捉例外のtracebackとしてstderrに流れてくる)。
  if (/not found\. copy config\.example\.yaml/.test(raw)) {
    return {
      category: "config_missing",
      title: "config.yamlが見つかりません",
      guidance:
        "設定画面の「configパス」が正しいか確認してください。まだ作成していない場合は config.example.yaml をコピーして config.yaml を作成してください。",
    };
  }

  // orgh/doctor.py がvaultチェックで出す detail 文言("<path> に到達できない" /
  // "<path> に書き込めない")を含む場合。
  if (/vault/.test(raw) && /(に到達できない|に書き込めない)/.test(raw)) {
    return {
      category: "vault_invalid",
      title: "vaultのパスが正しくありません",
      guidance:
        "config.yamlの vault.path が実在するディレクトリを指しているか、書き込み権限があるかを確認してください。vault(Obsidian連携)を使わない場合は vault 設定自体を省略できます。",
    };
  }

  // orgh/state.py validate_config() の ConfigError、または
  // yaml.safe_load() が投げるYAML構文エラー(yaml.scanner.ScannerError /
  // yaml.parser.ParserError 等)。
  if (/ConfigError|config: |config全体が|yaml\.scanner|yaml\.parser|YAMLError/.test(raw)) {
    return {
      category: "config_syntax",
      title: "config.yamlの内容に誤りがあります",
      guidance:
        "config.yamlの構文(YAML形式・必須キーの有無)を確認してください。config.example.yamlと見比べると原因を特定しやすくなります。",
    };
  }

  return {
    category: "unknown",
    title: "ミッション一覧を取得できませんでした",
    guidance:
      "原因を自動判別できませんでした。下記の詳細を確認するか、設定画面からorghコマンドとconfigの場所を見直してください。",
  };
}

/**
 * note指定モードでの起動失敗が「ノートが見つからない」ケースかどうかを
 * 判定する。orgh/cli.py の `sys.exit(f"note '{args.note}' not found")` が
 * 出す固定文言(desktop/src-tauri/src/cli.rs のspawn_and_bridgeがstderr末尾
 * を含めて包んだ後でも部分一致で検出できる)を対象にする。該当しなければ
 * nullを返し、呼び出し側は生メッセージをそのまま使うこと。
 */
export function classifyNoteNotFound(raw: string): string | null {
  if (/note '.*' not found/.test(raw)) {
    return "ノートが見つかりません。ノート名の綴りを確認するか、vault内の実ファイル名と照合してください。";
  }
  return null;
}

/**
 * ErrorBanner向けの合成文字列を作る区切り。ErrorBanner側はこの区切りを
 * 検出したら、区切り以前を主要文言、以降を折りたたみ表示の詳細として扱う。
 * 区切りが無い文字列(従来通りの単純なメッセージ)は全文をそのまま表示する
 * (他画面からの呼び出しに対する後方互換)。
 */
export const ERROR_DETAIL_SEPARATOR = "\n\n[詳細(元のエラーメッセージ)]\n";

/** 主要文言(friendly)と生メッセージ(raw)をERROR_DETAIL_SEPARATORで連結する。
 * 両者が同一内容なら情報を重複させず raw のみを返す。 */
export function withDetail(friendly: string, raw: string): string {
  if (friendly.trim() === raw.trim()) return raw;
  return `${friendly}${ERROR_DETAIL_SEPARATOR}${raw}`;
}
