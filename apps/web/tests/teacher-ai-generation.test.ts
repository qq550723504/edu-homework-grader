import { describe, expect, it, vi } from 'vitest'

import {
  createAiGenerationJob,
  expandQuestionTypeCounts,
  fetchCurriculumGradeMappings,
  fetchCurriculumObjectives,
  fetchCurriculumProfiles,
  fetchGenerationLimits,
} from '../app/lib/teacher-ai-generation'

describe('teacher AI generation API', () => {
  it('expands question type counts in a deterministic order and omits zero counts', () => {
    const types = expandQuestionTypeCounts({ E2: 2, M2: 1, M1: 0, E1: 0, E3: 0, E4: 0 })

    expect(types).toEqual(['M2', 'E2', 'E2'])
    expect(types).toHaveLength(3)
  })

  it('reads the public curriculum catalog and generation limits through the same-origin BFF', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ items: [{ code: 'cn-2022', name: '课程标准' }] })
      .mockResolvedValueOnce({ items: [{ internal_level: 'G5', external_label: '五年级' }] })
      .mockResolvedValueOnce({ items: [{ id: 'objective-1' }] })
      .mockResolvedValueOnce({ max_batch_size: 10, remaining_count: 8 })

    await expect(fetchCurriculumProfiles(request)).resolves.toEqual([{ code: 'cn-2022', name: '课程标准' }])
    await expect(fetchCurriculumGradeMappings(request, 'cn-2022')).resolves.toEqual([{ internal_level: 'G5', external_label: '五年级' }])
    await expect(fetchCurriculumObjectives(request, 'cn-2022', 'G5', 'mathematics')).resolves.toEqual([{ id: 'objective-1' }])
    await expect(fetchGenerationLimits(request)).resolves.toEqual({ max_batch_size: 10, remaining_count: 8 })

    expect(request).toHaveBeenNthCalledWith(1, '/api/core/v1/curriculum-profiles')
    expect(request).toHaveBeenNthCalledWith(2, '/api/core/v1/curriculum-profiles/cn-2022/grade-mappings')
    expect(request).toHaveBeenNthCalledWith(3, '/api/core/v1/curriculum-profiles/cn-2022/objectives?grade_level=G5&subject=mathematics')
    expect(request).toHaveBeenNthCalledWith(4, '/api/core/v1/ai-question-generation/limits')
  })

  it('sends only the public generation request body with CSRF and idempotency headers', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'job-1' })

    await createAiGenerationJob(request, 'csrf-token', 'request-key', {
      curriculum_objective_revision_id: 'objective-revision-1',
      question_types: ['M1', 'E2'],
      requested_count: 2,
      teacher_constraint: '结合本周课堂练习。',
    })

    expect(request).toHaveBeenCalledWith('/api/core/v1/ai-question-generation/jobs', {
      method: 'POST',
      headers: { 'X-CSRF-Token': 'csrf-token', 'Idempotency-Key': 'request-key' },
      body: {
        curriculum_objective_revision_id: 'objective-revision-1',
        question_types: ['M1', 'E2'],
        requested_count: 2,
        teacher_constraint: '结合本周课堂练习。',
      },
    })
    const serializedRequest = JSON.stringify(request.mock.calls[0][1])
    for (const serverOwnedField of [
      'grade', 'subject', 'policy_catalog_version', 'prompt_version', 'provider', 'system_prompt',
      'request_digest', 'validation', 'constraint_history',
    ]) {
      expect(serializedRequest).not.toContain(serverOwnedField)
    }
  })

  it('drops untyped server-owned and private fields instead of forwarding the caller object', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'job-1' })
    const untrustedInput = {
      curriculum_objective_revision_id: 'objective-revision-1',
      question_types: ['M1'],
      requested_count: 1,
      teacher_constraint: '使用课堂词汇。',
      grade: 'forged-grade',
      subject: 'forged-subject',
      policy_catalog_version: 'forged-catalog',
      prompt_version: 'forged-prompt',
      private_validation_features: { secret: true },
    }

    await createAiGenerationJob(request, 'csrf-token', 'request-key', untrustedInput as never)

    expect(request.mock.calls[0][1].body).toEqual({
      curriculum_objective_revision_id: 'objective-revision-1',
      question_types: ['M1'],
      requested_count: 1,
      teacher_constraint: '使用课堂词汇。',
    })
  })
})
