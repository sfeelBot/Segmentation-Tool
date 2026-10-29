# 학습 진행 다이얼로그 — 단계별 로그 / 느린 시작 조사 / 중지 버그 (2026-10-28)

사용자 요청 3건의 범위·우선순위·실행 순서를 정리한다. **기획 문서이며 구현은 포함하지
않는다** — 구현은 별도 "기획 검토" 단계 이후 구현 에이전트가 담당.

## 배경 — 리더의 사전 조사 (코드로 재확인 완료)

리더가 제시한 사실관계를 `app/core/trainer.py`, `app/widgets/training_progress_dialog.py`,
`app/tabs/training_tab.py`, `app/main_window.py`, `app/core/device_info.py`,
`app/core/logger.py`, `app/widgets/log_panel.py`를 직접 읽고 전부 재확인했다. 추가로
확인한 사실 2건(아래 "추가로 확인한 사실" 참고)이 원인 분석을 한 단계 더 정확하게
만든다.

### 추가로 확인한 사실

1. **CUDA 컨텍스트 초기화는 `model.to(device)`가 아니라 `pick_device()` 안에서 이미
   발생한다.** `app/core/device_info.py:pick_device()`가 `torch.zeros(1, device="cuda")`
   + `torch.cuda.synchronize()`로 "GPU가 실제로 살아있는지" 프로브를 하는데, 이게 프로세스
   최초의 CUDA 연산이면 CUDA 컨텍스트/드라이버 초기화 비용을 여기서 미리 다 낸다.
   `_train()`에서 `pick_device()`는 데이터셋 구성보다도 **먼저** 호출되므로(138~143행),
   리더가 지목한 "model.to(device)가 숨은 비용의 주범"이라는 가설은 **부분적으로만
   맞음** — 실제로는 `_train()` 맨 앞, 아무 로그도 없이 가장 먼저 멈추는 지점이
   `pick_device()`일 가능성이 더 크다. `model.to(device)`(223행) 시점엔 컨텍스트가
   이미 데워져 있어 보통 가중치 복사 비용만 남는다.
2. **`TrainerWorker`는 이미 `QThread`라서 UI 스레드 자체는 멈추지 않는다.** "멈춘 것처럼
   보인다"는 실제 freeze가 아니라 **피드백 부재**의 문제다 — 즉 1번 요청은 실제 성능
   개선보다 가시성(instrumentation) 문제에 가깝다.

### 단계 순서 재확인 (`_train()`, `app/core/trainer.py` 138~254행)

```
pick_device()                         ← CUDA 콜드스타트 비용이 실제로 여기 숨어있을 가능성 큼
SegmentationDataset (train, 다양 모드)  ← _collect_pairs() + random_crop시 ann 중심 JSON 파싱
SegmentationDataset (val, resize 모드)
train/val 이미지 인덱스 분할
DataLoader ×2 생성                     ← 워커 spawn은 첫 iterate 시점에 지연되므로 이 호출 자체는 보통 빠름
model.to(device)                      ← pick_device 이후라 보통 가중치 복사만
optimizer / loss_fn / scaler / scheduler 생성
── training_started 시그널 emit ──     ← 지금까지는 UI에 아무 신호도 없음
```

### 중지 버그 재확인 (`_train()` 257~417행, `app/tabs/training_tab.py`, `app/main_window.py`)

- `main_window.py:closeEvent()`(159행)는 `training_tab.queue_active`가 True면 창닫기를
  무조건 막는다.
- `queue_active`는 큐의 모든 waiting job이 끝나야(`training_tab.py:_run_next_job()`,
  482행) False가 된다.
- `_train()`의 배치 루프(271~298행)는 매 배치 직후 `self._stop.is_set()`을 확인해
  `stopped_early=True`로 빠르게 빠져나온다 — **여기까지는 이미 응답성이 괜찮음**
  (DataLoader가 다음 배치를 내주는 시간만큼만 지연, R4 캐싱 이후 보통 수~수십 ms).
- 문제는 그 다음: `stopped_early`든 아니든 **항상** validation 전체 루프(320~330행,
  `self._stop` 체크 없음) → 스케쥴러 step → checkpoint 저장(atomic_write, torch.save)을
  끝까지 수행한 뒤에야 바깥 `for epoch` 루프를 빠져나온다(루프 맨 위의 stop 체크가
  다음 epoch 진입을 막을 뿐). validation 대상이 크면(resize 모드로 원본 전체
  디코딩/리사이즈) 이 구간이 수분 걸릴 수 있다 — 중지 버튼이 "안 먹는 것처럼" 보이고
  그동안 `queue_active`가 True로 남아 메인 창도 못 닫힌다.
