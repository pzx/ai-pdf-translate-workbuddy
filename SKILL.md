---
name: ai-pdf-translate-workbuddy
description: 替换 .ai / PDF 卡片与印刷文件中的文字并保留原版式，输出原生 .ai、转曲矢量 PDF 和多语言 XLSX 台账。适用：把英文单词改成中文/法语/西班牙语等其他语言、点读认知卡片翻译、整套卡片批量翻译、改 PDF 或 Illustrator 文件上的文字、按图文对应翻译保留原字体字号颜色位置。触发词：翻译卡片、改 ai 文件文字、pdf 英文换中文、点读卡片、批量翻译 50 张、AI 文件改语言、转曲。只做文字替换，不做整页重设计。
---

# AI/PDF 卡片文字翻译替换

先分析后动手。**第一步固定查 Illustrator**：`python scripts/check_illustrator.py`
（注册表 ProgID，不启动应用，退出码 0=已安装）。

**第二步判定「转曲与否」（和文件类型同等重要，二维路由）**：
`python scripts/analyze_file.py <file>`
- **未转曲** = 能提取活文本 span（.ai 的 PDF 兼容流同样能读）；
- **已转曲** = 无文本但有矢量字形路径（`get_drawings()` 路径数≈字母数，见路线 D 判定坑）；
- 无文本也无矢量字形 = 文字烧进位图 → 路线 A。

⚠️ **不要只看文件类型选路线**：未转曲的 PDF 转成 .ai 后是**活 textFrames**，必须走标准替换；
已转曲的 .ai **没有 textFrames**，必须走转曲模板（删字形路径+重建文本框）。两条模板用错 = 原文残留或纹丝不动。

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
        │     ├─ 输入 .pdf + 已装 Illustrator   → 转 base.ai → 路线 C **转曲模板**（111.pdf 即此路）
        │     └─ 输入 .pdf + 未装 Illustrator   → 路线 D（矢量 redact+插入，**不转曲**）
        │
        └─ 文字烧进位图                    → 路线 A（OCR 定位 + inpaint 擦除重绘）
