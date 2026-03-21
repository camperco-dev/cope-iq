@echo off
call venv\Scripts\activate
uvicorn main:app --port 8000
