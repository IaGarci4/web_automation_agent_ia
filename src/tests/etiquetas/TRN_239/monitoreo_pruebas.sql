/* ============================================================================
   TRN-239 · Monitoreo manual de NUESTRAS pruebas en lunex.TransferLN
   ----------------------------------------------------------------------------
   Para correr en paralelo mientras se ejecuta la etiqueta o el happy path, y
   comparar a ojo lo que el script ENVÍA contra lo que la API PERSISTE.

   Ambiente: MaxiTest (SQL Server). Servidor 192.168.5.10.

   ¿Por qué esta consulta ve SOLO lo nuestro?
   El filtro principal es EnterByIdUser = TU usuario: es quien captura la
   transacción, así que todo lo que el script inserta queda a tu nombre y nada
   del resto del tráfico de TEST se cuela.

   >>> AJUSTA @EnterByIdUser CON TU ID ANTES DE CORRER <<<
   Si tu EnterByIdUser coincide con el IdUser del ExternalID, es 13491. Si no,
   ponlo aquí. Sin el valor correcto la consulta no devuelve nada.

   Como respaldo se deja también la identidad fija del script (Login, Entity,
   ExternalID, CID), por si alguna vez capturas con otro usuario:

       Login      = 'Lun3xProdUser'
       Entity     = 'MX01D3643A'
       ExternalID = 'M120312738S13491'   (= M{IdAgent*IdUser}S{IdUser}
                                             = M{8918*13491}S{13491})
       CID        = '797dd3a85456df7f014efd19320eefdw'

   Los teléfonos y montos son ALEATORIOS por diseño (bodies.py): cada fila que
   aparezca aquí debe corresponder 1:1 con una petición del log del script.
   ============================================================================ */

DECLARE @EnterByIdUser INT      = 13491;   -- << TU usuario. Confírmalo/ajústalo.
DECLARE @Login      VARCHAR(50) = 'Lun3xProdUser';
DECLARE @Entity     VARCHAR(50) = 'MX01D3643A';
DECLARE @ExternalID VARCHAR(50) = 'M120312738S13491';
DECLARE @CID        VARCHAR(50) = '797dd3a85456df7f014efd19320eefdw';
DECLARE @Desde      DATETIME    = CAST(GETDATE() AS DATE);   -- solo hoy


/* ----------------------------------------------------------------------------
   0) DESCUBRIR TU EnterByIdUser  (corre esto UNA vez, tras la primera alta)
   ----------------------------------------------------------------------------
   El script se autentica como 'Lun3xProdUser'. El EnterByIdUser que la API
   estampe en las filas puede ser tu 13491 o el que ese login resuelva en TEST.
   Esta consulta usa la identidad FIJA del script (no depende de EnterByIdUser)
   y te muestra qué usuario quedó, para que fijes @EnterByIdUser arriba con
   certeza.
---------------------------------------------------------------------------- */
SELECT DISTINCT t.EnterByIdUser, COUNT(*) AS Filas
FROM lunex.TransferLN AS t
WHERE t.Login      = @Login
  AND t.Entity     = @Entity
  AND t.ExternalID = @ExternalID
  AND t.CID        = @CID
  AND t.DateOfCreation >= @Desde
GROUP BY t.EnterByIdUser;


