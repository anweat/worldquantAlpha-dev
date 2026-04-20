@echo off
echo 🧠 启动 WorldQuant Alpha Studio...
echo 浏览器将自动打开 http://localhost:8501
cd /d "%~dp0"
python -m streamlit run src/ui/app.py --server.port 8501
