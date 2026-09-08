/* ================================================================
   pywebview API 桥
   ================================================================ */
let api = null;
const QUADRANT_NAMES = ['紧急且重要','紧急不重要','不紧急重要','不紧急不重要'];
const QUADRANT_COLORS = ['#e5533c','#e8912d','#3f7fd9','#4caf7d'];
const WEEKDAYS = ['周一','周二','周三','周四','周五','周六','周日'];
const HOUR_SLOTS = [['深夜','0-4'],['清晨','4-8'],['上午','8-12'],['下午','12-16'],['傍晚','16-20'],['夜晚','20-24']];
/* 主题清单：启动时由 Python 从 themes/ 目录注入（可插拔）；浏览器直开为空 */
const THEME_LIST = window.__PROMATHEMES__ || [];
const DEFAULT_THEME = (THEME_LIST.find(t => t.default === '1') || {}).id || 'paper';

window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  applyDate();
  setInterval(applyDate, 30000); // 时钟每分钟刷新（30s 间隔保证整分后尽快更新）
  startUpdateMonitor(); // 后台更新监控：下载完成后弹窗提示
  const st = await api.get_settings();
  isLocked = st.locked === '1';
  updateLockUI();
  applyTheme(st.theme || DEFAULT_THEME);
  await loadAllTags();
  await refreshAll();
  // 主题与内容就绪后再淡出加载页，避免主题切换闪烁
  hideSplash();
});

// 加载页文案三句轮播（每句 1s，至少轮播 3s）
const SPLASH_LINES = ['无极生太极','太极生两仪','两仪生四象'];
const splashStart = Date.now();
let splashTimer = null;
function splashLineHtml(line) {
  // 「四象」品牌字用四色渐变高亮；第三句「两仪生四象」整句微调放大 1.1 倍
  const brand = line.replace('四象', '<span class="splash-brand">四象</span>');
  return line === '两仪生四象' ? `<span class="splash-line-lg">${brand}</span>` : brand;
}
function startSplashRotation() {
  const el = document.getElementById('splash-text');
  if (!el) return;
  let idx = 0;
  splashTimer = setInterval(() => {
    idx = (idx + 1) % SPLASH_LINES.length;
    el.style.opacity = '0';
    setTimeout(() => {
      el.innerHTML = splashLineHtml(SPLASH_LINES[idx]);
      el.style.opacity = '1';
    }, 150);
    // 三句各 1s 播完一遍即停止，之后停留在最后一句（共 3s）
    if (idx >= SPLASH_LINES.length - 1) {
      clearInterval(splashTimer);
      splashTimer = null;
    }
  }, 1000);
}
startSplashRotation();

function hideSplash() {
  const splash = document.getElementById('splash');
  if (!splash || splash.classList.contains('hide')) return;
  // 加载文案至少轮播 3s 再淡出：淡出那一刻才停止轮播，避免提前打断（超过 3s 则停留在最后一句）
  const delay = Math.max(0, 3000 - (Date.now() - splashStart));
  setTimeout(() => {
    if (splashTimer) { clearInterval(splashTimer); splashTimer = null; }
    splash.classList.add('hide');
    setTimeout(() => { if (splash.parentNode) splash.remove(); }, 400);
  }, delay);
}
// 非 pywebview 环境（如浏览器直接打开）兜底隐藏加载页
setTimeout(() => { if (!api) hideSplash(); }, 3000);

function applyDate() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  // 顶部小字：日期 + 星期 + 当前时间（24 小时制）；版本号只在设置中显示
  document.getElementById('today-date').textContent =
    `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${WEEKDAYS[(d.getDay()+6)%7]} · ${hh}:${mm}`;
}

/* ================================================================
   主题切换
   ================================================================ */
function applyTheme(theme) {
  document.body.className = theme;
}

function onThemeSelect(themeId) {
  // 下拉选择即时预览（保存后持久化，重启由 Python 注入对应主题 CSS）
  applyTheme(themeId);
}

async function importThemeFile(input) {
  const f = input.files && input.files[0];
  if (!f) return;
  input.value = '';
  try {
    const text = await f.text();
    const r = await api.import_theme(f.name, text);
    if (!r.ok) { alert(r.error || '导入失败'); return; }
    // 新主题 CSS 立即注入页面（无需重启即可预览）
    const style = document.createElement('style');
    style.id = 'theme-imported-' + r.id;
    style.textContent = text;
    document.head.appendChild(style);
    // 刷新主题清单 + 下拉选项 + 应用新主题
    const list = await api.get_theme_list();
    window.__PROMATHEMES__ = list;
    const sel = document.getElementById('set-theme-select');
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = list.map(t =>
        `<option value="${t.id}"${t.id===r.id?' selected':''}>${esc(t.name)}${t.default==='1'?'（默认）':''}${t.builtin==='1'?'':' · 自定义'}</option>`
      ).join('') + (list.length === 0 ? '<option value="paper">晨雾纸墨（默认）</option>' : '');
      applyTheme(r.id);
      onThemeSelect(r.id);
      alert('主题已导入：' + (list.find(x=>x.id===r.id)||{}).name + '（重启后仍会保留）');
    }
  } catch (e) {
    alert('导入失败：' + e.message);
  }
}

/* ================================================================
   渲染
   ================================================================ */
async function refreshAll() {
  if (!api) return;
  const tasks = await api.get_active_tasks();
  // 标签筛选（多选：任务需包含任一选中标签）
  let filteredTasks = tasks;
  if (selectedTags.length > 0) {
    filteredTasks = tasks.filter(t => {
      const tags = parseTags(t.tag);
      return tags.some(tg => selectedTags.includes(tg));
    });
  }
  const byQ = {0:[],1:[],2:[],3:[]};
  filteredTasks.forEach(t => { if (byQ[t.quadrant]) byQ[t.quadrant].push(t); });
  for (let q = 0; q < 4; q++) renderQuadrant(q, byQ[q]);
}

function renderQuadrant(q, tasks) {
  const container = document.getElementById(`tasks-${q}`);
  document.getElementById(`count-${q}`).textContent = tasks.length;
  container.innerHTML = tasks.map(t => {
    const tags = parseTags(t.tag);
    // 标签筛选生效时，任务行只展示被勾选的标签
    let shownTags = tags;
    if (selectedTags.length > 0) shownTags = tags.filter(tg => selectedTags.includes(tg));
    const tagHTML = shownTags.slice(0,2).map(tg => tagSpan(tg)).join('')
      + (shownTags.length > 2 ? `<span class="tag" style="opacity:.7">+${shownTags.length-2}</span>` : '');
    return `<div class="task" draggable="true" data-id="${t.id}" data-quadrant="${q}"
      ondragstart="onDragStart(event)" ondragend="onDragEnd(event)" onclick="openDetail(${t.id})">
      <span class="cb" onclick="event.stopPropagation();completeTask(${t.id},this)"><svg viewBox="0 0 12 10" fill="none"><path d="M1 5.5 4.2 8.5 11 1.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg></span>
      <span class="t-title">${esc(t.title)}</span>
      ${tagHTML ? `<div class="tags">${tagHTML}</div>` : ''}
    </div>`;
  }).join('');
}

function parseTags(raw) {
  if (!raw || !raw.trim()) return [];
  try { const a = JSON.parse(raw); return Array.isArray(a) ? a.filter(x => String(x).trim()).map(String) : [raw]; }
  catch { return [raw]; }
}

