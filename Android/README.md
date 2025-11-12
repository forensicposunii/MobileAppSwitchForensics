# 1. 가상환경 생성 및 활성화
python -m venv .venv
.\.venv\Scripts\activate    # Windows

# 2. 필수 라이브러리 설치
pip install -r requirements.txt

# 3. 실행
python usagestats_to_sqlite.py
