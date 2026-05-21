# Layout-aware visual 수집(ingestion) spike (Donut)

issue #168 추적. OCR 기준선(`pymupdf` text layer + `pytesseract` fallback)과 layout-aware vision encoder-decoder(`Donut`)를 정직하게 1-페이지로 비교한다. [`visual_ingestion.py`](../../visual_ingestion.py) 의 모듈 docstring(4-10행)에서 지적한 "layout-aware vision foundation model 미평가" 갭을 해소한다.

## 범위(Scope)

- 제목 / 메타데이터 / 필드 / 표 / 단락을 포함한 **단일 1-페이지 합성(synthetic) PDF**(runner 가 재현 가능하게 생성; 커밋되는 바이너리 없음).
- **두 파이프라인 비교**: 현재의 `pymupdf+pytesseract` vs. 렌더링된 페이지 이미지에 대한 Donut.
- **결정은 여기 문서화되며 강제되지 않는다** — OCR 파이프라인은 ADR 0001 의 preserve-baseline invariant 에 따라 기본값으로 유지된다. Donut 은 `BIDMATE_VISUAL_OCR=donut` 환경변수 또는 `get_ocr_provider("donut")` 를 통한 opt-in 이다.

## Runner

```bash
# Both pipelines on a generated synthetic PDF, write results into this doc
pip install torch transformers sentencepiece     # one-time, ~800MB+
python3 scripts/run_donut_spike.py --write-doc

# Use a real (e.g. private) Korean RFP PDF — no ground truth, side-by-side dump
python3 scripts/run_donut_spike.py --input path/to/rfp.pdf

# Just the baseline (no torch needed)
python3 scripts/run_donut_spike.py --backend baseline
```

선택적 모델 override:

```bash
BIDMATE_DONUT_MODEL=naver-clova-ix/donut-base python3 scripts/run_donut_spike.py
```

기본 모델은 `daekeun-ml/donut-base-finetuned-korean`(issue 권고에 따른 Korean-finetuned)이며 `naver-clova-ix/donut-base`(English-trained generic)로 자동 fallback 한다. runner 는 모델을 in-process 로 캐시하므로 반복되는 `--input` 실행에서 재로드하지 않는다.

## 요구사항 & 주의점(Requirements & gotchas)

- `torch` 는 `requirements.txt` 에 **없다** — spike 실행 시에만 설치된다. 기본 설치는 가볍게 유지된다.
- **`torch>=2.6` 필요** — 구버전은 [CVE-2025-32434](https://nvd.nist.gov/vuln/detail/CVE-2025-32434) 에 따라 `.bin` checkpoint 로딩을 거부한다. Donut 모델은 여전히 `.bin`(`.safetensors` 아님)을 배포한다.
- **`sentencepiece`** 는 Donut 의 tokenizer 가 요구한다; 명시적으로 설치하라.
- Korean-finetuned 모델 ID `daekeun-ml/donut-base-finetuned-korean` 는 HF 에서 사용 불가(404)일 수 있다. runner 는 로드 실패 시 base 모델로 fallback 하고 실제로 로드된 모델로 결과를 라벨링한다.
- **GPU 강력 권장.** CPU 추론은 페이지당 수 초가 걸린다; 이 spike 는 GPU 에서만 규모 있게 실용적이다.

## 결과(Results)

_`scripts/run_donut_spike.py` 가 2026-05-11 19:12:57 +0900 에 생성. Ground truth: 합성(synthetic) 생성 PDF._

| Metric | text_recall | heading_match | table_cell_match | field_p | field_r | latency_s |
| --- | --- | --- | --- | --- | --- | --- |
| pymupdf+pytesseract | 0.914 | 3/3 | 12/12 | 1.0 | 1.0 | 0.12 |
| donut (naver-clova-ix/donut-base) | 0.0 | 0/3 | 0/12 | 0.0 | 0.0 | 7.132 |

**에러(Errors):**
- donut (naver-clova-ix/donut-base): donut inference failed: donut_load_failed: Due to a serious vulnerability issue in `torch.load`, even with `weights_only=True`, we now require users to upgrade torch to at least v2.6 in order to use the function. This version restriction does not apply when loading files with safetensors.
See the vulnerability report here https://nvd.nist.gov/vuln/detail/CVE-2025-32434

## 결정(Decision)

**OCR 기준선을 기본값으로 유지한다.** Donut 채택은 다음 기준에 게이트되며, 아직 어느 것도 충족되지 않았다:

1. [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md) 의 real-data 규율에 따라 (합성(synthetic) 아닌) **private 100-doc RFP corpus** 에서 측정된 ≥X percentage-point 향상(lift).
2. 제품 / CI 경로에서 GPU 사용 가능(CPU latency 는 감당 불가).
3. `.safetensors` weights 를 가진 안정적인 Korean-finetuned 모델 checkpoint(torch≥2.6 마찰 회피).
4. [ADR 0001](../adr/0001-preserve-naive-baseline.md) 의 preserve-baseline invariant 에 따라 extractive OCR 경로를 대체하기 위한 ADR 제안 및 수락(accepted).

당분간 Donut 은 reviewer 가 탐색을 위해 켤 수 있는 **진단 옵션(diagnostic option)** 이다:

```python
from visual_ingestion import get_ocr_provider, parse_visual_document
parse_visual_document(pdf, ocr_provider=get_ocr_provider("donut"))
```

## 재현 / 확장(Reproduce / extend)

두 파이프라인 모두 `OcrProvider` 인터페이스([`visual_ingestion.py:44`](../../visual_ingestion.py))를 통해 pluggable 하다. 다른 vision 모델(예: `pix2struct`, ColPali, LayoutLMv3) 추가는 `str` 또는 `list[dict[text, bbox, confidence]]` 를 반환하는 새 provider 함수다 — 기존 `normalize_ocr_result`([`visual_ingestion.py:577-581`](../../visual_ingestion.py))가 두 형태 모두 처리한다.

회귀 테스트 [`tests/test_visual_donut_regression.py`](../../tests/test_visual_donut_regression.py) 는 어떤 모델도 로드하지 않고 배선(wiring)을 보호한다; CI 는 `bash scripts/test.sh` 의 일부로 실행한다.
