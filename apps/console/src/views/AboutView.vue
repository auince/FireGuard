<script setup>
import {
  ArrowRight,
  BadgeCheck,
  Boxes,
  BrainCircuit,
  DoorOpen,
  FireExtinguisher,
  ScanSearch,
  ShieldCheck,
  Waves,
} from 'lucide-vue-next'

const capabilities = [
  {
    name: '外观与标识',
    desc: '辅助核查可见标识、操作说明与铭牌，模糊内容需现场确认。',
    icon: ScanSearch,
    tags: ['标识', '说明', '铭牌', '箱门'],
  },
  {
    name: '箱体结构',
    desc: '检查箱门、玻璃、锁具及箱体的完整性与可用状态。',
    icon: DoorOpen,
    tags: ['破损', '锈蚀', '启闭', '遮挡'],
  },
  {
    name: '内部组件',
    desc: '围绕水带、水枪、栓体、阀门等组件生成待核查建议。',
    icon: Boxes,
    tags: ['在位', '连接', '完整', '状态'],
  },
  {
    name: '软管卷盘',
    desc: '分析供水软管的卷绕、连接以及明显折弯与挤压情况。',
    icon: Waves,
    tags: ['卷盘', '软管', '折弯', '连接'],
  },
  {
    name: '灭火器',
    desc: '检查灭火器组件有无、外观完整性和可见摆放异常。',
    icon: FireExtinguisher,
    tags: ['有无', '外观', '附件', '摆放'],
  },
]

const foundations = [
  {
    name: 'Qwen3.5-9B 模型',
    desc: '结合问题、设施照片与条款原文，生成结构化巡检草稿。',
    icon: BrainCircuit,
  },
  {
    name: '可信法规检索',
    desc: '融合关键词与向量召回，回填原始条款并核验文档生效状态。',
    icon: ScanSearch,
  },
  {
    name: '可信结果校验',
    desc: '固定五节点执行链路，验证通过后仍需人工审核，保留过程记录。',
    icon: ShieldCheck,
  },
]

// Note: Foundation descriptions reflect the design, not measured performance claims
</script>

<template>
  <div class="about">
    <div class="about__container container">
      <header class="about-hero">
        <div class="about-hero__image" aria-hidden="true"></div>
        <div class="about-hero__content">
          <span class="about-hero__mark">消防设施智能巡检</span>
          <h1>
            <span>看见隐患，</span>
            <strong>也看见依据。</strong>
          </h1>
          <p>提交巡检问题与设施照片，检索法规原文，形成可复核的隐患说明和整改建议。</p>
          <router-link to="/inspect" class="about-hero__action">
            提交巡检
            <ArrowRight :size="18" />
          </router-link>
        </div>
        <div class="about-hero__footnote">
          <BadgeCheck :size="18" />
          <span>从现场图像到结构化结论，条款可核验 · 报告待人工审核</span>
        </div>
      </header>

      <section class="about-intro">
        <p class="about-kicker">关于系统</p>
        <div class="about-intro__content">
          <h2>让复杂的巡检判断，<br />变得清楚、稳定、可复核。</h2>
          <div class="about-intro__copy">
            <p>
              消防 Agent 以 Qwen3.5-9B
              模型为核心，协同可信法规检索与专业校验机制，对消防设施进行识别、分析和记录。
            </p>
            <p>
              系统保留问题、照片、条款引用和审核过程，形成完整的巡检记录链路。以下为核查方向，实际检测范围以现场照片质量和条款覆盖度为准。
            </p>
          </div>
        </div>
      </section>

      <section class="about-capabilities">
        <div class="about-section-heading">
          <div>
            <p class="about-kicker">检测范围</p>
            <h2>围绕常见消防设施提出核查问题</h2>
          </div>
          <span>围绕现场可见证据进行判断</span>
        </div>

        <div class="capability-list">
          <article v-for="(item, index) in capabilities" :key="item.name" class="capability-row">
            <span class="capability-row__index">0{{ index + 1 }}</span>
            <span class="capability-row__icon"><component :is="item.icon" :size="21" /></span>
            <h3>{{ item.name }}</h3>
            <p>{{ item.desc }}</p>
            <div class="capability-row__tags">
              <span v-for="tag in item.tags" :key="tag">{{ tag }}</span>
            </div>
          </article>
        </div>
      </section>

      <section class="about-foundation">
        <div class="about-section-heading">
          <div>
            <p class="about-kicker">核心能力</p>
            <h2>为可靠判断搭建智能基础</h2>
          </div>
        </div>

        <div class="foundation-grid">
          <article v-for="item in foundations" :key="item.name" class="foundation-item">
            <component :is="item.icon" :size="24" />
            <h3>{{ item.name }}</h3>
            <p>{{ item.desc }}</p>
          </article>
        </div>
      </section>

      <section class="about-cta">
        <div>
          <span>开始一次完整巡检</span>
          <h2>上传现场图片，获得清晰的检测结论。</h2>
        </div>
        <router-link to="/inspect" class="about-cta__button" aria-label="立即体验智能检测">
          <ArrowRight :size="21" />
        </router-link>
      </section>
    </div>
  </div>
