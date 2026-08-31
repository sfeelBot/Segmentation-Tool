# 존(Zone) 분석 탭 — 블랍 클릭 선택 + 편집 구조 감사 + Excel 확장 (2026-08-31)

## 배경

사용자 원문(보류 없이 바로 착수 확정):

> "도구에 추론 시 선택된 블랍에 대해 클릭할 수 있게해줘. zone세션 수정 도구들은
> 라벨링처럼 추론 annotation에 대해 수정할 수 있는 구조여야해. 확인해줘. 추가로 excel로
> 내보낼때 zone별 %말고도, zone위치의 blob의 크기 및 ai score를 보낼 수 있도록 해줘.
> 사람이 수정하고 손으로 표시한 부분은 그 blob의 평균값으로 대체해서 보내줘."

4개 요구사항을 3개 독립 라운드로 나눈다. R1·R3는 코드 변경, R2는 이번 기획 세션에서
코드 근거로 완결한 **감사(audit)** — 구현 라운드가 필요 없다.

| 라운드 | 요구사항 | 대상 | 구현 필요 |
|---|---|---|---|
| R1 | ① 추론 탭 블랍 클릭 선택 | `overlay_viewer.py`, `inference_engine.py`, `inference_tab.py` | 예 |
| R2 | ② Zone 편집 도구 = 라벨링과 동등한 구조인지 확인 | (감사만) | **아니오 — 이미 충족, 아래 결론 참고** |
| R3 | ③+④ Excel에 zone별 blob 크기+AI score, 수동편집 영역은 blob 평균으로 대체 | `zone_metrics.py`, `zone_analysis_tab.py`, `zone_batch_result_dialog.py` | 예 |

R1과 R3는 서로 다른 파일(추론 탭 vs 존 분석 탭)이라 **병렬 구현 가능**. R2는 선행 조건 없음.

---

## R1 — 추론 탭 블랍 클릭 선택

### 문제

`app/tabs/inference_tab.py`의 `OverlayViewerPanel`(`app/widgets/overlay_viewer.py`)은
줌/팬만 지원하고 클릭 인터랙션이 전혀 없다. `InferenceResult`(`app/core/inference_engine.py`)
는 이미 `class_map`(원본 해상도 라벨맵)과 `blobs: list[BlobStat]`(blob_id/class_id/
class_name/pixel_count/mean_confidence/min_confidence/max_confidence/centroid_x/y/
bbox_x/y/w/h)를 갖고 있어 "클릭 좌표 → blob 조회"에 필요한 데이터는 이미 존재한다.
**스코프는 "선택"까지다** — 삭제/편집 등 다른 동작과 연계하지 않는다(사용자 원문이
"클릭할 수 있게 해줘"까지만 요구).

Zone 탭의 `ZoneCanvas`(`app/widgets/zone_canvas.py`)의 `blob_delete` 모드가 이미
"클릭 → 화면좌표를 이미지좌표로 역변환 → 라벨맵 조회 → 블랍 식별" 패턴을 갖고 있지만,
그건 `zone_metrics.compute_blob_labels()`(4-connectivity, 타겟 클래스 단일 마스크
전용)를 쓴다 — 추론 탭은 클래스가 여러 개고 이미 계산된 `BlobStat`(8-connectivity,
`inference_engine._compute_blobs_and_filter()`가 threshold까지 반영해 만들어둠)을
그대로 재사용하는 게 더 정확하고 중복 계산이 없다. 즉 Zone 탭 패턴을 그대로 이식하지
않고, 추론 탭 전용의 더 가벼운 새 매칭 함수를 둔다.

### 설계

**1) `app/widgets/overlay_viewer.py` — `OverlayViewer`에 클릭 감지 추가**

지금 `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`는 좌클릭·중클릭 드래그로
팬만 한다. 클릭(드래그 이동량이 거의 0)과 팬 드래그를 구분해야 한다.

