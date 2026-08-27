# 존(Zone) 분석 탭 — GitHub 이슈 #13·#14 기획 (2026-08-27)

전제: R1~R4(2026-08-25 스펙)·신규 기능 3건 R-A/R-B/R-C(2026-08-26 스펙)·신규 기능
5건 R3-1~R3-5(2026-08-27 라운드3 스펙) 전부 구현+검증 통과, main sync PR #18도 병합
완료된 상태. 이번 작업은 별도 워크트리 `D:\segmentation model-zone-analysis-tab`
(`feature/zone-analysis-tab` 브랜치)에서 수행.

> **원문 확인 관련 유의사항**: 이번 기획 세션에는 `gh` CLI/셸 실행 도구가 지급되지
> 않아 `gh issue view 13`/`gh issue view 14`를 직접 실행하지 못했다. 아래 요구사항은
> 리더가 작업 지시에 포함한 요약(코디네이터가 이미 원문을 읽고 정리한 내용)을 그대로
> 채택하되, 언급된 코드 위치를 전부 직접 열어 사실관계를 교차검증했다(아래 "코드
> 근거" 절). 리더는 실제 이슈 원문을 다시 확인해, 특히 #13 요구사항4(아래 "판단 4"
> 절)의 두 해석 중 어느 쪽이 맞는지 사용자에게 확인해줄 것을 권장한다.

## 이슈 #13 — 존 분석 (요구사항 정리)

1. 검출된 원 **우클릭 시 삭제 또는 지름 변경**.
2. **신규 원 추가 시 기존 원들과 동일한 중심점을 자동으로 사용**, 지름(반지름)만
   입력/마우스 조절. 원이 없으면 기존처럼 클릭 위치가 중심.
3. 이 편집 기능(우클릭 지름변경, 신규원 중심공유)은 메인 탭과 오프라인 원 검출
   테스트 팝업 양쪽에서 동작해야 함.
4. "고정 원 옵션 선택 시 오프라인 원 검출 테스트 이미지와 동일하게" — 모호한 항목,
   아래 "판단 4"에서 두 해석과 권장안을 정리.

## 이슈 #14 — 존분석-2 (요구사항 정리)

1. 이미지 목록에서 이미지 선택 시(추론 실행 전) 원본 이미지를 캔버스에 미리보기.
2. "픽셀크기:" 라벨을 "픽셀 threshold:"로 변경(사소한 변경, 1번 라운드에 포함).

---

## 코드 근거 (전부 직접 열어 확인 완료)

### #13 관련

- `app/widgets/zone_canvas.py` `contextMenuEvent()`(L636-651): `QMenu`에
  `"원 삭제"` 액션 1개뿐. 확인됨(리더 서술과 일치).
- `mousePressEvent()`의 빈 공간 클릭 분기(L540-547):
  ```python
  center = self._screen_to_orig(pt)
  new_id = self._next_id
  self._next_id += 1
  self._circles.append(_CircleItem(new_id, center.x(), center.y(), 0.0))
  ```
  신규 원의 `(cx, cy)`가 클릭 위치 그대로 저장됨. 확인됨. **중요 발견**:
  `mouseMoveEvent()`의 `"create"` 분기(L572-575)는 반지름을 `item.cx, item.cy`
  (이미 저장된 중심)로부터의 화면 거리로 계산하므로, **`mousePressEvent()`에서
  `_CircleItem`을 append하기 전에 중심 좌표만 대표 중심으로 바꿔치기하면 드래그
  반지름 로직은 코드 변경 없이 그대로 동작한다** — diff를 `mousePressEvent()`의
  else 분기 한 곳으로 최소화할 수 있음.
- `ZoneCanvas`는 메인 탭(`zone_analysis_tab.py`)과 오프라인 팝업
  (`circle_detect_preview_dialog.py`)이 동일 클래스를 그대로 재사용
  (`self._canvas = ZoneCanvas()` 각각 L271 / L86) — 요구사항 3은 `ZoneCanvas`
  자체에 구현하면 신규 배선 없이 자동으로 양쪽에 적용됨. 확인됨.
