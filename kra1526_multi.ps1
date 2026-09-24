<#
.SYNOPSIS
    KRA-1526 MULTI-AGENTE - Lanzador SEPARADO del run mono.

.DESCRIPTION
    Corre SOLO los casos multi-agente (CP08/CP09) en la AGENCIA 0040, con su
    propio reporte (aparte del mono). Requiere credenciales multiagente en el
    entorno (PORTAL_USER_MULTI / MAXI_USER_M).

        .\kra1526_multi.ps1            -> CP08 + CP09 (multi) + abre el reporte
        .\kra1526_multi.ps1 CP09       -> un solo caso multi

    Activa KRA1526_MULTI=1 por ti. Para cambiar de agencia: $env:KRA1526_AGENCY="XXXX".

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

$venv = Join-Path $raiz 'venv\Scripts\python.exe'
if (Test-Path $venv) { $py = $venv }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = 'python' }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $py = 'py' }
else {
    Write-Host 'No encuentro Python (ni venv, ni python, ni py en el PATH).' -ForegroundColor Red
    exit 1
}

# Gate multi-agente + agencia por defecto 0040 (si no se fijo antes).
$env:KRA1526_MULTI = '1'
if (-not $env:KRA1526_AGENCY) { $env:KRA1526_AGENCY = '0040' }

$dir = 'src/tests/etiquetas/KRA_1526'
$reporte = Join-Path $raiz 'reports\evidence\KRA-1526\reporte_KRA-1526-multi.html'

switch -Regex ($Que) {

    '^todo$' {
        $res = Join-Path $raiz 'reports\evidence\KRA-1526\resultados_multi.json'
        if (Test-Path $res) { Remove-Item $res -Force -ErrorAction SilentlyContinue }
        & $py -m pytest $dir -m idor_multi -v -s @resto
        if (Test-Path $reporte) {
            Write-Host ''
            Write-Host "Reporte multi: $reporte" -ForegroundColor Cyan
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
        Write-Host '  .\kra1526_multi.ps1            (CP08 + CP09 multi, agencia 0040)'
        Write-Host '  .\kra1526_multi.ps1 CP09       (un caso multi)'
        Write-Host ''
        exit 2
    }
}