- `__init__`에 `self._press_pos: QPointF | None = None` 추가.
- `mousePressEvent`: 좌클릭일 때만 `self._press_pos = QPointF(event.position())` 저장
  (기존 팬 시작 로직은 그대로 유지, 추가만).
- `mouseReleaseEvent`: 좌클릭이고 `_press_pos`가 있고 픽스맵이 있으면, 이동 거리가
  `_CLICK_TOLERANCE_PX = 4.0`(신규 모듈 상수) 이하일 때만 **픽스맵 좌표계**(줌/팬을
  역변환한 좌표, `class_map`이 아니라 `self._pixmap` 좌표계 — 오버레이 픽스맵이
  `_MAX_OVERLAY_DIM` 관례로 다운스케일될 수 있으므로 호출부가 원본 해상도로 재환산해야
  함, 아래 3) 참고)로 신규 시그널 `pixmap_clicked = pyqtSignal(QPointF)`를 emit한다.
  기존 `_pan_active`/커서 리셋 로직은 그대로 둔다(순서상 이 판정을 먼저 하고 기존 로직
  실행, 애디티브).
- 신규 공개 getter `pixmap(self) -> QPixmap | None: return self._pixmap` — 외부(추론
  탭)가 스케일 계산에 필요.
- 신규 공개 API `set_highlight_rect(self, rect: QRectF | None) -> None` — 픽스맵
  좌표계의 사각형을 저장. `set_pixmap(..., reset_view=True)`(이미지 교체 시)와
  `clear()`에서 `self._highlight_rect = None`으로 리셋.
- `paintEvent`: 기존 `p.translate(self._pan); p.scale(self._zoom, self._zoom);
  p.drawPixmap(0, 0, self._pixmap)` 블록 안(같은 좌표계, 추가 변환 불필요)에 이어서
  `self._highlight_rect`가 있으면 노란 테두리 사각형(`QPen` cosmetic, `zone_canvas.py`의
  `_COLOR_SELECTED = QColor(255, 200, 0)`와 동일 색 재사용해 앱 전체 "선택됨" 색을
  통일)만 그린다.

이 변경은 `ZoneCanvas`(OverlayViewer 서브클래스)에도 상속되지만, `ZoneCanvas`는
`mousePressEvent`/`mouseReleaseEvent`를 전부 오버라이드해 원편집("circle") 모드에서는
`super()`를 전혀 호출하지 않으므로(코드 확인 완료) 새 클릭 감지는 원편집 모드에서
발동하지 않는다. "pan" 모드와 "blob_delete"/"brush_*" 모드의 좌클릭 외 버튼 경로는
`super()`를 호출하지만 `ZoneCanvas`는 `pixmap_clicked`/`set_highlight_rect`를 구독하지
않으므로 부작용 없음(회귀 없음, 검증 라운드에서 확인 필요).

**2) `app/core/inference_engine.py` — 클릭 좌표 → `BlobStat` 순수 함수**

```python
def blob_at(result: InferenceResult, x: int, y: int) -> BlobStat | None:
    """class_map(원본 해상도) 위의 정수 픽셀 좌표 (x, y)가 속한 blob을 반환한다.

    result.blobs는 _compute_blobs_and_filter()가 filtered class_map(거부된 blob은
    이미 배경 0으로 지워진 상태) 위에서 클래스별로 순서대로(래스터 스캔 순서) 담아둔
    것이다. 여기서 같은 filtered class_map을 동일 클래스·8-connectivity로 다시
    라벨링하면, 로컬 라벨 번호(1..n)는 거부된 blob이 이미 없으므로 result.blobs의
    (같은 class_id로 필터링한) 순서와 1:1 대응한다 — 별도 매칭/캐시 구조 불필요.
    """
```
내부: 범위 체크 → `cid = result.class_map[y, x]` (0이면 None) → `mask = (result.class_map
== cid)` → `cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)` →
`local_label = labels[y, x]` → `same_class = [b for b in result.blobs if b.class_id ==
cid]` → `same_class[local_label - 1]`(범위 밖이면 None, 방어적).

