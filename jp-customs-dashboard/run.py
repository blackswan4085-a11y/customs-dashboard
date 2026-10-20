#!/usr/bin/env python3
"""일본 재무성 무역통계(e-Stat) 수출입 대시보드 진입점.

사용법:
    python run.py                 # 서버 실행 + 브라우저 자동 오픈 (http://localhost:8002)
    python run.py --port 8080     # 포트 지정
    python run.py --no-open       # 브라우저 자동 오픈 끄기
    python run.py --collect       # 統計品別表 CSV 수집 후 종료

데이터는 collector.py 가 수집한 data/jptrade.db 를 사용합니다.
국가별 순위는 HS6 상세를 열 때 品別国別表(getStatsData)로 온디맨드 수집합니다.
"""
from __future__ import annotations

import argparse
import os
import sys

from jp_customs.config import load_config
from jp_customs.server import serve

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    ap = argparse.ArgumentParser(description="일본 재무성 무역통계(e-Stat) 수출입 대시보드")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--port", type=int, help="서버 포트 (기본 config의 port)")
    ap.add_argument("--no-open", action="store_true", help="브라우저 자동 오픈 끄기")
    ap.add_argument("--collect", action="store_true", help="데이터 수집 후 종료")
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

    serve(None, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