/* 多标签配色：按下标循环；颜色跟标签库（allTags）走，不跟象限/任务内序号走 */
const TAG_PALETTE = [
  ['#5b4bb5', '#e8e3ff'], ['#8a5a10', '#fff0d4'], ['#2e7d52', '#dcf5e8'],
  ['#2f6fc4', '#dcebff'], ['#b04a3c', '#fde3de'], ['#a83e80', '#fde3f2'],
];
function tagPaletteIndex(tg) {
  const i = allTags.indexOf(String(tg));
  if (i >= 0) return i;
  let h = 0;
  const s = String(tg);
  for (let k = 0; k < s.length; k++) h = (h * 31 + s.charCodeAt(k)) >>> 0;
  return h;
}
function tagPalette(tg) {
  return TAG_PALETTE[tagPaletteIndex(tg) % TAG_PALETTE.length];
}
function tagSpan(tg) {
  const [fg, bg] = tagPalette(tg);
  return `<span class="tag" style="background:${bg} !important;color:${fg} !important">${esc(tg)}</span>`;
}
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
// 把用户文本安全地放进内联事件处理器的 JavaScript 参数中。
// 不能只做 HTML 转义：浏览器会在执行 onclick 前还原实体，单引号会逃出字符串。
function jsArg(s) {
  return esc(JSON.stringify(String(s ?? ''))
    .replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029'));
}

/* ================================================================
   标签筛选（上拉面板 · 多选）
   ================================================================ */
let selectedTags = []; // 当前选中的标签集合，空数组 = 显示所有
let allTags = []; // 所有标签列表

async function loadAllTags() {
  if (!api) return;
  try {
    allTags = await api.get_all_tags();
    renderTagPanel();
    updateTagFilterBtn();
    renderTagChips();
  } catch(e) {
    console.error('加载标签失败:', e);
    // 失败也渲染空态，避免胶囊区静默空白
    renderTagChips();
  }
}

function renderTagPanel() {
  const container = document.getElementById('tag-panel-list');
  if (!container) return;
  if (allTags.length === 0) {
    container.innerHTML = '<div class="tag-panel-empty">暂无标签</div>';
    return;
  }
  container.innerHTML = allTags.map(tag => {
    const sel = selectedTags.includes(tag);
    return `<span class="tag-panel-item ${sel ? 'selected' : ''}" onclick="toggleTag(${jsArg(tag)})">
      <span class="ck">${sel
        ? '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="currentColor" stroke="currentColor" stroke-width="1.5"/><path d="M5 8.5l2 2 4-4.5" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        : '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>'}
      </span>${esc(tag)}
    </span>`;
  }).join('');
}

function toggleTag(tag) {
  const i = selectedTags.indexOf(tag);
  if (i >= 0) selectedTags.splice(i, 1);
  else selectedTags.push(tag);
  renderTagPanel();
  updateTagFilterBtn();
  refreshAll();
}

function selectAllTags() {
  selectedTags = [...allTags];
  renderTagPanel();
  updateTagFilterBtn();
  refreshAll();
}

function clearTags() {
  selectedTags = [];
  renderTagPanel();
  updateTagFilterBtn();
  refreshAll();
}

function updateTagFilterBtn() {
  const btn = document.getElementById('tag-filter-btn');
  const count = document.getElementById('tag-filter-btn-count');
  if (!btn) return;
  if (selectedTags.length > 0 && selectedTags.length < allTags.length) {
    btn.classList.add('active');
    if (count) { count.style.display = 'inline-flex'; count.textContent = selectedTags.length; }
  } else {
    btn.classList.remove('active');
    if (count) count.style.display = 'none';
  }
}

function toggleTagPanel() {
  const panel = document.getElementById('tag-panel');
  const btn = document.getElementById('tag-filter-btn');
  if (!panel || !btn) return;
  if (panel.classList.contains('open')) {
    panel.classList.remove('open');
    return;
  }
  // 动态定位：面板左缘对齐按钮左缘，向上弹出，保证不出屏
  const rect = btn.getBoundingClientRect();
  const panelW = 280;
  let left = rect.left;
  if (left + panelW > window.innerWidth - 12) left = window.innerWidth - panelW - 12;
  if (left < 12) left = 12;
  panel.style.left = left + 'px';
  panel.style.right = 'auto';
  panel.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
  panel.classList.add('open');
  loadAllTags();
}

// 点击外部关闭面板
// 用 mousedown 判断（在 click 之前触发）：toggleTag 的 renderTagPanel 会替换面板内 DOM，
// 导致 click 冒泡时 e.target 已脱离面板，误判为外部点击而关闭弹窗。
// mousedown 时 DOM 尚未变化，panel.contains 判断准确；另用坐标判断双保险。
document.addEventListener('mousedown', e => {
  const panel = document.getElementById('tag-panel');
  const btn = document.getElementById('tag-filter-btn');
  if (panel && panel.classList.contains('open')) {
    const rect = panel.getBoundingClientRect();
    const inPanel = e.clientX >= rect.left && e.clientX <= rect.right &&
                    e.clientY >= rect.top && e.clientY <= rect.bottom;
    if (inPanel || (btn && btn.contains(e.target))) return;
    panel.classList.remove('open');
  }
});

/* ================================================================
   拖拽
   ================================================================ */
let dragId = null;
function onDragStart(e) {
  dragId = e.currentTarget.dataset.id;
  e.currentTarget.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', dragId);
}
function onDragEnd(e) { e.currentTarget.classList.remove('dragging'); dragId = null; }
async function onDrop(e, q) {
  e.preventDefault();
  const id = dragId || e.dataTransfer.getData('text/plain');
  if (!id) return;
  await api.set_quadrant(parseInt(id), q);
  await refreshAll();
}
document.querySelectorAll('.quad').forEach(el => {
  el.addEventListener('dragover', e => e.preventDefault());
  el.addEventListener('drop', e => onDrop(e, parseInt(el.dataset.quadrant)));
});

/* ================================================================
   任务操作
   ================================================================ */
async function completeTask(id, el) {
  el.classList.add('checked');
  await api.complete_task(id);
  setTimeout(refreshAll, 250);
}

async function deleteTask(id, title) {
  if (!confirm(`确定删除「${title}」？`)) return;
  await api.delete_task(id);
  await refreshAll();
}

async function deleteReportTask(id, title) {
  if (!confirm(`确定删除「${title}」？`)) return;
  await api.delete_task(id);
  // 刷新日报内容和日历标记
  completedDatesCache = await api.get_completed_dates();
  loadReportDay(fmtDate(reportDate));
}

async function uncompleteReportTask(id, title) {
  if (!confirm(`确定将「${title}」恢复为未完成？任务将回到四象限主页。`)) return;
  await api.uncomplete_task(id);
  // 刷新日报内容和日历标记，同时刷新主页（任务回到四象限）
  completedDatesCache = await api.get_completed_dates();
  loadReportDay(fmtDate(reportDate));
  refreshAll();
}

/* 任务抽屉公共骨架（新建/编辑共用） */
const DRAWER_SAVE_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>';
const DRAWER_ADD_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
function taskDrawerShell({titleText, submitText, submitIcon, titleValue='', descValue='', tagsValue='', defaultQuad=0, completedHTML='', hintText='ctrl + ↩︎ 快速保存'}) {
  return `<div class="drawer" style="height:480px;min-height:400px;max-height:80vh" onclick="event.stopPropagation()">
      <div class="drawer-header" style="padding-top:24px">
        <h2>${titleText}</h2>
        <span style="flex:1"></span>
        <span class="icon-btn-sm" onclick="closeDrawer()" title="关闭">${ICON_SVGS.close}</span>
      </div>
      <div class="drawer-body" style="gap:22px;padding-top:16px">
        <div style="flex:3;display:flex;flex-direction:column;min-width:0;overflow-y:auto">
          <label>标题 *</label>
          <input id="dlg-title" maxlength="80" value="${esc(titleValue)}" style="margin-bottom:12px">
          <label>描述</label>
          <textarea id="dlg-desc" style="height:64px;flex:none;min-height:64px;resize:vertical;margin-bottom:8px">${esc(descValue)}</textarea>
          <label>标签 <span style="opacity:.45;font-size:10px;font-weight:400;letter-spacing:.02em">多个标签用逗号或空格分隔</span></label>
          <input id="dlg-tags" value="${esc(tagsValue)}" style="margin-bottom:8px">
          <div id="dlg-tag-chips" class="dlg-tag-chips"></div>
          ${completedHTML}
          <div class="hint" style="margin-bottom:0;font-size:10px;color:var(--muted);opacity:.72;text-align:right">${hintText}</div>
        </div>
        <div style="flex:1;display:flex;flex-direction:column;min-width:0">
          <label>所属象限</label>
          <div class="radio-group" id="dlg-quads" style="grid-template-columns:1fr;align-content:start;margin-bottom:0">
            ${QUADRANT_NAMES.map((n,i) => `<div class="radio-option${i===defaultQuad?' selected':''}" data-v="${i}" onclick="selectRadio(this)">
              <span style="width:9px;height:9px;border-radius:50%;background:${QUADRANT_COLORS[i]};flex-shrink:0"></span>${n}</div>`).join('')}
          </div>
        </div>
      </div>
      <div class="drawer-footer" style="justify-content:flex-end;gap:10px">
        <button class="btn" onclick="closeDrawer()" style="display:inline-flex;align-items:center;gap:5px">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>取消</button>
        <button class="btn primary" id="dlg-submit" style="display:inline-flex;align-items:center;gap:5px">${submitIcon}${submitText}</button>
      </div>
    </div>`;
}

async function openEdit(id) {
  const t = await api.get_task(id);
  if (!t) return;
  const tags = parseTags(t.tag);
  closeModal();
  closeDrawer();
  const overlay = document.createElement('div');
  overlay.id = 'drawer-overlay';
  overlay.className = 'drawer-overlay';
  overlay.onclick = e => { if (e.target === overlay) closeDrawer(); };

  // 已完成任务支持编辑完成时间（datetime-local）；进行中任务不显示
  const completedHTML = t.completed_at
    ? `<label>完成时间</label><input type="datetime-local" id="edit-completed" value="${esc(t.completed_at.replace(' ', 'T'))}" style="margin-bottom:10px">`
    : '';

  // 与新建任务完全相同的抽屉排版（复用 dlg-* 输入框，历史标签胶囊/快捷键逻辑共用）
  overlay.innerHTML = taskDrawerShell({
    titleText: '✏️ 编辑任务',
    submitText: '保存',
    submitIcon: DRAWER_SAVE_SVG,
    titleValue: t.title,
    descValue: t.description,
    tagsValue: tags.join(' '),
    defaultQuad: t.quadrant,
    completedHTML,
  });

  document.body.appendChild(overlay);
  document.getElementById('dlg-submit').onclick = async () => {
    try {
      const title = document.getElementById('dlg-title').value.trim();
      if (!title) { alert('任务标题不能为空'); document.getElementById('dlg-title').focus(); return; }
      const desc = document.getElementById('dlg-desc').value.trim();
      const rawTags = document.getElementById('dlg-tags').value;
      const tags = rawTags.split(/[,，;；、\s]+/).filter(x=>x.trim());
      const quad = parseInt(document.querySelector('#dlg-quads .selected')?.dataset.v ?? '0');
      // 完成时间：datetime-local 无秒，分钟数补 :00；清空表示恢复进行中
      let completedVal = '';
      const completedEl = document.getElementById('edit-completed');
      if (completedEl) {
        completedVal = completedEl.value ? completedEl.value.replace('T', ' ') : '';
        if (completedVal && completedVal.split(' ')[1].split(':').length === 2) completedVal += ':00';
      }
      await api.update_task(id, title, desc, JSON.stringify([...new Set(tags)]), quad, completedVal);
      closeDrawer();
      await loadAllTags();
      await refreshAll();
      // 若原任务已完成，同步刷新日报内容与日历标记
      if (t.completed_at) {
        completedDatesCache = await api.get_completed_dates();
        loadReportDay(fmtDate(reportDate));
      }
    } catch(err) { alert('保存失败: ' + err.message); console.error(err); }
  };
  setTimeout(() => document.getElementById('dlg-title').focus(), 100);
  // Ctrl+Enter 快速保存
  overlay.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      const submit = document.getElementById('dlg-submit');
      if (submit) submit.click();
    }
  });
  // 每次打开都重新拉取标签，避免刚保存的新标签还停在内存缓存里
  const tagInput = document.getElementById('dlg-tags');
  if (tagInput) tagInput.addEventListener('input', renderTagChips);
  await loadAllTags();
  renderTagChips();
}

