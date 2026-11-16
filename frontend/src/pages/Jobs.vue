<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const domains = ref([])
const domainId = ref(1)
const jobs = ref([])
const selectedId = ref(null)
const err = ref('')
const busy = ref(false)

const selected = computed(() => jobs.value.find((j) => j.id === selectedId.value) || null)

async function refresh() {
  jobs.value = await getJson(`/api/jobs?domain_id=${domainId.value}`)
  if (!jobs.value.some((j) => j.id === selectedId.value)) {
    selectedId.value = jobs.value.length ? jobs.value[0].id : null
  }
}

onMounted(async () => {
  try {
    domains.value = await getJson('/api/domains')
    if (domains.value.length) domainId.value = domains.value[0].id
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function run(step) {
  busy.value = true
  err.value = ''
  try {
    const url = step === '明细'
      ? '/api/jobs/paste-to-detail'
      : '/api/jobs/detail-to-summary'
    const job = await postJson(url, { domain_id: domainId.value })
    await refresh()
    selectedId.value = job.id
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

function proofOf(job) {
  return job && job.dim_alignment_proof
}

function samplesOf(job, kind) {
  const proof = proofOf(job)
  return proof && proof.sample_keys ? proof.sample_keys[kind] || [] : []
}
</script>
<template>
  <div>
    <h2>分层任务</h2>
    <p class="lead">
      按主题域推进：先贴源到明细，再明细到汇总。贴源到明细按门店维校验编码，
      未命中启用维或金额为负的行进拒收清单；店名以维表为准回填或覆盖。
      维对齐证明随任务落库，计数由启用维集合、拒收清单、明细层同源派生，不另设计数器。
    </p>
    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId" @change="refresh">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <button :disabled="busy" @click="run('明细')">跑贴源到明细</button>
      <button class="secondary" :disabled="busy" @click="run('汇总')">跑明细到汇总</button>
      <router-link class="btn secondary" to="/stores">查看门店维与拒收清单</router-link>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编号</th><th>步骤</th><th>状态</th><th>说明</th>
            <th>输入</th><th>写入</th><th>拒收</th><th>空名回填</th><th>冲突覆盖</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="j in jobs"
            :key="j.id"
            :class="{ selected: j.id === selectedId }"
            @click="selectedId = j.id"
          >
            <td>{{ j.id }}</td>
            <td>{{ j.step_label || j.step }}</td>
            <td>{{ j.status }}</td>
            <td>{{ j.message }}</td>
            <td>{{ j.in_count }}</td>
            <td>{{ j.out_count }}</td>
            <td :class="j.drop_count ? 'warn' : ''">{{ j.drop_count }}</td>
            <td>{{ j.backfill_count }}</td>
            <td :class="j.conflict_count ? 'warn' : ''">{{ j.conflict_count }}</td>
            <td>{{ j.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!jobs.length" class="muted">还没有任务记录。</p>
    </div>

    <div v-if="selected" class="panel">
      <h3>任务 {{ selected.id }} · 维对齐证明</h3>
      <template v-if="proofOf(selected)">
        <div class="stat-strip proof-strip">
          <div class="item"><div class="label">启用维数</div><div class="value">{{ proofOf(selected).enabled_dim_count }}</div></div>
          <div class="item"><div class="label">命中维</div><div class="value">{{ proofOf(selected).hit_count }}</div></div>
          <div class="item"><div class="label">拒收</div><div class="value">{{ proofOf(selected).reject_count }}</div></div>
          <div class="item"><div class="label">空名回填</div><div class="value">{{ proofOf(selected).backfill_count }}</div></div>
          <div class="item"><div class="label">冲突回填</div><div class="value">{{ proofOf(selected).conflict_count }}</div></div>
        </div>
        <p class="muted">
          证明落库后不可改写：否定项只按后续清洗任务重新取证，历史任务证明保持原样。
        </p>

        <h3>拒收原因（本任务）</h3>
        <table v-if="selected.reject_reasons.length">
          <thead><tr><th>拒收原因</th><th>行数</th></tr></thead>
          <tbody>
            <tr v-for="r in selected.reject_reasons" :key="r.reason">
              <td class="warn">{{ r.reason }}</td>
              <td>{{ r.count }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">本任务没有拒收行。</p>

        <h3>样本键</h3>
        <table v-if="samplesOf(selected, '命中').length">
          <thead><tr><th>类型</th><th>业务日</th><th>门店编码</th><th>门店名称</th><th>名称来源</th></tr></thead>
          <tbody>
            <tr v-for="(s, i) in samplesOf(selected, '命中')" :key="`hit-${i}`">
              <td>{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.门店名称 }}</td><td>{{ s.名称来源 }}</td>
            </tr>
            <tr v-for="(s, i) in samplesOf(selected, '空名回填')" :key="`backfill-${i}`">
              <td>{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.门店名称 }}</td><td>{{ s.名称来源 }}</td>
            </tr>
            <tr v-for="(s, i) in samplesOf(selected, '冲突回填')" :key="`conflict-${i}`">
              <td class="warn">{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.门店名称 }}</td><td>{{ s.名称来源 }}</td>
            </tr>
            <tr v-for="(s, i) in samplesOf(selected, '拒收')" :key="`reject-${i}`">
              <td class="warn">{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.贴源门店名称 || '（空）' }}</td><td class="warn">{{ s.拒收原因 }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">本任务没有样本键。</p>
      </template>
      <p v-else class="muted">该任务不是贴源到明细，暂无维对齐证明。</p>
    </div>
  </div>
</template>

<style scoped>
tr.selected td {
  background: #e7eef8;
  box-shadow: inset 3px 0 0 var(--accent);
}
tr { cursor: pointer; }
.proof-strip {
  grid-template-columns: repeat(5, 1fr);
  margin: 14px 0 10px;
}
.proof-strip .value { font-size: 24px; }
@media (max-width: 860px) {
  .proof-strip { grid-template-columns: 1fr 1fr; }
}
</style>
