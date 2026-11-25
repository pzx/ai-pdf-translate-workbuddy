---
name: ai-pdf-translate-workbuddy
description: 替换 .ai / PDF 卡片与印刷文件中的文字并保留原版式，输出原生 .ai、转曲矢量 PDF 和多语言 XLSX 台账。适用：把英文单词改成中文/法语/西班牙语等其他语言、点读认知卡片翻译、整套卡片批量翻译、多配色×多语言大批量交付、xlsx 审校回灌与按词增量重建、改 PDF 或 Illustrator 文件上的文字、按图文对应翻译保留原字体字号颜色位置。触发词：翻译卡片、改 ai 文件文字、pdf 英文换中文、点读卡片、批量翻译 50 张、AI 文件改语言、转曲、翻译台账审校、只重建受影响文件、整套卡片先出表审校再回灌、葡萄牙语巴西还是欧洲、西语变体、开工前确认语言。只做文字替换，不做整页重设计。
---

# AI/PDF 卡片文字翻译替换

## 第零步：开工前强制确认（AskUserQuestion）——不得跳过

**任何翻译/替换任务，动手前必须先向用户确认下面的歧义项；一项没确认就不写文件、不出产物。**
这些选项**不存放在技能里**（技能是通用工具箱），每次任务由用户当场决定，用提问卡（AskUserQuestion）
一次性问清再开工。以前有过"直接生成、事后返工"的教训：葡语变体选错、字母页约定没对齐，
都会导致整批返工。

**必问清单（按任务相关性取用，能并成一张卡就并成一张）：**

1. **目标语言及地区变体**（最高优先，直接影响译法）：
   - **葡萄牙语**必须问「巴西葡语(pt-BR) / 欧洲葡语(pt-PT)」——公交 ônibus/autocarro、
     果汁、地铁等大量词不同。**两者可以都要**（当作两种语言分别出本），但要让用户明确。
   - **西班牙语**若有，问「欧洲西语(es-ES) / 拉美西语(es-MX 等)」——公交车 autobús/camion、
     手机 móvil/celular 等不同。
   - 英语若有，问「美式 / 英式」（colour/color 等）；法语若涉及加拿大，问「法国 / 加拿大」；
     中文若有，问「简体 / 繁体」。
   - 其余语言（意/俄/德/日等）无常见地区分歧，按标准语言处理即可，不必单独问。
2. **输出形式**：可编辑 `.ai` + 转曲 `.pdf` + 台账 xlsx（正式交付）？还是只要预览 PDF？
   有 Illustrator 才有可编辑 .ai 和真转曲，无 AI 只能活字 PDF——环境限制要一并说清。
3. **字母页策略**（字母认知卡专用）：译文首字母可能与 A–Z 不再对应（A=apple→A=pomme），
   是"照常翻译词条、保留原字母插画，另出字母对应表"，还是要求字母与首字母一致（需连插图一起换，
   本技能不做重绘）。默认前者，但要让用户确认接受。
4. **词表/译文确认**：数量大或有人工词条表时，先出翻译对照 xlsx 给用户过目再批量执行。
5. **范围/缺漏**：源稿数量与"全部翻译"字面数不符时（如说 4 个文件但只齐 11/16 本），
   列出缺哪些、问是否补齐，不要自行假设。

**提问卡模板**（合并成一张多问题卡，避免连环打扰）：

```
question: "目标语言及地区变体？葡语/西语等有地区分歧的语言会决定大量词汇译法。"
header: "语言变体"
options: [巴西葡语+欧洲葡语都要(推荐) / 仅巴西葡语 / 仅欧洲葡语 / 其它语言组合...]

question: "输出形式？（本机有/无 Illustrator 决定能否出可编辑 .ai 与真转曲）"
header: "输出"
options: [可编辑.ai+转曲.pdf+台账(推荐) / 仅PDF预览 / ...]

question: "字母页译文首字母与 A-Z 不再对应，如何处理？"
header: "字母页"
options: [照常翻译词条+另出字母对应表(推荐) / 只翻非字母页 / ...]
```

