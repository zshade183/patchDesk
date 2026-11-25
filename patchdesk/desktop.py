"""Launch the bundled React workspace in a native desktop window."""
import mimetypes
import secrets
from hmac import compare_digest

from bottle import Bottle, abort, request, response, static_file

from .engine import ROOT
from .workspace import Workspace


class DesktopAPI:
    def __init__(self):
        self._workspace = Workspace()
        self._window = None

    def bootstrap(self):
        return self._workspace.bootstrap()

    def add_project(self):
        from webview import FileDialog

        selected = self._window.create_file_dialog(FileDialog.FOLDER)
        return self._workspace.add_project(selected[0]) if selected else None

    def select_project(self, path):
        return self._workspace.select_project(path)

    def report(self, run_id):
        return self._workspace.report(run_id)

    def submit(self, project, task, model, previous_id=None, retry=False):
        return self._workspace.submit(project, task, model, previous_id, retry)

    def example(self):
        return self._workspace.example()


def desktop_app(dist, api):
    app = Bottle()
    token = secrets.token_urlsafe(32)
    methods = {
        "bootstrap": api.bootstrap, "add_project": api.add_project,
        "select_project": api.select_project, "report": api.report,
        "submit": api.submit, "example": api.example,
    }

    @app.hook("before_request")
    def loopback_origin():
        if request.urlparts.hostname != "127.0.0.1":
            abort(403, "Local PatchDesk origin required")

    @app.get("/")
    def index():
        response.set_header("Cache-Control", "no-store")
        return (dist / "index.html").read_text(encoding="utf-8").replace(
            'content="__PATCHDESK_TOKEN__"', f'content="{token}"',
        )

    @app.get("/assets/<filename>")
    def assets(filename):
        return static_file(filename, root=str(dist / "assets"))

    @app.post("/api/<action>")
    def handle(action):
        candidate = request.get_header("X-PatchDesk-Token", "")
        if not compare_digest(candidate.encode("utf-8"), token.encode("ascii")):
            response.status = 403
            return {"error": "桌面请求验证失败"}
        method = methods.get(action)
        if method is None:
            response.status = 404
            return {"error": "未知桌面操作"}
        args = request.json
        if not isinstance(args, list):
            response.status = 400
            return {"error": "桌面请求参数格式错误"}
        try:
            return {"result": method(*args)}
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            response.status = 400
            return {"error": str(exc)}

    return app


def create_desktop_window(dist, api, **options):
    import webview

    # Windows may register .js as text/plain; JavaScript modules need a JS MIME type.
    mimetypes.add_type("text/javascript", ".js")
    api._window = webview.create_window("PatchDesk", desktop_app(dist, api), **options)
    return api._window


def main():
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("前端尚未构建。请运行 npm --prefix frontend ci 和 npm --prefix frontend run build。")

    import webview

    create_desktop_window(
        dist, DesktopAPI(), width=1320, height=860, min_size=(840, 600),
        background_color="#f7f8f4", text_select=True,
    )
    webview.start(gui="qt")
