# CPreta · versão 3.3

Seu diário de atividades, inteiramente local. Python + Flask, painel em **http://127.0.0.1:3847** e assistente nativo com Tkinter. Duas áreas principais: **Relatórios** e **Configuração**.

## O que mudou

- Janela redesenhada, perguntas em etapas e confirmação “Continuo na mesma” em um toque.
- Nova atividade → categoria → demanda e contexto; atualização simples ou detalhes opcionais de tentativas, acertos, falhas, motivos e resultado.
- Retomada de atividades recentes, encerramento explícito e confirmação de períodos ociosos.
- Registro também pelo painel, mesmo sem janela nativa disponível.
- Painel responsivo com atividade atual, cronômetro, gráficos, busca, filtros, histórico expansível e exportação CSV/Markdown.
- Perfis de frequência, adiar e silenciar; sessão persistente para evitar erros de formulário após reiniciar.
- Inicialização detecta instância existente. Encerramento pelo painel e recuperação de intervalos após interrupção.

## Instalar e executar no Windows

Requer Python 3.10 ou superior com Tcl/Tk. Extraia o ZIP e entre na pasta CPreta:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Iniciar-CPreta.cmd
```

O iniciador abre o navegador e mantém o CPreta em segundo plano. A janela de inicialização fecha após confirmar que o painel está disponível. Não é necessário manter um terminal aberto, ativar a venv nem mudar políticas do PowerShell. Se já houver uma instância aberta, ela será reutilizada.

## Instalar e executar no Linux

Requer Python 3.10+, venv e Tkinter. No Debian/Ubuntu, os pacotes de sistema são python3-venv, python3-tk e libxss1 (este último para detecção de inatividade em X11).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sh iniciar.sh
```

Execute na sessão gráfica do seu usuário. Em X11, o assistente usa inatividade e classe do aplicativo em foco. Em Wayland, a aplicação oferece registro manual, pois a sessão restringe esses sinais globais. O painel e a janela manual continuam disponíveis se Tk e a sessão gráfica estiverem disponíveis. A execução no Linux não foi validada nesta entrega.

A instalação inicial das dependências pode exigir internet; o uso posterior não depende de serviços externos. Fontes, CSS, JavaScript e gráficos são locais.

## Como usar

1. Em **Configuração**, personalize o nome, pasta de relatórios e ritmo das sugestões. Clique em Salvar.
2. Em **Relatórios**, use **Nova atividade** ou abra o assistente nativo. Para trabalho, informe cliente, demanda/projeto e atividade.
3. Registre avanços durante a atividade. Tentativas e resultados são opcionais; acertos + falhas não podem exceder tentativas.
4. Ao terminar, marque a conclusão. Para uma pausa, escolha ocioso. Ao voltar, confirme a pausa sugerida antes de ela entrar no histórico.
5. Use busca e filtros para localizar demandas e abra uma atividade para ver como foi executada. Exporte o período em CSV ou Markdown quando quiser.
6. Na seção **Relatórios salvos**, informe um título opcional, escolha Hoje ou Últimos 7 dias e clique em **Registrar relatório HTML**. O arquivo é gravado na pasta configurada e aparece na lista. Use Visualizar para abrir o relatório formatado e Baixar HTML para levar uma cópia.

O HTML contém gráficos, tempos por dia, cliente, demanda, descrição da execução, tentativas, falhas e resultados. CSS e gráficos estão no próprio arquivo: ele abre offline, sem o CPreta. Cada geração cria um arquivo distinto e preserva os anteriores. É uma cópia estática até aquele instante; mudanças posteriores no histórico exigem gerar outro relatório. Períodos sem registros não geram arquivos. O limite por relatório é 2 MB.

### Corrigir registros feitos por engano

- Abra uma atividade em **Atividades e resultados** e escolha **Excluir atividade inteira** para remover seus intervalos e atualizações de todos os períodos. Se estiver em andamento, a contagem dessa atividade para.
- Em cada atualização, **Excluir atualização** remove apenas suas descrições e tentativas; o tempo da atividade permanece.
- Em **Pausas registradas**, use **Excluir pausa** para remover um intervalo ocioso marcado por engano.
- Em **Relatórios salvos**, **Excluir HTML** remove somente o arquivo escolhido. A visualização de um HTML salvo também oferece essa ação.

