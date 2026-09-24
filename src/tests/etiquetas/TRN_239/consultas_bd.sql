/* ============================================================================
   TRN-239 · API Lunex — Consultas de base de datos

   La etiqueta automatizada ya valida la integridad por su cuenta
   (`flujos/bd.py`, caso CP08). Este archivo es para lo que NO puede hacer
   sola: mirar producción.

   El comparativo PROD-vs-TEST es manual por una razón — la etiqueta corre
   contra TEST y nadie debería darle a un arnés de pruebas credenciales de
   producción. Las consultas marcadas [PROD] las corre quien tenga ese
   acceso, y el resultado se compara a mano contra lo que registró la API
   nueva.

   Tablas: lunex.TransferLN (transacciones) · lunex.Product (catálogo)
   ============================================================================ */


/* ---------------------------------------------------------------------------
   1) ¿Quedó registrada la transacción que envié?
   El TransactionID sale del log de la corrida o del reporte HTML.
   --------------------------------------------------------------------------- */
DECLARE @TranID VARCHAR(20) = '1011257424';

SELECT TOP 1 *
FROM lunex.TransferLN
WHERE TransactionID = @TranID
ORDER BY 1 DESC;


/* ---------------------------------------------------------------------------
   2) ¿Se duplicó? — la comprobación de idempotencia, a mano.
   Más de una fila con el mismo TransactionID es una recarga cobrada dos veces.
   --------------------------------------------------------------------------- */
SELECT TransactionID, COUNT(*) AS Filas
FROM lunex.TransferLN
WHERE TransactionID = @TranID
GROUP BY TransactionID;


/* ---------------------------------------------------------------------------
   3) Últimas transacciones — revisión rápida tras una corrida.
   --------------------------------------------------------------------------- */
SELECT TOP (100) *
FROM lunex.TransferLN
ORDER BY 1 DESC;


/* ---------------------------------------------------------------------------
   4) Catálogo de productos activos.
   Es el mismo que lee `flujos/bd.py::productos_activos` para randomizar los
   SKU. Si aquí sale vacío, la etiqueta cae al catálogo fijo de parametros.py.
   --------------------------------------------------------------------------- */
SELECT SKU, Product, IdCarrier, IdCountry, Margin
FROM lunex.Product
WHERE IdGenericstatus = 1
ORDER BY Product;


/* ---------------------------------------------------------------------------
   5) VOID vs Cancelled — la pregunta abierta del brief.
   El Confluence documenta 'Cancelled' y el dev probó con 'VOID'. Esta
   consulta dice qué valores existen DE VERDAD en la tabla, que es la única
   respuesta que no depende de la memoria de nadie.
   --------------------------------------------------------------------------- */
SELECT Status, COUNT(*) AS Total
FROM lunex.TransferLN
GROUP BY Status
ORDER BY Total DESC;


/* ---------------------------------------------------------------------------
   6) Mapeo campo → columna (pregunta 1 del brief).
   Hasta que DEV confirme el mapeo, la etiqueta compara probando varios
   nombres candidatos y marca como NO VERIFICADO lo que no encuentra. Esta
   consulta lista las columnas reales: con ella se ajusta
   `flujos/bd.py::CANDIDATOS` y las comparaciones pasan a ser exactas.
   --------------------------------------------------------------------------- */
SELECT c.name AS Columna, t.name AS Tipo, c.max_length AS Largo,
       c.is_nullable AS Nulable
FROM sys.columns c
JOIN sys.types  t ON t.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('lunex.TransferLN')
ORDER BY c.column_id;


/* ===========================================================================
   COMPARATIVO CONTRA PRODUCCIÓN
   Correr en PROD y comparar contra lo que registró la API nueva en TEST.
   =========================================================================== */

/* 7a. [PROD] Volumen y rango de montos por producto.
   Si un SKU que en PROD mueve miles de envíos no aparece en TEST, o los
   rangos de monto no se parecen, la migración está tratando ese producto
   distinto. */
SELECT
    t.SKU,
    p.Product,
    COUNT(*)      AS Envios,
    MIN(t.Amount) AS MinAmount,
    MAX(t.Amount) AS MaxAmount,
    AVG(t.Amount) AS AvgAmount
FROM lunex.TransferLN t
LEFT JOIN lunex.Product p ON p.SKU = t.SKU
GROUP BY t.SKU, p.Product
ORDER BY Envios DESC;


/* 7b. [PROD] Distribución por estado — la semántica real de SUCCESS / FAILT /
   VOID / Cancelled en producción, contra la que debe cuadrar la API nueva. */
SELECT Status, COUNT(*) AS Total
FROM lunex.TransferLN
GROUP BY Status
ORDER BY Total DESC;


/* 7c. [PROD] Comisiones por tipo de producto (DTU vs ITU).
   Insumo de la pregunta 2 del brief: los rangos reales de Fee,
   CommissionPercentage y descuentos dicen qué debería salir del cálculo,
   aunque todavía no tengamos la fórmula. */
SELECT
    t.SKUType,
    COUNT(*)                    AS Envios,
    AVG(t.CommissionPercentage) AS ComisionMedia,
    AVG(t.Fee)                  AS FeeMedio,
    AVG(t.D1Discount)           AS D1Medio,
    AVG(t.R1Discount)           AS R1Medio
FROM lunex.TransferLN t
GROUP BY t.SKUType
ORDER BY Envios DESC;
