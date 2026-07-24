import { expect, test } from '@playwright/test'
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
    await testInfo.attach(source.replaceAll('/', '__'), {
      path: path.join(root, source),
      contentType: 'text/plain',
    })
  }
  expect(false, 'intentional one-shot source capture').toBeTruthy()
})
