# 리뷰 분석 API (C2·C3·S2). 고객응대 서버나 팀 공용 서버 어디서든 같은 방법으로 띄움.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 서버 디스크에 연결할 폴더 (docker run -v): 발표용 저장본, 붙여넣은 리뷰, 사용량 기록
RUN mkdir -p /app/data/replay /app/data/runtime /app/logs

# kiwi 모델을 미리 띄워 첫 요청이 느리지 않게 (실패해도 빌드는 계속, 그때는 글자 단서로 돎)
RUN python -c "from app.morph import get_analyzer; get_analyzer()" || true

EXPOSE 8020
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
