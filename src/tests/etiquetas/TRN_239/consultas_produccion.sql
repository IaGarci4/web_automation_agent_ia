/* ============================================================================
   TRN-239 · Consultas para PRODUCCIÓN — sin datos sensibles

   Archivo SEPARADO de `consultas_bd.sql` a propósito. Ese otro es para TEST y
   trae `SELECT *`, que en producción sacaría teléfonos, nombres y PINes de
   clientes reales. Tenerlos en dos archivos evita el copiar-pegar
   desafortunado a las once de la noche.

   Todo lo de aquí se puede pegar en un correo, en un ticket de Jira o en un
   Confluence sin pensárselo.

   ----------------------------------------------------------------------------
   QUÉ SE OMITE, Y POR QUÉ
   ----------------------------------------------------------------------------
   Phone, TopupPhone .......... datos personales de clientes reales
   SenderName/Address/City/State  datos personales del remitente
   Pin ........................ ES DINERO. Un PIN de recarga filtrado se gasta
   AccessNumber ............... credencial de acceso al producto
   Key ........................ el nonce de `MD5(Login + Password + Key)`.
                                Con Key y Md5 juntos se puede atacar la
                                contraseña sin conexión. Es lo más peligroso
                                de toda la tabla y lo que menos lo parece
   CID, ExternalID, Entity .... identifican agencia y usuario. Se agregan o
                                se cuentan, nunca se listan
   Login ...................... nombre de la cuenta de servicio

   Lo que SÍ sale: SKU, importes, comisiones, estados y fechas. Es todo lo que
   la comparación de la migración necesita.
   ============================================================================ */


/* ---------------------------------------------------------------------------
   1) EL RESUMEN — sustituye al `SELECT TOP 10 *`
   Una fila por producto, sin ningún dato de cliente. Es lo que hay que
   comparar contra lo que registre la API nueva en TEST.
   --------------------------------------------------------------------------- */
SELECT TOP (100)
    t.SKU,
    MAX(t.SKUName)            AS SKUName,
    t.SKUType,
    COUNT(*)                  AS Envios,
    SUM(CASE WHEN t.LNStatus = 'SUCCESS' THEN 1 ELSE 0 END) AS Exitosas,
    SUM(CASE WHEN t.LNStatus = 'VOID'    THEN 1 ELSE 0 END) AS Canceladas,
    SUM(CASE WHEN t.LNStatus = 'FAILT'   THEN 1 ELSE 0 END) AS Fallidas,
    MIN(t.Amount)             AS MontoMin,
    MAX(t.Amount)             AS MontoMax,
    AVG(t.Amount)             AS MontoMedio,
    MIN(t.TransactionDate)    AS Desde,
    MAX(t.TransactionDate)    AS Hasta
FROM lunex.TransferLN t
GROUP BY t.SKU, t.SKUType
ORDER BY Envios DESC;


/* ---------------------------------------------------------------------------
   2) COMISIONES por tipo de producto  →  punto 2 del brief
   La pregunta abierta más cara: cómo se calcula y se reparte la comisión.
   Sin un solo dato de cliente.
   --------------------------------------------------------------------------- */
SELECT
    t.SKUType,
    COUNT(*)                        AS Envios,
    /* ¿Es cierto que en ITU la comisión ES el D1Discount? */
    SUM(CASE WHEN t.D1Discount = t.Commission THEN 1 ELSE 0 END)
                                    AS ComisionIgualD1,
    AVG(t.D1Discount)               AS D1Medio,
    AVG(t.Commission)               AS ComisionMedia,
    AVG(t.AgentCommission)          AS AgenteMedia,
    AVG(t.CorpCommission)           AS CorpMedia,
    AVG(t.Fee)                      AS FeeMedio,
    /* Los CorpCommission NEGATIVOS: ¿son normales o un defecto? */
    SUM(CASE WHEN t.CorpCommission < 0 THEN 1 ELSE 0 END) AS CorpNegativas
FROM lunex.TransferLN t
GROUP BY t.SKUType
ORDER BY Envios DESC;


/* ---------------------------------------------------------------------------
   3) ¿Commission = AgentCommission + CorpCommission?  →  punto 2
   Si alguna fila no cuadra, ahí está el redondeo que hay que cazar.
   --------------------------------------------------------------------------- */
SELECT
    t.SKUType,
    COUNT(*) AS Filas,
    SUM(CASE WHEN ABS(t.Commission
                      - (t.AgentCommission + t.CorpCommission)) < 0.005
             THEN 1 ELSE 0 END) AS Cuadran,
    SUM(CASE WHEN ABS(t.Commission
                      - (t.AgentCommission + t.CorpCommission)) >= 0.005
             THEN 1 ELSE 0 END) AS NoCuadran,
    MAX(ABS(t.Commission - (t.AgentCommission + t.CorpCommission)))
                              AS DiferenciaMaxima
FROM lunex.TransferLN t
GROUP BY t.SKUType;


/* ---------------------------------------------------------------------------
   4) IdStatus ↔ LNStatus  →  puntos 1 y 3
   Confirma el mapeo de estados y si 'Cancelled' existe en algún sitio.
   --------------------------------------------------------------------------- */
SELECT t.IdStatus, t.LNStatus, COUNT(*) AS Total
FROM lunex.TransferLN t
GROUP BY t.IdStatus, t.LNStatus
ORDER BY Total DESC;


