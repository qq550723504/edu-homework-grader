# Multi-Question Assignment Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Enable atomic creation and revision of ordered, single-subject, multi-question assignments.

**Architecture:** A full ordered question-version list is validated and persisted transactionally by the API. The teacher workspace owns a small composition state model for selection and ordering; it submits the complete list on save. Student retrieval remains unchanged because it already reads AssignmentItem by position.

**Tech Stack:** FastAPI, SQLAlchemy, Nuxt 4, Vue 3, TypeScript, Vitest, Playwright, pytest.

## Global Constraints

- English accepts E1–E4 only; mathematics accepts M1/M2 only.
- Empty, duplicate, unpublished, tenant-foreign, and cross-subject selections return HTTP 422.
- Positions are server-generated as continuous 1..n; clients do not supply positions for complete composition.
- Drafts alone are mutable; published assignments remain frozen.
- Do not add a drag-and-drop dependency; use accessible move controls.

---

### Task 1: Make assignment composition atomic and subject-safe

**Files:**

- Modify: apps/api/src/edu_grader_api/services/assignments.py
- Modify: apps/api/src/edu_grader_api/routers/assignments.py
- Modify: apps/api/tests/test_assignments.py

**Interfaces:**

- Produces replace_assignment_items(session, assignment, teacher_id, question_version_ids) -> list[AssignmentItem].
- Extends create_assignment with question_version_ids.
- Produces PUT /v1/assignments/{assignment_id} with title, due_at, submission_rule, and question_version_ids.

- [ ] **Step 1: Write focused failing API tests.**

~~~python
def test_teacher_creates_ordered_english_assignment_atomically(client, session):
    teacher, classroom, english_versions = published_english_versions(session, count=5)
    response = client.post('/v1/assignments', headers=authorize(client, teacher), json={
        'class_id': str(classroom.id), 'title': 'Reading', 'subject': 'english',
        'due_at': '2026-08-01T12:00:00Z', 'submission_rule': {'allow_late': False},
        'question_version_ids': [str(version.id) for version in english_versions],
    })
    assert response.status_code == 201
    assert response.json()['positions'] == [1, 2, 3, 4, 5]

def test_composition_rejects_cross_subject_duplicate_and_empty_input(client, session):
    teacher, classroom, math_version, english_version = mixed_published_versions(session)
    for ids in ([], [str(math_version.id), str(math_version.id)], [str(english_version.id)]):
        response = client.post('/v1/assignments', headers=authorize(client, teacher), json=assignment_payload(
            classroom, subject='mathematics', question_version_ids=ids,
        ))
        assert response.status_code == 422
~~~

- [ ] **Step 2: Run the focused API tests.**

Run: pytest tests/test_assignments.py -q

Expected: failure because CreateAssignmentRequest has no question_version_ids and creation persists no items.

- [ ] **Step 3: Implement validation and transactional replacement.**

~~~python
SUBJECT_QUESTION_TYPES = {
    'english': frozenset({'E1', 'E2', 'E3', 'E4'}),
    'mathematics': frozenset({'M1', 'M2'}),
}

def replace_assignment_items(session, assignment, *, teacher_id, question_version_ids):
    _require_assignment_teacher(session, assignment, teacher_id)
    if assignment.status is not AssignmentStatus.DRAFT:
        raise AssignmentStateError('only draft assignments can change items')
    versions = _composition_versions(session, assignment, question_version_ids)
    session.query(AssignmentItem).filter_by(assignment_id=assignment.id).delete()
    items = [AssignmentItem(assignment=assignment, question_version=version, position=index)
             for index, version in enumerate(versions, start=1)]
    session.add_all(items)
    session.flush()
    return items
~~~

Validate the list before deleting existing items. Add the request field, route-level AssignmentValidationError to 422 mapping, and an update route that updates assignment fields plus calls replacement inside one session.begin block.

- [ ] **Step 4: Run API tests and static checks.**

Run: pytest tests/test_assignments.py tests/test_assignment_models.py -q && ruff check src tests

Expected: all tests pass and Ruff has no findings.

- [ ] **Step 5: Commit.**

~~~powershell
git add apps/api/src/edu_grader_api/services/assignments.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/tests/test_assignments.py
git commit -m "feat(api): compose multi-question assignments atomically"
~~~

### Task 2: Expose composition metadata and client API operations

**Files:**

- Modify: apps/api/src/edu_grader_api/routers/questions.py
- Modify: apps/web/app/lib/teacher-api.ts
- Modify: apps/web/tests/teacher-api.test.ts

**Interfaces:**

- TeacherQuestionVersion adds max_score: number.
- CreateAssignmentInput adds question_version_ids: string[].
- updateAssignment(request, csrfToken, assignmentId, input) performs PUT /api/core/v1/assignments/{assignmentId}.

- [ ] **Step 1: Write failing web API tests.**

~~~ts
it('sends the full ordered question list when creating an assignment', async () => {
  const request = vi.fn().mockResolvedValue({ id: 'assignment-1', status: 'draft', positions: [1, 2] })
  await createAssignment(request, 'csrf-token', {
    class_id: 'class-1', title: 'Algebra', subject: 'mathematics',
    due_at: '2026-07-30T00:00:00Z', submission_rule: { allow_late: false },
    question_version_ids: ['m1', 'm2'],
  })
  expect(request).toHaveBeenCalledWith('/api/core/v1/assignments', expect.objectContaining({
    body: expect.objectContaining({ question_version_ids: ['m1', 'm2'] }),
  }))
})
~~~

