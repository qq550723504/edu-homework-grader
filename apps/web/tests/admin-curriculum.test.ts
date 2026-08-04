import { describe, expect, it, vi } from 'vitest'

import {
  createCurriculumImport,
  dryRunCurriculumImport,
  fetchAdminCurriculumProfiles,
  fetchCurriculumImport,
  fetchCurriculumImportSchema,
  fetchCurriculumImports,
} from '../app/lib/admin-curriculum'

describe('curriculum administration API', () => {
  it('loads paginated profiles, imports, details, and schema through the BFF', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ items: [], total: 0, limit: 10, offset: 0 })
      .mockResolvedValueOnce({ items: [], total: 0, limit: 20, offset: 0 })
      .mockResolvedValueOnce({ id: 'batch-1', issues: [] })
      .mockResolvedValueOnce({ json_schema: {}, csv_columns: [] })

    await fetchAdminCurriculumProfiles(request, { status: 'active', limit: 10, offset: 0 })
    await fetchCurriculumImports(request, { status: 'draft', limit: 20, offset: 0 })
    await fetchCurriculumImport(request, 'batch/1')
    await fetchCurriculumImportSchema(request)

    expect(request).toHaveBeenNthCalledWith(
      1,
      '/api/core/v1/admin/curriculum/profiles?status=active&limit=10&offset=0',
    )
    expect(request).toHaveBeenNthCalledWith(
      2,
      '/api/core/v1/admin/curriculum/imports?status=draft&limit=20&offset=0',
    )
    expect(request).toHaveBeenNthCalledWith(
      3,
      '/api/core/v1/admin/curriculum/imports/batch%2F1',
    )
    expect(request).toHaveBeenNthCalledWith(4, '/api/core/v1/admin/curriculum/import-schema')
  })

  it('keeps dry-run stateless and protects draft creation with a stable key and digest', async () => {
    const request = vi.fn().mockResolvedValue({ id: 'batch-1' })
    const body = { format: 'json', document: { profile: {}, objectives: [] } }

    await dryRunCurriculumImport(request, 'csrf-token', body)
    await createCurriculumImport(request, 'csrf-token', 'create-key', {
      ...body,
      catalogue_fingerprint: 'a'.repeat(64),
      normalized_digest: 'b'.repeat(64),
    })

    expect(request).toHaveBeenNthCalledWith(
      1,
      '/api/core/v1/admin/curriculum/imports/dry-run',
      {
        method: 'POST',
        headers: { 'X-CSRF-Token': 'csrf-token' },
        body,
      },
    )
    expect(request).toHaveBeenNthCalledWith(
      2,
      '/api/core/v1/admin/curriculum/imports',
      {
        method: 'POST',
        headers: { 'X-CSRF-Token': 'csrf-token', 'Idempotency-Key': 'create-key' },
        body: { ...body, catalogue_fingerprint: 'a'.repeat(64), normalized_digest: 'b'.repeat(64) },
      },
    )
  })
})
