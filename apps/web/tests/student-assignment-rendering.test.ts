// @vitest-environment happy-dom

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed, onMounted, ref, watch } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AssignmentPage from '../app/pages/student/assignments/[assignmentId].vue'
import '../app/assets/css/main.css'

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

async function mountAssignmentPage(readingMaterial: string | null): Promise<VueWrapper> {
  vi.stubGlobal('$fetch', vi.fn(async (url: string) => {
    if (url === '/api/auth/session') {
      return { id: 'student-1', tenant_id: 'tenant-1', csrf_token: 'csrf-token' }
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
    vi.stubGlobal('computed', computed)
    vi.stubGlobal('onMounted', onMounted)
    vi.stubGlobal('ref', ref)
    vi.stubGlobal('useRoute', () => ({ params: { assignmentId: 'assignment-1' } }))
    vi.stubGlobal('watch', watch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
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
})
