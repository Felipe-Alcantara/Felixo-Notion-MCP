"""Testes da parte sem rede do script que importa artigos para a biblioteca."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.notion import importar_artigos_para_biblioteca as importador

COLUNAS = {
    "Name": {"nome": "Name", "tipo": "title", "titulo": True, "editavel": True},
    "Author": {"nome": "Author", "tipo": "select", "opcoes": ["Raphael Amorim"]},
    "Genres": {"nome": "Genres", "tipo": "multi_select", "opcoes": ["Computer Scinece", "Essays"]},
    "Tipo de conteúdo": {"nome": "Tipo de conteúdo", "tipo": "select", "opcoes": ["Livro"]},
    "Status": {"nome": "Status", "tipo": "status", "opcoes": ["Not started", "Finished"]},
    "Total Pages": {"nome": "Total Pages", "tipo": "number"},
    "URL da fonte": {"nome": "URL da fonte", "tipo": "url"},
    "Progress": {"nome": "Progress", "tipo": "formula", "editavel": False},
}
TIPOS = {nome: coluna["tipo"] for nome, coluna in COLUNAS.items()}


def artigo(chave: str = "a", **propriedades: object) -> importador.Artigo:
    base: dict[str, object] = {
        "Author": "Raphael Amorim",
        "Genres": ["Computer Scinece"],
        "Status": "Not started",
        "Total Pages": 2,
        "URL da fonte": f"https://exemplo.dev/{chave}/",
    }
    base.update(propriedades)
    return importador.Artigo(
        chave=chave, titulo=f"Artigo {chave}", propriedades=base, corpo="## Sobre"
    )


def test_lote_valido_nao_tem_problemas():
    assert importador.validar([artigo("a"), artigo("b")], COLUNAS, {}) == []


def test_opcao_inexistente_e_recusada_ate_ser_liberada():
    lote = [artigo("a", **{"Tipo de conteúdo": "Artigo"})]
    problemas = importador.validar(lote, COLUNAS, {})
    assert any("'Artigo' não é opção de 'Tipo de conteúdo'" in p for p in problemas)
    assert importador.validar(lote, COLUNAS, {"Tipo de conteúdo": {"Artigo"}}) == []


def test_erro_de_digitacao_em_multi_select_e_pego():
    problemas = importador.validar([artigo("a", Genres=["Computer Science"])], COLUNAS, {})
    assert any("'Computer Science' não é opção de 'Genres'" in p for p in problemas)


def test_coluna_calculada_inexistente_ou_titulo_sao_recusados():
    lote = [artigo("a", Progress=1, Inexistente="x", Name="outro")]
    problemas = " | ".join(importador.validar(lote, COLUNAS, {}))
    assert "'Progress' não aceita escrita" in problemas
    assert "coluna inexistente 'Inexistente'" in problemas
    assert "'Name' não aceita escrita" in problemas


def test_url_repetida_no_lote_e_url_ausente_sao_recusadas():
    repetida = artigo("b", **{"URL da fonte": "https://exemplo.dev/a/"})
    sem_url = artigo("c", **{"URL da fonte": ""})
    problemas = " | ".join(importador.validar([artigo("a"), repetida, sem_url], COLUNAS, {}))
    assert "b: mesma URL de a" in problemas
    assert "c: 'URL da fonte' ausente" in problemas


def test_tipos_errados_sao_recusados():
    lote = [artigo("a", Genres="Computer Scinece", **{"Total Pages": "2"})]
    problemas = " | ".join(importador.validar(lote, COLUNAS, {}))
    assert "'Genres' é multi_select e pede uma lista" in problemas
    assert "'Total Pages' é number" in problemas


def test_linha_existente_so_ganha_o_que_esta_vazio():
    desejadas = {"Author": "Raphael Amorim", "Total Pages": 3, "Status": "Not started"}
    atuais = {"Author": None, "Total Pages": 2, "Status": "Finished"}
    assert importador.completar_existente(desejadas, atuais, TIPOS) == {"Author": "Raphael Amorim"}


def test_multi_select_existente_recebe_so_os_valores_que_faltam():
    desejadas = {"Genres": ["Computer Scinece", "Essays"]}
    assert importador.completar_existente(
        desejadas, {"Genres": ["Computer Scinece"]}, TIPOS
    ) == {"Genres": ["Computer Scinece", "Essays"]}
    assert importador.completar_existente(
        desejadas, {"Genres": ["Essays", "Computer Scinece"]}, TIPOS
    ) == {}


def test_numero_zero_conta_como_preenchido():
    assert importador.completar_existente({"Total Pages": 3}, {"Total Pages": 0}, TIPOS) == {}


def test_argumentos_set_juntam_listas_em_csv():
    assert importador.argumentos_set({"Genres": ["A", "B"], "Total Pages": 2}) == [
        "--set",
        "Genres=A,B",
        "--set",
        "Total Pages=2",
    ]


def test_opcao_nova_mal_formada_e_recusada():
    assert importador.ler_opcoes_novas(["Tipo de conteúdo=Artigo"]) == {
        "Tipo de conteúdo": {"Artigo"}
    }
    with pytest.raises(importador.Erro):
        importador.ler_opcoes_novas(["sem-igual"])


def test_carregar_rascunhos_exige_o_par_json_md(tmp_path: Path):
    dados = {"titulo": "Artigo x", "propriedades": {"URL da fonte": "https://exemplo.dev/x/"}}
    (tmp_path / "x.json").write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(importador.Erro, match="falta o corpo"):
        importador.carregar_rascunhos(tmp_path)
    (tmp_path / "x.md").write_text("## Sobre\n", encoding="utf-8")
    [carregado] = importador.carregar_rascunhos(tmp_path)
    assert carregado.chave == "x"
    assert carregado.url == "https://exemplo.dev/x/"
    assert carregado.corpo == "## Sobre"


def test_opcoes_livres_aceitam_qualquer_valor_mas_nao_virgula():
    colunas = {**COLUNAS, "Tags": {"nome": "Tags", "tipo": "multi_select", "opcoes": []}}
    lote = [artigo("a", Tags=["rails", "llms"])]
    assert any("não é opção de 'Tags'" in p for p in importador.validar(lote, colunas, {}))
    assert importador.validar(lote, colunas, {}, ["Tags"]) == []
    com_virgula = [artigo("b", Tags=["a,b"])]
    assert any("vírgula" in p for p in importador.validar(com_virgula, colunas, {}, ["Tags"]))


def test_anexo_exige_coluna_de_arquivos_e_arquivo_existente(tmp_path: Path):
    colunas = {**COLUNAS, "PDF": {"nome": "PDF", "tipo": "files"}}
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    ok = artigo("a")
    ok.anexos["PDF"] = str(pdf)
    assert importador.validar([ok], colunas, {}) == []
    ruim = artigo("b")
    ruim.anexos.update({"Author": str(pdf), "PDF": str(tmp_path / "sumiu.pdf")})
    problemas = " | ".join(importador.validar([ruim], colunas, {}))
    assert "'Author', que não é coluna de arquivos" in problemas
    assert "arquivo do anexo não existe" in problemas


def test_aparencia_so_aceita_icone_e_capa():
    item = artigo("a")
    item.aparencia.update({"icone": "📘", "fundo": "x"})
    assert any("aparência só aceita" in p for p in importador.validar([item], COLUNAS, {}))


def test_nao_completar_tira_do_indice_a_linha_do_livro():
    url = "https://blog/post/"
    linhas = [
        {"id": "livro", "propriedades": {"URL da fonte": url, "Tipo de conteúdo": "Livro"}},
        {
            "id": "audio",
            "propriedades": {"URL da fonte": "https://blog/outro/", "Tipo de conteúdo": "Áudio"},
        },
    ]
    filtros = importador.ler_filtros(["Tipo de conteúdo=Livro"])
    indice = importador.indexar_por_url(linhas, filtros)
    assert url not in indice
    assert indice["https://blog/outro/"]["id"] == "audio"
    assert importador.indexar_por_url(linhas)[url]["id"] == "livro"
    with pytest.raises(importador.Erro):
        importador.ler_filtros(["sem-igual"])


def test_rascunho_le_anexos_e_aparencia(tmp_path: Path):
    dados = {
        "titulo": "Artigo x",
        "propriedades": {"URL da fonte": "https://exemplo.dev/x/"},
        "anexos": {"PDF": "C:/x.pdf"},
        "aparencia": {"icone": "📘", "capa": ""},
    }
    (tmp_path / "x.json").write_text(json.dumps(dados), encoding="utf-8")
    (tmp_path / "x.md").write_text("## Sobre\n", encoding="utf-8")
    [carregado] = importador.carregar_rascunhos(tmp_path)
    assert carregado.anexos == {"PDF": "C:/x.pdf"}
    assert carregado.aparencia == {"icone": "📘"}


def test_cli_roda_pelo_python_do_checkout_sem_passar_por_shell():
    comando, ambiente = importador.comando_cli("felipe", ["criar", 'Palestra "Ruby & GC"'])
    assert comando[:3] == [importador.sys.executable, "-m", "felixo_notion_mcp.api.cli"]
    assert comando[3:] == ["--json", "--perfil", "felipe", "criar", 'Palestra "Ruby & GC"']
    assert str(importador.SRC_DO_CHECKOUT) in ambiente["PYTHONPATH"]
    assert ambiente["PYTHONUTF8"] == "1"
    assert not any(parte.lower().endswith((".cmd", ".bat")) for parte in comando)
