import { spawn } from 'node:child_process'
import { access, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, isAbsolute, relative, resolve } from 'node:path'

const statePath = resolve(process.argv[2])
const startedPath = `${statePath}.started`
const stopPath = `${statePath}.stop`
const pollInterval = Number(process.env.E2E_SUPERVISOR_POLL_INTERVAL_MS ?? 100)
const shutdownGraceMs = Number(process.env.E2E_SUPERVISOR_SHUTDOWN_GRACE_MS ?? 2_000)

const runtime = JSON.parse(await readFile(statePath, 'utf8'))
const databasePath = resolve(runtime.databasePath)
const stateRelativeToTemp = relative(resolve(tmpdir()), statePath)
const databaseRelativeToTemp = relative(resolve(tmpdir()), databasePath)
if (
  !Number.isInteger(runtime.ownerPid)
  || runtime.ownerPid <= 0
  || typeof runtime.nonce !== 'string'
  || !/^[0-9a-f-]+$/.test(runtime.nonce)
  || stateRelativeToTemp.startsWith('..')
  || isAbsolute(stateRelativeToTemp)
  || databaseRelativeToTemp.startsWith('..')
  || isAbsolute(databaseRelativeToTemp)
  || !/^edu-homework-grader-e2e-[0-9a-f-]+\.sqlite$/.test(basename(databasePath))
  || typeof runtime.api?.command !== 'string'
  || !Array.isArray(runtime.api.args)
) {
  throw new Error('Invalid E2E API supervisor state')
}

const api = spawn(runtime.api.command, runtime.api.args, {
  env: process.env,
  stdio: 'ignore',
  windowsHide: true,
})
await writeFile(
  startedPath,
  JSON.stringify({ apiPid: api.pid, nonce: runtime.nonce, supervisorPid: process.pid }),
  'utf8',
)

let finalized = false
let interval
let apiClosed = false
const apiClosedPromise = new Promise((resolveClose) => {
  api.once('close', (code) => {
    apiClosed = true
    resolveClose(code)
  })
})

function processIsRunning(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

async function pathExists(path) {
  try {
    await access(path)
    return true
  } catch {
    return false
  }
}

async function removeWithWindowsRetry(path) {
  const deadline = Date.now() + 5_000
  while (true) {
    try {
      await rm(path, { force: true })
      return
    } catch (error) {
      if (!['EBUSY', 'EPERM'].includes(error?.code) || Date.now() >= deadline) throw error
      await new Promise((resolveWait) => setTimeout(resolveWait, 100))
    }
  }
}

async function removeRuntimeFiles() {
  for (const suffix of ['', '-journal', '-wal', '-shm']) {
    await removeWithWindowsRetry(`${databasePath}${suffix}`)
  }
  await rm(statePath, { force: true })
  await rm(startedPath, { force: true })
  await rm(stopPath, { force: true })
}

async function waitForOwnedApiExit(signal = 'SIGTERM') {
  if (apiClosed) return
  api.kill(signal)
  await Promise.race([
    apiClosedPromise,
    new Promise((resolveTimeout) => setTimeout(resolveTimeout, shutdownGraceMs)),
  ])
  if (!apiClosed) {
    api.kill('SIGKILL')
    await apiClosedPromise
  }
}

async function finalize(exitCode, signal) {
  if (finalized) return
  finalized = true
  clearInterval(interval)
  await waitForOwnedApiExit(signal)
  await removeRuntimeFiles()
  process.exitCode = exitCode
}

api.once('error', () => finalize(1))
apiClosedPromise.then((code) => finalize(code ?? 1))

interval = setInterval(async () => {
  if (await pathExists(stopPath)) {
    const requestedSignal = (await readFile(stopPath, 'utf8')).trim()
    await finalize(0, requestedSignal === 'SIGINT' ? 'SIGINT' : 'SIGTERM')
    return
  }
  if (!processIsRunning(runtime.ownerPid)) {
    await finalize(0, 'SIGTERM')
  }
}, pollInterval)
