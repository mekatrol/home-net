import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

import App from '../App.vue'
import { pinia } from '../pinia'
import router from '../router'

describe('App', () => {
  it('renders the sign-in route', async () => {
    router.push('/sign-in')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router],
      },
    })

    await nextTick()
    expect(wrapper.text()).toContain('Sign In')
  })
})
