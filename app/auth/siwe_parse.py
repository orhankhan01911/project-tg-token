"""Minimal SIWE (EIP-4361) message parser.

We do NOT use `siwe-py.SiweMessage.from_message` because its ABNF parser
has a state-corruption bug that causes parses to fail intermittently
after an arbitrary number of calls (reproduced standalone — `siwe==4.4.0`,
`abnf` upstream). The bug bites under load and would make every Mini
App verify request a coin flip in production.

The SIWE message format is fixed enough to parse with a few regexes:

    [scheme://]<domain> wants you to sign in with your Ethereum account:
    <address>

    [<statement>]

    URI: <uri>
    Version: <version>
    Chain ID: <chain-id>
    Nonce: <nonce>
    Issued At: <iso8601>
    [Expiration Time: <iso8601>]
    [Not Before: <iso8601>]
    [Request ID: <request-id>]
    [Resources:
    - <uri>
    - <uri>
    ...]

We extract only the fields the verifier cares about. Anything else is
left as a raw line for forensics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSiwe:
    domain: str
    address: str
    statement: str | None
    uri: str
    version: str
    chain_id: int
    nonce: str
    issued_at: str
    expiration_time: str | None
    not_before: str | None


_HEADER_RE = re.compile(
    r"^(?:(?P<scheme>[a-z][a-z0-9+.-]*)://)?"
    r"(?P<domain>[^\s]+)"
    r" wants you to sign in with your Ethereum account:\n"
    r"(?P<address>0x[0-9a-fA-F]{40})\n"
)
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z ]+):\s*(.+)$", re.MULTILINE)


class SiweParseError(ValueError):
    pass


def parse_siwe(message: str) -> ParsedSiwe:
    if not message:
        raise SiweParseError("empty message")

    header = _HEADER_RE.match(message)
    if not header:
        raise SiweParseError("missing or malformed header")

    domain = header.group("domain")
    address = header.group("address")

    # Statement is the optional block between the address and the URI: line.
    body = message[header.end():]
    statement: str | None = None
    if body.startswith("\n"):
        # body begins with \n<statement>\n\nURI: ... or just \n\nURI: ... if no statement
        rest = body.lstrip("\n")
        if not rest.startswith("URI: "):
            # Statement present — it's everything up to the next blank line
            stmt_end = rest.find("\n\n")
            if stmt_end == -1:
                raise SiweParseError("statement_not_terminated")
            statement = rest[:stmt_end]
            body = rest[stmt_end + 2:]
        else:
            body = rest

    fields: dict[str, str] = {m.group(1).strip(): m.group(2).strip() for m in _FIELD_RE.finditer(body)}

    required = ["URI", "Version", "Chain ID", "Nonce", "Issued At"]
    for k in required:
        if k not in fields:
            raise SiweParseError(f"missing_field:{k}")

    try:
        chain_id = int(fields["Chain ID"])
    except ValueError as e:
        raise SiweParseError("bad_chain_id") from e

    return ParsedSiwe(
        domain=domain,
        address=address,
        statement=statement,
        uri=fields["URI"],
        version=fields["Version"],
        chain_id=chain_id,
        nonce=fields["Nonce"],
        issued_at=fields["Issued At"],
        expiration_time=fields.get("Expiration Time"),
        not_before=fields.get("Not Before"),
    )
