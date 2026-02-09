import json
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.doc import Doc
from app.repositories.user_repository import DEV_USER_ID, get_or_create_dev_user
from app.services.storage_service import delete_doc_files, save_to_library, save_upload

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}

router = APIRouter()


@router.post("/docs/materials/upload")
async def upload_material(
    file: UploadFile = File(...),
    saveToLibrary: str = Form("false"),
    db: Session = Depends(get_db),
):
    """
    我的资料页：仅保存文件，不解析、不总结、不向量化。
    后续出题时再对该文档做总结提炼，作为 query 给模型。
    """
    suffix = ""
    if file.filename and "." in file.filename:
        suffix = "." + file.filename.rsplit(".", 1)[1].lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    user = get_or_create_dev_user(db)
    doc_id = str(uuid.uuid4())
    filename = file.filename or f"upload{suffix}"

    file_path, file_hash, file_size = save_upload(file.file, filename, doc_id)
    save_to_lib = saveToLibrary.lower() == "true"

    if save_to_lib:
        save_to_library(file_path, doc_id, filename)

    doc = Doc(
        id=doc_id,
        owner_id=user.id,
        file_name=filename,
        file_path=file_path,
        file_hash=file_hash,
        file_size=file_size,
        status="uploaded",
        save_to_library=save_to_lib,
    )
    db.add(doc)
    db.commit()

    return {"docId": doc_id, "fileName": filename, "status": "uploaded"}


@router.post("/docs/upload")
async def upload_doc(
    file: UploadFile = File(...),
    saveToLibrary: str = Form("false"),
    db: Session = Depends(get_db),
):
    suffix = ""
    if file.filename and "." in file.filename:
        suffix = "." + file.filename.rsplit(".", 1)[1].lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    user = get_or_create_dev_user(db)
    doc_id = str(uuid.uuid4())
    filename = file.filename or f"upload{suffix}"

    file_path, file_hash, file_size = save_upload(file.file, filename, doc_id)
    save_to_lib = saveToLibrary.lower() == "true"

    if save_to_lib:
        save_to_library(file_path, doc_id, filename)

    doc = Doc(
        id=doc_id,
        owner_id=user.id,
        file_name=filename,
        file_path=file_path,
        file_hash=file_hash,
        file_size=file_size,
        status="uploaded",
        save_to_library=save_to_lib,
    )
    db.add(doc)
    db.commit()

    return {"docId": doc_id, "fileName": filename, "status": "uploaded"}


def _doc_to_item(doc: Doc) -> dict:
    item = {
        "docId": doc.id,
        "fileName": doc.file_name,
        "status": doc.status,
        "createdAt": doc.created_at.isoformat() if doc.created_at else None,
    }
    if doc.status == "done":
        item["parsed"] = {
            "school": doc.parsed_school or "",
            "major": doc.parsed_major or "",
            "course": doc.parsed_course or "",
            "knowledgePoints": doc.parsed_knowledge_points or [],
            "summary": doc.parsed_summary or "",
        }
    return item


def _sse_event(data: dict, event: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    if event:
        return f"event: {event}\ndata: {payload}\n\n"
    return f"data: {payload}\n\n"


@router.get("/docs/{doc_id}/file")
def get_doc_file(doc_id: str, db: Session = Depends(get_db)):
    """获取文件内容以便前端预览。返回文件流，带正确的 Content-Type。"""
    doc = db.query(Doc).filter(Doc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")
    path = Path(doc.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    media_type, _ = mimetypes.guess_type(doc.file_name) or ("application/octet-stream", None)
    filename = doc.file_name or "file"
    # RFC 5987: 允许非 ASCII 文件名，避免 latin-1 编码错误
    filename_star = quote(filename)
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{filename_star}"
    }
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        headers=headers,
    )


@router.get("/docs/{doc_id}")
def get_doc(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(Doc).filter(Doc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")
    return _doc_to_item(doc)


@router.get("/docs")
def list_docs(
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100, alias="pageSize"),
    db: Session = Depends(get_db),
):
    get_or_create_dev_user(db)
    q = db.query(Doc).filter(Doc.owner_id == DEV_USER_ID)
    if keyword:
        q = q.filter(Doc.file_name.ilike(f"%{keyword}%"))
    total = q.count()
    items = q.order_by(Doc.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_doc_to_item(d) for d in items], "total": total}


@router.post("/docs/{doc_id}/parse")
def parse_doc(doc_id: str, db: Session = Depends(get_db)):
    from app.services.doc_parse_service import parse_and_index_stream

    doc = db.query(Doc).filter(Doc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")

    def gen():
        # 1) 标记解析中
        doc.status = "parsing"
        db.commit()
        yield _sse_event({"docId": doc.id, "status": "parsing"}, event="status")

        try:
            # 2) 调用大模型解析（流式）
            yield _sse_event({"stage": "summarize"}, event="progress")
            for chunk in parse_and_index_stream(
                file_path=doc.file_path,
                doc_id=doc.id,
                owner_id=doc.owner_id,
                db=db,
                doc=doc,
            ):
                if chunk:
                    yield _sse_event({"content": chunk}, event="chunk")
            doc.status = "done"
            db.commit()
            db.refresh(doc)

            # 3) 返回解析结果
            parsed = {
                "school": doc.parsed_school or "",
                "major": doc.parsed_major or "",
                "course": doc.parsed_course or "",
                "knowledgePoints": doc.parsed_knowledge_points or [],
                "summary": doc.parsed_summary or "",
            }
            yield _sse_event(
                {"docId": doc.id, "status": "done", "parsed": parsed},
                event="result",
            )
        except Exception as e:
            doc.status = "failed"
            db.commit()
            yield _sse_event(
                {"docId": doc.id, "status": "failed", "detail": str(e)},
                event="error",
            )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/docs/{doc_id}", status_code=204)
def delete_doc(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(Doc).filter(Doc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")
    delete_doc_files(doc)
    db.delete(doc)
    db.commit()