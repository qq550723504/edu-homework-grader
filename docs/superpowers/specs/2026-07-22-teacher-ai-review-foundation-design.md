# 教师 AI 候选题审核基础设计

**日期：** 2026-07-22

**范围：** GitHub #41 的第一个端到端基础切片：可审计的候选题修订、验证和受控入库 API。Nuxt 审核界面在该契约稳定后单独交付。

## 根因

当前生成服务已经保存候选题，验证服务也能产生不可变的验证运行；但候选题本身没有审核状态转换、教师编辑快照、拒绝原因或题库来源关联。教师端因而无法在不绕开 `QuestionVersion` 测试与发布门禁的前提下接受候选题。现有按租户读取任务的实现还会让同租户教师读取彼此任务，不满足 #41 的最小授权边界。

## 已评估的方案

1. **只做前端页面。** 能调用生成与验证接口，但不能安全地编辑、拒绝或接受入库；拒绝。
2. **一次交付完整表单、审核和批量入库。** 覆盖面最大，但会把课程选择、Provider 错误体验、持久化审核和 Nuxt 交互混入一个不可审查的大改动；拒绝。
3. **审核领域 API 先行，再接入教师工作台（采用）。** 先建立服务器端状态机、不可变修订和既有题库的受控桥接；下一切片只消费该契约。这样每一步都有独立测试、审核记录和回滚边界。

前端不引入独立状态机库：审核状态必须由后端持久化、并发检查和鉴权决定，Vue 仅投影服务端状态；新增客户端状态机不能提供所需的审计或授权保证。

## 数据边界

`GeneratedQuestionDraft.candidate_json` 保留 Provider 产生的原始候选内容，之后不再覆盖。新增 `GeneratedQuestionDraftRevision`：

- 每份候选在写入时建立第 1 个修订，内容与原稿相同；
- 教师编辑只追加修订，递增 `revision_number`，写入编辑人、内容摘要哈希和时间；
- 教师编辑修订和审核决定都保存请求的 idempotency key 与请求摘要；同一 key 只能重放完全相同的操作；
- 修订使用 `GeneratedCandidate` 的严格 schema，禁止额外字段；`objective_revision_id`、`question_type` 和 `policy_version` 必须与原始候选一致，避免借由编辑跨课程、跨题型或跨政策；
- `GeneratedQuestionDraft.current_revision_id` 指向当前修订；`teacher_state` 只取 `pending_review`、`rejected`、`accepted`。

已有 `GenerationValidationRun` 增加 `draft_revision_id`，验证始终读取该不可变修订，而不是可变工作副本。迁移为历史候选补建第 1 修订，并把历史验证运行关联到它；不会删除或重写历史验证证据。

新增 `GeneratedQuestionReviewDecision` 作为 append-only 审核记录，保存修订、操作者、动作、拒绝原因、warning 确认、受接受后创建的 `QuestionVersion` 和时间。它不保存系统 Prompt、教师约束或 Provider 密钥。

## 状态与并发规则

```text
pending_review --编辑--> pending_review (新 revision，旧验证失效)
pending_review --拒绝--> rejected
pending_review --接受--> accepted (创建 Question + draft QuestionVersion)
```

- 编辑、拒绝、接受均要求请求携带当前 `revision_number` 和 idempotency key；不匹配时返回稳定的 `409 review_revision_conflict`，不覆盖他人的操作。同一 key 且相同请求重放原结果；同一 key 的不同请求返回冲突。
- 编辑成功后立即以新修订调用现有验证器；API 返回新修订和该验证运行。所有旧运行仍可读取，但不再可作为接受依据。
- `blocked` 的当前修订不能接受；`warning` 只能在 `confirm_warnings=true` 时接受；`passed` 不需要确认。
- 只允许 `pending_review` 转换。重复接受或拒绝返回冲突，绝不创建第二个题库草稿。
- 拒绝原因固定为 `incorrect_answer`、`out_of_scope`、`unclear_wording`、`duplicate`、`unsuitable_for_students`、`other`，其中 `other` 必须提供 1–500 字说明。若当前修订尚无验证运行，拒绝操作先同步创建一条运行再记录拒绝；其结果不阻止拒绝，但保证每项审核决定都关联可追溯证据。
- 接受操作在一个事务内锁定草稿、修订和最新验证运行，创建现有 `Question` / draft `QuestionVersion`，写入审核决策和审计事件。它不自动发布，也不绕过测试运行。

## API 与授权

基础切片提供以下 JSON API：

