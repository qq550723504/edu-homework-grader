# Prompt 模板治理实施计划

**目标：** 将生成 Prompt 从请求方提供的任意字符串和 Provider 硬编码，收敛为可审计、可验证的服务端模板目录。

---

### Task 1: 模板目录与不变量

**文件：**
- 新建：`services/generator/src/edu_generator/prompt_templates.py`
- 修改：`services/generator/tests/test_contracts.py`

1. 先写 `generator-v1` 元数据、稳定指纹、未知版本和不适用题型的失败测试。
2. 实现纯目录/解析器，不依赖 API 或数据库。
3. 运行生成器契约测试。

### Task 2: 服务和 Provider 共同执行目录

**文件：**
- 修改：`apps/api/src/edu_grader_api/services/generation.py`
- 修改：`services/generator/src/edu_generator/openai_provider.py`
- 修改：`apps/api/tests/test_generation_service.py`
- 修改：`services/generator/tests/test_contracts.py`

1. 创建 Job 时根据版本与请求题型解析模板，未知或不适用项失败关闭。
2. Provider 调用前重新解析模板并使用目录中的系统约束与 Schema 版本。
3. 保持 fake provider、题目验证和发布边界不变。

### Task 3: 审计元数据和 API 非泄露回归

**文件：**
- 修改：`apps/api/src/edu_grader_api/services/generation.py`
- 修改：`apps/api/tests/test_generation_service.py`
- 修改：`apps/api/tests/test_ai_question_generation_api.py`
- 修改：本计划

1. 将版本、Schema、profile 范围、适用题型和模板指纹写入 `GenerationAttempt.request_summary`。
2. 验证 Job/草稿 API 响应不返回系统约束正文。
3. 记录范围和实际验证结果。

## 最终验证

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest services/generator/tests/test_contracts.py apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -q
ruff check apps/api/src/edu_grader_api services/generator/src/edu_generator apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py services/generator/tests/test_contracts.py
ruff format --check apps/api/src/edu_grader_api services/generator/src/edu_generator apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py services/generator/tests/test_contracts.py
git diff --check
```

## 完成记录

- [x] Task 1: 模板目录与不变量
- [x] Task 2: 服务和 Provider 共同执行目录
- [x] Task 3: 审计元数据和 API 非泄露回归

## 实际验证

- `PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src' python -m pytest services/generator/tests/test_contracts.py apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -q`：55 passed。
- 计划中列出的 `ruff check`、`ruff format --check` 和 `git diff --check`：通过。
- 运行时无法解析历史模板时，Job 以 `prompt_template_unavailable` 失败关闭、`failed_count` 覆盖未生成数量且不创建/调用 Attempt；正常 Attempt 的安全摘要仅记录模板元数据锚点，不记录系统约束正文或教师约束。