/* 新建任务抽屉：历史标签快速点选 */
function addTagToInput(tag) {
  const input = document.getElementById('dlg-tags');
  if (!input) return;
  const existing = input.value.split(/[,，;；、\s]+/).filter(Boolean);
  if (existing.includes(tag)) return;
  existing.push(tag);
  input.value = existing.join(' ');
  renderTagChips();
}

function removeTagFromInput(tag) {
  // 取消选择：仅移除该标签，保留输入框中其他已输入的标签文本
  const input = document.getElementById('dlg-tags');
  if (!input) return;
  const existing = input.value.split(/[,，;；、\s]+/).filter(Boolean);
  const idx = existing.indexOf(tag);
  if (idx < 0) return;
  existing.splice(idx, 1);
  input.value = existing.join(' ');
  renderTagChips();
}

function renderTagChips() {
  const box = document.getElementById('dlg-tag-chips');
  if (!box) return;
  const input = document.getElementById('dlg-tags');
  const existing = input ? input.value.split(/[,，;；、\s]+/).filter(Boolean) : [];
  // 输入框里刚打的新标签也立刻进胶囊，避免「看起来没加上」
  const tags = [];
  for (const tag of allTags.concat(existing)) {
    if (tag && !tags.includes(tag)) tags.push(tag);
  }
  if (!tags.length) {
    box.innerHTML = '<span class="dlg-tag-empty">暂无历史标签</span>';
    return;
  }
  // 按任务标签配色展示胶囊；已加入输入框的胶囊变淡，再次点击可取消选择
  box.innerHTML = tags.map((tag, i) => {
    const used = existing.includes(tag);
    const [fg, bg] = tagPalette(tag);
    const style = used
      ? `background:${bg} !important;color:${fg} !important;opacity:.38`
      : `background:${bg} !important;color:${fg} !important`;
    const fn = used ? 'removeTagFromInput' : 'addTagToInput';
    return `<span class="dlg-tag-chip${used ? ' used' : ''}" style="${style}" onclick="${fn}(${jsArg(tag)})">${esc(tag)}</span>`;
  }).join('');
}

/* ================================================================
   新建任务
   ================================================================ */
