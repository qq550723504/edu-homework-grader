// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import HomePage from '../app/pages/index.vue'
import '../app/assets/css/main.css'

describe('homepage task entry', () => {
  beforeEach(() => {
    vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBase: 'http://api.example.test' } }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('presents the project website, trustworthy learning loop, and direct workspace entries', () => {
    const wrapper = mount(HomePage, {
      global: { stubs: { NuxtLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } },
    })

    expect(wrapper.get('header').text()).toContain('Edu Homework Grader')
    expect(wrapper.get('h1').text()).toBe('让作业、反馈与教学协作更清楚')
    expect(wrapper.get('a[href="/student"]').text()).toContain('进入学生工作台')
    expect(wrapper.get('a[href="/teacher"]').text()).toContain('进入教师工作台')
    expect(wrapper.get('#platform-capabilities').text()).toContain('英语与数学作业')
    expect(wrapper.get('#platform-capabilities').text()).toContain('订正')
    expect(wrapper.get('#trust-principles').text()).toContain('AI 辅助，不替代教师判断')
    expect(wrapper.text()).toContain('学生')
    expect(wrapper.text()).toContain('教师与学校')
    expect(wrapper.text()).toContain('家长')
    expect(wrapper.text()).not.toContain('Core API:')
    expect(wrapper.text()).not.toContain('生产已上线')

    wrapper.unmount()
  })
})
