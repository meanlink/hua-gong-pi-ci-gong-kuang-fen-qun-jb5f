import {blindTrials, datasets, jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {chart} from '../components/common/chart.js';
import {esc, date, notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
import {BlindStatus} from '../constants/enums.js';

const isAdmin = () => session.user.role === 'admin';

export async function blindPage(id) {
 const [trials, allDatasets, allJobs] = await Promise.all([
  blindTrials.list(), datasets.list(), jobs.list(),
 ]);
 workspace.blindTrials = trials;
 workspace.datasets = allDatasets;
 // 列表为脱敏轻量视图，选中试验时拉取完整详情（含/不含明细按角色与状态决定）。
 const listed = id ? trials.find(t => String(t.id) === String(id)) : trials[0];
 const selected = listed ? await blindTrials.get(listed.id) : null;
 const baselineJobs = allJobs.filter(j => j.status === 'completed' && j.approved);
 const m = workspace.meta;
 return heading('06 / BLIND REVIEW', '盲测工况与揭盲管理',
  '负责人单独录入盲测批次；揭盲前分析人员只能看到脱敏元数据。盲测沿用定稿尺度与中心归群，不参与拟合；揭盲后明细才公开。')
  + '<div class="dataset-grid"><section class="panel">'
  // 左栏：盲测试验列表
  + '<div class="section-title"><h2>盲测试验</h2><span>' + trials.length + ' 项</span></div>'
  + '<div class="batch-list">' + (trials.length ? trials.map(t =>
    '<button class="batch-item" data-blind="' + t.id + '"><strong>' + esc(t.name) + '</strong>'
    + '<span>' + t.rows + ' 条 · ' + esc(BlindStatus[t.status] || t.status) + ' · 定稿K=' + esc(t.calibration?.k ?? '—') + '</span>'
    + '<small>SHA256 ' + esc(t.checksum.slice(0, 18)) + '… · ' + date(t.created_at) + '</small></button>'
  ).join('') : '<p class="empty">尚无盲测试验。</p>') + '</div>'
  // 左栏：改参试算（不落库），admin/analyst 可用
  + (session.user.role === 'viewer' ? '' :
   '<div class="section-title"><h2>改参试算（不落库）</h2><span>仅页面预览</span></div>'
   + '<form id="preview-form"><label>已公开数据批次<select name="dataset_id" required>'
   + allDatasets.map(d => '<option value="' + d.id + '">' + esc(d.name) + ' · ' + d.rows + ' 条</option>').join('')
   + '</select></label><label>试算 K 值<input type="number" step="1" name="clusters" value="4" min="2" max="6" required></label>'
   + '<button type="submit" class="primary">临时试算 ↗</button><p class="hint">试算不写入任务、不进队列，也不会改变定稿分群；定稿分群被揭盲锁定时试算会被拒绝。</p></form>'
   + '<div id="preview-result"></div>')
  // 左栏：负责人录入表单
  + (isAdmin() ?
   '<div class="section-title" style="margin-top:30px"><h2>负责人录入盲测工况</h2><span>仅业务负责人</span></div>'
   + '<form id="blind-form"><label>盲测试验名称<input name="name" required minlength="2" placeholder="例如：评审会盲测批次 B"></label>'
   + '<label>定稿分群（归群口径来源）<select name="baseline_job_id" required>'
   + (baselineJobs.length ? baselineJobs.map(j => '<option value="' + j.id + '">' + esc(j.name) + ' · K=' + esc(j.params.clusters) + '</option>').join('')
     : '<option value="">暂无已批准的定稿分群</option>') + '</select></label>'
   + '<label>上传 CSV 或 JSON<input type="file" id="blind-file" accept=".json,.csv"></label>'
   + '<label>盲测记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label>'
   + '<p class="hint">字段：' + m.columns.map(c => esc(c.key) + ' / ' + esc(c.label)).join('，')
   + '。5–5,000 条。盲测独立封存，不会进入任何数据批次与拟合。</p>'
   + '<button type="submit" class="primary" ' + (baselineJobs.length ? '' : 'disabled') + '>校验并封存盲测 ↗</button></form>'
   : '<p class="hint">盲测工况仅业务负责人可录入；你当前可查看脱敏信息与揭盲后的归群明细。</p>')
  + '</section>'
  // 右栏：选中试验详情
  + '<section class="panel">' + renderDetail(selected) + '</section></div>';
}

function renderDetail(t) {
 if (!t) return '<div class="section-title"><h2>试验详情</h2></div><div class="empty">从左侧选择一个盲测试验。</div>';
 const isRevealed = t.status === 'revealed';
 const head = '<div class="section-title"><h2 id="blind-detail-name">' + esc(t.name) + '</h2><span>' + esc(BlindStatus[t.status] || t.status) + '</span></div>'
  + '<div class="result-selector"><span>' + t.rows + ' 条盲测工况</span><span>定稿分群 #' + t.baseline_job_id + ' · K=' + esc(t.calibration?.k ?? '—') + '</span><span>定稿轮廓系数 ' + esc(t.calibration?.baseline_silhouette ?? '—') + '</span>'
  + (t.revealed_at ? '<span>揭盲时间 ' + date(t.revealed_at) + '</span>' : '') + '</div>';

 if (isRevealed && t.result) {
  const r = t.result;
  return head
   + '<section class="result-lead"><p class="eyebrow">UNBLINDED FINDING</p><h2>' + esc(r.summary) + '</h2>'
   + '<div class="metrics">' + (r.metrics || []).map(x => '<div><span>' + esc(x.label) + '</span><strong>' + esc(x.value) + '</strong></div>').join('') + '</div></section>'
   + '<section class="panel"><div class="section-title"><h2>归群汇总（沿用定稿中心）</h2><span>' + (r.table?.rows?.length || 0) + ' 个族群</span></div>'
   + table(r.table?.columns || [], r.table?.rows || []) + '</section>'
   + '<section class="panel"><div class="section-title"><h2>归群明细（已公开）</h2><span>' + (r.details?.rows?.length || 0) + ' 条</span></div>'
   + table(r.details?.columns || [], r.details?.rows || []) + '</section>'
   + (r.warnings || []).map(w => '<p class="warning">' + esc(w) + '</p>').join('');
 }

 // 盲态：非负责人完全看不到明细
 if (!isAdmin()) {
  return head + '<div class="empty">该试验仍处于<strong>盲态封存</strong>。揭盲前你只能看到记录数、内容指纹与定稿口径，批次明细与归群结论暂不公开；明细齐了并由负责人揭盲后在此查看。</div>';
 }
 // 负责人盲态可核对录入明细，但没有归群结论
 return head
  + (t.status === 'unblinding' ? '<p class="warning">揭盲进行中。若进程中断，系统会在恢复时自动回到盲态并释放定稿锁，可重新揭盲。</p>' : '')
  + '<div class="section-title"><h2>录入明细（仅负责人自查）</h2><span>' + (t.records?.length || 0) + ' 条 · 归群结论未生成</span></div>'
  + table(workspace.meta.columns, (t.records || []).slice(0, 100))
  + ((t.records?.length || 0) > 100 ? '<p class="hint">仅预览前 100 条，完整明细已封存。</p>' : '')
  + '<div style="margin-top:24px"><button class="primary" id="unblind-btn" ' + (t.status === 'unblinding' ? 'disabled' : '') + '>揭盲并发布归群明细 ↗</button>'
  + '<p class="hint">揭盲会锁定该定稿分群，与改参试算互斥，同一时刻只接受一方；重试不会重复发布。</p></div>';
}

export function bindBlind(refresh) {
 // 左栏切换试验
 document.querySelectorAll('[data-blind]').forEach(btn => btn.onclick = () => { location.hash = '#/blind/' + btn.dataset.blind; });

 // 文件读取（录入）
 const fileInput = document.querySelector('#blind-file');
 if (fileInput) fileInput.addEventListener('change', async e => {
  try {
   const file = e.target.files[0]; if (!file) return;
   const text = await file.text();
   const records = file.name.endsWith('.csv') ? parseCSV(text) : JSON.parse(text);
   document.querySelector('[name=records]').value = JSON.stringify(records, null, 2);
  } catch (error) { notify(error.message, true); }
 });

 // 负责人录入
 const blindForm = document.querySelector('#blind-form');
 if (blindForm) submit(blindForm, async f => {
  let records;
  try { records = JSON.parse(f.get('records')); }
  catch { throw new Error('记录不是合法 JSON'); }
  const t = await blindTrials.create({
   name: f.get('name'), baseline_job_id: Number(f.get('baseline_job_id')), records,
  });
  notify('盲测工况已封存，分析人员在揭盲前无法查看明细');
  location.hash = '#/blind/' + t.id;
  await refresh();
 });

 // 改参试算
 const previewForm = document.querySelector('#preview-form');
 if (previewForm) submit(previewForm, async f => {
  const box = document.querySelector('#preview-result');
  box.innerHTML = '<p class="hint">试算中…</p>';
  try {
   const data = await blindTrials.preview({
    dataset_id: Number(f.get('dataset_id')), clusters: Number(f.get('clusters')),
   });
   box.innerHTML = '<div class="section-title" style="margin-top:22px"><h2>试算结果 · K=' + esc(data.params.clusters) + '</h2><span>未保存</span></div>'
    + chart(data.result.chart)
    + table(data.result.table?.columns || [], data.result.table?.rows || []);
   notify('试算完成，未写入任何任务');
  } catch (error) {
   box.innerHTML = '<p class="warning">' + esc(error.message) + '</p>';
   notify(error.message, true);
  }
 });

 // 揭盲
 const unblindBtn = document.querySelector('#unblind-btn');
 if (unblindBtn) unblindBtn.onclick = async () => {
  const id = location.hash.split('/')[2];
  unblindBtn.disabled = true;
  try {
   const t = await blindTrials.unblind(Number(id));
   notify('已揭盲，归群明细对全部角色公开');
   location.hash = '#/blind/' + t.id;
   await refresh();
  } catch (error) {
   notify(error.message, true);
   unblindBtn.disabled = false;
  }
 };
}
