import { describe, expect, it, vi } from 'vitest'

import { batchConfirmReviewTasks, createAssignment, addAssignmentItem, createQuestion, createTestCase, decideReviewTask, decideTeacherAppeal, fetchTeacherWorkspace, publishAssignment, publishAttemptResults, publishQuestionVersion, runQuestionTests } from '../app/lib/teacher-api'

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

  it('creates, fills and publishes an assignment through the BFF', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'assignment-1', status: 'draft' })

    await createAssignment(request, 'csrf-token', { class_id: 'class-1', title: 'Algebra', subject: 'mathematics', due_at: '2026-07-30T00:00:00Z', submission_rule: { allow_late: false } })
    await addAssignmentItem(request, 'csrf-token', 'assignment-1', { question_version_id: 'version-1', position: 1 })
    await publishAssignment(request, 'csrf-token', 'assignment-1')

    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/assignments/assignment-1/items', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf-token' }, body: { question_version_id: 'version-1', position: 1 },
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
