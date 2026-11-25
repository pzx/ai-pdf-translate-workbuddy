# 通用大批量翻译流水线脚本（决策 JSON 驱动）

这套脚本把「决策 JSON 唯一真相源 → 台账审校 → 回灌 → 指纹增量重建 → 校验」的闭环做成了**配置驱动**的可执行工具，零项目绑定。适用于多配色 × 多语言、需要人工审校和按词增量修订的整套卡片交付。

## 一键闭环

```bash
cd <skill>/pipeline
cp config.example.json pipeline.json     # 改 base/语言表/配色表/命名模板
python export_spans.py                   # 源稿 -> work/spans_all.json（标题字号/字宽/字母表的唯一来源）
python init_translations.py --init       # 键从源稿+几何派生 -> translations.json / zh_gloss.json 骨架
python init_translations.py --keys       # 待译键清单（分批翻译用）
python init_translations.py --merge 1.json --lang it   # 分批回填（幂等、拒绝未知键）
python init_translations.py --check      # 缺键/多键/空值/软回车/_short/_abbr 一次报清
python preflight.py                      # 体检：内框/插画/标题/译表覆盖（阻断项退 2）
python build_width_tables.py             # 量字宽 -> work/width_tables.json（正文限宽/折行）
#   译文或字体改了就要重跑；没有这张表正文长词会冲出卡片
python ledger_export.py                  # 决策 JSON -> output/xlsx/<ledger>
#   人工在 xlsx 审校：浅黄底的 译文/字号/中文
python ledger_import.py --dry            # 先看差异
python ledger_import.py                  # 回灌写回决策 JSON（幂等、带备份）
python rebuild.py it purple              # 只重建改过的一本
python rebuild.py all                    # 全部（自动跳过未变）
python verify.py                         # 页数 + text=0 + 文件齐全
python verify.py --layout                # 附：决策意图静态校验（未定版式/插图相交）
python letters_export.py                 # 字母对应表（字母页卡片专用）
```

## 换版型 / 新工程的闭环（产生 cx，缺它闸门会拒绝出图）

上面的闭环假设决策 JSON 已存在。换新源稿（排版/页面尺寸都变了）时，决策 JSON 必须重建，否则 `cx` 缺失、闸门拦下。完整四步：

```bash
# 0) 备好 config：languages / colors / 命名模板 / translations.json（en->{lang:译文}）
#    translations 放在 work_dir 下，或由 files.translations 指定。
python export_spans.py                    # 0b) 源稿文本 spans（缺它标题字号会退化，见下）
python init_translations.py --init --check # 0c) 语言表骨架 + 校验（键必须来自源稿，别手敲）
python export_geometry.py all --no-run    # 1a) 只生成几何导出 JSX，不跑 AI
#     逐个打开 work/export_geom_<色>.jsx 检查？不需要——直接看下一步产出的 TSV 计数
python export_geometry.py all             # 1b) 调 Illustrator 导出 geom_/inner_ TSV
#     检查每本 geom_<色>.tsv 的 L/I/T 行数是否符合版面；不对就调 config.geometry_export 门限重跑
python build_decisions.py all             # 2) 几何+译文 -> 带 cx/dy/sz 的决策 JSON
#     输出 WROTE ... entries=N with_cx=N；with_cx 必须等于 entries，否则闸门会拦
python build_width_tables.py              # 2b) 量字宽 -> width_tables.json（正文 MAXW/SCALE/折行）
python ledger_export.py                   # 3) 出台账，人工审校译文/字号 -> ledger_import 回灌
python rebuild.py all                     # 4) 正常出图（闸门校验 cx 后放行）
```