async function openAdd(quadrant = 0) {
  closeModal();
  closeDrawer();
  const overlay = document.createElement('div');
  overlay.id = 'drawer-overlay';
  overlay.className = 'drawer-overlay';
  overlay.onclick = e => { if (e.target === overlay) closeDrawer(); };

  overlay.innerHTML = taskDrawerShell({
    titleText: '＋ 新建任务',
    submitText: '添加',
    submitIcon: DRAWER_ADD_SVG,
    defaultQuad: quadrant,
    hintText: 'ctrl + ↩︎ 快速添加任务',
  });

  document.body.appendChild(overlay);
  document.getElementById('dlg-submit').onclick = async () => {
    try {
      const title = document.getElementById('dlg-title').value.trim();
      if (!title) { alert('任务标题不能为空'); document.getElementById('dlg-title').focus(); return; }
      const desc = document.getElementById('dlg-desc').value.trim();
      const rawTags = document.getElementById('dlg-tags').value;
      const tags = rawTags.split(/[,，;；、\s]+/).filter(x=>x.trim());
      const quad = parseInt(document.querySelector('#dlg-quads .selected')?.dataset.v ?? '0');
      if (!api) { alert('系统未就绪，请稍后重试'); return; }
      await api.add_task(title, desc, JSON.stringify([...new Set(tags)]), quad);
      closeDrawer();
      await loadAllTags();
      await refreshAll();
    } catch(err) { alert('保存失败: ' + err.message); console.error(err); }
  };
  setTimeout(() => document.getElementById('dlg-title').focus(), 100);
  // Ctrl+Enter 快速添加任务
  overlay.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      const submit = document.getElementById('dlg-submit');
      if (submit) submit.click();
    }
  });
  // 每次打开都重新拉取标签，避免刚保存的新标签还停在内存缓存里
  const tagInput = document.getElementById('dlg-tags');
  if (tagInput) tagInput.addEventListener('input', renderTagChips);
  await loadAllTags();
  renderTagChips();
}

function selectRadio(el) {
  el.parentElement.querySelectorAll('.radio-option').forEach(o => o.classList.remove('selected'));
  el.classList.add('selected');
}

/* ================================================================
   任务详情
   ================================================================ */
async function openDetail(id) {
  const t = await api.get_task(id);
  if (!t) return;
  const tags = parseTags(t.tag);
  const qColor = QUADRANT_COLORS[t.quadrant] || '#8a93b0';
  const qName = QUADRANT_NAMES[t.quadrant] || `象限${t.quadrant}`;
  showModal('任务详情', `
    <h2 style="font-size:16px;margin:0 0 14px">${esc(t.title)}</h2>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;flex-wrap:wrap">
      <span style="width:8px;height:8px;border-radius:50%;background:${qColor};display:inline-block"></span>
      <span style="font-size:11px">${qName}</span>
      ${tags.map(tg => tagSpan(tg)).join('')}
    </div>
    <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:14px 16px;margin-bottom:14px">
      <div style="font-size:11px;margin-bottom:6px">任务描述</div>
      <div style="font-size:12.5px;line-height:1.6;white-space:pre-wrap;word-break:break-word">${esc(t.description) || '（无描述）'}</div>
    </div>
    <div style="font-size:12px;margin-bottom:4px">创建时间：${esc(t.created_at)}</div>
    ${t.completed_at ? `<div style="font-size:12px">完成归档：${esc(t.completed_at)}</div>` :
      '<div style="font-size:12px">状态：进行中</div>'}`,
    [{icon:'edit',action:'noop',handler:()=>{closeModal();openEdit(t.id)}},
     {icon:'delete',action:'noop',handler:()=>{closeModal();deleteTask(t.id,t.title)}},
     {icon:'close',action:'close'}]);
}

/* ================================================================
   设置
   ================================================================ */
async function openSettings() {
  const st = await api.get_settings();
  const mode = st.window_mode || 'topmost';
  const theme = st.theme || DEFAULT_THEME;
  let ver = '';
  try { ver = (await api.get_app_version()).version || ''; } catch(e) {}
  let autoStart = false;
  try { autoStart = await api.get_autostart(); } catch(e) {}
  clearUpdatePoll();
  closeDrawer();
  const overlay = document.createElement('div');
  overlay.id = 'drawer-overlay';
  overlay.className = 'drawer-overlay';
  overlay.onclick = e => { if (e.target === overlay) closeDrawer(); };

  overlay.innerHTML = `
    <div class="drawer" onclick="event.stopPropagation()">
      <div class="drawer-header">
        <h2>⚙️ 设置</h2>
        <span style="flex:1"></span>
        <span style="display:flex;align-items:center;gap:8px">
          <span style="font-size:12px">开机自启动</span>
          <label class="switch" title="开机自启动">
            <input type="checkbox" id="set-autostart" ${autoStart?'checked':''}>
            <span class="slider"></span>
          </label>
        </span>
      </div>
      <div class="drawer-body" style="flex-direction:column;gap:2px;overflow-y:auto">
        <label>窗口模式</label>
        <div class="radio-group" id="set-modes" style="grid-template-columns:repeat(3,1fr)">
          ${[{k:'desktop',n:'固定桌面',d:'无边框、不置顶'},{k:'topmost',n:'置顶最前',d:'无边框，悬浮所有应用之上'},
            {k:'normal',n:'普通窗口',d:'系统标题栏'}].map(m =>
            `<div class="radio-option${m.k===mode?' selected':''}" data-v="${m.k}" onclick="selectRadio(this)">
              <div><div style="font-weight:600;font-size:12.5px">${m.n}</div><div style="font-size:10.5px">${m.d}</div></div></div>`
          ).join('')}
        </div>
        <label>主题外观</label>
        <div style="display:flex;gap:8px;align-items:center">
          <select id="set-theme-select" onchange="onThemeSelect(this.value)" style="flex:1;min-width:0;padding:8px 10px;border-radius:9px;border:1px solid var(--border);background:var(--card);color:var(--ink);font-size:12.5px;outline:none;cursor:pointer">
            ${THEME_LIST.map(t =>
              `<option value="${t.id}"${t.id===theme?' selected':''}>${esc(t.name)}${t.default==='1'?'（默认）':''}${t.builtin==='1'?'':' · 自定义'}</option>`
            ).join('')}
            ${THEME_LIST.length === 0 ? '<option value="paper">晨雾纸墨（默认）</option>' : ''}
          </select>
          <button class="btn" onclick="document.getElementById('theme-file-input').click()" style="padding:8px 12px;flex:none">导入主题</button>
          <input type="file" id="theme-file-input" accept=".css" style="display:none" onchange="importThemeFile(this)">
        </div>
        <label>软件更新</label>
        <div class="update-card">
          <div class="update-head">
            <span class="update-ver" id="ver-label">当前版本 <b>v${esc(ver) || '未知'}</b><span class="update-new" id="update-new" style="display:none"></span></span>
            <span class="update-links">
              <button class="update-link" id="btn-check-update" onclick="checkUpdate()">检查更新</button>
              <button class="update-link primary" id="btn-download-update" onclick="downloadUpdate()" style="display:none">下载并更新</button>
              <button class="update-link primary" id="btn-apply-update" onclick="applyUpdateNow()" style="display:none">立即更新</button>
            </span>
          </div>
          <div id="update-status" class="update-status">尚未检查更新</div>
        </div>
      </div>
      <div class="drawer-footer">
        <span style="flex:1"></span>
        <button class="btn" onclick="closeDrawer()">取消</button>
        <button class="btn primary" onclick="saveSettingsFromDrawer()">确定</button>
      </div>
    </div>`;

  document.body.appendChild(overlay);
  // 展示当前更新状态（含后台已下载完成、可随时安装的情况）
  try {
    const st = await api.get_update_state();
    if (st && st.phase) {
      renderUpdateState(st);
      if (st.phase === 'checking' || st.phase === 'downloading') {
        updateTimer = setInterval(async () => {
          let s; try { s = await api.get_update_state(); } catch(e) { return; }
          renderUpdateState(s);
        }, 500);
      }
    }
  } catch(e) {}
}

