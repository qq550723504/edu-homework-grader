import { expect, test } from '@playwright/test'
import { copyFile, mkdir } from 'node:fs/promises'
import path from 'node:path'

const files = [
  'apps/api/src/edu_grader_api/services/math_semantics.py',
  'apps/api/src/edu_grader_api/services/question_verification.py',
  'apps/api/tests/test_math_semantics.py',
  'apps/api/tests/test_question_verification.py',
  'docs/status-evidence.json',
  'docs/project-status.md',
  'docs/roadmap.md',
]

test('capture PR 107 integration sources', async ({}, testInfo) => {
  const repositoryRoot = path.resolve(process.cwd(), '../..')
  for (const relativePath of files) {
    const destination = testInfo.outputPath('source', relativePath)
    await mkdir(path.dirname(destination), { recursive: true })
    await copyFile(path.join(repositoryRoot, relativePath), destination)
  }
  expect(false, 'intentional one-shot source capture').toBeTruthy()
})
