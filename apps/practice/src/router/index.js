import {createRouter,createWebHistory} from 'vue-router'
import {authState} from '@/stores/auth'
const routes=[
 {path:'/login',name:'Login',component:()=>import('@/views/AuthView.vue'),meta:{public:true,authLayout:true}},
 {path:'/',name:'Home',component:()=>import('@/views/AboutView.vue')},
 {path:'/inspect',name:'Inspect',component:()=>import('@/views/InspectView.vue')},
 {path:'/history',name:'History',component:()=>import('@/views/HistoryView.vue')},
 {path:'/reports/:id',name:'Report',component:()=>import('@/views/ReportView.vue')},
 {path:'/review',name:'Review',component:()=>import('@/views/ReviewView.vue')},
 {path:'/regulations',name:'Regulations',component:()=>import('@/views/RegulationKnowledgeView.vue')},
 {path:'/monitor',name:'Monitor',component:()=>import('@/views/MonitorView.vue')},
 {path:'/:pathMatch(.*)*',redirect:'/'}
]
const router=createRouter({history:createWebHistory(),routes,scrollBehavior:()=>({top:0})})
router.beforeEach(to=>{if(!to.meta.public&&!authState.user)return {name:'Login',query:{redirect:to.fullPath}};if(to.meta.authLayout&&authState.user)return '/';return true})
export default router
