/*
 * 原生 Illustrator 文本替换模板（Edit 驱动，改活文本对象后另存真 .ai）。
 * 用法：改好下面的 SRC/OUT/MAP 后，通过 run_jsx.ps1 或 AI 菜单 文件>脚本>其他脚本 运行。
 * 批量：把 BATCH_DIR 指到装 .ai 的文件夹，输出自动加 _fr 后缀（改 SUFFIX 变量换语言）。
 */
#target illustrator

var SRC_FILE  = "G:/path/to/input.ai";
var OUT_FILE  = "G:/path/to/output_ai.ai";
var LOG_FILE  = "G:/path/to/work/jsx_result.txt";

/* 批量模式：BATCH_DIR 非空则处理该目录下全部 .ai，输出到 OUT_DIR */
var BATCH_DIR = "";
var OUT_DIR   = "G:/path/to/output";
var SUFFIX    = "_fr";          // 输出文件名后缀

/* 替换表：按 textFrame 全文 strip 后精确匹配。特殊字符用 \\uXXXX（\\u0153=œ, \\u00e9=é） */
var MAP = {
    "Letters":   "Lettres",
    "apple":     "pomme",
    "dog":       "chien",
    "candy":     "bonbon",
    "balloon":   "ballon",
    "egg":       "\\u0153uf",
    "fish":      "poisson",
    "giraffe":   "girafe",
    "house":     "maison",
    "ice":       "glace",
    "jellyfish": "m\\u00e9duse"
};

/* 每个原文对象的墨迹宽度上限（pt）。必须先从源文件几何实测：
   硬容器（胶囊/按钮）= 容器宽 - 两侧边距；开放区域 = 词带内到邻近插画的对称可用宽。
   译文墨迹超过上限必须自动缩字号，绝不允许溢出容器（用户硬性要求）。
   缺 key 时该对象不收缩（仅用于确认过不会溢出的对象）。 */
var MAXW = {
    "Letters":   95,
    "apple":     171.6,
    "dog":       163.4,
    "candy":     173.4,
    "balloon":   179.6,
    "egg":       114.6,
    "fish":      175,
    "giraffe":   179.6,
    "house":     93.6,
    "ice":       174.8,
    "jellyfish": 106.8
};

var lines = [];
function log(s) { lines.push(s); }

function writeLog() {
    var f = new File(LOG_FILE);
    f.open("w");
    f.encoding = "UTF-8";
    f.writeln(lines.join("\\n"));
    f.close();
}

/* 替换单个 textFrame：恢复原字体/字号/颜色/对齐，并用 visibleBounds 中心回补，
   使新文字可见边界中心与原文字重合（误差目标 <=1pt），长译文不偏移。
   ⚠️ 防溢出政策：译文墨迹宽超过 MAXW[key] 必须按比例缩字号（迭代两轮收敛，
   每轮以当前字号为基数），缩完再水平回中。容器几何测量方法见 MAXW 注释。 */
function replaceInDoc(doc) {
    var count = 0;
    for (var i = 0; i < doc.textFrames.length; i++) {
        var tf = doc.textFrames[i];
        var key = tf.contents.replace(/^\\s+|\\s+$/g, "");
        if (!MAP[key]) continue;

        var old = tf.textRange;
        var fnt = null, sz = null, clr = null, just = null;
        try { fnt  = old.characterAttributes.textFont; } catch (e) {}
        try { sz   = old.characterAttributes.size; } catch (e) {}
        try { clr  = old.characterAttributes.fillColor; } catch (e) {}
        try { just = old.paragraphAttributes.justification; } catch (e) {}

        /* 记录替换前的墨迹中心（只用于水平回中 + 缩字后垂直回补） */
        var ob = null;
        try { ob = tf.visibleBounds; } catch (e) {}
        var ocx = ob ? (ob[0] + ob[2]) / 2 : null;
        var ocy = ob ? (ob[1] + ob[3]) / 2 : null;

        tf.contents = MAP[key];

        var nw = tf.textRange;
        try { if (fnt)  nw.characterAttributes.textFont = fnt; } catch (e) {}
        try { if (sz)   nw.characterAttributes.size = sz; } catch (e) {}
        try { if (clr)  nw.characterAttributes.fillColor = clr; } catch (e) {}
        try { if (just !== null) nw.paragraphAttributes.justification = just; } catch (e) {}

        /* 只做水平回中，垂直方向绝不 translate。
           点文本基线锚在插入点上，改内容/换字体后基线自动保持原位；
           若按 visibleBounds 垂直居中，换字体后行框高度变化（CJK ascender 很高）
           会把基线推偏——日语标题被顶到胶囊上沿就是这个原因。 */
        if (ocx !== null) {
            try {
                var nb = tf.visibleBounds;
                tf.translate(ocx - (nb[0] + nb[2]) / 2, 0);
            } catch (e) {}
        }

        /* 防溢出：墨迹宽 > maxw 时按比例缩字号，迭代两轮收敛。
           缩字号后墨迹以基线为锚向上收缩、视觉中心下沉，所以缩放完成后
           必须把墨迹垂直中心回补到原文字的墨迹垂直中心（ocy）——
           否则缩得越多文字越偏下（德语 Buchstaben 16.4pt 偏下就是这个问题）。 */
        var maxw = MAXW[key];
        if (maxw && sz) {
            var cur = sz;
            var shrank = false;
            for (var pass = 0; pass < 2; pass++) {
                try {
                    var vb = tf.visibleBounds;
                    var w = vb[2] - vb[0];
                    if (w > maxw) {
                        cur = Math.max(6, cur * maxw / w);
                        nw.characterAttributes.size = cur;
                        shrank = true;
                        log("  shrink: " + MAP[key] + " -> " + Math.round(cur * 10) / 10 + "pt");
                    } else { break; }
                } catch (eF) { break; }
            }
            if (shrank && ocx !== null) {
                try {
                    var vb3 = tf.visibleBounds;
                    tf.translate(ocx - (vb3[0] + vb3[2]) / 2,
                                 (ocy !== null ? ocy - (vb3[1] + vb3[3]) / 2 : 0));
                } catch (eC) {}
            }
        }

        count++;
        log("  " + key + " -> " + MAP[key]);
    }
    return count;
}

function processOne(src, dst) {
    var doc = app.open(new File(src));
    log("OPEN " + src + " | textFrames=" + doc.textFrames.length);
    var n = replaceInDoc(doc);
    var opts = new IllustratorSaveOptions();
    opts.pdfCompatible = true;
    doc.saveAs(new File(dst), opts);
    log("SAVE " + dst + " | replaced=" + n);
    doc.close(SaveOptions.DONOTSAVECHANGES);
}

try {
    app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
    if (BATCH_DIR !== "") {
        var folder = new Folder(BATCH_DIR);
        var files = folder.getFiles("*.ai");
        log("BATCH files=" + files.length);
        for (var i = 0; i < files.length; i++) {
            var nm = files[i].name.replace(/\\.ai$/i, SUFFIX + ".ai");
            processOne(files[i].absoluteURI, OUT_DIR + "/" + nm);
        }
    } else {
        processOne(SRC_FILE, OUT_FILE);
    }
    log("DONE");
} catch (e) {
    log("ERROR: " + e.message + " (line " + e.line + ")");
}
writeLog();
