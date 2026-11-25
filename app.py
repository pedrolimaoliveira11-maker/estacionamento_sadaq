from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
import math

app = Flask(__name__)
app.secret_key = 'chave_secreta_estacionamento'
DB_NAME = 'estacionamento.db'

PRECOS = {
    'hora': 10.00,
    'diaria': 50.00,
    'anual': 1200.00
}

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def agora_iso():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Todas as tabelas agora possuem colunas DATETIME
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            telefone TEXT,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            placa TEXT NOT NULL UNIQUE,
            modelo_marca TEXT NOT NULL,
            cor TEXT,
            tamanho TEXT,
            tipo TEXT,
            ano INTEGER,
            cliente_id INTEGER,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS vagas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            tipo TEXT NOT NULL,
            ocupada INTEGER DEFAULT 0,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            veiculo_id INTEGER NOT NULL,
            vaga_id INTEGER NOT NULL,
            entrada DATETIME NOT NULL,
            saida DATETIME,
            tipo_cobranca TEXT NOT NULL,
            valor_pago REAL DEFAULT 0,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (veiculo_id) REFERENCES veiculos(id),
            FOREIGN KEY (vaga_id) REFERENCES vagas(id)
        );
    ''')

    cursor.execute('SELECT COUNT(*) FROM vagas')
    if cursor.fetchone()[0] == 0:
        agora = agora_iso()
        vagas_iniciais = [
            ('P01', 'Preferencial', agora, agora),
            ('P02', 'Preferencial', agora, agora),
            ('P03', 'Preferencial', agora, agora),
            ('N01', 'Normal', agora, agora),
            ('N02', 'Normal', agora, agora),
            ('N03', 'Normal', agora, agora),
            ('N04', 'Normal', agora, agora),
            ('N05', 'Normal', agora, agora),
            ('N06', 'Normal', agora, agora)
        ]
        cursor.executemany(
            'INSERT INTO vagas (numero, tipo, criado_em, atualizado_em) VALUES (?, ?, ?, ?)',
            vagas_iniciais
        )

    conn.commit()
    conn.close()

def formatar_data_br(data_iso):
    if not data_iso:
        return '-'
    dt = datetime.strptime(data_iso, '%Y-%m-%d %H:%M:%S')
    return dt.strftime('%d/%m/%Y %H:%M:%S')

@app.route('/')
def index():
    conn = get_db()
    
    vagas_raw = conn.execute('SELECT * FROM vagas ORDER BY tipo DESC, numero ASC').fetchall()
    vagas = []
    for v in vagas_raw:
        item = dict(v)
        item['atualizado_em_br'] = formatar_data_br(v['atualizado_em'])
        vagas.append(item)

    vagas_livres = sum(1 for v in vagas if v['ocupada'] == 0)
    vagas_ocupadas = len(vagas) - vagas_livres

    ativos_raw = conn.execute('''
        SELECT m.id, v.placa, v.modelo_marca, v.cor, v.tipo as tipo_veiculo, c.nome as cliente,
               vg.numero as vaga, vg.tipo as tipo_vaga, m.entrada, m.tipo_cobranca
        FROM movimentacoes m
        JOIN veiculos v ON m.veiculo_id = v.id
        JOIN clientes c ON v.cliente_id = c.id
        JOIN vagas vg ON m.vaga_id = vg.id
        WHERE m.saida IS NULL
        ORDER BY m.id DESC
    ''').fetchall()

    ativos = []
    for a in ativos_raw:
        item = dict(a)
        item['entrada_br'] = formatar_data_br(a['entrada'])
        ativos.append(item)

    historico_raw = conn.execute('''
        SELECT m.id, v.placa, v.modelo_marca, c.nome as cliente, m.entrada, m.saida, m.tipo_cobranca, m.valor_pago
        FROM movimentacoes m
        JOIN veiculos v ON m.veiculo_id = v.id
        JOIN clientes c ON v.cliente_id = c.id
        WHERE m.saida IS NOT NULL
        ORDER BY m.id DESC
    ''').fetchall()

    historico = []
    for h in historico_raw:
        item = dict(h)
        item['entrada_br'] = formatar_data_br(h['entrada'])
        item['saida_br'] = formatar_data_br(h['saida'])
        historico.append(item)

    total_faturado = conn.execute('SELECT COALESCE(SUM(valor_pago), 0) FROM movimentacoes').fetchone()[0]

    conn.close()
    return render_template(
        'index.html',
        vagas=vagas,
        vagas_livres=vagas_livres,
        vagas_ocupadas=vagas_ocupadas,
        ativos=ativos,
        historico=historico,
        total_faturado=total_faturado,
        precos=PRECOS
    )

@app.route('/entrada', methods=['POST'])
def registrar_entrada():
    conn = get_db()
    cursor = conn.cursor()

    nome_cliente = request.form['nome_cliente'].strip()
    telefone = request.form['telefone'].strip()
    placa = request.form['placa'].upper().strip()
    modelo_marca = request.form['modelo_marca'].strip()
    cor = request.form['cor'].strip()
    tamanho = request.form['tamanho']
    tipo_veiculo = request.form['tipo_veiculo']
    ano = request.form['ano'] or None
    vaga_id = request.form['vaga_id']
    tipo_cobranca = request.form['tipo_cobranca']
    agora = agora_iso()

    ja_estacionado = cursor.execute('''
        SELECT m.id FROM movimentacoes m
        JOIN veiculos v ON m.veiculo_id = v.id
        WHERE v.placa = ? AND m.saida IS NULL
    ''', (placa,)).fetchone()

    if ja_estacionado:
        flash(f'Erro: O veículo de placa {placa} já está estacionado no pátio!', 'erro')
        conn.close()
        return redirect(url_for('index'))

    # 1. Insere cliente com DATETIME
    cursor.execute('INSERT INTO clientes (nome, telefone, criado_em) VALUES (?, ?, ?)', (nome_cliente, telefone, agora))
    cliente_id = cursor.lastrowid

    # 2. Insere ou atualiza veículo com DATETIME
    cursor.execute('SELECT id FROM veiculos WHERE placa = ?', (placa,))
    veiculo = cursor.fetchone()
    if veiculo:
        veiculo_id = veiculo['id']
        cursor.execute('''
            UPDATE veiculos SET modelo_marca=?, cor=?, tamanho=?, tipo=?, ano=?, cliente_id=?, atualizado_em=?
            WHERE id=?
        ''', (modelo_marca, cor, tamanho, tipo_veiculo, ano, cliente_id, agora, veiculo_id))
    else:
        cursor.execute('''
            INSERT INTO veiculos (placa, modelo_marca, cor, tamanho, tipo, ano, cliente_id, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (placa, modelo_marca, cor, tamanho, tipo_veiculo, ano, cliente_id, agora, agora))
        veiculo_id = cursor.lastrowid

    # 3. Insere movimentação com DATETIME
    cursor.execute('''
        INSERT INTO movimentacoes (veiculo_id, vaga_id, entrada, tipo_cobranca, criado_em)
        VALUES (?, ?, ?, ?, ?)
    ''', (veiculo_id, vaga_id, agora, tipo_cobranca, agora))
    
    # 4. Atualiza vaga e grava DATETIME da alteração
    cursor.execute('UPDATE vagas SET ocupada = 1, atualizado_em = ? WHERE id = ?', (agora, vaga_id))

    conn.commit()
    conn.close()
    flash(f'Entrada registrada com sucesso para a placa {placa} às {agora[11:]}!', 'sucesso')
    return redirect(url_for('index'))

