# AI 生成默认配置治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 以双人审批和运营评估证据受控晋级或回滚全局 AI 生成默认模型/Prompt，并让每个新 Job 固化当时配置。

**Architecture:** 三张表分别保存不可变配置、不可变变更请求和唯一当前默认指针。服务层独占状态机和证据校验；生成服务在创建 Job 时读取指针并快照配置；最小 Nuxt 管理页只调用管理员 API。

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy, Alembic, PostgreSQL/SQLite, Nuxt 3, Vue, Vitest, Playwright.

## Global Constraints

- 仅支持全局 provider + immutable model + prompt；不做租户默认、百分比路由或自动晋级。
- 现有 GenerationGovernanceEntry 仅保留 active/canary/paused/retired 准入，绝不加入默认字段。
- OpenAI 模型复用 validate_immutable_openai_model_id；Prompt 从目录解析并保存 fingerprint。
- 所有写操作写入 HMAC 审计链，且不包含题目正文、Prompt 正文、密钥、邮箱、OIDC subject。
- 提交人不能审批自己的请求；apply 时重验报告和全局控制状态。
- 无生效默认选择时生成失败关闭，返回 generation_default_not_configured；不得读取环境变量回退。
- 管理页单页、无草稿；普通管理员和教师无权读取。

## File Structure

- Create: apps/api/alembic/versions/0027_generation_default_governance.py
- Modify: apps/api/src/edu_grader_api/models.py
- Create: apps/api/src/edu_grader_api/services/generation_default_governance.py
- Modify: apps/api/src/edu_grader_api/services/generation.py
- Modify: apps/api/src/edu_grader_api/routers/ai_question_generation.py
- Modify: apps/api/src/edu_grader_api/routers/admin.py
- Modify: apps/api/src/edu_grader_api/main.py
- Create: apps/api/tests/test_generation_default_governance.py
- Create: apps/api/tests/test_generation_default_governance_api.py
- Create: apps/api/tests/test_generation_default_readiness.py
- Modify: apps/api/tests/test_generation_models.py, test_curriculum_models.py, test_generation_service.py, test_ai_question_generation_api.py
- Create: apps/web/app/lib/admin-generation-defaults.ts
- Modify: apps/web/app/pages/admin/index.vue
- Create: apps/web/tests/admin-generation-defaults.test.ts
- Create: apps/web/e2e/admin-generation-defaults.spec.ts
- Create: docs/operations/ai-generation-default-governance.md
- Modify: docs/README.md

### Task 1: 建立不可变数据边界

**Files:**
- Create: apps/api/alembic/versions/0027_generation_default_governance.py
- Modify: apps/api/src/edu_grader_api/models.py:157-163,665-710,738-794
- Test: apps/api/tests/test_generation_models.py and apps/api/tests/test_curriculum_models.py

**Interfaces:**
- Produces GenerationDefaultConfiguration, GenerationDefaultChangeRequest, GenerationDefaultSelection and GenerationDefaultChangeStatus.
- Produces nullable historical GenerationJob.provider_name, model_version, prompt_template_fingerprint; all new Jobs set every field.

- [ ] **Step 1: Write failing constraints and revision-head tests**

    def test_default_selection_is_global_singleton(session: Session) -> None:
        session.add_all([
            GenerationDefaultSelection(scope="global", configuration_id=uuid4(), applied_change_request_id=uuid4()),
            GenerationDefaultSelection(scope="global", configuration_id=uuid4(), applied_change_request_id=uuid4()),
        ])
        with pytest.raises(IntegrityError):
            session.commit()

    def test_latest_alembic_revision_is_the_head() -> None:
        assert _head_revision() == "0027_generation_default_governance"

- [ ] **Step 2: Run the tests to verify failure**

Run: python -m pytest apps/api/tests/test_generation_models.py apps/api/tests/test_curriculum_models.py -q
Expected: FAIL because models and revision are absent.

