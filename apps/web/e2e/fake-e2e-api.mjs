import { writeFile } from 'node:fs/promises'

const databasePath = process.argv[2]
await writeFile(databasePath, 'fictional e2e data', 'utf8')
setInterval(() => {}, 1_000)
