"""MCP(Model Context Protocol, 2025-06版)の最小stdioクライアント。

標準ライブラリのみで実装する(外部SDK不使用)。サーバをsubprocessとして起動し、
stdin/stdoutで改行区切りのJSON-RPC 2.0メッセージ(Content-Lengthフレーミングでは
ない、MCP stdio transportの流儀)をやり取りする。対応するメソッドは
initialize(+ notifications/initialized) / tools/list / tools/call の3つのみ
(resources/prompts/sampling等は対象外)。

    with McpClient(["notion-mcp-server"], env={...}) as client:
        client.initialize()
        tools = client.list_tools()
        result = client.call_tool("query_database", {"database_id": "..."})
"""
from __future__ import annotations

import json
import select
import subprocess
import threading
import time
from typing import Any

MCP_PROTOCOL_VERSION = "2025-06-18"


class McpError(Exception):
    """MCPサーバとの通信・プロトコル上のエラー全般。"""


class McpTimeoutError(McpError):
    """応答待ちがタイムアウトした。"""


class McpProcessError(McpError):
    """サーバプロセスの起動失敗、非0終了、または応答前の予期しない終了。"""


class McpProtocolError(McpError):
    """サーバから不正なJSON、または想定外のJSON-RPC形式が届いた。"""


class McpRpcError(McpError):
    """サーバがJSON-RPC 2.0 の error レスポンスを返した。"""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"MCP error {code}: {message}")


class McpClient:
    """MCPサーバをsubprocess起動し、stdioでJSON-RPC 2.0を話す最小クライアント。

    コンテキストマネージャとして使うこと。__exit__ でプロセスの終了処理
    (terminate -> 猶予後kill)を行う。
    """

    def __init__(self, command: list[str], env: dict[str, str] | None = None,
                 timeout: float = 30.0):
        if not command:
            raise ValueError("command が空: MCPサーバ起動コマンドが未設定")
        self._command = command
        self._env = env
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._id_lock = threading.Lock()

    def __enter__(self) -> "McpClient":
        try:
            self._proc = subprocess.Popen(
                self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=self._env, text=True, bufsize=1)
        except OSError as e:
            raise McpProcessError(
                f"MCPサーバの起動に失敗({self._command!r}): {e}") from e
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    # ------------------------------------------------------------ JSON-RPC I/O
    def _next_id(self) -> int:
        with self._id_lock:
            self._id += 1
            return self._id

    def _send(self, payload: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise McpProcessError("MCPサーバプロセスが起動していない")
        line = json.dumps(payload, ensure_ascii=False)
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise McpProcessError(f"MCPサーバへの書き込みに失敗: {e}") from e

    def _recv(self) -> dict:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise McpProcessError("MCPサーバプロセスが起動していない")
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpTimeoutError(
                    f"MCPサーバからの応答が{self._timeout}秒以内に届かない")
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                continue
            line = proc.stdout.readline()
            if line == "":
                # EOF: 応答を返す前にプロセスが終了した
                returncode = proc.wait(timeout=5)
                stderr = proc.stderr.read() if proc.stderr else ""
                raise McpProcessError(
                    f"MCPサーバが応答前に終了した(exit={returncode}): "
                    f"{stderr.strip()[:2000]}")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError as e:
                raise McpProtocolError(
                    f"MCPサーバから不正なJSON: {line[:500]!r}") from e

    def _request(self, method: str, params: dict | None = None) -> Any:
        req_id = self._next_id()
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method,
                    "params": params or {}})
        while True:
            resp = self._recv()
            if resp.get("id") != req_id:
                # 通知や別リクエストの応答は読み飛ばす(1リクエスト同時実行の前提)
                continue
            if "error" in resp:
                err = resp["error"] or {}
                raise McpRpcError(err.get("code", -1), err.get("message", ""),
                                   err.get("data"))
            return resp.get("result")

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # ------------------------------------------------------------------ MCP API
    def initialize(self, client_name: str = "orgh", client_version: str = "0.1.0") -> dict:
        result = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": client_version},
        })
        self._notify("notifications/initialized")
        return result or {}

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list")
        tools = (result or {}).get("tools")
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        result = self._request("tools/call", {
            "name": name, "arguments": arguments or {}})
        return result or {}
