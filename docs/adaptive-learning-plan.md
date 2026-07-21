# 学生知识画像与自适应练习实施计划

状态：Proposed  
更新日期：2026-07-21  
阶段：第三阶段  
前置能力：课程目标 #37、题目验证 #40、质量评估 #42、AI 治理 #43，以及稳定的题库与多题作业流程

## 1. 目标

在现有作业、题库、批改、教师复核和 K–13 课程目标体系之上，建立可解释的学生知识状态与低风险自适应练习能力。

目标链路：

```text
学生完成作业或练习
→ 形成版本化 Learning Event
→ 按题目—课程目标映射拆分证据
→ 更新知识点掌握度、置信度和错误模式
→ 识别薄弱点、先修缺口、遗忘风险和证据不足
→ 选择下一学习目标与目标难度
→ 从已经验证、教师审核并发布的题库选题
→ 学生练习并获得反馈
→ 教师查看解释、纠正画像并评估学习增益
```

本阶段不把学生归纳为单一“能力分”，也不允许系统把短期表现固化成永久标签。核心产物是：

- 每个课程目标上的当前知识状态；
- 支撑状态的可回放证据；
- 明确的不确定性；
- 可解释的下一步练习建议；
- 教师可查看、修正、暂停和覆盖的推荐决策。

## 2. 产品原则

1. **知识点状态，不是人格或固定能力标签。** 页面使用“证据不足、发展中、待巩固、稳定掌握、建议复习”等可改变状态。
2. **最终教学证据优先。** 教师确认分数、复核结果和订正表现优先于初始自动判分。
3. **低证据必须明确不确定。** 不用默认 50% 伪装成已经估计的掌握度。
4. **自适应只使用已审核题目。** 学生点击下一题时不得把未经验证、未经教师审核的 AI 新题直接展示给学生。
5. **推荐与正式成绩分离。** 首期自适应练习不进入正式考试、分班、处罚或高利害评价。
6. **教师拥有控制权。** 教师可以限制课程范围、难度、练习时长，纠正错误画像，或关闭某学生/班级的自动推荐。
7. **保留探索机会。** 系统不能因为早期错误只给低难度题，必须安排跨难度校准和课程进度题。
8. **可解释、可回放、可版本化。** 每次状态更新和推荐保存模型版本、规则版本、证据和原因。
9. **个人画像不进入 AI 出题 Provider。** Generator 只接收去标识化的题目库存需求，不接收学生身份、答案或知识画像。
10. **以学习结果而非点击率验收。** 核心效果是学习增益、延迟保持、迁移和教师认可，而不是做题量最大化。

## 3. 与现有平台和 AI 出题的关系

现有系统负责：

```text
QuestionVersion
→ 已验证评分策略
→ 多题作业
→ 学生答案
→ GradingRun
→ 教师复核
→ 成绩发布与订正
```

第二阶段 AI 出题负责：

```text
课程目标与题库缺口
→ AI 候选题
→ 独立验证
→ 教师审核
→ 正式题目草稿
→ 现有发布门禁
```

第三阶段自适应学习负责：

```text
已确认学习证据
→ 学生知识状态
→ 目标与难度选择
→ 从已发布题库选题
→ 发现库存缺口
→ 向 AI 出题系统提交去标识化补题需求
```

关键边界：

- 自适应引擎不调用外部模型现场生成学生下一题；
- AI Generator 不读取个人知识画像；
- 题库缺口请求只包含 curriculum profile、objective revision、题型、难度和错误模式标签；
- 新生成题必须经过 #40 验证、教师审核和现有发布门禁，之后才能进入自适应题池。

## 4. 首期范围

### 4.1 学生范围

首个试点建议限制为：

- G4–G9 数学：M1、M2；
- G4–G9 英语：E1、E2；
- E3、E4 只在教师最终确认后形成低权重或教师确认权重的知识证据；
- 只用于课后练习、订正和低风险诊断；
- K 阶段和 G13 不进入首个自适应试点。

