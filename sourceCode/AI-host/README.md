# AI & Server layer (Phase 1 P1-7, Phase 2 P2-1/2/3/6/10/11/12/13)

Code lives in `sourceCode/BE` (it runs inside the FastAPI backend and talks to vLLM on the host).

| Duty | Module | What it does |
|---|---|---|
| P1-2 | `services/privacy.py` | prompt sanitizing (PII redaction), private-endpoint allowlist for LLM calls, Fernet encryption |
| P1-7 / P2-1 | `services/nlu.py` | few-shot prompt, strict JSON + pydantic validation, 1 retry, literal-text guards, rule-based fallback |
| P2-2 | `services/rag.py`, `POST /api/v1/assistant/index-file` | pdf/image text -> chunks -> offline hashed embeddings -> per-user encrypted index; retrieved rows feed the prompt |
| P2-3 | `services/temporal.py` | relative dates -> date windows from `reference_now` only; vague input -> clarifying question + 7-day default |
| P2-6 | `services/normalizer.py` | non-diacritic restore, teencode, profanity removal, emoji/special-char stripping |
| P2-10 | `services/inference_queue.py` | FIFO broker, 1 inference at a time, 1 s max queue wait + 3 s LLM timeout = 4 s worst case |
| P2-11 | `services/telemetry.py` | queue depth, RAM, VRAM (nvidia-smi), NLU p50/p95 latency -> `telemetry_metric_logs` |
| P2-12 | `services/ai_logging.py` | `logs/ai_errors.jsonl`: category, exact prompt, retrieved context, raw output, reason |
| P2-13 | `routers/reminders.py` | device reports scheduled/delivered; DB columns + `logs/reminder_audit.jsonl` |

Env switches: `VLLM_ENDPOINT`, `LLM_TIMEOUT_SECONDS`, `DATA_ENCRYPTION_KEY`, `INFERENCE_QUEUE_LOGGING=1`,
`TELEMETRY_INTERVAL_SECONDS` (0 = off), `AI_ERROR_LOG_PATH`, `RAG_DATA_DIR`.

Measure P2-1 against the live model: `python tools/eval_nlu.py` (target: schema adherence >= 98 %, `bad_dates` = 0).
`python tools/eval_nlu.py --rules` scores the deterministic fallback alone.

When the AI fails, the API answer carries `nlu.fallback_mode = true` and `nlu.fallback_reason` (`CATEGORY: reason`, for example
`TIMEOUT: ReadTimeout`), so the cause can be read without opening the log file (the log is written on the machine that runs the backend).

Related AI work outside `BE/services`:
- `sourceCode/Database/knowledgebase/` and `database/UniInfo/`: the university knowledge base (collector, extractor, loader, `kb_*` schema);
- `routers/search.py` `POST /search/academic/ask`: question answering over indexed documents (6-step RAG, fallback to excerpts when the model is down);
- `services/proposals.py`: turns an NLU result into a proposal (free gaps from the deterministic engine, never from the model).
