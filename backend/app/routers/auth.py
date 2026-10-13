from fastapi import APIRouter, Depends, Response

from app.core.dependencies import CurrentUser, SessionDep, SettingsDep
from app.core.security import create_access_token
from app.core.throttle import enforce_login_throttle
from app.models.enums import Role
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, UserResponse
from app.schemas.common import ErrorResponse, Success
from app.services.auth import authenticate_user, register_user

router = APIRouter(prefix="/auth", tags=["authentication"])
ERRORS = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Malformed JSON",
        401: "Missing or invalid credentials",
        409: "Email already registered",
        422: "Invalid fields or unexpected properties",
        429: "Login attempt limit exceeded",
        500: "Unexpected server error",
    }.items()
}


@router.post(
    "/register/customer",
    status_code=201,
    response_model=Success[UserResponse],
    responses={key: ERRORS[key] for key in (400, 409, 422, 500)},
    summary="Register a Customer",
    description="Public JSON signup. The server assigns CUSTOMER.",
)
async def register_customer(request: RegisterRequest, session: SessionDep):
    user = await register_user(session, request, Role.CUSTOMER)
    return Success(data=UserResponse.model_validate(user))


@router.post(
    "/register/host",
    status_code=201,
    response_model=Success[UserResponse],
    responses={key: ERRORS[key] for key in (400, 409, 422, 500)},
    summary="Register a Host",
    description="Public JSON signup. The server assigns HOST.",
)
async def register_host(request: RegisterRequest, session: SessionDep):
    user = await register_user(session, request, Role.HOST)
    return Success(data=UserResponse.model_validate(user))


@router.post(
    "/login",
    response_model=Success[LoginResponse],
    dependencies=[Depends(enforce_login_throttle)],
    responses={key: ERRORS[key] for key in (400, 401, 422, 429, 500)},
    summary="Log in using JSON",
    description=(
        "Public JSON login for Customer, Host, and seeded Admin. Returns an expiring bearer token."
    ),
)
async def login(
    request: LoginRequest, session: SessionDep, settings: SettingsDep, response: Response
):
    user = await authenticate_user(session, request)
    token, expires_at = create_access_token(user.id, settings)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return Success(
        data=LoginResponse(
            access_token=token,
            expires_in=settings.jwt_expire_minutes * 60,
            expires_at=expires_at,
            user=UserResponse.model_validate(user),
        )
    )


@router.get(
    "/me",
    response_model=Success[UserResponse],
    responses={401: ERRORS[401], 500: ERRORS[500]},
    summary="Get the current user",
    description="Requires a valid bearer token; supports all roles.",
)
async def me(user: CurrentUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return Success(data=UserResponse.model_validate(user))