确认后把结果写进 `pipeline.json` 的 `languages` 表（code/name/font），再进入下面的第一步。
用户明确说"按你说的来/默认"时，按上面标"（推荐）"项执行，并在交付说明里注明所用变体。

---

先分析后动手。**第一步固定查 Illustrator**：`python scripts/check_illustrator.py`
（注册表 ProgID，不启动应用，退出码 0=已安装）。

**第二步判定「转曲与否」（和文件类型同等重要，二维路由）**：
`python scripts/analyze_file.py <file>`
- **未转曲** = 能提取活文本 span（.ai 的 PDF 兼容流同样能读）；
- **已转曲** = 无文本但有矢量字形路径（`get_drawings()` 路径数≈字母数，见路线 D 判定坑）；
- 无文本也无矢量字形 = 文字烧进位图 → 路线 A。

⚠️ **不要只看文件类型选路线**：未转曲的 PDF 转成 .ai 后是**活 textFrames**，必须走标准替换；
已转曲的 .ai **没有 textFrames**，必须走转曲模板（删字形路径+重建文本框）。两条模板用错 = 原文残留或纹丝不动。

**大批量任务（多配色×多语言、十几本以上、要人工审校/增量修订）——强制流程，不得跳过直接出结果**：
1. 先读 references/batch-pipeline.md 与 pipeline/README.md。
2. 复制 `pipeline/config.example.json` → `pipeline.json`，填语言表/配色表/命名模板/决策字段。
3. 用 `pipeline/` 脚本跑闭环，而不是直接生成结果：
   `export_spans.py`（源稿抽文本→标题字号/字宽/字母表的唯一来源）→
   `init_translations.py --init`（语言表键从源稿派生，别手敲；`--merge` 回填、`--check` 审计）→
   `preflight.py`（体检：内框/插画/标题/译表覆盖，阻断项退 2）→ `build_width_tables.py`（量字宽→正文限宽/折行表）→ `build_decisions.py`（产出带 cx 的决策）→ `qa_prebuild.py`（出图前闸门，阻断项退 1）→ `ledger_export.py`（出表）→ 人工审校 xlsx →
   `ledger_import.py`（回灌）→ `rebuild.py`（指纹增量重建）→ `verify.py` + `qa_output.py`（校验/成品复核）；字母页卡片再跑 `letters_export.py`。
   决策 JSON 是唯一真相源、xlsx 只是视图；只改表不回灌会被指纹判为「没变」而跳过。
   稳定性要点：关文件后等 2 秒、不要分段重启、不关 PDF 兼容层（细节见 batch-pipeline.md 第 6 / 12 节）。
4. **清空 work/output 重跑（换机、换版型、从零验证）前，先看 batch-pipeline.md 12.11**：非 ASCII 工程路径、
   joblist 绝对路径、`<脚本>.log` 日志命名、`export_geometry.py all` 语义、标题带 `title_band_ratio`，
   这 5 处任一没对齐，症状都是"全部 MISSING / 0 color(s) / 每本重试两次"，而产物其实可能已经对了。
5. **同一英文串在同一页承担两种角色**（缩写格 + 全名，如日历的 `May`）：不要手工改译表硬凑，
   在 `translations` 里给该词条加 `"<lang>_abbr"`，流水线会自动生成 `"<英文>#abbr"` 决策并用字号匹配，
   台账里以「（缩写格）」单列一行。