### 4.2 首期交付

- 题目—课程目标映射；
- 版本化学习事件；
- 可解释掌握度和置信度；
- 常见错误模式；
- 学生个人知识地图；
- 教师班级热力图和干预建议；
- 教师确认式推荐助手；
- 低风险自适应练习；
- 题库库存覆盖矩阵；
- 学习增益、保持度和公平性评估。

### 4.3 非目标

- 根据人口属性、家庭背景、学校或地区推断能力；
- 自动分班、升留级、处罚、招生或高风险考试决策；
- 用单一总分替代课程目标状态；
- 未经教师确认自动修改正式成绩；
- 让 AI 出题 Provider 接收学生历史作答；
- 首期使用深度知识追踪作为唯一生产模型；
- 基于少量作答给出永久“弱项”标签；
- 通过全班排名刺激低年级学生；
- 只追求预测下一题对错而不验证学习增益。

## 5. 目标架构

```text
Core API
├─ Question / QuestionVersion / Curriculum Objective Revision
├─ Attempts / GradingRun / ReviewDecision / Correction
├─ Learning Event Projector
├─ Student Model Service
│  ├─ evidence normalization
│  ├─ mastery update
│  ├─ uncertainty and forgetting
│  └─ misconception state
├─ Adaptive Recommendation Service
│  ├─ objective selection
│  ├─ difficulty policy
│  ├─ item candidate filter
│  ├─ exposure/diversity control
│  └─ explanation generation
├─ Inventory Coverage Service
└─ Audit / Privacy / Model Registry
        │
        ├───────────────┐
        ▼               ▼
Student Web         Teacher Web
├─ knowledge map    ├─ class heatmap
├─ review due       ├─ evidence drill-down
├─ practice plan    ├─ intervention suggestions
└─ adaptive session └─ override and approval
        │
        ▼
Published Question Pool
        │ insufficient inventory
        ▼
De-identified Content Demand
        │
        ▼
AI Authoring Pipeline
→ verification
→ teacher review
→ published inventory
```

首期可以把 Student Model 与 Recommendation 作为 Core API 内的独立模块实现；当更新量、回放和离线评估规模增长后，再拆成独立服务。无论部署形态如何，领域协议和版本记录必须独立。

## 6. 核心领域模型

### 6.1 题目—课程目标映射

`item_objective_links`

```text
id
question_version_id
curriculum_objective_revision_id
relationship_type
weight
evidence_role
mapping_version
created_by_user_id
verified_by_user_id
created_at
```

`relationship_type`：

- `primary`：题目主要测量目标；
- `secondary`：次要目标；
- `prerequisite`：解题需要但不是主要评测目标；
- `context`：只用于语境，不更新掌握度。

约束：

- 同一道题的 primary/secondary 权重之和必须可解释并通过校验；
- 自动生成的映射必须由教师或课程管理员确认；
- 已发布题目的映射修订必须版本化，不能静默改变历史学习状态；
- `prerequisite` 错误不能简单等同为 primary 目标未掌握。

### 6.2 学习事件

`learning_events`

```text
id
tenant_id
student_id
source_type
source_id
attempt_id
attempt_answer_id
question_version_id
event_type
score
max_score
decision
response_time_ms
hint_count
attempt_number
is_final_evidence
evidence_payload_json
occurred_at
recorded_at
```

建议事件类型：

```text
answer_saved
answer_submitted
auto_grade_created
teacher_review_completed
score_adjusted
result_published
hint_requested
correction_submitted
correction_published
answer_abandoned
```

事件是 append-only。教师改分或复核不覆盖旧事件，而是产生新的最终证据事件。

### 6.3 学生课程目标状态

`student_objective_states`

```text
tenant_id
student_id
curriculum_objective_revision_id
mastery_probability
confidence
evidence_count
independent_success_count
supported_success_count
failure_count
last_practiced_at
last_success_at
forgetting_risk
difficulty_band
state_label
model_version
state_version
updated_at
```

