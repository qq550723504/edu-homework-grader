# 教师班级与学生名册管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让教师在教师端创建自己负责的班级，并安全地单个录入或 CSV 导入该班学生名册。

**Architecture:** 新增 `/v1/teacher` 路由，以 `ClassTeacher` 关联作为班级数据授权边界。名册写入复用既有 `RosterRow`、`parse_roster` 和 `import_roster`；前端通过独立 `teacher-api.ts` 调用新接口。

**Tech Stack:** FastAPI、SQLAlchemy、pytest、Nuxt 4、Vue 3、TypeScript、Vitest。

## Global Constraints

- 教师仅可读写 `class_teachers` 中关联的班级；越权统一返回 `404 resource not found`。
- 不放宽或修改 `/v1/admin/*` 的管理员授权。
- 学生名册继续使用既有监护人同意校验、事务和审计事件。
- 不新增数据库表或迁移；教师端错误提示使用中文。

---

## File structure

- `apps/api/src/edu_grader_api/routers/teacher.py`：教师班级与名册 API。
- `apps/api/src/edu_grader_api/main.py`：注册教师路由。
- `apps/api/tests/test_teacher_roster.py`：教师授权和名册 API 测试。
- `apps/web/app/lib/teacher-api.ts`：教师 API 类型与请求函数。
- `apps/web/tests/teacher-api.test.ts`：客户端单测。
- `apps/web/app/pages/teacher/index.vue`：可操作的教师工作台。

### Task 1: 教师作用域的班级与名册 API

**Files:**
- Create: `apps/api/src/edu_grader_api/routers/teacher.py`
- Modify: `apps/api/src/edu_grader_api/main.py`
- Create: `apps/api/tests/test_teacher_roster.py`

**Interfaces:**
- Consumes: `CurrentPrincipal`、`require_role(Role.TEACHER)`、`Classroom`、`ClassTeacher`、`RosterRow`、`parse_roster()`、`import_roster()`。
- Produces: `GET /v1/teacher/classes`、`POST /v1/teacher/classes`、`POST /v1/teacher/classes/{class_id}/students`、`POST /v1/teacher/classes/{class_id}/students/import`。

- [ ] **Step 1: 写出失败测试**

在 `test_teacher_roster.py` 使用与 `test_roster_import.py` 相同的 SQLite fixture，但令认证返回老师身份；覆盖建班自动关联、同班单个学生写入、同班 CSV 导入和跨教师班级写入被拒绝。

```python
def test_teacher_cannot_write_other_teachers_class(teacher_client, other_class_id):
    response = teacher_client.post(
        f"/v1/teacher/classes/{other_class_id}/students",
        json={"school_id": "S-001", "display_name": "Ada", "under_14": False,
              "guardian_consent_status": "not_required"},
        headers={"Authorization": "Bearer teacher-token"},
    )
    assert response.status_code == 404
```

