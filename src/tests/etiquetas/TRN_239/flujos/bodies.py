"""
Construcción de los cuerpos de petición y de la firma.

Separado del cliente HTTP a propósito: un caso que quiere probar «qué pasa si
el Amount es negativo» necesita un cuerpo VÁLIDO y luego romper un solo campo.
Con la construcción aquí, el negativo es `body = alta(); body["Amount"] = -25`
— una línea que dice exactamente qué se está probando.
"""

import datetime
import hashlib
import json
import random
import time
from pathlib import Path
from xml.sax.saxutils import escape

from .. import parametros as P

# Espacios de nombres del requerimiento legacy. Se conservan tal cual: el servicio
# migrado sigue aceptando SOAP y el sobre tiene que ser el mismo que enviaba
# Urano, o la prueba de paridad no prueba nada.
NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_ADDR = "http://www.w3.org/2005/08/addressing"
NS_MAX = "http://schemas.datacontract.org/2004/07/MaxiBackOffice.Lunex.Payments.WCF"
ACCION_REGISTER = ("http://schemas.datacontract.org/2004/07/"
                   "MaxiBackOffice.Lunex.Payments.WCF/ILunexService/RegisterTransaction")
ACCION_CANCEL = ("http://schemas.datacontract.org/2004/07/"
                 "MaxiBackOffice.Lunex.Payments.WCF/ILunexService/CancelTransaction")


def md5_firma(key: int, login: str = None, password: str = None) -> str:
    """`MD5(Login + Password + Key)`, hex en minúsculas, UTF-8."""
    login = login if login is not None else P.LOGIN
    password = password if password is not None else P.PASSWORD
    return hashlib.md5(f"{login}{password}{key}".encode("utf-8")).hexdigest()


def fecha_gmt8() -> str:
    """`TransactionDate` en GMT-8.

    El requerimiento dice que la API suma 8 h internamente, así que la fecha se
    manda ya desplazada: si se enviara la hora local, lo persistido saldría
    con ocho horas de más y el caso de integridad fallaría por una conversión
    doble, no por un defecto real.

    Es una de las preguntas abiertas del brief — confirmar en BD que no hay
    doble conversión.
    """
    g8 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=8)
    return g8.strftime("%Y-%m-%dT%H:%M:%S")


def external_id(id_agent: int = None, id_user: int = None) -> str:
    """`M{IdAgent*IdUser}S{IdUser}` — la fórmula del requerimiento."""
    a = id_agent if id_agent is not None else P.ID_AGENT
    u = id_user if id_user is not None else P.ID_USER
    return f"M{a * u}S{u}"


def telefono() -> str:
    return str(random.randint(2000000000, 9999999999))


class Contadores:
    """`Key` y `TransactionID` incrementales, persistidos entre corridas.

    El requerimiento dice que `Key` es único e **irreutilizable**. Si se reinician
    en cada corrida, la segunda ejecución del día choca contra la primera y el
    fallo parece de la API cuando es del arnés. Se guardan en disco; si el
    archivo no existe se siembran desde el reloj, que garantiza no pisar nada
    de una corrida anterior.
    """

    def __init__(self, ruta: Path = None):
        self.ruta = Path(ruta or P.CONTADORES)
        try:
            self.estado = json.loads(self.ruta.read_text(encoding="utf-8"))
        except Exception:
            base = int(time.time() * 1000)
            self.estado = {"key": base, "tran": int(str(base)[-10:])}

    def siguiente(self, nombre: str) -> int:
        self.estado[nombre] = int(self.estado.get(nombre, 0)) + 1
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps(self.estado), encoding="utf-8")
        except Exception:
            pass
        return self.estado[nombre]


# ── Cuerpos JSON ────────────────────────────────────────────────────────────