建议人类可读状态：

```text
insufficient_evidence
needs_support
developing
mastered
stable_mastery
review_due
```

### 6.4 状态历史与回放

`student_objective_state_snapshots`

```text
id
student_id
objective_revision_id
previous_state_json
new_state_json
trigger_event_id
model_version
explanation_json
created_at
```

每次状态变化保存：

- 使用了哪些证据；
- 每个证据的权重；
- 更新前后数值；
- 状态标签变化原因；
- 模型和参数版本。

### 6.5 常见错误状态

`student_misconception_states`

```text
student_id
objective_revision_id
misconception_code
confidence
evidence_count
first_seen_at
last_seen_at
resolved_at
model_version
```

数学示例：

```text
DISTRIBUTION_MISSED_SECOND_TERM
NEGATIVE_SIGN_DROPPED
LIKE_TERMS_WRONG_VARIABLE
EQUATION_OPERATION_ONE_SIDE_ONLY
```

英语示例：

```text
PAST_TENSE_MISUSE
SUBJECT_VERB_AGREEMENT
ARTICLE_OMISSION
PLURAL_FORM_ERROR
READING_CAUSE_EFFECT_MISSED
```

错误模式必须由评分证据或教师确认支持，不能只由文本生成模型猜测。

### 6.6 题目校准与曝光

`item_calibration_stats`

```text
question_version_id
population_scope
attempt_count
independent_correct_rate
hinted_correct_rate
estimated_difficulty
discrimination_estimate
median_response_time_ms
exposure_count
last_calibrated_at
calibration_version
```

首期只将这些值作为可解释辅助，不在样本不足时显示精确难度结论。

### 6.7 推荐与练习会话

`recommendation_sessions`

```text
id
tenant_id
student_id
scope_json
policy_version
student_model_version
status
created_at
completed_at
```

`recommendation_items`

```text
id
recommendation_session_id
question_version_id
objective_revision_id
strategy_bucket
target_difficulty
rank
reason_json
shown_at
answered_at
outcome_event_id
```

`practice_plans`

```text
id
student_id
created_by
approved_by_teacher_id
objective_distribution_json
question_count
time_limit_minutes
status
expires_at
```

## 7. 证据规则

### 7.1 证据优先级

从高到低：

1. 教师最终确认的评分和错误原因；
2. 已发布订正结果；
3. 高置信度确定性题型评分；
4. 教师确认后的 E3/E4 评分点；
5. 使用提示后的正确答案；
6. 同一题多次尝试后的正确答案；
7. 未复核或依赖异常的自动建议。

`needs_review`、`grader-unavailable` 和未发布主观题不得作为强掌握证据。

### 7.2 证据特征

每条证据至少考虑：

- 正确、部分正确或错误；
- 目标知识点权重；
- 题目难度与样本置信度；
- 是否独立完成；
- 提示次数；
- 尝试次数；
- 响应时间是否异常；
- 是否属于订正；
- 是否由教师改分；
- 距离当前时间；
- 是否重复曝光同一道题。

### 7.3 证据防抖

- 一道题不得造成掌握度从“需要支持”直接跳到“稳定掌握”；
- 同一道题的重复尝试降低独立证据权重；
- 极短或极长响应时间只形成 warning，不直接判断作弊或能力；
- 不同题目、不同情境和不同难度的证据提高置信度；
- 低证据数量时保持 `insufficient_evidence`。

## 8. 学生模型演进

### Stage A：可解释规则与时间衰减

首期生产模型：

```text
prior
+ weighted independent successes
+ weighted supported successes
- weighted target errors
- forgetting decay
→ bounded mastery estimate and confidence
```

要求：

- 参数按 curriculum profile、学科和年级版本化；
- 能逐项解释每次更新；
- 支持离线回放；
- 教师可覆盖状态并记录原因；
- 不使用人口属性。

