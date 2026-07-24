# 项目状态（2026-07-24）

机器可读证据见 [`status-evidence.json`](status-evidence.json)。本页的证据基线提交为：

```text
f6587492750b71f96fa0914942d1e1b72bd3e9be
```

## 状态口径

项目状态必须使用下列四个层级，不能把它们互相替代：

| 状态 | 含义 |
| --- | --- |
| **代码已实现** | 功能和自动化测试已经进入 `main`。 |
| **CI 已验证** | 仓库受保护检查在精确提交上成功；不代表真实学校环境。 |
| **发布环境已验收** | 使用真实 OIDC、PostgreSQL、Provider、Grader 和浏览器，在同一隔离环境完成验收。 |
| **生产已上线** | 学校环境已经部署、监控、备份恢复、回滚和联合签署均完成。 |

当前结论：**代码已实现、仓库 CI 已验证；发布环境尚未完成统一全栈验收，生产尚未上线。**

## 能力状态

| 范围 | 代码/CI 状态 | 尚未完成的外部条件 |
| --- | --- | --- |
| 学生端 | 作业、草稿隔离、同步、提交、反馈、申诉与订正入口已实现；快速浏览器 E2E 使用隔离 SQLite、固定测试身份和确定性判卷替身 | #32 仍需完成网络/401/403/409/422/429/5xx 分类、冲突处理和页面生命周期清理；真实学生试点需 #31/#33 |
| 教师端 | 英语 E1–E4 引导建题、多题作业、题目测试/发布、复核、成绩发布、申诉处理和 AI 出题工作台已实现 | 教师影子模式需 #31 的统一发布环境验收和 #42 的教师校准质量证据 |
| Core API | 课程目录、题库、作业、审核、隐私、名册、监护人同意、Generator、验证、治理和生产评估导出已实现 | 发布环境中的身份、数据库、审计和故障降级仍需统一验证 |
| Grader | M1/M2、E1–E4、受限 MathJSON、LanguageTool 和固定英语嵌入模型已实现；E3/E4 保持教师最终复核 | 性能容量、学校网络和发布环境持续运行由 #31/#33 验收 |
| OIDC/BFF | Nuxt BFF、CSRF、HttpOnly 会话和开发 Keycloak 路径已实现 | 学校托管 HTTPS OIDC、真实角色映射和会话策略需 #31/#33 |
| AI 出题 | 课程约束、真实 Provider、`generator-v3`、候选验证、编辑/重验、拒绝/重生成、原子批量接受和安全转草稿已实现；验证器已加入版本化年级复杂度信号 | 未经审核直接发布仍禁止；先修图、数学语义边界、正式阈值、生产报告和发布环境验收仍缺 |
| AI 治理 | 全局/租户 `active`、`canary`、`paused`、`retired`、Kill Switch、权限和审计基础已实现 | #43 仍需默认版本晋级/回滚、预算、Provider 合规、版权下架和事故手册 |
| AI 评估 | 离线 fail-closed 门禁和生产形态只读导出/显式版本比较已实现 | #99 需首次真实只读数据库报告；#42 需教师黄金集、最终阈值、线上反馈和 shadow/canary 证据 |
| 部署 | Compose、Kubernetes 清单和 SHA 镜像发布工作流存在 | 清单存在不等于环境已部署；#33 的实际 rollout、监控、备份恢复和回滚尚未验收 |

## 可验证的仓库证据

### 最近完整 CI

PR #101 的最终测试提交：

```text
88f0b81c152bcf5166d9d216a7f3a115e322f59a
```

CI Run #259（Run ID `30032846201`）成功，包含：

- `changes`
- `python`：Ruff、完整 Python 测试和六题型确定性验证语料
- `migrations`：PostgreSQL upgrade/downgrade/re-upgrade
- `compose`：配置校验和 API/Web 镜像构建
- `live-grader-integration`：真实 Grader/LanguageTool HTTP 适配器
- `web`：单元测试、Nuxt production build 和 E2E 进程管理
- `browser-e2e`：Chromium 学生/教师快速垂直链路