每个成功写入断言 `Enrollment`、`StudentGuardianConsent` 和 `AuditLog` 存在。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest apps/api/tests/test_teacher_roster.py -v`

Expected: FAIL，`/v1/teacher/*` 路由尚未注册。

- [ ] **Step 3: 实现最小路由**

在路由内实现共用归属检查，并在每个接受 `class_id` 的接口调用它：

```python
def owned_class_or_404(session: Session, principal: CurrentPrincipal, class_id: UUID) -> Classroom:
    classroom = session.scalar(select(Classroom).where(
        Classroom.id == class_id, Classroom.tenant_id == UUID(principal.tenant_id)
    ))
    if classroom is None or session.get(ClassTeacher, (class_id, UUID(principal.user_id))) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    return classroom
```

`POST /classes` 在同一事务中创建 `Classroom`、当前教师的 `ClassTeacher`，并写入 `class.created` 与 `class.teacher_assigned` 审计事件。列表仅返回当前教师关联班级的 `id`、`code`、`name`、`student_count`。

单个学生接口把请求转换为当前班级 `code`、`name` 的 `RosterRow`，再调用 `import_roster()`。CSV 接口先 `parse_roster()`，拒绝任一行班级代码或名称与 URL 班级不一致的文件，然后调用同一服务。注册 `teacher_router` 到 `main.py`。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest apps/api/tests/test_teacher_roster.py apps/api/tests/test_roster_import.py apps/api/tests/test_class_access.py -v`

Expected: PASS，管理员名册导入回归仍通过。

```bash
git add apps/api/src/edu_grader_api/routers/teacher.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_teacher_roster.py
git commit -m "feat: let teachers manage their class rosters"
```

### Task 2: 教师 API 客户端

**Files:**
- Create: `apps/web/app/lib/teacher-api.ts`
- Create: `apps/web/tests/teacher-api.test.ts`

**Interfaces:**
- Consumes: `edu_access_token` Cookie 和 Task 1 的 HTTP 接口。
- Produces: `fetchTeacherClasses()`、`createTeacherClass()`、`createTeacherStudent()`、`importTeacherRoster()`。

- [ ] **Step 1: 写出失败测试**

使用 `vi.fn()` 断言请求方法、URL、Bearer Token 和请求体：

```ts
it('creates a class with the current login token', async () => {
  const request = vi.fn().mockResolvedValue({ id: 'class-1', code: '7A', name: 'Year 7 A', student_count: 0 })
  await createTeacherClass('https://api.example.test', 'token', { code: '7A', name: 'Year 7 A' }, request)
  expect(request).toHaveBeenCalledWith('https://api.example.test/v1/teacher/classes', {
    method: 'POST', headers: { Authorization: 'Bearer token' }, body: { code: '7A', name: 'Year 7 A' }
  })
})
```

为 `importTeacherRoster()` 增加测试：文件使用 `FormData` 的 `file` 字段，且不手动设置 multipart Content-Type。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix apps/web test -- teacher-api.test.ts`

Expected: FAIL，`teacher-api.ts` 不存在。

- [ ] **Step 3: 实现最小客户端**

导出：

```ts
export interface TeacherClass { id: string; code: string; name: string; student_count: number }
export interface CreateTeacherClass { code: string; name: string }
export interface CreateTeacherStudent {
  school_id: string; display_name: string; under_14: boolean
  guardian_consent_status: 'not_required' | 'pending' | 'granted' | 'withdrawn'
  guardian_consent_notice_version?: string; guardian_consent_evidence_reference?: string
}
```

JSON 请求使用 `Authorization: Bearer <token>`；上传使用 `FormData`，保留 `$fetch` 的原始错误供页面呈现。

- [ ] **Step 4: 验证并提交**

Run: `npm --prefix apps/web test -- teacher-api.test.ts student-api.test.ts`

Expected: PASS。

```bash
git add apps/web/app/lib/teacher-api.ts apps/web/tests/teacher-api.test.ts
git commit -m "feat: add teacher roster API client"
```

### Task 3: 可操作的教师工作台

**Files:**
- Modify: `apps/web/app/pages/teacher/index.vue`
- Modify: `apps/web/tests/teacher-api.test.ts`

**Interfaces:**
- Consumes: Task 2 的 `TeacherClass` 和 API 函数、`useRuntimeConfig()`、`edu_access_token` Cookie。
- Produces: “我的班级”、创建班级、单个录入学生和 CSV 导入页面。

- [ ] **Step 1: 增加实时班级数据测试**

```ts
it('returns live class counts for the teacher dashboard', async () => {
  const request = vi.fn().mockResolvedValue([{ id: 'class-1', code: '7A', name: 'Year 7 A', student_count: 3 }])
  await expect(fetchTeacherClasses('https://api.example.test', 'token', request))
    .resolves.toEqual([{ id: 'class-1', code: '7A', name: 'Year 7 A', student_count: 3 }])
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix apps/web test -- teacher-api.test.ts`

Expected: FAIL，直到 `fetchTeacherClasses()` 已实现。

- [ ] **Step 3: 替换静态教师页**

删除固定的 `36`、`82%`、`4` 指标和无行为按钮。挂载时加载班级；提供班级代码/名称表单；班级卡片显示学生数并可选中；选中班级后显示学生 ID、姓名、是否 14 岁以下及监护人同意字段；支持为所选班级上传 CSV。

提交成功后刷新列表并清空草稿。无 Token 显示“正在等待登录状态…”。失败时优先显示服务端 `data.detail`，否则显示“操作失败，请检查填写内容后重试。”。当 `under_14` 为真时才显示同意状态、通知版本和凭据引用字段。

- [ ] **Step 4: 验证并提交**

Run: `npm --prefix apps/web test -- teacher-api.test.ts && npm --prefix apps/web run build`

Expected: PASS，教师页不再包含硬编码指标。

```bash
git add apps/web/app/pages/teacher/index.vue apps/web/tests/teacher-api.test.ts
git commit -m "feat: add teacher class and roster workspace"
```

### Task 4: 使用说明与全量回归

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–3 的教师 API 和工作台。
- Produces: 名册 CSV 契约和交付验证证据。

- [ ] **Step 1: 写明 CSV 契约**

在 README 增加列头：

```text
class_code,class_name,student_school_id,student_display_name,student_under_14,guardian_consent_status,guardian_consent_notice_version,guardian_consent_evidence_reference
```

并说明 CSV 的班级代码与名称必须和页面中所选班级一致。

- [ ] **Step 2: 执行全量验证**

```bash
python -m pytest apps/api/tests -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

Expected: 三条命令均 PASS。

- [ ] **Step 3: 提交交付切片**

```bash
git add README.md
git commit -m "docs: explain teacher roster import"
```

## Self-review

- Spec coverage: Task 1 实现教师作用域、自动关联、名册与审计；Task 2–3 提供教师端入口和错误反馈；Task 4 提供说明与回归验证。
- Placeholder scan: 无 TBD、TODO 或未定义的处理步骤。
- Type consistency: `TeacherClass`、`CreateTeacherClass`、`CreateTeacherStudent` 在 Task 2 定义并由 Task 3 消费；接口路径与设计一致。
