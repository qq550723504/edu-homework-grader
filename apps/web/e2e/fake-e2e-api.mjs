import { writeFile } from 'node:fs/promises'

const databasePath = process.argv[2]
await Promise.all(
  ['', '-journal', '-wal', '-shm'].map((suffix) =>
    writeFile(`${databasePath}${suffix}`, `fictional e2e data${suffix}`, 'utf8'),
  ),
)
setInterval(() => {}, 1_000)
