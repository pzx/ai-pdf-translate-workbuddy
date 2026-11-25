/* geometry.jsx.inc - shared layout-constraint helpers for decision-driven JSX.
   Included verbatim by make_jsx.py. PURE ASCII on purpose: ExtendScript parses
   the job file as ANSI, so any non-ASCII byte breaks DoJavaScriptFile.
   All tuning lives in the injected GEO object (see config.example.json). */

/* True ink box: duplicate the frame, outline it, union the path bounds, delete
   the copy. visibleBounds includes font descent padding and is NOT the ink box.
   Returns null on failure so callers can fall back safely. */
function inkBounds(tf){
    var dup=null, arr=null, b=null;
    try{ dup=tf.duplicate(); }catch(e){ return null; }
    try{ arr=dup.createOutline(); }catch(e){
        try{ dup.remove(); }catch(e2){}
        return null;
    }
    var items=(arr&&arr.length!==undefined)?arr:[arr];
    if(!items||!items.length){ try{ dup.remove(); }catch(e){} return null; }
    try{
        b=items[0].geometricBounds;
        for(var i=1;i<items.length;i++){
            var q=items[i].geometricBounds;
            if(q[0]<b[0])b[0]=q[0];
            if(q[1]>b[1])b[1]=q[1];
            if(q[2]>b[2])b[2]=q[2];
            if(q[3]<b[3])b[3]=q[3];
        }
    }catch(e){ b=null; }
    for(var j=items.length-1;j>=0;j--){ try{ items[j].remove(); }catch(e){} }
    try{ dup.remove(); }catch(e){}
    return b;
}

/* Scan pathItems ONCE for plausible title ellipses. Size gates keep out the
   flanking dots and the wider "title + dots" combined box (~20% too wide). */
function scanEllipses(d){
    var out=[];
    var pis=d.pathItems, n=pis.length;
    for(var i=0;i<n;i++){
        var b=null; try{ b=pis[i].geometricBounds; }catch(e){ continue; }
        var w=b[2]-b[0], h=b[1]-b[3];
        if(w<GEO.ewmin||w>GEO.ewmax) continue;
        if(h<GEO.ehmin||h>GEO.ehmax) continue;
        out.push([b[0],b[1],b[2],b[3]]);
    }
    log("ELLC n="+out.length);
    return out;
}
function ellipseNear(list,tb){
    if(!list||!list.length) return null;
    var cx=(tb[0]+tb[2])/2, cy=(tb[1]+tb[3])/2;
    /* The title pill is the TIGHTEST ellipse that actually covers the title's
       centre. The old rule "ellipse must be narrower than the text" was
       inverted: the pill is always wider than the label, so it rejected the
       title's own background and every title fell back to "no-ellipse". */
    var best=null, bestArea=1e18;
    for(var i=0;i<list.length;i++){
        var b=list[i], w=b[2]-b[0], h=b[1]-b[3];
        if(w<=0||h<=0) continue;
        if(cx<b[0]-2||cx>b[2]+2||cy>b[1]+2||cy<b[3]-2) continue;   /* must cover centre */
        var ecx=(b[0]+b[2])/2, ecy=(b[1]+b[3])/2;
        if(Math.abs(ecx-cx)>GEO.edxy*4) continue;
        if(Math.abs(ecy-cy)>GEO.edxy*4) continue;
        var area=w*h;
        if(area<bestArea){ bestArea=area; best=b; }
    }
    return best;
}

function titleLead(tf,sz){
    /* Two lines need REAL leading. Typographic (OS/2) line height is ~0.94em;
       anything below that makes the descender of line 1 hit line 2, and the
       pill is only 34pt high so we must not overshoot either. */
    if(tf.contents.indexOf("\r")>=0) return Math.max(GEO.capr*sz+GEO.egap, 0.94*sz+1);
    return GEO.lead*(sz/18.0);
}
function applyTitleSize(tf,sz){
    try{ tf.textRange.characterAttributes.size=sz; }catch(e){ return false; }
    try{ var tt=tf.textRange; tt.characterAttributes.autoLeading=false;
         tt.characterAttributes.leading=titleLead(tf,sz); }catch(e){}
    return true;
}

