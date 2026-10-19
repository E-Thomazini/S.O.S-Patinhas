(()=>{
  const root=document.documentElement;
  const theme=document.getElementById('theme-btn');
  const apply=()=>{if(theme){theme.textContent=root.dataset.theme==='dark'?'☀':'☾';theme.setAttribute('aria-label',root.dataset.theme==='dark'?'Ativar modo claro':'Ativar modo escuro')}};
  apply();
  theme?.addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem('sos-theme',root.dataset.theme)}catch{}apply()});
  const menu=document.getElementById('menu-btn');const nav=document.getElementById('main-nav');
  menu?.addEventListener('click',()=>{const expanded=nav.classList.toggle('open');menu.setAttribute('aria-expanded',String(expanded))});
  document.querySelectorAll('[data-mask]').forEach(el=>el.addEventListener('input',()=>{
    const num=el.value.replace(/\D/g,'');
    if(el.dataset.mask==='cpf')el.value=num.slice(0,11).replace(/^(\d{3})(\d)/,'$1.$2').replace(/^(\d{3})\.(\d{3})(\d)/,'$1.$2.$3').replace(/\.(\d{3})(\d)/,'.$1-$2');
    if(el.dataset.mask==='cep')el.value=num.slice(0,8).replace(/^(\d{5})(\d)/,'$1-$2');
    if(el.dataset.mask==='phone')el.value=num.slice(0,11).replace(/^(\d{2})(\d)/,'($1) $2').replace(/(\d{4,5})(\d{4})$/,'$1-$2');
  }));
  document.querySelectorAll('[data-confirm]').forEach(el=>el.addEventListener('click',e=>{if(!confirm(el.dataset.confirm))e.preventDefault()}));
  const kind=document.getElementById('donation-kind');const fin=document.getElementById('donation-fin');const mat=document.getElementById('donation-mat');
  const toggle=()=>{if(kind&&fin&&mat){fin.hidden=kind.value!=='Financeira';mat.hidden=kind.value!=='Material'}};
  kind?.addEventListener('change',toggle);toggle();
  document.querySelectorAll('[data-copy-target]').forEach(btn=>btn.addEventListener('click',async()=>{
    const id=btn.getAttribute('data-copy-target'); const el=id?document.getElementById(id):null;
    const text=(el?.textContent||'').trim(); if(!text) return;
    try{await navigator.clipboard.writeText(text); const old=btn.textContent; btn.textContent='Copiado!'; setTimeout(()=>btn.textContent=old,1600)}catch{}}));
  const filters=document.getElementById('report-filters');
  const refreshExports=()=>{if(!filters)return;const params=new URLSearchParams(new FormData(filters));for(const [key,val] of [...params])if(!val)params.delete(key);document.querySelectorAll('[data-report-url]').forEach(link=>{link.href=link.dataset.reportUrl+(params.size?'?'+params.toString():'')})};
  filters?.addEventListener('input',refreshExports);filters?.addEventListener('change',refreshExports);
})();
