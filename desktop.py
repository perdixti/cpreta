"""Native conversation. No global mouse hooks, grabs or cursor operations."""
import json
import logging
import queue
import time
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont
import webbrowser
from activities import CATEGORIES
from attention import AttentionPolicy, Proposal
from signals import make_signals

BG, INK, MUTED, ACCENT = '#f5f5f8', '#23242b', '#707380', '#7160d5'
REASONS = {
    'context_change': ('Seu contexto mudou', 'A troca pode fazer parte da mesma demanda. Um toque confirma.'),
    'untracked': ('Vamos organizar seu foco?', 'Você está usando o dispositivo e ainda não há uma atividade em andamento.'),
    'resume': ('Hora de retomar?', 'Seu registro está em pausa. Escolha o próximo passo.'),
    'long_activity': ('Uma atualização rápida', 'Seu foco continua o mesmo? Registre um avanço quando fizer sentido.'),
    'manual': ('Seu próximo passo', 'Uma conversa curta para organizar o que você está fazendo.')
}


class SoftButton(tk.Canvas):
    def __init__(self, parent, text, command, primary=False, subtitle='', font='Segoe UI'):
        self.command, self.text, self.subtitle = command, text, subtitle
        self.primary, self.family, self.hover = primary, font, False
        super().__init__(parent, height=78 if subtitle else 44, bg=parent.cget('bg'),
                         highlightthickness=0, bd=0, takefocus=1, cursor='hand2')
        self.bind('<Configure>', self.draw)
        self.bind('<Enter>', lambda e: self.paint(True))
        self.bind('<Leave>', lambda e: self.paint(False))
        self.bind('<FocusIn>', self.draw)
        self.bind('<FocusOut>', self.draw)
        self.bind('<Button-1>', lambda e: self.invoke())
        self.bind('<Return>', lambda e: self.invoke())
        self.bind('<space>', lambda e: self.invoke())

    def paint(self, hover):
        self.hover = hover
        self.draw()

    def invoke(self):
        return self.command()

    def draw(self, event=None):
        self.delete('all')
        w, h, r = self.winfo_width()-2, self.winfo_height()-2, 12
        fill = '#6250c4' if self.primary and self.hover else ACCENT if self.primary else '#eeeafc' if self.hover else '#ffffff'
        outline = ACCENT if self.focus_get() == self else fill if self.primary else '#e2e2eb'
        pts = [r,1,w-r,1,w,1,w,r,w,h-r,w,h,w-r,h,r,h,1,h,1,h-r,1,r,1,1]
        self.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=2)
        title_font = tkfont.Font(family=self.family, size=11, weight='bold')
        title = self.text
        if self.subtitle:
            while title and title_font.measure(title) > max(50, w-46):
                title = title[:-2].rstrip() + '…' if len(title) > 2 else ''
        self.create_text(18 if self.subtitle else w/2,24 if self.subtitle else h/2,text=title,
                         anchor='w' if self.subtitle else 'center',font=(self.family,11,'bold'),
                         fill='white' if self.primary else INK,width=max(50,w-46))
        if self.subtitle:
            self.create_text(18,51,text=self.subtitle,anchor='w',width=max(50,w-46),
                             font=(self.family,9),fill='#e3ddff' if self.primary else MUTED)


