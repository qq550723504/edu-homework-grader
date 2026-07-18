from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from .auth import CurrentPrincipal, get_current_principal
from .models import Role


def require_role(role: Role) -> Callable[[CurrentPrincipal], CurrentPrincipal]:
    def dependency(
        principal: Annotated[CurrentPrincipal, Depends(get_current_principal)],
    ) -> CurrentPrincipal:
        if principal.role is not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        return principal

    return dependency
