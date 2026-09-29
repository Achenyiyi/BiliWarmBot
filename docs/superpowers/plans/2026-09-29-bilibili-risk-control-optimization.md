# Bilibili Risk Control Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing per-cycle and per-video processing quotas while routing every Bilibili request through a persistent, rate-aware guard that stops safely on risk control and resumes after cooldown.

**Architecture:** Register a guarded `curl_cffi` client through bilibili-api-python's supported client registration API. The client applies one global request gate, classifies HTTP/API failures, persists cooldown state, and raises typed exceptions. The bot propagates risk-control exceptions to abort only the current cycle, while retryable and non-retryable comment errors are handled separately.

**Tech Stack:** Python 3.12, asyncio, bilibili-api-python 17.4.2, curl_cffi, SQLite/JSON state, pytest.

**Spec:** User request to optimize the current branch without reducing data-processing quantities.

## Global Constraints

- Preserve `SEARCH_CONFIG["max_videos_per_scan"]` and `COMMENT_CONFIG["max_replies_per_video"]` values.
- Do not add proxy rotation, fingerprint spoofing, CAPTCHA bypass, or multi-account evasion.
- HTTP 412 must stop the current cycle and persist a cooldown across restarts.
- Side-effecting comment sends must not be blindly retried.
- All Bilibili request paths must share the same guard.

---

### Task 1: Guard state and guarded bilibili client

**Files:**
- Create: `utils/bilibili_guard.py`
- Create: `tests/test_bilibili_guard.py`
- Modify: `config/settings.py` to define guard-state path and policy values

**Interfaces:**
- `BilibiliRiskError`, `BilibiliCooldownError`, `BilibiliNonRetryableError`
- `BilibiliRequestGuard.before_request(method, url)`
- `BilibiliRequestGuard.after_response(method, url, status_code)`
- `install_bilibili_guard()`

- [ ] Write tests for persistent cooldown, 412 classification, and safe response logging.
- [ ] Implement atomic JSON state writes and an asyncio lock.
- [ ] Implement a guarded `CurlCFFIClient` subclass registered via `bilibili_api.register_client`.
- [ ] Run guard unit tests.

### Task 2: Propagate risk-control and classify comment errors

**Files:**
- Modify: `modules/comment_interaction.py`
- Modify: `core/warm_bot.py`
- Modify: `utils/retry_handler.py`
- Create: `tests/test_error_policy.py`

**Interfaces:**
- Risk errors must propagate out of search, comment reads, and sends.
- 12045/12002/12022/12061 become non-retryable typed errors.

- [ ] Add typed exception handling before broad exception handlers.
- [ ] Stop swallowing 412 in keyword, scene, random search, comment read, and send paths.
- [ ] Ensure send failures caused by non-retryable API codes do not enter `comment_retries`.
- [ ] Exclude risk and non-retryable errors from generic retry logic.
- [ ] Run focused tests.

### Task 3: Cycle-level safe abort and observability

**Files:**
- Modify: `core/warm_bot.py`
- Modify: `config/bot_config.py`
- Modify: `README.md`
- Create: `tests/test_cycle_policy.py`

**Interfaces:**
- `run_cycle()` aborts the current cycle on `BilibiliRiskError` and records cooldown state.
- Existing processing quotas remain unchanged.

- [ ] Install the guard before any API call.
- [ ] Add cycle-level risk-control handling and concise logging.
- [ ] Keep search and reply quotas unchanged while configuring pacing separately.
- [ ] Document recovery and operator steps.
- [ ] Run the complete test suite, compileall, and lint checks.

### Task 4: Final verification

**Files:**
- No new source files.

- [ ] Verify branch and diff.
- [ ] Run unit tests and import/initialization checks without sending comments.
- [ ] Confirm no secrets or database files are staged.
