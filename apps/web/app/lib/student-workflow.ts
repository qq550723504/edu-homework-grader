export function previousQuestionIndex(current: number): number {
  return Math.max(0, current - 1)
}

export function nextQuestionIndex(current: number, count: number): number {
  return Math.min(Math.max(0, count - 1), current + 1)
}

export function getUnansweredCount(items: Array<{ answer: Record<string, unknown> | null }>): number {
  return items.filter((item) => {
    if (!item.answer) return true
    if (item.answer.format === 'mathjson-v1') {
      return typeof item.answer.latex !== 'string'
        || item.answer.latex.trim() === ''
        || item.answer.mathjson === null
        || item.answer.mathjson === undefined
    }
    const value = item.answer.value
    return value === null || value === undefined || value === ''
  }).length
}