</template>

<style scoped>
.about {
  min-height: 100vh;
  padding: 96px 0 64px;
  background: #f4f6f5;
  color: #202523;
}

.about__container {
  max-width: 1180px;
}

.about-hero {
  position: relative;
  min-height: 520px;
  overflow: hidden;
  border-radius: 8px;
  background: #dfe3e1;
  box-shadow: 0 14px 36px rgba(30, 36, 33, 0.1);
}

.about-hero::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 1;
  width: 50%;
  background: rgba(247, 249, 248, 0.9);
}

.about-hero__image {
  background: linear-gradient(135deg, #213747, #0c1821);
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  filter: saturate(0.9) contrast(0.98);
}

.about-hero__content {
  position: relative;
  z-index: 1;
  width: min(46%, 510px);
  padding: 64px 0 0 58px;
}

.about-hero__mark {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
  color: #8f3733;
  font-size: 13px;
  font-weight: 650;
}

.about-hero__mark::before {
  content: '';
  width: 24px;
  height: 2px;
  background: #bd4c46;
}

.about-hero h1 {
  display: grid;
  margin: 0;
  color: #27312d;
  font-size: clamp(42px, 4.8vw, 62px);
  font-weight: 650;
  line-height: 1.16;
  letter-spacing: 0;
}

.about-hero h1 span,
.about-hero h1 strong {
  display: block;
  font: inherit;
}

.about-hero h1 strong {
  color: #973c37;
}

.about-hero__content p {
  max-width: 430px;
  margin: 24px 0 30px;
  color: #46514c;
  font-size: 15px;
  font-weight: 450;
  line-height: 1.9;
}

.about-hero__action {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 46px;
  padding: 0 20px;
  border-radius: 6px;
  background: #c84b45;
  color: #fff;
  font-weight: 700;
  text-decoration: none;
  transition:
    background 0.2s ease,
    transform 0.2s ease;
}

.about-hero__action:hover {
  background: #a63a35;
  transform: translateY(-1px);
}

.about-hero__footnote {
  position: absolute;
  bottom: 30px;
  left: 58px;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 9px;
  color: #6a736f;
  font-size: 13px;
}

.about-hero__footnote svg {
  color: #c84b45;
}

.about-intro,
.about-capabilities,
.about-foundation {
  padding-top: 78px;
}

.about-kicker {
  margin: 0 0 16px;
  color: #c84b45;
  font-size: 13px;
  font-weight: 700;
}

.about-intro__content {
  display: grid;
  grid-template-columns: minmax(300px, 0.9fr) minmax(0, 1.1fr);
  gap: 90px;
  padding-top: 28px;
  border-top: 1px solid #d8ddda;
}

.about-intro h2,
.about-section-heading h2,
.about-cta h2 {
  margin: 0;
  color: #202523;
  font-size: 31px;
  line-height: 1.42;
  letter-spacing: 0;
}

.about-intro__copy {
  display: grid;
  gap: 16px;
}

.about-intro__copy p {
  margin: 0;
  color: #626a66;
  font-size: 16px;
  line-height: 1.9;
}

.about-section-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 32px;
  margin-bottom: 28px;
}

.about-section-heading > span {
  padding-bottom: 6px;
  color: #8a928e;
  font-size: 13px;
}

.capability-list {
  border-top: 1px solid #cfd5d2;
}

