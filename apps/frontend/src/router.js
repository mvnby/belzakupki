import { createRouter, createWebHashHistory } from 'vue-router'
import { store } from './store.js'

// Lazy load views for efficiency
const Dashboard = () => import('./views/Dashboard.vue')
const Profiles = () => import('./views/Profiles.vue')
const Matches = () => import('./views/Matches.vue')
const Analytics = () => import('./views/Analytics.vue')
const Login = () => import('./views/Login.vue')
const Register = () => import('./views/Register.vue')
const CrmSettings = () => import('./views/CrmSettings.vue')
const AdminDashboard = () => import('./views/AdminDashboard.vue')
const Landing = () => import('./views/Landing.vue')

const routes = [
  {
    path: '/',
    redirect: () => {
      return store.isAuthenticated ? '/dashboard' : '/landing'
    }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: Dashboard,
    meta: { requiresAuth: true }
  },
  {
    path: '/admin',
    name: 'AdminDashboard',
    component: AdminDashboard,
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/landing',
    name: 'Landing',
    component: Landing
  },
  {
    path: '/profiles',
    name: 'Profiles',
    component: Profiles,
    meta: { requiresAuth: true }
  },
  {
    path: '/matches',
    name: 'Matches',
    component: Matches,
    meta: { requiresAuth: true }
  },
  {
    path: '/analytics',
    name: 'Analytics',
    component: Analytics,
    meta: { requiresAuth: true }
  },
  {
    path: '/login',
    name: 'Login',
    component: Login
  },
  {
    path: '/register',
    name: 'Register',
    component: Register
  },
  {
    path: '/crm-settings',
    name: 'CrmSettings',
    component: CrmSettings,
    meta: { requiresAuth: true }
  }
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes
})

// Authentication guard
router.beforeEach(async (to, from, next) => {
  // Load current user profile if token is set but user profile not loaded yet
  if (store.token && !store.user) {
    await store.loadUser()
  }

  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)
  const requiresAdmin = to.matched.some(record => record.meta.requiresAdmin)

  if (requiresAuth && !store.isAuthenticated) {
    // Try to load user profile in dev mode (auth may be disabled)
    const loaded = await store.loadUser()
    if (loaded) {
      if (requiresAdmin && (!store.user || store.user.role !== 'admin')) {
        next({ name: 'Dashboard' })
      } else {
        next()
      }
    } else {
      next({ name: 'Login' })
    }
  } else if (requiresAdmin && (!store.isAuthenticated || !store.user || store.user.role !== 'admin')) {
    next({ name: 'Dashboard' })
  } else if ((to.name === 'Login' || to.name === 'Register') && store.isAuthenticated) {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})
