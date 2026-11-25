export interface Turn {
  id?: string;
  task: string;
  answer?: string;
  status?: string;
}
export interface Check {
  passed: boolean | null;
  output: string;
}
export interface Report extends Turn {
  id: string;
  session_id?: string;
  project?: string;
  mode: "model" | "scripted";
  model?: string;
  status: string;
  failure: string;
  history?: Turn[];
  seconds: number;
  turns: number;
  diff: string;
  regression?: Check;
  acceptance?: Check;
  trace: { action: string; path: string; detail: string }[];
}
export interface Session {
  id: string;
  session_id: string;
  title: string;
  project?: string;
  mode: Report["mode"];
  status: string;
  failed: boolean;
}
export interface Settings {
  project: string;
  projects: string[];
  model: string;
  models: string[];
  defaultModel: string | null;
}
interface DesktopAPI {
  bootstrap(): Promise<{ settings: Settings; sessions: Session[] }>;
  add_project(): Promise<Settings | null>;
  select_project(path: string): Promise<Settings>;
  report(id: string): Promise<Report>;
  submit(project: string, task: string, model: string, previousId: string | null, retry: boolean): Promise<Report>;
  example(): Promise<Report>;
}

export async function desktopAPI(): Promise<DesktopAPI> {
  const token = document.querySelector<HTMLMetaElement>('meta[name="patchdesk-token"]')?.content;
  if (!token || token === "__PATCHDESK_TOKEN__") throw new Error("请通过 PatchDesk.cmd 启动桌面应用。");

  async function call<T>(action: string, ...args: unknown[]): Promise<T> {
    const response = await fetch(`/api/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-PatchDesk-Token": token! },
      body: JSON.stringify(args),
    });
    const body = await response.json() as { result: T; error?: string };
    if (!response.ok) throw new Error(body.error ?? "桌面请求失败");
    return body.result;
  }

  return {
    bootstrap: () => call("bootstrap"),
    add_project: () => call("add_project"),
    select_project: path => call("select_project", path),
    report: id => call("report", id),
    submit: (...args) => call("submit", ...args),
    example: () => call("example"),
  };
}
