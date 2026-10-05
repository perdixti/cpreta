"""Local workspace for user-described activities and contextual suggestions."""
from pathlib import Path
import hmac
import secrets
import time
import sqlite3
from datetime import datetime, timedelta
from reports import seal, verified, file_identity
from autostart import AutoStart, save_configuration

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for, jsonify, Response
from config import ConfigStore
from activities import ActivityStore
from runtime import Runtime

BASE = Path(__file__).resolve().parent


def create_app(data_dir=None, runtime=None, startup=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=64 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      TEMPLATES_AUTO_RELOAD=True,
                      SESSION_COOKIE_SAMESITE='Strict', TRUSTED_HOSTS=['127.0.0.1', 'localhost'])
    store = ConfigStore(Path(data_dir) if data_dir else BASE / 'data')
    key_path = store.data_dir / '.session-key'
    try:
        with key_path.open('x', encoding='ascii') as key_file:
            key_file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    app.secret_key = key_path.read_text(encoding='ascii').strip()
    if len(app.secret_key) < 32:
        raise RuntimeError('A chave de sessão local está inválida. Restaure data/.session-key.')
    app.config['SESSION_COOKIE_NAME'] = 'cpreta_session'
    ledger = ActivityStore(store.data_dir / 'activities.sqlite3')
    runtime = runtime or Runtime()
    startup = startup or AutoStart(BASE)
    app.extensions.update(config_store=store, activities=ledger, desktop_runtime=runtime)

    @app.context_processor
    def startup_context():
        return {'autostart_status': startup.status()} if request.endpoint == 'configuracao' else {}

    @app.before_request
    def protect_local_requests():
        if request.method == 'POST':
            if request.headers.get('Origin') not in (None, request.host_url.rstrip('/')):
                abort(403)
            if not hmac.compare_digest(session.get('csrf', '').encode(), request.form.get('csrf', '').encode()) or not session.get('csrf'):
                abort(403)
        session.setdefault('csrf', secrets.token_hex(32))

    @app.after_request
    def security_headers(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.endpoint == 'report_content':
            response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Preserve the same-origin form Origin; no-referrer makes Chromium send
        # Origin: null on POST, which our origin validation correctly rejects.
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/')
    def index():
        return redirect(url_for('relatorios'))

    @app.get('/health')
    def health():
        return jsonify(application='CPreta', version='3.3', desktop=runtime.desktop)

    @app.errorhandler(403)
    def forbidden(error):
        message = 'A sessão do formulário expirou ou sua origem foi recusada. Atualize a página e tente novamente.'
        if request.path.startswith(('/atividade/', '/sistema/')):
            return jsonify(error=message), 403
        return render_template('error.html', message=message, active='configuracao'), 403

    @app.route('/configuracao', methods=['GET', 'POST'])
    def configuracao():
        config = store.read()
        if request.method == 'POST':
            config = config | dict(device_name=request.form.get('device_name', '').strip(),
                          reports_directory=request.form.get('reports_directory', '').strip(),
                          auto_start=request.form.get('auto_start') == 'on')
            if 'monitor_settings' in request.form:
                config.update(monitor_enabled=request.form.get('monitor_enabled') == 'on',
                              observation_mode=request.form.get('observation_mode', 'idle'),
                              idle_minutes=request.form.get('idle_minutes', '5'),
                              change_seconds=request.form.get('change_seconds', '60'),
                              cooldown_minutes=request.form.get('cooldown_minutes', '5'))
                for field in ('checkin_minutes', 'snooze_minutes', 'max_prompts_hour'):
                    config[field] = request.form.get(field, config[field])
            try:
                save_configuration(store, config, startup)
            except (ValueError, OSError) as error:
                flash(str(error), 'error')
                return render_template('configuracao.html', config=config, runtime=runtime.snapshot(), active='configuracao'), 400
            flash('Configurações salvas neste dispositivo.', 'success')
            return redirect(url_for('configuracao'))
        return render_template('configuracao.html', config=config, runtime=runtime.snapshot(), active='configuracao')

    def report_path(name):
        root = store.reports_path(store.read()).resolve()
        if not name or '/' in name or '\\' in name or name in ('.', '..'):
            abort(404)
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file() or candidate.resolve().parent != root:
            abort(404)
        return candidate

    @app.route('/relatorios')
    def relatorios():
        root = store.reports_path(store.read())
        reports, error = [], None
        try:
            for path in root.iterdir():
                if path.is_file() and not path.is_symlink():
                    stat = path.stat()
                    reports.append(dict(name=path.name, size=stat.st_size, modified=stat.st_mtime,
                                        deletable=path.suffix.lower() in ('.html', '.htm'),
                                        viewable=path.suffix.lower() in ('.txt', '.md', '.json', '.csv', '.log', '.html', '.htm')))
            reports.sort(key=lambda item: item['modified'], reverse=True)
        except OSError:
            error = 'Não foi possível acessar a pasta de relatórios. Confira o caminho e as permissões em Configuração.'
        period = 'week' if request.args.get('period') == 'week' else 'today'
        dashboard = ledger.dashboard(period)
        return render_template('relatorios.html', reports=reports, directory=str(root), error=error,
                               dashboard=dashboard, runtime=runtime.snapshot(), config=store.read(), active='relatorios')

    @app.post('/atividade/popup')
    def request_popup():
        try:
            runtime.request_dialog()
        except ValueError as error:
            return jsonify(error=str(error)), 503
        return jsonify(ok=True, state='queued')

    @app.get('/atividade/opcoes')
    def activity_options():
        current, recent = ledger.current(), ledger.recent()
        requested = request.args.get('activity_id') or (current['activity_id'] if current else None)
        if requested:
            try:
                ident = int(requested)
                if not any(item['id'] == ident for item in recent):
                    recent.insert(0, ledger.get_activity(ident))
            except (ValueError, TypeError):
                return jsonify(error='Atividade não encontrada.'), 404
        return jsonify(current=current, recent=recent, suggestions=ledger.suggestions())

    @app.post('/atividade/registrar')
    def register_activity():
        action = request.form.get('action')
        try:
            if action == 'start':
                ledger.start(request.form)
            elif action in ('continue', 'complete'):
                ident = int(request.form.get('activity_id', ''))
                (ledger.complete if action == 'complete' else ledger.continue_activity)(ident, request.form)
            elif action == 'idle':
                ledger.idle()
            elif action == 'finish':
                ledger.finish()
            else:
                raise ValueError('Escolha uma ação válida.')
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        except (OSError, sqlite3.Error):
            app.logger.exception('Falha ao salvar registro local')
            return jsonify(error='Não foi possível salvar. Confira as permissões da pasta data e tente novamente.'), 500
        runtime.last_answer = time.time()
        return jsonify(ok=True, current=ledger.current())

    @app.post('/atividade/adiar')
    def snooze_activity():
        runtime.snoozed_until = time.time() + 1800
        return jsonify(ok=True)

    @app.post('/sistema/encerrar')
    def shutdown_app():
        ledger.finish()
        runtime.shutdown_requested.set()
        return jsonify(ok=True)

    @app.get('/relatorios/painel')
    def report_panel():
        period = 'week' if request.args.get('period') == 'week' else 'today'
        return render_template('activity_dashboard.html', dashboard=ledger.dashboard(period),
                               runtime=runtime.snapshot(), config=store.read())

    @app.post('/atividade/encerrar')
    def finish_activity():
        ledger.finish()
        runtime.last_answer = time.time()
        flash('Registro encerrado. O tempo fica preservado no histórico.', 'success')
        return redirect(url_for('relatorios'))

    @app.post('/atividade/pausar-sugestoes')
    def pause_suggestions():
        value = store.read()
        value['monitor_enabled'] = False
        store.save(value)
        flash('Sugestões automáticas pausadas. O registro manual continua disponível.', 'success')
        return redirect(url_for('relatorios'))

    @app.post('/atividade/ativar-sugestoes')
    def enable_suggestions():
        value = store.read()
        value['monitor_enabled'] = True
        store.save(value)
        runtime.last_answer = time.time()
        flash('Sugestões ativadas. Os intervalos podem ser ajustados em Configuração.', 'success')
        return redirect(url_for('relatorios'))

    @app.get('/atividade/status')
    def activity_status():
        current = ledger.current()
        import time
        if current:
            current['elapsed'] = max(0, time.time() - current['start'])
        return jsonify(current=current, runtime=runtime.snapshot())

    @app.route('/registros/excluir/<kind>/<int:ident>', methods=['GET', 'POST'])
    def delete_record(kind, ident):
        period = 'week' if request.args.get('period') == 'week' else 'today'
        back = url_for('relatorios', period=period)
        try:
            preview = ledger.deletion_preview(kind, ident)
            record = preview['record']
            if request.method == 'POST':
                if request.form.get('confirm') != 'delete':
                    abort(400)
                ledger.delete_record(kind, ident, request.form.get('fingerprint', ''))
                runtime.last_answer = time.time()
                flash('Registro excluído. Os totais foram recalculados.', 'success')
                return redirect(back)
            if kind == 'activity':
                title = record['title']
                explanation = 'Exclui esta atividade inteira, todos os seus intervalos de tempo e todas as atualizações, inclusive fora do período selecionado. Se estiver em andamento, sua contagem também será encerrada. Os HTMLs já salvos não serão alterados.'
            elif kind == 'update':
                title = record['note'] or record['result'] or record['reason'] or 'Atualização de tentativas'
                explanation = 'Exclui somente esta atualização e suas tentativas, acertos e falhas. A atividade e seus tempos permanecem. Os HTMLs já salvos não serão alterados.'
            else:
                title = 'Pausa de ' + local_date(record['start'])
                explanation = 'Exclui este intervalo ocioso inteiro. Se a pausa estiver em andamento, sua contagem será encerrada. As atividades e os HTMLs salvos permanecem.'
            return render_template('delete_confirmation.html', title=title, explanation=explanation,
                fingerprint=preview['fingerprint'], back=back, active='relatorios')
        except ValueError as error:
            flash(str(error), 'error')
            return redirect(back)
        except sqlite3.Error:
            flash('Não foi possível excluir o registro. Nenhuma exclusão parcial foi aplicada.', 'error')
            return redirect(back)

    @app.route('/relatorios/excluir/<path:name>', methods=['GET', 'POST'])
    def delete_report(name):
        back = url_for('relatorios', files='1', _anchor='arquivos')
        path = report_path(name)
        if path.suffix.lower() not in ('.html', '.htm'):
            abort(415)
        try:
            fingerprint = file_identity(path)
            if request.method == 'POST':
                if request.form.get('confirm') != 'delete':
                    abort(400)
                if not hmac.compare_digest(fingerprint.encode(), request.form.get('fingerprint', '').encode()):
                    flash('O arquivo ou a pasta mudou desde a confirmação. Abra a exclusão novamente.', 'error')
                    return redirect(back)
                path.unlink()
                flash('Arquivo HTML excluído. O histórico de atividades foi preservado.', 'success')
                return redirect(back)
            return render_template('delete_confirmation.html', title=name,
                explanation='Exclui somente este arquivo HTML da pasta configurada. O histórico de atividades e os outros arquivos permanecem.',
                fingerprint=fingerprint, back=back, active='relatorios')
        except OSError:
            flash('Não foi possível excluir o arquivo. Confira se está disponível e se você tem permissão na pasta.', 'error')
            return redirect(back)

    @app.post('/relatorios/registrar')
    def save_report():
        period = request.form.get('period', 'today')
        title = request.form.get('title', '').strip() or 'Relatório de atividades'
        if period not in ('today', 'week') or len(title) > 120:
            abort(400)
        data = ledger.dashboard(period)
        if not data['segments']:
            flash('Registre uma atividade ou pausa neste período antes de gerar o relatório.', 'error')
            return redirect(url_for('relatorios', period=period, files='1', _anchor='arquivos'))
        config = store.read()
        now = datetime.now()
        html = render_template('report_document.html', dashboard=data, title=title,
            device_name=config['device_name'], period_label='Hoje' if period == 'today' else 'Últimos 7 dias',
            start_date=(now - timedelta(days=6 if period == 'week' else 0)).strftime('%d/%m/%Y'),
            end_date=now.strftime('%d/%m/%Y'), generated_at=now.strftime('%d/%m/%Y às %H:%M:%S'),
            report_css=(BASE / 'static/css/report.css').read_text(encoding='utf-8'))
        try:
            content = seal(html, app.secret_key)
            root = store.reports_path(config)
            root.mkdir(parents=True, exist_ok=True)
            name = f"CPreta-{now:%Y-%m-%d_%H-%M-%S}-{secrets.token_hex(4)}.html"
            path = root / name
            with path.open('xb') as handle:
                try:
                    handle.write(content)
                except OSError:
                    handle.close()
                    path.unlink(missing_ok=True)
                    raise
        except (OSError, ValueError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Não foi possível salvar o relatório. Confira a pasta e suas permissões.', 'error')
            return redirect(url_for('relatorios', period=period, files='1', _anchor='arquivos'))
        flash(f'Relatório registrado: {name}')
        return redirect(url_for('relatorios', period=period, files='1', _anchor='arquivos'))

    @app.get('/relatorios/conteudo/<path:name>')
    def report_content(name):
        content = verified(report_path(name), app.secret_key)
        if content is None:
            abort(404)
        return Response(content, mimetype='text/html')

    @app.get('/relatorios/baixar/<path:name>')
    def download_report(name):
        content = verified(report_path(name), app.secret_key)
        if content is None:
            abort(404)
        return Response(content, mimetype='text/html', headers={
            'Content-Disposition': 'attachment; filename="CPreta-relatorio.html"'})

    @app.get('/relatorios/exportar.csv')
    def export_activity():
        period = 'week' if request.args.get('period') == 'week' else 'today'
        return Response(ledger.export_csv(period), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="CPreta-atividades.csv"'})

    @app.get('/relatorios/resumo.md')
    def export_summary():
        period = 'week' if request.args.get('period') == 'week' else 'today'
        data = ledger.dashboard(period)
        # Prefix every user-written line as quoted text in the exported document.
        def quote(value):
            return '\n'.join('> ' + line for line in str(value or '').splitlines())
        lines = ['# CPreta · Relatório de atividades', '', 'Período: ' + ('últimos 7 dias' if period == 'week' else 'hoje'),
                 f"Tempo em atividades: {duration(data['active'])}", f"Tempo ocioso: {duration(data['idle'])}", '']
        for item in data['activities']:
            lines += ['## Atividade', quote(item['title']), f"Tempo: {duration(item['duration'])}", 'Cliente / demanda:', quote(item['client'] + ' / ' + item['project']), '']
            for update in item['updates']:
                lines += ['### Atualização', 'Como foi feito:', quote(update['note']),
                          f"Tentativas: {update['attempts']} · acertos: {update['successes']} · erros: {update['failures']}",
                          'Falhas e motivos:', quote(update['reason']), 'Resultado e próximo passo:', quote(update['result']), '']
        return Response('\n'.join(lines), mimetype='text/markdown', headers={'Content-Disposition': 'attachment; filename="CPreta-resumo.md"'})

    @app.template_filter('duration')
    def duration(seconds):
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        return f'{hours}h {minutes:02d}min' if hours else f'{minutes}min' if minutes else f'{seconds}s'

    @app.route('/relatorios/visualizar/<path:name>')
    def visualizar(name):
        path = report_path(name)
        if path.suffix.lower() == '.html' and verified(path, app.secret_key) is not None:
            return render_template('saved_report.html', name=name, active='relatorios')
        if path.suffix.lower() not in ('.txt', '.md', '.json', '.csv', '.log', '.html', '.htm'):
            abort(415)
        if path.stat().st_size > 2 * 1024 * 1024:
            flash('Este arquivo ultrapassa o limite de visualização de 2 MB. Abra-o diretamente na pasta local.', 'error')
            return redirect(url_for('relatorios'))
        content = path.read_bytes()[:2 * 1024 * 1024].decode('utf-8', errors='replace')
        return render_template('visualizar.html', name=name, content=content, active='relatorios')

    @app.template_filter('file_size')
    def file_size(size):
        return f'{size / 1024:.1f} KB' if size >= 1024 else f'{size} B'

    @app.template_filter('local_date')
    def local_date(timestamp):
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y · %H:%M')

    return app


if __name__ == '__main__':
    from launcher import run
    run()