/* ----------------------------------------------------------------------------
   1) LO QUE ENVIAMOS, TAL COMO QUEDÓ GUARDADO  (comparación fila a fila)
   ----------------------------------------------------------------------------
   Una fila por transacción nuestra, con las columnas que el script randomiza
   y llena, más comprobaciones automáticas de las reglas que sacamos de
   producción. Verde/rojo a la vista, sin tener que hacer la cuenta.
---------------------------------------------------------------------------- */
SELECT
    t.TransactionID,
    t.SKU,
    t.SKUType,
    t.Amount,
    t.CountryCurrency                                   AS Moneda,
    t.ExRate,
    t.AmountInMN,

    /* Regla 1 (Query 10): AmountInMN = Amount * ExRate al centavo.
       En DTU las tres columnas van NULL: eso es CORRECTO, no descuadre. */
    CASE
        WHEN t.ExRate IS NULL AND t.AmountInMN IS NULL THEN 'DTU · sin conversion (ok)'
        WHEN t.ExRate IS NULL OR  t.AmountInMN IS NULL THEN '** revisar: una NULL y otra no'
        WHEN ABS(t.AmountInMN - (t.Amount * t.ExRate)) < 0.01 THEN 'ok'
        ELSE '** DESCUADRE Amount*ExRate'
    END                                                 AS Chk_AmountInMN,

    t.Phone,
    t.TopupPhone,

    /* Regla 2 (Query 6): en ITU/Pinless deben ser DISTINTOS; en DTU IGUALES. */
    CASE
        WHEN t.Phone = t.TopupPhone THEN 'iguales'
        ELSE 'distintos'
    END                                                 AS PhoneVsTopup,
    CASE
        WHEN t.SKUType = 'DTU'  AND t.Phone =  t.TopupPhone THEN 'ok'
        WHEN t.SKUType <> 'DTU' AND t.Phone <> t.TopupPhone THEN 'ok'
        ELSE '** revisar patron Phone/Topup'
    END                                                 AS Chk_Phone,

    t.D1Discount,
    t.Commission,
    t.AgentCommission,
    t.CorpCommission,
    t.Fee,

    /* Regla 3 (Query 2): en ITU, Commission = D1Discount, siempre. */
    CASE
        WHEN t.SKUType = 'ITU' AND ABS(t.Commission - t.D1Discount) < 0.01 THEN 'ok'
        WHEN t.SKUType = 'ITU' THEN '** ITU: Commission <> D1Discount'
        ELSE 'n/a (no ITU)'
    END                                                 AS Chk_ComisionITU,

    /* Regla 4 (Query 3): Commission = Agent + Corp, salvo DTU fee-based (=0). */
    CASE
        WHEN ABS(t.Commission - (t.AgentCommission + t.CorpCommission)) < 0.01 THEN 'suma ok'
        WHEN t.SKUType = 'DTU' AND t.Commission = 0 THEN 'DTU fee-based (esperado)'
        ELSE '** Commission <> Agent+Corp'
    END                                                 AS Chk_Reparto,

    t.LNStatus,
    t.IdStatus,

    /* Regla 5 (Query 4): 30/SUCCESS al alta, 22/VOID al cancelar. */
    CASE
        WHEN t.IdStatus = 30 AND t.LNStatus = 'SUCCESS' THEN 'alta ok'
        WHEN t.IdStatus = 22 AND t.LNStatus = 'VOID'    THEN 'cancelada ok'
        WHEN t.IdStatus = 22 AND t.LNStatus = 'SUCCESS' THEN '** 22 pero dice SUCCESS'
        ELSE '** estado inesperado'
    END                                                 AS Chk_Estado,

    t.IdSchema,
    t.DateOfCreation,
    t.TransactionDate,

    /* Regla 6 (Query 5/10): en prod el desfase es +1h; +7h delata doble
       conversion. Se calcula para vigilarlo en cada corrida. */
    DATEDIFF(MINUTE, t.DateOfCreation, t.TransactionDate) AS DesfaseMin,
    t.DateOfCancel
FROM lunex.TransferLN AS t
WHERE t.EnterByIdUser = @EnterByIdUser   -- << lo que capturaste TÚ
  AND t.DateOfCreation >= @Desde
  /* Filtro alternativo (descomenta y comenta EnterByIdUser si capturas con
     otro usuario): la identidad fija del script.
  AND t.Login = @Login AND t.Entity = @Entity
  AND t.ExternalID = @ExternalID AND t.CID = @CID
  */
ORDER BY t.DateOfCreation DESC;   -- lo más reciente arriba


/* ----------------------------------------------------------------------------
   2) RESUMEN DE LA CORRIDA  (¿cuántas altas, cuántas canceladas, hay descuadre?)
   ----------------------------------------------------------------------------
   Un vistazo rápido para saber si la corrida hizo lo que esperabas antes de
   ponerte a leer fila por fila.
---------------------------------------------------------------------------- */
SELECT
    COUNT(*)                                                    AS Transacciones,
    SUM(CASE WHEN t.IdStatus = 30 THEN 1 ELSE 0 END)           AS Altas_SUCCESS,
    SUM(CASE WHEN t.IdStatus = 22 THEN 1 ELSE 0 END)           AS Canceladas,
    SUM(CASE WHEN t.SKUType = 'ITU' THEN 1 ELSE 0 END)         AS ITU,
    SUM(CASE WHEN t.SKUType = 'DTU' THEN 1 ELSE 0 END)         AS DTU,
    /* Cuántas rompen alguna regla: si esto es > 0, hay algo que mirar. */
    SUM(CASE WHEN t.SKUType = 'ITU'
              AND ABS(t.Commission - t.D1Discount) >= 0.01 THEN 1 ELSE 0 END)
                                                               AS ITU_ComisionMal,
    SUM(CASE WHEN t.ExRate IS NOT NULL AND t.AmountInMN IS NOT NULL
              AND ABS(t.AmountInMN - (t.Amount * t.ExRate)) >= 0.01 THEN 1 ELSE 0 END)
                                                               AS AmountInMN_Descuadre,
    SUM(CASE WHEN t.SKUType <> 'DTU' AND t.Phone = t.TopupPhone THEN 1 ELSE 0 END)
                                                               AS Phone_PatronMal,
    MIN(t.DateOfCreation)                                       AS Primera,
    MAX(t.DateOfCreation)                                       AS Ultima
FROM lunex.TransferLN AS t
WHERE t.EnterByIdUser = @EnterByIdUser
  AND t.DateOfCreation >= @Desde;


/* ----------------------------------------------------------------------------
   3) BUSCAR UNA TRANSACCIÓN CONCRETA  (pega el TransactionID del log)
   ----------------------------------------------------------------------------
   Cuando el script imprime "tran=1757...", pégalo aquí para ver esa fila
   completa, con TODAS sus columnas, sin filtro de fecha.
---------------------------------------------------------------------------- */
-- SELECT * FROM lunex.TransferLN WHERE TransactionID = '<PEGA_AQUI_EL_TRANSACTIONID>';
