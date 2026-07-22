// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TeacherAiCandidateReview from '../app/components/teacher/TeacherAiCandidateReview.vue'
import TeacherAiJobList from '../app/components/teacher/TeacherAiJobList.vue'
import TeacherAiReviewWorkspace from '../app/components/teacher/TeacherAiReviewWorkspace.vue'
import TeacherAiQuestionsPage from '../app/pages/teacher/ai-questions.vue'
import type { TeacherAiDraft, TeacherAiGenerationJob, TeacherAiValidationRun } from '../app/lib/teacher-ai-review'

const mocks = vi.hoisted(() => ({
  acceptAiCandidate: vi.fn(),
  fetchAiGenerationDrafts: vi.fn(),
  fetchAiGenerationJobs: vi.fn(),
  fetchCurrentPrincipal: vi.fn(),
  rejectAiCandidate: vi.fn(),
  saveAiCandidateRevision: vi.fn(),
}))

vi.mock('../app/lib/teacher-ai-review', async (importOriginal) => ({
  ...await importOriginal<typeof import('../app/lib/teacher-ai-review')>(),
  acceptAiCandidate: mocks.acceptAiCandidate,
  fetchAiGenerationDrafts: mocks.fetchAiGenerationDrafts,
  fetchAiGenerationJobs: mocks.fetchAiGenerationJobs,
  rejectAiCandidate: mocks.rejectAiCandidate,
  saveAiCandidateRevision: mocks.saveAiCandidateRevision,
}))

vi.mock('../app/lib/student-api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../app/lib/student-api')>(),
  fetchCurrentPrincipal: mocks.fetchCurrentPrincipal,
}))

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

let route: { query: Record<string, string> }
let navigateTo: ReturnType<typeof vi.fn>

async function mountWorkspace(query: Record<string, string> = { job: 'job-1', draft: 'draft-1' }) {
  route.query = { ...query }
  const wrapper = mount(TeacherAiReviewWorkspace)
  await flushPromises()
  return wrapper
}

