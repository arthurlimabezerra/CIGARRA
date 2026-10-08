import os
import json
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import get_connection

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'chave_secreta_poli_upe_substitua_em_producao')

# Fuso horário fixo de Recife/Pernambuco (UTC-3)
FUSO_RECIFE = timezone(timedelta(hours=-3))

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def limpar_cpf(cpf_bruto):
    return ''.join(filter(str.isdigit, str(cpf_bruto))) if cpf_bruto else ''


# ---------------------------------------------------------
# ROTAS DE PÁGINAS (HTML)
# ---------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/coordenador')
def coordenador_page():
    return render_template('coord_panel.html')


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ---------------------------------------------------------
# ROTAS DE AUTENTICAÇÃO
# ---------------------------------------------------------

@app.route('/me', methods=['GET'])
def usuario_atual():
    if 'user_id' in session:
        return jsonify({
            "status": "success",
            "user": {
                "id": session['user_id'],
                "nome": session.get('user_nome'),
                "cpf": session.get('user_cpf'),
                "perfil": session.get('user_perfil')
            }
        }), 200
    return jsonify({"status": "error", "message": "Não autenticado"}), 401


@app.route('/cadastrar', methods=['POST'])
def cadastrar():
    data = request.json
    nome = data.get('nome')
    cpf = limpar_cpf(data.get('cpf'))
    senha = data.get('senha')

    if not nome or not cpf or not senha:
        return jsonify({"status": "error", "message": "Preencha o Nome, CPF e Senha."}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id FROM usuarios WHERE cpf = %s", (cpf,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"status": "error", "message": "CPF já cadastrado no sistema."}), 400

        senha_hash = generate_password_hash(senha)
        cursor.execute(
            "INSERT INTO usuarios (nome, cpf, senha_hash, perfil) VALUES (%s, %s, %s, 'aluno')",
            (nome, cpf, senha_hash)
        )
        conn.commit()

        new_id = cursor.lastrowid
        conn.close()

        session['user_id'] = new_id
        session['user_nome'] = nome
        session['user_cpf'] = cpf
        session['user_perfil'] = 'aluno'

        return jsonify({
            "status": "success",
            "message": "Cadastro realizado com sucesso!",
            "user": {"id": new_id, "nome": nome, "cpf": cpf, "perfil": "aluno"}
        }), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    cpf = limpar_cpf(data.get('cpf'))
    senha = data.get('senha')

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nome, senha_hash, perfil FROM usuarios WHERE cpf = %s", (cpf,))
        usuario = cursor.fetchone()
        conn.close()

        if usuario and check_password_hash(usuario['senha_hash'], senha):
            session['user_id'] = usuario['id']
            session['user_nome'] = usuario['nome']
            session['user_cpf'] = cpf
            session['user_perfil'] = usuario['perfil']

            return jsonify({
                "status": "success",
                "user": {
                    "id": usuario['id'],
                    "nome": usuario['nome'],
                    "cpf": cpf,
                    "perfil": usuario['perfil']
                }
            })
        else:
            return jsonify({"status": "error", "message": "CPF ou senha incorretos."}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"status": "success", "message": "Sessão encerrada com sucesso."}), 200


# ---------------------------------------------------------
# ROTAS DE MODIFICAÇÃO DE MATRÍCULA
# ---------------------------------------------------------

@app.route('/listar-oferta-turmas', methods=['GET'])
def listar_oferta_turmas():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT 
                d.id AS disciplina_id,
                d.nome AS disciplina_nome,
                d.bloco,
                t.id AS turma_id,
                t.codigo_turma,
                t.turno,
                t.horario AS horario_descricao
            FROM disciplinas d
            LEFT JOIN turmas t ON d.id = t.disciplina_id
            ORDER BY d.nome ASC, t.codigo_turma ASC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        disciplinas_map = {}
        for row in rows:
            disc_id = row['disciplina_id']
            if disc_id not in disciplinas_map:
                disciplinas_map[disc_id] = {
                    "id": disc_id,
                    "nome": row['disciplina_nome'],
                    "bloco": row['bloco'],
                    "turmas": []
                }
            if row['turma_id']:
                disciplinas_map[disc_id]['turmas'].append({
                    "turma_id": row['turma_id'],
                    "codigo_turma": row['codigo_turma'],
                    "turno": row['turno'],
                    "horario": row['horario_descricao']
                })

        return jsonify({"status": "success", "disciplinas": list(disciplinas_map.values())})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/salvar-matricula-atual', methods=['POST'])
def salvar_matricula_atual():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Sessão expirada."}), 401

    aluno_id = session['user_id']
    data = request.json
    turmas_ids = data.get('turmas_ids', [])

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM matricula_atual WHERE aluno_id = %s", (aluno_id,))

        for t_id in turmas_ids:
            cursor.execute(
                "INSERT INTO matricula_atual (aluno_id, turma_id) VALUES (%s, %s)",
                (aluno_id, t_id)
            )

        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Grade atual salva com sucesso!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/minha-matricula-atual', methods=['GET'])
