"""Project preferences, conversation history and desktop task coordination."""
import json
import os
import re
import threading
import uuid
from pathlib import Path

from dotenv import dotenv_values

from . import engine
from .benchmark import CASES, example


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def failure_reason(report):
    error = report.get("error") or ""
    status = report["status"]
    if "KeyError" in error and "MODEL_ID" in error:
        return "缺少默认模型。请在输入框下方选择或输入模型 ID，再重试。"
    if error:
        return error
    if status == "达到轮数上限" or (status == "提前停止" and report.get("turns") == 12):
        return "已达到 12 轮上限。可以缩小提问范围后重新发送。"
    if status != "已结束":
        return status
    for key, title in (("regression", "回归测试"), ("acceptance", "独立验收")):
        if report.get(key, {}).get("passed") is False:
            return f"{title}未通过。请查看验证结果。"
    return ""


class Workspace:
    def __init__(self):
        self._prefs_path = engine.RUNS / "desktop.json"
        self._prefs = read_json(self._prefs_path) or {}
        self._prefs_lock = threading.Lock()
        self._task_lock = threading.Lock()

    def _settings(self):
        config = dotenv_values(engine.ROOT / ".env")
        default = os.getenv("MODEL_ID") or config.get("MODEL_ID")
        fallback = os.getenv("FALLBACK_MODEL_ID") or config.get("FALLBACK_MODEL_ID")
        with self._prefs_lock:
            return {
                "projects": list(self._prefs.get("projects", [])),
                "project": self._prefs.get("project", ""),
                "models": list(dict.fromkeys(m for m in [default, fallback, *self._prefs.get("models", [])] if m)),
                "model": self._prefs.get("model", "").replace("配置默认模型", ""),
                "defaultModel": default,
            }

    def _sessions(self):
        latest = {}
        candidates = sorted(engine.RUNS.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            report = read_json(path)
            if not report or not {"id", "task", "status", "mode"} <= report.keys():
                continue
            session = report.get("session_id") or report["id"]
            if session in latest:
                continue
            history = report.get("history") or []
            latest[session] = {
                "id": report["id"], "session_id": session,
                "title": report.get("session_title") or (history[0]["task"] if history else report["task"]),
                "project": report.get("project"), "mode": report["mode"],
                "status": report["status"], "failed": bool(failure_reason(report)),
            }
        return list(latest.values())

    def bootstrap(self):
        return {"settings": self._settings(), "sessions": self._sessions()}

    def add_project(self, path):
        root = Path(path).resolve(strict=True)
        top = Path(engine.git(root, "rev-parse", "--show-toplevel").strip()).resolve()
        return self.select_project(str(top))

    def select_project(self, path):
        with self._prefs_lock:
            projects = self._prefs.setdefault("projects", [])
            if path and path not in projects:
                projects.append(path)
            self._prefs["project"] = path
            save_json(self._prefs_path, self._prefs)
        return self._settings()

    def report(self, run_id):
        if not re.fullmatch(r"[0-9a-f]{32}", run_id or ""):
            raise ValueError("任务编号无效")
        report = read_json(engine.RUNS / run_id / "report.json")
        if not report:
            raise ValueError("找不到任务记录")
        return {**report, "failure": failure_reason(report)}

    def submit(self, project, task, model, previous_id=None, retry=False):
        parent = self.report(previous_id) if previous_id else None
        if parent and parent["mode"] == "scripted":
            if retry:
                return self.example(parent)
            raise ValueError("请先选择项目，再开启编程会话")
        history = list(parent.get("history", [])) if parent else []
        if parent:
            project = parent.get("project")
            if retry:
                task = parent["task"]
            else:
                history.append({key: parent[key] for key in ("id", "task", "answer", "status") if key in parent})
        task = (task or "").strip()
        model = (model or "").strip()
        if not project or not task:
            raise ValueError("请先选择 Git 项目并输入任务")
        with self._prefs_lock:
            models = self._prefs.setdefault("models", [])
            if model and model not in models:
                models.append(model)
            self._prefs["model"] = model
            save_json(self._prefs_path, self._prefs)
        return self._execute(
            lambda: engine.run(project, task, model=model or None, history=history),
            parent, task=task, project=project, model=model or None, history=history, mode="model",
        )

    def example(self, parent=None):
        case = next((key for key, value in CASES.items() if parent and value.task == parent["task"]), next(iter(CASES)))
        return self._execute(lambda: example(case), parent, task=CASES[case].task, history=[], mode="scripted")

    def _execute(self, action, parent, **details):
        if not self._task_lock.acquire(blocking=False):
            raise ValueError("已有任务正在运行")
        try:
            try:
                report = action()
            except (OSError, ValueError, RuntimeError) as exc:
                report = dict(id=uuid.uuid4().hex, status="执行失败", error=str(exc),
                              turns=0, seconds=0, trace=[], diff="", **details)
            report["session_id"] = (parent.get("session_id") or parent["id"]) if parent else report["id"]
            history = report.get("history") or []
            report["session_title"] = (history[0]["task"] if history else report["task"])
            save_json(engine.RUNS / report["id"] / "report.json", report)
            return {**report, "failure": failure_reason(report)}
        finally:
            self._task_lock.release()