@app.route('/saida/<int:mov_id>')
def registrar_saida(mov_id):
    conn = get_db()
    cursor = conn.cursor()

    mov = cursor.execute('''
        SELECT m.*, v.placa FROM movimentacoes m
        JOIN veiculos v ON m.veiculo_id = v.id
        WHERE m.id = ?
    ''', (mov_id,)).fetchone()

    if mov and not mov['saida']:
        entrada_dt = datetime.strptime(mov['entrada'], '%Y-%m-%d %H:%M:%S')
        saida_dt = datetime.now()
        
        tipo = mov['tipo_cobranca']
        if tipo == 'hora':
            horas = math.ceil((saida_dt - entrada_dt).total_seconds() / 3600)
            horas = max(1, horas)
            valor = horas * PRECOS['hora']
        else:
            valor = PRECOS[tipo]

        saida_str = saida_dt.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('UPDATE movimentacoes SET saida = ?, valor_pago = ? WHERE id = ?', (saida_str, valor, mov_id))
        cursor.execute('UPDATE vagas SET ocupada = 0, atualizado_em = ? WHERE id = ?', (saida_str, mov['vaga_id']))
        flash(f"Saída liberada! Placa {mov['placa']} — Valor cobrado: R$ {valor:.2f}", 'sucesso')

    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)