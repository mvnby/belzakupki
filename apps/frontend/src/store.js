import { reactive, watch } from 'vue'

const TOKEN_KEY = 'belzakupki_token'

export const store = reactive({
  token: localStorage.getItem(TOKEN_KEY) || '',
  user: null,
  tenant: null,
  apiUrl: '', // Use current host as base URL for API requests
  isLoading: false,

  setToken(token) {
    this.token = token
    if (token) {
      localStorage.setItem(TOKEN_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_KEY)
      this.user = null
      this.tenant = null
    }
  },

  async fetch(endpoint, options = {}) {
    this.isLoading = true
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers
    }
    
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`
    }

    try {
      const response = await fetch(`${this.apiUrl}${endpoint}`, {
        ...options,
        headers
      })

      if (response.status === 401) {
        // Automatically logout on token expiration or invalid credentials
        this.setToken('')
        throw new Error('Сессия завершена. Войдите заново.')
      }

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || `Ошибка запроса: ${response.status}`)
      }

      // Check if it's streaming download
      const contentType = response.headers.get('content-type')
      if (contentType && contentType.includes('spreadsheetml')) {
        return response
      }

      return await response.json()
    } finally {
      this.isLoading = false
    }
  },

  async loadUser() {
    // If there is no token, do not attempt to auto-login, to allow guest view testing.
    if (!this.token) {
      return false
    }
    try {
      const user = await this.fetch('/api/auth/me')
      this.user = user
      this.tenant = { id: user.tenant_id, name: 'Моя организация' }
      return true
    } catch (e) {
      console.warn('Could not load user profile:', e.message)
      if (this.token) {
        this.setToken('')
      }
      return false
    }
  },

  get isAuthenticated() {
    return !!this.token || !!this.user
  }
})
