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

  it('guides students and teachers to their respective workspaces without exposing the API URL', () => {
    const wrapper = mount(HomePage, {
      global: {
        stubs: {
          NuxtLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
        },
      },
    })

    expect(wrapper.get('h1').text()).toBe('开始你的作业与教学工作')
    expect(wrapper.get('a[href="/student"]').text()).toBe('查看我的作业')
    expect(wrapper.get('a[href="/teacher"]').text()).toBe('进入教学工作台')
    expect(wrapper.text()).toContain('待完成作业')
    expect(wrapper.text()).toContain('创建作业')
    expect(wrapper.text()).toContain('为什么值得信赖')
    expect(wrapper.text()).not.toContain('Core API:')

    wrapper.unmount()
  })
})
