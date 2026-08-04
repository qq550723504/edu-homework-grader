// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CurriculumImportWorkspace from '../app/components/admin/CurriculumImportWorkspace.vue'

const mocks = vi.hoisted(() => ({
  createCurriculumImport: vi.fn(),
  dryRunCurriculumImport: vi.fn(),
  fetchCurriculumImportSchema: vi.fn(),
  fetchCurrentPrincipal: vi.fn(),
}))

vi.mock('../app/lib/admin-curriculum', () => ({
  createCurriculumImport: mocks.createCurriculumImport,
  dryRunCurriculumImport: mocks.dryRunCurriculumImport,
  fetchCurriculumImportSchema: mocks.fetchCurriculumImportSchema,
}))

vi.mock('../app/lib/student-api', () => ({ fetchCurrentPrincipal: mocks.fetchCurrentPrincipal }))

describe('curriculum import workspace', () => {
  beforeEach(() => {
    vi.stubGlobal('$fetch', vi.fn())
    vi.stubGlobal('navigateTo', vi.fn())
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'request-key') })
    mocks.fetchCurriculumImportSchema.mockResolvedValue({ json_schema: {}, csv_columns: [] })
    mocks.fetchCurrentPrincipal.mockResolvedValue({ csrf_token: 'csrf-token' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('shows validation problems and disables draft creation', async () => {
    mocks.dryRunCurriculumImport.mockResolvedValue({
      normalized_digest: 'digest',
      catalogue_fingerprint: 'a'.repeat(64),
      additions: [],
      updates: [],
      unchanged: [],
      conflicts: [],
      problems: [{ code: 'invalid_document', message: 'document is invalid' }],
      can_apply: false,
    })
    const wrapper = mount(CurriculumImportWorkspace)

    await flushPromises()
    await wrapper.get('[aria-label="JSON 课程目录"]').setValue('{"profile":{}}')
    await wrapper.get('[data-testid="run-curriculum-dry-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('document is invalid')
    expect(wrapper.get('[data-testid="create-curriculum-draft"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('reuses the dry-run fingerprint when creating a draft', async () => {
    const fingerprint = 'b'.repeat(64)
    mocks.dryRunCurriculumImport.mockResolvedValue({
      normalized_digest: 'digest',
      catalogue_fingerprint: fingerprint,
      additions: ['EX-1'],
      updates: [],
      unchanged: [],
      conflicts: [],
      problems: [],
      can_apply: true,
    })
    mocks.createCurriculumImport.mockResolvedValue({ id: 'batch-1' })
    const wrapper = mount(CurriculumImportWorkspace)

    await flushPromises()
    await wrapper.get('[aria-label="JSON 课程目录"]').setValue('{"profile":{},"objectives":[]}')
    await wrapper.get('[data-testid="run-curriculum-dry-run"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="create-curriculum-draft"]').trigger('click')
    await flushPromises()

    expect(mocks.createCurriculumImport).toHaveBeenCalledWith(
      expect.anything(),
      'csrf-token',
      'request-key',
      expect.objectContaining({ catalogue_fingerprint: fingerprint }),
    )
    wrapper.unmount()
  })

  it('explains that a fresh dry-run is required after a stale fingerprint conflict', async () => {
    mocks.dryRunCurriculumImport.mockResolvedValue({
      normalized_digest: 'digest',
      catalogue_fingerprint: 'c'.repeat(64),
      additions: [],
      updates: [],
      unchanged: [],
      conflicts: [],
      problems: [],
      can_apply: true,
    })
    mocks.createCurriculumImport.mockRejectedValue({ statusCode: 409 })
    const wrapper = mount(CurriculumImportWorkspace)

    await flushPromises()
    await wrapper.get('[aria-label="JSON 课程目录"]').setValue('{"profile":{},"objectives":[]}')
    await wrapper.get('[data-testid="run-curriculum-dry-run"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="create-curriculum-draft"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('目录已变化，请重新执行 dry-run')
    wrapper.unmount()
  })
})