要点：
- **第 1 步是唯一与版型相关的步骤**。JSX 按尺寸门限把页面对象分成标签/插图/标题/内框，门限全在 `config.geometry_export`。换版型先跑 `--no-run` 生成 JSX，再真跑导 TSV，用 TSV 里的对象计数校准门限。判据：每本 `L`（标签）数应等于词条数、`T`（标题）数等于标题数、`I`（插图）数合理。
- **标题文本**：新版导出 JSX 会让 `T` 对象带上英文标题文本，`build_decisions.py` 据此从 translations 表匹配标题译文，不再依赖硬编码标题列表。旧 TSV 的 T 文本为空时，用 `files.decision_tuning` 的 `titles` 补。
- **插图方向**：默认插图在标签上方（AI 坐标 cy 更大）。若新模板插图在下，设 `geometry_export.illus_above=false`。
- **项目专属修正**（可选）：`files.decision_tuning` 指向一个 JSON，可给短同义词、字号修正、复合词、手工标题；留空不填也能产出完整 `cx/dy/sz`。
- **R4 手工位置回灌**（`pos` 段）：同一 tuning JSON 的 `pos: {lang:{color:{"<ab>|<英文键>":{dx,dy}}}}` 记录审校者手工挪动的水平/垂直位移（`work/build_pos_tuning.py` 从手工版 vs 生成版的 span diff 自动生成）。`build_decisions.py` 在写出决策时叠加到 `cx/dy`，标记 `posfix=1`。**清空 work 后重跑仍复现手工位置**——这是"手工改完→回灌决策→从零重建"闭环的关键，不要把位移直接写进 v7_dec（会被重算覆盖）。
- **R3 同形词消歧**：同一画板内同一英文词以相同字号出现多次、含义不同（blue p17 两个 `short`：矮/短），决策层按 x 排序输出 `key@1`/`key@2`（各带自己的 `cx`、`dupof`、`dupidx`），译表可用 `short@2` 给不同译文。`make_jsx.py` 按文字框 x 中心就近匹配变体，日志记 `HOMOGRAPH`。普通重复词（缩写格，字号≥1.25×）仍走 `#abbr` 机制，不受影响。
- **R2 转曲文字**：源文件里被 outline 成矢量路径、没有文字层的标签（green p23 `gloves`），`export_spans` 看不到。在 `pipeline.json` 顶层 `vector_text: [{color,page,en,box:[x0,y0,x1,y1],size}]` 声明（**box 用 Illustrator 展开坐标**，从 Illustrator 诊断拿精确值：遍历 `groupItems` 打印与标签区重叠的对象 bbox）；`build_decisions.py` 连同该语译文写进决策 `vectext` 段；`make_jsx.py` 的 `replaceVectorText()` **按 bbox 精确匹配并 `remove()` 掉包装转曲字的 group（实测 gloves=6 个 compoundPathItem 包在 2 个 groupItem），再从同画板复制一个正文标签框填译文**（duplicate + `tf.position=[x,y]`）。译表缺词 PENDING 报 `VECTEXT-MISS`。**踩坑**：①遍历 `doc.pageItems` 会卡死 Illustrator（对象上万），用 `groupItems` 按 bbox 匹配；②纯色矩形覆盖会在渐变背景留明显色块，不要用；③duplicate 后 `geometricBounds`/`duplicate(matrix)` 都无效，只有 `tf.position=[x,y]` 可靠；④裸 `textFrames.add()` 文字不渲染，必须 duplicate 正文标签（按字号范围挑，跳过标题）；⑤bbox 的 y0>y1（top 值更大）。

**`vector_text_engine`（匹配容差，按项目字号调）**：`center_tol_pt`（bbox 中心容差，默认 3.0）、`size_tol_pt`（尺寸容差，默认 4.0）、`template_size_min_pt` / `template_size_max_pt`（可作模板的正文字号区间，默认 16.5 / 19.5）。默认值适合 18pt 标签的版面；换项目若正文字号不同，务必同步调整这两个字号阈值，否则找不到模板框。
- **R1 字体兜底**：`make_jsx.py` 用 fontTools 从 `font_file` 读出全部名称（family/full/PostScript，含本地化名）注入 `FONTCANDS`；`findFont()` 逐个匹配 Illustrator 字体表。修掉"字体已装（如 Segoe UI Bold/segoeuib.ttf 已在注册表）但 Illustrator 只认 PostScript 名 SegoeUI-Bold，全名匹配失败→静默回退源稿细体 Myriad Pro"的坑。全部落空写 `FONT-MISS` 日志，不再静默出细体。

