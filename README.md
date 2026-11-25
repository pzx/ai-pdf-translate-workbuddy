# ai-pdf-translate-workbuddy

替换 `.ai` / PDF 卡片与印刷文件中的文字并保留原版式，输出原生 `.ai`、转曲矢量 PDF 和多语言 XLSX 台账（WorkBuddy Skill）。

## 能力

- **二维路由**：先检测 Illustrator，再判定「转曲与否」——未转曲（活文本）走标准模板原位换字；已转曲（矢量字形）走转曲模板删字形路径 + 基线对齐重建
- **PDF 输入**：有 Illustrator 时先转 `.ai` 复用原生流程；无 Illustrator 时走 PyMuPDF 矢量路线（redact + 原生插入，不转曲）
- **色彩保真**：CMYK 复刻原文操作符（`k` 算子 / ExtGState 透明度），渲染与原版逐位一致
- **基线对齐**：fontTools 预计算译文墨迹相对基线偏移 + ExtendScript 转曲实测墨迹，PDF 路线与 AI 路线输出位置差 ≤0.5pt
- **字号规则**：只有标题可改字号（按椭圆收缩）；正文整本固定，超宽只走换词/折行/让位，缩号在三处被硬拦
- **多语言台账**：每个文字对象一行、每种语言一列，含字体/字号/状态/备注（字号列只读）

## 目录

```
SKILL.md                    技能主文档（路由 + 各路线步骤与坑）
agents/openai.yaml          接口描述
references/                 字体匹配、Illustrator 自动化、位图路线细节
scripts/                    分析、替换、转曲、验收、台账脚本
```

## 依赖

Windows + Python 3（pymupdf、Pillow、openpyxl、fontTools）、Adobe Illustrator（转曲与 .ai 原生流程需要）。
