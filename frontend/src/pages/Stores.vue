<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { getJson, postJson, putJson, deleteJson } from '../api'

const stores = ref([])
const rejections = ref([])
const domains = ref([])
const domainId = ref(null)
const jobs = ref([])
const err = ref('')
const busy = ref(false)

const form = reactive({ store_code: '', store_name: '', enabled: true })
const editing = ref(null)

const latestProofJob = computed(
  () => jobs.value.find((j) => j.step === 'paste_to_detail' && j.dim_alignment_proof) || null,
)
const proof = computed(() => (latestProofJob.value ? latestProofJob.value.dim_alignment_proof : null))
const rejectReasons = computed(() => (latestProofJob.value ? latestProofJob.value.reject_reasons : []))

async function refreshStores() {
  stores.value = await getJson('/api/stores')
}

async function refreshRejections() {
  const qs = domainId.value ? `?domain_id=${domainId.value}` : ''
  rejections.value = await getJson(`/api/rejections${qs}`)
}

async function refreshJobs() {
  if (!domainId.value) {
    jobs.value = []
    return
  }
  jobs.value = await getJson(`/api/jobs?domain_id=${domainId.value}`)
}

async function refreshAll() {
  await Promise.all([refreshStores(), refreshRejections(), refreshJobs()])
}

