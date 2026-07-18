from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import Role
from ..services.roster import RosterValidationError, import_roster, parse_roster


router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/students/import")
async def import_students(
    file: Annotated[UploadFile, File(...)],
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, int]:
    try:
        rows = parse_roster(await file.read())
        return {"imported": import_roster(session, principal, rows)}
    except RosterValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
