from fastapi import Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext

from ..models import User
from ..database import get_db

from .cookie import OAuth2PasswordBearerWithCookie

SECRET_KEY = "my_secret_key"
ALGORITHM = "HS256"
EXPIRATION_TIME = timedelta(days=14)

oauth2_scheme = OAuth2PasswordBearerWithCookie(tokenUrl="/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_jwt_token(data: dict):
    expiration = datetime.utcnow() + EXPIRATION_TIME
    data.update({"exp": expiration})
    token = jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
    return token


def verify_jwt_token(token: str):
    try:
        decoded_data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded_data
    except jwt.PyJWTError:
        return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    decoded_data = verify_jwt_token(token)
    if not decoded_data:
        return RedirectResponse('/login')
    user = db.query(User).filter(User.name == decoded_data["sub"]).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    return user