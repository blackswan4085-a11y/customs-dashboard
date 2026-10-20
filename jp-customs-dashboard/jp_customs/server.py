"""stdlib http.server 기반 대시보드 서버. 외부 웹 프레임워크 없음.

라우트:
  GET  /                       메인 페이지(HTML)
  GET  /api/meta               수집 메타
  GET  /api/overview           종합 개요(세계 합계)
  GET  /api/level?code=&level=  하위 레벨 집계 표
  GET  /api/detail?code=        선택 코드 상세(시계열+YoY+QoQ+국가순위+관련기업)
  POST /api/company/add | /delete
  POST /api/collect  + GET /api/collect/status
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import db
from .config import Config
from .report import page_html


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


_collect_state = {"running": False, "phase": "idle", "message": "", "index": 0,
                  "total": 0, "error": None, "summary": None}
_collect_lock = threading.Lock()


def _run_collect_bg(cfg: Config):
    import collector

    def progress(ev):
        with _collect_lock:
            _collect_state.update({
                "phase": ev.get("phase", _collect_state["phase"]),
                "message": ev.get("message", _collect_state["message"]),
                "index": ev.get("index", _collect_state["index"]),
                "total": ev.get("total", _collect_state["total"]),
            })

    try:
        summary = collector.run_collection(progress=progress, incremental=True, db_path=cfg.db_abspath)
        with _collect_lock:
            _collect_state.update({"summary": summary, "phase": "done"})
    except Exception as e:  # noqa: BLE001
        with _collect_lock:
            _collect_state.update({"error": str(e), "phase": "error", "message": f"오류: {e}"})
    finally:
        with _collect_lock:
            _collect_state["running"] = False


class Handler(BaseHTTPRequestHandler):
    cfg: Config = None

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, _json_bytes(obj), "application/json; charset=utf-8")

    def _conn(self):
        conn = db.connect(self.cfg.db_abspath)
        db.ensure_schema(conn)
        return conn

    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        try:
            if path in ("/", "/index.html"):
                return self._page()
            if path == "/api/meta":
                return self._json(db.get_meta(self._conn()))
            if path == "/api/overview":
                return self._json(db.overview(self._conn()))
            if path == "/api/level":
                return self._level(qs.get("code", [""])[0], int(qs.get("level", ["2"])[0]))
            if path == "/api/detail":
                return self._detail(qs.get("code", [""])[0])
            if path == "/api/collect/status":
                with _collect_lock:
                    return self._json(dict(_collect_state))
            return self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, code=500)

    def _page(self):
        conn = self._conn()
        meta = db.get_meta(conn)
        if not meta.get("latest_month"):
            lm = db.latest_month(conn)
            if lm:
                meta["latest_month"] = lm
        self._send(200, page_html(meta).encode("utf-8"), "text/html; charset=utf-8")

    def _level(self, code, level):
        conn = self._conn()
        from .hsnames import hs_name
        rows = db.level_summary(conn, code, level, db.latest_month(conn))
        for r in rows:
            r["name"] = hs_name(r["code"])
        return self._json(rows)

    def _collect_countries(self, hs6):
        try:
            import collector
            conn2 = self._conn()
            app = self.cfg.app_id or collector.load_app_id()
            collector.collect_country_breakdown(conn2, app, hs6)
        except Exception:  # noqa: BLE001
            pass

    def _detail(self, code):
        conn = self._conn()
        level = len(code)
        period = db.latest_month(conn)
        series = db.monthly_series(conn, code)
        # 국가별 순위: HS6(6자리) 코드일 때만, 없으면 온디맨드 수집
        imp_ctry, exp_ctry = [], []
        if level == 6:
            if not db.has_country(conn, code):
                self._collect_countries(code)
                conn = self._conn()
            imp_ctry = db.country_breakdown(conn, code, "imp")
            exp_ctry = db.country_breakdown(conn, code, "exp")
        return self._json({
            "prefix": code, "level": level,
            "name": db.name_for(conn, code),
            "series": series,
            "expYoy": db.compute_yoy(series, "exp_dlr"),
            "impYoy": db.compute_yoy(series, "imp_dlr"),
            "qExp": db.compute_quarterly(series, "exp_dlr"),
            "impCountries": imp_ctry, "expCountries": exp_ctry,
            "companies": db.list_companies(conn, code),
        })

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "bad json"}, code=400)
        try:
            conn = self._conn()
            if u.path == "/api/company/add":
                db.add_company(conn, str(body.get("hs_code", "")), int(body.get("hs_level", 0)),
                               str(body.get("company", "")).strip(), str(body.get("note", "")).strip(),
                               dt.datetime.now().isoformat(timespec="seconds"))
                return self._json({"ok": True})
            if u.path == "/api/company/delete":
                db.delete_company(conn, int(body.get("id")))
                return self._json({"ok": True})
            if u.path == "/api/collect":
                with _collect_lock:
                    if _collect_state["running"]:
                        return self._json({"ok": False, "error": "이미 수집이 진행 중입니다."})
                    _collect_state.update({"running": True, "phase": "start", "message": "수집 시작...",
                                           "index": 0, "total": 0, "error": None, "summary": None})
                threading.Thread(target=_run_collect_bg, args=(self.cfg,), daemon=True).start()
                return self._json({"ok": True})
            return self._json({"ok": False, "error": "unknown route"}, code=404)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)}, code=500)


def serve(_unused, cfg: Config) -> None:
    if not os.path.exists(cfg.db_abspath):
        print(f"[server] 데이터 DB가 없습니다: {cfg.db_abspath}")
        print("[server] 먼저 `python run.py --collect` 로 데이터를 수집하세요.")
        return
    Handler.cfg = cfg
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", cfg.port), Handler)
    except OSError as e:
        print(f"[server] 포트 {cfg.port} 바인딩 실패: {e}")
        return
    url = f"http://localhost:{cfg.port}/"
    print(f"[server] 실행: {url}  (종료 Ctrl+C)")
    if cfg.auto_open:
        threading.Timer(0.6, lambda: _safe_open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 종료합니다.")
    finally:
        httpd.server_close()


def _safe_open(url):
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
