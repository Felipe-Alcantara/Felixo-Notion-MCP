#!/usr/bin/env python3
"""Atualiza no Felixo AI Core as referências ao repositório antigo do Notion.

Uso:
    python3 scripts/migracao/atualizar_prompts_ai_core.py --simular
    python3 scripts/migracao/atualizar_prompts_ai_core.py [--banco CAMINHO]

Depois da etapa 1 do monolito (07/10/2026), o hub ``Automa-es-do-Notion`` virou o
repositório ``Felixo-Notion-MCP`` e o módulo ``notion_starter`` virou
``felixo_notion_mcp``. Os prompts de automação do AI Core (por exemplo o Workflow 3.0)
ainda citam os nomes antigos. Este script troca só trechos exatos e conhecidos:

- a URL do repositório no GitHub (a antiga ainda redireciona, mas deixa de ser a canônica);
- o caminho do módulo de histórico git usado nos relatórios;
- o nome do projeto do AI Core que aponta para a pasta do monolito.

A pasta local continua ``Automa-es-do-Notion`` até a etapa 4, então caminhos de disco não
mudam. Os prompts continuam mandando usar a CLI ``notion-tasks``: o MCP desta etapa ainda
não tem tudo o que a CLI faz (isso é a etapa 2).

Antes de escrever, guarda uma cópia do banco ao lado dele. É idempotente: sem trecho antigo,
nada é gravado. Feche o AI Core antes de rodar sem ``--simular``, para o app não regravar o
prompt antigo a partir da memória.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

BANCO_PADRAO = Path.home() / ".config" / "felixo-ai-core" / "database" / "felixo.sqlite"

TROCAS_NOS_PROMPTS = (
    (
        "https://github.com/Felipe-Alcantara/Automa-es-do-Notion",
        "https://github.com/Felipe-Alcantara/Felixo-Notion-MCP",
    ),
    ("notion_starter.git_historico", "felixo_notion_mcp.domain.git_historico"),
)
NOME_PROJETO_ANTIGO = "Automa-es-do-Notion"
NOME_PROJETO_NOVO = "Felixo-Notion-MCP"


def agora_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def trocar(texto: str) -> str:
    for antigo, novo in TROCAS_NOS_PROMPTS:
        texto = texto.replace(antigo, novo)
    return texto


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--banco", type=Path, default=BANCO_PADRAO, help="SQLite do AI Core")
    parser.add_argument("--simular", action="store_true", help="só lista o que mudaria")
    args = parser.parse_args(argv)

    if not args.banco.is_file():
        raise RuntimeError(f"Banco do AI Core não encontrado: {args.banco}")

    conexao = sqlite3.connect(args.banco)
    try:
        automacoes = [
            (identificador, nome, prompt)
            for identificador, nome, prompt in conexao.execute(
                "select id, name, prompt from automations"
            )
            if trocar(prompt) != prompt
        ]
        projetos = conexao.execute(
            "select id from projects where name = ?", (NOME_PROJETO_ANTIGO,)
        ).fetchall()

        for _, nome, _ in automacoes:
            print(f"[{'simula' if args.simular else 'muda'}] automação: {nome}")
        for (identificador,) in projetos:
            print(f"[{'simula' if args.simular else 'muda'}] projeto {identificador}: nome")
        if args.simular or not (automacoes or projetos):
            print(f"{len(automacoes)} automação(ões) e {len(projetos)} projeto(s) a mudar.")
            return 0

        copia = args.banco.with_name(
            f"{args.banco.stem}.antes-monolito-{datetime.now():%Y%m%d-%H%M%S}{args.banco.suffix}"
        )
        shutil.copy2(args.banco, copia)
        print(f"cópia de segurança: {copia}")

        momento = agora_iso()
        with conexao:
            for identificador, _, prompt in automacoes:
                conexao.execute(
                    "update automations set prompt = ?, updated_at = ? where id = ?",
                    (trocar(prompt), momento, identificador),
                )
            for (identificador,) in projetos:
                conexao.execute(
                    "update projects set name = ?, updated_at = ? where id = ?",
                    (NOME_PROJETO_NOVO, momento, identificador),
                )
        print(f"{len(automacoes)} automação(ões) e {len(projetos)} projeto(s) mudados.")
        return 0
    finally:
        conexao.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, sqlite3.Error) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        raise SystemExit(1) from erro
