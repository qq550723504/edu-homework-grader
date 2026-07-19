import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { delimiter, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const databasePath = join(tmpdir(), `edu-homework-grader-e2e-${randomUUID()}.sqlite`)
const statePath = resolve(repositoryRoot, 'apps/web/test-results/e2e-api-state.json')
const databaseUrl = `sqlite+pysqlite:///${databasePath.replaceAll('\\', '/')}`
const pythonPath = [
  resolve(repositoryRoot, 'apps/api/src'),
  resolve(repositoryRoot, 'services/grader/src'),
  resolve(repositoryRoot, 'packages/processor-policy/src'),
].join(delimiter)

await mkdir(dirname(statePath), { recursive: true })

const child = spawn(
  'python',
  [
    '-m',
    'uvicorn',
    'edu_grader_api.e2e_app:app',
    '--host',
    '127.0.0.1',
    '--port',
    '18000',
  ],
  {
    env: {
      ...process.env,
      E2E_DATABASE_URL: databaseUrl,
      PYTHONPATH: pythonPath,
    },
    stdio: 'inherit',
  },
)

await writeFile(statePath, JSON.stringify({ databasePath, pid: child.pid }), 'utf8')

async function removeRuntimeFiles() {
  await rm(databasePath, { force: true })
  await rm(statePath, { force: true })
}

let forwardedSignal = null
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    forwardedSignal = signal
    child.kill(signal)
  })
}

child.once('error', async (error) => {
  await removeRuntimeFiles()
  throw error
})

child.once('exit', async (code, signal) => {
  await removeRuntimeFiles()
  if (forwardedSignal) {
    process.exit(0)
  }
  process.exit(code ?? (signal ? 1 : 0))
})
