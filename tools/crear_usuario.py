"""
Alta/actualización de usuarios del LOGIN de la GUI (gui/usuarios.json).

El banco de usuarios NO se sube a git (está en .gitignore), así que cada máquina
tiene el suyo. Para que un compañero entre a la GUI en SU computadora, corre esto
una vez ahí con su correo y una contraseña.

Uso:
    python tools/crear_usuario.py correo@maxillc.com "SuPassword"
    python tools/crear_usuario.py --listar          # ver correos dados de alta

Dominios permitidos: @maxillc.com · @maxilabs.net · @maxiagentes.net
La contraseña se guarda hasheada (PBKDF2-HMAC-SHA256, salt por usuario).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.auth import crear_usuario, dominio_valido, cargar_usuarios  # noqa: E402


def main():
    args = sys.argv[1:]
    if args and args[0] in ("--listar", "-l", "list"):
        usuarios = cargar_usuarios()
        if not usuarios:
            print("(no hay usuarios dados de alta todavía)")
        else:
            print("Usuarios dados de alta:")
            for correo in sorted(usuarios):
                print(f"  • {correo}")
        return

    if len(args) < 2:
        print("Uso: python tools/crear_usuario.py <correo> \"<password>\"")
        print("     python tools/crear_usuario.py --listar")
        sys.exit(1)

    email = args[0].strip().lower()
    password = args[1]
    if not dominio_valido(email):
        print(f"✖ Dominio no permitido: {email}")
        print("  Usa un correo @maxillc.com, @maxilabs.net o @maxiagentes.net.")
        sys.exit(1)
    if len(password) < 6:
        print("✖ La contraseña debe tener al menos 6 caracteres.")
        sys.exit(1)

    crear_usuario(email, password)
    print(f"✓ Usuario '{email}' creado/actualizado.")
    print(f"  Total de usuarios: {len(cargar_usuarios())}.")


if __name__ == "__main__":
    main()
