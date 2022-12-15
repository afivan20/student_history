import gspread
import pathlib
import os


SHEET = 'schedule'
DIR = pathlib.Path(__file__).parent.resolve()
CREDENTIALS = 'credentials.json'

def connect_excel(worksheet):
    sa = gspread.service_account(os.path.join(DIR, CREDENTIALS))
    sheet = sa.open(SHEET) 
    worksheet = sheet.worksheet(worksheet)
    return worksheet

def student_history(student: str):
    worksheet = connect_excel(student.capitalize())
    try:
        result = worksheet.batch_get([f"B5:C10000", "E3:E4"])
    except Exception as e:
        print(e)
    return result