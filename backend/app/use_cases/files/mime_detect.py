# Определение mime по содержимому — магические байты (FR-057).
# python-magic требует libmagic (нет в slim-образе) — детектор по сигнатурам:
# достаточен для базового набора FR-055; неизвестная сигнатура → octet-stream
# (download-only, FR-056), текстовые файлы распознаются декодированием (FR-029).
from __future__ import annotations

import codecs

# Офисные форматы (ZIP-контейнеры; различаем по именам частей внутри — ниже)
_ZIP_MAGIC = b"PK\x03\x04"
_OFFICE_PARTS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word/",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xl/",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "ppt/",
}
_OLD_OFFICE = {
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": "application/msword",
}


def _looks_like_zip_with(head: bytes, data: bytes, part_prefix: str) -> bool:
    if not head.startswith(_ZIP_MAGIC):
        return False
    return part_prefix.encode() in data[:65536]


def detect_mime(data: bytes, filename: str = "") -> str:
    """Mime по магическим байтам (FR-057); текстовые — по декодируемости (FR-029).

    Порядок: точные сигнатуры → ZIP-контейнеры офисных форматов → текст
    (text/*, HTML исключён из автозаполнения — 16.1-87/112, но mime у HTML
    всё же text/html) → octet-stream.
    """
    head = data[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if head.startswith(b"PK\x03\x04"):
        for mime, part in _OFFICE_PARTS.items():
            if part.encode() in data[:65536]:
                return mime
        # прочие zip (например xlsx без parts не бывает) — общий zip
        return "application/zip"
    for magic, mime in _OLD_OFFICE.items():
        if head.startswith(magic):
            return mime
    if head.startswith(b"\x00\x00\x00\x18ftypmp42") or head.startswith(b"\x00\x00\x00\x18ftypisom") or b"ftyp" in head:
        return "video/mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"ID3") or head.startswith(b"\xff\xfb"):
        return "audio/mpeg"
    if head.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"GIF8"):
        return "image/gif"

    # Текст (FR-029): UTF-8/ASCII без NUL → text/*; HTML — по содержимому
    if b"\x00" not in data[:8192]:
        try:
            data[:8192].decode("utf-8")
        except UnicodeDecodeError:
            return "application/octet-stream"
        lower = data[:8192].lstrip().lower()
        if lower.startswith(b"<!doctype html") or lower.startswith(b"<html"):
            return "text/html"
        # SVG — XML с <svg
        if lower.startswith(b"<?xml") and b"<svg" in lower:
            return "image/svg+xml"
        if filename.lower().endswith((".md", ".markdown")):
            return "text/markdown"
        if filename.lower().endswith(".txt"):
            return "text/plain"
        return "text/plain"
    return "application/octet-stream"


def is_office_mime(mime: str) -> bool:
    """Офисные форматы → files.convert (LLD §6.3, FR-059)."""
    return mime in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    }


# Базовый набор извлекаемых форматов (16.1-121, LLD §6.3)
EXTRACTABLE_MIMES = frozenset({
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/pdf",
})


def is_extractable_mime(mime: str) -> bool:
    """Форматы извлечения текста → files.extract (16.1-121, FR-154, LLD §6.3).

    DOCX/XLSX/PPTX + PDF (базовый набор 6.2 с текстовым слоем); старые форматы
    MS Office (msword/vnd.ms-*) — без текстового слоя в рамках шага [8]:
    экстрактор OOXML+PDF, конвертация в PDF для них не предусмотрена.
    """
    return mime in EXTRACTABLE_MIMES


def is_text_mime(mime: str) -> bool:
    """Текстовый файл по FR-029: mime text/* (HTML включён в mime, но
    автозаполнение для него не выполняется — 16.1-112; проверяет вызывающий)."""
    return mime.startswith("text/") or mime == "image/svg+xml"


# Базовый набор предпросмотра (FR-055); допустимость загрузки — базовый + mime_extra
BASE_MIME_SET = {
    "text/markdown",
    "text/html",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png",
    "image/jpeg",
    "image/svg+xml",
    "application/pdf",
    # видео/аудио базового набора (FR-055): MP4/H.264, WebM, MP3
    "video/mp4",
    "video/webm",
    "audio/mpeg",
}


def is_download_only(mime: str, mime_extra: list[str] | None = None) -> bool:
    """mime вне базового набора и mime_extra — только скачивание (FR-056/064)."""
    return mime not in BASE_MIME_SET and mime not in (mime_extra or [])
