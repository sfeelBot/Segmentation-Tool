# GitHub #22(신규) + #16 후속(코드리뷰 발견) 스코프 산정 (2026-08-29)

서로 무관한 두 건. 순서 제약 없음(파일 겹침 없음) — 병렬 진행 가능.

---

## GitHub #22 — installer로 설치 시 기존 버전 있는지 체크 필요

### 문제 정의
원문이 매우 짧다("installer로 설치 시 기존 버젼 있는지 체크 필요"). 코드 확인 결과
`installer/setup.iss`에는 `[Setup]` 섹션(`AppId`/`AppVersion`/`OutputBaseFilename` 등)만
있고 `[Code]` 섹션 자체가 없다 — `InitializeSetup()` 같은 커스텀 로직이 전혀 없어, 기존
설치가 있어도 사용자에게 어떤 안내도 없이 Inno Setup 기본 동작(같은 `AppId`면 같은 폴더에
덮어쓰기)만 조용히 일어난다.

### 현재 동작 (근거)
- `AppId={{{#MyAppId}}` (`03C2678A-B979-4B99-A68B-842EA853D667`, `build/release-defines.iss`)
  고정값 — 버전이 달라도 같은 GUID라 Inno Setup은 이미 "업그레이드"로 인식하고 알아서
  `DefaultDirName` 아래 파일을 덮어쓴다. 즉 "완전히 무방비"는 아니고, **표준 업그레이드
  동작은 이미 작동한다.** 다만:
  - 실행 중인 앱(EXE)을 안내 없이 덮어쓰려 하면 파일 잠금으로 설치가 실패하거나 일부만
    갱신될 수 있음 — 종료 확인 절차 없음.
  - 사용자에게 "기존 버전 X.Y.Z가 설치되어 있다"는 사실 자체를 알려주지 않음 — 사용자가
    실수로 구버전을 재설치하거나, 낮은 버전으로 "다운그레이드"해도 아무 경고가 없음.
- `PrivilegesRequired=lowest` (per-user 설치) — 레지스트리 조회는 `HKA`(권한에 따라
  HKLM/HKCU 자동 매핑) 루트를 써야 한다. GitHub #2 요청1(`.segproj` 연결) 설계에서 이미
  같은 결론을 냄 — 이번에도 동일 원칙 적용.

### 설계 (Inno Setup 표준 패턴, 실측 불필요 — 스파이크 대상 아님)
`[Code]` 섹션에 `InitializeSetup(): Boolean` 함수를 추가해:
1. `RegQueryStringValue(HKA, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'DisplayVersion', OldVersion)`
   로 기존 설치 버전 조회(Inno Setup이 언인스톨 등록 시 자동으로 넣어주는 표준 키).
2. 찾으면 `MsgBox`로 "기존 버전 {OldVersion}이 설치되어 있습니다. 계속하시겠습니까?" 안내
   (버튼 구성은 아래 "결정 필요" 참고).
3. 필요 시 `CreateMutex`/`FindWindowByWindowName` 등으로 앱이 실행 중인지 확인해 실행
   중이면 종료를 요청하는 것도 같은 함수에서 함께 처리 가능(표준 부가 패턴, 필수는 아님 —
   구현 시 리스크/이익 판단은 구현 에이전트 재량).

