import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { access, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const e2eDirectory = dirname(fileURLToPath(import.meta.url))
const supervisorPath = join(e2eDirectory, 'e2e-api-supervisor.mjs')
const fakeApiPath = join(e2eDirectory, 'fake-e2e-api.mjs')
const launcherPath = join(e2eDirectory, 'start-e2e-api.mjs')

async function waitUntil(predicate, message) {
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise((resolveWait) => setTimeout(resolveWait, 25))
  }
  throw new Error(message)
}

async function pathExists(path) {
  try {
    await access(path)
    return true
  } catch {
    return false
  }
}

function databaseFamilyPaths(databasePath) {
  return ['', '-journal', '-wal', '-shm'].map((suffix) => `${databasePath}${suffix}`)
}

async function databaseFamilyIsGone(databasePath) {
  const existence = await Promise.all(databaseFamilyPaths(databasePath).map(pathExists))
  return existence.every((exists) => !exists)
}

test('normal stop removes every nonce-scoped SQLite artifact after API close', async (t) => {
  await access(supervisorPath)
  const nonce = randomUUID()
  const databasePath = join(tmpdir(), `edu-homework-grader-e2e-${nonce}.sqlite`)
  const statePath = join(tmpdir(), `edu-homework-grader-e2e-${nonce}.json`)
  const startedPath = `${statePath}.started`
  const owner = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    stdio: 'ignore',
  })
  let supervisor

  t.after(async () => {
    owner.kill()
    supervisor?.kill()
    await Promise.all([
      ...databaseFamilyPaths(databasePath).map((path) => rm(path, { force: true })),
      ...['', '.started', '.stop'].map((suffix) => rm(`${statePath}${suffix}`, { force: true })),
    ])
  })

  await writeFile(
    statePath,
    JSON.stringify({
      api: { args: [fakeApiPath, databasePath], command: process.execPath },
      databasePath,
      nonce,
      ownerPid: owner.pid,
    }),
    'utf8',
  )
  supervisor = spawn(process.execPath, [supervisorPath, statePath], {
    env: {
      ...process.env,
      E2E_SUPERVISOR_POLL_INTERVAL_MS: '20',
      E2E_SUPERVISOR_SHUTDOWN_GRACE_MS: '100',
    },
    stdio: 'ignore',
  })

  await waitUntil(
    async () => pathExists(startedPath) && pathExists(databasePath),
    'supervisor did not start its API child',
  )
  const { apiPid } = JSON.parse(await readFile(startedPath, 'utf8'))
  assert.equal(Number.isInteger(apiPid), true)

  await writeFile(`${statePath}.stop`, 'SIGTERM', 'utf8')
  const exitCode = await new Promise((resolveExit) => supervisor.once('exit', resolveExit))

  assert.equal(exitCode, 0)
  assert.equal(await databaseFamilyIsGone(databasePath), true)
  assert.equal(await pathExists(statePath), false)
  assert.equal(await pathExists(startedPath), false)
})

test('nonce mismatches refuse cleanup without deleting either target', {
  timeout: 20_000,
}, async (t) => {
  const cases = [
    {
      databaseNonce: randomUUID(),
      runtimeNonce: randomUUID(),
      stateNonce: undefined,
    },
    {
      databaseNonce: undefined,
      runtimeNonce: randomUUID(),
      stateNonce: randomUUID(),
    },
  ]

  for (const mismatch of cases) {
    const databaseNonce = mismatch.databaseNonce ?? mismatch.runtimeNonce
    const stateNonce = mismatch.stateNonce ?? mismatch.runtimeNonce
    const databasePath = join(tmpdir(), `edu-homework-grader-e2e-${databaseNonce}.sqlite`)
    const statePath = join(tmpdir(), `edu-homework-grader-e2e-${stateNonce}.json`)
    await writeFile(databasePath, 'must survive rejected cleanup', 'utf8')
    await writeFile(
      statePath,
      JSON.stringify({
        api: { args: [fakeApiPath, databasePath], command: process.execPath },
        databasePath,
        nonce: mismatch.runtimeNonce,
        ownerPid: 2_147_483_647,
      }),
      'utf8',
    )
    t.after(async () => {
      await Promise.all([
        ...databaseFamilyPaths(databasePath).map((path) => rm(path, { force: true })),
        ...['', '.started', '.stop'].map((suffix) => rm(`${statePath}${suffix}`, { force: true })),
      ])
    })

    const supervisor = spawn(process.execPath, [supervisorPath, statePath], { stdio: 'ignore' })
    const exitCode = await new Promise((resolveExit) => supervisor.once('exit', resolveExit))

    assert.notEqual(exitCode, 0)
    assert.equal(await readFile(databasePath, 'utf8'), 'must survive rejected cleanup')
  }
})

test('polluted parent identity environment cannot change the real E2E identity', {
  timeout: 30_000,
}, async (t) => {
  const statePrefix = 'edu-homework-grader-e2e-'
  const statesBefore = new Set(
    (await readdir(tmpdir())).filter((name) => name.startsWith(statePrefix) && name.endsWith('.json')),
  )
  const launcher = spawn(process.execPath, [launcherPath], {
    env: {
      ...process.env,
      APP_ENV: 'production',
      OIDC_ISSUER: 'https://conflicting-issuer.example.test/realms/wrong',
      OIDC_TENANT_SLUG: 'wrong-tenant',
    },
    stdio: 'ignore',
  })
  let statePath

  t.after(() => launcher.kill('SIGKILL'))

  await waitUntil(async () => {
    const stateName = (await readdir(tmpdir())).find(
      (name) => name.startsWith(statePrefix)
        && name.endsWith('.json')
        && !statesBefore.has(name),
    )
    if (!stateName) return false
    statePath = join(tmpdir(), stateName)
    return pathExists(`${statePath}.started`)
  }, 'launcher did not start its independent API supervisor')

  const { databasePath } = JSON.parse(await readFile(statePath, 'utf8'))
  await waitUntil(() => pathExists(databasePath), 'E2E API did not create its SQLite database')
  await waitUntil(async () => {
    try {
      const response = await fetch('http://127.0.0.1:18000/v1/student/assignments', {
        headers: { Authorization: 'Bearer e2e-student-token' },
      })
      return response.status === 200
    } catch {
      return false
    }
  }, 'fixed E2E student identity did not survive polluted parent OIDC settings')

  launcher.kill('SIGKILL')

  await waitUntil(
    async () => (await databaseFamilyIsGone(databasePath))
      && !(await pathExists(statePath))
      && !(await pathExists(`${statePath}.started`)),
    'supervisor did not clean runtime files after forced launcher exit',
  )

  assert.equal(await databaseFamilyIsGone(databasePath), true)
})
