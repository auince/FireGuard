<script setup>
import {reactive,ref} from 'vue'
import {useRouter,useRoute} from 'vue-router'
import {ShieldCheck,ArrowRight,UserRound,LockKeyhole,BadgeCheck,Eye,EyeOff} from 'lucide-vue-next'
import {authActions,authState} from '@/stores/auth'
const router=useRouter(),route=useRoute(),form=reactive({username:'',password:''}),error=ref(''),show=ref(false)
async function submit(){error.value='';try{await authActions.login(form);const redirect=route.query.redirect;await router.replace(typeof redirect==='string'&&redirect.startsWith('/')&&!redirect.startsWith('//')?redirect:'/')}catch(e){error.value=e.message}}
</script>
<template><div class="auth-page"><section class="auth-shell" aria-label="消防 Agent 登录"><aside class="auth-brand"><div class="auth-brand__identity"><span class="auth-brand__mark"><ShieldCheck :size="24"/></span><span class="auth-brand__name">消防 Agent</span></div><div class="auth-brand__copy"><p class="auth-brand__eyebrow">XF AGENT · INSPECTION</p><h1>看见隐患，<br>也看见依据。</h1><p>问题与照片、法规原文、人工审核，在清晰的流程里形成可追溯记录。</p></div><div class="auth-brand__footer"><span>简历练手原型</span><span>QWEN3.5-9B</span></div></aside><div class="auth-panel"><div class="auth-panel__topline"><span><BadgeCheck :size="16"/>受保护的工作区</span><span>XFAgent</span></div><div class="auth-panel__inner"><header class="auth-panel__header"><p>WELCOME BACK</p><h2>登录工作台</h2><span>使用已初始化的巡检员、复核员或管理员账号。</span></header><form class="auth-form" @submit.prevent="submit"><label class="auth-field"><span>用户名</span><span class="auth-field__control"><UserRound :size="18"/><input v-model.trim="form.username" autocomplete="username" required maxlength="100" placeholder="输入用户名"></span></label><label class="auth-field"><span>密码</span><span class="auth-field__control"><LockKeyhole :size="18"/><input v-model="form.password" :type="show?'text':'password'" autocomplete="current-password" required maxlength="200" placeholder="输入密码"><button type="button" :aria-label="show?'隐藏密码':'显示密码'" @click="show=!show"><EyeOff v-if="show" :size="17"/><Eye v-else :size="17"/></button></span></label><p v-if="error" role="alert" class="auth-error">{{error}}</p><button class="auth-submit" :disabled="authState.loading"><span>{{authState.loading?'正在验证':'进入工作台'}}</span><ArrowRight :size="18"/></button></form><p class="auth-switch">账号凭据由本项目初始化工具生成，请从服务器私有凭据文件获取。</p></div></div></section></div></template>

<style scoped>
.auth-page {
  --auth-accent: #c94741;
  --auth-accent-dark: #ab3934;
  --auth-ink: #24292e;
  --auth-muted: #6f777e;
  position: relative;
  width: 100%;
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 34px;
  overflow: hidden;
  background: #e8ecee;
}

.auth-page::before,
.auth-page::after {
  content: '';
  position: absolute;
  pointer-events: none;
}

.auth-page::before {
  inset: 0;
  border: 12px solid rgba(255, 255, 255, 0.34);
}

.auth-page::after {
  top: 0;
  left: 50%;
  width: 88px;
  height: 4px;
  background: var(--auth-accent);
  transform: translateX(-50%);
}

.auth-shell {
  position: relative;
  z-index: 1;
  width: min(1080px, 100%);
  min-height: 660px;
  display: grid;
  grid-template-columns: 390px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #d8dde0;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(40, 48, 54, 0.1);
}

.auth-brand {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 42px 40px 36px;
  overflow: hidden;
  color: var(--auth-ink);
  background: #eef1f1;
}

