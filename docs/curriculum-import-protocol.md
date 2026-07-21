# 课程运营导入协议

课程管理员通过 `/v1/admin/curriculum/imports/dry-run` 预演 JSON 或 CSV 导入。预演不写入课程数据，并返回 `catalogue_fingerprint`、新增/更新/未变更统计及逐项问题。将原始内容和该指纹提交到 `POST /v1/admin/curriculum/imports`；若目录在预演后变化，接口返回 `409`，必须重新预演。

JSON 使用 [最小示例](examples/curriculum-import-minimal.json) 的嵌套结构：必须包含 profile、source、至少一个 grade mapping、至少一个 objective 和 prerequisites。来源必须包含发布者、链接、文档号、许可证和整理日期；课程目标必须是人工整理的简短表述，不能复制教材或课程标准正文。

CSV 使用 [最小示例](examples/curriculum-import-minimal.csv) 的列：`code`、`grade_level`、`subject`、`domain`、`text`、`source_locator`、`allowed_question_types`、`difficulty_min`、`difficulty_max`、`activity_type`、`change_summary`。CSV 请求同时在 `profile`、`source` 和 `grade_mappings` 字段提供与 JSON 相同的元数据；多个题型用 `|` 分隔。CSV 问题报告行号和列名，JSON 问题报告 JSON Pointer。

状态顺序是 `draft -> in_review -> active`，也可从审核中退为 `retired`。导入者可以送审，但不能审核或激活自己的批次；另一名已配置课程管理员审核后才能激活。目标正文或生成约束变化会产生新的草稿 revision，原有激活 revision 保留到新版本激活时才退役。

当前退役影响范围标记为 `curriculum_only`：本服务尚未拥有提示词模板或生成任务对课程目标的外键。后续生成域接入时会扩展影响列表，而不改变该声明的含义。
