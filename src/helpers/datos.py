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

from src.helpers.zips_us import zip_aleatorio, US_STATES
from src.helpers.direcciones_us import domicilio_aleatorio

# Rango de montos para pruebas (USD, ENTEROS, sin centavos). Parametrizable.
MONTO_MIN = 100
MONTO_MAX = 400


# ════════════════════════════════════════════════════════════════════════════
#  REGLA DE CONTACTO — teléfonos y correos que NUNCA deben ser de alguien
# ════════════════════════════════════════════════════════════════════════════
#
# En TEST un teléfono aleatorio no molesta a nadie. **En PRODUCCIÓN sí**: la
# transacción es real, y Hermes ofrece mandar el recibo digital por SMS. Un
# número inventado al azar tiene dueño; si acierta con uno activo, una persona
# ajena recibe el recibo de una prueba. Eso es una fuga de datos de un cliente
# real y no hay forma de deshacerlo.
#
# Por eso la regla no es «acordarse en producción», es que el generador lo haga
# solo:
#
#     Ambiente TEST/STAGE  →  cualquier número (Faker)
#     Ambiente PRODUCCIÓN  →  número IMPOSIBLE, reservado, sin destinatario
#
# Los rangos elegidos no son inventados:
#
#   • EE.UU. — el plan de numeración norteamericano (NANP) reserva el bloque
#     `555-0100` a `555-0199` en CUALQUIER área para uso ficticio. Es el rango
#     que se usa en cine y televisión justo para esto: no se asigna a nadie.
#   • Correo — los dominios `example.com`/`.net`/`.org` están reservados por la
#     RFC 2606 y no tienen buzones: un correo enviado ahí no llega a ningún
#     sitio.
#   • México — no existe un rango ficticio oficial. Se usa la LADA `555`, que
#     no es asignable (Ciudad de México es la LADA `55`, de dos dígitos), así
#     que no enruta. ⚠️ Antes de la primera corrida en producción conviene que
#     Cumplimiento lo confirme; se puede cambiar sin tocar código con
#     TEL_FICTICIO_MX.
_AMBIENTES_PRODUCCION = ("PROD", "PRD", "PRODUCCION", "PRODUCCIÓN", "PRODUCTION",
                         "LIVE")


def es_produccion(ambiente: str = None) -> bool:
    """True si el ambiente configurado es producción."""
    amb = (ambiente or os.getenv("ENV") or os.getenv("AMBIENTE") or "").strip()
    if not amb:
        try:
            from config import settings
            amb = str(getattr(settings, "ENV", "") or "")
        except Exception:
            amb = ""
    return amb.strip().upper() in _AMBIENTES_PRODUCCION


def telefono_ficticio(pais: str = "us") -> str:
    """Teléfono de 10 dígitos GARANTIZADO sin destinatario.

    Se usa siempre que el ambiente sea producción, sin que el flujo tenga que
    pedirlo: la protección que hay que recordar activar es la que un día se
    olvida."""
    if str(pais).lower().startswith(("mx", "mex")):
        # LADA no asignable + 7 dígitos: 555 XXX XXXX
        base = os.getenv("TEL_FICTICIO_MX", "555")
        return base + "".join(str(random.randint(0, 9))
                              for _ in range(max(0, 10 - len(base))))
    # EE.UU.: área real + central 555 + línea 01NN (bloque ficticio del NANP)
    area = os.getenv("TEL_FICTICIO_US_AREA", "210")
    return f"{area}555{random.randint(100, 199):04d}"[:10]


