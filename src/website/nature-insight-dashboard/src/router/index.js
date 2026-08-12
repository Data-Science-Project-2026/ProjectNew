import { createRouter, createWebHistory } from 'vue-router'

import Species from '../views/Species.vue'
import Activities from '../views/Activities.vue'
import HumanResponses from '../views/HumanResponses.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/species' },
    { path: '/species', component: Species },
    { path: '/activities', component: Activities },
    { path: '/responses', component: HumanResponses }
  ]
})

export default router