- [ ] **Step 3: Implement models and migration**

    class GenerationDefaultChangeStatus(StrEnum):
        PENDING_APPROVAL = "pending_approval"
        APPROVED = "approved"
        REJECTED = "rejected"
        APPLIED = "applied"
        SUPERSEDED = "superseded"
        ROLLED_BACK = "rolled_back"

    class GenerationDefaultSelection(Base):
        __tablename__ = "generation_default_selections"
        scope: Mapped[str] = mapped_column(String(20), primary_key=True, default="global")
        configuration_id: Mapped[UUID] = mapped_column(ForeignKey("generation_default_configurations.id"), nullable=False)
        applied_change_request_id: Mapped[UUID] = mapped_column(ForeignKey("generation_default_change_requests.id"), nullable=False)
        __table_args__ = (CheckConstraint("scope = 'global'", name="ck_generation_default_scope_global"),)

Create configuration rows unique on provider/model/prompt/fingerprint. Create request rows with configuration, optional rollback source, submit/approve/apply identities and times, status, reason, idempotency key/digest, report SHA-256, record digest, run/spec IDs, watermark and redacted summary. Add unique submitted_by_user_id/idempotency_key. The migration adds nullable Job snapshot columns without backfilling.

- [ ] **Step 4: Verify and commit**

Run: python -m pytest apps/api/tests/test_generation_models.py apps/api/tests/test_curriculum_models.py -q
Expected: PASS.

    git add apps/api/alembic/versions/0027_generation_default_governance.py apps/api/src/edu_grader_api/models.py apps/api/tests/test_generation_models.py apps/api/tests/test_curriculum_models.py
    git commit -m "feat: persist generation default governance"

### Task 2: 实现报告校验和变更状态机

**Files:**
- Create: apps/api/src/edu_grader_api/services/generation_default_governance.py
- Create: apps/api/tests/test_generation_default_governance.py
- Modify: apps/api/src/edu_grader_api/services/generation_governance.py:49-141

**Interfaces:**
- Consumes Task 1 models, OperationalEvaluationReport, resolve_prompt_template, validate_immutable_openai_model_id and append_audit_event.
- Produces ResolvedGenerationDefault, GenerationDefaultGovernanceError, submit_change_request, approve_change_request, reject_change_request, apply_change_request, submit_rollback_request and resolve_active_default.

- [ ] **Step 1: Write failing evidence and self-approval tests**

    def test_submit_requires_passing_report_for_exact_candidate(session: Session, platform_admin: User) -> None:
        with pytest.raises(GenerationDefaultGovernanceError, match="evaluation_candidate_mismatch"):
            submit_change_request(session, actor=platform_admin,
                input=_candidate(model_version="gpt-5-2026-01-01"),
                evaluation_report=_report(model_id="gpt-5-2025-08-07"),
                idempotency_key="promote-1")

    def test_submitter_cannot_approve_own_request(session: Session, platform_admin: User) -> None:
        request = _submitted_request(session, platform_admin)
        with pytest.raises(GenerationDefaultGovernanceError, match="default_change_self_approval_forbidden"):
            approve_change_request(session, request_id=request.id, actor=platform_admin, reason="approved")

- [ ] **Step 2: Run to verify failure**

Run: python -m pytest apps/api/tests/test_generation_default_governance.py -q
Expected: FAIL because the service is absent.

- [ ] **Step 3: Implement only the service as lifecycle writer**

    @dataclass(frozen=True)
    class ResolvedGenerationDefault:
        provider_name: str
        model_version: str
        prompt_version: str
        prompt_template_fingerprint: str

    class GenerationDefaultGovernanceError(ValueError):
        def __init__(self, code: str) -> None:
            super().__init__(code)
            self.code = code

    def resolve_active_default(session: Session) -> ResolvedGenerationDefault:
        selection = session.get(GenerationDefaultSelection, "global")
        if selection is None:
            raise GenerationDefaultGovernanceError("generation_default_not_configured")
        return _resolved_from_configuration(selection.configuration)

Validate OperationalEvaluationReport.model_validate(report); require promotion_eligible and exact candidate provider/model/prompt. Persist a canonical JSON SHA-256 and safe report summary only. Resolve the Prompt against all supported question types and save fingerprint. Reject global paused, retired and canary components. Apply locks the selection/request with with_for_update(), revalidates every prerequisite, switches pointer and statuses in one transaction, then appends audit. Replays require identical request digest; otherwise return default_change_idempotency_conflict.