Cada exclusão abre uma tela de confirmação e só acontece após **Excluir permanentemente**. Cancelar preserva o item. Não há lixeira interna. Se o item mudar enquanto a confirmação estiver aberta, a exclusão é recusada e precisa ser revista. Os totais são recalculados após excluir registros. HTMLs já salvos são cópias independentes: excluir histórico não altera esses arquivos, e excluir um HTML não apaga as atividades que o geraram.

O painel atualiza os dados aproximadamente a cada 15 segundos; o cronômetro avança a cada segundo. Os registros usam o fuso local do computador. Uma atividade pode ter vários intervalos de execução.

## Quando o assistente aparece

O perfil **Mais presente** usa: troca de aplicativo estável por 30 segundos, intervalo mínimo de 5 minutos, até 6 sugestões por hora, inatividade a partir de 3 minutos e convite de atualização após 20 minutos de atividade. Os valores são configuráveis.

As sugestões consideram uso sem atividade registrada, retorno de pausa, troca estável de aplicativo e atividade longa. Ele procura uma breve pausa na interação e evita sugerir enquanto você está ausente, em tela cheia, na própria janela ou durante o silêncio escolhido. Uma pergunta já aberta não é duplicada. Você pode adiar ou silenciar por 30 minutos.

São heurísticas locais. O assistente não compreende a demanda por conta própria: trocar de aplicativo pode fazer parte da mesma tarefa, e mudar de tarefa dentro do mesmo aplicativo ou de uma sessão remota pode passar despercebido. Você confirma e descreve o trabalho. O lembrete de atividade longa pode ser desativado definindo seu intervalo como zero.

## Iniciar automaticamente com o Windows

Em Configuração, marque **Iniciar com o sistema** e salve. A aplicação registra uma entrada somente para o seu usuário e confirma o estado no cartão. Também é possível executar **Ativar-inicio-automatico.cmd** com dois cliques. Use sua conta normal do Windows.

O CPreta abre em segundo plano quando você entra na sua conta após ligar ou reiniciar o PC: sem terminal e sem abrir o navegador. A sessão gráfica precisa estar iniciada para o assistente mostrar perguntas. Ele não é um serviço anterior à tela de login. Uma instância já em execução é reutilizada.

Para desativar, desmarque a opção e salve. Isso remove apenas a entrada desta instalação, sem encerrar o CPreta em uso. Para parar imediatamente, use Encerrar CPreta. Se salvar falhar, o painel informa o erro e restaura as configurações anteriores. Não mova nem exclua a pasta ou o Python sem antes desativar o início automático e reativá-lo na nova instalação.

A integração usa HKCU/Software/Microsoft/Windows/CurrentVersion/Run, valor CPreta, com pythonw.exe e start_background.py --no-browser. [Documentação Microsoft](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys). Ela não precisa de serviço nem de privilégios administrativos; políticas do computador podem bloquear a gravação. Se o Windows desativar CPreta na lista Aplicativos de Inicialização do Gerenciador de Tarefas, reative-o nessa lista. Não foi realizado um reinício real durante a validação.

Nesta versão, a integração automática é para Windows. No Linux, continue usando iniciar.sh na sua sessão gráfica.

## Privacidade e armazenamento

- O aplicativo em foco é um sinal temporário em memória, descartado do histórico e dos relatórios. No Windows usa o nome do executável; no X11, WM_CLASS.
- Não lê títulos, URLs, conteúdo de páginas, teclas digitadas nem captura telas.
- Armazena as descrições fornecidas por você e os intervalos de tempo confirmados.
- Não usa IA, serviços remotos ou telemetria. Escuta exclusivamente em 127.0.0.1.
- Não modifica o cursor global, não instala hooks de mouse e não usa automação do ponteiro.
- Configurações: data/config.json; atividades: data/activities.sqlite3; recuperação: data/last_seen.json.
- Sessão: data/.session-key, gerada localmente. Não compartilhe esse arquivo.
- Diagnóstico: data/logs/cpreta.log, com rotação; registra erros de execução, não histórico de aplicativos.
- O diretório configurado contém arquivos de relatório externos; mudar essa pasta não move o banco de atividades.

