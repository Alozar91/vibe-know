# Files — транспорт (LLD §12.3, §6.2–6.4). Логика: use_cases/files/*.
# Отдача — api-стриминг [уточнение LLD]: единая точка авторизации, браузер
# к silo не обращается. Скачивание — только scan_state='ready' (FR-058).
from fastapi import APIRouter, Depends, Header, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep
from app.db.engine import get_db
from app.use_cases.common import parse_uuid

router = APIRouter(tags=["files"])


@router.post("/materials/{material_id}/file")
async def upload_file_ep(
    user: CurrentUserDep,
    material_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    text_update_choice: str | None = None,
):
    """Загрузка/замена файла (§6.2): mime по содержимому, дедуп CAS, очередь scan.

    text_update_choice: 'replace'|'keep' — ответ на предложение FR-030 (повторный
    вызов); без него при непустом тексте возвращается offer_text_update=true.
    """
    from app.use_cases.files.upload_file import upload_file

    data = await file.read()
    result = upload_file(
        db, user, material_id, file.filename or "без-имени", data,
        text_update_choice=text_update_choice,
    )
    return _json(result, headers={"ETag": f'"{result["version"]}"'})


@router.get("/materials/{material_id}/file")
async def download_file_ep(
    user: CurrentUserDep,
    material_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Скачивание исходника (§6.4, FR-062/067): право download, scan_state=ready,
    Range → 206. Аудит file_download (FR-140)."""
    from fastapi import Response as FastAPIResponse

    from app.db import models
    from app.use_cases.errors import DomainError, not_found
    from app.use_cases.files import silo
    from app.use_cases.files.upload_file import file_state
    from app.use_cases.lifecycle.audit import audit_log
    from app.use_cases.materials.get_material import get_material_or_404
    from app.use_cases.permissions.can import can

    m = get_material_or_404(db, user, material_id, permission="view")
    if not can(db, user, m.id, "download"):
        raise DomainError(
            status=403, code="ACCESS_DENIED", title="Доступ запрещён",
            detail="Нет права «Скачивание» на материал",
        )
    if m.current_file_id is None:
        raise not_found("У материала нет файла")
    fo = db.execute(
        select_file(m.current_file_id)
    ).scalar_one_or_none()
    if fo is None or fo.scan_state != "ready":
        # FR-058: отдача только после проверки (US-011 шаг 2)
        raise DomainError(
            status=409, code="FILE_PENDING_SCAN", title="Файл ещё проверяется",
            detail="Файл недоступен до завершения антивирусной проверки",
        )

    range_header = request.headers.get("range")
    body, st, headers = silo.get_object_stream(silo.cas_key(fo.sha256), range_header)
    if body is None:
        raise not_found("Файл отсутствует в хранилище")

    audit_log(db, user, "file_download", "material", m.id,
              details={"file_id": str(fo.id), "filename": fo.filename})
    db.commit()

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        _stream_body(body), status_code=st,
        media_type=headers.get("Content-Type", fo.mime_type),
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_name(fo.filename)}"',
            "Accept-Ranges": "bytes",
            **({"Content-Range": headers["ContentRange"]} if headers.get("ContentRange") else {}),
        },
    )


@router.get("/materials/{material_id}/pdf")
async def download_pdf_ep(
    user: CurrentUserDep,
    material_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """PDF-предпросмотр (§6.4, FR-059/061): право view/участие; только ready_pdf."""
    from fastapi import Response as FastAPIResponse

    from app.db import models
    from app.use_cases.errors import not_found
    from app.use_cases.files import silo
    from app.use_cases.materials.get_material import get_material_or_404

    m = get_material_or_404(db, user, material_id, permission="view")
    if m.current_file_id is None:
        raise not_found("У материала нет файла")
    fo = db.execute(select_file(m.current_file_id)).scalar_one_or_none()
    if fo is None or fo.pdf_state != "ready_pdf" or not fo.pdf_cas_key:
        raise not_found("PDF-предпросмотр недоступен (конвертация не завершена)")

    range_header = request.headers.get("range")
    body, st, headers = silo.get_object_stream(fo.pdf_cas_key, range_header)
    if body is None:
        raise not_found("PDF отсутствует в хранилище")

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        _stream_body(body), status_code=st, media_type="application/pdf",
        headers={"Accept-Ranges": "bytes",
                 **({"Content-Range": headers["ContentRange"]} if headers.get("ContentRange") else {})},
    )


@router.get("/materials/{material_id}/file-state")
async def file_state_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db)
) -> dict:
    """Состояние конвейера (§6.3, FR-058–061): опрос из карточки; без silo."""
    from app.db import models
    from app.use_cases.materials.get_material import get_material_or_404

    m = get_material_or_404(db, user, material_id)  # видимость — предикат
    if m.current_file_id is None:
        return {"file_id": None, "scan_state": None, "pdf_state": None}
    fo = db.execute(select_file(m.current_file_id)).scalar_one_or_none()
    if fo is None:
        from app.use_cases.errors import not_found

        raise not_found("Файл не найден")
    from app.use_cases.files.upload_file import file_state

    return file_state(fo)


@router.get("/materials/{material_id}/text.md")
async def download_text_ep(
    user: CurrentUserDep, material_id: str, db: Session = Depends(get_db)
):
    """Скачивание текстового представления .md (FR-107, 16.1-108): право download;
    пустой текст — недоступно (US-014 A2). Аудит text_export (FR-140)."""
    from fastapi import Response as FastAPIResponse

    from app.use_cases.errors import DomainError, not_found
    from app.use_cases.lifecycle.audit import audit_log
    from app.use_cases.materials.get_material import get_material_or_404
    from app.use_cases.permissions.can import can

    m = get_material_or_404(db, user, material_id, permission="view")
    if not can(db, user, m.id, "download"):
        raise DomainError(
            status=403, code="ACCESS_DENIED", title="Доступ запрещён",
            detail="Нет права «Скачивание» на материал",
        )
    if not m.text_content:
        # US-014 A2: действие недоступно при пустом тексте
        raise not_found("Текстовое представление пусто")

    audit_log(db, user, "text_export", "material", m.id)
    db.commit()

    return FastAPIResponse(
        content=m.text_content.encode("utf-8"), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="text.md"'},
    )


def _stream_body(body):
    """Стриминг S3-body клиенту (§6.4 api-стриминг); закрытие после отдачи."""
    try:
        yield from body.iter_chunks(65536)
    finally:
        body.close()


def select_file(file_id):
    from sqlalchemy import select

    from app.db import models

    return select(models.FileObject).where(models.FileObject.id == file_id)


def _safe_name(name: str) -> str:
    """Имя файла для Content-Disposition (без кавычек/переводов строк)."""
    return name.replace('"', "'").replace("\r", "").replace("\n", "")


def _json(obj, headers=None):
    from fastapi import Response

    import json

    return Response(
        content=json.dumps(obj, ensure_ascii=False), media_type="application/json",
        headers=headers or {},
    )