- [ ] **Step 4: Add rollback/privacy/concurrency cases and verify**

    def test_rollback_is_a_new_independently_approved_request(session: Session, admins: tuple[User, User]) -> None:
        submitter, approver = admins
        original = _applied_request(session, submitter, approver, model="gpt-5-2025-08-07")
        newer = _applied_request(session, submitter, approver, model="gpt-5-2026-01-01")
        rollback = submit_rollback_request(session, actor=submitter, target_request_id=original.id, reason="regression")
        approve_change_request(session, request_id=rollback.id, actor=approver, reason="verified")
        apply_change_request(session, request_id=rollback.id, actor=submitter)
        assert resolve_active_default(session).model_version == "gpt-5-2025-08-07"
        assert newer.status is GenerationDefaultChangeStatus.SUPERSEDED

Run: python -m pytest apps/api/tests/test_generation_default_governance.py apps/api/tests/test_generation_governance_controls.py -q
Expected: PASS.

    git add apps/api/src/edu_grader_api/services/generation_default_governance.py apps/api/src/edu_grader_api/services/generation_governance.py apps/api/tests/test_generation_default_governance.py
    git commit -m "feat: govern generation default changes"

### Task 3: 提供平台治理 API

**Files:**
- Modify: apps/api/src/edu_grader_api/routers/admin.py:1-322
- Create: apps/api/tests/test_generation_default_governance_api.py

**Interfaces:**
- Consumes Task 2 service and generation_governance_admin_subject_set.
- Produces GET /v1/admin/ai-generation-defaults; submit, approve/reject, apply and rollback endpoints.

- [ ] **Step 1: Write failing authorization and application tests**

    def test_only_platform_governance_admin_can_read_defaults(client: TestClient, tenant_admin: User) -> None:
        response = client.get("/v1/admin/ai-generation-defaults", headers=authorize(client, tenant_admin))
        assert response.status_code == 404

    def test_approved_request_applies_once_and_audits(client: TestClient, admins: tuple[User, User]) -> None:
        submitted = _submit(client, admins[0])
        assert _approve(client, submitted["id"], admins[1]).status_code == 200
        assert _apply(client, submitted["id"], admins[0]).status_code == 200
        assert _apply(client, submitted["id"], admins[0]).status_code == 409

- [ ] **Step 2: Run to verify failure**

Run: python -m pytest apps/api/tests/test_generation_default_governance_api.py -q
Expected: FAIL because endpoints are absent.