onMounted(async () => {
  try {
    domains.value = await getJson('/api/domains')
    if (domains.value.length) domainId.value = domains.value[0].id
    await refreshAll()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function addStore() {
  busy.value = true
  err.value = ''
  try {
    await postJson('/api/stores', { ...form })
    form.store_code = ''
    form.store_name = ''
    form.enabled = true
    await refreshStores()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

function startEdit(s) {
  editing.value = { id: s.id, store_code: s.store_code, store_name: s.store_name, enabled: !!s.enabled }
}

function cancelEdit() {
  editing.value = null
}

async function saveEdit() {
  busy.value = true
  err.value = ''
  try {
    await putJson(`/api/stores/${editing.value.id}`, { ...editing.value })
    editing.value = null
    await refreshStores()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function toggleEnabled(s) {
  err.value = ''
  try {
    await putJson(`/api/stores/${s.id}`, { enabled: !s.enabled })
    await refreshStores()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function removeStore(s) {
  if (!window.confirm(`确认删除门店维「${s.store_code} ${s.store_name}」？\n删除只影响之后的清洗，历史明细行不会被改动。`)) return
  err.value = ''
  try {
    await deleteJson(`/api/stores/${s.id}`)
    await refreshStores()
  } catch (e) {
    err.value = String(e.message || e)
  }
}
</script>
<template>
  <div>
    <h2>门店维</h2>
    <p class="lead">
      门店编码必须命中启用维，贴源行才能进入明细层；未命中或已停用的编码进入维缺失拒收清单。
      维表变更只影响之后的清洗，不会级联改写历史明细。
    </p>
    <p v-if="err" class="err">{{ err }}</p>

    <div class="panel">
      <h3>新增门店维</h3>
      <div class="toolbar">
        <label>门店编码 <input v-model="form.store_code" placeholder="如 S03" /></label>
        <label>门店名称 <input v-model="form.store_name" placeholder="如 城南店" /></label>
        <label class="check">
          <input type="checkbox" v-model="form.enabled" /> 启用
        </label>
        <button :disabled="busy" @click="addStore">登记门店维</button>
      </div>

      <table>
        <thead>
          <tr><th>编号</th><th>门店编码</th><th>门店名称</th><th>启用态</th><th>更新时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <template v-for="s in stores" :key="s.id">
            <tr v-if="!editing || editing.id !== s.id">
              <td>{{ s.id }}</td>
              <td>{{ s.store_code }}</td>
              <td>{{ s.store_name }}</td>
              <td>
                <span :class="s.enabled ? 'ok' : 'warn'">{{ s.enabled ? '启用' : '停用' }}</span>
              </td>
              <td>{{ s.updated_at }}</td>
              <td class="ops">
                <button class="secondary" @click="startEdit(s)">编辑</button>
                <button class="secondary" @click="toggleEnabled(s)">{{ s.enabled ? '停用' : '启用' }}</button>
                <button class="secondary" @click="removeStore(s)">删除</button>
              </td>
            </tr>
            <tr v-else>
              <td>{{ s.id }}</td>
              <td><input v-model="editing.store_code" /></td>
              <td><input v-model="editing.store_name" /></td>
              <td>
                <label class="check">
                  <input type="checkbox" v-model="editing.enabled" />
                  {{ editing.enabled ? '启用' : '停用' }}
                </label>
              </td>
              <td>{{ s.updated_at }}</td>
              <td class="ops">
                <button :disabled="busy" @click="saveEdit">保存</button>
                <button class="secondary" @click="cancelEdit">取消</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-if="!stores.length" class="muted">还没有门店维，请先登记。</p>
    </div>

    <div class="panel">
      <h3>维对齐证明</h3>
      <template v-if="proof">
        <p class="muted">
          来源任务 {{ latestProofJob.id }}（{{ latestProofJob.created_at }}）。
          以下字段由启用维集合、拒收清单、明细层同源派生后随任务固化，不另起独立计数器。
        </p>
        <div class="proof-grid">
          <div class="proof-item"><span class="label">启用维数</span><span class="value">{{ proof.enabled_dim_count }}</span></div>
          <div class="proof-item"><span class="label">命中维</span><span class="value">{{ proof.hit_count }}</span></div>
          <div class="proof-item"><span class="label">拒收</span><span class="value warn">{{ proof.reject_count }}</span></div>
          <div class="proof-item"><span class="label">空名回填</span><span class="value">{{ proof.backfill_count }}</span></div>
          <div class="proof-item"><span class="label">冲突回填</span><span class="value warn">{{ proof.conflict_count }}</span></div>
        </div>

        <h3>拒收原因（来源任务）</h3>
        <table v-if="rejectReasons.length">
          <thead><tr><th>拒收原因</th><th>行数</th></tr></thead>
          <tbody>
            <tr v-for="r in rejectReasons" :key="r.reason">
              <td class="warn">{{ r.reason }}</td>
              <td>{{ r.count }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">来源任务没有拒收行。</p>

        <h3>样本键</h3>
        <table>
          <thead><tr><th>类型</th><th>业务日</th><th>门店编码</th><th>门店名称 / 贴源名称</th><th>说明</th></tr></thead>
          <tbody>
            <tr v-for="(s, i) in proof.sample_keys.命中" :key="`hit-${i}`">
              <td>{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.门店名称 }}</td><td>{{ s.名称来源 }}</td>
            </tr>
            <tr v-for="(s, i) in proof.sample_keys.空名回填" :key="`back-${i}`">
              <td>{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.门店名称 }}</td><td>{{ s.名称来源 }}</td>
            </tr>
            <tr v-for="(s, i) in proof.sample_keys.冲突回填" :key="`conf-${i}`">
              <td class="warn">{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.门店名称 }}</td><td>{{ s.名称来源 }}</td>
            </tr>
            <tr v-for="(s, i) in proof.sample_keys.拒收" :key="`rej-${i}`">
              <td class="warn">{{ s.类型 }}</td><td>{{ s.业务日 }}</td><td>{{ s.门店编码 }}</td>
              <td>{{ s.贴源门店名称 || '（空）' }}</td><td class="warn">{{ s.拒收原因 }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <p v-else class="muted">该主题域还没有贴源到明细任务，暂无可展示的维对齐证明。</p>
    </div>

    <div class="panel">
      <h3>维缺失拒收清单</h3>
      <div class="toolbar">
        <label>
          主题域
          <select v-model.number="domainId" @change="refreshAll">
            <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
        <button class="secondary" @click="refreshAll">刷新</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>编号</th><th>任务</th><th>业务日</th><th>门店编码</th>
            <th>贴源门店名称</th><th>品类</th><th>金额</th><th>拒收原因</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rejections" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.job_id }}</td>
            <td>{{ r.biz_day }}</td>
            <td>{{ r.store_code || '（空）' }}</td>
            <td>{{ r.store_name_paste || '（空）' }}</td>
            <td>{{ r.category }}</td>
            <td>{{ r.amount }}</td>
            <td class="warn">{{ r.reason }}</td>
            <td>{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rejections.length" class="muted">暂无拒收记录。</p>
    </div>
  </div>
</template>

<style scoped>
input[type='text'],
input:not([type]) {
  font: inherit;
  padding: 7px 10px;
  border-radius: 2px;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  min-width: 120px;
}
label.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ops {
  white-space: nowrap;
}
.ops button {
  margin-right: 6px;
  padding: 5px 10px;
}
.proof-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  margin: 12px 0 18px;
  background: rgba(247, 249, 252, 0.7);
}
.proof-item {
  padding: 12px 14px;
  border-right: 1px solid var(--line);
  display: grid;
  gap: 4px;
}
.proof-item:last-child { border-right: none; }
.proof-item .label {
  font-size: 12px;
  color: var(--muted);
  letter-spacing: 0.06em;
}
.proof-item .value {
  font-size: 24px;
  font-family: "Noto Serif SC", serif;
  font-weight: 700;
}
.proof-item .value.warn { color: var(--warn); }
@media (max-width: 860px) {
  .proof-grid { grid-template-columns: 1fr 1fr; }
}
</style>
