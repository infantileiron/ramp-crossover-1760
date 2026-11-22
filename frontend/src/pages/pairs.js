import { api } from '../api/client.js';
import { sign } from '../components/common/signs.js';
import { empty, heading } from '../components/common/shell.js';
import { entryKinds, entryStates, sequences } from '../constants/domain.js';
import { bindForm, notice } from '../hooks/forms.js';
import { isComplete } from '../types/field.js';
import { e, sec, time } from '../utils/format.js';

const stateClass = { passed: 'ok', missing: 'warn', duplicate: 'neutral', sequence_conflict: 'warn', conflict: 'warn' };

function editor(batches) {
  const options = batches.map(batch => `<option value="${batch.id}">${e(batch.label)}</option>`).join('');
  return `<aside class="panel edit-panel"><div class="panel-title"><h2 id="pair-heading">录入试走</h2><p>以匿名编号保存，每次保存计入所选采集批次。缺测周期可留空。</p></div>
    ${batches.length ? `<form id="pair-form">
      <label>采集批次<select name="batch_id">${options}</select></label>
      <label>参与者编号<input name="code" pattern="[A-Z0-9][A-Z0-9\\-]{1,19}" placeholder="如 AB08" required maxlength="20"></label>
      <label>分配顺序<select name="sequence"><option value="AB">AB · 先 A 后 B</option><option value="BA">BA · 先 B 后 A</option></select></label>
      <div class="form-inline"><label>第 1 轮 <span id="first-sign" class="field-sign">A</span><input name="period1" type="number" min="0.01" max="900" step="0.01" placeholder="秒"></label>
      <label>第 2 轮 <span id="second-sign" class="field-sign">B</span><input name="period2" type="number" min="0.01" max="900" step="0.01" placeholder="秒"></label></div>
      <p class="form-error" role="alert" hidden></p>
      <div class="form-actions"><button type="submit" class="primary">保存记录</button><button type="button" id="pair-reset" class="quiet">重置</button></div>
    </form>` : '<p class="empty-inline">尚无采集批次，请先在下方新建批次再登记。</p>'}
    <div class="batch-box"><h3>新建采集批次</h3>
      <form id="batch-form"><label>批次名<input name="label" required maxlength="40" placeholder="如 现场补交"></label>
      <label>来源<input name="source" required maxlength="80" placeholder="如 计时员手记表二"></label>
      <p class="form-error" role="alert" hidden></p><button class="secondary" type="submit">保存批次</button></form></div></aside>`;
}

function batchList(batches) {
  if (!batches.length) return '';
  return `<ul class="version-list batch-list">${batches.map(batch => `<li><strong>${e(batch.label)}</strong>
    <small>${e(batch.source)} · ${batch.entries} 条上传 · ${batch.complete ? '<span class="status ok">完整</span>' : '<span class="status warn">待对账</span>'}</small></li>`).join('')}</ul>`;
}

