#!/bin/sh
# Valida um binário nativo já baixado numa máquina limpa (Linux ou macOS), sem Python.
#
# Uso:
#     sh validar_binario_limpo.sh <binario> <arquivo.sha256>
#
# Não instala nada e só usa o que todo sistema traz (sh, coreutils). Confere o SHA-256
# publicado, confirma que não há Python no PATH e roda --version, --help, tasks --help,
# doctor e --json doctor numa pasta de usuário descartável. No macOS também registra a
# assinatura e o que o Gatekeeper responde para o arquivo em quarentena. A saída é um
# relatório em Markdown; o código de saída é 1 se alguma conferência falhar.
#
# ACEITAR_PYTHON=1 só registra o Python encontrado em vez de falhar (o macOS sempre traz
# /usr/bin/python3, então lá a máquina nunca fica "sem Python" de verdade).

binario=$1
arquivo_sha=$2
if [ ! -f "$binario" ] || [ ! -f "$arquivo_sha" ]; then
    echo "Uso: sh validar_binario_limpo.sh <binario> <arquivo.sha256>" >&2
    exit 2
fi

falhas=0
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
sistema=$(uname -s)
base=$(mktemp -d)
copia="$base/$(basename "$binario")"
cp "$binario" "$copia"
chmod +x "$copia"

echo "## $(basename "$binario")"
echo
if [ "$sistema" = Darwin ]; then
    echo "- **Sistema:** $(sw_vers -productName) $(sw_vers -productVersion) ($(sw_vers -buildVersion))"
else
    echo "- **Sistema:** $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-desconhecido}")"
    echo "- **libc:** $(ldd --version 2>&1 | head -1)"
fi
echo "- **Kernel / arquitetura:** $(uname -sr) / $(uname -m)"
echo "- **Quando:** $(date -u '+%Y-%m-%d %H:%M UTC')"

pythons=$(command -v python3 python 2>/dev/null | tr '\n' ' ')
if [ -z "$pythons" ]; then
    echo "- **Python no PATH:** nenhum"
elif [ "${ACEITAR_PYTHON:-0}" = 1 ]; then
    echo "- **Python no PATH:** $pythons(aceito: o sistema traz e não dá para tirar)"
else
    echo "- **Python no PATH:** $pythons— a máquina **não está limpa**"
    falhas=$((falhas + 1))
fi

esperado=$(cut -d' ' -f1 "$arquivo_sha")
if command -v sha256sum >/dev/null 2>&1; then
    obtido=$(sha256sum "$copia" | cut -d' ' -f1)
else
    obtido=$(shasum -a 256 "$copia" | cut -d' ' -f1)
fi
if [ "$esperado" = "$obtido" ]; then
    echo "- **SHA-256:** confere com o publicado (\`$obtido\`)"
else
    echo "- **SHA-256:** **diferente** — publicado \`$esperado\`, baixado \`$obtido\`"
    falhas=$((falhas + 1))
fi

rodar() {
    # Pasta de usuário descartável e ambiente vazio: nada da conta de quem roda entra.
    env -i PATH="$PATH" HOME="$base/home" NOTION_AUTOMACOES_NO_UPDATE=1 "$copia" "$@" \
        >"$base/saida" 2>&1
    codigo=$?
    echo
    echo "### \`$*\` → código $codigo"
    echo
    echo '```'
    head -n 14 "$base/saida"
    echo '```'
    return $codigo
}
mkdir -p "$base/home"

if [ "$sistema" = Darwin ]; then
    echo
    echo "### Assinatura e Gatekeeper"
    echo
    echo '```'
    codesign -dv "$copia" 2>&1 | head -n 8
    # Quarentena igual à que o navegador grava num arquivo baixado.
    xattr -w com.apple.quarantine "0083;$(printf '%x' "$(date +%s)");Safari;" "$copia"
    echo "--- spctl com o arquivo em quarentena:"
    spctl --assess --type execute -vv "$copia" 2>&1
    echo "(código do spctl: $?)"
    echo '```'
    rodar --version || echo "Em quarentena o binário **não rodou** pelo terminal."
    xattr -d com.apple.quarantine "$copia"
    echo
    echo "Quarentena removida com \`xattr -d com.apple.quarantine\` (o passo manual)."
fi

rodar --version || falhas=$((falhas + 1))
rodar --help || falhas=$((falhas + 1))
rodar tasks --help || falhas=$((falhas + 1))
rodar doctor || falhas=$((falhas + 1))
rodar --json doctor || falhas=$((falhas + 1))

rm -rf "$base"
echo
if [ "$falhas" -eq 0 ]; then
    echo "**Resultado: aprovado.**"
else
    echo "**Resultado: reprovado ($falhas falha(s)).**"
    exit 1
fi