### Stage B：BKT/PFA 风格模型

在事件量和标签质量达到门槛后：

- 每个课程目标估计先验掌握、猜测、失误和学习转移；
- PFA 风格特征区分历史成功和失败次数；
- 与 Stage A 做离线和影子对比；
- 未证明改进前不切换默认模型。

### Stage C：IRT 与知识追踪组合

用于题目难度、区分度和学生状态联合校准：

- 题目样本不足时不使用不稳定参数；
- 按 profile/年级分层估计；
- 题目难度不作为学生固定能力标签；
- 所有参数带版本、样本量和置信区间。

### Stage D：复杂序列模型

只有同时满足以下条件才进入实验：

- 大规模真实交互数据；
- 稳定的课程目标和题目映射；
- 独立测试集和时间切分；
- 公平性和可解释性评估；
- 相比简单模型改善学习结果，而不只是下一题预测准确率；
- 可以安全回滚。

复杂模型不得直接替代教师判断或作为高利害决策依据。

## 9. 自适应推荐策略

### 9.1 目标选择桶

首期建议可配置起始比例：

| 策略桶 | 初始比例 | 目的 |
| --- | ---: | --- |
| 当前薄弱目标 | 40% | 针对性巩固 |
| 先修知识缺口 | 20% | 修复根因 |
| 已掌握但需要复习 | 15% | 降低遗忘 |
| 当前教学进度 | 15% | 保证课程覆盖 |
| 探索与校准 | 10% | 防止错误闭环和机会不足 |

这些比例是试点参数，不作为不可修改的教育规律硬编码。

### 9.2 难度带

候选题可分为：

- 信心恢复：目标正确率约 80%–90%；
- 常规学习：目标正确率约 60%–80%；
- 挑战迁移：目标正确率约 40%–60%。

在题目校准证据不足时，使用课程规则和教师标注，不伪造精确正确率。

### 9.3 候选题硬约束

候选题必须：

- curriculum profile 与 objective revision 匹配；
- 属于教师允许的课程范围；
- 已发布并通过题目验证门禁；
- 题型适合当前设备和会话；
- 不含未确认 warning 或 blocked 状态；
- 未达到个人和全局曝光上限；
- 近期没有重复出现；
- 难度位于允许区间；
- 不泄露标准答案或评分规则。

### 9.4 多样性与连续失败控制

- 限制同一知识点连续题数；
- 限制同一题型和表面模板连续出现；
- 连续错误达到阈值时降低难度、插入先修题或暂停并提示教师；
- 连续正确后逐步提高难度，而不是一次跳级；
- 每个会话保留课程进度题和探索题；
- 学生可暂停或退出，不使用无限练习循环。

### 9.5 推荐解释

每道题至少保存和可展示：

```json
{
  "objective": "去括号",
  "strategy_bucket": "weak_objective",
  "reason": "最近三道含括号前负号的题出现两次符号错误",
  "target_difficulty": "standard",
  "supporting_events": 3,
  "policy_version": "adaptive-policy-v1"
}
```

学生端使用简短、非标签化语言；教师端可以查看完整证据。

## 10. 题库库存与 AI 补题

建立覆盖矩阵：

```text
curriculum objective revision
× difficulty band
× question type
× misconception code
× language
× accessibility/device constraints
```

库存状态建议：

```text
sufficient
low
critical
unavailable
```

库存不足时创建 `content_demand_requests`：

```text
id
profile_id
objective_revision_id
question_type
difficulty_band
misconception_code
requested_count
reason
priority
status
```

请求不包含：

- student_id；
- 班级；
- 学号；
- 学生原始答案；
- 个人掌握度；
- 访问令牌。

AI 出题系统生成候选题后，仍需验证、教师审核和发布。库存补充完成前，推荐系统使用相邻已审核题目或提示教师库存不足，不能现场绕过门禁。

## 11. 核心 API

### 11.1 学生知识状态