**清空 work/output 后如何复现（数据分层）**：脚本逻辑在技能里、不会丢；但**译表内容属于项目数据**，技能本身不内置译文（保持通用）。每个项目应把审校确认的 `translations.json`、`zh_gloss.json`、`pos_tuning.json` 备份到 `<项目>/_seed/`。从零重建时：①`export_spans`/`export_geometry` 重建 spans/geom；②把 `_seed/` 三表拷回 work；③`build_decisions`→`build_width_tables`→`rebuild`。

**通用性边界（四类修复）**：R1（字体名候选）、R3（同形词 `@N` 消歧）是纯逻辑，**任何项目开箱即用、无需配置**。R2（转曲文字）、R4（位置回灌）是通用机制 + 项目数据：**R2 靠 `pipeline.json` 的 `vector_text` 声明 bbox、`vector_text_engine` 调容差；R4 靠 decision_tuning 的 `pos` 段**。这些声明/数据属于项目，清空 work 不会丢（config 在项目根、pos 在 `_seed/`），但换项目必须重新提供。若连 `_seed/` 也删了，译表内容必须由译者重新写入——没有任何脚本能凭空生成译文。

**改配置后必须重生成决策**：R2 的 `vector_text` 与 R4 的 `pos` 都在 `build_decisions.py` 阶段被写进决策 JSON（快照）。改了 config 或 tuning 文件后，要让 `build_decisions` 重跑一次再 rebuild，否则旧决策仍生效——这与"改译表要重跑决策"是同一条规则。
- **闸门**：`make_jsx.py` 会拒绝任何缺 `cx` 的决策（退出码 3），`rebuild.py` 据此整批中止（退出码 4）。所以只要 `build_decisions.py` 报 `with_cx == entries`，出图一定放行。

等价性已验证：用 D7 真实几何 + 译文表跑泛化引擎，产出 145 条决策，译文与 cx 与原工程 v7 引擎逐条一致（cx 差 <0.2pt），且能过闸门生成 JSX。

## 配置驱动（pipeline.json）

所有项目事实集中在一个文件，脚本不写死任何路径/语言/配色/命名：

| 配置键 | 作用 |
|---|---|
| `base` / `work_dir` / `input_dir` / `output_dir` / `xlsx_dir` | 目录根（相对 base 或绝对） |
| `batch_date` / 环境变量 `BATCH_DATE` | 成品批次目录 `output/<batch>/{ai,pdf}`；台账不带日期 |
| `languages` | `[{code,name,font}]` — code 用于决策文件名，name 用于台账/成品名，font 是实际输出字体 |
| `colors` | `[{code,name,no,pages}]` — no 是源稿文件名里的序号，pages 供校验 |
| `files` | Python 格式模板：`decision/source_ai/product/spans/gloss/manifest/ledger/letters/jsx/jsx_log` |
| `schema` | 决策 JSON 内的键名（默认 dec/val/sz/mode/title_map）+ `ab_is_zero_based` |
| `jsx` | 生成器、批处理 runner（默认 `../scripts/run_batch.ps1`）、wait_ms、done_marker、pdf_compatible |
| `geometry` | 版式约束注入 JSX 的参数（标题椭圆适配、inkBounds、双行行距、插图避让）——见下节 |
| `layout` | 正文字宽预算：`body_thresh_pt`（槽可用宽）、`title_maxw_pt`（无椭圆时的标题上限）、`wrap_space_pt`（折行所需下方空间）、`min_scale`（正文最小字号系数）；被 `build_width_tables.py` 使用 |
| `geometry_export` | 换版型时导出几何的对象分类门限（label/frame/title/illus/inner 尺寸区间、插图方向、`title_band_ratio`）——见「换版型闭环」|
| `decision_engine` | 决策求解阈值（最小间距、位移上限、行距等，punkt）；新项目一般沿用默认 |
| `font_dir` / `languages[].font_file` | 决策引擎按字体量字宽：优先用 font_file 精确指定 TTF，否则在 font_dir 里按字体名模糊匹配 |
| `gate.require_sz` | 决策闸门：cx 强制必填；sz 默认可选，仅当引擎保证每条都写 sz 时才设 true |

`files.*` 模板可用占位符：`{no} {color_code} {color_name} {lang_code} {lang_name} {base} {work} {batch}`。

## 决策 JSON 契约（唯一真相源）

