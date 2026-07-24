import { expect, test } from '@playwright/test'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'

async function walk(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true })
  const files: string[] = []
  for (const entry of entries) {
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await walk(target)))
    } else if (entry.isFile() && target.endsWith('.py')) {
      files.push(target)
    }
  }
  return files
}

test('locate run_candidate_verification call sites', async () => {
  const root = path.resolve(process.cwd(), '../..')
  const files = await walk(path.join(root, 'apps/api'))
  const matches: string[] = []
  for (const file of files) {
    const content = await readFile(file, 'utf8')
    if (content.includes('run_candidate_verification(')) {
      matches.push(path.relative(root, file))
    }
  }
  expect(matches, JSON.stringify(matches)).toEqual([])
})