async function saveSettingsFromDrawer() {
  const newMode = document.querySelector('#set-modes .selected')?.dataset.v;
  const newTheme = document.getElementById('set-theme-select')?.value;
  const newAutoStart = document.getElementById('set-autostart')?.checked;
  // 先写开机自启动，再保存设置：窗口模式变更会触发进程重启，
  // 若顺序颠倒，自启动写入会被随窗口销毁的 JS 桥跳过，导致重启后仍显示未开启
  if (typeof newAutoStart === 'boolean') {
    try {
      const ok = await api.set_autostart(newAutoStart);
      if (!ok) alert('开机自启动设置失败，请检查系统权限后重试');
    } catch(e) {}
  }
  if (newTheme) applyTheme(newTheme);
  await api.save_settings({window_mode: newMode, theme: newTheme});
  closeDrawer();
}

/* ================================================================
   检查更新（GitHub Releases）
   ================================================================ */
let updateTimer = null;
function clearUpdatePoll() { if (updateTimer) { clearInterval(updateTimer); updateTimer = null; } }

async function checkUpdate() {
  if (!api) return;
  clearUpdatePoll();
  const btn = document.getElementById('btn-check-update');
  const status = document.getElementById('update-status');
  // 本地已有下载好的新包：直接提示就绪，不再重复检查/下载
  try {
    const st0 = await api.get_update_state();
    if (st0 && st0.phase === 'ready') { renderUpdateState(st0); return; }
  } catch(e) { /* 继续常规检查 */ }
  if (btn) btn.disabled = true;
  if (status) status.textContent = '正在检查更新…';
  try { await api.start_check_update(); }
  catch(e) { if (status) status.textContent = '检查失败：' + e.message; if (btn) btn.disabled = false; return; }
  updateTimer = setInterval(async () => {
    let st;
    try { st = await api.get_update_state(); } catch(e) { return; }
    renderUpdateState(st);
  }, 500);
}

function renderUpdateState(st) {
  const status = document.getElementById('update-status');
  const checkBtn = document.getElementById('btn-check-update');
  const dlBtn = document.getElementById('btn-download-update');
  const applyBtn = document.getElementById('btn-apply-update');
  const newBadge = document.getElementById('update-new');
  if (!status) return;
  status.classList.remove('ok', 'err');
  if (st.phase === 'checking') {
    if (checkBtn) checkBtn.disabled = true;
    status.textContent = '正在检查更新…';
  } else if (st.phase === 'error') {
    if (checkBtn) checkBtn.disabled = false;
    if (dlBtn) { dlBtn.style.display = 'none'; dlBtn.textContent = '下载并更新'; }
    if (applyBtn) applyBtn.style.display = 'none';
    clearUpdatePoll();
    status.classList.add('err');
    status.textContent = st.error || '更新出错，请稍后重试';
  } else if (st.phase === 'result') {
    if (checkBtn) checkBtn.disabled = false;
    clearUpdatePoll();
    if (st.has_update) {
      if (newBadge) { newBadge.style.display = ''; newBadge.innerHTML = `（检测到新版本 <b>v${esc(st.latest_version)}</b>）`; }
      const notes = (st.notes || '').split('\n').filter(Boolean).slice(0, 6).map(s => esc(s)).join('\n');
      status.innerHTML = notes ? notes : '已找到新版本，可点击下方按钮下载';
      if (dlBtn) { dlBtn.style.display = ''; dlBtn.disabled = false; dlBtn.textContent = '下载并更新'; }
      if (applyBtn) applyBtn.style.display = 'none';
    } else {
      if (newBadge) newBadge.style.display = 'none';
      if (dlBtn) dlBtn.style.display = 'none';
      if (applyBtn) applyBtn.style.display = 'none';
      status.classList.add('ok');
      status.textContent = `已是最新版本 v${st.current_version}`;
    }
  } else if (st.phase === 'downloading') {
    if (checkBtn) checkBtn.disabled = true;
    if (dlBtn) { dlBtn.disabled = true; dlBtn.textContent = '下载中…'; }
    status.textContent = `正在下载更新… ${Math.round(st.progress)}%`;
  } else if (st.phase === 'ready') {
    if (checkBtn) checkBtn.disabled = false;
    if (dlBtn) dlBtn.style.display = 'none';
    clearUpdatePoll();
    status.classList.add('ok');
    status.textContent = '更新已下载完成，点击「立即更新」打开安装包';
    if (applyBtn) { applyBtn.style.display = ''; applyBtn.disabled = false; }
  } else if (st.phase === 'applying') {
    status.textContent = '正在打开安装包…';
  } else {
    status.textContent = '尚未检查更新，点击上方按钮开始';
  }
}

async function downloadUpdate() {
  const status = document.getElementById('update-status');
  const dlBtn = document.getElementById('btn-download-update');
  if (status) status.textContent = '准备下载…';
  if (dlBtn) { dlBtn.disabled = true; dlBtn.textContent = '下载中…'; }
  clearUpdatePoll();
  updateReadyPrompted = false; // 新一轮下载完成后可再次弹窗
  startUpdateMonitor();
  try { await api.start_download_update(); }
  catch(e) {
    if (status) status.textContent = '下载失败：' + e.message;
    if (dlBtn) { dlBtn.disabled = false; dlBtn.textContent = '下载并更新'; }
    return;
  }
  updateTimer = setInterval(async () => {
    let st;
    try { st = await api.get_update_state(); } catch(e) { return; }
    renderUpdateState(st);
  }, 500);
}

async function applyUpdateNow() {
  const status = document.getElementById('update-status');
  if (status) status.innerHTML = '<div style="color:#3dd68c">正在打开安装包…</div>';
  clearUpdatePoll();
  try {
    const r = await api.apply_update();
    if (r && r.ok === false) {
      if (status) status.textContent = (r.error || '更新失败') + '（请稍后重试）';
    } else if (status) {
      status.textContent = '已打开安装包。若四象仍在运行，请在安装器提示时关闭后再继续。';
    }
  } catch(e) { if (status) status.textContent = '应用更新失败：' + e.message; }
}

/* 后台更新监控：设置页关闭后仍持续轮询，下载完成弹窗询问是否立即更新 */
let updateMonitorTimer = null;
let updateReadyPrompted = false;
function startUpdateMonitor() {
  if (updateMonitorTimer) return;
  const stop = () => { clearInterval(updateMonitorTimer); updateMonitorTimer = null; };
  updateMonitorTimer = setInterval(async () => {
    let st;
    try { st = await api.get_update_state(); } catch(e) { return; }
    if (!st) return;
    if (st.phase === 'ready') {
      if (updateReadyPrompted) { stop(); return; }
      // 设置抽屉打开时由抽屉内轮询展示状态，等关闭后再弹窗
      if (document.getElementById('update-status')) return;
      updateReadyPrompted = true;
      stop();
      showUpdateReadyModal();
      return;
    }
    // 非下载/检查中的状态无需继续监控，停止轮询
    if (st.phase !== 'downloading' && st.phase !== 'checking') stop();
  }, 2000);
}

