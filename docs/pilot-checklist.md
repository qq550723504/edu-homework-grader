# 试点上线检查表

本检查表区分仓库门禁、发布环境验收和学校上线。勾选仓库 CI 不等同于勾选真实环境或生产项。当前证据基线见 [项目状态](project-status.md) 和 [机器可读状态证据](status-evidence.json)。

## A. 仓库 Release Candidate

- [x] 英语 E1–E4 引导建题可通过浏览器创建、测试和发布。
- [x] 同一学科支持多题、多题型作业编排、排序和学生预览。
- [x] Python、迁移、Compose、真实 Grader、Web 和 Chromium E2E 受保护检查全绿。
- [x] AI 只生成候选题；`blocked` 无法接受，`warning` 必须明确确认。
- [x] AI 候选题编辑后形成不可变 revision 并重新验证。
- [x] 接受 AI 候选题只创建 `QuestionVersion` 草稿，仍需原有测试和发布门禁。
- [x] `generator-v3` 真实 Provider 对 M1、M2、E1、E4 的受控验收通过。
- [x] 离线 AI evaluation gate 能在样本不足、未批准版本、矛盾状态或质量退化时失败。
- [x] 生产形态的生成/验证/审核数据可导出去标识化事实并做显式版本比较。
- [x] 文档状态、内部链接、CI Job、策略版本、Generator/Validator 版本和英语模型锁定值进入自动校验。

## B. 发布环境统一全栈验收（#31）

- [ ] 使用学校受控 HTTPS OIDC 完成真实教师、学生登录、刷新和登出。
- [ ] 不使用固定 E2E 身份、SQLite、Fake Provider 或 Grader monkeypatch。
- [ ] 在同一隔离环境运行 Nuxt BFF、Core API、PostgreSQL、Generator、固定真实 Provider、Grader 和 LanguageTool。
- [ ] 教师通过浏览器完成 M1、M2、E1、E4 的生成、验证、证据查看、编辑/重验、接受、题目测试和发布。
- [ ] 数据库中的 Job、Attempt、Candidate Revision、Validation Run、Review Decision、QuestionVersion 和 AuditEvent 与 UI 一致。
- [ ] `blocked`、`warning`、Provider 暂停、Grader/LanguageTool 故障和恢复场景符合 fail-closed 设计。
- [ ] 同一验收连续运行两次，无端口、会话、数据库、幂等键或资源残留冲突。
- [ ] Playwright trace、服务日志和诊断制品不包含令牌、学生答案或 Provider 密钥。

## C. 学生同步可靠性（#32）

- [ ] 明确区分真正离线、401、403、409、422、429 和 5xx。
- [ ] 不可重试错误停止自动重放；可重试错误使用有界退避。
- [ ] 409 冲突提供安全、可理解的最低可用解决界面。
- [ ] 页面卸载时清理网络、可见性和同步监听器。
- [ ] 本地草稿在会话过期或临时服务故障后仍可恢复。

## D. 身份、密钥与处理器边界

- [ ] 所有数据库、Keycloak 管理员、会话、Provider 和 `AUDIT_HMAC_KEY` 均来自受控 Secret Manager，不使用示例默认值。
- [ ] 学校管理员与平台课程/生成治理管理员使用不同 allowlist 和权限边界。
- [ ] Generator Provider 仅允许批准主机；普通教师无法读取系统 Prompt、模型密钥或治理细节。
- [ ] Grader/LanguageTool 网络仅允许 `PROCESSOR_ALLOWED_HOSTS`。
- [ ] 生成请求、日志和外部载荷不包含学生、班级、成绩、作答或访问令牌。
- [ ] Key、证书和审计 HMAC 轮换流程完成演练。

## E. 英语模型与批改服务

- [x] 英语模型具有固定 `model_id`、revision、tree digest 与离线目录。
- [x] Grader Dockerfile 构建时下载并校验固定制品。
- [x] CI 已构建真实 Grader/LanguageTool 并通过 Core API HTTP 集成。
- [ ] 发布环境 Grader `/ready` 返回 `ready`，并报告期望模型和运行库版本。
- [ ] 发布环境完成英语校准、延迟、并发和降级验收。
- [ ] E3/E4 始终由教师作最终判断，不因模型可用而自动发布成绩。

## F. AI 质量与治理（#42、#43、#83、#99）

- [ ] 在只读 Release Candidate PostgreSQL 副本运行 `Operational AI evaluation`，保存固定水位、manifest/digest 和报告 Artifact。
- [ ] 教师黄金集覆盖 Profile、年级、学科、题型和难度；数学答案有学科核验，E3/E4 有双教师裁决。
- [ ] 正式 Schema、答案、年级、重复、安全、接受率和成本阈值经教学评审并版本化。
- [ ] 默认模型/Prompt 晋级绑定通过的正式报告；回滚绑定历史批准版本和审批证据。
- [ ] Provider 数据保留、训练使用、区域和子处理器政策完成审查。
- [ ] 配额、并发、预算和异常成本告警完成演练。
- [ ] 内容来源、许可、权利人投诉、下架和受影响题目定位流程可执行。
- [ ] Curriculum Profile/年级复杂度、objective prerequisite 和数学多解/定义域边界完成验证。

## G. 数据、同意、备份与恢复（#33）

- [ ] 导入真实名册并核验未成年人监护人同意；缺失或撤回同意必须拒绝处理。
- [ ] 先运行 `python -m edu_grader_api.guardian_consent_integrity`；仅在确认结果后使用 `--execute` 为缺失记录建立 `pending` 状态。
- [ ] PostgreSQL 自动备份已启用，保留期限和加密符合试点要求。
- [ ] 在隔离数据库完成恢复演练，验证题目、作业、评分、审核决定和审计链。
- [ ] 迁移升级、回滚边界和应用版本回滚完成演练。
- [ ] 数据保留、删除、访问角色和事故响应经产品、运维和合规确认，见 [数据清单](data-inventory.md)。

## H. 实际部署、可观测性和签署（#33）

- [ ] Kubernetes/GHCR SHA 镜像已经实际 rollout；不能仅以清单或工作流存在作为证据。
- [ ] TLS、Ingress、DNS、Secret 注入、Pod 权限和网络策略通过检查。
- [ ] API、BFF、OIDC、PostgreSQL、Redis、Grader、LanguageTool 和 Generator 指标/日志/告警已接入。
- [ ] 提交峰值、批改 Worker 饱和、Provider 限流和 30–60 分钟长稳测试通过。
- [ ] Feature Flag、Generator/Provider/模型/Prompt Kill Switch 和应用回滚完成演练。
- [ ] 错误答案、内容安全、隐私泄露、Provider 故障和异常成本事故手册完成桌面演练。
- [ ] 产品、教学、运维、安全/合规负责人完成试点放行签署。
- [ ] 仅在以上真实环境证据完成后，才可把状态从“发布环境已验收”提升为“生产已上线”。