class ActivityDialog:
    def __init__(self, root, store, proposal, done, manual=False, config=None, present=True):
        self.store, self.proposal, self.done = store, proposal, done
        self.config = config or {}
        self.values, self.widgets = {}, {}
        self.closed = self.saved = False
        self.activity_id, self.primary = None, None
        self.auto_close = None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title('CPreta · Seu momento')
        self.window.configure(bg=BG)
        self.window.minsize(550,580)
        width, height = 620,min(770,max(580,self.window.winfo_screenheight()-110))
        x,y = max(0,(self.window.winfo_screenwidth()-width)//2),max(0,(self.window.winfo_screenheight()-height)//2-25)
        self.window.geometry(f'{width}x{height}+{x}+{y}')
        self.window.protocol('WM_DELETE_WINDOW',self.dismiss)
        self.window.bind('<Escape>',lambda e:self.dismiss())
        self.window.bind('<Control-Return>',lambda e:self.primary.invoke() if self.primary else None)
        header=tk.Frame(self.window,bg='#24242c',padx=28,pady=22)
        header.pack(fill='x')
        tk.Label(header,text='C▰  CPreta',font=(self.font,21,'bold'),bg='#24242c',fg='white').pack(side='left')
        tk.Label(header,text='●  SOMENTE LOCAL',font=(self.font,9),bg='#24242c',fg='#cabff9').pack(side='right')
        self.steps=tk.Label(self.window,bg='#eceaf3',fg='#71668d',font=(self.font,9),anchor='w',padx=28,pady=11)
        self.steps.pack(fill='x')
        self.footer=tk.Frame(self.window,bg=BG,padx=28,pady=18)
        self.footer.pack(side='bottom',fill='x')
        self.canvas=tk.Canvas(self.window,bg=BG,highlightthickness=0)
        self.canvas.pack(side='left',fill='both',expand=True)
        self.scroll=ttk.Scrollbar(self.window,orient='vertical',command=self.canvas.yview)
        self.scroll.pack(side='right',fill='y')
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.body=tk.Frame(self.canvas,bg=BG,padx=28,pady=25)
        self.body_id=self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.body_id,width=e.width))
        self.window.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units') if not isinstance(e.widget,tk.Text) else None)
        self.window.bind('<Button-4>',lambda e:self.canvas.yview_scroll(-1,'units'))
        self.window.bind('<Button-5>',lambda e:self.canvas.yview_scroll(1,'units'))
        self.pause_screen() if proposal.reason=='idle_return' else self.home()
        self.window.update_idletasks()
        if present:
            self.window.deiconify()
            if manual: self.window.lift()

    @property
    def font(self):
        return self.window.master.font_family

    def label(self,text,size=11,color=INK,bold=False,parent=None,pady=(0,10)):
        parent=parent or self.body
        w=tk.Label(parent,text=text,bg=parent.cget('bg'),fg=color,font=(self.font,size,'bold' if bold else 'normal'),anchor='w',justify='left',wraplength=510)
        w.pack(fill='x',pady=pady)
        return w

    def button(self,parent,text,command,primary=False,subtitle=''):
        return SoftButton(parent,text,command,primary,subtitle,self.font)

    def screen(self,step,title,subtitle,back=None):
        for child in self.body.winfo_children(): child.destroy()
        for child in self.footer.winfo_children(): child.destroy()
        self.widgets={}
        self.primary=None
        self.steps.configure(text=step)
        self.canvas.yview_moveto(0)
        self.label(title,24,bold=True)
        self.label(subtitle,11,MUTED,pady=(0,20))
        self.error=self.label('',10,'#a24747',pady=(0,0))
        left=tk.Frame(self.footer,bg=BG)
        left.pack(side='left',fill='x',expand=True,padx=(0,12))
        minutes=self.config.get('snooze_minutes',5)
        self.button(left,'← Voltar' if back else f'Adiar {minutes} min',back or self.dismiss).pack(fill='x')
        self.footer_right=tk.Frame(self.footer,bg=BG)
        self.footer_right.pack(side='right',fill='x',expand=True)

    def primary_button(self,text,command):
        self.primary=self.button(self.footer_right,text,command,True)
        self.primary.pack(fill='x')

    def card(self,title,subtitle,command,primary=False):
        self.button(self.body,title,command,primary,subtitle).pack(fill='x',pady=(0,10))

    def field(self,key,label,multiline=False,choices=None):
        self.label(label,10,bold=True,pady=(12,7))
        if multiline:
            w=tk.Text(self.body,height=3,wrap='word',font=(self.font,11),relief='flat',bd=0,bg='white',fg=INK,highlightthickness=1,highlightbackground='#dddde6',highlightcolor=ACCENT,padx=12,pady=10)
            w.insert('1.0',self.values.get(key,''))
        elif choices:
            w=ttk.Combobox(self.body,values=choices,font=(self.font,11))
            w.set(self.values.get(key,''))
        else:
            w=tk.Entry(self.body,font=(self.font,12),relief='flat',bg='white',fg=INK,insertbackground=INK,highlightthickness=1,highlightbackground='#dddde6',highlightcolor=ACCENT)
            w.insert(0,str(self.values.get(key,'')))
        w.pack(fill='x',ipady=9 if not multiline else 0)
        self.widgets[key]=w
        return w

    def remember(self):
        for key,w in self.widgets.items():
            self.values[key]=w.get('1.0','end-1c') if isinstance(w,tk.Text) else w.get()

    def run(self,action):
        try: action()
        except (ValueError,OSError) as error:
            self.error.configure(text=str(error))
            self.canvas.yview_moveto(0)
        except Exception:
            logging.exception('Não foi possível registrar a atividade')
            self.error.configure(text='Não foi possível salvar. Seu texto permanece aqui para tentar novamente.')
            self.canvas.yview_moveto(0)

    def home(self):
        self.current=self.store.current()
        title,subtitle=REASONS.get(self.proposal.reason,REASONS['manual'])
        self.screen('01  Seu momento    /    02  Contexto    /    03  Registro',title,subtitle)
        if self.current and self.current['kind']=='active':
            self.label('EM ANDAMENTO',9,ACCENT,True)
            self.label(self.current['title'],16,bold=True,pady=(0,6))
            self.label(' · '.join(x for x in [self.current['client'],self.current['project']] if x) or CATEGORIES[self.current['category']],10,MUTED,pady=(0,18))
            self.card('Continuo na mesma','Confirmar e voltar ao trabalho. Sem preencher nada.',lambda:self.run(self.same),True)
            self.card('Registrar avanço ou concluir','Como foi feito, tentativas e resultado.',lambda:self.begin_update(self.current['activity_id']))
        else:
            self.card('Retomar uma atividade','Voltar a uma demanda anterior.',self.choose_existing)
        self.card('Começar outra atividade','Dar contexto ao próximo período de trabalho.',self.begin_new)
        self.card('Estou ocioso','Iniciar uma pausa e preservar o tempo já registrado.',lambda:self.run(self.save_idle))
        self.primary_button('Silenciar 30 min',lambda:self.close(1800))

    def same(self):
        self.store.continue_activity(self.current['activity_id'],{})
        self.success('Foco confirmado.','O contador continua de onde estava.')

    def begin_new(self):
        self.values={}
        self.category()

    def category(self):
        self.screen('01  Seu momento    /    02  Categoria    /    03  Contexto','Qual é o tipo de atividade?','Escolha o contexto. Em seguida, uma descrição curta basta.',back=self.home)
        for key,label in CATEGORIES.items():
            self.card(label,{'trabalho':'Cliente, projeto ou demanda.','estudo':'Curso, pesquisa ou aprendizado.','pessoal':'Sua organização e seus projetos.','outro':'Uma atividade do seu jeito.'}[key],lambda key=key:self.set_category(key))

    def set_category(self,key):
        self.values['category']=key
        self.activity_details()

    def activity_details(self):
        self.screen('02  Categoria    →    03  Contexto','O que você vai fazer?','Um nome específico ajuda a entender o resultado depois.',back=lambda:(self.remember(),self.category()))
        if self.values['category']=='trabalho':
            suggestions=self.store.suggestions()
            self.field('client','Cliente · opcional',choices=suggestions['client'])
            self.field('project','Projeto ou demanda · opcional',choices=suggestions['project'])
        self.field('title','Atividade · obrigatório')
        self.field('note','Objetivo ou próximo passo · opcional',True)
        self.primary_button('Começar atividade →',lambda:self.run(self.save_start))

    def save_start(self):
        self.remember()
        self.store.start(self.values)
        self.success('Seu foco está registrado.',self.values['title'])

    def choose_existing(self):
        self.screen('Retomar uma atividade','De onde vamos continuar?','O tempo anterior e os resultados permanecem na mesma demanda.',back=self.home)
        for item in self.store.recent()[:12]:
            self.card(item['title'],' · '.join(x for x in [CATEGORIES[item['category']],item['client'],item['project']] if x),lambda item=item:self.begin_update(item['id']))
        self.primary_button('Nova atividade →',self.begin_new)

    def begin_update(self,ident):
        self.values={}
        self.activity_id=ident
        self.progress_note()

    def progress_note(self):
        item=self.store.get_activity(self.activity_id)
        self.screen('01  Avanço    /    02  Resultado','O que avançou?',item['title'],back=self.home)
        self.field('note','O que você fez? Como foi feito?',True)
        self.label('Pode ser uma frase. Os detalhes de tentativas ficam na próxima etapa.',10,MUTED,pady=(16,14))
        self.card('Salvar só esta atualização','Continuar a atividade sem adicionar tentativas.',lambda:self.run(self.save_note))
        self.primary_button('Detalhar resultado →',lambda:(self.remember(),self.results()))

    def save_note(self):
        self.remember()
        self.store.continue_activity(self.activity_id,{'note':self.values.get('note','')})
        self.success('Avanço salvo.','Sua atividade continua em andamento.')

    def results(self):
        self.screen('01  Avanço    →    02  Resultado','Como foi o resultado?','Informe somente as novas tentativas desta atualização.',back=lambda:(self.remember(),self.progress_note()))
        row=tk.Frame(self.body,bg=BG)
        row.pack(fill='x',pady=(0,12))
        for key,label in [('attempts','Tentativas'),('successes','Deram certo'),('failures','Deram errado')]:
            col=tk.Frame(row,bg=BG)
            col.pack(side='left',fill='x',expand=True,padx=(0,10))
            self.label(label,10,bold=True,parent=col)
            w=ttk.Spinbox(col,from_=0,to=10000,width=9,font=(self.font,12))
            w.set(self.values.get(key,0))
            w.pack(fill='x',ipady=7)
            self.widgets[key]=w
        self.field('reason','O que falhou e por quê? · opcional',True)
        self.field('result','Resultado e próximo passo · opcional',True)
        self.complete_var=tk.BooleanVar(value=False)
        current=self.store.current()
        if current and current['activity_id']==self.activity_id and current['kind']=='active':
            tk.Checkbutton(self.body,text='Concluir esta atividade ao salvar',variable=self.complete_var,bg=BG,fg=INK,activebackground=BG,font=(self.font,11),anchor='w').pack(fill='x',pady=(18,0))
        self.primary_button('Salvar resultado →',lambda:self.run(self.save_progress))

    def save_progress(self):
        self.remember()
        if self.complete_var.get(): self.store.complete(self.activity_id,self.values)
        else: self.store.continue_activity(self.activity_id,self.values)
        self.success('Resultado registrado.','Atividade concluída.' if self.complete_var.get() else 'Você pode continuar no seu ritmo.')

    def save_idle(self):
        self.store.idle()
        self.success('Pausa iniciada.','O tempo ocioso termina quando você retomar uma atividade.')

    def pause_screen(self):
        minutes=max(1,round((self.proposal.end-self.proposal.start)/60))
        self.screen('Uma pausa a confirmar','Você ficou ausente?',f'Percebemos cerca de {minutes} minutos sem interação. Leitura e reuniões também podem acontecer sem usar o computador.')
        self.card('Foi uma pausa. Voltei à mesma atividade.','Separar o tempo ocioso e retomar.',lambda:self.run(lambda:self.gap(True)),True)
        self.card('Foi uma pausa. Vou fazer outra coisa.','Registrar o intervalo e escolher uma atividade.',lambda:self.run(lambda:self.gap(False)))
        self.card('Continuei trabalhando','Manter o tempo como atividade.',self.close)

    def gap(self,resume):
        self.store.confirm_gap(self.proposal.start,self.proposal.end,resume)
        if resume: self.success('Intervalo organizado.','A mesma atividade está em andamento novamente.')
        else:
            self.proposal=Proposal('manual')
            self.begin_new()

    def success(self,title,subtitle):
        self.saved=True
        self.screen('✓  SALVO NESTE DISPOSITIVO',title,subtitle,back=self.close)
        self.primary_button('Voltar ao trabalho',self.close)
        self.card('Ver meus relatórios','Acompanhar tempo, contexto e resultados.',lambda:webbrowser.open('http://127.0.0.1:3847/relatorios'))
        self.auto_close = self.window.after(2200,self.close)

    def dismiss(self):
        self.close(0 if self.saved else self.config.get('snooze_minutes',5)*60)

    def close(self,snooze=0):
        if self.closed: return
        self.closed=True
        if self.auto_close:
            self.window.after_cancel(self.auto_close)
        self.window.destroy()
        self.done(snooze)