- `cv2`는 이미 이 파일 상단에서 import돼 있다. 신규 import 불필요.
- **자체 검증 요구**(ponytail 규칙 — 이 매칭 로직은 미묘해서 반드시 실행 가능한
  체크를 남긴다): `tests/test_inference_blob_at.py` 신규(또는 동등한 self-check) —
  (a) 서로 떨어진 같은 클래스 blob 2개를 담은 합성 `InferenceResult`(QImage는 최소
  더미로 구성 가능, QApplication 불필요)로 각 blob 중심 클릭 시 정확히 대응하는
  `BlobStat`(pixel_count로 식별)을 반환하는지, (b) 배경(class 0) 클릭은 None, (c)
  범위 밖 좌표는 None인지 확인.

**3) `app/tabs/inference_tab.py` — 배선**

- import에 `blob_at` 추가.
- 신규 상태 `self._selected_blob: BlobStat | None = None`.
- `self._viewer_panel.viewer.pixmap_clicked.connect(self._on_viewer_clicked)`.
- `_on_viewer_clicked(self, pt: QPointF)`:
  - `self._last_result is None`이면 조용히 반환(추론 전 클릭 무시).
  - `pixmap = self._viewer_panel.viewer.pixmap()`이 None이면 반환.
  - `h, w = self._last_result.class_map.shape`; `sx = w / pixmap.width(); sy = h /
    pixmap.height()`(오버레이 픽스맵이 다운스케일됐을 수 있으므로 원본 해상도로 역산 —
    `zone_canvas._orig_scale()`과 동일한 계산 패턴).
  - `x, y = int(pt.x() * sx), int(pt.y() * sy)`.
  - `blob = engine.blob_at(self._last_result, x, y)` → `self._selected_blob = blob` →
    `self._update_blob_selection_ui()`.
- `_update_blob_selection_ui(self)`:
  - `None`이면 `self._viewer_panel.viewer.set_highlight_rect(None)` + 라벨 비움.
  - 있으면 bbox를 원본 좌표 → 픽스맵 좌표로 나눠(`/sx, /sy`) `QRectF`를 만들어
    `set_highlight_rect()`에 전달 + 신규 `QLabel`(예: `self._lbl_selected_blob`,
    `_lbl_blob_count` 근처에 배치)에 `"선택된 blob — {class_name} · 면적
    {pixel_count}px · AI 점수 {mean_confidence*100:.1f}%"` 표시.
- 선택 상태를 지워야 하는 지점 3곳(블랍 id/geometry가 더 이상 유효하지 않을 수 있는
  시점) — `_on_image_selected()`(이미지 전환), `_on_run()`(새 추론 시작 직전),
  `_apply_threshold()`(재필터링으로 blob 구성이 바뀔 수 있음) 각각에서
  `self._selected_blob = None; self._update_blob_selection_ui()` 호출.

### 완료 기준(수용 기준)

- 추론 실행 후 오버레이에서 임의 blob 내부를 클릭하면 그 blob에 정확히 테두리 하이라이트가
  표시되고, 클래스명/면적/AI 점수가 라벨에 표시된다.
- 배경(마스크 없는 영역) 클릭 시 하이라이트/라벨이 사라진다(선택 해제).
- 좌클릭 드래그로 화면을 팬하는 기존 동작은 전혀 방해받지 않는다(클릭과 드래그가 명확히
  구분됨, 짧은 클릭만 blob 선택으로 해석).
- 이미지 전환/새 추론 실행/threshold 슬라이더 변경 시 이전 선택이 자동으로 해제된다(stale
  하이라이트 없음).
- 줌/패닝 상태에서 클릭해도 정확한 blob이 선택된다(좌표 역변환이 줌/팬을 반영).
- `F` 키로 원본 이미지 보기로 전환해도 크래시 없음(하이라이트가 남아 있어도 무방 — 데이터는
  여전히 유효하므로 버그 아님, 원하면 구현자가 개선 가능하나 필수 아님).
