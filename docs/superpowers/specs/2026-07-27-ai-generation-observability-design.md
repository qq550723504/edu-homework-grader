# AI 出题生成可观测性与自动校验设计

**日期：** 2026-07-27  
**状态：** 已确认，待实施计划  
**范围：** AI 出题批次的候选过滤诊断、生成后的首次校验和教师端批次状态呈现。

## 目标

教师创建或重新生成 AI 题目后，应当能够：

1. 在模型返回候选但平台拒绝入库时，看到安全且可操作的失败原因；
2. 在候选入库后立刻看到权威的 `passed`、`warning` 或 `blocked` 校验结论；
3. 不必为了触发首次校验而保存一次没有内容变化的修订。

AI 候选仍须经教师接受才能创建题库草稿；不会自动发布给学生。

## 根因

`run_generation_job` 目前对模型的结构化输出只保留候选数。候选在目标修订、题型、目标难度或策略规则任一条件不符时被静默跳过。若全部跳过，任务成为 `failed`，但 `failure_code` 为空，前端只能显示“失败 1 / 暂无候选题”。

候选入库后也不会自动调用现有的预算感知校验。首次 `GenerationValidationRun` 只在教师保存修订或做出审核决策时创建，因而生成完成后的候选必然显示“待校验 / 暂不能接受”。

## 采用方案

### 安全过滤诊断

在每个 `GenerationAttempt.response_summary` 中，除 `candidate_count` 外记录每个被跳过序号和稳定失败码。允许的失败码仅描述平台约束：

- `objective_revision_mismatch`
- `question_type_mismatch`
- `difficulty_out_of_tolerance`
- `policy_rule_invalid`
- `unexpected_candidate_ordinal`

诊断不保存模型的原始响应、题干、解析或评分规则。任务未成功产生任何候选时，`GenerationJob.failure_code` 为 `candidate_validation_failed`；批次 API 额外返回可展示的失败码摘要。

### 生成后自动校验

生成路由在成功持久化候选后，为每个新草稿的当前修订调用现有 `run_budget_aware_candidate_verification`。创建批次和单题重新生成共享同一私有协调函数，避免两条路径出现不同的校验行为。

校验仍使用既有 `HttpGraderClient`、现有的验证运行与 finding 模型；不产生教师修订，不伪造教师动作，也不改变 `accepted`、`rejected` 或批量接受状态机。

### 教师端呈现

批次列表保留当前成功/失败计数，但对失败批次显示一个安全的原因摘要。候选列表沿用当前从最新 `GenerationValidationRun` 派生的状态；因为生成时已创建校验运行，教师初次进入即可看到 `passed`、`warning` 或 `blocked`，无需无意义保存。

## 数据流

```text
Provider response
  -> 生成服务筛选并记录安全失败码
  -> 持久化有效草稿与初始修订
  -> 路由协调器运行既有候选校验
  -> job/draft/validation APIs
  -> 批次失败摘要与审核结论
```

Provider 请求失败继续使用既有 `ProviderFailure` 处理；候选过滤不是 Provider 故障。初始校验若出现正常的业务 finding，草稿保留并以 `blocked` 或 `warning` 进入教师审核。基础设施级校验异常沿用现有请求失败语义，不能把未完成的校验伪装成通过。

## 测试与验收

- 生成服务测试证明每一种过滤路径都有稳定、无内容泄漏的诊断；
- API 测试证明全量过滤的 job 有 `candidate_validation_failed` 和公开摘要；
- API 测试证明创建和重新生成路径会为每个生成草稿创建一次初始校验运行；
- Web 渲染测试证明失败摘要可见，且已有初始校验的候选不显示“待校验”；
- 运行 API 相关 pytest 与 Web 相关 Vitest。

## 非范围

- 不保存完整被拒模型输出；
- 不修改模型、Prompt、配额和课程目录；
- 不改变教师接受、拒绝、题库草稿或发布流程；
- 不处理待人工复现的 G8/G1 选择异常。
