"""Loopback CGI bridge for the fixed, read-only city snapshot."""
from __future__ import annotations

import os
import subprocess
from urllib.parse import parse_qsl

ROUTE = "/inspector/api/sign-wfs"
PARAMETERS = frozenset({
    "service", "version", "request", "acceptversions", "typename", "typenames",
    "srsname", "outputformat", "bbox", "filter", "resulttype", "count",
    "startindex", "maxfeatures", "propertyname", "sortby", "resourceid", "featureid",
})
OPERATIONS = {"getcapabilities", "describefeaturetype", "getfeature"}
MIME_TYPES = {"application/xml", "text/xml", "application/gml+xml",
              "application/geo+json", "application/json", "application/vnd.ogc.se_xml"}


class SignWFSError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def query_snapshot(executable, config, host, query):
    pairs = [(key.lower(), value) for key, value in parse_qsl(query, keep_blank_values=True)]
    fields = dict(pairs)
    if (len(fields) != len(pairs) or fields.keys() - PARAMETERS
            or fields.get("service", "").lower() != "wfs"
            or fields.get("request", "").lower() not in OPERATIONS):
        raise SignWFSError("Ungültige WFS-Abfrage.", 400)

    hostname, port = host.split(":", 1)
    env = {key: os.environ[key] for key in ("PATH", "GDAL_DATA", "PROJ_DATA", "PROJ_LIB")
           if key in os.environ}
    env.update(
        MAPSERVER_CONFIG_FILE=str(config),
        REQUEST_METHOD="GET",
        QUERY_STRING=query,
        SCRIPT_NAME=ROUTE,
        REQUEST_URI=f"{ROUTE}?{query}",
        SERVER_PROTOCOL="HTTP/1.1",
        SERVER_NAME=hostname,
        SERVER_PORT=port,
        HTTP_HOST=host,
    )
    try:
        result = subprocess.run(
            [str(executable)], env=env, cwd=config.parent, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SignWFSError("WFS-Snapshot nicht verfügbar.", 503) from None
    data = result.stdout
    if b"\r\n\r\n" in data[:2048]:
        headers, _, body = data.partition(b"\r\n\r\n")
    else:
        headers, _, body = data.partition(b"\n\n")
    content_type = ""
    status = 200
    for header in headers.splitlines():
        name, _, value = header.partition(b":")
        if name.lower() == b"content-type":
            content_type = value.strip().decode("ascii", errors="replace")
        elif name.lower() == b"status":
            code = value.strip().partition(b" ")[0]
            if code in (b"400", b"404", b"500"):
                status = int(code)
    if content_type.split(";", 1)[0] not in MIME_TYPES or not body or len(body) > 12 * 1024**2:
        raise SignWFSError("WFS-Snapshot nicht verfügbar.", 503)
    return body, content_type, status
