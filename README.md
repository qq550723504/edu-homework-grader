# Edu Homework Grader

面向英语与数学课程的作业提交、自动批改、教师复核和学生订正平台。

> 当前仓库已具备第一阶段浏览器垂直切片，但尚未生产就绪。能力边界、已知限制和试点条件见 [项目状态](docs/project-status.md)。

## 第一阶段范围

- 学生端：查看作业、在线答题、自动保存、提交、查看反馈、订正、申请复核。
- 教师端：建题、布置作业、查看进度、处理复核、发布成绩、查看共性错误。
- 英语：客观题、单词/短语填空、限定句子填空、阅读简答辅助批改。
- 数学：数值题、表达式等价、方程解、分步骤计算。
- 暂不做：手写 OCR、英语作文自动最终评分、几何证明全自动评分、原生 App。

## 技术架构

```text
Nuxt Web（OIDC BFF + HttpOnly 会话）
            │
            ▼
 FastAPI Core API ─── processor-policy
       │              │
       ▼              ▼
PostgreSQL/Redis   Grader Service ─── LanguageTool
                    ├─ English rules + 本地嵌入模型
                    └─ Safe Math AST + SymPy

Keycloak 提供开发 OIDC；浏览器 E2E 启动隔离 API/Nuxt 与 SQLite，使用固定测试身份和确定性替身。
```

仓库采用单体仓库结构：

```text
apps/
  api/                 核心业务 API
  web/                 学生端与教师端 Nuxt 应用
services/
  grader/              独立批改服务
docs/                   架构、范围、路线图与 ADR
```

## 本地启动

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

启动后：

- Web：http://localhost:3000
- Core API：http://localhost:8000/docs
- Grader：http://localhost:8010/docs
- PostgreSQL：localhost:5432
- Redis：localhost:6379
- Keycloak（开发身份服务）：http://localhost:8080

开发身份服务会在首次启动时导入 `infra/keycloak/edu-grader-realm.json`。`.env` 中的 Keycloak
管理员凭据和演示账号仅用于本机开发；生产部署不得使用 `.env.example`、Compose 默认值或本地
Keycloak，必须由受控 Secret Manager 注入数据库凭据和 `AUDIT_HMAC_KEY`，并使用学校托管的 HTTPS OIDC
发行方。

首次启动 API 前执行迁移与管理员引导：

```bash
docker compose exec api python -m alembic -c alembic.ini upgrade head
docker compose exec api python -m edu_grader_api.bootstrap
```

可重复运行的 API 质量检查：

```bash
make api-test
make api-lint
make question-test
```

### 不使用 Docker

Python 需要 3.12 或更高版本，Node.js 建议使用 22 LTS。

```bash
make install-python
make test

cd apps/web
npm ci
npm run dev
```

分别启动后端：

```bash
uvicorn edu_grader_api.main:app --app-dir apps/api/src --reload --port 8000
uvicorn edu_grader.main:app --app-dir services/grader/src --reload --port 8010
```

### 浏览器验收测试

首次运行先安装 Playwright 的 Chromium：

```bash
cd apps/web
npx playwright install chromium
npm run test:e2e
```

后续在 `apps/web` 目录运行 `npm run test:e2e` 即可。该命令会启动仅监听本机回环地址的
临时 API 和 Nuxt，使用虚构的种子数据，并在结束后删除临时 SQLite 数据库。此验收测试使用
固定的测试令牌，不验证生产 Keycloak 登录。学生的打开作业、输入、同步、提交与刷新均通过
浏览器完成：学生提交、教师查看证据并复核/发布、学生申诉、教师批准订正机会均通过页面验收。
E2E 使用固定身份、确定性判卷替身和临时 SQLite；不验证真实 Keycloak 登录、网络模型下载或生产 Grader 模型。

CI 使用与本地相同的质量门禁：`make lint && make test`、`make web-install && make web-test &&
make web-build`，以及 `make web-e2e`。迁移回滚验证需要一个 PostgreSQL 实例，并可运行：

```bash
DATABASE_URL=postgresql+psycopg://edu_grader:change-me@localhost:5432/edu_grader \
  python -m alembic -c apps/api/alembic.ini upgrade head
DATABASE_URL=postgresql+psycopg://edu_grader:change-me@localhost:5432/edu_grader \
  python -m alembic -c apps/api/alembic.ini downgrade base
```

