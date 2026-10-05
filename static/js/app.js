'use strict';
const csrf = () => document.body.dataset.csrf;
const toast = (text, error = false) => {
  const node = document.querySelector('#toast');
  node.textContent = text;
  node.classList.toggle('error', error);
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, 6500);
};
async function post(url, values = {}) {
  const body = values instanceof FormData ? new URLSearchParams(values) : new URLSearchParams(values);
  body.set('csrf', csrf());
  const response = await fetch(url, {method:'POST', body, signal:AbortSignal.timeout(15000)});
  const data = await response.json().catch(() => ({error:'Não foi possível concluir. Atualize a página e tente novamente.'}));
  if (!response.ok) throw new Error(data.error || 'Não foi possível salvar.');
  return data;
}

const settings = document.querySelector('#settings-form');
settings?.addEventListener('input', () => {
  document.querySelector('#save-hint').textContent = 'Há alterações para salvar.';
});
const presets = {
  present: {idle_minutes:3, change_seconds:30, cooldown_minutes:5, checkin_minutes:20, snooze_minutes:5, max_prompts_hour:6},
  balanced: {idle_minutes:5, change_seconds:60, cooldown_minutes:10, checkin_minutes:40, snooze_minutes:10, max_prompts_hour:4},
  quiet: {idle_minutes:8, change_seconds:120, cooldown_minutes:20, checkin_minutes:60, snooze_minutes:15, max_prompts_hour:2}
};
document.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => {
  Object.entries(presets[button.dataset.preset]).forEach(([key,value]) => { settings.elements[key].value = value; });
  document.querySelectorAll('[data-preset]').forEach(item => item.classList.toggle('selected', item === button));
  settings.dispatchEvent(new Event('input'));
}));

