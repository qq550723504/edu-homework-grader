// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TeacherAiGenerationForm from '../app/components/teacher/TeacherAiGenerationForm.vue'
import TeacherAiGenerationPage from '../app/components/teacher/TeacherAiGenerationPage.vue'
import TeacherAiGenerationNewPage from '../app/pages/teacher/ai-questions/new.vue'

const mocks = vi.hoisted(() => ({
  createAiGenerationJob: vi.fn(),
  fetchCurriculumGradeMappings: vi.fn(),
  fetchCurriculumObjectives: vi.fn(),
  fetchCurriculumProfiles: vi.fn(),
  fetchCurrentPrincipal: vi.fn(),
  fetchGenerationLimits: vi.fn(),
}))

vi.mock('../app/lib/teacher-ai-generation', async (importOriginal) => ({
  ...await importOriginal<typeof import('../app/lib/teacher-ai-generation')>(),
  createAiGenerationJob: mocks.createAiGenerationJob,
  fetchCurriculumGradeMappings: mocks.fetchCurriculumGradeMappings,
  fetchCurriculumObjectives: mocks.fetchCurriculumObjectives,
  fetchCurriculumProfiles: mocks.fetchCurriculumProfiles,
  fetchGenerationLimits: mocks.fetchGenerationLimits,
}))

vi.mock('../app/lib/student-api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../app/lib/student-api')>(),
  fetchCurrentPrincipal: mocks.fetchCurrentPrincipal,
}))

function objective(id = 'objective-1', subject = 'mathematics') {
  return {
    id: 'objective-record-1', code: 'MATH-G5-001', subject, domain: '数与代数',
    revision: {
      id, text: '理解小数的意义。', allowed_question_types: ['M1', 'E2'],
      difficulty_min: 0.2, difficulty_max: 0.6,
    },
  }
}