class DesktopController:
    def __init__(self,root,store,config_store,runtime):
        self.root,self.store,self.config_store,self.runtime=root,store,config_store,runtime
        root.withdraw()
        families=tkfont.families(root)
        root.font_family='Segoe UI' if 'Segoe UI' in families else 'DejaVu Sans' if 'DejaVu Sans' in families else 'Arial'
        style=ttk.Style(root)
        if 'clam' in style.theme_names(): style.theme_use('clam')
        style.configure('TCombobox',padding=8,fieldbackground='white',foreground=INK,arrowsize=14)
        style.configure('TSpinbox',padding=6,fieldbackground='white',foreground=INK)
        self.signals=make_signals()
        self.policy=AttentionPolicy()
        self.dialog=None
        self.stopping=False
        self.last_heartbeat=0
        runtime.desktop=True
        runtime.description=self.signals.description
        runtime.idle_available=self.signals.idle_available
        runtime.context_available=self.signals.context_available
        self.tick()

    def show(self,proposal,manual=False):
        if self.dialog:
            if manual: self.dialog.window.lift()
            return
        try: self.dialog=ActivityDialog(self.root,self.store,proposal,self.finished,manual,self.config_store.read())
        except Exception:
            self.runtime.dialog_open=False
            raise
        self.policy.shown(time.time())
        self.runtime.dialog_open=True

    def finished(self,snooze):
        self.policy.acknowledge(time.time(),snooze)
        self.runtime.snoozed_until=self.policy.snoozed_until
        self.runtime.dialog_open=False
        self.runtime.pending_idle=False
        self.dialog=None

    def heartbeat(self,now):
        path=self.config_store.data_dir/'last_seen.json'
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps({'at':now}),encoding='utf-8')
        temp.replace(path)

    def tick(self):
        if self.stopping: return
        try:
            config=self.config_store.read()
            if self.runtime.last_answer>self.policy.last_answer: self.policy.acknowledge(self.runtime.last_answer)
            if self.runtime.snoozed_until>self.policy.snoozed_until: self.policy.snoozed_until=self.runtime.snoozed_until
            try:
                self.runtime.requests.get_nowait()
                self.show(Proposal('manual'),manual=True)
            except queue.Empty: pass
            if config.get('monitor_enabled',False):
                sample=self.signals.sample(config.get('observation_mode','idle'))
                proposal=self.policy.observe(sample,config,self.store.current(),bool(self.dialog))
                self.runtime.pending_idle=self.policy.idle_start is not None
                if proposal: self.show(proposal)
            else:
                self.policy.reset()
                self.runtime.pending_idle=False
            now=time.time()
            if now-self.last_heartbeat>=10:
                self.heartbeat(now)
                self.last_heartbeat=now
            self.runtime.error=''
        except Exception:
            logging.exception('Falha no acompanhamento local')
            self.runtime.error='O acompanhamento precisa de atenção. O registro pelo painel continua disponível.'
        self.root.after(2000,self.tick)

    def shutdown(self):
        self.stopping=True
        self.store.finish()
        self.heartbeat(time.time())
        self.runtime.desktop=False
        self.root.destroy()
