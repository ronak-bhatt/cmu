<script setup>
import { ref, onMounted, computed } from 'vue'

const scenarios = ref({})
const picked = ref('')
const body = ref('')
const result = ref(null)
const error = ref('')
const busy = ref(false)
const sent = ref({})

onMounted(async () => {
  scenarios.value = await (await fetch('/api/scenarios')).json()
  pick(Object.keys(scenarios.value)[0])
})
function pick(name) {
  picked.value = name
  body.value = JSON.stringify(scenarios.value[name], null, 2)
}
async function assess() {
  error.value = ''; busy.value = true; sent.value = {}
  try {
    const r = await fetch('/api/investigations', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: body.value })
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText)
    result.value = await r.json()
  } catch (e) { error.value = `Could not assess this change: ${e.message}` }
  busy.value = false
}
async function feedback(f, confirmed) {
  await fetch(`/api/investigations/${result.value.investigation_id}/feedback`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ finding_id: f.id, confirmed }) })
  sent.value = { ...sent.value, [f.id]: confirmed ? 'Confirmed' : 'Rejected' }
}
const trail = computed(() => result.value?.hypotheses ?? [])
</script>

<template>
  <main>
    <header>
      <h1>Change review</h1>
      <p class="note">Recommend-only. Nothing on this page changes infrastructure.</p>
    </header>

    <section class="input">
      <label for="sc">Sample change</label>
      <select id="sc" :value="picked" @change="pick($event.target.value)">
        <option v-for="(_, name) in scenarios" :key="name" :value="name">{{ name }}</option>
      </select>
      <label for="cfg">Change (JSON)</label>
      <textarea id="cfg" v-model="body" rows="14" spellcheck="false"></textarea>
      <button :disabled="busy" @click="assess">{{ busy ? 'Assessing…' : 'Assess change' }}</button>
      <p v-if="error" class="err" role="alert">{{ error }}</p>
    </section>

    <section v-if="result" class="out">
      <div class="score">
        <span class="num">{{ result.score }}</span>
        <div>
          <strong>{{ result.target }}</strong>
          <p>{{ result.summary }}</p>
          <p v-if="result.requires_human" class="flag">Human approval required</p>
        </div>
      </div>

      <ul class="cats">
        <li v-for="(c, name) in result.category_scores" :key="name">
          <span>{{ name }}</span>
          <meter :value="c.remaining" min="0" :max="c.weight"></meter>
          <span>{{ c.remaining }}/{{ c.weight }}</span>
        </li>
      </ul>

      <h2>Findings</h2>
      <p v-if="!result.findings.length">No reliability risks found for this change.</p>
      <article v-for="f in result.findings" :key="f.id" :class="['finding', f.band]">
        <h3>{{ f.title }}</h3>
        <p class="meta">{{ f.band }} risk, priority {{ f.priority }} (severity {{ f.severity }} × likelihood {{ f.likelihood }} × impact {{ f.impact }}); {{ f.confidence }} confidence</p>
        <p>{{ f.recommendation }}</p>
        <p class="meta">Sources: {{ f.citations.join(', ') }}</p>
        <p class="meta">
          {{ f.approval.level.replace('_', ' ') }}<template v-if="f.approval.approvers.length"> by {{ f.approval.approvers.join(', ') }}</template>
          <template v-if="f.approval.reasons.length"> because {{ f.approval.reasons.join('; ') }}</template>
        </p>
        <div class="fb">
          <template v-if="sent[f.id]">{{ sent[f.id] }}. Recorded for review.</template>
          <template v-else>
            <button class="ghost" @click="feedback(f, true)">Confirm finding</button>
            <button class="ghost" @click="feedback(f, false)">Reject finding</button>
          </template>
        </div>
      </article>

      <h2>Reasoning trail</h2>
      <ol class="trail">
        <li v-for="h in trail" :key="h.id" :class="[h.status, 'd' + h.depth]">
          <span class="s">{{ h.score.toFixed(2) }}</span> {{ h.statement }}
          <span v-if="h.evidence && h.evidence.length" class="meta">[{{ h.evidence.join(', ') }}]</span>
          <em v-if="h.status === 'pruned'">pruned</em>
        </li>
      </ol>

      <template v-if="result.conflicts.length">
        <h2>Conflicts resolved</h2>
        <ul><li v-for="(c, i) in result.conflicts" :key="i">
          <strong>{{ c.kind }}:</strong> {{ c.detail }}. Winner: {{ c.winner }}<template v-if="c.loser"> over {{ c.loser }}</template> ({{ c.rule }}){{ c.resolved ? '' : '. Unresolved, needs a human' }}
        </li></ul>
      </template>
      <template v-if="result.excluded_sources.length">
        <h2>Sources not used</h2>
        <ul><li v-for="e in result.excluded_sources" :key="e.ref">{{ e.ref }}: {{ e.reason }}</li></ul>
      </template>
      <p v-for="s in result.safety_events" :key="s" class="err">Safety event: {{ s }}</p>
    </section>
  </main>