- [ ] **Step 3: Implement protected redacted endpoints**

    @router.get("/ai-generation-defaults")
    def get_ai_generation_defaults(
        principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        _require_global_governance_admin(principal)
        return generation_default_summary(session)

    @router.post("/ai-generation-default-change-requests", status_code=status.HTTP_201_CREATED)
    def submit_ai_generation_default_change(
        body: SubmitGenerationDefaultChangeRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        _require_global_governance_admin(principal)
        return _default_change_request_payload(
            submit_change_request(
                session, actor=_current_user(session, principal),
                input=body.to_service_input(), evaluation_report=body.evaluation_report,
                idempotency_key=idempotency_key,
            )
        )

Call _require_global_governance_admin before every route. Submit requires the idempotency header. Responses only expose IDs, version labels, status, reason, timestamps and safe evidence digests. Map lifecycle errors to 404 for hidden authorization, 409 for conflicts and 422 for bad evidence. Never serialize report JSON, Prompt content, audit hashes, OIDC subjects or emails.

- [ ] **Step 4: Verify and commit**

Run: python -m pytest apps/api/tests/test_generation_default_governance_api.py apps/api/tests/test_generation_governance_controls.py apps/api/tests/test_audit.py -q
Expected: PASS, including ai_generation_default.* events.

    git add apps/api/src/edu_grader_api/routers/admin.py apps/api/tests/test_generation_default_governance_api.py
    git commit -m "feat: expose generation default governance API"

### Task 4: 在 Job 创建时快照并强化 readiness

**Files:**
- Modify: apps/api/src/edu_grader_api/services/generation.py:53-365
- Modify: apps/api/src/edu_grader_api/routers/ai_question_generation.py:131-180,582-600
- Modify: apps/api/src/edu_grader_api/main.py:61-76
- Modify: apps/api/tests/test_generation_service.py and apps/api/tests/test_ai_question_generation_api.py
- Create: apps/api/tests/test_generation_default_readiness.py

**Interfaces:**
- Consumes Task 2 resolve_active_default.
- Produces Job snapshots and _generation_provider(provider_name, model_version).

- [ ] **Step 1: Write failing snapshot/readiness tests**

    def test_created_job_keeps_default_when_later_default_changes(session: Session, teacher: User, revision: CurriculumObjectiveRevision) -> None:
        _activate_default(session, model="gpt-5-2025-08-07", prompt="generator-v3")
        job = create_or_get_job(session, request=_request(revision), actor=teacher)
        _activate_default(session, model="gpt-5-2026-01-01", prompt="generator-v4")
        assert (job.model_version, job.prompt_version) == ("gpt-5-2025-08-07", "generator-v3")

    def test_ready_is_degraded_when_no_default_exists(client: TestClient) -> None:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["generation_default"] == "unconfigured"

- [ ] **Step 2: Run to verify failure**

Run: python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_default_readiness.py -q
Expected: FAIL because Jobs still use constants/settings.

- [ ] **Step 3: Persist the resolved default before provider call**

    # Add these four keyword arguments to the existing GenerationJob constructor
    # in create_or_get_job; retain every existing constructor argument.
    provider_name=default.provider_name,
    model_version=default.model_version,
    prompt_version=default.prompt_version,
    prompt_template_fingerprint=default.prompt_template_fingerprint,

Extend GenerationJobSnapshot with all four fields. Reject unsnapshotted Jobs with generation_default_not_configured and verify prompt fingerprint at run time. Change provider factory to accept stored provider/model, allow fake only as fake-v1, and use OpenAIResponsesProvider(model=model_version). After database readiness, resolve active default and return 503 with generation_default=unconfigured only for the absence error.

- [ ] **Step 4: Verify and commit**

Run: python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_default_readiness.py -q
Expected: PASS; later default/settings mutation cannot change existing Job.

    git add apps/api/src/edu_grader_api/services/generation.py apps/api/src/edu_grader_api/routers/ai_question_generation.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_default_readiness.py
    git commit -m "feat: snapshot governed generation defaults"

### Task 5: 完成简单管理员页面

**Files:**
- Create: apps/web/app/lib/admin-generation-defaults.ts
- Modify: apps/web/app/pages/admin/index.vue:1-8
- Create: apps/web/tests/admin-generation-defaults.test.ts

**Interfaces:**
- Consumes Task 3 routes and /api/auth/session CSRF token.
- Produces fetchGenerationDefaults, submitGenerationDefaultChange, decideGenerationDefaultChange, applyGenerationDefaultChange and requestGenerationDefaultRollback.

- [ ] **Step 1: Write failing helper/rendering tests**

    it('sends CSRF and idempotency when submitting a change', async () => {
      await submitGenerationDefaultChange(request, 'csrf', 'default-change-1', payload)
      expect(request).toHaveBeenCalledWith('/api/core/v1/admin/ai-generation-default-change-requests',
        expect.objectContaining({ method: 'POST', headers: { 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'default-change-1' } }))
    })

    it('renders current default, pending approval and history without report body', async () => {
      const screen = await mountSuspended(AdminGenerationDefaultsPage, { global: { stubs: { NuxtLink: true } } })
      expect(screen.text()).toContain('当前默认配置')
      expect(screen.text()).not.toContain('private evaluation candidate text')
    })

- [ ] **Step 2: Run to verify failure**

Run: npm --prefix apps/web test -- admin-generation-defaults.test.ts
Expected: FAIL because helper and controls are absent.

- [ ] **Step 3: Implement typed helper and single-page interface**

    export interface GenerationDefaultSummary {
      current: { provider_name: string; model_version: string; prompt_version: string } | null
      pending: GenerationDefaultChangeRequest[]
      history: GenerationDefaultChangeRequest[]
    }

    export function submitGenerationDefaultChange(request: Request, csrfToken: string, idempotencyKey: string, body: SubmitGenerationDefaultChange): Promise<GenerationDefaultChangeRequest> {
      return request('/api/core/v1/admin/ai-generation-default-change-requests', {
        method: 'POST', headers: { 'X-CSRF-Token': csrfToken, 'Idempotency-Key': idempotencyKey }, body,
      })
    }

Use one current-default card, inline submit form, state-gated pending actions and immutable history with rollback. Use short reason fields, disabled write buttons, one message and API reload after success. Do not store drafts or render report JSON, Prompt bodies or hidden identifiers.

- [ ] **Step 4: Verify and commit**

Run: npm --prefix apps/web test -- admin-generation-defaults.test.ts
Expected: PASS.

Run: npm --prefix apps/web run lint
Expected: PASS.

    git add apps/web/app/lib/admin-generation-defaults.ts apps/web/app/pages/admin/index.vue apps/web/tests/admin-generation-defaults.test.ts
    git commit -m "feat: add generation default governance admin page"

### Task 6: 增加浏览器证据和运行手册

**Files:**
- Create: apps/web/e2e/admin-generation-defaults.spec.ts
- Create: docs/operations/ai-generation-default-governance.md
- Modify: docs/README.md

**Interfaces:**
- Consumes Tasks 1-5.
- Produces submit -> independent approval -> apply -> rollback browser evidence and two-admin initialization handoff.

- [ ] **Step 1: Write failing browser flow**

    test('a second platform administrator approves, applies, and rolls back a governed default', async ({ browser }) => {
      const submitter = await loggedInPage(browser, 'platform-admin-a')
      await submitter.goto('/admin')
      await submitter.getByLabel('模型固定版本').fill('gpt-5-2025-08-07')
      await submitter.getByRole('button', { name: '提交晋级申请' }).click()
      const approver = await loggedInPage(browser, 'platform-admin-b')
      await approver.getByRole('button', { name: '批准' }).click()
      await approver.getByRole('button', { name: '应用为默认配置' }).click()
      await expect(approver.getByTestId('current-default-model')).toHaveText('gpt-5-2025-08-07')
    })

- [ ] **Step 2: Run to verify failure**

Run: npm --prefix apps/web run test:e2e -- admin-generation-defaults.spec.ts
Expected: FAIL until fixture and UI integration are complete.

- [ ] **Step 3: Write exact deployment/rollback procedure**

Document: run migration; authenticate two different subjects in GENERATION_GOVERNANCE_ADMIN_SUBJECTS; submit initial passing report; approve with the other subject; apply; assert /ready reports configured default; create a canary Job and inspect snapshots; verify audit chain; perform approved rollback. State migration alone does not configure production and environment fallback is prohibited.

- [ ] **Step 4: Run final verification and commit**

Run: npm --prefix apps/web run test:e2e -- admin-generation-defaults.spec.ts
Expected: PASS.

Run: python -m pytest apps/api/tests/test_generation_default_governance.py apps/api/tests/test_generation_default_governance_api.py apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_governance_controls.py -q
Expected: PASS.

Run: npm --prefix apps/web test -- admin-generation-defaults.test.ts
Expected: PASS.

Run: git diff --check origin/main..HEAD
Expected: no output.

    git add apps/web/e2e/admin-generation-defaults.spec.ts docs/operations/ai-generation-default-governance.md docs/README.md
    git commit -m "docs: add generation default governance runbook"

## Plan Self-Review

| Specification requirement | Plan coverage |
|---|---|
| Immutable configuration, request and current-default boundaries | Task 1 |
| Passing operational report with fixed identities | Task 2 |
| Independent approval, atomic application, audit and rollback | Tasks 2-3 |
| Job-time provider/model/Prompt/fingerprint snapshot and fail-closed readiness | Task 4 |
| Simple no-draft administrator interface | Task 5 |
| Two-admin initialization, browser evidence and deployment handoff | Task 6 |

Placeholder scan passed. All later tasks name their earlier producer exactly.
