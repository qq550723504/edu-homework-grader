# AI 出题多样性与跨批去重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同一课程目标的连续 AI 出题主动避开近期候选，并将跨批待审核近似题在验证阶段阻断。

**Architecture:** 保持唯一活跃的 `generator-v1`，通过 `GenerationRequest.avoid_prompts` 向模型传递有限且去标识化的近期题干，要求改变场景、条件与考查动作。服务端继续是最终裁判：重复检测扩展为同租户、同课程目标的跨批 `pending_review` 当前修订比较，既有已发布题和批内比较保持不变。

**Tech Stack:** Python 3、Pydantic v2、SQLAlchemy 2、FastAPI 服务层、现有 Grader 语义相似度契约、pytest。

## Global Constraints

- 保持唯一活跃运行时版本 `generator-v1`；不得新增提示词版本或教师端版本选择。
- 不改变题型、难度、课程目标、内容安全、答案正确性、审核、发布或重试状态机。
- 避重参考只能来自去标识化的候选题干；不得包含教师补充要求、用户身份信息或原始模型提示。
- 每次模型请求最多 8 条避重题干，每条最多 1,200 字符；公开 API payload 与尝试摘要不得包含题干原文。
- 跨批比较仅包含同一租户、同一 `curriculum_objective_revision_id`、不同任务、状态为 `pending_review` 的当前候选修订，最多 20 条最新记录。
- 语义服务不可用时保持现有 fail-closed 行为 `duplicate_semantic_check_unavailable`。

---

## File Structure

- Modify: `services/generator/src/edu_generator/contracts.py` — 为模型输入增加严格、去标识化的 `avoid_prompts`。
- Modify: `services/generator/src/edu_generator/prompt_templates.py` — 在现有 `generator-v1` 中声明不可仅替换人名/物品/数值的多样性规则。
- Modify: `services/generator/tests/test_contracts.py` — 约束、提示版本和 OpenAI 输入契约测试。
- Modify: `apps/api/src/edu_grader_api/services/generation.py` — 收集近期待审核题干、构造模型请求、记录仅含数量的尝试摘要。
- Modify: `apps/api/tests/test_generation_service.py` — 同租户/同目标过滤、截断、去重和隐私投影测试。
- Modify: `apps/api/src/edu_grader_api/services/question_verification.py` — 新增跨批待审核比较器与计数类别。
- Modify: `apps/api/tests/test_question_verification.py` — 跨批近似题阻断和排除范围测试。

### Task 1: 为 `generator-v1` 增加避重输入契约和多样性指令

**Files:**
- Modify: `services/generator/src/edu_generator/contracts.py`
- Modify: `services/generator/src/edu_generator/prompt_templates.py`
- Modify: `services/generator/tests/test_contracts.py`

**Interfaces:**
- Produces: `GenerationRequest.avoid_prompts: list[str]`，默认空列表，最多 8 项，每项长度 1 至 1,200。
- Produces: 仍名为 `generator-v1` 的模板，要求候选不能仅替换人名、物品或单个数值。
- Consumes: 现有 `GenerationRequest.model_post_init` 的去标识化检查和 OpenAI `request.model_dump(mode="json")` 输入。

- [ ] **Step 1: 写出契约与模板失败测试**

```python
def test_generation_request_rejects_more_than_eight_or_overlong_avoid_prompts() -> None:
    base = generation_request_payload()
    with pytest.raises(ValidationError):
        GenerationRequest(**base, avoid_prompts=["x"] * 9)
    with pytest.raises(ValidationError):
        GenerationRequest(**base, avoid_prompts=["x" * 1201])


def test_active_generator_requires_materially_different_context_and_reasoning() -> None:
    template = resolve_prompt_template("generator-v1", ["M1"])
    assert template.version == "generator-v1"
    assert "avoid_prompts" in template.system_instructions
    assert "not merely replace names, objects, or one number" in template.system_instructions
```

- [ ] **Step 2: 运行测试，确认测试因缺少字段和指令而失败**

Run: `python -m pytest services/generator/tests/test_contracts.py -q`

Expected: FAIL，`GenerationRequest` 不接受 `avoid_prompts`，或模板文字断言失败。

- [ ] **Step 3: 实现输入字段的边界约束**

```python
from typing import Annotated, Literal

AvoidPrompt = Annotated[str, Field(min_length=1, max_length=1_200)]


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_revision_id: UUID
    objective_text: str = Field(min_length=1, max_length=2_000)
    knowledge_point: str | None = Field(default=None, max_length=200)
    difficulty_min: float = Field(ge=0, le=1)
    difficulty_max: float = Field(ge=0, le=1)
    grade: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=100)
    items: list[GenerationPlanItem] = Field(min_length=1, max_length=20)
    requested_count: int = Field(ge=1, le=20)
    policy_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    teacher_constraint: str | None = Field(default=None, max_length=1_000)
    avoid_prompts: list[AvoidPrompt] = Field(default_factory=list, max_length=8)
```

