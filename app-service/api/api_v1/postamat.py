from typing import List, Dict

from fastapi import APIRouter, HTTPException, status

# from core.schemas.common import SuccessResponse
# from core.services.auth_service import get_current_active_user
from api.api_v1.api_depends import Session_dep, Org_dep
from core.schemas.postamat import PostamatWithCellsResponse, PostamatShortSchema
from core.services.postamat_service import postamat_service

router = APIRouter(
    prefix="/postamats",
    tags=["Postamats"],
)


# === Эндпоинты ===
@router.get("/", response_model=List[PostamatShortSchema])
async def get_all_postamats(
    org_id: Org_dep,
    db: Session_dep,
    skip: int = 0,
    limit: int = 100,
    #  current_user: User = Depends(get_current_active_user),
):
    """
    Получить список всех постаматов без ячеек.
    При указании org_id — только постаматы организации.
    """
    effective_org_id = org_id  # or current_user.org_id
    postamats = await postamat_service.get_all_postamats(
        db=db,
        org_id=effective_org_id,
        skip=skip,
        limit=limit,
    )
    return postamats


@router.get("/{postamat_id}", response_model=PostamatWithCellsResponse)
async def get_postamat_with_cells(
    postamat_id: int,
    org_id: Org_dep,
    db: Session_dep,
    #   current_user: User = Depends(get_current_active_user),
):
    """
    Получить постамат по ID вместе со всеми ячейками.
    При указании org_id проверяется принадлежность к организации.
    """
    result = await postamat_service.get_with_cells(
        db=db, postamat_id=postamat_id, org_id=org_id  # or current_user.org_id,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Postamat not found"
        )
    return result
