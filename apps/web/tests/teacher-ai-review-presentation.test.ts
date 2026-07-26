import { describe, expect, it } from 'vitest'

import { reviewPresentation } from '../app/lib/teacher-ai-review-presentation'
import type { TeacherAiDraft, TeacherAiValidationRun } from '../app/lib/teacher-ai-review'

const pendingDraft: TeacherAiDraft = {
  id: 'draft-1',
  ordinal: 1,
  teacher_state: 'pending_review',
  candidate: {
    objective_revision_id: 'objective-1',
    question_type: 'M1',
    policy_version: 'policy-1',
    prompt: 'What is 1 + 1?',
    rule_json: { expected: 2 },
    explanation: 'Add the numbers.',
    knowledge_point: 'Addition',
    difficulty: 0.2,
    reading_material: null,
  },
  revision_number: 1,
  validation_errors: [],
}

const passedRun: TeacherAiValidationRun = {
  id: 'run-1',
  draft_id: 'draft-1',
  revision_number: 1,
  run_number: 1,
  validator_version: 'validator-1',
  ruleset_version: 'ruleset-1',
  status: 'passed',
  feature_summary: {},
  findings: [],
  created_at: '2026-07-26T00:00:00Z',
}

const blockedRun: TeacherAiValidationRun = {
  ...passedRun,
  status: 'blocked',
  findings: [{ code: 'invalid', severity: 'blocked', evidence: {}, remediation: '请补充题干。' }],
}

describe('teacher AI review presentation', () => {
  it('explains a blocked pending candidate as requiring correction', () => {
    expect(reviewPresentation(pendingDraft, blockedRun)).toMatchObject({
      kind: 'needs_fix', label: '需修正', title: '暂不能接受',
      primaryAction: '修改并重新校验',
    })
  })

  it.each([
    ['warning', 'needs_confirmation', '需要教师确认', '已阅读后接受为题库草稿'],
    ['passed', 'ready', '可以接受', '接受为题库草稿'],
  ])('maps %s validations to a teacher decision', (status, kind, title, primaryAction) => {
    expect(reviewPresentation(pendingDraft, { ...passedRun, status } as TeacherAiValidationRun)).toMatchObject({ kind, title, primaryAction })
  })

  it.each([
    ['accepted', 'accepted', '已创建题库草稿'],
    ['rejected', 'rejected', '已拒绝这道候选题'],
  ])('maps terminal teacher state %s without an available write action', (teacher_state, kind, title) => {
    expect(reviewPresentation({ ...pendingDraft, teacher_state }, passedRun)).toMatchObject({ kind, title, primaryAction: null })
  })
})
