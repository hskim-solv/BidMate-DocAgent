# 0036: HwpNativeLoader를 pyhwp-gated 기본값으로 승격

- **Status**: superseded by [0049](./0049-kordoc-replaces-pyhwp-backend.md)
- **Date**: 2026-05-13
- **Superseded**: 2026-05-15 — pyhwp 0.1b15 API drift로 비공개 100-doc 실 eval에서 `hwp_native_rate = 0.0` 기록 (paragraph-only 추출이 RFP가 의존하는 table/heading 구조 손실). [ADR 0049](./0049-kordoc-replaces-pyhwp-backend.md)가 pyhwp 백엔드를 kordoc(npm 서브프로세스)으로 교체하고 `csv_text`를 무조건 fallback으로 유지.
- **Related**: [ADR 0001](0001-preserve-naive-baseline.md) (baseline 불변식), [`ingestion.py:_resolve_loader`](../../ingestion.py) (loader 라우팅), [issue #167](https://github.com/hskim-solv/BidMate-DocAgent/issues/167) (원본 spike), [issue #363](https://github.com/hskim-solv/BidMate-DocAgent/issues/363) (관측성), [issue #365](https://github.com/hskim-solv/BidMate-DocAgent/issues/365) (이 결정), [issue #426](https://github.com/hskim-solv/BidMate-DocAgent/issues/426) (구현)

## TL;DR

- HwpNativeLoader가 env-var opt-in이라 한국어 RFP 사용자가 더 나은 파서를 발견 못 함 — pyhwp 설치 감지 시 기본값으로 승격.
- `BIDMATE_HWP_LOADER=csv`를 명시적 opt-out, pyhwp 부재 시 CSV fallback 안전망 유지.
- 추후 ADR 0049가 pyhwp 0.1b15 API drift로 인해 kordoc 백엔드로 교체.

## 배경

`HwpNativeLoader` (`ingestion.py:L131`)는 issue #167에서 `BIDMATE_HWP_LOADER=native` opt-in spike로 추가. Issue #363이 `RuntimeWarning` + `last_fallback_reason` 관측성을 추가한 후 fallback 경로가 측정 가능해졌다.

Pre-Phase-3 audit가 env-var 게이트를 "scaffold가 load-bearing이 됨"으로 플래그 — 테이블 구조 추출이 실제로 필요한 한국어 RFP 사용자는 env var를 명시적으로 설정해야 해 더 나은 파서가 기본적으로 invisible. `with_tables=True` 변형(`BIDMATE_HWP_LOADER=native_tables`, issue #506)이 이를 가중: 두 미발견 knob이 타깃 corpus의 critical path를 제어.

## 결정

`_resolve_loader` (구현은 issue #426 트래킹)가 `importlib.util.find_spec("hwp5")`로 pyhwp 가용성을 감지하고, 패키지 존재 시 `HwpNativeLoader(with_tables=True)`를 기본값. `BIDMATE_HWP_LOADER=csv`가 CSV only 경로 필요 환경의 명시적 opt-out.

Env-var precedence (높음 → 낮음):
1. `BIDMATE_HWP_LOADER=csv` → `LOADERS["hwp"]` (CSV fallback, 명시적 opt-out)
2. `BIDMATE_HWP_LOADER=native` → `HwpNativeLoader(with_tables=False)` (text-only native)
3. `BIDMATE_HWP_LOADER=native_tables` → `HwpNativeLoader(with_tables=True)` (text + tables)
4. *(unset 또는 empty)* + pyhwp importable → `HwpNativeLoader(with_tables=True)` **← 새 기본값**
5. *(unset 또는 empty)* + pyhwp 부재 → `LOADERS["hwp"]` (무변; CI minimal 설치 안전)

`HwpNativeLoader.load()`가 이미 `ImportError`를 catch하고 `RuntimeWarning`과 함께 CSV text로 fallback하므로 case 5는 안전망이며 새 코드 경로 아님.

## 결과

**Easier:**
- pyhwp 설치된 한국어 RFP 사용자가 기본적으로 테이블 구조 획득 — env-var 문서 조회 불필요.
- 관측 가능한 `last_fallback_reason` 필드(issue #363)가 env-var-never-set 케이스가 아닌 실제 pyhwp 실패를 surface해 유용한 signal이 됨.
- `BIDMATE_HWP_LOADER=csv`가 발견 가능한, 문서화된 opt-out이지 invisible default 아님.

**Harder / constrained:**
- pyhwp가 문서화된 optional 의존성; `requirements-dev.txt` 또는 별도 `requirements-hwp.txt`가 선언해 기여자가 opt-in 가능해야.
- pyhwp 없는 CI smoke/test 실행이 case 5 (CSV fallback) cover해 import-detection 회귀 catch. 기존 `EMBEDDING_BACKEND=hashing` minimal 설치가 이미 충족.
- ADR 0001 naive-baseline 불변식 보존: `naive_baseline` eval preset이 HWP 파일을 로드 안 함; loader 기본값 변경이 eval bit-stability에 무영향.

**Re-open 조건:**
`BIDMATE_HWP_LOADER` unset으로 1회 `make real-eval` cycle 후 비공개 100-doc corpus에서 native-loader fallback rate가 20% 초과면 기본값 또는 pyhwp 감지 로직 재검토.

## 검토한 대안

- **Option 1 — Deprecate**: 한국어 RFP 사용자에게서 테이블 추출 capability 제거 — 사용 측정 없이 시기상조. pyhwp가 이미 동작하는데 premature.
- **Option 3 — visual_ingestion v2에 통합**: 올바른 장기 seam이나 `visual_ingestion.py` v2가 아직 미scoped. 이 결정을 phase-3 리팩토링에 블로킹하면 발견 가능성 수정이 무기한 지연.
- **Option 4 — Keep + Observe**: status quo env-var 게이트. Issue #363 landed 후 관측성이 측정 가능. 추가 deferral은 증거 축적이지만 더 나은 파서를 또 한 eval cycle invisible 유지.
