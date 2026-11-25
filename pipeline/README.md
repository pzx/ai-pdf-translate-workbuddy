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
python build_decisions.py all            # 几何 + 译文 -> 决策 JSON（带 cx/dy；正文不写 sz）
python qa_prebuild.py                    # ★出图前体检：字形/字宽/同排/页码/漏译/标题/缩写格
#   有阻断项退 1。这里改一个词 = 改译表；出图后才发现 = 重出一整本
python ledger_export.py                  # 决策 JSON -> output/xlsx/<ledger>
#   人工在 xlsx 审校：浅黄底的 译文/中文（字号列是只读灰底，见「正文禁缩」）
python ledger_import.py --dry            # 先看差异
python ledger_import.py                  # 回灌写回决策 JSON（幂等、带备份）
python rebuild.py it:orange              # 只重建改过的一本
python rebuild.py all                    # 全部（自动跳过未变）
python verify.py                         # 页数 + text=0 + 文件齐全
python verify.py --layout                # 附：决策意图静态校验（未定版式/插图相交）
python qa_output.py                      # ★出图后复核：直接读成品字形坐标，查页码压字/出血/页数/标题居中与椭圆溢出
python letters_export.py                 # 字母对应表（字母页卡片专用）
```

**两道闸，缺一不可**：`qa_prebuild` 在出图前把所有能算出来的问题算掉（不调 Illustrator，秒级）；`qa_output` 在出图后不信任何模型，只读成品真实坐标（唯一能抓到"模板自带的页码被我们的长词压住"这类问题的环节）。

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
python build_decisions.py all             # 2) 几何+译文 -> 带 cx/dy 的决策 JSON（正文不写 sz）
#     输出 WROTE ... entries=N with_cx=N；with_cx 必须等于 entries，否则闸门会拦
python build_width_tables.py              # 2b) 量字宽 -> width_tables.json（正文 MAXW + 折行）
python ledger_export.py                   # 3) 出台账，人工审校译文 -> ledger_import 回灌
python rebuild.py all                     # 4) 正常出图（闸门校验 cx 后放行）
```

要点：
- **第 1 步是唯一与版型相关的步骤**。JSX 按尺寸门限把页面对象分成标签/插图/标题/内框，门限全在 `config.geometry_export`。换版型先跑 `--no-run` 生成 JSX，再真跑导 TSV，用 TSV 里的对象计数校准门限。判据：每本 `L`（标签）数应等于词条数、`T`（标题）数等于标题数、`I`（插图）数合理。
- **标题文本**：新版导出 JSX 会让 `T` 对象带上英文标题文本，`build_decisions.py` 据此从 translations 表匹配标题译文，不再依赖硬编码标题列表。旧 TSV 的 T 文本为空时，用 `files.decision_tuning` 的 `titles` 补。
- **插图方向**：默认插图在标签上方（AI 坐标 cy 更大）。若新模板插图在下，设 `geometry_export.illus_above=false`。
- **项目专属修正**（可选）：`files.decision_tuning` 指向一个 JSON，可给短同义词（`short`）、复合词、手工标题、手工位置；留空不填也能产出完整 `cx/dy`。注意 `sizefix` 在默认策略下**被忽略**（正文禁缩，只有标题能改字号）。
- **R4 手工位置回灌**（`pos` 段）：同一 tuning JSON 的 `pos: {lang:{color:{"<ab>|<英文键>":{dx,dy}}}}` 记录审校者手工挪动的水平/垂直位移（由人工比对「手工挪过的成品」与「引擎生成版」的 span 坐标求得，没有现成脚本——位移只有几 pt，肉眼看不出来，必须量）。`build_decisions.py` 在写出决策时叠加到 `cx/dy`，标记 `posfix=1`。**清空 work 后重跑仍复现手工位置**——这是"手工改完→回灌决策→从零重建"闭环的关键，不要把位移直接写进 v7_dec（会被重算覆盖）。
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
| `layout` | 版式常量：`body_thresh_pt`（槽可用宽）、`title_maxw_pt`（无椭圆时的标题上限）、`wrap_space_pt`/`wrap_lift_pt`（折行所需下方空间与可上移量）、`pageno_gap_pt`/`pageno_shift_cap_pt`（页码禁区与最大让位）、`clash_gap_pt`、`obstacle_gap_pt`、`row_tol_pt`、`bottom_row_pt`、`facts_max_missing_ratio`、`min_scale`（`FIT` 严重度阈值：需要缩到 72% 才装下即视为装不下；**不是**缩号开关）。出图后闸门另有 `title_pill_w_range`/`title_pill_h_range`/`title_top_pt`/`title_pout`/`title_center_tol_pt`/`title_glyph`。**没有任何键能缩正文字号** |
| `geometry_export` | 换版型时导出几何的对象分类门限（label/frame/title/illus/inner 尺寸区间、插图方向、`title_band_ratio`）——见「换版型闭环」|
| `decision_engine` | 决策求解阈值（最小间距、位移上限、行距等，punkt）；新项目一般沿用默认 |
| `layout.title_band_pt` | 标题带高度：文字底边距页顶小于该值视为标题（默认 62，适合卡片；整页/海报版式需调大，否则读不到标题字号） |
| `font_dir` / `languages[].font_file` | 决策引擎按字体量字宽：优先用 font_file 精确指定 TTF/OTF（绝对路径或相对 `base`）；不填则按字体**内部名称**（family/full/PostScript）在 `font_dir` 解析——Windows 文件名是 `ARLRDBD.TTF` 这类短码，所以读 name 表而不是猜文件名。解析不到会明确报错并提示配 font_file。**量字宽必须用 Illustrator 实际排版的那个字体**，否则宽度/折行判断全是错的 |
| `gate.require_sz` | 决策闸门：cx 强制必填；sz 默认可选，仅当引擎保证每条都写 sz 时才设 true |

