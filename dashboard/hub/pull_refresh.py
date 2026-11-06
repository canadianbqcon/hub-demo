"""Pull down at the top of any Hub page on a phone to reload it (Sam's pick, 2026-10-08).

The Hub runs as a home-screen app, where iOS gives no pull-to-reload of its own.
The look is Workbench pick "Line carries the logo halves in"
(data/workbench/options/hub-pull-to-refresh): a line grows in from both edges
carrying the two halves of the Hub mark, they lock in the middle at the trigger
point, and the mark turns half-turns while the page reloads.

Injected into every HTML response like zoom_lock, so a new template cannot miss it.
Touch screens only. A pull starts only when nothing under the finger is scrolled
down and the finger is not on a map, so it never steals an inner list's scroll or
a map pan. Opt a region out with data-no-ptr.
"""

_TAG = b"""<script data-hub-ptr>(function(){
if(!matchMedia("(pointer:coarse)").matches)return;
var TRIG=141,REST=73,MAX=200,SPRING="cubic-bezier(.34,1.56,.64,1)",d=document,html=d.documentElement;
var ind,mk,l1,l2,tick,hit=false,y0=null,pull=0,live=false,busy=false;
function build(){
 ind=d.createElement("div");
 ind.style.cssText="position:fixed;left:0;right:0;top:0;height:0;overflow:hidden;z-index:2147483646;pointer-events:none;background:var(--bg,#fff)";
 ind.innerHTML='<style>.hub-ptr-hl{position:absolute;top:calc(35px + var(--ptr-y,0px));height:calc(3px + var(--ptr-t,0)*4px);margin-top:calc(var(--ptr-t,0)*-2px);width:calc(var(--ptr-p)*50% - 22px);background:var(--accent,#1d4ed8)}'+
  '.hub-ptr-mk{position:absolute;left:50%;top:calc(17px + var(--ptr-y,0px));width:39px;height:39px;margin-left:-19.5px;overflow:visible;color:var(--accent,#1d4ed8);fill:currentColor;stroke:currentColor;stroke-width:calc(var(--ptr-t,0)*6);transition:color .15s}'+
  '.hub-ptr-hl{transition:background .15s,opacity .2s}'+
  '.hub-ptr-ease .hub-ptr-hl{transition:top .45s cubic-bezier(.34,1.56,.64,1),height .3s,margin-top .3s,background .15s,opacity .2s}'+
  '.hub-ptr-ease .hub-ptr-mk{transition:top .45s cubic-bezier(.34,1.56,.64,1),stroke-width .3s,color .15s}'+
  '.hub-ptr-go .hub-ptr-hl{opacity:0}'+
  '.hub-ptr-ok,.hub-ptr-bad{--ptr-c:var(--good,#1d7a3f)}.hub-ptr-bad{--ptr-c:var(--alert,#c0291f)}'+
  '.hub-ptr-ok .hub-ptr-hl,.hub-ptr-bad .hub-ptr-hl{background:var(--ptr-c);opacity:1;animation:hub-ptr-flash .3s ease-out}'+
  '.hub-ptr-ok .hub-ptr-mk,.hub-ptr-bad .hub-ptr-mk{color:var(--ptr-c);animation:hub-ptr-flash .3s ease-out}'+
  '@keyframes hub-ptr-flash{0%{opacity:.25}100%{opacity:1}}'+
  '.hub-ptr-go .hub-ptr-mk{animation:hub-ptr-spin 1.2s cubic-bezier(.6,0,.2,1) infinite}'+
  '@keyframes hub-ptr-spin{0%{transform:rotate(0)}50%{transform:rotate(180deg)}100%{transform:rotate(360deg)}}'+
  '@media (prefers-reduced-motion:reduce){.hub-ptr-go .hub-ptr-mk{animation:none}}</style>'+
  '<i class="hub-ptr-hl" style="left:0"></i><i class="hub-ptr-hl" style="right:0"></i>'+
  '<svg class="hub-ptr-mk" viewBox="0 0 64 64"><path d="M8 8 H40 V20 H20 V40 H8 Z"/><path d="M56 56 H24 V44 H44 V24 H56 Z"/></svg>';
 html.appendChild(ind);
 var p=ind.querySelectorAll("path");l1=p[0];l2=p[1];mk=ind.querySelector("svg");
}
function blocked(t){
 for(var e=t;e&&e!==html;e=e.parentElement){
  if(e.nodeType!==1)continue;
  if(e.hasAttribute("data-no-ptr")||/\\b(leaflet-container|maplibregl-map)\\b/.test(e.getAttribute("class")||""))return true;
  if(e.scrollTop>0)return true;
 }
 return (d.scrollingElement||html).scrollTop>0;
}
function draw(px,ease,p){
 if(!ind)build();
 // released: spring past the target and settle; dragging: follow the finger exactly
 p=busy?1:(p||0);var tr=ease?"transform .45s "+SPRING:"none";
 ind.style.transition=ease?"height .45s "+SPRING:"none";
 l1.style.transition=l2.style.transition=tr;
 ind.style.height=px+"px";ind.style.setProperty("--ptr-p",p);ind.classList.toggle("hub-ptr-ease",!!ease);
 if(ease)ind.style.setProperty("--ptr-t",0);
 // once the gap shows the whole animation (REST), it drifts down at half the page's rate
 ind.style.setProperty("--ptr-y",Math.max(px-REST,0)*.5+"px");
 l1.style.transform="translateX("+(-280*(1-p))+"px)";l2.style.transform="translateX("+(280*(1-p))+"px)";
 d.body.style.transition=tr;d.body.style.transform=px?"translateY("+px+"px)":"";
}
d.addEventListener("touchstart",function(e){
 if(busy||e.touches.length!==1||blocked(e.target)){y0=null;return}
 y0=e.touches[0].clientY;pull=0;live=false;hit=false;
},{passive:true});
d.addEventListener("touchmove",function(e){
 if(y0===null||busy)return;
 var dy=e.touches[0].clientY-y0;
 if(!live){if(dy<=0){y0=null;return}live=true}
 e.preventDefault();
 // Trigger and travel are separate: the reload fires at TRIG px of thumb (2026-10-08: 336 -30%, then -40%),
 // while the page moves on a rubber band: easy at first, stiffer the further you go, never past MAX.
 // Elasticity halved 2026-10-08: the page closes half the gap between the band and the thumb.
 // ponytail: tune .5 for how much the band holds back, .571 for its curve, TRIG for when it fires
 pull=Math.max(dy,0);var band=MAX*(1-1/(pull*.571/MAX+1));
 draw(pull-(pull-band)*.5,false,Math.min(pull/TRIG,1));
 if(pull>=TRIG&&!hit){hit=true;buzz()}else if(pull<TRIG)hit=false;
 // tension: past the trigger only, line and brackets thicken, flattening toward a cap
 ind.style.setProperty("--ptr-t",pull>TRIG?1-1/((pull-TRIG)/150+1):0);
},{passive:false});
function end(){
 if(!live){y0=null;return}
 live=false;y0=null;
 if(pull>=TRIG){busy=true;ind.classList.add("hub-ptr-go");draw(REST,true);check()}
 else draw(0,true);
}
// One tick when the pull crosses the trigger. Android: vibrate. iOS Safari has no vibrate,
// but since iOS 18 toggling a switch-style checkbox gives the system tick, so click a hidden one.
// ponytail: the iOS path is an undocumented side effect; if a release drops it, it just goes silent.
function buzz(){
 if(navigator.vibrate){navigator.vibrate(10);return}
 if(!tick){tick=d.createElement("label");tick.style.cssText="position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none";
  tick.innerHTML='<input type="checkbox" switch tabindex="-1" aria-hidden="true">';ind.appendChild(tick)}
 tick.click();
}
// A reload can't report back once the page is gone, so ask the server first:
// green then reload if it answers, red then spring back (keeping this page) if not.
function check(){
 var ac=window.AbortController?new AbortController():null,t=setTimeout(function(){ac&&ac.abort()},8000);
 fetch(location.href,{method:"HEAD",cache:"no-store",signal:ac&&ac.signal}).then(function(r){
  clearTimeout(t);flash(r.ok);
 },function(){clearTimeout(t);flash(false)});
}
function flash(ok){
 ind.classList.remove("hub-ptr-go");ind.classList.add(ok?"hub-ptr-ok":"hub-ptr-bad");
 setTimeout(function(){
  if(ok){location.reload();return}
  ind.classList.remove("hub-ptr-bad");busy=false;draw(0,true);
 },ok?600:1100);
}
d.addEventListener("touchend",end);d.addEventListener("touchcancel",function(){pull=0;end()});
// a reload restored from the back/forward cache comes back mid-spin
addEventListener("pageshow",function(e){if(e.persisted&&ind){busy=false;ind.classList.remove("hub-ptr-go","hub-ptr-ok","hub-ptr-bad");draw(0,false)}});
})();</script>"""


def add_pull_refresh(resp):
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if ctype != "text/html" or resp.status_code != 200:
        return resp
    resp.direct_passthrough = False   # send_from_directory hands back a file wrapper
    body = resp.get_data()
    if b"data-hub-ptr" in body:
        return resp
    # ponytail: last </body> by rfind, not an HTML parser; a page without one gets it appended
    i = body.lower().rfind(b"</body>")
    resp.set_data(body[:i] + _TAG + body[i:] if i >= 0 else body + _TAG)
    return resp


if __name__ == "__main__":
    from flask import Response
    r = add_pull_refresh(Response(b"<html><body><p>x</p></body></html>", content_type="text/html"))
    out = r.get_data()
    assert out.count(b"data-hub-ptr") == 1 and out.index(b"data-hub-ptr") < out.index(b"</body>")
    assert add_pull_refresh(r).get_data() == out                          # idempotent
    assert b"data-hub-ptr" in add_pull_refresh(Response(b"<p>x</p>", content_type="text/html")).get_data()
    assert add_pull_refresh(Response(b"{}", content_type="application/json")).get_data() == b"{}"
    print("pull_refresh ok")