Caminhos relativos para relatórios partem de data/. O padrão relatorios corresponde a data/relatorios. Pastas locais absolutas são aceitas; não selecione unidades de rede ou pastas sincronizadas se desejar manter tudo exclusivamente neste computador.

A lista de arquivos não percorre subpastas nem links simbólicos. Relatórios HTML gerados nesta instalação têm sua integridade verificada e abrem em uma área isolada, sem scripts ou recursos externos. Arquivos externos ou alterados são exibidos como texto escapado, até 2 MB. Os arquivos originais não são alterados. Preserve data/.session-key no backup para manter a verificação dos relatórios salvos; o HTML continua abrindo diretamente no navegador mesmo sem essa chave.

## Atualização, backup e encerramento

Para atualizar uma instalação existente, encerre o CPreta e faça uma cópia de **toda a pasta data/**. Atualize o código preservando sua pasta data; não substitua seu config.json pelo exemplo do ZIP. Nesta atualização feita diretamente no projeto, os dados existentes foram preservados.

Encerre em Configuração → Encerrar CPreta. Fechar o navegador deixa o assistente funcionando em segundo plano, inclusive com as perguntas nativas. O próximo login volta a abri-lo se o início automático estiver ativado. Para diagnóstico, execute python app.py diretamente no terminal; nesse modo, Ctrl+C encerra. Ao encerrar normalmente, o intervalo em andamento é fechado. Após uma interrupção inesperada, a recuperação usa o último sinal de funcionamento salvo, sem contabilizar automaticamente todo o tempo em que o processo ficou desligado.

Se uma instância antiga ainda estiver aberta, encerre-a antes de iniciar a versão atualizada: o iniciador reutiliza instâncias existentes.

## Solução de problemas

- **Fora do ar:** execute Iniciar-CPreta.cmd. Se aparecer erro, confira data/logs/startup.log, data/logs/cpreta.log e a mensagem do iniciador. No Linux, sh iniciar.sh também inicia em segundo plano; sh iniciar.sh --no-browser dispensa a abertura do navegador.
- **Porta ocupada:** feche a instância anterior. Outra aplicação usando 3847 precisa ser encerrada antes.
- **Formulário expirado:** atualize a página antes de reenviar. Cookies precisam estar habilitados. A chave persistente mantém a sessão entre reinicializações.
- **Sem popup:** confira se sugestões estão ativas, se o período de silêncio terminou e se existe sessão gráfica/Tk. O registro pelo painel funciona independentemente do popup.
- **JSON inválido:** o arquivo é preservado e a inicialização informa o erro. Corrija-o ou restaure seu backup.

Modo somente web, sem observar aplicativos e sem popup:

```sh
python app.py --web-only --open-browser
```

## Código e validação

```text
app.py             rotas, formulários, arquivos e exportações
launcher.py        execução local e encerramento
start_background.py inicialização sem terminal e verificação de disponibilidade
autostart.py        registro e remoção do início automático por usuário no Windows
config.py          configuração JSON
activities.py      histórico SQLite e cálculos
reports.py         integridade dos relatórios HTML salvos
attention.py       critérios das sugestões
signals.py         sinais temporários Windows/X11
desktop.py         assistente nativo
runtime.py         comunicação entre painel e janela
templates/         telas e componentes
static/            CSS, JavaScript e marca
data/              dados locais
tests/             testes automatizados
```

```sh
python -m unittest discover -s tests -v
```

Os testes usam dados próprios, separados do histórico real. Cobrem persistência, segurança, cálculo de tempo, critérios de sugestões, registro web, conclusão e fluxo nativo oculto. No ambiente de entrega, os testes foram executados no Windows. O teste nativo percorre etapas sem exibir a janela nem controlar o mouse; ele não substitui inspeção visual em uma sessão gráfica real.

As proteções incluem validação de Host/origem, token de formulário, sessão persistente, conteúdo escapado e bloqueio de travessia de diretórios. Esta é uma aplicação de usuário único em loopback, sem acesso remoto nem autenticação multiusuário.
