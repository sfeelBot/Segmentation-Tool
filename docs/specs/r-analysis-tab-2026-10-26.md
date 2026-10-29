# R 분석(R Analysis) 탭 — 승인된 스펙

접수일: 2026-10-26. 브랜치 `feature/zone-analysis-tab`. 기존 "존 분석(Zone Analysis,
코드상 탭 키 `tab.zone_analysis` = "상/하부 분석")" 탭과 나란히 쓰이는 신규 탭. 이번
문서는 기획 산출물 — 코드 변경 없음.

## 작업 경과

리더가 Plan 서브에이전트로 상세 구현 계획을 수립한 뒤, 사용자와 디자인 목업(Artifact)을
4차례 반복해 레이아웃을 확정했다. 이 문서는 그 과정의 최종 산출물인 확정 스펙을 기록하는
것이며, 설계 옵션을 비교·검토하는 문서가 아니다(옵션 검토는 이미 완료됨).

## 배경

배터리 캡 녹 검사용 앱에 기존 존 분석 탭과 나란히 쓰일 새 탭을 추가한다. 핵심 차이는
여러 이미지를 하나의 "셀(cell)" 단위로 묶어 관리하고 셀 단위로 합/불 판정을 낸다는
점이다 — 이 "셀" 개념은 코드베이스에 전혀 없던 새 데이터 모델이다(존 분석 탭은 이미지
1장 = 분석 1건 단위이고 셀 개념이 없음). "R"은 셀 내 모든 이미지의 면적 합계를 분모로
나눈 비율을 가리키며, 이미지별이 아니라 **셀당 1번만** 계산해 스펙 상/하한과 비교한다.

## 확정된 요구사항

1. **측정 방식**: 임계값 이진화 → `cv2.findContours` 기반(AI 세그멘테이션 모델 아님).
   추후 AI 기반 교체가 쉬워야 하므로 한 함수에 격리하되, 전략/플러그인 추상화는 만들지
   않음(YAGNI) — 함수 본문 위에 교체 지점임을 알리는 주석만 남긴다.
2. **셀 그룹핑**: (a) 폴더 전체 선택 업로드 시 바로 아래 하위폴더명 = 셀 ID, 그 안의
   이미지들이 해당 셀 소속. (b) 개별 파일을 사용자가 지정한 셀 ID(신규/기존)에 수동
   추가도 가능. 셀 선택 후 이미지 삭제, 추가(append) 가능.
3. **ROI(사각형 검사구간)**: 전역(모든 셀 포함) 1회 지정 → 일괄 적용 + 특정 이미지만
   개별 보정(override) 가능.
4. **Threshold**: 슬라이더, 150ms debounce 라이브 프리뷰(존 분석 탭의 confidence
   슬라이더와 동일 패턴).
5. **분모(denominator)**: 설정 팝업에서 사용자가 강제 지정하는 단일 숫자(전역, 셀별
   분기 없음).
6. **스펙 상/하한 + 셀 합/불 판정(핵심 로직)**: 셀 내 모든 이미지의 면적 합계를 분자로
   해서 `R_cell = sum(area) / denominator`를 **셀당 1번만** 계산하고 스펙 상/하한과
   비교해 판정한다. 이미지별 개별 R/판정은 없음 — 이미지별 면적은 그 합계를 구성하는
   참고 데이터로만 표시한다.
7. **마스크 보정**: 존 분석 탭의 브러시 지우기/그리기/undo 패턴을 포팅한다(상속이 아니라
   복사 포팅 — 원↔임의 블롭 모양 수학이 다르기 때문).
8. **결과 화면**: 좌측에서 선택된 셀 기준으로 "셀 R·판정" + "이미지별 면적(참고)"을
   보여주고, 그 위/아래에 전체 셀 요약(합격/불합격/미검사 개수 등)을 고정 표시한다.
   Excel 내보내기를 포함한다.
9. **실행 범위 3단계**: 현재 이미지 검출 / 선택 셀 전체 일괄 검출 / 전체 셀(모든 셀)
   일괄 분석.

## 확정된 UI 레이아웃 (Artifact 목업 v4 기준)

Artifact: https://claude.ai/artifact/BfMMsfues4EAt3xF64y1er

- **상단**: `RStepIndicator` — 5단계 순수 표시용 배너(클릭 이동 없음): ① 이미지/셀
  업로드 → ② 검사 설정 → ③ Contour 자동 검출 → ④ 마스크 보정 → ⑤ 셀별 결과 확인.
