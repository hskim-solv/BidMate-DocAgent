# Reproducible Harness

이 harness는 기존 README 기본 흐름을 바꾸지 않고, smoke 실행에 필요한 입력 config, 로그, 예측, 평가 요약을 run 단위 디렉터리에 묶는다. 목적은 benchmark/ablation 확장 전에도 한 명령으로 재현 가능한 작은 실행 단위를 남기는 것이다.

## 실행

```bash
python3 scripts/run_harness.py --config harness/smoke.yaml
```

동일한 smoke harness는 Make target으로도 실행할 수 있다.

```bash
make harness-smoke
```

고정 run id를 사용하거나 기존 run을 덮어쓰려면 다음처럼 실행한다.

```bash
python3 scripts/run_harness.py \
  --config harness/smoke.yaml \
  --run_id issue25_smoke_test \
  --force
```

## Run ID와 artifact layout

`--run_id`를 생략하면 `<config_id>_YYYYMMDDTHHMMSSZ` 형식으로 생성한다. 기본 artifact root는 `artifacts/runs`이며, 전체 산출물은 `artifacts/runs/<run_id>/` 아래에 저장된다.

```text
artifacts/runs/<run_id>/
  run_manifest.json
  config_snapshot.json
  summary.json
  predictions.jsonl
  errors.jsonl
  index/index.json
  outputs/answer.json
  metrics/eval_summary.json
  logs/index.log
  logs/query.log
  logs/eval.log
```

`artifacts/runs/`는 Git 추적 대상이 아니다. 공개 synthetic smoke라도 raw prediction과 로그는 로컬 검증 산출물로 유지한다.

## 스키마

`run_manifest.json`은 다음 필드를 포함한다.

- `schema_version`: manifest schema version
- `run_id`: 실행 식별자
- `generated_at`: manifest 생성 시각
- `git_commit`, `git_dirty`: 실행 시점의 Git 상태
- `config_hash`: `config_snapshot.json`의 deterministic hash
- `config_snapshot_path`: 저장된 config snapshot 경로
- `artifacts`: 주요 산출물 경로
- `commands`: index/query/eval에 사용한 실제 command token
- `status`: `passed` 또는 `failed`
- `metrics`: `metrics/eval_summary.json`의 핵심 metric snapshot

`summary.json`은 다음 필드를 포함한다.

- `run_id`
- `status`
- `started_at`, `ended_at`
- `steps`: 각 단계 command, log path, return code, status
- `artifact_dir`
- `metrics_path`
- `errors_path`

`errors.jsonl`은 실패가 없어도 생성한다. 성공한 실행에서는 빈 파일이며, 실패한 실행에서는 실패 step, return code, log path, command를 JSONL로 기록한다.

## Smoke 범위

`harness/smoke.yaml`은 공개 synthetic RFP만 사용하고 hashing embedding으로 인덱스를 만든다. `harness/smoke_eval.yaml`은 작은 고정 case set만 포함한다.

- 단일 문서 보안 요구사항
- 기관 A/B AI 요구사항 비교

전체 품질 평가는 계속 `eval/run_eval.py --config eval/config.yaml`과 benchmark flow가 담당한다.

## Real-data profile

사설 RFP 데이터로 같은 manifest layout을 만들고 싶을 때는 `harness/real.example.yaml`을 `harness/real.local.yaml`로 복사하고 `eval.config` 경로를 자신의 `eval/real_config.local.yaml`로 맞춘 뒤 다음을 실행한다.

```bash
make harness-real
```

`harness/*.local.yaml`과 `eval/*.local.yaml`은 모두 `.gitignore`로 처리된다 (ADR 0005 commit boundary). real-data 산출물도 `artifacts/runs/`에 떨어지므로 자동으로 commit 대상에서 빠진다.

## Ablation matrix

`run_harness.py --matrix <yaml>`은 base config + cell override를 deep-merge해서 여러 cell을 직렬로 실행하고, 결과를 한 디렉터리에 묶는다.

```bash
make harness-ablation
# 또는 다른 matrix 파일로
make harness-ablation MATRIX=harness/my_ablation.yaml
```

생성물 layout:

```text
artifacts/matrices/<matrix_id>/
  matrix_summary.json        # 집계 manifest
  compare.md                 # compare.base가 설정된 경우만
  errors.jsonl
  cells/
    <cell_name>/
      cell_config.yaml       # 해당 cell의 merged config
      run_manifest.json
      config_snapshot.json
      summary.json
      predictions.jsonl
      metrics/eval_summary.json
      logs/{index,query,eval}.log
      outputs/answer.json
      index/
```

`harness/ablation.example.yaml`이 minimal 템플릿이다. 핵심 규칙:

- `base.{dataset,index,query,eval}`만 deep-merge 대상. 그 외 키(`id`, `description`, `artifact_root`, `matrix`, `compare`, `base`)는 override 금지 — `ValueError` raise.
- **ADR 0001 enforcement**: matrix 로드 시 `naive_baseline` 이름 cell이 없거나 `query.pipeline ≠ naive_baseline`이면 `SystemExit("ADR 0001 ...")`로 차단된다. naive baseline은 모든 matrix에 항상 존재해야 한다.
- `on_cell_failure: continue`(기본) — 실패 cell은 `errors.jsonl`에 기록하고 다음 cell로. `abort`는 첫 실패에서 종료.
- 매트릭스 exit code: 모든 cell pass 0, 하나라도 실패 2. (single-run과 동일 규약)
- `compare.base: <cell_name>` 설정 시 해당 cell을 베이스로 다른 cell들의 metric delta가 `compare.md`로 렌더링된다.

`matrix_summary.json` 주요 필드:

- `schema_version`, `matrix_id`, `matrix_config_hash`, `generated_at`, `started_at`, `git_commit`, `git_dirty`
- `matrix_config_path`, `matrix_dir`, `on_cell_failure`
- `cells[]`: 각 cell의 `{name, run_id, status, config_hash, run_manifest_path, metrics_snapshot, failure}`
- `compare`: `{base_cell, compare_md_path}` 또는 `null`
- `status`, `cells_passed`, `cells_failed`

## 두 run 비교 (compare 모드)

임의의 두 run을 markdown delta로 비교할 수 있다.

```bash
make harness-compare \
  RUN_A=artifacts/runs/public_synthetic_smoke_20260511T120000Z \
  RUN_B=artifacts/runs/public_synthetic_smoke_20260511T140000Z

# 또는 eval_summary.json 직접 지정
python3 scripts/run_harness.py --compare \
  --run-a reports/eval_summary.json \
  --run-b reports/eval_summary.head.json \
  --out compare.md
```

Metric 목록·formatting은 [`scripts/_eval_delta.py`](../scripts/_eval_delta.py)가 단일 source-of-truth이며, PR eval comment(`scripts/compare_eval.py`)와 matrix `compare.md`가 같은 정의를 공유한다.
