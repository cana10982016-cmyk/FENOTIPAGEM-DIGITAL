-- Tabelas da Fenotipagem Digital no schema 'fenotipagem' (aplicado no projeto inovaagro em 2026-11-21).
-- O servidor também cria tudo sozinho ao subir com DB_SCHEMA=fenotipagem.
-- RLS ligado sem políticas: só o servidor (usuário postgres) acessa; o schema não é exposto na API do Supabase.
CREATE SCHEMA IF NOT EXISTS fenotipagem;
SET LOCAL search_path TO fenotipagem;
CREATE TABLE IF NOT EXISTS usuarios (
	id SERIAL NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	nome VARCHAR(200) NOT NULL, 
	senha_hash VARCHAR(200) NOT NULL, 
	admin BOOLEAN NOT NULL, 
	ativo BOOLEAN NOT NULL, 
	criado_em TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_usuarios_email ON usuarios (email);
CREATE TABLE IF NOT EXISTS ensaios (
	id SERIAL NOT NULL, 
	nome VARCHAR(300) NOT NULL, 
	cliente VARCHAR(300) NOT NULL, 
	local VARCHAR(300) NOT NULL, 
	cultura VARCHAR(200) NOT NULL, 
	variedade VARCHAR(200) NOT NULL, 
	observacoes TEXT NOT NULL, 
	tratamentos JSON NOT NULL, 
	croqui JSON NOT NULL, 
	ajustes JSON NOT NULL, 
	criado_por INTEGER, 
	criado_em TIMESTAMP WITH TIME ZONE NOT NULL, 
	atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(criado_por) REFERENCES usuarios (id)
);
CREATE TABLE IF NOT EXISTS voos (
	id SERIAL NOT NULL, 
	ensaio_id INTEGER NOT NULL, 
	rotulo VARCHAR(100) NOT NULL, 
	data_voo VARCHAR(20) NOT NULL, 
	arquivo VARCHAR(300) NOT NULL, 
	caminho VARCHAR(500) NOT NULL, 
	tamanho BIGINT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	erro TEXT NOT NULL, 
	crs VARCHAR(200) NOT NULL, 
	georref BOOLEAN NOT NULL, 
	largura INTEGER NOT NULL, 
	altura INTEGER NOT NULL, 
	gsd_m FLOAT, 
	previa VARCHAR(500) NOT NULL, 
	previa_w INTEGER NOT NULL, 
	previa_h INTEGER NOT NULL, 
	limites JSON, 
	otsu FLOAT, 
	limiar_usado FLOAT, 
	resultados JSON, 
	processado_em TIMESTAMP WITH TIME ZONE, 
	criado_em TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ensaio_id) REFERENCES ensaios (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_voos_ensaio_id ON voos (ensaio_id);
ALTER TABLE fenotipagem.usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE fenotipagem.ensaios ENABLE ROW LEVEL SECURITY;
ALTER TABLE fenotipagem.voos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON SCHEMA fenotipagem FROM anon, authenticated;