- `GET /v1/ai-question-generation/jobs`：分页返回当前教师自己的任务；管理员可返回本租户任务。
- `GET /v1/ai-question-generation/jobs/{id}`、候选列表、重生、验证运行和审核写操作：教师只能访问自己创建任务的候选；管理员仅限同租户。
- `POST /v1/ai-generated-questions/{id}/revisions`：提交完整、严格的候选修订和 `expected_revision_number`，同步创建验证运行。
- `POST /v1/ai-generated-questions/{id}/reject`：提交版本和规范化原因。
- `POST /v1/ai-generated-questions/{id}/accept`：提交版本与 `confirm_warnings`，返回新建 draft `QuestionVersion` 标识。

响应只返回候选、修订号、审核状态、可展示的验证发现与题库草稿标识；不返回 Provider 请求摘要、模型密钥、系统 Prompt 或教师私有约束。所有读取以 404 隐藏跨租户或跨教师资源。

## 与既有题库的桥接

接受后使用既有 `create_question` 服务，以候选的 `prompt`、`question_type`、`policy_version` 与 `rule_json` 创建草稿。标题由安全截断的题干派生，保证不引入另一套题库创建逻辑。

E4 阅读材料不能拼接进 `QuestionVersion.prompt`：该列有 10,000 字符契约，且 prompt 指纹是题干去重的稳定边界。为此，`QuestionVersion` 增加独立的可空 `reading_material` 文本字段；AI E4 接受时写入该字段、题干仍写入 `prompt`，因此材料不会截断且题干重复检测保持不变。学生作业详情单独投影 `reading_material`，前端在题干前渲染它；旧题和非 E4 均返回/渲染为空。继任草稿保留该字段。首次切片不自动建测试用例：现有教师题库界面已经能为草稿创建测试、运行测试和发布；下一 UI 切片会将其串联。题库版本不会直接成为 `published`。

## 验收与测试

- 原始候选不可变；编辑得到新的、可追溯修订，编辑后验证绑定新修订。
- 锁定字段、schema、版本冲突、跨教师/跨租户访问均被拒绝且无信息泄漏。
- blocked 拒绝接受；warning 缺少显式确认拒绝；已通过或确认 warning 的接受恰好创建一个 `QuestionVersion(status=draft)`。
- 拒绝记录标准化原因和审核人；接受记录来源修订、审核人和新版本。
- 现有生成、验证、题库发布测试继续通过；新 API 测试覆盖以上状态机与事务幂等边界。

## 后续切片（不在本 PR）

Nuxt “AI 出题”模块将基于这些 API 添加生成表单、任务/候选卡、验证证据、编辑、拒绝、接受和批量操作。课程 profile 级联选择、成本预估、批量接受与 Playwright 全链路会在该 API 可用且数据契约稳定后实现，避免 UI 先行固化错误协议。

## 交付验证记录（2026-07-22）

- 最终评审修复后的 API 回归命令使用实际存在的 `apps/api/tests/test_questions.py`（计划中的 `test_questions_api.py` 不存在），连同生成模型、候选验证、审核 API、审核状态机和验证模型共运行 263 项测试，全部通过（39.80 秒）。公共候选列表已覆盖编辑后返回当前修订候选与 `revision_number`；接受入库标题已覆盖题干规范化、控制字符清理、200 字符上限和空/不安全输入回退。
- `ruff check` 覆盖 `apps/api/src/edu_grader_api`、0021 迁移和上述测试文件，结果为 `All checks passed!`；`ruff format --check` 报告 54 个文件均已格式化；`git diff --check` 无输出且退出成功。
- 迁移脚本链的静态 head 已由 `python -m alembic heads` 确认为 `0021_protect_ai_review_evidence`。0021 的隔离测试验证了 PostgreSQL 触发器只阻止 Provider 原稿 `candidate_json` 的实质变更、不会阻止生命周期状态或当前修订指针更新，并阻止 `validation_findings` 的 UPDATE/DELETE。本地仍未在真实 PostgreSQL 执行 `alembic upgrade head`：工作树没有可用数据库配置，先前默认连接已超时。因此合并前必须在已配置 PostgreSQL 环境完成升级，或等待 CI migration job 通过；在此之前不得合并，也不得把迁移标记为已在本地数据库应用。
- 授权回归包含教师仅可列出和变更自己生成任务的检查，跨教师草稿变更返回 `404`；管理员仍保持租户范围。Nuxt 审核界面、课程 profile 级联选择、成本预估、批量接受及 Playwright 端到端流程仍明确留在后续切片，Issue #41 不在本 PR 关闭。