function showUpdateReadyModal() {
  showModal('更新已就绪', `
    <div style="font-size:13px;line-height:1.8">
      新版本已下载完成，是否现在更新？<br>
      <span style="font-size:11px;color:var(--muted)">会打开安装包。若四象正在运行，安装器会提示关闭后再继续；装完可选择启动。稍后可在设置中点击「立即更新」。</span>
    </div>`,
    [
      {text:'稍后再说', action:'close'},
      {text:'现在更新', action:'noop', primary:true, handler: async () => {
        closeModal();
        await applyUpdateNow();
      }},
    ]);
}

/* ================================================================
   日报
   ================================================================ */
let reportDate = new Date();
let completedDatesCache = [];
let reportCalendarOpen = false;
let calYear, calMonth;

async function openReport() {
  completedDatesCache = await api.get_completed_dates();
  reportDate = new Date();
  reportCalendarOpen = false;
  renderReportDrawer();
}

function closeDrawer() {
  const d = document.getElementById('drawer-overlay');
  if (d) d.remove();
}

function renderReportDrawer() {
  closeDrawer();
  const sel = fmtDate(reportDate);
  const weekday = WEEKDAYS[(reportDate.getDay() + 6) % 7];
  calYear = reportDate.getFullYear();
  calMonth = reportDate.getMonth();

  const overlay = document.createElement('div');
  overlay.id = 'drawer-overlay';
  overlay.className = 'drawer-overlay';
  overlay.onclick = e => { if (e.target === overlay) closeDrawer(); };

  overlay.innerHTML = `
    <div class="drawer" onclick="event.stopPropagation()">
      <div class="drawer-header" style="gap:10px;position:relative">
        <h2>📋 日报</h2>
        <div class="report-nav">
          <button class="report-nav-btn" onclick="reportPrev()" title="前一天">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <div class="report-nav-center" onclick="toggleCalendar()" title="点击展开 / 收起日历">
            <span class="report-date">${sel} ${weekday}</span>
            <svg id="cal-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
          </div>
          <button class="report-nav-btn" onclick="reportNext()" title="后一天">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
          </button>
          <div class="report-calendar" id="report-calendar" style="display:none">
            <div class="calendar-nav">
              <button class="nav-btn" onclick="calPrev()">‹</button>
              <span class="cal-month" style="flex:1;text-align:center;font-weight:700"></span>
              <button class="nav-btn" onclick="calNext()">›</button>
            </div>
            <div class="calendar-grid" id="cal-grid"></div>
          </div>
        </div>
        <span style="flex:1"></span>
        <button class="btn" onclick="drawerExportDay()" style="padding:5px 12px;font-size:11px">导出当日</button>
        <button class="btn" onclick="drawerExportRange()" style="padding:5px 12px;font-size:11px">导出范围</button>
      </div>
      <div class="drawer-body" style="flex-direction:column;padding-top:6px">
        <div id="report-content" style="flex:1;overflow-y:auto;min-height:0"></div>
      </div>
    </div>`;

  document.body.appendChild(overlay);
  renderCalendar();
  loadReportDay(sel);
}

function updateReportNavDate() {
  const el = document.querySelector('.report-date');
  if (el) el.textContent = fmtDate(reportDate) + ' ' + WEEKDAYS[(reportDate.getDay() + 6) % 7];
}

function renderCalendar() {
  const sel = fmtDate(reportDate);
  const today = fmtDate(new Date());
  const monthLabel = document.querySelector('.report-calendar .cal-month');
  const grid = document.getElementById('cal-grid');
  if (monthLabel) monthLabel.textContent = `${calYear} 年 ${calMonth + 1} 月`;
  if (grid) grid.innerHTML = '一二三四五六日'.split('').map(d => `<div class="weekday">${d}</div>`).join('') + buildCalendarCells(calYear, calMonth, sel, today);
}

function buildCalendarCells(y, m, sel, today) {
  const first = new Date(y, m, 1);
  const offset = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(y, m+1, 0).getDate();
  let html = '';
  for (let i = 0; i < 42; i++) {
    const d = new Date(y, m, 1 - offset + i);
    const ds = fmtDate(d);
    const inMonth = d.getMonth() === m;
    if (!inMonth && (i - offset >= daysInMonth || i < offset)) { html += `<div class="day" style="visibility:hidden">0</div>`; continue; }
    const cls = ['day'];
    if (ds === today) cls.push('today');
    if (ds === sel) cls.push('selected');
    if (completedDatesCache.includes(ds)) cls.push('completed');
    html += `<div class="${cls.join(' ')}" onclick="selectReportDay('${ds}')">${d.getDate()}</div>`;
  }
  return html;
}

function selectReportDay(ds) {
  reportDate = parseDate(ds);
  hideCalendar();
  updateReportNavDate();
  loadReportDay(ds);
}

function computeReportStats(tasks) {
  const byQ = [0,0,0,0], byTag = {}, hours = new Array(24).fill(0);
  tasks.forEach(t => {
    byQ[t.quadrant] = (byQ[t.quadrant]||0) + 1;
    (parseTags(t.tag)||['（无标签）']).forEach(tg => byTag[tg]=(byTag[tg]||0)+1);
    const hm = (t.completed_at||'').split(' ')[1];
    if (hm) {
      const h = parseInt(hm.split(':')[0], 10);
      if (!isNaN(h) && h >= 0 && h < 24) hours[h]++;
    }
  });
  const slots = HOUR_SLOTS.map((_, i) => hours.slice(i*4, i*4+4).reduce((a,b)=>a+b, 0));
  const tagCount = Object.keys(byTag).length;
  let peak = null;
  slots.forEach((c, i) => { if (c > 0 && (!peak || c > peak.count)) peak = {count: c, name: HOUR_SLOTS[i][0] + ' ' + HOUR_SLOTS[i][1]}; });
  const times = tasks.map(t => t.completed_at).filter(Boolean).sort();
  let avgMin = null;
  if (times.length >= 2) {
    let total = 0;
    for (let i = 1; i < times.length; i++) {
      total += (new Date(times[i].replace(' ','T')) - new Date(times[i-1].replace(' ','T'))) / 60000;
    }
    avgMin = Math.round(total / (times.length - 1));
  }
  return {total: tasks.length, byQ, byTag, slots, tagCount, peak, avgMin};
}

