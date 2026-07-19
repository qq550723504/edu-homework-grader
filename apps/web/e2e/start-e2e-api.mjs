import { spawn, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { access, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { delimiter, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const nonce = randomUUID()
const databasePath = join(tmpdir(), `edu-homework-grader-e2e-${nonce}.sqlite`)
const statePath = join(tmpdir(), `edu-homework-grader-e2e-${nonce}.json`)
const startedPath = `${statePath}.started`
const stopPath = `${statePath}.stop`
const supervisorPath = resolve(repositoryRoot, 'apps/web/e2e/e2e-api-supervisor.mjs')
const databaseUrl = `sqlite+pysqlite:///${databasePath.replaceAll('\\', '/')}`
const pythonPath = [
  resolve(repositoryRoot, 'apps/api/src'),
  resolve(repositoryRoot, 'services/grader/src'),
  resolve(repositoryRoot, 'packages/processor-policy/src'),
].join(delimiter)

const inheritedEnvironment = Object.fromEntries(
  Object.entries(process.env).filter(
    ([name]) => name !== 'APP_ENV' && !name.startsWith('OIDC_'),
  ),
)
const supervisorEnvironment = {
  ...inheritedEnvironment,
  APP_ENV: 'test',
  E2E_DATABASE_URL: databaseUrl,
  OIDC_AUDIENCE: 'edu-grader-api',
  OIDC_ISSUER: 'http://localhost:8080/realms/edu-grader',
  OIDC_SCHOOL_ID_CLAIM: 'school_id',
  OIDC_TENANT_SLUG: 'pilot',
  PYTHONPATH: pythonPath,
}
await writeFile(
  statePath,
  JSON.stringify({
    api: {
      args: [
        '-m',
        'uvicorn',
        'edu_grader_api.e2e_app:app',
        '--host',
        '127.0.0.1',
        '--port',
        '18000',
      ],
      command: 'python',
    },
    databasePath,
    nonce,
    ownerPid: process.pid,
  }),
  'utf8',
)

if (process.platform === 'win32') {
  // Playwright force-kills webServer process trees on Windows. Start-Process
  // reparents the supervisor so it can observe this launcher disappearing.
  const command =
    'Start-Process -FilePath $env:E2E_NODE -ArgumentList $env:E2E_SUPERVISOR_ARGUMENTS -WindowStyle Hidden'
  const launched = spawnSync(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-Command', command],
    {
      encoding: 'utf8',
      env: {
        ...supervisorEnvironment,
        E2E_NODE: process.execPath,
        E2E_SUPERVISOR_ARGUMENTS: `"${supervisorPath}" "${statePath}"`,
      },
      windowsHide: true,
    },
  )
  if (launched.status !== 0) {
    await rm(statePath, { force: true })
    throw new Error(`Could not start E2E API supervisor: ${launched.stderr}`)
  }
} else {
  const supervisor = spawn(process.execPath, [supervisorPath, statePath], {
    detached: true,
    env: supervisorEnvironment,
    stdio: 'ignore',
  })
  supervisor.unref()
}

async function pathExists(path) {
  try {
    await access(path)
    return true
  } catch {
    return false
  }
}

const startupDeadline = Date.now() + 10_000
while (!(await pathExists(startedPath)) && Date.now() < startupDeadline) {
  await new Promise((resolveWait) => setTimeout(resolveWait, 50))
}
if (!(await pathExists(startedPath))) {
  await rm(statePath, { force: true })
  throw new Error('E2E API supervisor did not start')
}
const started = JSON.parse(await readFile(startedPath, 'utf8'))
if (started.nonce !== nonce) throw new Error('E2E API supervisor nonce mismatch')

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, async () => {
    await writeFile(stopPath, signal, 'utf8')
    process.exit(0)
  })
}

setInterval(async () => {
  if (!(await pathExists(statePath))) process.exit(1)
}, 250)