- Zone 탭(`ZoneCanvas`)의 원 편집/블랍삭제/브러시/팬 골든패스가 전부 회귀 없이 동작한다
  (`OverlayViewer` 공유 코드 변경이므로 필수 확인).

이 라운드는 **주요 기능 추가**로 분류 — 검증 라운드에서 실제 `python main.py` 구동 +
`QTest` 실이벤트로 추론 탭 골든패스(클릭 선택/해제/줌팬 중 클릭/이미지 전환/재추론)와
Zone 탭 회귀(원편집/블랍삭제/브러시그리기/브러시지우기/팬 5모드 전부)를 함께 확인할 것.

---

## R2 — Zone 편집 도구 = 라벨링 탭과 동등한 수정 가능 구조인가 (감사 결과)

### 결론: **격차 없음 — 이미 충족.** 구현 라운드 불필요.

`docs/agents/leader-log.md` "현재 상황 요약"의 2026-08-28 "Zone VOC 편집 도구화 완료"
기록을 실제 코드(`app/widgets/zone_canvas.py`, `app/tabs/zone_analysis_tab.py`,
`app/widgets/annotation_canvas.py`, `app/tabs/labeling_tab.py`)로 직접 대조한 결과다.

| 항목 | 라벨링 탭 (`annotation_canvas.py`/`labeling_tab.py`) | Zone 탭 (`zone_canvas.py`/`zone_analysis_tab.py`) |
|---|---|---|
| 편집 도구 배타 처리 | `QToolBar` + `setCheckable(True)` 액션들(코드상 명시적 `QActionGroup`은 안 쓰고 각 슬롯이 나머지를 끔) | `QToolBar` + `QActionGroup(self)`(명시적 배타, 원편집/브러시그리기/브러시지우기/블랍삭제/팬 5종) — **오히려 더 명시적인 구조** |
| Undo | `_undo_stack: list[list[AnnotationItem]]`, LIFO, **캡 30개**(`annotation_canvas.py:1556-1558`, BUG-014 대응 방어책) | `_undo_stack: list[dict]`, LIFO, **캡 없음**(원 튜플/블랍id 집합/스트로크 좌표만 저장하는 경량 스냅샷이라 BUG-014의 원인인 "대형 마스크 deepcopy" 자체가 없음) |
| Redo | 없음 | 없음 — **양쪽 다 없어 동등**(격차 아님) |
| 단축키 | `Ctrl+Z`(`QKeySequence.StandardKey.Undo`) | `Ctrl+Z`(동일 방식, `zone_canvas.py` `keyPressEvent`) |
| 되돌리기 가능 편집 종류 | 폴리곤/브러시그리기/지우개(브러시 지우기)/영역지우개/선택-이동 | 원 생성·이동·반지름조절·삭제/블랍 클릭삭제/브러시 지우기(픽셀단위)/브러시 그리기(픽셀단위) — **종류 수는 비슷하거나 더 많음**(원 편집이라는 이 탭 고유 조작까지 포함) |
| 영속화(저장) | `annotation_store.py` — 프로젝트 `annotations/{stem}.json`, 편집 시 디바운스 자동저장 | `zone_state_store.py` — 이미지 옆 사이드카 `{stem}.zone.json`, 500ms 디바운스 자동저장 + 이미지 전환 시 동기 flush(`annotation_canvas.py`와 동일 패턴을 R-ZONE-3에서 의도적으로 이식) |
| 저장 실패 처리 | 예외를 UI 레이어로 그대로 raise(CLAUDE.md 원칙) | 세션당 1회만 `QMessageBox.warning()` 표면화 + 로그(R-ZONE-3 판단 6, 라벨링 탭보다 명시적) |

