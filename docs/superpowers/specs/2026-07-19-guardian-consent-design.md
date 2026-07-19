# 未满十四周岁学生监护人同意设计

## 目标

为试点建立可核验、可撤回、可审计的未满十四周岁学生监护人同意机制。学校管理员导入线下已核验状态与凭证编号；平台不创建家长账号，也不收集监护人联系方式。

## 范围

本切片实现：

- 花名册导入未满十四周岁标记、同意状态和学校凭证编号。
- 学生 UUID 对应的同意记录、状态变更和撤回。
- 未获同意或已撤回学生的登录、作答、提交、评分和外部处理门禁。
- 管理员同意/撤回操作的签名审计事件。

本切片不实现家长门户、短信/邮箱验证、出生日期采集、数据删除工单或对外发送同意通知。

## 数据最小化

新增 `student_guardian_consents`，只保存：

- `student_id`：内部学生 UUID，唯一。
- `requires_guardian_consent`：学校确认的未满十四周岁布尔标记；不保存出生日期。
- `status`：`not_required`、`pending`、`granted` 或 `withdrawn`。
- `notice_version`：学校使用的同意告知版本。
- `evidence_reference`：学校侧凭证编号，限制为不含姓名、电话、邮箱或证件号的受控标识。
- `verified_by_user_id`、`granted_at`、`withdrawn_at`、`withdrawal_reason`、`version`。

平台不得保存监护人姓名、联系方式、身份证件、签名扫描件或同意书正文。凭证原件由学校受控系统保管。

## 状态与门禁

```text
not_required ──(学校标记未满十四周岁)──> pending
pending ──(管理员登记已核验同意)──> granted
granted ──(学校确认撤回)──> withdrawn
withdrawn ──(重新取得并核验同意)──> granted
```

只有 `not_required` 或 `granted` 的学生可以完成需要个人信息处理的新活动：登录到学生业务界面、读取新作业、保存答案、提交、触发评分、向 Grader 或任何外部处理器发送内容，以及创建申诉。`pending` 与 `withdrawn` 返回统一的 403 `guardian consent required`，不暴露学校凭证或年龄判断。

撤回不会物理删除既有作答、成绩、申诉或审计记录。记录进入只读保留状态，只可用于法定保存和安全保护；后续的数据主体请求切片决定删除、导出和例外保全流程。

## 导入与管理接口

学生花名册 CSV 增加以下列：

- `student_under_14`：`true` 或 `false`。
- `guardian_consent_status`：未满十四周岁学生只能为 `pending` 或 `granted`；其他学生必须为 `not_required`。
- `guardian_consent_notice_version`：`granted` 时必填。
- `guardian_consent_evidence_reference`：`granted` 时必填，采用学校生成的无个人信息编号。

导入在同一事务内写入学生、班级关系和同意状态。非法状态组合、超过长度、带控制字符或疑似联系方式/证件号的凭证编号会使整批回滚。

管理员接口用于针对已存在学生登记同意或撤回。操作采用乐观锁 `version`，并要求撤回理由；重新取得同意必须提供新告知版本和凭证编号。

## 审计与错误处理

状态导入、同意登记和撤回使用已有签名哈希账本，事件为 `guardian_consent.granted`、`guardian_consent.withdrawn` 和 `guardian_consent.imported`。审计 metadata 只保存学生 UUID、状态、告知版本、凭证引用和记录版本，不记录学生姓名、学校编号、答案或监护人信息。

同意记录写入或审计失败时，业务变更必须回滚。门禁查询故障时默认拒绝学生处理活动，不能降级为允许。

## 测试

- 模型与迁移测试覆盖唯一约束、状态组合和乐观锁。
- CSV 测试覆盖合法导入、非法组合整批回滚及凭证脱敏验证。
- API 测试覆盖 `pending` 和 `withdrawn` 学生不能读取/保存/提交/申诉，`granted` 学生不受影响。
- 管理员操作测试覆盖登记、撤回、重新同意、审计事件和并发冲突。
- Grader 客户端测试证明门禁阻断发生在任何出站评分调用之前。

## 验收映射

本切片满足 Issue #8 的“定义十四岁以下学生的监护人同意和撤回流程”验收项：学校负责身份和同意原件核验，平台保存最小状态与凭证引用、强制停止撤回后的新处理、并保留可验证审计证据。