```
check_illustrator.py + analyze_file.py
        │
        ├─ 【未转曲（有活文本 span）】
        │     ├─ 输入 .ai                       → 路线 C **标准模板**（textFrames 原位换文字）
        │     │     （未装 AI 则无法处理 .ai，如实报错）
        │     ├─ 输入 .pdf + 已装 Illustrator   → 先转 base.ai 再走路线 C **标准模板**
        │     │     （转出来的 .ai 是活 textFrames，不是转曲源！不要用转曲模板的删路径逻辑）
        │     └─ 输入 .pdf + 未装 Illustrator   → 路线 B（PyMuPDF 矢量替换，**不转曲**）
        │
        ├─ 【已转曲（矢量字形，无活文本）】
        │     ├─ 输入 .ai + 已装 Illustrator    → 路线 C **转曲模板**（删字形路径+建译文文本框），
        │     │     **CONVERT=false：直接拿源 .ai 当 base，不要再做 PDF→AI 转换**
        │     ├─ 输入 .ai + 未装 Illustrator    → 路线 D 操作其 PDF 兼容流出矢量 PDF（**出不了真 .ai**，
        │     │     台账/交付说明注明）；用户要 .ai 必须装 Illustrator
        │     ├─ 输入 .pdf + 已装 Illustrator   → 转 base.ai → 路线 C **转曲模板**
        │     └─ 输入 .pdf + 未装 Illustrator   → 路线 D（矢量 redact+插入，**不转曲**）
        │
        └─ 文字烧进位图                    → 路线 A（OCR 定位 + inpaint 擦除重绘）
```

## 输出组织与命名（硬规则）

- **目录按输入类型分**：`.ai` 输入 → 最终输出全部放 `output/ai/`；`.pdf` 输入 → 全部放 `output/pdf/`
  （即使走了 AI 流程转成 .ai 处理，输出目录仍按**输入**类型）。
- **交付物**：
  - `.ai` 输入：每语言 `源名_语言.ai`（可编辑文字）+ `源名_语言.pdf`（**全文本转曲**）+ 全源文件唯一一份台账 xlsx
  - `.pdf` 输入 + 有 Illustrator：同 .ai 输入（每语言 .ai + 转曲 .pdf + 唯一台账），放 `output/pdf/`
  - `.pdf` 输入 + 无 Illustrator：每语言 `源名_语言.pdf`（活文字矢量 PDF，**不转曲**）+ 唯一台账 xlsx
- **命名**：`源文件名_语言_YYYYMMDD.扩展名`（**不含 ai/pdf 类型段**）；台账 `源文件名_翻译_YYYYMMDD.xlsx`。
  日期为 8 位当天日期（如 20261117）。同一文件多语言只差语言段；台账每源文件仅一份、各目标语言一列。
- **默认字体**：原文件字体无法确定（转曲/位图源）时，一律用 **Arial Rounded MT Bold**
  （Windows: `C:\Windows\Fonts\ARLRDBD.TTF`）；用户主动指定字体时以用户为准，并在台账字体列注明来源。
  CJK 语言无对应字形时按字体回退链（思源黑体/微软雅黑 Bold），同样记入台账。

## 路线 B：PyMuPDF 矢量替换（快速预览）

1. 写 mapping.json（按 span 全文精确匹配）
2. `python scripts/translate_vector.py src.pdf out.pdf --map mapping.json --font <覆盖目标语言的ttf> --png 3`
   - redact 只删文字（IMAGE_NONE / LINE_ART_NONE），新词按原 bbox 中心居中、原字号原色写入
3. ViewImage 验收

⚠️ 只改 PDF 层：源若是 .ai，AIPrivateData 里仍是英文，Illustrator 打开显示旧文字。正式交付走路线 C。

## 路线 C：Illustrator 原生（正式交付首选）

1. 复制 `scripts/translate_native_template.jsx`，填 SRC/OUT/LOG/MAP（特殊字符 \uXXXX；批量填 BATCH_DIR）
2. 执行：`powershell -File scripts/run_jsx.ps1 <jsx> <log.txt>`；被 COM 拦截时见
   references/illustrator-automation.md（补丁重打 / VBS 双击兜底）
