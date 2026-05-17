# 0034: VLM Provider 분석 변형 — Donut 보류 + PaddleOCR 실측

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-05-13 |
| **Issue** | #594 |
| **Supersedes** | — |
| **Superseded by** | — |

## TL;DR

- Donut(torch≥2.6 + safetensors 미충족)·PaddleOCR(합성 PDF에서 +0pp lift, latency 2.2×) 모두 현 시점 defer. tesseract baseline 유지.
- `BIDMATE_VISUAL_OCR=paddleocr` opt-in 인프라(`visual_ingestion.paddleocr_provider`)는 추가해 real-data 재검증 준비.
- Re-evaluation은 비공개 100-doc 또는 50+ 한국어 도메인 실데이터에서 text_recall +5pp lift 시.

## 배경

[docs/vision/vision-spike.md](../vision/vision-spike.md) (issue #168)에서 Donut vision 모델과 pytesseract baseline을 1-page 합성 PDF에서 비교. 결과: Donut은 `torch≥2.6 + safetensors` 요건 미충족으로 실측 불가, baseline text_recall=0.914가 상한선.

ADR 0034는 세 가지 확정:
1. **Donut defer 결정 공식화** (vision-spike.md 결론을 ADR로 격상).
2. **PaddleOCR PP-OCRv4 실측** — GPU-free 대안으로 같은 합성 PDF에서 측정.
3. **향후 VLM 채택 기준 명시** — 실 한국어 RFP corpus에서 lift 확인까지 ocr baseline 유지.

## 결정

**tesseract baseline 유지. PaddleOCR와 Donut 모두 현 시점 defer.**

추가: `BIDMATE_VISUAL_OCR=paddleocr`로 PaddleOCR를 opt-in 사용할 인프라(`visual_ingestion.paddleocr_provider`) 추가해 향후 real-data 재검증 준비.

## Measured Results

Spike 실행: `python3 scripts/run_donut_spike.py --backend all` (2026-05-13, 합성 1-page PDF, CPU, macOS)

| Backend | text_recall | heading_match | table_cell_match | field_P | field_R | latency/page |
|---|---|---|---|---|---|---|
| pymupdf+pytesseract (baseline) | 0.914 | 3/3 | 1.000 | 1.000 | 1.000 | 65ms |
| PaddleOCR PP-OCRv4 | 0.914 | 3/3 | 1.000 | 1.000 | 1.000 | 142ms |
| Donut (Korean-finetuned / base) | N/A | N/A | N/A | N/A | N/A | ~7s |

**Donut 오류**: `donut_load_failed: torch≥2.6 required (CVE-2025-32434); models still ship .bin (not .safetensors)`

**PaddleOCR 해석**: 합성 PDF는 ASCII 텍스트 기반이라 tesseract가 이미 ceiling 근접 처리. PaddleOCR 강점(복잡한 다단 레이아웃, 한자 혼용, 기울어진 텍스트)이 발현 안 됨 — baseline 대비 **+0pp lift, latency 2.2× 증가**.

## Rationale

### 왜 채택하지 않는가 (현 시점)

채택 기준 (vision-spike.md Decision):

1. **비공개 100-doc RFP corpus에서 ≥+5pp text_recall lift** — 측정 안 됨 (합성 0pp)
2. **GPU available in production / CI** — macOS CI는 CPU only; latency 불가
3. **Korean-finetuned .safetensors checkpoint** — Donut 한정; PaddleOCR는 CPU OK이나 (1) 미달
4. **ADR 제안 및 수락** — 이 ADR이 (4) 충족

PaddleOCR는 (1) + (2) 동시 충족해야 baseline 교체. 현재 실측은 (1) 미확인.

### 왜 인프라는 추가하는가

real-data 재검증 시 코드 변경 없이 환경 변수 하나로 provider 교체 가능:

```bash
BIDMATE_VISUAL_OCR=paddleocr python3 scripts/build_index.py --input_dir data/raw
python3 eval/run_parser_eval.py --artifacts artifacts/visual_paddleocr/ --gold eval/parser_gold.yaml
```

`paddleocr_provider`는 기존 `OcrProvider` 프로토콜을 구현하므로 `parse_visual_document`의 모든 호출 경로 동작.

## Alternatives Considered

| 대안 | 기각 이유 |
|---|---|
| TrOCR (Microsoft) | `transformers` 의존이 Donut과 동일; GPU 불리 |
| EasyOCR | MIT 라이선스, CPU 지원이나 한국어 모델 정확도 불확실 — 추후 benchmark 후보 |
| Qwen2.5-VL-3B-Instruct | VLM 통합 품질 높지만 GPU 메모리 ~6GB 필요, CI 경로 불가 |
| LayoutLMv3 (Microsoft) | document understanding 특화이나 OCR layer 미포함; ingestion 재설계 필요 |
| 현 상태 유지 (Donut opt-in 제공) | ADR 0001 baseline 불변식 준수. OCR provider 인프라만 확장 |

## 결과

**Positive**:
- `OCR_PROVIDERS`에 `"paddleocr"` 추가 → 세 backend 병렬 비교 인프라 완성.
- `scripts/run_donut_spike.py --backend paddleocr`로 재현 가능 spike 문서화.
- 향후 실 한국어 RFP에서 lift 확인 시 ADR 재평가 조건 명시.

**Negative / Risk**:
- `paddleocr paddlepaddle` 설치(~300MB)가 일부 환경에서 기존 패키지(safetensors, PyYAML) 업그레이드 가능. 설치 전 `pip check` 권장.
- `paddleocr_provider`는 optional dep — 미설치 시 `OcrUnavailable` 예외.

## Re-evaluation Trigger

다음 조건 중 하나 충족 시 ADR 재오픈해 채택 검토:

- 비공개 100-doc RFP corpus (또는 50+ 한국어 도메인 실데이터)에서 text_recall +5pp 이상 lift 확인
- EasyOCR 또는 다른 CPU-feasible 한국어 OCR가 위 조건 충족
- GPU가 CI / production path에 추가되고 Donut safetensors checkpoint 사용 가능

ADR 레이블: [`adr-reopen`](https://github.com/hskim-solv/BidMate-DocAgent/labels/adr-reopen)

## Implementation Notes

변경 파일:
- `visual_ingestion.py`: `paddleocr_provider` 추가, `OCR_PROVIDERS` 업데이트, `get_ocr_provider`에 `"paddleocr"` case 추가.
- `scripts/run_donut_spike.py`: `run_paddleocr` 함수, `--backend paddleocr|all` 추가.

회귀 보호: 기존 `tests/test_visual_donut_regression.py`가 `OcrProvider` 인터페이스와 factory wiring 검증 (model load 불필요). 새 provider는 같은 인터페이스 구현하므로 추가 회귀 테스트 불필요.
