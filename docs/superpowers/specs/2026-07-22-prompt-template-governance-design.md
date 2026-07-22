# Prompt 模板治理设计

**日期：** 2026-07-22

**范围：** GitHub #43 的 Prompt 模板版本化与生成记录可追溯性

## 根因

当前 API 接受任意非空 `prompt_version`，但 OpenAI 的系统约束直接硬编码在 Provider。`GenerationAttempt` 只保存版本字符串，不能证明某次生成使用了什么系统约束、输出 Schema 或允许的题型/profile 范围。

## 决策

在 `edu_generator` 建立服务端静态 Prompt 模板目录。每个模板是不可变的值对象，至少含：

- 版本 ID；
- 精确系统约束文本；
- 输出 Schema 版本；
- 允许题型集合；
- profile 适用范围标识；
- 对上述规范化元数据和系统约束计算出的 SHA-256 指纹。

首个目录项 `generator-v1` 忠实承载当前 OpenAI 系统约束、既有 `generated_question_candidates` Schema 和所有当前题型，profile 范围为所有已激活课程 profile。未知模板版本或题型不适用的版本在创建 Job 时失败关闭；Provider 也在调用前重新解析目录，避免绕过服务层。

不新增数据库迁移。既有 `GenerationAttempt.prompt_version` 保留版本 ID；其已有 `request_summary` 写入 schema 版本、profile 范围、适用题型和模板指纹，形成对当时模板内容的审计锚点。

## 边界

- 不让普通教师读取系统约束、模板正文、密钥或防护细节；创建 Job 的 API 响应不增加这些内容。
- 不新增模板的管理员编辑、禁用、灰度、回滚或跨租户选择；这些是 #43 后续治理切片。
- 不执行 #42 的模型/Prompt 回归评估，也不改变 #41 的教师审核、接受或发布门禁。
- Fake provider 继续用于测试；其生成输出不模拟 Prompt 解释，但使用相同的目录预检。

## 验收

- `generator-v1` 产生与当前等价的 OpenAI 系统约束与严格 Schema。
- 未知或题型不适用的版本无法创建正式 GenerationJob，也无法通过直接 Provider 调用。
- 每次 Attempt 的持久化摘要包含版本、Schema、profile 范围、适用题型和稳定指纹，但不含系统 Prompt 正文或凭据。
- Job 和草稿 API 响应不泄露上述模板正文。