3. 验证真原生：解包 AIPrivateData，原生文本层应为目标语言、源语言零残留（方法见 references）
4. **转曲 PDF**：`.ai` 已 saveAs（可编辑）后，**同一文档内**遍历全部 textFrames `createOutline()`
   （倒序遍历，collection 会变）再 `saveAs .pdf`，close(DONOTSAVECHANGES)——.ai 文件保持可编辑。
   单文件也可用 `scripts/outline_export_template.jsx`；用 `scripts/verify_outlined_pdf.py` 验收
   （无残留文字、无字体资源、页数尺寸一致）。
   ⚠️ **解锁只碰 `locked`，绝不设 `visible=true` / `hidden=false`**——显示源稿隐藏对象会带出裁切辅助标记，
   转曲后变成红黑线框（已踩过坑，用户不允许出现）。
   **版式硬约束**：标题必须留在真椭圆内并光学居中、正文墨迹居中、双行设固定行距、译文不压插图——
   大批量走 `pipeline/` 时由 `geometry.jsx.inc` 自动注入（见 pipeline/README.md「版式约束」）；
   单文件走模板时需按第 6/7 步手工落实 MAXW、居中、行距、椭圆适配，不可省。
   ⚠️ **标题字号**：同一标题跨页必须同一字号，且取自源稿该标题的实测字号；
   放不下时按椭圆 `(x/a)²+(y/b)²≤1` 收缩（单行只按字身带判、允许下伸悬挂），
   缩到源字号 85% 以下才折两行，两行用源稿双行字号且必须 `textRange.paragraphAttributes.justification=CENTER`
   （设在 `tf.paragraphAttributes` 上会被静默忽略）。详见 batch-pipeline.md 12.6。
   ⚠️ **双行标题按块心居中，不为留余量缩字号**：整块（两行合起来的墨迹框）的块心对准胶囊椭圆心。
   **`title_two_fill` 默认 1.0**——装得下就用源稿字号，只有真的溢出椭圆才缩；收到 0.9 能换来每边约 5pt 白边，
   代价是白丢约 5% 字号（葡语 13.0→12.2pt），观感是「标题变小了」而不是「更好看」，所以要显式 opt-in。
   上行宽、下行窄时下行离弧更远（实测葡语顶行角点 `u=0.99`、下行 `0.57`），这是标题本身行宽不等造成的，
   块心居中就是正确版式；**不许用下移去拉平**（见坑④）。
   四个坑：①**译文自带 `\r` 也算双行**——`two` 要从内容判断，只看"本轮代码有没有折行"会把双行当单行、
   只居中首行 cap 带，整块下沉（实测上 13.2 / 下 1.4pt）；②**逐行量宽取最大**，把两行拼成一行量会把
   15.6pt 算成 11.3pt；③**判据要逐行，不能拿整块包围盒当矩形**——包围盒把「最宽行的两端」和「最深行的下沿」
   拼成一个角上无墨的假角，既会把首行两端放出去，也会在块稍一下移时把正确的 13pt 压到 11.5pt；
   ④**不许用下移补横向余量**——下移能把两行角点拉平（0.99→0.79），但块心掉到胶囊中心以下
   （上 8.4 / 下 2.9pt），像「整块沉下去」；`title_two_balance` 默认 0。
   出图后 `qa_output.py` 的 `TITLE-CENTER` / `TITLE-POUT` / `TITLE-TIGHT` 会按矢量路径复核
   （转曲后 `get_text()` 为空，文本类检查整页跳过，必须用路径判）。
   ⚠️ **只有标题可以改字号，正文标签一律不许缩**（用户明确要求，属硬约束，已做成三道闸）：
   正文放不下时只允许「换更贴切的词 → 折两行 → 让邻格/整体让位 → 报 `PN-TIGHT`/`manual` 交人工」，
   **禁止**为了塞进槽位把正文字号调小（决策里不要给正文写 `sz`、不要配 `sizefix`、更不要做自动缩号兜底）。
   一部卡片的正文是同一种字号，个别词变小会立刻被看出来。同理折行要满足两行净空，
   差 1pt 也不行——宁可交人工换词，不要硬塞。
   闸门位置：① `build_decisions.py` 不写正文 `sz`（`sizefix` 被忽略，除非 `gate.allow_body_sz`）；
   ② `make_jsx.py` 见到任何正文 `sz` 直接退 3，`rebuild.py` 整批中止；
   ③ `qa_prebuild.py` 的 `SZ` 列出图前再拦一次。台账的「字号」列因此是只读灰底。
   ⚠️ **译表里的 `\r` 是人工指定的换行**：求解器遇到带 `\r` 的译文必须保留断行去重新居中，
   不能再拍平成单行（拍平会把 148pt 的长词塞回只有 135pt 的列，然后靠移位硬挤邻居）。
   ⚠️ **决策闸门（pipeline 强制）**：决策条目必须带 `cx`（从源稿量出的目标水平中心），否则
   `make_jsx.py` 报错退出、`rebuild.py` 中止整批。`cx=null` 会让 JSX 静默跳过居中，每个词偏离插图。
   `sz` **只对标题有意义，正文一律不写**：标题字号由 `make_jsx` 按源稿实测 + 椭圆适配算，
   不读决策里的 `sz`；正文写了会被闸门拒绝（见上一条）。`gate.require_sz` 仅供
   `allow_body_sz=true` 的特殊版式使用。
   **换新源稿/换排版后，按 `pipeline/README.md`「换版型闭环」重建决策**：
   `export_geometry.py`（导出几何，门限在 `config.geometry_export` 可调）→
   `build_decisions.py`（几何+译文产出带 `cx` 的决策）→
   `build_width_tables.py`（量字宽，产出正文限宽/折行表）→ `qa_prebuild.py`（出图前闸门）→ 台账审校回灌 → `rebuild.py` → `qa_output.py`。
   闸门只挡住不完整数据，不负责生成它；缺 `cx` 时先跑这两个引擎，不要直接出图。
