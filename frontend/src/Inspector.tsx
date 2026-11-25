import { FileCode2, FlaskConical, ListTree } from "lucide-react";
import type { Check, Report } from "./bridge";

const tabs = [
  { id: "diff", title: "变更", icon: FileCode2 },
  { id: "checks", title: "验证", icon: FlaskConical },
  { id: "trace", title: "记录", icon: ListTree },
] as const;
export type InspectorTab = typeof tabs[number]["id"];

function CheckResult({ title, result }: { title: string; result: Check }) {
  const label = result.passed === null ? "未运行" : result.passed ? "通过" : "失败";
  return <section className="check"><h3>{title}<span className="chip">{label}</span></h3>
    <pre>{result.output || "没有测试输出"}</pre></section>;
}

export function Inspector({ report, tab, onTab, onLatest }: {
  report: Report | null; tab: InspectorTab; onTab: (tab: InspectorTab) => void; onLatest?: () => void;
}) {
  const files = report?.diff ? report.diff.split(/(?=^diff --git )/m) : [];
  return <aside className="inspector" aria-label="任务详情">
    <header className="inspector-title">任务详情{onLatest && <button className="turn-details" onClick={onLatest}>返回最新一轮</button>}</header>
    <nav className="inspector-tabs" aria-label="结果类型">
      {tabs.map(({ id, title, icon: Icon }) =>
        <button key={id} aria-pressed={tab === id} onClick={() => onTab(id)}><Icon size={15} />{title}</button>
      )}
    </nav>
    <div className="inspector-body">
      {!report && <p className="muted">运行任务后可查看变更和验证结果。</p>}
      {report && tab === "diff" && (files.length ? files.map((file, i) => {
        const lines = file.trimEnd().split("\n");
        const name = lines[0].replace(/^diff --git .* b\//, "");
        return <details className="diff" key={i} open>
          <summary><FileCode2 size={14} />{name || "补丁"}</summary>
          <pre>{lines.map((line, n) => <span key={n} className={
            line.startsWith("+++") || line.startsWith("---") ? "diff-meta" :
            line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" :
            line.startsWith("@@") ? "diff-meta" : undefined
          }>{line + "\n"}</span>)}</pre>
        </details>;
      }) : <p className="muted">这轮没有代码变更。</p>)}
      {report && tab === "checks" && <>
        {report.regression && <CheckResult title="回归测试" result={report.regression} />}
        {report.acceptance && <CheckResult title="独立验收" result={report.acceptance} />}
        {!report.regression && !report.acceptance && <p className="muted">本轮未执行验证。</p>}
      </>}
      {report && tab === "trace" && (report.trace.length ? report.trace.map((entry, i) =>
        <details className="trace" key={i}>
          <summary><strong>{entry.action}</strong> <span>{entry.path}</span></summary>
          <pre>{entry.detail}</pre>
        </details>
      ) : <p className="muted">本轮没有工具调用记录。</p>)}
    </div>
  </aside>;
}
