from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from student_api import student_history
from fastapi.templating import Jinja2Templates
from datetime import datetime
import locale
import uvicorn
from subprocess import Popen
import json

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates("templates")


with open('students.json', encoding='utf-8') as file:
    STUDENTS = json.load(file)


@app.get("/{student}")
async def history(request: Request, student, query: int = 5):
    if not STUDENTS.get(student.lower()): return PlainTextResponse('ничего не найдено ^_^')
    googlesheet_data = student_history(student)
    number = int(googlesheet_data[1][0][0])
    message = (f'Доступно уроков: {number} \n', f'Неоплаченных уроков: {abs(number)} \n')[number<0]
    n = query

    history = []
    for lesson in googlesheet_data[0]:

        if not query: break
        if not lesson or len(lesson)<2: continue
        if 'Оплата' not in lesson[1]: lesson[1] = 'Урок завершен'
        lesson_date = datetime.strptime(lesson[0], '%d-%b-%y')
        history.append((lesson_date, lesson[1]))
        query -= 1
    

    locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')
    history = list(map(lambda x: f"{x[0].strftime('%a %d-%b-%Y')} {x[1]}", history))
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    return templates.TemplateResponse(
        "student.html",
        context={
            "request": request, 
            "history": history,
            "name": STUDENTS[student.lower()],
            "student_id": student,
            "query": n,
            "is_more": not query,
            "message": message,
            }
        )
    
if __name__ == '__main__':
    Popen(['python', '-m', 'https_redirect'])
    uvicorn.run(
        'app:app', port=443, host='0.0.0.0',
        reload=True, reload_dirs=['html_files'],
        ssl_keyfile='/etc/letsencrypt/live/mydomain.com/privkey.pem',
        ssl_certfile='/etc/letsencrypt/live/mydomain.com/fullchain.pem')