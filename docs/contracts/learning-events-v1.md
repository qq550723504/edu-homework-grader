# Learning Event v1 数据契约

状态：Proposed  
版本：`learning-event-v1`  
适用阶段：学生知识画像与低风险自适应练习

## 1. 目的

Learning Event 是学生知识状态计算的不可变输入。它把作业、练习、复核、订正和教师改分等业务事实转换为可重放、可审计、可去重的学习证据。

本契约解决以下问题：

- 同一次作答在重试、异步任务或补偿流程中不能重复计入掌握度；
- 初始自动判分、教师复核和最终发布结果必须有明确优先级；
- 题目涉及多个课程目标时，证据需要按权重和角色拆分；
- 学生模型升级后必须能够从同一事件集重建状态；
- 删除、冻结、同意撤回和隐私请求必须能够阻止后续处理；
- 事件不能携带超出知识建模所需范围的个人信息。

Learning Event 不是分析日志，也不是前端埋点。它是业务数据库中的版本化事实记录。

## 2. 非目标

本契约不负责：

- 决定学生是否掌握某个目标；
- 直接选择下一道题；
- 保存完整浏览器行为轨迹；
- 保存模型输入向量或外部 Provider 响应；
- 替代 `GradingRun`、`ReviewDecision`、`GradePublication` 等原始业务记录；
- 修改正式成绩；
- 生成永久能力标签。

## 3. 核心实体

### 3.1 `item_objective_links`

将不可变的题目版本关联到不可变的课程目标 revision。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID | 主键 |
| `tenant_id` | UUID | 租户隔离 |
| `question_version_id` | UUID | 已发布或待发布题目版本 |
| `objective_revision_id` | UUID | 课程目标 revision |
| `relationship_type` | enum | `primary`、`secondary`、`prerequisite`、`context` |
| `evidence_weight` | decimal | 0 到 1；同一题的可计分目标权重之和不超过 1 |
| `evidence_role` | enum | `correctness`、`procedure`、`language_form`、`reading_content` 等 |
| `verified_by_user_id` | UUID | 教师或课程管理员 |
| `verified_at` | timestamp | 审核时间 |
| `version` | integer | 乐观锁版本 |

约束：

- `context` 关系不形成掌握度证据；
- 未审核映射不得进入学生模型；
- 已有 Learning Event 引用的映射不得原地修改；
- 修改映射必须创建新 revision，并只影响后续事件；
- 一题可以有多个 `primary`/`secondary` 目标，但需要说明权重和证据角色。

### 3.2 `learning_events`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID | 主键 |
| `event_key` | string | 全局幂等键 |
| `schema_version` | string | 固定为 `learning-event-v1` |
| `tenant_id` | UUID | 租户隔离 |
| `student_id` | UUID | 内部学生 UUID |
| `source_type` | enum | 原始业务对象类型 |
| `source_id` | UUID | 原始业务对象 ID |
| `question_version_id` | UUID | 题目版本 |
| `attempt_id` | UUID | 作答尝试，可空 |
| `attempt_answer_id` | UUID | 答案记录，可空 |
| `event_type` | enum | 事件类型 |
| `occurred_at` | timestamp | 业务事实发生时间 |
| `recorded_at` | timestamp | 事件写入时间 |
| `evidence_status` | enum | `eligible`、`provisional`、`excluded`、`superseded` |
| `score` | decimal | 最终或当前得分，可空 |
| `max_score` | decimal | 满分，可空 |
| `decision` | string | 判定结果，可空 |
| `response_time_ms` | integer | 可空；仅在可靠采集时使用 |
| `hint_count` | integer | 提示次数 |
| `attempt_number` | integer | 第几次作答 |
| `payload_json` | JSON | 最小必要结构化证据 |
| `supersedes_event_id` | UUID | 被替代事件，可空 |
| `audit_event_id` | UUID | 关联审计事件 |

`event_key` 建议形式：