```http
GET /v1/student/knowledge-map
GET /v1/student/objectives/{objective_revision_id}
GET /v1/student/review-due
```

### 11.2 教师视图

```http
GET  /v1/teacher/classes/{class_id}/knowledge-map
GET  /v1/teacher/students/{student_id}/objective-states
GET  /v1/teacher/students/{student_id}/recommendation-evidence
POST /v1/teacher/students/{student_id}/objective-overrides
POST /v1/teacher/practice-plans
```

### 11.3 自适应练习

```http
POST /v1/student/adaptive-sessions
GET  /v1/student/adaptive-sessions/{session_id}
POST /v1/student/adaptive-sessions/{session_id}/next
POST /v1/student/adaptive-sessions/{session_id}/complete
```

`next` 必须幂等，重复请求返回同一道已分配题，避免网络重试改变推荐。

### 11.4 管理与评估

```http
POST /v1/admin/student-models/replay
GET  /v1/admin/student-models/evaluations
GET  /v1/admin/content-inventory/coverage
POST /v1/admin/content-demand-requests
```

## 12. 学生端

### 12.1 个人知识地图

展示：

- 本周新掌握目标；
- 发展中的目标；
- 建议复习；
- 证据不足；
- 最近发现的具体易错模式；
- 下一步练习计划。

示例：

```text
去括号
状态：发展中
证据：最近 8 题中 5 题独立完成
表现：正数括号基本稳定；括号前为负号时容易遗漏符号变化
下一步：完成 3 道负号去括号练习
```

不展示：

- 智商式能力值；
- 永久“弱学生”标签；
- 缺少证据却过度精确的百分比；
- 默认全班排名；
- 基于人口属性的比较。

### 12.2 自适应练习会话

- 显示本次目标、预计题数和预计时长；
- 允许暂停和继续；
- 每题提供当前系统已有反馈；
- 连续失败时提供提示、降低难度或建议教师帮助；
- 会话结束显示知识点层面的进展，不只显示总分；
- 不把探索题错误直接描述为“退步”。

## 13. 教师端

### 13.1 班级热力图

按课程目标展示：

```text
稳定掌握
发展中
需要支持
建议复习
证据不足
```

教师可以查看：

- 每个状态的人数；
- 支撑证据覆盖；
- 共同错误模式；
- 最近练习时间；
- 推荐后学习结果；
- 证据不足或异常变化的学生。

### 13.2 学生详情

- 状态变化时间线；
- 关键证据；
- 题目难度和提示使用；
- 常见错误；
- 当前推荐策略；
- 教师覆盖、冻结或重置入口；
- 覆盖原因与审计记录。

### 13.3 教师推荐助手

在自动推荐前先交付：

```text
建议给学生 A：
- 去括号基础题 2 道
- 负号专项题 3 道
- 分配律复习题 1 道
```

教师可：

- 接受；
- 修改题数和范围；
- 删除某目标；
- 固定难度；
- 选择具体题目；
- 拒绝并记录原因。

教师处理结果形成策略评估数据。

## 14. 冷启动

新学生没有历史证据时：

1. 使用课程 profile、年级和教师教学进度作为范围先验；
2. 教师指定起始单元；
3. 安排 8–15 题低压力诊断；
4. 抽样先修知识；
5. 前几次会话提高探索比例；
6. 达到最低跨题证据量后才显示掌握结论。

冷启动页面显示：

```text
证据不足
正在了解你的学习情况
```

不得显示伪精确的默认掌握百分比。

## 15. 隐私、安全与公平性

### 15.1 数据边界

- 学生知识状态属于敏感教育画像；
- 只用于教学反馈和低风险练习；
- 默认不对家长、其他学生或无关教师开放；
- 外部 Generator/模型不得接收个人画像；
- 导出受权限、目的和审计控制；
- 删除学生数据时同步删除或去标识化状态、快照和推荐记录。

### 15.2 人工解释与救济