```json
{
  "dec": { "0": { "egg": {"val":"uovo","cx":708.3,"dy":0,"mode":"keep","sz":18.0} } },
  "title_map": { "Vehicles": "Veicoli" }
}
```

- `dec[画板][英文原文]` → 译文与版式；`title_map` 是颜色共用的标题。
- **一个英文串两种角色**：同一英文在同一页出现两种字号（典型：日历格里印缩写 `May`、格下印全名 `May`）时，最上面那一条（小字号）会被提升成独立键 `"<英文>#abbr"`，译文取 `translations` 里的 `"<lang>_abbr"`，并带 `szsrc`（原稿小字号）。`make_jsx` 按文字框自身字号匹配 `szsrc`（±0.7pt）决定用哪个，另一个框仍用主译文。台账里英文原文仍是 `May`（中文对照靠它取键），用**字号列**（该格真实的 12.8）与**模式列**（`keep·缩写格`）区分，ID 保留 `#abbr`，回灌照常。缺 `"<lang>_abbr"` 时不猜，只在 `pending` 里报 `ABBR-MISS`。
- 台账只是这份数据的**视图**；出图脚本只读决策 JSON，绝不读 xlsx。
- 改内容必须「台账 → 回灌 → 重建」，只改表不回灌会被指纹判为「没变」而跳过。

## 决策闸门（防止错位成品流出）

`make_jsx.py` 在生成 JSX 前会校验决策 JSON：

- **缺 `cx` 强制拦截**：`cx` 是从源稿量出的目标水平中心。缺了它，JSX 里的居中 `translate()` 会被静默跳过，成品每个词都偏离插图——这正是"只写 val/mode、没跑几何"的新工程出错的样子。报错退出码 3，列出画板|词条示例。
- **空决策拦截**：`dec` 下没有任何条目时同样报错。
- **`sz` 默认可选**：缺 `sz` = 沿用源字号，是合法用法（参考工程 145/145 条有 cx、0/145 条有 sz）。只有你的决策引擎保证每条都写 `sz` 时，才在 `pipeline.json` 设 `gate.require_sz=true` 打开严格模式。

`rebuild.py` 会把生成器的闸门失败**累计并中止整批**（退出码 4），不会像以前那样 `continue` 后照样返回 0、让人误以为交付成功。闸门失败时 Illustrator 根本不会被调用。

> 换版型/换排版时请先跑几何导出与决策引擎产出带 `cx` 的决策 JSON；本闸门只负责挡住不完整数据，不负责生成它。

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `common.py` | 配置加载、路径解析、字号/中文查询、\r↔\n 归一化、指纹、列定位 |
| `geomlib.py` | 几何 TSV 解析（labels/illus/frames/pageno/title + own_illus 关联），路径来自配置 |
| `export_geometry.py` + `geometry_export_template.jsx` | 换版型时从源稿导出几何 TSV；门限配置驱动，JSX 纯 ASCII |
| `build_decisions.py` | 几何 + 译文 -> 带 cx/dy/sz 的决策 JSON（布局无关的求解），产出过闸门所需数据 |
| `init_translations.py` | 语言表骨架/分批合并/校验：`--init` `--keys` `--merge` `--merge-gloss` `--check`。**只生成结构与校验，不编内容** |
| `export_spans.py` | 源稿 .ai/PDF -> `spans_all.json` + `unique_strings.json`（**全新工程的第一步**，整条链的文本事实都来自它） |
| `preflight.py` | 出决策前的体检：内框/插画/标题/译表覆盖/未解条目，阻断项退 2 |
| `build_width_tables.py` | 源稿 spans + 译文 + 真实字体 -> `width_tables.json`（每词 `MAXW`/`SCALE`、正文折行）；译文或字体变了要重跑 |
| `ledger_export.py` | 决策 JSON → 台账（总览/每语言一页/全语言对照）；**出表前自动回灌**防丢编辑 |
| `ledger_import.py` | 台账 → 决策 JSON；按表头名定位列、幂等、写前备份 |
| `letters_export.py` | 字母对应表 + 特有字母页（A–Z 保留英文时说明词与字母的对应） |
| `rebuild.py` | 指纹增量重建：单本/单语言/全部/`--force`；生成 JSX 后调批处理 |
| `make_jsx.py` | 决策驱动生成纯 ASCII 的 Illustrator JSX |
| `verify.py` | 校验 PDF 页数、活字=0（已转曲）、文件齐全；`--layout` 附加决策意图静态检查 |
| `geometry.jsx.inc` | 通用几何约束片段（纯 ASCII），由 `make_jsx.py` 注入生成的 JSX |