describe('teacher AI review rendering', () => {
  beforeEach(() => {
    route = reactive({ query: {} })
    navigateTo = vi.fn(async (destination: { query?: Record<string, string> }) => {
      if (destination.query) route.query = { ...destination.query }
      await nextTick()
    })
    vi.stubGlobal('$fetch', vi.fn())
    vi.stubGlobal('navigateTo', navigateTo)
    vi.stubGlobal('useRoute', () => route)
    vi.stubGlobal('useHead', vi.fn())
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'operation-key') })
    mocks.fetchAiGenerationJobs.mockResolvedValue([
      { id: 'job-1', status: 'completed', succeeded_count: 1, failed_count: 0 },
    ])
    mocks.fetchAiGenerationDrafts.mockResolvedValue([warningE4Draft])
    mocks.fetchCurrentPrincipal.mockResolvedValue({ id: 'teacher-1', tenant_id: 'tenant-1', csrf_token: 'csrf-token' })
    mocks.saveAiCandidateRevision.mockResolvedValue({
      draft_id: 'draft-1', revision_number: 2, validation_run: warningValidation,
    })
    mocks.rejectAiCandidate.mockResolvedValue({
      draft_id: 'draft-1', action: 'reject', revision_number: 1,
      validation_run: warningValidation, accepted_question_version_id: null,
    })
    mocks.acceptAiCandidate.mockResolvedValue({
      draft_id: 'draft-1', action: 'accept', revision_number: 1,
      validation_run: warningValidation, accepted_question_version_id: 'version-1',
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

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

  it('keeps malformed rule JSON visible and does not emit a revision', async () => {
    const wrapper = mount(TeacherAiCandidateReview, {
      props: { draft: warningE4Draft, validation: warningValidation, busy: false },
    })

    await wrapper.get('textarea[aria-label="评分规则 JSON"]').setValue('{not valid JSON')
    await wrapper.get('[data-testid="save-revision"]').trigger('click')

    expect(wrapper.get('[role="alert"]').text()).toContain('有效的 JSON 对象')
    expect(wrapper.emitted('save-revision')).toBeUndefined()
  })

  it('resets rejection controls when the selected draft changes', async () => {
    const wrapper = mount(TeacherAiCandidateReview, {
      props: { draft: warningE4Draft, validation: warningValidation, busy: false },
    })

    await wrapper.get('select[aria-label="拒绝原因"]').setValue('unclear_wording')
    await wrapper.get('textarea[aria-label="拒绝详情"]').setValue('Question wording is ambiguous.')
    await wrapper.setProps({ draft: { ...warningE4Draft, id: 'draft-2' } })

    expect((wrapper.get('select[aria-label="拒绝原因"]').element as HTMLSelectElement).value).toBe('incorrect_answer')
    expect((wrapper.get('textarea[aria-label="拒绝详情"]').element as HTMLTextAreaElement).value).toBe('')
  })

  it('restores the selected job and draft from the route query and syncs draft selection through navigation', async () => {
    const secondDraft = { ...warningE4Draft, id: 'draft-2', ordinal: 2 }
    mocks.fetchAiGenerationDrafts.mockResolvedValue([warningE4Draft, secondDraft])

    const wrapper = await mountWorkspace()

    expect(mocks.fetchAiGenerationJobs).toHaveBeenCalledTimes(1)
    expect(mocks.fetchAiGenerationDrafts).toHaveBeenCalledWith(expect.any(Function), 'job-1')
    expect(wrapper.get('textarea[aria-label="题目提示"]').element).toHaveProperty('value', warningE4Draft.candidate.prompt)

    await wrapper.get('[data-testid="generation-draft-draft-2"]').trigger('click')

    expect(navigateTo).toHaveBeenCalledWith({ query: { job: 'job-1', draft: 'draft-2' } })
  })

  it('reloads the selected draft after a revision conflict instead of retaining stale edits', async () => {
    mocks.saveAiCandidateRevision.mockRejectedValue({ data: { detail: { code: 'review_revision_conflict' } } })
    mocks.fetchAiGenerationDrafts
      .mockResolvedValueOnce([warningE4Draft])
      .mockResolvedValueOnce([{ ...warningE4Draft, revision_number: 2, candidate: { ...warningE4Draft.candidate, prompt: 'Latest server prompt' } }])
    const wrapper = await mountWorkspace()

    await wrapper.get('textarea[aria-label="题目提示"]').setValue('Stale local prompt')
    await wrapper.get('[data-testid="save-revision"]').trigger('click')
    await flushPromises()

    expect(mocks.fetchAiGenerationDrafts).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('候选已被更新，已加载最新修订。')
    expect(wrapper.get('textarea[aria-label="题目提示"]').element).toHaveProperty('value', 'Latest server prompt')
  })

  it('locks writes while obtaining CSRF, uses one idempotency key, and refreshes after success', async () => {
    let resolvePrincipal!: (principal: { id: string; tenant_id: string; csrf_token: string }) => void
    mocks.fetchCurrentPrincipal.mockReturnValue(new Promise((resolve) => { resolvePrincipal = resolve }))
    const wrapper = await mountWorkspace()

    await wrapper.get('[data-testid="save-revision"]').trigger('click')
    await nextTick()
    expect(wrapper.get('[data-testid="save-revision"]').attributes('disabled')).toBeDefined()

    resolvePrincipal({ id: 'teacher-1', tenant_id: 'tenant-1', csrf_token: 'csrf-token' })
    await flushPromises()

    expect(mocks.saveAiCandidateRevision).toHaveBeenCalledWith(
      expect.any(Function), 'csrf-token', 'draft-1', 'operation-key', 1, warningE4Draft.candidate,
    )
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
    expect(mocks.fetchAiGenerationDrafts).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="save-revision"]').attributes('disabled')).toBeUndefined()
  })

  it.each([
    [{ statusCode: 404 }, '未找到所选的 AI 出题批次或候选题。'],
    [{ status: 429 }, '请求过于频繁，请稍后重试。'],
    [{ response: { status: 503 } }, 'AI 出题审核服务暂时不可用，请稍后重试。'],
    [new TypeError('fetch failed'), '网络连接异常，请检查网络后重试。'],
  ])('keeps the last successful data when refresh fails with a public error', async (error, publicMessage) => {
    const wrapper = await mountWorkspace()
    mocks.fetchAiGenerationJobs.mockRejectedValueOnce(error)

    route.query = { ...route.query }
    await flushPromises()

    expect(wrapper.get('textarea[aria-label="题目提示"]').element).toHaveProperty(
      'value', warningE4Draft.candidate.prompt,
    )
    expect(wrapper.get('[role="alert"]').text()).toContain(publicMessage)
  })

  it('renders the dedicated teacher route shell and page title', () => {
    const wrapper = mount(TeacherAiQuestionsPage, {
      global: {
        stubs: {
          LogoutButton: true,
          NuxtLink: { template: '<a><slot /></a>' },
          TeacherWorkbenchNav: true,
        },
      },
    })

    expect(wrapper.get('main').classes()).toContain('teacher-workbench')
    expect(wrapper.get('aside').classes()).toContain('teacher-workbench__sidebar')
    expect(wrapper.get('.teacher-workbench__content').exists()).toBe(true)
    expect(wrapper.text()).toContain('AI 出题审核')
    expect(useHead).toHaveBeenCalledWith({ title: 'AI 出题审核' })
  })
})