**결론 근거**: 두 캔버스 모두 (1) 라벨링 탭 규격의 배타적 `QToolBar`, (2) LIFO 단일
Undo 스택(redo 없음, 양쪽 동일), (3) `Ctrl+Z` 단축키, (4) 디스크 자동 저장(디바운스+전환
시 flush)까지 **구조적으로 동일한 패턴**을 갖는다. Zone 탭 쪽이 Undo 캡이 없고(경량
스냅샷 설계 덕분에 가능해진 것) 저장 실패 알림이 더 명시적이라는 점에서 오히려 사소하게
더 나은 지점도 있다. "라벨링처럼 수정할 수 있는 구조여야 한다"는 요구사항은 **이미
충족된 상태로 확인됨** — 사용자에게 별도 개발 없이 이 감사 결과를 공유하면 된다.

---

## R3 — Excel 내보내기: zone별 blob 크기 + AI 점수, 수동편집 영역은 blob 평균으로 대체

### 핵심 설계 결정

**1) "blob"의 정의는 Zone 탭이 이미 쓰는 4-connectivity(`zone_metrics.compute_blob_labels`)
로 통일한다** — `inference_engine.BlobStat`(8-connectivity, 클릭 삭제와 무관하게 전
클래스에 대해 계산됨)을 재사용하지 않는다. 이유: 사용자가 브러시로 지우거나 클릭으로
삭제하는 "blob"의 정체성이 이미 `compute_blob_labels()`(4-connectivity, 타겟 클래스
전용) 기준으로 정의돼 있어(`ZoneCanvas._blob_labels`), Excel에 나가는 blob도 같은
정체성을 써야 "화면에서 편집한 blob"과 "Excel에 찍힌 blob"이 항상 일치한다. 다른
connectivity를 섞으면 숫자가 갈라져 사용자가 혼란스러워진다.

**2) "수동편집 영역은 blob 평균으로 대체"의 정확한 구현 — 픽셀이 아니라 blob 단위
통계로 자연스럽게 해결된다.** AI 점수(confidence)는 원래 모델이 예측한 픽셀에만
의미가 있다(사람이 브러시로 새로 그린 픽셀엔 모델의 confidence 자체가 없다 — 모델이
그 자리를 타겟이 아니라고 봤을 수도 있으므로). 따라서:

- `ai_mask`(모델이 실제로 타겟 클래스라고 예측 + threshold 통과 + 사용자가 블랍삭제로
  지우지 않은 픽셀) 위에서만 confidence 평균을 낸다.
- `final_mask`(`ai_mask`에 사용자의 수동 그리기/지우기 스트로크까지 반영한 최종 마스크,
  `_current_target_mask()`가 이미 계산하는 것과 동일)로 **blob을 나눈다**(즉 blob의
  "모양"은 최종 편집 결과 기준).
- 한 blob의 AI 점수 = `confidence_map[해당 blob의 픽셀들 ∩ ai_mask]`의 평균. 사람이
  브러시로 새로 그려 넣은 픽셀은 `ai_mask`에 없으므로 이 평균 계산에서 자동으로
  빠지고, 대신 그 픽셀이 속한 blob 전체의(원래 모델이 예측했던 부분의) 평균값이 그
  blob의 대표 점수로 쓰인다 — **사용자가 요청한 "그 blob의 평균값으로 대체"를 픽셀별
  임의 보간 없이 정확히 구현**한다.
- 예외: blob이 100% 수동으로 그려져 원래 모델 예측 픽셀이 전혀 없으면(`ai_mask`
  교집합이 공집합) 평균을 낼 대상 자체가 없다 — 이 경우 AI 점수는 **N/A(공란)**로
  내보낸다(0%로 채우면 "모델이 낮은 확신으로 예측했다"는 잘못된 의미가 되므로 배제,
  사용자가 이미 "그냥 진행해"로 확정했으므로 결정 대기 등록 없이 합리적 기본값으로
  채택).