const dialog = document.querySelector('#activity-dialog');
const form = document.querySelector('#activity-form');
let step = 'choice', options = {current:null, recent:[], suggestions:{}}, saving = false;
const descriptions = {
  choice:['O que vamos registrar?','Um passo pequeno para dar contexto ao seu dia.','SEU MOMENTO'],
  category:['Qual é o contexto?','Escolha a categoria da sua próxima atividade.','01 / CATEGORIA'],
  details:['O que você vai fazer?','Descreva a tarefa real, do seu jeito.','02 / ATIVIDADE'],
  recent:['De onde vamos continuar?','Retome uma atividade sem perder o histórico.','RETOMAR'],
  note:['O que avançou?','Pode ser uma frase. Registre o que fez e como fez.','01 / AVANÇO'],
  results:['Como foi o resultado?','Registre as novas tentativas desta atualização.','02 / RESULTADO']
};
function go(next) {
  step = next;
  dialog.querySelectorAll('[data-step]').forEach(node => { node.hidden = node.dataset.step !== step; });
  const [title, description, progress] = descriptions[step];
  document.querySelector('#dialog-title').textContent = title;
  document.querySelector('#dialog-description').textContent = description;
  document.querySelector('#dialog-progress').textContent = progress;
  const submit = document.querySelector('#dialog-submit');
  submit.hidden = !['details','note','results'].includes(step);
  submit.textContent = step === 'details' ? 'Começar atividade →' : step === 'note' ? 'Salvar e continuar →' : 'Salvar resultado →';
  document.querySelector('#dialog-back').textContent = step === 'choice' ? 'Agora não' : '← Voltar';
  document.querySelector('#dialog-error').hidden = true;
  dialog.querySelector('.dialog-body').scrollTop = 0;
  requestAnimationFrame(() => dialog.querySelector('[data-step="'+step+'"] input:not([type=hidden]), [data-step="'+step+'"] textarea, [data-step="'+step+'"] button')?.focus());
}
function choice(title, subtitle, action) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'choice-card';
  const strong = document.createElement('strong'), small = document.createElement('small');
  strong.textContent = title; small.textContent = subtitle;
  button.append(strong, small); button.addEventListener('click', action);
  return button;
}
function updateActivity(id) {
  const item = options.recent.find(item => item.id === Number(id));
  if (!item) { toast('A atividade não foi encontrada. Atualize o painel.', true); return; }
  form.elements.action.value = 'continue';
  form.elements.activity_id.value = item.id;
  document.querySelector('#update-context').textContent = item.title;
  document.querySelector('#complete-option').hidden = !(options.current?.kind === 'active' && options.current.activity_id === item.id);
  document.querySelector('#activity-complete').checked = false;
  go('note');
}
async function openDialog(intent = 'choice', activityId) {
  if (!dialog || dialog.open) return;
  form.reset();
  document.querySelector('#activity-objective').value = '';
  try {
    const response = await fetch('/atividade/opcoes' + (activityId ? '?activity_id='+encodeURIComponent(activityId) : ''), {cache:'no-store', signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('Não foi possível carregar suas atividades.');
    options = await response.json();
  } catch (error) { toast(error.message, true); return; }
  for (const key of ['client','project']) {
    const list = document.querySelector('#'+key+'-suggestions');
    list.replaceChildren(...(options.suggestions[key] || []).map(value => { const o=document.createElement('option'); o.value=value; return o; }));
  }
  const recent = document.querySelector('#recent-activities');
  recent.replaceChildren(...options.recent.map(item => choice(item.title, [item.client,item.project,item.category].filter(Boolean).join(' · '), () => updateActivity(item.id))));
  if (!options.recent.length) { const p=document.createElement('p'); p.textContent='Ainda não há atividades. Comece uma nova para criar seu histórico.'; recent.append(p); }
  const current = document.querySelector('#current-choice');
  current.replaceChildren();
  if (options.current?.kind === 'active') {
    current.append(choice('Continuo na mesma', options.current.title, () => quick('continue', options.current.activity_id)));
    current.append(choice('Registrar avanço ou concluir', 'Acrescentar contexto e resultado.', () => updateActivity(options.current.activity_id)));
  }
  dialog.showModal();
  if (intent === 'start') go('category');
  else if (intent === 'continue' && (activityId || options.current?.activity_id)) updateActivity(activityId || options.current.activity_id);
  else go('choice');
}
function showError(error) {
  const target = document.querySelector('#dialog-error');
  target.textContent = error.message; target.hidden = false;
  dialog.querySelector('.dialog-body').scrollTop = 0;
}
async function quick(action, id) {
  if (saving) return;
  saving = true;
  try {
    await post('/atividade/registrar', {action, activity_id:id || ''});
    dialog.close(); toast(action === 'idle' ? 'Pausa iniciada.' : 'Foco confirmado. O contador continua.');
    await refreshPanel(true);
  } catch (error) { showError(error); }
  finally { saving = false; }
}
dialog?.querySelector('.dialog-close').addEventListener('click', () => { if (!saving) dialog.close(); });
dialog?.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
dialog?.addEventListener('click', event => {
  if (saving) return;
  const category = event.target.closest('[data-category]');
  const next = event.target.closest('[data-step-to]');
  const quickButton = event.target.closest('[data-quick-action]');
  if (category) {
    form.elements.action.value = 'start';
    form.elements.category.value = category.dataset.category;
    document.querySelector('#work-fields').hidden = category.dataset.category !== 'trabalho';
    go('details');
  } else if (next) go(next.dataset.stepTo);
  else if (quickButton) quick(quickButton.dataset.quickAction);
});
document.querySelector('#dialog-back')?.addEventListener('click', () => {
  if (saving) return;
  if (step === 'choice') dialog.close();
  else go({details:'category',results:'note',category:'choice',recent:'choice',note:'choice'}[step]);
});
form?.addEventListener('submit', async event => {
  event.preventDefault();
  if (saving || !['details','note','results'].includes(step)) return;
  const values = new FormData(form);
  if (step === 'details') values.set('note', document.querySelector('#activity-objective').value);
  if (step !== 'results') {
    ['attempts','successes','failures'].forEach(key => values.set(key,'0'));
    ['reason','result'].forEach(key => values.set(key,''));
  } else if (document.querySelector('#activity-complete').checked && !document.querySelector('#complete-option').hidden) {
    values.set('action','complete');
  }
  saving = true;
  const submit = document.querySelector('#dialog-submit');
  submit.disabled = true; submit.textContent = 'Salvando…';
  try {
    await post('/atividade/registrar', values);
    dialog.close(); toast('Registro salvo no dispositivo.');
    await refreshPanel(true);
  } catch (error) { showError(error); }
  finally { saving=false; submit.disabled=false; submit.textContent='Salvar →'; }
});

document.addEventListener('click', async event => {
  const register = event.target.closest('.web-register');
  if (register) { await openDialog(register.dataset.intent, register.dataset.activityId); return; }
  const native = event.target.closest('.popup-trigger');
  if (native) {
    native.disabled = true;
    try { await post('/atividade/popup'); toast('Janela solicitada. Se ela não aparecer, registre pelo painel.'); }
    catch (_) { toast('Vamos registrar pelo painel.'); await openDialog(); }
    finally { native.disabled = false; }
  }
  const snooze = event.target.closest('.snooze-button');
  if (snooze) {
    try { await post('/atividade/adiar'); toast('Sugestões silenciadas por 30 minutos.'); await refreshPanel(true); }
    catch(error) { toast(error.message,true); }
  }
  const shutdown = event.target.closest('.shutdown-button');
  if (shutdown && confirm('Encerrar o CPreta? O tempo da atividade atual será preservado.')) {
    try { await post('/sistema/encerrar'); toast('CPreta encerrado. Use o iniciador para abrir novamente.'); updateConnection(false); }
    catch(error) { toast(error.message,true); }
  }
});

function filterActivities() {
  const term=(document.querySelector('#activity-search')?.value || '').toLocaleLowerCase('pt-BR');
  const category=document.querySelector('#category-filter')?.value || '';
  const rows=[...document.querySelectorAll('.activity-detail')];
  rows.forEach(row => { row.hidden = !row.dataset.search.toLocaleLowerCase('pt-BR').includes(term) || Boolean(category && row.dataset.category !== category); });
  const empty=document.querySelector('.no-results');
  if (empty) empty.hidden=!rows.length || rows.some(row => !row.hidden);
}
document.addEventListener('input',event => {
  if (['activity-search','category-filter'].includes(event.target.id)) filterActivities();
});
function updateConnection(connected) {
  const node=document.querySelector('#connection-status');
  node.classList.toggle('offline',!connected);
  node.replaceChildren();
  node.append(document.createElement('i'), document.createTextNode(connected ? 'Neste dispositivo' : 'Sem conexão · reabra o CPreta'));
}
let refreshing=false;
async function refreshPanel(force=false) {
  const panel=document.querySelector('.activity-dashboard');
  if (!panel || refreshing || (!force && (document.hidden || dialog?.open || panel.contains(document.activeElement) || window.getSelection()?.toString()))) return;
  refreshing=true;
  try {
    const response=await fetch('/relatorios/painel?period='+panel.dataset.period, {cache:'no-store',signal:AbortSignal.timeout(8000)});
    if (!response.ok) throw new Error('offline');
    const html=await response.text();
    const next=new DOMParser().parseFromString(html,'text/html').querySelector('.activity-dashboard');
    if (!next) throw new Error('offline');
    const expanded=new Set([...panel.querySelectorAll('details[open]')].map(item=>item.dataset.id));
    const search=panel.querySelector('#activity-search')?.value || '';
    const category=panel.querySelector('#category-filter')?.value || '';
    next.querySelectorAll('details').forEach(item=>{item.open=expanded.has(item.dataset.id);});
    next.querySelector('#activity-search').value=search;
    next.querySelector('#category-filter').value=category;
    panel.replaceWith(next);
    filterActivities(); startClocks(); updateConnection(true);
  } catch (_) { updateConnection(false); }
  finally { refreshing=false; }
}
function startClocks() {
  document.querySelectorAll('[data-elapsed]').forEach(node => { node.dataset.since=Date.now(); });
}
startClocks();
setInterval(() => {
  document.querySelectorAll('[data-elapsed]').forEach(node => {
    const seconds=Math.max(0,Number(node.dataset.elapsed)+Math.floor((Date.now()-Number(node.dataset.since))/1000));
    const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;
    node.textContent=(h ? String(h).padStart(2,'0')+':' : '')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
  });
},1000);
setInterval(()=>refreshPanel(),15000);
