# Offline/Online Run Manifest

이 manifest는 ADR 0079의 v0-b milestone을 위한 실행 환경 provenance다. 목적은
offline과 online 평가(evaluation)를 같은 schema로 기록해, metric aggregate가
어떤 환경과 payload boundary에서 생성됐는지 review할 수 있게 하는 것이다.

이 문서는 성능(performance) 주장을 만들지 않는다. Private real-eval 원문,
질문, 답변, 근거(evidence), `doc_id`, `chunk_id`, filename, exact local path는
manifest에 쓰지 않는다.

## Command

```bash
python3 scripts/agent_loop.py eval-run-manifest \
  --mode offline \
  --payload-class none \
  --egress-mode none \
  --provider local \
  --model local-judge-v1 \
  --judge-backend local-llm
```

```bash
python3 scripts/agent_loop.py eval-run-manifest \
  --mode online \
  --payload-class private-raw \
  --egress-mode private-raw \
  --provider openai \
  --model gpt-example \
  --judge-backend external-judge
```

Default output:

```text
reports/agent_loop/offline_online_run_manifest.json
```

`eval/run_eval.py` also records the same `environment`, `model`, `payload`, and
`privacy` sections inside `run_manifest`. A config may provide an optional
top-level block:

```yaml
run_environment:
  mode: offline
  provider: local
  model: local-judge-v1
  judge_backend: local-llm
  hardware: local-gpu
  payload_class: none
  private_data_egress: none
```

The same values can be overridden for ad hoc runs with:

```text
BIDMATE_EVAL_ENVIRONMENT
BIDMATE_EVAL_PROVIDER
BIDMATE_EVAL_MODEL
BIDMATE_EVAL_JUDGE_BACKEND
BIDMATE_EVAL_HARDWARE
BIDMATE_EVAL_PAYLOAD_CLASS
BIDMATE_EVAL_PRIVATE_DATA_EGRESS
```

## Schema

Top-level fields:

| field | purpose |
|---|---|
| `schema_version` | Manifest schema version. Current value: `1`. |
| `generated_at` | UTC generation timestamp. |
| `git_head` | Current git commit. |
| `branch` | Current git branch. |
| `environment` | Offline/online execution mode and network assumptions. |
| `model` | Provider/model/judge backend provenance. |
| `payload` | Payload class and private-data egress mode. |
| `provenance` | Surface, case family, config digest, and sanitized source command. |
| `cost_latency` | Optional online cost/latency scalars. |
| `privacy` | Commit-safety booleans. |

`environment` fields:

| field | offline | online |
|---|---|---|
| `mode` | `offline` | `online` |
| `network` | `closed` | `non-closed` |
| `external_api_allowed` | `false` | `true` |
| `external_api_used` | derived from provider | derived from provider |
| `hardware` | sanitized scalar | sanitized scalar |

`payload.private_data_egress` values:

| value | meaning |
|---|---|
| `none` | No private data leaves the execution environment. Required for offline. |
| `metadata-only` | Only coarse metadata/provenance leaves the environment. |
| `public-only` | Only public fixture or synthetic public payload leaves the environment. |
| `private-raw` | Private raw payload egress is intentionally allowed and recorded. |

## Privacy Contract

- Offline manifests must set `private_data_egress` to `none`.
- Online manifests must record provider and model.
- Config paths are not serialized. Only `config_sha256` is recorded.
- Source commands are sanitized before serialization.
- Manifest generation fails if exact local paths or raw private fields are present.

## Claim Boundary

This manifest is provenance evidence only. It supports later v0-c report review,
but it is not a private real-eval result, benchmark lift, regression fix, or RFP
quality claim.
