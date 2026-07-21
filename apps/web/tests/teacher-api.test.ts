import { describe, expect, it, vi } from 'vitest'

import { batchConfirmReviewTasks, createAssignment, createQuestion, createTeacherRosterClass, createTeacherRosterStudent, createTestCase, decideReviewTask, decideTeacherAppeal, fetchQuestionPolicyCatalog, fetchQuestionTestCaseTemplates, fetchTeacherRosterClasses, fetchTeacherWorkspace, importTeacherRoster, previewQuestionTestCase, publishAssignment, publishAttemptResults, publishQuestionVersion, runQuestionTests, updateAssignment } from '../app/lib/teacher-api'

describe('teacher workspace API', () => {
  it('loads classes, question versions, assignments and review metrics through the BFF', async () => {
    const request = vi.fn().mockResolvedValue({})

    await fetchTeacherWorkspace(request)

    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/classes')
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/questions')
    expect(request).toHaveBeenNthCalledWith(3, '/api/core/v1/assignments')
    expect(request).toHaveBeenNthCalledWith(4, '/api/core/v1/review-metrics')
    expect(request).toHaveBeenNthCalledWith(5, '/api/core/v1/review-tasks')
  })

  it('creates a question through the BFF with its session CSRF token', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'version-1', status: 'draft' })

    await createQuestion(request, 'csrf-token', {
      title: 'Addition',
      prompt: 'What is 2 + 3?',
      question_type: 'M1',
      policy_version: '1',
      rule: { expected: 5 },
    })

    expect(request).toHaveBeenCalledWith('/api/core/v1/questions', {
      method: 'POST',
      headers: { 'X-CSRF-Token': 'csrf-token' },
      body: {
        title: 'Addition',
        prompt: 'What is 2 + 3?',
        question_type: 'M1',
        policy_version: '1',
        rule: { expected: 5 },
      },
    })
  })

  it('loads the API-owned question policy catalog through the BFF', async () => {
    const request = vi.fn().mockResolvedValue({ policies: [{ question_type: 'E4', policy_version: '2' }] })

    await expect(fetchQuestionPolicyCatalog(request))
      .resolves.toEqual([{ question_type: 'E4', policy_version: '2' }])
    expect(request).toHaveBeenCalledWith('/api/core/v1/question-policy-catalog')
  })

  it('loads editable test templates and previews their expected result through the BFF', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ templates: [{ category: 'correct', answer: { format: 'text-v1', text: 'cat' } }] })
      .mockResolvedValueOnce({ decision: 'auto_accepted', score: 1, evidence: { criterion: 'accepted_answers' }, grader_version: 'grader@1' })

    await expect(fetchQuestionTestCaseTemplates(request, 'version-1')).resolves.toEqual([
      { category: 'correct', answer: { format: 'text-v1', text: 'cat' } },
    ])
    await expect(previewQuestionTestCase(request, 'csrf-token', 'version-1', { format: 'text-v1', text: 'cat' })).resolves.toMatchObject({
      decision: 'auto_accepted', score: 1,
    })
    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/question-versions/version-1/test-case-templates')
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/question-versions/version-1/test-case-preview', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { answer: { format: 'text-v1', text: 'cat' } },
    })
  })

  it('runs and publishes a version through CSRF-protected BFF endpoints', async () => {
    const request = vi.fn().mockResolvedValue({ status: 'passed', case_runs: [] })

    await createTestCase(request, 'csrf-token', 'version-1', {
      category: 'correct', answer: { format: 'text-v1', text: '5' }, expected_decision: 'auto_accepted', expected_score: 1, expected_evidence: {},
    })
    await runQuestionTests(request, 'csrf-token', 'version-1')
    await publishQuestionVersion(request, 'csrf-token', 'version-1')

    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/question-versions/version-1/test-runs', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/api/core/v1/question-versions/version-1/publish', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' },
    })
  })

  it('sends the full ordered question list when creating and updating an assignment', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'assignment-1', status: 'draft', positions: [1, 2] })

    const composition = { class_id: 'class-1', title: 'Algebra', subject: 'mathematics', due_at: '2026-07-30T00:00:00Z', submission_rule: { allow_late: false }, question_version_ids: ['m1', 'm2'] }
    await createAssignment(request, 'csrf-token', composition)
    await updateAssignment(request, 'csrf-token', 'assignment-1', composition)
    await publishAssignment(request, 'csrf-token', 'assignment-1')

    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/assignments', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: composition,
    })
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/assignments/assignment-1', {
      method: 'PUT', headers: { 'X-CSRF-Token': 'csrf-token' }, body: composition,
    })
    expect(request).toHaveBeenNthCalledWith(3, '/api/core/v1/assignments/assignment-1/publish', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' },
    })
  })

  it('sends review, publication and appeal decisions through CSRF-protected BFF routes', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'decision-1' })

    await decideReviewTask(request, 'csrf-token', 'task-1', { action: 'adjust_score', version: 2, score: 0.5, reason: 'Partial credit.' })
    await batchConfirmReviewTasks(request, 'csrf-token', 'assignment-1', ['task-2'])
    await publishAttemptResults(request, 'csrf-token', 'assignment-1', 'attempt-1')
    await decideTeacherAppeal(request, 'csrf-token', 'appeal-1', { approve: false, version: 1, reason: 'Evidence supports the score.' })

    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/review-tasks/task-1/decisions', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { action: 'adjust_score', version: 2, score: 0.5, reason: 'Partial credit.' },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/review-tasks/batch-confirm?assignment_id=assignment-1', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { task_ids: ['task-2'] },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/api/core/v1/assignments/assignment-1/attempts/attempt-1/publish-results', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' },
    })
    expect(request).toHaveBeenNthCalledWith(4, '/api/core/v1/review-appeals/appeal-1/decisions', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { approve: false, version: 1, reason: 'Evidence supports the score.' },
    })
  })
})

describe('teacher roster API', () => {
  it('loads roster classes through the authenticated BFF', async () => {
    const request = vi.fn().mockResolvedValue({
      items: [{ id: 'class-1', code: '7A', name: 'Year 7 A', student_count: 3 }],
    })

    await expect(fetchTeacherRosterClasses(request))
      .resolves.toEqual([{ id: 'class-1', code: '7A', name: 'Year 7 A', student_count: 3 }])
    expect(request).toHaveBeenCalledWith('/api/core/v1/teacher/classes')
  })

  it('protects roster writes with the session CSRF token', async () => {
    const request = vi.fn().mockResolvedValue({ imported: 1 })

    await createTeacherRosterClass(request, 'csrf-token', { code: '7A', name: 'Year 7 A' })
    await createTeacherRosterStudent(request, 'csrf-token', 'class-1', {
      school_id: 'S-001', display_name: 'Ada', under_14: false, guardian_consent_status: 'not_required',
    })
    await importTeacherRoster(request, 'csrf-token', 'class-1', new Blob(['header']))

    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/teacher/classes', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { code: '7A', name: 'Year 7 A' },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/teacher/classes/class-1/students', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' },
      body: { school_id: 'S-001', display_name: 'Ada', under_14: false, guardian_consent_status: 'not_required' },
    })
    const [, uploadOptions] = request.mock.calls[2]
    expect(uploadOptions.headers).toEqual({ 'X-CSRF-Token': 'csrf-token' })
    expect(uploadOptions.body).toBeInstanceOf(FormData)
  })
})