function fmtInterval(m) {
  if (m == null) return '—';
  if (m < 1) return '<1 分钟';
  if (m < 60) return m + ' 分钟';
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h} 小时 ${r} 分` : `${h} 小时`;
}

function cardsHTML(stats) {
  const cards = [
    {num: stats.total, label: '完成任务', color: QUADRANT_COLORS[3]},
    {num: stats.tagCount, label: '涉及标签', color: QUADRANT_COLORS[2]},
    {num: stats.peak ? stats.peak.name : '—', label: '高峰时段', color: QUADRANT_COLORS[1]},
    {num: fmtInterval(stats.avgMin), label: '平均完成间隔', color: QUADRANT_COLORS[0]},
  ];
  return `<div class="report-hero">` + cards.map(c =>
    `<div class="hero-card"><span class="hero-bar" style="background:${c.color}"></span>` +
    `<div class="hero-num">${esc(String(c.num))}</div><div class="hero-label">${c.label}</div></div>`
  ).join('') + `</div>`;
}

function donutHTML(stats) {
  const size = 168, stroke = 22;
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, cx = size / 2;
  let acc = 0, circles = '';
  for (let q = 0; q < 4; q++) {
    const v = stats.byQ[q] || 0;
    if (v <= 0) continue;
    const frac = v / stats.total;
    const len = frac * c;
    circles += `<circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${QUADRANT_COLORS[q]}" ` +
      `stroke-width="${stroke}" stroke-dasharray="${len.toFixed(2)} ${(c-len).toFixed(2)}" ` +
      `transform="rotate(${(acc*360-90).toFixed(2)} ${cx} ${cx})"/>`;
    acc += frac;
  }
  const legend = QUADRANT_NAMES.map((n, q) => {
    const v = stats.byQ[q] || 0;
    const pct = stats.total ? Math.round(v / stats.total * 100) : 0;
    return `<div class="legend-row"><span class="legend-dot" style="background:${QUADRANT_COLORS[q]}"></span>` +
      `<span class="legend-name">${n}</span><span class="legend-val">${v}</span>` +
      `<span class="legend-pct">${pct}%</span></div>`;
  }).join('');
  return `<div class="donut-wrap">` +
    `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" class="donut">${circles}` +
    `<text x="${cx}" y="${cx-1}" text-anchor="middle" class="donut-num">${stats.total}</text>` +
    `<text x="${cx}" y="${cx+15}" text-anchor="middle" class="donut-cap">完成任务</text></svg>` +
    `<div class="legend">${legend}</div></div>`;
}

function tagBarsHTML(byTag) {
  const entries = Object.entries(byTag).sort((a,b) => b[1]-a[1]).slice(0, 8);
  if (!entries.length) return '<div class="chart-empty">今日无标签记录</div>';
  const top = entries[0][1];
  return entries.map(([tag, count], i) => {
    const [fg] = tagPalette(tag);
    const pct = Math.round(count / top * 100);
    return `<div class="tbar-row"><span class="tbar-name" title="${esc(tag)}">${esc(tag)}</span>` +
      `<div class="tbar-track"><div class="tbar-fill" style="width:${pct}%;background:${fg}"></div></div>` +
      `<span class="tbar-val">${count}</span></div>`;
  }).join('');
}

function hourBarsHTML(slots) {
  const top = Math.max.apply(null, slots.concat([1]));
  return slots.map((count, i) => {
    const pct = count ? Math.max(3, Math.round(count / top * 100)) : 0;
    const [name, span] = HOUR_SLOTS[i];
    return `<div class="hbar-col${count ? '' : ' empty'}"><span class="hbar-val">${count}</span>` +
      `<div class="hbar" style="height:${pct}%"></div>` +
      `<span class="hbar-label">${name}<br>${span}</span></div>`;
  }).join('');
}

function reportEmptyHTML(ds) {
  return `<div class="report-empty">` +
    `<svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><path d="M9 16l2 2 4-4"/></svg>` +
    `<div style="font-size:13px">${ds} 暂无已完成任务</div>` +
    `<div class="sub">去四象限勾选任务，完成记录会出现在这里</div></div>`;
}

async function loadReportDay(ds) {
  const tasks = await api.get_completed_tasks(ds);
  const el = document.getElementById('report-content');
  if (!el) return;
  if (!tasks.length) {
    el.innerHTML = reportEmptyHTML(ds);
    return;
  }
  const stats = computeReportStats(tasks);
  const tagsCell = t => '<div class="report-tags">' + parseTags(t.tag).map(tg => tagSpan(tg)).join('') + '</div>';
  el.innerHTML = `
    <div class="report-tabs">
      <div class="report-tab active" data-tab="detail" onclick="switchReportTab('detail')">
        <span class="report-overview-title">任务明细</span>
      </div>
      <div class="report-tab" data-tab="overview" onclick="switchReportTab('overview')">
        <span class="report-overview-title">日报概览</span>
      </div>
    </div>
    <div id="report-page-overview" style="display:none">
      ${cardsHTML(stats)}
      <div class="report-charts">
        <div class="chart-card">
          <h3>象限分布</h3>
          ${donutHTML(stats)}
        </div>
        <div class="chart-card">
          <h3>标签分布</h3>
          ${tagBarsHTML(stats.byTag)}
        </div>
        <div class="chart-card full">
          <h3>完成时段</h3>
          <div class="horbars">${hourBarsHTML(stats.slots)}</div>
        </div>
      </div>
    </div>
    <div id="report-page-detail">
      <div class="report-table"><table>
      <thead><tr>
        <th style="width:72px">完成时间</th>
        <th style="width:124px">标题</th>
        <th style="width:110px">标签</th>
        <th style="width:88px">象限</th>
        <th>描述</th>
        <th style="width:112px;text-align:center">操作</th>
      </tr></thead>
      <tbody>${tasks.map(t=>`<tr>
        <td>${esc(((t.completed_at||'').split(' ')[1]||'').slice(0,5))}</td>
        <td>${esc(t.title)}</td>
        <td style="white-space:normal;word-break:break-word">${tagsCell(t)}</td>
        <td>${esc(QUADRANT_NAMES[t.quadrant])}</td>
        <td style="white-space:pre-wrap;word-break:break-word">${esc(t.description)}</td>
        <td style="text-align:center;white-space:nowrap">
          <span class="icon-btn-sm" onclick="uncompleteReportTask(${t.id},${jsArg(t.title)})" title="取消完成" style="color:var(--q4,#3dd68c)">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" fill="currentColor" stroke="currentColor" stroke-width="1.2"/><path d="M5 8.2l2 2 4-4.4" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </span>
          <span class="icon-btn-sm" onclick="openEdit(${t.id})" title="编辑">${ICON_SVGS.edit}</span>
          <span class="icon-btn-sm danger" onclick="deleteReportTask(${t.id},${jsArg(t.title)})" title="删除">
            ${ICON_SVGS.delete}
          </span>
        </td>
      </tr>`).join('')}</tbody>
    </table></div>
    </div>`;
}

function switchReportTab(name) {
  document.querySelectorAll('.report-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === name);
  });
  const overview = document.getElementById('report-page-overview');
  const detail = document.getElementById('report-page-detail');
  if (overview) overview.style.display = name === 'overview' ? '' : 'none';
  if (detail) detail.style.display = name === 'detail' ? '' : 'none';
}

function calPrev() {
  const total = calYear * 12 + calMonth - 1;
  calYear = Math.floor(total / 12);
  calMonth = total % 12;
  renderCalendar();
}
function calNext() {
  const total = calYear * 12 + calMonth + 1;
  calYear = Math.floor(total / 12);
  calMonth = total % 12;
  renderCalendar();
}
function hideCalendar() {
  reportCalendarOpen = false;
  const cal = document.getElementById('report-calendar');
  const chevron = document.getElementById('cal-chevron');
  if (cal) cal.style.display = 'none';
  if (chevron) chevron.style.transform = '';
}
function toggleCalendar() {
  reportCalendarOpen = !reportCalendarOpen;
  const cal = document.getElementById('report-calendar');
  const chevron = document.getElementById('cal-chevron');
  if (reportCalendarOpen) {
    calYear = reportDate.getFullYear();
    calMonth = reportDate.getMonth();
    renderCalendar();
  }
  if (cal) cal.style.display = reportCalendarOpen ? 'block' : 'none';
  if (chevron) chevron.style.transform = reportCalendarOpen ? 'rotate(180deg)' : '';
}
function reportPrev() {
  reportDate = new Date(reportDate.getFullYear(), reportDate.getMonth(), reportDate.getDate() - 1);
  hideCalendar();
  updateReportNavDate();
  loadReportDay(fmtDate(reportDate));
}
function reportNext() {
  reportDate = new Date(reportDate.getFullYear(), reportDate.getMonth(), reportDate.getDate() + 1);
  hideCalendar();
  updateReportNavDate();
  loadReportDay(fmtDate(reportDate));
}

