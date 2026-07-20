# 项目状态（2026-07-20）

## 判定口径

- **已实现并有回归** 不等同于生产验收。
- **浏览器 E2E** 使用固定测试身份、隔离 SQLite 与确定性判卷替身。
- **生产未就绪** 项必须在试点环境完成外部验证。

| 范围 | 当前状态 | 限制 |
| --- | --- | --- |
| 学生端 | 作业、草稿隔离、同步、提交、反馈、申诉与订正入口已实现 | 离线草稿使用 IndexedDB。 |
| 教师端 | 建题、测试门禁、发布题目/作业、复核、发布成绩、处理申诉已实现 | 不含高级题库运营与报表。 |
| Core API | 题目、作业、复核、申诉、隐私、名册和监护人同意 API 已实现 | 以运行中的 `/docs` 为权威契约。 |
| Grader | M1/M2、E1–E4 编排及受限数学 worker 已实现 | E3/E4 是辅助判分，不自动作最终判定。 |
| OIDC/BFF | BFF、CSRF、HttpOnly 会话已实现，并已通过本机 Keycloak 的学生/教师真实浏览器验收 | 生产 IdP 仍需在试点环境按学校配置复验。 |
| 英语模型 | 生命周期复用、离线制品预取、`/ready` 与每次评分的模型/运行库元数据已实现 | 仍需在可访问 Docker Hub 的环境完成镜像构建与真实校准验收。 |

## Issue #11–#19

| Issue | 当前结论 |
| --- | --- |
| #11 | 答案信封与迁移已实现并有测试。 |
| #12 | 学生草稿隔离已实现，E2E 覆盖。 |
| #13 | 重批任务替换链已实现。 |
| #14 | 最小教师浏览器闭环已实现并由 E2E 覆盖。 |
| #15 | 截止时间与状态已实现。 |
| #16 | CI 覆盖 Python、迁移、Compose、真实 Grader HTTP、Web 和浏览器 E2E；不代表镜像已发布。 |
| #17 | OIDC/BFF 已实现；开发 Realm 已验证学生登录、教师路径隔离、登出与教师登录。 |
| #18 | 固定 revision/digest 的离线模型构建层、生命周期加载和 GradingRun 模型/运行库元数据已实现；镜像构建与真实模型校准待外部网络恢复后验收。 |
| #19 | 生产默认密钥拒绝、处理器主机约束、缺失/矛盾同意 fail-closed 与审计修复命令已实现；密钥托管/恢复演练待完成。 |

## 与 CI 一致的验证命令

```bash
make install-python
make lint
make test
cd apps/web && npm ci && npm test && npm run build
cd apps/web && npx playwright install chromium && npm run test:e2e
```

迁移往返、Compose 构建和真实 Grader HTTP 适配器测试由 `.github/workflows/ci.yml` 的独立 job 执行。