def correo_ficticio() -> str:
    """Correo en un dominio reservado por la RFC 2606: no tiene buzón."""
    return f"qa.kra{random.randint(1000, 9999)}@example.com"


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
        self._dom = None   # domicilio REAL elegido una vez: dirección y zip coherentes

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

    def telefono(self, pais: str = "us") -> str:
        """Teléfono según la regla de ambiente. Úsalo en vez de Faker a pelo.

        TEST → cualquiera. PRODUCCIÓN → imposible, sin destinatario."""
        if es_produccion():
            return telefono_ficticio(pais)
        return self.fake.numerify("##########")

    def telefono_prefijo(self, prefijo: str = "573", largo: int = 10) -> str:
        """
        Teléfono que RESPETA un prefijo obligatorio (Validation Rule). Ej. para
        Uniteller Colombia el beneficiario debe empezar con '573' (KRA-1125):
        telefono_prefijo('573', 10) → '573' + 7 dígitos aleatorios.

        En PRODUCCIÓN se conserva el prefijo —lo exige la validación— pero el
        resto se rellena con un bloque que no enruta: los móviles colombianos
        empiezan por 3, así que un abonado que arranca con 0 no existe. El
        prefijo manda porque sin él el formulario se rechaza; lo que se elige es
        que dentro de lo válido en forma, sea imposible en destino.
        """
        import random
        prefijo = "".join(ch for ch in str(prefijo) if ch.isdigit())
        faltan = max(0, largo - len(prefijo))
        if es_produccion():
            relleno = "000" + "".join(str(random.randint(0, 9))
                                      for _ in range(max(0, faltan - 3)))
            return prefijo + relleno[:faltan]
        return prefijo + "".join(str(random.randint(0, 9)) for _ in range(faltan))

    # ── Domicilio REAL (dirección + zip coherentes) ─────────────────────────

    def _domicilio(self) -> dict:
        """Elige UN domicilio real la primera vez y lo reutiliza toda la corrida.

        Así `us_zip` y `address` salen del MISMO lugar: la dirección existe y
        casa con el ZIP, que es lo que exige el validador de Hermes. Ver
        `direcciones_us.py`.
        """
        if self._dom is None:
            self._dom = domicilio_aleatorio()
        return self._dom

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
            # En producción, número imposible SIEMPRE. Se decide aquí y no en
            # cada flujo a propósito: si hay que acordarse de pedirlo, algún
            # día no se pide — y el precio de ese día es que un cliente real
            # reciba por SMS el recibo de una prueba.
            if es_produccion():
                pais = "mx" if ("benef" in t or "mx" in t) else "us"
                return telefono_ficticio(pais)
            return self.fake.numerify("##########")
        # ZIP de EE.UU. REAL, del MISMO domicilio que la dirección (así casan).
        # Hermes autocompleta City/State desde el zip. Debe ir ANTES del zip
        # genérico porque "us_zip" contiene "zip".
        if "us_zip" in t or "uszip" in t:
            return self._domicilio()["zip"]
        # Ciudad/estado de EE.UU. del mismo domicilio (por si un flujo los pide
        # en vez de dejar que Hermes autocomplete). Estado en NOMBRE COMPLETO.
        if "us_city" in t:
            return self._domicilio()["ciudad"]
        if "us_state" in t:
            return US_STATES.get(self._domicilio()["estado"],
                                 self._domicilio()["estado"])
        if "address" in t or "direccion" in t:
            # Dirección REAL (pública/comercial) que EXISTE y casa con el
            # us_zip: el validador de Hermes exige que la dirección sea real.
            # Ya no se inventa con Faker. Ver `direcciones_us.py`.
            return _ascii_limpio(self._domicilio()["direccion"])
        if "zip" in t or "postal" in t:
            return self.fake.numerify("#####")
        if "email" in t or "mail" in t:
            # Mismo riesgo que el teléfono: el recibo digital también puede irse
            # por correo. Faker inventa dominios que a veces existen de verdad.
            return correo_ficticio() if es_produccion() else self.fake.email()
        if "city" in t or "ciudad" in t:
            return _sin_acentos(self.fake.city())
        if "date" in t or "fecha" in t or "birth" in t:
            return self.fake.date_of_birth(minimum_age=18, maximum_age=80).strftime("%m/%d/%Y")
        if "amount" in t:
            return str(random.randint(MONTO_MIN, MONTO_MAX))
        if "number" in t or "num" in t:
            return self.fake.numerify("######")
        return _sin_acentos(self.fake.word())
