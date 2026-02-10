import json
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.doc import Doc
from app.models.exercise import Exercise
from app.repositories.user_repository import DEV_USER_ID, get_or_create_dev_user
from app.services.storage_service import delete_doc_files_async, save_to_library_async, save_upload_async

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}

router = APIRouter()


@router.post("/docs/materials/upload")
async def upload_material(
    file: UploadFile = File(...),
    saveToLibrary: str = Form("false"),
    db: AsyncSession = Depends(get_db),
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

    user = await get_or_create_dev_user(db)
    doc_id = str(uuid.uuid4())
    filename = file.filename or f"upload{suffix}"

    file_path, file_hash, file_size = await save_upload_async(file.file, filename, doc_id)
    save_to_lib = saveToLibrary.lower() == "true"

    if save_to_lib:
        await save_to_library_async(file_path, doc_id, filename)

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
    await db.commit()

    return {"docId": doc_id, "fileName": filename, "status": "uploaded"}


@router.post("/docs/upload")
async def upload_doc(
    file: UploadFile = File(...),
    saveToLibrary: str = Form("false"),
    db: AsyncSession = Depends(get_db),
):
    suffix = ""
    if file.filename and "." in file.filename:
        suffix = "." + file.filename.rsplit(".", 1)[1].lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    user = await get_or_create_dev_user(db)
    doc_id = str(uuid.uuid4())
    filename = file.filename or f"upload{suffix}"

    file_path, file_hash, file_size = await save_upload_async(file.file, filename, doc_id)
    save_to_lib = saveToLibrary.lower() == "true"

    if save_to_lib:
        await save_to_library_async(file_path, doc_id, filename)

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
    await db.commit()

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
async def get_doc_file(doc_id: str, db: AsyncSession = Depends(get_db)):
    """获取文件内容以便前端预览。返回文件流，带正确的 Content-Type。"""
    result = await db.execute(select(Doc).where(Doc.id == doc_id))
    doc = result.scalars().first()
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
async def get_doc(doc_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Doc).where(Doc.id == doc_id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")
    return _doc_to_item(doc)


@router.get("/docs")
async def list_docs(
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100, alias="pageSize"),
    db: AsyncSession = Depends(get_db),
):
    await get_or_create_dev_user(db)
    q = select(Doc).where(Doc.owner_id == DEV_USER_ID)
    if keyword:
        q = q.where(Doc.file_name.ilike(f"%{keyword}%"))
    count_stmt = select(func.count()).select_from(Doc).where(Doc.owner_id == DEV_USER_ID)
    if keyword:
        count_stmt = count_stmt.where(Doc.file_name.ilike(f"%{keyword}%"))
    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        q.order_by(Doc.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()
    return {"items": [_doc_to_item(d) for d in items], "total": total}


@router.post("/docs/{doc_id}/parse")
async def parse_doc(doc_id: str, db: AsyncSession = Depends(get_db)):
    from app.services.doc_parse_service import parse_and_index_stream

    result = await db.execute(select(Doc).where(Doc.id == doc_id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")

    # 在 commit 前取出所需字段，避免 commit 后 ORM 对象过期导致懒加载触发 MissingGreenlet
    doc_id_val = doc.id
    owner_id_val = doc.owner_id
    file_path_val = doc.file_path

    async def gen():
        # 1) 标记解析中
        doc.status = "parsing"
        await db.commit()
        yield _sse_event({"docId": doc_id_val, "status": "parsing"}, event="status")

        try:
            # 2) 调用大模型解析（流式）
            yield _sse_event({"stage": "summarize"}, event="progress")
            async for chunk in parse_and_index_stream(
                file_path=file_path_val,
                doc_id=doc_id_val,
                owner_id=owner_id_val,
                db=db,
                doc=doc,
            ):
                if chunk:
                    yield _sse_event({"content": chunk}, event="chunk")
            doc.status = "done"
            await db.commit()
            await db.refresh(doc)

            # 3) 返回解析结果
            parsed = {
                "school": doc.parsed_school or "",
                "major": doc.parsed_major or "",
                "course": doc.parsed_course or "",
                "knowledgePoints": doc.parsed_knowledge_points or [],
                "summary": doc.parsed_summary or "",
            }
            yield _sse_event(
                {"docId": doc_id_val, "status": "done", "parsed": parsed},
                event="result",
            )
        except Exception as e:
            doc.status = "failed"
            await db.commit()
            yield _sse_event(
                {"docId": doc_id_val, "status": "failed", "detail": str(e)},
                event="error",
            )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/docs/{doc_id}", status_code=204)
async def delete_doc(doc_id: str, db: AsyncSession = Depends(get_db)):
    """
    删除资料。按外键依赖先解除练习对该资料的引用，再删磁盘文件，最后删 doc 记录，避免外键约束错误。
    """
    result = await db.execute(select(Doc).where(Doc.id == doc_id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="doc not found")

    # 1) 解除 exercises 对当前 doc 的引用，避免删 doc 时触发外键约束
    await db.execute(
        update(Exercise).where(Exercise.source_doc_id == doc_id).values(source_doc_id=None)
    )
    await db.flush()
    # 2) 删除磁盘上的文件（需在删 doc 前执行，依赖 doc 的 file_path 等）
    await delete_doc_files_async(doc)
    # 3) 删除 doc 记录
    await db.execute(Doc.__table__.delete().where(Doc.id == doc_id))
    await db.commit()