function entryTable(entries) {
  if (!entries.length) return empty('暂无对账记录', '保存第一条试走记录后，这里会列出每次上传的来源与前后值。');
  const cell = (before, after) => before == null && after == null ? '—' : `${sec(before)} → ${sec(after)}`;
  return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>批次 · 来源</th><th>参与者</th><th>类型</th><th>第 1 轮 前→后</th><th>第 2 轮 前→后</th><th>对账标记</th></tr></thead>
    <tbody>${entries.map(row => `<tr><td>${time(row.created_at)}</td><td>${e(row.batch_label)} · ${e(row.batch_source)}</td>
      <th scope="row" class="code">${e(row.code)}</th><td>${entryKinds[row.kind]}</td>
      <td class="number">${cell(row.prev_period1, row.period1)}</td><td class="number">${cell(row.prev_period2, row.period2)}</td>
      <td><span class="status ${stateClass[row.status]}">${entryStates[row.status]}</span></td></tr>`).join('')}</tbody></table></div>`;
}

export function pairsPage(root, { route, pairs, batches, entries, user, refresh }) {
  const edit = user.role === 'analyst';
  if (!route) { root.innerHTML = empty('暂无路线', '导入现场路线后可查看配对记录。'); return; }
  root.innerHTML = `${heading('配对记录 · 采集批次对账', `${e(route.code)} · ${e(route.name)}　/　用时单位为秒`, edit ? '<a class="button secondary" href="#runs">进入对照运行 →</a>' : '')}
    <div class="split ${edit ? '' : 'single'}"><div>
      <section class="panel records">
        <div class="panel-title title-row"><div><h2>试走台账</h2><p>${pairs.length} 人登记 · ${pairs.filter(isComplete).length} 人完整配对</p></div>
          <label class="filter-label">顺序<select id="sequence-filter"><option value="">全部</option><option>AB</option><option>BA</option></select></label></div>
        <div class="table-wrap" id="pair-list"></div></section>
      <section class="panel records"><div class="panel-title"><h2>对账记录</h2><p>补录、修改与重复上传的来源、前后值与标记；被覆盖且无法恢复的记录标记为冲突。</p></div>
        <div id="entry-list">${entryTable(entries)}</div></section>
    </div>${edit ? editor(batches) : `<aside class="panel"><div class="panel-title"><h2>采集批次</h2></div>${batchList(batches)}</aside>`}</div>`;
  const list = root.querySelector('#pair-list');
  const filter = root.querySelector('#sequence-filter');
  function fill() {
    const rows = pairs.filter(row => !filter.value || filter.value === row.sequence);
    list.innerHTML = rows.length ? `<table><thead><tr><th>参与者</th><th>顺序</th><th>第 1 轮</th><th>第 2 轮</th><th>配对状态</th><th>采集批次</th>${edit ? '<th><span class="sr-only">操作</span></th>' : ''}</tr></thead>
      <tbody>${rows.map(row => `<tr><th scope="row" class="code">${e(row.code)}</th><td>${sequences[row.sequence].map(code => sign(code)).join(' ')}</td>
        <td class="number">${sec(row.period1)}</td><td class="number">${sec(row.period2)}</td>
        <td><span class="status ${isComplete(row) ? 'ok' : 'warn'}">${isComplete(row) ? '齐全' : '缺测'}</span></td>
        <td>${e(row.batch_label || '—')}</td>
        ${edit ? `<td><button type="button" class="text-button" data-pair="${e(row.code)}">补录／编辑</button></td>` : ''}</tr>`).join('')}</tbody></table>` : empty('此顺序暂无记录', '可切回全部顺序，或登记首位参与者。');
  }
  filter.addEventListener('change', fill);
  fill();
  if (edit) {
    const batchBox = root.querySelector('.batch-box');
    if (batchBox) batchBox.insertAdjacentHTML('beforebegin', batchList(batches));
    bindForm('batch-form', async values => {
      await api.createBatch(route.code, values);
      notice(`已建立采集批次「${values.label}」`);
      await refresh();
    });
  }
  if (!edit) return;
  const form = root.querySelector('#pair-form');
  if (!form) return;
  const fields = form.elements;
  function showSigns() {
    const [first, second] = sequences[fields.sequence.value];
    root.querySelector('#first-sign').textContent = first;
    root.querySelector('#second-sign').textContent = second;
  }
  fields.sequence.addEventListener('change', showSigns);
  root.querySelector('#pair-reset').onclick = () => {
    form.reset(); fields.code.readOnly = false; fields.sequence.disabled = false;
    root.querySelector('#pair-heading').textContent = '录入试走';
    form.querySelector('.form-error').hidden = true;
    showSigns();
  };
  list.onclick = event => {
    const code = event.target.closest('[data-pair]')?.dataset.pair;
    if (!code) return;
    const row = pairs.find(item => item.code === code);
    for (const name of ['code', 'sequence', 'period1', 'period2']) fields[name].value = row[name] ?? '';
    if (row.batch_id) fields.batch_id.value = row.batch_id;
    fields.code.readOnly = true;
    fields.sequence.disabled = true;
    root.querySelector('#pair-heading').textContent = `编辑 ${code}`;
    form.querySelector('.form-error').hidden = true;
    showSigns();
    fields.period1.focus();
  };
  bindForm('pair-form', async (values, node) => {
    try {
      const saved = await api.savePair(route.code, values.code, {
        batch_id: Number(values.batch_id), sequence: node.elements.sequence.value,
        period1: values.period1 || null, period2: values.period2 || null,
      });
      const status = saved.entry?.status;
      notice(status === 'duplicate' ? `${values.code} 为重复上传，未重复计数` : `已保存 ${values.code} 的现场记录，对账标记：${entryStates[status] || '通过'}`);
    } catch (err) {
      notice(err.message);
    }
    await refresh();
  });
}
