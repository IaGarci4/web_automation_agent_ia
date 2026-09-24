/* ============================================================================
   TRN-239 · Validar que SKUType (DTU/ITU) corresponda al PAÍS real del SKU
   ----------------------------------------------------------------------------
   Objetivo: garantizar que el SKUType que manda el script coincida con el país
   del producto. Regla (confirmada por producción):

       DTU = doméstico  → país = EE. UU.
       ITU = internacional → país ≠ EE. UU.

   La llave correcta es IdCountry (lunex.Product.IdCountry = Country.IdCountry).

   La consulta NO asume la regla: la COMPARA contra el SKUType que producción
   realmente usó para cada SKU (de lunex.TransferLN). Si la regla está bien,
   la columna Coincide sale 'OK'; si sale '** REVISAR' en muchos, se invierte.

   Ambiente: SQL Server. Ajusta el esquema de la tabla Country si hace falta
   (puede ser Country, dbo.Country u operation.Country).
   ============================================================================ */


/* ----------------------------------------------------------------------------
   PASO 0 · Encontrar el IdCountry de EE. UU. (se usa en la regla de abajo).
   Corre esto primero y confirma el IdCountry / cómo se llama.
---------------------------------------------------------------------------- */
SELECT IdCountry, CountryName, CountryCode, CountryCodeISO3166
FROM Country
WHERE CountryCodeISO3166 = 'US'
   OR CountryCode = 'USA'
   OR CountryName LIKE 'UNITED STATES%'
   OR CountryName LIKE 'USA%'
   OR CountryName LIKE 'ESTADOS UNIDOS%';


/* ----------------------------------------------------------------------------
   1 · INNER JOIN Producto ↔ País  +  SKUType esperado vs. real
   ----------------------------------------------------------------------------
   - SKUType_Esperado: lo que la regla país→tipo dice.
   - SKUType_Real: lo que producción usó para ese SKU (de TransferLN).
   - Coincide: 'OK' si concuerdan; '** REVISAR' si no.
   La detección de EE. UU. es tolerante (código ISO, código o nombre).
---------------------------------------------------------------------------- */
SELECT
    p.SKU,
    p.Product,
    p.IdCountry,
    c.CountryName,
    c.CountryCodeISO3166,
    p.IdCarrier,
    p.Margin,
    CASE
        WHEN c.CountryCodeISO3166 = 'US'
          OR c.CountryCode = 'USA'
          OR c.CountryName LIKE 'UNITED STATES%'
          OR c.CountryName LIKE 'USA%'
          OR c.CountryName LIKE 'ESTADOS UNIDOS%'
        THEN 'DTU'          -- doméstico (EE. UU.)
        ELSE 'ITU'          -- internacional (fuera de EE. UU.)
    END                                              AS SKUType_Esperado,
    t.SKUType_Real,
    CASE
        WHEN t.SKUType_Real IS NULL THEN '(sin ventas en TransferLN)'
        WHEN t.SKUType_Real =
             CASE WHEN c.CountryCodeISO3166 = 'US'
                    OR c.CountryCode = 'USA'
                    OR c.CountryName LIKE 'UNITED STATES%'
                    OR c.CountryName LIKE 'USA%'
                    OR c.CountryName LIKE 'ESTADOS UNIDOS%'
                  THEN 'DTU' ELSE 'ITU' END
        THEN 'OK'
        ELSE '** REVISAR'
    END                                              AS Coincide
FROM lunex.Product AS p
INNER JOIN Country AS c ON p.IdCountry = c.IdCountry
LEFT JOIN (
    /* El SKUType que producción realmente usó por SKU. Si un SKU tiene más de
       uno, MAX() basta para detectar el caso; el paso 2 los desglosa. */
    SELECT SKU, MAX(SKUType) AS SKUType_Real
    FROM lunex.TransferLN
    GROUP BY SKU
) AS t ON t.SKU = p.SKU
WHERE p.IdGenericstatus = 1                          -- solo productos activos
ORDER BY Coincide DESC, p.SKU;   -- los '** REVISAR' primero


/* ----------------------------------------------------------------------------
   2 · Solo las discrepancias (para reportar): país dice un tipo y producción
       usó otro, o un mismo SKU con DOS SKUType distintos.
---------------------------------------------------------------------------- */
SELECT
    p.SKU, p.Product, c.CountryName,
    CASE WHEN c.CountryCodeISO3166 = 'US' OR c.CountryCode = 'USA'
              OR c.CountryName LIKE 'UNITED STATES%' OR c.CountryName LIKE 'USA%'
              OR c.CountryName LIKE 'ESTADOS UNIDOS%'
         THEN 'DTU' ELSE 'ITU' END                   AS SKUType_Esperado,
    STRING_AGG(CONVERT(varchar(20), t.SKUType), ', ') AS Tipos_En_Produccion,
    COUNT(DISTINCT t.SKUType)                         AS CuantosTipos
FROM lunex.Product AS p
INNER JOIN Country AS c        ON p.IdCountry = c.IdCountry
INNER JOIN lunex.TransferLN AS t ON t.SKU = p.SKU
WHERE p.IdGenericstatus = 1
GROUP BY p.SKU, p.Product, c.CountryName, c.CountryCodeISO3166,
         c.CountryCode
HAVING COUNT(DISTINCT t.SKUType) > 1                  -- SKU con tipos mezclados
    OR MAX(t.SKUType) <> CASE WHEN c.CountryCodeISO3166 = 'US' OR c.CountryCode = 'USA'
                                   OR c.CountryName LIKE 'UNITED STATES%'
                                   OR c.CountryName LIKE 'USA%'
                                   OR c.CountryName LIKE 'ESTADOS UNIDOS%'
                              THEN 'DTU' ELSE 'ITU' END
ORDER BY CuantosTipos DESC, p.SKU;