async function drawerExportDay() {
  try {
    const ds = fmtDate(reportDate);
    const files = await api.export_day(ds);
    alert(files.length ? `已生成 ${files.length} 个文件：\n${files.slice(0,6).join('\n')}` : `${ds} 没有已完成任务`);
  } catch (err) {
    alert('导出失败：' + (err.message || err));
  }
}

async function drawerExportRange() {
  try {
    const start = prompt('开始日期（YYYY-MM-DD）', fmtDate(new Date(new Date().getFullYear(), new Date().getMonth(), 1)));
    if (!start) return;
    const end = prompt('结束日期（YYYY-MM-DD）', fmtDate(new Date()));
    if (!end) return;
    const files = await api.export_range(start, end);
    alert(files.length ? `已生成 ${files.length} 个文件` : '该范围内没有可导出的记录');
  } catch (err) {
    alert('导出失败：' + (err.message || err));
  }
}

/* ================================================================
   设置操作
   ================================================================ */
let isLocked = false;

function updateLockUI() {
  const btn = document.getElementById('lock-btn');
  if (!btn) return;
  btn.title = isLocked ? '已锁定（点击解锁）' : '点击锁定';
  // 图标反映实时锁定状态：锁定时闭锁，解锁时开锁
  const icon = document.getElementById('lock-icon');
  if (icon) {
    icon.innerHTML = isLocked
      ? '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
      : '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>';
  }
  // 锁定时禁止窗口拖动：移除头部拖拽区域（pywebview 仅拖动 .pywebview-drag-region）
  const header = document.querySelector('header');
  if (header) header.classList.toggle('pywebview-drag-region', !isLocked);
}

async function toggleLock() {
  isLocked = !isLocked;
  updateLockUI();
  await api.save_settings({locked: isLocked ? '1' : '0'});
}

function clearStickyHover() {
  const b = document.body;
  if (!b) return;
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  b.style.pointerEvents = 'none';
  void b.offsetHeight;
  b.style.pointerEvents = '';
}
window.addEventListener('focus', clearStickyHover);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') clearStickyHover();
});
async function hideToTray() {
  clearStickyHover();
  if (!api) return;
  if (typeof api.minimize === 'function') await api.minimize();
  else if (typeof api.hide_to_tray === 'function') await api.hide_to_tray();
}
async function quitApp() { await api.quit(); }

/* ================================================================
   弹窗系统
   ================================================================ */
const ICON_SVGS = {
  edit: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
  delete: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
  close: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
};

function showModal(title, bodyHTML, buttons=[], opts={}) {
  let overlay = document.getElementById('modal-overlay');
  if (overlay) overlay.remove();
  overlay = document.createElement('div');
  overlay.id = 'modal-overlay';
  overlay.className = 'modal-overlay';
  overlay.onclick = e => { if (e.target === overlay) closeModal(); };
  const btnsHTML = buttons.map(b => {
    if (b.icon) {
      const cls = `icon-btn-sm${b.icon==='delete'?' danger':''}`;
      return `<span class="${cls}" data-icon="${b.icon}">${ICON_SVGS[b.icon]||''}</span>`;
    }
    return `<button class="btn${b.primary?' primary':''}">${b.text||''}</button>`;
  }).join('');
  overlay.innerHTML = `<div class="modal">
    <div style="display:flex;align-items:center;margin-bottom:16px"><h2 style="margin:0;flex:1">${title}</h2></div>
    <div class="modal-body">${bodyHTML}</div>
    <div class="actions">${btnsHTML}</div>
  </div>`;
  document.body.appendChild(overlay);
  const btnEls = overlay.querySelectorAll('.actions .btn, .actions .icon-btn-sm');
  btnEls.forEach((el, i) => {
    const b = buttons[i];
    el.onclick = async () => { if (b.handler) await b.handler(); if (b.action === 'close') closeModal(); };
  });
}
function closeModal() { const o = document.getElementById('modal-overlay'); if (o) o.remove(); }

/* 工具 */
function fmtDate(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function parseDate(s) { const [y,m,d] = s.split('-').map(Number); return new Date(y,m-1,d); }

/* ================================================================
   窗口边缘拖拽调整大小
   ================================================================ */
const RESIZE_EDGE = 6;
const MIN_W = 600, MIN_H = 450;
let resizing = null;

function getResizeDir(e) {
  const w = window.innerWidth, h = window.innerHeight;
  const x = e.clientX, y = e.clientY;
  let dir = '';
  if (y < RESIZE_EDGE) dir += 'n';
  else if (y > h - RESIZE_EDGE) dir += 's';
  if (x < RESIZE_EDGE) dir += 'w';
  else if (x > w - RESIZE_EDGE) dir += 'e';
  return dir;
}

const CURSOR_MAP = {
  'n':'ns-resize','s':'ns-resize','e':'ew-resize','w':'ew-resize',
  'ne':'nesw-resize','sw':'nesw-resize','nw':'nwse-resize','se':'nwse-resize'
};

document.addEventListener('mousemove', e => {
  if (resizing) {
    const dx = e.screenX - resizing.sx;
    const dy = e.screenY - resizing.sy;
    let w = resizing.ow, h = resizing.oh;
    if (resizing.dir.includes('e')) w = resizing.ow + dx;
    if (resizing.dir.includes('s')) h = resizing.oh + dy;
    if (resizing.dir.includes('w')) w = resizing.ow - dx;
    if (resizing.dir.includes('n')) h = resizing.oh - dy;
    w = Math.max(MIN_W, w);
    h = Math.max(MIN_H, h);
    if (api) api.resize(w, h);
    e.preventDefault();
    return;
  }
  const dir = getResizeDir(e);
  document.body.style.cursor = dir ? (CURSOR_MAP[dir] || '') : '';
});

document.addEventListener('mousedown', e => {
  const dir = getResizeDir(e);
  if (!dir || e.button !== 0) return;
  resizing = {
    dir, sx: e.screenX, sy: e.screenY,
    ow: window.innerWidth, oh: window.innerHeight
  };
  e.preventDefault();
});

document.addEventListener('mouseup', () => {
  if (resizing) resizing = null;
});

/* ================================================================
   事件委托（替代 inline onclick，避免 CSP 问题）
   ================================================================ */
document.addEventListener('click', e => {
  const tagBtn = document.getElementById('tag-filter-btn');
  if (tagBtn && (e.target === tagBtn || tagBtn.contains(e.target))) {
    toggleTagPanel();
    return;
  }
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;
  if (action === 'add') openAdd(parseInt(el.dataset.q) || 0);
  else if (action === 'add-task') openAdd();
  else if (action === 'report') openReport();
  else if (action === 'settings') openSettings();
  else if (action === 'lock') toggleLock();
  else if (action === 'minimize') hideToTray();
  else if (action === 'quit') quitApp();
});

/* 键盘 Esc */
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
