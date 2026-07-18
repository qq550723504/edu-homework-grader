export function previousQuestionIndex(current: number): number {
  return Math.max(0, current - 1)
}

export function nextQuestionIndex(current: number, count: number): number {
  return Math.min(Math.max(0, count - 1), current + 1)
}

export function getUnansweredCount(items: Array<{ answer: Record<string, unknown> | null }>): number {
  return items.filter((item) => {
    const value = item.answer?.value
    return value === null || value === undefined || value === ''
  }).length
}
