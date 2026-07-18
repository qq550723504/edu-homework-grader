# Edu Homework Grader

面向英语与数学课程的作业提交、自动批改、教师复核和学生订正平台。

> 当前仓库是第一阶段 MVP 的启动骨架。原则是：确定性题型自动批改，主观或低置信度答案进入教师复核。

## 第一阶段范围

- 学生端：查看作业、在线答题、自动保存、提交、查看反馈、订正、申请复核。
- 教师端：建题、布置作业、查看进度、处理复核、发布成绩、查看共性错误。
- 英语：客观题、单词/短语填空、限定句子填空、阅读简答辅助批改。
- 数学：数值题、表达式等价、方程解、分步骤计算。
- 暂不做：手写 OCR、英语作文自动最终评分、几何证明全自动评分、原生 App。

## 技术架构

```text
Nuxt Web（学生端 + 教师端）
            │
            ▼
       FastAPI Core API
       │              │
       ▼              ▼
 PostgreSQL/Redis   Grader Service
                    ├─ English rules
                    └─ Safe Math AST + SymPy
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

开发身份服务会在首次启动时导入 `infra/keycloak/edu-grader-realm.json`。仅本地开发可使用
`.env` 中的 Keycloak 管理员凭据和演示账号；生产环境必须替换为学校的 OIDC 发行方和受控密钥。

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
npm install
npm run dev
```

分别启动后端：

```bash
uvicorn edu_grader_api.main:app --app-dir apps/api/src --reload --port 8000
uvicorn edu_grader.main:app --app-dir services/grader/src --reload --port 8010
```

## 已实现的验证性接口

```http
GET  /health
GET  /v1/meta/capabilities

POST /v1/grade/english/exact
POST /v1/grade/math/numeric
POST /v1/grade/math/expression
```

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

当前 HTTP Grader 适配器已接入 M1；其他题型策略可先完成版本和测试用例配置，待对应 Grader
适配器上线后运行测试。每次测试运行和发布都会保留版本、规则、批改器版本及结果记录。

数学表达式接口只接受受控 JSON AST，不接受未经清洗的 Python、LaTeX 或 SymPy 字符串。当前原型对节点类型、变量、深度、节点数、数字长度和指数范围做白名单限制。

## 质量门槛

- 确定性题型错误放行率不高于 0.5%。
- 批改器异常不得默认判零分，必须进入人工复核。
- 每次评分保存题目版本、规则版本和批改器版本。
- 所有教师改分记录原分、改后分和理由。
- 学生正式提交使用幂等键，答案保存使用乐观锁。

## 下一步

见 [MVP 路线图](docs/roadmap.md) 和仓库 Issues。建议将仓库从 `fastapi` 重命名为 `edu-homework-grader`，以匹配产品范围。

## 学生作答本地保存

学生作答页把草稿和待同步操作保存在浏览器 IndexedDB 中；断网时继续保存，恢复网络后尝试同步。发生版本冲突时保留本地与服务端答案，必须由学生处理，绝不静默覆盖。

学生页面依赖后续 Nuxt 登录层提供短期 `edu_access_token` cookie；该令牌只用于调用已受 OIDC 保护的 API，不在页面中实现登录或长期令牌存储。正式提交在本地队列清空后携带持久化的 `Idempotency-Key`，网络重试不会重复提交。
