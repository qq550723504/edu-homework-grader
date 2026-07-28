# 生产 CD 运维手册

本手册适用于 `qq550723504/edu-homework-grader` 的生产发布与回滚。本文档和当前
分支只提供自动化代码与操作说明；**本分支没有创建或修改 GitHub Environment、
Environment Secret、审批规则、分支规则，也没有连接或变更生产 Kubernetes。**

## 启用前检查

在允许首次生产发布前，由仓库和集群管理员完成以下非源码配置：

1. 使用 Repository Ruleset 或 Branch Protection 保护 `main`，至少要求 PR 和 CI
   通过后才能合并。
2. 在 GitHub 仓库创建名为 `production` 的 Environment：
   - 配置至少一名 Required reviewer；建议禁止发起人自行批准。
   - 在 Environment 的 Deployment branches and tags 中选择仅允许 `main`，并确认
     `main` 是受保护分支。不能只依赖工作流里的 `github.ref` 条件；服务端
     Environment 分支限制才是防止分支版本工作流取得生产凭据的必要边界。
3. 确认操作者的 `gh` 已登录固定仓库，`kubectl` 当前 context 指向生产集群，并且
   有权在 `edu-homework-grader` namespace 应用部署身份 RBAC 和请求
   ServiceAccount Token。
4. 生产运行时 Secret、数据库和入口证书必须已由各自的受控流程配置。下面的
   bootstrap 不读取或创建应用 Secret。

Required reviewers 和仅允许受保护 `main` 两项缺一不可；未完成时不要上传
`KUBECONFIG_B64`，也不要批准任何生产 job。

## 一次性创建部署凭据

先预览固定目标，不会写入：

```powershell
pwsh -NoProfile -File ./scripts/k8s/bootstrap-production-deployer.ps1 `
  -ConfirmProductionCredential -WhatIf
```

核对当前 Kubernetes context、GitHub 登录和预览目标后，再执行带交互确认的命令：

```powershell
pwsh -NoProfile -File ./scripts/k8s/bootstrap-production-deployer.ps1 `
  -ConfirmProductionCredential -Confirm
```

`-ConfirmProductionCredential` 是必填的生产意图开关，`-Confirm` 会在写入前要求
操作者确认。脚本只面向固定仓库和 namespace，并执行以下写入：

- server-side apply
  `infra/k8s/production/github-production-deployer-rbac.yaml`，在
  `edu-homework-grader` 创建或更新 `github-production-deployer`
  ServiceAccount、namespace Role 和 RoleBinding；
- 请求最长 `8760h` 的 ServiceAccount Token，并拒绝集群签发的剩余寿命不足
  `720h` 的 Token；
- 在内存中生成最小 kubeconfig，直接以标准输入上传为 GitHub `production`
  Environment Secret `KUBECONFIG_B64`。

脚本不会把 kubeconfig 写到磁盘或打印到控制台。不要把 Secret 值复制到命令行、
工单、聊天或日志。发布 runner 只把它解码到权限受限的临时文件，job 结束时始终
删除该文件。

## 正常发布

1. PR 全部检查通过后合并到受保护的 `main`。
2. 合并后的准确 revision 运行 `CI`。只有 CI 成功，发布工作流才继续；纯
   `docs/**` 或 Markdown 变更会跳过镜像与部署。
3. `Publish production images` 为 API、Grader、Web 和 LanguageTool 构建同一个
   40 位 CI head SHA 标签的四个 GHCR 镜像，并收集每个不可变镜像 digest。
4. 发布工作流将该 SHA 和四个 digest 交给真实 PostgreSQL、Grader 与
   LanguageTool 的发布证据工作流。证据 Artifact 通过前，部署 job 不会创建。
5. `deploy` job 在 `production` Environment 等待 Required reviewer。审批者核对
   commit、PR、CI 和四个镜像后批准；部署脚本以相同 digest 渲染实际的
   `repository@sha256:…` 镜像引用。
6. job 在取得集群凭据前及实际部署前各检查一次：若 `main` 已出现更晚的代码
   变更，旧版本拒绝部署；仅有文档后继时仍可部署该待审版本。
7. 部署脚本使用准确 SHA 渲染临时 Kustomize release，应用命名空间内工作负载，
   等待四个 Deployment、API Service ready endpoint 和公网
   `https://edu.getkr.com/`。结果写入 GitHub Actions step summary。

不要用 `latest`、分支名或缩短 SHA 代替发布 SHA，也不要在集群中手工改镜像来
绕过审批历史。

## 自动回滚与发布失败

部署前，脚本会捕获 API init/API、Grader、Web、LanguageTool 和激活过期 CronJob
当前运行的六个准确镜像引用。若 apply 后的 rollout、API ready endpoint 或公网
检查失败，它会用这些已捕获引用重新渲染并应用回滚版本，然后再次等待四个
Deployment rollout。

