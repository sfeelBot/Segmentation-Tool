# SECURITY — 모델 코드 샌드박스

## 위협 모델

이 앱은 **로컬 단독 사용 도구**다.
사용자는 자신의 PyTorch 모델 코드를 직접 붙여넣으므로
악의적인 코드보다는 **실수로 인한 피해**(무한 루프, 과도한 메모리 할당)가
주요 위협이다.

| 위협 | 발생 가능성 | 대응 |
|------|-------------|------|
| 실수로 `os.system()` 호출 | 낮음 | AST 차단 |
| 무한 루프로 앱 멈춤 | 중간 | QThread + stop_event |
| VRAM 고갈 | 중간 | memory_fraction 제한 |
| 악성 코드 고의 삽입 | 매우 낮음 (로컬 개인 도구) | AST 차단 + 제한적 exec |

---

## 방어 계층

### Layer 1: AST 정적 분석

코드를 **실행하지 않고** `ast.parse()`로 파싱하여 검사.

```python
BLOCKED_MODULES = {
    'os', 'sys', 'subprocess', 'socket', 'requests',
    'urllib', 'shutil', 'pathlib', 'builtins', 'ctypes',
    'importlib', 'pickle', 'shelve',
}
BLOCKED_CALLS = {
    'eval', 'exec', 'compile', 'open', '__import__',
    'globals', 'locals', 'vars', 'dir',
}
```

모든 `ast.Import` / `ast.ImportFrom` 노드의 모듈명을 `BLOCKED_MODULES`와 대조.
모든 `ast.Call` 노드의 함수명을 `BLOCKED_CALLS`와 대조.

### Layer 2: 제한적 실행 네임스페이스

검증 통과 후 `exec(code, safe_globals)` 실행.
`safe_globals['__builtins__']`에 허용 내장 함수만 포함.

```python
ALLOWED_BUILTINS = [
    'abs', 'all', 'any', 'bool', 'dict', 'enumerate',
    'filter', 'float', 'int', 'len', 'list', 'map',
    'max', 'min', 'range', 'round', 'set', 'sorted',
    'str', 'sum', 'tuple', 'zip', 'print', 'isinstance',
    'hasattr', 'getattr', 'setattr', 'super', 'type',
]
```

### Layer 3: QThread 격리

모델 실행(학습·추론)은 별도 `QThread`에서 수행.
메인 UI 스레드 영향 없음.
`stop_event: threading.Event`로 언제든 중단 가능.

### Layer 4: GPU 메모리 제한

```python
if torch.cuda.is_available():
    torch.cuda.set_per_process_memory_fraction(0.85)
```

---

## 리스크 수용 사항

이 앱은 개인 로컬 환경 전용이므로 다음은 의도적으로 허용한다:

- 사용자가 허용 모듈(torch, numpy 등) 안에서 파일 시스템 접근
  (예: `torch.save()`) — 학습 결과 저장에 필요
- subprocess 격리 미적용 — 로컬 환경에서 오버헤드 대비 이득 없음

다중 사용자 환경이나 외부 코드 실행이 필요한 경우:
`subprocess` + `multiprocessing.ProcessPoolExecutor` + `ulimit` 적용 필요.
