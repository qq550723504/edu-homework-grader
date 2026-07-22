# 规则型难度信号实施计划

### Task 1: 抽取安全复杂度观测并定义估计契约

**文件：**
- 修改：`apps/api/src/edu_grader_api/services/question_verification.py`
- 修改：`apps/api/tests/test_question_verification.py`

1. 先写规则估计与稳定、脱敏特征的失败测试。
2. 提取供现有年级警告复用的安全观测指标；实现不依赖模型的估计函数。
3. 运行验证器单元测试。

### Task 2: 持久化运行信号与 API 回归

**文件：**
- 修改：`apps/api/src/edu_grader_api/services/question_verification.py`
- 修改：`apps/api/tests/test_question_verification.py`
- 修改：`apps/api/tests/test_ai_question_generation_api.py`
- 修改：本计划

1. 把信号写入 `feature_summary_json`，保留现有 duplicate 摘要。
2. 验证 API 返回结构可消费但不泄露正文；无效/不安全路径安全降级。
3. 记录范围与最终验证。

## 最终验证

```powershell
$env:PYTHONPATH='apps/api/src;services/generator/src;packages/processor-policy/src'
python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py -q
ruff check apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py
ruff format --check apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py
git diff --check
```

## 完成记录

- [x] Task 1: 安全复杂度观测与规则估计（`bdd7439`）
- [x] Task 2: 持久化与 API 回归

Task 2 将 `rule-based-difficulty-v1` 信号与既有 duplicate/content-policy
摘要共同写入每一个验证运行。正常路径只传入候选声明难度、课程范围、
题型、受限题干、规则和已验证的 M2 AST；验证异常路径使用空题干、未知题型
和空范围，避免将候选正文或内部异常带入审计数据。API 回归验证了路由 payload
可以消费该信号且不包含题干或教师专用文本；无效目标难度仍产生既有
`difficulty_out_of_range` blocked finding。

P2 修订：正常信号明确记录 `availability: available` 和固定的 `reason: null`；验证器异常不再伪造
`0.25` 的估计值，而是记录同版本的 `availability: unavailable` schema，包含
空特征、空数值和稳定的 `validator_unavailable` 原因。服务和 API 路由回归均验证
该状态不带候选正文、教师文本或内部诊断。

2026-07-22 最终验证通过：`207 passed`；Ruff check、Ruff format check 与
`git diff --check` 均通过。