Keep the existing item-count validator and `assert_deidentified_payload(self.model_dump(mode="json"))` unchanged so every supplied reference receives the same PII guard as all other model-bound fields.

- [ ] **Step 4: Extend only the existing `generator-v1` instructions**

```python
"The request may include avoid_prompts containing recent de-identified questions. "
"Use them only as diversity boundaries and never copy or paraphrase them. "
"Each candidate must differ materially from every avoid_prompts item in at least two of: "
"context or objects, key values or conditions, and the cognitive action or solution structure. "
"Do not merely replace names, objects, or one number. "
"Candidates in the same response must follow the same diversity rule. "
```

Append this text to `_GENERATOR_V1.system_instructions`; retain its `version="generator-v1"`, schema version and all existing question-type requirements.

- [ ] **Step 5: Run the generator contract tests**

Run: `python -m pytest services/generator/tests/test_contracts.py -q`

Expected: PASS。

- [ ] **Step 6: Commit the generator-boundary change**

```bash
git add services/generator/src/edu_generator/contracts.py services/generator/src/edu_generator/prompt_templates.py services/generator/tests/test_contracts.py
git commit -m "feat: add diversity boundaries to active generator"
```

### Task 2: 从近期同目标待审核候选构造私有避重参考

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/generation.py`
- Modify: `apps/api/tests/test_generation_service.py`

**Interfaces:**
- Consumes: `GenerationJob.tenant_id`、`GenerationJob.curriculum_objective_revision_id`、`GeneratedQuestionDraft.current_revision_id`、`GeneratedQuestionDraft.teacher_state`。
- Produces: `_recent_pending_avoid_prompts(session, job=job) -> list[str]`，最多 8 个规范化去重后的 1,200 字符题干。
- Produces: `_provider_request(session, job, teacher_constraint=teacher_constraint).avoid_prompts`；`_request_summary` 仅含 `avoid_prompt_count` 和 `avoid_prompt_max_length`。

- [ ] **Step 1: 写出服务层失败测试**

```python
def test_provider_request_uses_only_recent_same_objective_pending_prompts(session: Session) -> None:
    job = make_generation_job(session, objective_revision=revision, tenant=tenant)
    add_current_draft(session, tenant=tenant, objective_revision=revision, prompt="Keep this nearby.", teacher_state="pending_review", created_at=utc_now())
    add_current_draft(session, tenant=tenant, objective_revision=other_revision, prompt="Other objective.", teacher_state="pending_review", created_at=utc_now())
    add_current_draft(session, tenant=other_tenant, objective_revision=revision, prompt="Other tenant.", teacher_state="pending_review", created_at=utc_now())
    add_current_draft(session, tenant=tenant, objective_revision=revision, prompt="Rejected candidate.", teacher_state="rejected", created_at=utc_now())

    request = _provider_request(session, job, teacher_constraint=None)

    assert request.avoid_prompts == ["Keep this nearby."]


def test_request_summary_does_not_contain_avoid_prompt_text(session: Session) -> None:
    request = request_with_avoid_prompts(["Do not persist this prompt."])
    summary = _request_summary(request, requested_count=1, template=resolve_prompt_template("generator-v1", ["M1"]))
    assert summary["avoid_prompt_count"] == 1
    assert summary["avoid_prompt_max_length"] == 1200
    assert "Do not persist this prompt." not in str(summary)
```

- [ ] **Step 2: 运行测试，确认缺少收集器和摘要字段**

Run: `$env:PYTHONPATH = 'apps/api/src;services/generator/src;services/grader/src;packages/processor-policy/src'; python -m pytest apps/api/tests/test_generation_service.py -q`

Expected: FAIL，`avoid_prompts` 为空或摘要没有计数。

- [ ] **Step 3: 实现有界的近期待审核题干查询**

```python
_AVOID_PROMPT_LIMIT = 8
_AVOID_PROMPT_MAX_LENGTH = 1_200
_AVOID_PROMPT_SCAN_LIMIT = 20