**3) zone 배정은 blob 중심점(centroid) 기준.** 배터리 캡 물리 구조상 blob(녹 반점)이
zone 경계를 가로질러 걸치는 경우는 드물고, 걸치더라도 "이 blob은 대략 이 zone에
있다"는 대표 위치 하나만 있으면 충분하다(사용자 원문 "zone위치의 blob"도 이 해석과
일치). `zones_from_circles()`가 이미 반환하는 `Zone.mask`(불리언 배열)에 centroid
좌표를 그대로 조회하면 되므로 새 기하 함수가 필요 없다(기존 Zone 데이터 재사용, YAGNI).

### 변경 파일

**`app/core/zone_metrics.py`**

- `compute_blob_labels()`의 반환값에 **centroid를 추가**(현재 `_, labels, stats, _ =
  cv2.connectedComponentsWithStats(...)`로 centroid를 버리고 있음 — 이미 계산되는
  값이라 추가 비용 없음). 새 시그니처: `-> tuple[np.ndarray, np.ndarray, np.ndarray]`
  (labels, stats, centroids). **기존 호출부 2곳 수정 필요**(하위 호환 아님, 아래
  "영향받는 기존 코드" 참고).
- 신규 dataclass:
  ```python
  @dataclass
  class ZoneBlobStat:
      zone_name: str
      blob_id: int             # final_mask 라벨 순서 기준 1부터
      pixel_count: int
      ai_score: float | None   # 0~1, 순수 수동 blob이면 None
      centroid_x: float
      centroid_y: float
      bbox_x: int
      bbox_y: int
      bbox_w: int
      bbox_h: int
  ```
- 신규 순수 함수:
  ```python
  def zone_blob_stats(
      zones: list[Zone],
      ai_mask: np.ndarray,
      final_mask: np.ndarray,
      confidence_map: np.ndarray,
  ) -> list[ZoneBlobStat]:
  ```
  `compute_blob_labels(final_mask)`로 라벨링 → `np.bincount`(inference_engine의
  `_compute_blobs_and_filter`와 동일한 벡터화 패턴 재사용, blob 개수와 무관하게
  O(H×W) 1회)로 라벨별 `ai_mask` 교집합 픽셀 수·confidence 합을 구해 평균 → 교집합이
  0이면 `ai_score=None` → centroid로 `zones` 순회해 포함하는 zone 이름 결정(못 찾으면
  방어적으로 "미분류", 존들이 전체 이미지를 파티션하므로 실제로는 발생하지 않음).
- `export_zone_percentages_to_excel()`에 선택 인자 추가(하위 호환):
  ```python
  def export_zone_percentages_to_excel(
      rows: list[tuple[str, str, float]],
      out_path: Path,
      blob_rows: list[tuple[str, ZoneBlobStat]] | None = None,
  ) -> None:
  ```
  `blob_rows`가 있을 때만 3번째 시트 `"zone_blobs"` 추가 — 헤더 `["이미지파일명",
  "존이름", "blob_id", "픽셀수(면적)", "AI 점수(%)", "중심x", "중심y", "bbox_x",
  "bbox_y", "bbox_w", "bbox_h"]`(기존 `export_blobs_to_excel()` 헤더 명명 관례
  재사용), `ai_score`가 `None`이면 `"N/A"` 문자열.
- 기존 `__main__` self-check 블록에 `compute_blob_labels` 언팩 수정(2-tuple →
  3-tuple) + `zone_blob_stats()` 신규 검증 케이스 추가: (a) AI 예측 blob 1개 +
  수동으로만 그려진 blob 1개(교집합 없음) 합성 → 전자는 숫자 AI 점수, 후자는 `None`
  확인, (b) zone 2개 걸친 합성 데이터로 각 blob이 올바른 zone 이름에 배정되는지 확인.

**`app/tabs/zone_analysis_tab.py`**

