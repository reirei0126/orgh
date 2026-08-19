"""`orgh notion pull` / `orgh notion writeback`: Notion MCPサーバ経由の連携。

- 接続は必ずMCP経由(orgh/mcp_client.py)。Notion REST APIを直接叩かない。
- pull: 生成ノートには着火トリガタグ(vault.trigger_tag、既定 "go")を付けない。
  人間がNotion由来ノートを確認してから既存のObsidian経路(#go等)で着火する
  設計であり、watchへの新経路は作らない。
  冪等性: 取込済みページIDの台帳を <runs_dir>/_notion/pulled.json に
  {page_id: {"note": <相対パス>, "pulled_at": <epoch秒>}} として持つ。
  台帳に載っているpage_idは再pullしても新規ノートを作らず、既存ノートも
  上書きしない(スキップ)。
- writeback: doneミッションの結果サマリをMCP経由でNotionページとして作成
  するよう要求する(best-effort。詳細はwriteback()のdocstring参照)。
- トークンの値そのものはここにもconfigにも書かない。notion.token_env で
  指定した環境変数名をos.environから読み、MCPサーバの子プロセスへ渡す。
  未設定ならNotionConfigErrorで明示的に落ちる。
- ツール名(データベース照会・ページ本文取得・ページ作成)はMCPサーバ実装依存
  のため、候補名リストから解決する(_resolve_tool)。見つからなければ
  NotionToolResolutionErrorで明示的に落ちる。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import listing
from .mcp_client import McpClient, McpError
from .state import RunStore

DEFAULT_TOKEN_ENV = "OPENAPI_MCP_HEADERS"

# サーバ実装ごとにツール名が揺れるため、候補の先頭から一致するものを採用する。
# API-post-database-query / API-get-block-children はNotion公式MCPサーバ
# (notion-mcp-server, OpenAPI operationId直訳)の慣習に合わせた第一候補。
_DB_QUERY_TOOL_CANDIDATES = (
    "API-post-database-query",
    "query_database",
    "query-database",
    "queryDatabase",
    "notion_query_database",
)
_PAGE_CONTENT_TOOL_CANDIDATES = (
    "API-get-block-children",
    "get_block_children",
    "get-block-children",
    "getBlockChildren",
    "notion_get_page",
)
_CREATE_PAGE_TOOL_CANDIDATES = (
    "API-post-page",
    "create_page",
    "create-page",
    "createPage",
    "notion_create_page",
)

_SLUG_RE = re.compile(r"[^\w\-ぁ-んァ-ヶ一-龠ー]+")


class NotionError(Exception):
    """Notion連携全般のエラー(pull()呼び出し元がユーザ向けメッセージとして表示可)。"""


class NotionDisabledError(NotionError):
    """notion.mcp_command が未設定(Notion連携が無効)。"""


class NotionConfigError(NotionError):
    """必須config・環境変数の欠落。"""


class NotionToolResolutionError(NotionError):
    """MCPサーバのtools/listから必要なツールを解決できなかった。"""


class NotionWritebackStateError(NotionError):
    """doneでないミッションへのwritebackを実行前に明示的に拒否する。
    best-effort扱い(MCP接続失敗等)とは区別し、これは常に例外で落ちる。"""


class _Ledger:
    """取込済みNotionページIDの冪等台帳。

    パス: <runs_dir>/_notion/pulled.json
    形式: {page_id: {"note": <note_pathのstr>, "pulled_at": <epoch秒>}}
    """

    def __init__(self, runs_dir: str | Path):
        self.fp = Path(runs_dir) / "_notion" / "pulled.json"
        self.data: dict[str, dict] = (
            json.loads(self.fp.read_text()) if self.fp.exists() else {})

    def has(self, page_id: str) -> bool:
        return page_id in self.data

    def mark(self, page_id: str, note_path: str) -> None:
        self.data[page_id] = {"note": note_path, "pulled_at": time.time()}
        self.fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))
        os.replace(tmp, self.fp)


def _resolve_tool(tools: list[dict], candidates: tuple[str, ...], purpose: str) -> str:
    names = {t.get("name") for t in tools if isinstance(t, dict) and t.get("name")}
    for c in candidates:
        if c in names:
            return c
    lowered = {n.lower(): n for n in names if isinstance(n, str)}
    for c in candidates:
        if c.lower() in lowered:
            return lowered[c.lower()]
    raise NotionToolResolutionError(
        f"{purpose}用のツールが見つからない"
        f"(候補: {list(candidates)} / サーバ提供ツール: {sorted(n for n in names if n)})")


def _extract_result_data(result: dict) -> Any:
    """tools/call の結果(MCP 2025-06のCallToolResult)から中身を取り出す。

    isError=trueは例外化。structuredContentがあればそれを優先し、無ければ
    contentのtextブロックを連結してJSONとして解釈を試みる(ダメなら生文字列)。
    """
    if result.get("isError"):
        content = result.get("content") or []
        text = " ".join(
            c.get("text", "") for c in content if isinstance(c, dict))
        raise NotionError(f"MCPツール呼び出しがエラーを返した: {text[:500]}")
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content") or []
    text = "".join(
        c.get("text", "") for c in content
        if isinstance(c, dict) and c.get("type") == "text")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _as_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    return []


def _page_title(page: dict) -> str:
    props = page.get("properties") or {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            text = "".join(
                seg.get("plain_text", "") for seg in (prop.get("title") or [])
                if isinstance(seg, dict))
            if text:
                return text
    return page.get("id", "untitled")


def _blocks_to_body(blocks: list) -> str:
    """Notionブロック配列からplain_textを再帰的でなく素朴に連結して本文化する。
    想定と異なる形状のブロックはJSONのまま添える(情報を握りつぶさない)。"""
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        payload = block.get(btype) if btype else None
        rich = (payload or {}).get("rich_text") if isinstance(payload, dict) else None
        if isinstance(rich, list):
            text = "".join(
                seg.get("plain_text", "") for seg in rich if isinstance(seg, dict))
            if text:
                lines.append(text)
                continue
        lines.append(f"```json\n{json.dumps(block, ensure_ascii=False, indent=2)}\n```")
    return "\n\n".join(lines)


def _slugify(title: str, page_id: str) -> str:
    slug = _SLUG_RE.sub("-", title).strip("-")
    if not slug:
        slug = "notion"
    return f"notion-{slug}-{page_id[:8]}"


def _write_note(inbox_dir: Path, mission_tag: str, page: dict, body: str) -> Path:
    title = _page_title(page)
    fname = _slugify(title, page["id"]) + ".md"
    note_path = inbox_dir / fname
    frontmatter = (
        "---\n"
        f"tags: [{mission_tag}]\n"
        f"notion_page_id: {page['id']}\n"
        f"notion_url: {page.get('url', '')}\n"
        "source: notion\n"
        "---\n"
    )
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(f"{frontmatter}\n# {title}\n\n{body}\n")
    return note_path


def pull(cfg: dict) -> list[Path]:
    """Notion MCP経由で未取込ページをvault inboxへミッションノートとして書き出す。

    戻り値は今回新規に書き出したノートのパス一覧(取込済みでスキップした分は
    含まない)。設定・環境変数不足はNotionError系の例外で明示的に落ちる。
    """
    ncfg = cfg.get("notion") or {}
    mcp_command = ncfg.get("mcp_command") or []
    if not mcp_command:
        raise NotionDisabledError(
            "notion.mcp_command が未設定。Notion連携は無効(config.yamlのnotion"
            "セクションでMCPサーバ起動コマンドを指定すること)")

    database_id = ncfg.get("database_id")
    if not database_id:
        raise NotionConfigError("notion.database_id が未設定")

    token_env = ncfg.get("token_env") or DEFAULT_TOKEN_ENV
    token_value = os.environ.get(token_env)
    if not token_value:
        raise NotionConfigError(
            f"環境変数 {token_env} が未設定。Notion MCPサーバへ渡す認証情報が無い"
            f"(notion.token_env で指定した環境変数を先にexportすること)")

    vcfg = cfg.get("vault") or {}
    vault_path = vcfg.get("path")
    if not vault_path:
        raise NotionConfigError("vault.path が未設定。Notion取込先のinboxを決められない")
    inbox_dir = Path(vault_path).expanduser() / vcfg.get("inbox", "inbox")
    mission_tag = vcfg.get("mission_tag", "mission")

    ledger = _Ledger(cfg.get("runs_dir", "runs"))
    child_env = {**os.environ, token_env: token_value}

    written: list[Path] = []
    with McpClient(mcp_command, env=child_env) as client:
        client.initialize()
        tools = client.list_tools()
        query_tool = _resolve_tool(tools, _DB_QUERY_TOOL_CANDIDATES, "データベース照会")
        content_tool = _resolve_tool(
            tools, _PAGE_CONTENT_TOOL_CANDIDATES, "ページ本文取得")

        query_result = client.call_tool(query_tool, {"database_id": database_id})
        pages = _as_list(_extract_result_data(query_result))

        for page in pages:
            if not isinstance(page, dict):
                continue
            page_id = page.get("id")
            if not page_id or ledger.has(page_id):
                continue
            content_result = client.call_tool(content_tool, {"block_id": page_id})
            blocks = _as_list(_extract_result_data(content_result))
            body = _blocks_to_body(blocks)
            note_path = _write_note(inbox_dir, mission_tag, page, body)
            ledger.mark(page_id, str(note_path))
            written.append(note_path)

    return written


def _mission_branches(mission) -> list[str]:
    """タスクごとの成果物ブランチ名(orgh/worktree.pyが t.branch に設定する
    f"orgh/{mission_id}/{task.id}"形式)を、登場順・重複無しで集める。"""
    branches: list[str] = []
    for t in mission.tasks:
        if t.branch and t.branch not in branches:
            branches.append(t.branch)
    return branches


def _writeback_summary_children(intent: str, verdict_present: bool,
                                 cost_usd: float, branches: list[str]) -> list[dict]:
    lines = [
        f"intent: {intent}",
        f"verdict: {'あり' if verdict_present else 'なし'}",
        f"cost_usd: {cost_usd:.4f}",
        f"branch: {', '.join(branches) if branches else '(なし)'}",
    ]
    return [
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [
             {"type": "text", "text": {"content": line}}]}}
        for line in lines
    ]


def writeback(cfg: dict, mission_id: str) -> dict:
    """doneミッションの結果サマリを、MCP経由でNotionページとして作成するよう要求する。

    読み出しは既存API限定: ミッション状態は RunStore.load(reset_inflight=False)
    (読み取り専用。実行中系ステータスの巻き戻しをしない)で、verdict有無は
    listing.has_verdict() で取得する(新しい読み出し経路は作らない)。

    doneでないミッション(全タスクが status=="done" ではない、またはtasksが
    空)を指定した場合は NotionWritebackStateError で即座に落ちる — これは
    MCP呼び出しの前に判定するため、MCPサーバへは一切接続しない。config不備
    (mcp_command/database_id/token_env)も同様にNotionError系で即座に落ちる。

    doneミッションに対するMCP呼び出し以降はbest-effort: MCP接続失敗
    (McpProcessError/McpTimeoutError)・ツール未解決(NotionToolResolutionError)・
    JSON-RPCエラー(McpRpcError)・isError付きCallToolResult(NotionError)の
    いずれが起きても例外を外へ伝播させない。この関数はいかなる分岐でも
    store.save()等ミッション状態の書き換えを一切行わない(読むだけ)ため、
    MCP側の失敗でミッションのledger/stateが変化することはない
    (orgh/notify.pyのA1out — 冪等な識別子・失敗を握って続行・記録は残す、と
    同じ流儀。ここでの「記録」はledgerへの追記ではなくCLI出力に委ねる)。

    戻り値は {"ok": bool, "error": str | None}。呼び出し元CLI
    (orgh notion writeback)はconfig不備・doneでないミッション指定のみを
    非0終了とし、MCP起因のbest-effortな失敗(ok=False)はorgh notion pullの
    設定不備時と同様の「明示的な不備は落とす」方針とは別物として0終了で
    扱う(実行はできたが連携が届かなかっただけであり、ミッション進行を
    妨げるべきではないため)。
    """
    ncfg = cfg.get("notion") or {}
    mcp_command = ncfg.get("mcp_command") or []
    if not mcp_command:
        raise NotionDisabledError(
            "notion.mcp_command が未設定。Notion連携は無効(config.yamlのnotion"
            "セクションでMCPサーバ起動コマンドを指定すること)")

    database_id = ncfg.get("database_id")
    if not database_id:
        raise NotionConfigError("notion.database_id が未設定")

    token_env = ncfg.get("token_env") or DEFAULT_TOKEN_ENV
    token_value = os.environ.get(token_env)
    if not token_value:
        raise NotionConfigError(
            f"環境変数 {token_env} が未設定。Notion MCPサーバへ渡す認証情報が無い"
            f"(notion.token_env で指定した環境変数を先にexportすること)")

    store = RunStore(cfg.get("runs_dir", "runs"), mission_id)
    mission = store.load(reset_inflight=False)  # 読むだけ。実行状態は触らない
    if not mission.tasks or any(t.status != "done" for t in mission.tasks):
        raise NotionWritebackStateError(
            f"mission '{mission_id}' はdoneではない(writebackは実行しない)")

    verdict_present = listing.has_verdict(store.dir)
    cost_usd = mission.budget.spent_usd if mission.budget else 0.0
    branches = _mission_branches(mission)
    title = f"orgh mission {mission.id}: {mission.intent}"[:200]

    child_env = {**os.environ, token_env: token_value}
    try:
        with McpClient(mcp_command, env=child_env) as client:
            client.initialize()
            tools = client.list_tools()
            create_tool = _resolve_tool(
                tools, _CREATE_PAGE_TOOL_CANDIDATES, "ページ作成")
            arguments = {
                "parent": {"database_id": database_id},
                "properties": {
                    "title": {"title": [
                        {"type": "text", "text": {"content": title}}]},
                },
                "children": _writeback_summary_children(
                    mission.intent, verdict_present, cost_usd, branches),
            }
            result = client.call_tool(create_tool, arguments)
            _extract_result_data(result)  # isError=true を例外化させるためだけに呼ぶ
    except (NotionError, McpError) as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True, "error": None}
