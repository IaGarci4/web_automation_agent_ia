"""
Datos — generador de datos de formulario con OVERRIDES + Faker por defecto.

Resuelve: "envío Elektra, cliente Juan Valdez Robledo, monto 158.25, lo demás
random". Cada campo libre del formulario toma:
  • el valor que el usuario fijó (override), si aplica; o
  • un valor Faker aleatorio (distinto en cada corrida, pero CONSISTENTE
    durante la misma corrida — mismo campo → mismo valor, vía cache).

Los overrides llegan por la variable de entorno FLOW_OVERRIDES (JSON), que el
agente arma desde la instrucción en lenguaje natural. Ejemplo:
    FLOW_OVERRIDES = {"cliente": "Juan Valdez Robledo", "monto": "158.25"}

Claves semánticas que entiende valor():
  customer_name / customer_last1 / customer_last2   (← override 'cliente')
  beneficiary_name / beneficiary_last1 / beneficiary_last2  (← 'beneficiario')
  phone · address · zip · us_zip · email · date · amount (← 'monto')

Campos geográficos/typeahead (país, ciudad, estado) NO se aleatorizan aquí:
los resuelve el flujo (país/ciudad del pagador, o el pool de
ciudades_estado_por_pais del catálogo de pagadores).
"""

import os
import re
import json
import random
import unicodedata
from faker import Faker

from src.helpers.zips_us import zip_aleatorio

# Rango de montos para pruebas (USD, ENTEROS, sin centavos). Parametrizable.
MONTO_MIN = 100
MONTO_MAX = 400


def _sin_acentos(texto: str) -> str:
    """
    Quita SOLO los acentos/diacríticos (á→a, ñ→n, Á→A), conservando el resto
    de caracteres (@ . / - espacios). Muchos portales (Hermes incluido)
    rechazan datos con acentos.
    """
    if texto is None:
        return texto
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")


def _ascii_limpio(texto: str) -> str:
    """Quita acentos y deja solo letras/números/espacios (sin caracteres raros)."""
    limpio = re.sub(r"[^A-Za-z0-9 ]", " ", _sin_acentos(texto))
    return re.sub(r"\s+", " ", limpio).strip()


