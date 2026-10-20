#!/usr/bin/env python3
"""관세청 수출입통계 대시보드 진입점.

사용법:
    python run.py                 # 서버 실행 + 브라우저 자동 오픈 (http://localhost:8000)
    python run.py --port 8080     # 포트 지정
    python run.py --no-open       # 브라우저 자동 오픈 끄기
    python run.py --collect       # API 수집 실행 후 종료 (collector.py 와 동일)
    python run.py --static        # 서버 없이 정적 HTML 1개 생성 (output/index.html)

데이터는 collector.py 가 수집한 data/trade.db 를 사용합니다.
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from customs.config import load_config
from customs.server import serve

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    ap = argparse.ArgumentParser(description="관세청 수출입통계 대시보드")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--port", type=int, help="서버 포트 (기본 config의 port)")
    ap.add_argument("--no-open", action="store_true", help="브라우저 자동 오픈 끄기")
    ap.add_argument("--collect", action="store_true", help="API 데이터 수집 후 종료")
    ap.add_argument("--static", action="store_true",
                    help="서버 없이 정적 HTML 파일만 생성 (관련기업 편집 불가)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.port:
        cfg.port = args.port
    if args.no_open:
        cfg.auto_open = False

    if args.collect:
        import collector
        collector.main()
        return 0

    if args.static:
        return _static(cfg)

    serve(None, cfg)
    return 0


def _static(cfg) -> int:
    from customs import db
    from customs.report import build_static

    if not os.path.exists(cfg.db_abspath):
        print(f"[run] 데이터 DB가 없습니다: {cfg.db_abspath}")
        print("[run] 먼저 `python run.py --collect` 로 데이터를 수집하세요.")
        return 1
    conn = db.connect(cfg.db_abspath)
    db.ensure_schema(conn)
    meta = db.get_meta(conn)
    html = build_static(conn, meta)
    out_dir = os.path.join(HERE, "output")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ 정적 리포트 생성: {out}  ({len(html)//1024} KB)")
    if cfg.auto_open:
        try:
            webbrowser.open("file://" + os.path.abspath(out))
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
