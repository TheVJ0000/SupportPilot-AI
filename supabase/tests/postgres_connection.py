"""Minimal test-only libpq binding using the existing PostgreSQL installation.

No new Python package. Connection values and SQL diagnostics never leave memory.
"""

import ctypes
import os
import shutil
from pathlib import Path

from certifi import where


class SqlFailure(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__("Database test SQLSTATE " + code)


class Postgres:
    def __init__(
        self, environment: dict[str, str], application: str = "supportpilot_security"
    ):
        executable = shutil.which("psql")
        if not executable:
            raise RuntimeError("Existing PostgreSQL client is required")
        directory = Path(executable).parent
        self.dll_directory = (
            os.add_dll_directory(str(directory)) if os.name == "nt" else None
        )
        self.library = ctypes.CDLL(
            str(directory / "libpq.dll") if os.name == "nt" else "libpq.so"
        )
        signatures = {
            "PQconnectdb": ([ctypes.c_char_p], ctypes.c_void_p),
            "PQstatus": ([ctypes.c_void_p], ctypes.c_int),
            "PQerrorMessage": ([ctypes.c_void_p], ctypes.c_char_p),
            "PQexec": ([ctypes.c_void_p, ctypes.c_char_p], ctypes.c_void_p),
            "PQresultStatus": ([ctypes.c_void_p], ctypes.c_int),
            "PQresultErrorField": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_char_p),
            "PQntuples": ([ctypes.c_void_p], ctypes.c_int),
            "PQnfields": ([ctypes.c_void_p], ctypes.c_int),
            "PQgetvalue": (
                [ctypes.c_void_p, ctypes.c_int, ctypes.c_int],
                ctypes.c_char_p,
            ),
            "PQclear": ([ctypes.c_void_p], None),
            "PQfinish": ([ctypes.c_void_p], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.library, name)
            function.argtypes = arguments
            function.restype = result
        values = {
            key: environment.get(variable, "")
            for key, variable in [
                ("host", "PGHOST"),
                ("port", "PGPORT"),
                ("dbname", "PGDATABASE"),
                ("user", "PGUSER"),
                ("password", "PGPASSWORD"),
            ]
        }
        values.update(
            sslmode="verify-full",
            sslrootcert=environment.get("PGSSLROOTCERT") or where(),
            connect_timeout="10",
            application_name=application,
        )

        def quote(value):
            return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

        connection = " ".join(
            key + "=" + quote(value) for key, value in values.items() if value
        )
        self.pointer = self.library.PQconnectdb(connection.encode())
        if not self.pointer or self.library.PQstatus(self.pointer) != 0:
            diagnostic = (
                self.library.PQerrorMessage(self.pointer).lower()
                if self.pointer
                else b""
            )
            self.close()
            if b"certificate verify failed" in diagnostic:
                raise RuntimeError("Database TLS certificate validation failed")
            if b"password authentication failed" in diagnostic:
                raise RuntimeError(
                    "Ephemeral database authentication failed; serialize CLI operations"
                )
            raise RuntimeError("Database connection failed; diagnostics suppressed")
        try:
            self.query(
                "set role postgres; set statement_timeout='15s'; set client_min_messages=error;"
            )
        except RuntimeError:
            self.close()
            raise

    def query(self, sql: str) -> list[list[str]]:
        result = self.library.PQexec(self.pointer, sql.encode())
        try:
            if not result or self.library.PQresultStatus(result) not in (1, 2):
                code = (
                    self.library.PQresultErrorField(result, ord("C"))
                    if result
                    else None
                )
                raise SqlFailure(code.decode() if code else "unknown")
            return [
                [
                    self.library.PQgetvalue(result, row, column).decode()
                    for column in range(self.library.PQnfields(result))
                ]
                for row in range(self.library.PQntuples(result))
            ]
        finally:
            if result:
                self.library.PQclear(result)

    def close(self) -> None:
        if getattr(self, "pointer", None):
            self.library.PQfinish(self.pointer)
            self.pointer = None
        if self.dll_directory:
            self.dll_directory.close()
