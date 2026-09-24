/* ============================================================================
   TRN-239 · Buscar dónde se registra el "Validation error" (Errorcode 5)
   ----------------------------------------------------------------------------
   La API responde "Validation error" genérico, sin decir QUÉ campo falta
   (TRN-294). Este archivo NO valida nada: es para RASTREAR si ese error queda
   guardado en alguna tabla de log/auditoría, y así poder pedir a alguien de
   producción que lo revise (o revisarlo tú en TEST).

   Se corre por pasos, de arriba a abajo, en el ambiente TEST (MaxiTest).
   Ambiente: SQL Server, servidor 192.168.5.10.
   ============================================================================ */


/* ----------------------------------------------------------------------------
   PASO 1 · ¿Qué tablas podrían guardar logs o errores?
   Busca por nombre: log, error, audit, event, request, notif, trace.
---------------------------------------------------------------------------- */
SELECT s.name AS Esquema, t.name AS Tabla,
       p.rows AS FilasAprox
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE t.name LIKE '%log%'   OR t.name LIKE '%error%'
   OR t.name LIKE '%audit%' OR t.name LIKE '%event%'
   OR t.name LIKE '%request%' OR t.name LIKE '%notif%'
   OR t.name LIKE '%trace%'  OR t.name LIKE '%hist%'
ORDER BY p.rows DESC;


/* ----------------------------------------------------------------------------
   PASO 2 · ¿Qué columnas hablan de error/mensaje/validación?
   Aunque la tabla no se llame "log", una columna "ErrorText" la delata.
---------------------------------------------------------------------------- */
SELECT s.name AS Esquema, t.name AS Tabla, c.name AS Columna,
       ty.name AS Tipo
FROM sys.columns c
JOIN sys.tables t  ON t.object_id = c.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.types ty  ON ty.user_type_id = c.user_type_id
WHERE c.name LIKE '%error%'   OR c.name LIKE '%message%'
   OR c.name LIKE '%mensaje%' OR c.name LIKE '%validation%'
   OR c.name LIKE '%detail%'  OR c.name LIKE '%errorcode%'
   OR c.name LIKE '%response%' OR c.name LIKE '%request%'
ORDER BY s.name, t.name, c.name;


/* ----------------------------------------------------------------------------
   PASO 3 · Todo lo que cuelga del esquema lunex (por si el log vive ahí)
---------------------------------------------------------------------------- */
SELECT t.name AS Tabla, p.rows AS FilasAprox
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE s.name = 'lunex'
ORDER BY t.name;


/* ----------------------------------------------------------------------------
   PASO 4 · Plantilla: cuando el PASO 1/2 te dé una tabla de log, úsala aquí.
   Reemplaza <ESQUEMA>.<TABLA_LOG> y las columnas por las que hayan aparecido.
   La idea: ver los últimos errores registrados, filtrando por lo nuestro.
---------------------------------------------------------------------------- */
-- SELECT TOP 100 *
-- FROM <ESQUEMA>.<TABLA_LOG>
-- WHERE (<COLUMNA_TEXTO> LIKE '%Validation%' OR <COLUMNA_CODIGO> = 5)
--   AND <COLUMNA_FECHA> >= CAST(GETDATE() AS DATE)   -- de hoy
-- ORDER BY <COLUMNA_FECHA> DESC;


/* ----------------------------------------------------------------------------
   NOTA sobre dónde puede NO estar
   ----------------------------------------------------------------------------
   La API nueva es FastAPI. Es posible que los errores de validación (400/5)
   se registren en el LOG DE LA APLICACIÓN (archivo o stack de logs del
   servicio), no en SQL Server. Si los pasos 1-3 no devuelven nada, ese es el
   siguiente lugar a pedir: los logs del servicio en zeus-services. Con la
   marca de tiempo de la respuesta (`Reponse_timestamp`) y el `ResponseID` de
   la respuesta de la API se puede cruzar contra ese log.
---------------------------------------------------------------------------- */
