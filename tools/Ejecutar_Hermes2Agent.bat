@echo off
REM ============================================================================
REM  Copia versionada del lanzador del Hermes2Agent con CDP abierto (KRA-860 /
REM  WebView2). Mantener en sync con el .bat del Desktop del equipo QA.
REM
REM  Abre el puerto de depuracion para que Playwright se enganche al WebView2:
REM    --remote-debugging-port=9222  -> endpoint CDP en 127.0.0.1:9222
REM    --remote-allow-origins=*      -> OBLIGATORIO (si no, el websocket CDP da 403)
REM
REM  Solo builds STAGE/QA. Verifica con:  python tools\agent_cdp_check.py
REM  Si el puerto NO abre, el agente fija los args por codigo -> ver Fallback en
REM  docs/AGENTE_CDP_WEBVIEW2.md (cambio de 1 linea del lado dev, epic KRA-860).
REM ============================================================================
set "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222 --remote-allow-origins=*"
start "" "C:\MaxiInstall\Maxi\HERMES2_agent.Installer\Hermes2Agent.exe"
exit /b
