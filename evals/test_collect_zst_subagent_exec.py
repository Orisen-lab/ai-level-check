#!/usr/bin/env python3
"""三個漏算情境：
1. Codex 把舊對話壓成 .jsonl.zst，本人操作要讀得到。
2. codex exec（被別的 agent 或排程呼叫）thread_source 也寫 "user"，要算自動化，不是本人。
3. Claude Code 子代理紀錄在 <專案>/<主對話>/subagents/ 底下，要算進子代理。
"""
import json
import pathlib
import runpy
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECT = ROOT / "scripts" / "collect.py"


def codex_session(originator, source, text):
    return [
        {"timestamp": "2026-10-01T10:00:00Z", "type": "session_meta",
         "payload": {"originator": originator, "source": source, "thread_source": "user",
                     "cwd": "/tmp/fixture"}},
        {"timestamp": "2026-10-01T10:00:05Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]}},
    ]


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")


def compress(path):
    try:
        import zstandard  # type: ignore
        data = zstandard.ZstdCompressor().compress(path.read_bytes())
        path.with_name(path.name + ".zst").write_bytes(data)
    except ImportError:
        subprocess.run(["zstd", "-q", "--rm", str(path)], check=True)
        return
    path.unlink()


def main():
    try:
        import zstandard  # noqa: F401  # type: ignore
        has_zst = True
    except ImportError:
        has_zst = bool(shutil.which("zstd"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        codex = tmp / "codex" / "sessions" / "2026" / "10" / "01"
        desktop = codex / "rollout-2026-10-01T10-00-00-desktop.jsonl"
        write_jsonl(desktop, codex_session("Codex Desktop", "vscode", "幫我想三個首頁標題"))
        if has_zst:
            compress(desktop)
        write_jsonl(codex / "rollout-2026-10-01T10-00-00-exec.jsonl",
                    codex_session("codex_exec", "exec", "Generate 5 separate images"))

        claude = tmp / "claude" / "projects" / "fixture"
        write_jsonl(claude / "main-1.jsonl", [
            {"type": "user", "timestamp": "2026-10-01T11:00:00+08:00", "entrypoint": "claude-desktop",
             "origin": {"kind": "human"}, "message": {"content": "幫我整理這份文件"}},
            {"type": "assistant", "timestamp": "2026-10-01T11:00:05+08:00",
             "message": {"content": [{"type": "tool_use", "name": "Agent", "input": {}}]}},
        ])
        write_jsonl(claude / "main-1" / "subagents" / "agent-abc.jsonl", [
            {"type": "user", "timestamp": "2026-10-01T11:00:06+08:00", "isSidechain": True,
             "message": {"content": "探索專案目錄，回報結構"}},
            {"type": "assistant", "timestamp": "2026-10-01T11:00:09+08:00", "isSidechain": True,
             "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
        ])

        out = tmp / "evidence"
        old_argv = sys.argv
        try:
            sys.argv = [str(COLLECT), "--claude-root", str(tmp / "claude"),
                        "--codex-root", str(tmp / "codex"), "--source", "claude-code,codex",
                        "--since", "2026-09-30", "--until", "2026-10-02", "--out", str(out)]
            runpy.run_path(str(COLLECT), run_name="__main__")
        finally:
            sys.argv = old_argv

        s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        split, habitats = s["session_split"], s["habitats"]

        assert split["subagent"] == 1, split
        assert habitats["automation_by_source"].get("codex") == 1, habitats
        if has_zst:
            assert habitats["human_by_source"].get("codex") == 1, habitats
            assert "unread_compressed" not in s, s.get("unread_compressed")
        assert habitats["human_by_source"].get("claude-code") == 1, habitats
        print("ok" + ("" if has_zst else "（本機沒有 zstd，壓縮檔情境略過）"))


if __name__ == "__main__":
    main()
