from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.auth import authenticate_user, create_access_token, get_current_user
from backend.limiter import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos",
        )
    token = create_access_token(
        subject=user["username"],
        extra={
            "is_admin": bool(user["is_admin"]),
            "nome": user["nome"],
            "tv": user.get("token_version", 1),
        },
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "nome": user["nome"],
            "email": user["email"],
            "is_admin": bool(user["is_admin"]),
        },
    }


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "username": user["username"],
        "nome": user["nome"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
    }