def alta(cnt: Contadores, producto=None, *, monto: float = None,
         estado: str = None, transaction_id: str = None) -> dict:
    """Cuerpo de `RegisterTransaction`. Randomiza producto y teléfono.

    `transaction_id` se puede fijar: lo necesita el caso de idempotencia, que
    consiste precisamente en reenviar el mismo dos veces.
    """
    key = cnt.siguiente("key")
    tran = transaction_id or str(cnt.siguiente("tran"))
    sku, nombre, tipo = producto or random.choice(P.PRODUCTOS)

    # `Phone` y `TopupPhone` NO son el mismo campo, y depende del tipo.
    # Medido sobre 7 millones de filas de producción:
    #
    #     ITU      4 656 668 distintos  ·      2 994 iguales   (99.94 % distintos)
    #     Pinless    492 158 distintos  ·          0 iguales   (100 %)
    #     DTU         28 745 distintos  ·  1 842 767 iguales   (98.5 % iguales)
    #
    # Uno es el teléfono del cliente y el otro el número que se recarga. Antes
    # se mandaba el MISMO en los dos para todo, y en ITU eso reproducía un
    # caso que ocurre en el 0.06 % de la producción: se estaba probando la
    # excepción y no la regla.
    tel = telefono()
    tel_recarga = tel if tipo == "DTU" else telefono()

    # Monto, moneda y tipo de cambio coherentes con el producto (ver
    # `parametros.PERFIL_SKU`). `AmountInMN = Amount × ExRate` se cumple al
    # centavo en producción, así que se calcula en lugar de fijarse.
    pf = P.perfil(sku, tipo)
    if monto is None:
        monto = P.MONTO if pf["min"] <= P.MONTO <= pf["max"] else round(
            random.uniform(pf["min"], pf["max"]), 2)
    exrate = pf["exrate"]
    en_mn = round(monto * exrate, 2) if exrate is not None else None

    # `D1Discount` es la comisión que manda el cliente. En ITU la API la
    # persiste tal cual en `Commission` (4 659 662 de 4 659 662 filas). En los
    # DTU «fee based» se guarda 0 y la comisión real la pone el esquema del
    # agente — por eso aquí solo se manda un valor plausible y el CP06 lo
    # reporta sin exigirlo: la fórmula sigue siendo pregunta abierta.
    d1 = round(monto * 0.11, 2) if tipo == "ITU" else 1.50
    return {
        "Login": P.LOGIN,
        "Md5": md5_firma(key),
        "Key": key,
        "Action": "lunex",
        "Status": estado or P.ESTADO_ALTA,
        "TransactionID": tran,
        "TransactionDate": fecha_gmt8(),
        "CID": P.CID,
        "Entity": P.ENTITY,
        "ExternalID": external_id(),
        "SKU": sku,
        "SKUName": nombre,
        "SKUType": tipo,
        "Amount": monto,
        "Phone": tel,
        "TopupPhone": tel_recarga,
        "PIN": None,
        "D1Discount": d1,
        "D2Discount": 0,
        "R1Discount": 0,
        "R2Discount": 0,
        "Fee": 0,
        "CommissionPercentage": 9.00,
        "DestinationAmount": None,
        "DestinationCurrency": None,
        "ExRate": exrate,
        "AmountInMN": en_mn,
        "CountryCurrency": pf["moneda"],
        "Name": "None None",
        "Address": "",
        "City": "",
        "State": "",
        "AccessNumber": None,
        "ExpirationDate": None,
    }


def cancelacion(cnt: Contadores, transaction_id: str, sku: str,
                skutype: str, *, estado: str = None) -> dict:
    """Cuerpo de `CancelTransaction`. `Key` propia, distinta de la del alta."""
    key = cnt.siguiente("key")
    return {
        "Login": P.LOGIN,
        "Md5": md5_firma(key),
        "Key": key,
        "Action": "lunex",
        "Status": estado or P.ESTADO_CANCELACION,
        "TransactionID": str(transaction_id),
        "SKU": sku,
        "SKUType": skutype,
        "ExternalID": external_id(),
        "TransactionDate": fecha_gmt8(),
    }


# ── Sobre SOAP ──────────────────────────────────────────────────────────────

def _campo_soap(clave, valor) -> str:
    if valor is None:
        return f'<max:{clave} i:nil="true"/>'
    return f"<max:{clave}>{escape(str(valor))}</max:{clave}>"


def sobre_soap(cuerpo: dict, operacion: str = "RegisterTransaction") -> str:
    """Envuelve el MISMO diccionario del JSON en el sobre SOAP del legacy.

    Reutilizar el diccionario no es comodidad: es lo que hace honesta la
    prueba de paridad del CP02. Si los dos formatos se construyeran por
    separado, una diferencia entre ellos podría venir del arnés y no de la
    API, que es exactamente lo que la migración tiene que descartar.
    """
    accion = ACCION_REGISTER if operacion == "RegisterTransaction" else ACCION_CANCEL
    destino = P.BASE_URL + (P.RUTA_REGISTER if operacion == "RegisterTransaction"
                            else P.RUTA_CANCEL)
    campos = "\n            ".join(_campo_soap(k, v) for k, v in cuerpo.items())
    return f"""<s:Envelope xmlns:s="{NS_SOAP}"
            xmlns:a="{NS_ADDR}"
            xmlns:i="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:max="{NS_MAX}">
  <s:Header>
    <a:Action s:mustUnderstand="1">{accion}</a:Action>
    <a:To s:mustUnderstand="1">{escape(destino)}</a:To>
  </s:Header>
  <s:Body>
    <max:{operacion}>
      <max:request>
            {campos}
      </max:request>
    </max:{operacion}>
  </s:Body>
</s:Envelope>"""
