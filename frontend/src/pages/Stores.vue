<script setup>
import { onMounted, reactive, ref } from 'vue'
import { getJson, postJson, putJson, deleteJson } from '../api'

const stores = ref([])
const rejections = ref([])
const domains = ref([])
const domainId = ref(null)
const err = ref('')
const busy = ref(false)

const form = reactive({ store_code: '', store_name: '', enabled: true })
const editing = ref(null)

async function refreshStores() {
  stores.value = await getJson('/api/stores')
}

async function refreshRejections() {
  const qs = domainId.value ? `?domain_id=${domainId.value}` : ''
  rejections.value = await getJson(`/api/rejections${qs}`)
}

async function refreshAll() {
  await Promise.all([refreshStores(), refreshRejections()])
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
      <h3>维缺失拒收清单</h3>
      <div class="toolbar">
        <label>
          主题域
          <select v-model.number="domainId" @change="refreshRejections">
            <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
        <button class="secondary" @click="refreshRejections">刷新</button>
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
</style>