def _recent_pending_avoid_prompts(session: Session, *, job: GenerationJob) -> list[str]:
    rows = session.scalars(
        select(GeneratedQuestionDraftRevision.candidate_json)
        .join(GeneratedQuestionDraft, GeneratedQuestionDraft.current_revision_id == GeneratedQuestionDraftRevision.id)
        .join(GenerationJob, GeneratedQuestionDraft.job_id == GenerationJob.id)
        .where(
            GenerationJob.tenant_id == job.tenant_id,
            GenerationJob.curriculum_objective_revision_id == job.curriculum_objective_revision_id,
            GeneratedQuestionDraft.job_id != job.id,
            GeneratedQuestionDraft.teacher_state == "pending_review",
        )
        .order_by(GeneratedQuestionDraft.created_at.desc(), GeneratedQuestionDraft.id.desc())
        .limit(_AVOID_PROMPT_SCAN_LIMIT)
    )
    prompts: list[str] = []
    seen: set[str] = set()
    for candidate in rows:
        prompt = candidate.get("prompt") if isinstance(candidate, dict) else None
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        trimmed = prompt.strip()[:_AVOID_PROMPT_MAX_LENGTH]
        key = fingerprint_prompt(trimmed).normalized_hash
        if key in seen:
            continue
        seen.add(key)
        prompts.append(trimmed)
        if len(prompts) == _AVOID_PROMPT_LIMIT:
            break
    return prompts