AI evaluation gate Run #38（Run ID `30032847548`）成功。

这些结果证明仓库基线通过自动化门禁，**不证明学校发布环境已经验收或生产已上线**。

### 真实 AI Provider

受保护环境的 Live generator Provider acceptance Run `30024119371` 已对精确 PR head 验证：

```text
generator-v3
├── M1
├── M2
├── E1
└── E4
```

该验收覆盖严格 Structured Outputs、M1/M2 answer assertions 和 E4 reading material；未使用 Fake Provider 回退。

### 当前生成与验证版本

| 项目 | 当前值 |
| --- | --- |
| Prompt | `generator-v3` |
| Validator | `verification-v6` |
| Ruleset | `rules-v6` |
| Grade complexity rules | `grade-complexity-v1`（历史平面规则归一为 `grade-complexity-legacy-v0`） |
| Operational evaluation exporter | `operational-ai-evaluation-export-v1` |
| 默认策略 | `M1@1`、`M2@2`、`E1@2`、`E2@1`、`E3@1`、`E4@2` |

### 英语嵌入模型

| 字段 | 固定值 |
| --- | --- |
| model ID | `sentence-transformers/all-MiniLM-L6-v2` |
| revision | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` |
| tree digest | `sha256:84714cdabb16d132cbe6e1a4cbd21167abd09eccbdaf69dd053136ae68cc7c17` |

Grader Dockerfile 两个阶段均固定上述值。Compose/CI 已成功构建真实 Grader 依赖并通过 HTTP 集成；不再保留“等待 Docker Hub 网络后才能验证镜像”的旧结论。

## 关键 Issue 状态

| Issue | 当前结论 |
| --- | --- |
| #29 | 英语 E1–E4 教师建题已完成。 |
| #30 | 多题、多题型作业编排已完成。 |
| #31 | 开放：真实 Keycloak/OIDC、PostgreSQL、Provider、Grader 和浏览器统一验收。 |
| #32 | 开放：学生同步错误分类、退避、冲突和页面生命周期。 |
| #33 | 开放：实际试点部署、监控、备份恢复、容量、回滚和联合签署。 |
| #34 | 已完成：状态页、机器证据和文档完整性门禁已进入 `main`。 |
| #39 | Generator 与真实 Provider 已完成。 |
| #40 | 候选题验证主体已完成。 |
| #41 | 教师 AI 出题工作台已完成。 |
| #42 | 开放：教师黄金集、正式阈值、线上反馈和 shadow/canary。 |
| #43 | 开放：运营治理剩余项。 |
| #83 | 开放：年级复杂度首个切片已实现；仍缺先修图、数学语义和容量边界。 |
| #99 | 开放：首次真实只读数据库评估、成本完整性和发布后修正映射。 |
| #76 | 开放：AI Authoring Teacher Shadow MVP 里程碑。 |

## 当前发布阻断顺序

```text
#83 先修/数学语义边界 ─┐
#99 正式生产评估 ──────┼→ #42 教师阈值与线上证据 ─┐
#43 运营治理 ──────────┘                          ├→ #31 统一全栈验收
#32 学生同步可靠性 ──────────────────────────────┤
                                                    └→ #33 学校试点部署
```

#34 已完成，后续状态漂移由 `Docs integrity` 自动阻止。

## 与 CI 一致的本地验证命令

```bash
make install-python
make lint
make test
make verification-regression
python scripts/check_docs_status.py

cd apps/web
npm ci
npm test
npm run build
npm run test:e2e-runtime
npx playwright install --with-deps chromium
npm run test:e2e
```

迁移往返、Compose 构建和真实 Grader HTTP 测试仍由 `.github/workflows/ci.yml` 的独立 Job 执行。真实 Provider 与生产评估导出只能在对应的受保护 Environment 中手动运行。