5. **台账**（轻量版，适合中小批量）：`python scripts/make_translation_xlsx.py src.ai output --lang fr --map fr.json`
   ——xlsx 目录参数传 `output` 即按输入类型自动路由到 `output/ai/`（pdf 源→`output/pdf/`），
   自动命名 `源名_翻译_YYYYMMDD.xlsx`；每个文字对象一行、每种语言一列，再翻新语言对同一张表跑即可。
   多配色×多语言、需审校/增量修订的整套交付改用开头强制流程的 `pipeline/` 决策驱动台账，两套不通用。

**路线 C 有两套模板，按「转曲与否」选，不按文件类型选**：

6. **标准模板 `translate_native_template.jsx`**（源未转曲、有活 textFrames）：
   适用于未转曲 .ai 直接输入、**以及未转曲 PDF 转 base.ai 之后**（转出来的 textFrames 是活的）。
   在原 textFrame 里原位替换 contents，字体/字号/颜色/位置天然复刻，最简单可靠。
   **防溢出 = 只缩标题（硬性）**：替换后实测 `visibleBounds` 墨迹宽，`MAXW[key]` 只对
   **标题**生效（模板里 `TITLE_MINSZ`，默认 19pt；低于它的正文只记 `BODY-OVERFLOW`，字号不动）。
   标题缩字号时迭代两轮、每轮以当前字号为基数，缩完后**必须把墨迹垂直中心回补到原文字的
   墨迹垂直中心**——缩字号以基线为锚向上收缩，不回补则缩得越多越偏下（德语 Buchstaben
   缩到 16.4pt 后明显偏下，回补后与原 Letters 墨迹中心差 0.3pt）。MAXW 必须先从源文件
   几何实测：硬容器（胶囊/按钮）= 容器宽 − 两侧边距；开放区域 = 词带内到邻近插画的
   对称可用宽。实测教训：德语 Buchstaben（23pt 时宽 119pt）溢出 95pt 宽胶囊 → 缩到
   16.4pt 后居中完好；不要假设"标题一般放得下"——逐语言渲染验收标题墨迹完全在容器内
   且垂直居中。
   **正文超宽的正确处理是改词/折行/让位，不是缩字号**（见下面「只有标题可以改字号」）；
   模板只报 BODY-OVERFLOW 交人工，绝不静默缩。
   **不要**对未转曲源用删路径逻辑——活文本没有字形路径可删，原文会残留。