.auth-brand::before,
.auth-brand::after {
  content: '';
  position: absolute;
  right: -92px;
  width: 260px;
  height: 260px;
  border: 1px solid rgba(78, 92, 98, 0.1);
  border-radius: 50%;
}

.auth-brand::before { bottom: 52px; }
.auth-brand::after { bottom: -36px; right: -20px; }

.auth-brand__identity {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 12px;
  width: max-content;
}

.auth-brand__mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 7px;
  color: #fff;
  background: var(--auth-accent);
  box-shadow: 0 8px 20px rgba(201, 71, 65, 0.2);
}

.auth-brand__name {
  color: var(--auth-ink);
  font-size: 19px;
  font-weight: 750;
}

.auth-brand__copy {
  position: relative;
  z-index: 1;
  margin: auto 0;
}

.auth-brand__eyebrow,
.auth-panel__header > p {
  margin: 0;
  color: var(--auth-accent);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0;
}

.auth-brand h1 {
  margin: 16px 0 0;
  font-size: 36px;
  line-height: 1.38;
  color: #1f2529;
  letter-spacing: 0;
}

.auth-brand__copy > p:last-child {
  max-width: 280px;
  margin: 22px 0 0;
  color: #697279;
  font-size: 14px;
  line-height: 1.85;
}

.auth-brand__footer {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 18px;
  border-top: 1px solid #d4d9db;
  color: #858d93;
  font-size: 10px;
}

.auth-brand__status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #4f585e;
  font-size: 12px;
}

.auth-brand__status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #318968;
  box-shadow: 0 0 0 4px rgba(49, 137, 104, 0.11);
}

.auth-brand__version { white-space: nowrap; }

.auth-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 30px 56px 44px;
  background: #fcfcfb;
}

.auth-panel__topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 20px;
  border-bottom: 1px solid #e4e7e8;
  color: #969da2;
  font-size: 10px;
}

.auth-panel__topline span:first-child {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #5d656a;
  font-size: 12px;
  font-weight: 650;
}

.auth-panel__topline svg { color: var(--auth-accent); }

.auth-panel__inner {
  width: min(430px, 100%);
  margin: auto;
  padding: 32px 0 8px;
}

.auth-panel__header h2 {
  margin: 9px 0 8px;
  color: var(--auth-ink);
  font-size: 29px;
  line-height: 1.3;
  letter-spacing: 0;
}

.auth-panel__header > span {
  color: var(--auth-muted);
  font-size: 13px;
  line-height: 1.7;
}

.auth-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 26px 0 22px;
  border-bottom: 1px solid #dfe3e5;
}

.auth-tabs a {
  position: relative;
  padding: 10px 12px 12px;
  color: #8a8f96;
  font-size: 14px;
  font-weight: 650;
  text-align: center;
}

.auth-tabs a::after {
  content: '';
  position: absolute;
  right: 14px;
  bottom: -1px;
  left: 14px;
  height: 2px;
  background: transparent;
}

.auth-tabs a.active { color: #202329; }
.auth-tabs a.active::after { background: var(--auth-accent); }

.auth-form { display: grid; gap: 16px; }

.auth-form__row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: 14px;
}

.auth-form__row > .auth-field {
  width: 100%;
  min-width: 0;
}

.auth-field {
  display: grid;
  gap: 7px;
  min-width: 0;
  color: #50545b;
  font-size: 12px;
  font-weight: 650;
}

.auth-field__label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.auth-field__label small {
  color: #989ea4;
  font-size: 10px;
  font-weight: 500;
}

.auth-field__control {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 50px;
  padding: 0 14px;
  overflow: hidden;
  box-sizing: border-box;
  border: 1px solid #d9dee1;
  border-radius: 7px;
  color: #969ba3;
  background: #f7f8f8;
  transition: border-color 150ms ease, box-shadow 150ms ease, background 150ms ease;
}

.auth-field__control > svg { flex: 0 0 auto; }