```

Import `fingerprint_prompt` from the existing question-fingerprint service. In `_provider_request`, pass `avoid_prompts=_recent_pending_avoid_prompts(session, job=job)`. Do not add this field to `GenerationJob`, request digests, route input models or public job/draft payloads.

- [ ] **Step 4: Record only privacy-safe request summary metadata**

```python
"avoid_prompt_count": len(request.avoid_prompts),
"avoid_prompt_max_length": _AVOID_PROMPT_MAX_LENGTH,
```

Add the two keys to `_request_summary`; do not serialize `request.avoid_prompts` or any prompt hash there.

- [ ] **Step 5: Run service tests**

Run: `$env:PYTHONPATH = 'apps/api/src;services/generator/src;services/grader/src;packages/processor-policy/src'; python -m pytest apps/api/tests/test_generation_service.py -q`

Expected: PASS。

- [ ] **Step 6: Commit the private-reference construction**

```bash
git add apps/api/src/edu_grader_api/services/generation.py apps/api/tests/test_generation_service.py
git commit -m "feat: provide pending prompts as diversity boundaries"
```

### Task 3: 将跨批待审核候选纳入精确和语义去重

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**
- Consumes: `_pending_current_revision_candidates(session, draft=draft, tenant_id=tenant_id)`。
- Produces: `_semantic_comparators` 类别 `pending_candidate`；`comparison_counts` 固定包含 `published_question`、`batch_candidate` 和 `pending_candidate`。
- Produces: 跨批近似候选的现有阻断 finding `duplicate_semantic_near_match`，其安全证据 `comparison` 等于 `pending_candidate`。

- [ ] **Step 1: 写出跨批阻断与排除范围的失败测试**

```python
def test_semantic_duplicate_blocks_same_objective_pending_candidate_from_another_job(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("How many apples are there?"))
    add_pending_draft_for_objective(session, tenant_id=draft.job.tenant_id, objective_revision_id=draft.job.curriculum_objective_revision_id, prompt="Count the apples in the basket.")
    grader = SemanticGrader([semantic_result([0.98])])

    run = run_candidate_verification(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.BLOCKED
    assert run.findings[0].code == "duplicate_semantic_near_match"
    assert run.findings[0].evidence_json["comparison"] == "pending_candidate"
    assert run.feature_summary_json["comparison_counts"]["pending_candidate"] == 1


def test_pending_comparator_excludes_other_tenants_objectives_and_rejected_drafts(session: Session) -> None:
    draft = generation_draft(session)
    add_pending_draft_for_objective(session, tenant_id=other_tenant.id, objective_revision_id=draft.job.curriculum_objective_revision_id, prompt="Other tenant.")
    add_pending_draft_for_objective(session, tenant_id=draft.job.tenant_id, objective_revision_id=other_revision.id, prompt="Other objective.")
    add_pending_draft_for_objective(session, tenant_id=draft.job.tenant_id, objective_revision_id=draft.job.curriculum_objective_revision_id, prompt="Rejected.", teacher_state="rejected")

    comparators = _semantic_comparators(session, draft=draft, tenant_id=draft.job.tenant_id)

    assert all(item.category != "pending_candidate" for item in comparators)
```

- [ ] **Step 2: 运行测试，确认当前比较器只返回已发布和批内候选**

Run: `$env:PYTHONPATH = 'apps/api/src;services/generator/src;services/grader/src;packages/processor-policy/src'; python -m pytest apps/api/tests/test_question_verification.py -q`

Expected: FAIL，语义请求没有跨批候选，或 `comparison_counts` 不含 `pending_candidate`。

- [ ] **Step 3: 实现跨批当前修订查询和类别计数**

```python
def _pending_current_revision_candidates(session: Session, *, draft: GeneratedQuestionDraft, tenant_id: object) -> list[dict[str, object]]:
    return list(session.scalars(
        select(GeneratedQuestionDraftRevision.candidate_json)
        .join(GeneratedQuestionDraft, GeneratedQuestionDraft.current_revision_id == GeneratedQuestionDraftRevision.id)
        .join(GenerationJob, GeneratedQuestionDraft.job_id == GenerationJob.id)
        .where(
            GenerationJob.tenant_id == tenant_id,
            GenerationJob.curriculum_objective_revision_id == draft.job.curriculum_objective_revision_id,
            GeneratedQuestionDraft.job_id != draft.job_id,
            GeneratedQuestionDraft.teacher_state == "pending_review",
        )
        .order_by(GeneratedQuestionDraft.created_at.desc(), GeneratedQuestionDraft.id.desc())
        .limit(20)
    ))
```

Build `pending_rows = [(candidate, None, None) for candidate in _pending_current_revision_candidates(session, draft=draft, tenant_id=tenant_id)]`, then enumerate categories in this exact order: `published_question`, `batch_candidate`, `pending_candidate`. Update `_empty_duplicate_feature_summary` and `_duplicate_feature_summary` to initialize/count all three categories. Keep the existing normalized-hash de-duplication so the same prompt is compared at most once even if it appears in multiple categories.

- [ ] **Step 4: Verify safe evidence and fail-closed behavior remain unchanged**

```python
assert run.findings[0].evidence_json == {
    "comparison": "pending_candidate",
    "method": "semantic",
    "threshold_band": "at_or_above",
}
assert "Count the apples in the basket." not in str(run.findings[0].evidence_json)
```

Keep `_duplicate_unavailable_finding()` unchanged; add an assertion that a failing semantic response still produces `duplicate_semantic_check_unavailable` when a pending comparator exists.

- [ ] **Step 5: Run verification tests**

Run: `$env:PYTHONPATH = 'apps/api/src;services/generator/src;services/grader/src;packages/processor-policy/src'; python -m pytest apps/api/tests/test_question_verification.py -q`

Expected: PASS。

- [ ] **Step 6: Commit the cross-batch verifier change**

```bash
git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
git commit -m "feat: block duplicate pending generation candidates"
```

### Task 4: 进行全链路回归和任务验收

**Files:**
- Modify: `apps/api/tests/test_generation_service.py`
- Modify: `apps/api/tests/test_question_verification.py`
- Modify: `services/generator/tests/test_contracts.py`

**Interfaces:**
- Consumes: Tasks 1–3 的模型输入、私有参考收集与验证类别。
- Produces: 可重复运行的回归证据；无需增加浏览器端接口或数据库迁移。

- [ ] **Step 1: 运行三项针对性回归**

Run: `$env:PYTHONPATH = 'apps/api/src;services/generator/src;services/grader/src;packages/processor-policy/src'; python -m pytest services/generator/tests/test_contracts.py apps/api/tests/test_generation_service.py apps/api/tests/test_question_verification.py -q`

Expected: PASS，包含新避重请求、跨批 pending 比较和原有 fail-closed 语义错误场景。

- [ ] **Step 2: 检查格式、静态检查和改动边界**

Run: `ruff format --check apps/api/src/edu_grader_api/services/generation.py apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_generation_service.py apps/api/tests/test_question_verification.py services/generator/src/edu_generator/contracts.py services/generator/src/edu_generator/prompt_templates.py services/generator/tests/test_contracts.py`

Expected: PASS。

Run: `ruff check apps/api/src/edu_grader_api/services/generation.py apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_generation_service.py apps/api/tests/test_question_verification.py services/generator/src/edu_generator/contracts.py services/generator/src/edu_generator/prompt_templates.py services/generator/tests/test_contracts.py`

Expected: PASS。

Run: `git diff --check && git status --short`

Expected: 无空白错误，且只包含本计划和设计允许的生成器、生成服务、验证服务及其测试文件。

- [ ] **Step 3: 提交最终回归调整（如测试任务中仍有未提交文件）**

```bash
git add services/generator/tests/test_contracts.py apps/api/tests/test_generation_service.py apps/api/tests/test_question_verification.py
git commit -m "test: cover generation diversity controls"
```

## Self-Review

- [x] 多样性主动约束、8 条/1,200 字符上限和 `generator-v1` 单版本要求由 Task 1、Task 2 覆盖。
- [x] 同租户/同课程目标/不同任务/待审核/20 条上限的跨批范围由 Task 2、Task 3 覆盖。
- [x] 公开 payload 与尝试摘要不泄漏历史题干由 Task 2 覆盖。
- [x] 已发布题、批内题、阈值阻断和 fail-closed 语义服务行为由 Task 3、Task 4 保留并回归验证。
- [x] 本计划没有教材、21cnjy、前端布局、重试状态机或提示词版本体系变更。
- [x] 已检查术语一致性：`avoid_prompts`、`pending_candidate`、`_recent_pending_avoid_prompts` 和 `_pending_current_revision_candidates` 的生产者/消费者一致。