## 版式约束（生成即带上，不必另写）

`make_jsx.py` 会把 `geometry.jsx.inc` 和 `config.geometry` 注入每份 JSX，把卡片的经典版式坑变成**可执行约束**：

- **标题不超椭圆 + 居中**（`title_fit`，默认开）——四条硬约束，缺一条就会复现「同组标题字号不一 / 字压在椭圆上」：
  1. **一个标题一个字号，跨页一致**：字号取自源稿该标题的实测字号（`build_decisions` 之外的 `make_jsx.py` 现场从 spans 读），同一 `title_map` key 在所有页面用同一个值。**不要**逐帧按椭圆重算，否则同名字号必然发散。
  2. **必须落在椭圆内**：标题胶囊是真椭圆（4 段贝塞尔），`(x/a)²+(y/b)²≤1` 才算放得下；119×34pt 的椭圆在字身高度处只剩约 105pt 可用宽。超了按比例缩小（单行只按字身带判定，允许 `g/p` 的下伸字母悬挂）。
  3. **放不下才折两行**：单行缩到源字号 85% 以下才折行；折行用源稿双行标题的字号，再按椭圆收缩。两行必须 **`textRange.paragraphAttributes.justification = CENTER`**（设在 `tf.paragraphAttributes` 上会被静默忽略，两行就左对齐了），并按墨迹框整体居中。
  4. **居中基准**：单行按字身框（cap 顶→基线）居中，双行按墨迹框居中；不要用 `(top+bottom)/2`（下伸字母会把整块顶高）。
- **折行落位优先级**：内移（±`shift_cap_pt`）→ **大内移**（±`relax_shift_pt`，仍限本列）→ 折行 → 短译。折行时先吃文字净空 `room`，不够才**整排上移**（同排每格文字+插画同量位移，上限 = 该排所有插画上方净空的最小值），绝不单独抬一张图。台账模式列会标 `·整排↑x`。
- **页面事实只在一处算**：`geomlib._attach_facts()` 产出每标签的 `row / ill / room / illok / ceil`，决策层只读不算。缺内框或缺插画占比过高会直接 `REFUSED`（不再静默跳页）。
- **`layout.wrap_clear_pt`（默认 1.0）**：折行块与下方障碍/插画的净空。2mm 的一般 cushion 会把只差几 pt 的双行全部否决——源稿设计本身就只留 1–2pt。`violations()` 的 IL/PN 下限同步用它。
- **mode=wrap 必须 `\r`**：写回自愈 + 回读硬校验，不一致 `REFUSED`（曾两次出现换行符丢失，164pt 单行出图）。
- **终态审计**：决策层修不动的标签以前静默出图；`violations` 结果记回 state 并打印，剩几条、在哪一目了然。
- **出决策前先跑 `preflight.py`**：页数/标签数/底排数/行分布、译表覆盖、上次决策的未解条目，一屏看清；有阻断项退 2。
- **标题必须落在页顶标题带**（`geometry_export.title_band_ratio`，默认 0.25）：只看盒子尺寸/字号会把日历格子、徽章这类"同形状"的组误判成标题（实测真标题全在卡片高度 0.87 处，误判的在 0.24/0.60）。带外一律不判 T，另对"一页多 T"报警。
- **正文限宽**（`layout` + `width_tables.json`）：`build_width_tables.py` 用源稿 spans + 译文 + 真实字体量出每个词的 `MAXW`（可用墨迹宽）与 `SCALE`（字号系数），放不下的先折两行、再按 `min_scale` 缩字号；`make_jsx.py` 注入这两张表并逐词执行。**没有这张表时正文长词会直接冲出卡片**。
- **墨迹对齐**（`ink_bounds_words`）：开则复制文字→转曲→量真墨迹框（不含字体留白）再定位，比 `visibleBounds` 准但稍慢；默认关以保持速度。标题始终用 inkBounds。
- **双行行距**：含软回车的框设 `autoLeading=false`、leading=`max(cap×字号+gap, 0.94×字号+1)`——0.94em 是 typo 行高，低于它下行会碰上行；单行沿用 `lead_at_18×(字号/18)`。
- **文本与插画不相交**（`obstacle_gap` + `obstacle_nudge_cap`）：决策 JSON 可在 `"obstacles": {"<画板>": [[x0,y0,x1,y1],...]}` 给插图框（与 visibleBounds 同坐标系，top>y>bottom）。默认 `ocap=0` **只告警不移动**；决策引擎已做过避让就保持 0，手工搭决策才调大让它上移。
- **按画板取决策**（`boardOf`）：同一英文 key 可能出现在多页（`tree`、`rainbow`），出图时必须先用文字框中心算出它属于哪个画板，只取该画板的 `cx`；否则会拿别页的坐标，把词拖到另一页的插图上。

