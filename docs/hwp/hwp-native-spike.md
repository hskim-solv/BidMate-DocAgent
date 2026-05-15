# HWP native parser spike (issue #167)

## 목적

기존 `HwpCsvTextLoader` ([`ingestion.py`](../../ingestion.py))는 HWP 본문을 native parse하지 않고
`data_list.csv`의 `텍스트` 컬럼 — 사용자가 사전에 추출해 둔 plain text — 에 의존한다.
한국어 RFP / 나라장터 corpora에서는 이 사전 추출 단계가 외부 preprocessing
종속성으로 남아 있어, native HWP parsing이 가능하다면 그 의존성을 제거할 수 있다.

[`docs/visual-ingestion-v2.md`](../vision/visual-ingestion-v2.md)의 "What this is NOT" 섹션은
이 한계를 명시적으로 라벨링하고 native HWP parser를 "후속 단계 항목"으로 남겨두었다.
본 spike가 그 후속 단계의 첫 측정이다.

## What this is NOT

- **Productionization 아님.** native loader는 opt-in 환경변수로만 활성화되며 기본
  ingestion 경로(CSV `텍스트`)는 보존된다 (ADR 0001 baseline invariant).
- **HWPX 지원 아님.** XML 기반 HWPX 변종은 별도 이슈로 분리한다.
- **HWP→PDF visual ingestion 변경 아님.** `visual_ingestion.py`의 `visual_fallback_hwp`
  경로는 본 spike 범위가 아니다.
- **`텍스트` 컬럼 required 해제 아님.** 데이터 컨트랙트는 그대로 유지한다 (adopt 결정 시 별도 PR).

## Modes (2026-05-13 update — PR-C1)

`BIDMATE_HWP_LOADER` 의 세 가지 값:

| 값 | Loader | 출력 | 측정 baseline |
|---|---|---|---|
| 미설정 / 기본 | `HwpCsvTextLoader` | CSV `텍스트` 컬럼 | ADR 0001 baseline (불변) |
| `native` (#167 spike) | `HwpNativeLoader(with_tables=False)` | paragraph plain text | 본 문서의 측정 baseline |
| `native_tables` (#506 / PR-C1) | `HwpNativeLoader(with_tables=True)` | paragraph plain text **+** 표 셀 (row/col/span metadata) | 별도 측정 — body text 는 `native` 와 동일, 표는 별도 sections |

`native_tables` 모드는 `Section.events()` cooked event stream 을 순회하며
`TableBody` / `TableCell` model 진입을 추적해 셀 내부 `Text` 페이로드를 누적,
표 외부 paragraph 와 격리한다 (셀 텍스트가 본문에 누설되지 않으므로 BM25 중복
색인 위험 없음). pyhwp 미설치 / 파싱 실패 시 silent CSV fallback 그대로
(``last_native_tables=[]``, `RuntimeWarning` 발생).

## Scope

다음 라이브러리를 spike 대상으로 한다.

- **`pyhwp`** (`hwp5.xmlmodel.Hwp5File`) — Python 기반 HWP 5.x 파서. 구조화된 paragraph /
  text_chunk 추출 가능. PyPI: `pip install pyhwp`.
- **`olefile`** — HWP는 OLE compound document이므로 OLE stream 단위 raw 접근의
  안전망. pyhwp가 cover하지 못하는 변종이 있을 때 fallback으로 사용한다 (현 spike에서는
  pyhwp만 1차 경로로 wired, olefile은 follow-up 옵션으로 남김).

측정 차원:

1. **Text recall** — CSV `텍스트` 컬럼 대비 native가 더 많은 본문을 복원하는가.
2. **표 (table) 재구성** — 셀 병합/분할/multi-row 헤더가 보존되는가.
3. **읽기 순서** — heading / 본문 / footnote / textbox 순서 보존.
4. **인코딩** — 한글 자모 분리·결합, 특수문자(₩, ㎡, ㈜ 등) 손상 여부.
5. **Latency** — doc 1건 파싱 시간 (p50, p95).

## 설계

### Opt-in dispatch

[`ingestion.py`](../../ingestion.py)의 `_resolve_loader()`가 환경변수
`BIDMATE_HWP_LOADER=native`일 때 `HwpNativeLoader` 인스턴스를 반환한다.
미설정 / 빈 문자열 / 그 외 값에서는 기존 `HwpCsvTextLoader`가 유지된다.

```python
# 기본 (ADR 0001 baseline)
docs, _ = load_documents_from_metadata_csv(csv_path, files_dir)
# → text_source = "data_list_csv_text"

# Opt-in
os.environ["BIDMATE_HWP_LOADER"] = "native"
docs, _ = load_documents_from_metadata_csv(csv_path, files_dir)
# → text_source = "hwp_native" (성공 시), "data_list_csv_text" (fallback 시)
```

### Failure policy (3-단 fallback)

`HwpNativeLoader.load_text()` 내부:

1. `with_tables=False` (기본 `native` 모드) 면 `_extract_hwp_native(source_path)`,
   `with_tables=True` (`native_tables` 모드, PR-C1) 면
   `_extract_hwp_native_with_tables(source_path)` 시도.
2. `ImportError` (pyhwp 미설치) / `OSError` (OLE 헤더 오류 등) / `RuntimeError`
   (파싱 중 예외) 발생 시 native 결과를 버리고 CSV `텍스트` 컬럼 사용.
   `last_native_tables` 는 `[]` 로 reset.
3. CSV 컬럼도 비어 있으면 기존 `empty_text` failure로 처리 — 기존 taxonomy 그대로.

이 정책 덕에 pyhwp가 설치되지 않은 환경(CI 포함)에서도 native loader는 silent
fallback으로 동작하고, regression 테스트는 mock 기반으로 모든 경로를 가드한다.

### Metadata 표시

`text_source` metadata 키가 더 이상 하드코딩되지 않는다. 성공한 native 추출은
`"hwp_native"`, fallback은 `"data_list_csv_text"`로 마킹된다.
downstream eval / 분석 코드가 이 값을 보고 spike의 성능 영향을 분리할 수 있다.

## 측정 실행 가이드

샘플 raw HWP 파일은 ADR 0005 (private data boundary)에 따라 커밋되지 않는다.
spike 결과 수치만 본 문서에 기록한다.

### 준비

```bash
pip install pyhwp olefile
```

### 실행

로컬에 `<HWP_DIR>/`에 5–10개의 한국어 RFP HWP 파일을 두고, 동일한 파일을
참조하는 `data_list.csv`(컬럼: `공고 번호`, `사업명`, `발주 기관`, `파일형식=hwp`,
`파일명`, `텍스트`)를 작성한다. `텍스트` 컬럼에는 사용자가 사전 추출한 baseline 본문이
들어간다 (대조군).

```bash
# Baseline (CSV)
python3 -c "
import json
from ingestion import load_documents_from_metadata_csv
docs, _ = load_documents_from_metadata_csv('<CSV>', '<HWP_DIR>')
print(json.dumps([{'doc': d['doc_id'], 'src': d['metadata']['text_source'],
                   'len': len(d['sections'][0]['text'])} for d in docs], indent=2,
                 ensure_ascii=False))
"

# Native
BIDMATE_HWP_LOADER=native python3 -c "
import json
from ingestion import load_documents_from_metadata_csv
docs, _ = load_documents_from_metadata_csv('<CSV>', '<HWP_DIR>')
print(json.dumps([{'doc': d['doc_id'], 'src': d['metadata']['text_source'],
                   'len': len(d['sections'][0]['text'])} for d in docs], indent=2,
                 ensure_ascii=False))
"
```

native 경로에서 `src`가 모두 `"hwp_native"`로 떨어지면 파싱 성공, `"data_list_csv_text"`가
섞이면 해당 파일에서 fallback이 발생한 것이다 (raw HWP 변종 / 버전 / OLE 오류 등).

## 결과 (측정 후 채울 것)

샘플 N = TBD개 (사용자 로컬), HWP 5.x.

| 차원 | CSV baseline | Native (pyhwp) | Δ / 비고 |
|---|---|---|---|
| 본문 char 길이 (median) | TBD | TBD | TBD |
| 표 재구성 (cell count, 5건 표본) | n/a (CSV는 plain) | TBD | TBD |
| 읽기 순서 보존 (heading→body→footnote) | n/a | TBD | TBD |
| 인코딩 오류 (자모 분리, ㈜/₩/㎡ 손상) 건수 | 0 | TBD | TBD |
| Latency / doc (median, p95 ms) | < 5 | TBD | TBD |
| fallback 빈도 (native→CSV) | n/a | TBD / N | TBD |

## 결정 (TBD)

- [ ] **Adopt as default** — 후속 PR에서 (a) requirements.txt에 `pyhwp` 추가, (b) ADR 작성
  (pipeline 변경 = ADR threshold 통과), (c) `텍스트` 컬럼 optional 전환 검토.
- [ ] **Adopt as opt-in only** — 기본은 CSV 유지, 사용자가 원할 때 환경변수로 활성화.
  이번 PR 형태 그대로 유지하고 후속 작업 없음.
- [ ] **Reject** — pyhwp 출력이 baseline에 미달하거나 라이센스 / 유지보수 리스크가
  크면 native loader 자체를 제거한다 (지금 시점의 spike 결과는 본 문서에 기록만 남김).

결정 사유: _측정 결과 채운 뒤 1–2 문장으로 기록한다._

## 위험

- **pyhwp 유지보수.** 최근 릴리스 cadence가 느린 편이다. 적용 시 pinned version으로
  requirements 관리 필요.
- **라이센스.** pyhwp는 GPL-3 (확인 필요). 사내 RFP 데이터에 적용 시 호환 검토 필요.
- **표 셀 reconstruction 난이도.** HWP는 표 셀이 document tree에 산재해 있어 단순
  paragraph 추출만으로는 표 구조가 복원되지 않을 수 있다. spike 측정에서 가장 약점
  가능성이 큰 차원. → **PR-C1 (#506) 에서 `native_tables` 모드로 별도 해소.**
  cooked event stream 의 `TableBody` / `TableCell` 진입을 추적해 셀 텍스트를 본문과
  격리·셀 좌표 (row/col/span) 보존; 본 spike 의 `native` 모드는 변경 없음.
- **#160 real-eval baseline 미해결.** 본 spike의 default 경로는 미변경이라 ingestion
  단계 회귀는 unit test로 가드되지만, 실제 `make real-eval-delta`의 byte-equal
  검증은 #160 해결 후에만 신뢰 가능하다.

## 관련

- 이슈: [#167](https://github.com/hskim-solv/BidMate-DocAgent/issues/167)
- ADR: [0001 — preserve naive baseline](../adr/0001-preserve-naive-baseline.md)
- 선행 문서: [visual-ingestion-v2.md](../vision/visual-ingestion-v2.md) "What this is NOT" §
- 후속 (HWPX 등): 별도 이슈
