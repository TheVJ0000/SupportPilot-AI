import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'

const bundleDirectory = path.resolve('dist')
const protectedVariables = ['SUPABASE_SECRET_KEY', 'GEMINI_API_KEY', 'RESEND_API_KEY']

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...(await filesUnder(target)))
    else files.push(target)
  }
  return files
}

const forbidden = protectedVariables.map((name) => ({ category: name, value: name }))
for (const name of protectedVariables) {
  const value = process.env[name]
  if (value && value.length >= 12) forbidden.push({ category: `${name} value`, value })
}

const findings = new Set()
for (const file of await filesUnder(bundleDirectory)) {
  const content = await readFile(file)
  const text = content.toString('utf8')
  for (const candidate of forbidden) {
    if (text.includes(candidate.value)) findings.add(candidate.category)
  }
}

if (findings.size > 0) {
  console.error(`Frontend bundle secret check failed for: ${[...findings].join(', ')}`)
  process.exitCode = 1
} else {
  console.log('Frontend bundle secret check passed.')
}
