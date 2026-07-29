# 题库、智能组卷与开放能力平台

状态：提案  
更新时间：2026-07-27  
Epic：[#144](https://github.com/qq550723504/edu-homework-grader/issues/144)  
关联：#30（多题作业）、#36（AI 出题）、#37/#38（课程目录）、#39（Provider）、#40（验证）、#41（教师审核）

## 1. 决策摘要

`edu-homework-grader` 将建设供应商无关的题库与智能组卷平台；二一题库只是首个外部内容提供方，而不是前端或公共 API 的直接依赖。平台以本地的课程、题目版本、试卷版本和授权快照为事实来源，最终可在授权边界内向内部教师端和外部客户端提供稳定 API。

```text
教师端 / 受授权的第三方客户端
              │
              ▼
 Edu Homework Grader application services
     ├─ 本地题库与已发布 QuestionVersion
     ├─ 外部 QuestionBankProvider（首批：二一）
     └─ AI 候选题生成（既有 Generator）
              │
              ▼
  PaperVersion → Assignment → AssignmentItem
```

不采用“二一 API 原样透传”方案：这会把供应商路径、标识、可用性和授权语义泄漏到产品边界，且会使学生作答时依赖外部服务。

## 2. 已有能力与本期缺口

| 已有基础 | 本提案新增的领域能力 |
| --- | --- |
| `CurriculumProfile`、年级映射、目标 revision 和带来源治理的课程导入 | 教材版本、册别、章节、知识点的外部映射与增量同步游标 |
| `Question` / `QuestionVersion`、发布前测试、教师审核 | 富题目内容、题目媒体、外部来源引用、许可和本地授权快照 |
| AI 题目 `GenerationProvider`、验证和受控转草稿 | 面向题库的 `QuestionBankProvider`、相似题/图搜/库存等不同能力契约 |
| 多题 `Assignment` / `AssignmentItem` | 独立的 `Paper`、`PaperVersion`、大题、题目分值、蓝图、生成和导出任务 |
| 课程目标与 AI 安全/版权治理 | 外部内容的展示、持久化、AI 处理和再分发许可门禁 |

已有 AI 题目生成流程保持不变：生成或外部导入的内容先成为草稿，经过验证与教师确认后才可进入正式题库或试卷。此提案不允许绕过 `QuestionVersion` 的发布前测试门禁。

## 3. 产品范围与优先级

### P0：教材、统一检索与可审核组卷闭环

- 教材目录同步：学科、年级、教材版本、册别、章节、知识点，以及本地 UUID 到外部标识的映射；
- 多条件题库检索和详情导入：课程范围、题型、难度、年份/地区/题类、关键词、仅客观题、严格知识点和超纲排除；
- 外部题目的本地授权快照、去重、来源和许可记录；
- 章节/知识点组卷、题型库存预检、双向细目蓝图、单题替换和质量报告；
- `PaperVersion` 教师确认后物化为当前 `Assignment` / `AssignmentItem`，不改写学生已有作答和批改记录。

### P1：增强题目获取与输出

- 题库相似题；
- 按图搜题（识别、精确/相似匹配、文件安全检查）；
- AI 原创变式题：复用既有生成、验证和教师审核链路；
- A/B 平行卷、班级错题巩固卷；
- 教师卷、学生卷、答案卷和解析卷的 DOCX/PDF 异步导出。

### P2：开放平台与嵌入式能力

- 对外 API、机器客户端认证、scope、配额、审计、幂等、Webhook 与租户隔离；
- 只向被授权的客户暴露其可访问的本地或外部内容；
- 嵌入式组卷组件和备课资源推荐。

VR 实验、资源商城和完整备课库不进入此 Epic 的关键路径。

## 4. 架构边界

### 4.1 Provider 不等于内部领域模型

定义同步的、供应商无关的 `QuestionBankProvider` 能力族，而不是把所有来源强行塞入一个接口：

```python
class CatalogSyncProvider(Protocol):
    async def sync_catalog(self, cursor: str | None) -> CatalogSyncPage: ...

class QuestionSearchProvider(Protocol):
    async def search(self, query: QuestionSearchQuery) -> QuestionSearchPage: ...
    async def get_question(self, external_id: str) -> ExternalQuestionDetail: ...
    async def count_available(self, constraints: InventoryQuery) -> InventoryReport: ...

class SimilarQuestionProvider(Protocol):
    async def find_similar(self, query: SimilarQuestionQuery) -> QuestionSearchPage: ...

class ImageQuestionSearchProvider(Protocol):
    async def search_by_image(self, request: ImageQuestionSearchRequest) -> ImageSearchResult: ...
```

具体 Provider 可只实现自身支持的能力；组合服务负责能力发现、超时、结果标准化、来源排序、去重、许可过滤和可观测性。AI 变式生成继续走既有 `GenerationProvider`，不冒充外部题库检索。

### 4.2 外部内容进入学生路径前必须本地化

```text
外部搜索结果
→ 获取题目详情
→ 内容清洗与统一结构转换
→ 许可与租户范围检查
→ 本地授权快照 + ExternalContentReference
→ QuestionVersion 草稿
→ 评分规则/测试/教师审核
→ PaperVersion
→ AssignmentItem
```

学生作答、批改、复核和成绩发布只能引用本地不可变版本；不能在作答时实时请求供应商，也不能因供应商内容变更而改变已发布作业。

### 4.3 授权优先于技术可行性

对每个外部内容引用记录 `provider`、`external_id`、来源版本、`license_scope`、允许租户、是否可持久化、学生展示、AI 处理、再分发和合同到期时间。检索成功不等于有权导入、展示、导出或经开放 API 再提供。

在书面合同明确允许前，二一等外部内容仅可用于合同约定的产品、租户和用途；不得默认对外转售、再授权或让 AI Provider 处理原题内容。此项须由法务/采购确认，不以公开开发者文档替代授权。

## 5. 核心领域模型

保留既有 `Question`、`QuestionVersion`、`Assignment` 和 `AssignmentItem`，新增下列聚合和关联，而非用 `AssignmentItem` 承担试卷排版职责：

```text
CatalogSource / TextbookVersion / TextbookBook / Chapter / KnowledgePoint
ExternalCatalogReference / CatalogSyncJob

QuestionContent / QuestionMediaAsset / QuestionCurriculumTag
ExternalContentReference / QuestionSourceMetadata / QuestionSimilarityEdge
QuestionExposureRecord

Paper / PaperVersion / PaperSection / PaperItem
PaperBlueprint / PaperBlueprintVersion / PaperGenerationJob
PaperQualityReport / PaperExportJob
```

`QuestionVersion` 需要逐步演进为可表达题干、选项、材料、子题、答案、解析、媒体、难度、预估用时、年级和自动批改能力的富内容模型。迁移时须保持当前 M1/M2/E1–E4 的 `prompt`、`reading_material`、`rule_json` 和发布契约可读，禁止一次性重写已发布版本。

## 6. 稳定 API 轮廓

内部 API 使用 `/v1`，开放 API 使用 `/open/v1`，两者复用 Application Service，仅在认证、权限、限额和响应脱敏上不同。

| 领域 | 代表性接口 |
| --- | --- |
| 目录 | `GET /v1/catalog/{subjects,textbook-versions,books,chapters,knowledge-points}`、`POST /v1/catalog/sync-jobs` |
| 检索 | `POST /v1/question-bank/search`、`GET /v1/question-bank/questions/{id}` |
| 相似/图搜 | `POST /v1/question-bank/questions/{id}/similar-search`、`POST /v1/question-search/image` |
| AI 变式 | `POST /v1/question-variation-jobs`；结果必须回到既有候选题治理链路 |
| 试卷蓝图 | `POST /v1/paper-blueprints`、`POST /v1/paper-blueprints/availability` |
| 组卷 | `POST /v1/paper-generation-jobs`、`GET /v1/paper-generation-jobs/{id}` |
| 试卷操作 | `GET /v1/papers/{id}`、`POST /v1/papers/{id}/items/{item_id}/replace`、`GET /v1/papers/{id}/quality-report` |
| 导出 | `POST /v1/papers/{id}/exports`、`GET /v1/export-jobs/{id}` |

请求和响应只使用本地 UUID 与统一枚举；Provider 名称和外部 ID 仅作为受权限控制的来源元数据返回。所有创建任务和会导致选题结果变化的操作都要支持 `Idempotency-Key`。

## 7. 组卷质量与发布门禁

`PaperBlueprint` 明确表达“题型 × 知识点 × 难度 × 分值 × 能力层级”，并允许附加：课程范围、题型库存、最近曝光排除、最大题间相似度、超纲排除和最小自动批改比例。

组卷前输出可行性报告；组卷后生成质量报告，至少覆盖总分、难度分布、知识点覆盖、重复/高度相似题、超纲、题型库存替代、预估时长和自动批改覆盖率。任何放宽范围、使用 AI 补题或采用未发布题目都必须显式显示，并由教师确认。

```text
PaperBlueprintVersion
→ PaperGenerationJob
→ PaperVersion（ready_for_review）
→ 教师审批
→ Assignment 草稿与不可变 AssignmentItem 快照
→ 现有作答、批改、复核与发布流程
```

## 8. 实施拆分与依赖

本 Epic 只跟踪目标、边界和验收，不应由单一 PR 完成。按以下可独立验收的子议题拆分：

1. **P0：外部教材目录与来源/许可证映射。** 建立目录映射、增量同步、审核和回滚；依赖 #37/#38。
2. **P0：富题目、外部内容引用与本地授权快照。** 保持已有题目版本兼容，落实媒体与安全清洗。
3. **P0：统一检索与二一 Provider。** 实现搜索、详情、库存、能力降级和端到端授权过滤。
4. **P0：Paper / Blueprint / 组卷质量模型。** 先完成库存预检、章节/知识点组卷、替题和质量报告。
5. **P0：PaperVersion 到 Assignment 的受控物化。** 不破坏 #30 的多题作业、学生作答和已发布历史。
6. **P1：相似题、图搜、AI 变式与 A/B 卷。** 图像上传必须独立威胁建模；AI 变式复用 #36 的治理边界。
7. **P1：DOCX/PDF 导出。** 采用成熟、可维护的 DOCX/PDF 库和模板方案；先完成无供应商内容泄露的本地题目导出。
8. **P2：开放平台。** 先完成客户端认证、scope、配额、审计、IP 限制、Webhook 和内容授权，再开放第三方检索/导出。

每个子议题在实现前应调查可复用的成熟开源库（富文本/公式清洗、OCR、DOCX/PDF 渲染、向量检索），并记录许可证、活跃维护状态、数据处理位置与安全边界，避免重复造轮子。

## 9. Epic 验收标准

- [ ] 教师能在明确教材和知识点范围内检索并选入受授权的题目；外部内容不会在学生作答时实时依赖供应商。
- [ ] 已发布题目、试卷、作业和学生作答始终可回放到本地不可变版本、来源、许可和教师决策。
- [ ] 教师能以章节、知识点或双向细目创建蓝图；系统在生成前报告库存不足，在生成后报告可解释质量结果。
- [ ] 教师确认的 `PaperVersion` 可安全创建现有多题作业，不改变现有自动批改、复核和成绩发布边界。
- [ ] AI 变式题仍要经过现有验证和教师审核；不得直接进入 `published` 或学生作业。
- [ ] 图搜上传实施大小、格式、内容检测、恶意文件扫描、隔离存储、保留期和置信度返回；无匹配不能伪装为精确题目。
- [ ] 对外 API 只在客户端 scope、租户、额度和内容授权均通过时返回数据，并有可审计的拒绝路径。
- [ ] 合同未明确允许的外部内容不能被再分发、导出、再授权或送入第三方 AI 服务。

## 10. 参考

- 二一开放平台：[API 总览](https://dev.21cnjy.com/docs/api/)、[题库资源](https://dev.21cnjy.com/docs/api/questions.html)、[数据同步](https://dev.21cnjy.com/docs/api/sync.html)、[试卷资源](https://dev.21cnjy.com/docs/api/papers.html)、[双向细目](https://dev.21cnjy.com/docs/api/inventory.html)。这些资料用于能力调研，不构成内容使用、持久化或再分发的授权。
- 项目既有设计：[AI 出题实施计划](ai-question-generation-plan.md)、[课程运营导入协议](curriculum-import-protocol.md)、[自适应学习实施计划](adaptive-learning-plan.md)。
