# #37 K–13 课程 Profile 基础设计

## 范围

本设计只实现 AI 出题的课程约束基础：版本化课程目录、只读查询、管理员工作流和供后续生成服务引用的契约。候选题生成、模型 Provider、质量评估和教师审核分别属于 #39–#43。

K–13 是平台内部层级，不是单一法定课程标准；它不能推断学生所属地区、学校课程或能力水平。

## 选定方案

采用“受治理的内部目录”，而不是导入完整课标或接受租户自由标签。

- 导入完整课标会将授权、解析与编辑审核提前扩大为本任务的范围。
- 租户自由文本标签不能提供权威、稳定的生成约束。
- 选定方案保存经审核的短目标摘要和来源元数据，为首个生成器提供稳定标识；批量导入与来源治理留给 #38。

## 首批 Profile 与来源规则

首批 Profile 如下：

| 代码 | 权威依据与版本 | 内部层级 | 用途 |
| --- | --- | --- | --- |
| `cn-preschool-3-6-2012` | 教育部 [《3—6岁儿童学习与发展指南》](https://www.moe.gov.cn/srcsite/A06/s3327/201210/t20121009_143254.html)（2012） | `K3_4`、`K4_5`、`K5_6` | 仅非评分学习活动 |
| `cn-compulsory-2022` | 教育部 [《义务教育课程方案和课程标准（2022年版）》](https://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html) | `G1`–`G9` | 义务教育阶段目标 |
| `cn-high-school-2017-2020` | 教育部 [《普通高中课程方案和课程标准（2017年版2020年修订）》](https://hudong.moe.gov.cn/srcsite/A26/s8001/202006/t20200603_462199.html) | `G10`–`G12` | 高中阶段目标 |
| `cefr-2020` | Council of Europe [CEFR Companion Volume](https://www.coe.int/en/web/common-european-framework-reference-languages/cefr-companion-volume-and-its-language-versions)（2020） | 显式映射时可用于 `G1`–`G13` | 语言能力描述符，不是年龄或年级课程 |

每条来源记录保存发布机构、规范 URL、标题、发布日期、引用版本、可选失效日期和编辑说明；不保存教材、教辅、试卷或长篇受版权保护文本。目标修订只保存经审核的短摘要及来源定位，不复制原文段落。

替换官方标准必须新增 profile 或 revision，经审核后再停用旧版。停用会阻止新生成任务使用旧版，但不会改变历史引用。

## 目录模型

目录是平台级参考数据，不归任一租户所有。每个租户读取相同的已审核有效行；课程表不保存学生、班级、租户或学校数据。因此跨租户读取安全，同时不会出现一个租户修改或隐藏另一租户课程记录的情况。

`curriculum_profiles`

- UUID、唯一代码、显示名称、适用地区、版本标签、状态（`draft`、`in_review`、`active`、`retired`）、来源记录 ID、生效日期与时间戳。

`curriculum_grade_mappings`

- profile ID、内部层级（`K3_4`–`G13`）、外部学段/年级标签、排序与可选说明；
- 每个 profile、内部层级和外部标签组合唯一，因此同一内部层级可在不同 profile 中映射到不同外部年级。

`curriculum_objectives`

- UUID、profile ID、稳定目标代码、学科、领域、单元、知识点键、生命周期状态与时间戳；
- 此稳定实体不能作为历史内容引用。

`curriculum_objective_revisions`

- UUID、目标 ID、单调递增 revision 编号、已审核短文本、来源定位、允许题型、难度下限/上限、活动类型、审核状态、审核人 ID 与时间戳；
- revision 只追加。已审核 revision 可以停用，不能原地修改。

`curriculum_prerequisites`

- 依赖目标 revision ID、先修目标 revision ID、关系类型与时间戳；
- 拒绝自引用和重复有向边；激活前检测循环依赖。

`curriculum_source_records`

- 保存上文所述来源元数据和版权安全的编辑处理说明。

#39 新增的生成表必须保存 `curriculum_profile_id` 与精确的 `curriculum_objective_revision_id`，不能只保存自由文本年级、学科或知识点标签。

## 规则与权限

`curriculum_admin` 是独立的平台管理能力，与教师和学生角色分开配置。它可创建 profile、添加映射、提交修订、审核、启用、停用及维护先修关系。教师仅可读取有效目录并选择目标；学生没有课程目录端点。

服务在启用或发起生成前强制执行：

- `G13` 必须显式选择有效 profile，不能使用隐式平台默认值；
- `K3_4`、`K4_5`、`K5_6` 的目标只能允许 `learning_activity-v1`，不能允许 M1/M2/E1–E4 评分题；
- 评分目标允许的题型必须存在于当前策略目录，不支持的题型被拒绝；
- 无效 profile、目标或 revision 不能用于新生成任务；
- 修改已审核目标内容必须创建新 revision，引用旧 revision 的记录保持不变。

非法层级、题型或 profile 组合返回稳定的 HTTP 422，并带机器可读错误码与字段路径。普通读取者访问不存在或无效资源返回 404；无 `curriculum_admin` 的写操作返回 403。

## API 边界

已认证教师和课程管理员获得只读接口：

```text
GET /v1/curriculum-profiles
GET /v1/curriculum-profiles/{profile_id}/grade-mappings
GET /v1/curriculum-profiles/{profile_id}/objectives?grade_level=&subject=&domain=&knowledge_point=&question_type=
GET /v1/curriculum-objective-revisions/{revision_id}
```

课程管理员另有 profile、映射、目标、revision、先修关系和生命周期动作的写入/审核接口。审核与启用动作写入审计事件，其中保存执行者、目标 revision、旧状态、新状态和来源版本；绝不保存学生数据或复制的来源文本。

## 种子与验收覆盖

种子包含四个 profile、各自适用的内部层级映射、每个支持学科/领域的一项或多项短目标摘要，以及上述来源记录。它仅用于验证 profile → 年级 → 学科 → 领域 → 目标的选择链路，不声称是完整国家课程目录。

测试覆盖：

- Alembic upgrade 与 downgrade；
- 两个租户的可见性及无跨租户写入；
- 教师读取权限、学生拒绝访问、课程管理员写入/审核权限；
- profile、年级、领域与题型过滤；
- K 阶段活动限制、G13 显式 profile 限制及非法组合的 422；
- 追加式 revision、历史引用保留及停用后阻止新使用；
- 种子来源元数据与全部四个 profile 代码。

## 延后范围

#38 负责批量导入、编辑队列、来源接入工具与扩展来源治理；#39 保存生成引用；#40 验证候选题的题型、难度、安全与重复；#41 实现教师选择与审核界面。