- import에 `zone_blob_stats`, `ZoneBlobStat` 추가.
- `_current_target_mask()`를 두 단계로 분리(기존 동작 100% 보존, 리팩터링만):
  ```python
  def _ai_and_final_masks(self) -> tuple[np.ndarray | None, np.ndarray | None]:
      if self._last_result is None or self._target_class_id is None:
          return None, None
      ai_mask = self._last_result.class_map == self._target_class_id
      removed = self._canvas.removed_blob_ids()
      labels = self._canvas.blob_labels()
      if removed and labels is not None:
          ai_mask = ai_mask & ~np.isin(labels, list(removed))
      final_mask = self._canvas.apply_manual_strokes(ai_mask)
      return ai_mask, final_mask

  def _current_target_mask(self) -> np.ndarray | None:
      return self._ai_and_final_masks()[1]
  ```
- 신규 헬퍼:
  ```python
  def _compute_zone_blob_rows(self) -> list[tuple[str, ZoneBlobStat]]:
      if self._image_path is None:
          return []
      circles_raw = self._canvas.circles_with_ids()
      if not circles_raw or self._last_result is None or self._target_class_id is None:
          return []
      circles = [Circle(cid, cx, cy, r) for cid, cx, cy, r in circles_raw]
      h, w = self._last_result.raw_class_map.shape
      zones = zones_from_circles(circles, (h, w))
      ai_mask, final_mask = self._ai_and_final_masks()
      if ai_mask is None:
          return []
      stats = zone_blob_stats(zones, ai_mask, final_mask, self._last_result.confidence_map)
      return [(self._image_path.name, s) for s in stats]
  ```
- `_on_export_single()`: `blob_rows = self._compute_zone_blob_rows()`를 계산해
  `export_zone_percentages_to_excel(excel_rows, Path(path), blob_rows)`로 전달.
- `_ZoneBatchWorker.run()`: 기존 `target_mask` 계산 체인(158~164행)을 그대로 두되,
  removed_blob_ids 반영 직후(수동 스트로크 적용 **전**) 시점의 마스크를 `ai_mask`로
  보존해두고, `apply_manual_strokes()` 결과를 `final_mask`로 이름 붙인다. 존 퍼센티지
  계산(`zone_stats`)은 기존처럼 `final_mask` 기준 그대로. 이어서
  `zone_blob_stats(zones, ai_mask, final_mask, result.confidence_map)`을 호출해
  `blob_rows.extend((path.name, s) for s in stats)`. `compute_blob_labels()` 반환값
  변경(3-tuple)에 맞춰 162행 `labels, _ = compute_blob_labels(target_mask)`를
  `labels, _, _ = compute_blob_labels(target_mask)`로 수정.
  `completed = pyqtSignal(object)` → `pyqtSignal(object, object)`(rows, blob_rows)로
  변경, `self.completed.emit(rows, blob_rows)`.
- `_on_batch_completed(self, rows, blob_rows)`로 시그니처 변경,
  `ZoneBatchResultDialog(rows, blob_rows, self).exec()`로 전달.

**`app/widgets/zone_batch_result_dialog.py`**

- `__init__(self, rows, blob_rows, parent=None)`로 변경, `self._blob_rows = blob_rows`
  저장.
- 기존 "Excel로 내보내기" 버튼 핸들러의
  `export_zone_percentages_to_excel(self._rows, Path(path))` 호출에 `self._blob_rows`
  세 번째 인자로 추가.
- **화면 표시(Long/Wide 탭)는 이번 라운드에서 건드리지 않는다** — 사용자 요청은 "excel로
  내보낼 때"까지가 범위이고, 온스크린 미리보기 테이블에 3번째 blob 탭을 추가하는 건
  범위 밖(ponytail: 화면 미리보기에 blob 탭 추가는 스킵 — 사용자가 Excel 열기 전
  미리보기를 원하면 그때 추가).

### 영향받는 기존 코드 (`compute_blob_labels` 시그니처 변경)