- **좌측 패널(폭 비율 1)**: 셀 목록(폴더 일괄 업로드/파일로 셀에 추가 버튼, 각 셀 행에
  판정 상태 dot) + 선택 셀의 이미지 목록(클릭 시 중앙 뷰어와 연동 — 현재 보는 이미지에
  강조 표시, 선택 이미지 삭제/셀에 이미지 추가 버튼) + 검사 설정 요약 카드(ROI 지정
  여부/threshold/분모/스펙 범위 4줄 요약 + "검사 설정 열기/조정" 버튼 → 팝업 모달로
  ROI 지정 버튼 2개(전역 지정/이 이미지만 보정)·threshold 슬라이더·분모 입력·스펙
  상하한 입력을 담음).
- **중앙 패널(폭 비율 3, 가장 넓음)**: 이미지 뷰어 + 마스크 보정 캔버스만. 이미지 위에
  역할별로 분리된 2개의 플로팅 오버레이 클러스터: (1) 편집 도구 클러스터(그리기/지우기/
  pan 토글 그룹 + 브러시 크기 + Undo), (2) 실행/탐색 버튼 클러스터(현재 이미지 검출/
  선택 셀 전체/전체 셀 분석 버튼 + 이미지 전환 ◀ 파일명 ▶). 캔버스 하단에 현재 셀의
  이미지 썸네일 스트립(클릭 시 해당 이미지로 전환, 좌측 리스트 클릭과 동일하게 동작).
- **우측 패널(폭 비율 1)**: 전체 셀 요약(고정, 여러 셀의 합격/불합격/미검사 개수 통계)
  + 그 아래 "현재 선택된 셀 — {cell_id}" 타이틀을 붙인 결과 블록(셀 R·판정 강조 표시
  + 이미지별 면적 참고 목록, 셀 선택 변경 시 이 블록만 갱신) + Excel 내보내기 버튼.

## 데이터 모델 (단일 세션 JSON, 이미지별 사이드카 아님)

```json
{
  "version": 1,
  "cells": {
    "CELL-A": {
      "images": [
        {"path": "...", "roi_override": null, "threshold": 128,
         "manual_strokes": [...], "area": 48213}
      ]
    }
  },
  "global_roi": [120, 80, 400, 300],
  "threshold": 128,
  "denominator": 46620.0,
  "spec_lower": 0.9,
  "spec_upper": 1.1
}
```

셀 단위 `sum_area`/`R_cell`/`pass_fail`은 저장하지 않고 로드 시 `images[].area` 합계로
항상 재계산한다(단일 소스, 분모/스펙 변경 시 즉시 갱신). "단일 세션 JSON" 선택 이유:
셀은 이미지 횡단 개념이고 분모/스펙/전역 ROI는 탭 전체 설정이라 이미지별 사이드카
(`app/core/zone_state_store.py` 방식)보다 프로젝트 전체 JSON(`app/core/annotation_store.py`
방식)에 더 가깝다.

## 파일 목록 (구현 단계 참고용 — "예정" 파일로만 기재, 지금 생성하지 않음)

- **신규 core**:
  - `app/core/r_analysis_metrics.py` — `detect_contour_mask`/`contour_area`/
    `compute_cell_ratio`/`pass_fail`/`cell_rollup`/`export_r_results_to_excel`.
    `zone_metrics.disk_mask`/`zone_metrics.apply_manual_strokes`(현재
    `app/core/zone_metrics.py`에 실재 확인됨)를 재사용.
  - `app/core/r_cell_store.py` — 단일 세션 JSON, `zone_state_store.py`의 atomic-write
    패턴(`save_state`) 재사용.
- **신규 widgets**:
  - `app/widgets/r_roi_canvas.py` — `RRoiCanvas`, `OverlayViewer`(`app/widgets/
    overlay_viewer.py`) 상속. 사각형 드래그 생성/이동/8-handle 리사이즈 +
    브러시 지우기/그리기/undo 포팅(`zone_canvas.py`의 브러시 스탬프/undo 스택 패턴 참고,
    상속이 아니라 복사 포팅 — 요구사항 7).
  - `app/widgets/r_cell_panel.py` — `RCellPanel`.
  - `app/widgets/r_settings_panel.py` — `RSettingsPanel`, 팝업 다이얼로그로 구현.
  - `app/widgets/r_step_indicator.py` — `RStepIndicator`.
  - `app/widgets/r_batch_result_dialog.py` — `RBatchResultDialog`, 셀 기준 Long/Wide +
    Excel export.
- **신규 tab**: `app/tabs/r_analysis_tab.py` — `RAnalysisTab`.
- **기존 파일 변경**:
  - `app/main_window.py` — 탭 등록.
  - `app/core/i18n.py` — `tab.r_analysis` ko/en 키 추가.

## 작업 후

`docs/agents/planning-log.md`에 날짜(2026-10-26)·요약·상태를 append 완료(본 문서와 같은
세션에서 처리).
