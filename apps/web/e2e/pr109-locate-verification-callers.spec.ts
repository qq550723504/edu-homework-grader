import { expect, test } from '@playwright/test'
import { copyFile, mkdir } from 'node:fs/promises'
import path from 'node:path'

const sources = [
  'apps/api/src/edu_grader_api/routers/ai_question_validation.py',
  'apps/api/src/edu_grader_api/services/ai_question_review.py',
  'apps/api/src/edu_grader_api/services/question_verification.py',
  'apps/api/tests/test_question_verification.py',
]

test('capture PR 109 production caller sources', async ({}, testInfo) => {
  const root = path.resolve(process.cwd(), '../..')
  for (const source of sources) {
    const destination = testInfo.outputPath('source', source)
    await mkdir(path.dirname(destination), { recursive: true })
    await copyFile(path.join(root, source), destination)
  }
  expect(false, 'intentional one-shot source capture').toBeTruthy()
})
