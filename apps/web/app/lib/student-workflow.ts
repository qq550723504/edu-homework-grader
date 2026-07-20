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
    if (item.answer.format !== 'text-v1') return true
    const text = item.answer.text
    return typeof text !== 'string' || text === ''
  }).length
}

export function isAssignmentWritable(status: string | undefined): boolean {
  return !['overdue', 'submitted_pending_review', 'completed', 'correction_required'].includes(status ?? '')
}

export function editorStateForItem(item: { answer: Record<string, unknown> | null } | undefined): {
  text: string
  mathAnswer: Record<string, unknown> | null
} {
  const answer = item?.answer
  if (answer?.format === 'mathjson-v1') return { text: '', mathAnswer: answer }
  return {
    text: answer?.format === 'text-v1' && typeof answer.text === 'string' ? answer.text : '',
    mathAnswer: null
  }
}
