import type { TeacherQuestionVersion } from './teacher-api'

export type AssignmentSubject = 'english' | 'mathematics'

const subjectQuestionTypes: Record<AssignmentSubject, ReadonlySet<string>> = {
  english: new Set(['E1', 'E2', 'E3', 'E4']),
  mathematics: new Set(['M1', 'M2']),
}

export function availableQuestionsForSubject(
  questions: TeacherQuestionVersion[], subject: AssignmentSubject,
): TeacherQuestionVersion[] {
  return questions.filter((question) => question.status === 'published'
    && subjectQuestionTypes[subject].has(question.question_type))
}

export function addQuestionToComposition(
  selected: TeacherQuestionVersion[], question: TeacherQuestionVersion, subject: AssignmentSubject,
): TeacherQuestionVersion[] {
  if (question.status !== 'published'
    || !subjectQuestionTypes[subject].has(question.question_type)
    || selected.some((entry) => entry.id === question.id)) return selected
  return [...selected, question]
}

export function moveQuestion(
  selected: TeacherQuestionVersion[], index: number, offset: number,
): TeacherQuestionVersion[] {
  const destination = index + offset
  if (index < 0 || index >= selected.length || destination < 0 || destination >= selected.length) {
    return selected
  }
  const reordered = [...selected]
  const [question] = reordered.splice(index, 1)
  reordered.splice(destination, 0, question)
  return reordered
}

export function removeQuestion(
  selected: TeacherQuestionVersion[], questionVersionId: string,
): TeacherQuestionVersion[] {
  return selected.filter((question) => question.id !== questionVersionId)
}

export function compositionSummary(selected: TeacherQuestionVersion[]): {
  count: number
  totalScore: number
  types: Record<string, number>
} {
  return selected.reduce((summary, question) => {
    summary.count += 1
    summary.totalScore += question.max_score
    summary.types[question.question_type] = (summary.types[question.question_type] ?? 0) + 1
    return summary
  }, { count: 0, totalScore: 0, types: {} } as { count: number; totalScore: number; types: Record<string, number> })
}
