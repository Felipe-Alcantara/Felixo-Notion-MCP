# Valida o binário nativo do Windows já baixado numa máquina limpa, sem Python.
#
# Uso:
#     powershell -ExecutionPolicy Bypass -File validar_binario_limpo.ps1 <binario.exe> <arquivo.sha256>
#
# Não instala nada. Confere o SHA-256 publicado, confirma que não há Python no PATH,
# registra a assinatura Authenticode, marca o arquivo como "baixado da internet" (a marca
# que aciona o SmartScreen) e roda --version, --help, tasks --help e doctor numa pasta de
# usuário descartável. A saída é um relatório em Markdown; sai com 1 se algo falhar.
#
# O aviso do SmartScreen só aparece ao abrir pelo Explorer, numa sessão com tela: aqui
# fica registrado que o arquivo marcado roda pelo terminal, não o aviso em si.

param(
    [Parameter(Mandatory = $true)][string]$Binario,
    [Parameter(Mandatory = $true)][string]$ArquivoSha
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$falhas = 0
$base = Join-Path $env:TEMP ("validar-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $base | Out-Null
$copia = Join-Path $base (Split-Path $Binario -Leaf)
Copy-Item $Binario $copia

$so = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
"## $(Split-Path $Binario -Leaf)"
""
"- **Sistema:** $($so.ProductName) $($so.DisplayVersion) (build $($so.CurrentBuild).$($so.UBR))"
"- **Arquitetura:** $env:PROCESSOR_ARCHITECTURE"
"- **Quando:** $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')) UTC"

$pythons = @(Get-Command python, python3, py -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
if ($pythons.Count -eq 0) {
    "- **Python no PATH:** nenhum"
} else {
    "- **Python no PATH:** $($pythons -join ', ') - a máquina **não está limpa**"
    $falhas++
}

$esperado = ((Get-Content $ArquivoSha -Raw).Trim() -split '\s+')[0].ToLower()
$obtido = (Get-FileHash $copia -Algorithm SHA256).Hash.ToLower()
if ($esperado -eq $obtido) {
    "- **SHA-256:** confere com o publicado (``$obtido``)"
} else {
    "- **SHA-256:** **diferente** - publicado ``$esperado``, baixado ``$obtido``"
    $falhas++
}

"- **Assinatura Authenticode:** $((Get-AuthenticodeSignature $copia).Status)"
Set-Content -Path $copia -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
"- **Marca de arquivo baixado (Zone.Identifier):** gravada, ZoneId=3"

$env:NOTION_AUTOMACOES_NO_UPDATE = "1"
$env:USERPROFILE = Join-Path $base "home"
$env:APPDATA = Join-Path $base "home\AppData\Roaming"
$env:LOCALAPPDATA = Join-Path $base "home\AppData\Local"
New-Item -ItemType Directory -Force -Path $env:APPDATA, $env:LOCALAPPDATA | Out-Null

foreach ($argumentos in @(@("--version"), @("--help"), @("tasks", "--help"), @("doctor"))) {
    $saida = & $copia @argumentos 2>&1 | Out-String
    $codigo = $LASTEXITCODE
    ""
    "### ``$($argumentos -join ' ')`` → código $codigo"
    ""
    '```'
    ($saida -split "`r?`n" | Select-Object -First 14) -join "`n"
    '```'
    if ($codigo -ne 0) { $falhas++ }
}

Remove-Item -Recurse -Force $base -ErrorAction SilentlyContinue
""
if ($falhas -eq 0) {
    "**Resultado: aprovado.**"
} else {
    "**Resultado: reprovado ($falhas falha(s)).**"
    exit 1
}
