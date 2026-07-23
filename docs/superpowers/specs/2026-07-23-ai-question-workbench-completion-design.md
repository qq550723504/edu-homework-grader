# AI 出题工作台收尾设计

**日期：** 2026-07-23

**Issue：** #41

**范围：** 完成教师 AI 出题工作台尚未交付的逐题难度分布、单题重生成与批量接受闭环。

## 背景与根因

已合入的生成表单、审核工作台和后端批量接受接口完成了 #41 的大部分流程，但仍有三个缺口：

1. 公开生成请求只有扁平 `question_types`，无法把“基础／中等／提高”的目标难度可靠地交给 Provider，也无法在审核时证明候选题应满足哪个目标。
2. API 已有单题重生成和原子批量接受端点，教师界面尚未接入，因此浏览器不能完成 issue 要求的两类操作。
3. 现有工作台的单项操作可恢复，但批量操作需要同样明确的 warning 确认、幂等重放和刷新恢复语义。

浏览器不能成为课程、验证、额度或审核权限的权威；只在前端增加控件会把这些保证变成可绕过的展示。

## 已评估方案

1. **仅在前端接通重生成和批量接受。** 变更最小，但难度分布仍没有可信生成契约，不能完成 #41；不采用。
2. **在现有任务 `distribution_json` 中持久化有序逐题计划（采用）。** 服务端将题型和难度档位转换为目标难度；Provider、验证、重生成和审核都消费同一计划。它复用已有任务、候选题 ordinal 和快照机制，不需要重复的数据表。
3. **新增独立的逐题计划表。** 可支持未来复杂调度，但与当前任务 JSON、候选题顺序和 immutable revision 重复，迁移与维护成本超过本期价值；不采用。

## 服务端契约与数据流

公开创建请求由 `question_types` 改为有序 `items`：

```json
{
  "curriculum_objective_revision_id": "uuid",
  "items": [
    {"question_type": "M1", "difficulty_band": "foundation"},
    {"question_type": "M2", "difficulty_band": "stretch"}
  ],
  "requested_count": 2,
  "teacher_constraint": "只使用动物主题，不含学生信息"
}
```

`difficulty_band` 只允许 `foundation`、`standard` 和 `stretch`。服务端从 active curriculum objective revision 的 `difficulty_min` 与 `difficulty_max` 推导各档位的确定性目标值，构造并持久化如下计划：

```json
{
  "items": [
    {"question_type": "M1", "difficulty_band": "foundation", "target_difficulty": 0.2},
    {"question_type": "M2", "difficulty_band": "stretch", "target_difficulty": 0.8}
  ]
}
```

客户端不能提交 `target_difficulty`、年级、学科、Prompt、模型或政策版本。创建服务验证项目数、允许题型、课程权限、额度和幂等请求后，才创建任务并向 Provider 发出包含有序逐题计划的请求。Provider 返回的候选题仍以 ordinal 绑定该计划项；验证结果必须说明候选难度是否偏离其计划目标。任务保留完整计划，即使默认 Prompt 或课程版本以后变化。

`POST /v1/ai-generated-questions/{draft_id}/regenerate` 从源 draft 的 ordinal 找到原任务计划项，并为新单题任务复制题型、难度档位、目标难度和原任务快照。它只创建新任务，绝不修改源候选、修订、验证或审核记录。额度、去标识化和 Provider 错误仍使用既有服务端控制。

## 教师工作台

生成表单在每个允许题型下提供基础、标准和提高的计数控件，并从其派生有序 `items`。页面展示总题量、真实可用额度以及课程允许的难度范围；它不估算没有可信数据源的金额。提交成功后只在路由中保存 job id。

审核工作台增加：

- 每个候选题的选择状态和批量接受工具栏；只有 `pending_review` 的候选可选择，blocked 候选始终不可选。
- warning 候选的逐题确认。未确认的 warning 不会发送为 `confirm_warnings: true`，而后端仍负责最终拒绝。
- 使用 `POST /jobs/{job_id}/bulk-accept` 的单个 Idempotency-Key；服务端成功才更新被接受项，任一冲突、blocked、过期修订或未确认 warning 都显示为整批失败并保留用户选择。
- 每张候选卡的“重新生成”操作。它使用 CSRF 和 Idempotency-Key；成功后跳转到新单题任务，源题的链接和审计轨迹保持不变。

所有写操作沿用现有公共错误映射。网络结果不确定时，客户端保留同一幂等键，并以刷新读取权威服务端状态，而非假定本地操作成功。页面不展示 Provider 密钥、系统 Prompt、私有验证特征或内部安全规则。

## 组件边界

- `apps/api/src/edu_grader_api/services/generation.py`：计划模型、目标推导、请求合法性、Provider 请求和重生成继承。
- `services/generator`：将有序计划作为公开内部 Provider 契约的一部分，并在假 Provider 与 OpenAI Prompt 中保持一致。
- `apps/api/src/edu_grader_api/routers/ai_question_generation.py`：缩小公开请求、投影安全的计划元数据，并保持写入端点的授权/幂等语义。
- `apps/web/app/lib/teacher-ai-generation.ts`：难度计数到请求项目的纯转换与客户端预检。
- `TeacherAiGenerationForm.vue`：题型/难度计数、额度和明确状态，不持有服务端权威。
- `apps/web/app/lib/teacher-ai-review.ts`：批量接受与重生成的纯 API 客户端和类型。
- `TeacherAiReviewWorkspace.vue` 与 `TeacherAiCandidateReview.vue`：选择、warning 确认、写入协调和跳转；不复制接受资格判断。

## 错误处理与安全不变量

- 课程目标不允许的题型、未知档位、数量不一致、伪造目标难度、额度不足和同键不同体必须由服务端拒绝。
- 单题重生成必须继承源计划；它不得把已审核候选回写为 pending 或改变其验证证据。
- 批量接受保持 all-or-nothing：写入失败不能产生部分 `QuestionVersion` 草稿。
- `blocked` 永不可接受；`warning` 必须由教师逐项确认；任何成功结果都只创建 `draft` QuestionVersion。
- 任务、候选题和批量接受均遵从 tenant/teacher 范围，且请求、日志和 Provider 载荷不含学生、班级、成绩、作答或访问令牌。

## 验证

- API/服务层：难度计划推导与快照、Provider 输入、候选顺序/计划对应、重生成继承、权限、额度、请求幂等与批量原子回滚。
- Vitest：难度计数展开、选择限制、warning 确认、公开错误映射、提交中状态与未知结果刷新。
- Playwright：G7 M1/M2 的生成到批量接受，以及 G8 E1/E4 的生成、单题重生成、审核和草稿题库交接。
- 回归：相关 API 套件、Web Vitest、Nuxt build 与现有教师 AI E2E。

## 非范围

- 模型或 Prompt 成本金额估算、队列轮询基础设施和 #42 离线评估体系。
- 模型/Prompt 灰度、回滚、预算告警与其他 #43 治理交付。
- K 阶段非评分活动（#44）和发布级真实 OIDC/PostgreSQL/Grader 全栈环境（#31）。
