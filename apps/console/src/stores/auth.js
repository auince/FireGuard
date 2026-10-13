import { reactive, readonly } from 'vue'
import { post, setToken, request } from '@/api'
const state = reactive({ user: null, initialized: false, loading: false })
let generation = 0
function clear() {
  generation++
  state.user = null
  setToken('')
}
window.addEventListener('xf-auth-expired', () => {
  clear()
  window.location.assign('/login')
})
const login = async (payload) => {
  state.loading = true
  try {
    const reply = await post('/login', payload)
    generation++
    state.user = { ...reply.actor, displayName: reply.actor.username }
    setToken(reply.token)
    return state.user
  } finally {
    state.loading = false
  }
}
const logout = async () => {
  state.loading = true
  try {
    await post('/logout', {})
  } finally {
    clear()
    state.loading = false
  }
}
export const authState = readonly(state)
export const authActions = {
  initialize: async () => {
    if (!state.initialized) {
      try {
        const reply = await request('/me', { quiet401: true })
        state.user = reply.actor
      } catch {
      } finally {
        state.initialized = true
      }
    }
    return state.user
  },
  login,
  logout,
}
export const authGeneration = () => generation