- Summary 为 `failed; rollback succeeded`：集群已恢复捕获的旧镜像，但发布
  workflow 仍然失败。保留现场，关联失败 SHA，分析 Actions 日志和平台日志，
  修复后走新 PR；不要盲目重新运行同一个发布。
- Summary 为 `failed; rollback failed`：按高优先级生产事故处理。停止新的生产
  审批，通知值班和集群管理员，使用独立的授权运维身份检查 workload、事件和
  日志。确认集群状态后，可选择下文的已知良好 SHA 手动回滚；若同一部署路径仍
  失败，按事故变更流程人工恢复，而不是反复批准。
- 若在首次 apply 前失败，集群未发生变更；修复凭据、镜像或配置问题后重新走
  正常发布。

## 手动回滚到既有 SHA

1. 从成功的历史 `Publish production images` run、发布 Summary 或 GHCR 记录中
   选择一个已知良好的**完整、40 位、小写十六进制 commit SHA**。
2. 在 GitHub Actions 打开 `Roll back production`，点击 `Run workflow`，分支
   必须选择 `main`，在 `image_sha` 填入该 SHA。
3. rollback job 先在 `production` Environment 等待 Required reviewer。审批者
   核对请求的目标 SHA 和事故记录；此时 job 尚未执行镜像预检。
4. 批准后，job 才验证 SHA，并确认 API、Grader、Web 和 LanguageTool 四个 GHCR
   manifest 全部存在。两项预检都通过后才解码临时 kubeconfig、接触集群，并使用
   受信任的 `main` 部署脚本执行 rollout、健康检查和失败时自动恢复逻辑。

缺少任何一个镜像、SHA 不是严格 40 位小写格式、选择非 `main` ref 时，workflow
都会停止；SHA 和镜像错误虽然在审批后报告，但仍发生在 kubeconfig 解码和集群
访问前。不要用手工推送同名标签补齐历史版本。

## 健康检查与日志

自动部署检查四个 Deployment rollout、API Service 是否有 ready endpoint，以及
公网 `GET https://edu.getkr.com/`。可供授权内网排障使用的运行时健康端点包括：

- API：`http://api:8000/health` 和依赖数据库的 `http://api:8000/ready`；
- Grader：`http://grader:8010/health` 和模型就绪检查
  `http://grader:8010/ready`；
- LanguageTool：`http://languagetool:8010/v2/languages`；
- Web：`http://web:3000/`。

Kubernetes 为 API 和 Grader 配置的 `readinessProbe` 是各自的 `/ready`，没有把
`/health` 配为 Kubernetes probe。API Pod 的 `/ready` 成功后才会进入 API Service
ready endpoints，这也是部署脚本使用的 API 集群内就绪信号；LanguageTool 和 Web
的 readiness probe 分别使用上表的 `/v2/languages` 和 `/`。

Ingress 只把公网 `/` 路径交给 Web；不要为了排障临时暴露内部 health endpoint。
优先查看 GitHub Actions run 日志及 step summary，其中包含目标 SHA、捕获的旧镜像、
开始/结束时间和结果，不包含 kubeconfig。

`github-production-deployer` 无权读取 Pod、Pod log 或 Secret。需要进一步排障时，
使用单独的、经审计的只读运维身份，例如：

```powershell
kubectl -n edu-homework-grader get deployments
kubectl -n edu-homework-grader get events --sort-by=.lastTimestamp
kubectl -n edu-homework-grader logs deployment/api --all-containers --since=30m
kubectl -n edu-homework-grader logs deployment/grader --all-containers --since=30m
```

不得下载 `KUBECONFIG_B64` 充当日常排障凭据。

## `KUBECONFIG_B64` 保留、轮换与撤销

- GitHub 仅把该值保留在 `production` Environment Secret；在凭据台账记录签发
  日期、负责人和下次轮换日期，不能记录 Secret 值。轮换日期必须早于集群实际
  Token 到期；脚本的最低可接受寿命为 720 小时。
- 例行轮换前停止生产审批并确认没有 deployment 正在运行。本项目把轮换按
  “删除 Secret 和旧 ServiceAccount，再 bootstrap 重签”执行。仅重新运行
  bootstrap 虽会替换 GitHub Secret，但旧 Token 仍可能有效到期，不能视为完成
  轮换或撤销。
- 怀疑泄露、人员权限变化、集群 CA/端点变化或 RBAC 事件时，先立即删除
  Environment Secret 并撤销集群身份：

```powershell
gh secret delete KUBECONFIG_B64 --env production `
  --repo qq550723504/edu-homework-grader
kubectl -n edu-homework-grader delete rolebinding github-production-deployer
kubectl -n edu-homework-grader delete serviceaccount github-production-deployer
```

删除后保持生产审批暂停。调查完成时重新核对 Environment 的 reviewer 和仅
`main` 分支限制，再运行带显式确认的 bootstrap；它会重新创建 RBAC 身份并上传
新 Secret。最后用新的普通 PR 发布验证，不要把真实凭据用于本地试运行。
