# 文档索引

## 当前状态与路线

- [项目状态](project-status.md)：能力、验证证据和生产限制。
- [试点上线检查表](pilot-checklist.md)：真实登录、模型、密钥、备份恢复、同意和 CI 放行项。
- [产品路线图](roadmap.md)：作业批改 MVP、试点门槛、AI 出题和自适应学习阶段计划。

## 产品实施计划

- [K–13 课程约束型 AI 出题实施计划](ai-question-generation-plan.md)：课程模型、生成服务、验证门禁、教师审核、质量指标和 12 周实施安排。
- [学生知识画像与自适应练习实施计划](adaptive-learning-plan.md)：交付顺序、系统边界和 16 周实施安排。其早期数据模型草图已由 Learning Event v1 数据契约取代；迁移、Schema 和消费者必须以该契约为准。

## 自适应学习契约与治理

- [Learning Event v1 数据契约](contracts/learning-events-v1.md)：题目—目标映射、幂等事件、证据替代、重放、同意和删除。
- [Student Model v1 模型卡](model-cards/student-model-v1.md)：模型目的、输入输出、不确定性、冷启动、公平性、监控与回滚。
- [学生知识画像隐私影响评估](privacy/student-profile-impact-assessment.md)：处理目的、数据流、访问、风险、同意、删除和试点审批。
- [自适应学习试点实验协议](experiments/adaptive-pilot-protocol.md)：影子模式、对照设计、效果指标、安全中止和退出标准。
- [ADR-0002：自适应学习的证据、推荐与安全边界](adr/0002-adaptive-learning-safety-boundaries.md)。

## 架构与运营

- [架构](architecture.md)、[数据清单](data-inventory.md)。
- [ADR-0001：单体仓库](adr/0001-monorepo.md)。

`docs/superpowers/` 保存历史设计与执行材料，不是当前产品承诺；以 README、项目状态、路线图、实施计划、已接受 ADR、数据契约和运行中的 OpenAPI 为准。
