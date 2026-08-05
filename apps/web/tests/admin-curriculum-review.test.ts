// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CurriculumImportDetail from '../app/components/admin/CurriculumImportDetail.vue'
import CurriculumProfileDetail from '../app/components/admin/CurriculumProfileDetail.vue'

const mocks = vi.hoisted(() => ({
  activateCurriculumImport: vi.fn(),
  exportCurriculumProfile: vi.fn(),
  fetchCurriculumImport: vi.fn(),
  fetchCurriculumProfile: vi.fn(),
  fetchRetirementImpact: vi.fn(),
  fetchCurrentPrincipal: vi.fn(),
  retireCurriculumProfile: vi.fn(),
  reviewCurriculumImport: vi.fn(),
  submitCurriculumImportReview: vi.fn(),
}))

vi.mock('../app/lib/admin-curriculum', () => ({
  activateCurriculumImport: mocks.activateCurriculumImport,
  exportCurriculumProfile: mocks.exportCurriculumProfile,
  fetchCurriculumImport: mocks.fetchCurriculumImport,
  fetchCurriculumProfile: mocks.fetchCurriculumProfile,
  fetchRetirementImpact: mocks.fetchRetirementImpact,
  retireCurriculumProfile: mocks.retireCurriculumProfile,
  reviewCurriculumImport: mocks.reviewCurriculumImport,
  submitCurriculumImportReview: mocks.submitCurriculumImportReview,
}))

vi.mock('../app/lib/student-api', () => ({ fetchCurrentPrincipal: mocks.fetchCurrentPrincipal }))

describe('curriculum import review and profile lifecycle', () => {
  beforeEach(() => {
    vi.stubGlobal('$fetch', vi.fn())
    vi.stubGlobal('navigateTo', vi.fn())
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'request-key') })
    vi.stubGlobal('confirm', vi.fn(() => true))
    mocks.fetchCurrentPrincipal.mockResolvedValue({ id: 'reviewer-1', tenant_id: 'tenant-1', csrf_token: 'csrf-token' })
    mocks.fetchCurriculumImport.mockResolvedValue({
      id: 'batch-1',
      status: 'draft',
      profile: { name: '数学', version_label: '2026' },
      issues: [],
      summary: { additions: ['M-1'] },
      proposed_objectives: [{ code: 'M-1', subject: '数学', domain: '数与代数', text: '理解数的组成' }],
      submitted_by_user_id: 'submitter-1',
      reviewed_by_user_id: null,
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('exposes submit, approve, and activate actions according to the import state', async () => {
    mocks.submitCurriculumImportReview.mockResolvedValue({ status: 'in_review' })
    mocks.reviewCurriculumImport.mockResolvedValue({ status: 'in_review', reviewed_by_user_id: 'reviewer-1' })
    mocks.activateCurriculumImport.mockResolvedValue({ status: 'active' })
    const wrapper = mount(CurriculumImportDetail, { props: { batchId: 'batch-1' } })

    await flushPromises()
    await wrapper.get('[data-testid="submit-curriculum-review"]').trigger('click')
    await flushPromises()
    expect(mocks.submitCurriculumImportReview).toHaveBeenCalledWith(expect.anything(), 'csrf-token', 'request-key', 'batch-1')

    await wrapper.get('[data-testid="approve-curriculum-import"]').trigger('click')
    await flushPromises()
    expect(mocks.reviewCurriculumImport).toHaveBeenCalledWith(expect.anything(), 'csrf-token', 'request-key', 'batch-1', true)

    await wrapper.get('[data-testid="activate-curriculum-import"]').trigger('click')
    await flushPromises()
    expect(mocks.activateCurriculumImport).toHaveBeenCalledWith(expect.anything(), 'csrf-token', 'request-key', 'batch-1')
    expect(wrapper.text()).toContain('理解数的组成')
    wrapper.unmount()
  })

  it('hides actions for a non-owner and requires confirmation before activation', async () => {
    mocks.fetchCurrentPrincipal.mockResolvedValue({ id: 'submitter-1', tenant_id: 'tenant-1', csrf_token: 'csrf-token' })
    mocks.fetchCurriculumImport.mockResolvedValue({
      id: 'batch-1',
      status: 'in_review',
      profile: { name: '数学', version_label: '2026' },
      issues: [{ code: 'invalid_text', message: '无效文本', source_path: '$.objectives[0].text', source_row: 4, source_column: 'text' }],
      summary: {},
      proposed_objectives: [],
      submitted_by_user_id: 'submitter-1',
      reviewed_by_user_id: 'reviewer-1',
    })
    const wrapper = mount(CurriculumImportDetail, { props: { batchId: 'batch-1' } })

    await flushPromises()

    expect(wrapper.find('[data-testid="approve-curriculum-import"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="activate-curriculum-import"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('invalid_text')
    expect(wrapper.text()).toContain('第 4 行')
    wrapper.unmount()
  })

  it('does not activate when confirmation is dismissed', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    mocks.fetchCurriculumImport.mockResolvedValue({
      id: 'batch-1',
      status: 'in_review',
      profile: { name: '数学', version_label: '2026' },
      issues: [],
      summary: {},
      proposed_objectives: [],
      submitted_by_user_id: 'submitter-1',
      reviewed_by_user_id: 'reviewer-1',
    })
    const wrapper = mount(CurriculumImportDetail, { props: { batchId: 'batch-1' } })

    await flushPromises()
    await wrapper.get('[data-testid="activate-curriculum-import"]').trigger('click')

    expect(confirm).toHaveBeenCalled()
    expect(mocks.activateCurriculumImport).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('requires a retirement confirmation and shows impact before retiring a profile', async () => {
    mocks.fetchCurriculumProfile.mockResolvedValue({ id: 'profile-1', code: 'math-2026', name: '数学', status: 'active', objective_count: 2, grade_mappings: [], objectives: [] })
    mocks.fetchRetirementImpact.mockResolvedValue({ references: [], coverage: { assignments: 0 } })
    mocks.retireCurriculumProfile.mockResolvedValue({ status: 'retired' })
    const wrapper = mount(CurriculumProfileDetail, { props: { profileCode: 'math-2026' } })

    await flushPromises()
    await wrapper.get('[data-testid="load-retirement-impact"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="retire-curriculum-profile"]').trigger('click')
    await flushPromises()

    expect(mocks.fetchRetirementImpact).toHaveBeenCalledWith(expect.anything(), 'profile-1')
    expect(confirm).toHaveBeenCalled()
    expect(mocks.retireCurriculumProfile).toHaveBeenCalledWith(expect.anything(), 'csrf-token', 'request-key', 'profile-1')
    wrapper.unmount()
  })
})