7. **转曲模板 `pdf_to_ai_translate_template.jsx`**（源已转曲、无活文本、字形是矢量路径）：
   适用于转曲 PDF 转 base.ai 之后、**以及转曲 .ai 直接输入（CONVERT=false，源即 base，
   跳过 PDF→AI 转换步骤）**。递归收集 pageItems（GroupItem 要深入），只删
   `PathItem`/`CompoundPathItem`（**绝不碰 RasterItem/PlacedItem**），bounds 完全落入
   字形区域（±2.5pt）即删；再 `doc.textFrames.add()` 建译文文本框：
   字体用 `findFont` 遍历 name 匹配（**itemByName 对字体全部抛 No such element，不可用**）；
   **定位用基线对齐，绝不用行框（geometricBounds）中心**——CJK 字体行框比拉丁高很多且
   墨迹在行框内偏上，按行框居中会把日语等译文压低十几 pt，墨迹中心对齐也会与基线行为差
   3~7pt。正确做法：① 驱动端用 fontTools 从字体轮廓算译文墨迹低于基线的距离 `below`，
   原基线取原字形路径底边**最小值**（众数会被降部字母骗，如 egg 两个 g）；② JSX 里复制一份
   译文转曲量实测墨迹 bbox，`墨迹底 + below = 实际基线`，平移使基线落在目标基线上——
   与"AI 输入保留原基线"的行为完全一致（PDF 路线和 AI 路线输出位置就一致了）；
   maxw 超宽只记录不缩字号（正文禁缩；标题走椭圆适配）。颜色/字号/透明度复刻原文操作符。
   生成驱动脚本时：转曲 .ai 输入 → CONVERT=false；转曲 .pdf 输入 → 先转 base.ai。
8. **PDF → AI 转换**（仅当源是 .pdf 且走 AI 流程时）：`app.open(new File(src.pdf))` →
   `saveAs` 一个 base `.ai`（IllustratorSaveOptions，pdfCompatible=true）→ close。
   每语言从 base.ai 打开处理，base 不重复转换。
   PDF 导入可能弹对话框，先设 `app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS`。
9. **两大坐标/颜色坑**：
   - 坐标系：AI 打开 PDF 后 DOCUMENT 坐标系原点在**左下、y 向上**，`geometricBounds = [left, top,
     right, bottom]` 且 top > bottom。pymupdf 的 pt 坐标（y 从页顶向下）要换算：
     `ai_top = H - pdf_y_top`，`ai_bottom = H - pdf_y_bottom`（H=页高）。
   - **CMYKColor 取值是 0–100 百分比，不是 0–1！** `black=1` 只是 1% 黑（≈白）——纯黑必须
     `black=100`。白 = 四值全 0。原文带透明度状态（如 GS ca=0.9）时文本框 `opacity = 90` 复刻。
10. 验收：渲染对比原版——文字区外像素差异 0、词墨迹模态色应与原版**逐位一致**（AI 原生 CMYK，
   无任何转换偏差）、标题墨迹高与原版一致；转曲后 `get_text()` 为空。

## 路线 D：已转曲矢量 PDF

**仅在本机无 Illustrator 时使用**（有 AI 一律走路线 C，保证色彩/字号与原版完全一致且出可编辑 .ai）。

**判定坑：`get_text()` 提取不到文字 ≠ 位图文字。** 先 `page.get_drawings()` 查矢量路径——
路径数与字母数吻合、按填色聚类（深色=词、白=反白标题）即是转曲字形，走本路线（优先级高于路线 A）。
矢量路线全程无栅格补丁：原图片/背景像素级零改动，不存在 CMYK→RGB 色差接缝（淡框）问题。

一步式脚本：`python scripts/vector_redact_insert.py src.pdf out.pdf --items items.json`
（items.json：rect 为 PDF pt 坐标的原字形并集 bbox、text、fontfile、fontsize、color、max_width）

1. 原字形并集 bbox 用 `get_drawings()` 按填色+区域聚类实测，不用估算
2. 脚本内部：`add_redact_annot(rect 外扩 ~1.5pt)` + `apply_redactions(
   images=PDF_REDACT_IMAGE_NONE, graphics=PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
   text=PDF_REDACT_TEXT_NONE)`——只删被完全覆盖的字形路径，大背景/插画保留；**不得用背景色矩形覆盖**
