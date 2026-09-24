<#
.SYNOPSIS
    TRN-239 - Corre la etiqueta completa y abre los reportes.

.DESCRIPTION
    Un solo comando para probar todo:

        1. Comprueba que la API responde (preflight)
        2. Corre los 8 casos de prueba con pytest
        3. Corre el happy path (alta + cancelacion en una sola pasada)
        4. Cancela las altas SUCCESS/FAILT que dejo la corrida (limpieza)
        5. Abre los dos reportes HTML en el navegador

    Cada paso se ejecuta aunque el anterior falle: la gracia es tener el
    panorama completo en una corrida, no parar en el primer tropiezo. El
    codigo de salida es el de pytest, para que sirva en CI.

    Nota: se escribe en ASCII a proposito. Windows PowerShell 5.1 lee los .ps1
    con la codepage del sistema (cp1252), y cualquier caracter no-ASCII (como
    los recuadros - o acentos) sale como mojibake en consola.

.PARAMETER SinBD
    Salta las validaciones contra SQL Server. Usalo si no estas en la VPN.
    Los pasos que dependen de la base salen como NO VERIFICADO, no como PASS.

.PARAMETER SinHappyPath
    Solo los 8 casos, sin la corrida manual de alta y cancelacion.

.PARAMETER Sku
    Fuerza un SKU en el happy path. Por omision elige uno al azar del
    catalogo vivo de lunex.Product.

.PARAMETER NoAbrir
    No abre los reportes al terminar.

.PARAMETER SinLimpiar
    NO cancela al final las altas que dejo la corrida. Por defecto si se
    limpian (se cancelan via API) para no acumular datos en TEST. Con -SinBD
    la limpieza se omite igual, porque necesita leer la base.

.EXAMPLE
    .\tools\trn239_correr_todo.ps1
    .\tools\trn239_correr_todo.ps1 -SinBD
    .\tools\trn239_correr_todo.ps1 -Sku 8456
    .\tools\trn239_correr_todo.ps1 -SinLimpiar
#>

[CmdletBinding()]
param(
    [switch]$SinBD,
    [switch]$SinHappyPath,
    [string]$Sku,
    [switch]$NoAbrir,
    [switch]$SinLimpiar
)

$ErrorActionPreference = 'Continue'
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

# Los scripts de Python SI imprimen UTF-8 (recuadros, acentos) y se ven bien;
# esto asegura que la consola quede en UTF-8 para todos ellos.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Titulo($texto) {
    Write-Host ''
    Write-Host ('-' * 74) -ForegroundColor DarkGray
    Write-Host "  $texto" -ForegroundColor Cyan
    Write-Host ('-' * 74) -ForegroundColor DarkGray
}

# Python: usa el del venv si existe, si no el del sistema. Se resuelve una vez
# y se guarda en $py para no depender de que 'python' este en el PATH.
$venv = Join-Path $raiz 'venv\Scripts\python.exe'
if (Test-Path $venv) {
    $py = $venv
    Write-Host 'Python: venv del repo' -ForegroundColor DarkGray
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = 'python'
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $py = 'py'
} else {
    Write-Host 'No encuentro Python (ni venv, ni python, ni py en el PATH).' -ForegroundColor Red
    Write-Host 'Instala Python o activa el venv y vuelve a intentar.' -ForegroundColor Red
    exit 1
}

if ($SinBD) {
    $env:TRN239_VALIDAR_BD = '0'
    Write-Host 'Validacion de base de datos DESACTIVADA (-SinBD).' -ForegroundColor Yellow
    Write-Host 'Los pasos que dependen de SQL saldran como NO VERIFICADO.' -ForegroundColor Yellow
}

# 1. Preflight. Se pregunta antes de nada porque cambia como se lee todo lo
# demas: con la API caida, un caso negativo "pasa" sin haber probado nada.
Titulo '1/5 - Preflight: responde la API?'
& $py -m src.tests.etiquetas.TRN_239.preflight

# 2. Los 8 casos.
Titulo '2/5 - Casos de prueba (CP01 a CP08)'
& $py -m pytest src/tests/etiquetas/TRN_239 -v -s
$codigo = $LASTEXITCODE

# 3. Happy path.
if (-not $SinHappyPath) {
    Titulo '3/5 - Happy path: alta + cancelacion'
    $argumentos = @('src\tests\etiquetas\TRN_239\trn239_happy_path.py')
    if ($Sku) { $argumentos += @('--sku', $Sku) }
    & $py @argumentos
} else {
    Titulo '3/5 - Happy path OMITIDO (-SinHappyPath)'
}

# 4. Limpieza de TEST. La suite deja altas sin cancelar por corrida; se
# cancelan via API para no acumular datos. Filtra por nuestra identidad
# (EnterByIdUser + Login + Entity + ExternalID + CID). Necesita BD.
if ($SinLimpiar) {
    Titulo '4/5 - Limpieza OMITIDA (-SinLimpiar)'
} elseif ($SinBD) {
    Titulo '4/5 - Limpieza OMITIDA (sin BD no se puede saber que cancelar)'
} else {
    Titulo '4/5 - Limpieza: cancelar las altas que dejo la corrida'
    & $py src\tests\etiquetas\TRN_239\trn239_limpiar.py
}

# 5. Reportes.
Titulo '5/5 - Reportes'
$reportes = @(
    'reports\evidence\TRN-239\reporte_TRN-239.html',
    'reports\evidence\TRN-239\happy_path_TRN-239.html'
)
foreach ($r in $reportes) {
    $ruta = Join-Path $raiz $r
    if (Test-Path $ruta) {
        Write-Host "  $r" -ForegroundColor Green
        if (-not $NoAbrir) { Start-Process $ruta }
    } else {
        Write-Host "  $r  (no se genero)" -ForegroundColor DarkYellow
    }
}

Write-Host ''
Write-Host 'Recuerda como se lee esto:' -ForegroundColor Cyan
Write-Host '  pytest te dice si la AUTOMATIZACION corrio.'
Write-Host '  El reporte HTML te dice si hay un DEFECTO.'
Write-Host '  NO VERIFICADO no es un aprobado: es "no lo pude comprobar".'
Write-Host ''

exit $codigo
