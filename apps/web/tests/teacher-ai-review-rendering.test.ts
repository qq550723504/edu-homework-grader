// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TeacherAiCandidateReview from '../app/components/teacher/TeacherAiCandidateReview.vue'
import TeacherAiJobList from '../app/components/teacher/TeacherAiJobList.vue'
import type { TeacherAiDraft, TeacherAiGenerationJob, TeacherAiValidationRun } from '../app/lib/teacher-ai-review'

const warningValidation: TeacherAiValidationRun = {
  id: 'validation-1',
  draft_id: 'draft-1',
  revision_number: 1,
  run_number: 1,
  validator_version: 'validator@1',
  ruleset_version: 'rules@1',
  status: 'warning',
  feature_summary: {},
  findings: [{
    code: 'LOW_EVIDENCE',
    severity: 'warning',
    evidence: { matched_phrases: [] },
    remediation: 'Add a direct quotation from the passage.',
  }],
  created_at: '2026-07-22T00:00:00Z',
}

const warningE4Draft: TeacherAiDraft = {
  id: 'draft-1',
  ordinal: 1,
  teacher_state: 'pending_review',
  revision_number: 1,
  validation_errors: [],
  candidate: {
    objective_revision_id: 'objective-1',
    question_type: 'E4',
    policy_version: 'policy-1',
    prompt: 'Why was the bridge closed?',
    rule_json: { accepted_answers: ['flooding'] },
    explanation: 'The passage states the reason.',
    knowledge_point: 'Reading comprehension',
    difficulty: 0.6,
    reading_material: 'The bridge was closed. Heavy rain had flooded the river.',
  },
}

describe('teacher AI review rendering', () => {
  it('renders jobs with their status and counts, and selects a job', async () => {
    const jobs: TeacherAiGenerationJob[] = [
      { id: 'job-1', status: 'completed', succeeded_count: 3, failed_count: 1 },
      { id: 'job-2', status: 'running', succeeded_count: 1, failed_count: 0 },
    ]
    const wrapper = mount(TeacherAiJobList, { props: { jobs, selectedJobId: 'job-1' } })

    expect(wrapper.get('[data-testid="generation-job-job-1"]').text()).toContain('completed')
    expect(wrapper.get('[data-testid="generation-job-job-1"]').text()).toContain('成功 3')
    expect(wrapper.get('[data-testid="generation-job-job-1"]').text()).toContain('失败 1')
    expect(wrapper.get('[data-testid="generation-job-job-1"]').attributes('aria-current')).toBe('true')

    await wrapper.get('[data-testid="generation-job-job-2"]').trigger('click')
    expect(wrapper.emitted('select-job')).toEqual([['job-2']])
  })

  it('renders E4 material and blocks acceptance until warning confirmation', async () => {
    const wrapper = mount(TeacherAiCandidateReview, {
      props: { draft: warningE4Draft, validation: warningValidation, busy: false },
    })

    expect(wrapper.get('[data-testid="reading-material"]').text()).toContain('The bridge was closed.')
    expect(wrapper.get('[data-testid="validation-finding"]').text()).toContain('LOW_EVIDENCE')
    expect(wrapper.get('[data-testid="validation-finding"]').text()).toContain('Add a direct quotation')
    expect(wrapper.get('[data-testid="accept-candidate"]').attributes('disabled')).toBeDefined()

    await wrapper.get('input[aria-label="确认 warning 后接受"]').setValue(true)
    expect(wrapper.get('[data-testid="accept-candidate"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="accept-candidate"]').trigger('click')
    expect(wrapper.emitted('accept')).toEqual([[{ confirmWarnings: true }]])
  })

  it('keeps blocked candidates from being accepted and emits rejection with reason and detail', async () => {
    const wrapper = mount(TeacherAiCandidateReview, {
      props: { draft: warningE4Draft, validation: { ...warningValidation, status: 'blocked' }, busy: false },
    })

    expect(wrapper.get('[data-testid="accept-candidate"]').attributes('disabled')).toBeDefined()
    await wrapper.get('select[aria-label="拒绝原因"]').setValue('unclear_wording')
    await wrapper.get('textarea[aria-label="拒绝详情"]').setValue('Question wording is ambiguous.')
    await wrapper.get('[data-testid="reject-candidate"]').trigger('click')
    expect(wrapper.emitted('reject')).toEqual([['unclear_wording', 'Question wording is ambiguous.']])
  })

  it('emits parsed editable candidate fields and an accepted-state notice', async () => {
    const wrapper = mount(TeacherAiCandidateReview, {
      props: { draft: { ...warningE4Draft, teacher_state: 'accepted' }, validation: warningValidation, busy: false },
    })

    expect(wrapper.get('[data-testid="accepted-notice"]').text()).toContain('已接受')
    await wrapper.get('textarea[aria-label="题目提示"]').setValue('Edited question')
    await wrapper.get('textarea[aria-label="评分规则 JSON"]').setValue('{\n  "accepted_answers": ["flood"]\n}')
    await wrapper.get('input[aria-label="难度"]').setValue('0.7')
    await wrapper.get('textarea[aria-label="阅读材料"]').setValue('Edited material')
    await wrapper.get('[data-testid="save-revision"]').trigger('click')

    expect(wrapper.emitted('save-revision')).toEqual([[
      expect.objectContaining({
        prompt: 'Edited question',
        rule_json: { accepted_answers: ['flood'] },
        difficulty: 0.7,
        reading_material: 'Edited material',
        objective_revision_id: 'objective-1',
        question_type: 'E4',
      }),
    ]])
  })
})