- 이 설계는 의도적이다(주석 참고, BUG-026: "1 epoch도 못 채우고 멈춰도 체크포인트
  최소 1개는 보존"). 즉 **아예 없애면 안 되고, 조건을 좁혀야 한다.**

---

## 작업 A — 중지(Stop) 버그 수정 (우선순위 P1, 최우선)

### 문제 정의
학습 중지 요청 시, 이미 이전 epoch에서 체크포인트가 저장된 상태라면 BUG-026이 보장하려는
"최소 1개 체크포인트"는 이미 충족돼 있다. 그런데도 현재 epoch의 validation+checkpoint
저장을 강제로 완료시키는 바람에 중지 응답성이 떨어지고, 그 여파로 메인 창도 닫히지 않는다.

### 설계 (리더 제안 방향 — 코드 재검토 결과 타당하다고 판단, 보강 1건 추가)

**A-1. 이전 체크포인트가 있으면 validation/저장을 건너뛰고 즉시 종료 (리더 제안 그대로 채택)**

`_train()`의 배치 루프 종료 직후(`stopped_early` 로그 다음), validation 블록 진입 전에:

```python
if stopped_early and history:
    log.info("중지 요청 반영 — 이전 체크포인트가 이미 존재해 "
             "이번 epoch의 validation/checkpoint 저장을 생략하고 즉시 종료")
    break
```

- `history`가 비어있지 않다 = 최소 1개 epoch을 완주했다 = best.pt(또는 간격 체크포인트)가
  최소 1개는 이미 디스크에 있다(epoch 1 종료 시 `best_iou`가 `-inf`에서 갱신되므로
  `best.pt`는 거의 항상 epoch 1 완료 시점에 저장됨). 따라서 이 분기는 BUG-026이 지키려는
  불변식을 깨지 않는다.
- epoch 1(아직 `history` 비어있음) 중 중지 요청 시에는 **기존 동작 그대로 유지** —
  validation·checkpoint를 끝까지 완료해 BUG-026 보장을 지킨다.

**A-2. (보강, 필수) epoch 1의 강제 validation도 stop에 반응하도록 — validation 루프 안에도
stop 체크 추가**

A-1만으로는 "epoch 1이 실행 중일 때" 멈추면 여전히 큰 validation set에서 응답성 문제가
재현된다. 리더가 "검토해달라"고 명시한 지점이 바로 이것 — 검토 결과 **필요하다고 판단**.
validation 루프(320~330행)에도 stop 체크를 추가한다:

```python
for images, masks in val_loader:
    if history and self._stop.is_set():
        log.info("중지 요청 — validation 조기 종료 (처리한 배치만으로 지표 계산)")
        break
    ...
    val_batches_processed += 1   # 신규 카운터
```

- **⚠️ 기획검토에서 발견된 엣지 케이스(해결됨) — 조건은 `self._stop.is_set()` 단독이 아니라
  반드시 `history and self._stop.is_set()`.** epoch 1(아직 `history` 비어있음) 중 **학습
  배치 루프 단계에서** 중지 요청이 들어오면 `self._stop`은 이미 set된 상태로 validation에
  진입한다. 조건이 `self._stop.is_set()` 단독이면 validation 첫 반복에서 즉시 break해
  `val_batches_processed=0`인 의미 없는(val_loss=0.0, IoU=0.0) 체크포인트가 저장돼버려
  BUG-026이 지키려던 "최소 1개의 **의미 있는** 체크포인트" 보장이 깨진다. `history and`를
  앞에 붙이면 epoch 1(history 비어있음)에서는 이 조건이 항상 False가 되어 validation이
  **항상 끝까지** 돈다(기존 동작 그대로, 회귀 없음). stop 체크가 실제로 발동하는 건 epoch
  2 이상이면서 "학습 배치는 다 끝났는데 validation 도중에" 멈추는 경우뿐이고, 그 경우엔
  이미 이전 epoch의 체크포인트가 있으므로 이번 epoch을 부분 데이터로 cut해도 안전하다.
- **추가 가드**: validation 종료 후 `val_batches_processed == 0`이면(= 조기 종료로 단 한
  배치도 못 돌린 경우) 이번 epoch은 `history.append(...)`/checkpoint 저장을 **생략**하고
  로그만 남긴 뒤 바깥 `for epoch` 루프로 돌아간다(다음 반복 맨 위의 stop 체크가 즉시
  종료시킴). `history`가 비어있지 않은 상태에서만 이 분기에 도달할 수 있으므로(위 가드
  덕분) "0배치 epoch을 건너뛰어도" 이미 이전 epoch에 유효한 체크포인트가 있어 BUG-026
  불변식은 유지된다.
- **주의(구현 필수 수정 사항)**: 현재 `val_loss /= len(val_loader)`(332~333행)는 전체
  배치 수로 나누는데, 조기 종료 시 이 값이 실제 처리한 배치 수보다 커서 `val_loss`가
  부정확하게 낮게 계산된다. `len(val_loader)` 대신 신규 카운터
  `val_batches_processed`(0보다 큰 경우에만 나누기)로 바꿔야 한다. `metric_accumulator`는
  이미 스트리밍 방식이라 추가 수정 불필요(부분 배치만으로도 올바르게 동작).
- 이 변경은 epoch 1뿐 아니라 모든 epoch의 validation에 적용되지만, A-1 덕분에
  "`history`가 있는" 상태에서는 이 루프 자체에 도달하지 않으므로 실질적으로는 epoch 1
  케이스(그리고 `val_split`이 매우 작아 `history` 조건과 무관하게 아주 드물게 발생할
  수 있는 경쟁상황)에만 영향을 준다. 리스크 낮음.

### 범위 밖으로 둔 것 (검토했으나 이번 라운드에 포함하지 않음)

- **DataLoader 블로킹(워커 행잉) 자체에 대한 타임아웃 처리** — `DataLoader(timeout=N)`
  옵션이 존재하긴 하나, 정상적인 느린 배치와 진짜 행(hang)을 구분하는 임계값을 실측
  없이 정하면 오히려 정상 학습 중 가짜 타임아웃 에러를 유발할 위험이 있다. 이번 3건
  요청에 포함되지 않은 별개 리스크이며, A-1/A-2로 중지 응답성 문제의 실질적 원인(강제
  validation)은 해소되므로 지금 손대지 않는다. 향후 실제로 DataLoader 행잉이 재현되면
  그때 별도로 재논의.

### 영향 파일
- `app/core/trainer.py` — `_train()` 단독 수정(배치 루프 종료 직후 분기 1개, validation
  루프 내 stop 체크 1개 + 분모 수정). 다른 함수·다른 파일 변경 없음.
- `app/main_window.py`/`app/tabs/training_tab.py` — **수정 불필요.** `queue_active`가
  프롬프트하게 False로 떨어지면 `closeEvent()`가 자연히 통과한다(원인이 `trainer.py`에만
  있었음을 확인).

### 검증 체크리스트 (검증 에이전트용)
1. epoch 2 이상 진행 중 "현재 작업만 중지" → 수 초 내 중지, 이전 체크포인트 유지,
   새 checkpoint/validation 파일 생성 안 됨.
2. epoch 2 이상 진행 중 "전체 큐 중지" → `queue_active`가 False로 전환, 메인 창
   `closeEvent()`가 확인 다이얼로그까지 정상 진행(더 이상 막히지 않음).
3. epoch 1 진행 중(아직 체크포인트 없음) 중지 → `history`가 비어있어 A-2 조건
   (`history and self._stop.is_set()`)이 항상 False가 되므로 **기존과 완전히 동일하게**
   validation이 끝까지 돌고 체크포인트 1개가 생성된 뒤 종료된다(이 케이스는 A-2로
   빨라지지 않음 — 의도된 동작, BUG-026 불변식 유지가 목적). 응답성 개선은 5번 항목
   (epoch 2 이상에서 validation 도중 중지)에서 확인.
3-1. epoch 2 이상, **training 배치는 모두 끝나고 validation 도중** 중지 → A-2가 즉시
   반응해 조기 종료, `val_batches_processed`가 0이면 이번 epoch은 저장을 건너뛰고(로그
   확인), 1개 이상이면 올바른 분모로 계산된 부분 지표가 저장되는지 확인.
4. val_loss 수치가 조기 종료 전/후 비정상적으로 튀지 않는지(분모 수정 확인) — 작은
   검증셋으로 중지 없이 정상 완주한 case와 비교해 스케일이 맞는지 확인.
5. 회귀 없음: 중지하지 않고 정상 완주하는 일반 학습 플로우(epoch 전체 완료, best.pt/
   간격 checkpoint 생성, training_metrics.json/png 생성)가 기존과 동일하게 동작.

---

## 작업 B — 학습 준비 단계별 로그 UI (우선순위 P2)

### 문제 정의
`training_started` 시그널이 디바이스 선택→데이터셋 구성→분할→DataLoader 생성→
`model.to(device)`→optimizer/scheduler 생성까지 **전부 끝난 뒤**에만 발생해, 그 사이
UI(`TrainingProgressDialog`)에는 아무 정보도 뜨지 않는다. 사용자는 "학습 대기열"
(`q_box`, `train_progress.queue_title`) **바로 아래**에 지금 몇 번째 준비 단계인지
보여주는 간단한 로그를 원한다.

### 설계

**B-1. 새 시그널 — 완료 로그가 아니라 "지금 시작하는" 단계를 알리는 신호**

기존 `log.info(...)` 호출들은 전부 "~완료" 시점에 찍힌다(예: "데이터셋 로드 완료").
느린 구간(특히 `pick_device()`) 동안은 **시작 시점에도** 신호가 있어야 "멈춘 것처럼"
보이지 않는다. `TrainerWorker`에 신규 시그널 추가:

```python
stage_changed = pyqtSignal(str)   # stage_key — 아래 고정 순서 중 하나
```

`_train()` 안에서 각 단계 **진입 직전**(블로킹 호출 바로 앞)에 emit:

| 순서 | stage_key | 삽입 위치(현재 줄 기준, 대략) |
|---|---|---|
| 1 | `"device"` | `pick_device()` 호출 직전(140행) |
| 2 | `"dataset_train"` | train `SegmentationDataset(...)` 호출 직전(154행) |
| 3 | `"dataset_val"` | val `SegmentationDataset(...)` 호출 직전(196행) |
| 4 | `"dataloader"` | `DataLoader(...)` ×2 생성 직전(210행) |
| 5 | `"model_to_device"` | `self._model.to(device)` 직전(222행) |
| 6 | `"optimizer"` | `_build_optimizer(...)` 호출 직전(231행) |

총 6단계 고정(설정값에 따라 단계 수가 달라지지 않음 — 분기 없이 항상 이 순서로 실행됨을
코드로 확인함). `training_started` emit 시점 이후로는 이 단계 로그는 더 이상 의미가
없으므로(에폭 진행 UI가 넘겨받음) 추가 단계 정의는 불필요.

**B-2. UI — 다이얼로그 내 신규 컴팩트 로그 뷰어, `q_box` 바로 아래**

`app/widgets/training_progress_dialog.py`의 `_build_ui()`에서 `root.addWidget(q_box, ...)`
와 버튼 행 사이에 작은 읽기 전용 리스트(또는 라벨 스택)를 하나 추가한다. 요구사항은
"간략히"이므로 큰 위젯 불필요 — 높이 상한(예: 80~100px 정도, 6줄 넘지 않음)을 두고
`set_current_job()` 호출 시 clear, `stage_changed` 수신 시 한 줄 append(예:
`"[2/6] 데이터셋 구성 중…"`). 스타일은 기존 `_queue_list`와 통일.

**B-3. 텍스트는 i18n 키로 — 로거 브리지 직접 재사용은 권장하지 않음**

`app/widgets/log_panel.py`가 전역 로거 브리지(`app/core/logger.py:bridge.log_received`)를
구독해 모든 `log.info()`를 UI에 그대로 보여주는 기존 패턴이 있어, 처음엔 "trainer 로거만
필터링해서 재사용"하는 쪽이 코드가 더 적게 든다고 판단했으나 **기각**: `trainer.py`의
`log.info()` 문자열은 전부 한국어 하드코딩 진단용 메시지이고, `training_progress_dialog.py`는
"아이콘/이모지 i18n 완비" 라운드(`docs/roadmap.md` 해당 절)에서 이미 영문 전환이 끝난
사용자 대상 UI다. 로거 브리지를 그대로 꽂으면 번역이 끝난 다이얼로그 안에 다시 한국어
전용 텍스트가 섞여 들어가는 회귀가 생긴다. 따라서:
- `stage_changed`는 **문자열이 아니라 짧은 key**만 들고 다니고,
- UI 쪽에서 `t(f"train_progress.stage.{key}")`로 조회해 렌더링,
- `i18n.py`에 ko/en 6쌍 신규 키(`train_progress.stage.device` 등) + 접두 포맷
  (`"[{idx}/{total}] {label}"` 조립은 코드에서, 번역 문자열은 라벨만) 추가.
- `trainer.py`의 기존 "~완료" `log.info()` 호출들은 그대로 둔다(파일 로그/콘솔 진단용,
  변경 불필요) — 이번 작업은 그 옆에 **별도의 사용자 대상 신호**를 하나 더 만드는 것이지
  기존 로그를 대체하는 게 아니다.

### 영향 파일
- `app/core/trainer.py` — `TrainerWorker`에 `stage_changed` 시그널 추가 + `_train()`에
  emit 호출 6곳 삽입(전부 기존 코드 삭제 없이 순수 추가).
- `app/widgets/training_progress_dialog.py` — `q_box` 바로 아래 신규 위젯 + 수신 메서드
  (예: `append_stage(key: str)`) + `set_current_job()`에서 clear.
- `app/tabs/training_tab.py` — `_run_next_job()`에서 기존 5개 시그널 connect 옆에
  `self._worker.stage_changed.connect(...)` 1줄 추가(새 job 시작 시마다 재연결되는
  기존 패턴과 동일), `_retire_trainer()`의 disconnect 목록에도 추가.
- `app/core/i18n.py` — `train_progress.stage.*` ko/en 6쌍 신규.

### 검증 체크리스트
1. 학습 큐 시작 직후(`training_started` emit 전) 다이얼로그에 "[1/6] …" ~ "[6/6] …"가
   순서대로, 빈 틈 없이(멈춘 것처럼 보이지 않게) 나타나는지 — 특히 "device" 단계에서
   오래 머무르는지(=느린 구간 가설 확인, 작업 C의 측정 자료로도 활용).
2. en 전환 시 전부 영어로 표시, 잔존 한국어 없음.
3. 다음 job 시작 시 이전 job의 stage 로그가 clear되고 새로 쌓이는지.
4. 큐 전체 중지/에러 발생 시 `_retire_trainer()`의 disconnect가 `stage_changed`까지
   포함해 정상 동작(다음 job의 신호가 이전 job 핸들러로 새는 stale-signal 버그 없음 —
   기존 5개 시그널과 동일 패턴이라 리스크 낮음).

---

## 작업 C — 느린 시작 구간 원인 조사 + 가능하면 개선 (우선순위 P3)

### 결론 — 이번 라운드는 "측정 가능하게 만드는 것"까지만, 알고리즘적 개선은 보류

CUDA 컨텍스트/cuDNN 초기화는 프로세스 생애 중 **1회성** 비용이고 GPU/드라이버 조합에
의존적이라, 코드를 고친다고 사라지는 비용이 아니다(위 "추가로 확인한 사실" 1번).
실측 없이 "얼마나 느린지" 모르는 상태에서 아키텍처를 바꾸는 것(예: 앱 시작 시 CUDA
프리워밍)은 **스파이크가 필요한 영역**으로 판단해 지금 결정하지 않는다.

- **지금 할 수 있는 것**: 작업 B의 `stage_changed` 신호 + 기존 "~완료" 로그가 이미
  시각(timestamp)을 `data/logs/app.log`에 남긴다. 추가로 `trainer.py`에 각 단계의
  소요 시간을 명시적으로 `log.info()`하도록(`time.perf_counter()` 측정 1줄씩) 작업 B에
  끼워넣으면, 다음에 "느리다"는 보고가 들어왔을 때 **어느 단계가 몇 초 걸렸는지 로그만
  보고 바로 알 수 있다.** 이는 작업 B의 범위를 아주 약간 확장하는 것뿐이라 별도
  라운드가 필요 없음 — 구현 에이전트가 B를 구현할 때 각 단계 종료 시 경과시간을 같이
  로그하도록 포함.
- **보류(스파이크 필요, 지금 결정하지 않음)**: 만약 B의 로그로 실측했을 때 `pick_device()`
  단계가 실제로 수 초~수십 초로 확인되면, "앱 시작 시(또는 학습 탭 진입 시) CUDA를
  미리 데워서 학습 시작 시점의 지연을 앱 기동 시점으로 옮긴다"는 선택지가 있다. 이건
  **기동 시간 증가 ↔ 학습 시작 지연 감소**라는 트레이드오프라 실측 데이터 없이 리더가
  결정하면 안 된다고 판단 — 리더에게 스파이크 필요 여부 보고(아래 "리더 보고" 참고).
- **범위 밖, 별도 백로그로만 기록**: `torch.backends.cudnn.benchmark`가 현재 꺼져있음
  (코드 어디에도 설정 없음) — 이건 "시작 구간이 느리다"는 이번 불편과는 무관한(매
  batch의 반복 비용에 영향) **별개의 성능 기회**다. random_crop 모드는 crop 크기가
  job 설정으로 고정이라 `cudnn.benchmark=True`를 켜도 안전할 가능성이 높지만, 이번
  3건 요청 범위가 아니므로 이번 라운드에 포함하지 않고 로드맵에 "향후 후보"로만 남긴다.

### 영향 파일
- `app/core/trainer.py` — 작업 B의 emit 지점에 `time.perf_counter()` 경과시간 로그 1줄씩
  추가(순수 추가, 작업 B와 같은 diff 범위 내에서 처리 — 별도 작업 단위 아님).

### 검증 체크리스트
- `data/logs/app.log`에 6단계 각각의 소요시간이 초 단위로 남는지, 특히 `device` 단계가
  이상치로 보이는지(1회성이라 두 번째 학습부터는 짧아질 것으로 예상 — 같은 세션에서
  job을 2개 이상 큐에 넣고 비교해보면 "1회성 비용" 가설을 바로 검증할 수 있음, 검증
  에이전트가 이 비교를 꼭 수행할 것).

---

## 실행 순서 요약

1. **작업 A(중지 버그 수정)** — `trainer.py` 단독, 가장 심각한 사용자 영향(앱이 안 닫힘),
   다른 작업과 의존관계 없음. 최우선 단독 라운드.
2. **작업 B+C(단계별 로그 UI + 시간 계측)** — `trainer.py`(새 시그널+타이밍 로그) +
   `training_progress_dialog.py` + `training_tab.py` + `i18n.py`. A와 같은 파일
   (`trainer.py`)을 건드리므로 A 완료·검증 후 순차 진행 권장(동시 병렬 금지 — diff
   충돌 위험, AGENTS.md "같은 파일 수정은 순차 진행" 관례). A가 수정하는 영역(배치 루프
   종료~validation~checkpoint, 257~340행대)과 B가 수정하는 영역(138~254행대, 준비 단계)은
   서로 겹치지 않지만, 같은 파일이라 **순차 진행**이 안전하다.
3. **작업 C의 알고리즘적 개선(CUDA 프리워밍 등)** — 보류. B 배포 후 실측 로그를 리더가
   확인하고, 필요하면 스파이크 에이전트에게 "프리워밍 비용 대 이득" 실측을 요청.

## 리더에게 보고할 사항 (스파이크 필요 여부)

- **CUDA 프리워밍(앱/탭 진입 시 미리 GPU 컨텍스트를 데우는 것)의 가치는 실측 전까지
  판단 보류.** 작업 B가 배포되면 로그로 `pick_device()` 단계 소요시간이 바로 보이므로,
  그 수치를 본 뒤에 "프리워밍이 필요한가"를 결정하는 것을 권장 — 지금 결정하지 않음.
  이건 기술 선택(아키텍처) 사이의 트레이드오프라 실측 근거 없이 기획 단계에서 결정하면
  안 된다고 판단했다.
- `cudnn.benchmark=True` 활성화는 이번 3건과 무관한 별개 성능 기회로, 결정이 필요한
  수준은 아니지만(리스크 낮음, 사용자가 요청한 적 없음) 참고용으로만 로드맵에 남겨둠.

## 사용자 결정 필요 지점

없음. 작업 A/B/C 전부 코드 근거로 설계가 확정됐고, 구현 재량으로 처리 가능한 선택
(위젯 높이, 정확한 문자열 등)만 남아 있어 `docs/decisions-needed.md`에 등록하지 않았다.
