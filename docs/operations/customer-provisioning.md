# 首批客户开通运行手册

该流程只绑定已经由学校 OIDC 身份服务创建的教师身份，不接收或保存教师密码，也不会输出学生激活码。重复执行同一配置会复用租户、教师、班级和学生记录。

## 开通顺序

1. 在学校 OIDC 中准备教师账号和负责开通的管理员账号，并取得两个账号的 `sub`。不要把密码或客户端 Secret 写入 CSV、工单或仓库。
2. 准备 UTF-8 花名册。必须包含以下列：

   `class_code,class_name,student_school_id,student_display_name,student_under_14,guardian_consent_status,guardian_consent_notice_version,guardian_consent_evidence_reference`

3. 将花名册作为一次性文件复制到 API 容器的临时目录，然后执行开通命令。`OIDC_TENANT_SLUG` 必须与目标租户一致；操作人 subject 必须对应该租户的管理员身份。

   ```bash
   export ROSTER_FILE=/secure/path/acme-roster.csv
   docker compose cp "$ROSTER_FILE" api:/tmp/customer-roster.csv
   docker compose exec -T api python -m edu_grader_api.cli.provision_customer \
     --tenant-slug "${OIDC_TENANT_SLUG:-pilot}" \
     --tenant-name "Acme School" \
     --operator-subject "<oidc-operator-sub>" \
     --teacher-subject "<oidc-teacher-sub>" \
     --teacher-name "Teacher Name" \
     --teacher-email teacher@example.edu \
     --roster-csv /tmp/customer-roster.csv
   docker compose exec -T api rm -f /tmp/customer-roster.csv
   ```

   输出只包含租户、教师、班级 ID 和导入人数。命令不会输出密码、OIDC Secret 或学生激活码。

4. 教师使用真实 HTTPS OIDC 登录后，在教师工作台选择未绑定学生并下载一次性激活码 CSV。激活码只在下载响应中出现一次，需通过受控线下渠道交付给学生。
5. 学生首次登录会消费激活码；七天内未使用的激活会由过期任务禁用。丢失或泄露时，教师重新签发新码，旧码会被撤销。

## 安全与回滚

- `--operator-subject` 和 `--teacher-subject` 必须来自配置的 OIDC 发行方；操作人必须是目标租户管理员，跨租户身份冲突会拒绝执行。CLI 不接受自定义 issuer 或不受信任的 tenant slug。
- 花名册解析失败不会写入数据；已存在记录只更新显示名称、班级名称和同意状态。
- 激活码不进入日志、数据库明文、浏览器存储、Linear 或 GitHub。
- 客户开通失败时，租户、用户、班级、花名册和审计写入会整体回滚；修正 OIDC 身份或花名册后可安全重跑。命令完成后立即删除容器内的临时 CSV；Kubernetes 场景应使用短生命周期 Job/Secret 挂载，不要给 API Pod 增加持久化花名册卷。