/* Fit the WHOLE ink block (1 or 2 lines) inside the ellipse:
       (W/2a)^2 + (H/2b)^2 <= M^2
   Closed-form first pass, then an 8-pass safety net that re-measures the real
   ink box. Finally centre on the type body (cap top -> last baseline), NOT the
   raw ink box, which rides high when the first line is wider. */
function fitTitle(tf,tb,base,ell){
    if(!ell){ applyTitleSize(tf,base||18); return false; }
    var e=ell;
    var ecx=(e[0]+e[2])/2, ecy=(e[1]+e[3])/2;
    var ea=(e[2]-e[0])/2, eb=(e[1]-e[3])/2;
    if(ea<1||eb<1){ applyTitleSize(tf,base||18); return false; }
    var M=GEO.emargin;
    var sz=base||18;
    var twoMove=(tf.contents.indexOf("\r")>=0);
    applyTitleSize(tf,sz);
    var b0=inkBounds(tf)||tf.visibleBounds;
    var w0=b0[2]-b0[0], h0=b0[1]-b0[3];
    if(w0>0.5&&h0>0.5&&sz>0.5){
        var k1=w0/sz, k2=h0/sz;
        var D=(ea*M*k2)/(eb*k1);
        var u=D/Math.sqrt(1+D*D);
        var sz2=(2*eb*u)/k2;
        if(sz2>sz) sz2=sz;                    /* never enlarge */
        if(sz2<sz*0.3) sz2=sz*0.3;            /* never collapse */
        if(sz-sz2>0.05){ sz=sz2; applyTitleSize(tf,sz); }
    }
    for(var g=0;g<8;g++){
        var b1=inkBounds(tf)||tf.visibleBounds;
        var w=b1[2]-b1[0], h=b1[1]-b1[3];
        var qq=h/(2*eb); if(qq>0.97) qq=0.97;
        var availW=2*ea*Math.sqrt(1-qq*qq)*M;
        if(w<=availW+0.25) break;
        sz=sz*(availW/w);
        if(!applyTitleSize(tf,sz)) break;
    }
    for(var q=0;q<6;q++){
        var b2=inkBounds(tf)||tf.visibleBounds;
        var vc;
        if(twoMove){
            var capT=GEO.capr*sz;
            var hcap=capT+(capT+GEO.egap);    /* cap top -> last baseline */
            vc=b2[1]-hcap/2;
        }else{
            var capH2=GEO.capr*sz;
            var desc=b2[1]-capH2-b2[3];       /* ink below baseline */
            if(desc<0) desc=0;
            vc=b2[1]-(capH2+0.5*desc)/2;      /* cap centre, desc at half weight */
        }
        var dx=ecx-(b2[0]+b2[2])/2, dy=ecy-vc;
        if(Math.abs(dx)<0.2&&Math.abs(dy)<0.2) break;
        tf.translate(dx,dy);
    }
    return true;
}

/* How far outside the pill does an ink box sit?  1.0 = exactly on the edge.
   The pill is a real ELLIPSE (4 cubic beziers), not a rounded rectangle, so
   the usable width shrinks fast as the text rises: at 8pt above the centre of
   a 119x34 pill only 105pt of width is left.  Checking the corners against
   (x/a)^2+(y/b)^2 is the only honest test. */
function ellOverflow(b,ell,m){
    var cx=(ell[0]+ell[2])/2, cy=(ell[1]+ell[3])/2;
    var a=(ell[2]-ell[0])/2*m, bb=(ell[1]-ell[3])/2*m;
    if(a<=0||bb<=0) return 0;
    var pts=[[b[0],b[1]],[b[2],b[1]],[b[0],b[3]],[b[2],b[3]],
             [b[0],(b[1]+b[3])/2],[b[2],(b[1]+b[3])/2]];
    var worst=0;
    for(var i=0;i<pts.length;i++){
        var dx=(pts[i][0]-cx)/a, dy=(pts[i][1]-cy)/bb;
        var k=Math.sqrt(dx*dx+dy*dy);
        if(k>worst) worst=k;
    }
    return worst;
}