### BUG-016과의 관계
`QA.md` BUG-016(P3, Open): 무인 제거(`/VERYSILENT`) 후 설치 폴더와 `data\logs\`가 완전히
삭제되지 않는 문제. 이번 #22 설계가 "기존 버전 자동 제거 후 재설치" 방식을 택하면, 내부적으로
구버전 언인스톨러를 실행하게 되어 BUG-016이 재설치 과정에 직접 끼어든다(잔존 파일이 새 설치에
섞여 들어갈 위험). "경고만 하고 계속 진행"(Inno Setup 기본 덮어쓰기에 맡김) 방식이면 BUG-016과
무관하게 독립적으로 처리 가능. **어느 쪽을 택할지가 아래 결정 필요 사항과 직결됨.**

### zone 브랜치 이식성
zone은 별도 `installer/setup.iss` 파일(별도 `AppId`/제품명)을 갖고 있다 — 이번 라운드는
main만 수정하지만, `InitializeSetup()` 패턴 자체는 `{#MyAppId}` 같은 `#define` 매크로만
쓰기 때문에 zone 쪽에 그대로 복사해도 다른 코드 변경 없이 동작한다(일반적 패턴으로 설계됨).

### 결정 필요 사항 — `docs/decisions-needed.md` 등록 대상
원문만으로 정확한 원하는 동작을 알 수 없어 다음 3가지 중 선택 필요:
1. **경고만 하고 계속 진행** (기존 버전 X.Y.Z 발견 → 안내 팝업 → 확인 시 계속, Inno Setup
   표준 덮어쓰기에 맡김) — 최소 구현, BUG-016과 무관.
2. **기존 버전 자동 제거 후 새로 설치** (안내 팝업 → 확인 시 구버전 언인스톨러
   `UninstallString` 실행 → 완료 후 새 설치 진행) — BUG-016 잔존 파일 문제와 얽힘, 함께
   고칠지 별도로 둘지도 같이 결정 필요.
3. **구버전이 설치돼 있으면 설치 자체를 거부**(다운그레이드 방지 등 더 엄격한 정책) — 흔치
   않은 요구라 원문과 맞을 가능성은 낮지만 배제하지 않고 선택지에 포함.

기본 권장(제안일 뿐, 결정은 사용자 몫): 1번이 가장 낮은 리스크·최소 변경이며 "체크 필요"라는
원문과 가장 직접적으로 부합. 2번을 원한다면 BUG-016을 같은 라운드에서 함께 고치는 것을 권장.

### 구현 대상 파일
`installer/setup.iss` 1개 (신규 `[Code]` 섹션 추가). 코드(Python) 변경 없음.

### 검증 골든 패스 (결정 이후 구현 완료 시)
1. 구버전 installer로 먼저 설치 → 새 버전 installer 실행 → 안내 팝업에 기존 버전 번호가
   정확히 표시되는지 확인.
2. (2번 선택 시) 자동 제거 진행 후 설치 폴더에 구버전 잔재가 남지 않는지 확인(BUG-016
   시나리오와 겹치므로 같이 재현·확인).
3. 최초 설치(기존 버전 없음) 시 안내 팝업이 뜨지 않고 정상 진행되는지 확인(회귀 없음).
4. `PrivilegesRequired=lowest` 상태에서 관리자 권한 없이도 레지스트리 조회가 정상 동작하는지
   확인(HKA 매핑 검증).

---

## GitHub #16 후속 — retry 헬퍼를 다른 파일 쓰기 경로로 확장

### 배경
GitHub #16 수정(커밋 `6ecee43`)이 `app/widgets/export_dialog.py`의 모듈 레벨 함수
`_copy_with_retry()`를 만들어 그 파일의 `shutil.copy2` 호출 3곳(json/yolo/coco 내보내기)에만
적용했다. 오늘 코드리뷰에서 같은 부류의 문제(백신/OneDrive/탐색기 미리보기 등 일시적 파일
잠금)에 노출된 다른 쓰기 경로 4곳이 재시도 없이 그대로 남아있는 것을 확인:

| 파일:줄 | 쓰기 방식 | 현재 보호 | 비고 |
|---|---|---|---|
| `app/widgets/import_dialog.py:79` | `shutil.copy2()` | 없음 | `ImportWorker.run()`, 외곽 `try/except`는 있으나 재시도 없이 즉시 실패 처리 |
| `app/widgets/image_browser.py:83` | `shutil.copy2()` | `except Exception: skipped += 1` (재시도 없음) | **bare-ish except가 실패 원인 구분 없이 조용히 스킵 — 재시도와 별개의 관찰성 버그** |
| `app/widgets/image_browser.py:348` | `shutil.copy2()` | **전혀 없음**(예외 그대로 전파) | 단일 파일 추가(`_on_add`) 경로, UI 슬롯에서 미처리 예외 → Qt 처리로 흘러감 |
| `app/core/annotation_store.py:158-160` (`save()`) | `Path.write_text()` | 없음(재시도도, 원자적 쓰기도 없음) | **가장 빈번한 쓰기 경로** — 라벨링 편집마다 호출됨 |
| `app/core/trainer.py:382, 389` | `torch.save()` | 없음 | 체크포인트 저장 — 실패 시 몇 시간짜리 학습 산출물 유실 위험 |

같은 파일 `annotation_store.py`의 `set_ok_and_clear_annotations()`(216~256행)는 이미
temp파일 생성 + `os.fsync` + `os.replace` 원자적 쓰기 패턴을 쓰고 있다 — 재사용 가능한
기존 관례.

### 설계 — 신규 최소 모듈 `app/core/file_io.py`
자료형이 제각각(`shutil.copy2` / `Path.write_text` / `torch.save`)이라 하나의 함수로 억지
통합하지 않고, **호출부가 자기 쓰기 로직을 클로저로 넘기는 2개의 작은 제네릭 헬퍼**로
분리한다(CLAUDE.md "core 모듈은 예외를 그대로 raise" 준수 — 마지막 시도 실패 시 원래
예외를 그대로 올린다):

```python
def retry_on_permission_error(write_fn, *, attempts=3, delay=0.3):
    """write_fn()을 실행. PermissionError만 재시도(백신/탐색기 미리보기/OneDrive 등
    일시적 잠금 대응), 다른 예외나 마지막 시도 실패는 그대로 raise."""
    for i in range(attempts):
        try:
            return write_fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def atomic_write(path: Path, write_fn: Callable[[Path], None], *, attempts=3, delay=0.3) -> None:
    """write_fn(temp_path)로 같은 디렉터리의 임시 파일에 쓴 뒤 retry_on_permission_error로
    감싼 os.replace(temp_path, path)로 교체. 중간에 실패하면 temp 파일 정리 후 raise.
    (set_ok_and_clear_annotations()의 기존 temp+replace 패턴을 일반화한 것.)"""
```

적용:
- **`export_dialog.py` 기존 `_copy_with_retry()` 제거**, 호출부 3곳을
  `retry_on_permission_error(lambda: shutil.copy2(src, dst))`로 교체(동작 동일, 중복
  제거).
- **`import_dialog.py:79`**: `retry_on_permission_error(lambda: shutil.copy2(src_img, img_path))`.
- **`image_browser.py:348`(`_on_add`)**: `retry_on_permission_error(...)`로 감싸고,
  실패 시 `QMessageBox.critical()`로 표시(CLAUDE.md UI 예외 처리 원칙 — 이 경로는 UI
  슬롯이라 지금처럼 예외를 그냥 흘려보내면 안 됨. 현재도 미처리라 이번에 같이 고침).
- **`image_browser.py:83`**: 재시도는 `retry_on_permission_error`로 감싸되, **재시도까지
  실패한 경우에만** 기존처럼 `skipped += 1` 카운트(폴더 일괄 추가라 개별 실패로 전체를
  중단시키지 않는 현재 정책은 유지). 단, `except Exception`을 `except (PermissionError, OSError)`
  정도로 좁히고 **`log.warning()`을 추가**해 실패 원인이 조용히 사라지지 않게 한다 — 이건
  재시도와 무관한 별개 버그(관찰성 문제)이므로 최소 수정만(로그 추가), 동작 자체(스킵하고
  계속 진행)는 바꾸지 않는다. YAGNI — 실패 목록을 사용자에게 팝업으로 보여주는 것까지는
  이번 요청 범위 밖.
- **`annotation_store.save()`**: `_ann_path(image_path).write_text(...)` 한 줄을
  `atomic_write(_ann_path(image_path), lambda p: p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"))`
  로 교체. 부수 효과로 크래시/전원차단 도중에도 라벨 JSON이 반쪽짜리로 남지 않는 원자성까지
  같이 확보됨(가장 빈번한 쓰기 경로라 이 이득이 큼). `set_ok_and_clear_annotations()`도
  같은 헬퍼로 리팩터링해 중복 제거(선택 사항, 트리비얼하면 같이 정리 — 동작 변경 없음).
- **`trainer.py:382, 389`**: `torch.save(checkpoint, path)` → `atomic_write(path, lambda p: torch.save(checkpoint, p))`.
  체크포인트는 몇백MB~GB급일 수 있어 임시파일이 같은 디렉터리(`checkpoints_dir()`)에
  생성되는지 확인 필요(다른 드라이브면 `os.replace`가 실패할 수 있음 — `atomic_write`는
  `path.parent`에 `tempfile.mkstemp`하도록 설계해 이 문제를 원천적으로 피함).
  **부가 발견**: 같은 파일 396행 부근 `training_metrics.json`의 `write_text()`도 동일한
  무보호 쓰기 패턴이지만 이번 요청(#16 후속) 대상 목록에는 없었음 — 손실 시 심각도가
  체크포인트보다 낮고(재학습 없이도 대부분 정보 복구 가능) 범위 확대 지시가 없어 **이번
  라운드에서는 손대지 않음**(YAGNI). 트리비얼하게 같은 헬퍼를 끼워 넣을 수 있는 자리라는
  점만 기록해둔다 — 필요 시 후속으로.

### 스코프에서 제외한 것 (YAGNI)
- `shutil.copy2` 4곳에 `atomic_write` 패턴까지 적용하지 않음 — `copy2`는 이미 OS 레벨에서
  파일 전체를 복사하는 단일 호출이고, 실패해도 대상 경로에 원본 이미지가 있던 게 아니라
  신규 생성이라 원자성 이득이 낮음(반쪽 파일이 남아도 재시도/재추가로 복구 쉬움) + 대용량
  이미지 복사를 임시파일 경유로 두 번 쓰면 I/O가 배가됨. retry만으로 충분.
- 재시도 횟수/딜레이 값은 기존 `_copy_with_retry()`와 동일(`attempts=3, delay=0.3`) 그대로
  이식 — 새 값 튜닝 근거 없음.
- `image_browser.py:83`의 실패를 사용자에게 팝업으로 알리는 것: 범위 밖(로그만 추가).

### 결정 필요 사항
없음 — 설계가 확정적이고 트레이드오프가 명확해 바로 구현 가능.

### 구현 대상 파일
- 신설: `app/core/file_io.py` (제네릭 헬퍼 2개, Qt 의존성 없음)
- 수정: `app/widgets/export_dialog.py`(`_copy_with_retry` 제거 후 교체), `app/widgets/import_dialog.py`,
  `app/widgets/image_browser.py`(2곳), `app/core/annotation_store.py`(`save()`, 선택적으로
  `set_ok_and_clear_annotations()` 중복 제거), `app/core/trainer.py`(2곳)

### 검증 골든 패스
1. 정상 경로(잠금 없음) — 라벨링 편집·저장, 학습 체크포인트 저장, 이미지 추가/폴더추가,
   가져오기/내보내기가 전부 기존과 동일하게 동작하는지 회귀 확인(가장 중요 — 이번 변경이
   앱에서 가장 자주 실행되는 경로 `annotation_store.save()`를 건드리므로).
2. `annotation_store.save()` 도중 프로세스를 강제 종료(또는 디스크 공간 인위 부족)해도
   기존 라벨 JSON이 손상되지 않고 그대로 남아있는지 확인(원자성 검증).
3. (가능하면) 대상 파일을 다른 프로세스로 열어 잠금을 건 상태에서 각 경로 실행 → 재시도
   로그(`time.sleep` 3회) 후 최종 실패 시 원래 예외 메시지(`PermissionError`)가 그대로
   사용자/로그에 노출되는지 확인.
4. `image_browser.py:348`(`_on_add`)에서 실패 시 `QMessageBox.critical()`이 뜨고 앱이
   크래시하지 않는지 확인(기존엔 미처리 예외였음 — 회귀 아니라 신규 방어).
5. `image_browser.py:83`(폴더 일괄 추가) 실패 시에도 전체 작업이 중단되지 않고 계속
   진행되며, `log.warning()`으로 실패 원인이 기록되는지 확인.
6. 체크포인트 저장 경로(`checkpoints_dir()`)가 임시파일 생성 위치와 같은 파일시스템인지
   확인(다른 드라이브 마운트 등 특수 환경에서 `os.replace` 실패 여부).
