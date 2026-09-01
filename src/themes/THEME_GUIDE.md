# 主题开发规范（Theme Guide）

四象的主题系统为**单 CSS 文件 = 单主题**，可插拔、可快速安装。任何新主题都应遵循本规范，以保证跨主题一致性与 tkinter 回退可用。

## 1. 文件与命名

- 文件名即主题 id，必须为 ASCII：`[a-z0-9_-]`，如 `paper.css`、`my-cool.css`。
- 文件放在 `src/themes/`（源码模式）；打包后用户可在 exe 同目录 `themes/` 自行添加，启动时自动加载。
- 文件头部必须带 `/*!` 元数据注释：

```
/*!
 * id: paper          # 必须与文件名一致
 * name: 晨雾纸墨      # 下拉框显示的中文名
 * desc: 一句描述      # 可选
 * default: 1         # 仅默认主题为 1，其余 0
 */
```

- WebView 样式必须写在 `body.<id> { ... }` 及后代选择器下，避免与公共样式冲突。

## 2. 布局骨架（程序层，主题不要重复）

四象限等高、防挤压等**布局结构**由公共 CSS（`app.html`）统一负责：

```css
.grid{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:10px;padding:0 14px;flex:1;min-height:0}
.quad{position:relative;display:flex;flex-direction:column;min-height:0}
```

主题里**不需要**再写 `.grid` / `.quad` 的 `display`、`grid-template`、`flex`、`min-height` 等布局属性，只写外观：圆角、边框、背景、阴影、hover 动效。

## 3. CSS 变量体系

### 3.1 `--tk-*`：tkinter 回退配色（必需，单一来源）

每个主题必须在 `body.<id>` 中定义完整的 `--tk-*` 变量行，供 tkinter 回退版与打包时 `styles.py` 解析。必要字段：

| 变量 | 说明 |
| --- | --- |
| `--tk-bg` / `--tk-card` / `--tk-panel` / `--tk-panel2` | 窗口底 / 卡片 / 面板 / 面板次级 |
| `--tk-row_bg` / `--tk-row_hover` / `--tk-row_active` | 任务行三态 |
| `--tk-text` / `--tk-title_text` / `--tk-muted` / `--tk-secondary` | 文字色阶 |
| `--tk-border` / `--tk-accent` / `--tk-accent_light` / `--tk-accent_dark` | 边框与主色 |
| `--tk-green` / `--tk-tag_bg` / `--tk-tag_fg` | 完成 / 标签 |
| `--tk-check_box` / `--tk-check_border` / `--tk-check_border_hover` | 勾选框 |
| `--tk-qc0..3` / `--tk-qb0..3` | 四象限卡底色 / 描边色（**必须 hex**，tkinter 不支持 rgba） |
| `--tk-btn_hover` / `--tk-btn_press` / `--tk-report_*` / `--tk-grip` / `--tk-lock_*` | 按钮 / 日报 / 拖拽把手 / 锁定 |
| `--tk-ghost_bg` / `--tk-alpha` / `--tk-topline` / `--tk-check_round` | 透明度与形态 |
| `--tk-grad_hi` / `--tk-grad_lo` / `--tk-bg_accent` / `--tk-bg_grid` | 设计字段（列表用空格分隔） |

校验：`theme_loader.extract_tk_colors` 会解析该行；缺失字段自动回退到内置默认配色。

### 3.2 WebView 变量

WebView 层自定义变量建议统一命名，方便维护：

```css
--ink; --muted; --secondary; --border;
--accent; --accent-light; --accent-dark;
--q1; --q2; --q3; --q4;          /* 四象限主色 */
--card; --panel; --panel2;
--shadow;                          /* 阴影色（rgba） */
```

组件优先引用变量，避免硬编码颜色（`.q1`/`.q3` 等象限 tint 背景可写 rgba 常量，按主题自定）。

## 4. 组件模块清单

主题应覆盖以下模块（结构见公共 CSS，主题只定义颜色/圆角/阴影/动效）：

| 模块 | 说明 |
| --- | --- |
| `.widget` | 主窗容器：建议半透明 + `backdrop-filter:blur()` 磨砂；`::before` 顶部高光 |
| `header` / `h1` / `.date` | 标题栏（h1 可换字体族增强气质） |
| `.quad` / `.q1`~`.q4` / `.q-head` / `.tint` / `.q-name` / `.q-count` / `.q-add` | 四象限卡片 |
| `.task` / `.cb` / `.t-title` / `.tag` | 任务行 |
| `footer` / `.btn` / `.spacer` / `.grip` | 底部操作区 |
| `.icon-btn-sm` / `.switch` | 图标按钮 / 开关 |
| `.modal` / `.drawer` 及内部 input/textarea/select | 弹层与抽屉（浅色主题需补 input 边框/背景，见 6） |
| `.update-card` / `.report-*` / `.calendar-grid` / `.tag-panel` | 更新卡 / 日报 / 日历 / 标签面板 |

## 5. 装饰层约定

- 装饰元素 `.orb / .blob / .grid-bg / .leaf / .thread` 默认 `display:none`（公共层）。
- 主题需要时在文件末尾启用：`body.<id> .blob{display:block}`。
- 建议：背景光斑用 `filter:blur(60~80px)` 的低透明色块，配合磨砂才有层次。

## 6. 质感与可读性要点

- **磨砂质感**：`.widget` 用 `rgba(...)` 半透明 + `backdrop-filter:blur(24~30px) saturate(140~160%)`，并配 `::before` 线性高光；body 背景必须有渐变/光斑，否则磨砂透不出层次。
- **弹层输入框**：公共 `.drawer input/.drawer textarea` 只有骨架（padding/border-radius），主题必须补背景与边框色，例如：
  ```css
  body.xxx .drawer input,body.xxx .drawer textarea{background:var(--row_bg);color:var(--ink);border-color:var(--border)}
  ```
- 深色主题边框用 `rgba(255,255,255,.08~.14)`，浅色主题用 `rgba(255,255,255,.8~.92)` 或主题边框色。
- 卡片/任务行建议轻微半透明，让磨砂在组件层延续。

## 7. 交付前检查清单

1. 括号平衡：`css.count('{') == css.count('}')`。
2. `--tk-*` 变量行完整；`qc0..3` / `qb0..3` 全部为 hex。
3. 有 `/*!` 元数据头，id 与文件名一致，default 仅一套为 1。
4. 文件内只有 `body.<id> ...` 选择器，无裸选择器。
5. 渲染注入后 `body.<id>` 与 `id: <id>` 各只出现一次（防占位重复注入）。
6. `theme_loader.theme_list()` 能正确解析元数据；`styles.THEMES` 含该主题。

## 8. 安装与导入

- 用户手动安装：把 `.css` 放入应用目录 `themes/`（打包版为 exe 同目录），重启生效。
- 应用内导入：设置 → 主题外观 → 导入主题（校验 ASCII 文件名、`body.<id>` 规则、512KB 上限），导入后无需重启即时预览。
- 同名文件覆盖用户版本优先；内置缺失时自动从 `src/themes/` 兜底补全。
