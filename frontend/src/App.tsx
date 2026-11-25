import { ArrowUp, CircleAlert, FlaskConical, FolderOpen, GitBranch, LoaderCircle, MessageSquare, Plus, RotateCcw, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { desktopAPI } from "./bridge";
import type { Report, Session, Settings, Turn } from "./bridge";
import { Inspector } from "./Inspector";
import type { InspectorTab } from "./Inspector";

function basename(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

function ConversationTurn({ turn, onInspect }: { turn: Turn; onInspect?: () => void }) {
  return <>
    <article className="message question"><b>你</b><p>{turn.task}</p></article>
    {turn.answer && <article className="message answer"><b>PatchDesk</b>
      <Markdown skipHtml components={{
        a: ({ children }) => <span>{children}</span>,
        img: ({ alt }) => <span>{alt}</span>,
      }}>{turn.answer}</Markdown>
    </article>}
    {onInspect && <button className="turn-details" onClick={onInspect}>查看本轮任务详情</button>}
  </>;
}

export function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [inspected, setInspected] = useState<Report | null>(null);
  const [model, setModel] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [filtered, setFiltered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState<InspectorTab>("diff");
  const input = useRef<HTMLTextAreaElement>(null);
  const latest = useRef<HTMLDivElement>(null);
  const project = report?.mode === "model" ? report.project ?? settings?.project : settings?.project;
  const continuing = report?.mode === "model" && Boolean(report.project);
  const sessionId = report?.session_id ?? report?.id;
  const draftKey = continuing ? sessionId! : project ?? "";
  const text = drafts[draftKey] ?? "";
  const disabled = !settings || busy || loading;

  const failures = report?.failure;
  const visible = filtered ? sessions.filter(s => s.mode === "model" && s.project === settings?.project) : sessions;

  useEffect(() => {
    desktopAPI().then(api => api.bootstrap()).then(result => {
      setSettings(result.settings);
      setModel(result.settings.model);
      setSessions(result.sessions);
    }).catch(cause => setError(String(cause)));
  }, []);
  useEffect(() => {
    latest.current?.scrollIntoView({ block: "end" });
  }, [report, pending]);

  function newConversation() {
    setReport(null);
    setInspected(null);
    setError("");
    setTab("diff");
    input.current?.focus();
  }

  async function updateProject(path?: string) {
    setLoading(true);
    setError("");
    try {
      const api = await desktopAPI();
      const update = path === undefined ? await api.add_project() : await api.select_project(path);
      if (update) {
        setSettings(update);
        newConversation();
      }
    } catch (cause) {
      setError(String(cause));
    } finally {
      setLoading(false);
    }
  }

  async function openSession(session: Session) {
    setLoading(true);
    setError("");
    try {
      const api = await desktopAPI();
      const result = await api.report(session.id);
      setReport(result);
      setInspected(null);
      if (result.mode === "model" && result.model) setModel(result.model);
      setTab("diff");
    } catch (cause) {
      setError(String(cause));
    } finally {
      setLoading(false);
    }
  }

  async function inspectTurn(id: string) {
    setLoading(true);
    setError("");
    try {
      const api = await desktopAPI();
      setInspected(await api.report(id));
      setTab("diff");
    } catch (cause) {
      setError(String(cause));
    } finally {
      setLoading(false);
    }
  }

  async function run(demo = false, retry = false) {
    if (disabled) return;
    const task = retry ? report?.task ?? "" : text.trim();
    if (!demo && !retry && (!project || !task)) {
      setError("请先选择项目并输入任务。");
      return;
    }
    setBusy(true);
    setError("");
    setPending(demo ? "运行离线分页示例" : task);
    try {
      const api = await desktopAPI();
      const result = demo ? await api.example() :
        await api.submit(project ?? "", task, model, continuing || retry ? report?.id ?? null : null, retry);
      setReport(result);
      setInspected(null);
      setTab(result.mode === "scripted" && result.diff ? "diff" : result.failure && result.regression?.passed === false ? "checks" : "diff");
      if (demo) setFiltered(false);
      if (!demo && !retry) setDrafts(previous => ({ ...previous, [draftKey]: "" }));
      const data = await api.bootstrap();
      setSettings(data.settings);
      setSessions(data.sessions);
    } catch (cause) {
      setError(String(cause));
    } finally {
      setPending("");
      setBusy(false);
      input.current?.focus();
    }
  }

  return <div className="workspace">
    <aside className="sidebar" aria-label="项目和会话">
      <div className="brand"><span className="brand-icon"><Terminal size={21} /></span><strong>PatchDesk</strong></div>
      <button className="new" disabled={disabled} onClick={newConversation}><Plus size={18} />新建会话</button>
      <div className="side-heading"><label htmlFor="project">项目</label>
        <button className="icon-button" title="添加 Git 项目" aria-label="添加 Git 项目" disabled={disabled} onClick={() => void updateProject()}><FolderOpen size={16} /></button>
      </div>
      <select id="project" aria-label="切换项目" value={settings?.project ?? ""} disabled={disabled}
        onChange={event => void updateProject(event.target.value)}>
        <option value="" disabled>选择 Git 项目</option>
        {settings?.projects.map(path => <option key={path} value={path} title={path}>{basename(path)}</option>)}
      </select>
      <div className="side-heading sessions-heading"><span>会话</span>
        <label className="filter"><input type="checkbox" checked={filtered} onChange={e => setFiltered(e.target.checked)} />仅当前项目</label>
      </div>
      <div className="sessions">
        {visible.map(session => <button key={session.session_id} disabled={disabled}
          className={session.session_id === sessionId ? "session current" : "session"}
          title={session.title} onClick={() => void openSession(session)}>
          {session.failed ? <CircleAlert size={16} className="session-error" /> : <MessageSquare size={16} />}
          <span><strong>{session.title}</strong><small>{session.mode === "scripted" ? "离线示例" : session.project ? basename(session.project) : "历史项目"}</small></span>
        </button>)}
        {!visible.length && <p className="sidebar-empty">暂无会话</p>}
      </div>
      <button className="demo" disabled={disabled} onClick={() => void run(true)}><FlaskConical size={17} />运行离线示例</button>
    </aside>

    <main className="conversation">
      <header className="topbar">
        <span className="project-title" title={project}><GitBranch size={16} />{project ? basename(project) : "本地工作区"}</span>
        {report && <span className={"chip " + (report.mode === "scripted" ? "offline" : "")}>{report.mode === "scripted" ? "离线示例" : report.model || "模型任务"}</span>}
      </header>
      <div className="conversation-scroll">
        <div className="conversation-content">
          {!report && !pending && <div className="welcome">
            <span className="welcome-icon"><Terminal size={29} /></span>
            <h1>想在项目中做什么？</h1>
            <p>选择 Git 项目，提问或描述你想修改的内容。</p>
            {!project && <button className="secondary" disabled={disabled} onClick={() => void updateProject()}><FolderOpen size={16} />添加项目</button>}
          </div>}
          {report?.history?.map((turn, index) => <ConversationTurn key={index} turn={turn}
            onInspect={turn.id && !disabled ? () => void inspectTurn(turn.id!) : undefined} />)}
          {report && <ConversationTurn turn={report} />}
          {report && <div className="run-status">{report.status} · {report.turns} 轮 · {report.seconds} 秒</div>}
          {failures && <div className="alert" role="alert">
            <CircleAlert size={19} /><div><strong>这轮任务需要处理</strong><p>{failures}</p></div>
            {(report?.project || report?.mode === "scripted") &&
              <button className="secondary" disabled={disabled} onClick={() => void run(false, true)}><RotateCcw size={15} />重试</button>}
          </div>}
          {pending && <div className="pending" role="status"><LoaderCircle size={18} />正在处理 · {pending}</div>}
          {error && <div className="alert" role="alert"><CircleAlert size={19} /><p>{error}</p></div>}
          <div ref={latest} />
        </div>
      </div>
      <div className="composer-wrap">
        <form className="composer" onSubmit={e => { e.preventDefault(); void run(); }}>
          <textarea ref={input} aria-label={continuing ? "输入后续问题" : "输入任务"} value={text}
            placeholder={continuing ? "继续提问…" : "输入你的问题或修改需求…"} disabled={disabled}
            onChange={e => setDrafts(previous => ({ ...previous, [draftKey]: e.target.value }))}
            onKeyDown={e => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void run();
              }
            }} />
          <div className="composer-footer">
            <label className="model"><span>模型</span>
              <input list="models" value={model} onChange={e => setModel(e.target.value)} disabled={disabled}
                placeholder={settings?.defaultModel ?? "配置默认模型"} spellCheck={false} />
            </label>
            <datalist id="models">{settings?.models.map(id => <option key={id} value={id} />)}</datalist>
            <div className="send-actions"><kbd>Ctrl ↵</kbd>
              <button className="send" disabled={disabled || !text.trim()} type="submit">{continuing ? "继续提问" : "发送"}<ArrowUp size={17} /></button>
            </div>
          </div>
        </form>
      </div>
    </main>
    <Inspector report={inspected ?? report} tab={tab} onTab={setTab} onLatest={inspected ? () => setInspected(null) : undefined} />
  </div>;
}