.capability-row {
  display: grid;
  grid-template-columns: 42px 44px 150px minmax(260px, 1fr) auto;
  align-items: center;
  gap: 18px;
  min-height: 104px;
  border-bottom: 1px solid #d8ddda;
}

.capability-row__index {
  color: #9aa19d;
  font-size: 12px;
  font-weight: 700;
}

.capability-row__icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid #ead7d5;
  border-radius: 6px;
  background: #fff;
  color: #c84b45;
}

.capability-row h3 {
  margin: 0;
  font-size: 18px;
}

.capability-row > p {
  margin: 0;
  color: #69716d;
  font-size: 14px;
  line-height: 1.7;
}

.capability-row__tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: 220px;
}

.capability-row__tags span {
  padding: 5px 9px;
  border: 1px solid #dfe3e1;
  border-radius: 999px;
  background: #fff;
  color: #737b77;
  font-size: 11px;
  white-space: nowrap;
}

.foundation-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: 1px solid #cfd5d2;
}

.foundation-item {
  min-height: 210px;
  padding: 30px 32px 28px 0;
  border-bottom: 1px solid #d8ddda;
}

.foundation-item + .foundation-item {
  padding-left: 32px;
  border-left: 1px solid #d8ddda;
}

.foundation-item svg {
  color: #c84b45;
}

.foundation-item h3 {
  margin: 28px 0 10px;
  font-size: 19px;
}

.foundation-item p {
  max-width: 300px;
  margin: 0;
  color: #6c746f;
  font-size: 14px;
  line-height: 1.75;
}

.about-cta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 36px;
  margin-top: 78px;
  padding: 32px 2px;
  border-top: 1px solid #cfd5d2;
  border-bottom: 1px solid #cfd5d2;
  background: transparent;
}

.about-cta > div > span {
  display: block;
  margin-bottom: 8px;
  color: #8f3733;
  font-size: 13px;
  font-weight: 650;
}

.about-cta h2 {
  color: #27312d;
  font-size: 25px;
  font-weight: 650;
}

.about-cta__button {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  flex: 0 0 auto;
  border-radius: 50%;
  border: 1px solid #bd4c46;
  background: #fff;
  color: #a33f3a;
  transition:
    background 0.2s ease,
    transform 0.2s ease;
}

.about-cta__button:hover {
  background: #faeeed;
  transform: translateX(2px);
}

@media (max-width: 960px) {
  .about-hero__content {
    width: 54%;
    padding-left: 38px;
  }

  .about-hero__footnote {
    left: 38px;
  }

  .about-intro__content {
    gap: 48px;
  }

  .capability-row {
    grid-template-columns: 34px 42px 130px minmax(0, 1fr);
  }

  .capability-row__tags {
    display: none;
  }
}

@media (max-width: 680px) {
  .about {
    padding: 82px 0 40px;
  }

  .about-hero {
    min-height: 570px;
  }

  .about-hero::before {
    width: 100%;
    background: rgba(247, 249, 248, 0.76);
  }

  .about-hero__image {
    object-position: 64% center;
  }

  .about-hero__content {
    width: auto;
    padding: 38px 24px 0;
  }

  .about-hero h1 {
    font-size: 39px;
  }

  .about-hero__content p {
    color: #3e4743;
    font-size: 15px;
  }

  .about-hero__footnote {
    right: 24px;
    bottom: 24px;
    left: 24px;
  }

  .about-intro,
  .about-capabilities,
  .about-foundation {
    padding-top: 54px;
  }

  .about-intro__content {
    grid-template-columns: 1fr;
    gap: 22px;
  }

  .about-section-heading {
    align-items: start;
    flex-direction: column;
    gap: 8px;
  }

  .capability-row {
    grid-template-columns: 34px 42px minmax(0, 1fr);
    gap: 12px;
    padding: 18px 0;
  }

  .capability-row h3 {
    font-size: 17px;
  }

  .capability-row > p {
    grid-column: 3;
  }

  .foundation-grid {
    grid-template-columns: 1fr;
  }

  .foundation-item {
    min-height: 0;
    padding: 26px 0;
  }

  .foundation-item + .foundation-item {
    padding-left: 0;
    border-left: 0;
  }

  .foundation-item h3 {
    margin-top: 18px;
  }

  .about-cta {
    margin-top: 54px;
    padding: 28px 24px;
  }
}
</style>