class Datos:
    def __init__(self, locale: str = "es_MX"):
        self.fake = Faker(locale)
        self.fake_en = Faker("en_US")   # direcciones en inglés (sin acentos)
        try:
            self.over = json.loads(os.getenv("FLOW_OVERRIDES", "") or "{}")
        except Exception:
            self.over = {}
        self._cliente = str(self.over.get("cliente", "")).split()
        self._benef = str(self.over.get("beneficiario", "")).split()
        self._cache = {}   # consistencia: misma semántica → mismo valor en la corrida

    # ── Bandera de cancelación (la decide el usuario en lenguaje natural) ────

    @property
    def debe_cancelar(self) -> bool:
        """True si la instrucción pidió cancelar (env FLOW_CANCEL=1)."""
        return str(os.getenv("FLOW_CANCEL", "")).strip().lower() in ("1", "true", "si", "sí", "yes")

    def nombre_cliente(self) -> str:
        """
        Nombre del cliente USADO en el flujo (para buscarlo y cancelar después).
        Devuelve el override 'cliente' o el nombre Faker ya generado y cacheado.
        """
        if self._cliente:
            return " ".join(self._cliente)
        partes = [self._cache.get("customer_name", ""),
                  self._cache.get("customer_last1", ""),
                  self._cache.get("customer_last2", "")]
        return " ".join(p for p in partes if p).strip()

    # ── API principal ─────────────────────────────────────────────────────

    def valor(self, semantica: str, tipo: str = None) -> str:
        """
        Devuelve el override del campo o un valor Faker, SIEMPRE sin acentos.
        Conserva '@ . / -' para que email, fecha y monto sigan válidos.

        Cachea por `semantica`: el mismo campo devuelve el MISMO valor durante
        toda la corrida (necesario para buscar luego al cliente por su nombre).
        """
        if semantica in self._cache:
            return self._cache[semantica]
        val = _sin_acentos(self._valor_raw(semantica, tipo))
        self._cache[semantica] = val
        return val

    def _valor_raw(self, semantica: str, tipo: str = None) -> str:
        """Resuelve el valor (override o Faker) sin limpiar acentos todavía."""
        # Nombre del cliente (override 'cliente', dividido en palabras)
        if semantica == "customer_name" and self._cliente:
            return self._cliente[0]
        if semantica == "customer_last1" and len(self._cliente) > 1:
            return self._cliente[1]
        if semantica == "customer_last2" and len(self._cliente) > 2:
            return " ".join(self._cliente[2:])
        # Nombre del beneficiario (override 'beneficiario')
        if semantica == "beneficiary_name" and self._benef:
            return self._benef[0]
        if semantica == "beneficiary_last1" and len(self._benef) > 1:
            return self._benef[1]
        if semantica == "beneficiary_last2" and len(self._benef) > 2:
            return " ".join(self._benef[2:])
        # Monto (override 'monto') — SIEMPRE entero, sin centavos (125, 248, …)
        if semantica == "amount":
            if self.over.get("monto"):
                try:
                    return str(int(round(float(str(self.over["monto"]).replace(",", ".")))))
                except Exception:
                    return str(self.over["monto"])
            return str(random.randint(MONTO_MIN, MONTO_MAX))
        # Override directo por nombre semántico (ej. {"email": "x@y.com"})
        if semantica in self.over:
            return str(self.over[semantica])
        # Faker por tipo
        return self._faker(tipo or semantica)

    def monto(self) -> str:
        return self.valor("amount")

    def numero_cuenta(self) -> str:
        """Número de cuenta aleatorio de 11 a 16 dígitos (envíos tipo Depósito)."""
        import random
        n = random.randint(11, 16)
        return "".join(str(random.randint(0, 9)) for _ in range(n))

    def telefono_prefijo(self, prefijo: str = "573", largo: int = 10) -> str:
        """
        Teléfono que RESPETA un prefijo obligatorio (Validation Rule). Ej. para
        Uniteller Colombia el beneficiario debe empezar con '573' (KRA-1125):
        telefono_prefijo('573', 10) → '573' + 7 dígitos aleatorios.
        """
        import random
        prefijo = "".join(ch for ch in str(prefijo) if ch.isdigit())
        faltan = max(0, largo - len(prefijo))
        return prefijo + "".join(str(random.randint(0, 9)) for _ in range(faltan))

    # ── Faker por tipo de campo ────────────────────────────────────────────

    def _faker(self, tipo: str) -> str:
        t = (tipo or "").lower()
        if "first_name" in t or t == "name":
            return self.fake.first_name()
        if "last" in t:
            return self.fake.last_name()
        if "full" in t or "nombre" in t:
            return self.fake.name()
        if "phone" in t or "cell" in t or "tel" in t:
            return self.fake.numerify("##########")
        # ZIP de EE.UU. REAL (Hermes autocompleta City/State desde él).
        # Debe ir ANTES del zip genérico porque "us_zip" contiene "zip".
        if "us_zip" in t or "uszip" in t:
            return zip_aleatorio()
        if "address" in t or "direccion" in t:
            # Formato: "1452 road drive" — número de 4 dígitos + calle sin acentos
            numero = random.randint(1000, 9999)
            calle = _ascii_limpio(self.fake_en.street_name())
            return f"{numero} {calle}"
        if "zip" in t or "postal" in t:
            return self.fake.numerify("#####")
        if "email" in t or "mail" in t:
            return self.fake.email()
        if "city" in t or "ciudad" in t:
            return _sin_acentos(self.fake.city())
        if "date" in t or "fecha" in t or "birth" in t:
            return self.fake.date_of_birth(minimum_age=18, maximum_age=80).strftime("%m/%d/%Y")
        if "amount" in t:
            return str(random.randint(MONTO_MIN, MONTO_MAX))
        if "number" in t or "num" in t:
            return self.fake.numerify("######")
        return _sin_acentos(self.fake.word())
