"""R 분석 탭 — 단일 세션 JSON 읽기·쓰기.

`annotation_store.py`와 같은 "단일 JSON, 사이드카 아님" 컨벤션(스펙 "데이터 모델"
절) — 셀은 이미지 횡단 개념이고 분모/스펙/전역 ROI는 탭 전체 설정이라 이미지별
사이드카(`zone_state_store.py` 방식)보다 프로젝트 전체 JSON에 더 가깝다.
atomic write는 `app/core/file_io.atomic_write`(tempfile+os.replace, 재시도 포함)를
그대로 재사용한다(annotation_store.save()와 동일 패턴, 재구현 금지).

셀 단위 sum_area/R_cell/pass_fail은 저장하지 않는다 — 로드 시 `images[].area` 합계로
항상 재계산하는 것이 단일 소스(분모/스펙 변경 시 즉시 갱신, 스펙 "데이터 모델" 절).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.file_io import atomic_write

_VERSION = 1


def load(path: Path) -> dict:
    """파일이 없으면 빈 기본 세션(버전 1, 셀 없음)을 반환한다."""
    if not path.exists():
        return _default_session()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_session()
    if not isinstance(data, dict):
        return _default_session()
    data.setdefault("version", _VERSION)
    data.setdefault("cells", {})
    data.setdefault("global_roi", None)
    data.setdefault("threshold", 128)
    data.setdefault("denominator", 0.0)
    data.setdefault("spec_lower", 0.0)
    data.setdefault("spec_upper", 0.0)
    return data


def save(path: Path, data: dict) -> None:
    atomic_write(path, lambda p: p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    ))


def _default_session() -> dict:
    return {
        "version": _VERSION,
        "cells": {},
        "global_roi": None,
        "threshold": 128,
        "denominator": 0.0,
        "spec_lower": 0.0,
        "spec_upper": 0.0,
    }


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r_session.json"

        # 파일 없음 -> 기본 세션
        empty = load(path)
        assert empty["version"] == 1 and empty["cells"] == {}

        session = {
            "version": 1,
            "cells": {
                "CELL-A": {"images": [
                    {"path": "a.jpg", "roi_override": None, "threshold": 128,
                     "manual_strokes": [], "area": 300},
                ]},
            },
            "global_roi": [0, 0, 50, 50],
            "threshold": 127,
            "denominator": 300.0,
            "spec_lower": 0.9,
            "spec_upper": 1.1,
        }
        save(path, session)
        loaded = load(path)
        assert loaded["cells"]["CELL-A"]["images"][0]["area"] == 300
        assert loaded["global_roi"] == [0, 0, 50, 50]
        assert path.exists()

        # 손상된 JSON -> 기본 세션으로 폴백(예외를 삼키지 않고 안전하게 복구)
        path.write_text("{ broken", encoding="utf-8")
        fallback = load(path)
        assert fallback["cells"] == {}

        print("r_cell_store self-check OK")
