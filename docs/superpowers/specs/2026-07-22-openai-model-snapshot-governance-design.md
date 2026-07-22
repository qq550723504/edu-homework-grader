# OpenAI 模型快照治理设计

**日期：** 2026-07-22

**范围：** GitHub #43 的不可变模型标识要求

## 问题

当前 OpenAI 生成配置只要求 `GENERATOR_OPENAI_MODEL` 非空。`gpt-5` 这类别名会随服务端更新而指向不同底层快照，却会被原样保存为生成尝试的 `model_version`，使同一审计记录无法确定实际模型版本。

## 决策

仅当 `GENERATION_PROVIDER=openai` 时，模型必须是可辨识的不可变 OpenAI 模型 ID。接受三种稳定形式：以有效 ISO 日期结尾的快照（例如 `gpt-5-2025-08-07`）、旧式有效月日快照（例如 `gpt-4-0613`），以及 OpenAI 返回的四段 fine-tuned ID（例如 `ft:gpt-4o-mini:acemeco:suffix:abc123`）。空值保留现有“未配置”错误；普通别名、`latest`、日期无效或结构不完整的值统一拒绝。

实现一个只依赖标准库的生成器边界校验函数，并在两个位置调用：

1. `Settings` 的 OpenAI 生产配置校验，确保不安全部署在启动时失败；
2. `OpenAIResponsesProvider` 构造器，确保绕过设置直接构造适配器时仍然失败关闭。

生产环境的跨字段设置校验由声明顺序最后的设置字段的 `after` validator 执行，且启用默认值校验。它仅在所有前置字段已成功解析后运行，因此保留原有字段解析优先序；Pydantic 的结构化错误只携带该安全字段的输入，而不是完整原始设置输入。这样避免 `@model_validator` 将 API key 附到 `ValidationError.errors()`。

成功时完整快照字符串仍写入既有 `GenerationAttempt.model_version`。不添加迁移，不选择或默认任何实际模型，不读取或写入密钥。

## 约束与边界

- 不改变 fake provider 或其他 provider。
- 不把有效 OpenAI API key 暴露在设置校验的字符串或结构化错误中。
- 直接构造、`model_validate`、JSON/字符串 Pydantic 验证及 `TypeAdapter` 入口使用同一生产安全策略。
- 不治理 `prompt_version`、提示词目录、灰度、回滚或评测；这些仍是 #43 的后续独立切片。
- 不改变 #39 的真实 Provider 部署前提：部署方仍需提供受控的 API 密钥、允许的端点和具体快照。
- 验证规则对日期快照校验真实日历日期，对旧式月日快照校验有效月日；fine-tuned ID 必须符合 OpenAI 的固定四段结构。规则不从名称中推断端点兼容性，实际调用仍由 Provider 处理。

## 验收

- `gpt-5-2025-08-07`、`gpt-4-0613` 和合法 fine-tuned ID 可用于 OpenAI 设置和适配器。
- `gpt-5`、`latest`、无效日期、无效旧式月日和结构不完整的 fine-tuned ID 在启动配置和直接适配器构造中都被拒绝。
- 缺少模型保持既有 `provider_not_configured` 语义。
- 现有允许端点校验、结构化输出和审计持久化行为不变。
