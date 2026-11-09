# CAS-хранилище silo (LLD §6.1, HLD §6.4): boto3 S3-клиент.
# Ключи-исходники: ab/cd/<sha256-hex> (неизменяемые); PDF-кэш: pdf/<sha256-hex>
# (перезаписываемый). Bucket создаётся silo-init (deploy).
from __future__ import annotations

import boto3
from botocore.config import Config

from app.config import get_settings

_client = None


def _s3():
    """Ленивый S3-клиент (один на процесс; pool_pre_ping не нужен — botocore сам)."""
    global _client
    if _client is None:
        s = get_settings()
        _client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            config=Config(
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    return _client


def cas_key(sha256_hex: str) -> str:
    """Ключ исходника: ab/cd/<hex> (первые 4 hex — префикс шардирования, §6.1)."""
    return f"{sha256_hex[:2]}/{sha256_hex[2:4]}/{sha256_hex}"


def pdf_key(sha256_hex: str) -> str:
    """Ключ PDF-кэша: pdf/<hex> (перезаписываемый объект, §6.1)."""
    return f"pdf/{sha256_hex}"


def put_object(key: str, data: bytes, content_type: str | None = None) -> None:
    """PUT в bucket cas; идемпотентен для неизменяемых CAS-объектов (§6.1)."""
    kwargs = {"Bucket": get_settings().s3_bucket, "Key": key, "Body": data}
    if content_type:
        kwargs["ContentType"] = content_type
    _s3().put_object(**kwargs)


def get_object_stream(key: str, range_header: str | None = None):
    """S3 GET с опциональным Range (FR-062); возвращает (body, status_code, headers).

    body поддерживает read()/iter_chunks(); вызывающий закрывает.
    """
    kwargs = {"Bucket": get_settings().s3_bucket, "Key": key}
    if range_header:
        kwargs["Range"] = range_header
    try:
        resp = _s3().get_object(**kwargs)
    except _s3().exceptions.ClientError as e:  # noqa: F821 — вычисляется в рантайме
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            return None, 404, {}
        if code in ("InvalidRange", "RangeNotSatisfiable", "416"):
            return None, 416, {}
        raise
    headers = {
        "Content-Type": resp.get("ContentType", "application/octet-stream"),
        "Content-Length": str(resp.get("ContentLength", "")),
        "ETag": resp.get("ETag", ""),
        "Last-Modified": resp.get("LastModified").isoformat() if resp.get("LastModified") else "",
        "AcceptRanges": "bytes",
        "ContentRange": resp.get("ContentRange", ""),
    }
    return resp["Body"], 200, headers


def head_object(key: str) -> dict | None:
    """HEAD объекта; None — нет объекта (проверка PDF-кэша)."""
    try:
        return _s3().head_object(Bucket=get_settings().s3_bucket, Key=key)
        # noqa — botocore.exceptions.ClientError ловим по имени без импорта
    except Exception as e:  # noqa: BLE001 — botocore не даёт стабильного класса до вызова
        if type(e).__name__ == "ClientError" and getattr(e, "response", {}).get(
            "Error", {}
        ).get("Code", "") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def delete_object(key: str) -> None:
    """DELETE объекта (только cas_gc, этап 10)."""
    _s3().delete_object(Bucket=get_settings().s3_bucket, Key=key)


def list_keys(prefix: str) -> list[str]:
    """Список ключей с префиксом (для cas_reconcile/cas_gc, этап 10)."""
    paginator = _s3().get_paginator("list_objects_v2")
    out = []
    for page in paginator.paginate(Bucket=get_settings().s3_bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            out.append(item["Key"])
    return out
