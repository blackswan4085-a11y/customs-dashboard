"""stdlib http.server 기반 대시보드 서버. 외부 웹 프레임워크 없음.

라우트:
  GET  /                      메인 페이지(HTML)
  GET  /api/meta              수집 메타
  GET  /api/names?level=2|4|6 레벨별 대표 품목명 매핑
  GET  /api/level?code=&level= 하위 레벨 집계 표
  GET  /api/detail?code=      선택 코드 상세(시계열+YoY+QoQ+관련기업)
  POST /api/company/add       관련기업 추가
  POST /api/company/delete    관련기업 삭제
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


class Handler(BaseHTTPRequestHandler):
    cfg: Config = None  # 클래스 속성으로 주입

    # 조용한 로깅
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
        try:
            if path == "/" or path == "/index.html":
                return self._page()
            if path == "/api/meta":
                conn = self._conn()
                return self._json(db.get_meta(conn))
            if path == "/api/names":
                level = int(qs.get("level", ["2"])[0])
                conn = self._conn()
                return self._json(db.representative_names(conn, level))
            if path == "/api/level":
                code = qs.get("code", [""])[0]
                level = int(qs.get("level", ["2"])[0])
                conn = self._conn()
                period = db.latest_month(conn)
                return self._json(db.level_summary(conn, code, level, period))
            if path == "/api/detail":
                return self._detail(qs.get("code", [""])[0])
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
        html = page_html(meta, embedded=None)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _detail(self, code: str):
        conn = self._conn()
        level = len(code)
        series = db.monthly_series(conn, code)
        exp_yoy = db.compute_yoy(series, "exp_dlr")
        imp_yoy = db.compute_yoy(series, "imp_dlr")
        q_exp = db.compute_quarterly(series, "exp_dlr")
        companies = db.list_companies(conn, code)
        name = db.name_for(conn, code)
        return self._json(
            {
                "prefix": code,
                "level": level,
                "name": name,
                "series": series,
                "expYoy": exp_yoy,
                "impYoy": imp_yoy,
                "qExp": q_exp,
                "companies": companies,
            }
        )

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
            return self._json({"ok": False, "error": "unknown route"}, code=404)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)}, code=500)


def serve(_unused, cfg: Config) -> None:
    db_path = cfg.db_abspath
    if not os.path.exists(db_path):
        print(f"[server] 데이터 DB가 없습니다: {db_path}")
        print("[server] 먼저 `python collector.py` 로 데이터를 수집하세요.")
        return

    Handler.cfg = cfg
    addr = ("127.0.0.1", cfg.port)
    try:
        httpd = ThreadingHTTPServer(addr, Handler)
    except OSError as e:
        print(f"[server] 포트 {cfg.port} 바인딩 실패: {e}")
        print("[server] 이미 서버가 실행 중이거나 다른 프로세스가 포트를 사용 중입니다.")
        return
    # 포트 독점 (SO_REUSEADDR 비활성 유지 → 중복 실행 방지는 바인딩 실패로 처리)
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