`files.*` 模板可用占位符：`{no} {color_code} {color_name} {lang_code} {lang_name} {base} {work} {batch}`。

## 决策 JSON 契约（唯一真相源）

```json
{
  "dec": { "0": { "egg": {"val":"uovo","cx":708.3,"dy":0,"mode":"keep"} } },
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
- **正文 `sz` 强制拦截**：只有卡片标题可以改大小，而标题字号由 `make_jsx` 按源稿实测 + 椭圆适配算，不读决策的 `sz`。所以任何正文 `sz` 都是错误数据（台账误填、旧脚本、手工改决策），一律退 3 并列出条目。真要允许（特殊版式）必须在 `pipeline.json` 设 `gate.allow_body_sz=true`，那会同时放开 `tuning.sizefix`。

`rebuild.py` 会把生成器的闸门失败**累计并中止整批**（退出码 4），不会像以前那样 `continue` 后照样返回 0、让人误以为交付成功。闸门失败时 Illustrator 根本不会被调用。

> 换版型/换排版时请先跑几何导出与决策引擎产出带 `cx` 的决策 JSON；本闸门只负责挡住不完整数据，不负责生成它。

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `common.py` | 配置加载、路径解析、字号/中文查询、\r↔\n 归一化、指纹、列定位 |
| `geomlib.py` | 几何 TSV 解析（labels/illus/frames/pageno/title + own_illus 关联），路径来自配置 |
| `export_geometry.py` + `geometry_export_template.jsx` | 换版型时从源稿导出几何 TSV；门限配置驱动，JSX 纯 ASCII |
| `build_decisions.py` | 几何 + 译文 -> 带 cx/dy 的决策 JSON（布局无关的求解），产出过闸门所需数据；正文不写 `sz` |
| `init_translations.py` | 语言表骨架/分批合并/校验：`--init` `--keys` `--merge` `--merge-gloss` `--check`。**只生成结构与校验，不编内容** |
| `export_spans.py` | 源稿 .ai/PDF -> `spans_all.json` + `unique_strings.json`（**全新工程的第一步**，整条链的文本事实都来自它） |
| `preflight.py` | 出决策前的体检：内框/插画/标题/译表覆盖/未解条目，阻断项退 2 |
| `build_width_tables.py` | 源稿 spans + 译文 + 真实字体 -> `width_tables.json`（每词 `MAXW` + 正文折行；不缩字号）；译文或字体变了要重跑 |
| `ledger_export.py` | 决策 JSON → 台账（总览/每语言一页/全语言对照）；**出表前自动回灌**防丢编辑 |
| `ledger_import.py` | 台账 → 决策 JSON；按表头名定位列、幂等、写前备份 |
| `letters_export.py` | 字母对应表 + 特有字母页（A–Z 保留英文时说明词与字母的对应） |
| `qa_prebuild.py` | **出图前闸门**：字形覆盖 / 字宽超槽 / 同排间距 / 页码禁区（含双行块真实高度）/ 漏译 / 标题 / 缩写格 / 正文被改字号（`SZ`）；`--detail` 列明细、`--json` 存结果，阻断项退 1 |
| `qa_output.py` | **出图后复核**：读成品 .ai/.pdf 的真实字形坐标，查页码压字（`PAGENO`）/ 出血（`BLEED`）/ 页数（`COUNT`）/ 标题胶囊（`TITLE-CENTER` 双行块心偏离椭圆心 >`title_center_tol_pt`；`TITLE-POUT` 某行角点越出椭圆 >`title_pout`；`TITLE-TIGHT` 多行块超出 `title_two_fill` 的余量、只在项目把 fill 调到 1 以下时才可能触发；`TITLE-UNREAD` 找到胶囊却没匹配到任何字形路径，**阻断**并提示调 `layout.title_glyph`）。⚠️ 前两项靠 `get_text()`，**成品转曲后文本层为空、整页会被跳过**（这就是"全绿"却漏掉双行偏心的原因），所以标题检查读**矢量路径**：胶囊 = 顶部 `title_pill_w_range`×`title_pill_h_range` 内（默认 100–145×26–46pt）、`y1<title_top_pt` 的填充椭圆，字形 = 其内浅色（`title_glyph="light"`）或深色（`"dark"`）填充路径，按行聚类、以字形底边中位数当基线（下伸字母不计越界）。换版型必须同步这几个键，否则闸门找不到胶囊或字形。`.ai` 是**活文本**（标题是 text frame，胶囊内一个字形路径都没有），这时回退读 span 的基线原点：只判块心（容差 ×2.5，span 框的 ascent/descent 空白不对称，实测偏差 1.5pt 而 PDF 是 0.0），椭圆弧判定只对转曲 PDF 的真实字形路径做。 |
| `rebuild.py` | 指纹增量重建：单本/单语言/全部/`--force`；生成 JSX 后调批处理 |
| `make_jsx.py` | 决策驱动生成纯 ASCII 的 Illustrator JSX |
| `verify.py` | 校验 PDF 页数、活字=0（已转曲）、文件齐全；`--layout` 附加决策意图静态检查 |
| `geometry.jsx.inc` | 通用几何约束片段（纯 ASCII），由 `make_jsx.py` 注入生成的 JSX |

## 版式约束（生成即带上，不必另写）

`make_jsx.py` 会把 `geometry.jsx.inc` 和 `config.geometry` 注入每份 JSX，把卡片的经典版式坑变成**可执行约束**：

- **标题不超椭圆 + 居中**（`title_fit`，默认开）——五条硬约束，缺一条就会复现「同组标题字号不一 / 字压在椭圆上 / 双行不居中」：
  1. **一个标题一个字号，跨页一致**：字号取自源稿该标题的实测字号（`build_decisions` 之外的 `make_jsx.py` 现场从 spans 读），同一 `title_map` key 在所有页面用同一个值。**不要**逐帧按椭圆重算，否则同名字号必然发散。
  2. **必须落在椭圆内**：标题胶囊是真椭圆（4 段贝塞尔），`u=(x/a)²+(y/b)²≤1` 才算放得下；119×34pt 的椭圆在字身高度处只剩约 105pt 可用宽。单行按字身带判定、允许 `g/p` 下伸悬挂，上限 `u≤1`。双行上限同为 `u ≤ title_two_fill`，**默认 1.0：装得下就用源稿字号，只有真溢出才缩**。不要为了「留视觉余量」把它调到 1 以下——`0.9` 每边能多出约 5pt 白边，代价是白丢约 5% 字号（葡语 13.0→12.2pt、意语 15.0→13.4pt），观感是标题变小，而不是更好看；要余量必须显式 opt-in 并接受这个代价。葡语 `Necessidades/diárias` 顶行角点 `u=0.99`、下行 `0.57` 的落差，来自标题本身两行宽度差（43.8pt vs 21pt），块心居中就是正确版式。
     ⚠️ **判据要逐行，不能拿整块包围盒当矩形**：包围盒会把「最宽行的两端」和「最深行的下沿」拼成一个假角——那个角上根本没有墨。按它判：① 太松，首行两端戳出胶囊（14.8pt 时 `Necessidades` 露出深绿）；② 一动就误判，双行块只要下移 2.8pt，包围盒底角 `u` 就从 0.955 涨到 1.18，引擎把本来正确的 13pt 压成 11.5pt。现行实现：`make_jsx._fits()` 按「最宽行的半宽 + 块半高」判定居中的块（块对称，两个外角等价），JSX 的 `centerTitleInPill()` 用 `TITLEW` 传入的**逐行宽度**分别算两行的角点。
  3. **放不下才折两行**：单行缩到源字号 85% 以下才折行；折行用源稿双行标题的字号，再按椭圆收缩。两行必须 **`textRange.paragraphAttributes.justification = CENTER`**（设在 `tf.paragraphAttributes` 上会被静默忽略，两行就左对齐了）。
  4. **居中基准**：单行按字身框（cap 顶→基线）居中，下伸字母允许悬挂；**双行按整块墨迹框居中**（块心对准椭圆心），上下留白相等（实测：意语 15.0pt 上下各 3.2pt、葡语 13.0pt 上下各 5.7pt，块心偏移 0.0pt）。
     ⚠️ **不许用「下移」补横向余量**：把两行的椭圆利用率拉平（`title_two_balance=1`）确实能让顶行的角点从 0.99 退到 0.79，但块心随之落到胶囊中心以下 —— 上留白 8.4pt、下留白 2.9pt，看着像「整块掉进胶囊」而不是居中。块心居中就是终态：两行宽度不等时，窄的那行离弧更远是正常的。`title_two_balance` 默认 0。
  5. **译文自带换行也算双行**：`"Daily\rNecessities": "Necessidades\rdiárias"` 这种，`two` 必须从**内容**判断（`TITLE[key].indexOf("\r")>=0`），不能只看「本轮代码有没有折行」。只看代码会把双行当单行、只居中首行 cap 带，整块下沉（实测上留白 13.2pt / 下留白 1.4pt）；量宽也必须**逐行取最大值**，把两行拼成一行量会把 15.6pt 算成 11.3pt。
- **折行落位优先级**：内移（±`shift_cap_pt`）→ **大内移**（±`relax_shift_pt`，仍限本列）→ 折行 → 短译。折行时先吃文字净空 `room`（只抬文字）；文字抬不动、且该标签在**底排**（`illok`）时，才把自己的插图一起抬（`illdy`），上限 = 该排所有插画上方净空 `ceil` 的最小值。同排其它格只跟随文字平移（`rowdy`），插图不动——所以整排的图永远在同一水平线上。台账模式列会标 `·整排↑x`。
- **页面事实只在一处算**：`geomlib._attach_facts()` 产出每标签的 `row / ill / room / illok / ceil`，决策层只读不算。缺内框或缺插画占比过高会直接 `REFUSED`（不再静默跳页）。
- **`layout.wrap_clear_pt`（默认 1.0）**：折行块与下方障碍/插画的净空。2mm 的一般 cushion 会把只差几 pt 的双行全部否决——源稿设计本身就只留 1–2pt。`violations()` 的 IL/PN 下限同步用它。
- **mode=wrap 必须 `\r`**：写回自愈 + 回读硬校验，不一致 `REFUSED`（曾两次出现换行符丢失，164pt 单行出图）。
- **终态审计**：决策层修不动的标签以前静默出图；`violations` 结果记回 state 并打印，剩几条、在哪一目了然。
- **出决策前先跑 `preflight.py`**：页数/标签数/底排数/行分布、译表覆盖、上次决策的未解条目，一屏看清；有阻断项退 2。
- **标题必须落在页顶标题带**（`geometry_export.title_band_ratio`，默认 0.25）：只看盒子尺寸/字号会把日历格子、徽章这类"同形状"的组误判成标题（实测真标题全在卡片高度 0.87 处，误判的在 0.24/0.60）。带外一律不判 T，另对"一页多 T"报警。
- **正文限宽**（`layout` + `width_tables.json`）：`build_width_tables.py` 用源稿 spans + 译文 + 真实字体量出每个词的 `MAXW`（可用墨迹宽）和折行后的译文，`make_jsx.py` 注入并逐词执行。**没有这张表时正文长词会直接冲出卡片**。表里只做「折/不折」的判断，**不做字号缩放**——放不下的词在 `overflow` 里列出来，由人换词。
- **墨迹对齐**（`ink_bounds_words`）：开则复制文字→转曲→量真墨迹框（不含字体留白）再定位，比 `visibleBounds` 准但稍慢；默认关以保持速度。标题始终用 inkBounds。
- **双行行距**：含软回车的框设 `autoLeading=false`、leading=`max(cap×字号+gap, 0.94×字号+1)`——0.94em 是 typo 行高，低于它下行会碰上行；单行沿用 `lead_at_18×(字号/18)`。
- **正文字号是固定的，只有标题可改大小**：正文放不下时按「换更贴切的词 → 折两行 → 邻格/整体让位 → `PN-TIGHT`/`manual` 交人工」处理，**不得**缩字号。所以决策里不要给正文写 `sz`、不要配 `tuning.sizefix`，求解器也没有自动缩号这一档。一版卡片正文统一 18pt，个别词变成 16.9pt 一眼就能看出来。
  这条现在有四道闸：`build_decisions` 不写 `sz`；`make_jsx` 见到 `sz` 退 3 并中止整批；`qa_prebuild` 的 `SZ` 列出图前再拦；JSX 运行时（`GEO.absz=false`）一律沿用文本框原字号，决策里即便残留 `sz` 也只记 `BODY-SZ-IGNORED`。台账「字号」列是只读灰底（`ledger_import` 不再回写 `sz`，改了也只会打印一行 `ignored`）。
- **译表里的 `\r` 是人工指定的换行，求解器必须保留**：早期求解释放冲突的第一步是 `val.replace('\r',' ')`，把人工分好的两行拍平回一行——一条 148pt 的长词于是被塞回 135pt 的列，只能靠左右移位硬挤，最后离邻居 3pt。现在带 `\r` 的译文原样保留断行、只重新居中。
- **页码是右侧禁区，不只是下方障碍**（`layout.pageno_gap_pt` 默认 10.5；`pageno_shift_cap_pt` 默认 16）：角上的页码由模板绘制、不进译表，所以任何「标签对标签」的检查都看不见它。`build_decisions` 现在对**同一行**的每个标签算 `右端 ≤ 页码左端 − pageno_gap`，不够就左移（上限 shift_cap，并避让左邻居），移不动打 `PN-TIGHT` 让人换短词。实测一版卡片 `accovacciarsi` 右端距页码仅 4.8pt、`cavolo riccio` 仅 1.1pt——印出来就是压字。
- **文本与插画不相交**（`obstacle_gap` + `obstacle_nudge_cap`）：决策 JSON 可在 `"obstacles": {"<画板>": [[x0,y0,x1,y1],...]}` 给插图框（与 visibleBounds 同坐标系，top>y>bottom）。默认 `ocap=0` **只告警不移动**；决策引擎已做过避让就保持 0，手工搭决策才调大让它上移。
- **按画板取决策**（`boardOf`）：同一英文 key 可能出现在多页（`tree`、`rainbow`），出图时必须先用文字框中心算出它属于哪个画板，只取该画板的 `cx`；否则会拿别页的坐标，把词拖到另一页的插图上。

⚠️ 红框：`unlockAll` **只解锁 `locked`，绝不设 `visible=true`/`hidden=false`**——显示源稿隐藏对象会带出裁切标记，转曲后成红黑线框。`scripts/outline_export_template.jsx` 和 `references/illustrator-automation.md` 已按此修正。

## 编码进脚本的关键经验（勿删）

- **出表前先回灌**：目标台账已存在时，`ledger_export` 先跑 import 再覆盖，`XL_NO_SYNC=1` 可跳过。
- **按表头名定位列**：加列、调列顺序都不破坏回灌；主键用稳定 ID。
- **`\r`↔`\n` 归一化**：xlsx 把软回车存成 `\n`，不归一化会误判「全表都改了」。
- **签名只排脚本，不排规则**：指纹算决策文件 + 源稿 + `width_tables.json` 的 size/mtime，**外加** `geometry/layout/gate/decision_engine/languages/default_font` 六个配置段的哈希。改脚本不误触发全量（故意重做加 `--force`），但改一个 `title_two_fill`、椭圆边距或字体**必须**让书失效——否则 `rebuild.py all` 全报 SKIP(unchanged)，新规则永远进不了成品。升级到这一版后首次 rebuild 会全量重建一次，因为指纹口径变了。
- **不可翻译的模板元素也是版面**：页码、角标、水印不进译表，因此不会被任何词表或标签碰撞检查覆盖。凡是模板画的固定元素，都要单独当障碍物建模——页码已内置，其它角标用决策 JSON 的 `obstacles` 传。
- **体检要量「决策实际要排的字」，不是字宽表里的全称**：`qa_prebuild` 的 FIT 曾用 `width_tables.overflow` 的 `need_scale`，而那张表在求解前生成、记的是长全称。求解器选了短译（`коляска` 而非 `инвалидная коляска`）后，检查器仍按全称判「放不下」，凭空报出 2 条超宽——照着改会把正确译文改坏。现在按决策里的 `val` 与 `width_tables.slot[key].maxw` 现场算。
- **检查必须在出图前**：`rebuild.py` 一次出一整本（几分钟到十几分钟），「先出图再抽检」会把每个可静态计算的缺陷都变成一次全量重出。能算的（字宽、间距、字形覆盖）一律先用 `qa_prebuild.py` 算完再出图，出图后只用 `qa_output.py` 做实物复核。
- **work 目录别放名字含 `decision` 的其它 JSON**：`build_width_tables.py` 只认 `v7_dec_<lang>_<color>.json`（已按文件名结构过滤并跳过其它文件），但历史版本会把它当决策解析并 IndexError；调优文件建议命名 `posfix.json`。
- **`rebuild.py` 选择器**：`all` / `<lang>` / `<color>` / `<lang>:<color>` / `<lang>_<color>` / 逗号分隔均可用；旧版按前两个字符切分会把 `it:orange` 静默解析成无效组合后照常退 0。
- **看产物 mtime 判成功**：不信任批处理控制台的 stdout（非 UTF-8 会乱码）。
- **语言表的键必须派生，不能手敲**：`init_translations.py --init` 把 `spans` 与 `geom`（复合两行词只存在于几何里）的文本并起来做键，实测从旧表查出 **21 个死键**（`ear/eye/trousers/soup/sushi/swimming pool…` 源稿里根本没有），同时补齐 84 条缺失的中文。`--merge` 拒绝未知键，写错一个字母就被挡住，不会静默变成英文。
- **三道静默失败守卫**（都由"删掉 work 从零重跑"暴露出来的）：①译表覆盖不足 → `build_decisions.py` 直接 REFUSED（缺词条时 `tr()` 会静默回退英文，PDF 照样过 `verify.py`）；②缺 `spans_all.json` → `make_jsx.py` 退出码 3（旧行为是给所有标题兜底 22pt，绿本 15.8/橙本 14.7 会被放大）；③缺 spans 的 `build_width_tables.py` 给可执行的修复提示而不是 traceback。
- **joblist 写绝对路径 + 读时 `-Encoding UTF8`**：runner 的 `$root` 是脚本目录（`<skill>/scripts`），相对项会在那里找（永远 MISSING）；PS 5.1 的 `Get-Content` 默认按 ANSI 解码，工程路径含中文时整行变乱码。两处都修过，别回退。
- **`<脚本>.log` 是硬契约**：runner 只认 `ChangeExtension(jsx,'.log')`，日志写别处就会被判「no log output」→ 每本重试 2 次、汇总成 FAIL，而产物其实是对的。
- **JSX 纯 ASCII**：所有非 ASCII 经 `js()` 转 `\uXXXX`；注释全英文，否则 `DoJavaScriptFile` 报 "code was missing"。
- **PDF 兼容层默认开**：`pdfCompatible=true`，正常交付不得关闭。
- **关文件后等 2 秒**：由 `../scripts/run_batch.ps1` 的 `-WaitMs 2000` 保证，别调小。

更完整的踩坑与大批量方法论见 `../references/batch-pipeline.md`。