- `_on_batch_process()`(`zone_analysis_tab.py` L835-927)의 "1번째 이미지 원을
  전체에 적용"(`apply_to_all`, `_chk_apply_all` 체크박스) 분기(L885-893):
  ```python
  if ref_w > 0 and ref_h > 0 and (w, h) != (ref_w, ref_h):
      sx, sy = w / ref_w, h / ref_h
      circles = [(cx * sx, cy * sy, r * (sx + sy) / 2) for cx, cy, r in circles_ref]
  else:
      circles = circles_ref
  ```
- `_apply_circles_from_popup()`(같은 파일 L757-781, R3-5, 팝업→메인탭)의
  해상도 방어 분기(L770-773):
  ```python
  if pop_w > 0 and pop_h > 0 and (pop_w, pop_h) != (ref_w, ref_h):
      sx, sy = ref_w / pop_w, ref_h / pop_h
      circles = [(cx * sx, cy * sy, r * (sx + sy) / 2) for cx, cy, r in circles]
  ```
  **두 코드가 수학적으로 완전히 동일한 연산**(원 목록 A를 해상도 B에 비례
  스케일 적용)을 서로 다른 두 곳에 독립적으로 구현해둔 것을 확인 — 리더의
  "두 곳에 독립 구현돼 있을 것"이라는 가설이 코드로 실제 확인됨. 방향만
  반대(A→B vs B→A)일 뿐 로직은 동일.

### #14 관련

- `_on_list_image_selected()`(`zone_analysis_tab.py` L381-399): `Image.open()`으로
  크기만 읽고(`self._image_size = im.size`) `self._canvas.set_circles/set_pixmap`
  등 캔버스 표시 관련 호출이 전혀 없음 — 주석 `# 새 이미지는 아직 추론 전 --
  캔버스에 표시할 배경 없음`(L393) 확인됨. 캔버스는 이전 이미지의 오버레이를
  그대로 유지하거나(전환 직후 잠깐), 처음이면 빈 화면.
- `app/widgets/overlay_viewer.py` `OverlayViewer.set_pixmap(pixmap: QPixmap)`
  (L28-31): `InferenceResult` 등 특정 타입에 종속되지 않은 **범용 QPixmap
  세터**임을 확인 — 오버레이 합성 이미지든 순수 원본 이미지든 그대로 받는다.
- **결정적 선례**: `app/widgets/circle_detect_preview_dialog.py`
  `_on_open_image()`(L137-167)가 정확히 이 패턴을 이미 쓰고 있음 — 추론 전
  순수 원본 이미지를 `_rgb_to_qpixmap()`(L30-36, PIL RGB ndarray → QPixmap
  단순 변환 헬퍼, `auto_label_preview_dialog._pil_to_qpixmap()`과 동일 패턴)으로
  변환해 `self._canvas.set_pixmap(...)`에 그대로 넘긴다. 다운스케일도
  `_PREVIEW_MAX_DIM = 2048`로 미리 썸네일화(`Image.thumbnail`)해 20MP+ 원본을
  그대로 QPixmap화하지 않도록 방어함. **이 코드를 그대로 이식하면 됨** — 신규
  렌더링 경로 작성 불필요, 사용자 지시대로 기존 `set_pixmap()` 재사용 확정.
- "픽셀크기:" 라벨: `zone_analysis_tab.py` L126 `toolbar_row2.addWidget(QLabel("픽셀크기:"))`
  확인됨.

---

## 판단 1 — #13 요구사항1 (우클릭 지름 변경)

`contextMenuEvent()`에 `"지름 변경..."` 액션 추가. `QInputDialog.getDouble()`로
**지름**(원문이 "지름"이라 명시) 값을 직접 입력받아 `r = diameter / 2`로 변환해
저장 — 데이터 모델(`_CircleItem.r`)은 그대로 반지름 유지(존 계산·좌표 변환 로직이
전부 `r`을 반지름으로 가정하므로 데이터 모델을 바꿀 이유 없음, 입력 UI 레이어에서만
지름↔반지름 환산).