.auth-field__control:focus-within {
  border-color: var(--auth-accent);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(201, 71, 65, 0.08);
}

.auth-field__control input {
  width: 0;
  min-width: 0;
  flex: 1 1 0;
  border: 0;
  outline: 0;
  color: var(--auth-ink);
  font-size: 14px;
  background: transparent;
}

.auth-field__control input::placeholder { color: #a6aab1; }

.auth-field__reveal {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 5px;
  color: #858a92;
}

.auth-field__reveal:hover { color: #292c31; background: #eef0f2; }

.auth-error {
  margin: 0;
  padding: 10px 12px;
  border-left: 3px solid var(--auth-accent);
  border-radius: 4px;
  color: #ae2c29;
  font-size: 12px;
  background: #fdf0ef;
}

.auth-submit {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 52px;
  margin-top: 3px;
  padding: 0 18px;
  border-radius: 7px;
  color: #fff;
  font-size: 14px;
  font-weight: 720;
  background: var(--auth-accent);
  box-shadow: 0 10px 22px rgba(201, 71, 65, 0.18);
  transition: background 150ms ease, transform 150ms ease, box-shadow 150ms ease;
}

.auth-submit > span { display: inline-flex; align-items: center; gap: 9px; }

.auth-submit:hover:not(:disabled) {
  background: var(--auth-accent-dark);
  box-shadow: 0 12px 26px rgba(201, 71, 65, 0.22);
  transform: translateY(-1px);
}

.auth-submit:disabled { cursor: wait; opacity: 0.72; }

.auth-submit__spinner {
  width: 15px;
  height: 15px;
  border: 2px solid rgba(255, 255, 255, 0.45);
  border-top-color: #fff;
  border-radius: 50%;
  animation: auth-spin 700ms linear infinite;
}

.auth-switch {
  margin: 19px 0 0;
  color: #858a92;
  font-size: 12px;
  text-align: center;
}

.auth-switch a {
  margin-left: 5px;
  color: var(--auth-accent);
  font-weight: 700;
}

@keyframes auth-spin { to { transform: rotate(360deg); } }

@media (max-width: 980px) {
  .auth-page { padding: 20px; place-items: start center; }
  .auth-shell { min-height: calc(100vh - 40px); grid-template-columns: 1fr; }
  .auth-brand { min-height: 150px; padding: 25px 26px; }
  .auth-brand__copy { margin: 24px 0 0; }
  .auth-brand__copy > p:last-child,
  .auth-brand__footer,
  .auth-brand::before,
  .auth-brand::after { display: none; }
  .auth-brand h1 { margin-top: 8px; font-size: 26px; line-height: 1.35; }
  .auth-brand__eyebrow { display: none; }
  .auth-panel { padding: 22px 30px 38px; }
  .auth-panel__topline { padding-bottom: 16px; }
  .auth-panel__inner { width: min(460px, 100%); margin: 0 auto; padding-top: 28px; }
}

@media (max-width: 520px) {
  .auth-page { padding: 0; background: #fff; }
  .auth-page::before,
  .auth-page::after { display: none; }
  .auth-shell { min-height: 100vh; border: 0; border-radius: 0; box-shadow: none; }
  .auth-brand { min-height: 120px; padding: 22px 20px; }
  .auth-brand__mark { width: 36px; height: 36px; }
  .auth-brand__name { font-size: 17px; }
  .auth-brand__copy { margin-top: 17px; }
  .auth-brand h1 { font-size: 22px; }
  .auth-brand h1 br { display: none; }
  .auth-panel { padding: 18px 20px 34px; }
  .auth-panel__topline span:last-child { display: none; }
  .auth-panel__inner { padding-top: 24px; }
  .auth-panel__header h2 { font-size: 26px; }
  .auth-form__row { grid-template-columns: 1fr; }
  .auth-field__label small { display: none; }
}
</style>
