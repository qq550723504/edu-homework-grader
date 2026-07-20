# 试点上线检查表

- [ ] 使用学校受控 HTTPS OIDC 完成真实教师、学生登录/登出浏览器验收。
- [ ] 所有数据库、Keycloak 管理员、会话和 `AUDIT_HMAC_KEY` 均来自受控密钥系统，不使用示例默认值。
- [ ] 英语模型具有固定 `model_id`、revision、digest 与离线目录，Grader `/ready` 返回 `ready`。
- [ ] 验证处理器网络仅允许 `PROCESSOR_ALLOWED_HOSTS`。
- [ ] 完成 PostgreSQL 备份、隔离恢复、迁移升级和审计链校验演练。
- [ ] 导入真实名册并核验未成年人监护人同意；缺失/撤回同意必须拒绝处理。先运行 `python -m edu_grader_api.guardian_consent_integrity`，仅在确认结果后使用 `--execute` 为缺失记录建立 `pending` 状态。
- [ ] 运行完整 CI：Python、迁移、Compose、真实 Grader、Web 单测与浏览器 E2E。
- [ ] 审阅数据保留、删除、访问角色和事故响应流程，见 [数据清单](data-inventory.md)。