- [ ] **Step 2: Run the focused Vitest file.**

Run: npm test -- tests/teacher-api.test.ts

Expected: TypeScript error because question_version_ids and updateAssignment do not exist.

- [ ] **Step 3: Implement the API contract.**

Question-list serialization computes max_score from rule_json when it is a positive number, otherwise 1. Update Request permits PUT and teacher-api Request supports method PUT.

- [ ] **Step 4: Run contract tests.**

Run: npm test -- tests/teacher-api.test.ts

Expected: PASS.

- [ ] **Step 5: Commit.**

~~~powershell
git add apps/api/src/edu_grader_api/routers/questions.py apps/web/app/lib/teacher-api.ts apps/web/tests/teacher-api.test.ts
git commit -m "feat(web): expose assignment composition contract"
~~~

### Task 3: Build teacher composition state and editing UI

**Files:**

- Create: apps/web/app/lib/assignment-composition.ts
- Create: apps/web/tests/assignment-composition.test.ts
- Modify: apps/web/app/pages/teacher/index.vue
- Modify: apps/web/tests/teacher-workbench.test.ts

**Interfaces:**

- Produces availableQuestionsForSubject, addQuestionToComposition, moveQuestion, removeQuestion, compositionSummary.
- Composition entries use TeacherQuestionVersion and preserve selection order.
- Teacher page exposes subject selection, question picker, preview, save composition, and draft update actions.

- [ ] **Step 1: Write failing pure-state tests.**

~~~ts
it('keeps one ordered subject-compatible copy of each question', () => {
  const selected = addQuestionToComposition([], m1)
  expect(addQuestionToComposition(selected, m1)).toEqual(selected)
  expect(moveQuestion([m1, m2], 1, -1)).toEqual([m2, m1])
  expect(compositionSummary([m1, m2])).toMatchObject({ count: 2, totalScore: 3, types: { M1: 1, M2: 1 } })
})
~~~

- [ ] **Step 2: Run the state tests.**

Run: npm test -- tests/assignment-composition.test.ts

Expected: module-not-found failure.

- [ ] **Step 3: Implement state helpers and wire the page.**

Use a subject select with values english and mathematics. Render only published compatible questions; use add, move-up, move-down, and remove buttons. Display title, prompt, type, policy version, max score, count, total, and type distribution. Render a student preview using selected prompts only. Save invokes createAssignment for no draft ID or updateAssignment for an existing draft. Reject empty selections before requests and display server 422 messages.

- [ ] **Step 4: Run focused UI tests and production build.**

Run: npm test -- tests/assignment-composition.test.ts tests/teacher-api.test.ts tests/teacher-workbench.test.ts && npm run build

Expected: all tests pass and Nuxt build exits 0.

- [ ] **Step 5: Commit.**

~~~powershell
git add apps/web/app/lib/assignment-composition.ts apps/web/tests/assignment-composition.test.ts apps/web/app/pages/teacher/index.vue apps/web/tests/teacher-workbench.test.ts
git commit -m "feat(web): compose multi-question assignments"
~~~

### Task 4: Verify teacher and student workflows through browsers

**Files:**

- Modify: apps/web/e2e/student-vertical-slice.spec.ts
- Modify: apps/api/tests/test_ci_e2e_workflow.py only if the new scenario requires an existing workflow allow-list.

**Interfaces:**

- Adds browser cases for one five-item English composition with three English types and one M1/M2 mathematics composition.
- Asserts the student assignment detail presents question IDs in teacher-selected order.

- [ ] **Step 1: Write the failing Playwright scenarios.**

~~~ts
test('teacher composes an ordered mathematics assignment and student receives that order', async ({ page, request }) => {
  await establishTeacherSession(page)
  await page.goto(`${webBaseUrl}/teacher#assignments`)
  await page.getByLabel('作业学科').selectOption('mathematics')
  await page.getByRole('button', { name: '添加题目 M1' }).click()
  await page.getByRole('button', { name: '添加题目 M2' }).click()
  await page.getByRole('button', { name: '上移 M2' }).click()
  await page.getByRole('button', { name: '保存编排' }).click()
  const detail = await assignmentDetail(request, createdAssignmentId, studentHeaders)
  expect(detail.items.map((item: { question_type: string }) => item.question_type)).toEqual(['M2', 'M1'])
})
~~~

Add a five-item English case using at least E1, E2, and E4, then assert the create payload subject is english and all positions are continuous.

- [ ] **Step 2: Run the named scenarios.**

Run: npx playwright test e2e/student-vertical-slice.spec.ts --grep "composes an ordered"

Expected: failure because the composition controls and atomic API payload do not exist.

- [ ] **Step 3: Add only deterministic E2E fixture data required for the scenarios.**

The fixture creates tenant-local published E1, E2, E4, M1, and M2 versions through public API/service setup. It must not mock the composition API or bypass question subject validation.

- [ ] **Step 4: Run complete regression checks.**

Run: npm test && npm run test:e2e

Run: pytest tests/test_assignments.py tests/test_assignment_models.py tests/test_ci_e2e_workflow.py -q

Expected: all commands pass.

- [ ] **Step 5: Commit.**

~~~powershell
git add apps/web/e2e/student-vertical-slice.spec.ts apps/api/tests/test_ci_e2e_workflow.py
git commit -m "test: cover multi-question assignment composition"
~~~