```text
{tenant_id}:{source_type}:{source_id}:{event_type}:{source_version}
```

生产实现可以使用稳定哈希，但必须保证同一业务事实重复消费时得到相同键。

## 4. 事件类型

首期支持：

| 事件类型 | 触发点 | 默认证据状态 |
| --- | --- | --- |
| `answer_graded` | 自动批改完成 | 取决于题型与置信度 |
| `review_resolved` | 教师确认或改分 | `eligible` |
| `grade_published` | 成绩正式发布 | `eligible` |
| `correction_graded` | 订正批改完成 | 取决于最终确认 |
| `correction_published` | 订正结果发布 | `eligible` |
| `hint_requested` | 学生请求提示 | `eligible`，但不是正确性证据 |
| `practice_abandoned` | 练习中止 | `eligible`，仅用于体验和安全策略 |
| `teacher_evidence_override` | 教师覆盖知识证据 | `eligible` |
| `privacy_processing_blocked` | 隐私请求或同意状态阻断 | `excluded` |

首期不将以下事件作为强知识证据：

- 页面浏览；
- 鼠标点击；
- 仅打开题目；
- 网络错误；
- 未发布的主观题系统建议；
- `grader-unavailable`；
- `needs_review` 且教师尚未处理；
- 未完成的草稿答案。

## 5. 证据优先级与替代规则

同一 `AttemptAnswer` 可能产生多条事件。状态计算必须遵循：

1. 教师最终确认的 `review_resolved`；
2. 已发布订正结果；
3. 已发布正式成绩；
4. 高置信度确定性自动判分；
5. 未确认的系统建议，仅作 provisional 或排除。

教师改分时：

```text
旧 answer_graded
→ evidence_status = superseded
→ 新 review_resolved 引用 supersedes_event_id
```

不能删除旧事件，也不能直接修改旧事件的分数。状态计算读取当前有效事件视图。

## 6. 事件载荷

### 6.1 数学确定性题示例

```json
{
  "schema_version": "learning-event-v1",
  "event_type": "answer_graded",
  "source_type": "grading_run",
  "evidence_status": "eligible",
  "decision": "auto_accepted",
  "score": 4,
  "max_score": 4,
  "attempt_number": 1,
  "payload": {
    "question_type": "M2",
    "policy_version": "2",
    "grader_version": "grader-0.1.0",
    "criteria": [
      {
        "code": "algebraic_equivalence",
        "passed": true,
        "score": 4,
        "max_score": 4
      }
    ],
    "hint_count": 0
  }
}
```

### 6.2 教师改分示例

```json
{
  "schema_version": "learning-event-v1",
  "event_type": "review_resolved",
  "source_type": "review_decision",
  "evidence_status": "eligible",
  "decision": "adjust_score",
  "score": 3,
  "max_score": 4,
  "payload": {
    "original_score": 4,
    "final_score": 3,
    "reason_code": "required_form_missing",
    "teacher_comment_present": true
  }
}
```

事件载荷不得保存：

- 学生姓名、邮箱、手机号或学校编号；
- Access/Refresh Token；
- 完整系统 Prompt；
- 外部模型凭据；
- 无必要的完整原始答案；
- 浏览器 Cookie；
- 自由文本教师备注全文，除非业务与合规明确要求。

完整答案和评分证据仍保存在原始业务表，Learning Event 只保存模型所需的最小结构化摘要和引用。

## 7. 题目—课程目标证据拆分

状态计算前将一个事件拆成零到多个 `objective_evidence`：

```text
Learning Event
+ item_objective_links revision
+ criterion/signals
→ objective evidence rows
```

建议字段：

| 字段 | 说明 |
| --- | --- |
| `learning_event_id` | 来源事件 |
| `objective_revision_id` | 目标 revision |
| `mapping_revision_id` | 映射 revision |
| `evidence_value` | -1 到 1 的标准化证据 |
| `evidence_weight` | 映射权重、题目质量和事件可信度组合 |
| `evidence_kind` | 正确、部分正确、错误模式、提示依赖等 |
| `explanation_code` | 稳定解释码 |
| `model_eligible` | 是否进入当前学生模型 |