describe('teacher AI generation request rendering', () => {
  beforeEach(() => {
    vi.stubGlobal('$fetch', vi.fn())
    vi.stubGlobal('navigateTo', vi.fn())
    vi.stubGlobal('useHead', vi.fn())
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'request-key') })
    mocks.fetchCurriculumProfiles.mockResolvedValue([{ code: 'cn-2022', name: '课程标准' }])
    mocks.fetchCurriculumGradeMappings.mockResolvedValue([{ internal_level: 'G5', external_label: '五年级' }])
    mocks.fetchCurriculumObjectives.mockResolvedValue([objective()])
    mocks.fetchGenerationLimits.mockResolvedValue({ max_batch_size: 5, remaining_count: 2 })
    mocks.fetchCurrentPrincipal.mockResolvedValue({ csrf_token: 'csrf-token' })
    mocks.createAiGenerationJob.mockResolvedValue({ id: 'job-1' })
  })

  afterEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  async function mountForm() {
    const wrapper = mount(TeacherAiGenerationForm)
    await flushPromises()
    return wrapper
  }

  async function selectObjective(wrapper: ReturnType<typeof mount>) {
    await wrapper.get('select[aria-label="课程方案"]').setValue('cn-2022')
    await flushPromises()
    await wrapper.get('select[aria-label="年级"]').setValue('G5')
    await flushPromises()
    await wrapper.get('select[aria-label="学科"]').setValue('mathematics')
    await flushPromises()
    await wrapper.get('select[aria-label="课程目标"]').setValue('objective-1')
    await nextTick()
  }

  it('resets dependent selections and keeps zero quota requests disabled', async () => {
    mocks.fetchGenerationLimits.mockResolvedValue({ max_batch_size: 5, remaining_count: 0 })
    const wrapper = await mountForm()

    await wrapper.get('select[aria-label="课程方案"]').setValue('cn-2022')
    await flushPromises()
    await wrapper.get('select[aria-label="年级"]').setValue('G5')
    await flushPromises()
    await wrapper.get('select[aria-label="学科"]').setValue('mathematics')
    await flushPromises()
    await wrapper.get('select[aria-label="课程目标"]').setValue('objective-1')
    await nextTick()

    expect(wrapper.get('[data-testid="create-ai-generation-job"]').attributes('disabled')).toBeDefined()
    await wrapper.get('select[aria-label="年级"]').setValue('')
    await nextTick()
    expect((wrapper.get('select[aria-label="学科"]').element as HTMLSelectElement).value).toBe('')
    expect((wrapper.get('select[aria-label="课程目标"]').element as HTMLSelectElement).value).toBe('')
    expect(wrapper.find('[data-testid="question-type-M1-decrement"]').exists()).toBe(false)
  })

  it('shows only the active revision allowed types and its actual difficulty bounds', async () => {
    const wrapper = await mountForm()
    await selectObjective(wrapper)

    expect(wrapper.get('[data-testid="difficulty-range"]').text()).toContain('0.2')
    expect(wrapper.get('[data-testid="difficulty-range"]').text()).toContain('0.6')
    expect(wrapper.find('[data-testid="question-type-M1-increment"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="question-type-E2-increment"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="question-type-E4-increment"]').exists()).toBe(false)
  })

  it('uses one idempotency key and navigates only to the public job URL after a successful request', async () => {
    const wrapper = await mountForm()
    await selectObjective(wrapper)
    await wrapper.get('[data-testid="question-type-M1-increment"]').trigger('click')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.createAiGenerationJob).toHaveBeenCalledWith(
      expect.any(Function), 'csrf-token', 'request-key', {
        curriculum_objective_revision_id: 'objective-1', question_types: ['M1'], requested_count: 1,
      },
    )
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
    expect(navigateTo).toHaveBeenCalledWith('/teacher/ai-questions?job=job-1')
    expect(JSON.stringify(navigateTo.mock.calls)).not.toContain('request-key')
    expect(JSON.stringify(navigateTo.mock.calls)).not.toContain('teacher_constraint')
  })

  it('keeps a stale objective response from overwriting a newer subject selection', async () => {
    let resolveOld!: (value: ReturnType<typeof objective>[]) => void
    mocks.fetchCurriculumObjectives
      .mockResolvedValueOnce([objective('objective-mathematics', 'mathematics'), objective('objective-english', 'english')])
      .mockImplementation((_request, _profile, _grade, subject) => subject === 'mathematics'
        ? new Promise((resolve) => { resolveOld = resolve })
        : Promise.resolve([objective('objective-english', 'english')]))
    const wrapper = await mountForm()
    await wrapper.get('select[aria-label="课程方案"]').setValue('cn-2022')
    await flushPromises()
    await wrapper.get('select[aria-label="年级"]').setValue('G5')
    await flushPromises()
    await wrapper.get('select[aria-label="学科"]').setValue('mathematics')
    await nextTick()
    await wrapper.get('select[aria-label="学科"]').setValue('english')
    await flushPromises()
    resolveOld([objective('objective-old', 'mathematics')])
    await flushPromises()

    const objectiveValues = wrapper.get('select[aria-label="课程目标"]').findAll('option')
      .map((option) => option.attributes('value'))
    expect(objectiveValues).toContain('objective-english')
    expect(objectiveValues).not.toContain('objective-old')
  })

  it('clearing a parent selection releases catalogue loading while its stale child request is pending', async () => {
    let resolveGrades!: (value: Array<{ internal_level: string, external_label: string }>) => void
    mocks.fetchCurriculumGradeMappings.mockImplementationOnce(() => new Promise((resolve) => { resolveGrades = resolve }))
    const wrapper = await mountForm()

    await wrapper.get('select[aria-label="课程方案"]').setValue('cn-2022')
    await nextTick()
    await wrapper.get('select[aria-label="课程方案"]').setValue('')
    await nextTick()
    expect(wrapper.get('.ai-generation-form').attributes('aria-busy')).toBe('false')
    resolveGrades([{ internal_level: 'G5', external_label: '五年级' }])
    await flushPromises()

    await wrapper.get('select[aria-label="课程方案"]').setValue('cn-2022')
    await flushPromises()
    let resolveSubjects!: (value: ReturnType<typeof objective>[]) => void
    mocks.fetchCurriculumObjectives.mockImplementationOnce(() => new Promise((resolve) => { resolveSubjects = resolve }))
    await wrapper.get('select[aria-label="年级"]').setValue('G5')
    await nextTick()
    await wrapper.get('select[aria-label="年级"]').setValue('')
    await nextTick()
    expect(wrapper.get('.ai-generation-form').attributes('aria-busy')).toBe('false')
    resolveSubjects([objective()])
    await flushPromises()

    await wrapper.get('select[aria-label="年级"]').setValue('G5')
    await flushPromises()
    let resolveObjectives!: (value: ReturnType<typeof objective>[]) => void
    mocks.fetchCurriculumObjectives.mockImplementationOnce(() => new Promise((resolve) => { resolveObjectives = resolve }))
    await wrapper.get('select[aria-label="学科"]').setValue('mathematics')
    await nextTick()
    await wrapper.get('select[aria-label="学科"]').setValue('')
    await nextTick()
    expect(wrapper.get('.ai-generation-form').attributes('aria-busy')).toBe('false')
    resolveObjectives([objective()])
    await flushPromises()
  })

  it('renders the dedicated generation page shell and exposes a new-batch entry from review', () => {
    const wrapper = mount(TeacherAiGenerationPage, {
      global: { stubs: { LogoutButton: true, NuxtLink: { template: '<a><slot /></a>' }, TeacherWorkbenchNav: true } },
    })
    const routeWrapper = mount(TeacherAiGenerationNewPage, {
      global: { stubs: { TeacherAiGenerationPage: true } },
    })

    expect(wrapper.get('main').classes()).toContain('teacher-workbench')
    expect(wrapper.text()).toContain('创建 AI 出题批次')
    expect(routeWrapper.findComponent({ name: 'TeacherAiGenerationPage' }).exists()).toBe(true)
  })

  it('uses directory pages so Nuxt maps the review root and new-batch child routes separately', () => {
    const reviewPage = resolve(process.cwd(), 'app/pages/teacher/ai-questions/index.vue')
    const newBatchPage = resolve(process.cwd(), 'app/pages/teacher/ai-questions/new.vue')
    const conflictingFlatPage = resolve(process.cwd(), 'app/pages/teacher/ai-questions.vue')

    expect(existsSync(reviewPage)).toBe(true)
    expect(existsSync(newBatchPage)).toBe(true)
    expect(existsSync(conflictingFlatPage)).toBe(false)
    expect(readFileSync(reviewPage, 'utf8')).toContain('TeacherAiReviewWorkspace')
    expect(readFileSync(newBatchPage, 'utf8')).toContain('TeacherAiGenerationPage')
  })
})
