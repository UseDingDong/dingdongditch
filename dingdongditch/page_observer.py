"""Bounded DOM/accessibility/geometry observation; contains no planning logic."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dingdongditch.contract.observation import (
    CandidateEvidenceLevel,
    LocatorAttestation,
    LocatorAttestationStatus,
    ObservationCommit,
    ObservationEvidenceView,
    ObservationFreshnessResult,
    ObservationReference,
    ObservationTransactionEvidence,
    ObservationTransactionState,
    PageObservation,
    PageObservationOptions,
    SnapshotCore,
)
from dingdongditch.runtime.publication import (
    PublicationUnavailableError,
    publish_json,
    read_published_json,
)


_SNAPSHOT_JS = r"""
(limits) => {
  if (!window.__dddObservationEpoch) {
    window.__dddObservationEpoch={value:0};
    new MutationObserver(()=>window.__dddObservationEpoch.value++)
      .observe(document,{subtree:true,childList:true,attributes:true,characterData:true});
  }
  if (!window.__dddObservationDocumentId) {
    window.__dddObservationDocumentId =
      (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID() :
      `${Date.now()}-${Math.random()}`;
    window.__dddObservationNodeTokens = new WeakMap();
    window.__dddObservationNodeCounter = 0;
  }
  const nodeToken = e => {
    if (!window.__dddObservationNodeTokens.has(e)) {
      window.__dddObservationNodeTokens.set(
        e,
        `${window.__dddObservationDocumentId}:${++window.__dddObservationNodeCounter}`
      );
    }
    return window.__dddObservationNodeTokens.get(e);
  };
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
    return {_node:e,element_id:`el_${i+1}`,node_continuity_token:nodeToken(e),dom_tag:e.tagName.toLowerCase(),semantic_role:rr,
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
  const matches=nodes.filter(e=>e.tagName.toLowerCase()===identity.dom_tag&&
    role(e)===identity.semantic_role&&
    (identity.accessible_name===null||name(e)===identity.accessible_name)&&
    (identity.placeholder===null||e.getAttribute('placeholder')===identity.placeholder));
  const root=document.documentElement,body=document.body;
  const matchedToken = matches.length===1 && window.__dddObservationNodeTokens
    ? window.__dddObservationNodeTokens.get(matches[0]) || null : null;
  return {match_count:matches.length,node_continuity_token:matchedToken,
    visible:matches.length===1?visible(matches[0]):null,
    enabled:matches.length===1?!(matches[0].disabled||matches[0].getAttribute('aria-disabled')==='true'):null,
    selected:matches.length===1?(('selected'in matches[0])?!!matches[0].selected:
      (matches[0].hasAttribute('aria-selected')?matches[0].getAttribute('aria-selected')==='true':null)):null,
    pressed:matches.length===1?(matches[0].hasAttribute('aria-pressed')?matches[0].getAttribute('aria-pressed')==='true':null):null,
    signature:[location.href,document.title,root.childElementCount,document.querySelectorAll('*').length,
      root.scrollWidth,root.scrollHeight,
      window.__dddObservationEpoch ? window.__dddObservationEpoch.value : -1].join('|')};
}
"""

_WAIT_FOR_MUTATION_QUIESCENCE_JS = r"""
({quietMs, budgetMs}) => new Promise((resolve, reject) => {
  let quietTimer;
  let budgetTimer;
  let observer;
  const cleanup = () => {
    if (quietTimer) clearTimeout(quietTimer);
    if (budgetTimer) clearTimeout(budgetTimer);
    if (observer) observer.disconnect();
  };
  const settled = () => { cleanup(); resolve({quiescent: true}); };
  const armQuiet = () => {
    if (quietTimer) clearTimeout(quietTimer);
    quietTimer = setTimeout(settled, quietMs);
  };
  observer = new MutationObserver(armQuiet);
  observer.observe(document, {
    subtree: true, childList: true, attributes: true, characterData: true
  });
  budgetTimer = setTimeout(() => {
    cleanup();
    reject(new Error('observation_budget_exceeded_before_quiescence'));
  }, budgetMs);
  armQuiet();
})
"""


class PageObserver:
    def __init__(self, backend: Any):
        self.backend = backend
        self._observations: dict[str, PageObservation] = {}
        self._commits: dict[str, ObservationCommit] = {}
        self._attestations: dict[str, LocatorAttestation] = {}
        self._transactions: dict[str, ObservationTransactionEvidence] = {}
        store = getattr(backend, "observation_store_root", None)
        self._store_root = Path(store) if store is not None else None
        self._load_durable_commits()

    def observe_page(self, options: PageObservationOptions | None = None) -> PageObservation:
        options = options or PageObservationOptions()
        options.validate()
        if not self.backend.is_started:
            raise RuntimeError("page observation requires an active backend")
        transaction_id = str(uuid.uuid4())
        started = time.time_ns() // 1_000_000
        binding = self._browser_binding()
        states = [
            ObservationTransactionState.REQUESTED.value,
            ObservationTransactionState.BINDING.value,
            ObservationTransactionState.CAPTURING.value,
        ]
        try:
            observation = self._capture_once(
                options, transaction_id=transaction_id, browser_binding=binding,
                transaction_states=states,
            )
            return observation
        except Exception as exc:
            states.extend([
                ObservationTransactionState.ABORTING.value,
                ObservationTransactionState.ABORTED.value,
            ])
            self._transactions[transaction_id] = ObservationTransactionEvidence(
                transaction_id=transaction_id,
                state=ObservationTransactionState.ABORTED,
                states=states,
                browser_binding=binding,
                started_at_ms=started,
                completed_at_ms=time.time_ns() // 1_000_000,
                failure_kind=type(exc).__name__,
                failure_message=str(exc),
            )
            raise

    def _browser_binding(self) -> dict[str, Any]:
        return {
            "backend_identity": getattr(self.backend, "backend_identity", None),
            "browser_identity": getattr(self.backend, "browser_identity", None),
            "browser_session_id": getattr(self.backend, "browser_session_id", None),
            "session_identity": getattr(self.backend, "browser_session_id", None),
            "context_id": getattr(self.backend, "context_id", None),
            "page_id": getattr(self.backend, "page_id", None),
            "backend_generation": getattr(self.backend, "_generation", None),
            "binding_generation": getattr(self.backend, "_generation", None),
        }

    @staticmethod
    def _binding_identity(binding: Any) -> tuple[Any, ...]:
        return tuple(binding.get(key) for key in (
            "backend_identity", "browser_identity", "session_identity",
            "context_id", "page_id", "binding_generation",
        ))

    def _commit_path(self, commit_id: str) -> Path:
        assert self._store_root is not None
        return self._store_root / f"{commit_id}.json"

    @staticmethod
    def _verify_observation_hash(observation: PageObservation) -> bool:
        values = observation.to_dict()
        expected = values.get("observation_hash")
        values["observation_hash"] = ""
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest() == expected

    def _publish_durable_commit(
        self, observation: PageObservation, commit: ObservationCommit
    ) -> None:
        if self._store_root is None:
            return
        publish_json(
            self._commit_path(commit.commit_id),
            {
                "schema_version": "1.0.0",
                "observation": observation.to_dict(),
                "commit": commit.to_dict(),
            },
            sort_keys=True,
        )

    def _load_durable_commits(self) -> None:
        if self._store_root is None or not self._store_root.exists():
            return
        for path in sorted(self._store_root.glob("*.json")):
            try:
                payload = read_published_json(path)
                observation = PageObservation.from_dict(payload["observation"])
                raw_commit = dict(payload["commit"])
                raw_commit["state"] = ObservationTransactionState(raw_commit["state"])
                commit = ObservationCommit(**raw_commit)
                if (
                    payload.get("schema_version") != "1.0.0"
                    or path.stem != commit.commit_id
                    or commit.observation_id != observation.observation_id
                    or commit.commit_id != observation.commit_id
                    or commit.observation_hash != observation.observation_hash
                    or self._binding_identity(commit.browser_binding)
                    != self._binding_identity(commit.evidence["snapshot_core"]["browser_binding"])
                    or not self._verify_observation_hash(observation)
                ):
                    continue
                # Durable evidence from another browser generation remains on
                # disk, but is not admitted as live composable state.
                if self._binding_identity(commit.browser_binding) != self._binding_identity(
                    self._browser_binding()
                ):
                    continue
            except (KeyError, TypeError, ValueError, PublicationUnavailableError):
                continue
            self._observations[observation.observation_id] = observation
            self._commits[observation.observation_id] = commit

    def _capture_once(
        self,
        options: PageObservationOptions,
        *,
        transaction_id: str | None = None,
        browser_binding: dict[str, Any] | None = None,
        transaction_states: list[str] | None = None,
    ) -> PageObservation:
        options.validate()
        transaction_id = transaction_id or str(uuid.uuid4())
        browser_binding = browser_binding or self._browser_binding()
        states = transaction_states if transaction_states is not None else [
            ObservationTransactionState.REQUESTED.value,
            ObservationTransactionState.BINDING.value,
            ObservationTransactionState.CAPTURING.value,
        ]
        started = time.time_ns() // 1_000_000
        budget_started = time.monotonic_ns() // 1_000_000
        deadline = budget_started + options.observation_budget_ms

        def require_budget(phase: str) -> int:
            remaining = deadline - (time.monotonic_ns() // 1_000_000)
            if remaining <= 0:
                raise TimeoutError(f"observation_budget_exceeded:{phase}")
            return remaining

        self.backend.page.evaluate(
            _WAIT_FOR_MUTATION_QUIESCENCE_JS,
            {
                "quietMs": options.mutation_quiescence_ms,
                "budgetMs": require_budget("quiescence"),
            },
        )
        require_budget("capture")
        raw = self.backend.page.evaluate(_SNAPSHOT_JS, {
            "maxElements": options.max_interactive_elements,
            "maxTextBlocks": options.max_text_blocks,
            "maxRegions": options.max_regions,
            "maxScrollables": options.max_scrollable_containers,
            "maxTextLength": options.max_text_length,
        })
        if not isinstance(raw, dict) or not isinstance(raw.get("signature"), str):
            raise ValueError("atomic snapshot returned an invalid capture envelope")
        require_budget("validation")
        states.append(ObservationTransactionState.VALIDATING.value)
        snapshot_id = str(uuid.uuid4())
        snapshot_payload = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        snapshot_hash = hashlib.sha256(snapshot_payload.encode()).hexdigest()
        states.append(ObservationTransactionState.DERIVING.value)
        for element in raw["elements"]:
            element["locator_candidates"] = self._locator_candidates(element, raw["elements"], raw["regions"])
        relationships = self._relationships(raw["elements"], options)
        require_budget("derivation")
        observation_id = str(uuid.uuid4())
        commit_id = str(uuid.uuid4())
        captured = time.time_ns() // 1_000_000
        fingerprint = hashlib.sha256(raw["signature"].encode()).hexdigest()
        diagnostics = {
            "capture_duration_ms": captured - started,
            "timing": {
                "observation_budget_ms": options.observation_budget_ms,
                "mutation_quiescence_ms": options.mutation_quiescence_ms,
                "quiescence_enforced": True,
                "budget_enforced_before_publication": True,
            },
            "truncated": {
                "interactive_elements": raw["totalElements"] > len(raw["elements"]),
                "regions": raw["totalRegions"] > len(raw["regions"]),
                "visible_text": raw["textLimitReached"],
                "relationships": False,
                "payload": False,
            },
            "counts_before_limits": {"interactive_elements": raw["totalElements"], "regions": raw["totalRegions"]},
            "evidence_sources": ["DOM", "ARIA", "accessible-name rules", "computed visibility", "bounding geometry", "hit testing"],
            "transaction": {
                "transaction_id": transaction_id,
                "state": ObservationTransactionState.COMMITTED.value,
                "states": states + [
                    ObservationTransactionState.SEALED.value,
                    ObservationTransactionState.COMMITTED.value,
                ],
                "capture_mode": "atomic_snapshot_core",
                "locator_attestation_boundary": "independent",
                "observation_budget_ms": options.observation_budget_ms,
            },
        }
        scroll = {
            **raw["document"], "viewport_width": raw["viewport"]["width"], "viewport_height": raw["viewport"]["height"],
            "can_scroll_up": raw["document"]["scroll_y"] > 0,
            "can_scroll_down": raw["document"]["scroll_y"] + raw["viewport"]["height"] < raw["document"]["height"],
            "scrollable_containers": raw["scrollables"],
        }
        observation_values = dict(
            observation_id=observation_id, timestamp=datetime.now(timezone.utc).isoformat(),
            captured_at_ms=captured, browser_profile=self.backend.browser_config.profile.value,
            url=raw["url"], title=raw["title"], viewport=raw["viewport"], document=raw["document"],
            focus=raw["focus"], overlays=raw["overlays"], regions=raw["regions"],
            visible_text=raw["textBlocks"], interactive_elements=raw["elements"],
            spatial_relationships=relationships, scroll_context=scroll,
            freshness={"fingerprint": fingerprint, "max_age_ms": options.freshness_max_age_ms,
                       "page_id": self.backend.page_id, "captured_at_ms": captured},
            diagnostics=diagnostics, transaction_id=transaction_id,
            snapshot_id=snapshot_id, commit_id=commit_id, observation_hash="")
        while len(json.dumps(observation_values, ensure_ascii=False).encode()) > options.max_payload_bytes:
            diagnostics["truncated"]["payload"] = True
            if observation_values["visible_text"]: observation_values["visible_text"].pop()
            elif observation_values["spatial_relationships"]: observation_values["spatial_relationships"].pop()
            elif observation_values["interactive_elements"]: observation_values["interactive_elements"].pop()
            else: break
        hash_payload = json.dumps(observation_values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        observation_hash = hashlib.sha256(hash_payload.encode()).hexdigest()
        observation_values["observation_hash"] = observation_hash
        states.append(ObservationTransactionState.SEALED.value)
        obs = PageObservation(**observation_values)
        require_budget("publication")
        committed_at = time.time_ns() // 1_000_000
        snapshot_core = SnapshotCore(
            snapshot_id=snapshot_id, transaction_id=transaction_id,
            captured_at_ms=captured, browser_binding=browser_binding,
            signature=raw["signature"], payload_hash=snapshot_hash,
            capture_evidence={"mode": "single_browser_evaluation", "complete": True},
        )
        commit = ObservationCommit(
            commit_id=commit_id, transaction_id=transaction_id,
            observation_id=observation_id, snapshot_id=snapshot_id,
            observation_hash=observation_hash, committed_at_ms=committed_at,
            state=ObservationTransactionState.COMMITTED,
            browser_binding=browser_binding,
            evidence={"snapshot_core": snapshot_core.to_dict()},
        )
        # The durable bundle is the publication point.  Only a complete,
        # atomically replaced observation+commit pair becomes visible.
        self._publish_durable_commit(obs, commit)
        self._observations[observation_id] = obs
        self._commits[observation_id] = commit
        states.append(ObservationTransactionState.COMMITTED.value)
        self._transactions[transaction_id] = ObservationTransactionEvidence(
            transaction_id=transaction_id,
            state=ObservationTransactionState.COMMITTED,
            states=states,
            browser_binding=browser_binding,
            started_at_ms=started,
            completed_at_ms=committed_at,
        )
        if len(self._observations) > 20:
            expired_id = next(iter(self._observations))
            self._observations.pop(expired_id)
            self._commits.pop(expired_id, None)
        return obs

    def _verify_locator_candidates(self, candidates: list[dict[str, Any]]) -> None:
        """Use the execution resolver's primitives to attest advertised cardinality."""
        for candidate in candidates:
            count, failure = self._query_locator_candidate(candidate)
            if count is None and failure is None:
                continue
            self._apply_locator_attestation(candidate, count, failure)
        candidates.sort(key=lambda item: (not item["unique"], -item["confidence"]))

    def _query_locator_candidate(
        self, candidate: dict[str, Any]
    ) -> tuple[int | None, str | None]:
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
                region = self.backend.page.get_by_role(
                    value["region_role"],
                    name=value["region_name"],
                    exact=True,
                ) if value.get("region_name") else self.backend.page.get_by_role(
                    value["region_role"]
                )
                count = region.get_by_role(
                    value["role"], name=value["name"], exact=True
                ).count()
            else:
                return None, None
        except Exception as exc:
            return None, type(exc).__name__
        return count, None

    @staticmethod
    def _apply_locator_attestation(
        candidate: dict[str, Any], count: int | None, failure: str | None
    ) -> None:
        if failure is not None:
            candidate.update({
                "match_count": None, "unique": False, "confidence": 0.0,
                "known_ambiguity": f"cardinality check failed: {failure}",
            })
            return
        candidate["match_count"] = count
        candidate["unique"] = count == 1
        if count != 1:
            candidate["confidence"] = min(candidate["confidence"], .45)
            candidate["known_ambiguity"] = f"{count} matching elements"

    @staticmethod
    def _locator_query_key(candidate: dict[str, Any]) -> tuple[Any, ...] | None:
        kind = candidate["locator_type"]
        value = candidate["locator_value"]
        if kind == "role_name":
            return ("role_name", value["role"], value["name"], True)
        if kind == "within_region":
            return (
                "within_region", value["region_role"], value.get("region_name"),
                value["role"], value["name"], True,
            )
        if kind in {"exact_text", "test_id", "css"}:
            return (kind, json.dumps(value, ensure_ascii=False, sort_keys=True))
        return None

    @staticmethod
    def _playwright_region_role(role: str) -> str:
        return {
            "header": "banner",
            "section": "region",
            "footer": "contentinfo",
            "aside": "complementary",
        }.get(role, role)

    def attest_observation_locators(
        self, observation_id: str
    ) -> tuple[LocatorAttestation, ...]:
        """Collect immutable locator evidence outside the observation transaction."""
        observation = self._observations.get(observation_id)
        commit = self._commits.get(observation_id)
        if observation is None or commit is None:
            raise KeyError(f"unknown observation: {observation_id}")
        binding = self._browser_binding()
        if (
            observation.commit_id != commit.commit_id
            or observation.observation_hash != commit.observation_hash
            or self._binding_identity(binding)
            != self._binding_identity(commit.browser_binding)
        ):
            raise RuntimeError("observation_attestation_binding_mismatch")
        records: list[LocatorAttestation] = []
        query_results: dict[
            tuple[Any, ...], tuple[int | None, str | None, str]
        ] = {}
        for element in observation.interactive_elements:
            for published in element["locator_candidates"]:
                query_key = self._locator_query_key(published)
                if query_key is None:
                    continue
                candidate = dict(published)
                query_reused = query_key in query_results
                if query_reused:
                    count, failure, query_id = query_results[query_key]
                else:
                    count, failure = self._query_locator_candidate(candidate)
                    query_id = str(uuid.uuid4())
                    query_results[query_key] = (count, failure, query_id)
                self._apply_locator_attestation(candidate, count, failure)
                if candidate["match_count"] is None:
                    status = LocatorAttestationStatus.ATTESTATION_FAILED
                elif candidate["match_count"] == 0:
                    status = LocatorAttestationStatus.ATTESTED_MISSING
                elif candidate["match_count"] == 1:
                    status = LocatorAttestationStatus.ATTESTED_UNIQUE
                else:
                    status = LocatorAttestationStatus.ATTESTED_AMBIGUOUS
                evidence = {
                    "observation_id": observation_id,
                    "commit_id": commit.commit_id,
                    "candidate_id": candidate["candidate_id"],
                    "element_id": element["element_id"],
                    "locator_type": candidate["locator_type"],
                    "locator_value": candidate["locator_value"],
                    "match_count": candidate["match_count"],
                    "unique": candidate["unique"],
                    "status": status.value,
                    "query_id": query_id,
                    "query_reused": query_reused,
                    "browser_binding": binding,
                }
                evidence_hash = hashlib.sha256(json.dumps(
                    evidence, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ).encode()).hexdigest()
                record = LocatorAttestation(
                    attestation_id=str(uuid.uuid4()),
                    query_id=query_id, query_reused=query_reused,
                    observation_id=observation_id,
                    commit_id=commit.commit_id,
                    candidate_id=candidate["candidate_id"],
                    element_id=element["element_id"],
                    locator_type=candidate["locator_type"],
                    locator_value=candidate["locator_value"],
                    attested_at_ms=time.time_ns() // 1_000_000,
                    browser_binding=binding,
                    match_count=candidate["match_count"],
                    unique=candidate["unique"],
                    status=status,
                    confidence=candidate["confidence"],
                    known_ambiguity=candidate["known_ambiguity"],
                    evidence_hash=evidence_hash,
                )
                self._attestations[record.attestation_id] = record
                records.append(record)
        return tuple(records)

    def evidence_view(
        self,
        observation_id: str,
        *,
        freshness: ObservationFreshnessResult | None = None,
    ) -> ObservationEvidenceView:
        observation = self._observations.get(observation_id)
        commit = self._commits.get(observation_id)
        if observation is None or commit is None:
            raise KeyError(f"unknown observation: {observation_id}")
        attestations = tuple(
            record for record in self._attestations.values()
            if record.observation_id == observation_id
        )
        for record in attestations:
            if (
                record.commit_id != commit.commit_id
                or self._binding_identity(record.browser_binding)
                != self._binding_identity(commit.browser_binding)
            ):
                raise RuntimeError("observation_attestation_binding_mismatch")
        return ObservationEvidenceView(
            observation=observation, commit=commit,
            attestations=attestations, freshness=freshness,
        )

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
            add("within_region",{
                "region":region["accessible_name"] or region["semantic_role"] if region else e["owning_region_id"],
                "region_role":PageObserver._playwright_region_role(
                    region["semantic_role"] if region else "region"
                ),
                "region_name":region["accessible_name"] if region else None,
                "role":e["semantic_role"],"name":e["accessible_name"]},count,.86,"role/name constrained to owning region")
        ordered = sorted(candidates,key=lambda x:(not x["unique"],-x["confidence"]))
        for index, candidate in enumerate(ordered, 1):
            candidate["candidate_id"] = f"{e['element_id']}:candidate_{index}"
            candidate["snapshot_match_count"] = candidate["match_count"]
            candidate["snapshot_unique"] = candidate["unique"]
            candidate["evidence_level"] = (
                CandidateEvidenceLevel.SNAPSHOT_UNIQUE.value
                if candidate["unique"] else CandidateEvidenceLevel.DERIVED.value
            )
            candidate["attestation_status"] = "not_present"
        return ordered

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
        commit=self._commits.get(reference.observation_id)
        def result(fresh: bool, reason: str, element: dict[str, Any] | None = None) -> ObservationFreshnessResult:
            return ObservationFreshnessResult(
                fresh, reason, element,
                commit_id=commit.commit_id if commit else None,
                observation_hash=commit.observation_hash if commit else None,
            )
        if obs is None:return result(False,"unknown_observation")
        if self.backend.page_id != obs.freshness["page_id"] or self.backend.page.url != obs.url:
            return result(False,"page_navigated")
        if time.time_ns()//1_000_000-obs.captured_at_ms>obs.freshness["max_age_ms"]:
            return result(False,"observation_expired")
        old=next((e for e in obs.interactive_elements if e["element_id"]==reference.element_id),None)
        if old is None:return result(False,"unknown_element")
        continuity_token = old.get("node_continuity_token")
        if not continuity_token:return result(False,"node_continuity_unavailable")
        raw=self.backend.page.evaluate(_VALIDATE_REFERENCE_JS,{"dom_tag":old["dom_tag"],
            "semantic_role":old["semantic_role"],"accessible_name":old["accessible_name"],
            "placeholder":old["placeholder"]})
        if raw["match_count"]!=1:return result(False,"element_disappeared_or_ambiguous")
        if raw.get("node_continuity_token") != continuity_token:
            return result(False,"element_replaced")
        found=dict(old)
        for key in ("visible","enabled","selected","pressed"):
            found[key]=raw[key]
        for key,value in reference.expected.items():
            if found.get(key)!=value:return result(False,f"expected_property_changed:{key}")
        fingerprint=hashlib.sha256(raw["signature"].encode()).hexdigest()
        if fingerprint != obs.freshness["fingerprint"]:
            return result(True,"same_node_with_unrelated_dom_change",found)
        return result(True,"same_dom_node",found)
