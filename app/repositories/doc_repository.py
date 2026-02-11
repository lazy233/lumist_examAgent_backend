"""文档（Doc）数据访问层。"""
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doc import Doc
from app.models.exercise import Exercise


async def get_doc_by_id(db: AsyncSession, doc_id: str) -> Doc | None:
    """按 ID 查询文档，不存在返回 None。"""
    result = await db.execute(select(Doc).where(Doc.id == doc_id))
    return result.scalars().first()


async def create_doc(
    db: AsyncSession,
    *,
    doc_id: str,
    owner_id: str,
    file_name: str,
    file_path: str,
    file_hash: str | None = None,
    file_size: int | None = None,
    status: str = "uploaded",
    save_to_library: bool = False,
) -> Doc:
    """创建文档记录。doc_id 由调用方提供（通常先用于文件保存路径）。返回 Doc（commit 后）。"""
    doc = Doc(
        id=doc_id,
        owner_id=owner_id,
        file_name=file_name,
        file_path=file_path,
        file_hash=file_hash,
        file_size=file_size,
        status=status,
        save_to_library=save_to_library,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def list_docs(
    db: AsyncSession,
    owner_id: str,
    *,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Doc], int]:
    """
    分页列出某用户的文档。返回 (items, total)。
    """
    q = select(Doc).where(Doc.owner_id == owner_id)
    count_stmt = select(func.count()).select_from(Doc).where(Doc.owner_id == owner_id)
    if keyword:
        q = q.where(Doc.file_name.ilike(f"%{keyword}%"))
        count_stmt = count_stmt.where(Doc.file_name.ilike(f"%{keyword}%"))
    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        q.order_by(Doc.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()
    return list(items), total


async def commit_and_refresh_doc(db: AsyncSession, doc: Doc) -> None:
    """提交对 doc 的修改并刷新对象（避免懒加载 MissingGreenlet）。"""
    await db.commit()
    await db.refresh(doc)


async def unlink_exercises_from_doc(db: AsyncSession, doc_id: str) -> None:
    """解除练习对该文档的外键引用，便于删除 doc。"""
    await db.execute(
        update(Exercise).where(Exercise.source_doc_id == doc_id).values(source_doc_id=None)
    )
    await db.flush()


async def delete_doc_by_id(db: AsyncSession, doc_id: str) -> None:
    """按 ID 删除文档记录。调用方需先解除关联并删除磁盘文件。"""
    await db.execute(Doc.__table__.delete().where(Doc.id == doc_id))
    await db.commit()
