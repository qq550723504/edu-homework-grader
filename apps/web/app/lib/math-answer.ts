export type MathAnswer = {
  format: 'mathjson-v1'
  latex: string
  mathjson: unknown
}

export type MathFieldValue = {
  value: string
  getValue(format: 'math-json'): string
}

export function toMathAnswer(field: MathFieldValue): MathAnswer | null {
  const latex = field.value.trim()
  if (!latex) return null
  try {
    const mathjson: unknown = JSON.parse(field.getValue('math-json'))
    if (mathjson === null || mathjson === '' || (Array.isArray(mathjson) && mathjson.length === 0)) {
      return null
    }
    return { format: 'mathjson-v1', latex, mathjson }
  } catch {
    return null
  }
}