def minha_matricula_atual():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Não autenticado"}), 401

    aluno_id = session['user_id']
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT m.turma_id, d.nome AS disciplina_nome, t.codigo_turma, t.turno, t.horario AS horario_descricao
            FROM matricula_atual m
            JOIN turmas t ON m.turma_id = t.id
            JOIN disciplinas d ON t.disciplina_id = d.id
            WHERE m.aluno_id = %s
        """
        cursor.execute(query, (aluno_id,))
        matriculas = cursor.fetchall()
        conn.close()
        return jsonify({"status": "success", "matriculas": matriculas})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/enviar-apelo-modificacao', methods=['POST'])
def enviar_apelo_modificacao():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Sessão expirada."}), 401

    aluno_id = session['user_id']
    justificativa = request.form.get('justificativa')

    turmas_remover = json.loads(request.form.get('turmas_remover', '[]'))
    turmas_adicionar = json.loads(request.form.get('turmas_adicionar', '[]'))

    if not turmas_adicionar and not turmas_remover:
        return jsonify(
            {"status": "error", "message": "Selecione ao menos uma disciplina para adicionar ou remover."}), 400

    if not justificativa or not justificativa.strip():
        return jsonify({"status": "error", "message": "Digite a justificativa."}), 400

    caminho_arquivo = None
    file = request.files.get('documento')

    if file and file.filename != '':
        if not allowed_file(file.filename):
            return jsonify(
                {"status": "error", "message": "Formato de arquivo inválido. Envie apenas PDF, PNG ou JPG."}), 400

        filename = secure_filename(file.filename)
        caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], f"apelo_{aluno_id}_{filename}")
        file.save(caminho_arquivo)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Data e hora exatas no fuso horário UTC-3 (Recife)
        agora = datetime.now(FUSO_RECIFE).strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            "INSERT INTO solicitacoes_modificacao (aluno_id, justificativa, caminho_anexo, data_solicitacao) VALUES (%s, %s, %s, %s)",
            (aluno_id, justificativa, caminho_arquivo, agora)
        )
        solicitacao_id = cursor.lastrowid

        for t_id in turmas_remover:
            cursor.execute(
                "INSERT INTO itens_solicitacao_modificacao (solicitacao_id, tipo, turma_id) VALUES (%s, 'REMOVER', %s)",
                (solicitacao_id, t_id)
            )

        for t_id in turmas_adicionar:
            cursor.execute(
                "INSERT INTO itens_solicitacao_modificacao (solicitacao_id, tipo, turma_id) VALUES (%s, 'ADICIONAR', %s)",
                (solicitacao_id, t_id)
            )

        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Solicitação enviada com sucesso!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# ROTAS DO COORDENADOR
# ---------------------------------------------------------

@app.route('/coordenador/solicitacoes', methods=['GET'])
def listar_todas_solicitacoes():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Procura em ordem cronológica crescente para sequenciar os pedidos (1º, 2º, 3º...)
        query_solicitacoes = """
            SELECT 
                s.id, s.aluno_id, u.nome AS aluno_nome, u.cpf AS aluno_cpf, 
                s.justificativa, s.caminho_anexo, s.status, s.data_solicitacao
            FROM solicitacoes_modificacao s
            JOIN usuarios u ON s.aluno_id = u.id
            ORDER BY s.data_solicitacao ASC
        """
        cursor.execute(query_solicitacoes)
        solicitacoes = cursor.fetchall()

        if not solicitacoes:
            conn.close()
            return jsonify({"status": "success", "solicitacoes": []})

        # 2. Atribui o número sequencial individual de cada aluno
        contador_por_aluno = {}
        for s in solicitacoes:
            aluno_id = s['aluno_id']
            contador_por_aluno[aluno_id] = contador_por_aluno.get(aluno_id, 0) + 1
            s['numero_pedido_aluno'] = contador_por_aluno[aluno_id]

            if isinstance(s.get('data_solicitacao'), datetime):
                s['data_solicitacao'] = s['data_solicitacao'].strftime('%Y-%m-%dT%H:%M:%S')

        # 3. Inverte a lista para exibir as mais recentes no topo do painel
        solicitacoes.reverse()

        solicitacao_ids = [s['id'] for s in solicitacoes]
        format_strings = ','.join(['%s'] * len(solicitacao_ids))

        query_itens = f"""
            SELECT i.solicitacao_id, i.tipo, d.nome AS disciplina_nome, t.codigo_turma, t.horario AS horario_descricao
            FROM itens_solicitacao_modificacao i
            JOIN turmas t ON i.turma_id = t.id
            JOIN disciplinas d ON t.disciplina_id = d.id
            WHERE i.solicitacao_id IN ({format_strings})
        """
        cursor.execute(query_itens, tuple(solicitacao_ids))
        todos_itens = cursor.fetchall()
        conn.close()

        itens_por_solicitacao = {}
        for item in todos_itens:
            s_id = item.pop('solicitacao_id')
            if s_id not in itens_por_solicitacao:
                itens_por_solicitacao[s_id] = []
            itens_por_solicitacao[s_id].append(item)

        for s in solicitacoes:
            s['itens'] = itens_por_solicitacao.get(s['id'], [])

        return jsonify({"status": "success", "solicitacoes": solicitacoes})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/coordenador/alterar-status', methods=['POST'])
def alterar_status_solicitacao():
    data = request.json
    solicitacao_id = data.get('id')
    novo_status = data.get('status')

    if not solicitacao_id or not novo_status:
        return jsonify({"status": "error", "message": "Dados incompletos."}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE solicitacoes_modificacao SET status = %s WHERE id = %s",
            (novo_status, solicitacao_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"Solicitação {novo_status.lower()} com sucesso!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/coordenador/grade-aluno/<int:aluno_id>', methods=['GET'])
def buscar_grade_aluno(aluno_id):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT 
                d.nome AS disciplina_nome,
                d.bloco,
                t.codigo_turma,
                t.turno,
                t.horario AS horario_descricao
            FROM matricula_atual m
            JOIN turmas t ON m.turma_id = t.id
            JOIN disciplinas d ON t.disciplina_id = d.id
            WHERE m.aluno_id = %s
            ORDER BY d.bloco ASC, d.nome ASC
        """
        cursor.execute(query, (aluno_id,))
        matriculas = cursor.fetchall()
        conn.close()
        return jsonify({"status": "success", "matriculas": matriculas})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)