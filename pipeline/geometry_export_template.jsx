/*target illustrator
/* geometry_export_template.jsx - generic, pure-ASCII geometry exporter.
   Inject __SRC__, __LOG_GEOM__, __LOG_INNER__, __LOG_JOB__, __CFG__ (a GEO object literal).
   GEO.tband = title band as a fraction of card height measured from the TOP
   (0.25 = top quarter). A candidate title outside that band is never a title.
   Classifies page objects into L(label) / I(illustration) / F(frame) /
   T(title) / P(page number) by SIZE GATES supplied in GEO, so a new layout
   can be tuned via pipeline.json without editing this file.
   Output per artboard row:
     ab <TAB> kind <TAB> cx <TAB> cy <TAB> x0 <TAB> ytop <TAB> x1 <TAB> ybot <TAB> kids <TAB> txt
   Text is escaped: tabs/spaces to spaces, CR/LF to '|'. */
var SRC=__SRC__, LOG_GEOM=__LOG_GEOM__, LOG_INNER=__LOG_INNER__, LOG_JOB=__LOG_JOB__;
__CFG__
var glines=[], ilines=[];
function r1(v){return Math.round(v*10)/10;}
function esc(s){return s.replace(/[\t]/g," ").replace(/[\r\n]/g,"|");}
function inAB(cx,cy,r){return cx>=r[0]-2&&cx<=r[2]+2&&cy>=r[3]-2&&cy<=r[1]+2;}
/* The title pill sits in the TOP band of every card. Without this test a
   calendar cell group (140x110, 5 kids) that happens to contain a 19pt-ish
   text is misfiled as a title and its month abbreviation ends up in
   title_map -> the page is then re-centred into the wrong pill. */
function inTitleBand(cy,r){return cy>=r[1]-(r[1]-r[3])*GEO.tband;}
/* first TextFrame contents inside a group (labels/titles are often nested) */
function groupText(it){
    var found="";
    try{
        var kids=it.pageItems,i,k;
        for(i=0;i<kids.length;i++){
            k=kids[i];
            if(k.typename==="TextFrame"){try{found=esc(k.contents);}catch(e){} if(found)return found;}
        }
        for(i=0;i<kids.length&&!found;i++){
            if(kids[i].typename==="GroupItem"){found=groupText(kids[i]);if(found)return found;}
        }
    }catch(e){}
    return found;
}
/* Largest font size of any TextFrame inside an item (depth <= 3).
   Used to recognise a TITLE by its TEXT instead of by its bounding box: some
   pages group the pill and the word differently, so a 137x34 banner can fall
   outside title_w/h_range and be misfiled as an illustration -- its title then
   never reaches the decisions and the page keeps its English title. */
function textSize(it){
    var best=0;
    function walk(o,d){
        if(d>3)return;
        var kids=[];try{kids=o.pageItems;}catch(e){return;}
        for(var i=0;i<kids.length;i++){
            var k=kids[i];
            try{
                if(k.typename==="TextFrame"){
                    var s=k.textRange.characterAttributes.size;
                    if(s>best)best=s;
                }else if(k.typename==="GroupItem")walk(k,d+1);
            }catch(e){}
        }
    }
    try{
        if(it.typename==="TextFrame")return it.textRange.characterAttributes.size;
        walk(it,0);
    }catch(e){}
    return best;
}
/* true when box b is already covered by a row we emitted (dedupe for the
   document-wide text pass) */
