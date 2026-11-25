"""Local single-task coding assistant for trusted Python repositories."""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .usage import task_usage

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".runs"


def command(args, cwd, timeout=30):
    result = subprocess.run(args, cwd=cwd, capture_output=True, encoding="utf-8",
                            errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    return result.returncode, result.stdout + result.stderr


def git(cwd, *args):
    code, output = command(["git", *args], cwd)
    if code:
        raise ValueError(output[-2000:])
    return output


def run(repo, request, script=None, acceptance=None, mode="model", model=None, *, history=None):
    source = Path(repo).resolve(strict=True)
    if not source.is_dir() or not request.strip():
        raise ValueError("请选择仓库并填写需求")
    if Path(git(source, "rev-parse", "--show-toplevel").strip()).resolve() != source:
        raise ValueError("请输入 Git 仓库根目录")
    base = git(source, "rev-parse", "HEAD").strip()
    folder = RUNS / uuid.uuid4().hex
    folder.mkdir(parents=True)
    work = folder / "repo"
    git(folder, "clone", "--quiet", "--no-local", "--no-checkout", "--", str(source), str(work))
    git(work, "checkout", "--quiet", "--detach", base)
    files = git(work, "ls-files", "-z").split("\0")
    allowed = {
        path for path in files
        if (path.endswith(".py") or path.lower() in {"readme.md", "readme.rst", "readme.txt", "readme"})
        and not (work / path).is_symlink()
        and (work / path).resolve().is_relative_to(work)
    }
    tests = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    start = time.monotonic()
    trace = []
    report = dict(id=folder.name, mode=mode, base=base, project=str(source), model=model, task=request, trace=trace,
                  turns=0, status="达到轮数上限")
    if history:
        report["history"] = history
    job = folder / "job.json"
    job.write_text(json.dumps(dict(task=request, paths=sorted(allowed), script=script, model=model, history=history or [])), encoding="utf-8")
    try:
        code, output = command([sys.executable, str(Path(__file__).with_name("worker.py")), str(job)], work, timeout=600)
        if code:
            report.update(status="执行失败", error=output.strip().splitlines()[-1][:240] if output.strip() else "worker failed")
        else:
            report.update(json.loads((folder / "actions.json").read_text(encoding="utf-8")))
    except subprocess.TimeoutExpired:
        report.update(status="执行超时")
    report["usage"] = task_usage(folder / "usage.jsonl")
    report["diff"] = git(work, "diff", "--no-ext-diff", "HEAD")
    for name, args in [("regression", tests), ("acceptance", acceptance)]:
        if name == "regression" and not (work / "tests").is_dir():
            report[name] = dict(passed=None, output="项目没有 tests 目录，未运行 unittest。")
            continue
        if args:
            try:
                code, output = command(args, work)
                report[name] = dict(passed=code == 0 and (name != "regression" or "Ran 0 tests" not in output), output=output[-6000:])
            except subprocess.TimeoutExpired:
                report[name] = dict(passed=False, output="验证超时")
    report["seconds"] = round(time.monotonic() - start, 2)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