- 초기값: 현재 반지름의 2배(`item.r * 2`).
- 범위: 0.1 ~ `max(img_orig_w, img_orig_h) * 2`(넉넉한 상한, 원본 이미지 크기 기준
  — 하드코딩된 매직넘버보다 이미지 크기에 연동하는 편이 다양한 해상도에 안전).
- 변경 확정 시 `_push_undo()` 호출 후 `item.r = new_diameter / 2`,
  `self.update()`, `self.circles_changed.emit()` — 기존 원 이동/반지름조절 드래그와
  동일한 신호 흐름을 그대로 타므로 사이드 패널/존 재계산이 자동으로 갱신됨(BUG-018/
  019 재발 방지 패턴 유지, 신규 배선 불필요).
- 컨텍스트 메뉴가 이미 `hit = self._hit_test(pt)`로 원을 특정해두므로, "지름 변경"
  선택 시 그 원(`self._find(circle_id)`)의 `r`만 수정하면 됨 — 신규 헬퍼 불필요.

## 판단 2 — #13 요구사항2 (신규 원 중심 공유)

**대표 중심 산출 규칙(권장 기본값)**: `self._circles`가 1개 이상이면 **모든 기존
원의 중심 평균**(`cx_avg = mean(c.cx for c in circles)`, `cy_avg` 동일)을 대표
중심으로 사용. "가장 최근에 추가된 원" 대신 평균을 권장하는 근거:
- 배터리 캡은 물리적으로 동심 구조라 정상 케이스에서는 모든 원의 중심이 거의
  일치함 — 이 경우 평균이든 최근 원이든 결과가 사실상 같아 선택 기준이 중요하지
  않음.
- 차이가 나는 것은 사용자가 수동 편집(드래그)으로 특정 원 하나를 살짝 어긋나게
  옮겨둔 비정상 케이스인데, 이때 "가장 최근에 추가된 원"을 기준으로 삼으면 그
  어긋난 원 하나가 다음 신규 원 전체에 오차를 전파시킨다. 평균은 이상치 1개의
  영향을 원 개수만큼 희석해 더 견고하다.
- 계산 비용도 원이 보통 2~5개뿐이라 무시할 수준(추가 자료구조·캐싱 불필요).

**구현 최소화**: `mousePressEvent()`의 빈 공간 클릭(else) 분기만 수정 —
```python
else:
    if self._circles:
        cx = sum(c.cx for c in self._circles) / len(self._circles)
        cy = sum(c.cy for c in self._circles) / len(self._circles)
    else:
        p0 = self._screen_to_orig(pt)
        cx, cy = p0.x(), p0.y()
    new_id = self._next_id
    self._next_id += 1
    self._circles.append(_CircleItem(new_id, cx, cy, 0.0))
    ...
```
드래그 중 반지름 계산(`mouseMoveEvent`의 `"create"` 분기)은 이미 `item.cx, item.cy`
기준으로 화면 거리를 재는 구조라 **수정 불필요** — 클릭 위치가 원의 둘레를
결정하는 값(반지름)으로만 쓰이고, 중심은 항상 대표 중심에 고정된다(요구사항
"지름만 입력하거나 마우스로 조절"과 정확히 일치).

**결정 대기 등록**: "평균 vs 최근 원" 중 평균을 기본값으로 채택해 바로 구현
가능하다고 판단했지만, 사용자가 다른 쪽을 선호할 수 있어 `docs/decisions-needed.md`
에 "이 기본값으로 진행해도 되는지"만 확인받는 가벼운 항목으로 등록(재질문이 아니라
확인 요청 형태).

## 판단 3 — #13 요구사항3 (메인 탭 + 팝업 양쪽 적용)

코드 근거에서 이미 확인됨 — `ZoneCanvas`가 두 곳에서 인스턴스만 다르게 생성되는
공유 위젯이므로 판단 1·2를 `zone_canvas.py`에 구현하면 별도 조치 없이 양쪽에 자동
적용된다. **신규 작업 없음, 검증 단계에서 "팝업에서도 동일하게 동작하는지"만
실제 GUI로 재확인**.

