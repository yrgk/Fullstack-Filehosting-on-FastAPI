from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slugify import slugify
from sqlalchemy.orm import Session

from .auth.auth import create_jwt_token, pwd_context, get_current_user
from .database import Base, get_db, engine
from .models import File, Repository, User
from .script import create_url, s3
from .schemas import RepositoryItem


app = FastAPI()


Base.metadata.create_all(engine)

# Loading static files
app.mount('/static', StaticFiles(directory='frontend/static'), name='static')
templates = Jinja2Templates(directory='frontend/templates')



@app.exception_handler(404)
def not_found_exception_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse('404.html', {'request': request})


# Routing
@app.get('/')
def main(request: Request):
    current_user = get_current_user()
    return templates.TemplateResponse('index.html', {'request': request, 'user': current_user})


## Auth endpoints
@app.post("/token")
def authenticate_user(
    request: Request,
    name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    ):
    user = db.query(User).filter(User.name == name and User.password == password).first()
    if not user:
        return templates.TemplateResponse('auth/auth.html',{"error": "Incorrect username or password", "request": request}, status_code=301)

    is_password_correct = pwd_context.verify(password, user.password)

    if not is_password_correct:
        return templates.TemplateResponse('auth/auth.html', {'request': request, 'error': 'Incorrect username or password'})
    jwt_token = create_jwt_token({"sub": user.name,})

    response = RedirectResponse("/repository", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token",value=f"Bearer {jwt_token}", httponly=True)
    return response


@app.get('/login')
def login(request: Request):
    return templates.TemplateResponse('auth/auth.html', {'request': request})


@app.post("/register")
def register_user(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user1 = db.query(User).filter(User.name == name).first()
    user2 = db.query(User).filter(User.email == email).first()
    if user1 or user2:
        return templates.TemplateResponse('auth/register.html',{"error": "There is already an account with the same email or username", "request": request}, status_code=301)
    else:
        hashed_password = pwd_context.hash(password)
        user = User(
            email=email,
            name=name,
            password=hashed_password
        )
        db.add(user)
        db.commit()
        jwt_token = create_jwt_token({"sub": user.name,})

        response = RedirectResponse("/repository", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="access_token",value=f"Bearer {jwt_token}", httponly=True)
        return response


@app.get('/signup')
def sign_up(request: Request):
    return templates.TemplateResponse('auth/register.html', {'request': request, 'user': Depends(get_current_user)})


@app.get('/logout')
def logout():
    response = RedirectResponse(url='/',status_code=302)
    response.set_cookie(key='access_token',value='', httponly=True)
    return response



## CRUD repositories
@app.get('/repository/{link}')
def get_repository(link: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rep = db.query(Repository).filter(Repository.link == link).first()

    if rep:
        if current_user.id == rep.user_id:
            repositories = db.query(Repository).filter(Repository.user_id == current_user.id).all()[::-1]
            files = db.query(File).filter(File.rep_id == rep.id)
            return templates.TemplateResponse('rep.html', {'request': request, 'files': files, 'repositories': repositories, 'repository': rep, 'user': current_user})
        else:
            files = db.query(File).filter(File.rep_id == rep.id)
            return templates.TemplateResponse('view.html', {'request': request, 'repository': rep, 'files': files, 'user': current_user})
    else:
        return templates.TemplateResponse('404.html', {'request': request})


@app.get('/repository')
def repository_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    repositories = db.query(Repository).filter(Repository.user_id == current_user.id).all()[::-1]
    return templates.TemplateResponse('reps.html', {'request': request, 'repositories': repositories, 'user': current_user})


@app.post('/repository/create')
def create_repository(name: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rep_name = f'filehosting-litix-{slugify(name)}'
    s3.create_bucket(Bucket=rep_name)

    rep = Repository(
        view_name=name,
        name=rep_name,
        link=create_url(),
        user_id=current_user.id
    )
    db.add(rep)
    db.commit()
    db.refresh(rep)

    return RedirectResponse('/repository', status_code=status.HTTP_303_SEE_OTHER)


@app.get('/repository/delete/{name}')
def delete_repository(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rep: RepositoryItem = db.query(Repository).filter(Repository.name == name).first()
    files = db.query(File).filter(File.rep_id == rep.id)

    files.delete(synchronize_session=False)
    db.delete(rep)
    db.commit()

    try:
        file_list = s3.list_objects(Bucket=name)["Contents"]
        for file in file_list:
            s3.delete_object(Bucket=name, Key=file["Key"])
        s3.delete_bucket(Bucket=name)
    except:
        s3.delete_bucket(Bucket=name)

    return RedirectResponse('/repository', status_code=status.HTTP_303_SEE_OTHER)



## CRUD files
@app.post('/file/add/{link}')
def add_file(link: str, file: UploadFile = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):

    rep = db.query(Repository).filter(Repository.link == link).first()
    file_name = slugify(file.filename)
    url = f'/file/read?bucket_name={rep.name}&key={file_name}'
    try:
        s3.upload_fileobj(file.file, Bucket=rep.name, Key=file.filename)
        newfile = File(
            view_name=file.filename,
            name=file_name,
            download_link=url,
            rep_id=rep.id
        )
        db.add(newfile)
        db.commit()
    except:
        pass

    return RedirectResponse(f'/repository/{link}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/file/remove')
def remove_file(bucket_name: str, name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    s3.delete_object(Bucket=bucket_name, Key=name)
    file = db.query(File).filter(File.name == name)
    rep = db.query(Repository).filter(Repository.id == file.first().rep_id).first()
    file.delete()
    db.commit()

    return RedirectResponse(f'/repository/{rep.link}', status_code=status.HTTP_303_SEE_OTHER)


@app.get('/file/read')
def download_file(bucket_name: str, key: str, db: Session = Depends(get_db)):
    file_name = db.query(File).filter(File.name == key).first()
    content = s3.get_object(Bucket=bucket_name, Key=file_name.view_name)['Body'].read()
    return Response(
        content=content,
        headers={
            'Content-Disposition': f'attachment;filename={file_name.view_name}',
            'Content-Type': 'application/octet-stream',
            'Access-Control-Expose-Headers': 'Content-Disposition',
        }
    )