import { describe, expect, it, vi } from 'vitest'

import {
  acceptAiCandidate,
  canAcceptCandidate,
  candidateEditInput,
  fetchAiGenerationDrafts,
  fetchAiGenerationJobs,
  rejectAiCandidate,
  saveAiCandidateRevision,
  type TeacherAiCandidate,
  type TeacherAiValidationRun,
} from '../app/lib/teacher-ai-review'

const candidate: TeacherAiCandidate = {
  objective_revision_id: 'objective-1',
  question_type: 'E4',
  policy_version: '2',
  prompt: 'Read the passage and answer the question.',
  rule_json: { scoring_points: [{ phrase: 'evidence', score: 1 }] },
  explanation: 'Checks reading comprehension.',
  knowledge_point: 'Reading comprehension',
  difficulty: 0.6,
  reading_material: 'A short passage.',
}

const passedRun: TeacherAiValidationRun = {
  id: 'run-1',
  draft_id: 'draft-1',
  revision_number: 1,
  run_number: 1,
  validator_version: 'validator@1',
  ruleset_version: 'rules@1',
  status: 'passed',
  feature_summary: {},
  findings: [],
  created_at: '2026-07-22T00:00:00Z',
}

const warningRun: TeacherAiValidationRun = { ...passedRun, status: 'warning' }
const blockedRun: TeacherAiValidationRun = { ...passedRun, status: 'blocked' }

describe('teacher AI review API', () => {
  it('loads generation jobs and their drafts through the same-origin BFF', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ items: [{ id: 'job-1', status: 'completed' }] })
      .mockResolvedValueOnce({ items: [{ id: 'draft-1', candidate, teacher_state: 'pending_review', revision_number: 1, validation_errors: [] }] })

    await expect(fetchAiGenerationJobs(request)).resolves.toEqual([{ id: 'job-1', status: 'completed' }])
    await expect(fetchAiGenerationDrafts(request, 'job-1')).resolves.toMatchObject([{ id: 'draft-1', candidate }])
    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/ai-question-generation/jobs')
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/ai-question-generation/jobs/job-1/questions')
  })

  it('sends a revision with CSRF, idempotency key and the immutable candidate fields', async () => {
    const request = vi.fn().mockResolvedValue({ draft_id: 'draft-1', revision_number: 2, validation_run: passedRun })
    await saveAiCandidateRevision(request, 'csrf', 'draft-1', 'key-1', 1, candidate)
    expect(request).toHaveBeenCalledWith('/api/core/v1/ai-generated-questions/draft-1/revisions', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'key-1' },
      body: { expected_revision_number: 1, candidate },
    })
  })

  it('preserves server-owned candidate identity and validates editable candidate values', () => {
    expect(candidateEditInput(candidate, {
      prompt: 'Edited prompt',
      rule_json: '{"accepted_answers":["answer"]}',
      explanation: 'Edited explanation',
      knowledge_point: 'Edited knowledge point',
      difficulty: '0.7',
      reading_material: 'Edited passage.',
    })).toEqual({
      ...candidate,
      prompt: 'Edited prompt',
      rule_json: { accepted_answers: ['answer'] },
      explanation: 'Edited explanation',
      knowledge_point: 'Edited knowledge point',
      difficulty: 0.7,
      reading_material: 'Edited passage.',
    })
    expect(() => candidateEditInput(candidate, { rule_json: '{' })).toThrow('valid JSON')
    expect(() => candidateEditInput({ ...candidate, question_type: 'M1', reading_material: null }, { reading_material: 'not allowed' })).toThrow('E4')
    expect(() => candidateEditInput(candidate, { difficulty: '1.1' })).toThrow('between 0 and 1')
    expect(() => candidateEditInput(candidate, { difficulty: '' })).toThrow('between 0 and 1')
    expect(() => candidateEditInput(candidate, { difficulty: '   ' })).toThrow('between 0 and 1')
    expect(() => candidateEditInput(candidate, { difficulty: 'Infinity' })).toThrow('between 0 and 1')
  })

  it('sends one-operation idempotency keys for rejection and acceptance without publishing', async () => {
    const request = vi.fn().mockResolvedValue({ draft_id: 'draft-1', action: 'accept', revision_number: 1, validation_run: passedRun, accepted_question_version_id: 'version-1' })

    await rejectAiCandidate(request, 'csrf', 'draft-1', 'reject-key', 1, 'duplicate', 'Already covered.')
    await acceptAiCandidate(request, 'csrf', 'draft-1', 'accept-key', 1, true)

    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/ai-generated-questions/draft-1/reject', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'reject-key' },
      body: { expected_revision_number: 1, reason: 'duplicate', detail: 'Already covered.' },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/ai-generated-questions/draft-1/accept', {
      method: 'POST', headers: { 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'accept-key' },
      body: { expected_revision_number: 1, confirm_warnings: true },
    })
    expect(request.mock.calls.flat().join(' ')).not.toContain('publish')
  })

  it('requires warning confirmation and rejects blocked candidates', () => {
    expect(canAcceptCandidate({ teacher_state: 'pending_review', validation: blockedRun, warningConfirmed: true })).toBe(false)
    expect(canAcceptCandidate({ teacher_state: 'pending_review', validation: warningRun, warningConfirmed: false })).toBe(false)
    expect(canAcceptCandidate({ teacher_state: 'pending_review', validation: warningRun, warningConfirmed: true })).toBe(true)
    expect(canAcceptCandidate({ teacher_state: 'accepted', validation: passedRun, warningConfirmed: false })).toBe(false)
  })
})
