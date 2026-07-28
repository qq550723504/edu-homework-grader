# AI 生成默认配置治理运行手册

全局 AI 生成默认值由一个固定 Provider、不可变模型版本和已登记 Prompt 版本组成。它不是环境变量，也不按租户、用户或流量比例覆盖。每次变更都必须有通过的运营评估报告、不同主体的审批和审计链记录。

## 部署前提

1. 部署包含 Alembic `0027_generation_default_governance` 的 API，并运行数据库迁移。
2. 在受保护的部署环境配置 `GENERATION_GOVERNANCE_ADMIN_SUBJECTS`，填写至少两个不同的 OIDC subject，以逗号分隔。普通学校管理员、教师和学生不应出现在此列表。
3. 确认候选 Provider、模型和 Prompt 的全局生成治理状态为 `active`。`canary`、`paused`、`retired` 都不能作为全局默认值。
4. 使用生产形态、只读导出的运营评估生成报告。报告必须表示候选配置、`promotion_eligible=true`，并带有确定的 run、spec、水位和记录摘要；不要把题目正文、Prompt 正文、密钥或身份信息粘贴进申请说明。

迁移只创建治理数据结构，**不会**写入生产默认值。没有生效默认值时，`/ready` 返回 HTTP 503，新的生成任务返回 `generation_default_not_configured`；不得以环境变量或代码常量回退。

## 首次初始化与晋级

1. 平台治理管理员 A 登录 `/admin`，在单页中填写 Provider、模型固定版本、Prompt 版本、简短申请说明，以及完整的运营评估报告 JSON，然后提交晋级申请。
2. 管理员 B（不同 OIDC subject）在“待审批”中审阅版本标签、原因和安全证据摘要；报告正文和 Prompt 正文不会在页面或 API 响应中展示。B 填写审批说明并批准。
3. 任一平台治理管理员在历史记录中填写应用说明并“应用”。该动作会再次校验候选 Prompt 指纹和全局控制状态，在一个事务中切换唯一全局指针并写入 HMAC 审计链。
4. 访问 `/ready`，必须得到 `{"status":"ready","database":"ready","generation_default":"ready"}`。若 `generation_default` 为 `unconfigured` 或 `unavailable`，停止发布并处理配置/数据库问题。
5. 创建一个小规模生成 Job，核对 `generation_jobs.provider_name`、`model_version`、`prompt_version` 和 `prompt_template_fingerprint` 都是刚应用的值。后续默认值改变不应修改既有 Job 的快照。
6. 核对审计链中的 `ai_generation_default.change_submitted`、`change_approved` 和 `change_applied` 事件；审计元数据只能含配置 ID、版本标签和摘要，不应含题目、Prompt、密钥、邮箱或 OIDC subject。

提交者不能审批自己的申请。重复使用相同幂等键只允许完全相同的请求；不同内容会被拒绝。已批准的请求也只能应用一次。

## 回滚

回滚同样需要独立审批，不是直接覆盖：

1. 在“历史”中找到要恢复的旧默认值（通常是被新值替换后状态为 `superseded` 的记录），点击“申请回滚”并填写原因。
2. 由另一个治理管理员批准回滚申请。
3. 应用该已批准的回滚申请，检查 `/ready` 仍为 `generation_default=ready`，并创建一个小规模 Job 验证新 Job 已快照旧配置。
4. 复核回滚提交、批准和应用的审计事件，并记录触发原因、影响范围和后续评估计划。

不要对当前候选值本身发起“回滚到自身”的申请；应选择需要恢复的历史配置。发生 Provider 故障或质量事故时，可以先把受影响组件的全局治理状态置为 `paused` 来阻止新晋级与运行，再走上述独立审批恢复已验证的默认值。

## 故障处理

- `/ready` 的 `database=unavailable`：先恢复数据库连通性，不要尝试修改默认指针。
- `/ready` 的 `generation_default=unconfigured`：按首次初始化流程完成双人审批和应用。
- 提交或应用被拒绝为组件未激活：修复相应全局 Provider/模型/Prompt 控制状态，并重新验证运营证据；不要绕过控制记录。
- Prompt 指纹已变化：不要应用旧申请。重新运行评估，以当前目录中的 Prompt 重新提交申请。
- 生成 Job 失败为 `generation_default_not_configured`：该 Job 不会回退到环境变量。完成治理初始化后，以新的幂等键重新创建 Job。

保留运营评估产物和审计证据的访问控制、保留期及事件响应流程，遵循[生产事实评估运行手册](ai-evaluation-operational.md)。