/* Deterministic variant used by the current pipeline: the caller has already
   decided the font size (one size for the whole book), so this only
     - shrinks until the ink box is INSIDE the pill (never leaves a word
       hanging over the oval, which was the "atmosferico / Settimane" overflow),
     - centres the ink block on the pill both ways.
   No aspect-ratio closed form, no per-title "looks about right" shrinking:
   that is what made identical titles land on different sizes. */
function centerTitleInPill(tf,ell,sz,two){
    if(!ell){ applyTitleSize(tf,sz||18); return sz||18; }
    var e=ell, M=GEO.emargin;
    if((e[2]-e[0])<2||(e[1]-e[3])<2){ applyTitleSize(tf,sz||18); return sz||18; }
    sz=sz||18;
    applyTitleSize(tf,sz);
    var floor=Math.max(6,(GEO.tsz||22)*0.45);
    for(var g=0;g<10;g++){
        /* 1. centre first: the fit test must be done where the text will sit */
        for(var q=0;q<3;q++){
            var b=inkBounds(tf)||tf.visibleBounds;
            var dx=(e[0]+e[2])/2-(b[0]+b[2])/2;
            var vc=two?((b[1]+b[3])/2):(b[1]-GEO.capr*sz/2);
            var dy=(e[1]+e[3])/2-vc;
            if(Math.abs(dx)<0.2&&Math.abs(dy)<0.2) break;
            tf.translate(dx,dy);
        }
        /* 2. still poking out of the oval -> scale down to sit exactly inside.
           For one line only the CAP band counts: a descender (Stagioni "g")
           is allowed to hang, otherwise the same word shrinks 0.7pt more just
           because its tail dips lower. */
        var bb=inkBounds(tf)||tf.visibleBounds;
        var bx=two?bb:[bb[0],bb[1],bb[2],bb[1]-GEO.capr*sz];
        var k=ellOverflow(bx,e,M);
        if(k<=1.0) break;
        sz=sz/Math.max(1.001,k)*0.997;
        if(sz<floor){ sz=floor; applyTitleSize(tf,sz); break; }
        if(!applyTitleSize(tf,sz)) break;
    }
    /* 3. final centring after the size settled */
    for(var q2=0;q2<3;q2++){
        var b2=inkBounds(tf)||tf.visibleBounds;
        var dx2=(e[0]+e[2])/2-(b2[0]+b2[2])/2;
        var vc2=two?((b2[1]+b2[3])/2):(b2[1]-GEO.capr*sz/2);
        var dy2=(e[1]+e[3])/2-vc2;
        if(Math.abs(dx2)<0.2&&Math.abs(dy2)<0.2) break;
        tf.translate(dx2,dy2);
    }
    return sz;
}

/* Axis-aligned separation; 0 when the boxes touch or overlap. */
function rectGap(a,b){
    var dx=Math.max(b[0]-a[2], a[0]-b[2]);
    var dy=Math.max(b[3]-a[1], a[3]-b[1]);
    if(dx<=0&&dy<=0) return 0;
    if(dx<=0) return dy;
    if(dy<=0) return dx;
    return Math.sqrt(dx*dx+dy*dy);
}

/* Guard: after the decision's cx/dy are applied, check the word against the
   configured illustration boxes. GEO.ocap=0 => WARN ONLY (never move an
   approved layout); >0 => nudge upward by at most ocap points. The engine that
   produces the decision JSON already avoids collisions - this is a safety net
   for projects that build decisions manually. */
function guardObstacles(tf,obs,key){
    if(!GEO.ogap||!obs||!obs.length) return;
    var moved=0;
    for(var pass=0;pass<4;pass++){
        var b=GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds;
        var worst=1e9;
        for(var i=0;i<obs.length;i++){
            var g=rectGap(b,obs[i]);
            if(g<worst) worst=g;
        }
        if(worst>=GEO.ogap){ if(moved>0)log("OBS ok "+key+" gap="+worst.toFixed(2)); return; }
        if(GEO.ocap<=0){ log("OBS WARN "+key+" gap="+worst.toFixed(2)+" < "+GEO.ogap); return; }
        var step=Math.min(GEO.ocap-moved, GEO.ogap-worst+0.2);
        if(step<=0){ log("OBS WARN "+key+" cap reached gap="+worst.toFixed(2)); return; }
        tf.translate(0,-step); moved+=step;
    }
}