## 판단 4 — #13 요구사항4 ("고정 원 옵션 선택 시 오프라인 원 검출 테스트 이미지와
동일하게") — 가장 모호한 항목, 두 해석 병기

리더가 제시한 1차 해석(코드 중복 통합)과, 코드를 직접 대조한 뒤 발견한 대안 해석을
함께 정리한다. **이 항목은 원문을 다시 읽거나 사용자에게 직접 확인하기 전까지는
착수하지 않는 것을 권장**(아래 "라운드 분할"에서 별도 대기 라운드로 분리).

### 해석 A (리더의 1차 해석) — "같은 로직을 공유해야 한다" (리팩터링)

`_on_batch_process()`의 "1번째 이미지 원을 전체에 적용"(고정 원 옵션)과
`_apply_circles_from_popup()`(오프라인 팝업 → 메인 탭 라운드트립, R3-5)이 **수학적
으로 동일한 비례 스케일 연산을 독립적으로 두 번 구현**하고 있다는 것을 코드로
확인했다(위 "코드 근거" 절 참고) — 방향만 반대(원본 해상도→대상 해상도 vs
팝업 해상도→메인 해상도)일 뿐 완전히 같은 공식. 이 해석이 맞다면 작업은:

```python
def _scale_circles(circles, from_size, to_size):
    """(cx,cy,r) 목록을 from_size(w,h) 기준에서 to_size(w,h) 기준으로 비례 스케일.
    크기가 같으면 원본 그대로 반환(항등 변환)."""
    fw, fh = from_size
    tw, th = to_size
    if fw <= 0 or fh <= 0 or (fw, fh) == (tw, th):
        return list(circles)
    sx, sy = tw / fw, th / fh
    return [(cx * sx, cy * sy, r * (sx + sy) / 2) for cx, cy, r in circles]
```
을 `zone_analysis_tab.py` 모듈 레벨(또는 작은 헬퍼)에 신설하고, `_on_batch_process()`
L886-893과 `_apply_circles_from_popup()` L770-773 양쪽을 이 함수 호출로 교체 —
순수 리팩터링(동작 변화 없음, 회귀 위험 최소, 두 곳 다 이미 검증된 로직이라 결과가
바뀌면 안 됨을 검증에서 반드시 대조).

### 해석 B (코드 대조 중 새로 떠오른 대안 해석) — "고정 원의 출처를 오프라인
팝업으로 삼을 수 있게 해달라" (신규 기능 없이 이미 충족됐을 가능성)