⚠️ 红框：`unlockAll` **只解锁 `locked`，绝不设 `visible=true`/`hidden=false`**——显示源稿隐藏对象会带出裁切标记，转曲后成红黑线框。`scripts/outline_export_template.jsx` 和 `references/illustrator-automation.md` 已按此修正。

## 编码进脚本的关键经验（勿删）

- **出表前先回灌**：目标台账已存在时，`ledger_export` 先跑 import 再覆盖，`XL_NO_SYNC=1` 可跳过。
- **按表头名定位列**：加列、调列顺序都不破坏回灌；主键用稳定 ID。
- **`\r`↔`\n` 归一化**：xlsx 把软回车存成 `\n`，不归一化会误判「全表都改了」。
- **字号改回源值自动清覆盖**：`rec.sz` 与源字号差 <0.05 时删除该键。
- **签名不含脚本**：指纹只算决策文件 + 源稿 + `width_tables.json` 的 size/mtime；改脚本不误触发全量，故意重做加 `--force`。`width_tables.json` 必须计入——折行/短译/槽宽都在里面，漏掉它会出现「改了规则但重建全 SKIP（unchanged）」的假象。
- **看产物 mtime 判成功**：不信任 PowerShell stdout（非 UTF-8 会乱码）。
- **语言表的键必须派生，不能手敲**：`init_translations.py --init` 把 `spans` 与 `geom`（复合两行词只存在于几何里）的文本并起来做键，实测从旧表查出 **21 个死键**（`ear/eye/trousers/soup/sushi/swimming pool…` 源稿里根本没有），同时补齐 84 条缺失的中文。`--merge` 拒绝未知键，写错一个字母就被挡住，不会静默变成英文。
- **三道静默失败守卫**（都由"删掉 work 从零重跑"暴露出来的）：①译表覆盖不足 → `build_decisions.py` 直接 REFUSED（缺词条时 `tr()` 会静默回退英文，PDF 照样过 `verify.py`）；②缺 `spans_all.json` → `make_jsx.py` 退出码 3（旧行为是给所有标题兜底 22pt，绿本 15.8/橙本 14.7 会被放大）；③缺 spans 的 `build_width_tables.py` 给可执行的修复提示而不是 traceback。
- **joblist 写绝对路径 + 读时 `-Encoding UTF8`**：runner 的 `$root` 是脚本目录（`<skill>/scripts`），相对项会在那里找（永远 MISSING）；PS 5.1 的 `Get-Content` 默认按 ANSI 解码，工程路径含中文时整行变乱码。两处都修过，别回退。
- **`<脚本>.log` 是硬契约**：runner 只认 `ChangeExtension(jsx,'.log')`，日志写别处就会被判「no log output」→ 每本重试 2 次、汇总成 FAIL，而产物其实是对的。
- **JSX 纯 ASCII**：所有非 ASCII 经 `js()` 转 `\uXXXX`；注释全英文，否则 `DoJavaScriptFile` 报 "code was missing"。
- **PDF 兼容层默认开**：`pdfCompatible=true`，正常交付不得关闭。
- **关文件后等 2 秒**：由 `../scripts/run_batch.ps1` 的 `-WaitMs 2000` 保证，别调小。

更完整的踩坑与大批量方法论见 `../references/batch-pipeline.md`。