/* ---------------------------------------------------------------------------
   5) EL DESFASE HORARIO  →  punto 6
   En TEST medimos +7 h y el requerimiento dice +8. Si en producción salen las dos
   cifras según la época del año, es horario de verano — y entonces cualquier
   prueba con un desfase fijo se rompe dos veces al año.
   Solo fechas: no hay nada personal aquí.
   --------------------------------------------------------------------------- */
SELECT
    DATEDIFF(HOUR, t.DateOfCreation, t.TransactionDate) AS HorasDeDesfase,
    COUNT(*)               AS Filas,
    MIN(t.DateOfCreation)  AS Desde,
    MAX(t.DateOfCreation)  AS Hasta
FROM lunex.TransferLN t
WHERE t.DateOfCreation IS NOT NULL AND t.TransactionDate IS NOT NULL
GROUP BY DATEDIFF(HOUR, t.DateOfCreation, t.TransactionDate)
ORDER BY Filas DESC;


/* ---------------------------------------------------------------------------
   6) ¿Phone y TopupPhone son el mismo número?  →  punto 8
   Contesta la pregunta SIN mostrar un solo dígito: solo si coinciden.
   --------------------------------------------------------------------------- */
SELECT
    t.SKUType,
    CASE WHEN t.Phone = t.TopupPhone THEN 'iguales' ELSE 'distintos' END
                        AS Comparacion,
    COUNT(*)            AS Filas
FROM lunex.TransferLN t
WHERE t.Phone IS NOT NULL AND t.TopupPhone IS NOT NULL
GROUP BY t.SKUType,
         CASE WHEN t.Phone = t.TopupPhone THEN 'iguales' ELSE 'distintos' END
ORDER BY Filas DESC;


/* ---------------------------------------------------------------------------
   7) ¿Un mismo SKU con varios nombres?  →  punto 8
   En TEST el 8485 aparece como «Honduras - Paquetigo» y como «T-Mobile USA».
   Si en producción también pasa, el SKUName que se guarda es el que manda el
   cliente y no se valida contra el catálogo.
   --------------------------------------------------------------------------- */
SELECT t.SKU, COUNT(DISTINCT t.SKUName) AS NombresDistintos,
       MIN(t.SKUName) AS Ejemplo1, MAX(t.SKUName) AS Ejemplo2
FROM lunex.TransferLN t
GROUP BY t.SKU
HAVING COUNT(DISTINCT t.SKUName) > 1
ORDER BY NombresDistintos DESC;


/* ---------------------------------------------------------------------------
   8) Coherencia de moneda  →  punto 8
   En TEST hay filas de Telcel (México) guardando CountryCurrency = 'HNL'.
   Si el par SKU ↔ moneda no es estable, esos campos se copian del request
   sin validar.
   --------------------------------------------------------------------------- */
SELECT t.SKU, MAX(t.SKUName) AS SKUName,
       COUNT(DISTINCT t.CountryCurrency) AS MonedasDistintas,
       COUNT(*) AS Filas
FROM lunex.TransferLN t
WHERE t.CountryCurrency IS NOT NULL
GROUP BY t.SKU
HAVING COUNT(DISTINCT t.CountryCurrency) > 1
ORDER BY MonedasDistintas DESC;


/* ---------------------------------------------------------------------------
   9) Duplicados de TransactionID  →  punto 5
   Si en producción hay TransactionID repetidos, la idempotencia no la
   garantiza la base de datos.
   --------------------------------------------------------------------------- */
SELECT TOP (50) t.TransactionID, COUNT(*) AS Veces,
       COUNT(DISTINCT t.LNStatus) AS EstadosDistintos
FROM lunex.TransferLN t
GROUP BY t.TransactionID
HAVING COUNT(*) > 1
ORDER BY Veces DESC;


/* ---------------------------------------------------------------------------
   10) DETALLE, si de verdad hace falta ver filas
   Últimas 20, con lo identificable enmascarado. Úsala solo si las agregadas
   no bastan: aunque va enmascarada, sigue siendo detalle de producción.
   --------------------------------------------------------------------------- */
SELECT TOP (20)
    t.IdTransferLN,
    t.SKU, t.SKUName, t.SKUType,
    t.Amount, t.ExRate, t.AmountInMN, t.CountryCurrency,
    t.D1Discount, t.D2Discount, t.R1Discount, t.R2Discount,
    t.Commission, t.AgentCommission, t.CorpCommission, t.Fee,
    t.LNStatus, t.IdStatus,
    t.DateOfCreation, t.TransactionDate, t.DateOfCancel,
    /* Enmascarados: se conserva la FORMA del dato, no el dato */
    LEN(t.Phone)                                   AS LargoPhone,
    CASE WHEN t.Phone = t.TopupPhone THEN 'iguales'
         ELSE 'distintos' END                      AS PhoneVsTopup,
    CASE WHEN t.Pin IS NULL THEN 'sin PIN'
         ELSE 'CON PIN' END                        AS TienePin,
    'agencia_' + CONVERT(VARCHAR(10),
        DENSE_RANK() OVER (ORDER BY t.Entity))     AS AgenciaAnonima,
    t.IdSchema, t.IdAgentPaymentSchema
FROM lunex.TransferLN t
ORDER BY t.IdTransferLN DESC;
