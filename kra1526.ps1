<#
.SYNOPSIS
    KRA-1526 - Lanzador unico de la prueba de autorizacion IDOR (IdUser/IdAgent).

.DESCRIPTION
    Todo automatico, sin pegar curl: inicia sesion en Hermes 2 TEST, captura en
    vivo el request real de la busqueda global (token + IdUser/IdAgent propios),
    reproduce las variantes mono-agente y abre un reporte HTML estilo TRN-239.

    Se ejecuta desde la raiz del repo (C:\Repositorios\AutomationAgent).

        .\kra1526.ps1            -> TODO (7 casos) + abre el reporte
        .\kra1526.ps1 CP02       -> un solo caso (CP01..CP07)

    Los flags extra pasan de largo (ej. --headed, -k algo).

    ASCII a proposito: Windows PowerShell lee los .ps1 con cp1252.
#>

param(
    [Parameter(Position = 0)]
    [string]$Que = 'todo'
)
$resto = $args
$raiz = $PSScriptRoot
Set-Location $raiz
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# Python: venv del repo si existe, si no el del sistema.
$venv = Join-Path $raiz 'venv\Scripts\python.exe'
if (Test-Path $venv) { $py = $venv }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = 'python' }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $py = 'py' }
else {
    Write-Host 'No encuentro Python (ni venv, ni python, ni py en el PATH).' -ForegroundColor Red
    exit 1
}

# Forzar perfil MONO: si en esta misma sesion de PowerShell se corrio antes el
# runner multi, la variable KRA1526_MULTI=1 quedaria pegada y el reporte mono
# se escribiria en el archivo multi. La limpiamos SIEMPRE aqui.
$env:KRA1526_MULTI = '0'

$dir = 'src/tests/etiquetas/KRA_1526'
$reporte = Join-Path $raiz 'reports\evidence\KRA-1526\reporte_KRA-1526.html'

switch -Regex ($Que) {

    '^todo$' {
        # Reset del acumulado para que la corrida entregada sea limpia.
        $res = Join-Path $raiz 'reports\evidence\KRA-1526\resultados.json'
        if (Test-Path $res) { Remove-Item $res -Force -ErrorAction SilentlyContinue }
        & $py -m pytest $dir -m idor -v -s @resto
        if (Test-Path $reporte) {
            Write-Host ''
            Write-Host "Reporte: $reporte" -ForegroundColor Cyan
            Start-Process $reporte
        }
        break
    }

    '^CP\d' {
        & $py -m pytest $dir -k $Que -v -s @resto
        if (Test-Path $reporte) { Start-Process $reporte }
        break
    }

    default {
        Write-Host ''
        Write-Host "No reconozco '$Que'." -ForegroundColor Yellow
        Write-Host 'Usa una de estas:' -ForegroundColor Cyan
        Write-Host '  .\kra1526.ps1            (mono: CP01..CP07 + abre reporte)'
        Write-Host '  .\kra1526.ps1 CP02       (un caso mono)'
        Write-Host '  .\kra1526_multi.ps1      (multi-agente CP08/CP09, agencia 0040 - aparte)'
        Write-Host ''
        exit 2
    }
}
