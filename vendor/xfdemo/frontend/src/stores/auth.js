import { reactive, readonly } from 'vue'
import {
  fetchCurrentUser,
  loginAccount,
  logoutAccount,
  registerAccount
} from '@/api'


const state = reactive({
  user: null,
  initialized: false,
  loading: false
})

let initializationPromise = null

const setUser = (user) => {
  state.user = user || null
  state.initialized = true
}

const initialize = async () => {
  if (state.initialized) return state.user
  if (initializationPromise) return initializationPromise
  initializationPromise = fetchCurrentUser()
    .then((payload) => {
      setUser(payload?.user)
      return state.user
    })
    .catch(() => {
      setUser(null)
      return null
    })
    .finally(() => {
      initializationPromise = null
    })
  return initializationPromise
}

const login = async (payload) => {
  state.loading = true
  try {
    const response = await loginAccount(payload)
    setUser(response.user)
    return response.user
  } finally {
    state.loading = false
  }
}

const register = async (payload) => {
  state.loading = true
  try {
    const response = await registerAccount(payload)
    setUser(response.user)
    return response.user
  } finally {
    state.loading = false
  }
}

const logout = async () => {
  state.loading = true
  try {
    await logoutAccount()
  } finally {
    setUser(null)
    state.loading = false
  }
}

export const authState = readonly(state)
export const authActions = { initialize, login, register, logout, setUser }
