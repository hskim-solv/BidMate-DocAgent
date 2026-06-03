# 실험 결과 HTML 자동 생성

실험 산출물(`reports/**/*.aggregate.json`, `reports/**/eval_summary.json`,
`reports/retrieval/**/REPORT.md`) 옆에 사람이 브라우저로 훑을 수 있는 짝
`.html` 을 자동 생성한다. CLAUDE.md L51 "AI 가 이어받을 문서는 Markdown,
사람이 검토할 문서는 HTML" 원칙의 실험 표면 구현.

진입점은 `scripts/render_experiment_report_html.py` (issue #1661). 의존성 0
— `scripts/html_report.py` 의 4유틸만 재사용한다. ADR 0005 boundary 는
`scripts/_governance.py` 의 기존 함수/상수를 그대로 재사용해서 pre-commit
스캐너와 동일하게 강제된다.

## 트리거 경로 (이중화)

| 경로 | 어디서 | 언제 | 비고 |
|---|---|---|---|
| **정상** Makefile inline | `eval` / `smoke` / `real-eval-v2-check` / `real-eval-baseline-update` / `real-eval-history-render` 마지막 step | target 실행 직후 | `@$(MAKE) -s experiment-report-html` |
| **안전망** Stop hook | `scripts/claude-hooks/stop-experiment-report.sh` | 매 Claude Code Stop 이벤트 | ad-hoc `python3 eval/run_eval.py …` 같은 우회 경로 커버 |

두 경로 모두 동일 스크립트를 호출하고 stale/missing 짝만 렌더해서 멱등이다.

## 입력 allowlist

- `reports/**/*.aggregate.json` — 모든 aggregate 표면 (real100, real100_v2,
  retrieval, rag_pipeline 등)
- `reports/**/eval_summary.json` — smoke / eval 산출물
- `reports/retrieval/**/REPORT.md` — retrieval-eval skill phase 보고서

## 입력 denylist (ADR 0005 boundary)

다음은 자동으로 거부된다 (exit 2 `denied`, stderr 에 사유):

- 파일명: `raw_results.json`, `data_list*.csv`
- 경로 부분: `data/private/`, `outputs/`
- top-level 키: `chunk_text`, `raw_text`, `answer_text`
- `reports/retrieval/phase4*` 아래: `_governance.PHASE4_PRIVATE_KEYS`
  (`query`, `sample_queries`, `gold_agency`, `gold_project`,
  `extracted_agency`, `extracted_project`)
- `EVAL_PRIVACY_ARTIFACT_GLOBS` (`reports/retrieval`, `reports/real100`,
  `reports/real100_v2`) 아래: `_governance.find_eval_private_text`
  (한글 문자 + 콜론 포함 dict key)

2026-05-21 #1144 (realistic-metadata `raw_results.json` 의 `gold_agency`
실값 committed 노출 → history-rewrite) 재발 방지가 명시 동기.

## 수동 호출

```bash
# 단일 파일
python3 scripts/render_experiment_report_html.py \
  --input reports/real100_v2/baseline.aggregate.json

# 전체 reports/ 스캔, stale 만 렌더
python3 scripts/render_experiment_report_html.py --auto-scan

# stale 가 있는지만 확인 (exit 1 if stale, 0 otherwise)
python3 scripts/render_experiment_report_html.py --check --auto-scan

# Makefile target (auto-scan + quiet 의 thin wrapper)
make experiment-report-html
```

## Stop hook escape hatch

```bash
# 비활성화 (해당 shell session 한정)
BIDMATE_EXPERIMENT_REPORT_STOP_HOOK=0

# 강제 발화 테스트
BIDMATE_EXPERIMENT_REPORT_FORCE=1 \
  bash scripts/claude-hooks/stop-experiment-report.sh
```

## 큰 파일 가드

5 MB 초과 입력은 자동 skip + stderr 경고. 현재 모든 aggregate 표면이
200 KB 미만이라 실질적으로 도달하지 않는 보호선.

## Multi-worktree 주의

각 워크트리는 자체 `reports/` 디렉터리를 갖는 게 기본이다. 동일 reports/
디렉터리를 공유하는 경우 HTML write 가 race 할 수 있어서 atomic write
(`tempfile.NamedTemporaryFile` + `os.replace`) 로 완화하지만, 동시 실행은
권장하지 않는다.
병행 Codex/Claude 세션에서 report HTML을 PR evidence로 붙이려면 먼저
[`overlap-preflight`](./ai-codex-workflow.md#overlap-preflight)를 실행해
공유 reports/ 경로 또는 변경 파일 충돌이 없다는 근거를 남긴다.

## Non-goals

- Markdown → 풍부한 HTML 변환 (헤더/링크/볼드 등). 현재는
  `<pre class="markdown">` plaintext escape + 첫 `# ` 라인 → title 정도의
  최소 변환. mistune/markdown 라이브러리 도입은 별 PR.
- HTML 을 `docs/leaderboard/` 같은 공개 surface 로 배포. 현 PR 은
  `reports/**/*.html` 로컬/private 용도만.
- aggregate 산출물 자체의 키 스키마 변경 (view 레이어 only).