```

## 输出组织与命名（硬规则）

- **目录按输入类型分**：`.ai` 输入 → 最终输出全部放 `output/ai/`；`.pdf` 输入 → 全部放 `output/pdf/`
  （即使走了 AI 流程转成 .ai 处理，输出目录仍按**输入**类型）。
- **交付物**：
  - `.ai` 输入：每语言 `源名_语言.ai`（可编辑文字）+ `源名_语言.pdf`（**全文本转曲**）+ 全源文件唯一 `源名_翻译.xlsx`
  - `.pdf` 输入 + 有 Illustrator：同 .ai 输入（每语言 .ai + 转曲 .pdf + 唯一 xlsx），放 `output/pdf/`
  - `.pdf` 输入 + 无 Illustrator：每语言 `源名_语言.pdf`（活文字矢量 PDF，**不转曲**）+ 唯一 `源名_翻译.xlsx`
- **命名**：`源文件名_语言_YYYYMMDD.扩展名`（**不含 ai/pdf 类型段**）；台账 `源文件名_翻译_YYYYMMDD.xlsx`。
  日期为 8 位当天日期（如 20261117）。同一文件多语言只差语言段；台账每源文件仅一份、七语各一列。
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
   （无残留文字、无字体资源、页数尺寸一致）
5. **台账**：`python scripts/make_translation_xlsx.py src.ai output --lang fr --map fr.json`
   ——xlsx 目录参数传 `output` 即按输入类型自动路由到 `output/ai/`（pdf 源→`output/pdf/`），
   自动命名 `源名_翻译_YYYYMMDD.xlsx`；每个文字对象一行、每种语言一列，再翻新语言对同一张表跑即可

**路线 C 有两套模板，按「转曲与否」选，不按文件类型选**：

6. **标准模板 `translate_native_template.jsx`**（源未转曲、有活 textFrames）：
   适用于未转曲 .ai 直接输入、**以及未转曲 PDF 转 base.ai 之后**（转出来的 textFrames 是活的）。
   在原 textFrame 里原位替换 contents，字体/字号/颜色/位置天然复刻，最简单可靠。
   **防溢出（硬性要求）**：替换后实测 `visibleBounds` 墨迹宽，超过 `MAXW[key]` 必须按比例
   缩字号（迭代两轮、每轮以当前字号为基数）。缩完后**必须把墨迹垂直中心回补到原文字的
   墨迹垂直中心**——缩字号以基线为锚向上收缩，不回补则缩得越多越偏下（德语 Buchstaben
   缩到 16.4pt 后明显偏下，回补后与原 Letters 墨迹中心差 0.3pt）。MAXW 必须先从源文件
   几何实测：硬容器（胶囊/按钮）= 容器宽 − 两侧边距；开放区域 = 词带内到邻近插画的
   对称可用宽。实测教训：德语 Buchstaben（23pt 时宽 119pt）溢出 95pt 宽胶囊 → 缩到
   16.4pt 后居中完好；不要假设"标题一般放得下"——逐语言渲染验收标题墨迹完全在容器内
   且垂直居中。
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
   maxw 超宽收缩（硬性，同标准模板的 MAXW 规则）。颜色/字号/透明度复刻原文操作符。
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
9. 验收：渲染对比原版——文字区外像素差异 0、词墨迹模态色应与原版**逐位一致**（AI 原生 CMYK，
   无任何转换偏差）、标题墨迹高与原版一致；转曲后 `get_text()` 为空。

**路线 D 仅在本机无 Illustrator 时使用**（有 AI 一律走路线 C，保证色彩/字号与原版完全一致且出可编辑 .ai）。

## 路线 D：已转曲矢量 PDF

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
8. **不做转曲**：路线 D 只在本机无 Illustrator 时走——无 AI 无法转曲，最终输出保持
   活文字矢量 PDF，交付说明/台账注明"未转曲（本机无 Illustrator）"。
   （若以后装了 AI，此文件应改走路线 C 重出。）
9. **台账**：转曲源提取不到文字对象，用 `--seed` 传人工核对的对象清单
   （[{page,text,size},...]，font 缺省即默认 Arial Rounded MT Bold），状态列标"转曲-重建"

细节见 references/font-matching.md。台账中此类对象标"转曲-重建"。

## 路线 A：位图擦除重绘（文字烧进图片）

1. `analyze_file.py <file> --render 3`；ViewImage 记录样式与背景
2. `detect_text_boxes.py` 出候选包围盒，人工核对
3. 写 items.json（box/text/color/mask_color），`raster_erase_redraw.py`
   擦除（**inpaint 修复，禁止纯色填充**——渐变底上必留色块）+ 居中重绘 + 回包同尺寸 PDF
4. ViewImage 验收（**每次换新输出文件名，同名覆盖会命中预览缓存**）

细节与坑见 references/raster-route.md。台账中此类文字标记"重建-OCR"。

## 通用规则

- **替换表先给用户过目**再执行；同页同词可因语境不同译（台账按对象编号区分，不按字串合并）。
- **政策**：译文**绝不允许溢出容器**——所有文字对象设实测宽度上限，超出自动按比例缩字号
  （硬容器留边距、开放区留到邻近插画的间隙）；缩后验收标题墨迹完全在容器内。
  品牌名、产品名、数字、非目标语言文字保留；
  轮廓字/图片内文字如实标"未处理"，不冒充已翻译。字母认知卡的译文首字母可能不再与 A-Z 对应
  （A=apple→A=pomme），需提醒用户如要对应得连插图一起换。
- **字形覆盖预检**：目标语言特殊字符（œ é à ñ ü…）确认字体有字形，缺则换微软雅黑/思源黑体并告知。
- **验收清单**：无源语言残留、无重影、无色块、译文居中（中心误差 ≤1pt）、特殊字符正确、
  转曲 PDF 无字体残留、插图/装饰/页码完好、台账状态如实。
- **cv2 读不了中文路径**：用 PIL 或 np.fromfile；OpenCV 是 BGR，hex 颜色要 [::-1]。
- **批量**：同版式卡片坐标/替换表可复用；50 张量级优先路线 C 的 BATCH_DIR。
