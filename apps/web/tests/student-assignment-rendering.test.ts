// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AssignmentPage from '../app/pages/student/assignments/[assignmentId].vue'
import '../app/assets/css/main.css'
import { resetDraftDatabase } from '../app/lib/drafts'

function assignmentDetail(readingMaterial: string | null) {
  return {
    id: 'assignment-1',
    title: 'English reading',
    status: 'pending',
    attempt: { id: 'attempt-1' },
    items: [
      {
        id: 'item-1',
        position: 1,
        prompt: 'Why did the students arrive late?',
        reading_material: readingMaterial,
        input: { kind: 'text-v1' },
        answer: null,
        version: 1
      }
    ]
  }
}

let requestedUrls: string[] = []

async function mountAssignmentPage(readingMaterial: string | null, saveFailure?: unknown | unknown[]): Promise<VueWrapper> {
  const saveFailures = Array.isArray(saveFailure) ? [...saveFailure] : [saveFailure]
  vi.stubGlobal('$fetch', vi.fn(async (url: string) => {
    requestedUrls.push(url)
    if (url === '/api/auth/session') {
      return { id: 'student-1', tenant_id: 'tenant-1', csrf_token: 'csrf-token' }
    }
    if (url.startsWith('/api/core/v1/student/attempts/')) {
      const failure = saveFailures.shift()
      if (failure) throw failure
      return { version: 2 }
    }
    return assignmentDetail(readingMaterial)
  }))
  const wrapper = mount(AssignmentPage, {
    attachTo: document.body,
    global: {
      stubs: {
        LogoutButton: true,
        MathAnswerField: true,
        NuxtLink: { template: '<a><slot /></a>' }
      }
    }
  })
  await flushPromises()
  return wrapper
}

describe('student assignment question rendering', () => {
  beforeEach(() => {
    requestedUrls = []
    vi.stubGlobal('computed', computed)
    vi.stubGlobal('onBeforeUnmount', onBeforeUnmount)
    vi.stubGlobal('navigator', { onLine: true })
    vi.stubGlobal('onMounted', onMounted)
    vi.stubGlobal('ref', ref)
    vi.stubGlobal('useRoute', () => ({ params: { assignmentId: 'assignment-1' } }))
    vi.stubGlobal('watch', watch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  afterEach(async () => {
    await resetDraftDatabase()
  })

  it('renders multiline reading material before the question prompt', async () => {
    const wrapper = await mountAssignmentPage('First line.\nSecond line.')
    const material = wrapper.get('.reading-material')
    const prompt = wrapper.get('h2')

    expect(material.text()).toBe('First line.\nSecond line.')
    expect(
      material.element.compareDocumentPosition(prompt.element)
      & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
    expect(getComputedStyle(material.element).whiteSpace).toBe('pre-wrap')

    wrapper.unmount()
  })

  it('does not render a reading material block for legacy null material', async () => {
    const wrapper = await mountAssignmentPage(null)

    expect(wrapper.find('.reading-material').exists()).toBe(false)
    expect(wrapper.get('h2').text()).toBe('Why did the students arrive late?')

    wrapper.unmount()
  })

  it('shows a safe validation message and keeps the answer editable', async () => {
    const wrapper = await mountAssignmentPage(null, {
      statusCode: 422,
      data: { detail: { code: 'mathjson_invalid', message: 'internal parser secret' } }
    })

    const input = wrapper.get('textarea[aria-label="答案"]')
    expect(input.attributes('disabled')).toBeUndefined()
    ;(input.element as HTMLTextAreaElement).value = 'synthetic answer'
    await (wrapper.vm.$ as { setupState: { saveDraft: (event: Event) => Promise<void> } }).setupState.saveDraft({ target: input.element } as Event)
    await flushPromises()

    expect(requestedUrls).toContain('/api/core/v1/student/attempts/attempt-1/answers/item-1')
    expect(wrapper.text()).toContain('答案格式需要修改后再同步。')
    expect(wrapper.get('textarea[aria-label="答案"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('secret')
    wrapper.unmount()
  })

  it('blocks additional writes after a processing restriction', async () => {
    const wrapper = await mountAssignmentPage(null, { statusCode: 403 })

    const input = wrapper.get('textarea[aria-label="答案"]')
    expect(input.attributes('disabled')).toBeUndefined()
    ;(input.element as HTMLTextAreaElement).value = 'synthetic answer'
    await (wrapper.vm.$ as { setupState: { saveDraft: (event: Event) => Promise<void> } }).setupState.saveDraft({ target: input.element } as Event)
    await flushPromises()

    expect(requestedUrls).toContain('/api/core/v1/student/attempts/attempt-1/answers/item-1')
    expect(wrapper.text()).toContain('当前无法处理作答，请联系教师或管理员。')
    expect(wrapper.get('textarea[aria-label="答案"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('requires an explicit choice when the server has a newer answer', async () => {
    const wrapper = await mountAssignmentPage(null, {
      statusCode: 409,
      data: { current: { answer: { format: 'text-v1', text: 'server answer' }, version: 2 } }
    })
    const input = wrapper.get('textarea[aria-label="答案"]')
    ;(input.element as HTMLTextAreaElement).value = 'local answer'
    await (wrapper.vm.$ as { setupState: { saveDraft: (event: Event) => Promise<void> } }).setupState.saveDraft({ target: input.element } as Event)
    await flushPromises()

    expect(wrapper.get('[data-testid="use-server-answer"]').text()).toBe('采用服务器答案')
    expect(wrapper.get('[data-testid="keep-local-answer"]').text()).toBe('保留我的答案')
    expect(wrapper.text()).not.toContain('server answer')
    wrapper.unmount()
  })

  it('refreshes the BFF session once before retrying a 401 save', async () => {
    const wrapper = await mountAssignmentPage(null, [{ statusCode: 401 }, undefined])
    const input = wrapper.get('textarea[aria-label="答案"]')
    ;(input.element as HTMLTextAreaElement).value = 'synthetic answer'
    await (wrapper.vm.$ as { setupState: { saveDraft: (event: Event) => Promise<void> } }).setupState.saveDraft({ target: input.element } as Event)
    await flushPromises()

    expect(requestedUrls.filter((url) => url === '/api/auth/session')).toHaveLength(2)
    expect(requestedUrls.filter((url) => url.startsWith('/api/core/v1/student/attempts/'))).toHaveLength(2)
    expect(wrapper.text()).toContain('已同步。')
    wrapper.unmount()
  })

  it('retries one rate-limited save using Retry-After without a tight loop', async () => {
    const wrapper = await mountAssignmentPage(null, [
      { response: { status: 429, headers: { get: () => '0' } } },
      undefined
    ])
    const input = wrapper.get('textarea[aria-label="答案"]')
    ;(input.element as HTMLTextAreaElement).value = 'synthetic answer'
    await (wrapper.vm.$ as { setupState: { saveDraft: (event: Event) => Promise<void> } }).setupState.saveDraft({ target: input.element } as Event)
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))
    await flushPromises()

    expect(requestedUrls.filter((url) => url.startsWith('/api/core/v1/student/attempts/'))).toHaveLength(2)
    wrapper.unmount()
  })

  it('removes named browser listeners when the assignment page unmounts', async () => {
    const removeEventListener = vi.spyOn(window, 'removeEventListener')
    const wrapper = await mountAssignmentPage(null)

    wrapper.unmount()

    expect(removeEventListener).toHaveBeenCalledWith('online', expect.any(Function))
    expect(removeEventListener).toHaveBeenCalledWith('offline', expect.any(Function))
    expect(removeEventListener).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
  })
})
