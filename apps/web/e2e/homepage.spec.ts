import { expect, test } from '@playwright/test'

test('homepage presents both workspace entries and the trustworthy learning loop on desktop', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('Edu Homework Grader｜作业、反馈与教学协作平台')
  await expect(page.getByRole('heading', { name: '让作业、反馈与教学协作更清楚' })).toBeVisible()
  const studentCtas = page.getByRole('link', { name: '进入学生工作台' })
  const teacherCtas = page.getByRole('link', { name: '进入教师工作台' })
  await expect(studentCtas).toHaveCount(3)
  await expect(teacherCtas).toHaveCount(3)
  for (const studentCta of await studentCtas.all()) await expect(studentCta).toHaveAttribute('href', '/student')
  for (const teacherCta of await teacherCtas.all()) await expect(teacherCta).toHaveAttribute('href', '/teacher')
  await expect(page.getByRole('heading', { name: '从作业到订正，学习过程有迹可循' })).toBeVisible()
  await expect(page.getByText('AI 辅助，不替代教师判断')).toBeVisible()
  const [student, teacher] = await Promise.all([page.locator('.homepage__student-entry').boundingBox(), page.locator('.homepage__teacher-entry').boundingBox()])
  expect(student).not.toBeNull(); expect(teacher).not.toBeNull(); expect(Math.abs(student!.y - teacher!.y)).toBeLessThan(8)
  await page.addStyleTag({ content: 'html { scrollbar-gutter: stable; }' })
  const [homepage, tinted] = await Promise.all([page.locator('.homepage').boundingBox(), page.locator('.homepage__section--tinted').boundingBox()])
  expect(homepage).not.toBeNull(); expect(tinted).not.toBeNull()
  expect(tinted!.x).toBeCloseTo(homepage!.x, 1)
  expect(tinted!.width).toBeCloseTo(homepage!.width, 1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('homepage remains single-column and without horizontal overflow at 320px', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 320, height: 720 } }); const page = await context.newPage()
  try {
    await page.goto('/')
    const [student, teacher] = await Promise.all([page.locator('.homepage__student-entry').boundingBox(), page.locator('.homepage__teacher-entry').boundingBox()])
    expect(student).not.toBeNull(); expect(teacher).not.toBeNull(); expect(teacher!.y).toBeGreaterThan(student!.y + student!.height)
    await expect(page.getByRole('link', { name: '平台能力' })).toHaveCSS('min-height', '44px')
    await expect(page.getByRole('link', { name: '为什么可信' })).toHaveCSS('min-height', '44px')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  } finally { await context.close() }
})
