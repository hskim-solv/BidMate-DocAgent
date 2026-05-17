# 0018: 한국어 공개 RAG bench 를 보조 out-of-domain 표면으로

- **Status**: accepted
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md) (기준선 보존), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (eval 분리 discipline), [ADR 0012](./0012-llm-judge-on-public-synthetic.md) (추가 표면 패턴), [`eval/korean_public/`](../../eval/korean_public/), 이슈 #295

## TL;DR

- KorQuAD 2.1 dev 150 케이스 결정론 sample 에 기존 파이프라인 실행 — 한국어 일반 텍스트 일반화 sanity check.
- 절대 대체·CI gate 안 됨; `eval/korean_public/` 격리 → ADR 0005 의 3-way 분리로 확장.
- 헤드라인 수치는 의도적으로 낮음 — RFP 도메인 특화 시스템 문서화, target benchmark 아님.

## 배경

"한국 스택" 포트폴리오 포지셔닝은 코드에 존재 — `text_normalize.py` 의 조사 stripper, RFP 스타일 multi-doc 쿼리용 `apply_comparison_balance`, alias 자동 추출 — 그러나 **공개 검증 가능 한국어 수치** 뒷받침 부재. 두 기존 eval 표면 모두 본 갭 보유:

- **공개 합성** (`eval/config.yaml`, n=42): in-domain 손으로 쓴 RFP 케이스. reviewer 가 수치 재현 가능하나 corpus *자체* 가 파이프라인 튜닝된 shape.
- **Private 실데이터** (operator-side, n=21, ADR 0005 commit 경계): in-domain 실 RFP. reviewer 재현 불가.

"한국어 일반 텍스트에서 retrieval / citation 파이프라인이 어떻게 동작합니까?" 묻는 시니어 reviewer 에게 repo 에 가리킬 게 없음. *어떤* commodity 한국어 RAG benchmark — 낮은 점수라도 — 추가가 검증 가능 artifact 로 갭 봉쇄.

KorQuAD 2.x 가 dominant 한국어 MRC benchmark (CC BY-ND 2.0 KR, SQuAD-shape, 장문서 Wikipedia context). dev split 은 공식 미러에서 공개 다운로드 가능.

## 결정

**보조·미대체·미CI-gate** eval 표면 추가 — 기존 `rag_core.run_rag_query` 파이프라인을 KorQuAD 2.1 dev 결정론 150-질문 sample 에 실행. 표면은 `eval/korean_public/` 격리 → ADR 0005 spirit (합성-CI vs private-실데이터 분리) 가 *3-way* 분리로 보존.

구체적으로:

1. `eval/korean_public/fetch_korquad.py` 가 공식 KorQuAD 2.1 dev_00 ZIP 다운로드, HTML strip, `seed=17` 로 결정론 N=150 답 가능 점수 가능 질문 sample. raw archive 는 `data/korean_public/` 캐시 (gitignored — corpus 재배포 안 함). sample 파일 (`data/korean_public/korquad_dev_sample.json`) 도 gitignored; SHA-256 (fetcher 가 출력) 만 재현성 기록 원할 시 commit 적합.
2. `eval/korean_public/run.py` 가 corpus 빌드 (sampled 기사당 문서 1개, 기존 `build_index_payload_from_documents` 경로 사용) + bootstrap 95% CI 동반 4 메트릭 보고 (seed=17, 1000 resample, 합성 표면과 동일 머신):
   - `retrieval_recall_at_top_k` (기본 top-k=5)
   - `answer_substring_match` (gold 답을 `answer_text` substring)
   - `citation_doc_precision` (gold 기사 가리키는 인용)
   - `citation_coverage` (인용 생성한 쿼리 fraction)
3. 출력 `reports/korean_public/eval_summary.json` 거주 (기존 `reports/*` 패턴 gitignored).
4. `make korean-public-eval` 이 스크립트 end-to-end 실행.
5. **합성 CI eval (`pr-eval.yml`) 가 본 표면 호출 안 함.** 의도적: KorQuAD 수치는 파이프라인 정확성 아닌 upstream 데이터셋 분포 속성. PR gate 시키면 파이프라인 미변경 리팩터 처벌.

## 결과

Easier:

- "한국어 일반 텍스트 일반화" 질문에 reviewer 가 <2 분 안에 실행 가능한 구체·재현 수치.
- 합성 표면의 동일 `bootstrap_ci` 머신 + 재현성 해시 레시피 자연 확장 — Linux host eval 실행이 macOS 와 (wall-clock 지연 modulo) 동일 헤드라인 수치 생산해야.
- 새 한국어 공개 benchmark (AI Hub 행정문서, MIRAcL Korean, …) 가 `eval/korean_public/` sibling 으로 동일 shape 랜딩 가능 — KorQuAD 위가 아닌 옆 슬롯.

Costs / 정직성:

- **헤드라인 수치가 합성 표면 대비 나쁘게 보임.** hashing 백엔드 + naive_baseline 파이프라인 첫 사이클 측정 retrieval_recall@5 ~ 0.500, answer_substring_match ~ 0.013. **이는 정확 + load-bearing**: 파이프라인이 RFP 도메인 특화이며 일반 한국어 QA 시스템 아님을 문서화. README + senior-positioning 이 *일반화 sanity check* 로 framing, target benchmark 아님.
- raw KorQuAD archive 큼 (~93MB). fetch 단계 무료 아님; 스크립트가 적극 캐시 → 후속 run 거의 즉시.
- KorQuAD 2.x 가 단답 케이스 ("1", "1,200만 화소") 많음. `answer_substring_match` 가 그쪽에 permissive; exact-match 메트릭은 더 낮게 점수. 컨벤션상 substring match 보고 + `eval/korean_public/README.md` 에 트레이드오프 문서화.

본 ADR 이 **결정 안 하는** 것:

- cross-host 재현성 강제용 sample-파일 해시 commit 여부 — 실 기준선 원할 때 별도 결정.
- KorQuAD 수치를 README 헤드라인 메트릭 표에 fold 여부 — 초기 사이클은 in-domain / out-of-domain 주장 conflate 회피 위해 별도 섹션 유지.
- KorQuAD 1.0 (단답 SQuAD 스타일 passage) 확장 여부 — 범위 외; 2.x 가 RFP-shape 에 더 가까운 variant.

## 검토한 대안

- **AI Hub 한국어 행정문서 QA** — 가장 도메인 일치, 그러나 배포가 한국 학술/기관 로그인 필요. reviewer 재현성 죽이는 ("다운로드 한국 학술 이메일 필요") hard no.
- **MIRAcL Korean dev** — retrieval-only multilingual benchmark, 답-문자열 ground truth 없음. 3 신호 중 1개만 테스트; 합성 표면 측정 인용-grounding 축 누락.
- **소규모 in-house 한국어 RAG fixture 빌드** — 라이선스 이슈 우회, 그러나 reviewer 가 외부 세계 대비 검증 불가한 in-house 데이터셋 또 추가.
- **합성 표면을 KorQuAD 로 대체** — ADR 0001 (기준선 보존) + ADR 0005 (합성-CI 가 계약 테스트 거주) 위반. ADR 0011, 0013, 0014, 0015, 0017 과 같은 strict 추가-표면 discipline 적용.