function boxCovered(b){
    for(var i=0;i<glines.length;i++){
        var f=glines[i].split("\t");
        if(f.length<8)continue;
        /* only dedupe against TEXT rows: an F/I row is a container whose box
           holds every label on the card, so treating it as "already covered"
           would suppress exactly the nested text we are looking for */
        if(f[1]!=="L"&&f[1]!=="T"&&f[1]!=="P")continue;
        var x0=parseFloat(f[4]),y1=parseFloat(f[5]),x1=parseFloat(f[6]),y0=parseFloat(f[7]);
        if(b[0]>=x0-1.5&&b[2]<=x1+1.5&&b[3]>=y0-1.5&&b[1]<=y1+1.5)return true;
    }
    return false;
}
/* recursively find precise inner frames */function walkInner(items,ai){
    for(var i=0;i<items.length;i++){
        var it=items[i],vb;try{vb=it.visibleBounds;}catch(e){continue;}
        var w=vb[2]-vb[0],h=vb[1]-vb[3];
        if(w>GEO.iwmin&&w<GEO.iwmax&&h>GEO.innerHMin&&h<GEO.innerHMax){
            var cx=(vb[0]+vb[2])/2,cy=(vb[1]+vb[3])/2;
            ilines.push([ai,r1(cx),r1(cy),r1(vb[0]),r1(vb[1]),r1(vb[2]),r1(vb[3]),r1(w),r1(h)].join("\t"));
        }
        try{if(it.pageItems&&it.pageItems.length>0)walkInner(it.pageItems,ai);}catch(e){}
    }
}
try{
    app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
    var doc=app.open(new File(SRC));
    var rects=[];for(var a=0;a<doc.artboards.length;a++)rects.push(doc.artboards[a].artboardRect);
    var xbestByAb={};
    for(var ai=0;ai<rects.length;ai++){
        var r=rects[ai];
        var gotT=false, xbest=null;
        for(var L=0;L<doc.layers.length;L++){
            var items=doc.layers[L].pageItems;
            for(var i=0;i<items.length;i++){
                var it=items[i],vb;try{vb=it.visibleBounds;}catch(e){continue;}
                var cx=(vb[0]+vb[2])/2,cy=(vb[1]+vb[3])/2;
                if(!inAB(cx,cy,r))continue;
                var w=vb[2]-vb[0],h=vb[1]-vb[3];
                var ty=it.typename,kids=0,txt="";
                try{kids=it.pageItems.length;}catch(e){}
                var kind="";
                if(ty==="TextFrame"){
                    try{txt=esc(it.contents);}catch(e){}
                    kind=(/^\s*\d+\s*$/.test(txt))?"P":"L";
                }else if(ty==="RasterItem"||ty==="PlacedItem"){
                    kind="I";
                }else if(ty==="GroupItem"){
                    /* order matters: label (single kid, short) -> frame (big)
                       -> title (banner) -> illustration (multi-kid) */
                    if(kids===1&&h>=GEO.lhmin&&h<=GEO.lhmax){kind="L";txt=groupText(it);}
                    else if(w>GEO.fwmin&&h>GEO.fhmin)kind="F";
                    else if(w>GEO.twmin&&w<GEO.twmax&&h>GEO.thmin&&h<GEO.thmax&&inTitleBand(cy,r)){kind="T";txt=groupText(it);}
                    /* banner geometry can differ per page; if the group holds a
                       TITLE-SIZED text, trust the text over the box */
                    else if(w<=GEO.fwmin&&textSize(it)>=GEO.tmin&&inTitleBand(cy,r)){kind="T";txt=groupText(it);}
                    else if(kids>=GEO.iminKids&&h>=GEO.iminH)kind="I";
                    else continue;
                }else if(ty==="PathItem"){
                    /* vector art in the title band: remembered only, in case this
                       artboard turns out to have no text title at all */
                    var top=r[1],bot=r[3],band=top-(top-bot)*0.20;
                    if(cy>=band&&w>=GEO.xwmin&&w<=GEO.xwmax&&h>=GEO.xhmin&&h<=GEO.xhmax){
                        if(!xbest||w>xbest[2]-xbest[0])xbest=vb;
                    }
                    continue;
                }else continue;
                if(kind==="T")gotT=true;
                glines.push([ai,kind,r1(cx),r1(cy),r1(vb[0]),r1(vb[1]),r1(vb[2]),r1(vb[3]),kids,txt].join("\t"));
            }
        }
        /* No text title found by the object walk; remember the banner-shaped
           vector art so we can decide AFTER the document-wide text pass whether
           this artboard's title really is outlined. */
        if(!gotT&&xbest)xbestByAb[ai]=xbest;
    }
    /* Document-wide text pass: the walk above only visits top-level pageItems,
       so a TextFrame nested deeper (or inside an odd group) can be missed. A
       text object is authoritative -- large ones are titles, the rest labels. */
    for(var t=0;t<doc.textFrames.length;t++){
        var tfx=doc.textFrames[t],tvb;try{tvb=tfx.visibleBounds;}catch(e){continue;}
        var tcx=(tvb[0]+tvb[2])/2,tcy=(tvb[1]+tvb[3])/2;
        var tai=-1;
        for(var q=0;q<rects.length;q++){ if(inAB(tcx,tcy,rects[q])){tai=q;break;} }
        if(tai<0)continue;
        if(boxCovered(tvb))continue;
        var ttxt="";try{ttxt=esc(tfx.contents);}catch(e){}
        if(!ttxt||/^\s*\d+\s*$/.test(ttxt))continue;
        var tsz=0;try{tsz=tfx.textRange.characterAttributes.size;}catch(e){}
        var tk=(tsz>=GEO.tmin&&inTitleBand(tcy,rects[tai]))?"T":"L";
        glines.push([tai,tk,r1(tcx),r1(tcy),r1(tvb[0]),r1(tvb[1]),r1(tvb[2]),r1(tvb[3]),1,ttxt].join("\t"));
    }
    /* Outlined-title markers, decided only after the text pass: an artboard
       whose title survives as banner-shaped vector art and still has no live
       text title was flattened -- name it so the export report is honest. */
    for(var xa=0;xa<rects.length;xa++){
        var hasT=false;
        for(var gx=0;gx<glines.length;gx++){
            var fx=glines[gx].split("\t");
            if(fx.length>1&&parseInt(fx[0],10)===xa&&fx[1]==="T"){hasT=true;break;}
        }
        var xb=xbestByAb[xa];
        if(!hasT&&xb){
            glines.push([xa,"X",r1((xb[0]+xb[2])/2),r1((xb[1]+xb[3])/2),
                         r1(xb[0]),r1(xb[1]),r1(xb[2]),r1(xb[3]),0,""].join("\t"));
        }
    }
    /* inner frames (recursive), scoped per artboard */
    for(var L=0;L<doc.layers.length;L++){
        var items=doc.layers[L].pageItems;
        for(var a=0;a<rects.length;a++){
            var sub=[];
            for(var i=0;i<items.length;i++){
                var it=items[i],vb;try{vb=it.visibleBounds;}catch(e){continue;}
                var cx=(vb[0]+vb[2])/2,cy=(vb[1]+vb[3])/2;
                if(inAB(cx,cy,rects[a]))sub.push(it);
            }
            walkInner(sub,a);
        }
    }
    /* Any artboard left with no text object at all (no label, no page number,
       no title) is almost certainly flattened to outlines. Emit a Y marker so
       the export report says so, instead of the page silently staying English. */
    for(var ai2=0;ai2<rects.length;ai2++){
        var hasText=false;
        for(var g2=0;g2<glines.length;g2++){
            var f2=glines[g2].split("\t");
            if(f2.length<2||parseInt(f2[0],10)!==ai2)continue;
            if(f2[1]==="L"||f2[1]==="T"||f2[1]==="P"){hasText=true;break;}
        }
        if(!hasText){
            var rr=rects[ai2];
            glines.push([ai2,"Y",r1((rr[0]+rr[2])/2),r1((rr[1]+rr[3])/2),
                         r1(rr[0]),r1(rr[1]),r1(rr[2]),r1(rr[3]),0,""].join("\t"));
        }
    }
    try{doc.close(SaveOptions.DONOTSAVECHANGES);}catch(e){}
}catch(e){glines.push("ERROR\t"+e.message+"\tline "+e.line);}
function wlog(name,lines){var f=new File(name);f.open("w");f.encoding="UTF-8";f.writeln(lines.join("\n"));f.close();}
wlog(LOG_GEOM,glines);
wlog(LOG_INNER,ilines);
/* the batch runner looks for "<jsx>.log" next to the script - write it THERE,
   not next to the TSV, or every book is retried twice as "no log output" */
var lf=new File(LOG_JOB);lf.open("w");lf.encoding="UTF-8";
lf.writeln((glines[0]&&glines[0].indexOf("ERROR")===0)?"ERROR: geometry export failed":"DONE total_ms=0");lf.close();