- 学生和教师可以查看主要判断依据；
- 教师可以更正知识状态和错误模式；
- 学生可以对明显错误反馈申请教师查看；
- 模型不得直接决定正式成绩、分班或处罚；
- 每次覆盖和修正保留审计。

### 15.3 公平性控制

不得使用以下字段作为能力特征：

- 性别；
- 家庭收入；
- 民族；
- 地区；
- 学校声誉；
- 家长职业；
- 设备价格；
- 其他非学习证据属性。

评估必须比较不同群体获得的：

- 题目难度；
- 挑战题机会；
- 课程目标覆盖；
- 提示和干预机会；
- 连续失败率；
- 教师覆盖率。

发现显著差异时暂停策略扩展并调查原因。

### 15.4 防止自我强化

- 保留探索题比例；
- 定期给跨难度校准题；
- 不因一次错误永久降低状态；
- 记录未被展示的候选题和过滤原因；
- 教师可关闭个性化并恢复课程顺序；
- 模型升级前离线回放历史事件；
- 推荐策略必须能回滚。

## 16. 评估指标

### 16.1 模型质量

| 指标 | 说明 |
| --- | --- |
| 状态校准误差 | 预测掌握与后续独立表现是否一致 |
| 证据覆盖率 | 有足够跨题证据的目标占比 |
| 状态稳定性 | 单题是否导致不合理跳变 |
| 教师纠正率 | 教师认为画像错误的比例 |
| 错误模式准确率 | 诊断是否被教师确认 |

### 16.2 教学效果

| 指标 | 说明 |
| --- | --- |
| 前测—后测提升 | 同一目标上的学习增益 |
| 延迟保持 | 一周或更长时间后的保持表现 |
| 迁移表现 | 新情境或综合题上的表现 |
| 订正后独立成功 | 不依赖原题记忆的再次成功 |
| 达标时间 | 达到稳定掌握所需练习量和时间 |

### 16.3 推荐质量

| 指标 | 说明 |
| --- | --- |
| 教师接受率 | 推荐计划被直接接受的比例 |
| 教师修改率 | 教师调整目标、题数或难度的比例 |
| 连续失败率 | 会话中连续错误达到阈值的比例 |
| 跳过/放弃率 | 学生未完成推荐会话的比例 |
| 重复曝光率 | 近期重复题目或近似模板比例 |
| 课程覆盖偏差 | 推荐是否偏离教师教学进度 |

### 16.4 公平性与机会

- 难度分布差异；
- 挑战题机会差异；
- 推荐时长和题量差异；
- 证据不足状态持续时间；
- 教师干预机会；
- 各群体学习增益。

### 16.5 系统指标

- 状态更新延迟；
- `next` 推荐 P95；
- 事件投影积压；
- 回放时间；
- 推荐失败率；
- 每次会话计算成本。

## 17. 16 周实施计划

| 周期 | 目标 | 主要交付 |
| --- | --- | --- |
| 1–2 | 证据基础 | 题目—目标映射、Learning Event、最终证据规则、迁移和审计 |
| 3–4 | 状态模型 | Stage A 掌握度、置信度、状态快照、回放工具和影子计算 |
| 5–6 | 教师洞察 | 班级热力图、学生详情、证据解释和人工覆盖 |
| 7–8 | 推荐助手 | 目标选择、难度带、题目过滤、教师确认式练习计划 |
| 9–11 | 低风险自适应 | 学生练习会话、幂等 next、连续失败保护、暂停和恢复 |
| 10–12 | 库存联动 | 覆盖矩阵、去标识化补题需求、与 AI 出题工作台联动 |
| 12–14 | 评估与治理 | 离线回放、学习增益、保持度、公平性、删除和人工救济 |
| 15 | 影子试点 | 推荐只展示给教师，不自动派题，收集接受和修改原因 |
| 16 | 有限试点 | 只开放通过门槛的年级、目标和题型，不影响正式成绩 |