</template>

<style>
:root {
  --paper: #f3f5f4; --card: #ffffff; --ink: #16222b; --muted: #55646f; --line: #cfd8d6; --accent: #0e6a70;
  --critical: #a3271c; --high: #b4530b; --medium: #8a6d00; --low: #2e6b3b;
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark) {
  :root { --paper: #11181d; --card: #18222a; --ink: #e8eeee; --muted: #9fb0b8; --line: #2c3a44; --accent: #5cc3c9;
    --critical: #ff8a7d; --high: #f5a15f; --medium: #e0c04d; --low: #7fcf8d; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font: 16px/1.55 'IBM Plex Sans', system-ui, sans-serif; }
main { max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; display: grid; gap: 32px; grid-template-columns: minmax(0, 380px) minmax(0, 1fr); }
header { grid-column: 1 / -1; }
h1, h2, h3, .num { font-family: 'Source Serif 4', Georgia, serif; }
h1 { margin: 0; font-size: 2rem; }
h2 { font-size: 1.25rem; margin: 32px 0 8px; }
h3 { font-size: 1.05rem; margin: 0 0 4px; }
.note, .meta { color: var(--muted); margin: 4px 0; font-size: .9rem; }
label { display: block; margin: 16px 0 4px; font-weight: 500; }
select, textarea { width: 100%; padding: 8px; border: 1px solid var(--line); border-radius: 4px; background: var(--card); color: var(--ink); font: inherit; }
textarea { font-family: ui-monospace, Menlo, monospace; font-size: .8rem; }
button { margin-top: 12px; padding: 9px 16px; border: 0; border-radius: 4px; background: var(--accent); color: var(--paper); font-family: inherit; font-weight: 600; font-size: .95rem; cursor: pointer; }
button.ghost { background: none; color: var(--accent); border: 1px solid var(--accent); margin-right: 8px; padding: 4px 10px; }
button:disabled { opacity: .6; cursor: wait; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.err { color: var(--critical); }
.score { display: flex; gap: 20px; align-items: center; }
.num { font-size: 5rem; font-weight: 700; line-height: 1; }
.score p { margin: 4px 0; }
.flag { color: var(--high); font-weight: 600; }
.cats { list-style: none; padding: 0; margin: 20px 0 0; display: grid; gap: 6px; }
.cats li { display: grid; grid-template-columns: 110px 1fr 56px; gap: 10px; align-items: center; font-size: .9rem; }
meter { width: 100%; height: 10px; }
.finding { background: var(--card); border: 1px solid var(--line); border-left: 6px solid var(--line); border-radius: 4px; padding: 12px 16px; margin: 10px 0; }
.finding.critical { border-left-color: var(--critical); } .finding.high { border-left-color: var(--high); }
.finding.medium { border-left-color: var(--medium); } .finding.low { border-left-color: var(--low); }
.fb { margin-top: 8px; font-size: .9rem; color: var(--muted); }
.trail { list-style: none; padding: 0; margin: 0; font-size: .9rem; }
.trail li { padding: 2px 0; }
.trail .d1 { margin-left: 18px; } .trail .d2 { margin-left: 36px; } .trail .d3 { margin-left: 54px; }
.trail .pruned { color: var(--muted); text-decoration: line-through; }
.trail em { text-decoration: none; display: inline-block; margin-left: 8px; font-style: normal; }
.trail .s { display: inline-block; min-width: 2.5em; font-variant-numeric: tabular-nums; color: var(--accent); }
@media (max-width: 800px) { main { grid-template-columns: 1fr; } .num { font-size: 3.5rem; } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
