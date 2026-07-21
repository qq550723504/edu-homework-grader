# 数据清单与保存规则

本清单是试点阶段的工程控制基线；学校的法定保存要求或有效保全措施优先。任何新增字段、表、出站处理器或保留策略，都必须先更新本文件。

| 记录组 | 表 | 用途 | 敏感等级 | 允许访问角色 | 处理器 | 默认保存期限 | 删除触发条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 身份与花名册 | `users`、`classes`、`class_teachers`、`enrollments` | 建立租户成员、班级和任课关系 | restricted | 租户管理员；对应班级教师 | Core API、Keycloak | 在读期间加 2 年 | 经过保全检查的已验证删除请求 |
| 监护人同意状态 | `student_guardian_consents` | 保存学校核验的未满 14 周岁学生同意状态与不透明凭证引用 | restricted | 租户管理员；事件响应人员 | Core API | 在读期间加 2 年 | 经过保全检查的已验证删除请求 |
| 删除请求与保全状态 | `privacy_requests` | 记录学校管理员登记的删除请求、保全状态与清理资格时间 | restricted | 租户管理员；事件响应人员 | Core API | 请求完成后按适用学校政策保留 | 适用保存期届满 |
| 学生作答与成绩 | `student_attempts`、`attempt_answers`、`grading_runs`、`grading_signals`、`grade_publications` | 提交、评分、反馈和发布 | restricted | 本人；对应班级教师；租户管理员 | Core API、Grader | 成绩发布后 2 年 | 保存期届满或批准的删除请求 |
| 草稿作答 | 草稿状态的 `student_attempts`、`attempt_answers` | 自动保存和断网恢复 | restricted | 本人；对应班级教师 | Core API | 提交或放弃后 30 天 | 定时清理 |
| 申诉与订正 | `review_appeals`、`correction_attempts`、`review_decisions`、`review_tasks` | 人工复核、订正和理由留存 | restricted | 本人；对应班级教师；租户管理员 | Core API | 决定后 2 年 | 保存期届满或批准的删除请求 |
| 学习画像证据与状态 | `learning_events`、`objective_evidence`、`student_objective_states`、`student_model_snapshots`、`misconception_states` | 版本化学习证据、目标状态、可解释性与模型重放 | restricted | 本人；对应班级教师；租户管理员；受控模型运维 | Core API、Student Model | 试点结束或最后一次有效学习活动后 12 个月，以较早者为准 | 经保全检查的已验证删除请求、同意撤回后的派生数据清理、试点结束 |
| 推荐、实验与内容需求 | `recommendation_sessions`、`experiment_assignments`、`content_demands` | 教师确认式推荐、受控试点评估与聚合题库缺口 | restricted | 本人；对应班级教师；租户管理员；受控实验分析人员 | Core API、Student Model、AI Generator（仅满足聚合阈值的 content demand） | 推荐会话 90 天；实验分组和 content demand 至试点结束后 12 个月 | 经保全检查的已验证删除请求、退出试点、试点结束或保存期届满 |
| 安全审计 | `audit_logs`、`audit_chain_heads` | 安全调查、受控操作留痕和链完整性校验 | confidential | 租户管理员；事件响应人员 | Core API、Keycloak 事件存储 | 3 年 | 在独立链头导出完成后的保存期届满 |

## 身份与最小化规则

- 学生业务关联只使用 `users.id` 内部 UUID；作答、评分和复核处理器不接收姓名、学校编号、OIDC subject、班级或租户 slug。
- `school_id` 只用于受信任花名册和首次 OIDC 绑定。学生不要求、不保存手机号；学生数据库约束禁止保存工作邮箱。
- 花名册仅保存 `student_under_14`、同意状态、通知版本和不透明凭证引用；不得导入出生日期、监护人姓名、联系方式、身份证明、同意书正文或签名扫描件。
- Web OIDC 客户端只请求登录、角色、受众和 `school_id` 所必需的 scope，不请求 `profile` 或 `email`。
- Grader 仅接收题型、策略版本、题目规则和答案。英语语法服务与语义模型也属于受控处理器，必须遵守处理器 allowlist 和最小字段契约。

## 删除限制

当法律、学校制度或安全事件保全义务要求继续保存时，记录进入删除待处理状态；此时只允许存储和必要安全保护，不能继续用于评分、展示、分析或训练。

受控清理会删除学生作答、评分、申诉、回执、选课和监护人同意记录，并移除 OIDC 绑定。为保持不可变审计账本的外键完整性，`users` 仅保留去标识化的内部 UUID 壳，不得保留原姓名、学校编号或 OIDC 身份。