3. 字体按 references/font-matching.md 视觉匹配（分组识别、样张对比、置信度入台账）
4. 译文 `page.insert_font(fontname=alias, fontfile=...)` 后插入；**基线用 PIL getbbox 实测墨迹
   居中**（CJK/拉丁/西里尔都精确，勿用 ascender 猜测——符号错一次文字整体偏十几 pt）
5. **变量字体（VF）坑**：pymupdf `Font(fontfile=VF.ttf)` 加载的是默认实例（如 NotoSansSC-Thin），
   字重会错。先用 fontTools instancer 按 wght 实例化成静态 ttf（同步改 name 表）再喂给 pymupdf/PIL
6. **CMYK 色彩保真（颜色不一致的头号根因）**：原文件多为 CMYK。绝不能用 `get_drawings()` 报告的
   RGB 值插译文（那是朴素换算，与 ICC 实际渲染差 ~30/255）。正确做法：读内容流找原文填充算子
   （词多为 `0 0 0 1 k` 纯 K 黑、反白标题 `0 0 0 0 k`），items 里指定 `"cmyk": [C,M,Y,K]`，
   脚本会把插入流的 rg/RG 改写成 k/K；原文若带 ExtGState（如 GS1 ca=0.9，Form 上常见），用
   `"gs": "/GS1"` 一并复刻——**复刻源操作符**即可保证渲染/印刷走同一条路径，颜色必然一致。
   验收：渲染后文字模态色与原版应逐位一致（±1 为 Illustrator 回写容差）
7. 验收：核验输出 span 实际字体名与字号；渲染对比原版，文字区 ±25pt 外像素差异应为 0；
   新旧墨迹中心差 ≤1pt；ViewImage 目检无残留字形、无色块；**标题字号保持原字号，
   max_width 设为容器（胶囊/板）内宽而非原文字宽，避免无谓收缩**
8. **不做转曲**：无 AI 无法转曲，输出保持活文字矢量 PDF，台账注明"未转曲（本机无 Illustrator）"，日后装了 AI 应改走路线 C 重出。
9. **台账**：转曲源提取不到文字对象，用 `--seed` 传人工核对的对象清单
   （[{page,text,size},...]，font 缺省即默认 Arial Rounded MT Bold），状态列标"转曲-重建"

## 路线 A：位图擦除重绘（文字烧进图片）

1. `analyze_file.py <file> --render 3`；ViewImage 记录样式与背景
2. `detect_text_boxes.py` 出候选包围盒，人工核对
3. 写 items.json（box/text/color/mask_color），`raster_erase_redraw.py`
   擦除（**inpaint 修复，禁止纯色填充**——渐变底上必留色块）+ 居中重绘 + 回包同尺寸 PDF
4. ViewImage 验收（**每次换新输出文件名，同名覆盖会命中预览缓存**）

细节与坑见 references/raster-route.md。台账中此类文字标记"重建-OCR"。

## 通用规则