示例：

```text
题目：3(x - 2) + 4x

primary：去括号，weight=0.6
secondary：合并同类项，weight=0.4
prerequisite：整数符号运算，weight=0（除非出现明确错误信号）
```

如果学生在展开步骤正确、合并步骤错误，则不能把整题零分平均分配给两个目标。必须利用评分 criterion、步骤信号或教师确认拆分证据。

## 8. 排序、迟到和重放

事件按 `occurred_at` 解释业务顺序，按 `recorded_at` 追踪写入延迟。

实现必须支持：

- 事件迟到；
- 教师数天后改分；
- 订正结果晚于正式成绩；
- 模型版本升级后全量重放；
- 指定学生、班级、课程目标或时间窗口的局部重建。

状态重建使用稳定水位：

```text
max(recorded_at, id)
```

或等价的单调游标。运行过程中产生的新事件进入下一批，不与当前重放混合。

## 9. 事务与投递

推荐使用事务 Outbox：

```text
业务事务写入 GradePublication/ReviewDecision
+ 同事务写入 learning_event_outbox
→ 后台 Worker 幂等创建 Learning Event
```

不建议在 HTTP 请求完成后以“尽力而为”方式异步发送事件，否则会出现正式成绩已发布但知识状态永远缺失。

最低要求：

- Outbox 与业务记录同事务；
- 消费至少一次；
- `event_key` 去重；
- 重试有界且可观测；
- Dead Letter 只保存引用和错误，不复制敏感答案；
- 事件积压超过阈值触发告警。

## 10. 隐私、同意与删除

Learning Event 属于学生教育画像的基础数据。

处理前必须满足：

- 学生处理权限允许；
- 监护人同意状态允许；
- 不存在阻断中的隐私请求；
- 当前用途在已声明范围内。

同意撤回或处理限制生效后：

- 停止创建新的模型事件；
- 停止状态更新和推荐；
- 不删除依法或业务必须保留的原始成绩记录；
- 按数据保留政策删除、隔离或去标识化派生事件和状态；
- 记录不含学生敏感内容的审计事实。

删除流程必须覆盖：

```text
Learning Event
objective evidence
student objective state
state snapshots
misconception state
recommendation session
experiment assignment
```

## 11. 版本兼容

- 生产消费者必须显式声明支持的 `schema_version`；
- 新增可选字段可以保持 v1；
- 改变字段语义、幂等规则或证据优先级需要新版本；
- v1 事件不可在原地迁移成不同语义；
- 新模型可读取旧事件，但必须记录兼容转换器版本。

## 12. 验收测试

至少覆盖：

- 同一业务事实重复投递只产生一条事件；
- 自动判分后教师改分，旧证据被 supersede；
- 订正结果形成独立事件且优先于原错误证据；
- `needs_review` 不形成强证据；
- Grader 依赖故障不改变掌握状态；
- 一题多目标按 criterion 正确拆分；
- 迟到事件触发受影响状态重算；
- 跨租户读取和写入被拒绝；
- 同意撤回后不再创建事件；
- 删除请求覆盖全部派生对象；
- 从空状态全量重放得到稳定、可重复结果。

## 13. Definition of Done

本契约进入 `Accepted` 前必须满足：

1. 数据模型、Alembic 迁移和 OpenAPI/内部事件 Schema 一致；
2. 事件由事务 Outbox 或等价可靠机制创建；
3. 幂等、替代、迟到和重放测试通过；
4. 题目—目标映射经过审核且可版本化；
5. 隐私删除、同意撤回和跨租户测试通过；
6. 学生模型可以仅依赖事件和映射重建状态；
7. 普通日志、告警和 Dead Letter 不包含完整学生答案或身份信息。