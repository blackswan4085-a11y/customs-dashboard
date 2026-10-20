"""stdlib http.server 기반 대시보드 서버. 외부 웹 프레임워크 없음.

라우트:
  GET  /                       메인 페이지(HTML)
  GET  /api/meta               수집 메타
  GET  /api/countries          국가 목록(교역액 순)
  GET  /api/overview?cty=      종합 개요(국가 선택 시 그 국가 기준)
  GET  /api/level?code=&level=&cty=   하위 레벨 집계 표 (필요 시 온디맨드 수집)
  GET  /api/detail?code=&cty=  선택 코드 상세(시계열+YoY+QoQ+국가순위+관련기업)
  POST /api/company/add        관련기업 추가
  POST /api/company/delete     관련기업 삭제
  POST /api/collect            HS2 전량 수집 시작(백그라운드)
  GET  /api/collect/status     수집 진행 상태
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


# 수집(업데이트) 진행 상태 — 단일 서버 프로세스 내 공유
_collect_state = {
    "running": False, "phase": "idle", "message": "",
    "index": 0, "total": 0, "latest": None, "error": None, "summary": None,
}
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
                "latest": ev.get("latest", _collect_state["latest"]),
            })

    try:
        summary = collector.run_collection(
            progress=progress, incremental=True, db_path=cfg.db_abspath
        )
        with _collect_lock:
            _collect_state.update({"summary": summary, "phase": "done"})
    except Exception as e:  # noqa: BLE001
        with _collect_lock:
            _collect_state.update({"error": str(e), "phase": "error", "message": f"오류: {e}"})
    finally:
        with _collect_lock:
            _collect_state["running"] = False


class Handler(BaseHTTPRequestHandler):
    cfg: Config = None  # 클래스 속성으로 주입

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
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

    # ---------------- GET ----------------
    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        cty = (qs.get("cty", [""])[0] or "").strip() or None
        try:
            if path in ("/", "/index.html"):
                return self._page()
            if path == "/api/meta":
                return self._json(db.get_meta(self._conn()))
            if path == "/api/countries":
                return self._json(db.country_list(self._conn()))
            if path == "/api/overview":
                return self._json(db.overview(self._conn(), cty))
            if path == "/api/level":
                return self._level(qs.get("code", [""])[0], int(qs.get("level", ["2"])[0]), cty)
            if path == "/api/detail":
                return self._detail(qs.get("code", [""])[0], cty)
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
        html = page_html(meta)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _collect(self, hs_prefix, sublevel):
        """온디맨드 수집 공통 진입점. 실패해도 빈 응답으로 진행."""
        try:
            import collector
            conn2 = self._conn()
            key = self.cfg.api_key or collector.load_api_key()
            months = int(self.cfg.months)
            collector.collect_detail(conn2, key, hs_prefix, sublevel, months=months)
        except Exception:  # noqa: BLE001
            pass

    def _level(self, code, level, cty):
        """code(상위 prefix) 하위 level 자리 목록. HS4/HS6 은 없으면 온디맨드 수집."""
        conn = self._conn()
        if level > 2 and not db.level_summary(conn, code, level, db.latest_month(conn)):
            self._collect(code, level)
            conn = self._conn()
        return self._json(db.level_summary(conn, code, level, db.latest_month(conn), cty))

    def _detail(self, code, cty):
        conn = self._conn()
        level = len(code)
        # HS4/HS6 상세는 '-' 시계열(2개월 이상)이 없으면 온디맨드 수집.
        # (목록 수집으로 최근월 1개만 있는 경우도 '없음'으로 간주해 전체 시계열을 받는다)
        if level > 2 and not cty and len(db.monthly_series(conn, code, None)) < 2:
            self._collect(code, min(level + 2, 6))
            conn = self._conn()
        period = db.latest_month(conn)
        series = db.monthly_series(conn, code, cty)
        return self._json({
            "prefix": code,
            "level": level,
            "country": cty or "",
            "name": db.name_for(conn, code),
            "series": series,
            "expYoy": db.compute_yoy(series, "exp_dlr"),
            "impYoy": db.compute_yoy(series, "imp_dlr"),
            "qExp": db.compute_quarterly(series, "exp_dlr"),
            "impCountries": db.country_breakdown(conn, code, period, "imp"),
            "expCountries": db.country_breakdown(conn, code, period, "exp"),
            "companies": db.list_companies(conn, code),
        })

    # ---------------- POST ----------------
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
                db.add_company(
                    conn,
                    str(body.get("hs_code", "")),
                    int(body.get("hs_level", 0)),
                    str(body.get("company", "")).strip(),
                    str(body.get("note", "")).strip(),
                    dt.datetime.now().isoformat(timespec="seconds"),
                )
                return self._json({"ok": True})
            if u.path == "/api/company/delete":
                db.delete_company(conn, int(body.get("id")))
                return self._json({"ok": True})
            if u.path == "/api/collect":
                with _collect_lock:
                    if _collect_state["running"]:
                        return self._json({"ok": False, "error": "이미 수집이 진행 중입니다."})
                    _collect_state.update({"running": True, "phase": "start",
                                           "message": "수집 시작...", "index": 0,
                                           "total": 0, "error": None, "summary": None})
                threading.Thread(target=_run_collect_bg, args=(self.cfg,), daemon=True).start()
                return self._json({"ok": True})
            return self._json({"ok": False, "error": "unknown route"}, code=404)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)}, code=500)


def serve(_unused, cfg: Config) -> None:
    db_path = cfg.db_abspath
    if not os.path.exists(db_path):
        print(f"[server] 데이터 DB가 없습니다: {db_path}")
        print("[server] 먼저 `python run.py --collect` 로 데이터를 수집하세요.")
        return

    Handler.cfg = cfg
    addr = ("127.0.0.1", cfg.port)
    try:
        httpd = ThreadingHTTPServer(addr, Handler)
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


def _safe_open(url: str):
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