- **替换表先给用户过目**再执行；同页同词可因语境不同译（台账按对象编号区分，不按字串合并）。
- **R1 字体名候选（通用）**：Illustrator 认的字体名可能 ≠ 系统配置里的 family+style 名（字体已装但只暴露 PostScript 名）。批量流水线从 `font_file` 读全部名字（family/full/PostScript/本地化名）逐个试，全落空记 `FONT-MISS`，绝不静默留源稿字体。无需项目配置。
- **R2 转曲文字（需项目声明）**：被 outline 成矢量路径、无文字层的标签不会被 `export_spans` 提取。在 `pipeline.json` 顶层 `vector_text` 声明其 bbox（Illustrator 展开坐标），`replaceVectorText()` 按 bbox 找到并 `remove()` 掉包装它的 group，再从同画板复制一个正文标签框填译文原位。匹配容差与模板字号范围由 `vector_text_engine` 配置（`center_tol_pt` / `size_tol_pt` / `template_size_min_pt` / `template_size_max_pt`，默认 3.0 / 4.0 / 16.5 / 19.5，按项目正文字号调整）。**平台坑**：①绝不遍历 `doc.pageItems`（对象多时 Illustrator 卡死），用 `groupItems` 按 bbox 匹配；②别用纯色矩形覆盖渐变背景；③duplicate 后只有 `tf.position=[x,y]` 定位可靠（`geometricBounds`/`duplicate(matrix)` 无效）；④裸 `textFrames.add()` 文字不渲染，必须复制已有正文标签作模板。bbox 用诊断脚本（遍历 groupItems 打印匹配框的对象）取精确值。
- **R3 同形词（通用）**：同画板同词同字号不同义时，决策按 x 排序输出 `key@1/@2`、译表用 `<key>@2` 给第二义；JSX 按文字框 x 就近匹配。缩写格（字号≥1.25×）仍走 `#abbr` 机制，两者不冲突。无需项目配置。
- **R4 手工位置回灌（需项目数据）**：审校手工挪的位置存进 `decision_tuning` 的 `pos` 段（`<ab>|<英文键>`→dx/dy），决策层叠加，清空 work 重跑仍复现。译表/位置表属项目数据，备份到 `<项目>/_seed/`，见 pipeline/README「清空 work 后如何复现」。
- **政策**：译文**绝不允许溢出容器**，但修法分两种：**标题**按容器/椭圆收缩（唯一允许改字号的
  对象）；**正文**改词、折行、让位，超宽只报 `BODY-OVERFLOW` 交人工，绝不缩字号。
  容器上限先用源文件几何实测（硬容器留边距、开放区留到邻近插画的间隙）。
  品牌名、产品名、数字、非目标语言文字保留；
  轮廓字/图片内文字如实标"未处理"，不冒充已翻译。字母认知卡的译文首字母可能不再与 A-Z 对应
  （A=apple→A=pomme），需提醒用户如要对应得连插图一起换。
- **字形覆盖预检**：目标语言特殊字符（œ é à ñ ü…）确认字体有字形，缺则换微软雅黑/思源黑体并告知。
- **R5 出图前后双闸（通用，pipeline 路线必跑）**：
  1. `qa_prebuild.py`（出图前，不调 Illustrator）：字形覆盖 / 字宽超槽 / 同排间距 / **页码禁区** / 漏译 / 标题 / 缩写格 / **正文缩号**。它算的全是几何题，秒级返回；在这里改一个词的成本是改译表，出图后才发现就是重出一整本。
  2. `qa_output.py`（出图后）：**不信任何模型，只读成品 .ai/.pdf 的真实字形坐标**，查页码压字、出血、页数。
  顺序不能反：`rebuild.py` 一次出一整本（数分钟起），「先出图再肉眼抽检」会把每个可静态计算的缺陷变成一次全量重出。
- **不可翻译的模板元素也是版面**：页码、角标、水印不进译表，任何「词与词」的碰撞检查都看不见它们，必须单独当障碍物建模。页码已内置为**右侧禁区**（`layout.pageno_gap_pt` 默认 10.5，不够则左移、移不动打 `PN-TIGHT`）；其它固定角标用决策 JSON 的 `obstacles` 传。实测教训：卡片右下角页码被末词压住时，视觉上一个 1.1pt 的"间隙"在代码里叫"没重叠"。
- **验收清单**：无源语言残留、无重影、无色块、译文居中（中心误差 ≤1pt）、特殊字符正确、
  转曲 PDF 无字体残留、插图/装饰完好、**页码与任何译文净空 ≥10pt 且未被压字**、台账状态如实。
- **cv2 读不了中文路径**：用 PIL 或 np.fromfile；OpenCV 是 BGR，hex 颜色要 [::-1]。
- **批量**：同版式卡片坐标/替换表可复用；50 张量级优先路线 C 的 BATCH_DIR。多配色×多语言的整套交付走 `pipeline/` 闭环（见开头强制流程）。
