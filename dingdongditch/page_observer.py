"""Bounded DOM/accessibility/geometry observation; contains no planning logic."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from dingdongditch.contract.observation import (
    ObservationFreshnessResult,
    ObservationReference,
    PageObservation,
    PageObservationOptions,
)


_SNAPSHOT_JS = r"""
(limits) => {
  if (!window.__dddObservationEpoch) {
    window.__dddObservationEpoch={value:0};
    new MutationObserver(()=>window.__dddObservationEpoch.value++)
      .observe(document,{subtree:true,childList:true,attributes:true,characterData:true});
  }
  const vw = window.innerWidth, vh = window.innerHeight, dpr = window.devicePixelRatio || 1;
  const roleMap = {A:'link',BUTTON:'button',TEXTAREA:'textbox',SELECT:'combobox',
    OPTION:'option',SUMMARY:'button'};
  const validRoles = new Set(['button','link','textbox','checkbox','radio','switch','tab',
    'menuitem','menuitemcheckbox','menuitemradio','option','combobox','listbox','slider',
    'spinbutton','searchbox','treeitem']);
  const regionRoles = new Set(['banner','navigation','main','region','form','complementary',
    'contentinfo','dialog','alertdialog','toolbar','menu','tablist']);
  const regionTag = {HEADER:'header',NAV:'navigation',MAIN:'main',SECTION:'section',
    FORM:'form',ASIDE:'aside',FOOTER:'footer',DIALOG:'dialog'};
  const rect = e => { const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; };
  const norm = r => ({x:r.x/vw*100,y:r.y/vh*100,width:r.width/vw*100,height:r.height/vh*100});
  const visible = e => {
    const s=getComputedStyle(e), r=e.getBoundingClientRect();
    return s.display!=='none' && s.visibility!=='hidden' && Number(s.opacity)!==0 &&
      r.width>0 && r.height>0 && r.bottom>0 && r.right>0 && r.top<vh && r.left<vw;
  };
  const text = e => (e.innerText || e.textContent || '').replace(/\s+/g,' ').trim();
  const name = e => {
    const aria=e.getAttribute('aria-label'); if (aria) return aria.trim();
    const ids=(e.getAttribute('aria-labelledby')||'').trim().split(/\s+/).filter(Boolean);
    if (ids.length) { const t=ids.map(id=>document.getElementById(id)).filter(Boolean).map(text).join(' ').trim(); if(t)return t; }
    if (e.labels && e.labels.length) { const t=[...e.labels].map(text).join(' ').trim(); if(t)return t; }
    return (e.getAttribute('alt') || e.getAttribute('title') || text(e)).trim();
  };
  const regionName = e => {
    const aria=e.getAttribute('aria-label'); if(aria)return aria.trim();
    const ids=(e.getAttribute('aria-labelledby')||'').trim().split(/\s+/).filter(Boolean);
    return ids.map(id=>document.getElementById(id)).filter(Boolean).map(text).join(' ').trim();
  };
  const role = e => e.getAttribute('role') || roleMap[e.tagName] ||
    (e.tagName==='INPUT' ? ({button:'button',submit:'button',reset:'button',checkbox:'checkbox',
      radio:'radio',range:'slider',email:'textbox',search:'searchbox',tel:'textbox',
      text:'textbox',url:'textbox',number:'spinbutton'}[(e.type||'text').toLowerCase()] || 'textbox') : null);
  const selectedState = e => {
    if ('selected' in e) return {value:!!e.selected,source:'native_selected'};
    if (e.hasAttribute('aria-selected')) return {value:e.getAttribute('aria-selected')==='true',source:'aria-selected'};
    if (e.hasAttribute('aria-current')) return {value:!['false',''].includes(e.getAttribute('aria-current')),source:'aria-current'};
    const state=(e.getAttribute('data-state')||'').toLowerCase();
    if (state) return {value:['active','selected','on','checked','open','current'].includes(state),source:'data-state'};
    const tokens=[...e.classList];
    if (tokens.some(t=>/^(is-)?(active|selected|current|checked)$/.test(t.toLowerCase())))
      return {value:true,source:'class_state_token'};
    if (tokens.some(t=>/^[^:]*[^a-z]?(text|color|background|bg)[^:]*:var\(--[^)]*(active|selected|current)[^)]*\)/i.test(t)))
      return {value:true,source:'css_active_variable_binding'};
    return {value:null,source:null};
  };
  const regionNodes=[...document.querySelectorAll('header,nav,main,section,form,aside,footer,dialog,[role]')]
    .filter(e=>regionTag[e.tagName] || regionRoles.has(e.getAttribute('role'))).filter(visible);
  const regions=regionNodes.slice(0,limits.maxRegions).map((e,i)=>{
    const r=rect(e); return {_node:e,region_id:`reg_${i+1}`,semantic_role:e.getAttribute('role')||
      regionTag[e.tagName]||'region',accessible_name:regionName(e)||null,visible:true,bounds_px:r,
      bounds_normalized:norm(r),parent_region_id:null,child_region_ids:[],interactive_element_ids:[]};
  });
  for (const r of regions) {
    let p=r._node.parentElement;
    while(p) { const pr=regions.find(x=>x._node===p); if(pr){r.parent_region_id=pr.region_id;pr.child_region_ids.push(r.region_id);break;} p=p.parentElement; }
  }
  const selector='button,a[href],input,textarea,select,option,summary,[contenteditable=""],[contenteditable="true"],[role],[tabindex]';
  const nodes=[...document.querySelectorAll(selector)].filter(e=>{
    const rr=role(e), tabindex=e.getAttribute('tabindex');
    return visible(e) && !e.hidden && (validRoles.has(rr)||e.matches('button,a[href],input,textarea,select,option,summary,[contenteditable=""],[contenteditable="true"]')||(tabindex!==null&&Number(tabindex)>=0));
  });
  const allCount=nodes.length;
  const elements=nodes.slice(0,limits.maxElements).map((e,i)=>{
    const r=rect(e), rr=role(e), t=text(e).slice(0,limits.maxTextLength);
    const sensitive=(e.tagName==='INPUT' && ['password','hidden'].includes((e.type||'').toLowerCase())) ||
      /token|secret|password|passwd|api.?key/i.test(`${e.name||''} ${e.id||''} ${e.getAttribute('autocomplete')||''}`);
    const center={x:r.x+r.width/2,y:r.y+r.height/2};
    const hit=(center.x>=0&&center.x<vw&&center.y>=0&&center.y<vh)?document.elementFromPoint(center.x,center.y):null;
    const owner=[...regions].reverse().find(x=>x._node.contains(e));
    const attrs={};
    for(const a of ['id','name','data-testid','data-test','data-qa','aria-controls','aria-describedby','aria-current','data-state','autocomplete','class'])
      if(e.getAttribute(a)!==null) attrs[a]=e.getAttribute(a);
    const selection=selectedState(e);
    return {_node:e,element_id:`el_${i+1}`,dom_tag:e.tagName.toLowerCase(),semantic_role:rr,
      accessible_name:name(e).slice(0,limits.maxTextLength)||null,visible_text:t||null,
      input_type:e.tagName==='INPUT'?(e.type||'text'):null,href:e.href||null,
      placeholder:e.getAttribute('placeholder'),current_value:sensitive?'[REDACTED]':
        (['INPUT','TEXTAREA','SELECT'].includes(e.tagName)?String(e.value).slice(0,limits.maxTextLength):null),
      value_redacted:sensitive,enabled:!(e.disabled||e.getAttribute('aria-disabled')==='true'),visible:true,
      editable:e.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(e.tagName),
      focusable:e.tabIndex>=0,focused:document.activeElement===e,
      checked:'checked' in e?!!e.checked:(e.getAttribute('aria-checked')==='true'?true:e.getAttribute('aria-checked')==='false'?false:null),
      selected:selection.value,selected_state_source:selection.source,
      expanded:e.hasAttribute('aria-expanded')?e.getAttribute('aria-expanded')==='true':null,
      pressed:e.hasAttribute('aria-pressed')?e.getAttribute('aria-pressed')==='true':null,
      required:!!e.required||e.getAttribute('aria-required')==='true',readonly:!!e.readOnly||e.getAttribute('aria-readonly')==='true',
      bounds_px:r,bounds_normalized:norm(r),center_px:center,
      center_normalized:{x:center.x/vw*100,y:center.y/vh*100},
      viewport_inclusion:r.x>=0&&r.y>=0&&r.x+r.width<=vw&&r.y+r.height<=vh?'fully':
        (r.y+r.height>0&&r.x+r.width>0&&r.y<vh&&r.x<vw?'partially':'outside'),
      occlusion_state:hit && (hit===e||e.contains(hit))?'not_occluded':(hit?'occluded':'unknown'),
      owning_region_id:owner?owner.region_id:null,parent_interactive_element_id:null,useful_attributes:attrs};
  });
  for(const x of elements) {
    let p=x._node.parentElement; while(p){const pe=elements.find(y=>y._node===p);if(pe){x.parent_interactive_element_id=pe.element_id;break;}p=p.parentElement;}
    const r=regions.find(y=>y.region_id===x.owning_region_id); if(r)r.interactive_element_ids.push(x.element_id);
  }
  const overlays=regions.filter(r=>['dialog','alertdialog','menu'].includes(r.semantic_role)||r._node.tagName==='DIALOG').map((r,i)=>{
    const s=getComputedStyle(r._node), b=r.bounds_px, cx=Math.max(0,Math.min(vw-1,b.x+b.width/2)),cy=Math.max(0,Math.min(vh-1,b.y+b.height/2));
    const hit=document.elementFromPoint(cx,cy);
    return {overlay_id:`overlay_${i+1}`,role:r.semantic_role,accessible_name:r.accessible_name,bounds_px:b,
      bounds_normalized:r.bounds_normalized,blocking:!!hit&&r._node.contains(hit)&&b.width*b.height>vw*vh*.15,
      contained_interactive_element_ids:r.interactive_element_ids,z_index:s.zIndex==='auto'?null:Number(s.zIndex)};
  });
  const textNodes=[]; const textGroups=new WeakMap();let textGroupCounter=0;
  const walker=document.createTreeWalker(document.body||document.documentElement,NodeFilter.SHOW_TEXT);
  let n; while((n=walker.nextNode())&&textNodes.length<limits.maxTextBlocks){
    const v=n.nodeValue.replace(/\s+/g,' ').trim(); if(!v||!visible(n.parentElement))continue;
    let group=n.parentElement;
    for(let depth=0,p=group.parentElement;depth<4&&p;depth++,p=p.parentElement){
      const candidate=text(p);
      if(/^[\p{L}\p{N}'-]{1,40}$/u.test(candidate))group=p;else break;
    }
    const groupText=text(group);
    if(!textGroups.has(group))textGroups.set(group,`text_group_${++textGroupCounter}`);
    const groupId=textGroups.get(group);
    if(textNodes.some(x=>x.text_group_id===groupId))continue;
    const range=document.createRange();range.selectNodeContents(group);const r=range.getBoundingClientRect();
    if(!r.width||!r.height||r.bottom<=0||r.right<=0||r.top>=vh||r.left>=vw)continue;
    if(textNodes.some(x=>x.text===groupText&&Math.abs(x.bounds_px.x-r.x)<1&&Math.abs(x.bounds_px.y-r.y)<1))continue;
    const owner=[...regions].reverse().find(x=>x._node.contains(group));
    textNodes.push({text_block_id:`text_${textNodes.length+1}`,text_group_id:groupId,
      text:groupText.slice(0,limits.maxTextLength),
      owning_region_id:owner?owner.region_id:null,bounds_px:{x:r.x,y:r.y,width:r.width,height:r.height},
      bounds_normalized:norm(r),truncated:groupText.length>limits.maxTextLength});
  }
  const scrollables=[...document.querySelectorAll('*')].filter(e=>{const s=getComputedStyle(e);return visible(e)&&
    /(auto|scroll)/.test(s.overflowY+s.overflowX)&&(e.scrollHeight>e.clientHeight||e.scrollWidth>e.clientWidth);})
    .slice(0,limits.maxScrollables).map((e,i)=>{const r=rect(e);return{container_id:`scroll_${i+1}`,bounds_px:r,
      scroll_x:e.scrollLeft,scroll_y:e.scrollTop,scroll_width:e.scrollWidth,scroll_height:e.scrollHeight,
      client_width:e.clientWidth,client_height:e.clientHeight,max_scroll_x:e.scrollWidth-e.clientWidth,
      max_scroll_y:e.scrollHeight-e.clientHeight,contained_region_ids:regions.filter(x=>e.contains(x._node)).map(x=>x.region_id),
      contained_interactive_element_ids:elements.filter(x=>e.contains(x._node)).map(x=>x.element_id)}});
  const active=elements.find(x=>x._node===document.activeElement);
  const activeDom=document.activeElement;
  const clean=x=>{delete x._node;return x}; regions.forEach(clean);elements.forEach(clean);
  const root=document.documentElement, body=document.body;
  return {url:location.href,title:document.title,viewport:{width:vw,height:vh,device_pixel_ratio:dpr},
    document:{width:Math.max(root.scrollWidth,body?body.scrollWidth:0),height:Math.max(root.scrollHeight,body?body.scrollHeight:0),
      scroll_x:window.scrollX,scroll_y:window.scrollY},
    focus:{page_has_focus:document.hasFocus(),focused_element_id:active?active.element_id:null,
      focused_element_role:active?active.semantic_role:null,focused_element_accessible_name:active?active.accessible_name:null,
      focused_element_editable:active?active.editable:false,active_frame:{url:location.href,name:window.name||null},
      active_dom_element:activeDom?{tag:activeDom.tagName.toLowerCase(),id:activeDom.id||null,
        role:activeDom.getAttribute('role'),editable:activeDom.isContentEditable||
          ['INPUT','TEXTAREA','SELECT'].includes(activeDom.tagName),
        focusable:activeDom.tabIndex>=0,visible:visible(activeDom)}:null,
      inside_dialog_or_overlay:!!(document.activeElement&&document.activeElement.closest('dialog,[role="dialog"],[role="alertdialog"],[popover]'))},
    regions,elements,overlays,textBlocks:textNodes,scrollables,totalElements:allCount,
    totalRegions:regionNodes.length,textLimitReached:!!n,
    signature:[location.href,document.title,root.childElementCount,document.querySelectorAll('*').length,
      root.scrollWidth,root.scrollHeight,window.__dddObservationEpoch.value].join('|')};
}
"""

_SIGNATURE_JS = r"""() => {
  const root=document.documentElement;
  return [location.href,document.title,root.childElementCount,
    document.querySelectorAll('*').length,root.scrollWidth,root.scrollHeight,
    window.__dddObservationEpoch ? window.__dddObservationEpoch.value : -1].join('|');
}"""

_WAIT_FOR_DOM_QUIESCENCE_JS = r"""
({quietMs, budgetMs}) => new Promise(resolve => {
  let mutations = 0;
  let settled = false;
  let quietTimer = null;
  const finish = stable => {
    if (settled) return;
    settled = true;
    observer.disconnect();
    if (quietTimer !== null) clearTimeout(quietTimer);
    clearTimeout(budgetTimer);
    resolve({
      stable,
      mutations,
      mutation_epoch: window.__dddObservationEpoch
        ? window.__dddObservationEpoch.value : null
    });
  };
  const armQuietWindow = () => {
    if (quietTimer !== null) clearTimeout(quietTimer);
    quietTimer = setTimeout(() => finish(true), quietMs);
  };
  const observer = new MutationObserver(records => {
    mutations += records.length;
    armQuietWindow();
  });
  observer.observe(document, {
    subtree: true,
    childList: true,
    attributes: true,
    characterData: true
  });
  const budgetTimer = setTimeout(() => finish(false), budgetMs);
  armQuietWindow();
})
"""


class _ObservationMutated(RuntimeError):
    def __init__(self, before: str, after: str) -> None:
        super().__init__("DOM mutated during observation capture")
        self.before = before
        self.after = after


class ObservationUnstableError(RuntimeError):
    def __init__(self, evidence: dict[str, Any]) -> None:
        super().__init__(
            "page changed while observation locator attestations were collected"
        )
        self.evidence = evidence

_VALIDATE_REFERENCE_JS = r"""
(identity) => {
  const roleMap={A:'link',BUTTON:'button',TEXTAREA:'textbox',SELECT:'combobox',
    OPTION:'option',SUMMARY:'button'};
  const role=e=>e.getAttribute('role')||roleMap[e.tagName]||
    (e.tagName==='INPUT'?({button:'button',submit:'button',reset:'button',checkbox:'checkbox',
      radio:'radio',range:'slider',email:'textbox',search:'searchbox',tel:'textbox',
      text:'textbox',url:'textbox',number:'spinbutton'}[(e.type||'text').toLowerCase()]||'textbox'):null);
  const text=e=>(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim();
  const name=e=>{
    const aria=e.getAttribute('aria-label');if(aria)return aria.trim();
    const ids=(e.getAttribute('aria-labelledby')||'').trim().split(/\s+/).filter(Boolean);
    if(ids.length){const t=ids.map(id=>document.getElementById(id)).filter(Boolean).map(text).join(' ').trim();if(t)return t;}
    if(e.labels&&e.labels.length){const t=[...e.labels].map(text).join(' ').trim();if(t)return t;}
    return(e.getAttribute('alt')||e.getAttribute('title')||text(e)).trim();
  };
  const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return s.display!=='none'&&
    s.visibility!=='hidden'&&Number(s.opacity)!==0&&r.width>0&&r.height>0&&
    r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth};
  const nodes=[...document.querySelectorAll('button,a[href],input,textarea,select,option,summary,[contenteditable=""],[contenteditable="true"],[role],[tabindex]')];
  const matches=nodes.filter(e=>e.tagName.toLowerCase()===identity.dom_tag&&role(e)===identity.semantic_role&&name(e)===identity.accessible_name);
  const root=document.documentElement,body=document.body;
  return {match_count:matches.length,visible:matches.length===1?visible(matches[0]):null,
    enabled:matches.length===1?!(matches[0].disabled||matches[0].getAttribute('aria-disabled')==='true'):null,
    selected:matches.length===1?(('selected'in matches[0])?!!matches[0].selected:
      (matches[0].hasAttribute('aria-selected')?matches[0].getAttribute('aria-selected')==='true':null)):null,
    pressed:matches.length===1?(matches[0].hasAttribute('aria-pressed')?matches[0].getAttribute('aria-pressed')==='true':null):null,
    signature:[location.href,document.title,root.childElementCount,document.querySelectorAll('*').length,
      root.scrollWidth,root.scrollHeight,
      window.__dddObservationEpoch ? window.__dddObservationEpoch.value : -1].join('|')};
}
"""


class PageObserver:
    def __init__(self, backend: Any):
        self.backend = backend
        self._observations: dict[str, PageObservation] = {}

    def observe_page(self, options: PageObservationOptions | None = None) -> PageObservation:
        options = options or PageObservationOptions()
        options.validate()
        if not self.backend.is_started:
            raise RuntimeError("page observation requires an active backend")
        deadline = time.monotonic_ns() // 1_000_000 + options.observation_budget_ms
        attempts = 0
        discarded: list[dict[str, Any]] = []
        while True:
            attempts += 1
            try:
                observation = self._capture_once(options)
                observation.diagnostics["transaction"] = {
                    "attempts": attempts,
                    "discarded_attempts": list(discarded),
                    "observation_budget_ms": options.observation_budget_ms,
                    "mutation_quiescence_ms": options.mutation_quiescence_ms,
                }
                return observation
            except _ObservationMutated as mutation:
                now = time.monotonic_ns() // 1_000_000
                remaining = deadline - now
                evidence = {
                    "attempt": attempts,
                    "before_fingerprint": hashlib.sha256(
                        mutation.before.encode()
                    ).hexdigest(),
                    "after_fingerprint": hashlib.sha256(
                        mutation.after.encode()
                    ).hexdigest(),
                    "remaining_budget_ms": max(0, remaining),
                }
                discarded.append(evidence)
                if remaining <= 0:
                    raise ObservationUnstableError({
                        "attempts": attempts,
                        "discarded_attempts": discarded,
                        "reason": "observation_budget_exhausted",
                    }) from mutation
                quiescence = self.backend.page.evaluate(
                    _WAIT_FOR_DOM_QUIESCENCE_JS,
                    {
                        "quietMs": options.mutation_quiescence_ms,
                        "budgetMs": remaining,
                    },
                )
                evidence["quiescence"] = dict(quiescence)
                if not quiescence.get("stable"):
                    raise ObservationUnstableError({
                        "attempts": attempts,
                        "discarded_attempts": discarded,
                        "reason": "dom_never_reached_quiescence",
                    }) from mutation

    def _capture_once(self, options: PageObservationOptions) -> PageObservation:
        options.validate()
        started = time.time_ns() // 1_000_000
        raw = self.backend.page.evaluate(_SNAPSHOT_JS, {
            "maxElements": options.max_interactive_elements,
            "maxTextBlocks": options.max_text_blocks,
            "maxRegions": options.max_regions,
            "maxScrollables": options.max_scrollable_containers,
            "maxTextLength": options.max_text_length,
        })
        for element in raw["elements"]:
            element["locator_candidates"] = self._locator_candidates(element, raw["elements"], raw["regions"])
            self._verify_locator_candidates(element["locator_candidates"])
        final_signature = self.backend.page.evaluate(_SIGNATURE_JS)
        if final_signature != raw["signature"]:
            raise _ObservationMutated(raw["signature"], final_signature)
        relationships = self._relationships(raw["elements"], options)
        observation_id = str(uuid.uuid4())
        captured = time.time_ns() // 1_000_000
        fingerprint = hashlib.sha256(raw["signature"].encode()).hexdigest()
        diagnostics = {
            "capture_duration_ms": captured - started,
            "truncated": {
                "interactive_elements": raw["totalElements"] > len(raw["elements"]),
                "regions": raw["totalRegions"] > len(raw["regions"]),
                "visible_text": raw["textLimitReached"],
                "relationships": False,
                "payload": False,
            },
            "counts_before_limits": {"interactive_elements": raw["totalElements"], "regions": raw["totalRegions"]},
            "evidence_sources": ["DOM", "ARIA", "accessible-name rules", "computed visibility", "bounding geometry", "hit testing"],
        }
        scroll = {
            **raw["document"], "viewport_width": raw["viewport"]["width"], "viewport_height": raw["viewport"]["height"],
            "can_scroll_up": raw["document"]["scroll_y"] > 0,
            "can_scroll_down": raw["document"]["scroll_y"] + raw["viewport"]["height"] < raw["document"]["height"],
            "scrollable_containers": raw["scrollables"],
        }
        obs = PageObservation(
            observation_id=observation_id, timestamp=datetime.now(timezone.utc).isoformat(),
            captured_at_ms=captured, browser_profile=self.backend.browser_config.profile.value,
            url=raw["url"], title=raw["title"], viewport=raw["viewport"], document=raw["document"],
            focus=raw["focus"], overlays=raw["overlays"], regions=raw["regions"],
            visible_text=raw["textBlocks"], interactive_elements=raw["elements"],
            spatial_relationships=relationships, scroll_context=scroll,
            freshness={"fingerprint": fingerprint, "max_age_ms": options.freshness_max_age_ms,
                       "page_id": self.backend.page_id, "captured_at_ms": captured},
            diagnostics=diagnostics)
        while len(json.dumps(obs.to_dict(), ensure_ascii=False).encode()) > options.max_payload_bytes:
            diagnostics["truncated"]["payload"] = True
            if obs.visible_text: obs.visible_text.pop()
            elif obs.spatial_relationships: obs.spatial_relationships.pop()
            elif obs.interactive_elements: obs.interactive_elements.pop()
            else: break
        self._observations[observation_id] = obs
        if len(self._observations) > 20:
            self._observations.pop(next(iter(self._observations)))
        return obs

    def _verify_locator_candidates(self, candidates: list[dict[str, Any]]) -> None:
        """Use the execution resolver's primitives to attest advertised cardinality."""
        for candidate in candidates:
            kind = candidate["locator_type"]
            value = candidate["locator_value"]
            try:
                if kind == "role_name":
                    count = self.backend.page.get_by_role(
                        value["role"], name=value["name"], exact=True
                    ).count()
                elif kind == "exact_text":
                    count = self.backend.page.get_by_text(value, exact=True).count()
                elif kind == "test_id":
                    count = self.backend.page.get_by_test_id(value).count()
                elif kind == "css":
                    count = self.backend.page.locator(value).count()
                elif kind == "within_region":
                    # A constrained role/name cannot succeed when its primary identity
                    # has no candidates, regardless of the proposed region.
                    count = self.backend.page.get_by_role(
                        value["role"], name=value["name"], exact=True
                    ).count()
                else:
                    continue
            except Exception as exc:
                candidate.update({"match_count": None, "unique": False, "confidence": 0.0,
                                  "known_ambiguity": f"cardinality check failed: {type(exc).__name__}"})
                continue
            candidate["match_count"] = count
            candidate["unique"] = count == 1
            if count != 1:
                candidate["confidence"] = min(candidate["confidence"], .45)
                candidate["known_ambiguity"] = f"{count} matching elements"
        candidates.sort(key=lambda item: (not item["unique"], -item["confidence"]))

    @staticmethod
    def _locator_candidates(e: dict[str, Any], elements: list[dict[str, Any]], regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        def add(kind: str, value: Any, count: int, confidence: float, reason: str) -> None:
            candidates.append({"locator_type": kind, "locator_value": value, "expected_cardinality": 1,
                "match_count": count, "unique": count == 1, "confidence": confidence if count == 1 else min(confidence, .45),
                "reason": reason, "known_ambiguity": None if count == 1 else f"{count} matching elements"})
        attrs=e["useful_attributes"]
        test=attrs.get("data-testid") or attrs.get("data-test") or attrs.get("data-qa")
        if test:
            count=sum(1 for x in elements if test in (x["useful_attributes"].get("data-testid"),x["useful_attributes"].get("data-test"),x["useful_attributes"].get("data-qa")))
            add("test_id", test, count, .99, "unique explicit test attribute" if count == 1 else "duplicate test attribute")
        if e["semantic_role"] and e["accessible_name"]:
            count=sum(1 for x in elements if x["semantic_role"]==e["semantic_role"] and x["accessible_name"]==e["accessible_name"])
            add("role_name", {"role":e["semantic_role"],"name":e["accessible_name"],"exact":True}, count, .95, "exact accessible role and name")
        if e["placeholder"]:
            count=sum(1 for x in elements if x["placeholder"]==e["placeholder"]); add("placeholder",e["placeholder"],count,.88,"exact placeholder")
        if attrs.get("id") and not any(s in attrs["id"].lower() for s in ("react","ember",":","__")):
            count=sum(1 for x in elements if x["useful_attributes"].get("id")==attrs["id"]);add("css",f"#{attrs['id']}",count,.9,"stable-looking DOM id")
        if e["visible_text"] and len(e["visible_text"]) <= 120:
            count=sum(1 for x in elements if x["visible_text"]==e["visible_text"]);add("exact_text",e["visible_text"],count,.8,"exact visible text")
        if e["owning_region_id"] and e["semantic_role"] and e["accessible_name"]:
            region=next((r for r in regions if r["region_id"]==e["owning_region_id"]),None)
            count=sum(1 for x in elements if x["owning_region_id"]==e["owning_region_id"] and
                      x["semantic_role"]==e["semantic_role"] and x["accessible_name"]==e["accessible_name"])
            add("within_region",{"region":region["accessible_name"] or region["semantic_role"] if region else e["owning_region_id"],
                "role":e["semantic_role"],"name":e["accessible_name"]},count,.86,"role/name constrained to owning region")
        return sorted(candidates,key=lambda x:(not x["unique"],-x["confidence"]))

    @staticmethod
    def _relationships(elements: list[dict[str, Any]], options: PageObservationOptions) -> list[dict[str, Any]]:
        out: list[dict[str, Any]]=[]
        for a in elements:
            candidates=[]
            for b in elements:
                if a is b or (a["owning_region_id"] != b["owning_region_id"] and a["owning_region_id"] is not None): continue
                ac,bc=a["center_px"],b["center_px"]; dx=bc["x"]-ac["x"];dy=bc["y"]-ac["y"];dist=math.hypot(dx,dy)
                if dist<=options.max_relationship_distance_px:candidates.append((dist,b,dx,dy))
            for dist,b,dx,dy in sorted(candidates,key=lambda x:x[0])[:options.max_relationships_per_element]:
                ar,br=a["bounds_px"],b["bounds_px"]; ix=max(0,min(ar["x"]+ar["width"],br["x"]+br["width"])-max(ar["x"],br["x"]))
                iy=max(0,min(ar["y"]+ar["height"],br["y"]+br["height"])-max(ar["y"],br["y"]))
                overlap=ix*iy/min(max(1,ar["width"]*ar["height"]),max(1,br["width"]*br["height"]))*100
                horizontal_gap=max(0.0,max(ar["x"],br["x"])-min(ar["x"]+ar["width"],br["x"]+br["width"]))
                vertical_gap=max(0.0,max(ar["y"],br["y"])-min(ar["y"]+ar["height"],br["y"]+br["height"]))
                types=["nearest_to"]
                if abs(dy)<=max(ar["height"],br["height"])*.5:types.append("same_row_as")
                if abs(dx)<=max(ar["width"],br["width"])*.5:types.append("same_column_as")
                if dx>0:types.append("right_of")
                elif dx<0:types.append("left_of")
                if dy>0:types.append("below")
                elif dy<0:types.append("above")
                if overlap>.01:types.append("overlaps")
                if dist<max(ar["width"],ar["height"],br["width"],br["height"])*2:types.append("adjacent_to")
                out.append({"source_element_id":a["element_id"],"target_element_id":b["element_id"],
                    "relationship_types":types,"horizontal_distance_px":horizontal_gap,"vertical_distance_px":vertical_gap,
                    "euclidean_distance_px":math.hypot(horizontal_gap,vertical_gap),"center_distance_px":dist,
                    "overlap_percentage":overlap})
        return out

    def validate_reference(self, reference: ObservationReference) -> ObservationFreshnessResult:
        obs=self._observations.get(reference.observation_id)
        if obs is None:return ObservationFreshnessResult(False,"unknown_observation")
        if self.backend.page_id != obs.freshness["page_id"] or self.backend.page.url != obs.url:
            return ObservationFreshnessResult(False,"page_navigated")
        if time.time_ns()//1_000_000-obs.captured_at_ms>obs.freshness["max_age_ms"]:
            return ObservationFreshnessResult(False,"observation_expired")
        old=next((e for e in obs.interactive_elements if e["element_id"]==reference.element_id),None)
        if old is None:return ObservationFreshnessResult(False,"unknown_element")
        raw=self.backend.page.evaluate(_VALIDATE_REFERENCE_JS,{"dom_tag":old["dom_tag"],
            "semantic_role":old["semantic_role"],"accessible_name":old["accessible_name"]})
        if raw["match_count"]!=1:return ObservationFreshnessResult(False,"element_disappeared_or_ambiguous")
        found=dict(old)
        for key in ("visible","enabled","selected","pressed"):
            found[key]=raw[key]
        for key,value in reference.expected.items():
            if found.get(key)!=value:return ObservationFreshnessResult(False,f"expected_property_changed:{key}")
        fingerprint=hashlib.sha256(raw["signature"].encode()).hexdigest()
        if fingerprint != obs.freshness["fingerprint"]:
            return ObservationFreshnessResult(True,"re_resolved_with_unrelated_dom_change",found)
        return ObservationFreshnessResult(True,"re_resolved",found)
