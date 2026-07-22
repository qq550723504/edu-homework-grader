# 教师 AI 出题请求设计

**日期：** 2026-07-22

**范围：** GitHub #41 的生成请求切片。教师依据当前课程目标创建候选题批次，随后进入已合并的审核工作台。单题重生成和批量接受仍留给后续切片。

## 根因与边界

已有 `POST /v1/ai-question-generation/jobs` 是集成契约：浏览器必须自行提供年级、学科、政策目录版本和 Prompt 版本。服务端只验证目标 active 及题型允许，遭篡改或过期页面仍能把与课程目标不一致的元数据写入任务；额度也只在提交后以 429 返回。

本切片将课程目标修订版作为唯一课程权威。服务端从其 `objective.subject` 和 `grade_mapping.internal_level` 派生任务学科、年级；由服务器拥有的常量选择并快照记录政策目录与 Prompt 版本。浏览器只提交 `curriculum_objective_revision_id`、题型分配、题数和可选的去标识化教师约束。服务端仍是授权、配额、幂等和审计的唯一权威。

浏览器不显示或保存 Provider 密钥、系统 Prompt、请求摘要、私有验证特征或教师约束历史。费用没有可信的费率/计量契约，页面不得推测金额；只显示真实的批次和当日额度计数。

## 已评估方案

1. **在网页硬编码版本和上限。** 最快接通旧写接口，但会把策略复制到不可信客户端，且不能防止年级/学科漂移；不采用。
2. **新增服务端受控生成表单契约，复用既有课程读取接口（采用）。** 课程 profile、年级映射和目标继续从 `/v1/curriculum-profiles/*` 读取；新增 `/v1/ai-question-generation/limits` 返回调用者真实可用额度；创建路由缩小为不含客户端版本、年级和学科的请求。
3. **另建课程 API 或费用估算。** 前者复制已有目录，后者没有可验证数据源；不采用。

## API 契约

`GET /v1/ai-question-generation/limits` 仅供 admin/teacher 使用，按当前 tenant 和 UTC 日统计：

~~~json
{
  "max_batch_size": 20,
  "daily_tenant_limit": 100,
  "daily_used_count": 36,
  "remaining_count": 64
}
~~~

它只作预检；创建路由仍在写入前重新计算，避免并发超额。

`POST /v1/ai-question-generation/jobs` 的公开 body：

~~~json
{
  "curriculum_objective_revision_id": "uuid",
  "question_types": ["M1", "M1", "E1"],
  "requested_count": 3,
  "teacher_constraint": "只使用动物主题，不含学生信息"
}
~~~

重复题型就是题型数量分配，`requested_count` 必须等于 `question_types.length`。服务端拒绝不允许题型、含个人数据的约束、超单批/当日额度和同一幂等键的不同请求。任务持久化时派生年级、学科，并使用 `GENERATION_PROMPT_VERSION` 与 `GENERATION_POLICY_CATALOG_VERSION` 快照。重生成沿用原任务快照，不走浏览器表单契约。

本切片展示目标的 `difficulty_min`/`difficulty_max` 作为生成边界和审核参考，但不伪造“按难度比例生成”：当前 Provider 请求无法证明逐题配比输出。难度分布将在后续 Provider/验证契约切片中作为显式 per-candidate target 实现。

## 页面和数据流

导航在现有 `/teacher/ai-questions` 审核页提供“生成新批次”链接，打开独立且可恢复的 `/teacher/ai-questions/new`。

~~~text
GET curriculum profiles
  -> GET grade mappings(profile)
  -> GET objectives(profile, grade, subject)
  -> GET generation limits
  -> POST generation job + CSRF + Idempotency-Key
  -> /teacher/ai-questions?job=<new-id>
~~~

选择 profile 清空年级、学科、目标和题型；选择年级清空学科、目标和题型；选择学科重读目标；选择目标将题型分配复位，显示目标文本、允许题型和真实难度范围。数量控件以每个允许类型的非负计数表示分配，再派生扁平 `question_types`。总数为零、超过 `min(max_batch_size, remaining_count)` 或存在不允许类型时，提交禁用并说明原因。

加载、空目录、额度为零、创建中、429、422、409、503 和网络失败均有明确状态。成功后仅保留服务端 job id；约束与幂等键不进入 URL、localStorage 或历史列表。网络重试同一未决操作复用同一个 key。

## 组件边界

- `apps/web/app/lib/teacher-ai-generation.ts`：纯类型、课程/额度/创建请求函数、题型计数展开与提交前校验。
- `TeacherAiGenerationForm.vue`：课程级联、加载状态、题型计数、提交与公开错误；仅 emit 成功 job。
- `TeacherAiGenerationPage.vue`：获取会话 CSRF、管理一次提交的幂等键、成功跳转审核页。
- `pages/teacher/ai-questions/new.vue`：复用教师工作台壳和导航。

窄屏按 profile、年级/学科、目标、题型分配、额度和提交按钮的单列顺序显示；宽屏仅在不改变阅读顺序时使用 Grid。所有字段有关联 label，题型加减控件包含具体题型的 accessible name。

## 测试与验收

- API：外部无法伪造年级/学科/版本；类型数与总数不一致、目标不允许类型、配额不足、幂等冲突均被拒绝；额度端点按 tenant 和 UTC 日隔离。
- Vitest：课程查询 URL 编码；计数正确展开；限制、目标范围和空选择阻止提交；创建请求含 CSRF/幂等头且不发送旧客户端字段。
- DOM：级联清空下游选择；目标仅显示允许题型和真实难度范围；成功跳转返回 job；错误不泄露服务器异常原文。
- Playwright：E2E 教师选择已种入课程目标、分配题型、创建 fake Provider 批次并到达该批次审核页。
- 全量 API/Web 测试、Nuxt build 和既有审核 E2E 不回归。

## 明确不做

本切片不实现未经 Provider 契约保证的难度配比、费用金额、单题重生成、批量接受、任务轮询或跨目标混合批次。任务完成后的审核、编辑、拒绝和单题接受继续由 #77 工作台处理。