`compute_blob_labels()`를 호출하는 기존 지점 전부 3-tuple 언팩으로 수정 필요(grep으로
확인한 전체 목록, 이 3곳 외 호출부 없음):
1. `zone_metrics.py` 자체 `__main__` self-check(213행 부근).
2. `zone_analysis_tab.py` `_on_target_changed()`(857행) — `labels, stats, _ =
   compute_blob_labels(target_mask)`(centroid 미사용, 버림).
3. `zone_analysis_tab.py` `_ZoneBatchWorker.run()`(162행) — `labels, _, _ =
   compute_blob_labels(target_mask)`(stats/centroid 미사용, 버림).

### 완료 기준(수용 기준)

- 단일 이미지 Excel 내보내기 시 `zone_blobs` 시트가 생성되고, 화면에 표시되는 존
  퍼센티지와 시트의 blob 픽셀수 합이 합리적으로 대응한다(같은 zone 내 blob 픽셀 합 ≈
  그 zone 면적 × 퍼센티지/100, 반올림 오차 허용).
- 배치 처리 → `ZoneBatchResultDialog`에서 "Excel로 내보내기" 시에도 동일하게
  `zone_blobs` 시트가 이미지별로 채워진다.
- 원본 모델 예측 픽셀만 있는 blob은 숫자 AI 점수(0~100%)를, 100% 수동으로 그려진
  blob은 `"N/A"`를 갖는다 — 합성 데이터로 두 케이스 모두 실제 확인.
- 블랍 삭제 모드로 지운 blob은 `zone_blobs` 시트에 전혀 나타나지 않는다(이미 삭제된
  것이므로 당연히 제외 — `final_mask` 자체가 그 픽셀들을 갖고 있지 않음).
- 기존 `zones`/`zones_wide` 시트 내용·값은 이번 변경으로 전혀 달라지지 않는다(회귀 없음
  — `blob_rows` 인자는 선택적이고 기존 두 시트 생성 로직은 그대로).
- `pytest`로 `zone_metrics.py` self-check(`python -m app.core.zone_metrics` 또는 동등)
  통과 + 기존 `tests/test_zone_github_13_14.py`/`tests/test_zone_edit_toolbar.py`/
  `tests/test_zone_state_persistence.py` 전부 통과(회귀 없음, `compute_blob_labels`
  시그니처 변경이 테스트 코드 안에서도 쓰이는지 grep으로 먼저 확인할 것).

이 라운드도 **주요 기능 추가**로 분류 — 검증 라운드에서 실제 `python main.py` 구동으로
단일 이미지 export + 배치 export 골든패스를 실행하고, 저장된 xlsx를
`openpyxl.load_workbook()`으로 재오픈해 `zone_blobs` 시트 값을 numpy 오라클(합성
이미지로 손계산)과 대조할 것(R-C 3c 검증 관례와 동일 수준).

---

## 구현 위임 시 참고

- R1(추론 탭)과 R3(Zone 탭)는 파일이 전혀 겹치지 않아 **두 구현 에이전트를 병렬로 위임
  가능**. 단 R1이 `overlay_viewer.py`(Zone 탭도 상속해서 씀)를 건드리므로, R3 작업자는
  R1의 `overlay_viewer.py` 변경 사항이 `ZoneCanvas` 쪽에 영향 없는지 별도로 신경 쓸
  필요는 없다(R1 설계 자체가 애디티브 + `ZoneCanvas`가 관련 경로를 오버라이드해서
  차단함, 위에서 확인 완료) — 다만 두 라운드가 **같은 커밋에 섞이지 않게** 순서만
  분리해서 커밋할 것.
- R2는 구현 없이 이 문서의 "R2" 절 자체가 산출물이다. 리더가 사용자에게 결론("이미
  구조적으로 동등함 확인됨")을 그대로 전달하면 된다.
- 검증 우선순위 제안: R1 → R3 순(또는 병렬) 무관, 두 라운드 모두 독립적으로 검증
  가능하다.