## 18. 发布阶段

### Stage 0：事件与映射验证

- 只写入 Learning Event；
- 状态模型离线运行；
- 不在 UI 展示，不影响教学。

### Stage 1：教师影子画像

- 教师可查看状态和证据；
- 不自动推荐；
- 收集教师纠正和目标映射问题。

### Stage 2：教师推荐助手

- 系统生成练习建议；
- 教师确认后布置；
- 不自动派题；
- 评估建议接受率和学习效果。

### Stage 3：低风险自适应练习

- 只用于课后练习；
- 只使用已审核题目；
- 不计入正式成绩；
- 提供解释、暂停、退出和教师控制。

### Stage 4：题库库存自动补充建议

- 只生成去标识化 content demand；
- AI 候选题仍经验证和教师审核；
- 不进行学生级实时生成。

### Stage 5：扩大范围

只有当分层学习增益、保持度、公平性和教师纠正率均达到门槛后，才扩展年级、题型、课程 profile 或自动化程度。

## 19. 建议试点门槛

阈值必须经影子数据校准，以下仅为初始目标：

| 指标 | 初始目标 |
| --- | ---: |
| 无证据或低证据时错误显示“掌握”的比例 | ≤ 0.5% |
| 单题导致跨越两个以上状态等级的比例 | 0% |
| 教师认为知识状态明显错误的比例 | ≤ 5% |
| 推荐计划教师直接接受率 | ≥ 60% |
| 推荐计划教师修改后接受率 | ≥ 85% |
| 自适应会话连续失败触发率 | ≤ 10% |
| 近期重复或近似题曝光率 | ≤ 3% |
| 已审核题目使用率 | 100% |
| 未经教师审核 AI 题直接展示率 | 0% |
| 正式成绩被推荐模型自动修改率 | 0% |
| 推荐 API P95 | ≤ 500 ms |

学习增益和保持度门槛应以对照或准实验结果确定，不能用固定常量替代教学验证。

## 20. 建议后续 Issue 拆分

1. `[Epic][Adaptive Learning] 学生知识画像与个性化练习系统`
2. `[Learning Data] 建立 Learning Event 与题目—课程目标证据模型`
3. `[Student Model] 实现可解释掌握度、不确定性和回放`
4. `[Misconceptions] 建立数学与英语常见错误状态`
5. `[Calibration] 建立题目难度、区分度和曝光统计`
6. `[Recommendation] 实现目标、难度和题目排序策略`
7. `[Teacher Web] 实现班级热力图、证据查看和教师推荐助手`
8. `[Student Web] 实现个人知识地图与低风险自适应练习`
9. `[Inventory] 建立题库覆盖矩阵与去标识化 AI 补题需求`
10. `[Evaluation] 建立学习增益、保持度、公平性和策略回归评估`
11. `[Governance] 建立画像解释、人工覆盖、删除和高利害使用限制`

## 21. Definition of Done

第三阶段 MVP 只有在以下条件全部满足时才算完成：

1. 每个知识状态都有课程 objective revision 和可回放学习证据；
2. 最终教师评分和订正证据优先于初始自动判分；
3. 低证据状态明确显示不确定，不伪造精确结论；
4. 教师能查看、解释、纠正和暂停画像与推荐；
5. 自适应练习只使用已验证、教师审核并发布的题目；
6. AI 出题 Provider 不接收个人画像、学生身份或原始答案；
7. 推荐策略保留探索、先修、课程进度和间隔复习机会；
8. 画像和推荐不能直接修改正式成绩或用于高利害决策；
9. 模型、规则、课程、映射和推荐版本全部可追溯和回滚；
10. 删除学生数据时，知识状态、快照和推荐记录同步处理；
11. 离线和影子评估能发现校准、学习效果、公平性或重复曝光退化；
12. 有限试点证明教师可接受、学生不会持续失败，并产生可验证的学习增益或保持改善。
