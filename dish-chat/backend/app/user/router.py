from fastapi import APIRouter

from .schemas import User
from app.dependencies import UserEmailDep, DBSessionDep
from .service import get_last_release_date

router = APIRouter()

# whoami
@router.get("/whoami", tags=["user"])
async def get_user(db: DBSessionDep, email: UserEmailDep) -> User:
    '''Simply parse request header and respond user information.'''
    last_release_date = await get_last_release_date(db, user_email=email)
    # Parse email safely - handle both firstname.lastname and single name formats
    username = email.split('@')[0]
    name_parts = username.split('.')
    
    if len(name_parts) >= 2:
        first_name = name_parts[0].capitalize()
        last_name = name_parts[1].capitalize()
    else:
        # Single name or hyphenated name
        first_name = username.capitalize()
        last_name = ""
    
    return User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        last_release_date=last_release_date
    )

