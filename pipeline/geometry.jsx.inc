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
function centerTitleInPill(tf,ell,sz,two,vdown,w1,w2){
    if(!ell){ applyTitleSize(tf,sz||18); return sz||18; }
    var e=ell, M=GEO.emargin;
    if((e[2]-e[0])<2||(e[1]-e[3])<2){ applyTitleSize(tf,sz||18); return sz||18; }
    sz=sz||18;
    applyTitleSize(tf,sz);
    /* vdown: how far BELOW the oval's centre a two-line block should sit, in
       points at the size it was measured at (TITLEDY). Plain centring puts the
       wider line on the block's outer edge, where the oval has already tapered,
       so that line ends up nearly touching the curve while the short line
       floats inside -- the "looks lopsided" report. Equalising the oval
       utilisation of the outer lines is what _two_line_shift() computes; it
       can only lower the worst corner. Scales with the size, so keep the ratio
       when the loop below has to shrink the title. */
    var vo=two?(vdown||0):0, sz0=sz;
    var floor=Math.max(6,(GEO.tsz||22)*0.45);
    /* ---- TWO-LINE TITLE: judge each line, place with the offset -----------
       A two-line block is NOT a rectangle: its bounding box pairs the widest
       line's ends with the deepest line's edge, and those two corners can lie
       far outside the oval while every glyph is well inside ("Necessidades"
       43.8pt wide on top, "diarias" 21pt below). Testing the box instead of
       the lines makes the engine shrink a correctly sized title to 11.5pt the
       moment the block is nudged down, so the lines are measured here on their
       own: line 1 sits at the block's top edge, line 2 one lead lower, and each
       is tested against the oval with its OWN width.
       w1/w2 are the line widths at `sz0` (TITLEW, from the generator); they
       scale with the size. Descenders are ignored on purpose -- a "q" tail may
       dip below the oval the way a single-line title's already may. */
    if(two && w1>0){
        var A2=(e[2]-e[0])/2*M, B2=(e[1]-e[3])/2*M;
        var cxE=(e[0]+e[2])/2, cyE=(e[1]+e[3])/2;
        for(var g2=0;g2<8;g2++){
            for(var q3=0;q3<3;q3++){
                var b3=inkBounds(tf)||tf.visibleBounds;
                var dx3=cxE-(b3[0]+b3[2])/2;
                var dy3=(cyE-vo*(sz/sz0))-((b3[1]+b3[3])/2);
                if(Math.abs(dx3)<0.2&&Math.abs(dy3)<0.2) break;
                tf.translate(dx3,dy3);
            }
            var b4=inkBounds(tf)||tf.visibleBounds;
            var kk=sz/sz0, ld2=GEO.lead*sz/18;
            var t1=b4[1];
            var u1=Math.pow((w1*kk/2)/A2,2)+Math.pow((t1-cyE)/B2,2);
            var u2=Math.pow((w2*kk/2)/A2,2)+Math.pow((t1-ld2-GEO.capr*sz-cyE)/B2,2);
            var uw=Math.max(u1,u2);
            if(uw<=GEO.t2f) break;
            sz=sz*Math.sqrt(GEO.t2f/uw)*0.995;
            if(sz<floor){ sz=floor; applyTitleSize(tf,sz); break; }
            if(!applyTitleSize(tf,sz)) break;
        }
        return sz;
    }
    for(var g=0;g<10;g++){
        /* 1. centre first: the fit test must be done where the text will sit */
        for(var q=0;q<3;q++){
            var b=inkBounds(tf)||tf.visibleBounds;
            var dx=(e[0]+e[2])/2-(b[0]+b[2])/2;
            var vc=two?((b[1]+b[3])/2+vo*(sz/sz0)):(b[1]-GEO.capr*sz/2);
            var dy=(e[1]+e[3])/2-vc;
            if(Math.abs(dx)<0.2&&Math.abs(dy)<0.2) break;
            tf.translate(dx,dy);
        }
        /* 2. still poking out of the oval -> scale down to sit exactly inside.
           For one line only the CAP band counts: a descender (Stagioni "g")
           is allowed to hang, otherwise the same word shrinks 0.7pt more just
           because its tail dips lower.
           A TWO-LINE title is tested as a BLOCK against the same ellipse: the
           widest line has to sit inside the oval at BOTH of the block's outer
           edges. Testing it as a rectangle instead let "Necessidades" grow to
           14.8pt and poke out of the pill's left and right ends -- the oval is a
           true ellipse (4 beziers), so there is no straight edge to lean on. */
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
        var vc2=two?((b2[1]+b2[3])/2+vo*(sz/sz0)):(b2[1]-GEO.capr*sz/2);
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
   approved layout); >0 => move DOWN, i.e. away from the artwork sitting above
   the label, by at most ocap points (Y grows up in the document space, so
   translate(0,-step) goes down). The engine that produces the decision JSON
   already avoids collisions - this is a safety net for hand-built decisions. */
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
