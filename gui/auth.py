"""
Autenticación de la GUI (banco de usuarios Maxi).

Seguridad básica: contraseñas guardadas como PBKDF2-HMAC-SHA256 (salt por
usuario, 200k iteraciones). Esto es SOLO para entrar al agente — no tiene nada
que ver con credenciales de HERMES/Chronos u otros portales.

El banco vive en gui/usuarios.json. En el primer arranque se siembra con el
correo administrador y una contraseña por defecto (env AGENT_ADMIN_PASSWORD,
default 'Maxi2026*'). Cambia/agrega usuarios con crear_usuario().
"""

import hashlib
import json
import os
import secrets
from pathlib import Path

_ARCHIVO = Path(__file__).parent / "usuarios.json"

ADMIN_EMAIL = "ext.iagarcia@maxillc.com"
_ADMIN_PASS_DEFECTO = os.getenv("AGENT_ADMIN_PASSWORD", "Maxi2026*")

# Dominios de correo Maxi permitidos (banco de seguridad válido).
DOMINIOS_VALIDOS = ("@maxillc.com", "@maxilabs.net", "@maxiagentes.net")

MENSAJE_SOPORTE = ("Por favor contacte a soporte a través del correo "
                   "helpdesk@maxillc.com")

_ITERS = 200_000


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERS
    ).hex()


def cargar_usuarios() -> dict:
    if _ARCHIVO.exists():
        try:
            return json.loads(_ARCHIVO.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def guardar_usuarios(usuarios: dict) -> None:
    _ARCHIVO.write_text(json.dumps(usuarios, indent=2, ensure_ascii=False),
                        encoding="utf-8")


def crear_usuario(email: str, password: str) -> None:
    """Agrega o actualiza un usuario en el banco (con salt propio)."""
    usuarios = cargar_usuarios()
    salt = secrets.token_hex(16)
    usuarios[email.strip().lower()] = {"salt": salt, "hash": _hash(password, salt)}
    guardar_usuarios(usuarios)


def _sembrar_si_vacio() -> None:
    """Primer arranque: crea el usuario administrador si el banco está vacío."""
    usuarios = cargar_usuarios()
    if not usuarios:
        crear_usuario(ADMIN_EMAIL, _ADMIN_PASS_DEFECTO)


def dominio_valido(email: str) -> bool:
    return email.strip().lower().endswith(DOMINIOS_VALIDOS)


def verificar(email: str, password: str) -> bool:
    """True si el correo Maxi existe en el banco y la contraseña coincide."""
    _sembrar_si_vacio()
    email = (email or "").strip().lower()
    if not dominio_valido(email):
        return False
    usuarios = cargar_usuarios()
    u = usuarios.get(email)
    if not u:
        return False
    try:
        return secrets.compare_digest(_hash(password or "", u["salt"]), u["hash"])
    except Exception:
        return False
