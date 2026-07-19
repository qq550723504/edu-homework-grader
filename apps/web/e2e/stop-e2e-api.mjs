import { execFile } from 'node:child_process'
import { readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, resolve } from 'node:path'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'

const execFileAsync = promisify(execFile)
const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const statePath = resolve(repositoryRoot, 'apps/web/test-results/e2e-api-state.json')

function processIsRunning(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

async function waitForExit(pid) {
  const deadline = Date.now() + 5_000
  while (processIsRunning(pid) && Date.now() < deadline) {
    await new Promise((resolveWait) => setTimeout(resolveWait, 50))
  }
  if (processIsRunning(pid)) {
    throw new Error(`E2E API process ${pid} did not exit`)
  }
}

export default async function stopE2eApi() {
  let runtime
  try {
    runtime = JSON.parse(await readFile(statePath, 'utf8'))
  } catch (error) {
    if (error?.code === 'ENOENT') return
    throw error
  }

  const databasePath = resolve(runtime.databasePath)
  if (
    !Number.isInteger(runtime.pid)
    || runtime.pid <= 0
    || dirname(databasePath) !== resolve(tmpdir())
    || !/^edu-homework-grader-e2e-[0-9a-f-]+\.sqlite$/.test(basename(databasePath))
  ) {
    throw new Error('Invalid E2E API runtime state')
  }

  if (processIsRunning(runtime.pid)) {
    if (process.platform === 'win32') {
      await execFileAsync('taskkill', ['/pid', String(runtime.pid), '/T', '/F'])
    } else {
      process.kill(runtime.pid, 'SIGTERM')
    }
  }

  await waitForExit(runtime.pid)
  await rm(databasePath, { force: true })
  await rm(statePath, { force: true })
}