"오프라인 원 검출 테스트 **이미지**와 동일하게"라는 문구가 "로직 공유"가 아니라
"참조 대상"을 가리키는 것일 수 있다. 즉 배치 처리의 "1번째 이미지 원을 전체에
적용"이 지금은 **메인 탭에 현재 로드된 이미지**의 원만 기준으로 쓰는데, 사용자는
이 기준 원을 **오프라인 팝업에서 미리 튜닝해둔 원**으로 삼고 싶다는 뜻일 수 있다.
그런데 R3-5(2026-08-27 같은 날 완료)가 이미 "오프라인 팝업 → 메인 탭 적용" 버튼을
구현해뒀으므로, 사용자가 ①팝업에서 원을 확정 → ②"메인 탭에 적용" 클릭(기존
`_apply_circles_from_popup()`) → ③메인 탭 캔버스에 반영된 그 원으로 배치 처리
"1번째 이미지 원을 전체에 적용" 체크 후 실행 — 이 흐름은 **코드 변경 없이 지금
이미 동작**한다(두 라운드가 서로 다른 날 따로 계획됐지만 결과적으로 조합 가능).
이 해석이 맞다면 **신규 구현이 전혀 필요 없고**, 검증 에이전트가 이 조합 흐름이
실제로 매끄럽게 동작하는지 골든패스로 한 번 확인하는 것으로 충분하다(현재 R3-5
검증은 "팝업→메인탭 적용"까지만 확인했지, 그 뒤 "적용된 원으로 배치처리까지
이어지는지"는 명시적으로 재확인한 적 없음 — 이 부분만 검증 갭으로 존재).

### 권장

두 해석 모두 저비용이라 "확신이 안 서니 스파이크"까지는 필요 없지만, 구현
방향이 다르므로(해석 A=리팩터링 코드변경, 해석 B=검증만) **사용자 확인 없이
진행하지 않는다** — `docs/decisions-needed.md`에 두 해석과 함께 등록. 착수
순서 상으로는 해석 B(검증만, 위험 없음)를 먼저 시도해 실제로 이미 되는지 확인한
뒤, 그래도 사용자가 "코드 중복을 없애달라"는 뜻이었다면 해석 A(리팩터링)를
추가로 진행하는 것을 권장(두 해석이 상호 배타적이지 않고 B 확인 후 A를 얹어도
무방하므로 순서 유연).

---

## 판단 5 — #14 요구사항1 (원본 이미지 미리보기)

`_on_list_image_selected()`에 이미지 로드+표시 로직 추가 — `circle_detect_preview_dialog._on_open_image()`
의 패턴을 그대로 이식:

```python
def _on_list_image_selected(self, path: Path) -> None:
    self._image_path = path
    try:
        with Image.open(str(path)) as im:
            rgb_im = im.convert("RGB")
            self._image_size = rgb_im.size
            preview_im = rgb_im.copy()
        preview_im.thumbnail((_PREVIEW_MAX_DIM, _PREVIEW_MAX_DIM), Image.BILINEAR)
        self._canvas.set_image_size(*self._image_size)
        self._canvas.set_pixmap(_rgb_to_qpixmap(np.array(preview_im)))
    except Exception:
        self._image_size = (0, 0)
        self._canvas.clear()
    self._canvas.clear_circles()
    ...(이하 기존 로직 그대로: 자동검출 버튼 비활성화, set_blob_data(None, None) 등)
```

- `_rgb_to_qpixmap()`은 `circle_detect_preview_dialog.py`에 이미 있는 private
  헬퍼와 완전히 동일한 5줄짜리 변환 함수다. 이 코드베이스는 이미 같은 패턴을
  `auto_label_preview_dialog._pil_to_qpixmap()`과 `circle_detect_preview_dialog._rgb_to_qpixmap()`
  두 곳에 독립 중복해온 선례가 있다(공용 유틸로 뽑지 않는 것이 기존 관례) — 이번에도
  `zone_analysis_tab.py`에 같은 5줄을 그대로 복제하는 쪽을 권장(라더: 5줄짜리 순수
  변환 함수를 위해 신규 공유 모듈을 만드는 것은 과함, 기존 관례와도 일치).
- `_PREVIEW_MAX_DIM` 상수(2048)도 `circle_detect_preview_dialog.py`와 동일 값으로
  복제 — 20MP+ BMP 원본을 그대로 QPixmap화하지 않기 위한 기존 방어 관례를 그대로 따름.
- 캔버스에 표시된 원본 미리보기는 "▶ 추론 실행" 버튼을 누르면 기존 로직
  (`_setup_target_classes` → `self._canvas.set_pixmap(result.overlay_pixmap)`)이
  오버레이 합성 이미지로 자연스럽게 덮어써 회귀 없음(기존 흐름 그대로).
- 실패 처리(이미지 로드 예외): 기존 `_image_size = (0, 0)`에 더해 `self._canvas.clear()`
  호출 추가(캔버스에 이전 이미지가 남아있는 상태 방지) — 사소하지만 있으면 좋은
  보강, 없어도 치명적이지 않으므로 구현자가 시간이 부족하면 생략 가능(YAGNI 경계선).

## 판단 6 — #14 요구사항2 (라벨 텍스트 변경)

`zone_analysis_tab.py` L126의 `QLabel("픽셀크기:")` → `QLabel("픽셀 threshold:")`
1줄 변경. 별도 라운드 불필요 — 판단 5와 같은 라운드(같은 파일, 인접 영역)에 포함.

---

## 파일 구조 (신규 파일 없음)

- `app/widgets/zone_canvas.py` — 판단 1(지름 변경 메뉴), 판단 2(신규 원 중심 공유).
- `app/tabs/zone_analysis_tab.py` — 판단 5(원본 미리보기), 판단 6(라벨 변경),
  판단 4 해석 A 채택 시 `_scale_circles()` 헬퍼 추가 + 2곳 교체.

## 라운드 분할 제안

의존관계·리스크 기준(요청 순서 #13→#14가 아니라 파일 겹침 없는 두 그룹으로 나눠
**병렬 진행 가능**):

- **R13-A**(요청1 우선순위 높음, `zone_canvas.py` 단독, 결정 불필요 — 판단 2의
  "평균 중심" 기본값만 가벼운 확인 필요) — 지름 변경 컨텍스트 메뉴 + 신규 원 중심
  공유. 요구사항3(양쪽 적용)은 구현 부산물로 자동 충족, 검증 단계에서 확인만.
- **R14-A**(`zone_analysis_tab.py` 단독, 결정 불필요, 저리스크) — 원본 이미지
  미리보기 + 라벨 텍스트 변경. R13-A와 파일이 겹치지 않아 **동시 진행 가능**.
- **R13-B**(대기, `zone_analysis_tab.py`) — #13 요구사항4. **착수 전 사용자에게
  원문 재확인 또는 해석 A/B 중 선택을 받아야 함**(위 "판단 4" 절). 해석 B로
  판명되면 코드 변경 없이 검증만으로 종료, 해석 A면 소규모 리팩터링 라운드로 진행.
  R13-A/R14-A와 파일이 일부 겹치므로(같은 `zone_analysis_tab.py`) 그쪽들이 먼저
  구현+검증 완료된 뒤 착수 권장(간단한 diff 충돌 방지 목적, 기술적 의존관계는 아님).

## 결정 필요 항목 (decisions-needed.md 등록 대상)

1. **판단 2 — 신규 원 대표 중심 산출 규칙**: "기존 원들의 평균 중심"을 기본값으로
   제안 — 이대로 진행해도 되는지, 아니면 "가장 최근에 추가된 원"을 원하는지 확인.
2. **판단 4 — "고정 원 옵션... 오프라인 원 검출 테스트 이미지와 동일하게"**: 해석
   A(중복 로직 리팩터링 통합) vs 해석 B(고정 원의 출처를 오프라인 팝업 결과로
   쓰는 흐름이 R3-5 덕에 이미 가능함, 검증만 필요) 중 어느 쪽이 원문 의도에
   가까운지 사용자 확인 필요 — 가능하면 GitHub 이슈 #13 원문을 리더가 직접
   재확인해줄 것을 권장(이번 세션은 `gh` 도구 미지급으로 원문을 못 읽음).

## 리스크

- 판단 1(지름 변경)·판단 2(중심 공유) 모두 `mousePressEvent`/`contextMenuEvent`라는
  이미 여러 라운드(R2/R4/R3-3/R3-4)에 걸쳐 계속 수정돼온 함수라 diff를 해당 분기로
  최소화하고, 기존 Undo(R3-4)/블랍삭제(R4)/브러시지우기(R3-3) 모드 배타 처리와
  충돌하지 않는지 확인 필요 — 판단 1·2는 모두 `self._mode == "circle"` 기본 모드
  범위 내 동작이라 다른 모드와 상호작용 없음(컨텍스트 메뉴도 `contextMenuEvent()`
  L637에 이미 `self._mode != "circle"` 가드가 있어 자동으로 안전).
- 판단 5(원본 미리보기)는 대용량 이미지(5472×3648 BMP)를 목록 클릭마다 동기 로드
  하므로, 폴더에 수십~수백 장이 있을 때 빠르게 연속 클릭하면 약간의 지연이 체감될
  수 있음 — 기존 `circle_detect_preview_dialog.py`도 동일한 동기 로드 방식이라
  새로운 리스크는 아니지만, 검증 단계에서 체감 지연이 없는지 확인 권장(문제 있으면
  후속 라운드에서 스레드 워커로 격리, 이번 라운드 범위 아님— YAGNI).
