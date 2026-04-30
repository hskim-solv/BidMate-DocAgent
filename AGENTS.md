# AGENTS.md

## Purpose
이 저장소는 RFP 문서 이해를 위한 Agentic RAG 시스템을 재현 가능하게 유지하는 것을 목표로 한다.

모든 변경은 아래 원칙을 따라야 한다.
- 먼저 현재 baseline을 깨지 않는지 확인한다.
- 변경 이유와 검증 결과를 남긴다.
- README의 실행 흐름과 산출물 경로를 유지한다.
- 불필요한 구조 변경보다 작은 단위의 검증 가능한 변경을 선호한다.

---

## Repository map
- `app.py`: CLI 질의 실행 엔트리포인트
- `rag_core.py`: 핵심 RAG 파이프라인 로직
- `scripts/`: 인덱싱 및 README metric 갱신 스크립트
- `eval/`: 평가 스크립트 및 설정
- `data/raw/`: 공개 synthetic RFP 입력 문서
- `data/index/`: 생성된 인덱스 산출물
- `outputs/`: 질의 실행 결과
- `reports/`: 평가 결과
- `docs/`: 설계 배경, 실패 사례, 회고 문서

---

## Ground rules
1. 먼저 현재 동작을 재현하고, 그 다음 변경한다.
2. 한 번에 하나의 목적만 수정한다.
3. README에 적힌 기본 실행 순서를 함부로 바꾸지 않는다.
4. 산출물 기본 경로는 유지한다.
   - `data/index/`
   - `outputs/`
   - `reports/`
5. 새 기능 추가보다 재현성, 안정성, 근거성을 우선한다.
6. 의존성 추가는 꼭 필요할 때만 한다.
7. 큰 리팩터링은 요구되지 않은 한 피한다.
8. 동작이 바뀌면 관련 문서도 함께 갱신한다.
9. 질의 응답 품질을 바꾸는 수정은 반드시 평가 결과와 함께 제시한다.
10. 실패하면 숨기지 말고 원인을 분류해 보고한다.
    - 환경 문제
    - 경로/입출력 문제
    - 의존성 문제
    - 로직 문제
    - README와 실제 코드 불일치

---

## Default workflow
작업을 시작할 때는 아래 순서를 기본으로 따른다.

### 1) 환경 확인
가능하면 현재 의존성으로 그대로 재현한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 인덱싱
```bash
python3 scripts/build_index.py --input_dir data/raw --output_dir data/index
```

### 3) 샘플 질의 실행
```bash
python3 app.py --input_dir data/index --output_dir outputs --query "기관 A와 기관 B의 AI 요구사항 차이 알려줘"
```

### 4) 평가 실행
```bash
python3 eval/run_eval.py --index_dir data/index --output_dir reports --config eval/config.yaml
```

### 5) README 일관성 검증
```bash
python3 scripts/update_readme_metrics.py --report reports/eval_summary.json --readme README.md --check
```

---

## What to do before editing code
코드를 수정하기 전에 우선 아래를 확인한다.
- 현재 baseline이 실제로 실행되는가
- 인덱스가 생성되는가
- 질의 결과 파일이 생성되는가
- 평가 요약 파일이 생성되는가
- README metric check가 통과하는가

위가 실패하면, 기능 추가보다 먼저 재현 실패 원인을 찾는다.

---

## Change policy
### 허용되는 우선 변경
- 깨진 실행 경로 수정
- 문서와 실제 코드 불일치 수정
- 작은 버그 수정
- 테스트/스모크 실행성 강화
- 평가 재현성 개선
- 로그/에러 메시지 개선

### 신중해야 하는 변경
- retrieval 전략 전면 교체
- answer generation 로직 대폭 수정
- 파일/디렉터리 구조 대규모 이동
- 기본 CLI 인터페이스 변경
- metric 정의 변경

이런 변경은 반드시 이유와 영향을 요약한다.

---

## Output expectations
작업이 끝나면 아래 형식으로 결과를 요약한다.

1. 무엇을 바꿨는지
2. 왜 바꿨는지
3. 어떤 파일을 수정했는지
4. 어떤 명령으로 검증했는지
5. 결과가 어땠는지
6. 남아 있는 리스크가 무엇인지

---

## Done definition
작업 완료로 간주하려면 가능한 범위에서 아래를 만족해야 한다.

### 최소 완료 조건
- 관련 코드가 실행된다
- 기존 기본 경로를 유지한다
- 에러가 있으면 재현 가능한 방식으로 설명한다

### 권장 완료 조건
- 인덱싱 성공
- 샘플 질의 성공
- 평가 실행 성공
- README metric check 성공

### 품질 변경 작업의 완료 조건
- 변경 전/후 차이를 설명한다
- `reports/eval_summary.json` 기준으로 영향 요약
- groundedness, citation, abstention 관련 품질 저하가 있으면 명시한다

---

## Documentation policy
다음 경우 문서를 함께 갱신한다.
- 실행 방법이 바뀐 경우 → `README.md`
- 설계 판단이 바뀐 경우 → `docs/`
- 실패 원인이나 한계를 발견한 경우 → 관련 docs 문서 또는 새 로그 문서

문서를 갱신하지 못했다면 왜 못했는지 적는다.

---

## Preferred style for changes
- 작은 PR/작은 diff 선호
- 함수 단위로 의도 명확하게 수정
- 매직 넘버/하드코딩 최소화
- 에러 메시지는 사용자가 다음 행동을 알 수 있게 작성
- 필요 이상으로 추상화하지 않음

---

## If blocked
막히면 멈춰서 추측으로 크게 바꾸지 말고 아래 중 하나를 한다.
- 실패 원인 가설 2~3개 제시
- 재현 명령과 에러를 정리
- 최소 수정안 제안
- 우회 가능한 fallback 경로 설명

---

## First-task priority
이 저장소에서 가장 먼저 해야 할 일은 새 기능 추가가 아니라 baseline 재현성 고정이다.

우선순위:
1. README 기준 end-to-end 재현
2. 스모크 검증 루프 고정
3. 그 다음 작은 개선

---

## Non-goals by default
명시적으로 요청되지 않았다면 아래는 기본 작업 범위가 아니다.
- UI 추가
- 웹 서비스화
- 대규모 아키텍처 재설계
- 외부 유료 API 의존성 추가
- 비공개 원본 RFP 데이터 복원 시도
