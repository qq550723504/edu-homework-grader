# OpenAI 模型快照治理实施计划

> **执行约束：** 每项变更先写失败测试，完成后运行列出的验证；不暂存 `.superpowers/` 工作记录。

**目标：** OpenAI 生成只接受不可变、带真实日期的模型快照，并将该快照保持为审计模型版本。

**架构：** 在生成器包加入无副作用的快照格式校验函数。API 设置与 OpenAI 适配器复用该函数，分别覆盖启动时配置和直接构造边界。

---

### Task 1: 定义并测试快照契约

**文件：**
- 新建：`services/generator/src/edu_generator/model_snapshots.py`
- 修改：`services/generator/tests/test_contracts.py`

**步骤：**
1. 添加接受有效日期后缀、拒绝无日期/无效日期的测试。
2. 实现标准库校验函数。
3. 让 `OpenAIResponsesProvider` 使用它，并保持空模型的既有错误语义。
4. 运行 `python -m pytest services/generator/tests/test_contracts.py -q`。

### Task 2: 在部署配置边界强制执行

**文件：**
- 修改：`apps/api/src/edu_grader_api/settings.py`
- 修改：`apps/api/tests/test_settings.py`

**步骤：**
1. 为生产 OpenAI 配置添加别名拒绝和快照接受测试。
2. 复用任务 1 的校验函数，不复制正则或日期逻辑。
3. 运行 `python -m pytest apps/api/tests/test_settings.py -q`。

### Task 3: 记录范围与验收证据

**文件：**
- 修改：本计划

**步骤：**
1. 记录实际测试命令及通过结果。
2. 明确 #39、#41、#42 和 #43 其余项不在本次范围。
3. 审查 `git diff --check` 和变更文件范围。

## 最终验证

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest services/generator/tests/test_contracts.py apps/api/tests/test_settings.py apps/api/tests/test_ai_question_generation_api.py -q
ruff check apps/api/src/edu_grader_api services/generator/src/edu_generator apps/api/tests/test_settings.py services/generator/tests/test_contracts.py
ruff format --check apps/api/src/edu_grader_api services/generator/src/edu_generator apps/api/tests/test_settings.py services/generator/tests/test_contracts.py
git diff --check
```

## 实际验收记录

- 任务 1 已完成：执行 `python -m pytest services/generator/tests/test_contracts.py -q`，结果为 `20 passed`；对应的 `ruff check`、`ruff format --check` 与 `git diff --check` 均通过。
- 任务 2 已完成：执行 `python -m pytest apps/api/tests/test_settings.py -q`，结果为 `24 passed`；对应的 `ruff check`、`ruff format --check` 与 `git diff --check` 均通过。
- 最终组合验证已完成：`python -m pytest services/generator/tests/test_contracts.py apps/api/tests/test_settings.py apps/api/tests/test_ai_question_generation_api.py -q` 结果为 `48 passed`；完整变更范围的 `ruff check`、`ruff format --check` 与 `git diff --check` 均通过。

## 非目标与后续边界

- 本切片不配置真实 OpenAI API 密钥或实际使用的模型快照，不完成 #39 所需的受控真实 Provider 部署。
- 本切片不实现 #41 的教师审阅、确认或发布工作流，也不实现 #42 的评测能力。
- 本切片不治理 #43 的提示词版本/目录、灰度或金丝雀发布、回滚、监测与告警等其余项目；这些需要独立切片。

## 完成记录

- [x] 任务 1：快照契约与适配器边界
- [x] 任务 2：设置边界
- [x] 任务 3：范围与验证记录
