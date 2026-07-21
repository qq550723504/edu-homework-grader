# K–13 课程约束型 AI 出题实施计划

状态：M1 基础能力已实现（#39）；教师审核接入与生成质量验证仍待后续 Issue
更新日期：2026-07-21
Epic：[#36](https://github.com/qq550723504/edu-homework-grader/issues/36)

## 1. 目标

在现有题库、评分策略、发布前测试和教师审核能力之前增加一个 AI 候选题生成层，使教师可以按课程体系、年级、学习目标、题型、数量和难度分布生成英语与数学候选题。

目标链路：

```text
课程目标约束
→ AI 生成候选题
→ 结构与策略校验
→ 数学/英语确定性验证
→ 年级、难度、重复与安全检查
→ 教师审核和编辑
→ 现有发布前测试门禁
→ 正式题库
→ 多题作业编排
```

AI 不拥有发布权限。任何候选题必须由教师明确接受，并继续通过现有 QuestionVersion 测试与发布门禁。

当前实现的运行边界：Core API 持久化作业、配额、审计与候选草稿，`services/generator` 只处理
去标识化的结构化请求和 Provider 适配。默认使用确定性 `fake` Provider；生产可选 OpenAI Responses
Provider，但必须从 Secret Manager 注入 `OPENAI_API_KEY`，显式指定固定 `GENERATOR_OPENAI_MODEL`，并使用
专用主机 allowlist。候选题只进入 `generated_question_drafts`，不创建或发布 `QuestionVersion`。

## 2. 产品原则

1. **AI 生成候选，教师最终负责。** 不允许 AI 生成结果直接进入 `published`。
2. **确定性验证优先。** 标准答案必须通过 Grader、规则或可解释检查，不能仅依赖第二次模型评审。
3. **课程版本可追溯。** 每道候选题引用明确的 curriculum profile 和 objective revision。
4. **模型与 Prompt 可追溯。** 保存不可变模型版本、Prompt 版本、参数、随机种子和验证器版本。
5. **学生数据不进入生成链路。** 生成请求不得包含学生、班级、成绩、作答、学校身份或令牌。
6. **K 阶段不等于小学提前教学。** 学前阶段输出非评分学习活动，不进入自动评分题库。
7. **K–13 是内部层级。** 必须映射到具体地区、课程标准、语言能力框架和版本。
8. **不以生成量衡量质量。** 核心指标是答案准确性、年级适配、重复率、教师接受率和发布后改答案率。

## 3. K–13 内部层级与课程 Profile

| 内部层级 | 平台含义 | 生成边界 |
| --- | --- | --- |
| `K3_4` | 3–4 岁学前发展阶段 | 非评分活动 |
| `K4_5` | 4–5 岁学前发展阶段 | 非评分活动 |
| `K5_6` | 5–6 岁学前/幼小衔接阶段 | 非评分活动，不做超前小学考试 |
| `G1`–`G6` | 小学通用层级 | M1、E1、E2；高年级可逐步开放 M2/E3/E4 |
| `G7`–`G9` | 初中通用层级 | M1、M2、E1–E4 |
| `G10`–`G12` | 高中通用层级 | 首期只开放已有策略可验证的题型 |
| `G13` | Year 13、大学先修或过渡课程 | 必须选择明确 profile，禁止使用全局默认课程顺序 |

首批 profile 建议：

- `cn-preschool-3-6-2012`：教育部[《3—6岁儿童学习与发展指南》](https://www.moe.gov.cn/srcsite/A06/s3327/201210/t20121009_143254.html)（2012），对应 K 阶段；
- `cn-compulsory-2022`：教育部[《义务教育课程方案和课程标准（2022年版）》](https://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html)，对应 G1–G9；
- `cn-high-school-2017-2020`：教育部[《普通高中课程方案和课程标准（2017年版2020年修订）》](https://hudong.moe.gov.cn/srcsite/A26/s8001/202006/t20200603_462199.html)，对应 G10–G12；
- `cefr-2020`：Council of Europe [CEFR Companion Volume](https://www.coe.int/en/web/common-european-framework-reference-languages/cefr-companion-volume-and-its-language-versions)（2020），作为跨地区语言能力框架，不单独推导年级。

Profile 保存官方来源 URL、发布机构、版本、生效区间、审核状态和不超过学习目标所需的短摘要；不导入教材、教辅或试卷正文。上述版本是首期基线而非永久默认值：官方发布替代版本时新增 profile 和 objective revision，停用旧版以阻止新生成任务引用，历史题目和生成记录继续保留原引用。

后续地区教材版、国际课程版和机构自定义 profile 必须走版本化导入与审核流程。

## 4. 首期功能范围

### 4.1 评分题目

| 年级范围 | 学科 | 首期题型 | 发布策略 |
| --- | --- | --- | --- |
| G1–G6 | 数学 | M1 数值题 | 通过验证与教师审核后进入题库 |
| G4–G12 | 数学 | M2 表达式题 | 通过安全 MathJSON/AST 验证 |
| G1–G12 | 英语 | E1、E2 | 确定性规则验证 |
| G4–G12 | 英语 | E3、E4 | 必须教师复核，不自动最终判定 |
| G13 | 英语/数学 | 已有策略覆盖的题型 | 仅在具体 profile 下开放 |

### 4.2 K 阶段活动

K 阶段使用独立的 `learning_activity-v1`，生成：

- 图片或实物分类；
- 数量感和一一对应；
- 图形匹配与空间观察；
- 简单找规律；
- 听音、口语和情景问答；
- 动作、游戏和生活情境活动；
- 教师观察要点和亲子引导建议。

K 活动不得包含分数、排名、限时考试或自动能力画像。

### 4.3 首期非目标

- 几何证明自动出题与全自动判分；
- 开放性数学建模；
- 英语作文自动最终评分；
- 直接生成高风险正式考试并自动发布；
- 根据真实学生历史作答做个性化生成；
- 复制特定商业题库、试卷或教材页面；
- AI 自动决定课程目标或改变学校课程安排。

## 5. 目标架构

```text
Teacher Web
  └─ AI Authoring Workspace
        │
        ▼
Core API
  ├─ curriculum profiles/objectives
  ├─ generation jobs and drafts
  ├─ permissions, quotas and audit
  └─ conversion to QuestionVersion draft
        │
        ▼
Generator Service
  ├─ provider abstraction
  ├─ versioned prompt templates
  ├─ structured JSON output
  └─ bounded retries/cancellation
        │
        ▼
Verification Pipeline
  ├─ policy/schema validation
  ├─ Math Grader + safe worker
  ├─ English rules + LanguageTool
  ├─ grade/difficulty checks
  ├─ duplicate and copyright-risk checks
  └─ content safety checks
        │
        ▼
Generated Question Draft Pool
        │ teacher accepts/edits/rejects
        ▼
Question + QuestionVersion (draft)
        │ existing test-run gate
        ▼
Published Question
        │
        ▼
Multi-question Assignment
```

Generator 不直接写正式题库。Core API 负责权限、状态机、持久化和审计；Grader 仍负责确定性评分与数学安全执行。

## 6. 领域模型

### 6.1 课程数据

```text
curriculum_profiles
curriculum_grade_mappings
curriculum_objectives
curriculum_objective_revisions
curriculum_prerequisites
curriculum_source_records
```

### 6.2 生成数据

```text
generation_jobs
generation_attempts
generated_question_drafts
generation_validation_runs
validation_findings
generation_teacher_reviews
generation_quota_ledgers
```

关键关系：

- `generation_job` 引用一个 profile 和一个或多个 objective revision；
- `generated_question_draft` 引用生成 attempt 和最新 validation run；
- 教师接受候选题后，创建 `Question` 与草稿 `QuestionVersion`；
- 正式题目保留 `generated_question_draft_id`，但不能反向覆盖原始生成记录；
- 课程、模型、Prompt 和验证规则升级后，历史结果保持不变。

## 7. 候选题状态机

```text
generated
  ↓
validating
  ├─ blocked
  ├─ warning
  └─ passed
        ↓
ready_for_review
  ├─ rejected
  ├─ regenerating
  ├─ edited → revalidating
  └─ accepted
        ↓
converted_to_question_draft
        ↓
现有测试与发布门禁
```

约束：

- `blocked` 不可接受；
- `warning` 需要教师明确确认；
- 编辑题干、答案规则、评分点、课程目标或难度后必须重新运行相关验证器；
- 接受不等于发布；
- 重复点击接受必须幂等，不能创建多个正式题目。

## 8. 核心 API

```http
GET  /v1/curriculum-profiles
GET  /v1/curriculum-profiles/{profile_id}/objectives

POST /v1/ai-question-generation/jobs
GET  /v1/ai-question-generation/jobs/{job_id}
POST /v1/ai-question-generation/jobs/{job_id}/cancel
GET  /v1/ai-question-generation/jobs/{job_id}/questions

POST /v1/ai-generated-questions/{question_id}/regenerate
POST /v1/ai-generated-questions/{question_id}/validate
PATCH /v1/ai-generated-questions/{question_id}
POST /v1/ai-generated-questions/{question_id}/accept
POST /v1/ai-generated-questions/{question_id}/reject
POST /v1/ai-question-generation/jobs/{job_id}/bulk-accept
```

示例生成请求：

```json
{
  "curriculum_profile": "cn-compulsory-2022",
  "grade_level": "G7",
  "subject": "mathematics",
  "objective_revision_ids": ["objective-revision-id"],
  "question_distribution": [
    {"question_type": "M1", "count": 2},
    {"question_type": "M2", "count": 5}
  ],
  "difficulty_distribution": {
    "basic": 3,
    "intermediate": 3,
    "advanced": 1
  },
  "language": "zh-CN",
  "include_explanation": true,
  "include_common_mistakes": true
}
```

## 9. 结构化输出要求

模型输出必须匹配平台维护的 JSON Schema。正式处理路径不接受自由格式 Markdown。

每道评分题至少包含：

```json
{
  "curriculum": {
    "profile_code": "cn-compulsory-2022",
    "grade_level": "G7",
    "objective_revision_ids": ["..."]
  },
  "question": {
    "title": "合并同类项",
    "question_type": "M2",
    "policy_version": "2",
    "prompt": "化简：3x + 2 - x + 5",
    "rule": {
      "expected": ["Add", ["Multiply", 2, "x"], 7],
      "variables": ["x"],
      "required_form": "expanded",
      "max_score": 4
    },
    "explanation": "先合并含 x 的同类项，再合并常数项。",
    "knowledge_points": ["合并同类项"],
    "difficulty": {"label": "basic", "score": 0.28}
  },
  "generation": {
    "prompt_version": "math-generator-v1",
    "model_id": "configured-generator",
    "model_version": "immutable-version",
    "seed": 42185
  }
}
```

## 10. 验证门禁

### 10.1 通用

- 策略 Schema；
- 课程目标与允许题型；
- 题干、答案规则、解析和总分一致性；
- 年级与先修范围；
- 内容安全与年龄适配；
- 生成候选字段在本地按 `minor-content-policy-v1` 做确定性内容扫描：明确不适合未成年人的内容和直接复现受保护材料的请求会阻止，依赖语境的成熟主题会警告；持久化证据只包含类别、规则和策略版本元数据。扩展策略须经 #42 评估；许可、教师请求过滤和下架工作归 #43 所有；
- 精确重复、规范化重复和语义近重复；
- 版权/来源风险；
- 输出长度和结构复杂度。
- 年级复杂度阈值只由目标 curriculum profile 的 grade mapping 持有：可分别配置题干词元数、最长句词元数、数值绝对值和安全 M2 AST 的运算节点数。超过阈值只产生 `grade_complexity_warning`，其稳定证据仅含 `grade_level`、`metric`、`observed` 和 `limit`；不会携带题干、MathJSON、AST 或 Provider 内容，也不会自动发布或替代教师决定。M2 只复用 Grader 已规范化的一份安全 AST；阈值校准、黄金评估和质量门槛仍由 #42 负责，教师确认 warning 的工作流仍由 #41 负责。

### 10.2 数学

- M1 数值与误差规则可解析；对 Schema 有效且策略版本为 `"1"` 的候选题，Core 依次将正确答案、空答案、两个含端点的误差边界，以及两个边界外答案作为六个 `text-v1` 探针交给现有数值 Grader；任何依赖异常、非有限分数或不符合接受/拒绝契约的结果都会阻止候选题，持久化证据只记录稳定的探针标识，不保存数值、容差、分数或 Grader 反馈；
- M2 MathJSON 可规范化并进入安全 AST；
- 标准答案通过现有 Grader；
- M1 的上述逐候选题探针不推断题干特定的常见误解或语义干扰项；课程相关的 common-misconception distractors、黄金语料与错误率校准仍是 #40/#42 后续工作；
- 多解、定义域不明、增根/漏根和不支持结构必须阻止或警告；
- 验证执行沿用 CPU、内存和墙钟限制。

### 10.3 英语

- E1 答案集合非空且规范化规则一致；
- E2 lemma、词形和约束完整；
- E3 题干/参考表达通过语法检查，仍保持人工复核；
- E4 评分点分值与总分一致，证据短语与材料存在关联；
- 词汇、句长和篇幅符合 profile/CEFR 约束；
- E3/E4 验证结果不能改变其人工复核策略。

## 11. 12 周实施阶段

| 周期 | 目标 | 主要交付 | Issues |
| --- | --- | --- | --- |
| 1–2 | 课程基础 | profile、年级映射、目标 revision、查询 API | #37 |
| 2–3 | 课程运营 | CSV/JSON dry-run、审核、激活、来源治理 | #38 |
| 3–5 | 生成服务 | Generator、provider 抽象、结构化输出、任务状态机 | #39 |
| 4–7 | 验证门禁 | 数学/英语验证、难度、安全、重复检查 | #40 |
| 6–8 | 教师工作台 | 发起生成、查看进度、审核、编辑、接受和拒绝 | #41 |
| 8–10 | 评估与治理 | 黄金评估集、质量门槛、配额、审计、模型/Prompt 生命周期 | #42、#43 |
| 10–11 | 集成验收 | 真实服务链路、题库发布、多题作业和故障降级 | #31、#36 |
| 12 | 影子试点 | 教师使用候选题但不自动发布，复盘指标和风险 | #36 |
| 后续 | K 阶段 | 非评分 Learning Activity 模式 | #44 |

#29 和 #30 是英语结构化建题、多题作业编排的前置产品能力，应在 AI 教师工作台完整验收前完成。

## 12. Issue 映射

| Issue | 工作流 | 优先级 |
| --- | --- | --- |
| #36 | AI 出题 Epic 与整体验收 | Epic |
| #37 | K–13 课程数据模型 | P0 |
| #38 | 课程导入、审核与来源治理 | P0 |
| #39 | 生成服务和 provider 抽象 | P0 |
| #40 | 答案、难度、重复与安全门禁 | P0 |
| #41 | 教师 AI 出题工作台 | P1 |
| #42 | 离线/线上质量评估 | P1 |
| #43 | 模型、Prompt、隐私、配额和版权治理 | P1 |
| #44 | K 阶段非评分活动 | P2 |

## 13. 质量指标与试点门槛

建议初始目标：

| 指标 | 初始目标 |
| --- | ---: |
| 结构 Schema 通过率 | ≥ 98% |
| 数学答案错误率 | ≤ 0.5% |
| 年级明显不匹配率 | ≤ 2% |
| 重复或高度相似题率 | ≤ 3% |
| 教师直接接受率 | ≥ 60% |
| 教师修改后接受率 | ≥ 85% |
| 发布后改答案率 | ≤ 0.5% |
| 未经教师审核发布率 | 0% |

阈值必须基于版本化评估集和真实影子试点校准，不应作为不可变常量硬编码。

## 14. 发布阶段

### Stage 0：内部开发

- fake provider；
- 最小课程样例；
- 不调用外部模型；
- 只验证状态机和 Schema。

### Stage 1：内部生成实验

- 真实 provider；
- 生成结果仅开发/学科团队可见；
- 所有题目人工双重审核；
- 建立黄金评估集。

### Stage 2：教师影子模式

- 试点教师可生成和审核；
- 候选题不会自动进入作业；
- 收集接受、修改、拒绝和重新生成原因。

### Stage 3：有限试点

- 只开放通过门槛的 profile、年级和题型；
- 教师接受后仍需题目测试与发布门禁；
- 每周复盘错误答案、超纲、重复和成本。

### Stage 4：扩大范围

只有当分层指标稳定后，才扩展年级、题型、课程 profile 或 provider。K 阶段单独验收，不随评分题目自动开放。

## 15. Definition of Done

AI 出题 MVP 只有在以下条件全部满足时才算完成：

1. 课程目标来源、版本和审核状态可追溯；
2. 生成服务不处理学生个人信息；
3. M1、M2、E1–E4 输出与现有策略协议一致；
4. 候选题经过独立、可解释的验证流水线；
5. blocked 题不能被教师接受；
6. 接受后的题目仍然是草稿并经过现有发布门禁；
7. 模型、Prompt、课程和验证版本均被保存；
8. 评估集能够阻止答案错误、超纲或重复率显著退化的版本；
9. 教师能够通过浏览器完成生成、审核、编辑和入库；
10. 影子试点达到约定质量指标，且未经教师审核发布率为零。