## 核心 API

运行 API 后，完整且可交互的契约位于 [Core API OpenAPI](http://localhost:8000/docs)；Grader OpenAPI 位于 `http://localhost:8010/docs`。主要路由分组：

- 身份、班级、名册与监护人同意：`/v1/me`、`/v1/classes`、`/v1/admin/*`。
- 题库、版本与作业：`/v1/questions`、`/v1/question-versions/*`、`/v1/assignments`。
- 学生作答、申诉与隐私：`/v1/student/*`、`/v1/privacy-requests`。
- 教师复核、申诉和成绩发布：`/v1/review-tasks`、`/v1/review-appeals`、`/v1/review-metrics`、`/v1/assignments/*/publish-results`。

## 题目版本与发布门禁

教师使用 `POST /v1/questions` 创建租户内题目和第一个草稿版本。规则 JSON 仅可使用平台维护的
`M1`（数值）、`M2`（表达式）、`E1`（英文精确匹配）和 `E4`（英文辅助简答）策略版本；API 会在保存前返回带 JSON Pointer 的 422 校验错误。

发布前，为草稿添加 `correct`、`incorrect`、`empty` 和 `boundary` 测试用例，并调用
`POST /v1/question-versions/{version_id}/test-runs`。只有同一草稿最近一次完整测试通过，
`POST /v1/question-versions/{version_id}/publish` 才会成功；已发布版本须通过
`POST /v1/questions/{question_id}/versions` 创建后继草稿，不能原地修改。

首次部署或升级后执行：

```bash
docker compose exec api python -m alembic -c alembic.ini upgrade head
```

当前 HTTP Grader 适配器已接入 M1 和 M2@2（受限 MathJSON）；M2@1 保留原有兼容策略。每次测试运行和发布都会保留版本、规则、批改器版本及结果记录。

英语 E4 使用 `sentence-transformers/all-MiniLM-L6-v2`（Apache-2.0），固定为提交 `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` 和 tree digest `sha256:709383867deb097dbd130f792d5f60065aa34d33d17a14033fdceeb7a6a1c10b`。Grader 镜像构建时下载并校验该制品；运行时以 `local_files_only=True` 加载，绝不联网下载。升级必须同时更新 revision、digest、校准样例和部署验证。

数学表达式接口只接受受控 JSON AST，不接受未经清洗的 Python、LaTeX 或 SymPy 字符串。当前原型对节点类型、变量、深度、节点数、数字长度和指数范围做白名单限制。
学生端以 MathLive 同时保存展示用 LaTeX 和 MathJSON，服务端会再次验证并只将规范化 AST 交给隔离 worker。默认 worker 限制为 1 CPU 秒、512 MiB 地址空间和 1 秒墙钟；可用 `GRADER_MATH_CPU_SECONDS`、`GRADER_MATH_MEMORY_BYTES` 与 `GRADER_MATH_TIMEOUT_SECONDS` 调整。Compose 还对 Grader 设定 0.5 CPU、1536 MiB 和 64 PID 上限。超时或资源耗尽会进入教师复核，绝不自动判零。

## 质量门槛

- 确定性题型错误放行率不高于 0.5%。
- 批改器异常不得默认判零分，必须进入人工复核。
- 每次评分保存题目版本、规则版本和批改器版本。
- 所有教师改分记录原分、改后分和理由。
- 学生正式提交使用幂等键，答案保存使用乐观锁。
- 试点数据处理字段、访问角色和保存期限见 [数据清单](docs/data-inventory.md)。

## 下一步

见 [项目状态](docs/project-status.md)、[文档索引](docs/README.md)、[试点上线检查表](docs/pilot-checklist.md) 和 [MVP 路线图](docs/roadmap.md)。

## 学生作答本地保存

学生作答页把草稿和待同步操作保存在浏览器 IndexedDB 中；断网时继续保存，恢复网络后尝试同步。发生版本冲突时保留本地与服务端答案，必须由学生处理，绝不静默覆盖。

Nuxt 通过 OIDC Authorization Code + PKCE 建立服务端 BFF 会话。访问令牌只保存在加密、HttpOnly 会话中；浏览器代码不读取令牌，Core API 调用经 `/api/core/*` 代理并使用 CSRF 保护。正式提交在本地队列清空后携带持久化的 `Idempotency-Key`，网络重试不会重复提交。

