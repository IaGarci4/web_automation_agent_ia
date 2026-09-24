<#
.SYNOPSIS
    TRN-239 - Lanzador unico. Tres formas, un solo nombre que recordar.

.DESCRIPTION
    Se ejecuta siempre desde la raiz del repo (C:\Repositorios\AutomationAgent),
    asi que el comando no lleva rutas.

        .\trn239.ps1            -> TODO (preflight + 8 casos + happy path +
                                   limpieza + abre reportes)
        .\trn239.ps1 CP03       -> un solo caso (CP01..CP08)
        .\trn239.ps1 limpiar    -> cancela las altas que dejo la corrida

    Los flags extra pasan de largo. Ejemplos:
        .\trn239.ps1 -SinBD
        .\trn239.ps1 limpiar --dry-run

    Escrito en ASCII a proposito: Windows PowerShell lee los .ps1 con cp1252 y
    los caracteres raros salen como mojibake.
#>

param(
    [Parameter(Position = 0)]
    [string]$Que = 'todo'
)

# El resto de argumentos (flags como -SinBD, --dry-run) viaja en $args y se
# reenvia tal cual. Se usa $args en vez de [CmdletBinding]+RemainingArguments
# porque asi un flag desconocido pasa de largo en vez de reventar el lanzador.
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

switch -Regex ($Que) {

    '^todo$' {
        & (Join-Path $raiz 'tools\trn239_correr_todo.ps1') @resto
        break
    }

    '^limpi' {
        & $py 'src\tests\etiquetas\TRN_239\trn239_limpiar.py' @resto
        break
    }

    '^CP\d' {
        # Un solo caso, sin limpieza: para inspeccionar a mano.
        & $py -m pytest 'src/tests/etiquetas/TRN_239' -k $Que -v -s @resto
        break
    }

    default {
        Write-Host ''
        Write-Host "No reconozco '$Que'." -ForegroundColor Yellow
        Write-Host 'Usa una de estas:' -ForegroundColor Cyan
        Write-Host '  .\trn239.ps1            (todo)'
        Write-Host '  .\trn239.ps1 CP03       (un caso: CP01..CP08)'
        Write-Host '  .\trn239.ps1 limpiar    (cancelar lo que dejo la corrida)'
        Write-Host ''
        exit 2
    }
}
